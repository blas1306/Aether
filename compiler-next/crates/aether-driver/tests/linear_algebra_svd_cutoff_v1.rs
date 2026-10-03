//! LINEAR-ALGEBRA-SVD-CUTOFF-V1 public and white-box qualification.

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
            "aether-svd-cutoff-{label}-{}-{}",
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

fn run(source: &str, white_box: bool, optimization: OptimizationLevel) -> i32 {
    let directory = Directory::new("native");
    let entry = if white_box {
        directory.white_box(source)
    } else {
        directory.imported(source)
    };
    let session = CompilationSession::discover(&entry)
        .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"));
    let compilation = compile_session_with_optimization(session, &[Emit::Llvm], optimization)
        .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"));
    let executable = directory.0.join("qualification");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    Command::new(executable)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn diagnostics(source: &str) -> String {
    let directory = Directory::new("visibility");
    let entry = directory.imported(source);
    compile_session(CompilationSession::discover(&entry).unwrap(), &[])
        .unwrap_err()
        .into_iter()
        .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn binary_dimension_conversion_covers_boundaries_without_losing_progress() {
    let source = r"
int main(){
 if(dimensionAsT<float64>(0)!=0.0||dimensionAsT<float64>(1)!=1.0||dimensionAsT<float64>(13)!=13.0){return 1;}
 if(dimensionAsT<float64>(9007199254740992)!=9007199254740992.0){return 2;}
 if(dimensionAsT<float64>(9007199254740993)!=9007199254740992.0){return 3;}
 if(dimensionAsT<float64>(18446744073709551615)!=18446744073709551616.0){return 4;}
 if(dimensionAsT<float32>(16777216)!=float32(16777216.0)){return 5;}
 if(dimensionAsT<float32>(16777217)!=float32(16777216.0)){return 6;}
 if(dimensionAsT<float32>(33554431)!=float32(33554432.0)){return 7;}
 if(dimensionAsT<float32>(18446744073709551615)!=float32(18446744073709551616.0)){return 8;}
 return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(source, true, optimization), 0, "{optimization:?}");
    }
}

#[test]
fn default_classification_is_strict_normalized_and_scale_safe() {
    let source = r"
int main(){
 float64 e=epsilon<float64>();
 Matrix<float64>u=matrixFilled<float64>(2,4,0.0);Matrix<float64>v=matrixFilled<float64>(4,2,0.0);
 Vector<float64,Column>s=[1.0,4.0*e,2.0*e,e];SVD<float64>f=SVD<float64>(u,s,v);
 if(retainedSingularValueCount<float64>(&f)!=2){return 1;}
 Matrix<float64>zu=matrixFilled<float64>(3,2,0.0);Matrix<float64>zv=matrixFilled<float64>(2,1,0.0);
 Vector<float64,Column>zs=[0.0,-0.0];SVD<float64>zf=SVD<float64>(zu,zs,zv);
 if(retainedSingularValueCount<float64>(&zf)!=0){return 2;}
 Matrix<float64>eu=matrixFilled<float64>(7,0,0.0);Vector<float64,Column>es=vectorFilled<float64,Column>(0,0.0);Matrix<float64>ev=matrixFilled<float64>(0,5,0.0);
 SVD<float64>ef=SVD<float64>(eu,es,ev);if(retainedSingularValueCount<float64>(&ef)!=0){return 3;}
 // The least positive subnormal survives: forming epsilon*dimension*sigmaMax
 // first would round the threshold to that same value and discard on equality.
 Matrix<float64>tu=matrixFilled<float64>(2,2,0.0);Matrix<float64>tv=matrixFilled<float64>(2,2,0.0);
 Vector<float64,Column>ts=[1.0e-308,5.0e-324];SVD<float64>tf=SVD<float64>(tu,ts,tv);
 if(retainedSingularValueCount<float64>(&tf)!=2){return 4;}
 Matrix<float64>hu=matrixFilled<float64>(2,2,0.0);Matrix<float64>hv=matrixFilled<float64>(2,2,0.0);
 Vector<float64,Column>hs=[1.0e308,5.0e292];SVD<float64>hf=SVD<float64>(hu,hs,hv);
 if(retainedSingularValueCount<float64>(&hf)!=2){return 5;}
 float32 e32=epsilon<float32>();Matrix<float32>u32=matrixFilled<float32>(2,4,float32(0.0));Matrix<float32>v32=matrixFilled<float32>(4,2,float32(0.0));
 Vector<float32,Column>s32=[float32(1.0),float32(4.0)*e32,float32(2.0)*e32,e32];SVD<float32>f32=SVD<float32>(u32,s32,v32);
 if(retainedSingularValueCount<float32>(&f32)!=2){return 6;}
 Matrix<float32>t32u=matrixFilled<float32>(2,2,float32(0.0));Matrix<float32>t32v=matrixFilled<float32>(2,2,float32(0.0));
 Vector<float32,Column>t32s=[float32(5.0e-39),float32(1.0e-45)];SVD<float32>t32f=SVD<float32>(t32u,t32s,t32v);
 if(retainedSingularValueCount<float32>(&t32f)!=2){return 7;}
 Matrix<float32>h32u=matrixFilled<float32>(2,2,float32(0.0));Matrix<float32>h32v=matrixFilled<float32>(2,2,float32(0.0));
 Vector<float32,Column>h32s=[float32(3.0e38),float32(1.0e32)];SVD<float32>h32f=SVD<float32>(h32u,h32s,h32v);
 if(retainedSingularValueCount<float32>(&h32f)!=2){return 8;}
 return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(source, true, optimization), 0, "{optimization:?}");
    }
}

