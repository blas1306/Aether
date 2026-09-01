//! Cross-layer and native qualification for NEXT-VERTICAL-4.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, build_path, compile_session, compile_source, run_path,
};
use aether_frontend::{ModuleId, SourceFile, SourceId};

fn workspace() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap()
}

fn program(name: &str) -> PathBuf {
    workspace().join("tests/programs").join(name)
}

fn module_program(case: &str) -> PathBuf {
    workspace().join("tests/modules").join(case).join("main.ae")
}

fn temporary(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!(
        "aether-next-test-{}-{nonce}-{name}",
        std::process::id()
    ))
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn native_programs_execute_with_expected_status() {
    let toolchain = ClangToolchain::default();
    for (source, expected) in [
        ("sum_loop.ae", 45),
        ("branch.ae", 14),
        ("zero_loop.ae", 0),
        ("bool_local.ae", 6),
        ("direct_call.ae", 42),
        ("bool_return.ae", 1),
        ("nested_calls.ae", 25),
        ("forward_call.ae", 11),
        ("recursion.ae", 120),
        ("mutual_recursion.ae", 7),
        ("parameter_value.ae", 9),
    ] {
        let (_, status) = run_path(&program(source), &[], &toolchain).unwrap();
        assert_eq!(status.code(), Some(expected), "{source}");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn dynamic_overflow_traps_natively() {
    let (_, status) = run_path(
        &program("dynamic_overflow.ae"),
        &[],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert!(!status.success());
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn build_and_run_share_identical_pipeline_output() {
    let artifact = temporary("build");
    let built = build_path(
        &program("sum_loop.ae"),
        &artifact,
        &[Emit::Llvm],
        &ClangToolchain::default(),
    )
    .unwrap();
    let (run, status) = run_path(
        &program("sum_loop.ae"),
        &[Emit::Llvm],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(built.llvm, run.llvm);
    assert_eq!(status.code(), Some(45));
    let _ = fs::remove_file(artifact);
}

#[test]
fn dumps_are_deterministic_and_all_phase_boundaries_are_visible() {
    let text = fs::read_to_string(program("sum_loop.ae")).unwrap();
    let source = SourceFile::new("sum_loop.ae", text);
    let emits = [Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let first = compile_source(&source, &emits).unwrap();
    let second = compile_source(&source, &emits).unwrap();
    assert_eq!(first.dumps, second.dumps);
    assert_eq!(first.dumps.len(), 5);
    assert_eq!(first.timings_ns.len(), 8);
}

#[test]
fn differential_manifest_admission_and_codes_are_current() {
    let manifest = fs::read_to_string(workspace().join("tests/differential.tsv")).unwrap();
    let mut cases = 0;
    for line in manifest
        .lines()
        .filter(|line| !line.is_empty() && !line.starts_with('#'))
    {
        let fields: Vec<_> = line.split('\t').collect();
        assert_eq!(fields.len(), 5, "bad manifest row: {line}");
        let source_path = workspace().join("tests").join(fields[4]);
        let source = SourceFile::new(fields[4], fs::read_to_string(source_path).unwrap());
        let result = compile_source(&source, &[]);
        match fields[2].split_once(':') {
            Some(("accept", _)) => assert!(result.is_ok(), "{} should be accepted", fields[0]),
            Some(("reject", code)) => {
                assert_eq!(result.unwrap_err()[0].code, code, "{}", fields[0]);
            }
            None if fields[2] == "trap" => assert!(
                result.is_ok(),
                "{} should compile before trapping",
                fields[0]
            ),
            _ => panic!("unknown expectation {}", fields[2]),
        }
        cases += 1;
    }
    assert!(cases >= 20);
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn generated_llvm_is_accepted_by_clang_verifier() {
    let text = fs::read_to_string(program("sum_loop.ae")).unwrap();
    let llvm = compile_source(&SourceFile::new("sum_loop.ae", text), &[])
        .unwrap()
        .llvm;
    let ll = temporary("module.ll");
    let object = temporary("module.o");
    fs::write(&ll, llvm).unwrap();
    let output = Command::new("clang")
        .args(["-x", "ir", "-c"])
        .arg(&ll)
        .arg("-o")
        .arg(&object)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let _ = fs::remove_file(ll);
    let _ = fs::remove_file(object);
}

#[test]
fn scalar_function_diagnostics_are_stable_and_structured() {
    for (source, code) in [
        ("duplicate_function.ae", "E0211"),
        ("unknown_callee.ae", "E0212"),
        ("too_many_arguments.ae", "E0213"),
        ("too_few_arguments.ae", "E0213"),
        ("wrong_argument_type.ae", "E0214"),
        ("return_wrong_type.ae", "E0205"),
        ("unsupported_function_value.ae", "E0215"),
        ("malformed_function.ae", "E0104"),
    ] {
        let text = fs::read_to_string(program(source)).unwrap();
        let diagnostic = compile_source(&SourceFile::new(source, text), &[])
            .unwrap_err()
            .remove(0);
        assert_eq!(diagnostic.code, code, "{source}");
        assert!(diagnostic.span.is_some(), "{source}");
    }
}

#[test]
fn dumps_expose_function_identity_signatures_parameters_and_calls() {
    let text = fs::read_to_string(program("direct_call.ae")).unwrap();
    let result = compile_source(
        &SourceFile::new("direct_call.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &result.dumps[&phase];
        assert!(dump.contains("FunctionId"), "{phase:?}");
        assert!(dump.contains("parameters"), "{phase:?}");
        assert!(dump.contains("Call"), "{phase:?}");
    }
    let llvm = &result.dumps[&Emit::Llvm];
    assert!(llvm.contains("__aether_v2_m4_main_f3_add"));
    assert!(llvm.contains("__aether_v2_m4_main_f4_main"));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn multi_module_programs_build_and_run_natively() {
    for (case, expected) in [
        ("one_import", 42),
        ("multiple", 42),
        ("transitive", 42),
        ("shared", 41),
        ("cycle", 42),
        ("imported_main", 42),
    ] {
        let (_, status) = run_path(&module_program(case), &[], &ClangToolchain::default()).unwrap();
        assert_eq!(status.code(), Some(expected), "{case}");
    }
}

#[test]
fn discovery_assigns_unique_ids_and_processes_shared_dependencies_once() {
    let session = CompilationSession::discover(&module_program("shared")).unwrap();
    assert_eq!(session.modules().len(), 4);
    assert_eq!(session.entry(), ModuleId(0));
    for (index, module) in session.modules().iter().enumerate() {
        let index = u32::try_from(index).unwrap();
        assert_eq!(module.info().id, ModuleId(index));
        assert_eq!(module.info().source, SourceId(index));
        assert_eq!(module.source().id, module.info().source);
    }
    let common = session
        .modules()
        .iter()
        .filter(|module| module.info().name == "common")
        .count();
    assert_eq!(common, 1);
}

#[test]
fn module_dumps_and_mangling_are_deterministic_and_collision_free() {
    let emits = [Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let first = compile_session(
        CompilationSession::discover(&module_program("multiple")).unwrap(),
        &emits,
    )
    .unwrap();
    let second = compile_session(
        CompilationSession::discover(&module_program("multiple")).unwrap(),
        &emits,
    )
    .unwrap();
    assert_eq!(first.dumps, second.dumps);
    for phase in [Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &first.dumps[&phase];
        assert!(dump.contains("ModuleId"), "{phase:?}");
        assert!(dump.contains("source_name"), "{phase:?}");
        assert!(dump.contains("imports"), "{phase:?}");
    }
    let llvm = &first.llvm;
    assert!(llvm.contains("__aether_v2_m1_a_f3_foo"));
    assert!(llvm.contains("__aether_v2_m1_b_f3_foo"));
    assert_ne!(
        llvm.find("__aether_v2_m1_a_f3_foo"),
        llvm.find("__aether_v2_m1_b_f3_foo")
    );
    assert_eq!(first.timings_ns.len(), 10);
}

#[test]
fn multi_file_diagnostics_are_structured_and_keep_source_provenance() {
    for (case, code, source_name) in [
        ("errors/unknown_function", "E0222", "main.ae"),
        ("errors/not_imported", "E0223", "a.ae"),
        ("errors/imported_semantic", "E0202", "broken.ae"),
        ("errors/unknown_module", "E0221", "main.ae"),
        ("errors/invalid_qualified", "E0224", "main.ae"),
        ("errors/duplicate_import", "E0220", "main.ae"),
        ("errors/malformed_import", "E0100", "main.ae"),
        ("errors/imported_unsupported", "E0001", "broken.ae"),
    ] {
        let error = CompilationSession::discover(&module_program(case))
            .and_then(|session| compile_session(session, &[]))
            .unwrap_err()
            .remove(0);
        assert_eq!(error.code, code, "{case}");
        assert_eq!(error.source_name.as_deref(), Some(source_name), "{case}");
        assert!(error.span.is_some(), "{case}");
    }

    let error = CompilationSession::discover(&module_program("errors/missing_module"))
        .unwrap_err()
        .remove(0);
    assert_eq!(error.code, "E0701");
    assert_eq!(error.source_name.as_deref(), Some("main.ae"));
    assert!(error.span.is_some());
}

#[test]
fn vertical3_scalar_contract_is_canonical_and_explicit() {
    let source = SourceFile::new(
        "scalars.ae",
        r"
alias Tiny = int8;
alias TinyChain = Tiny;
int64 signed_widen(TinyChain x) { int16 a = x; int32 b = a; return b; }
uint64 unsigned_widen(byte x) { uint16 a = x; uint32 b = a; return b; }
float64 float_widen(float x) { return x; }
float32 add32(float32 a,float32 b){return a+b;}
bool feq(float64 a,float64 b){return a==b;} bool fne(float64 a,float64 b){return a!=b;}
bool flt(float64 a,float64 b){return a<b;} bool fle(float64 a,float64 b){return a<=b;}
bool fgt(float64 a,float64 b){return a>b;} bool fge(float64 a,float64 b){return a>=b;}
bool default_float(){return 3.14==3.14;} bool default_integer(){return 7==7;}
int main() {
    Tiny lo = -128; int8 hi = 127;
    uint8 zero = 0; byte top = 255;
    isize si = -1; usize ui = 1;
    float32 f = 1.5; double d = float_widen(f) * 2.0;
    if (lo < hi) { if (zero < top) { if (d == 3.0) { return signed_widen(42); } } }
    return 0;
}
",
    );
    let result = compile_source(&source, &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm]).unwrap();
    let hir = &result.dumps[&Emit::Hir];
    assert!(hir.contains("TinyChain"));
    assert!(
        hir.contains("canonical: Integer(\n            Int8")
            || hir.contains("canonical: Integer(Int8)")
    );
    assert!(hir.contains("SignExtend"));
    assert!(hir.contains("FloatExtend"));
    let llvm = &result.llvm;
    assert!(llvm.contains("sext i8"));
    assert!(llvm.contains("zext i8"));
    assert!(llvm.contains("fpext float"));
    assert!(llvm.contains("fmul double"));
    assert!(llvm.contains("fadd float"));
    assert!(llvm.contains("fcmp oeq double"));
    assert!(llvm.contains("icmp eq i64"));
    assert!(llvm.contains("icmp ult i8"));
    for predicate in ["une", "olt", "ole", "ogt", "oge"] {
        assert!(
            llvm.contains(&format!("fcmp {predicate} double")),
            "{predicate}"
        );
    }
}

#[test]
fn vertical3_ranges_conversions_and_alias_cycles_are_structured() {
    for (text, code) in [
        ("int main(){int8 x=128;return x;}", "E0209"),
        ("int main(){uint8 x=-1;return x;}", "E0209"),
        ("int main(){int16 x=1;int8 y=x;return y;}", "E0218"),
        ("int main(){int8 x=1;uint8 y=2;return x+y;}", "E0218"),
        ("int main(){float32 x=1.0;int64 y=x;return y;}", "E0218"),
        ("alias A=B;alias B=A;int main(){return 0;}", "E0226"),
        ("alias A=Missing;int main(){return 0;}", "E0204"),
    ] {
        let error = compile_source(&SourceFile::new("negative.ae", text), &[]).unwrap_err();
        assert_eq!(error[0].code, code, "{text}");
        assert!(error[0].span.is_some());
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical3_scalars_execute_and_unsigned_underflow_traps() {
    let ok = temporary("v3-ok");
    let compiled = compile_source(&SourceFile::new("v3.ae", "int main(){uint8 x=250;uint8 y=5;uint8 z=x+y;float32 f=1.5;float64 d=f+0.5;if(z==255){if(d==2.0){return 42;}}return 0;}"), &[]).unwrap();
    ClangToolchain::default()
        .link_executable(&compiled.llvm, &ok)
        .unwrap();
    assert_eq!(Command::new(&ok).status().unwrap().code(), Some(42));
    let _ = fs::remove_file(ok);

    let trap = temporary("v3-trap");
    let compiled = compile_source(
        &SourceFile::new(
            "trap.ae",
            "int main(){uint8 x=0;uint8 one=1;x=x-one;return 0;}",
        ),
        &[],
    )
    .unwrap();
    ClangToolchain::default()
        .link_executable(&compiled.llvm, &trap)
        .unwrap();
    assert!(!Command::new(&trap).status().unwrap().success());
    let _ = fs::remove_file(trap);
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical3_all_integer_boundaries_and_checked_families_compile() {
    let source = SourceFile::new(
        "widths.ae",
        r"
int8 s8(int8 a,int8 b){return a+b;} int16 s16(int16 a,int16 b){return a-b;}
int32 s32(int32 a,int32 b){return a*b;} uint8 u8(uint8 a,uint8 b){return a+b;}
uint16 u16(uint16 a,uint16 b){return a-b;} uint32 u32(uint32 a,uint32 b){return a*b;}
uint64 u64(uint64 a,uint64 b){return a+b;}
int main(){int8 a=-128;int8 b=127;int16 c=-32768;int16 d=32767;
int32 e=-2147483648;int32 f=2147483647;int64 g=-9223372036854775808;int64 g2=9223372036854775807;
uint8 h0=0;uint8 h=255;uint16 i0=0;uint16 i=65535;uint32 j0=0;uint32 j=4294967295;
uint64 k0=0;uint64 k=18446744073709551615;isize p=-9223372036854775808;usize q=18446744073709551615;
return s8(1,2);}
",
    );
    let llvm = compile_source(&source, &[]).unwrap().llvm;
    for intrinsic in [
        "llvm.sadd.with.overflow.i8",
        "llvm.ssub.with.overflow.i16",
        "llvm.smul.with.overflow.i32",
        "llvm.uadd.with.overflow.i8",
        "llvm.usub.with.overflow.i16",
        "llvm.umul.with.overflow.i32",
        "llvm.uadd.with.overflow.i64",
    ] {
        assert!(llvm.contains(intrinsic), "{intrinsic}");
    }
    let artifact = temporary("v3-widths");
    ClangToolchain::default()
        .link_executable(&llvm, &artifact)
        .unwrap();
    assert_eq!(Command::new(&artifact).status().unwrap().code(), Some(3));
    let _ = fs::remove_file(artifact);
}

#[test]
fn vertical3_alias_signatures_work_across_modules() {
    let root = temporary("v3-modules");
    fs::create_dir(&root).unwrap();
    fs::write(
        root.join("main.ae"),
        "import math;int main(){return math.answer(21);}",
    )
    .unwrap();
    fs::write(
        root.join("math.ae"),
        "alias Scalar=int16;int answer(Scalar x){return int(x+x);}",
    )
    .unwrap();
    let compilation = compile_session(
        CompilationSession::discover(&root.join("main.ae")).unwrap(),
        &[Emit::Hir],
    )
    .unwrap();
    assert!(compilation.dumps[&Emit::Hir].contains("Scalar"));
    assert!(compilation.dumps[&Emit::Hir].contains("ExplicitCast"));
    let _ = fs::remove_file(root.join("main.ae"));
    let _ = fs::remove_file(root.join("math.ae"));
    let _ = fs::remove_dir(root);
}

#[test]
fn vertical4_cast_diagnostics_and_dumps_are_structured() {
    for (text, code) in [
        ("int main(){return int8(128);}", "E0231"),
        ("int main(){return uint32(-1);}", "E0231"),
        ("int main(){return int32(2147483648);}", "E0231"),
        ("int main(){return int32(2147483648.0);}", "E0231"),
        ("int main(){return int(true);}", "E0232"),
        ("int main(){return bool(1);}", "E0232"),
    ] {
        let diagnostic = compile_source(&SourceFile::new("cast-error.ae", text), &[])
            .unwrap_err()
            .remove(0);
        assert_eq!(diagnostic.code, code, "{text}");
        assert!(diagnostic.span.is_some());
    }

    let text = fs::read_to_string(program("v4_casts.ae")).unwrap();
    let result = compile_source(
        &SourceFile::new("v4_casts.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(result.dumps[&Emit::Hir].contains("ExplicitCast"));
    for phase in [Emit::Mir, Emit::Ssa] {
        let dump = &result.dumps[&phase];
        assert!(dump.contains("Cast"), "{phase:?}");
        assert!(dump.contains("ConversionOutOfRange"), "{phase:?}");
    }
    assert!(result.llvm.contains("trap_conversion_out_of_range"));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical4_casts_execute_and_runtime_failures_trap() {
    let (_, status) = run_path(&program("v4_casts.ae"), &[], &ClangToolchain::default()).unwrap();
    assert_eq!(status.code(), Some(127));

    for source in [
        "v4_cast_trap.ae",
        "v4_signed_unsigned_trap.ae",
        "v4_unsigned_signed_trap.ae",
    ] {
        let (_, status) = run_path(&program(source), &[], &ClangToolchain::default()).unwrap();
        assert!(!status.success(), "{source}");
    }

    let artifact = temporary("v4-cast-boundaries");
    let source = SourceFile::new(
        "cast-boundaries.ae",
        "int main(){if(int32(3.9)==3){if(int32(-3.9)==-3){if(uint8(-0.9)==0){if(int8(-128.9)==-128){uint64 u=18446744073709551615;usize z=usize(u);uint64 back=uint64(z);isize s=-1;int64 signed_back=int64(s);float64 d=float64(back);float32 f=float32(d);if(signed_back==-1){if(d>0.0){if(f>0.0){return 42;}}}}}}}return 0;}",
    );
    let compilation = compile_source(&source, &[]).unwrap();
    ClangToolchain::default()
        .link_executable(&compilation.llvm, &artifact)
        .unwrap();
    assert_eq!(Command::new(&artifact).status().unwrap().code(), Some(42));
    let _ = fs::remove_file(artifact);
}

#[test]
fn vertical4_division_diagnostics_and_ir_contracts_are_structured() {
    for (text, code) in [
        ("int main(){return 1/0;}", "E0233"),
        ("int main(){return -9223372036854775808/-1;}", "E0234"),
        ("int main(){return int(4.0%2.0);}", "E0235"),
    ] {
        let diagnostic = compile_source(&SourceFile::new("division-error.ae", text), &[])
            .unwrap_err()
            .remove(0);
        assert_eq!(diagnostic.code, code, "{text}");
        assert!(diagnostic.span.is_some());
    }

    let text = fs::read_to_string(program("v4_division.ae")).unwrap();
    let result = compile_source(
        &SourceFile::new("v4_division.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(result.dumps[&Emit::Hir].contains("DivideIntegerSignedChecked"));
    for phase in [Emit::Mir, Emit::Ssa] {
        let dump = &result.dumps[&phase];
        assert!(dump.contains("DivisionByZero"), "{phase:?}");
        assert!(dump.contains("DivisionOverflow"), "{phase:?}");
        assert!(dump.contains("RemainderIntegerSignedChecked"), "{phase:?}");
    }
    assert!(result.llvm.contains("trap_division_by_zero"));
    assert!(result.llvm.contains("trap_division_overflow"));
    assert!(result.llvm.contains("fdiv double"));

    let widths = SourceFile::new(
        "division-widths.ae",
        r"
int8 s8(int8 a,int8 b){return a/b;} int16 s16(int16 a,int16 b){return a%b;}
int32 s32(int32 a,int32 b){return a/b;} int64 s64(int64 a,int64 b){return a%b;}
uint8 u8(uint8 a,uint8 b){return a/b;} uint16 u16(uint16 a,uint16 b){return a%b;}
uint32 u32(uint32 a,uint32 b){return a/b;} uint64 u64(uint64 a,uint64 b){return a%b;}
isize si(isize a,isize b){return a/b;} usize ui(usize a,usize b){return a%b;}
int main(){return s8(5,2);}
",
    );
    let llvm = compile_source(&widths, &[]).unwrap().llvm;
    for operation in [
        "sdiv i8", "srem i16", "sdiv i32", "srem i64", "udiv i8", "urem i16", "udiv i32",
        "urem i64",
    ] {
        assert!(llvm.contains(operation), "{operation}");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical4_division_and_remainder_execute_without_backend_ub() {
    for (source, expected) in [
        ("v4_division.ae", 42),
        ("v4_rem_min.ae", 0),
        ("v4_float_ieee.ae", 42),
    ] {
        let (_, status) = run_path(&program(source), &[], &ClangToolchain::default()).unwrap();
        assert_eq!(status.code(), Some(expected), "{source}");
    }
    for source in [
        "v4_div_zero.ae",
        "v4_div_overflow.ae",
        "v4_float_to_int_trap.ae",
        "v4_nan_to_int_trap.ae",
    ] {
        let (_, status) = run_path(&program(source), &[], &ClangToolchain::default()).unwrap();
        assert!(!status.success(), "{source}");
    }
}
