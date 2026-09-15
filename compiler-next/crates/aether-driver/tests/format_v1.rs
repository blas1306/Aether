//! FORMAT-V1 canonical scalar strings and interpolation qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{
    InterpolationConversion, InterpolationFragment, InterpolationSizePlan, SourceFile, StringOp,
    StringOwnership, analyze, parse_source,
};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-format-v1-{}-{}",
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

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("format_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn execute(llvm: &str, optimization: OptimizationLevel) -> std::process::Output {
    let directory = Directory::new();
    let ir = directory.0.join("program.ll");
    let executable = directory.0.join("program");
    fs::write(&ir, llvm).unwrap();
    let option = match optimization {
        OptimizationLevel::O0 => "-O0",
        OptimizationLevel::O2 => "-O2",
    };
    let linked = Command::new("clang")
        .args(["-Wno-override-module", option, "-x", "ir"])
        .arg(&ir)
        .arg("-o")
        .arg(&executable)
        .arg("-lstdc++")
        .output()
        .unwrap();
    assert!(
        linked.status.success(),
        "{}",
        String::from_utf8_lossy(&linked.stderr)
    );
    Command::new(executable).output().unwrap()
}

#[test]
fn scalar_spellings_and_float_thresholds_are_byte_exact_at_o0_o2() {
    let source = r#"int main(){
int8 a=-128;int16 b=-32768;int32 c=-2147483648;int64 d=-9223372036854775808;
uint8 e=255;uint16 f=65535;uint32 g=4294967295;uint64 h=18446744073709551615;
isize i=-9223372036854775808;usize j=18446744073709551615;
println("${a}|${b}|${c}|${d}|${e}|${f}|${g}|${h}|${i}|${j}");
println("${true}|${false}|${1e-6}|${1e-7}|${1e20}|${1e21}|${-0.0}|${1.0/0.0}|${-1.0/0.0}|${0.0/0.0}");
float32 fmax=3.4028235e38;float32 fmin=1e-45;
println("${fmax}|${fmin}|${1.7976931348623157e308}|${5e-324}");
println(str(1.5));
return 0;}"#;
    let expected = b"-128|-32768|-2147483648|-9223372036854775808|255|65535|4294967295|18446744073709551615|-9223372036854775808|18446744073709551615\ntrue|false|0.000001|1e-7|100000000000000000000|1e+21|-0|Inf|-Inf|NaN\n3.4028235e+38|1e-45|1.7976931348623157e+308|5e-324\n1.5\n";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let output = execute(&compilation.llvm, optimization);
        assert!(output.status.success());
        assert_eq!(output.stdout, expected);
    }
}

#[test]
fn char_utf8_nul_and_literal_escape_are_exact() {
    let source = "int main(){char a='A';char b='é';char c='€';char d='𐍈';char z='\\0';print(\"${a}${b}${c}${d}${z}|\\${a}|$20|{x}|{{}}\");return 0;}";
    let compilation = compile(source, OptimizationLevel::O0);
    let output = execute(&compilation.llvm, OptimizationLevel::O0);
    assert!(output.status.success());
    assert_eq!(output.stdout, "Aé€𐍈\0|${a}|$20|{x}|{{}}".as_bytes());
}

#[test]
fn interpolation_keeps_a_structured_plan_and_one_publication() {
    let compilation = compile(
        "int main(){int x=3;string s=\"v=${x + 4}\";println(s);return 0;}",
        OptimizationLevel::O0,
    );
    assert!(compilation.dumps[&Emit::Hir].contains("Interpolate"));
    assert!(compilation.dumps[&Emit::Mir].contains("Interpolate"));
    assert!(compilation.dumps[&Emit::Ssa].contains("Interpolate"));
    assert!(!compilation.dumps[&Emit::Ssa].contains("Concat"));
    assert!(
        compilation
            .llvm
            .contains("call ptr @aether_string_allocate")
    );
}

