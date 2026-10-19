//! LINEAR-ALGEBRA-SVD-LEAST-SQUARES-V1 numeric, resource, and IR qualification.

use std::{
    fmt::Write as _,
    fs,
    io::Write as _,
    path::PathBuf,
    process::{Command, Stdio},
};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session_with_optimization,
};

const LIBRARY: &str = include_str!("../../../../linearAlgebra/src/lib.ae");

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-svd-least-squares-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn imported(&self, source: &str) -> PathBuf {
        fs::write(self.0.join("linearAlgebra.ae"), LIBRARY).unwrap();
        let entry = self.0.join("main.ae");
        fs::write(&entry, source).unwrap();
        entry
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn compile(
    source: &str,
    optimization: OptimizationLevel,
    emit: &[Emit],
) -> aether_driver::Compilation {
    let directory = Directory::new("compile");
    compile_session_with_optimization(
        CompilationSession::discover(&directory.imported(source)).unwrap(),
        emit,
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"))
}

fn status_llvm(llvm: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    let directory = Directory::new("run");
    let executable = directory.0.join("qualification");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &executable)
        .unwrap();
    Command::new(executable).status().unwrap()
}

fn run(source: &str, optimization: OptimizationLevel) {
    let compilation = compile(source, optimization, &[Emit::Llvm]);
    assert_eq!(
        status_llvm(&compilation.llvm, optimization).code(),
        Some(0),
        "{optimization:?}"
    );
}

fn allocation_guard(llvm: &str, expected: u64) -> String {
    let guarded = llvm.replace(
        "  %process_status = trunc i64 %aether_result to i32",
        &format!(
            "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, {expected}\n  %free_ok = icmp eq i64 %frees, {expected}\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99"
        ),
    );
    assert_ne!(guarded, llvm);
    guarded
}

fn matrix_literal(rows: usize, columns: usize, values: &[f64], float32: bool) -> String {
    assert_eq!(values.len(), rows * columns);
    let mut literal = String::from("[");
    for row in 0..rows {
        if row != 0 {
            literal.push(';');
        }
        for column in 0..columns {
            if column != 0 {
                literal.push(',');
            }
            let value = values[row * columns + column];
            if float32 {
                write!(literal, "float32({value:.17e})").unwrap();
            } else {
                write!(literal, "{value:.17e}").unwrap();
            }
        }
    }
    literal.push(']');
    literal
}

fn vector_literal(values: &[f64], float32: bool) -> String {
    let mut literal = String::from("[");
    for (index, value) in values.iter().enumerate() {
        if index != 0 {
            literal.push(',');
        }
        if float32 {
            write!(literal, "float32({value:.17e})").unwrap();
        } else {
            write!(literal, "{value:.17e}").unwrap();
        }
    }
    literal.push(']');
    literal
}

/// Independent test-only NumPy/LAPACK oracle. An absolute Aether cutoff is
/// converted to `NumPy`'s rcond using the oracle's largest singular value.
fn numpy_lstsq(
    rows: usize,
    columns: usize,
    a: &[f64],
    b: &[f64],
    float32: bool,
    cutoff: Option<f64>,
) -> Vec<f64> {
    let script = r#"
import sys
import numpy as np
rows, columns = map(int, sys.stdin.readline().split())
dtype = np.float32 if sys.argv[1] == "32" else np.float64
a = np.fromstring(sys.stdin.readline(), sep=" ", dtype=dtype).reshape((rows, columns))
b = np.fromstring(sys.stdin.readline(), sep=" ", dtype=dtype)
s = np.linalg.svd(a, compute_uv=False)
if sys.argv[2] == "default":
    rcond = max(rows, columns) * np.finfo(dtype).eps
else:
    cutoff = float(sys.argv[2])
    rcond = cutoff / float(s[0]) if s.size and s[0] != 0 else 0.0
x = np.linalg.lstsq(a, b, rcond=rcond)[0]
print(" ".join(format(float(value), ".17e") for value in x))
"#;
    let cutoff_arg = cutoff.map_or_else(|| "default".to_owned(), |value| value.to_string());
    let mut child = Command::new("python3")
        .args(["-c", script, if float32 { "32" } else { "64" }, &cutoff_arg])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("qualification requires python3 with NumPy");
    {
        let input = child.stdin.as_mut().unwrap();
        writeln!(input, "{rows} {columns}").unwrap();
        for value in a {
            write!(input, "{value:.17e} ").unwrap();
        }
        writeln!(input).unwrap();
        for value in b {
            write!(input, "{value:.17e} ").unwrap();
        }
        writeln!(input).unwrap();
    }
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "NumPy oracle failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout)
        .unwrap()
        .split_whitespace()
        .map(|value| value.parse().unwrap())
        .collect()
}

#[test]
#[allow(clippy::too_many_lines)] // The table intentionally keeps the numeric corpus local.
fn numpy_oracle_covers_square_tall_wide_rank_deficient_and_cutoffs_at_o0_o2() {
    let cases = [
        (2, 2, vec![3.0, 1.0, 1.0, 2.0], vec![7.0, 5.0], false, None),
        (
            4,
            2,
            vec![1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 2.0, -1.0],
            vec![1.0, 2.0, 2.5, -0.25],
            false,
            None,
        ),
        (
            3,
            2,
            vec![1.0, 0.0, 0.0, 1.0, 1.0, 1.0],
            vec![1.0, 2.0, 3.0],
            false,
            None,
        ),
        (
            2,
            3,
            vec![1.0, 0.0, 1.0, 0.0, 1.0, 1.0],
            vec![2.0, 3.0],
            false,
            None,
        ),
        (
            3,
            2,
            vec![1.0, 2.0, 2.0, 4.0, 3.0, 6.0],
            vec![1.0, 2.0, 4.0],
            false,
            None,
        ),
        (
            2,
            2,
            vec![4.0, 0.0, 0.0, 0.5],
            vec![8.0, 3.0],
            false,
            Some(0.5),
        ),
        (2, 2, vec![3.0, 0.0, 0.0, -3.0], vec![6.0, 9.0], false, None),
        (
            2,
            3,
            vec![0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            vec![2.0, -1.0],
            false,
            None,
        ),
        (
            2,
            2,
            vec![1.0e150, 0.0, 0.0, -2.0e150],
            vec![2.0e150, 6.0e150],
            false,
            None,
        ),
        (
            2,
            2,
            vec![1.0e-150, 0.0, 0.0, -2.0e-150],
            vec![2.0e-150, 6.0e-150],
            false,
            None,
        ),
        (
            3,
            2,
            vec![1.0, 2.0, 3.0, 4.0, 5.0, 7.0],
            vec![1.0, -2.0, 4.0],
            true,
            None,
        ),
        (
            2,
            3,
            vec![1.0, 2.0, 0.0, 0.0, 1.0, 1.0],
            vec![2.0, -1.0],
            true,
            Some(0.0),
        ),
    ];
    let mut source =
        String::from("package consumer;import linearAlgebra as la;int main(){int failed=0;");
    for (index, (rows, columns, a, b, float32, cutoff)) in cases.iter().enumerate() {
        let expected = numpy_lstsq(*rows, *columns, a, b, *float32, *cutoff);
        let scalar = if *float32 { "float32" } else { "float64" };
        let tolerance = if *float32 {
            "float32(3.0e-3)"
        } else {
            "2.0e-10"
        };
        let one = if *float32 { "float32(1.0)" } else { "1.0" };
        let call = cutoff.map_or_else(
            || format!("la.leastSquares(a{index},b{index})"),
            |value| {
                if *float32 {
                    format!("la.leastSquares(a{index},b{index},float32({value:.17e}))")
                } else {
                    format!("la.leastSquares(a{index},b{index},{value:.17e})")
                }
            },
        );
        writeln!(
            source,
            "Matrix<{scalar}>a{index}={};Vector<{scalar},Column>b{index}={};Vector<{scalar},Column>x{index}={call};Vector<{scalar},Column>e{index}={};usize j{index}=1;while(j{index}<=dimension(x{index})){{if(abs(x{index}[j{index}]-e{index}[j{index}])>{tolerance}*({one}+abs(e{index}[j{index}]))){{failed=failed+1;}}j{index}=j{index}+1;}}",
            matrix_literal(*rows, *columns, a, *float32),
            vector_literal(b, *float32),
            vector_literal(&expected, *float32),
        )
        .unwrap();
    }
    source.push_str("return failed;}");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(&source, optimization);
    }
}

#[test]
fn minimum_norm_residual_normal_condition_cross_property_and_matrix_rhs_hold() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 Matrix<float64>a=[1.0,1.0];Vector<float64,Column>b=[2.0];
 Vector<float64,Column>x=la.leastSquares(a,b);if(abs(x[1]-1.0)>1.0e-11||abs(x[2]-1.0)>1.0e-11){return 1;}
 float64 t=3.5;float64 base=x[1]*x[1]+x[2]*x[2];float64 perturbed=(x[1]+t)*(x[1]+t)+(x[2]-t)*(x[2]-t);if(base>perturbed+1.0e-12){return 2;}
 float64 residual=a[1,1]*x[1]+a[1,2]*x[2]-b[1];float64 residual2=a[1,1]*(x[1]+t)+a[1,2]*(x[2]-t)-b[1];if(abs(residual)>1.0e-11||abs(residual2-residual)>1.0e-12){return 3;}
 Matrix<float64>rankDeficient=[1.0,2.0;2.0,4.0];Vector<float64,Column>rankRhs=[3.0,6.0];Vector<float64,Column>rankX=la.leastSquares(rankDeficient,rankRhs);if(abs(rankX[1]-0.6)>1.0e-10||abs(rankX[2]-1.2)>1.0e-10){return 4;}float64 nullT=2.25;float64 rankBase=rankX[1]*rankX[1]+rankX[2]*rankX[2];float64 rankPerturbed=(rankX[1]-2.0*nullT)*(rankX[1]-2.0*nullT)+(rankX[2]+nullT)*(rankX[2]+nullT);if(rankBase>rankPerturbed+1.0e-12){return 5;}
 Matrix<float64>tall=[1.0,0.0;0.0,1.0;1.0,1.0];Vector<float64,Column>rhs=[1.0,2.0,4.0];Vector<float64,Column>y=la.leastSquares(tall,rhs);
 float64 r1=y[1]-1.0;float64 r2=y[2]-2.0;float64 r3=y[1]+y[2]-4.0;if(abs(r1+r3)>1.0e-10||abs(r2+r3)>1.0e-10){return 6;}
 Matrix<float64>pinv=la.pseudoInverse(tall);Vector<float64,Column>oracle=matrix_view(pinv)*vector_view(rhs);if(abs(y[1]-oracle[1])>1.0e-10||abs(y[2]-oracle[2])>1.0e-10){return 7;}
 la.SVD<float64>factor=la.svd(tall);Vector<float64,Column>yf=la.leastSquares(factor,rhs);Matrix<float64>pinvf=la.pseudoInverse(factor);Vector<float64,Column>oraclef=matrix_view(pinvf)*vector_view(rhs);if(abs(yf[1]-y[1])>1.0e-12||abs(yf[2]-y[2])>1.0e-12||abs(yf[1]-oraclef[1])>1.0e-10||abs(yf[2]-oraclef[2])>1.0e-10){return 8;}
 Matrix<float64>B=[1.0,2.0;2.0,-1.0;3.0,3.0];Matrix<float64>X=la.leastSquares(factor,B);Vector<float64,Column>b1=[1.0,2.0,3.0];Vector<float64,Column>b2=[2.0,-1.0,3.0];Vector<float64,Column>x1=la.leastSquares(factor,b1);Vector<float64,Column>x2=la.leastSquares(factor,b2);
 if(rows(X)!=2||columns(X)!=2){return 9;}usize j=1;while(j<=2){if(abs(X[j,1]-x1[j])>1.0e-12||abs(X[j,2]-x2[j])>1.0e-12){return 10;}j=j+1;}
 if(tall[3,2]!=1.0||rhs[3]!=4.0||B[3,2]!=3.0||factor.S[1]<factor.S[2]){return 11;}
 return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn cutoff_manual_factor_ieee_and_degenerate_shapes_are_literal() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 Matrix<float64>a=[1.0,0.0;0.0,1.0e-20];Vector<float64,Column>b=[2.0,3.0];Vector<float64,Column>d=la.leastSquares(a,b);Vector<float64,Column>z=la.leastSquares(a,b,0.0);if(abs(d[1]-2.0)>1.0e-12||d[2]!=0.0||abs(z[2]-3.0e20)>1.0e6){return 1;}
 Matrix<float64>u=[1.0;0.0;0.0];Vector<float64,Column>s=[2.0];Matrix<float64>vt=[0.0,1.0,0.0,0.0];la.SVD<float64>f=la.SVD<float64>(u,s,vt);Vector<float64,Column>rhs=[6.0,8.0,10.0];Vector<float64,Column>x=la.leastSquares(f,rhs);if(dimension(x)!=4||x[1]!=0.0||x[2]!=3.0||x[3]!=0.0||x[4]!=0.0){return 2;}
 Matrix<float64>B=[6.0,2.0;8.0,4.0;10.0,5.0];Matrix<float64>X=la.leastSquares(f,B);if(rows(X)!=4||columns(X)!=2||X[2,1]!=3.0||X[2,2]!=1.0){return 3;}
 Matrix<float64>m0=matrixFilled<float64>(4,0,0.0);Vector<float64,Column>b4=vectorFilled<float64,Column>(4,1.0);Vector<float64,Column>x0=la.leastSquares(m0,b4);if(dimension(x0)!=0){return 4;}
 Matrix<float64>a0n=matrixFilled<float64>(0,5,0.0);Vector<float64,Column>b0=vectorFilled<float64,Column>(0,0.0);Vector<float64,Column>x5=la.leastSquares(a0n,b0);if(dimension(x5)!=5||x5[1]!=0.0){return 5;}
 Matrix<float64>B0q=matrixFilled<float64>(0,3,0.0);Matrix<float64>X5q=la.leastSquares(a0n,B0q);if(rows(X5q)!=5||columns(X5q)!=3||X5q[1,1]!=0.0){return 6;}
 Matrix<float64>Bm0=matrixFilled<float64>(4,2,1.0);Matrix<float64>X0q=la.leastSquares(m0,Bm0);if(rows(X0q)!=0||columns(X0q)!=2){return 7;}
 Matrix<float64>Bq0=matrixFilled<float64>(4,0,0.0);Matrix<float64>Xq0=la.leastSquares(m0,Bq0);if(rows(Xq0)!=0||columns(Xq0)!=0){return 8;}
 Matrix<float64>pu=matrixFilled<float64>(3,0,0.0);Vector<float64,Column>ps=vectorFilled<float64,Column>(0,0.0);Matrix<float64>pv=matrixFilled<float64>(0,4,0.0);la.SVD<float64>pf=la.SVD<float64>(pu,ps,pv);Vector<float64,Column>pb=vectorFilled<float64,Column>(3,2.0);Vector<float64,Column>px=la.leastSquares(pf,pb);if(dimension(px)!=4||px[1]!=0.0){return 9;}
 float64 zero=0.0;float64 nan=zero/zero;float64 inf=1.0/zero;int caught=0;
 try{Vector<float64,Column>q=la.leastSquares(a,b,-1.0);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 try{Vector<float64,Column>q=la.leastSquares(a,b,nan);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 try{Vector<float64,Column>q=la.leastSquares(a,b,inf);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 try{Vector<float64,Column>q=la.leastSquares(f,rhs,nan);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 try{Matrix<float64>q=la.leastSquares(f,B,inf);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 if(caught!=5){return 10;}
 Matrix<float64>eu=[1.0];Vector<float64,Column>es=[5.0e-324];Matrix<float64>ev=[1.0];la.SVD<float64>ef=la.SVD<float64>(eu,es,ev);Vector<float64,Column>eb=[1.0];Vector<float64,Column>ex=la.leastSquares(ef,eb,0.0);if(ex[1]!=inf){return 11;}
 return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn rhs_and_factor_shape_guards_precede_invalid_cutoff() {
    let sources = [
        "package consumer;import linearAlgebra as la;int main(){float64 z=0.0;Matrix<float64>a=[1.0];Vector<float64,Column>b=[1.0,2.0];Vector<float64,Column>x=la.leastSquares(a,b,z/z);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){float64 z=0.0;Matrix<float64>a=[1.0];Matrix<float64>b=matrixFilled<float64>(2,1,0.0);Matrix<float64>x=la.leastSquares(a,b,z/z);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){float64 z=0.0;Matrix<float64>u=matrixFilled<float64>(1,1,0.0);Vector<float64,Column>s=[1.0,0.0];Matrix<float64>v=matrixFilled<float64>(2,1,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);Vector<float64,Column>b=[1.0];Vector<float64,Column>x=la.leastSquares(f,b,z/z);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){float64 z=0.0;Matrix<float64>u=[1.0];Vector<float64,Column>s=[1.0];Matrix<float64>v=[1.0];la.SVD<float64>f=la.SVD<float64>(u,s,v);Matrix<float64>b=matrixFilled<float64>(2,1,0.0);Matrix<float64>x=la.leastSquares(f,b,z/z);return 0;}",
    ];
    for source in sources {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization, &[Emit::Llvm]);
            let instrumented = compilation.llvm.replace(
                "trap_shape_mismatch:\n  ; structured Aether trap: ShapeMismatch\n  call void @llvm.trap()",
                "trap_shape_mismatch:\n  call void @exit(i32 73)",
            ) + "\ndeclare void @exit(i32)\n";
            assert_eq!(status_llvm(&instrumented, optimization).code(), Some(73));
        }
    }
}

#[test]
fn factor_reuse_allocates_only_outputs_and_matrix_routes_factor_once() {
    let cases = [
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=la.identity<float64>(2);Vector<float64,Column>s=[2.0,1.0];Matrix<float64>v=la.identity<float64>(2);la.SVD<float64>f=la.SVD<float64>(u,s,v);Vector<float64,Column>b1=[4.0,3.0];Vector<float64,Column>b2=[2.0,5.0];Matrix<float64>B=[4.0,2.0;3.0,5.0];Vector<float64,Column>x1=la.leastSquares(f,b1);Vector<float64,Column>x2=la.leastSquares(f,b2,0.0);Matrix<float64>X=la.leastSquares(f,B);return int(x1[1]+x2[1]+X[1,1]-5.0);}",
            9,
            false,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[2.0,0.0;0.0,1.0];Vector<float64,Column>b=[4.0,3.0];Vector<float64,Column>x=la.leastSquares(a,b);return int(x[1]+x[2]-5.0);}",
            10,
            true,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[2.0,0.0;0.0,1.0];Matrix<float64>B=[4.0,2.0;3.0,1.0];Matrix<float64>X=la.leastSquares(a,B);return int(X[1,1]+X[2,1]-5.0);}",
            10,
            true,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=matrixFilled<float64>(3,0,0.0);Vector<float64,Column>s=vectorFilled<float64,Column>(0,0.0);Matrix<float64>v=matrixFilled<float64>(0,4,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);Vector<float64,Column>b=vectorFilled<float64,Column>(3,1.0);Vector<float64,Column>x=la.leastSquares(f,b);return int(dimension(x)-4);}",
            2,
            false,
        ),
    ];
    for (source, expected, matrix_route) in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization, &[Emit::Llvm]);
            if !matrix_route {
                assert!(!compilation.llvm.contains("assembleSVDWorkspace__gfFloat64"));
                assert!(!compilation.llvm.contains("f3_svd__gfFloat64"));
            } else if optimization == OptimizationLevel::O0 {
                let svd_calls = compilation
                    .llvm
                    .lines()
                    .filter(|line| {
                        line.contains("svd")
                            && (line.contains(" call ") || line.contains(" invoke "))
                    })
                    .count();
                assert_eq!(svd_calls, 1);
            }
            assert_eq!(
                status_llvm(&allocation_guard(&compilation.llvm, expected), optimization).code(),
                Some(0),
                "expected {expected} allocations at {optimization:?}"
            );
        }
    }
}

