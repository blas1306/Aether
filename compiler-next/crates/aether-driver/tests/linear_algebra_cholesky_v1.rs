//! LINEAR-ALGEBRA-CHOLESKY-V1 package, domain, lowering, ownership, and allocation qualification.

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
            "aether-linear-algebra-cholesky-{label}-{}-{}",
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

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    let directory = Directory::new("compile");
    let entry = directory.entry(source);
    compile_session_with_optimization(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
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

fn status_llvm(llvm: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    let directory = Directory::new("native");
    let executable = directory.0.join("program");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &executable)
        .unwrap_or_else(|error| panic!("{error:#?}\n{llvm}"));
    Command::new(executable).status().unwrap()
}

fn run_both(source: &str) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(
            status_llvm(&compilation.llvm, optimization).code(),
            Some(0),
            "{optimization:?}: {source}"
        );
    }
}

#[test]
fn public_surface_and_kernel_structure_are_exact() {
    let start = LIBRARY
        .find("Cholesky<T> choleskyInPlace<T: IEEEFloat>(Matrix<T> A)")
        .unwrap();
    let end = LIBRARY[start..].find("// A materialized QR").unwrap() + start;
    let kernel = &LIBRARY[start..end];

    assert_eq!(
        LIBRARY
            .matches("Cholesky<T> choleskyInPlace<T: IEEEFloat>(Matrix<T> A)")
            .count(),
        1
    );
    assert!(LIBRARY.contains("struct Cholesky<T: Storable> {\n    Matrix<T> L;\n}"));
    assert_eq!(
        LIBRARY
            .matches("public class NotSymmetricMatrixException : Exception")
            .count(),
        1
    );
    assert_eq!(
        LIBRARY
            .matches("public class NotPositiveDefiniteException : Exception")
            .count(),
        1
    );
    assert!(kernel.starts_with(
        "Cholesky<T> choleskyInPlace<T: IEEEFloat>(Matrix<T> A) {\n    shapeGuard(rows(A) == columns(A));"
    ));
    assert!(kernel.contains("value = value - A[i,k] * A[j,k];"));
    assert!(kernel.contains("if (!((value - value) == zero) || !(value > zero))"));
    assert!(kernel.contains("A[i,i] = sqrt(value);"));
    assert!(kernel.contains("A[i,j] = value / A[j,j];"));
    assert!(kernel.contains("A[i,j] = zero;"));
    assert!(kernel.contains("return Cholesky<T>(A);"));
    for forbidden in [
        "float32",
        "float64",
        "Matrix<T> L =",
        "Vector<",
        "transpose",
        "matrix_view",
        "abs(",
        "epsilon",
        "tolerance",
    ] {
        assert!(!kernel.contains(forbidden), "kernel contains {forbidden}");
    }
}

