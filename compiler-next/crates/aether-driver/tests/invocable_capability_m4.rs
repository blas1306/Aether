//! INVOCABLE-CAPABILITY-V1 M4 end-to-end qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session_with_optimization,
    compile_source_with_optimization,
};
use aether_frontend::{FunctionId, SourceFile, TypeData, analyze, parse_source, verify_hir};

fn run(source: &str, label: &str, optimization: OptimizationLevel) -> (i32, String) {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let compilation = compile_source_with_optimization(
        &SourceFile::new(format!("invocable_m4_{label}.ae"), source),
        &[Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{label}: {diagnostics:#?}"));
    let executable = std::env::temp_dir().join(format!(
        "aether-invocable-m4-{label}-{}-{}-{optimization:?}",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap_or_else(|diagnostics| panic!("{diagnostics:#?}\n{}", compilation.llvm));
    let status = Command::new(&executable)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1);
    let _ = fs::remove_file(executable);
    (status, compilation.llvm)
}

fn instrument_closure_counts(llvm: &str) -> String {
    let checks = r"  %m4_retains = load i64, ptr @aether_closure_retain_count
  %m4_releases = load i64, ptr @aether_closure_release_count
  %m4_destroys = load i64, ptr @aether_closure_destroy_count
  %m4_allocs = load i64, ptr @aether_heap_alloc_count
  %m4_frees = load i64, ptr @aether_heap_free_count
  %m4_retain_ok = icmp eq i64 %m4_retains, 1
  %m4_release_ok = icmp eq i64 %m4_releases, 2
  %m4_destroy_ok = icmp eq i64 %m4_destroys, 1
  %m4_alloc_ok = icmp eq i64 %m4_allocs, 1
  %m4_free_ok = icmp eq i64 %m4_frees, 1
  %m4_arc0 = and i1 %m4_retain_ok, %m4_release_ok
  %m4_arc1 = and i1 %m4_destroy_ok, %m4_alloc_ok
  %m4_arc2 = and i1 %m4_arc0, %m4_arc1
  %m4_all_ok = and i1 %m4_arc2, %m4_free_ok
  %m4_status = select i1 %m4_all_ok, i32 %process_status, i32 99
  ret i32 %m4_status";
    let instrumented = llvm.replace("  ret i32 %process_status", checks);
    assert_ne!(instrumented, llvm, "runtime counter hook was not found");
    instrumented
}

fn execute_llvm(llvm: &str, label: &str, optimization: OptimizationLevel) -> i32 {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let executable = std::env::temp_dir().join(format!(
        "aether-invocable-m4-instrumented-{label}-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &executable)
        .unwrap();
    let status = Command::new(&executable)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1);
    let _ = fs::remove_file(executable);
    status
}

const MULTIPLE_CALLABLES: &str = r"
R combine<P:Copy,R:RingOps,F:Invocable<(P),R>,G:Invocable<(P),R>>(F f,G g,P x){
  return f(x)+g(x);
}
int plus1(int x){return x+1;}
int plus2(int x){return x+2;}
int main(){
  Function<(int),int> f=plus1;
  Function<(int),int> g=plus2;
  int a=1;var c=(int x) capture(copy a)=>x+a;
  int b=2;var d=(int x) capture(copy b)=>x+b;
  int ff=combine(f,g,10);
  int fc=combine(f,c,10);
  int cf=combine(c,g,10);
  int cc=combine(c,d,10);
  return ff+fc+cf+cc-91;
}
";

#[test]
fn two_independent_callable_binders_generate_four_exact_instances() {
    let hir = analyze(
        parse_source(&SourceFile::new(
            "invocable_m4_combinations.ae",
            MULTIPLE_CALLABLES,
        ))
        .unwrap(),
    )
    .unwrap();
    verify_hir(&hir).unwrap();
    let instances = hir
        .functions()
        .iter()
        .filter(|function| function.function_id == FunctionId(0))
        .collect::<Vec<_>>();
    assert_eq!(
        instances.len(),
        4,
        "FF, FC, CF and CC specialize separately"
    );
    let kinds = instances
        .iter()
        .map(|function| {
            let first = matches!(
                hir.types().get(function.parameters[0].ty),
                Some(TypeData::Closure { .. })
            );
            let second = matches!(
                hir.types().get(function.parameters[1].ty),
                Some(TypeData::Closure { .. })
            );
            (first, second)
        })
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(
        kinds,
        [(false, false), (false, true), (true, false), (true, true)].into()
    );

    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(MULTIPLE_CALLABLES, "combinations", optimization).0, 0);
    }
}

const NUMERIC_INTEGRATION: &str = r#"
float64 integrate<C:Invocable<(float64),float64>>(
  C f,float64 a,float64 b,usize n
){
  float64 h=(b-a)/float64(n);
  float64 sum=0.0;
  usize i=0;
  while(i<n){
    sum=sum+f(a+(float64(i)+0.5)*h);
    i=i+1;
  }
  return sum*h;
}
float64 square(float64 x){return x*x;}
int main(){
  Function<(float64),float64> top=square;
  float64 r0=integrate(top,0.0,1.0,usize(100));
  float64 r1=integrate((float64 x)=>x*x,0.0,1.0,usize(100));
  float64 factor=2.0;
  var copied=(float64 x) capture(copy factor)=>factor*x;
  float64 r2=integrate(copied,0.0,1.0,usize(100));
  string label="alias";
  var aliased=(float64 x) capture(alias label)=>x*x;
  float64 r3=integrate(aliased,0.0,1.0,usize(100));
  Matrix<int> data=[2];
  var moved=(float64 x) capture(move data)=>x+x;
  float64 r4=integrate(moved,0.0,1.0,usize(100));
  float64 square_expected=0.333325;
  if(abs(r0-square_expected)>1.0e-12||abs(r1-square_expected)>1.0e-12){return 1;}
  if(abs(r2-1.0)>1.0e-12||abs(r3-square_expected)>1.0e-12||abs(r4-1.0)>1.0e-12){return 2;}
  return 0;
}
"#;

#[test]
fn rectangle_integration_runs_all_required_carriers_at_o0_and_o2() {
    // Midpoint rectangles for x^2 on [0,1], n=100:
    // 1/3 - 1/(12*n^2) = 0.333325 exactly in real arithmetic.
    let independently_computed = 1.0_f64 / 3.0 - 1.0 / (12.0 * 100.0_f64.powi(2));
    assert!((independently_computed - 0.333_325).abs() < 1.0e-15);
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (status, llvm) = run(NUMERIC_INTEGRATION, "integration", optimization);
        assert_eq!(status, 0, "numeric consumer failed at {optimization:?}");
        assert!(!llvm.contains("CapabilityInvoke"));
        assert!(!llvm.contains("invocable_adapter"));
    }
}

#[test]
fn invocable_adds_no_arc_or_allocation_over_direct_closure_parameter() {
    let generic = "int twice<C:Invocable<(int),int>>(C f,int x){return f(x)+f(x);}int main(){int n=1;var f=(int x) capture(copy n)=>x+n;return twice(f,20)-42;}";
    let direct = "int twice(Closure<(int),int> f,int x){return f(x)+f(x);}int main(){int n=1;var f=(int x) capture(copy n)=>x+n;return twice(f,20)-42;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (generic_status, generic_llvm) = run(generic, "cost-generic", optimization);
        let (direct_status, direct_llvm) = run(direct, "cost-direct", optimization);
        assert_eq!((generic_status, direct_status), (0, 0));
        assert_eq!(
            execute_llvm(
                &instrument_closure_counts(&generic_llvm),
                "generic",
                optimization
            ),
            0
        );
        assert_eq!(
            execute_llvm(
                &instrument_closure_counts(&direct_llvm),
                "direct",
                optimization
            ),
            0
        );
        assert!(!generic_llvm.contains("invocable_adapter"));
        assert!(!generic_llvm.contains("CapabilityInvoke"));
    }
}

#[test]
fn generic_invocable_import_monomorphizes_across_source_modules() {
    let entry = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/modules/invocable_capability_m4/main.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        let executable = std::env::temp_dir().join(format!(
            "aether-invocable-m4-import-{}-{optimization:?}",
            std::process::id()
        ));
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &executable)
            .unwrap();
        let status = Command::new(&executable).status().unwrap();
        let _ = fs::remove_file(executable);
        assert_eq!(status.code(), Some(0));
        assert!(!compilation.llvm.contains("CapabilityInvoke"));
    }
}

