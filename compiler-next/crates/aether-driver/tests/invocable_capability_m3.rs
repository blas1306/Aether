//! INVOCABLE-CAPABILITY-V1 M3 concrete specialization qualification.

use std::{fs, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{
    FunctionId, HirExprKind, HirStmtKind, SourceFile, TypeData, analyze, parse_source, verify_hir,
};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

const SPECIALIZATION_SOURCE: &str = r"
int apply<C:Invocable<(int),int>>(C f,int x){return f(x);}
int twice<C:Invocable<(int),int>>(C f,int x){return f(x)+f(x);}
int inc(int x){return x+1;}
int main(){
  Function<(int),int> f=inc;
  int from_function=apply(f,19);
  int offset=1;
  var closure=(int x) capture(copy offset)=>x+offset;
  return from_function+apply(closure,10)+twice(closure,10);
}
";

fn hir(source: &str) -> aether_frontend::TypedHir {
    analyze(parse_source(&SourceFile::new("invocable_m3.ae", source)).unwrap()).unwrap()
}

#[test]
fn capability_invoke_specializes_to_existing_function_and_closure_spines() {
    let hir = hir(SPECIALIZATION_SOURCE);
    verify_hir(&hir).unwrap();

    let apply = hir
        .functions()
        .iter()
        .find(|function| function.function_id == FunctionId(0))
        .unwrap();
    let HirStmtKind::Return { value, drops } = &apply.body.statements[0].kind else {
        panic!("expected apply return")
    };
    assert!(matches!(value.kind, HirExprKind::IndirectCall { .. }));
    assert_eq!(
        drops.as_slice(),
        [],
        "Function specialization must not invent Drop"
    );
    assert_eq!(
        hir.functions()
            .iter()
            .filter(|function| function.function_id == FunctionId(0))
            .count(),
        2,
        "the same declaration must have distinct Function and Closure instances"
    );

    let twice = hir
        .functions()
        .iter()
        .find(|function| function.function_id == FunctionId(1))
        .unwrap();
    assert!(matches!(
        hir.types().get(twice.parameters[0].ty),
        Some(TypeData::Closure { .. })
    ));
    let HirStmtKind::Return { value, drops } = &twice.body.statements[0].kind else {
        panic!("expected twice return")
    };
    let HirExprKind::Binary { left, right, .. } = &value.kind else {
        panic!("expected repeated invocation")
    };
    let (
        HirExprKind::ClosureCall {
            call_site: left_site,
            ..
        },
        HirExprKind::ClosureCall {
            call_site: right_site,
            ..
        },
    ) = (&left.kind, &right.kind)
    else {
        panic!("expected two specialized ClosureCall operations")
    };
    assert_ne!(left_site, right_site);
    assert_eq!(drops.len(), 1, "live Closure parameter needs one cleanup");

    let twice_id = twice.id;
    let mir = verify_mir(lower_hir(hir)).unwrap();
    let closure_function = &mir.as_mir().functions[twice_id.0 as usize];
    let closure_borrows = closure_function
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .filter(|instruction| matches!(instruction.value, Rvalue::ClosureBorrow { .. }))
        .count();
    let closure_calls = closure_function
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .filter(|instruction| matches!(instruction.value, Rvalue::ClosureCall { .. }))
        .count();
    let closure_ends = closure_function
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .filter(|instruction| matches!(instruction.value, Rvalue::EndClosureBorrow { .. }))
        .count();
    assert_eq!((closure_borrows, closure_calls), (2, 2));
    assert!(closure_ends >= 2);
    assert!(!closure_function.blocks.iter().any(|block| {
        block.instructions.iter().any(|instruction| {
            matches!(
                instruction.value,
                Rvalue::ClosureCreate { .. } | Rvalue::ClosureAlias { .. }
            )
        })
    }));

    let ssa = verify_ssa(build_ssa(&mir)).unwrap();
    let closure_ssa = &ssa.as_ssa().functions[twice_id.0 as usize];
    assert_eq!(
        closure_ssa
            .blocks
            .iter()
            .flat_map(|block| &block.instructions)
            .filter(|instruction| matches!(instruction.op, SsaOp::ClosureCall { .. }))
            .count(),
        2
    );
}

#[test]
fn concrete_owner_obligations_resolve_for_ignored_and_transferred_carriers() {
    let hir = hir(
        "void ignore<C:Invocable<(int),int>>(C f){return;} C relay<C:Invocable<(int),int>>(C f){return f;} int inc(int x){return x+1;} int main(){Function<(int),int> f=inc;ignore(f);Function<(int),int> g=relay(f);int offset=1;var c=(int x) capture(copy offset)=>x+offset;ignore(c);var d=relay(c);return g(0)+d(0);}",
    );
    verify_hir(&hir).unwrap();
    for function in hir.functions() {
        if function.function_id == FunctionId(0) {
            let HirStmtKind::Return { drops, .. } = &function.body.statements[0].kind else {
                panic!("expected ignore return")
            };
            if matches!(
                hir.types().get(function.parameters[0].ty),
                Some(TypeData::Function { .. })
            ) {
                assert_eq!(drops.as_slice(), []);
            } else {
                assert_eq!(drops.len(), 1);
            }
        }
        if function.function_id == FunctionId(1) {
            let HirStmtKind::Return { value, drops } = &function.body.statements[0].kind else {
                panic!("expected relay return")
            };
            if matches!(
                hir.types().get(function.parameters[0].ty),
                Some(TypeData::Closure { .. })
            ) {
                assert!(matches!(value.kind, HirExprKind::Move(_)));
            }
            assert_eq!(drops.as_slice(), []);
        }
    }
}

#[test]
fn specialized_function_and_closure_execute_at_o0_and_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_source_with_optimization(
            &SourceFile::new("invocable_m3_runtime.ae", SPECIALIZATION_SOURCE),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        assert!(!compilation.llvm.contains("CapabilityInvoke"));
        let executable = std::env::temp_dir().join(format!(
            "aether-invocable-m3-{}-{optimization:?}",
            std::process::id()
        ));
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &executable)
            .unwrap();
        let status = Command::new(&executable).status().unwrap();
        let _ = fs::remove_file(executable);
        assert_eq!(status.code(), Some(53));
    }
}

