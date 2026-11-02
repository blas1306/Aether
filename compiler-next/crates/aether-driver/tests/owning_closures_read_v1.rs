//! OWNING-CLOSURES-READ-V1 foundation and fail-closed qualification.

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{
    AstCaptureMode, AstExprKind, AstStmtKind, AstTypeKind, CaptureMode, SourceFile,
    TargetProperties, TypeArena, TypeData, TypeId, collect_signatures, layout_of, lex, parse,
};

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
