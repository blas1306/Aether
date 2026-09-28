//! LINEAR-ALGEBRA-GENERIC-DET-V1 package, diagnostics, lowering and ownership qualification.

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
            "aether-linear-algebra-det-{label}-{}-{}",
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
fn det_has_exactly_two_generic_declarations_and_delegates_once() {
    let det_start = LIBRARY
        .find("T det<T: IEEEFloat>(ref LU<T> factor)")
        .unwrap();
    let factor_end = LIBRARY.find("T det<T: IEEEFloat>(Matrix<T> A)").unwrap();
    let det_end = LIBRARY
        .find("Vector<T,Column> solve<T: IEEEFloat>(")
        .unwrap();
    let factor_implementation = &LIBRARY[det_start..factor_end];
    let det_implementation = &LIBRARY[det_start..det_end];
    assert_eq!(
        LIBRARY
            .matches("T det<T: IEEEFloat>(ref LU<T> factor)")
            .count(),
        1
    );
    assert_eq!(
        LIBRARY.matches("T det<T: IEEEFloat>(Matrix<T> A)").count(),
        1
    );
    assert_eq!(LIBRARY.matches(" det<").count(), 2);
    assert!(!LIBRARY.contains("float64 det("));
    assert!(!LIBRARY.contains("float32 det("));
    assert_eq!(
        det_implementation.matches("LU<T> factor = lu(A);").count(),
        1
    );
    assert_eq!(det_implementation.matches("lu(A)").count(), 1);
    assert!(det_implementation.contains("T result = 1;"));
    assert!(det_implementation.contains("result = -result;"));
    assert_eq!(factor_implementation.matches("shapeGuard(").count(), 4);
    let guards = [
        "shapeGuard(rows((*factor).L) == columns((*factor).L));",
        "shapeGuard(rows((*factor).U) == columns((*factor).U));",
        "shapeGuard(rows((*factor).L) == rows((*factor).U));",
        "shapeGuard(dimension((*factor).permutation) == rows((*factor).U));",
    ];
    let mut previous = 0;
    for guard in guards {
        let position = factor_implementation.find(guard).unwrap();
        assert!(position >= previous, "guard out of order: {guard}");
        previous = position;
    }
    assert!(factor_implementation.contains("result = result * (*factor).U[i,i];"));
    assert!(!det_implementation.contains("float32((*factor).permutationSign)"));
    assert!(!det_implementation.contains("float64((*factor).permutationSign)"));
    assert!(!LIBRARY.contains("determinant("));
    assert!(!LIBRARY.contains("detFloat32"));
    assert!(!LIBRARY.contains("aether_det"));
    assert!(!det_implementation.contains("MatrixView"));
    assert!(!det_implementation.contains("SingularMatrixException"));
    assert!(!det_implementation.contains("matrix_view"));
}

