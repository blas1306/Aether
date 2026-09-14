//! CORE-V1 closed prelude, canonical identity and native qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{CoreSymbol, SourceFile, analyze, parse_source};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Output(PathBuf);

impl Output {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-core-v1-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        )))
    }
}

impl Drop for Output {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("core_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn status(source: &str, optimization: OptimizationLevel) -> i32 {
    let compilation = compile(source, optimization);
    let output = Output::new("native");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &output.0)
        .unwrap();
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

#[test]
fn prelude_surface_runs_without_imports_at_o0_and_o2() {
    let source = r#"
int main(){
  int a=abs(-7); int b=min(a,9); int c=max(b,8); int d=clamp(c,0,10);
  float32 f=sqrt(float32(4.0));
  double x=1.0; double y=exp(x)-2.0*x*x; double z=ln(1.0)+sin(0.0)+cos(0.0)+tan(0.0);
  print(""); println("done");
  if(byteLength("A\0hé")!=5){return 90;}
  if(d!=8){return 91;} if(f!=float32(2.0)){return 92;}
  if(y<0.718){return 93;} if(y>0.719){return 93;}
  if(z<0.999){return 94;} if(z>1.001){return 94;}
  return 0;
}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(dump.contains("CoreSymbolKey"));
            assert!(dump.contains("profile: 1"));
            assert!(dump.contains("Exp"));
        }
        assert_eq!(status(source, optimization), 0);
    }
}

#[test]
fn admitted_integer_and_float_signatures_are_closed_and_use_existing_widening() {
    for ty in [
        "int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "isize", "usize",
        "float32", "float64",
    ] {
        let source = format!(
            "int main(){{{ty} x={ty}(2);{ty} lo={ty}(1);{ty} hi={ty}(3);{ty} a=min(x,hi);{ty} b=max(a,lo);{ty} c=clamp(b,lo,hi);if(c!=x){{return 1;}}return 0;}}"
        );
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            assert_eq!(status(&source, optimization), 0, "{ty} {optimization:?}");
        }
    }
    for ty in [
        "int8", "int16", "int32", "int64", "isize", "float32", "float64",
    ] {
        let source = format!(
            "int main(){{{ty} x={ty}(-2);{ty} y=abs(x);if(y!={ty}(2)){{return 1;}}return 0;}}"
        );
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            assert_eq!(status(&source, optimization), 0, "{ty} {optimization:?}");
        }
    }
    let widening = compile(
        "int main(){int8 a=1;int16 b=2;int16 c=min(a,b);return int(c)-1;}",
        OptimizationLevel::O0,
    );
    assert!(widening.dumps[&Emit::Hir].contains("SignExtend"));

    for invalid in [
        "int main(){uint8 x=1;uint8 y=abs(x);return 0;}",
        "int main(){int n=1;double x=sqrt(n);return 0;}",
        "int main(){int x=min(1.0,2);return 0;}",
        "int main(){double x=sin<float64>(1.0);return 0;}",
    ] {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("bad.ae", invalid),
                &[],
                OptimizationLevel::O0
            )
            .is_err()
        );
    }
}

#[test]
fn floating_domain_nan_infinity_and_signed_zero_follow_libm_ieee_behavior() {
    let source = r"
int main(){
  double nan=0.0/0.0; double inf=1.0/0.0;
  if(sqrt(-1.0)==sqrt(-1.0)){return 1;}
  if(ln(0.0)!=0.0-inf){return 2;}
  if(exp(inf)!=inf){return 3;}
  if(min(nan,2.0)!=2.0){return 4;} if(max(nan,2.0)!=2.0){return 4;}
  if(clamp(nan,1.0,3.0)!=1.0){return 5;}
  if(abs(-0.0)!=0.0){return 6;}
  return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
    }
}

#[test]
fn every_transcendental_preserves_float32_and_float64() {
    for ty in ["float32", "float64"] {
        let source = format!(
            "int main(){{{ty} z={ty}(0.0);{ty} o={ty}(1.0);if(sqrt(o)!=o){{return 1;}}if(exp(z)!=o){{return 2;}}if(ln(o)!=z){{return 3;}}if(sin(z)!=z){{return 4;}}if(cos(z)!=o){{return 5;}}if(tan(z)!=z){{return 6;}}return 0;}}"
        );
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            assert_eq!(status(&source, optimization), 0, "{ty} {optimization:?}");
        }
    }
}

#[test]
fn signed_minimum_abs_uses_the_existing_integer_overflow_trap() {
    let source = "int main(){int x=-9223372036854775808;return int(abs(x));}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_ne!(status(source, optimization), 0);
    }
}

#[test]
fn package_members_shadow_prelude_and_imports_do_not_open_or_change_it() {
    let shadow = compile(
        "double exp(double x){return x+1.0;}int main(){double y=exp(2.0);if(y!=3.0){return 1;}return 0;}",
        OptimizationLevel::O0,
    );
    assert!(!shadow.llvm.contains("@exp(double"));
    assert!(!shadow.llvm.contains("Core libm dependency"));

    let unused = compile(
        "int unused(){double x=exp(1.0);println(\"unused\");return 0;}int main(){return 0;}",
        OptimizationLevel::O0,
    );
    assert!(!unused.llvm.contains("Core libm dependency"));
    assert!(!unused.llvm.contains("aether_string_write"));

    let qualified = "int main(){double x=std.Math.exp(1.0);return 0;}";
    assert!(
        compile_source_with_optimization(
            &SourceFile::new("bad.ae", qualified),
            &[],
            OptimizationLevel::O0
        )
        .is_err()
    );

    let lexical = "int main(){double exp=2.0;double y=exp(1.0);return 0;}";
    let diagnostics = compile_source_with_optimization(
        &SourceFile::new("lexical.ae", lexical),
        &[],
        OptimizationLevel::O0,
    )
    .unwrap_err();
    assert_eq!(diagnostics[0].code, "E0215");
}

#[test]
fn mir_and_ssa_reject_malformed_core_identity_independently() {
    let hir = analyze(
        parse_source(&SourceFile::new(
            "corrupt.ae",
            "int main(){double x=exp(1.0);return 0;}",
        ))
        .unwrap(),
    )
    .unwrap();
    let mir = lower_hir(hir);
    let verified = verify_mir(mir.clone()).unwrap();

    let mut bad_mir = mir;
    let call = bad_mir.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::Core(call) => Some(call),
            _ => None,
        })
        .unwrap();
    call.function.identity.member = "sin".into();
    assert!(verify_mir(bad_mir).is_err());

    let mut bad_ssa = build_ssa(&verified);
    let call = bad_ssa.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::Core(call) => Some(call),
            _ => None,
        })
        .unwrap();
    call.function.symbol = CoreSymbol::Sin;
    assert!(verify_ssa(bad_ssa).is_err());
}
