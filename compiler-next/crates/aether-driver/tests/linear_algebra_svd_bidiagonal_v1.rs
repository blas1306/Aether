//! LINEAR-ALGEBRA-SVD-BIDIAGONAL-V1 internal qualification.

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
            "aether-svd-bidiagonal-{label}-{}-{}",
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
fn types_and_entry_are_private() {
    for expression in [
        "int probe(la.BidiagonalOrientation x){return 0;}",
        "int probe(la.CompactBidiagonalReduction<float64> x){return 0;}",
        "int probe(la.BidiagonalSVDSeed<float64> x){return 0;}",
        "int probe(ref Matrix<float64>x){var y=la.bidiagonalSVDSeed(x);return 0;}",
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
            .map(|d| d.message.as_str())
            .collect::<Vec<_>>()
            .join("\n");
        assert!(
            text.contains("internal to its module") || text.contains("unknown"),
            "{text}"
        );
    }
}

#[test]
fn source_has_one_compact_kernel_and_the_normative_formula() {
    assert_eq!(LIBRARY.matches("struct BidiagonalOrientation").count(), 1);
    assert_eq!(
        LIBRARY
            .matches("struct CompactBidiagonalReduction<")
            .count(),
        1
    );
    assert_eq!(LIBRARY.matches("struct BidiagonalSVDSeed<").count(), 1);
    assert_eq!(
        LIBRARY
            .matches("int reduceTallBidiagonal<T: IEEEFloat>(")
            .count(),
        1
    );
    for required in [
        "transpose_view_mut(workspace), M, N",
        "stableNormRange<T>(leftAxis, i, M)",
        "stableNormRange<T>(rightAxis, i + 1, N)",
        "(X[r,i] / betaLeft) / denominatorRatio",
        "(X[i,c] / betaRight) / denominatorRatio",
    ] {
        assert!(LIBRARY.contains(required), "{required}");
    }
    let start = LIBRARY
        .find("int reduceTallBidiagonal<T: IEEEFloat>(")
        .unwrap();
    let end = LIBRARY[start..]
        .find("Matrix<T> materializeBidiagonalUpperU")
        .unwrap()
        + start;
    let kernel = &LIBRARY[start..end];
    for forbidden in ["Matrix<T> B", "epsilon<T>()", "sqrt(sum"] {
        assert!(!kernel.contains(forbidden), "{forbidden}");
    }
}

