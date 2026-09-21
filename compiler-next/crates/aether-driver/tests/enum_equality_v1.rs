//! ENUM-EQUALITY-V1 end-to-end qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session_with_optimization,
    compile_source, compile_source_with_optimization,
};
use aether_frontend::SourceFile;

struct Temporary(PathBuf);

impl Temporary {
    fn path(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-enum-equality-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        )))
    }

    fn directory(label: &str) -> Self {
        let temporary = Self::path(label);
        fs::create_dir(&temporary.0).unwrap();
        temporary
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

fn status(source: &str, optimization: OptimizationLevel) -> i32 {
    let compilation = compile_source_with_optimization(
        &SourceFile::new("enum_equality_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"));
    let output = Temporary::path("native");
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
    compile_source(&SourceFile::new("bad_enum_equality_v1.ae", source), &[])
        .unwrap_err()
        .into_iter()
        .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn variants_locals_params_returns_conditions_and_generic_instances_work_o0_o2() {
    let reproducer = r"
enum Status {
    Ok,
    Error
}

int main() {
    Status status = Status.Ok;
    if (status == Status.Ok) {
        return 0;
    }
    return 1;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(reproducer, optimization), 0);
    }

    let source = r"
enum Status { Ok, Error }
alias State = Status;
enum Box<T> { Empty, Full }
bool same(Status left, Status right) { return left == right; }
bool different<T>(Box<T> left, Box<T> right) { return left != right; }
int main() {
    State a = Status.Ok;
    Status b = Status.Error;
    if (!(Status.Ok == Status.Ok)) { return 1; }
    if (Status.Ok == Status.Error) { return 2; }
    if (!(a == Status.Ok)) { return 3; }
    if (a == b) { return 4; }
    if (!(a != b)) { return 5; }
    if (!same(a, Status.Ok)) { return 6; }
    Box<int> left = Box<int>.Empty;
    Box<int> right = Box<int>.Full;
    bool genericResult = different<int>(left, right);
    if (!genericResult) { return 7; }
    return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
    }

    let compilation = compile_source_with_optimization(
        &SourceFile::new("enum_equality_dump.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        OptimizationLevel::O0,
    )
    .unwrap();
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        assert!(
            dump.contains("Equal") && dump.contains("NotEqual"),
            "{phase:?}\n{dump}"
        );
        assert!(
            dump.contains("Status") && dump.contains("Box<int64>"),
            "{phase:?}\n{dump}"
        );
    }
    assert!(compilation.llvm.contains("extractvalue"));
    assert!(compilation.llvm.contains("icmp eq i32"));
    assert!(compilation.llvm.contains("icmp ne i32"));
    assert!(!compilation.llvm.contains("memcmp"));
}

#[test]
fn nominal_instance_payload_and_operand_mismatches_have_dedicated_diagnostics() {
    let cases = [
        (
            "enum A{X}enum B{X}int main(){if(A.X==B.X){return 1;}return 0;}",
            "E0470",
        ),
        (
            "enum Box<T>{Empty,Full}int main(){Box<int>a=Box<int>.Empty;Box<double>b=Box<double>.Empty;if(a==b){return 1;}return 0;}",
            "E0472",
        ),
        (
            "enum Status{Ok,Error}int main(){if(Status.Ok==1){return 1;}return 0;}",
            "E0472",
        ),
        (
            "enum Status{Ok,Error}int main(){if(Status.Ok==true){return 1;}return 0;}",
            "E0472",
        ),
        (
            "enum Status{Ok,Error}struct S{int x;}int main(){if(Status.Ok==S(1)){return 1;}return 0;}",
            "E0472",
        ),
        (
            "enum Status{Ok,Error}int main(){Status a=Status.Ok;Status b=Status.Error;if(a<b){return 1;}return 0;}",
            "E0472",
        ),
        (
            "enum Result{Ok,Error(int)}int main(){Result a=Result.Ok;Result b=Result.Ok;if(a==b){return 1;}return 0;}",
            "E0471",
        ),
        (
            "enum Status{Ok,Error}int main(){Status a=Status.Ok;Status b=Status.Error;Status c=a+b;return 0;}",
            "E0472",
        ),
    ];
    for (source, code) in cases {
        let actual = diagnostics(source);
        assert!(actual.contains(code), "{source}\n{actual}");
        assert!(!actual.contains("E0348"), "{source}\n{actual}");
    }
}

#[test]
fn nullable_rules_are_unchanged() {
    let valid = r"
enum Status { Ok, Error }
int main() {
    Status? value = null;
    if (value != null) { return 1; }
    value = Status.Ok;
    if (null == value) { return 2; }
    return 0;
}
";
    assert_eq!(status(valid, OptimizationLevel::O0), 0);
    let invalid = diagnostics(
        "enum Status{Ok,Error}int main(){Status? a=null;Status? b=null;if(a==b){return 1;}return 0;}",
    );
    assert!(invalid.contains("general nullable equality"), "{invalid}");
    assert!(!invalid.contains("E047"), "{invalid}");
}

#[test]
fn imported_enum_identity_and_qualified_variants_work_o0_o2() {
    let directory = Temporary::directory("packages");
    fs::write(
        directory.0.join("states.ae"),
        "package states;enum Status{Ok,Error}bool ok(Status value){return value==Status.Ok;}",
    )
    .unwrap();
    let entry = directory.0.join("main.ae");
    fs::write(
        &entry,
        "package app;import states;int main(){states.Status value=states.Status.Ok;if(!states.ok(value)){return 1;}return 0;}",
    )
    .unwrap();
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            optimization,
        )
        .unwrap();
        let output = Temporary::path("package-native");
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &output.0)
            .unwrap();
        assert_eq!(Command::new(&output.0).status().unwrap().code(), Some(0));
    }
}

