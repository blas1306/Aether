//! LINEAR-ALGEBRA-SVD-ASSEMBLY-V1 public and white-box qualification.

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
            "aether-svd-assembly-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn white_box(&self, source: &str) -> PathBuf {
        let path = self.0.join("linearAlgebra.ae");
        fs::write(&path, format!("{LIBRARY}\n{source}\n")).unwrap();
        path
    }

    fn imported(&self, source: &str) -> PathBuf {
        fs::write(self.0.join("linearAlgebra.ae"), LIBRARY).unwrap();
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

fn run_imported(source: &str, optimization: OptimizationLevel) {
    let directory = Directory::new("public");
    let entry = directory.imported(source);
    let compilation = compile_session_with_optimization(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Llvm],
        optimization,
    )
    .unwrap();
    let executable = directory.0.join("qualification");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    assert_eq!(
        Command::new(executable).status().unwrap().code(),
        Some(0),
        "{optimization:?}"
    );
}

fn run_white_box(source: &str, optimization: OptimizationLevel) {
    let directory = Directory::new("white-box");
    let entry = directory.white_box(source);
    let compilation = compile_session_with_optimization(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Llvm],
        optimization,
    )
    .unwrap();
    let executable = directory.0.join("qualification");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    assert_eq!(Command::new(executable).status().unwrap().code(), Some(0));
}

#[test]
fn public_thin_preserving_svd_works_for_both_float_types_and_empty_shapes() {
    let source = r"
package consumer;import linearAlgebra as la;
int validate64(ref Matrix<float64>a,float64 tolerance){
 usize m=rows(*a);usize n=columns(*a);usize k=m;if(n<k){k=n;}la.SVD<float64>f=la.svd(a);
 if(rows(f.U)!=m||columns(f.U)!=k||dimension(f.S)!=k||rows(f.Vt)!=k||columns(f.Vt)!=n){return 1;}
 usize i=1;while(i<=k){if(f.S[i]<0.0||(i>1&&f.S[i-1]<f.S[i])){return 2;}usize j=1;while(j<=k){float64 uu=0.0;float64 vv=0.0;usize q=1;
  while(q<=m){uu=uu+f.U[q,i]*f.U[q,j];q=q+1;}q=1;while(q<=n){vv=vv+f.Vt[i,q]*f.Vt[j,q];q=q+1;}float64 wanted=0.0;if(i==j){wanted=1.0;}
  if(abs(uu-wanted)>tolerance||abs(vv-wanted)>tolerance){return 3;}j=j+1;}i=i+1;}
 i=1;while(i<=m){usize j=1;while(j<=n){float64 value=0.0;usize q=1;while(q<=k){value=value+f.U[i,q]*f.S[q]*f.Vt[q,j];q=q+1;}
  if(abs(value-(*a)[i,j])>tolerance*(1.0+abs((*a)[i,j]))){return 4;}j=j+1;}i=i+1;}return 0;
}
int main(){
 Matrix<float64>a=[3.0,1.0;0.0,2.0];int x=validate64(&a,2.0e-11);if(x!=0){return x;}if(a[1,1]!=3.0||a[1,2]!=1.0){return 5;}
 la.SVD<float64>oracle=la.svd(a);if(abs(oracle.S[1]-sqrt(7.0+sqrt(13.0)))>2.0e-12||abs(oracle.S[2]-sqrt(7.0-sqrt(13.0)))>2.0e-12){return 6;}
 Matrix<float64>t=[1.0,2.0;3.0,4.0;5.0,6.0;7.0,8.0;9.0,10.0];x=validate64(&t,5.0e-11);if(x!=0){return 10+x;}
 Matrix<float64>w=[1.0,2.0,3.0,4.0,5.0;2.0,4.0,6.0,8.0,10.0];x=validate64(&w,5.0e-11);if(x!=0){return 20+x;}
 Matrix<float64>z=matrixFilled<float64>(3,2,0.0);x=validate64(&z,1.0e-12);if(x!=0){return 30+x;}
 Matrix<float64>e00=matrixFilled<float64>(0,0,0.0);var f00=la.svd(e00);if(rows(f00.U)!=0||columns(f00.U)!=0||dimension(f00.S)!=0||rows(f00.Vt)!=0||columns(f00.Vt)!=0){return 40;}
 Matrix<float64>em0=matrixFilled<float64>(4,0,0.0);var fm0=la.svd(em0);if(rows(fm0.U)!=4||columns(fm0.U)!=0||dimension(fm0.S)!=0||rows(fm0.Vt)!=0||columns(fm0.Vt)!=0){return 41;}
 Matrix<float64>e0n=matrixFilled<float64>(0,4,0.0);var f0n=la.svd(e0n);if(rows(f0n.U)!=0||columns(f0n.U)!=0||dimension(f0n.S)!=0||rows(f0n.Vt)!=0||columns(f0n.Vt)!=4){return 42;}
 Matrix<float32>s=[float32(-1.0),float32(0.0);float32(0.0),float32(4.0)];la.SVD<float32>fs=la.svd<float32>(s);if(fs.S[1]!=float32(4.0)||fs.S[2]!=float32(1.0)){return 43;}
 float64 q=0.0;Matrix<float64>bad=[1.0,q/q];int caught=0;try{var ignored=la.svd(bad);}catch(la.NonFiniteMatrixException error){caught=1;}if(caught!=1||bad[1,1]!=1.0){return 44;}
 Matrix<float64>inf=[1.0,1.0/q];caught=0;try{var ignored=la.svd(inf);}catch(la.NonFiniteMatrixException error){caught=1;}if(caught!=1){return 45;}
 Matrix<float64>negativeInf=[-1.0/q];caught=0;try{var ignored=la.svd(negativeInf);}catch(la.NonFiniteMatrixException error){caught=1;}if(caught!=1){return 46;}
 caught=0;try{throw la.NumericalConvergenceException();}catch(la.NumericalConvergenceException error){caught=1;}if(caught!=1){return 47;}
 return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run_imported(source, optimization);
    }
}

