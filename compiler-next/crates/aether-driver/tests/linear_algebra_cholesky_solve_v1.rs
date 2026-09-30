//! LINEAR-ALGEBRA-CHOLESKY-SOLVE-V1 package, lowering, IEEE, shape, and allocation qualification.

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
            "aether-linear-algebra-cholesky-solve-{label}-{}-{}",
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
fn api_guards_workspaces_and_loop_order_are_the_exact_source_contract() {
    assert_eq!(LIBRARY.matches(" solve<T: IEEEFloat>(").count(), 6);
    assert_eq!(
        LIBRARY
            .matches("Vector<T,Column> solve<T: IEEEFloat>(")
            .count(),
        3
    );
    assert_eq!(LIBRARY.matches("Matrix<T> solve<T: IEEEFloat>(").count(), 3);

    let vector_start = LIBRARY
        .find("// Solve L L^T x = b using one owning result")
        .unwrap();
    let matrix_start = LIBRARY
        .find("// Solve L L^T X = B directly in one n by q owning result")
        .unwrap();
    let end = LIBRARY.find("// A materialized QR factorization").unwrap();
    let vector = &LIBRARY[vector_start..matrix_start];
    let matrix = &LIBRARY[matrix_start..end];

    let vector_square = vector
        .find("shapeGuard(rows((*factor).L) == columns((*factor).L));")
        .unwrap();
    let vector_rhs = vector
        .find("shapeGuard(dimension(*b) == rows((*factor).L));")
        .unwrap();
    let vector_n = vector.find("usize n = rows((*factor).L);").unwrap();
    let vector_alloc = vector
        .find("Vector<T,Column> w = vectorFilled<T,Column>(n, zero);")
        .unwrap();
    assert!(vector_square < vector_rhs && vector_rhs < vector_n && vector_n < vector_alloc);
    assert_eq!(vector.matches("vectorFilled<").count(), 1);
    assert!(!vector.contains("throw "));
    assert!(!vector.contains("transpose"));
    assert!(vector.contains("value = value - (*factor).L[i,j] * w[j];"));
    assert!(vector.contains("value = value - (*factor).L[j,i] * w[j];"));
    assert!(vector.contains("w[i] = value / (*factor).L[i,i];"));

    let matrix_square = matrix
        .find("shapeGuard(rows((*factor).L) == columns((*factor).L));")
        .unwrap();
    let matrix_rhs = matrix
        .find("shapeGuard(rows(*B) == rows((*factor).L));")
        .unwrap();
    let matrix_n = matrix.find("usize n = rows((*factor).L);").unwrap();
    let matrix_q = matrix.find("usize q = columns(*B);").unwrap();
    let matrix_alloc = matrix
        .find("Matrix<T> W = matrixFilled<T>(n, q, zero);")
        .unwrap();
    assert!(
        matrix_square < matrix_rhs
            && matrix_rhs < matrix_n
            && matrix_n < matrix_q
            && matrix_q < matrix_alloc
    );
    assert_eq!(matrix.matches("matrixFilled<").count(), 1);
    assert!(!matrix.contains("Vector<"));
    assert!(!matrix.contains("throw "));
    assert!(!matrix.contains("transpose"));
    assert!(matrix.contains("value = value - (*factor).L[i,j] * W[j,c];"));
    assert!(matrix.contains("value = value - (*factor).L[j,i] * W[j,c];"));
    assert!(matrix.contains("W[i,c] = value / (*factor).L[i,i];"));
}