#[test]
fn malformed_and_unsupported_fields_fail_closed() {
    for (source, text) in [
        ("int main(){string s=\"${}\";return 0;}", "cannot be empty"),
        (
            "int main(){string s=\"${1\";return 0;}",
            "missing its closing",
        ),
        (
            "struct S{int x;}int main(){S s=S(1);string x=\"${s}\";return 0;}",
            "not interpolable",
        ),
        (
            "int main(){string s=\"x\";string x=str(s);return 0;}",
            "no v1 signature",
        ),
    ] {
        let errors = compile_source_with_optimization(
            &SourceFile::new("bad.ae", source),
            &[],
            OptimizationLevel::O0,
        )
        .unwrap_err();
        assert!(
            errors.iter().any(|error| error.message.contains(text)),
            "{errors:#?}"
        );
    }
}

#[test]
fn format_runtime_is_reachable_only_from_str_or_interpolation() {
    let plain = compile(
        "int main(){string x=\"plain\";println(x);return 0;}",
        OptimizationLevel::O0,
    );
    assert!(!plain.llvm.contains("aether_format_i64"));
    assert!(!plain.llvm.contains("to_chars"));
    let formatted = compile(
        "int main(){string x=str(7);println(x);return 0;}",
        OptimizationLevel::O0,
    );
    assert!(formatted.llvm.contains("aether_format_i64"));
    let ssa = {
        let ast = aether_frontend::parse_source(&SourceFile::new(
            "x.ae",
            "int main(){string x=\"${7}\";return 0;}",
        ))
        .unwrap();
        let hir = aether_frontend::analyze(ast).unwrap();
        let mir = aether_middle::verify_mir(aether_middle::lower_hir(hir)).unwrap();
        aether_middle::verify_ssa(aether_middle::build_ssa(&mir)).unwrap()
    };
    assert!(ssa.as_ssa().functions.iter().flat_map(|f| &f.blocks).flat_map(|b| &b.instructions).any(|i| matches!(&i.op, SsaOp::String(op) if matches!(op.as_ref(), StringOp::Interpolate { .. }))));
}

#[test]
fn mir_and_ssa_reject_independent_interpolation_corruptions() {
    let source = SourceFile::new("corrupt.ae", "int main(){string x=\"${1}${2}\";return 0;}");
    let mir = lower_hir(analyze(parse_source(&source).unwrap()).unwrap());
    verify_mir(mir.clone()).unwrap();

    for corruption in 0..4 {
        let mut damaged = mir.clone();
        let instruction = damaged
            .functions
            .iter_mut()
            .flat_map(|function| &mut function.blocks)
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(&instruction.value, Rvalue::String(op) if matches!(op.as_ref(), StringOp::Interpolate { .. })))
            .unwrap();
        let Rvalue::String(op) = &mut instruction.value else {
            unreachable!()
        };
        let StringOp::Interpolate {
            fragments,
            ownership,
            size_plan,
        } = op.as_mut()
        else {
            unreachable!()
        };
        match corruption {
            0 => fragments.swap(0, 1),
            1 => {
                let InterpolationFragment::Hole { ty, .. } = &mut fragments[0] else {
                    unreachable!()
                };
                *ty = aether_frontend::TypeId::BOOL;
            }
            2 => {
                let InterpolationFragment::Hole { conversion, .. } = &mut fragments[0] else {
                    unreachable!()
                };
                *conversion = InterpolationConversion::StringBorrow;
            }
            3 => {
                *ownership = StringOwnership::Borrowed;
                *size_plan = InterpolationSizePlan::Unchecked;
            }
            _ => unreachable!(),
        }
        assert!(verify_mir(damaged).is_err());
    }

    let verified = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();
    let mut missing_drop = ssa;
    for block in missing_drop
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
    {
        if let Some(index) = block
            .instructions
            .iter()
            .position(|instruction| matches!(instruction.op, SsaOp::Drop { .. }))
        {
            block.instructions.remove(index);
            assert!(verify_ssa(missing_drop).is_err());
            return;
        }
    }
    panic!("expected interpolation owner Drop");
}