#[test]
fn public_surface_direct_kernels_and_lowering_are_closed() {
    assert_eq!(
        LIBRARY
            .matches("public Vector<T,Column> leastSquares<")
            .count(),
        4
    );
    assert_eq!(LIBRARY.matches("public Matrix<T> leastSquares<").count(), 4);
    assert!(LIBRARY.contains("projection = projection + (*factor).U[i,r] * (*b)[i];"));
    assert!(LIBRARY.contains("result[j] = result[j] + (*factor).Vt[r,j] * coefficient;"));
    assert!(LIBRARY.contains("projection = projection + (*factor).U[i,r] * (*B)[i,c];"));
    assert!(LIBRARY.contains("result[j,c] + (*factor).Vt[r,j] * coefficient;"));
    assert_eq!(LIBRARY.matches("SVD<T> factor = svd<T>(A);").count(), 6);

    let vector_kernel = LIBRARY
        .split("Vector<T,Column> leastSquaresVectorRetained")
        .nth(1)
        .unwrap()
        .split("Matrix<T> leastSquaresMatrixRetained")
        .next()
        .unwrap();
    let matrix_kernel = LIBRARY
        .split("Matrix<T> leastSquaresMatrixRetained")
        .nth(1)
        .unwrap()
        .split("public Vector<T,Column> leastSquares")
        .next()
        .unwrap();
    for kernel in [vector_kernel, matrix_kernel] {
        for forbidden in [
            "pseudoInverse",
            "svd<",
            "transpose",
            "matrix_view",
            "vector_view",
        ] {
            assert!(!kernel.contains(forbidden), "{forbidden}");
        }
    }

    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[2.0,0.0;0.0,1.0];Vector<float64,Column>b=[4.0,3.0];Matrix<float64>B=[4.0,2.0;3.0,1.0];la.SVD<float64>f=la.svd(a);Vector<float64,Column>x1=la.leastSquares(f,b);Vector<float64,Column>x2=la.leastSquares(f,b,0.0);Vector<float64,Column>x3=la.leastSquares(a,b);Vector<float64,Column>x4=la.leastSquares(a,b,0.0);Matrix<float64>X1=la.leastSquares(f,B);Matrix<float64>X2=la.leastSquares(a,B);Matrix<float32>c=[float32(1.0)];Vector<float32,Column>d=[float32(2.0)];Vector<float32,Column>y=la.leastSquares(c,d);return int(x1[1]+x2[1]+x3[1]+x4[1]+X1[1,1]+X2[1,1]+y[1]-14.0);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization, &[Emit::Mir, Emit::Ssa, Emit::Llvm]);
        for phase in [Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(!dump.contains("GenericParam("), "{phase:?}");
            assert!(!dump.contains("witness"), "{phase:?}");
            assert!(!dump.contains("vtable"), "{phase:?}");
        }
        for forbidden in ["TypeId", "LAPACK", "least_squares_opcode"] {
            assert!(!compilation.llvm.contains(forbidden), "{forbidden}");
        }
        assert!(
            compilation
                .llvm
                .contains("leastSquaresVectorRetained__gfFloat64")
        );
        assert!(
            compilation
                .llvm
                .contains("leastSquaresMatrixRetained__gfFloat64")
        );
        assert!(
            compilation
                .llvm
                .contains("leastSquaresVectorRetained__gfFloat32")
        );
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }
}
