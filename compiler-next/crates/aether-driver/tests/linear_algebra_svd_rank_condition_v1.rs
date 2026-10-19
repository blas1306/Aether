//! LINEAR-ALGEBRA-SVD-RANK-CONDITION-V1 public, numeric, resource, and IR qualification.

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
            "aether-svd-rank-condition-{label}-{}-{}",
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

fn numpy_condition(rows: usize, columns: usize, values: &[f64], float32: bool) -> f64 {
    let script = r#"
import sys
import numpy as np
rows, columns = map(int, sys.stdin.readline().split())
dtype = np.float32 if sys.argv[1] == "32" else np.float64
values = np.fromstring(sys.stdin.readline(), sep=" ", dtype=dtype)
print(format(float(np.linalg.cond(values.reshape((rows, columns)), 2)), ".17e"))
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
        writeln!(input, "{rows} {columns}").unwrap();
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
    String::from_utf8(output.stdout)
        .unwrap()
        .trim()
        .parse()
        .unwrap()
}

#[test]
fn numerical_rank_uses_shared_default_and_explicit_policy_for_both_types() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 Matrix<float64>u=matrixFilled<float64>(2,4,0.0);Matrix<float64>v=matrixFilled<float64>(4,2,0.0);
 Vector<float64,Column>s=[1.0,4.440892098500627e-16,4.440892098500626e-16,4.4408920985006257e-16];
 la.SVD<float64>f=la.SVD<float64>(u,s,v);
 if(la.numericalRank(f)!=2){return 1;}
 if(la.numericalRank(f,4.440892098500626e-16)!=2){return 2;}
 if(la.numericalRank(f,4.440892098500627e-16)!=1){return 3;}
 if(la.numericalRank(f,0.0)!=4||la.numericalRank(f,-0.0)!=4){return 4;}

 Matrix<float64>nu=matrixFilled<float64>(2,2,0.0);Matrix<float64>nv=matrixFilled<float64>(2,2,0.0);
 Vector<float64,Column>ns=[1.0,1.0e-20];la.SVD<float64>nf=la.SVD<float64>(nu,ns,nv);
 if(la.nonzeroSingularValueCount(nf)!=2||la.numericalRank(nf)!=1){return 5;}
 Matrix<float64>pinv=la.pseudoInverse(nf);Vector<float64,Column>b=[2.0,3.0];Vector<float64,Column>x=la.leastSquares(nf,b);
 if(pinv[2,2]!=0.0||x[2]!=0.0){return 6;}

 Matrix<float64>zu=matrixFilled<float64>(2,2,0.0);Matrix<float64>zv=matrixFilled<float64>(2,2,0.0);
 Vector<float64,Column>zs=[0.0,-0.0];la.SVD<float64>zf=la.SVD<float64>(zu,zs,zv);
 if(la.numericalRank(zf)!=0||la.numericalRank(zf,0.0)!=0){return 7;}
 Matrix<float64>ru=matrixFilled<float64>(2,2,0.0);Matrix<float64>rv=matrixFilled<float64>(2,2,0.0);
 Vector<float64,Column>rs=[4.0,4.0];la.SVD<float64>rf=la.SVD<float64>(ru,rs,rv);
 if(la.numericalRank(rf)!=2){return 8;}
 Matrix<float64>tu=matrixFilled<float64>(2,2,0.0);Matrix<float64>tv=matrixFilled<float64>(2,2,0.0);
 Vector<float64,Column>ts=[1.0e-308,5.0e-324];la.SVD<float64>tf=la.SVD<float64>(tu,ts,tv);
 if(la.numericalRank(tf)!=2){return 9;}

 Matrix<float32>u32=matrixFilled<float32>(2,4,float32(0.0));Matrix<float32>v32=matrixFilled<float32>(4,2,float32(0.0));
 Vector<float32,Column>s32=[float32(1.0),float32(2.3841860752327193e-7),float32(2.384185791015625e-7),float32(2.3841856489070778e-7)];
 la.SVD<float32>f32=la.SVD<float32>(u32,s32,v32);
 if(la.numericalRank(f32)!=2||la.numericalRank(f32,float32(2.384185791015625e-7))!=2){return 10;}
 Matrix<float32>t32u=matrixFilled<float32>(2,2,float32(0.0));Matrix<float32>t32v=matrixFilled<float32>(2,2,float32(0.0));
 Vector<float32,Column>t32s=[float32(5.0e-39),float32(1.0e-45)];la.SVD<float32>t32f=la.SVD<float32>(t32u,t32s,t32v);
 if(la.numericalRank(t32f)!=2){return 11;}
 return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn numerical_rank_matrix_empty_zero_and_cutoff_validation_contract() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 Matrix<float64>a=[3.0,0.0;0.0,2.0;0.0,0.0];
 if(la.numericalRank(a)!=2||la.numericalRank(a,2.0)!=1){return 1;}
 Matrix<float64>z=matrixFilled<float64>(2,3,0.0);if(la.numericalRank(z)!=0){return 2;}
 Matrix<float64>a00=matrixFilled<float64>(0,0,0.0);Matrix<float64>am0=matrixFilled<float64>(3,0,0.0);Matrix<float64>a0n=matrixFilled<float64>(0,4,0.0);
 if(la.numericalRank(a00)!=0||la.numericalRank(am0)!=0||la.numericalRank(a0n)!=0){return 3;}
 float64 zero=0.0;float64 nan=zero/zero;float64 inf=1.0/zero;int caught=0;
 try{usize q=la.numericalRank(a,-1.0);}catch(la.InvalidSingularValueCutoffException error){caught=caught+1;}
 try{usize q=la.numericalRank(a,nan);}catch(la.InvalidSingularValueCutoffException error){caught=caught+1;}
 try{usize q=la.numericalRank(a,inf);}catch(la.InvalidSingularValueCutoffException error){caught=caught+1;}
 try{usize q=la.numericalRank(a,-inf);}catch(la.InvalidSingularValueCutoffException error){caught=caught+1;}
 Matrix<float64>u=[1.0];Vector<float64,Column>s=[1.0];Matrix<float64>v=[1.0];la.SVD<float64>f=la.SVD<float64>(u,s,v);
 try{usize q=la.numericalRank(f,nan);}catch(la.InvalidSingularValueCutoffException error){caught=caught+1;}
 if(caught!=5){return 4;}
 return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }

    let invalid_factors = [
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=matrixFilled<float64>(1,1,0.0);Vector<float64,Column>s=[1.0,0.0];Matrix<float64>v=matrixFilled<float64>(2,1,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);return int(la.numericalRank(f));}",
        "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=matrixFilled<float64>(1,2,0.0);Vector<float64,Column>s=[1.0,0.0];Matrix<float64>v=matrixFilled<float64>(1,1,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);float64 c=la.condition2(f);return int(c);}",
    ];
    for source in invalid_factors {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization, &[Emit::Llvm]);
            assert_ne!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
        }
    }
}

