//! LINEAR-ALGEBRA-GENERIC-SOLVE-V1 matrix package qualification.

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
            "aether-linear-algebra-solve-matrix-{label}-{}-{}",
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

#[test]
fn solve_has_exactly_four_generic_overloads_and_one_matrix_kernel() {
    assert_eq!(LIBRARY.matches(" solve<T: IEEEFloat>(").count(), 4);
    assert_eq!(
        LIBRARY
            .matches("Vector<T,Column> solve<T: IEEEFloat>(")
            .count(),
        2
    );
    assert_eq!(LIBRARY.matches("Matrix<T> solve<T: IEEEFloat>(").count(), 2);
    assert!(!LIBRARY.contains("Matrix<float64> solve("));
    assert!(!LIBRARY.contains("Matrix<float32> solve("));

    let start = LIBRARY.find("Matrix<T> solve<T: IEEEFloat>(").unwrap();
    let end = LIBRARY.find("// A materialized QR factorization").unwrap();
    let implementation = &LIBRARY[start..end];
    assert_eq!(implementation.matches("LU<T> factor = lu(A);").count(), 1);
    assert_eq!(implementation.matches("lu(A)").count(), 1);
    assert_eq!(
        implementation
            .matches("Matrix<T> W = matrixFilled<T>(n, q, zero);")
            .count(),
        1
    );
    assert!(!implementation.contains("MatrixView"));
    assert!(!LIBRARY.contains("solveMatrix"));
    assert!(!LIBRARY.contains("aether_solve_matrix"));
    assert!(!LIBRARY.contains("permutationMatrix"));
}

#[test]
fn matrix_solve_lowers_as_ordinary_package_code_in_every_phase() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[0.0,1.0;2.0,3.0];la.LU<float64>f=la.lu(a);Matrix<float64>b=[2.0,1.0;8.0,5.0];Matrix<float64>x=la.solve(f,b);Matrix<float32>c=[float32(2.0)];Matrix<float32>d=[float32(6.0),float32(4.0)];Matrix<float32>y=la.solve(c,d);return int(x[1,1]+float64(y[1,1])-4.0);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(dump.contains("ShapeGuard"), "{phase:?}");
            assert!(dump.contains("MatrixFilled"), "{phase:?}");
        }
        assert!(compilation.llvm.contains("aether_matrix_fill_fFloat64"));
        assert!(compilation.llvm.contains("aether_matrix_fill_fFloat32"));
        assert!(!compilation.llvm.contains("aether_solve_matrix"));
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn unsupported_precision_element_and_rhs_view_types_are_e0460() {
    let rejected = [
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0];Matrix<float32>b=[float32(1.0)];Matrix<float64>x=la.solve(a,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<int>a=[1];Matrix<int>b=[1];Matrix<int>x=la.solve(a,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0];Matrix<float64>b=[1.0];MatrixView<float64>v=matrix_view(b);Matrix<float64>x=la.solve(a,v);return 0;}",
    ];
    for source in rejected {
        let errors = diagnostics(source);
        assert!(errors.contains("E0460"), "{errors}");
        assert!(errors.contains("no matching overload"), "{errors}");
    }
}