#[test]
fn explicit_cutoff_is_absolute_validated_even_for_empty_spectra() {
    let source = r"
int main(){
 Matrix<float64>u=matrixFilled<float64>(2,4,0.0);Matrix<float64>v=matrixFilled<float64>(4,3,0.0);
 Vector<float64,Column>s=[9.0,3.0,1.0,5.0e-324];SVD<float64>f=SVD<float64>(u,s,v);
 if(retainedSingularValueCount<float64>(&f,0.0)!=4){return 1;}
 if(retainedSingularValueCount<float64>(&f,-0.0)!=4){return 2;}
 if(retainedSingularValueCount<float64>(&f,3.0)!=1){return 3;}
 if(retainedSingularValueCount<float64>(&f,2.0)!=2){return 4;}
 Matrix<float64>eu=matrixFilled<float64>(0,0,0.0);Vector<float64,Column>es=vectorFilled<float64,Column>(0,0.0);Matrix<float64>ev=matrixFilled<float64>(0,0,0.0);SVD<float64>ef=SVD<float64>(eu,es,ev);
 float64 z=0.0;float64 nan=z/z;float64 inf=1.0/z;int caught=0;
 try{retainedSingularValueCount<float64>(&ef,-1.0);}catch(InvalidSingularValueCutoffException error){caught=caught+1;}
 try{retainedSingularValueCount<float64>(&ef,nan);}catch(InvalidSingularValueCutoffException error){caught=caught+1;}
 try{retainedSingularValueCount<float64>(&ef,inf);}catch(InvalidSingularValueCutoffException error){caught=caught+1;}
 try{retainedSingularValueCount<float64>(&ef,-inf);}catch(InvalidSingularValueCutoffException error){caught=caught+1;}
 if(caught!=4){return 5;}
 Vector<float32,Column>s32=[float32(8.0),float32(2.0),float32(1.0e-40)];Matrix<float32>u32=matrixFilled<float32>(1,3,float32(0.0));Matrix<float32>v32=matrixFilled<float32>(3,1,float32(0.0));SVD<float32>f32=SVD<float32>(u32,s32,v32);
 if(retainedSingularValueCount<float32>(&f32,float32(2.0))!=1||retainedSingularValueCount<float32>(&f32,float32(0.0))!=3){return 6;}
 return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(source, true, optimization), 0, "{optimization:?}");
    }
}

