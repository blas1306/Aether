//! LINEAR-ALGEBRA-SOLVE-V1 package, diagnostics, lowering and ownership qualification.

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
            "aether-linear-algebra-solve-{label}-{}-{}",
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
fn solve_has_exactly_the_closed_public_surface_and_one_kernel_per_precision() {
    let solve_start = LIBRARY.find("Vector<float64,Column> solve(").unwrap();
    let solve_end = LIBRARY.find("Matrix<float64> solve(").unwrap();
    let solve_implementation = &LIBRARY[solve_start..solve_end];
    assert_eq!(LIBRARY.matches("Vector<float64,Column> solve(").count(), 2);
    assert_eq!(LIBRARY.matches("Vector<float32,Column> solve(").count(), 2);
    assert_eq!(
        LIBRARY
            .matches("public class SingularMatrixException : Exception")
            .count(),
        1
    );
    assert_eq!(
        solve_implementation
            .matches("LU<float64> factor = lu(A);")
            .count(),
        1
    );
    assert_eq!(
        solve_implementation
            .matches("LU<float32> factor = lu(A);")
            .count(),
        1
    );
    assert!(!LIBRARY.contains("solveFloat32"));
    assert!(!LIBRARY.contains("solveLU"));
    assert!(!LIBRARY.contains("aether_solve"));
    assert!(!LIBRARY.contains("permutationMatrix"));
}

#[test]
fn solve_lowers_as_ordinary_borrowing_package_code_in_every_phase() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[0.0,1.0;2.0,3.0];la.LU<float64>f=la.lu(a);Vector<float64,Column>b=[2.0,8.0];Vector<float64,Column>x=la.solve(f,b);Matrix<float32>c=[float32(2.0)];Vector<float32,Column>d=[float32(6.0)];Vector<float32,Column>y=la.solve(c,d);return int(x[1]+float64(y[1])-4.0);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(dump.contains("ShapeGuard"), "{phase:?}");
            assert!(dump.contains("VectorFilled"), "{phase:?}");
        }
        assert!(compilation.llvm.contains("aether_vector_fill_fFloat64"));
        assert!(compilation.llvm.contains("aether_vector_fill_fFloat32"));
        assert!(!compilation.llvm.contains("aether_solve"));
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn unsupported_rhs_orientation_precision_and_element_types_are_e0460() {
    let rejected = [
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0];Vector<float64,Row>b=[1.0];Vector<float64,Column>x=la.solve(a,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0];Vector<float32,Column>b=[float32(1.0)];Vector<float64,Column>x=la.solve(a,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<int>a=[1];Vector<int,Column>b=[1];Vector<int,Column>x=la.solve(a,b);return 0;}",
    ];
    for source in rejected {
        let errors = diagnostics(source);
        assert!(errors.contains("E0460 no matching overload"), "{errors}");
    }
}

#[test]
fn matrix_is_consumed_while_factor_and_rhs_are_only_borrowed() {
    let moved = diagnostics(
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0];Vector<float64,Column>b=[2.0];Vector<float64,Column>x=la.solve(a,b);return int(a[1,1]);}",
    );
    assert!(
        moved.contains("use after move of non-Copy local `a`"),
        "{moved}"
    );

    let borrowed = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[2.0];la.LU<float64>f=la.lu(a);Vector<float64,Column>b=[6.0];Vector<float64,Column>x=la.solve(f,b);return int(x[1]+b[1]+f.U[1,1]-11.0);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(borrowed, optimization);
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn every_dynamic_shape_mismatch_reaches_shape_guard_before_later_work() {
    let cases = [
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0];Vector<float64,Column>b=[1.0];Vector<float64,Column>x=la.solve(a,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,0.0;0.0,1.0];Vector<float64,Column>b=[1.0];Vector<float64,Column>x=la.solve(a,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0];la.LU<float64>f=la.lu(a);Vector<float64,Column>b=[1.0];Vector<float64,Column>x=la.solve(f,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Vector<usize,Column>p=[1];Matrix<float64>l=[1.0];Matrix<float64>u=[1.0];la.LU<float64>f=la.LU<float64>(p,1,l,u);Vector<float64,Column>b=[];Vector<float64,Column>x=la.solve(f,b);return 0;}",
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
fn factor_solve_allocates_only_its_result_and_empty_solve_allocates_nothing() {
    let nonempty = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[0.0,1.0;2.0,3.0];la.LU<float64>f=la.lu(a);Vector<float64,Column>b=[2.0,8.0];Vector<float64,Column>x=la.solve(f,b);return int(x[1]+x[2]-3.0);}";
    let empty = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=la.zeros(0,0);la.LU<float64>f=la.lu(a);Vector<float64,Column>b=la.zeros(0);Vector<float64,Column>x=la.solve(f,b);return int(dimension(x));}";
    for (source, expected) in [(nonempty, 5_i64), (empty, 0_i64)] {
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
fn singularity_is_a_catchable_exception_and_borrowed_inputs_survive_unwind() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0;2.0,4.0];la.LU<float64>f=la.lu(a);Vector<float64,Column>b=[3.0,7.0];int caught=0;try{Vector<float64,Column>x=la.solve(f,b);}catch(la.SingularMatrixException e){caught=1;}if(caught!=1||b[1]!=3.0||f.permutation[1]!=2){return 1;}Vector<float64,Column>b2=[1.0,0.0];try{Vector<float64,Column>y=la.solve(f,b2);}catch(la.SingularMatrixException e){caught=caught+1;}return caught-2;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert!(compilation.dumps[&Emit::Mir].contains("Unwind"));
        assert!(compilation.llvm.contains("resume { ptr, i32 }"));
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn singular_unwind_cleans_workspace_and_direct_solve_temporary_factor() {
    let cases = [
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0;2.0,4.0];la.LU<float64>f=la.lu(a);Vector<float64,Column>b=[3.0,6.0];int caught=0;try{Vector<float64,Column>x=la.solve(f,b);}catch(la.SingularMatrixException e){caught=1;}return caught-1;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0;2.0,4.0];Vector<float64,Column>b=[3.0,7.0];int caught=0;try{Vector<float64,Column>x=la.solve(a,b);}catch(la.SingularMatrixException e){caught=1;}return caught-1+int(b[1]-3.0);}",
    ];
    for source in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization);
            let guarded = compilation.llvm.replace(
                "  %process_status = trunc i64 %aether_result to i32",
                "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %heap_ok = icmp eq i64 %allocs, %frees\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99",
            );
            assert_ne!(guarded, compilation.llvm);
            assert_eq!(status_llvm(&guarded, optimization).code(), Some(0));
        }
    }
}
