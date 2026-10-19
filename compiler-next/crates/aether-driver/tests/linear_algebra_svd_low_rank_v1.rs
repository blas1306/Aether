//! LINEAR-ALGEBRA-SVD-LOW-RANK-V1 public, numeric, resource, and IR qualification.

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
            "aether-svd-low-rank-{label}-{}-{}",
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

/// Independent qualification-only NumPy/LAPACK oracle.  It constructs the
/// truncated SVD and computes the two tail errors outside product code.
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
fn exact_prefix_rank_zero_full_rank_deficiency_and_empty_shapes() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 Matrix<float64>u=[1.0,0.0;0.0,1.0;0.0,0.0];Vector<float64,Column>s=[4.0,0.0];Matrix<float64>v=[1.0,0.0,0.0;0.0,1.0,0.0];la.SVD<float64>f=la.SVD<float64>(u,s,v);
 if(la.numericalRank(f)!=1){return 1;}
 Matrix<float64>a0=la.lowRankApproximation(f,0);Matrix<float64>a1=la.lowRankApproximation(f,1);Matrix<float64>a2=la.lowRankApproximation(f,2);
 if(rows(a0)!=3||columns(a0)!=3||a0[1,1]!=0.0||a0[2,2]!=0.0){return 2;}
 if(a1[1,1]!=4.0||a1[2,2]!=0.0||a2[1,1]!=4.0||a2[2,2]!=0.0){return 3;}
 if(la.lowRankSpectralError(f,0)!=4.0||la.lowRankSpectralError(f,1)!=0.0||la.lowRankSpectralError(f,2)!=0.0){return 4;}
 if(la.lowRankFrobeniusError(f,0)!=4.0||la.lowRankFrobeniusError(f,1)!=0.0||la.lowRankFrobeniusError(f,2)!=0.0){return 5;}
 Matrix<float64>eu=matrixFilled<float64>(3,0,0.0);Vector<float64,Column>es=vectorFilled<float64,Column>(0,0.0);Matrix<float64>ev=matrixFilled<float64>(0,4,0.0);la.SVD<float64>ef=la.SVD<float64>(eu,es,ev);
 Matrix<float64>empty=la.lowRankApproximation(ef,0);if(rows(empty)!=3||columns(empty)!=4||la.lowRankSpectralError(ef,0)!=0.0||la.lowRankFrobeniusError(ef,0)!=0.0){return 6;}
 Matrix<float64>ru=[1.0,0.0;0.0,1.0];Vector<float64,Column>rs=[3.0,3.0];Matrix<float64>rv=[1.0,0.0;0.0,1.0];la.SVD<float64>rf=la.SVD<float64>(ru,rs,rv);Matrix<float64>rr1=la.lowRankApproximation(rf,1);Matrix<float64>rr2=la.lowRankApproximation(rf,2);
 if(rr1[1,1]!=3.0||rr1[2,2]!=0.0||rr2[1,1]!=3.0||rr2[2,2]!=3.0||la.lowRankSpectralError(rf,1)!=3.0){return 7;}
 Matrix<float64>a00=matrixFilled<float64>(0,0,0.0);Matrix<float64>am0=matrixFilled<float64>(2,0,0.0);Matrix<float64>a0n=matrixFilled<float64>(0,3,0.0);
 Matrix<float64>r00=la.lowRankApproximation(a00,0);Matrix<float64>rm0=la.lowRankApproximation(am0,0);Matrix<float64>r0n=la.lowRankApproximation(a0n,0);
 if(rows(r00)!=0||columns(r00)!=0||rows(rm0)!=2||columns(rm0)!=0||rows(r0n)!=0||columns(r0n)!=3){return 8;}
 if(la.lowRankSpectralError(am0,0)!=0.0||la.lowRankFrobeniusError(a0n,0)!=0.0){return 9;}
 if(f.S[1]!=4.0||f.U[1,1]!=1.0||f.Vt[1,1]!=1.0){return 10;}
 return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn numpy_oracle_covers_square_tall_wide_repeated_and_both_precisions() {
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
        writeln!(source, "Matrix<{scalar}>a{index}={actual};la.SVD<{scalar}>f{index}=la.svd(a{index});Matrix<{scalar}>x{index}=la.lowRankApproximation(f{index},{rank});Matrix<{scalar}>y{index}=la.lowRankApproximation(a{index},{rank});Matrix<{scalar}>e{index}={oracle};usize i{index}=1;while(i{index}<=rows(x{index})){{usize j{index}=1;while(j{index}<=columns(x{index})){{if(abs(x{index}[i{index},j{index}]-e{index}[i{index},j{index}])>{tolerance}*({one}+abs(e{index}[i{index},j{index}]))){{failed=failed+1;}}if(abs(y{index}[i{index},j{index}]-e{index}[i{index},j{index}])>{tolerance}*({one}+abs(e{index}[i{index},j{index}]))){{failed=failed+1;}}j{index}=j{index}+1;}}i{index}=i{index}+1;}}if(abs(la.lowRankSpectralError(f{index},{rank})-{spectral})>{tolerance}*({one}+abs({spectral}))){{failed=failed+1;}}if(abs(la.lowRankFrobeniusError(a{index},{rank})-{frobenius})>{tolerance}*({one}+abs({frobenius}))){{failed=failed+1;}}if(a{index}[1,1]!={scalar}({:.17e})){{failed=failed+1;}}", values[0]).unwrap();
    }
    source.push_str("return failed;}");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(&source, optimization);
    }
}

