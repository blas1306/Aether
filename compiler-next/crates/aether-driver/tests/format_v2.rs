//! FORMAT-V2 explicit fixed/scientific decimal formatting qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session_with_optimization,
};

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-format-v2-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn write(&self, relative: &str, source: &str) -> PathBuf {
        let path = self.0.join(relative);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, source).unwrap();
        path
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    let directory = Directory::new("source");
    let entry = directory.write("main.ae", source);
    compile_session_with_optimization(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn execute(
    compilation: &aether_driver::Compilation,
    optimization: OptimizationLevel,
) -> std::process::Output {
    let directory = Directory::new("native");
    let executable = directory.0.join("program");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    Command::new(executable).output().unwrap()
}

fn compile_and_execute(source: &str, optimization: OptimizationLevel) -> std::process::Output {
    execute(&compile(source, optimization), optimization)
}

#[test]
fn fixed_and_scientific_are_byte_exact_at_o0_o2() {
    let source = r"package main;import std.Format;
int main(){
 float64 tieEvenLow=2.5;float64 tieEvenHigh=3.5;float64 negativeLow=-2.5;float64 negativeHigh=-3.5;
 float64 binaryBelow=2.675;float64 carry=9.999;float64 positiveZero=0.0;float64 negativeZero=-0.0;
 println(std.Format.fixed(tieEvenLow,0));println(std.Format.fixed(tieEvenHigh,0));
 println(std.Format.fixed(negativeLow,0));println(std.Format.fixed(negativeHigh,0));
 println(std.Format.fixed(binaryBelow,2));println(std.Format.fixed(carry,2));
 println(std.Format.fixed(positiveZero,3));println(std.Format.fixed(negativeZero,3));
 println(std.Format.scientific(tieEvenLow,0));println(std.Format.scientific(tieEvenHigh,2));
 println(std.Format.scientific(binaryBelow,2));println(std.Format.scientific(carry,2));
 println(std.Format.scientific(positiveZero,3));println(std.Format.scientific(negativeZero,3));
 float32 binaryAbove=2.65;float32 carry32=9.999;
 println(std.Format.fixed(binaryAbove,1));println(std.Format.scientific(binaryAbove,1));
 println(std.Format.fixed(carry32,1));println(std.Format.scientific(carry32,2));
 return 0;
}";
    // Vectors were generated independently with Python Decimal.from_float and
    // IEEE bit-pattern widening, then frozen here rather than using the runtime
    // under test as its own oracle.
    let expected = b"2\n4\n-2\n-4\n2.67\n10.00\n0.000\n-0.000\n2e+0\n3.50e+0\n2.67e+0\n1.00e+1\n0.000e+0\n-0.000e+0\n2.7\n2.7e+0\n10.0\n1.00e+1\n";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let output = compile_and_execute(source, optimization);
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(output.stdout, expected, "{optimization:?}");
    }
}

#[test]
fn ieee_extremes_special_values_and_high_precision_are_exact() {
    let source = r"package main;import std.Format;
int main(){
 float32 fmax=3.4028235e38;float32 fsub=1e-45;float32 fnormal=1.17549435e-38;
 float64 dmax=1.7976931348623157e308;float64 dsub=5e-324;float64 dnormal=2.2250738585072014e-308;
 println(std.Format.fixed(fmax,0));println(std.Format.fixed(fsub,50));
 println(std.Format.scientific(fmax,2));println(std.Format.scientific(fsub,2));println(std.Format.scientific(fnormal,2));
 println(std.Format.fixed(dmax,0));println(std.Format.scientific(dmax,2));
 println(std.Format.scientific(dsub,2));println(std.Format.scientific(dnormal,2));
 float64 nan=0.0/0.0;float64 inf=1.0/0.0;float64 ninf=-1.0/0.0;
 println(std.Format.fixed(nan,18446744073709551615));
 println(std.Format.fixed(inf,99));println(std.Format.scientific(ninf,99));
 return 0;
}";
    let max_f64 = "179769313486231570814527423731704356798070567525844996598917476803157260780028538760589558632766878171540458953514382464234321326889464182768467546703537516986049910576551282076245490090389328944075868508455133942304583236903222948165808559332123348274797826204144723168738177180919299881250404026184124858368";
    let expected = format!(
        "340282346638528859811704183484516925440\n0.00000000000000000000000000000000000000000000140130\n3.40e+38\n1.40e-45\n1.18e-38\n{max_f64}\n1.80e+308\n4.94e-324\n2.23e-308\nNaN\nInf\n-Inf\n"
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let output = compile_and_execute(source, optimization);
        assert!(output.status.success());
        assert_eq!(output.stdout, expected.as_bytes(), "{optimization:?}");
    }
}