#[test]
fn condition2_uses_the_complete_thin_spectrum_without_cutoff() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 float64 zero=0.0;float64 inf=1.0/zero;
 Matrix<float64>u=matrixFilled<float64>(4,3,0.0);Matrix<float64>v=matrixFilled<float64>(3,5,0.0);
 Vector<float64,Column>s=[10.0,2.0,1.0];la.SVD<float64>f=la.SVD<float64>(u,s,v);
 if(la.condition2(f)!=10.0){return 1;}
 Matrix<float64>du=matrixFilled<float64>(4,3,0.0);Matrix<float64>dv=matrixFilled<float64>(3,5,0.0);
 Vector<float64,Column>ds=[10.0,2.0,0.0];la.SVD<float64>df=la.SVD<float64>(du,ds,dv);if(la.condition2(df)!=inf){return 2;}
 Matrix<float64>ou=[1.0];Matrix<float64>ov=[1.0];Vector<float64,Column>tiny=[5.0e-324];la.SVD<float64>tf=la.SVD<float64>(ou,tiny,ov);if(la.condition2(tf)!=1.0){return 3;}
 Matrix<float64>nu=[1.0];Matrix<float64>nv=[1.0];Vector<float64,Column>one=[1.0e-20];la.SVD<float64>nf=la.SVD<float64>(nu,one,nv);if(la.condition2(nf)!=1.0||la.numericalRank(nf)!=1){return 4;}
 Matrix<float64>eu=matrixFilled<float64>(3,0,0.0);Vector<float64,Column>es=vectorFilled<float64,Column>(0,0.0);Matrix<float64>ev=matrixFilled<float64>(0,7,0.0);la.SVD<float64>ef=la.SVD<float64>(eu,es,ev);if(la.condition2(ef)!=inf){return 5;}
 Matrix<float64>ru=matrixFilled<float64>(4,3,0.0);Matrix<float64>rv=matrixFilled<float64>(3,5,0.0);
 Vector<float64,Column>rep=[4.0,4.0,4.0];la.SVD<float64>rf=la.SVD<float64>(ru,rep,rv);if(la.condition2(rf)!=1.0){return 6;}
 Matrix<float64>hu=matrixFilled<float64>(2,2,0.0);Matrix<float64>hv=matrixFilled<float64>(2,2,0.0);
 Vector<float64,Column>large=[1.0e200,1.0e-100];la.SVD<float64>lf=la.SVD<float64>(hu,large,hv);if(abs(la.condition2(lf)/1.0e300-1.0)>1.0e-15){return 7;}
 Matrix<float64>ofu=matrixFilled<float64>(2,2,0.0);Matrix<float64>ofv=matrixFilled<float64>(2,2,0.0);
 Vector<float64,Column>overflow=[1.0e308,1.0e-308];la.SVD<float64>of=la.SVD<float64>(ofu,overflow,ofv);if(la.condition2(of)!=inf){return 8;}
 Matrix<float64>a=[3.0,0.0,0.0;0.0,1.0,0.0];if(abs(la.condition2(a)-3.0)>1.0e-12){return 9;}
 Matrix<float64>z=matrixFilled<float64>(2,3,0.0);if(la.condition2(z)!=inf){return 10;}
 Matrix<float64>a00=matrixFilled<float64>(0,0,0.0);Matrix<float64>am0=matrixFilled<float64>(3,0,0.0);Matrix<float64>a0n=matrixFilled<float64>(0,4,0.0);
 if(la.condition2(a00)!=inf||la.condition2(am0)!=inf||la.condition2(a0n)!=inf){return 11;}
 Matrix<float32>u32=[float32(1.0)];Vector<float32,Column>s32=[float32(1.0e-40)];Matrix<float32>v32=[float32(1.0)];la.SVD<float32>f32=la.SVD<float32>(u32,s32,v32);
 if(la.condition2(f32)!=float32(1.0)){return 12;}
 if(f.S[1]!=10.0||rows(f.U)!=4||columns(f.Vt)!=5){return 13;}
 return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn matrix_routes_inherit_svd_nonfinite_rejection() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){float64 z=0.0;float64 nan=z/z;Matrix<float64>a=[1.0,nan];int caught=0;
 try{usize r=la.numericalRank(a);}catch(la.NonFiniteMatrixException error){caught=caught+1;}
 try{float64 c=la.condition2(a);}catch(la.NonFiniteMatrixException error){caught=caught+1;}
 return caught-2;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn numpy_lapack_oracle_matches_matrix_condition_definition() {
    let cases = [
        (3, 2, vec![1.0, 2.0, 3.0, 5.0, 7.0, 11.0], false),
        (2, 3, vec![1.0, 2.0, 4.0, 3.0, 5.0, 7.0], true),
    ];
    for (rows, columns, values, float32) in cases {
        let expected = numpy_condition(rows, columns, &values, float32);
        let scalar = if float32 { "float32" } else { "float64" };
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
        let tolerance = if float32 {
            expected * 3.0e-4
        } else {
            expected * 1.0e-11
        };
        let expected_literal = if float32 {
            format!("float32({expected:.17e})")
        } else {
            format!("{expected:.17e}")
        };
        let tolerance_literal = if float32 {
            format!("float32({tolerance:.17e})")
        } else {
            format!("{tolerance:.17e}")
        };
        let source = format!(
            "package consumer;import linearAlgebra as la;int main(){{Matrix<{scalar}>a={literal};{scalar} actual=la.condition2(a);if(abs(actual-{expected_literal})>{tolerance_literal}){{return 1;}}return 0;}}"
        );
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            run(&source, optimization);
        }
    }
}

