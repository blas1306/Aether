//! BORROWED-INVOCABLE-PARAM-V1 M2 MIR/SSA and runtime qualification.

use std::{fs, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{FunctionId, SourceFile, TypeData, analyze, parse_source};
use aether_middle::{
    PlaceBase, Rvalue, SsaOp, SsaPlaceBase, build_ssa, lower_hir, verify_mir, verify_ssa,
};

const SOURCE: &str = r"
int twice<C:Invocable<(int),int>>(ref C f,int x){return f(x)+f(x);}
int inc(int x){return x+1;}
int main(){
  Function<(int),int> f=inc;
  int a=twice(f,20);
  int offset=1;
  var closure=(int x) capture(copy offset)=>x+offset;
  int b=twice(closure,20);
  int still_alive=closure(0);
  int fresh=twice((int x) capture(copy offset)=>x+offset,20);
  return a+b+still_alive+fresh-127;
}
";

fn raw_mir() -> aether_middle::FlowMir {
    let hir = analyze(parse_source(&SourceFile::new("borrowed_invocable_m2.ae", SOURCE)).unwrap())
        .unwrap();
    lower_hir(hir)
}

fn run(source: &str, optimization: OptimizationLevel) -> (i32, String) {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let compilation = compile_source_with_optimization(
        &SourceFile::new("borrowed_invocable_m2.ae", source),
        &[Emit::Llvm],
        optimization,
    )
    .unwrap();
    let executable = std::env::temp_dir().join(format!(
        "aether-borrowed-invocable-m2-{}-{}-{optimization:?}",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    let status = Command::new(&executable)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1);
    let _ = fs::remove_file(executable);
    (status, compilation.llvm)
}

#[test]
fn borrowed_closure_uses_dereferenced_parameter_place_through_mir_and_ssa() {
    let mir = verify_mir(raw_mir()).unwrap();
    let closure_instance = mir
        .as_mir()
        .functions
        .iter()
        .find(|function| {
            function.function_id == FunctionId(0)
                && function.parameters.first().is_some_and(|parameter| {
                    mir.as_mir().types.reference_info(parameter.ty).is_some_and(
                        |(pointee, mutable)| {
                            !mutable
                                && matches!(
                                    mir.as_mir().types.get(pointee),
                                    Some(TypeData::Closure { .. })
                                )
                        },
                    )
                })
        })
        .unwrap();
    let parameter = closure_instance.parameters[0].local;
    let operations = closure_instance
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .collect::<Vec<_>>();
    assert_eq!(
        operations
            .iter()
            .filter(|instruction| matches!(instruction.value, Rvalue::ClosureBorrow { .. }))
            .count(),
        2
    );
    assert!(
        operations
            .iter()
            .all(|instruction| match &instruction.value {
                Rvalue::ClosureBorrow { carrier, .. }
                | Rvalue::ClosureCall { carrier, .. }
                | Rvalue::EndClosureBorrow { carrier, .. } => matches!(
                    carrier.base,
                    PlaceBase::Dereference {
                        reference: aether_middle::Operand::Local(local),
                        mutable: false
                    } if local == parameter
                ),
                Rvalue::ClosureAlias { .. } => false,
                _ => true,
            })
    );

    let ssa = verify_ssa(build_ssa(&mir)).unwrap();
    let closure_ssa = &ssa.as_ssa().functions[closure_instance.id.0 as usize];
    let parameter = closure_ssa.parameters[0].value;
    assert!(
        closure_ssa
            .blocks
            .iter()
            .flat_map(|block| &block.instructions)
            .all(|instruction| match &instruction.op {
                SsaOp::ClosureBorrow { carrier, .. }
                | SsaOp::ClosureCall { carrier, .. }
                | SsaOp::EndClosureBorrow { carrier, .. } => matches!(
                    carrier.base,
                    SsaPlaceBase::Dereference {
                        reference: aether_middle::SsaOperand::Value(value),
                        mutable: false
                    } if value == parameter
                ),
                SsaOp::ClosureAlias { .. } => false,
                _ => true,
            })
    );
}

#[test]
fn borrowed_closure_provenance_corruptions_fail_closed_in_mir_and_ssa() {
    let mut bad_mir = raw_mir();
    let carrier = bad_mir
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::ClosureBorrow { carrier, .. }
                if matches!(carrier.base, PlaceBase::Dereference { .. }) =>
            {
                Some(carrier)
            }
            _ => None,
        })
        .unwrap();
    let PlaceBase::Dereference { mutable, .. } = &mut carrier.base else {
        unreachable!()
    };
    *mutable = true;
    assert!(verify_mir(bad_mir).is_err());

    let mir = verify_mir(raw_mir()).unwrap();
    let mut bad_ssa = build_ssa(&mir);
    let carrier = bad_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::ClosureBorrow { carrier, .. }
                if matches!(carrier.base, SsaPlaceBase::Dereference { .. }) =>
            {
                Some(carrier)
            }
            _ => None,
        })
        .unwrap();
    let SsaPlaceBase::Dereference { mutable, .. } = &mut carrier.base else {
        unreachable!()
    };
    *mutable = true;
    assert!(verify_ssa(bad_ssa).is_err());
}

#[test]
fn borrowed_function_closure_lvalue_and_fresh_execute_at_o0_and_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (status, llvm) = run(SOURCE, optimization);
        assert_eq!(status, 0, "borrowed invocation failed at {optimization:?}");
        assert!(!llvm.contains("BorrowedCapabilityInvoke"));
        assert!(!llvm.contains("CapabilityInvoke"));
        assert!(!llvm.contains("invocable_adapter"));
    }
}

#[test]
fn borrowed_invocation_unwind_catch_rethrow_and_finally_execute_at_o0_and_o2() {
    let cases = [
        r"open class Problem:Exception{public init(){}}
int fail(int x){throw Problem();}
int apply<C:Invocable<(int),int>>(ref C f,int x){return f(x);}
int main(){int state=0;Function<(int),int> f=fail;try{apply(f,1);}catch(Problem p){state=state+1;}finally{state=state+2;}return state-3;}",
        r"open class Problem:Exception{public init(){}}
int failArgument(){throw Problem();}
int apply<C:Invocable<(int),int>>(ref C f){return f(failArgument());}
int main(){int state=0;int n=1;var f=(int x) capture(copy n)=>x+n;try{apply(f);}catch(Problem p){state=1;}return state-1;}",
        r"open class Problem:Exception{public init(){}}
int maybe(int x){if(x==0){throw Problem();}return x;}
int recover<C:Invocable<(int),int>>(ref C f){try{return f(0);}catch(Problem p){return f(1);}}
int main(){Function<(int),int> f=maybe;return recover(f)-1;}",
        r"open class Problem:Exception{public init(){}}
int fail(int x){throw Problem();}
int apply<C:Invocable<(int),int>>(ref C f,int x){return f(x);}
int main(){int state=0;int n=1;var f=(int x) capture(copy n)=>fail(x);try{try{apply(f,1);}catch(Problem p){throw;}finally{state=state+1;}}catch(Exception p){state=state+2;}return state-3;}",
    ];
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        for source in cases {
            assert_eq!(run(source, optimization).0, 0, "failed at {optimization:?}");
        }
    }
}