#[test]
fn package_surface_works_across_modules_and_prefers_exact_float_overload() {
    let directory = Directory::new("modules");
    let entry = directory.write(
        "main.ae",
        "package App;import App.Values;int main(){string a=App.Values.asFixed();string b=App.Values.asScientific();println(a);println(b);return 0;}",
    );
    directory.write(
        "values.ae",
        "package App.Values;import std.Format as fmt;public string asFixed(){float32 x=2.65;return fmt.fixed(x,1);}public string asScientific(){float64 x=0.03125;return fmt.scientific(x,4);}",
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            optimization,
        )
        .unwrap();
        assert!(compilation.llvm.contains("fpext float"));
        let output = execute(&compilation, optimization);
        assert!(output.status.success());
        assert_eq!(output.stdout, b"2.7\n3.1250e-2\n");
    }
}

#[test]
fn precision_limit_traps_before_truncation_or_allocation() {
    let source = r"package main;import std.Format;
int main(){float64 value=1.0;string impossible=std.Format.fixed(value,18446744073709551615);return int(byteLength(impossible));}";
    let compilation = compile(source, OptimizationLevel::O0);
    assert!(compilation.llvm.contains("precision_too_large"));
    let output = execute(&compilation, OptimizationLevel::O0);
    assert!(!output.status.success());
}

#[test]
fn ambient_rounding_mode_does_not_change_decimal_rounding() {
    let source = r"package main;import std.Format;
int main(){float64 a=2.5;float64 b=2.675;float64 c=9.999;println(std.Format.fixed(a,0));println(std.Format.fixed(b,2));println(std.Format.scientific(c,2));return 0;}";
    let compilation = compile(source, OptimizationLevel::O0);
    let directory = Directory::new("rounding-mode");
    let ir = directory.write("program.ll", &compilation.llvm);
    let helper = directory.write(
        "rounding.c",
        "#include <fenv.h>\n__attribute__((constructor)) static void upward(void){fesetround(FE_UPWARD);}\n",
    );
    let executable = directory.0.join("program");
    let linked = Command::new("clang")
        .args(["-O0", "-Wno-override-module", "-x", "ir"])
        .arg(ir)
        .args(["-x", "c"])
        .arg(helper)
        .arg("-o")
        .arg(&executable)
        .args(["-lstdc++", "-lm"])
        .output()
        .unwrap();
    assert!(
        linked.status.success(),
        "{}",
        String::from_utf8_lossy(&linked.stderr)
    );
    let output = Command::new(executable).output().unwrap();
    assert!(output.status.success());
    assert_eq!(output.stdout, b"2\n2.67\n1.00e+1\n");
}

#[test]
fn reachability_and_existing_shortest_format_remain_separate() {
    let plain = compile(
        "package main;import std.Format;int main(){float64 x=2.675;println(str(x));return 0;}",
        OptimizationLevel::O0,
    );
    assert!(!plain.llvm.contains("aether_format_explicit_f64"));
    assert!(!plain.llvm.contains("chars_formati"));
    let plain_output = execute(&plain, OptimizationLevel::O0);
    assert!(plain_output.status.success());
    assert_eq!(plain_output.stdout, b"2.675\n");

    let formatted = compile(
        "package main;import std.Format;int main(){float64 x=2.675;println(std.Format.fixed(x,2));return 0;}",
        OptimizationLevel::O0,
    );
    assert!(formatted.llvm.contains("aether_format_explicit_f64"));
    assert!(formatted.llvm.contains("chars_formati"));
}

#[test]
fn format_api_fails_closed_without_import_or_with_wrong_types() {
    for source in [
        "package main;int main(){float64 x=1.0;string s=std.Format.fixed(x,2);return 0;}",
        "package main;import std.Format;int main(){string s=std.Format.fixed(true,2);return 0;}",
        "package main;import std.Format;int main(){float64 x=1.0;string s=std.Format.fixed(x,-1);return 0;}",
    ] {
        let directory = Directory::new("invalid");
        let entry = directory.write("main.ae", source);
        assert!(
            CompilationSession::discover(&entry)
                .and_then(|session| {
                    compile_session_with_optimization(session, &[], OptimizationLevel::O0)
                })
                .is_err(),
            "{source}"
        );
    }
}
