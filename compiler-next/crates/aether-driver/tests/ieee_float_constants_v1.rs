//! IEEE-FLOAT-CONSTANTS-V1 source, HIR, reification and native qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session,
    compile_source_with_optimization,
};
use aether_frontend::{CoreSymbol, SourceFile, prelude_symbol};

struct Output(PathBuf);

impl Drop for Output {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("ieee_float_constants_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"))
}

fn status(llvm: &str, optimization: OptimizationLevel) -> i32 {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let output = Output(std::env::temp_dir().join(format!(
        "aether-ieee-float-constants-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    )));
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &output.0)
        .unwrap();
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn diagnostics(source: &str) -> String {
    compile_source_with_optimization(
        &SourceFile::new("bad_ieee_float_constants_v1.ae", source),
        &[],
        OptimizationLevel::O0,
    )
    .unwrap_err()
    .into_iter()
    .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
    .collect::<Vec<_>>()
    .join("\n")
}

#[test]
fn epsilon_has_one_canonical_core_identity() {
    assert_eq!(prelude_symbol("epsilon"), Some(CoreSymbol::Epsilon));
    for spelling in ["eps", "machineEpsilon", "float32Epsilon", "float64Epsilon"] {
        assert_eq!(prelude_symbol(spelling), None);
    }
}

#[test]
fn exact_payloads_aliases_and_generic_forwarding_survive_o0_and_o2() {
    let source = r"
T e<T:IEEEFloat>(){return epsilon<T>();}
int main(){
  float32 a=epsilon<float32>();float64 b=epsilon<float64>();
  float c=epsilon<float>();double d=epsilon<double>();
  float32 eg=e<float32>();float64 dg=e<float64>();
  if(a!=c||b!=d||a!=eg||b!=dg){return 1;}
  if(!(float32(1.0)+a>float32(1.0))){return 2;}
  if(!(1.0+b>1.0)){return 3;}
  return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let hir = &compilation.dumps[&Emit::Hir];
        assert!(hir.contains("IEEEFloatConstant"));
        assert!(hir.contains("Epsilon"));
        assert!(hir.contains("result_type"));
        assert!(hir.contains("IEEEFloat"));
        assert!(hir.contains("872415232"), "{hir}");
        assert!(hir.contains("4372995238176751616"), "{hir}");
        for phase in [Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(!dump.contains("IEEEFloatConstant"));
            assert!(!dump.contains("GenericParam("));
            assert!(!dump.contains("epsilon"));
            assert!(!dump.contains("witness"));
            assert!(!dump.contains("vtable"));
        }
        for residue in [
            "epsilon",
            "IEEEFloatConstant",
            "TypeId",
            "witness",
            "vtable",
        ] {
            assert!(
                !compilation.llvm.contains(residue),
                "LLVM contains {residue}"
            );
        }
        assert_eq!(status(&compilation.llvm, optimization), 0);
    }
}

#[test]
fn invalid_calls_use_general_type_and_arity_diagnostics() {
    for source in [
        "int main(){float32 x=epsilon();return 0;}",
        "int main(){int32 x=epsilon<int32>();return 0;}",
        "T bad<T:RealOps>(){return epsilon<T>();}int main(){return 0;}",
        "int main(){float32 x=epsilon<float32>(float32(1.0));return 0;}",
        "int main(){float32 x=epsilon<float32,float64>();return 0;}",
    ] {
        let output = diagnostics(source);
        assert!(output.starts_with('E'), "{source}: {output}");
    }
    assert!(diagnostics("int main(){int32 x=epsilon<int32>();return 0;}").contains("IEEEFloat"));
    assert!(
        diagnostics("T bad<T:RealOps>(){return epsilon<T>();}int main(){return 0;}")
            .contains("IEEEFloat")
    );
}

#[test]
fn ordinary_linear_algebra_package_can_forward_epsilon_without_imports() {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let directory = std::env::temp_dir().join(format!(
        "aether-ieee-float-linear-algebra-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    fs::create_dir(&directory).unwrap();
    fs::write(
        directory.join("linearAlgebra.ae"),
        "package linearAlgebra;public T e<T:IEEEFloat>(){T value=epsilon<T>();return value;}",
    )
    .unwrap();
    let entry = directory.join("main.ae");
    fs::write(
        &entry,
        "package consumer;import linearAlgebra as la;int main(){float32 x=la.e<float32>();float64 y=la.e<float64>();if(!(float32(1.0)+x>float32(1.0))){return 1;}if(!(1.0+y>1.0)){return 2;}return 0;}",
    )
    .unwrap();
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(compilation.dumps[&Emit::Hir].contains("IEEEFloatConstant"));
    for phase in [Emit::Mir, Emit::Ssa] {
        assert!(!compilation.dumps[&phase].contains("IEEEFloatConstant"));
        assert!(!compilation.dumps[&phase].contains("epsilon"));
    }
    fs::remove_dir_all(directory).unwrap();
}