#[test]
fn sign_sort_correlated_permutation_and_exception_identity_are_exact() {
    let source = r"
int main(){
 Vector<float64,Column>s=[-0.0,-2.0,3.0,3.0];Matrix<float64>u=identity<float64>(4);Matrix<float64>v=identity<float64>(4);
 normalizeAndSortSVD<float64>(&mut s,&mut u,&mut v);
 if(s[1]!=3.0||s[2]!=3.0||s[3]!=2.0||s[4]!=0.0||1.0/s[4]!=1.0/0.0){return 1;}
 if(u[3,1]!=1.0||u[4,2]!=1.0||u[2,3]!=1.0||u[1,4]!=1.0){return 2;}
 if(v[1,3]!=1.0||v[2,4]!=1.0||v[3,2]!=-1.0||v[4,1]!=1.0){return 3;}
 float64 z=0.0;Vector<float64,Column>d=[3.0,2.0];Vector<float64,Column>e=[1.0];Matrix<float64>qu=identity<float64>(2);Matrix<float64>qv=identity<float64>(2);
 BidiagonalSVDSeed<float64>seed=BidiagonalSVDSeed<float64>(d,e,qu,qv,BidiagonalOrientation(false));int caught=0;
 try{var ignored=bidiagonalSVDQRWithMaxSteps<float64>(seed,0);}catch(NumericalConvergenceException error){caught=1;}if(caught!=1){return 4;}
 Vector<float64,Column>nanS=[z/z];Matrix<float64>one=[1.0];caught=0;try{validateFiniteSVDResult<float64>(&nanS,&one,&one);}catch(NumericalConvergenceException error){caught=1;}if(caught!=1){return 5;}
 return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run_white_box(source, optimization);
    }
}

#[test]
fn public_surface_and_lowering_are_closed() {
    let directory = Directory::new("visibility");
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0];var f=la.svdInPlace(a);return 0;}";
    let diagnostics = compile_session(
        CompilationSession::discover(&directory.imported(source)).unwrap(),
        &[],
    )
    .unwrap_err();
    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("unknown"))
    );

    let directory = Directory::new("lowering");
    let entry = directory.imported("package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0;3.0,4.0];la.SVD<float64>x=la.svd(a);Matrix<float32>b=[float32(2.0)];la.SVD<float32>y=la.svd(b);return int(dimension(x.S)+dimension(y.S)-3);}");
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    for residue in ["GenericParam(", "witness", "vtable"] {
        assert!(
            !compilation.dumps[&Emit::Mir].contains(residue),
            "MIR: {residue}"
        );
        assert!(
            !compilation.dumps[&Emit::Ssa].contains(residue),
            "SSA: {residue}"
        );
        assert!(!compilation.llvm.contains(residue), "LLVM: {residue}");
    }
    assert!(!compilation.llvm.contains("TypeId"));
    assert!(!compilation.llvm.contains("LAPACK"));
    assert!(compilation.llvm.contains("assembleSVDWorkspace__gfFloat64"));
    assert!(compilation.llvm.contains("assembleSVDWorkspace__gfFloat32"));
}
