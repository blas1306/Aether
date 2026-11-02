//! ANONYMOUS-FUNCTIONS-V1 capture-free qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session_with_optimization,
    compile_source_with_optimization,
};
use aether_frontend::SourceFile;

struct Output(PathBuf);

impl Output {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-anonymous-functions-v1-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        )))
    }
}

impl Drop for Output {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("anonymous_functions_v1.ae", source),
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn status(source: &str, optimization: OptimizationLevel) -> i32 {
    let compilation = compile(source, optimization);
    let output = Output::new("native");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &output.0)
        .unwrap();
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn diagnostics(source: &str) -> String {
    compile_source_with_optimization(
        &SourceFile::new("bad_anonymous_functions_v1.ae", source),
        &[],
        OptimizationLevel::O0,
    )
    .unwrap_err()
    .into_iter()
    .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
    .collect::<Vec<_>>()
    .join("\n")
}

#[test]
fn zero_one_many_var_expected_and_repeated_calls_run_at_o0_o2() {
    let source = r"
int apply(Function<(int),int> f,int x){return f(x);}
int main(){
  var forty=()=>40;
  var add=(int a,int b)=>a+b;
  Function<(int),int> square=(int x)=>x*x;
  return forty()+add(1,1)+apply(square,0);
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 42);
    }
    let compilation = compile(source, OptimizationLevel::O0);
    for emit in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&emit];
        assert!(dump.contains("FunctionRef"));
        assert!(dump.contains("IndirectCall"));
        assert!(dump.contains("$lambda$"));
        assert!(!dump.contains("Closure"));
    }
    assert!(!compilation.llvm.contains("closure"));
    assert!(!compilation.llvm.contains("alloc_lambda"));
}

#[test]
fn bool_void_and_top_level_calls_use_the_existing_function_spine() {
    let source = r"
int answer(){return 42;}
void noop(){}
void run(Function<(),void> f){f();}
int main(){
  Function<(int),bool> positive=(int x)=>x>0;
  run(()=>noop());
  if(positive(1)){return answer();}
  return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 42);
    }
}

#[test]
fn capture_signature_and_arity_errors_fail_closed() {
    let shadowing = r"
int main(){int value=99;var f=(int value)=>value+1;return f(41);}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(shadowing, optimization), 42);
    }

    let capture = diagnostics("int main(){int n=4;var f=(int x)=>x+n;return f(1);}");
    assert!(
        capture.contains("E0376 capturing Closure reached VerifiedSsa"),
        "{capture}"
    );

    let signature = diagnostics("int main(){Function<(double),double> f=(int x)=>x;return 0;}");
    assert!(
        signature.contains("E0351 anonymous function has type"),
        "{signature}"
    );

    let arity = diagnostics("int main(){var f=(int x)=>x;return f();}");
    assert!(arity.contains("requires 1 arguments"), "{arity}");
}

#[test]
fn imported_calls_and_nested_capture_free_lambdas_run_at_o0_o2() {
    let entry = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/modules/anonymous_functions_v1/main.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            optimization,
        )
        .unwrap();
        let output = Output::new("imports-nested");
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &output.0)
            .unwrap();
        assert_eq!(Command::new(&output.0).status().unwrap().code(), Some(42));
    }
}

#[test]
fn exception_from_lambda_target_propagates_through_indirect_call() {
    let source = r"
open class Problem:Exception{public init(){}}
int fail(){throw Problem();}
int invoke(Function<(),int> f){return f();}
int main(){
  int result=0;
  try{result=invoke(()=>fail());}
  catch(Problem problem){result=42;}
  return result;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 42);
    }
    let compilation = compile(source, OptimizationLevel::O0);
    assert!(compilation.dumps[&Emit::Mir].contains("unwind: Some"));
    assert!(compilation.llvm.contains("invoke i64 %"));
}
