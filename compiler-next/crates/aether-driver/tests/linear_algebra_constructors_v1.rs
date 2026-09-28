//! LINEAR-ALGEBRA-CONSTRUCTORS-V1 package and diagnostic qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session,
    compile_session_with_optimization,
};

const LIBRARY: &str = include_str!("../../../../linearAlgebra/src/lib.ae");

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-linear-algebra-constructors-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        fs::write(path.join("linearAlgebra.ae"), LIBRARY).unwrap();
        Self(path)
    }

    fn entry(&self, source: &str) -> PathBuf {
        let path = self.0.join("main.ae");
        fs::write(&path, source).unwrap();
        path
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn diagnostics(source: &str) -> String {
    let directory = Directory::new("diagnostic");
    let entry = directory.entry(source);
    compile_session(CompilationSession::discover(&entry).unwrap(), &[])
        .unwrap_err()
        .into_iter()
        .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn ordinary_package_lowers_constructors_only_through_filled_init() {
    let directory = Directory::new("lowering");
    let entry = directory.entry(
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=la.zeros(3,2);Vector<float32,Row>r=la.ones(4);Matrix<float64>i=la.identity(3);return int(rows(a)+dimension(r)+columns(i)-10);}",
    );
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        assert!(compilation.dumps[&phase].contains("MatrixFilled"));
        assert!(compilation.dumps[&phase].contains("VectorFilled"));
    }
    assert!(compilation.llvm.contains("@aether_matrix_fill_"));
    assert!(compilation.llvm.contains("@aether_vector_fill_"));
    assert!(!LIBRARY.contains("A * transpose_view(A)"));
    assert!(!LIBRARY.contains("zerosMatrix"));
    assert!(!LIBRARY.contains("zerosRow"));
    assert!(!LIBRARY.contains("zerosColumn"));
    assert!(!LIBRARY.contains("onesMatrix"));
}

#[test]
fn absent_expected_type_is_ambiguous_and_mismatches_have_no_match() {
    let one_argument = diagnostics(
        "package consumer;import linearAlgebra as la;int main(){var value=la.zeros(3);return 0;}",
    );
    assert!(
        one_argument.contains("E0461 ambiguous overload"),
        "{one_argument}"
    );

    let two_arguments = diagnostics(
        "package consumer;import linearAlgebra as la;int main(){var value=la.zeros(3,2);return 0;}",
    );
    assert!(
        two_arguments.contains("E0461 ambiguous overload"),
        "{two_arguments}"
    );

    let wrong_argument = diagnostics(
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>value=la.zeros(true);return 0;}",
    );
    assert!(
        wrong_argument.contains("E0460 no matching overload"),
        "{wrong_argument}"
    );

    let wrong_result = diagnostics(
        "package consumer;import linearAlgebra as la;int main(){Matrix<int>value=la.ones(3);return 0;}",
    );
    assert!(
        wrong_result.contains("E0460 result type mismatch"),
        "{wrong_result}"
    );
}

#[test]
fn each_nonempty_constructor_allocates_once_and_zero_shapes_allocate_nothing() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>z=la.zeros(3,2);Matrix<float64>o=la.ones(2);Matrix<float64>z0=la.zeros(3,0);Matrix<float64>o0=la.ones(0,3);Vector<float64,Row>r=la.zeros(4);Vector<float64,Column>c=la.ones(0);Matrix<float64>i=la.identity(3);return int(rows(z)+rows(o)+rows(z0)+rows(o0)+dimension(r)+dimension(c)+rows(i)-15);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("allocations");
        let entry = directory.entry(source);
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        let guarded = compilation.llvm.replace(
            "  %process_status = trunc i64 %aether_result to i32",
            "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, 4\n  %free_ok = icmp eq i64 %frees, 4\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99",
        );
        assert_ne!(guarded, compilation.llvm);
        let executable = directory.0.join("allocation-check");
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&guarded, &executable)
            .unwrap();
        assert_eq!(
            Command::new(executable).status().unwrap().code(),
            Some(0),
            "{optimization:?}"
        );
    }
}
