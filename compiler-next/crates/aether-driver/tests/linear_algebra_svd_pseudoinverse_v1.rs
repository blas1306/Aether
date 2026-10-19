//! LINEAR-ALGEBRA-SVD-PSEUDOINVERSE-V1 public, numeric, resource, and IR qualification.

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
            "aether-svd-pseudoinverse-{label}-{}-{}",
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

/// Independent test-only NumPy/LAPACK oracle. The product source and linked
/// Aether executable never import or link it. Default rcond is reproduced on
/// the host as max(m,n)*finfo(dtype).eps; explicit absolute cutoff is converted
/// to `NumPy`'s relative rcond using the oracle's largest singular value.
fn numpy_pinv(
    rows: usize,
    columns: usize,
    values: &[f64],
    float32: bool,
    cutoff: Option<f64>,
) -> Vec<f64> {
    let script = r#"
import sys
import numpy as np
rows, columns = map(int, sys.stdin.readline().split())
dtype = np.float32 if sys.argv[1] == "32" else np.float64
values = np.fromstring(sys.stdin.readline(), sep=" ", dtype=dtype)
a = values.reshape((rows, columns))
s = np.linalg.svd(a, compute_uv=False)
if sys.argv[2] == "default":
    rcond = max(rows, columns) * np.finfo(dtype).eps
else:
    cutoff = float(sys.argv[2])
    rcond = cutoff / float(s[0]) if s.size and s[0] != 0 else 0.0
p = np.linalg.pinv(a, rcond=rcond)
print(" ".join(format(float(value), ".17e") for value in p.ravel()))
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
        .split_whitespace()
        .map(|value| value.parse().unwrap())
        .collect()
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

#[test]
fn numpy_pinv_oracle_matches_default_and_explicit_cutoff_for_both_types() {
    let cases = [
        (3, 2, vec![1.0, 2.0, 3.0, 5.0, 7.0, 11.0], false, None),
        (2, 2, vec![4.0, 0.0, 0.0, 0.75], false, Some(0.75)),
        (2, 3, vec![1.0, 2.0, 4.0, 3.0, 5.0, 7.0], true, None),
        (2, 2, vec![3.0, 0.0, 0.0, 1.0], true, Some(1.0)),
    ];
    let mut source =
        String::from("package consumer;import linearAlgebra as la;int main(){int failed=0;");
    for (index, (rows, columns, values, float32, cutoff)) in cases.iter().enumerate() {
        let expected = numpy_pinv(*rows, *columns, values, *float32, *cutoff);
        let scalar = if *float32 { "float32" } else { "float64" };
        let tolerance = if *float32 {
            "float32(8.0e-4)"
        } else {
            "2.0e-11"
        };
        let one = if *float32 { "float32(1.0)" } else { "1.0" };
        let matrix = matrix_literal(*rows, *columns, values, *float32);
        let oracle = matrix_literal(*columns, *rows, &expected, *float32);
        let call = cutoff.map_or_else(
            || format!("la.pseudoInverse(a{index})"),
            |value| {
                if *float32 {
                    format!("la.pseudoInverse(a{index},float32({value:.17e}))")
                } else {
                    format!("la.pseudoInverse(a{index},{value:.17e})")
                }
            },
        );
        writeln!(
            source,
            "Matrix<{scalar}>a{index}={matrix};Matrix<{scalar}>p{index}={call};Matrix<{scalar}>e{index}={oracle};usize i{index}=1;while(i{index}<=rows(p{index})){{usize j{index}=1;while(j{index}<=columns(p{index})){{if(abs(p{index}[i{index},j{index}]-e{index}[i{index},j{index}])>{tolerance}*({one}+abs(e{index}[i{index},j{index}]))){{failed=failed+1;}}j{index}=j{index}+1;}}i{index}=i{index}+1;}}"
        )
        .unwrap();
    }
    source.push_str("return failed;}");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(&source, optimization);
    }
}