#[test]
fn factor_queries_allocate_nothing_and_lower_without_svd_or_runtime_magic() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=[1.0,0.0;0.0,1.0];Vector<float64,Column>s=[2.0,1.0e-20];Matrix<float64>v=[1.0,0.0;0.0,1.0];la.SVD<float64>f=la.SVD<float64>(u,s,v);usize r=la.numericalRank(f);usize z=la.numericalRank(f,0.0);float64 c=la.condition2(f);if(r!=1||z!=2||c!=2.0e20){return 1;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization, &[Emit::Mir, Emit::Ssa, Emit::Llvm]);
        assert_eq!(
            status_llvm(&allocation_guard(&compilation.llvm, 3), optimization).code(),
            Some(0),
            "{optimization:?}"
        );
        assert!(!compilation.llvm.contains("assembleSVDWorkspace__gfFloat64"));
        assert!(!compilation.llvm.contains("f3_svd__gfFloat64"));
        for phase in [Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(!dump.contains("GenericParam("), "{phase:?}");
            assert!(!dump.contains("witness"), "{phase:?}");
            assert!(!dump.contains("vtable"), "{phase:?}");
        }
        for forbidden in ["TypeId", "LAPACK", "rank_opcode", "cond_opcode"] {
            assert!(!compilation.llvm.contains(forbidden), "{forbidden}");
        }
        assert!(compilation.llvm.contains("numericalRank"));
        assert!(compilation.llvm.contains("condition2"));
        assert!(compilation.llvm.contains("__gfFloat64"));
    }
}

