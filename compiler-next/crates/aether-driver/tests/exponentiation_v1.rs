//! Cross-layer qualification for EXPONENTIATION-V1.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{PowerMode, SourceFile, analyze, parse_source};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("exponentiation_v1.ae", source),
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

struct Output(PathBuf);
impl Output {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-power-v1-{}-{}",
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

fn status(source: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    let compilation = compile(source, optimization);
    let output = Output::new();
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &output.0)
        .unwrap_or_else(|error| panic!("{error:#?}\n{}", compilation.llvm));
    Command::new(&output.0).status().unwrap()
}

#[test]
fn lexer_precedence_and_right_associativity_are_exact() {
    let parsed = parse_source(&SourceFile::new(
        "power_parse.ae",
        "int main(){return -2**2 + (-2)**2 + 2**3**2 + 2**-3;}",
    ))
    .unwrap();
    let ast = format!("{parsed:#?}");
    assert!(ast.matches("Power").count() >= 5, "{ast}");
    assert!(ast.contains("Negate"));
    let source = "int main(){return 2**=3;}";
    assert!(parse_source(&SourceFile::new("bad_power.ae", source)).is_err());
    assert!(
        compile_source_with_optimization(
            &SourceFile::new("bad_power.ae", "int main(){return 2***3;}"),
            &[],
            OptimizationLevel::O0,
        )
        .is_err()
    );
    compile(
        "int main(){int x=2;x*=3;return *(&x)-6;}",
        OptimizationLevel::O0,
    );
}

#[test]
fn all_integer_types_aliases_and_heterogeneous_exponents_are_admitted() {
    let source = r"alias Tiny=int8;int main(){
      int8 a=2;int16 b=2;int32 c=2;int64 d=2;uint8 e=2;uint16 f=2;
      uint32 g=2;uint64 h=2;isize i=2;usize j=2;Tiny t=2;uint64 n=3;
      if(a**n!=8||b**n!=8||c**n!=8||d**n!=8||e**n!=8||f**n!=8){return 1;}
      if(g**n!=8||h**n!=8||i**n!=8||j**n!=8||t**n!=8){return 2;}
      return 0;
    }";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization).code(), Some(0));
    }
}

#[test]
fn operator_and_core_pow_share_power_specs_and_shadowing_still_wins() {
    let compilation = compile(
        "int main(){int a=2;uint8 e=5;int x=a**e;int y=pow(a,e);return x-y;}",
        OptimizationLevel::O0,
    );
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        assert!(
            dump.matches("IntegerChecked").count() >= 2,
            "{phase:?}\n{dump}"
        );
    }
    assert!(compilation.dumps[&Emit::Hir].contains("CoreSymbolKey"));
    let shadow = compile(
        "int pow(int a,int b){return a+b;}int main(){return pow(2,3)-5;}",
        OptimizationLevel::O0,
    );
    assert!(!shadow.dumps[&Emit::Hir].contains("PowerSpec"));
}

#[test]
fn integer_boundaries_shortcuts_overflow_and_negative_domain_are_correct() {
    let valid = "int main(){if(0**0!=1||0**uint64(18446744073709551615)!=0||1**uint64(18446744073709551615)!=1||(-1)**uint64(18446744073709551615)!=-1||(-2)**63!=-9223372036854775808){return 1;}return 0;}";
    let overflow = "int f(int b,uint8 e){return b**e;}int main(){return f(-2,64);}";
    let negative = "int f(int e){return 2**e;}int main(){return f(-1);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(valid, optimization).code(), Some(0));
        assert!(!status(overflow, optimization).success());
        assert!(!status(negative, optimization).success());
    }
    assert!(
        compile_source_with_optimization(
            &SourceFile::new("negative_constant.ae", "int main(){return 2**-1;}"),
            &[],
            OptimizationLevel::O0,
        )
        .is_err()
    );
    assert!(
        compile_source_with_optimization(
            &SourceFile::new("overflow_constant.ae", "int main(){return (-2)**64;}"),
            &[],
            OptimizationLevel::O0,
        )
        .is_err()
    );
}