#[test]
fn cholesky_reifies_only_ordinary_capability_operations() {
    let source = "package consumer;import linearAlgebra as la;la.Cholesky<T> forward<T:IEEEFloat>(Matrix<T>a){return la.cholesky(a);}int main(){Matrix<float64>a=[4.0,2.0;2.0,5.0];var x=la.cholesky(a);Matrix<float32>b=[float32(4.0),float32(2.0);float32(2.0),float32(5.0)];la.Cholesky<float32>y=la.cholesky<float32>(b);Matrix<float64>c=[9.0];la.Cholesky<float64>z=forward(c);return int(x.L[1,1]+float64(y.L[1,1])+z.L[1,1]-7.0);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let hir = &compilation.dumps[&Emit::Hir];
        for operation in [
            "capability: Zero",
            "behavior: Sub",
            "behavior: Mul",
            "behavior: Div",
            "operation: Equal",
            "operation: Greater",
            "operation: Sqrt",
        ] {
            assert!(hir.contains(operation), "missing {operation}");
        }
        for phase in [Emit::Mir, Emit::Ssa] {
            for residue in [
                "AlgebraicValue",
                "CapabilityBinary",
                "CapabilityCompare",
                "CapabilityMath",
                "GenericParam(",
                "witness",
                "vtable",
            ] {
                assert!(!compilation.dumps[&phase].contains(residue));
            }
        }
        for residue in ["TypeId", "witness", "vtable", "aether_cholesky"] {
            assert!(!compilation.llvm.contains(residue));
        }
        assert!(compilation.llvm.contains("call double @sqrt(double"));
        assert!(compilation.llvm.contains("call float @sqrtf(float"));
        assert!(compilation.llvm.contains("cholesky__gfFloat64"));
        assert!(compilation.llvm.contains("cholesky__gfFloat32"));
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn non_ieee_elements_are_rejected_and_the_in_place_input_is_consumed() {
    for source in [
        "package consumer;import linearAlgebra as la;int main(){Matrix<int>a=[1];var f=la.cholesky(a);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<int>a=[1];var f=la.cholesky<int>(a);return 0;}",
    ] {
        let output = diagnostics(source);
        assert!(output.contains("IEEEFloat"), "{output}");
    }
    let moved = diagnostics(
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0];var f=la.choleskyInPlace(a);return int(a[1,1]);}",
    );
    assert!(
        moved.contains("use after move of non-Copy local `a`"),
        "{moved}"
    );
}

#[test]
fn valid_zero_subnormal_and_signed_zero_symmetry_cases_succeed() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>e=la.zeros(0,0);var ef=la.cholesky(e);if(rows(ef.L)!=0||columns(ef.L)!=0){return 1;}Matrix<float64>s=[5e-324];var sf=la.cholesky(s);if(!(sf.L[1,1]>0.0)||!((sf.L[1,1]-sf.L[1,1])==0.0)){return 2;}Matrix<float64>z=[4.0,0.0;-0.0,9.0];var zf=la.cholesky(z);if(zf.L[1,2]!=0.0||1.0/zf.L[1,2]!=1.0/0.0){return 3;}Matrix<float32>s32=[float32(1e-45)];var sf32=la.cholesky(s32);if(!(sf32.L[1,1]>float32(0.0))){return 4;}return 0;}";
    run_both(source);
}

#[test]
fn every_nominal_invalid_domain_case_throws_the_exact_exception() {
    let positive_definite_failures = [
        "[1.0,1.0;1.0,1.0]",
        "[1.0,2.0;2.0,4.0]",
        "[1.0,2.0;2.0,1.0]",
        "[-1.0]",
        "[0.0]",
        "[-0.0]",
        "[-5e-324]",
        "[0.0/0.0]",
        "[1.0/0.0]",
        "[-1.0/0.0]",
        "[2.0,0.0/0.0;0.0/0.0,2.0]",
        "[2.0,1.0/0.0;1.0/0.0,2.0]",
        "[2.0,-1.0/0.0;-1.0/0.0,2.0]",
        "[5e-324,1e308;1e308,1e308]",
    ];
    for matrix in positive_definite_failures {
        let source = format!(
            "package consumer;import linearAlgebra as la;int main(){{Matrix<float64>a={matrix};int caught=0;try{{var f=la.cholesky(a);}}catch(la.NotPositiveDefiniteException e){{caught=1;}}return caught-1;}}"
        );
        run_both(&source);
    }

    for matrix in ["[2.0,1.0;0.0,2.0]", "[2.0,1.0000000000000002;1.0,2.0]"] {
        let source = format!(
            "package consumer;import linearAlgebra as la;int main(){{Matrix<float64>a={matrix};int caught=0;try{{var f=la.cholesky(a);}}catch(la.NotSymmetricMatrixException e){{caught=1;}}return caught-1;}}"
        );
        run_both(&source);
    }
    run_both(
        "package consumer;import linearAlgebra as la;int main(){Matrix<float32>a=[float32(2.0),float32(1.0000001);float32(1.0),float32(2.0)];int caught=0;try{var f=la.cholesky(a);}catch(la.NotSymmetricMatrixException e){caught=1;}return caught-1;}",
    );
}