#[test]
fn exact_enum_type_ids_survive_hir_mir_and_ssa() {
    let source = "enum Box<T>{Empty,Full}int main(){Box<int>a=Box<int>.Empty;Box<int>b=Box<int>.Full;if(a==b){return 1;}return 0;}";
    let compilation = compile_source_with_optimization(
        &SourceFile::new("type_ids.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        OptimizationLevel::O0,
    )
    .unwrap();
    let hir = &compilation.dumps[&Emit::Hir];
    let enum_type = hir
        .lines()
        .find_map(|line| {
            (line.contains("Box<int64>") && line.contains("TypeId("))
                .then(|| line.split("TypeId(").nth(1)?.split(')').next())
                .flatten()
        })
        .expect("Box<int> type id");
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        assert!(
            compilation.dumps[&phase].contains(&format!("TypeId({enum_type})")),
            "{phase:?}"
        );
    }
    assert!(
        compilation.dumps[&Emit::Hir]
            .lines()
            .any(|line| line.contains("EnumInstance"))
            || compilation.dumps[&Emit::Hir].contains("Box<int64>")
    );
}

#[test]
fn numerical_methods_uses_direct_status_equality_and_keeps_eighteen_true_lines_o0_o2() {
    let entry = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../examples/numerical_methods/main.ae");
    let results = fs::read_to_string(entry.with_file_name("Results.ae")).unwrap();
    assert!(!results.contains("match (status)"));
    assert!(results.contains("status == RootStatus.Converged"));
    assert!(results.contains("status == IntegrationStatus.Success"));

    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            optimization,
        )
        .unwrap();
        let output = Temporary::path("numerical-methods");
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &output.0)
            .unwrap();
        let execution = Command::new(&output.0).output().unwrap();
        assert!(execution.status.success());
        let stdout = String::from_utf8(execution.stdout).unwrap();
        let lines = stdout.lines().collect::<Vec<_>>();
        assert_eq!(lines.len(), 18, "{optimization:?}\n{stdout}");
        assert!(
            lines.iter().all(|line| line.ends_with("true")),
            "{optimization:?}\n{stdout}"
        );
    }
}