#[test]
fn generic_source_lowers_to_concrete_direct_float_operations() {
    let source = "package consumer;import linearAlgebra as la;Vector<T,Column>v<T:IEEEFloat>(ref la.Cholesky<T>f,ref Vector<T,Column>b){return la.solve(f,b);}Matrix<T>m<T:IEEEFloat>(ref la.Cholesky<T>f,ref Matrix<T>b){return la.solve(f,b);}int main(){Matrix<float64>l=[2.0,99.0;1.0,2.0];la.Cholesky<float64>f=la.Cholesky<float64>(l);Vector<float64,Column>b=[8.0,12.0];Vector<float64,Column>x=v(f,b);Matrix<float32>k=[float32(2.0)];la.Cholesky<float32>g=la.Cholesky<float32>(k);Matrix<float32>r=[float32(8.0),float32(4.0)];Matrix<float32>y=m(g,r);return int(x[1]+x[2]+float64(y[1,1])+float64(y[1,2])-6.0);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let hir = &compilation.dumps[&Emit::Hir];
        for operation in [
            "ShapeGuard",
            "capability: Zero",
            "behavior: Sub",
            "behavior: Mul",
            "behavior: Div",
            "SubtractFloat",
            "MultiplyFloat",
            "DivideFloat",
        ] {
            assert!(hir.contains(operation), "HIR missing {operation}");
        }
        for phase in [Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            for residue in ["GenericParam(", "CapabilityBinary", "witness", "vtable"] {
                assert!(!dump.contains(residue), "{phase:?} contains {residue}");
            }
            assert!(!dump.contains("Transpose"), "{phase:?}");
        }
        for residue in [
            "fast-math",
            "TypeId",
            "witness",
            "vtable",
            "aether_cholesky_solve",
        ] {
            assert!(
                !compilation.llvm.contains(residue),
                "LLVM contains {residue}"
            );
        }
        assert_eq!(status(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn both_precisions_reuse_factors_match_lu_and_ignore_physical_upper() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[4.0,2.0;2.0,5.0];la.Cholesky<float64>ch=la.cholesky(a);Vector<float64,Column>b1=[8.0,12.0];Vector<float64,Column>b2=[2.0,13.0];Vector<float64,Column>x1=la.solve(ch,b1);Vector<float64,Column>x2=la.solve(ch,b2);Matrix<float64>B=[8.0,2.0;12.0,13.0];Matrix<float64>X=la.solve(ch,B);la.LU<float64>lu=la.lu(a);Matrix<float64>Y=la.solve(lu,B);if(abs(x1[1]-1.0)>1e-12||abs(x1[2]-2.0)>1e-12||abs(x2[1]+1.0)>1e-12||abs(x2[2]-3.0)>1e-12){return 1;}if(abs(X[1,2]-Y[1,2])>1e-12||abs(X[2,2]-Y[2,2])>1e-12){return 2;}Matrix<float64>l=[2.0,-777.0;1.0,2.0];la.Cholesky<float64>forged=la.Cholesky<float64>(l);Vector<float64,Column>u=la.solve(forged,b1);if(u[1]!=x1[1]||u[2]!=x1[2]){return 3;}if(ch.L[2,1]!=1.0||b1[1]!=8.0||B[2,2]!=13.0){return 4;}Matrix<float32>c=[float32(4.0),float32(2.0);float32(2.0),float32(5.0)];la.Cholesky<float32>f=la.cholesky(c);Vector<float32,Column>d=[float32(8.0),float32(12.0)];Vector<float32,Column>z=la.solve(f,d);Matrix<float32>D=[float32(8.0);float32(12.0)];Matrix<float32>Z=la.solve(f,D);if(abs(z[1]-float32(1.0))>float32(2e-5)||abs(z[2]-float32(2.0))>float32(2e-5)||abs(Z[2,1]-z[2])>float32(2e-5)){return 5;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(status(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn scalar_and_diagonal_spd_systems_are_solved_in_both_precisions() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[9.0];la.Cholesky<float64>f=la.cholesky(a);Vector<float64,Column>b=[18.0];Vector<float64,Column>x=la.solve(f,b);if(x[1]!=2.0){return 1;}Matrix<float64>d=[4.0,0.0;0.0,9.0];la.Cholesky<float64>g=la.cholesky(d);Vector<float64,Column>e=[8.0,27.0];Vector<float64,Column>y=la.solve(g,e);Matrix<float64>E=[8.0;27.0];Matrix<float64>Y=la.solve(g,E);if(y[1]!=2.0||y[2]!=3.0||Y[1,1]!=y[1]||Y[2,1]!=y[2]){return 2;}Matrix<float32>p=[float32(4.0),float32(0.0);float32(0.0),float32(9.0)];la.Cholesky<float32>h=la.cholesky(p);Vector<float32,Column>q=[float32(8.0),float32(27.0)];Vector<float32,Column>z=la.solve(h,q);if(z[1]!=float32(2.0)||z[2]!=float32(3.0)){return 3;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(status(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn manual_aggregates_follow_ieee_arithmetic_without_nominal_exceptions() {
    let source = "package consumer;import linearAlgebra as la;int main(){float64 z=0.0;float64 inf=1.0/z;float64 nan=z/z;Vector<float64,Column>b=[1.0];Matrix<float64>lp=[z];la.Cholesky<float64>fp=la.Cholesky<float64>(lp);Vector<float64,Column>xp=la.solve(fp,b);if(xp[1]!=inf){return 1;}Matrix<float64>ln=[-z];la.Cholesky<float64>fn=la.Cholesky<float64>(ln);Vector<float64,Column>xn=la.solve(fn,b);if(xn[1]!=inf){return 2;}Matrix<float64>lm=[-2.0];la.Cholesky<float64>fm=la.Cholesky<float64>(lm);Vector<float64,Column>xm=la.solve(fm,b);if(xm[1]!=0.25){return 3;}Matrix<float64>lq=[nan];la.Cholesky<float64>fq=la.Cholesky<float64>(lq);Vector<float64,Column>xq=la.solve(fq,b);if(xq[1]==xq[1]){return 4;}Matrix<float64>li=[inf];la.Cholesky<float64>fi=la.Cholesky<float64>(li);Vector<float64,Column>xi=la.solve(fi,b);if(xi[1]!=z||1.0/xi[1]!=inf){return 5;}Matrix<float64>lj=[-inf];la.Cholesky<float64>fj=la.Cholesky<float64>(lj);Vector<float64,Column>xj=la.solve(fj,b);if(xj[1]!=z||1.0/xj[1]!=inf){return 6;}Matrix<float64>lc=[2.0,19.0;3.0,4.0];la.Cholesky<float64>fc=la.Cholesky<float64>(lc);Vector<float64,Column>bc=[8.0,28.0];Vector<float64,Column>xc=la.solve(fc,bc);if(abs(xc[1]-0.5)>1e-12||abs(xc[2]-1.0)>1e-12){return 7;}Matrix<float64>invalid=[z,99.0;7.0,nan];la.Cholesky<float64>invalidFactor=la.Cholesky<float64>(invalid);Matrix<float64>empty=la.zeros(2,0);Matrix<float64>xe=la.solve(invalidFactor,empty);return int(rows(xe)+columns(xe)-2);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(status(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn shape_guards_precede_workspace_creation_for_both_rhs_kinds() {
    let cases = [
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>l=[1.0,2.0];la.Cholesky<float64>f=la.Cholesky<float64>(l);Vector<float64,Column>b=[1.0];Vector<float64,Column>x=la.solve(f,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>l=[1.0];la.Cholesky<float64>f=la.Cholesky<float64>(l);Vector<float64,Column>b=[];Vector<float64,Column>x=la.solve(f,b);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>l=[1.0];la.Cholesky<float64>f=la.Cholesky<float64>(l);Matrix<float64>b=la.zeros(0,3);Matrix<float64>x=la.solve(f,b);return 0;}",
    ];
    for source in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization);
            let instrumented = compilation.llvm.replace(
                "trap_shape_mismatch:\n  ; structured Aether trap: ShapeMismatch\n  call void @llvm.trap()",
                "trap_shape_mismatch:\n  call void @exit(i32 73)",
            ) + "\ndeclare void @exit(i32)\n";
            assert_eq!(status(&instrumented, optimization).code(), Some(73));
        }
    }
}

#[test]
fn result_has_one_backing_exactly_when_its_logical_size_is_nonzero() {
    let cases = [
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>l=[2.0,0.0;1.0,2.0];la.Cholesky<float64>f=la.Cholesky<float64>(l);Vector<float64,Column>b=[8.0,12.0];Vector<float64,Column>x=la.solve(f,b);return int(x[1]+x[2]-3.0);}",
            3,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>l=la.zeros(0,0);la.Cholesky<float64>f=la.Cholesky<float64>(l);Vector<float64,Column>b=la.zeros(0);Vector<float64,Column>x=la.solve(f,b);return int(dimension(x));}",
            0,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>l=[2.0,0.0;1.0,2.0];la.Cholesky<float64>f=la.Cholesky<float64>(l);Matrix<float64>b=[8.0,2.0;12.0,13.0];Matrix<float64>x=la.solve(f,b);return int(x[1,1]+x[2,1]-3.0);}",
            3,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>l=[0.0,9.0;7.0,0.0];la.Cholesky<float64>f=la.Cholesky<float64>(l);Matrix<float64>b=la.zeros(2,0);Matrix<float64>x=la.solve(f,b);return int(rows(x)+columns(x)-2);}",
            1,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>l=la.zeros(0,0);la.Cholesky<float64>f=la.Cholesky<float64>(l);Matrix<float64>b=la.zeros(0,4);Matrix<float64>x=la.solve(f,b);return int(rows(x)+columns(x)-4);}",
            0,
        ),
    ];
    for (source, expected) in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization);
            assert_eq!(
                status(&allocation_guard(&compilation.llvm, expected), optimization).code(),
                Some(0)
            );
        }
    }
}