#[test]
fn moore_penrose_identities_and_all_required_numeric_classes_pass_at_o0_o2() {
    let source = r"
package consumer;import linearAlgebra as la;
int validate64(ref Matrix<float64>a,float64 tolerance){
 Matrix<float64>p=la.pseudoInverse(a);if(rows(p)!=columns(*a)||columns(p)!=rows(*a)){return 1;}
 Matrix<float64>ap=matrix_view(*a)*matrix_view(p);Matrix<float64>pa=matrix_view(p)*matrix_view(*a);
 Matrix<float64>apa=matrix_view(ap)*matrix_view(*a);Matrix<float64>pap=matrix_view(pa)*matrix_view(p);
 usize i=1;while(i<=rows(*a)){usize j=1;while(j<=columns(*a)){if(abs(apa[i,j]-(*a)[i,j])>tolerance*(1.0+abs((*a)[i,j]))){return 2;}j=j+1;}i=i+1;}
 i=1;while(i<=rows(p)){usize j=1;while(j<=columns(p)){if(abs(pap[i,j]-p[i,j])>tolerance*(1.0+abs(p[i,j]))){return 3;}j=j+1;}i=i+1;}
 i=1;while(i<=rows(ap)){usize j=1;while(j<=columns(ap)){if(abs(ap[i,j]-ap[j,i])>tolerance*(1.0+abs(ap[i,j]))){return 4;}j=j+1;}i=i+1;}
 i=1;while(i<=rows(pa)){usize j=1;while(j<=columns(pa)){if(abs(pa[i,j]-pa[j,i])>tolerance*(1.0+abs(pa[i,j]))){return 5;}j=j+1;}i=i+1;}return 0;
}
int validate32(ref Matrix<float32>a,float32 tolerance){
 Matrix<float32>p=la.pseudoInverse(a);if(rows(p)!=columns(*a)||columns(p)!=rows(*a)){return 1;}
 Matrix<float32>ap=matrix_view(*a)*matrix_view(p);Matrix<float32>pa=matrix_view(p)*matrix_view(*a);
 Matrix<float32>apa=matrix_view(ap)*matrix_view(*a);Matrix<float32>pap=matrix_view(pa)*matrix_view(p);
 usize i=1;while(i<=rows(*a)){usize j=1;while(j<=columns(*a)){if(abs(apa[i,j]-(*a)[i,j])>tolerance*(float32(1.0)+abs((*a)[i,j]))){return 2;}j=j+1;}i=i+1;}
 i=1;while(i<=rows(p)){usize j=1;while(j<=columns(p)){if(abs(pap[i,j]-p[i,j])>tolerance*(float32(1.0)+abs(p[i,j]))){return 3;}j=j+1;}i=i+1;}
 i=1;while(i<=rows(ap)){usize j=1;while(j<=columns(ap)){if(abs(ap[i,j]-ap[j,i])>tolerance*(float32(1.0)+abs(ap[i,j]))){return 4;}j=j+1;}i=i+1;}
 i=1;while(i<=rows(pa)){usize j=1;while(j<=columns(pa)){if(abs(pa[i,j]-pa[j,i])>tolerance*(float32(1.0)+abs(pa[i,j]))){return 5;}j=j+1;}i=i+1;}return 0;
}
int main(){
 Matrix<float64>s=[4.0,1.0;2.0,3.0];if(validate64(&s,2.0e-11)!=0){return 1;}
 Matrix<float64>t=[1.0,2.0;3.0,4.0;5.0,7.0];if(validate64(&t,8.0e-11)!=0){return 2;}
 Matrix<float64>w=[1.0,2.0,3.0;4.0,5.0,7.0];if(validate64(&w,8.0e-11)!=0){return 3;}
 Matrix<float64>d=[1.0,2.0,3.0;2.0,4.0,6.0;0.0,0.0,0.0];if(validate64(&d,2.0e-10)!=0){return 4;}
 Matrix<float64>z=matrixFilled<float64>(3,2,0.0);if(validate64(&z,1.0e-12)!=0){return 5;}
 Matrix<float64>r=[5.0,0.0,0.0;0.0,-5.0,0.0;0.0,0.0,2.0];if(validate64(&r,2.0e-11)!=0){return 6;}
 Matrix<float64>large=[1.0e150,0.0;0.0,-2.0e150];if(validate64(&large,2.0e-11)!=0){return 7;}
 Matrix<float64>small=[1.0e-150,0.0;0.0,-2.0e-150];if(validate64(&small,2.0e-11)!=0){return 8;}
 Matrix<float32>sf=[float32(4.0),float32(1.0);float32(2.0),float32(3.0)];if(validate32(&sf,float32(8.0e-4))!=0){return 9;}
 Matrix<float32>tf=[float32(1.0),float32(2.0);float32(3.0),float32(4.0);float32(5.0),float32(7.0)];if(validate32(&tf,float32(2.0e-3))!=0){return 10;}
 Matrix<float32>wf=[float32(1.0),float32(2.0),float32(3.0);float32(4.0),float32(5.0),float32(7.0)];if(validate32(&wf,float32(2.0e-3))!=0){return 11;}
 Matrix<float32>df=[float32(1.0),float32(2.0);float32(2.0),float32(4.0)];if(validate32(&df,float32(3.0e-3))!=0){return 12;}
 Matrix<float32>lf=[float32(1.0e20),float32(0.0);float32(0.0),float32(-2.0e20)];if(validate32(&lf,float32(2.0e-3))!=0){return 13;}
 Matrix<float32>smf=[float32(1.0e-20),float32(0.0);float32(0.0),float32(-2.0e-20)];if(validate32(&smf,float32(2.0e-3))!=0){return 14;}
 Matrix<float32>zf=matrixFilled<float32>(2,3,float32(0.0));if(validate32(&zf,float32(1.0e-5))!=0){return 15;}
 Matrix<float32>rf=[float32(3.0),float32(0.0);float32(0.0),float32(-3.0)];if(validate32(&rf,float32(8.0e-4))!=0){return 16;}
 return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn cutoff_empty_shape_manual_factor_and_ieee_semantics_are_exact() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 Matrix<float64>tiny=[1.0,0.0;0.0,1.0e-20];Matrix<float64>td=la.pseudoInverse(tiny);if(abs(td[1,1]-1.0)>1.0e-12||td[2,2]!=0.0){return 1;}
 Matrix<float64>c=[4.0,0.0;0.0,1.0];Matrix<float64>cp=la.pseudoInverse(c,1.0);if(abs(cp[1,1]-0.25)>1.0e-12||cp[2,2]!=0.0){return 2;}
 Matrix<float64>cz=la.pseudoInverse(c,0.0);if(abs(cz[1,1]-0.25)>1.0e-12||abs(cz[2,2]-1.0)>1.0e-12){return 3;}
 Matrix<float32>tiny32=[float32(1.0),float32(0.0);float32(0.0),float32(1.0e-8)];Matrix<float32>tiny32p=la.pseudoInverse(tiny32);if(abs(tiny32p[1,1]-float32(1.0))>float32(1.0e-5)||tiny32p[2,2]!=float32(0.0)){return 14;}
 Matrix<float32>cz32=la.pseudoInverse(tiny32,float32(0.0));if(abs(cz32[2,2]-float32(1.0e8))>float32(64.0)){return 15;}
 Matrix<float64>u=[1.0;0.0;0.0];Vector<float64,Column>sv=[2.0];Matrix<float64>vt=[0.0,1.0,0.0,0.0];la.SVD<float64>f=la.SVD<float64>(u,sv,vt);
 Matrix<float64>fp=la.pseudoInverse(f);if(rows(fp)!=4||columns(fp)!=3||fp[2,1]!=0.5){return 4;}
 Matrix<float64>fp2=la.pseudoInverse(f,0.0);if(fp2[2,1]!=0.5||f.S[1]!=2.0){return 5;}
 Matrix<float64>m0=matrixFilled<float64>(4,0,0.0);Matrix<float64>pm0=la.pseudoInverse(m0);if(rows(pm0)!=0||columns(pm0)!=4){return 6;}
 Matrix<float64>z0n=matrixFilled<float64>(0,5,0.0);Matrix<float64>p0n=la.pseudoInverse(z0n);if(rows(p0n)!=5||columns(p0n)!=0){return 7;}
 Matrix<float64>z00=matrixFilled<float64>(0,0,0.0);Matrix<float64>p00=la.pseudoInverse(z00);if(rows(p00)!=0||columns(p00)!=0){return 8;}
 Matrix<float64>pu=matrixFilled<float64>(3,0,0.0);Vector<float64,Column>ps=vectorFilled<float64,Column>(0,0.0);Matrix<float64>pv=matrixFilled<float64>(0,4,0.0);la.SVD<float64>pf=la.SVD<float64>(pu,ps,pv);Matrix<float64>pp=la.pseudoInverse(pf);if(rows(pp)!=4||columns(pp)!=3||pp[1,1]!=0.0){return 9;}
 float64 zero=0.0;float64 nan=zero/zero;float64 inf=1.0/zero;int caught=0;
 try{Matrix<float64>x=la.pseudoInverse(z00,-1.0);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 try{Matrix<float64>x=la.pseudoInverse(z00,nan);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 try{Matrix<float64>x=la.pseudoInverse(z00,inf);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 try{Matrix<float64>x=la.pseudoInverse(z00,-inf);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}
 Matrix<float64>bad=[nan];try{Matrix<float64>x=la.pseudoInverse(bad,-1.0);}catch(la.InvalidSingularValueCutoffException e){caught=caught+1;}catch(la.NonFiniteMatrixException e){return 10;}
 if(caught!=5){return 11;}
 Matrix<float64>ru=[1.0e-308];Vector<float64,Column>rs=[1.0e-308];Matrix<float64>rv=[1.0];la.SVD<float64>rf=la.SVD<float64>(ru,rs,rv);Matrix<float64>rp=la.pseudoInverse(rf,0.0);if(abs(rp[1,1]-1.0)>1.0e-15){return 12;}
 Matrix<float64>iu=[1.0];Vector<float64,Column>is=[5.0e-324];Matrix<float64>iv=[1.0];la.SVD<float64>ifactor=la.SVD<float64>(iu,is,iv);Matrix<float64>ip=la.pseudoInverse(ifactor,0.0);if(ip[1,1]!=inf){return 13;}
 return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn factor_shape_guards_precede_cutoff_validation() {
    let source = "package consumer;import linearAlgebra as la;int main(){float64 z=0.0;Matrix<float64>u=matrixFilled<float64>(1,1,0.0);Vector<float64,Column>s=[1.0,0.0];Matrix<float64>v=matrixFilled<float64>(2,1,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);Matrix<float64>p=la.pseudoInverse(f,z/z);return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization, &[Emit::Llvm]);
        let instrumented = compilation.llvm.replace(
            "trap_shape_mismatch:\n  ; structured Aether trap: ShapeMismatch\n  call void @llvm.trap()",
            "trap_shape_mismatch:\n  call void @exit(i32 73)",
        ) + "\ndeclare void @exit(i32)\n";
        assert_eq!(status_llvm(&instrumented, optimization).code(), Some(73));
    }
}

#[test]
fn allocations_reuse_and_empty_outputs_match_the_contract() {
    let cases = [
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=la.identity<float64>(2);Vector<float64,Column>s=[2.0,1.0];Matrix<float64>v=la.identity<float64>(2);la.SVD<float64>f=la.SVD<float64>(u,s,v);Matrix<float64>p1=la.pseudoInverse(f);Matrix<float64>p2=la.pseudoInverse(f,1.0);return int(p1[1,1]+p2[1,1]-1.0);}",
            5,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[2.0,0.0;0.0,1.0];Matrix<float64>p=la.pseudoInverse(a);return int(p[1,1]+p[2,2]-1.5);}",
            9,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=matrixFilled<float64>(4,0,0.0);Vector<float64,Column>s=vectorFilled<float64,Column>(0,0.0);Matrix<float64>v=matrixFilled<float64>(0,0,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);Matrix<float64>p=la.pseudoInverse(f);return int(rows(p)+columns(p)-4);}",
            0,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=matrixFilled<float64>(4,0,0.0);Vector<float64,Column>s=vectorFilled<float64,Column>(0,0.0);Matrix<float64>v=matrixFilled<float64>(0,6,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);Matrix<float64>p=la.pseudoInverse(f);return int(rows(p)+columns(p)-10);}",
            1,
        ),
    ];
    for (source, expected) in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization, &[Emit::Llvm]);
            if expected == 5 {
                // Both calls consume a precomputed factor: SVD is unreachable
                // from the emitted program in either optimization mode.
                assert!(!compilation.llvm.contains("assembleSVDWorkspace__gfFloat64"));
                assert!(!compilation.llvm.contains("f3_svd__gfFloat64"));
            }
            if expected == 9 && optimization == OptimizationLevel::O0 {
                // The Matrix overload performs one source-level SVD call. At
                // O0 it remains one direct IR call (O2 may inline it).
                let svd_lines = compilation
                    .llvm
                    .lines()
                    .filter(|line| line.contains("svd"))
                    .collect::<Vec<_>>();
                assert_eq!(
                    svd_lines
                        .iter()
                        .filter(|line| line.contains(" call ") || line.contains(" invoke "))
                        .count(),
                    1,
                    "{svd_lines:#?}"
                );
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
fn public_surface_kernel_shape_and_lowering_are_closed() {
    assert_eq!(
        LIBRARY.matches("public Matrix<T> pseudoInverse<").count(),
        4
    );
    for forbidden in [
        "pseudoInverseExact",
        "pseudoInverseInPlace",
        "SigmaPlus",
        "numpy",
        "LAPACK",
    ] {
        assert!(!LIBRARY.contains(forbidden), "{forbidden}");
    }
    assert!(LIBRARY.contains("T scaledV = (*factor).Vt[r,j] / sigma;"));
    assert!(LIBRARY.contains("T contribution = scaledV * (*factor).U[i,r];"));
    assert_eq!(LIBRARY.matches("SVD<T> factor = svd<T>(A);").count(), 2);

    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[2.0,0.0;0.0,1.0];la.SVD<float64>f=la.svd(a);Matrix<float64>p1=la.pseudoInverse(f);Matrix<float64>p2=la.pseudoInverse(f,0.0);Matrix<float64>p3=la.pseudoInverse(a);Matrix<float64>p4=la.pseudoInverse(a,0.0);Matrix<float32>b=[float32(1.0)];la.SVD<float32>g=la.svd(b);Matrix<float32>q=la.pseudoInverse(g);return int(p1[1,1]+p2[1,1]+p3[1,1]+p4[1,1]+q[1,1]-3.0);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization, &[Emit::Mir, Emit::Ssa, Emit::Llvm]);
        for phase in [Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(!dump.contains("GenericParam("), "{phase:?}");
            assert!(!dump.contains("witness"), "{phase:?}");
            assert!(!dump.contains("vtable"), "{phase:?}");
        }
        for forbidden in ["TypeId", "LAPACK", "pseudoinverse_opcode"] {
            assert!(!compilation.llvm.contains(forbidden), "{forbidden}");
        }
        assert!(
            compilation
                .llvm
                .contains("pseudoInverseRetained__gfFloat64")
        );
        assert!(
            compilation
                .llvm
                .contains("pseudoInverseRetained__gfFloat32")
        );
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }
}