#[test]
fn float_integer_and_float_libm_are_distinct_and_native() {
    let source = r"int main(){
      float32 a=float32(2.0)**int8(-3);float64 b=2.0**uint64(10);
      double n=(-2.0)**0.5;float32 nf=float32(-2.0)**float32(0.5);
      double z=(-0.0)**int8(3);double ni=0.0-1.0/0.0;
      double p=(-1.0)**int64(-9223372036854775808);
      double q=(-1.0)**uint64(18446744073709551615);
      if(a!=float32(0.125)||b!=1024.0){return 1;}
      if(n==n||nf==nf){return 2;}if(1.0/z!=ni){return 3;}
      if(p!=1.0||q!=-1.0){return 4;}return 0;
    }";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization).code(), Some(0));
    }
    let compilation = compile(source, OptimizationLevel::O0);
    let hir = &compilation.dumps[&Emit::Hir];
    assert!(hir.contains("FloatInteger") && hir.contains("FloatLibm"));
    assert!(compilation.llvm.contains("@pow(double, double)"));
    assert!(compilation.llvm.contains("@powf(float, float)"));
    assert!(!compilation.llvm.contains("fast"));
}

#[test]
fn operands_are_evaluated_once_in_left_to_right_order() {
    let compilation = compile(
        "int base(){return 2;}uint8 exponent(){return 3;}int main(){return base()**exponent()-8;}",
        OptimizationLevel::O0,
    );
    let calls = compilation
        .llvm
        .lines()
        .filter(|line| line.contains(" = call "))
        .filter(|line| line.contains("base") || line.contains("exponent"))
        .collect::<Vec<_>>();
    assert_eq!(calls.len(), 2, "{}", compilation.llvm);
    assert!(calls[0].contains("base"), "{calls:#?}");
    assert!(calls[1].contains("exponent"), "{calls:#?}");
}

#[test]
fn invalid_matrix_and_contextual_literals_follow_the_closed_rules() {
    compile(
        "int main(){float32 x=2**3;float32 y=pow(2,3);double z=2**3.0;return int(x+y+z)-24;}",
        OptimizationLevel::O0,
    );
    for source in [
        "int main(){bool x=true;return int(x**2);}",
        "int main(){int x=2;double y=2.0;return x**y;}",
        "T f<T>(T x){return x**2;}int main(){return 0;}",
    ] {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("bad_power.ae", source),
                &[],
                OptimizationLevel::O0,
            )
            .is_err(),
            "unexpectedly accepted {source}"
        );
    }
}

#[test]
fn mir_and_ssa_power_contract_corruption_is_rejected() {
    let hir = analyze(
        parse_source(&SourceFile::new(
            "power_corrupt.ae",
            "int f(int x,uint8 e){return x**e;}int main(){return f(2,3)-8;}",
        ))
        .unwrap(),
    )
    .unwrap();
    let raw = lower_hir(hir);
    let verified = verify_mir(raw.clone()).unwrap();
    let mut bad_mir = raw;
    let spec = bad_mir
        .functions
        .iter_mut()
        .flat_map(|f| &mut f.blocks)
        .flat_map(|b| &mut b.instructions)
        .find_map(|i| match &mut i.value {
            Rvalue::Power { spec, .. } => Some(spec),
            _ => None,
        })
        .unwrap();
    spec.mode = PowerMode::FloatInteger;
    assert!(verify_mir(bad_mir).is_err());

    let mut bad_ssa = build_ssa(&verified);
    let spec = bad_ssa
        .functions
        .iter_mut()
        .flat_map(|f| &mut f.blocks)
        .flat_map(|b| &mut b.instructions)
        .find_map(|i| match &mut i.op {
            SsaOp::Power { spec, .. } => Some(spec),
            _ => None,
        })
        .unwrap();
    spec.overflow_trap = false;
    assert!(verify_ssa(bad_ssa).is_err());
}

#[test]
fn libm_and_helpers_are_reachability_driven_and_logarithmic() {
    let dead = compile(
        "double dead(double x){return x**2.5;}int main(){return 0;}",
        OptimizationLevel::O0,
    );
    assert!(!dead.llvm.contains("@pow(double, double)"));
    let live = compile(
        "int main(){int x=2;uint64 e=63;return int(x**e);}",
        OptimizationLevel::O0,
    );
    assert!(live.llvm.contains("lshr i64"));
    assert!(live.llvm.contains("with.overflow"));
    assert!(live.llvm.contains("%finished"));
}