#[test]
fn public_surface_delegation_and_constant_time_condition_are_closed() {
    assert_eq!(LIBRARY.matches("public usize numericalRank<").count(), 4);
    assert_eq!(LIBRARY.matches("public T condition2<").count(), 2);
    assert_eq!(
        LIBRARY
            .matches("public usize nonzeroSingularValueCount<")
            .count(),
        1
    );
    assert!(!LIBRARY.contains("effectiveCondition2"));

    let factor_rank = LIBRARY
        .split("public usize numericalRank<T: IEEEFloat>(ref SVD<T> factor) {")
        .nth(1)
        .unwrap()
        .split("public usize numericalRank<T: IEEEFloat>(ref SVD<T> factor, T cutoff)")
        .next()
        .unwrap();
    assert!(factor_rank.contains("return retainedSingularValueCount<T>(factor);"));
    assert!(!factor_rank.contains("svd<"));

    let factor_condition = LIBRARY
        .split("public T condition2<T: IEEEFloat>(ref SVD<T> factor) {")
        .nth(1)
        .unwrap()
        .split("public T condition2<T: IEEEFloat>(ref Matrix<T> A)")
        .next()
        .unwrap();
    assert!(factor_condition.contains("guardSVDFactorShapes<T>(factor);"));
    assert!(factor_condition.contains("return one / zero;"));
    assert!(factor_condition.contains("T sigmaMax = (*factor).S[1];"));
    assert!(factor_condition.contains("return sigmaMax / sigmaMin;"));
    assert!(!factor_condition.contains("while"));
    assert!(!factor_condition.contains("retainedSingularValueCount"));
    assert!(!factor_condition.contains("svd<"));

    let matrix_routes = LIBRARY
        .split("public usize numericalRank<T: IEEEFloat>(ref Matrix<T> A) {")
        .nth(1)
        .unwrap()
        .split("public class RankDeficientMatrixException")
        .next()
        .unwrap();
    assert_eq!(
        matrix_routes.matches("SVD<T> factor = svd<T>(A);").count(),
        3
    );

    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[2.0,0.0;0.0,1.0];usize r1=la.numericalRank(a);usize r2=la.numericalRank(a,0.0);float64 c=la.condition2(a);Matrix<float32>b=[float32(3.0)];la.SVD<float32>f=la.svd(b);usize r3=la.numericalRank(f);float32 d=la.condition2(f);if(r1!=2||r2!=2||r3!=1||c!=2.0||d!=float32(1.0)){return 1;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization, &[Emit::Mir, Emit::Ssa, Emit::Llvm]);
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
        assert!(compilation.llvm.contains("numericalRank"));
        assert!(compilation.llvm.contains("condition2"));
        assert!(compilation.llvm.contains("__gfFloat64"));
        assert!(compilation.llvm.contains("__gfFloat32"));
    }
}
