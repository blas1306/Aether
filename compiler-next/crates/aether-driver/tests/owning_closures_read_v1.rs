//! OWNING-CLOSURES-READ-V1 foundation and fail-closed qualification.

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{
    AstCaptureMode, AstExprKind, AstStmtKind, AstTypeKind, CaptureMode, SourceFile,
    TargetProperties, TypeArena, TypeData, TypeId, analyze_bodies, collect_signatures, layout_of,
    lex, parse,
};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

fn declared(source: &str) -> aether_frontend::DeclaredProgram {
    let source = SourceFile::new("capture_analysis.ae", source);
    collect_signatures(parse(&source, lex(&source).unwrap()).unwrap()).unwrap()
}

#[test]
fn closure_type_is_distinct_owning_one_pointer_carrier() {
    let mut types = TypeArena::new();
    let closure = types
        .intern_closure(vec![TypeId::FLOAT64], TypeId::FLOAT64)
        .unwrap();
    let function = types
        .intern_function(vec![TypeId::FLOAT64], TypeId::FLOAT64)
        .unwrap();

    assert_ne!(closure, function);
    assert!(matches!(types.get(closure), Some(TypeData::Closure { .. })));
    let properties = types.properties(closure).unwrap();
    assert!(properties.is_known && properties.is_relocatable && properties.is_storable);
    assert!(!properties.is_copy && properties.needs_drop);
    assert_eq!(
        layout_of(&types, closure, TargetProperties::LINUX_X86_64, &[], &[])
            .map(|layout| (layout.size, layout.align)),
        Some((8, 8))
    );
}

#[test]
fn closure_type_and_partial_capture_clause_parse_without_function_coercion() {
    let source = SourceFile::new(
        "owning_closures_read_v1.ae",
        r#"
Closure<(double),double> accept(Closure<(double),double> f){return f;}
int main(){
  double a=2.0;
  string label="x";
  var f=(double x) capture(copy a, alias label)=>a*x;
  return 0;
}"#,
    );
    let ast = parse(&source, lex(&source).unwrap()).unwrap();
    assert!(matches!(
        ast.functions()[0].return_type.kind,
        AstTypeKind::Closure { .. }
    ));
    let main = ast
        .functions()
        .iter()
        .find(|function| function.name == "main")
        .unwrap();
    let lambda = main
        .body
        .statements
        .iter()
        .find_map(|statement| match &statement.kind {
            AstStmtKind::Local { initializer, .. } => match &initializer.kind {
                AstExprKind::Lambda { captures, .. } => Some(captures),
                _ => None,
            },
            _ => None,
        })
        .unwrap();
    assert_eq!(lambda.len(), 2);
    assert_eq!(lambda[0].mode, AstCaptureMode::Copy);
    assert_eq!(lambda[0].name, "a");
    assert_eq!(lambda[1].mode, AstCaptureMode::Alias);
    assert_eq!(lambda[1].name, "label");
}

#[test]
fn malformed_capture_modes_and_trailing_entries_fail_closed() {
    for (source, expected) in [
        (
            "int main(){var f=() capture()=>0;}",
            "capture clause cannot be empty",
        ),
        (
            "int main(){int a=1;var f=() capture(clone a)=>a;}",
            "capture mode must",
        ),
        (
            "int main(){int a=1;var f=() capture(copy a,)=>a;}",
            "expected capture after",
        ),
        (
            "int main(){int a=1;var f=() capture(copy a, copy a)=>a;}",
            "duplicate explicit capture",
        ),
    ] {
        let source = SourceFile::new("bad_closure.ae", source);
        let diagnostics = parse(&source, lex(&source).unwrap()).unwrap_err();
        assert!(
            diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E0368"
                    && diagnostic.message.contains(expected))
        );
    }
}

