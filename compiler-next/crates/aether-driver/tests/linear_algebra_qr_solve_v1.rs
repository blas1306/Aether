//! LINEAR-ALGEBRA-QR-SOLVE-V1 source, lowering, IEEE, shape, and numerical qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session_with_optimization,
};

const LIBRARY: &str = include_str!("../../../../linearAlgebra/src/lib.ae");

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-linear-algebra-qr-solve-{label}-{}-{}",
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

fn status(llvm: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    let directory = Directory::new("native");
    let executable = directory.0.join("program");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &executable)
        .unwrap_or_else(|error| panic!("{error:#?}\n{llvm}"));
    Command::new(executable).status().unwrap()
}

fn allocation_guard(llvm: &str, expected: i64) -> String {
    let guarded = llvm.replace(
        "  %process_status = trunc i64 %aether_result to i32",
        &format!(
            "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, {expected}\n  %free_ok = icmp eq i64 %frees, {expected}\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99"
        ),
    );
    assert_ne!(guarded, llvm);
    guarded
}

#[test]
fn api_guards_scan_workspace_and_loop_order_are_literal() {
    assert_eq!(
        LIBRARY
            .matches("public class RankDeficientMatrixException : Exception")
            .count(),
        1
    );
    assert_eq!(LIBRARY.matches(" solve<T: IEEEFloat>(").count(), 8);

    let vector_start = LIBRARY
        .find("// Solve the square or tall full-column-rank system")
        .unwrap();
    let matrix_start = LIBRARY
        .find("// Solve one or more square or tall full-column-rank")
        .unwrap();
    let end = LIBRARY.find("// Householder QR").unwrap();
    let vector = &LIBRARY[vector_start..matrix_start];
    let matrix = &LIBRARY[matrix_start..end];

    for body in [vector, matrix] {
        let q_square = body
            .find("shapeGuard(rows((*factor).Q) == columns((*factor).Q));")
            .unwrap();
        let r_rows = body
            .find("shapeGuard(rows((*factor).R) == rows((*factor).Q));")
            .unwrap();
        let tall = body
            .find("shapeGuard(rows((*factor).R) >= columns((*factor).R));")
            .unwrap();
        let scan = body.find("if ((*factor).R[i,i] == zero)").unwrap();
        assert!(q_square < r_rows && r_rows < tall && tall < scan);
        assert_eq!(
            body.matches("throw RankDeficientMatrixException();")
                .count(),
            1
        );
        assert!(!body.contains("transpose"));
        assert!(!body.contains("leastSquares"));
    }

    let vector_rhs = vector
        .find("shapeGuard(dimension(*b) == rows((*factor).Q));")
        .unwrap();
    let vector_m = vector.find("usize m = rows((*factor).Q);").unwrap();
    let vector_scan = vector.find("if ((*factor).R[i,i] == zero)").unwrap();
    let vector_alloc = vector.find("vectorFilled<T,Column>(n, zero)").unwrap();
    assert!(vector_rhs < vector_m && vector_m < vector_scan && vector_scan < vector_alloc);
    assert_eq!(vector.matches("vectorFilled<").count(), 1);
    assert!(vector.contains("T product = (*factor).Q[k,i] * (*b)[k];"));
    assert!(vector.contains("T product = (*factor).R[i,j] * w[j];"));

    let matrix_rhs = matrix
        .find("shapeGuard(rows(*B) == rows((*factor).Q));")
        .unwrap();
    let matrix_m = matrix.find("usize m = rows((*factor).Q);").unwrap();
    let matrix_q = matrix.find("usize q = columns(*B);").unwrap();
    let matrix_scan = matrix.find("if ((*factor).R[i,i] == zero)").unwrap();
    let matrix_alloc = matrix.find("matrixFilled<T>(n, q, zero)").unwrap();
    assert!(
        matrix_rhs < matrix_m
            && matrix_m < matrix_q
            && matrix_q < matrix_scan
            && matrix_scan < matrix_alloc
    );
    assert_eq!(matrix.matches("matrixFilled<").count(), 1);
    assert!(!matrix.contains("Vector<"));
    assert!(matrix.contains("T product = (*factor).Q[k,i] * (*B)[k,c];"));
    assert!(matrix.contains("T product = (*factor).R[i,j] * W[j,c];"));
}

