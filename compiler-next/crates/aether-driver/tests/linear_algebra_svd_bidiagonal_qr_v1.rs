//! LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-V1 internal qualification.

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
            "aether-svd-bidiagonal-qr-{label}-{}-{}",
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

fn run(source: &str, optimization: OptimizationLevel) {
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
    assert_eq!(
        Command::new(executable).status().unwrap().code(),
        Some(0),
        "{optimization:?}"
    );
}

#[test]
fn qr_surface_and_exception_remain_module_private() {
    for expression in [
        "int probe(la.BidiagonalSVDConverged<float64> x){return 0;}",
        "int probe(la.NumericalConvergenceException x){return 0;}",
        "int probe(la.BidiagonalSVDSeed<float64> x){var y=la.bidiagonalSVDQR(x);return 0;}",
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
}

#[test]
fn exact_helpers_deflation_budget_and_nonfinite_paths_work() {
    let source = r"
int budgetFailure(){
    Vector<float64,Column>d=[3.0,2.0];Vector<float64,Column>e=[1.0];Matrix<float64>u=identity<float64>(2);Matrix<float64>v=identity<float64>(2);
    BidiagonalSVDSeed<float64>s=BidiagonalSVDSeed<float64>(d,e,u,v,BidiagonalOrientation(false));
    try{convergeBidiagonalSVDSeed<float64>(&mut s,0);}
    catch(NumericalConvergenceException error){return 0;}return 1;
}
int nonfiniteFailure(){
    float64 z=0.0;float64 nan=z/z;Vector<float64,Column>d=[nan,2.0];Vector<float64,Column>e=[1.0];Matrix<float64>u=identity<float64>(2);Matrix<float64>v=identity<float64>(2);
    BidiagonalSVDSeed<float64>s=BidiagonalSVDSeed<float64>(d,e,u,v,BidiagonalOrientation(false));
    try{convergeBidiagonalSVDSeed<float64>(&mut s,1);}
    catch(NumericalConvergenceException error){return 0;}return 1;
}
int main(){
    float64 z=0.0;
    BidiagonalGivens<float64> g=bidiagonalGivens<float64>(3.0,4.0);
    if(g.r!=5.0||abs(g.c*g.c+g.s*g.s-1.0)>1.0e-15||abs(-g.s*3.0+g.c*4.0)>1.0e-15){return 1;}
    g=bidiagonalGivens<float64>(z,-z);
    if(g.c!=1.0||g.s!=z||1.0/g.s!=1.0/z){return 2;}

    Vector<float64,Column>shiftD=[3.0,2.0];Vector<float64,Column>shiftE=[4.0];
    BidiagonalShift<float64>shift=bidiagonalWilkinsonShift<float64>(&shiftD,&shiftE,1,2);
    float64 expected=((29.0+sqrt(697.0))/2.0)/16.0;
    if(abs(shift.lambda-expected)>2.0e-15||shift.sigma!=4.0){return 10;}
    Vector<float64,Column>largeD=[3.0e200,2.0e200];Vector<float64,Column>largeE=[4.0e200];
    BidiagonalShift<float64>largeShift=bidiagonalWilkinsonShift<float64>(&largeD,&largeE,1,2);
    if(!isFiniteInternal<float64>(largeShift.lambda)||abs(largeShift.lambda-shift.lambda)>2.0e-15){return 11;}

    Vector<float64,Column>d=[4.0,2.0];
    float64 threshold=(epsilon<float64>()*4.0)*(1.0+0.5);
    Vector<float64,Column>e=[threshold];
    deflateBidiagonal<float64>(&d,&mut e,epsilon<float64>());
    if(e[1]!=z||1.0/e[1]!=1.0/z){return 3;}
    e=[threshold+threshold];
    deflateBidiagonal<float64>(&d,&mut e,epsilon<float64>());
    if(e[1]==z){return 4;}
    d=[z,-z];e=[-z];
    deflateBidiagonal<float64>(&d,&mut e,epsilon<float64>());
    if(1.0/e[1]!=1.0/z){return 5;}

    if(budgetFailure()!=0){return 6;}
    Matrix<float64>a=[3.0,1.0;0.0,2.0];BidiagonalSVDSeed<float64>s=bidiagonalSVDSeed<float64>(&a);
    BidiagonalSVDSeed<float64>converged=bidiagonalSVDQRWithMaxSteps<float64>(s,128);
    if(converged.e[1]!=z||1.0/converged.e[1]!=1.0/z){return 7;}

    d=[3.0,2.0];e=[z];Matrix<float64>u=identity<float64>(2);Matrix<float64>v=identity<float64>(2);
    BidiagonalSVDSeed<float64>diagonal=BidiagonalSVDSeed<float64>(d,e,u,v,BidiagonalOrientation(false));
    BidiagonalSVDSeed<float64>diagonalResult=bidiagonalSVDQRWithMaxSteps<float64>(diagonal,0);
    if(diagonalResult.d[1]!=3.0||diagonalResult.d[2]!=2.0){return 8;}
    if(nonfiniteFailure()!=0){return 9;}
    return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn reconstructs_real_upper_and_transposed_seeds_for_both_float_types() {
    let source = r"
int validate64(ref Matrix<float64>A,float64 tolerance){
    usize m=rows(*A);usize n=columns(*A);usize k=m;if(n<k){k=n;}
    BidiagonalSVDSeed<float64>s=bidiagonalSVDQR<float64>(bidiagonalSVDSeed<float64>(A));
    usize i=1;while(i<=m){usize j=1;while(j<=n){float64 value=0.0;usize r=1;
        while(r<=k){value=value+s.U[i,r]*s.d[r]*s.Vt[r,j];r=r+1;}
        if(abs(value-(*A)[i,j])>tolerance*(1.0+abs((*A)[i,j]))){return 1;}j=j+1;}i=i+1;}
    i=1;while(i<=k){usize j=1;while(j<=k){float64 uu=0.0;float64 vv=0.0;usize r=1;
        while(r<=m){uu=uu+s.U[r,i]*s.U[r,j];r=r+1;}r=1;while(r<=n){vv=vv+s.Vt[i,r]*s.Vt[j,r];r=r+1;}
        float64 wanted=0.0;if(i==j){wanted=1.0;}if(abs(uu-wanted)>tolerance||abs(vv-wanted)>tolerance){return 2;}j=j+1;}i=i+1;}
    i=1;while(i<=dimension(s.e)){if(s.e[i]!=0.0||1.0/s.e[i]!=1.0/0.0){return 3;}i=i+1;}return 0;
}
int validate32(ref Matrix<float32>A,float32 tolerance){
    usize m=rows(*A);usize n=columns(*A);usize k=m;if(n<k){k=n;}
    BidiagonalSVDSeed<float32>s=bidiagonalSVDQR<float32>(bidiagonalSVDSeed<float32>(A));
    usize i=1;while(i<=m){usize j=1;while(j<=n){float32 value=float32(0.0);usize r=1;
        while(r<=k){value=value+s.U[i,r]*s.d[r]*s.Vt[r,j];r=r+1;}
        if(abs(value-(*A)[i,j])>tolerance*(float32(1.0)+abs((*A)[i,j]))){return 11;}j=j+1;}i=i+1;}return 0;
}
int synthetic(Vector<float64,Column>d,Vector<float64,Column>e,bool transposed,float64 tolerance){
    usize k=dimension(d);Matrix<float64>original=matrixFilled<float64>(k,k,0.0);usize i=1;
    while(i<=k){original[i,i]=d[i];if(i<k){if(transposed){original[i+1,i]=e[i];}else{original[i,i+1]=e[i];}}i=i+1;}
    Matrix<float64>u=identity<float64>(k);Matrix<float64>v=identity<float64>(k);
    BidiagonalSVDConverged<float64>s=bidiagonalSVDQR<float64>(d,e,u,v,BidiagonalOrientation(transposed));
    i=1;while(i<=k){usize j=1;while(j<=k){float64 value=0.0;usize r=1;while(r<=k){value=value+s.U[i,r]*s.d[r]*s.Vt[r,j];r=r+1;}
        if(abs(value-original[i,j])>tolerance*(1.0+abs(original[i,j]))){return int(i*10+j);}j=j+1;}i=i+1;}return 0;
}
int main(){
    Matrix<float64>a=[4.0,1.0,-2.0;1.0,2.0,3.0;0.5,-1.0,5.0];int x=validate64(&a,2.0e-11);if(x!=0){return x;}
    Matrix<float64>b=[1.0,2.0;3.0,4.0;5.0,6.0;7.0,8.0];x=validate64(&b,3.0e-11);if(x!=0){return x+10;}
    Matrix<float64>c=[1.0,2.0,3.0,4.0;2.0,4.0,6.0,8.0];x=validate64(&c,3.0e-11);if(x!=0){return x+20;}
    Matrix<float64>z=matrixFilled<float64>(3,3,0.0);x=validate64(&z,1.0e-12);if(x!=0){return x+30;}
    Matrix<float64>r=[2.0,0.0,0.0;0.0,2.0,0.0;0.0,0.0,0.0];x=validate64(&r,1.0e-12);if(x!=0){return x+40;}
    Matrix<float64>separated=[1.0e150,2.0e149;0.0,1.0e-150];x=validate64(&separated,1.0e-10);if(x!=0){return x+50;}
    Matrix<float32>f=[float32(1.0),float32(-2.0);float32(3.0),float32(4.0);float32(5.0),float32(-6.0)];x=validate32(&f,float32(4.0e-5));if(x!=0){return x+60;}
    Matrix<float32>w=[float32(1.0),float32(2.0),float32(3.0);float32(-4.0),float32(5.0),float32(-6.0)];x=validate32(&w,float32(4.0e-5));if(x!=0){return x+80;}
    Vector<float64,Column>sd1=[0.0,4.0,2.0];Vector<float64,Column>se1=[1.0,3.0];x=synthetic(sd1,se1,false,3.0e-12);if(x!=0){return x;}
    Vector<float64,Column>sd2=[4.0,2.0,0.0];Vector<float64,Column>se2=[1.0,3.0];x=synthetic(sd2,se2,false,3.0e-12);if(x!=0){return x;}
    Vector<float64,Column>sd3=[0.0,4.0,2.0];Vector<float64,Column>se3=[1.0,3.0];x=synthetic(sd3,se3,true,3.0e-12);if(x!=0){return x;}
    Vector<float64,Column>sd4=[2.0,2.0,2.0];Vector<float64,Column>se4=[-0.0,0.0];x=synthetic(sd4,se4,false,1.0e-14);if(x!=0){return x;}
    Vector<float64,Column>sd5=[5.0e-324,1.0e-323];Vector<float64,Column>se5=[-0.0];x=synthetic(sd5,se5,false,1.0e-323);if(x!=0){return x;}
    Matrix<float64>empty=matrixFilled<float64>(0,3,0.0);var es=bidiagonalSVDQR<float64>(bidiagonalSVDSeed<float64>(&empty));if(dimension(es.d)!=0){return 101;}
    Vector<float64,Column>od=[-7.0];Vector<float64,Column>oe=vectorFilled<float64,Column>(0,0.0);Matrix<float64>ou=identity<float64>(1);Matrix<float64>ov=identity<float64>(1);
    var os=bidiagonalSVDQR<float64>(BidiagonalSVDSeed<float64>(od,oe,ou,ov,BidiagonalOrientation(false)));if(os.d[1]!=-7.0){return 102;}
    return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn lowering_is_scalar_monomorphized_and_qr_adds_no_allocations() {
    let directory = Directory::new("lowering");
    let entry = directory.white_box("int main(){Matrix<float64>a=[1.0,2.0;3.0,4.0];var x=bidiagonalSVDQR<float64>(bidiagonalSVDSeedInPlace<float64>(a));Matrix<float32>b=[float32(2.0),float32(1.0);float32(0.0),float32(3.0)];var y=bidiagonalSVDQR<float32>(bidiagonalSVDSeedInPlace<float32>(b));return int(dimension(x.d)+dimension(y.d)-4);}");
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
    assert!(compilation.llvm.contains("chaseBidiagonalBulge__gfFloat64"));
    assert!(compilation.llvm.contains("chaseBidiagonalBulge__gfFloat32"));

    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("allocations");
        let entry = directory.white_box("int main(){Matrix<float64>a=[3.0,1.0;0.0,2.0];var s=bidiagonalSVDSeedInPlace<float64>(a);var result=bidiagonalSVDQR<float64>(s);return int(abs(result.d[1])+abs(result.d[2])-5.0);}");
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        let guarded = compilation.llvm.replace(
            "  %process_status = trunc i64 %aether_result to i32",
            "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, 7\n  %free_ok = icmp eq i64 %frees, 7\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99",
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