#[test]
fn versioned_arc_helpers_use_the_v1_header_destroy_offset() {
    let source = SourceFile::new(
        "closure_abi_v1.ae",
        "void sink(Closure<(double),double> f){} int main(){return 0;}",
    );
    let compilation =
        compile_source_with_optimization(&source, &[Emit::Llvm], OptimizationLevel::O0).unwrap();
    assert!(
        compilation
            .llvm
            .contains("define ptr @aether_closure_retain_v1")
    );
    assert!(
        compilation
            .llvm
            .contains("define void @aether_closure_release_v1")
    );
    assert!(
        compilation
            .llvm
            .contains("getelementptr i8, ptr %box, i64 16")
    );
    assert!(
        compilation
            .llvm
            .contains("call void %destroy_thunk(ptr %box)")
    );
}

#[test]
fn automatic_copy_and_alias_captures_have_typed_binding_metadata() {
    let declarations = declared(
        r"int host(string label){double scale=2.0;var f=(double x)=>x*scale+length(label);return 0;}int main(){return 0;}",
    );
    let environments = declarations.closure_environments();
    assert_eq!(environments.len(), 1);
    let captures = &environments[0].captures;
    assert_eq!(captures.len(), 2);
    assert_eq!(
        (captures[0].name.as_str(), captures[0].mode),
        ("scale", CaptureMode::Copy)
    );
    assert_eq!(
        (captures[1].name.as_str(), captures[1].mode),
        ("label", CaptureMode::Alias)
    );
    assert_ne!(captures[0].binding, captures[1].binding);
    assert!(
        captures
            .iter()
            .all(|capture| capture.first_use_span.is_some())
    );
    assert!(matches!(
        declarations.types().get(environments[0].signature),
        Some(TypeData::Closure { .. })
    ));
}

#[test]
fn explicit_copy_and_alias_modes_override_their_exact_bindings() {
    let declarations = declared(
        r"int host(string label){double scale=2.0;var f=(double x) capture(copy scale, alias label)=>x*scale+length(label);return 0;}int main(){return 0;}",
    );
    let captures = &declarations.closure_environments()[0].captures;
    assert_eq!(captures.len(), 2);
    assert!(captures.iter().all(|capture| capture.explicit));
    assert_eq!(captures[0].mode, CaptureMode::Copy);
    assert_eq!(captures[1].mode, CaptureMode::Alias);
    assert!(declarations.closure_warnings().is_empty());
}

#[test]
fn partial_clause_keeps_explicit_unused_move_and_orders_implicit_after_it() {
    let declarations = declared(
        r"int host(Matrix<double> data){double scale=2.0;var f=(double x) capture(move data)=>x*scale;return 0;}int main(){return 0;}",
    );
    let captures = &declarations.closure_environments()[0].captures;
    assert_eq!(captures.len(), 2);
    assert_eq!(
        (
            captures[0].name.as_str(),
            captures[0].mode,
            captures[0].explicit
        ),
        ("data", CaptureMode::Move, true)
    );
    assert!(captures[0].first_use_span.is_none());
    assert_eq!(
        (
            captures[1].name.as_str(),
            captures[1].mode,
            captures[1].explicit
        ),
        ("scale", CaptureMode::Copy, false)
    );
    assert_eq!(
        (captures[0].canonical_index, captures[1].canonical_index),
        (0, 1)
    );
    assert_eq!(declarations.closure_warnings().len(), 1);
    let warning = &declarations.closure_warnings()[0];
    assert_eq!(warning.code, "W0369");
    assert_eq!(warning.capture_span, captures[0].explicit_span.unwrap());
    assert_eq!(warning.declaration_span, captures[0].declaration_span);
}

#[test]
fn lexical_shadowing_and_invalid_explicit_capture_fail_source_spanned() {
    let source = SourceFile::new(
        "shadowed_capture.ae",
        "int host(){int x=1;var f=(int x) capture(copy x)=>x;return 0;}int main(){return 0;}",
    );
    let diagnostics =
        collect_signatures(parse(&source, lex(&source).unwrap()).unwrap()).unwrap_err();
    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E0369"
                && diagnostic.message.contains("shadowed")
                && diagnostic.span.is_some())
    );
}

#[test]
fn equal_spellings_in_distinct_scopes_keep_distinct_binding_ids() {
    let declarations = declared(
        "int host(){int x=1;if(true){int x=2;var a=()=>x;}if(true){var b=()=>x;}return 0;}int main(){return 0;}",
    );
    let bindings = declarations
        .closure_environments()
        .iter()
        .map(|environment| environment.captures[0].binding)
        .collect::<Vec<_>>();
    assert_eq!(bindings.len(), 2);
    assert_ne!(bindings[0], bindings[1]);
}

