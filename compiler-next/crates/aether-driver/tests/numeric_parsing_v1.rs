//! NUMERIC-PARSING-V1 checked, locale-independent numeric conversion qualification.

use std::{fmt::Write, fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, build_path};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-numeric-parsing-v1-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn compile_and_run(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    let directory = Directory::new();
    let input = directory.0.join("main.ae");
    let executable = directory.0.join("program");
    fs::write(&input, source).unwrap();
    let compilation = build_path(
        &input,
        &executable,
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        &ClangToolchain::default().with_optimization(optimization),
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"));
    let output = Command::new(executable).output().unwrap();
    assert_eq!(output.status.code(), Some(0), "{source}");
    compilation
}

fn rejects(source: &str) -> bool {
    let directory = Directory::new();
    let input = directory.0.join("main.ae");
    let executable = directory.0.join("program");
    fs::write(&input, source).unwrap();
    build_path(&input, &executable, &[], &ClangToolchain::default()).is_err()
}

#[test]
fn integer_and_double_contract_runs_at_o0_o2() {
    let source = include_str!("../../../tests/programs/numeric_parsing_v1_smoke.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_and_run(source, optimization);
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            assert!(compilation.dumps[&phase].contains("ParseInt"));
            assert!(compilation.dumps[&phase].contains("ParseDouble"));
        }
        assert!(compilation.llvm.contains("@aether_text_parse_int"));
        assert!(compilation.llvm.contains("@aether_text_parse_double"));
        assert!(!compilation.llvm.contains("strtod"));
        assert!(!compilation.llvm.contains("strlen"));
    }
}

#[test]
fn module_types_and_reachability_are_closed() {
    assert!(rejects(
        "package main;int main(){std.Text.parseInt(\"1\");return 0;}"
    ));
    assert!(rejects(
        "package main;import std.Text;int main(){std.Text.parseInt();return 0;}"
    ));
    assert!(rejects(
        "package main;import std.Text;int main(){std.Text.parseDouble(1);return 0;}"
    ));
    assert!(rejects(
        "package main;import std.Text;int main(){std.Text.DoubleParseResult x=std.Text.parseInt(\"1\");return 0;}"
    ));

    let only_int = compile_and_run(
        "package main;import std.Text;int main(){match(std.Text.parseInt(\"1\")){std.Text.IntParseResult.Value(x)=>{return x-1;} std.Text.IntParseResult.Invalid=>{return 1;} std.Text.IntParseResult.Overflow=>{return 2;}}}",
        OptimizationLevel::O0,
    );
    assert!(only_int.llvm.contains("@aether_text_parse_int"));
    assert!(!only_int.llvm.contains("@aether_text_parse_double"));
    assert!(!only_int.llvm.contains("@aether_numeric_parse_double"));

    let only_double = compile_and_run(
        "package main;import std.Text as text;int main(){match(text.parseDouble(\"1\")){text.DoubleParseResult.Value(x)=>{if(x==1.0){return 0;}return 1;} text.DoubleParseResult.Invalid=>{return 2;} text.DoubleParseResult.Overflow=>{return 3;} text.DoubleParseResult.Underflow=>{return 4;}}}",
        OptimizationLevel::O0,
    );
    assert!(only_double.llvm.contains("@aether_text_parse_double"));
    assert!(!only_double.llvm.contains("@aether_text_parse_int"));
}

#[test]
fn finite_formatter_round_trips_and_long_inputs_remain_checked() {
    let mut values = vec![
        0.0_f64,
        -0.0,
        f64::MIN_POSITIVE,
        f64::MAX,
        f64::from_bits(1),
        f64::from_bits(0x000f_ffff_ffff_ffff),
        f64::from_bits(0x0010_0000_0000_0001),
    ];
    let mut state = 0x4d59_5df4_d0f3_3173_u64;
    while values.len() < 72 {
        state = state
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        let value = f64::from_bits(state);
        if value.is_finite() {
            values.push(value);
        }
    }
    let mut source = String::from(
        "package main;import std.Text;int roundTripInt(int x){match(std.Text.parseInt(str(x))){std.Text.IntParseResult.Value(y)=>{if(y!=x){return 1;}} std.Text.IntParseResult.Invalid=>{return 2;} std.Text.IntParseResult.Overflow=>{return 3;}}return 0;}int roundTrip(double x){match(std.Text.parseDouble(str(x))){std.Text.DoubleParseResult.Value(y)=>{if(x==0.0){if(1.0/x!=1.0/y){return 1;}}else{if(y!=x){return 2;}}} std.Text.DoubleParseResult.Invalid=>{return 3;} std.Text.DoubleParseResult.Overflow=>{return 4;} std.Text.DoubleParseResult.Underflow=>{return 5;}}return 0;}int main(){if(roundTripInt(-9223372036854775808)!=0||roundTripInt(9223372036854775807)!=0||roundTripInt(-1)!=0||roundTripInt(0)!=0||roundTripInt(1)!=0){return 6;}",
    );
    for value in values {
        write!(source, "if(roundTrip({value:?})!=0){{return 1;}}").unwrap();
    }
    let long = "9".repeat(4_000);
    write!(
        source,
        "match(std.Text.parseDouble(\"{long}x\")){{std.Text.DoubleParseResult.Invalid=>{{}} std.Text.DoubleParseResult.Value(v)=>{{return 2;}} std.Text.DoubleParseResult.Overflow=>{{return 3;}} std.Text.DoubleParseResult.Underflow=>{{return 4;}}}}return 0;}}"
    )
    .unwrap();
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        compile_and_run(&source, optimization);
    }
}
