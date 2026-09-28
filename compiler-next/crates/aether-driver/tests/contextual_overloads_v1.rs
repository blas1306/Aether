//! CONTEXTUAL-OVERLOADS-V1 qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session,
    compile_source_with_optimization,
};
use aether_frontend::{SourceFile, analyze, parse_source, verify_hir};
use aether_middle::{build_ssa, lower_hir, verify_mir, verify_ssa};

fn analyze_source(source: &str) -> aether_frontend::TypedHir {
    analyze(parse_source(&SourceFile::new("contextual_overloads_v1.ae", source)).unwrap())
        .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"))
}

fn diagnostics(source: &str) -> String {
    compile_source_with_optimization(
        &SourceFile::new("bad_contextual_overloads_v1.ae", source),
        &[],
        OptimizationLevel::O0,
    )
    .unwrap_err()
    .into_iter()
    .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
    .collect::<Vec<_>>()
    .join("\n")
}

struct Temporary(PathBuf);

impl Temporary {
    fn path(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-contextual-overloads-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        )))
    }

    fn directory(label: &str) -> Self {
        let value = Self::path(label);
        fs::create_dir_all(&value.0).unwrap();
        value
    }
}

impl Drop for Temporary {
    fn drop(&mut self) {
        let _ = if self.0.is_dir() {
            fs::remove_dir_all(&self.0)
        } else {
            fs::remove_file(&self.0)
        };
    }
}

#[test]
fn resolves_by_arity_argument_result_and_nested_parameter_context() {
    let source = r"
int arity(){return 1;}
int arity(int value){return value;}
int argument(int value){return value+1;}
int argument(bool value){if(value){return 7;}return 8;}
int contextual(usize value){return int(value);}
bool contextual(usize value){return value!=0;}
int consume(int value){return value;}
int main(){
  int a=arity();
  int b=arity(2);
  int c=argument(true);
  int d=contextual(4);
  bool e=contextual(1);
  int f=consume(contextual(5));
  if(e){return a+b+c+d+f-19;}
  return 1;
}
";
    let hir = analyze_source(source);
    verify_hir(&hir).unwrap();
    let mir = verify_mir(lower_hir(hir)).unwrap();
    verify_ssa(build_ssa(&mir)).unwrap();

    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_source_with_optimization(
            &SourceFile::new("contextual_overloads_v1.ae", source),
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            optimization,
        )
        .unwrap();
        let output = Temporary::path("native");
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &output.0)
            .unwrap();
        assert_eq!(
            Command::new(&output.0).status().unwrap().code(),
            Some(0),
            "{optimization:?}"
        );
    }
}

#[test]
fn infers_return_only_generic_and_preserves_vector_orientation() {
    let source = r"
struct Bundle{Matrix<int> matrix;}
Matrix<T> empty<T:Storable>(usize ignored){return [];}
Vector<T,Row> empty<T:Storable>(usize ignored){return [];}
Vector<T,Column> empty<T:Storable>(usize ignored){return [];}
Matrix<T> square<T:Storable>(usize ignored,usize alsoIgnored){return [];}
Matrix<int> fromReturn(){return empty(1);}
int main(){
  Matrix<int> matrix=empty(1);
  Vector<int,Row> row=empty(2);
  Vector<int,Column> column=empty(3);
  Matrix<float64> assigned=[];
  assigned=empty(4);
  Matrix<int> nested=square(2,2);
  Matrix<int> returned=fromReturn();
  Bundle bundle=Bundle(empty(5));
  return int(rows(matrix)+dimension(row)+dimension(column)+rows(assigned)+rows(nested)+rows(returned)+rows(bundle.matrix));
}
";
    let hir = analyze_source(source);
    verify_hir(&hir).unwrap();
    let mir = verify_mir(lower_hir(hir)).unwrap();
    verify_ssa(build_ssa(&mir)).unwrap();
}

#[test]
fn constraints_and_import_aliases_participate_without_name_special_cases() {
    let constrained = r"
int classify<T:Add>(T value){return 1;}
int classify<T:Storable>(T value){return 2;}
int main(){int selected=classify(true);return selected-2;}
";
    analyze_source(constrained);

    let directory = Temporary::directory("modules");
    let entry = directory.0.join("main.ae");
    let library = directory.0.join("library.ae");
    fs::write(
        &entry,
        "package Main; import Library.Values as values; int main(){int a=values.pick(true);bool b=values.pick(1);if(b){return a-7;}return 1;}",
    )
    .unwrap();
    fs::write(
        library,
        "package Library.Values; int pick(bool value){if(value){return 7;}return 8;} bool pick(int value){return value!=0;}",
    )
    .unwrap();
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(compilation.dumps[&Emit::Hir].contains("pick"));
    assert!(!compilation.dumps[&Emit::Mir].contains("Overload"));
    assert!(!compilation.dumps[&Emit::Ssa].contains("Overload"));
}

#[test]
fn ambiguity_no_match_missing_context_and_result_mismatch_are_diagnostic() {
    let ambiguous = diagnostics(
        "int select(int x){return x;}bool select(int x){return x!=0;}int main(){var x=select(1);return 0;}",
    );
    assert!(
        ambiguous.contains("E0461 ambiguous overload"),
        "{ambiguous}"
    );

    let no_match = diagnostics(
        "int select(int x){return x;}int select(bool x){return 0;}int main(){return select(\"bad\");}",
    );
    assert!(
        no_match.contains("E0460 no matching overload"),
        "{no_match}"
    );

    let missing = diagnostics(
        "Matrix<T> only<T:Storable>(usize x){return [];}int main(){var x=only(1);return 0;}",
    );
    assert!(
        missing.contains("E0263") || missing.contains("E0462"),
        "{missing}"
    );

    let mismatch = diagnostics(
        "string result(int x){return \"x\";}int result(bool x){return 1;}int main(){int x=result(1);return x;}",
    );
    assert!(
        mismatch.contains("E0460 result type mismatch"),
        "{mismatch}"
    );

    let orientation = diagnostics(
        "Vector<T,Row> direction<T:Storable>(usize x){return [];}Vector<T,Column> direction<T:Storable>(usize x){return [];}int main(){var x=direction<int>(1);return 0;}",
    );
    assert!(
        orientation.contains("orientation ambiguity"),
        "{orientation}"
    );
}
