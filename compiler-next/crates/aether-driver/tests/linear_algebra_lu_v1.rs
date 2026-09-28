//! LINEAR-ALGEBRA-LU-V1 package, lowering, and allocation qualification.

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
            "aether-linear-algebra-lu-{label}-{}-{}",
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

#[test]
fn lu_has_exactly_the_closed_public_surface() {
    assert_eq!(LIBRARY.matches("LU<float64> lu(").count(), 1);
    assert_eq!(LIBRARY.matches("LU<float32> lu(").count(), 1);
    assert!(!LIBRARY.contains("luPartial"));
    assert!(!LIBRARY.contains("permutationMatrix"));
    assert!(!LIBRARY.contains("permuteRows"));
    assert!(!LIBRARY.contains("singular;"));
}

#[test]
fn lu_lowers_as_ordinary_package_code_in_every_phase() {
    let directory = Directory::new("lowering");
    let entry = directory.entry(
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[0.0,2.0;3.0,4.0];la.LU<float64>x=la.lu(a);Matrix<float32>b=[float32(1.0)];la.LU<float32>y=la.lu(b);return x.permutationSign+y.permutationSign;}",
    );
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        assert!(dump.contains("MatrixRows"), "{phase:?}");
        assert!(dump.contains("MatrixColumns"), "{phase:?}");
        assert!(dump.contains("MatrixFilled"), "{phase:?}");
        assert!(dump.contains("VectorFilled"), "{phase:?}");
    }
    assert!(compilation.llvm.contains("@aether_matrix_index_fFloat64"));
    assert!(compilation.llvm.contains("@aether_matrix_index_fFloat32"));
    assert!(compilation.llvm.contains("@aether_matrix_fill_fFloat64"));
    assert!(compilation.llvm.contains("@aether_matrix_fill_fFloat32"));
    assert!(compilation.llvm.contains("@aether_vector_fill_iUsize"));
    assert!(!compilation.llvm.contains("aether_lu"));
}

#[test]
fn lu_allocates_only_input_permutation_and_one_additional_factor() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[0.0,2.0;3.0,4.0;5.0,6.0];la.LU<float64>f=la.lu(a);return int(rows(f.L)+rows(f.U)+dimension(f.permutation)-8);}";
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
            "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, 3\n  %free_ok = icmp eq i64 %frees, 3\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99",
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
