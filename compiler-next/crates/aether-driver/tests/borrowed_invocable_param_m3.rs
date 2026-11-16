//! BORROWED-INVOCABLE-PARAM-V1 M3 final end-to-end qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session_with_optimization,
    compile_source_with_optimization,
};
use aether_frontend::{FunctionId, SourceFile, TypeData, analyze, parse_source, verify_hir};
use aether_middle::{
    PlaceBase, Rvalue, SsaOp, SsaPlaceBase, build_ssa, lower_hir, verify_mir, verify_ssa,
};

fn compile(source: &str, optimization: OptimizationLevel) -> String {
    compile_source_with_optimization(
        &SourceFile::new("borrowed_invocable_m3.ae", source),
        &[Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{diagnostics:#?}"))
    .llvm
}

fn execute(llvm: &str, label: &str, optimization: OptimizationLevel) -> i32 {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let executable = std::env::temp_dir().join(format!(
        "aether-borrowed-invocable-m3-{label}-{}-{}-{optimization:?}",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &executable)
        .unwrap_or_else(|diagnostics| panic!("{diagnostics:#?}\n{llvm}"));
    let status = Command::new(&executable)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1);
    let _ = fs::remove_file(executable);
    status
}

fn run(source: &str, label: &str, optimization: OptimizationLevel) -> (i32, String) {
    let llvm = compile(source, optimization);
    let status = execute(&llvm, label, optimization);
    (status, llvm)
}

fn instrument_closure_counts(
    llvm: &str,
    expected_retain: u64,
    expected_release: u64,
    expected_destroy: u64,
    expected_alloc: u64,
    expected_free: u64,
) -> String {
    let checks = format!(
        r"  %m3_retains = load i64, ptr @aether_closure_retain_count
  %m3_releases = load i64, ptr @aether_closure_release_count
  %m3_destroys = load i64, ptr @aether_closure_destroy_count
  %m3_allocs = load i64, ptr @aether_heap_alloc_count
  %m3_frees = load i64, ptr @aether_heap_free_count
  %m3_retain_ok = icmp eq i64 %m3_retains, {expected_retain}
  %m3_release_ok = icmp eq i64 %m3_releases, {expected_release}
  %m3_destroy_ok = icmp eq i64 %m3_destroys, {expected_destroy}
  %m3_alloc_ok = icmp eq i64 %m3_allocs, {expected_alloc}
  %m3_free_ok = icmp eq i64 %m3_frees, {expected_free}
  %m3_arc0 = and i1 %m3_retain_ok, %m3_release_ok
  %m3_arc1 = and i1 %m3_destroy_ok, %m3_alloc_ok
  %m3_arc2 = and i1 %m3_arc0, %m3_arc1
  %m3_all_ok = and i1 %m3_arc2, %m3_free_ok
  %m3_status = select i1 %m3_all_ok, i32 %process_status, i32 99
  ret i32 %m3_status"
    );
    let instrumented = llvm.replace("  ret i32 %process_status", &checks);
    assert_ne!(instrumented, llvm, "runtime counter hook was not found");
    instrumented
}

const FUNCTIONAL_MATRIX: &str = r#"
void fire<C:Invocable<(),void>>(ref C f){f();}
int choose<C:Invocable<(int),int>>(ref C f,int x,bool call){if(call){return f(x);}return x;}
int repeat<C:Invocable<(int),int>>(ref C f,int x,int n){int value=x;int i=0;while(i<n){value=f(value);i=i+1;}return value;}
int invoke3<C:Invocable<(int,bool,int),int>>(ref C f,int x,bool first,int y){return f(x,first,y);}
P generic<P:Copy,C:Invocable<(P),P>>(ref C f,P x){return f(x);}
int combine<F:Invocable<(int),int>,G:Invocable<(int),int>>(ref F f,ref G g,int x){return f(x)+g(x);}
int forward<C:Invocable<(int),int>>(ref C f,int x){return choose(f,x,true);}
void noop(){return;}
int plus1(int x){return x+1;}
int select(int x,bool first,int y){if(first){return x;}return y;}
int main(){
  Function<(),void> v=noop;fire(v);fire(()=>noop());
  Function<(int),int> f=plus1;
  if(choose(f,10,false)!=10||choose(f,10,true)!=11||repeat(f,10,0)!=10||repeat(f,10,3)!=13){return 1;}
  if(forward(f,10)!=11||generic(f,10)!=11){return 2;}
  Function<(int,bool,int),int> three=select;if(invoke3(three,20,true,1)!=20){return 3;}
  int copyValue=1;string label="x";Matrix<int> data=[2];
  var copy=(int x) capture(copy copyValue)=>x+copyValue;
  var aliased=(int x) capture(alias label)=>x+int(byteLength(label));
  var moved=(int x) capture(move data)=>x+2;
  if(repeat(copy,10,2)!=12||copy(0)!=1){return 4;}
  if(repeat(aliased,10,2)!=12||aliased(0)!=1){return 5;}
  if(repeat(moved,10,2)!=14||moved(0)!=2){return 6;}
  if(repeat((int x) capture(copy copyValue)=>x+copyValue,10,2)!=12){return 7;}
  if(repeat((int x) capture(alias label)=>x+int(byteLength(label)),10,2)!=12){return 8;}
  Matrix<int> freshData=[2];
  if(repeat((int x) capture(move freshData)=>x+2,10,2)!=14){return 9;}
  int ff=combine(f,f,10);int fc=combine(f,copy,10);int cf=combine(copy,f,10);int cc=combine(copy,aliased,10);
  if(ff+fc+cf+cc!=88){return 10;}
  return 0;
}
"#;

#[test]
fn complete_function_closure_control_flow_arity_and_two_evidence_matrix_runs_o0_o2() {
    let hir =
        analyze(parse_source(&SourceFile::new("borrowed_matrix.ae", FUNCTIONAL_MATRIX)).unwrap())
            .unwrap();
    verify_hir(&hir).unwrap();
    let combinations = hir
        .functions()
        .iter()
        .filter(|function| function.function_id == FunctionId(5))
        .map(|function| {
            let first = hir
                .types()
                .reference_info(function.parameters[0].ty)
                .unwrap()
                .0;
            let second = hir
                .types()
                .reference_info(function.parameters[1].ty)
                .unwrap()
                .0;
            (
                matches!(hir.types().get(first), Some(TypeData::Closure { .. })),
                matches!(hir.types().get(second), Some(TypeData::Closure { .. })),
            )
        })
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(
        combinations,
        [(false, false), (false, true), (true, false), (true, true)].into()
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (status, llvm) = run(FUNCTIONAL_MATRIX, "matrix", optimization);
        assert_eq!(status, 0, "functional matrix failed at {optimization:?}");
        assert!(!llvm.contains("BorrowedCapabilityInvoke"));
        assert!(!llvm.contains("CapabilityInvoke"));
        assert!(!llvm.contains("invocable_adapter"));
    }
}

#[test]
fn borrowed_place_and_outer_call_borrow_are_nested_and_owner_cleanup_is_later() {
    let source = r"int twice<C:Invocable<(int),int>>(ref C f,int x){return f(x)+f(x);}int main(){int n=1;var f=(int x) capture(copy n)=>x+n;int a=twice(f,20);int b=twice((int x) capture(copy n)=>x+n,20);return a+b+f(0)-85;}";
    let hir =
        analyze(parse_source(&SourceFile::new("borrow_nesting.ae", source)).unwrap()).unwrap();
    let mir = verify_mir(lower_hir(hir)).unwrap();
    let borrowed = mir
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
    let parameter = borrowed.parameters[0].local;
    let operations = borrowed
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .collect::<Vec<_>>();
    assert_eq!(
        operations
            .iter()
            .filter(|i| matches!(i.value, Rvalue::ClosureBorrow { .. }))
            .count(),
        2
    );
    assert_eq!(
        operations
            .iter()
            .filter(|i| matches!(i.value, Rvalue::ClosureCall { .. }))
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
                Rvalue::Drop { owner } =>
                    !matches!(owner.base, PlaceBase::Local(local) if local == parameter),
                _ => true,
            })
    );
    let ssa = verify_ssa(build_ssa(&mir)).unwrap();
    let borrowed_ssa = &ssa.as_ssa().functions[borrowed.id.0 as usize];
    let parameter = borrowed_ssa.parameters[0].value;
    assert!(
        borrowed_ssa
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
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(source, "nesting", optimization).0, 0);
    }
}