#[test]
fn public_nonzero_count_is_representational_and_checks_factor_shapes() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 Matrix<float64>u=matrixFilled<float64>(2,5,0.0);Matrix<float64>v=matrixFilled<float64>(5,7,0.0);Vector<float64,Column>s=[4.0,-0.0,0.0,5.0e-324,-2.0];la.SVD<float64>f=la.SVD<float64>(u,s,v);
 if(la.nonzeroSingularValueCount(f)!=3){return 1;}
 Matrix<float64>zu=matrixFilled<float64>(1,3,0.0);Matrix<float64>zv=matrixFilled<float64>(3,1,0.0);Vector<float64,Column>zs=[0.0,-0.0,0.0];la.SVD<float64>zf=la.SVD<float64>(zu,zs,zv);if(la.nonzeroSingularValueCount(zf)!=0){return 2;}
 Matrix<float32>au=matrixFilled<float32>(1,3,float32(0.0));Matrix<float32>av=matrixFilled<float32>(3,1,float32(0.0));Vector<float32,Column>values32=[float32(3.0),float32(2.0),float32(1.0)];la.SVD<float32>af=la.SVD<float32>(au,values32,av);if(la.nonzeroSingularValueCount<float32>(af)!=3){return 3;}
 Matrix<float64>eu=matrixFilled<float64>(4,0,0.0);Vector<float64,Column>es=vectorFilled<float64,Column>(0,0.0);Matrix<float64>ev=matrixFilled<float64>(0,6,0.0);la.SVD<float64>ef=la.SVD<float64>(eu,es,ev);if(la.nonzeroSingularValueCount(ef)!=0){return 4;}
 return 0;
}";
    let invalid_u = r"package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=matrixFilled<float64>(1,1,0.0);Vector<float64,Column>s=[1.0,0.0];Matrix<float64>v=matrixFilled<float64>(2,1,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);usize count=la.nonzeroSingularValueCount(f);return int(count);}";
    let invalid_v = r"package consumer;import linearAlgebra as la;int main(){Matrix<float64>u=matrixFilled<float64>(1,2,0.0);Vector<float64,Column>s=[1.0,0.0];Matrix<float64>v=matrixFilled<float64>(1,1,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);usize count=la.nonzeroSingularValueCount(f);return int(count);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(source, false, optimization), 0, "{optimization:?}");
        assert_ne!(run(invalid_u, false, optimization), 0, "{optimization:?}");
        assert_ne!(run(invalid_v, false, optimization), 0, "{optimization:?}");
    }
}

#[test]
fn public_surface_and_private_authorities_are_closed() {
    for expression in [
        "int main(){return int(la.dimensionAsT<float64>(2));}",
        "int main(){la.validateSingularValueCutoff<float64>(0.0);return 0;}",
        "int main(){Matrix<float64>u=matrixFilled<float64>(0,0,0.0);Vector<float64,Column>s=vectorFilled<float64,Column>(0,0.0);Matrix<float64>v=matrixFilled<float64>(0,0,0.0);la.SVD<float64>f=la.SVD<float64>(u,s,v);return int(la.retainedSingularValueCount(f));}",
    ] {
        let output = diagnostics(&format!(
            "package consumer;import linearAlgebra as la;{expression}"
        ));
        assert!(
            output.contains("internal to its module") || output.contains("unknown function"),
            "{output}"
        );
    }
    assert_eq!(
        LIBRARY
            .matches("public class InvalidSingularValueCutoffException")
            .count(),
        1
    );
    assert_eq!(
        LIBRARY
            .matches("public usize nonzeroSingularValueCount<")
            .count(),
        1
    );
    assert!(!LIBRARY.contains("public usize numericalRank<"));
    assert!(!LIBRARY.contains("public Matrix<T> pseudoInverse<"));
    assert!(!LIBRARY.contains("condition2<T:"));
    assert!(LIBRARY.contains("(*factor).S[i] / sigmaMax > relativeCutoff"));
    assert!(!LIBRARY.contains("relativeCutoff * sigmaMax"));
}

#[test]
fn helpers_are_scalar_monomorphized_shared_and_allocate_no_owners() {
    let directory = Directory::new("resources");
    let entry = directory.white_box(
        r"int main(){Matrix<float64>u=matrixFilled<float64>(2,2,0.0);Vector<float64,Column>s=[1.0,0.0];Matrix<float64>v=matrixFilled<float64>(2,2,0.0);SVD<float64>f=SVD<float64>(u,s,v);usize a=retainedSingularValueCount<float64>(&f);usize b=retainedSingularValueCount<float64>(&f,0.0);usize c=nonzeroSingularValueCount<float64>(&f);return int(a+b+c-3);}",
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Mir, Emit::Ssa, Emit::Llvm],
            optimization,
        )
        .unwrap();
        for phase in [Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(!dump.contains("GenericParam("), "{phase:?}");
            assert!(!dump.contains("witness"), "{phase:?}");
            assert!(!dump.contains("vtable"), "{phase:?}");
        }
        assert!(compilation.llvm.contains("retainedSingularValueCount"));
        assert!(compilation.llvm.contains("dimensionAsT"));
        let guarded = compilation.llvm.replace(
            "  %process_status = trunc i64 %aether_result to i32",
            "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, 3\n  %free_ok = icmp eq i64 %frees, 3\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99",
        );
        assert_ne!(guarded, compilation.llvm);
        let executable = directory.0.join(format!("resources-{optimization:?}"));
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