#[test]
fn noncapturing_and_copy_alias_move_carriers_execute_through_specialization() {
    let source = r#"
R apply<P,R,C:Invocable<(P),R>>(C f,P x){return f(x);}
int inc(int x){return x+1;}
int main(){
  Function<(int),int> top=inc;
  var plain=(int x)=>x+1;
  int offset=1;
  var copied=(int x) capture(copy offset)=>x+offset;
  string label="abcd";
  var aliased=(int x) capture(alias label)=>x+4;
  Matrix<int> data=[1];
  var moved=(int x) capture(move data)=>x+data[1,1];
  return apply(top,1)+apply(plain,2)+apply(copied,3)+apply(aliased,4)+apply(moved,5);
}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_source_with_optimization(
            &SourceFile::new("invocable_m3_carriers.ae", source),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        let executable = std::env::temp_dir().join(format!(
            "aether-invocable-m3-carriers-{}-{optimization:?}",
            std::process::id()
        ));
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &executable)
            .unwrap();
        let status = Command::new(&executable).status().unwrap();
        let _ = fs::remove_file(executable);
        assert_eq!(status.code(), Some(23));
    }
}

#[test]
fn specialized_closure_unwind_closes_borrow_and_preserves_the_active_exception() {
    let source = r"
open class Problem:Exception{public init(){}}
int fail(){throw Problem();}
int invoke<C:Invocable<(),int>>(C f){return f();}
int main(){
  int offset=1;
  var closure=() capture(copy offset)=>fail()+offset;
  try{return invoke(closure);}catch(Problem problem){return 42;}
}
";
    let hir = hir(source);
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
    let call = function
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .find(|instruction| matches!(instruction.value, Rvalue::ClosureCall { .. }))
        .unwrap();
    let unwind = call
        .unwind
        .expect("specialized invocation remains may-unwind");
    let pad = &function.blocks[unwind.0 as usize];
    assert!(pad.landing_pad.is_some());
    assert!(matches!(
        pad.instructions
            .first()
            .map(|instruction| &instruction.value),
        Some(Rvalue::EndClosureBorrow { .. })
    ));
    verify_ssa(build_ssa(&mir)).unwrap();

    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_source_with_optimization(
            &SourceFile::new("invocable_m3_unwind.ae", source),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        let executable = std::env::temp_dir().join(format!(
            "aether-invocable-m3-unwind-{}-{optimization:?}",
            std::process::id()
        ));
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &executable)
            .unwrap();
        let status = Command::new(&executable).status().unwrap();
        let _ = fs::remove_file(executable);
        assert_eq!(status.code(), Some(42));
    }
}