#[test]
fn nonexistent_and_mutably_borrowed_explicit_captures_are_rejected() {
    for (source, expected) in [
        (
            "int host(){var f=() capture(copy missing)=>0;return 0;}int main(){return 0;}",
            "does not name an outer binding",
        ),
        (
            "int host(){int x=1;var f=()=>&mut x;return 0;}int main(){return 0;}",
            "mutable access",
        ),
    ] {
        let source = SourceFile::new("invalid_explicit_capture.ae", source);
        let diagnostics =
            collect_signatures(parse(&source, lex(&source).unwrap()).unwrap()).unwrap_err();
        assert!(
            diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E0369"
                    && diagnostic.message.contains(expected))
        );
    }
}

#[test]
fn reference_and_implicit_move_only_capture_are_rejected() {
    for (source, expected) in [
        (
            "int host(ref int x){var f=()=>x;return 0;}int main(){return 0;}",
            "non-Storable",
        ),
        (
            "int host(Matrix<double> data){var f=()=>rows(data);return 0;}int main(){return 0;}",
            "capture(move data)",
        ),
    ] {
        let source = SourceFile::new("invalid_capture.ae", source);
        let diagnostics =
            collect_signatures(parse(&source, lex(&source).unwrap()).unwrap()).unwrap_err();
        assert!(
            diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E0369"
                    && diagnostic.message.contains(expected))
        );
    }
}

#[test]
fn nested_lambda_propagates_transitive_capture_by_binding_identity() {
    let declarations = declared(
        "int host(){int offset=1;var outer=(int x)=>(int y)=>x+y+offset;return 0;}int main(){return 0;}",
    );
    assert_eq!(declarations.closure_environments().len(), 2);
    let offset = declarations
        .closure_environments()
        .iter()
        .flat_map(|environment| &environment.captures)
        .filter(|capture| capture.name == "offset")
        .map(|capture| capture.binding)
        .collect::<Vec<_>>();
    assert_eq!(offset.len(), 2);
    assert_eq!(offset[0], offset[1]);
}

#[test]
fn productive_boundary_is_explicit_after_capture_analysis() {
    let source = SourceFile::new(
        "capture_boundary.ae",
        "int main(){int offset=1;var f=(int x)=>x+offset;return 0;}",
    );
    let diagnostics =
        compile_source_with_optimization(&source, &[Emit::Hir], OptimizationLevel::O0).unwrap_err();
    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E0376")
    );
    assert!(
        !diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E0359")
    );
}

#[test]
fn closure_ownership_operations_reach_verified_hir_mir_and_ssa() {
    let hir = analyze_bodies(declared(
        "int main(){int offset=1;var f=(int x)=>x+offset;int y=f(2);return y;}",
    ))
    .unwrap();
    let hir_dump = hir.dump();
    assert!(hir_dump.contains("ClosureCreate"));
    assert!(hir_dump.contains("ClosureCall"));

    let mir = verify_mir(lower_hir(hir)).unwrap();
    let mir_dump = mir.dump();
    assert!(mir_dump.contains("ClosureCreate"));
    assert!(mir_dump.contains("ClosureBorrow"));
    assert!(mir_dump.contains("ClosureCall"));
    assert!(mir_dump.contains("EndClosureBorrow"));

    let ssa = verify_ssa(build_ssa(&mir)).unwrap();
    let ssa_dump = ssa.dump();
    assert!(ssa_dump.contains("ClosureCreate"));
    assert!(ssa_dump.contains("ClosureBorrow"));
    assert!(ssa_dump.contains("ClosureCall"));
    assert!(ssa_dump.contains("EndClosureBorrow"));
}

fn closure_mir() -> aether_middle::FlowMir {
    lower_hir(
        analyze_bodies(declared(
            "int main(){int a=1;int b=2;var f=(int x)=>x+a+b;int y=f(3);return y;}",
        ))
        .unwrap(),
    )
}