#[test]
fn zero_multi_parameter_and_void_invocations_execute_at_o0_and_o2() {
    let source = r"
void fire<C:Invocable<(),void>>(C f){f();}
int invoke3<C:Invocable<(int,bool,int),int>>(C f,int x,bool choose,int y){
  return f(x,choose,y);
}
void noop(){return;}
int select(int x,bool choose,int y){if(choose){return x;}return y;}
int main(){
  Function<(),void> f0=noop;fire(f0);fire(()=>noop());
  Function<(int,bool,int),int> f3=select;
  int a=invoke3(f3,20,true,1);
  int offset=1;
  var closure=(int x,bool choose,int y) capture(copy offset)=>x+y+offset;
  return a+invoke3(closure,10,false,10)-41;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(source, "shapes", optimization).0, 0);
    }
}

#[test]
fn every_signature_dimension_and_numeric_conversion_mismatch_is_rejected() {
    let cases = [
        // Arity.
        "C keep<C:Invocable<(int,bool),int>>(C f){return f;}int one(int x){return x;}int main(){Function<(int),int> f=one;var x=keep<Function<(int),int>>(f);return 0;}",
        // First and second parameter positions, independently.
        "C keep<C:Invocable<(int,bool),int>>(C f){return f;}int bad(bool x,bool y){return 0;}int main(){Function<(bool,bool),int> f=bad;var x=keep<Function<(bool,bool),int>>(f);return 0;}",
        "C keep<C:Invocable<(int,bool),int>>(C f){return f;}int bad(int x,int y){return 0;}int main(){Function<(int,int),int> f=bad;var x=keep<Function<(int,int),int>>(f);return 0;}",
        // Result.
        "C keep<C:Invocable<(int),int>>(C f){return f;}bool bad(int x){return true;}int main(){Function<(int),bool> f=bad;var x=keep<Function<(int),bool>>(f);return 0;}",
        // Neither widening nor narrowing is an Invocable adaptation.
        "C keep<C:Invocable<(float64),float64>>(C f){return f;}float32 bad(float32 x){return x;}int main(){Function<(float32),float32> f=bad;var x=keep<Function<(float32),float32>>(f);return 0;}",
        "C keep<C:Invocable<(float32),float32>>(C f){return f;}float64 bad(float64 x){return x;}int main(){Function<(float64),float64> f=bad;var x=keep<Function<(float64),float64>>(f);return 0;}",
    ];
    for source in cases {
        let ast = parse_source(&SourceFile::new("invocable_m4_mismatch.ae", source)).unwrap();
        let diagnostics = analyze(ast).unwrap_err();
        assert!(
            diagnostics.iter().any(
                |diagnostic| diagnostic.message.contains("signature mismatch")
                    || diagnostic
                        .message
                        .contains("conflicts with Invocable requirement")
            ),
            "unexpected diagnostics: {diagnostics:#?}"
        );
    }
}

