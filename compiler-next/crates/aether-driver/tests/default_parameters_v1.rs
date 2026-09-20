//! DEFAULT-PARAMETERS-V1 qualification.

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
            "aether-default-parameters-v1-{label}-{}-{}",
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
        &SourceFile::new("default_parameters_v1.ae", source),
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn status(source: &str, optimization: OptimizationLevel) -> i32 {
    let compilation = compile(source, optimization);
    run_llvm(&compilation.llvm, optimization)
}

fn run_llvm(llvm: &str, optimization: OptimizationLevel) -> i32 {
    let output = Output::new("native");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &output.0)
        .unwrap();
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn diagnostics(source: &str) -> String {
    compile_source_with_optimization(
        &SourceFile::new("bad_default_parameters_v1.ae", source),
        &[],
        OptimizationLevel::O0,
    )
    .unwrap_err()
    .into_iter()
    .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
    .collect::<Vec<_>>()
    .join("\n")
}

fn workspace() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

#[test]
fn trailing_omission_and_chained_defaults_run_at_o0_o2() {
    let source = r"
int encode(int a=1,int b=a+1,int c=b+1){return a*100+b*10+c;}
int main(){return encode()+encode(2)+encode(2,4)+encode(2,4,6)-848;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
    }
    let compilation = compile(source, OptimizationLevel::O0);
    let hir = &compilation.dumps[&Emit::Hir];
    assert!(hir.contains("HirCallArgument"));
    assert!(hir.contains("origin: Explicit"));
    assert!(hir.contains("origin: Defaulted"));
    assert!(hir.contains("name: \"$call"));
    assert!(!compilation.dumps[&Emit::Mir].contains("Defaulted"));
    assert!(!compilation.dumps[&Emit::Ssa].contains("Defaulted"));
}

#[test]
fn explicit_and_default_arguments_are_evaluated_once_left_to_right() {
    let source = r"
int next(ref mut int count){*count=*count+1;return *count;}
int encode(ref mut int count,int a=next(count),int b=next(count)){return a*100+b*10+*count;}
int main(){int count=0;int first=encode(&mut count);int second=encode(&mut count);return first+second+count-470;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
    }
}

#[test]
fn implicit_shared_borrow_works_for_explicit_and_defaulted_arguments() {
    let source = r"
int read(int x,ref int value=x){return *value;}
int main(){int other=2;return read(40)+read(40,other)-42;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(run_llvm(&compilation.llvm, optimization), 0);
        assert!(compilation.dumps[&Emit::Hir].contains("CallScopedSharedBorrow"));
        assert!(compilation.dumps[&Emit::Mir].contains("Borrow"));
        assert!(compilation.dumps[&Emit::Mir].contains("EndBorrow"));
    }
}

#[test]
fn generic_inference_uses_only_explicit_arguments() {
    let accepted = r"
T choose<T>(T value,T fallback=value){return fallback;}
int main(){return choose(21)+choose<int>(21)-42;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(accepted, optimization), 0);
    }
    let rejected = r"
open class Problem:Exception{public init(){}}
T fail<T>(){throw Problem();}
int missing<T>(T value=fail<T>()){return 0;}
int main(){return missing();}
";
    assert!(diagnostics(rejected).contains("E0263 cannot infer generic parameter `T`"));
}

#[test]
fn later_throw_uses_ordinary_unwind_and_prior_binding_cleanup() {
    let source = r"
open class Problem:Exception{public init(){}}
int fail(){throw Problem();}
int consume(Buffer<int> first=Buffer<int>(1,1),Buffer<int> second=Buffer<int>(1,2),int value=fail()){return value;}
int main(){try{return consume();}catch(Problem problem){return 42;}}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(run_llvm(&compilation.llvm, optimization), 42);
        let mir = &compilation.dumps[&Emit::Mir];
        assert!(mir.contains("unwind: Some"));
        assert!(mir.contains("Drop"));
        assert!(!mir.contains("Defaulted"));
    }
}

#[test]
fn diagnostics_cover_the_closed_v1_rules() {
    let cases = [
        (
            "int f(int a=0,int b){return b;}int main(){return 0;}",
            "E0360 parameter `b` is required after a parameter with a default",
        ),
        (
            "int f(int a=\"x\"){return a;}int main(){return 0;}",
            "E0361 default for parameter `a` requires int64",
        ),
        (
            "int f(int a,int b=0){return a+b;}int main(){return f();}",
            "E0362 function `f` accepts 1..2 arguments, found 0",
        ),
        (
            "int f(int a=0){return a;}int main(){return f(1,2);}",
            "E0363 function `f` accepts at most 1 arguments, found 2",
        ),
        (
            "int f(int a=a){return a;}int main(){return 0;}",
            "E0364 default for `a` cannot reference itself parameter `a`",
        ),
        (
            "int f(int a=b,int b=1){return a+b;}int main(){return 0;}",
            "E0364 default for `a` cannot reference later parameter `b`",
        ),
        (
            "int f(int a=missing){return a;}int main(){return 0;}",
            "E0365 default for parameter `a` requires int64",
        ),
        (
            "int f(int a,int b=0){return a+b;}int main(){Function<(int,int),int> g=f;return g(1);}",
            "E0366 function value requires 2 arguments",
        ),
        (
            "class C{public int f(int x=0){return x;}}int main(){return 0;}",
            "E0367 default parameters are not yet supported on methods",
        ),
        (
            "class C{public init(int x=0){}}int main(){return 0;}",
            "E0367 default parameters are not yet supported on methods or initializers",
        ),
        (
            "interface I{int f(int x=0);}int main(){return 0;}",
            "E0367 default parameters are not yet supported on interface requirements",
        ),
    ];
    for (source, expected) in cases {
        let actual = diagnostics(source);
        assert!(actual.contains(expected), "{source}\n{actual}");
    }
}

#[test]
fn function_values_keep_full_type_and_llvm_prototype_is_unchanged() {
    let with_default = compile(
        "double f(double x,double y=0.0){return x+y;}int main(){Function<(double,double),double> g=f;return 0;}",
        OptimizationLevel::O0,
    );
    let without_default = compile(
        "double f(double x,double y){return x+y;}int main(){Function<(double,double),double> g=f;return 0;}",
        OptimizationLevel::O0,
    );
    for llvm in [&with_default.llvm, &without_default.llvm] {
        assert!(llvm.contains("define double"));
        assert!(llvm.contains("(double %v0, double %v1)"));
        assert!(!llvm.contains("arity"));
    }
    assert_eq!(
        with_default
            .llvm
            .lines()
            .find(|line| line.starts_with("define double")),
        without_default
            .llvm
            .lines()
            .find(|line| line.starts_with("define double"))
    );
    assert!(with_default.dumps[&Emit::Hir].contains("FunctionRef"));
    assert!(!with_default.llvm.contains("thunk"));
    assert!(!with_default.llvm.contains("wrapper"));
}

#[test]
fn imported_default_uses_provider_declaration_scope() {
    let entry = workspace().join("tests/modules/default_parameters_v1/main.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            optimization,
        )
        .unwrap();
        assert_eq!(run_llvm(&compilation.llvm, optimization), 42);
        assert!(compilation.dumps[&Emit::Hir].contains("Defaulted"));
    }
}