#[test]
fn closure_mir_corruptions_are_rejected_without_hir_authority() {
    let mir = closure_mir();
    verify_mir(mir.clone()).unwrap();
    for mutation in 0..7 {
        let mut bad = mir.clone();
        let create = bad
            .functions
            .iter_mut()
            .flat_map(|function| &mut function.blocks)
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.value, Rvalue::ClosureCreate { .. }))
            .unwrap();
        let Rvalue::ClosureCreate {
            recipe, captures, ..
        } = &mut create.value
        else {
            unreachable!()
        };
        match mutation {
            0 => {
                captures.pop();
            }
            1 => captures.swap(0, 1),
            2 => captures[0].mode = CaptureMode::Alias,
            3 => captures[0].binding = captures[1].binding,
            4 => captures[0].capture_type = TypeId::STRING,
            5 => captures[0].initialized_after = 9,
            6 => recipe.destroy_nounwind = false,
            _ => unreachable!(),
        }
        assert!(verify_mir(bad).is_err(), "mutation {mutation}");
    }

    let mut missing_end = mir;
    for block in missing_end
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
    {
        block
            .instructions
            .retain(|instruction| !matches!(instruction.value, Rvalue::EndClosureBorrow { .. }));
    }
    assert!(verify_mir(missing_end).is_err());

    let mut missing_drop = closure_mir();
    for block in missing_drop
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
    {
        block
            .instructions
            .retain(|instruction| !matches!(instruction.value, Rvalue::Drop { .. }));
    }
    assert!(verify_mir(missing_drop).is_err());

    let mut double_drop = closure_mir();
    let block = double_drop
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .find(|block| {
            block
                .instructions
                .iter()
                .any(|instruction| matches!(instruction.value, Rvalue::Drop { .. }))
        })
        .unwrap();
    let drop = block
        .instructions
        .iter()
        .find(|instruction| matches!(instruction.value, Rvalue::Drop { .. }))
        .unwrap()
        .clone();
    block.instructions.push(drop);
    assert!(verify_mir(double_drop).is_err());
}

#[test]
fn closure_ssa_corruptions_are_rejected_without_mir_authority() {
    let verified = verify_mir(closure_mir()).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();
    for mutation in 0..7 {
        let mut bad = ssa.clone();
        let create = bad
            .functions
            .iter_mut()
            .flat_map(|function| &mut function.blocks)
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.op, SsaOp::ClosureCreate { .. }))
            .unwrap();
        let SsaOp::ClosureCreate {
            recipe, captures, ..
        } = &mut create.op
        else {
            unreachable!()
        };
        match mutation {
            0 => {
                captures.pop();
            }
            1 => captures.swap(0, 1),
            2 => captures[0].mode = CaptureMode::Alias,
            3 => captures[0].binding = captures[1].binding,
            4 => captures[0].source_type = TypeId::STRING,
            5 => captures[0].initialized_before = 8,
            6 => recipe.destroy_nounwind = false,
            _ => unreachable!(),
        }
        assert!(verify_ssa(bad).is_err(), "mutation {mutation}");
    }

    let mut missing_end = ssa;
    for block in missing_end
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
    {
        block
            .instructions
            .retain(|instruction| !matches!(instruction.op, SsaOp::EndClosureBorrow { .. }));
    }
    assert!(verify_ssa(missing_end).is_err());

    let verified = verify_mir(closure_mir()).unwrap();
    let mut missing_drop = build_ssa(&verified);
    for block in missing_drop
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
    {
        block
            .instructions
            .retain(|instruction| !matches!(instruction.op, SsaOp::Drop { .. }));
    }
    assert!(verify_ssa(missing_drop).is_err());
}