#[test]
fn square_tall_matrix_and_both_precisions_solve_correctly() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[3.0,1.0;1.0,2.0];la.QR<float64>f=la.qr(a);Vector<float64,Column>b=[5.0,5.0];Vector<float64,Column>x=la.solve(f,b);Matrix<float64>B=[5.0,2.0;5.0,4.0];Matrix<float64>X=la.solve(f,B);if(abs(x[1]-1.0)>1e-11||abs(x[2]-2.0)>1e-11||abs(X[1,1]-x[1])>1e-11||abs(X[2,2]-2.0)>1e-11){return 1;}Matrix<float64>t=[1.0,0.0;0.0,1.0;1.0,1.0];la.QR<float64>g=la.qr(t);Vector<float64,Column>c=[1.0,2.0,4.0];Vector<float64,Column>y=la.solve(g,c);if(abs(y[1]-4.0/3.0)>1e-11||abs(y[2]-7.0/3.0)>1e-11){return 2;}Matrix<float32>s=[float32(2.0)];la.QR<float32>h=la.qr(s);Vector<float32,Column>d=[float32(8.0)];Vector<float32,Column>z=la.solve<float32>(h,d);if(abs(z[1]-float32(4.0))>float32(2e-5)){return 3;}if(b[1]!=5.0||B[2,2]!=4.0||f.R[1,1]==0.0){return 4;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(status(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn exact_zero_rank_policy_runs_for_empty_matrix_rhs() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>q=[1.0,0.0;0.0,1.0];Matrix<float64>r=[1.0,2.0;0.0,-0.0];la.QR<float64>f=la.QR<float64>(q,r);Matrix<float64>b=la.zeros(2,0);int caught=0;try{Matrix<float64>x=la.solve(f,b);}catch(la.RankDeficientMatrixException e){caught=1;}if(caught!=1||rows(b)!=2||columns(b)!=0){return 1;}Matrix<float64>rn=[0.0/0.0];Matrix<float64>qn=[1.0];la.QR<float64>n=la.QR<float64>(qn,rn);Vector<float64,Column>v=[1.0];Vector<float64,Column>w=la.solve(n,v);if(w[1]==w[1]){return 2;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(status(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn zero_shapes_preserve_both_matrix_extents() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>q=la.zeros(0,0);Matrix<float64>r=la.zeros(0,0);la.QR<float64>f=la.QR<float64>(q,r);Vector<float64,Column>b=la.zeros(0);Vector<float64,Column>x=la.solve(f,b);Matrix<float64>B=la.zeros(0,3);Matrix<float64>X=la.solve(f,B);Matrix<float64>q2=[1.0,0.0;0.0,1.0];Matrix<float64>r2=la.zeros(2,0);la.QR<float64>g=la.QR<float64>(q2,r2);Vector<float64,Column>c=[1.0,2.0];Vector<float64,Column>y=la.solve(g,c);Matrix<float64>C=la.zeros(2,4);Matrix<float64>Y=la.solve(g,C);if(dimension(x)!=0||rows(X)!=0||columns(X)!=3||dimension(y)!=0||rows(Y)!=0||columns(Y)!=4){return 1;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(status(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn result_has_exactly_one_backing_only_when_nonempty() {
    let cases = [
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>q=[1.0,0.0;0.0,1.0];Matrix<float64>r=[2.0,0.0;0.0,4.0];la.QR<float64>f=la.QR<float64>(q,r);Vector<float64,Column>b=[4.0,8.0];Vector<float64,Column>x=la.solve(f,b);return int(x[1]+x[2]-4.0);}",
            4,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>q=[1.0,0.0;0.0,1.0];Matrix<float64>r=[2.0,0.0;0.0,4.0];la.QR<float64>f=la.QR<float64>(q,r);Matrix<float64>b=[4.0;8.0];Matrix<float64>x=la.solve(f,b);return int(x[1,1]+x[2,1]-4.0);}",
            4,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>q=la.zeros(0,0);Matrix<float64>r=la.zeros(0,0);la.QR<float64>f=la.QR<float64>(q,r);Matrix<float64>b=la.zeros(0,3);Matrix<float64>x=la.solve(f,b);return int(rows(x)+columns(x)-3);}",
            0,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>q=[1.0,0.0;0.0,1.0];Matrix<float64>r=la.zeros(2,0);la.QR<float64>f=la.QR<float64>(q,r);Matrix<float64>b=la.zeros(2,4);Matrix<float64>x=la.solve(f,b);return int(rows(x)+columns(x)-4);}",
            2,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>q=[1.0,0.0;0.0,1.0];Matrix<float64>r=[2.0,0.0;0.0,4.0];la.QR<float64>f=la.QR<float64>(q,r);Matrix<float64>b=la.zeros(2,0);Matrix<float64>x=la.solve(f,b);return int(rows(x)+columns(x)-2);}",
            2,
        ),
    ];
    for (source, expected) in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization);
            assert_eq!(
                status(&allocation_guard(&compilation.llvm, expected), optimization).code(),
                Some(0),
                "expected {expected} allocations for {source} at {optimization:?}"
            );
        }
    }
}

#[test]
fn generic_lowering_is_concrete_and_has_no_transpose_or_dispatch() {
    let source = "package consumer;import linearAlgebra as la;Vector<T,Column>s<T:IEEEFloat>(ref la.QR<T>f,ref Vector<T,Column>b){return la.solve(f,b);}int main(){Matrix<float64>q=[1.0];Matrix<float64>r=[2.0];la.QR<float64>f=la.QR<float64>(q,r);Vector<float64,Column>b=[4.0];Vector<float64,Column>x=s(f,b);return int(x[1]-2.0);}";
    let compilation = compile(source, OptimizationLevel::O0);
    let hir = &compilation.dumps[&Emit::Hir];
    for operation in [
        "ShapeGuard",
        "capability: Zero",
        "operation: Equal",
        "behavior: Add",
        "behavior: Mul",
        "behavior: Sub",
        "behavior: Div",
    ] {
        assert!(hir.contains(operation), "HIR missing {operation}");
    }
    for phase in [Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        for residue in [
            "GenericParam(",
            "CapabilityBinary",
            "Transpose",
            "witness",
            "vtable",
        ] {
            assert!(!dump.contains(residue), "{phase:?} contains {residue}");
        }
    }
    for residue in ["fast-math", "TypeId", "aether_qr_solve"] {
        assert!(
            !compilation.llvm.contains(residue),
            "LLVM contains {residue}"
        );
    }
    assert_eq!(
        status(&compilation.llvm, OptimizationLevel::O0).code(),
        Some(0)
    );
}