#[test]
fn stable_tail_norm_handles_extreme_scales_without_squares() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 Matrix<float64>u=matrixFilled<float64>(2,2,0.0);Matrix<float64>v=matrixFilled<float64>(2,2,0.0);Vector<float64,Column>s=[1.0e308,1.0e308];la.SVD<float64>f=la.SVD<float64>(u,s,v);
 float64 e=la.lowRankFrobeniusError(f,0);if(!(e>1.4e308)||e==1.0/0.0){return 1;}
 Matrix<float64>tu=matrixFilled<float64>(2,2,0.0);Matrix<float64>tv=matrixFilled<float64>(2,2,0.0);Vector<float64,Column>t=[1.0e-200,1.0e-200];la.SVD<float64>g=la.SVD<float64>(tu,t,tv);float64 q=la.lowRankFrobeniusError(g,0);if(!(q>1.4e-200)||!(q<1.5e-200)){return 2;}
 Matrix<float32>u32=matrixFilled<float32>(2,2,float32(0.0));Matrix<float32>v32=matrixFilled<float32>(2,2,float32(0.0));Vector<float32,Column>s32=[float32(2.0e38),float32(2.0e38)];la.SVD<float32>f32=la.SVD<float32>(u32,s32,v32);float32 e32=la.lowRankFrobeniusError(f32,0);if(!(e32>float32(2.8e38))||e32==float32(1.0)/float32(0.0)){return 3;}
 return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn invalid_rank_and_factor_shapes_trap_with_normative_guard_order() {
    let invalid = [
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=[1.0];Vector<float64,Column>s=[1.0];Matrix<float64>v=[1.0];la.SVD<float64>f=la.SVD<float64>(u,s,v);Matrix<float64>x=la.lowRankApproximation(f,2);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=[1.0];Vector<float64,Column>s=[1.0];Matrix<float64>v=[1.0];la.SVD<float64>f=la.SVD<float64>(u,s,v);float64 x=la.lowRankSpectralError(f,2);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=[1.0];Vector<float64,Column>s=[1.0];Matrix<float64>v=[1.0];la.SVD<float64>f=la.SVD<float64>(u,s,v);float64 x=la.lowRankFrobeniusError(f,2);return 0;}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=matrixFilled<float64>(1,1,0.0);Vector<float64,Column>s=[1.0,0.0];Matrix<float64>v=matrixFilled<float64>(2,1,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);Matrix<float64>x=la.lowRankApproximation(f,3);return 0;}",
    ];
    for source in invalid {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization, &[Emit::Llvm]);
            assert_ne!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
        }
    }

    for name in [
        "lowRankApproximation",
        "lowRankSpectralError",
        "lowRankFrobeniusError",
    ] {
        let factor = LIBRARY
            .split(&format!(
                "public {}<T: IEEEFloat>(\n    ref SVD<T> factor,",
                if name == "lowRankApproximation" {
                    "Matrix<T> lowRankApproximation"
                } else if name == "lowRankSpectralError" {
                    "T lowRankSpectralError"
                } else {
                    "T lowRankFrobeniusError"
                }
            ))
            .nth(1)
            .unwrap();
        let guards = factor.find("guardSVDFactorShapes<T>(factor);").unwrap();
        let rank_guard = factor.find("shapeGuard(rank <= p);").unwrap();
        assert!(guards < rank_guard, "{name}");
    }
}

