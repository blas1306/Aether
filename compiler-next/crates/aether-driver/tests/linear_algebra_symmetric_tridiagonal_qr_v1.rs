//! LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-V1 internal qualification.

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
            "aether-symmetric-tridiagonal-qr-{label}-{}-{}",
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

fn compile_and_run(source: &str, optimization: OptimizationLevel) -> String {
    let directory = Directory::new("native");
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
    let output = Command::new(executable).output().unwrap();
    assert!(
        output.status.success(),
        "{optimization:?}: exit={:?}\nstdout={}\nstderr={}",
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap()
}

#[test]
fn private_surface_and_single_shared_authorities_are_exact() {
    for expression in [
        "int probe(la.SymmetricTridiagonalSeed<float64> x){return 0;}",
        "int probe(la.GivensRotation<float64> x){return 0;}",
        "int probe(Vector<float64,Column>d,Vector<float64,Column>e,Matrix<float64>q){return la.convergeSymmetricTridiagonalState(&mut d,&mut e,&mut q,1);}",
        "int probe(la.SymmetricTridiagonalSeed<float64> x){var y=la.symmetricTridiagonalQR(x);return 0;}",
    ] {
        let directory = Directory::new("visibility");
        let source = format!(
            "package consumer;import linearAlgebra as la;{expression}int main(){{return 0;}}"
        );
        let diagnostics = compile_session(
            CompilationSession::discover(&directory.imported(&source)).unwrap(),
            &[],
        )
        .unwrap_err();
        let text = diagnostics
            .iter()
            .map(|diagnostic| diagnostic.message.as_str())
            .collect::<Vec<_>>()
            .join("\n");
        assert!(
            text.contains("internal to its module") || text.contains("unknown"),
            "{text}"
        );
    }

    for declaration in [
        "struct GivensRotation<T: Storable>",
        "GivensRotation<T> givensRotation<T: IEEEFloat>",
        "void rotateColumnsByGivens<T: IEEEFloat>",
        "void deflateAdjacentOffDiagonal<T: IEEEFloat>",
        "TrailingActiveBlock selectTrailingActiveBlock<T: IEEEFloat>",
        "int convergeSymmetricTridiagonalState<T: IEEEFloat>",
        "symmetricTridiagonalQRWithMaxSweeps<T: IEEEFloat>",
        "symmetricTridiagonalQR<T: IEEEFloat>",
    ] {
        assert_eq!(LIBRARY.matches(declaration).count(), 1, "{declaration}");
    }
    for removed in [
        "BidiagonalGivens",
        "bidiagonalGivens",
        "rotateBidiagonalColumns",
        "rotateBidiagonalRows",
        "BidiagonalActiveBlock",
        "deflateBidiagonal",
        "selectBidiagonalBlock",
    ] {
        assert!(!LIBRARY.contains(removed), "{removed}");
    }

    let start = LIBRARY
        .find("int convergeSymmetricTridiagonalState<T: IEEEFloat>")
        .unwrap();
    let end = LIBRARY[start..]
        .find("BidiagonalShift<T> bidiagonalWilkinsonShift")
        .unwrap()
        + start;
    let phase = &LIBRARY[start..end];
    for forbidden in [
        "matrixFilled",
        "vectorFilled",
        "identity<",
        "Matrix<T> T",
        "Matrix<T> G",
        "bidiagonalWilkinsonShift",
        "chaseBidiagonalBulge",
        "qr<",
        "LAPACK",
        "BLAS",
    ] {
        assert!(!phase.contains(forbidden), "{forbidden}");
    }
    assert!(phase.contains("usize maxSweeps = 64 * n;"));
}

#[test]
fn exact_primitives_splitting_budget_shapes_and_failure_paths_work() {
    let source = r"
int activeCapFailure(){
 Vector<float64,Column>d=[2.0,5.0];Vector<float64,Column>e=[-3.0];Matrix<float64>q=identity<float64>(2);
 try{convergeSymmetricTridiagonalState<float64>(&mut d,&mut e,&mut q,0);}
 catch(NumericalConvergenceException error){return 0;}return 1;
}
int nonfiniteFailure(){
 float64 z=0.0;float64 nan=z/z;Vector<float64,Column>d=[nan,2.0];Vector<float64,Column>e=[1.0];Matrix<float64>q=identity<float64>(2);
 try{convergeSymmetricTridiagonalState<float64>(&mut d,&mut e,&mut q,1);}
 catch(NumericalConvergenceException error){return 0;}return 1;
}
int internalUpdateFailure(){
 Vector<float64,Column>d=[1.7976931348623157e308,1.7976931348623157e308];Vector<float64,Column>e=[1.7976931348623157e308];Matrix<float64>q=identity<float64>(2);
 try{convergeSymmetricTridiagonalState<float64>(&mut d,&mut e,&mut q,1);}
 catch(NumericalConvergenceException error){return 0;}return 1;
}
int internalAccumulationFailure(){
 Vector<float64,Column>d=[2.0,5.0];Vector<float64,Column>e=[-3.0];Matrix<float64>q=[1.7976931348623157e308,1.7976931348623157e308;1.7976931348623157e308,1.7976931348623157e308];
 try{convergeSymmetricTridiagonalState<float64>(&mut d,&mut e,&mut q,1);}
 catch(NumericalConvergenceException error){return 0;}return 1;
}
int minimalCap(){
 Vector<float64,Column>d=[2.0,5.0];Vector<float64,Column>e=[-3.0];Matrix<float64>q=identity<float64>(2);
 convergeSymmetricTridiagonalState<float64>(&mut d,&mut e,&mut q,1);if(e[1]!=0.0){return 1;}return 0;
}
int splitDoesNotResetBudget(){
 Vector<float64,Column>d=[2.0,5.0,1.0,4.0,9.0];Vector<float64,Column>e=[-3.0,0.0,2.0,0.0];Matrix<float64>q=identity<float64>(5);
 try{convergeSymmetricTridiagonalState<float64>(&mut d,&mut e,&mut q,1);}
 catch(NumericalConvergenceException error){return 0;}return 1;
}
int splitTwoSweeps(){
 Vector<float64,Column>d=[2.0,5.0,1.0,4.0,9.0];Vector<float64,Column>e=[-3.0,0.0,2.0,0.0];Matrix<float64>q=identity<float64>(5);
 convergeSymmetricTridiagonalState<float64>(&mut d,&mut e,&mut q,2);return 0;
}
int main(){
 float64 z=0.0;
 GivensRotation<float64>g=givensRotation<float64>(3.0,4.0);
 if(g.r!=5.0||abs(g.c*g.c+g.s*g.s-1.0)>1.0e-15||abs(-g.s*3.0+g.c*4.0)>1.0e-15){return 1;}
 g=givensRotation<float64>(-z,z);
 if(g.c!=1.0||g.s!=z||1.0/g.s!=1.0/z){return 2;}

 Vector<float64,Column>d=[4.0,2.0];float64 threshold=(epsilon<float64>()*4.0)*(1.0+0.5);
 Vector<float64,Column>e=[threshold];deflateAdjacentOffDiagonal<float64>(&d,&mut e,epsilon<float64>());
 if(e[1]!=z||1.0/e[1]!=1.0/z){return 3;}
 e=[1.3322676295501877e-15];deflateAdjacentOffDiagonal<float64>(&d,&mut e,epsilon<float64>());if(e[1]!=z){return 4;}
 e=[1.332267629550188e-15];deflateAdjacentOffDiagonal<float64>(&d,&mut e,epsilon<float64>());if(e[1]==z){return 4;}
 d=[z,-z];e=[-z];deflateAdjacentOffDiagonal<float64>(&d,&mut e,epsilon<float64>());if(1.0/e[1]!=1.0/z){return 5;}
 d=[1.0e308,-1.0e308];e=[1.0e290];deflateAdjacentOffDiagonal<float64>(&d,&mut e,epsilon<float64>());if(e[1]!=z){return 6;}
 d=[5.0e-324,1.0e-323];e=[5.0e-324];deflateAdjacentOffDiagonal<float64>(&d,&mut e,epsilon<float64>());if(e[1]==z){return 7;}
 Vector<float32,Column>fd=[float32(4.0),float32(2.0)];Vector<float32,Column>fe=[float32(7.1525574e-7)];
 deflateAdjacentOffDiagonal<float32>(&fd,&mut fe,epsilon<float32>());if(fe[1]!=float32(0.0)){return 7;}
 fe=[float32(7.152557e-7)];deflateAdjacentOffDiagonal<float32>(&fd,&mut fe,epsilon<float32>());if(fe[1]!=float32(0.0)){return 7;}
 fe=[float32(7.152558e-7)];deflateAdjacentOffDiagonal<float32>(&fd,&mut fe,epsilon<float32>());if(fe[1]==float32(0.0)){return 7;}

 d=[1.0,2.0,3.0,4.0,5.0];e=[1.0,z,2.0,z];TrailingActiveBlock b=selectTrailingActiveBlock<float64>(&d,&e);
 if(!b.active||b.lo!=3||b.hi!=4){return 8;}
 e=[1.0,z,z,z];b=selectTrailingActiveBlock<float64>(&d,&e);if(!b.active||b.lo!=1||b.hi!=2){return 9;}
 e=[z,z,z,z];b=selectTrailingActiveBlock<float64>(&d,&e);if(b.active){return 10;}

 d=[5.0,2.0];e=[1.0];var sm=symmetricTridiagonalWilkinsonShift<float64>(&d,&e,2);if(sm.muNormalized>=0.5){return 11;}
 d=[2.0,5.0];e=[-1.0];var sp=symmetricTridiagonalWilkinsonShift<float64>(&d,&e,2);if(sp.muNormalized<=0.5){return 12;}
 d=[2.0,2.0];e=[1.0];var se=symmetricTridiagonalWilkinsonShift<float64>(&d,&e,2);if(abs(se.muNormalized-0.5)>1.0e-15){return 13;}
 e=[-1.0];var sn=symmetricTridiagonalWilkinsonShift<float64>(&d,&e,2);if(sn.muNormalized!=se.muNormalized){return 14;}

 d=[-z,z];e=[-z];Matrix<float64>localQ=identity<float64>(2);chaseSymmetricTridiagonalBulge<float64>(&mut d,&mut e,&mut localQ,1,2,1.0,z);
 if(1.0/d[1]!=1.0/z||1.0/e[1]!=1.0/z||1.0/d[2]!=1.0/z){return 14;}

 if(activeCapFailure()!=0||nonfiniteFailure()!=0||internalUpdateFailure()!=0||internalAccumulationFailure()!=0||minimalCap()!=0||splitDoesNotResetBudget()!=0||splitTwoSweeps()!=0){return 15;}
 d=[3.0,2.0];e=[-z];Matrix<float64>q=identity<float64>(2);convergeSymmetricTridiagonalState<float64>(&mut d,&mut e,&mut q,0);
 if(1.0/e[1]!=1.0/z){return 16;}
 Vector<float64,Column>d0=vectorFilled<float64,Column>(0,z);Vector<float64,Column>e0=vectorFilled<float64,Column>(0,z);Matrix<float64>q0=matrixFilled<float64>(0,0,z);
 convergeSymmetricTridiagonalState<float64>(&mut d0,&mut e0,&mut q0,0);
 Vector<float64,Column>d1=[7.0];Vector<float64,Column>e1=vectorFilled<float64,Column>(0,z);Matrix<float64>q1=[-1.0];
 convergeSymmetricTridiagonalState<float64>(&mut d1,&mut e1,&mut q1,0);if(d1[1]!=7.0||q1[1,1]!=-1.0){return 17;}
 return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        compile_and_run(source, optimization);
    }
}

#[test]
fn converges_corpus_and_preserves_similarity_for_both_float_types() {
    let source = r"
int check64(Vector<float64,Column>d,Vector<float64,Column>e,Matrix<float64>q0,float64 tolerance){
 usize n=dimension(d);Vector<float64,Column>d0=vectorFilled<float64,Column>(n,0.0);Vector<float64,Column>e0=vectorFilled<float64,Column>(dimension(e),0.0);
 usize i=1;while(i<=n){d0[i]=d[i];i=i+1;}i=1;while(i<=dimension(e)){e0[i]=e[i];i=i+1;}
 Matrix<float64>q0copy=matrixFilled<float64>(n,n,0.0);i=1;while(i<=n){usize j=1;while(j<=n){q0copy[i,j]=q0[i,j];j=j+1;}i=i+1;}
 SymmetricTridiagonalSeed<float64>s=SymmetricTridiagonalSeed<float64>(d,e,q0);var result=symmetricTridiagonalQR<float64>(s);
 i=1;while(i<=dimension(result.e)){if(result.e[i]!=0.0||1.0/result.e[i]!=1.0/0.0){return 1;}i=i+1;}
 i=1;while(i<=n){usize j=1;while(j<=n){float64 orth=0.0;usize k=1;while(k<=n){orth=orth+result.vectors[k,i]*result.vectors[k,j];k=k+1;}float64 wanted=0.0;if(i==j){wanted=1.0;}if(abs(orth-wanted)>2.0e-11){return 2;}j=j+1;}i=i+1;}
 // Z=Q0^T*Q, then compare Z^T*T0*Z with diag(d).
 i=1;while(i<=n){usize j=1;while(j<=n){float64 transformed=0.0;usize r=1;while(r<=n){float64 zir=0.0;float64 zrj=0.0;
   usize k=1;while(k<=n){zir=zir+q0copy[k,r]*result.vectors[k,i];zrj=zrj+q0copy[k,r]*result.vectors[k,j];k=k+1;}
   float64 tz=d0[r]*zrj;if(r>1){float64 zprev=0.0;k=1;while(k<=n){zprev=zprev+q0copy[k,r-1]*result.vectors[k,j];k=k+1;}tz=tz+e0[r-1]*zprev;}
   if(r<n){float64 znext=0.0;k=1;while(k<=n){znext=znext+q0copy[k,r+1]*result.vectors[k,j];k=k+1;}tz=tz+e0[r]*znext;}
   transformed=transformed+zir*tz;r=r+1;}
  float64 wanted=0.0;if(i==j){wanted=result.d[i];}if(abs(transformed-wanted)>tolerance*(1.0+abs(wanted))){return 3;}j=j+1;}i=i+1;}return 0;
}
int check32(Vector<float32,Column>d,Vector<float32,Column>e,float32 tolerance){
 usize n=dimension(d);Matrix<float32>q=identity<float32>(n);Vector<float32,Column>d0=vectorFilled<float32,Column>(n,float32(0.0));Vector<float32,Column>e0=vectorFilled<float32,Column>(dimension(e),float32(0.0));usize i=1;
 while(i<=n){d0[i]=d[i];i=i+1;}i=1;while(i<=dimension(e)){e0[i]=e[i];i=i+1;}var s=symmetricTridiagonalQR<float32>(SymmetricTridiagonalSeed<float32>(d,e,q));
 i=1;while(i<=dimension(s.e)){if(s.e[i]!=float32(0.0)){return 1;}i=i+1;}i=1;while(i<=n){usize j=1;while(j<=n){float32 value=float32(0.0);usize r=1;while(r<=n){float32 tz=d0[r]*s.vectors[r,j];if(r>1){tz=tz+e0[r-1]*s.vectors[r-1,j];}if(r<n){tz=tz+e0[r]*s.vectors[r+1,j];}value=value+s.vectors[r,i]*tz;r=r+1;}float32 wanted=float32(0.0);if(i==j){wanted=s.d[i];}if(abs(value-wanted)>tolerance*(float32(1.0)+abs(wanted))){return 2;}j=j+1;}i=i+1;}return 0;
}
int main(){
 int x=0;
 x=check64([2.0,5.0],[-3.0],identity<float64>(2),2.0e-12);if(x!=0){return 10+x;}
 x=check64([2.0,5.0],[-3.0],[0.0,-1.0;1.0,0.0],2.0e-12);if(x!=0){return 15+x;}
 x=check64([1.0,2.0,3.0],[0.5,-0.75],identity<float64>(3),4.0e-12);if(x!=0){return 20+x;}
 x=check64([0.0,-3.0,1.0],[2.0,1.0],identity<float64>(3),4.0e-12);if(x!=0){return 30+x;}
 x=check64([2.0,2.0,2.0,2.0],[0.0,1.0e-8,0.0],identity<float64>(4),5.0e-12);if(x!=0){return 40+x;}
 x=check64([4.0,4.000000000001,4.000000000002],[1.0e-7,-1.0e-7],identity<float64>(3),8.0e-12);if(x!=0){return 50+x;}
 x=check64([1.0,-1.0,0.5,-0.5,3.0],[0.25,-0.75,1.25,-0.5],identity<float64>(5),1.0e-11);if(x!=0){return 60+x;}
 x=check64([1.0e200,-1.0e200,5.0e199],[2.0e199,-3.0e199],identity<float64>(3),2.0e187);if(x!=0){return 70+x;}
 x=check64([1.0e-200,-1.0e-200,5.0e-201],[2.0e-201,-3.0e-201],identity<float64>(3),1.0e-212);if(x!=0){return 80+x;}
 x=check32([float32(2.0),float32(5.0)],[float32(-3.0)],float32(3.0e-5));if(x!=0){return 90+x;}
 x=check32([float32(1.0),float32(-2.0),float32(4.0)],[float32(0.5),float32(-1.25)],float32(8.0e-5));if(x!=0){return 100+x;}
 return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        compile_and_run(source, optimization);
    }
}

#[test]
fn eigenvalues_match_numpy_oracle_without_productive_sorting() {
    let source = r"
int main(){
 Vector<float64,Column>d=[1.0,-2.0,4.0,0.5];Vector<float64,Column>e=[0.75,-1.25,2.0];Matrix<float64>q=identity<float64>(4);
 var s=symmetricTridiagonalQR<float64>(SymmetricTridiagonalSeed<float64>(d,e,q));usize i=1;while(i<=4){println(s.d[i]);i=i+1;}return 0;
}
";
    let observed = compile_and_run(source, OptimizationLevel::O2)
        .split_whitespace()
        .map(|value| value.parse::<f64>().unwrap())
        .collect::<Vec<_>>();
    let output = Command::new("python3")
        .args([
            "-c",
            "import numpy as np; a=np.diag([1.,-2.,4.,.5])+np.diag([.75,-1.25,2.],1)+np.diag([.75,-1.25,2.],-1); print(*np.linalg.eigvalsh(a))",
        ])
        .output()
        .unwrap();
    assert!(output.status.success(), "numpy oracle unavailable");
    let expected = String::from_utf8(output.stdout)
        .unwrap()
        .split_whitespace()
        .map(|value| value.parse::<f64>().unwrap())
        .collect::<Vec<_>>();
    let mut observed = observed;
    observed.sort_by(f64::total_cmp);
    for (actual, wanted) in observed.iter().zip(expected) {
        assert!((actual - wanted).abs() <= 2.0e-12 * (1.0 + wanted.abs()));
    }
}

#[test]
fn lowering_is_monomorphized_and_qr_phase_adds_no_allocations() {
    let directory = Directory::new("lowering");
    let entry = directory.white_box(
        "int main(){Vector<float64,Column>d=[2.0,5.0];Vector<float64,Column>e=[-3.0];Matrix<float64>q=identity<float64>(2);var x=symmetricTridiagonalQR<float64>(SymmetricTridiagonalSeed<float64>(d,e,q));Vector<float32,Column>f=[float32(1.0),float32(3.0)];Vector<float32,Column>g=[float32(0.5)];Matrix<float32>r=identity<float32>(2);var y=symmetricTridiagonalQR<float32>(SymmetricTridiagonalSeed<float32>(f,g,r));return int(dimension(x.d)+dimension(y.d)-4);}",
    );
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    for residue in ["GenericParam(", "witness", "vtable", "boxing"] {
        assert!(
            !compilation.dumps[&Emit::Mir].contains(residue),
            "{residue}"
        );
        assert!(
            !compilation.dumps[&Emit::Ssa].contains(residue),
            "{residue}"
        );
        assert!(!compilation.llvm.contains(residue), "{residue}");
    }
    assert!(!compilation.llvm.contains("TypeId"));
    for symbol in [
        "convergeSymmetricTridiagonalState__gfFloat64",
        "convergeSymmetricTridiagonalState__gfFloat32",
        "givensRotation__gfFloat64",
        "givensRotation__gfFloat32",
    ] {
        assert!(compilation.llvm.contains(symbol), "{symbol}");
    }
    for forbidden in ["LAPACK", "BLAS", "ffi", "llvm.matrix", "indirectbr"] {
        assert!(!compilation.llvm.contains(forbidden), "{forbidden}");
    }

    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("allocations");
        let entry = directory.white_box("int main(){Matrix<float64>a=[4.0,1.0,-2.0;1.0,2.0,0.5;-2.0,0.5,3.0];var s=symmetricTridiagonalSeedInPlace(a);var result=symmetricTridiagonalQR<float64>(s);return int(rows(result.vectors)-3);}");
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        let guarded = compilation.llvm.replace(
            "  %process_status = trunc i64 %aether_result to i32",
            "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, 6\n  %free_ok = icmp eq i64 %frees, 6\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99",
        );
        assert_ne!(guarded, compilation.llvm);
        let executable = directory.0.join("allocation-check");
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&guarded, &executable)
            .unwrap();
        assert_eq!(Command::new(executable).status().unwrap().code(), Some(0));
    }
}