#[test]
fn direct_by_value_and_borrowed_lvalue_costs_are_instrumented_separately() {
    let scenarios = [
        (
            "direct",
            "int main(){int n=1;var f=(int x) capture(copy n)=>x+n;int value=f(20)+f(20);return value-42;}",
            (0, 1, 1, 1, 1),
        ),
        (
            "by-value",
            "int twice<C:Invocable<(int),int>>(C f,int x){return f(x)+f(x);}int main(){int n=1;var f=(int x) capture(copy n)=>x+n;return twice(f,20)-42;}",
            (1, 2, 1, 1, 1),
        ),
        (
            "borrowed",
            "int twice<C:Invocable<(int),int>>(ref C f,int x){return f(x)+f(x);}int main(){int n=1;var f=(int x) capture(copy n)=>x+n;int value=twice(f,20);int alive=f(0);return value+alive-43;}",
            (0, 1, 1, 1, 1),
        ),
    ];
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        for (label, source, counts) in scenarios {
            let llvm = compile(source, optimization);
            let instrumented =
                instrument_closure_counts(&llvm, counts.0, counts.1, counts.2, counts.3, counts.4);
            assert_eq!(
                execute(&instrumented, label, optimization),
                0,
                "counter mismatch for {label} at {optimization:?}"
            );
            assert!(!llvm.contains("invocable_adapter"));
            assert!(!llvm.contains("BorrowedCapabilityInvoke"));
        }
    }
}

