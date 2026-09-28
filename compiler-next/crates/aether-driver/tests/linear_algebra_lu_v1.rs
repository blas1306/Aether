//! LINEAR-ALGEBRA-GENERIC-LU-V1 package, lowering, diagnostics, and allocation qualification.

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
fn lu_has_exactly_one_ieee_float_source_kernel() {
    let lu_start = LIBRARY.find("LU<T> lu<T: IEEEFloat>(Matrix<T> A)").unwrap();
    let lu_end = LIBRARY.find("T det<T: IEEEFloat>(").unwrap();
    let lu_implementation = &LIBRARY[lu_start..lu_end];
    assert_eq!(
        LIBRARY
            .matches("LU<T> lu<T: IEEEFloat>(Matrix<T> A)")
            .count(),
        1
    );
    assert!(!LIBRARY.contains("LU<float64> lu("));
    assert!(!LIBRARY.contains("LU<float32> lu("));
    assert_eq!(lu_implementation.matches("T zero = 0;").count(), 1);
    assert_eq!(lu_implementation.matches("T one = 1;").count(), 1);
    assert!(!LIBRARY.contains("luPartial"));
    assert!(!LIBRARY.contains("permutationMatrix"));
    assert!(!LIBRARY.contains("permuteRows"));
    assert!(!LIBRARY.contains("singular;"));
}

#[test]
fn lu_lowers_as_ordinary_package_code_in_every_phase() {
    let directory = Directory::new("lowering");
    let entry = directory.entry(
        "package consumer;import linearAlgebra as la;la.LU<T> forward<T:IEEEFloat>(Matrix<T>a){return la.lu(a);}int main(){Matrix<float64>a=[0.0,2.0;3.0,4.0];var x=la.lu(a);Matrix<float32>b=[float32(1.0)];la.LU<float32>y=la.lu<float32>(b);Matrix<float64>c=[1.0];la.LU<float64>z=forward(c);return x.permutationSign+y.permutationSign+z.permutationSign;}",
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
    let hir = &compilation.dumps[&Emit::Hir];
    for capability_operation in [
        "AlgebraicValue",
        "CapabilityMath",
        "CapabilityCompare",
        "CapabilityBinary",
    ] {
        assert!(hir.contains(capability_operation), "{capability_operation}");
        for phase in [Emit::Mir, Emit::Ssa] {
            assert!(!compilation.dumps[&phase].contains(capability_operation));
        }
        assert!(!compilation.llvm.contains(capability_operation));
    }
    for exact_operation in [
        "capability: Zero",
        "capability: One",
        "operation: Abs",
        "operation: NotEqual",
        "operation: Greater",
        "behavior: Div",
        "behavior: Sub",
        "behavior: Mul",
    ] {
        assert!(hir.contains(exact_operation), "{exact_operation}");
    }
    for generic_residue in ["GenericParam(", "witness", "vtable"] {
        assert!(!compilation.dumps[&Emit::Mir].contains(generic_residue));
        assert!(!compilation.dumps[&Emit::Ssa].contains(generic_residue));
        assert!(!compilation.llvm.contains(generic_residue));
    }
    assert!(!compilation.llvm.contains("TypeId"));
    assert!(compilation.llvm.contains("@aether_matrix_index_fFloat64"));
    assert!(compilation.llvm.contains("@aether_matrix_index_fFloat32"));
    assert!(compilation.llvm.contains("@aether_matrix_fill_fFloat64"));
    assert!(compilation.llvm.contains("@aether_matrix_fill_fFloat32"));
    assert!(compilation.llvm.contains("@aether_vector_fill_iUsize"));
    assert!(compilation.llvm.contains("call double @fabs(double"));
    assert!(compilation.llvm.contains("call float @fabsf(float"));
    assert!(compilation.llvm.contains("linearAlgebra_f2_lu__gfFloat64"));
    assert!(compilation.llvm.contains("linearAlgebra_f2_lu__gfFloat32"));
    assert!(!compilation.llvm.contains("aether_lu"));
}

#[test]
fn lu_rejects_non_ieee_elements_through_the_general_constraint() {
    for source in [
        "package consumer;import linearAlgebra as la;int main(){Matrix<int>a=[1];var f=la.lu(a);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<int>a=[1];var f=la.lu<int>(a);return 0;}",
    ] {
        let output = diagnostics(source);
        assert!(output.contains("IEEEFloat"), "{source}: {output}");
        assert!(!output.contains("linearAlgebra only"), "{source}: {output}");
    }
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