#[test]
fn validation_precedence_is_shape_then_nonfinite_then_asymmetry_then_pivot() {
    let cases = [
        (
            "Matrix<float64>a=[1.0,9.0;8.0,0.0/0.0];",
            "la.NotPositiveDefiniteException",
        ),
        (
            "Matrix<float64>a=[1.0,1.0/0.0;8.0,2.0];",
            "la.NotPositiveDefiniteException",
        ),
        (
            "Matrix<float64>a=[2.0,1.0,0.0;0.0,2.0,0.0;0.0,0.0,0.0/0.0];",
            "la.NotSymmetricMatrixException",
        ),
        (
            "Matrix<float64>a=[1.0,2.0;2.0,1.0];",
            "la.NotPositiveDefiniteException",
        ),
    ];
    for (declaration, exception) in cases {
        let source = format!(
            "package consumer;import linearAlgebra as la;int main(){{{declaration}int caught=0;try{{var f=la.cholesky(a);}}catch({exception} e){{caught=1;}}return caught-1;}}"
        );
        run_both(&source);
    }
}

#[test]
fn rectangular_shapes_including_zero_extents_trap_as_shape_mismatch() {
    let cases = [
        "Matrix<float64>a=[1.0,2.0];",
        "Vector<float64,Column>c=[];Vector<float64,Row>r=[1.0,2.0];Matrix<float64>a=c*r;",
        "Vector<float64,Column>c=[1.0,2.0];Vector<float64,Row>r=[];Matrix<float64>a=c*r;",
    ];
    for declaration in cases {
        let source = format!(
            "package consumer;import linearAlgebra as la;int main(){{{declaration}var f=la.cholesky(a);return 0;}}"
        );
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(&source, optimization);
            let instrumented = compilation.llvm.replace(
                "trap_shape_mismatch:\n  ; structured Aether trap: ShapeMismatch\n  call void @llvm.trap()",
                "trap_shape_mismatch:\n  call void @exit(i32 73)",
            ) + "\ndeclare void @exit(i32)\n";
            assert_eq!(status_llvm(&instrumented, optimization).code(), Some(73));
        }
    }
}

#[test]
fn success_reuses_the_input_backing_and_zero_shape_allocates_nothing() {
    let cases = [
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[4.0,2.0;2.0,5.0];var f=la.choleskyInPlace(a);return int(f.L[1,1]-2.0);}",
            1_i64,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=la.zeros(0,0);var f=la.choleskyInPlace(a);return int(rows(f.L)+columns(f.L));}",
            0_i64,
        ),
    ];
    for (source, expected) in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization);
            let guarded = compilation.llvm.replace(
                "  %process_status = trunc i64 %aether_result to i32",
                &format!(
                    "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, {expected}\n  %free_ok = icmp eq i64 %frees, {expected}\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99"
                ),
            );
            assert_ne!(guarded, compilation.llvm);
            assert_eq!(status_llvm(&guarded, optimization).code(), Some(0));
        }
    }
}

#[test]
fn both_exception_paths_unwind_without_leak_or_double_drop() {
    for source in [
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[2.0,1.0;0.0,2.0];int caught=0;try{var f=la.cholesky(a);}catch(la.NotSymmetricMatrixException e){caught=1;}return caught-1;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0;2.0,1.0];int caught=0;try{var f=la.cholesky(a);}catch(la.NotPositiveDefiniteException e){caught=1;}return caught-1;}",
    ] {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization);
            assert!(compilation.dumps[&Emit::Mir].contains("Unwind"));
            let guarded = compilation.llvm.replace(
                "  %process_status = trunc i64 %aether_result to i32",
                "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %heap_ok = icmp eq i64 %allocs, %frees\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99",
            );
            assert_ne!(guarded, compilation.llvm);
            assert_eq!(status_llvm(&guarded, optimization).code(), Some(0));
        }
    }
}
