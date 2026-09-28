//! LINEAR-ALGEBRA-GENERIC-QR-V1 package, lowering, diagnostics, and allocation qualification.

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
            "aether-linear-algebra-qr-{label}-{}-{}",
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
fn qr_has_one_ieee_float_kernel_and_only_a_compatibility_wrapper() {
    let qr_start = LIBRARY.find("QR<T> qr<T: IEEEFloat>(Matrix<T> A)").unwrap();
    let wrapper_start = LIBRARY
        .find("QR<float32> qrFloat32(Matrix<float32> A)")
        .unwrap();
    let kernel = &LIBRARY[qr_start..wrapper_start];
    let wrapper = &LIBRARY[wrapper_start..];

    assert_eq!(
        LIBRARY
            .matches("QR<T> qr<T: IEEEFloat>(Matrix<T> A)")
            .count(),
        1
    );
    assert!(!LIBRARY.contains("QR<float64> qr(Matrix<float64> A)"));
    assert_eq!(kernel.matches("T zero = 0;").count(), 1);
    assert_eq!(kernel.matches("T one = 1;").count(), 1);
    assert_eq!(kernel.matches("T two = one + one;").count(), 1);
    assert_eq!(kernel.matches("identity<T>(m)").count(), 1);
    assert!(!kernel.contains("float32"));
    assert!(!kernel.contains("float64"));
    assert!(wrapper.contains("return qr(A);"));
    assert_eq!(wrapper.matches("while (").count(), 0);
}

#[test]
fn qr_lowers_as_parametric_package_code_and_concrete_float_instances() {
    let directory = Directory::new("lowering");
    let entry = directory.entry(
        "package consumer;import linearAlgebra as la;la.QR<T> forward<T:IEEEFloat>(Matrix<T>a){return la.qr(a);}int main(){Matrix<float64>a=[12.0,-51.0;6.0,167.0];var x=la.qr(a);Matrix<float32>b=[float32(1.0),float32(2.0);float32(3.0),float32(4.0)];la.QR<float32>y=la.qr<float32>(b);Matrix<float64>c=[1.0];la.QR<float64>z=forward(c);return int(rows(x.Q)+rows(y.Q)+rows(z.Q)-5);}",
    );
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    let hir = &compilation.dumps[&Emit::Hir];
    for capability_operation in [
        "AlgebraicValue",
        "CapabilityBinary",
        "CapabilityUnary",
        "CapabilityCompare",
        "CapabilityMath",
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
        "behavior: Add",
        "behavior: Sub",
        "behavior: Mul",
        "behavior: Div",
        "operation: Negate",
        "operation: NotEqual",
        "operation: Less",
        "operation: GreaterEqual",
        "operation: Abs",
        "operation: Sqrt",
    ] {
        assert!(hir.contains(exact_operation), "{exact_operation}");
    }
    for generic_residue in ["GenericParam(", "witness", "vtable"] {
        assert!(!compilation.dumps[&Emit::Mir].contains(generic_residue));
        assert!(!compilation.dumps[&Emit::Ssa].contains(generic_residue));
        assert!(!compilation.llvm.contains(generic_residue));
    }
    assert!(!compilation.llvm.contains("TypeId"));
    assert!(compilation.llvm.contains("call double @fabs(double"));
    assert!(compilation.llvm.contains("call float @fabsf(float"));
    assert!(compilation.llvm.contains("call double @sqrt(double"));
    assert!(compilation.llvm.contains("call float @sqrtf(float"));
    assert!(compilation.llvm.contains("linearAlgebra_f2_qr__gfFloat64"));
    assert!(compilation.llvm.contains("linearAlgebra_f2_qr__gfFloat32"));
}

#[test]
fn qr_rejects_non_ieee_elements_through_the_general_constraint() {
    for source in [
        "package consumer;import linearAlgebra as la;int main(){Matrix<int>a=[1];var f=la.qr(a);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<int>a=[1];var f=la.qr<int>(a);return 0;}",
    ] {
        let output = diagnostics(source);
        assert!(output.contains("IEEEFloat"), "{source}: {output}");
        assert!(!output.contains("linearAlgebra only"), "{source}: {output}");
    }
}

#[test]
fn qr_allocates_only_the_input_and_materialized_q() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0;3.0,4.0;5.0,6.0];la.QR<float64>f=la.qr(a);return int(rows(f.Q)+columns(f.R)-5);}";
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
            "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, 2\n  %free_ok = icmp eq i64 %frees, 2\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99",
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