const NUMERIC_INTEGRATION: &str = r"
float64 integrate<C:Invocable<(float64),float64>>(ref C f,float64 a,float64 b,usize n){
  float64 h=(b-a)/float64(n);float64 sum=0.0;usize i=0;
  while(i<n){sum=sum+f(a+(float64(i)+0.5)*h);i=i+1;}
  return sum*h;
}
float64 square(float64 x){return x*x;}
int main(){
  Function<(float64),float64> top=square;
  float64 r0=integrate(top,0.0,1.0,usize(100));
  float64 scale=2.0;var closure=(float64 x) capture(copy scale)=>scale*x;
  float64 r1=integrate(closure,0.0,1.0,usize(100));
  float64 alive=closure(0.5);
  float64 r2=integrate((float64 x) capture(copy scale)=>scale*x,0.0,1.0,usize(100));
  float64 expected=0.333325;
  if(abs(r0-expected)>1.0e-12){return 1;}
  if(abs(r1-1.0)>1.0e-12||abs(r2-1.0)>1.0e-12||abs(alive-1.0)>1.0e-12){return 2;}
  return 0;
}
";

#[test]
fn borrowed_midpoint_consumer_function_closure_lvalue_and_fresh_runs_o0_o2() {
    let independently_computed = 1.0_f64 / 3.0 - 1.0 / (12.0 * 100.0_f64.powi(2));
    assert!((independently_computed - 0.333_325).abs() < 1.0e-15);
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (status, llvm) = run(NUMERIC_INTEGRATION, "numeric", optimization);
        assert_eq!(status, 0, "numeric consumer failed at {optimization:?}");
        assert!(!llvm.contains("BorrowedCapabilityInvoke"));
        assert!(!llvm.contains("CapabilityInvoke"));
        assert!(!llvm.contains("invocable_adapter"));
        // Two closure boxes are intrinsic to the lvalue/fresh closures. Borrowed
        // adaptation itself contributes no retain or additional allocation.
        let instrumented = instrument_closure_counts(&llvm, 0, 2, 2, 2, 2);
        assert_eq!(execute(&instrumented, "numeric-counts", optimization), 0);
    }
}

#[test]
fn borrowed_generic_import_and_forwarding_monomorphize_across_modules_o0_o2() {
    let entry = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/modules/borrowed_invocable_param_m3/main.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        assert_eq!(execute(&compilation.llvm, "module", optimization), 0);
        assert!(!compilation.llvm.contains("BorrowedCapabilityInvoke"));
        assert!(!compilation.llvm.contains("CapabilityInvoke"));
    }
}

#[test]
fn forbidden_borrowed_forms_and_owning_or_escape_operations_are_rejected() {
    let cases = [
        "int bad<C:Invocable<(int),int>>(ref mut C f){return f(1);}int main(){return 0;}",
        "C bad<C:Invocable<(int),int>>(ref C f){C owner=*f;return owner;}int main(){return 0;}",
        "ref C bad<C:Invocable<(int),int>>(ref C f){return f;}int main(){return 0;}",
        "void bad<C:Invocable<(int),int>>(ref C f){var escaped=(int x)=>f(x);return;}int main(){return 0;}",
        "void bad<C:Invocable<(int),int>>(ref C f){*f=*f;return;}int main(){return 0;}",
        "int bad<C:Invocable<(int),int>>(ref C f){return f(true);}int main(){return 0;}",
        "int bad<C:Invocable<(int),int>>(ref C f){return f(1);}int main(){int x=1;return bad(x);}",
    ];
    for source in cases {
        let parsed = parse_source(&SourceFile::new("borrowed_negative.ae", source));
        let rejected = parsed.is_err() || analyze(parsed.unwrap()).is_err();
        assert!(rejected, "accepted forbidden borrowed form: {source}");
    }
}
