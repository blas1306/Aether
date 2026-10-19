//! LINEAR-ALGEBRA-SVD-DERIVED-QUALIFICATION-CLOSURE-1 joint qualification.

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
            "aether-svd-derived-closure-{label}-{}-{}",
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
        CompilationSession::discover(&directory.imported(source))
            .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}")),
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

fn svd_call_count(llvm: &str) -> usize {
    llvm.lines()
        .filter(|line| {
            line.contains("svd") && (line.contains(" call ") || line.contains(" invoke "))
        })
        .count()
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

/// Independent qualification-only NumPy/LAPACK oracle for the literal
/// Eckart--Young prefix and both Mirsky errors.
fn numpy_low_rank(
    rows: usize,
    columns: usize,
    values: &[f64],
    rank: usize,
    float32: bool,
) -> (Vec<f64>, f64, f64) {
    let script = r#"
import sys
import numpy as np
rows, columns, rank = map(int, sys.stdin.readline().split())
dtype = np.float32 if sys.argv[1] == "32" else np.float64
a = np.fromstring(sys.stdin.readline(), sep=" ", dtype=dtype).reshape((rows, columns))
u, s, vt = np.linalg.svd(a, full_matrices=False)
ak = (u[:, :rank] * s[:rank]) @ vt[:rank, :]
spectral = 0.0 if rank == s.size else float(s[rank])
frobenius = float(np.linalg.norm(s[rank:]))
print(" ".join(format(float(value), ".17e") for value in ak.ravel()))
print(format(spectral, ".17e"))
print(format(frobenius, ".17e"))
"#;
    let mut child = Command::new("python3")
        .args(["-c", script, if float32 { "32" } else { "64" }])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("qualification requires python3 with NumPy");
    {
        let input = child.stdin.as_mut().unwrap();
        writeln!(input, "{rows} {columns} {rank}").unwrap();
        for value in values {
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
    let stdout = String::from_utf8(output.stdout).unwrap();
    let mut lines = stdout.lines();
    let approximation = lines
        .next()
        .unwrap()
        .split_whitespace()
        .map(|value| value.parse().unwrap())
        .collect();
    let spectral = lines.next().unwrap().parse().unwrap();
    let frobenius = lines.next().unwrap().parse().unwrap();
    (approximation, spectral, frobenius)
}

#[test]
fn shared_cutoff_condition_and_literal_rank_are_jointly_closed() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 Matrix<float64>u=la.identity<float64>(3);Vector<float64,Column>s=[8.0,2.0,1.0e-20];Matrix<float64>v=la.identity<float64>(3);la.SVD<float64>f=la.SVD<float64>(u,s,v);Vector<float64,Column>b=[8.0,6.0,4.0];
 if(la.numericalRank(f,2.0)!=1){return 1;}Matrix<float64>p=la.pseudoInverse(f,2.0);Vector<float64,Column>x=la.leastSquares(f,b,2.0);
 if(p[1,1]!=0.125||p[2,2]!=0.0||p[3,3]!=0.0||x[1]!=1.0||x[2]!=0.0||x[3]!=0.0){return 2;}
 if(la.numericalRank(f,0.0)!=3||la.numericalRank(f)!=2){return 3;}
 if(la.condition2(f)!=8.0e20){return 4;}Matrix<float64>a3=la.lowRankApproximation(f,3);if(a3[1,1]!=8.0||a3[2,2]!=2.0||a3[3,3]!=1.0e-20){return 5;}
 Matrix<float64>a0=la.lowRankApproximation(f,0);if(a0[1,1]!=0.0||a0[2,2]!=0.0||a0[3,3]!=0.0){return 6;}
 if(la.lowRankSpectralError(f,1)!=2.0||la.lowRankFrobeniusError(f,3)!=0.0){return 7;}
 Matrix<float64>eu=matrixFilled<float64>(2,0,0.0);Vector<float64,Column>es=vectorFilled<float64,Column>(0,0.0);Matrix<float64>ev=matrixFilled<float64>(0,4,0.0);la.SVD<float64>ef=la.SVD<float64>(eu,es,ev);float64 inf=1.0/0.0;if(la.condition2(ef)!=inf){return 8;}
 Matrix<float64>zu=la.identity<float64>(2);Vector<float64,Column>zs=[1.0,0.0];Matrix<float64>zv=la.identity<float64>(2);la.SVD<float64>zf=la.SVD<float64>(zu,zs,zv);if(la.condition2(zf)!=inf){return 9;}
 Matrix<float32>u32=la.identity<float32>(2);Vector<float32,Column>s32=[float32(4.0),float32(1.0e-8)];Matrix<float32>v32=la.identity<float32>(2);la.SVD<float32>f32=la.SVD<float32>(u32,s32,v32);Vector<float32,Column>b32=[float32(8.0),float32(3.0)];
 if(la.numericalRank(f32)!=1||la.numericalRank(f32,float32(1.0e-8))!=1){return 10;}Matrix<float32>p32=la.pseudoInverse(f32,float32(1.0e-8));Vector<float32,Column>x32=la.leastSquares(f32,b32,float32(1.0e-8));if(p32[2,2]!=float32(0.0)||x32[2]!=float32(0.0)){return 11;}
 if(la.condition2(f32)!=float32(4.0e8)){return 12;}Matrix<float32>a32=la.lowRankApproximation(f32,2);if(a32[2,2]!=float32(1.0e-8)){return 13;}
 float64 zero=0.0;float64 nan=zero/zero;int caught=0;
 try{usize q=la.numericalRank(f,nan);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 try{Matrix<float64>q=la.pseudoInverse(f,nan);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 try{Vector<float64,Column>q=la.leastSquares(f,b,nan);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 Matrix<float64>bad=[nan];Vector<float64,Column>bb=[1.0];
 try{usize q=la.numericalRank(bad,-1.0);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 try{Matrix<float64>q=la.pseudoInverse(bad,-1.0);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 try{Vector<float64,Column>q=la.leastSquares(bad,bb,-1.0);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 if(caught!=6){return 14;}return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn pseudoinverse_and_least_squares_agree_with_minimum_norm_and_residuals() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 Matrix<float64>a=[1.0,1.0];Vector<float64,Column>b=[2.0];la.SVD<float64>f=la.svd(a);
 Vector<float64,Column>xm=la.leastSquares(a,b);Vector<float64,Column>xf=la.leastSquares(f,b);Matrix<float64>pm=la.pseudoInverse(a);Matrix<float64>pf=la.pseudoInverse(f);Vector<float64,Column>om=matrix_view(pm)*vector_view(b);Vector<float64,Column>of=matrix_view(pf)*vector_view(b);
 if(abs(xm[1]-om[1])>1.0e-12||abs(xm[2]-om[2])>1.0e-12||abs(xf[1]-of[1])>1.0e-12||abs(xf[2]-of[2])>1.0e-12){return 1;}
 float64 t=3.0;float64 norm=xm[1]*xm[1]+xm[2]*xm[2];float64 other=(xm[1]+t)*(xm[1]+t)+(xm[2]-t)*(xm[2]-t);if(norm>other||abs(a[1,1]*xm[1]+a[1,2]*xm[2]-b[1])>1.0e-12){return 2;}
 Matrix<float64>tall=[1.0,0.0;0.0,1.0;1.0,1.0];Vector<float64,Column>rhs=[1.0,2.0,4.0];Vector<float64,Column>x=la.leastSquares(tall,rhs);float64 r1=x[1]-1.0;float64 r2=x[2]-2.0;float64 r3=x[1]+x[2]-4.0;if(abs(r1+r3)>1.0e-10||abs(r2+r3)>1.0e-10){return 3;}
 Matrix<float32>a32=[float32(1.0),float32(1.0)];Vector<float32,Column>b32=[float32(2.0)];la.SVD<float32>f32=la.svd(a32);Vector<float32,Column>x32=la.leastSquares(f32,b32);Matrix<float32>p32=la.pseudoInverse(f32);Vector<float32,Column>o32=matrix_view(p32)*vector_view(b32);if(abs(x32[1]-o32[1])>float32(2.0e-5)||abs(x32[2]-o32[2])>float32(2.0e-5)){return 4;}
 if(a[1,1]!=1.0||b[1]!=2.0||f.S[1]<=0.0||a32[1,2]!=float32(1.0)){return 5;}return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn eckart_young_oracle_covers_square_tall_wide_and_both_precisions() {
    let cases = [
        (
            3,
            3,
            vec![5.0, 0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 1.0],
            2,
            false,
        ),
        (4, 2, vec![1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 2.0, 6.0], 1, false),
        (2, 4, vec![3.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0], 1, true),
    ];
    let mut source =
        String::from("package consumer;import linearAlgebra as la;int main(){int failed=0;");
    for (index, (rows, columns, values, rank, float32)) in cases.iter().enumerate() {
        let (expected, spectral, frobenius) =
            numpy_low_rank(*rows, *columns, values, *rank, *float32);
        let scalar = if *float32 { "float32" } else { "float64" };
        let tolerance = if *float32 {
            "float32(8.0e-4)"
        } else {
            "2.0e-10"
        };
        let one = if *float32 { "float32(1.0)" } else { "1.0" };
        let actual = matrix_literal(*rows, *columns, values, *float32);
        let oracle = matrix_literal(*rows, *columns, &expected, *float32);
        let spectral = if *float32 {
            format!("float32({spectral:.17e})")
        } else {
            format!("{spectral:.17e}")
        };
        let frobenius = if *float32 {
            format!("float32({frobenius:.17e})")
        } else {
            format!("{frobenius:.17e}")
        };
        writeln!(source, "Matrix<{scalar}>a{index}={actual};la.SVD<{scalar}>f{index}=la.svd(a{index});Matrix<{scalar}>x{index}=la.lowRankApproximation(f{index},{rank});Matrix<{scalar}>e{index}={oracle};usize i{index}=1;while(i{index}<=rows(x{index})){{usize j{index}=1;while(j{index}<=columns(x{index})){{if(abs(x{index}[i{index},j{index}]-e{index}[i{index},j{index}])>{tolerance}*({one}+abs(e{index}[i{index},j{index}]))){{failed=failed+1;}}j{index}=j{index}+1;}}i{index}=i{index}+1;}}if(abs(la.lowRankSpectralError(f{index},{rank})-{spectral})>{tolerance}*({one}+abs({spectral}))){{failed=failed+1;}}if(abs(la.lowRankFrobeniusError(f{index},{rank})-{frobenius})>{tolerance}*({one}+abs({frobenius}))){{failed=failed+1;}}").unwrap();
    }
    source.push_str("return failed;}");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(&source, optimization);
    }
}

#[test]
fn empty_shapes_and_structurally_valid_manual_factors_preserve_extents() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){float64 inf=1.0/0.0;
 Matrix<float64>m0=matrixFilled<float64>(3,0,0.0);Vector<float64,Column>b3=vectorFilled<float64,Column>(3,1.0);Matrix<float64>p0=la.pseudoInverse(m0);Vector<float64,Column>x0=la.leastSquares(m0,b3);Matrix<float64>l0=la.lowRankApproximation(m0,0);if(rows(p0)!=0||columns(p0)!=3||dimension(x0)!=0||rows(l0)!=3||columns(l0)!=0||la.numericalRank(m0)!=0||la.condition2(m0)!=inf){return 1;}
 Matrix<float64>n0=matrixFilled<float64>(0,4,0.0);Vector<float64,Column>b0=vectorFilled<float64,Column>(0,0.0);Matrix<float64>pn=la.pseudoInverse(n0);Vector<float64,Column>xn=la.leastSquares(n0,b0);Matrix<float64>ln=la.lowRankApproximation(n0,0);if(rows(pn)!=4||columns(pn)!=0||dimension(xn)!=4||xn[1]!=0.0||rows(ln)!=0||columns(ln)!=4||la.lowRankSpectralError(n0,0)!=0.0||la.lowRankFrobeniusError(n0,0)!=0.0){return 2;}
 Matrix<float64>z=matrixFilled<float64>(0,0,0.0);Matrix<float64>pz=la.pseudoInverse(z);Vector<float64,Column>xz=la.leastSquares(z,b0);if(rows(pz)!=0||dimension(xz)!=0||la.numericalRank(z)!=0||la.condition2(z)!=inf){return 3;}
 Matrix<float64>u=[1.0,0.0;0.0,1.0;0.0,0.0];Vector<float64,Column>s=[4.0,1.0];Matrix<float64>v=[1.0,0.0,0.0,0.0;0.0,1.0,0.0,0.0];la.SVD<float64>f=la.SVD<float64>(u,s,v);Vector<float64,Column>b=[8.0,3.0,9.0];Matrix<float64>p=la.pseudoInverse(f);Vector<float64,Column>x=la.leastSquares(f,b);Matrix<float64>l=la.lowRankApproximation(f,2);if(rows(p)!=4||columns(p)!=3||dimension(x)!=4||x[1]!=2.0||x[2]!=3.0||rows(l)!=3||columns(l)!=4||l[1,1]!=4.0||l[2,2]!=1.0||la.numericalRank(f)!=2||la.condition2(f)!=4.0){return 4;}
 if(la.lowRankSpectralError(f,1)!=1.0||la.lowRankFrobeniusError(f,1)!=1.0||f.S[1]!=4.0||b[3]!=9.0){return 5;}return 0;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn one_public_svd_feeds_the_whole_family_without_hidden_allocations() {
    let source = r"package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[4.0,0.0;0.0,2.0];Vector<float64,Column>b=[8.0,6.0];la.SVD<float64>f=la.svd(a);Matrix<float64>p=la.pseudoInverse(f);Vector<float64,Column>x=la.leastSquares(f,b);usize r=la.numericalRank(f);float64 c=la.condition2(f);Matrix<float64>l=la.lowRankApproximation(f,1);float64 se=la.lowRankSpectralError(f,1);float64 fe=la.lowRankFrobeniusError(f,1);if(p[1,1]!=0.25||x[1]!=2.0||x[2]!=3.0||r!=2||c!=2.0||l[1,1]!=4.0||l[2,2]!=0.0||se!=2.0||fe!=2.0||a[2,2]!=2.0||b[2]!=6.0||f.S[1]!=4.0){return 1;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization, &[Emit::Mir, Emit::Ssa, Emit::Llvm]);
        if optimization == OptimizationLevel::O0 {
            assert_eq!(svd_call_count(&compilation.llvm), 1);
        }
        for phase in [Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(!dump.contains("GenericParam("), "{phase:?}");
            assert!(!dump.contains("witness"), "{phase:?}");
            assert!(!dump.contains("vtable"), "{phase:?}");
        }
        for forbidden in [
            "TypeId",
            "LAPACK",
            "pseudoinverse_opcode",
            "least_squares_opcode",
            "rank_opcode",
            "cond_opcode",
            "low_rank_opcode",
        ] {
            assert!(!compilation.llvm.contains(forbidden), "{forbidden}");
        }
        assert_eq!(
            status_llvm(&allocation_guard(&compilation.llvm, 12), optimization).code(),
            Some(0),
            "{optimization:?}"
        );
    }
}

#[test]
fn every_matrix_route_factorizes_once_and_forbidden_couplings_are_absent() {
    let source = r"package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[4.0,0.0;0.0,2.0];Vector<float64,Column>b=[8.0,6.0];Matrix<float64>B=[8.0,4.0;6.0,2.0];Matrix<float64>p1=la.pseudoInverse(a);Matrix<float64>p2=la.pseudoInverse(a,0.0);Vector<float64,Column>x1=la.leastSquares(a,b);Vector<float64,Column>x2=la.leastSquares(a,b,0.0);Matrix<float64>X1=la.leastSquares(a,B);Matrix<float64>X2=la.leastSquares(a,B,0.0);usize r1=la.numericalRank(a);usize r2=la.numericalRank(a,0.0);float64 c=la.condition2(a);Matrix<float64>l=la.lowRankApproximation(a,1);float64 se=la.lowRankSpectralError(a,1);float64 fe=la.lowRankFrobeniusError(a,1);if(p1[1,1]!=0.25||p2[2,2]!=0.5||x1[1]!=2.0||x2[2]!=3.0||X1[1,1]!=2.0||X2[2,2]!=1.0||r1!=2||r2!=2||c!=2.0||l[1,1]!=4.0||se!=2.0||fe!=2.0){return 1;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization, &[Emit::Llvm]);
        if optimization == OptimizationLevel::O0 {
            assert_eq!(svd_call_count(&compilation.llvm), 12);
        }
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }

    let least_squares = LIBRARY
        .split("// Apply the retained thin-SVD prefix directly to one right-hand side.")
        .nth(1)
        .unwrap()
        .split("// Effective rank under the same shared policy")
        .next()
        .unwrap();
    assert!(!least_squares.contains("pseudoInverse<"));
    assert!(!least_squares.contains("normalEquation"));

    let condition = LIBRARY
        .split("public T condition2<T: IEEEFloat>(ref SVD<T> factor) {")
        .nth(1)
        .unwrap()
        .split("public T condition2<T: IEEEFloat>(ref Matrix<T> A)")
        .next()
        .unwrap();
    for forbidden in ["cutoff", "retainedSingularValueCount", "epsilon<"] {
        assert!(!condition.contains(forbidden), "{forbidden}");
    }

    let low_rank = LIBRARY
        .split("public Matrix<T> lowRankApproximation<T: IEEEFloat>(\n    ref SVD<T> factor,")
        .nth(1)
        .unwrap()
        .split("public class RankDeficientMatrixException")
        .next()
        .unwrap();
    for forbidden in [
        "numericalRank",
        "retainedSingularValueCount",
        "epsilon<",
        "cutoff",
    ] {
        assert!(!low_rank.contains(forbidden), "{forbidden}");
    }
    assert_eq!(low_rank.matches("SVD<T> factor = svd<T>(A);").count(), 3);
}

#[test]
fn structural_guards_precede_invalid_cutoffs() {
    let sources = [
        "package consumer;import linearAlgebra as la;int main(){float64 z=0.0;Matrix<float64>u=matrixFilled<float64>(1,1,0.0);Vector<float64,Column>s=[1.0,0.0];Matrix<float64>v=matrixFilled<float64>(2,1,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);Matrix<float64>x=la.pseudoInverse(f,z/z);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){float64 z=0.0;Matrix<float64>a=[1.0];Vector<float64,Column>b=[1.0,2.0];Vector<float64,Column>x=la.leastSquares(a,b,z/z);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){float64 z=0.0;Matrix<float64>u=matrixFilled<float64>(1,1,0.0);Vector<float64,Column>s=[1.0,0.0];Matrix<float64>v=matrixFilled<float64>(2,1,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);usize x=la.numericalRank(f,z/z);return int(x);}",
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