#[test]
fn det_reifies_capability_operations_before_mir_and_emits_concrete_instances() {
    let source = "package consumer;import linearAlgebra as la;T forward<T:IEEEFloat>(ref la.LU<T>f){return la.det(f);}int main(){Matrix<float64>a=[0.0,1.0;2.0,3.0];la.LU<float64>f=la.lu(a);float64 x=forward(f);Matrix<float32>b=[float32(-4.0)];float32 y=la.det(b);return int(x+float64(y)+6.0);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(dump.contains("ShapeGuard"), "{phase:?}");
            assert!(dump.contains("MatrixRows"), "{phase:?}");
            assert!(dump.contains("MatrixColumns"), "{phase:?}");
            assert!(!dump.contains("MatrixProduct"), "{phase:?}");
            assert!(!dump.contains("aether_det"), "{phase:?}");
        }
        let hir = &compilation.dumps[&Emit::Hir];
        for operation in [
            "AlgebraicValue",
            "capability: One",
            "CapabilityUnary",
            "operation: Negate",
            "CapabilityBinary",
            "behavior: Mul",
        ] {
            assert!(hir.contains(operation), "missing parametric {operation}");
        }
        for concrete_operation in ["NegateFloat", "MultiplyFloat"] {
            assert!(
                hir.contains(concrete_operation),
                "missing concrete HIR {concrete_operation}"
            );
        }
        for phase in [Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            for residue in [
                "AlgebraicValue",
                "CapabilityUnary",
                "CapabilityBinary",
                "GenericParam(",
                "witness",
                "vtable",
            ] {
                assert!(!dump.contains(residue), "{phase:?} contains {residue}");
            }
        }
        assert!(compilation.llvm.contains("@aether_matrix_index_fFloat64"));
        assert!(compilation.llvm.contains("@aether_matrix_index_fFloat32"));
        assert!(compilation.llvm.contains("fmul double"));
        assert!(compilation.llvm.contains("fmul float"));
        assert!(
            compilation
                .llvm
                .contains("linearAlgebra_f3_det__o13__gfFloat64"),
            "missing float64 det instance\n{}",
            compilation.llvm
        );
        assert!(
            compilation
                .llvm
                .contains("linearAlgebra_f3_det__o13__gfFloat32"),
            "missing float32 det instance\n{}",
            compilation.llvm
        );
        for residue in ["Capability", "GenericParam", "TypeId", "witness", "vtable"] {
            assert!(
                !compilation.llvm.contains(residue),
                "LLVM contains {residue}"
            );
        }
        assert!(!compilation.llvm.contains("aether_det"));
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn unsupported_element_view_and_result_types_are_e0460() {
    let rejected = [
        "package consumer;import linearAlgebra as la;int main(){Matrix<int>a=[1];int x=la.det(a);return x;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0];MatrixView<float64>v=matrix_view(a);float64 x=la.det(v);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0];float32 x=la.det(a);return 0;}",
    ];
    for source in rejected {
        let errors = diagnostics(source);
        assert!(errors.contains("E0460"), "{errors}");
        assert!(
            errors.contains("no matching overload") || errors.contains("result type mismatch"),
            "{errors}"
        );
    }
}

#[test]
fn matrix_is_consumed_while_factor_is_borrowed_and_reusable() {
    let moved = diagnostics(
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0];float64 d=la.det(a);return int(a[1,1]);}",
    );
    assert!(
        moved.contains("use after move of non-Copy local `a`"),
        "{moved}"
    );

    let borrowed = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[0.0,1.0;2.0,3.0];la.LU<float64>f=la.lu(a);float64 d1=la.det(f);Vector<float64,Column>b=[2.0,8.0];Vector<float64,Column>x=la.solve(f,b);float64 d2=la.det(f);if(abs(d1-d2)>1e-12||f.permutationSign!=-1||x[1]!=1.0||x[2]!=2.0){return 1;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(borrowed, optimization);
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn every_dynamic_shape_mismatch_reaches_shape_guard_before_accesses() {
    let cases = [
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0];float64 d=la.det(a);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Vector<usize,Column>p=[1];Matrix<float64>l=[1.0,0.0];Matrix<float64>u=[1.0];la.LU<float64>f=la.LU<float64>(p,1,l,u);float64 d=la.det(f);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0];la.LU<float64>f=la.lu(a);float64 d=la.det(f);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Vector<usize,Column>p=[1,2];Matrix<float64>l=[1.0];Matrix<float64>u=[1.0,0.0;0.0,1.0];la.LU<float64>f=la.LU<float64>(p,1,l,u);float64 d=la.det(f);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Vector<usize,Column>p=[];Matrix<float64>l=[1.0];Matrix<float64>u=[1.0];la.LU<float64>f=la.LU<float64>(p,1,l,u);float64 d=la.det(f);return 0;}",
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
fn determinant_from_factor_allocates_nothing_including_order_zero() {
    let cases = [
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[0.0,1.0;2.0,3.0];la.LU<float64>f=la.lu(a);float64 d=la.det(f);return int(d+2.0);}",
            3_i64,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=la.zeros(0,0);la.LU<float64>f=la.lu(a);float64 d=la.det(f);return int(d-1.0);}",
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
fn singular_and_negative_zero_follow_ieee_without_exception() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0;2.0,4.0];float64 singular=la.det(a);Matrix<float64>z=[-0.0];float64 negativeZero=la.det(z);if(singular!=0.0||negativeZero!=0.0||1.0/negativeZero!=-1.0/0.0){return 1;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }
}