#[test]
fn factor_routes_meet_allocation_and_ir_contracts() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=[1.0,0.0;0.0,1.0];Vector<float64,Column>s=[4.0,3.0];Matrix<float64>v=[1.0,0.0;0.0,1.0];la.SVD<float64>f=la.SVD<float64>(u,s,v);Matrix<float64>x=la.lowRankApproximation(f,1);float64 a=la.lowRankSpectralError(f,1);float64 b=la.lowRankFrobeniusError(f,1);if(x[1,1]!=4.0||x[2,2]!=0.0||a!=3.0||b!=3.0){return 1;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization, &[Emit::Mir, Emit::Ssa, Emit::Llvm]);
        assert_eq!(
            status_llvm(&allocation_guard(&compilation.llvm, 4), optimization).code(),
            Some(0)
        );
        assert!(!compilation.llvm.contains("assembleSVDWorkspace__gfFloat64"));
        assert!(!compilation.llvm.contains("f3_svd__gfFloat64"));
        for phase in [Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(!dump.contains("GenericParam("), "{phase:?}");
            assert!(!dump.contains("witness"), "{phase:?}");
            assert!(!dump.contains("vtable"), "{phase:?}");
        }
        for forbidden in [
            "TypeId",
            "LAPACK",
            "low_rank_opcode",
            "retainedSingularValueCount",
        ] {
            assert!(!compilation.llvm.contains(forbidden), "{forbidden}");
        }
    }

    let matrix_routes = [
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[4.0,0.0;0.0,3.0];Matrix<float64>x=la.lowRankApproximation(a,1);return int(x[1,1]-4.0);}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[4.0,0.0;0.0,3.0];float64 x=la.lowRankSpectralError(a,1);return int(x-3.0);}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[4.0,0.0;0.0,3.0];float64 x=la.lowRankFrobeniusError(a,1);return int(x-3.0);}",
    ];
    for source in matrix_routes {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization, &[Emit::Llvm]);
            if optimization == OptimizationLevel::O0 {
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
            assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
        }
    }
}

#[test]
fn public_surface_delegation_kernel_and_optimality_are_closed() {
    assert_eq!(
        LIBRARY
            .matches("public Matrix<T> lowRankApproximation<")
            .count(),
        2
    );
    assert_eq!(LIBRARY.matches("public T lowRankSpectralError<").count(), 2);
    assert_eq!(
        LIBRARY.matches("public T lowRankFrobeniusError<").count(),
        2
    );

    let family = LIBRARY
        .split("// Reconstruct exactly the requested prefix of a thin SVD.")
        .nth(1)
        .unwrap()
        .split("public class RankDeficientMatrixException")
        .next()
        .unwrap();
    assert_eq!(family.matches("SVD<T> factor = svd<T>(A);").count(), 3);
    assert!(family.contains("T scaledU = (*factor).U[i,r] * sigma;"));
    assert!(family.contains("T contribution = scaledU * (*factor).Vt[r,j];"));
    assert!(family.contains("stableNormRange<T>(vector_view((*factor).S), rank + 1, p)"));
    for forbidden in [
        "numericalRank",
        "retainedSingularValueCount",
        "epsilon<",
        "cutoff",
        "Matrix<T> residual",
        "Matrix<T> Sigma",
    ] {
        assert!(!family.contains(forbidden), "{forbidden}");
    }

    // A small independent Eckart--Young/Mirsky optimality witness.  Altering
    // one retained singular coefficient keeps rank two but makes both residual
    // norms strictly worse than the truncated SVD for diag(5,3,1).
    let output = Command::new("python3")
        .args(["-c", "import numpy as np\na=np.diag([5.,3.,1.])\nu,s,vt=np.linalg.svd(a,full_matrices=False)\nak=(u[:,:2]*s[:2])@vt[:2,:]\nc=(u[:,:2]*np.array([2.5,3.]))@vt[:2,:]\nr=a-ak\nq=a-c\nassert np.linalg.matrix_rank(c)<=2\nassert np.linalg.norm(r,2)<np.linalg.norm(q,2)\nassert np.linalg.norm(r,'fro')<np.linalg.norm(q,'fro')"])
        .output()
        .expect("qualification requires python3 with NumPy");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}