#[test]
fn coefficient_matrix_is_consumed_and_factor_and_matrix_rhs_are_borrowed() {
    let moved = diagnostics(
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0];Matrix<float64>b=[2.0];Matrix<float64>x=la.solve(a,b);return int(a[1,1]);}",
    );
    assert!(
        moved.contains("use after move of non-Copy local `a`"),
        "{moved}"
    );

    let borrowed = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[2.0];la.LU<float64>f=la.lu(a);Matrix<float64>b=[6.0,4.0];Matrix<float64>x=la.solve(f,b);Matrix<float64>y=la.solve(f,b);Vector<float64,Column>v=[8.0];Vector<float64,Column>z=la.solve(f,v);return int(x[1,1]+y[1,2]+z[1]+b[1,1]+f.U[1,1]-17.0);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(borrowed, optimization);
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn all_matrix_and_lu_shape_mismatches_precede_allocation_and_access() {
    let cases = [
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0];Matrix<float64>b=[1.0];Matrix<float64>x=la.solve(a,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,0.0;0.0,1.0];Matrix<float64>b=[1.0];Matrix<float64>x=la.solve(a,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Vector<usize,Column>p=[1];Matrix<float64>l=[1.0,0.0];Matrix<float64>u=[1.0];la.LU<float64>f=la.LU<float64>(p,1,l,u);Matrix<float64>b=[1.0];Matrix<float64>x=la.solve(f,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Vector<usize,Column>p=[1];Matrix<float64>l=[1.0];Matrix<float64>u=[1.0,0.0];la.LU<float64>f=la.LU<float64>(p,1,l,u);Matrix<float64>b=[1.0];Matrix<float64>x=la.solve(f,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Vector<usize,Column>p=[1];Matrix<float64>l=[1.0];Matrix<float64>u=[1.0,0.0;0.0,1.0];la.LU<float64>f=la.LU<float64>(p,1,l,u);Matrix<float64>b=[1.0;2.0];Matrix<float64>x=la.solve(f,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Vector<usize,Column>p=[];Matrix<float64>l=[1.0];Matrix<float64>u=[1.0];la.LU<float64>f=la.LU<float64>(p,1,l,u);Matrix<float64>b=[1.0];Matrix<float64>x=la.solve(f,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Vector<usize,Column>p=[1];Matrix<float64>l=[1.0];Matrix<float64>u=[0.0];la.LU<float64>f=la.LU<float64>(p,1,l,u);Matrix<float64>b=la.zeros(0,0);Matrix<float64>x=la.solve(f,b);return 0;}",
    ];
    for source in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization);
            let instrumented = compilation.llvm.replace(
                "trap_shape_mismatch:\n  ; structured Aether trap: ShapeMismatch\n  call void @llvm.trap()",
                "trap_shape_mismatch:\n  call void @exit(i32 73)",
            ) + "\ndeclare void @exit(i32)\n";
            assert_eq!(status_llvm(&instrumented, optimization).code(), Some(73));
        }
    }
}

#[test]
fn factor_solve_has_one_result_allocation_and_zero_extent_results_have_none() {
    let cases = [
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[0.0,1.0;2.0,3.0];la.LU<float64>f=la.lu(a);Matrix<float64>b=[2.0,1.0;8.0,5.0];Matrix<float64>x=la.solve(f,b);return int(x[1,1]+x[2,1]-3.0);}",
            5_i64,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[2.0,0.0;0.0,3.0];la.LU<float64>f=la.lu(a);Matrix<float64>b=la.zeros(2,0);Matrix<float64>x=la.solve(f,b);return int(rows(x)+columns(x)-2);}",
            3_i64,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=la.zeros(0,0);la.LU<float64>f=la.lu(a);Matrix<float64>b=la.zeros(0,4);Matrix<float64>x=la.solve(f,b);return int(rows(x)+columns(x)-4);}",
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
fn singularity_is_checked_for_empty_rhs_and_unwind_preserves_borrowed_inputs() {
    let sources = [
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0;2.0,4.0];la.LU<float64>f=la.lu(a);Matrix<float64>b=[3.0,1.0;6.0,2.0];int caught=0;try{Matrix<float64>x=la.solve(f,b);}catch(la.SingularMatrixException e){caught=1;}if(caught!=1||b[1,1]!=3.0||f.permutation[1]!=2){return 1;}try{Matrix<float64>y=la.solve(f,b);}catch(la.SingularMatrixException e){caught=caught+1;}return caught-2;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0;2.0,4.0];la.LU<float64>f=la.lu(a);Matrix<float64>b=la.zeros(2,0);int caught=0;try{Matrix<float64>x=la.solve(f,b);}catch(la.SingularMatrixException e){caught=1;}return caught-1+int(rows(b)-2)+int(columns(b));}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0;2.0,4.0];Matrix<float64>b=[3.0,1.0;6.0,2.0];int caught=0;try{Matrix<float64>x=la.solve(a,b);}catch(la.SingularMatrixException e){caught=1;}return caught-1+int(b[1,1]-3.0);}",
    ];
    for source in sources {
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