#[test]
fn reconstructs_thin_orthonormal_seeds_at_o0_and_o2() {
    let source = r"
int validate64(ref Matrix<float64> A, bool wide, float64 tolerance) {
    BidiagonalSVDSeed<float64> s = bidiagonalSVDSeed<float64>(A);
    usize m=rows(*A); usize n=columns(*A); usize k=m; if(n<k){k=n;}
    usize ke=0; if(k>0){ke=k-1;}
    if(dimension(s.d)!=k||dimension(s.e)!=ke||rows(s.U)!=m||columns(s.U)!=k||rows(s.Vt)!=k||columns(s.Vt)!=n){return 1;}
    if(s.orientation.transposed!=wide){return 2;}
    usize i=1;
    while(i<=m){usize j=1;while(j<=n){float64 value=0.0;usize r=1;while(r<=k){
        float64 center=s.d[r]*s.Vt[r,j];
        if(!wide&&r<k){center=center+s.e[r]*s.Vt[r+1,j];}
        if(wide&&r>1){center=center+s.e[r-1]*s.Vt[r-1,j];}
        value=value+s.U[i,r]*center;r=r+1;}
        if(abs(value-(*A)[i,j])>tolerance*(1.0+abs((*A)[i,j]))){return 4;}j=j+1;}i=i+1;}
    i=1;while(i<=k){usize j=1;while(j<=k){float64 ud=0.0;float64 vd=0.0;usize r=1;
        while(r<=m){ud=ud+s.U[r,i]*s.U[r,j];r=r+1;}r=1;
        while(r<=n){vd=vd+s.Vt[i,r]*s.Vt[j,r];r=r+1;}
        float64 wanted=0.0;if(i==j){wanted=1.0;}
        if(abs(ud-wanted)>tolerance||abs(vd-wanted)>tolerance){return 5;}j=j+1;}i=i+1;}
    return 0;
}
int validate32(ref Matrix<float32> A, bool wide, float32 tolerance) {
    BidiagonalSVDSeed<float32> s=bidiagonalSVDSeed<float32>(A);
    usize m=rows(*A);usize n=columns(*A);usize k=m;if(n<k){k=n;}
    usize i=1;while(i<=m){usize j=1;while(j<=n){float32 value=float32(0.0);usize r=1;while(r<=k){
        float32 center=s.d[r]*s.Vt[r,j];
        if(!wide&&r<k){center=center+s.e[r]*s.Vt[r+1,j];}
        if(wide&&r>1){center=center+s.e[r-1]*s.Vt[r-1,j];}
        value=value+s.U[i,r]*center;r=r+1;}
        if(abs(value-(*A)[i,j])>tolerance*(float32(1.0)+abs((*A)[i,j]))){return 11;}j=j+1;}i=i+1;}
    i=1;while(i<=k){usize j=1;while(j<=k){float32 ud=float32(0.0);float32 vd=float32(0.0);usize r=1;
        while(r<=m){ud=ud+s.U[r,i]*s.U[r,j];r=r+1;}r=1;
        while(r<=n){vd=vd+s.Vt[i,r]*s.Vt[j,r];r=r+1;}
        float32 wanted=float32(0.0);if(i==j){wanted=float32(1.0);}
        if(abs(ud-wanted)>tolerance||abs(vd-wanted)>tolerance){return 12;}j=j+1;}i=i+1;}
    return 0;
}
int degenerates(){float64 z=0.0;Matrix<float64>a=matrixFilled<float64>(3,2,z);var s=bidiagonalSVDSeed(&a);
    if(s.d[1]!=z||1.0/s.d[1]!=1.0/z||s.e[1]!=z||s.U[1,1]!=1.0||s.Vt[2,2]!=1.0){return 21;}
    Matrix<float64>b=matrixFilled<float64>(3,0,z);s=bidiagonalSVDSeed(&b);if(rows(s.U)!=3||columns(s.U)!=0||columns(s.Vt)!=0){return 22;}
    Matrix<float64>c=matrixFilled<float64>(0,4,z);s=bidiagonalSVDSeed(&c);if(rows(s.U)!=0||rows(s.Vt)!=0||columns(s.Vt)!=4){return 23;}
    Matrix<float64>d=matrixFilled<float64>(0,0,z);s=bidiagonalSVDSeed(&d);if(rows(s.U)!=0||columns(s.Vt)!=0){return 24;}
    Matrix<float64>signed=[-z,z;z,-z];s=bidiagonalSVDSeed(&signed);if(1.0/s.d[1]!=1.0/z||1.0/s.e[1]!=1.0/z){return 25;}return 0;}
int compactLayout(){Matrix<float64>a=[1.0,2.0;0.0,3.0];var r=compactBidiagonalReduction(a);
    if(r.workspace[1,1]!=r.d[1]||r.workspace[1,2]!=r.e[1]||r.workspace[2,2]!=r.d[2]){return 26;}
    if(r.tauLeft[1]!=2.0||r.tauRight[1]!=2.0||r.orientation.transposed){return 27;}
    Matrix<float64>b=[1.0,0.0;2.0,0.0;3.0,0.0];r=compactBidiagonalReduction(b);
    if(r.tauRight[1]!=0.0||r.e[1]!=0.0){return 28;}return 0;}
int main(){
    Matrix<float64>a=[4.0,1.0,-2.0;1.0,2.0,3.0;0.5,-1.0,5.0];int x=validate64(&a,false,1.0e-11);if(x!=0){return x;}
    Matrix<float64>b=[1.0,2.0;3.0,4.0;5.0,6.0;7.0,8.0];x=validate64(&b,false,1.0e-11);if(x!=0){return x+30;}
    Matrix<float64>c=[1.0,2.0,3.0,4.0,5.0;2.0,4.0,6.0,8.0,10.0];x=validate64(&c,true,1.0e-11);if(x!=0){return x+40;}
    Matrix<float64>d=[3.0;4.0;0.0];x=validate64(&d,false,1.0e-11);if(x!=0){return x+50;}
    Matrix<float64>e=[3.0,4.0,-2.0,1.0];x=validate64(&e,true,1.0e-11);if(x!=0){return x+60;}
    Matrix<float32>f=[float32(1.0),float32(-2.0);float32(3.0),float32(4.0);float32(5.0),float32(-6.0)];x=validate32(&f,false,float32(2.0e-5));if(x!=0){return x+70;}
    Matrix<float32>g=[float32(1.0),float32(2.0),float32(3.0);float32(-4.0),float32(5.0),float32(-6.0)];x=validate32(&g,true,float32(2.0e-5));if(x!=0){return x+90;}
    Matrix<float64>huge=[1.0e308,1.0e-200;1.0e-200,-1.0e308];x=validate64(&huge,false,1.0e-11);if(x!=0){return x+110;}
    Matrix<float64>tiny=[1.0e-200,-2.0e-200;3.0e-200,4.0e-200];x=validate64(&tiny,false,1.0e-11);if(x!=0){return x+120;}
    Matrix<float32>huge32=[float32(2.0e38),float32(1.0e-30);float32(1.0e-30),float32(-2.0e38)];x=validate32(&huge32,false,float32(2.0e-5));if(x!=0){return x+140;}
    Matrix<float32>tiny32=[float32(1.0e-30),float32(-2.0e-30);float32(3.0e-30),float32(4.0e-30)];x=validate32(&tiny32,false,float32(2.0e-5));if(x!=0){return x+160;}
    x=compactLayout();if(x!=0){return x;}return degenerates();}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn monomorphizes_and_observes_the_seven_owner_budget() {
    let directory = Directory::new("lowering");
    let entry = directory.white_box("int main(){Matrix<float64>a=[1.0,2.0,3.0;4.0,5.0,6.0];var x=bidiagonalSVDSeedInPlace(a);Matrix<float32>b=[float32(1.0);float32(2.0)];var y=bidiagonalSVDSeedInPlace(b);return int(columns(x.Vt)+rows(y.U)-5);}");
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    for residue in ["GenericParam(", "witness", "vtable"] {
        assert!(!compilation.dumps[&Emit::Mir].contains(residue));
        assert!(!compilation.dumps[&Emit::Ssa].contains(residue));
        assert!(!compilation.llvm.contains(residue));
    }
    assert!(!compilation.llvm.contains("TypeId"));
    assert!(compilation.llvm.contains("reduceTallBidiagonal__gfFloat64"));
    assert!(compilation.llvm.contains("reduceTallBidiagonal__gfFloat32"));

    for source in [
        "int main(){Matrix<float64>a=[1.0,2.0;3.0,4.0;5.0,6.0];var s=bidiagonalSVDSeedInPlace(a);return int(rows(s.U)+columns(s.Vt)-5);}",
        "int main(){Matrix<float64>a=[1.0,2.0,3.0;4.0,5.0,6.0];var s=bidiagonalSVDSeedInPlace(a);return int(rows(s.U)+columns(s.Vt)-5);}",
    ] {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let d = Directory::new("allocations");
            let e = d.white_box(source);
            let c = compile_session_with_optimization(
                CompilationSession::discover(&e).unwrap(),
                &[Emit::Llvm],
                optimization,
            )
            .unwrap();
            let guarded=c.llvm.replace("  %process_status = trunc i64 %aether_result to i32","  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, 7\n  %free_ok = icmp eq i64 %frees, 7\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99");
            assert_ne!(guarded, c.llvm);
            let executable = d.0.join("allocation-check");
            ClangToolchain::default()
                .with_optimization(optimization)
                .link_executable(&guarded, &executable)
                .unwrap();
            assert_eq!(
                Command::new(executable).status().unwrap().code(),
                Some(0),
                "{optimization:?}"
            );
        }
    }
}