#[test]
fn function_closure_argument_unwind_resume_and_finally_execute_at_o0_and_o2() {
    let cases = [
        r"open class Problem:Exception{public init(){}}int fail(int x){throw Problem();}int apply<C:Invocable<(int),int>>(C f,int x){return f(x);}int main(){int state=0;Function<(int),int> f=fail;try{apply(f,1);}catch(Problem p){state=state+1;}finally{state=state+2;}return state-3;}",
        r"open class Problem:Exception{public init(){}}int fail(int x){throw Problem();}int apply<C:Invocable<(int),int>>(C f,int x){return f(x);}int main(){int state=0;int offset=1;try{apply((int x) capture(copy offset)=>fail(x)+offset,1);}catch(Problem p){state=state+1;}finally{state=state+2;}return state-3;}",
        r"open class Problem:Exception{public init(){}}int failArgument(){throw Problem();}int apply<C:Invocable<(int),int>>(C f,int x){return f(x);}int main(){int state=0;int offset=1;try{apply((int x) capture(copy offset)=>x+offset,failArgument());}catch(Problem p){state=state+1;}finally{state=state+2;}return state-3;}",
        r"open class Problem:Exception{public init(){}}int fail(int x){throw Problem();}int apply<C:Invocable<(int),int>>(C f,int x){return f(x);}int main(){int state=0;Function<(int),int> f=fail;try{try{apply(f,1);}catch(Problem p){throw;}finally{state=state+1;}}catch(Exception p){state=state+2;}return state-3;}",
    ];
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        for (index, source) in cases.iter().enumerate() {
            assert_eq!(
                run(source, &format!("exceptions-{index}"), optimization).0,
                0
            );
        }
    }
}