#[test]
fn copy_alias_and_move_capture_acquisitions_survive_verified_ssa() {
    let hir = analyze_bodies(declared(
        r#"int main(){
  int a=1;
  string label="x";
  Matrix<int> data=[1];
  var f=(int x) capture(copy a, alias label, move data)=>x+a;
  return 0;
}"#,
    ))
    .unwrap();
    let mir = verify_mir(lower_hir(hir)).unwrap();
    let ssa = verify_ssa(build_ssa(&mir)).unwrap();
    let modes = ssa
        .as_ssa()
        .functions
        .iter()
        .flat_map(|function| &function.blocks)
        .flat_map(|block| &block.instructions)
        .find_map(|instruction| match &instruction.op {
            SsaOp::ClosureCreate { captures, .. } => Some(
                captures
                    .iter()
                    .map(|capture| capture.mode)
                    .collect::<Vec<_>>(),
            ),
            _ => None,
        })
        .unwrap();
    assert_eq!(
        modes,
        vec![CaptureMode::Copy, CaptureMode::Alias, CaptureMode::Move]
    );
}

#[test]
fn closure_return_argument_alias_and_self_replacement_verify() {
    let hir = analyze_bodies(declared(
        r"
Closure<(int),int> make(){int offset=4;return (int x)=>x+offset;}
int apply(Closure<(int),int> g){return g(2);}
int main(){var f=make();f=f;return apply(f);}
",
    ))
    .unwrap();
    let mir = verify_mir(lower_hir(hir)).unwrap();
    let dump = mir.dump();
    assert!(dump.contains("ClosureAlias"));
    assert!(dump.contains("Drop"));
    let ssa = verify_ssa(build_ssa(&mir)).unwrap();
    assert!(ssa.dump().contains("ClosureCall"));
}

#[test]
fn closure_invocation_unwind_closes_borrow_and_preserves_event_pad() {
    let hir = analyze_bodies(declared(
        r"
open class Problem:Exception{public init(){}}
int fail(){throw Problem();}
int main(){int offset=1;var f=()=>fail()+offset;try{return f();}catch(Problem p){return 42;}}
",
    ))
    .unwrap();
    let mir = verify_mir(lower_hir(hir)).unwrap();
    let function = mir
        .as_mir()
        .functions
        .iter()
        .find(|function| {
            function.blocks.iter().any(|block| {
                block
                    .instructions
                    .iter()
                    .any(|instruction| matches!(instruction.value, Rvalue::ClosureCall { .. }))
            })
        })
        .unwrap();
    let unwind = function
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .find_map(|instruction| {
            matches!(instruction.value, Rvalue::ClosureCall { .. })
                .then_some(instruction.unwind)
                .flatten()
        })
        .expect("ClosureCall conservatively unwinds");
    let pad = &function.blocks[unwind.0 as usize];
    assert!(pad.landing_pad.is_some());
    assert!(
        pad.instructions
            .iter()
            .any(|instruction| matches!(instruction.value, Rvalue::EndClosureBorrow { .. }))
    );
    assert!(
        function
            .blocks
            .iter()
            .flat_map(|block| &block.instructions)
            .filter(|instruction| matches!(instruction.value, Rvalue::EndClosureBorrow { .. }))
            .count()
            >= 2
    );

    let ssa = verify_ssa(build_ssa(&mir)).unwrap();
    assert!(
        ssa.as_ssa()
            .functions
            .iter()
            .flat_map(|function| &function.blocks)
            .filter(|block| block.landing_pad.is_some())
            .any(|block| block
                .instructions
                .iter()
                .any(|instruction| matches!(instruction.op, SsaOp::EndClosureBorrow { .. })))
    );
}

#[test]
fn nested_closure_transitive_bindings_verify_deterministically() {
    let source = "int main(){int offset=1;var outer=(int x)=>(int y)=>x+y+offset;return 0;}";
    let first = analyze_bodies(declared(source)).unwrap();
    let second = analyze_bodies(declared(source)).unwrap();
    assert_eq!(first.closure_environments(), second.closure_environments());
    let mir = verify_mir(lower_hir(first)).unwrap();
    assert_eq!(mir.as_mir().closure_environments.len(), 2);
    let ssa = verify_ssa(build_ssa(&mir)).unwrap();
    assert_eq!(ssa.as_ssa().closure_environments.len(), 2);
}

#[test]
fn move_capture_invalidates_source_before_later_hir_use() {
    let diagnostics = analyze_bodies(declared(
        "int main(){Matrix<int> data=[1];var f=() capture(move data)=>0;int value=data[1,1];return value;}",
    ))
    .unwrap_err();
    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E0291")
    );
}
