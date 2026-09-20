//! FUNCTION-VALUES-V1 non-capturing callable qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session_with_optimization,
    compile_source_with_optimization,
};
use aether_frontend::{SourceFile, TargetProperties, TypeArena, TypeData, TypeId, layout_of};

struct Output(PathBuf);

impl Output {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-function-values-v1-{label}-{}-{}",
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
        &SourceFile::new("function_values_v1.ae", source),
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

fn diagnostics(source: &str) -> Vec<String> {
    compile_source_with_optimization(
        &SourceFile::new("bad_function_values_v1.ae", source),
        &[],
        OptimizationLevel::O0,
    )
    .unwrap_err()
    .into_iter()
    .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
    .collect()
}

fn workspace() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

#[test]
fn canonical_type_is_one_pointer_copy_storable_and_invariant() {
    let mut types = TypeArena::new();
    let unary = types
        .intern_function(vec![TypeId::FLOAT64], TypeId::FLOAT64)
        .unwrap();
    assert_eq!(
        unary,
        types
            .intern_function(vec![TypeId::FLOAT64], TypeId::FLOAT64)
            .unwrap()
    );
    assert_ne!(
        unary,
        types
            .intern_function(vec![TypeId::INT64], TypeId::FLOAT64)
            .unwrap()
    );
    assert!(matches!(types.get(unary), Some(TypeData::Function { .. })));
    let properties = types.properties(unary).unwrap();
    assert!(properties.is_known);
    assert!(properties.is_copy && properties.is_relocatable && properties.is_storable);
    assert!(!properties.needs_drop);
    let layout = layout_of(&types, unary, TargetProperties::LINUX_X86_64, &[], &[]).unwrap();
    assert_eq!((layout.size, layout.align), (8, 8));
    assert!(
        types
            .intern_function(vec![TypeId::VOID], TypeId::INT64)
            .is_err()
    );
}

#[test]
fn zero_unary_multiple_void_local_and_parameter_calls_run_at_o0_o2() {
    let source = r"
int answer(){return 40;}
int add(int a,int b){return a+b;}
int bump(int x){return x+1;}
void consume(int x){}
int call0(Function<(),int> f){return f();}
int call2(Function<(int,int),int> f,int a,int b){return f(a,b);}
void callVoid(Function<(int),void> f,int x){f(x);}
int main(){
  Function<(int,int),int> local=add;
  callVoid(consume,1);
  return call0(answer)+call2(local,1,bump(0));
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 42);
    }
    let compilation = compile(source, OptimizationLevel::O0);
    for emit in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        assert!(compilation.dumps[&emit].contains("FunctionRef"));
        assert!(compilation.dumps[&emit].contains("IndirectCall"));
        assert!(compilation.dumps[&emit].contains("Call {"));
    }
    assert!(compilation.llvm.contains("call i64 %"));
    assert!(compilation.llvm.contains("call i1 %"));
    assert!(!compilation.llvm.contains("bitcast"));
    assert!(!compilation.llvm.contains("ptrtoint"));
}

#[test]
fn generic_function_type_is_fully_concretized_before_mir() {
    let source = r"
T apply<T>(Function<(T),T> f,T value){return f(value);}
int increment(int value){return value+1;}
int main(){return apply<int>(increment,41);}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(status(source, optimization), 42);
        assert!(compilation.dumps[&Emit::Hir].contains("Function<(T), T>"));
        assert!(compilation.dumps[&Emit::Mir].contains("Function<(int64), int64>"));
        assert!(!compilation.dumps[&Emit::Mir].contains("GenericParam"));
    }
}

#[test]
fn syntax_signature_arity_void_and_open_generic_fail_closed() {
    let cases = [
        (
            "int use(Function<int,int> f){return 0;}int main(){return 0;}",
            "E0110 invalid Function type syntax",
        ),
        (
            "int f(int x){return x;}int main(){Function<(double),double> g=f;return 0;}",
            "E0351",
        ),
        (
            "int f(int x){return x;}int main(){Function<(int),int> g=f;return g();}",
            "E0366 function value requires 1 arguments",
        ),
        (
            "int use(Function<(void),int> f){return 0;}int main(){return 0;}",
            "E0350 Function parameter type cannot be void",
        ),
        (
            "T identity<T>(T x){return x;}int main(){Function<(int),int> f=identity;return 0;}",
            "E0355 generic function must be explicitly instantiated",
        ),
        (
            "int main(){Function<(double),double> f=abs;return 0;}",
            "E0356 builtin functions are not values",
        ),
        (
            "class C{public int value(){return 1;}}int main(){C c=C();Function<(),int> f=c.value;return 0;}",
            "E0354 bound and method function values are not supported",
        ),
    ];
    for (source, expected) in cases {
        let actual = diagnostics(source).join("\n");
        assert!(actual.contains(expected), "{source}\n{actual}");
    }
}

#[test]
fn indirect_unwind_catch_and_finally_use_existing_exception_routes() {
    let source = r"
open class Problem:Exception{public init(){}}
int fail(){throw Problem();}
int invoke(Function<(),int> f){return f();}
int main(){
  int result=0;
  try{result=invoke(fail);}
  catch(Problem problem){result=17;}
  finally{result=result+1;}
  return result;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(status(source, optimization), 18);
        assert!(compilation.dumps[&Emit::Mir].contains("IndirectCall"));
        assert!(compilation.dumps[&Emit::Mir].contains("unwind: Some"));
        assert!(compilation.dumps[&Emit::Ssa].contains("IndirectCall"));
        assert!(compilation.llvm.contains("invoke i64 %"));
        assert!(compilation.llvm.contains("landingpad { ptr, i32 }"));
    }
}

#[test]
fn address_taken_only_target_is_emitted_without_callable_lifecycle() {
    let source = "int hidden(){return 7;}int main(){Function<(),int> f=hidden;return 0;}";
    let compilation = compile(source, OptimizationLevel::O2);
    assert!(compilation.llvm.contains("_hidden()"));
    assert!(!compilation.llvm.contains("bitcast"));
    assert!(!compilation.llvm.contains("aether_drop_F"));
    for operation in ["retain_F", "release_F", "alloc_F"] {
        assert!(!compilation.llvm.contains(operation));
    }
}

#[test]
fn qualified_imported_function_reference_runs_at_o0_o2() {
    let entry = workspace().join("tests/modules/function_values_v1/main.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            optimization,
        )
        .unwrap();
        let output = Output::new("imported");
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &output.0)
            .unwrap();
        assert_eq!(Command::new(&output.0).status().unwrap().code(), Some(42));
        for emit in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            assert!(compilation.dumps[&emit].contains("FunctionRef"));
            assert!(compilation.dumps[&emit].contains("IndirectCall"));
        }
    }
}

#[test]
fn later_function_storage_verticals_remain_closed() {
    for source in [
        "int answer(){return 1;}Function<(),int> get(){return answer;}int main(){return 0;}",
        "struct Holder{Function<(),int> callback;}int main(){return 0;}",
        "enum Holder{Some(Function<(),int>)}int main(){return 0;}",
        "int main(){Array<Function<(),int>> callbacks={};return 0;}",
        "int main(){List<Function<(),int>> callbacks=List<Function<(),int>>();return 0;}",
    ] {
        let actual = diagnostics(source).join("\n");
        assert!(actual.contains("E0357"), "{source}\n{actual}");
    }
}
