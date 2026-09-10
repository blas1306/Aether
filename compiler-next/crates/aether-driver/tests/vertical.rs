//! Cross-layer and native qualification through NEXT-VERTICAL-18.

use std::fmt::Write;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, build_path, compile_session, compile_source, run_path,
};
use aether_frontend::{
    Capability, ModuleId, SourceFile, SourceId, TargetProperties, TypeData, analyze, layout_of,
    parse_source,
};

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
    static NEXT_TEMPORARY: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let sequence = NEXT_TEMPORARY.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!(
        "aether-next-test-{}-{nonce}-{sequence}-{name}",
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
        ("v5_structs.ae", 42),
        ("v6_enums.ae", 42),
        ("v9_references.ae", 31),
        ("v9_scalar_ref.ae", 2),
        ("v9_aggregate_ref.ae", 5),
        ("v10_element_ref.ae", 11),
        ("v10_view.ae", 11),
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
    assert_eq!(
        first
            .timings_ns
            .keys()
            .filter(|key| !key.starts_with("frontend.detail."))
            .count(),
        8
    );
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
        ("v5_structs", 20),
        ("v6_enums", 42),
    ] {
        let (_, status) = run_path(&module_program(case), &[], &ClangToolchain::default()).unwrap();
        assert_eq!(status.code(), Some(expected), "{case}");
    }
}

#[test]
fn vertical5_struct_diagnostics_are_structured() {
    for (text, code) in [
        (
            "struct P{int x;int y;}int main(){P p=P(1);return 0;}",
            "E0246",
        ),
        ("struct P{int x;}int main(){P p=P(1,2);return 0;}", "E0246"),
        ("struct P{int x;}int main(){P p=P(true);return 0;}", "E0247"),
        ("struct P{int x;int x;}int main(){return 0;}", "E0241"),
        ("struct P{int x;}int main(){P p=P(1);return p.y;}", "E0243"),
        ("int main(){int x=1;return x.y;}", "E0244"),
        (
            "struct P{int x;}int main(){P p=P(1);p.x=true;return 0;}",
            "E0245",
        ),
        ("int main(){Missing p=Missing(1);return 0;}", "E0204"),
        ("struct Node{Node next;}int main(){return 0;}", "E0242"),
        ("struct A{B b;}struct B{A a;}int main(){return 0;}", "E0242"),
        (
            "struct P{int x;}struct P{int y;}int main(){return 0;}",
            "E0240",
        ),
        (
            "struct P{int x;}int P(int x){return x;}int main(){return 0;}",
            "E0240",
        ),
        ("struct P{int x;}alias P=int;int main(){return 0;}", "E0240"),
        (
            "struct A{int x;}struct B{int x;}int take(A a){return a.x;}int main(){B b=B(1);return take(b);}",
            "E0214",
        ),
    ] {
        let diagnostic = compile_source(&SourceFile::new("v5-error.ae", text), &[])
            .unwrap_err()
            .remove(0);
        assert_eq!(diagnostic.code, code, "{text}: {}", diagnostic.message);
        assert!(diagnostic.span.is_some(), "{text}");
    }
}

#[test]
fn vertical5_dumps_resolve_fields_places_and_aggregate_ssa() {
    let text = fs::read_to_string(program("v5_structs.ae")).unwrap();
    let result = compile_source(
        &SourceFile::new("v5_structs.ae", text),
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(result.dumps[&Emit::Ast].contains("Call"));
    let hir = &result.dumps[&Emit::Hir];
    assert!(hir.contains("StructInit"));
    assert!(hir.contains("StructId"));
    assert!(hir.contains("FieldId"));
    assert!(hir.contains("FloatExtend"));
    let mir = &result.dumps[&Emit::Mir];
    assert!(mir.contains("Place"));
    assert!(mir.contains("Aggregate"));
    let ssa = &result.dumps[&Emit::Ssa];
    assert!(ssa.contains("ExtractField"));
    assert!(ssa.contains("InsertField"));
    assert!(ssa.contains("Phi {"));
    let llvm = &result.dumps[&Emit::Llvm];
    assert!(llvm.contains("%aether.struct.0 = type"));
    assert!(llvm.contains("insertvalue"));
    assert!(llvm.contains("extractvalue"));
}

#[test]
fn vertical5_qualified_and_unqualified_type_resolution() {
    let compilation = compile_session(
        CompilationSession::discover(&module_program("v5_structs")).unwrap(),
        &[Emit::Hir, Emit::Llvm],
    )
    .unwrap();
    let hir = &compilation.dumps[&Emit::Hir];
    assert!(hir.contains("geometry"));
    assert!(hir.contains("Position"));
    assert!(hir.matches("name: \"Point\"").count() >= 2);

    let diagnostic = CompilationSession::discover(&module_program("errors/v5_unqualified"))
        .and_then(|session| compile_session(session, &[]))
        .unwrap_err()
        .remove(0);
    assert_eq!(diagnostic.code, "E0204");
    assert_eq!(diagnostic.source_name.as_deref(), Some("main.ae"));

    let diagnostic = CompilationSession::discover(&module_program("errors/v5_cross_nominality"))
        .and_then(|session| compile_session(session, &[]))
        .unwrap_err()
        .remove(0);
    assert_eq!(diagnostic.code, "E0214");
    assert_eq!(diagnostic.source_name.as_deref(), Some("main.ae"));
}

#[test]
fn vertical6_enum_diagnostics_are_structured() {
    for (text, code) in [
        ("enum A{X,}enum A{Y,}int main(){return 0;}", "E0240"),
        ("enum A{X,X,}int main(){return 0;}", "E0251"),
        ("enum A{X,}int main(){A a=A.X();return 0;}", "E0250"),
        ("enum A{X(int),}int main(){A a=A.X;return 0;}", "E0250"),
        ("enum A{X,}int main(){A a=A.Y;return 0;}", "E0252"),
        ("enum A{X(int),}int main(){A a=A.X();return 0;}", "E0253"),
        (
            "enum A{X(int),}int main(){A a=A.X(true);return 0;}",
            "E0254",
        ),
        ("int main(){int x=1;match(x){}return 0;}", "E0255"),
        (
            "enum A{X,}int main(){A a=A.X;match(a){A.X=>{return 1;}A.X=>{return 2;}}}",
            "E0256",
        ),
        (
            "enum A{X,}enum B{X,}int main(){A a=A.X;match(a){B.X=>{return 1;}}}",
            "E0257",
        ),
        (
            "enum A{X,Y,}int main(){A a=A.X;match(a){A.X=>{return 1;}}}",
            "E0258",
        ),
        (
            "enum Chain{Nil,Cons(int,Chain),}int main(){return 0;}",
            "E0259",
        ),
        (
            "struct A{B b;}enum B{Value(A),}int main(){return 0;}",
            "E0259",
        ),
        (
            "enum A{X,}int A(int x){return x;}int main(){return 0;}",
            "E0240",
        ),
        ("struct A{int x;}enum A{X,}int main(){return 0;}", "E0240"),
    ] {
        let diagnostic = compile_source(&SourceFile::new("v6-error.ae", text), &[])
            .unwrap_err()
            .remove(0);
        assert_eq!(diagnostic.code, code, "{text}: {}", diagnostic.message);
        assert!(diagnostic.span.is_some(), "{text}");
    }
}

#[test]
fn vertical6_dumps_expose_nominal_ids_switch_and_tagged_lowering() {
    let text = fs::read_to_string(program("v6_enums.ae")).unwrap();
    let result = compile_source(
        &SourceFile::new("v6_enums.ae", text),
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    let ast = &result.dumps[&Emit::Ast];
    assert!(ast.contains("AstEnum"));
    assert!(ast.contains("Match"));
    let hir = &result.dumps[&Emit::Hir];
    assert!(hir.contains("EnumId"));
    assert!(hir.contains("VariantId"));
    assert!(hir.contains("EnumInit"));
    assert!(hir.contains("HirMatchBinding"));
    for phase in [Emit::Mir, Emit::Ssa] {
        let dump = &result.dumps[&phase];
        assert!(dump.contains("EnumConstruct"), "{phase:?}");
        assert!(dump.contains("EnumDiscriminant"), "{phase:?}");
        assert!(dump.contains("EnumPayload"), "{phase:?}");
        assert!(dump.contains("Switch"), "{phase:?}");
    }
    let llvm = &result.dumps[&Emit::Llvm];
    assert!(llvm.contains("%aether.enum.0 = type"));
    assert!(llvm.contains("switch i32"));
    assert!(llvm.contains("insertvalue %aether.enum.0"));
    assert!(llvm.contains("extractvalue %aether.enum.0"));
}

#[test]
fn vertical6_qualified_alias_construction_and_matching_resolve() {
    let compilation = compile_session(
        CompilationSession::discover(&module_program("v6_enums")).unwrap(),
        &[Emit::Ast, Emit::Hir, Emit::Llvm],
    )
    .unwrap();
    assert!(compilation.dumps[&Emit::Ast].contains("VariantCall"));
    let hir = &compilation.dumps[&Emit::Hir];
    assert!(hir.contains("Numeric"));
    assert!(hir.contains("TypeId(13) = Number"));
    assert!(hir.contains("canonical: TypeId(\n            13"));
    assert!(compilation.llvm.contains("switch i32"));

    let diagnostic = CompilationSession::discover(&module_program("errors/v6_unqualified"))
        .and_then(|session| compile_session(session, &[]))
        .unwrap_err()
        .remove(0);
    assert_eq!(diagnostic.code, "E0204");
    assert_eq!(diagnostic.source_name.as_deref(), Some("main.ae"));
}

#[test]
fn vertical7_type_id_arena_is_canonical_nominal_and_deterministic() {
    let source = SourceFile::new(
        "type_ids.ae",
        r"
struct A { int x; }
struct B { int x; }
enum E { V(int) }
enum F { V(int) }
alias Whole = int64;
alias WholeAgain = Whole;
alias Position = A;
int64 convert(Whole value) { return int64(value); }
int main() {
    Position p = Position(1);
    E e = E.V(p.x);
    isize target_sized = isize(1);
    return convert(p.x);
}
",
    );
    let emits = [Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let first = compile_source(&source, &emits).unwrap();
    let second = compile_source(&source, &emits).unwrap();
    assert_eq!(first.dumps, second.dumps);
    assert_eq!(first.llvm, second.llvm);

    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &first.dumps[&phase];
        assert!(dump.contains("types (session-local)"), "{phase:?}");
        assert!(dump.contains("TypeId(4) = int64"), "{phase:?}");
        assert!(dump.contains("TypeId(9) = isize"), "{phase:?}");
        assert!(dump.contains("TypeId(13) = A"), "{phase:?}");
        assert!(dump.contains("TypeId(14) = B"), "{phase:?}");
        assert!(dump.contains("TypeId(15) = E"), "{phase:?}");
        assert!(dump.contains("TypeId(16) = F"), "{phase:?}");
    }
    let hir = &first.dumps[&Emit::Hir];
    assert!(hir.contains("WholeAgain"));
    assert!(hir.contains("Position"));
    assert!(hir.contains("ExplicitCast"));
    assert!(first.llvm.contains("%aether.struct.0 = type"));
    assert!(first.llvm.contains("%aether.struct.1 = type"));
    assert!(first.llvm.contains("%aether.enum.0 = type"));
    assert!(first.llvm.contains("%aether.enum.1 = type"));
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
    assert_eq!(
        first
            .timings_ns
            .keys()
            .filter(|key| !key.starts_with("frontend.detail."))
            .count(),
        10
    );
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
    assert!(hir.contains("TypeId(1) = int8"));
    assert!(hir.contains("canonical: TypeId(\n            1"));
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

#[test]
fn vertical8_generic_identity_instances_are_canonical_and_inference_is_local() {
    let source = SourceFile::new(
        "v8-instances.ae",
        r"
T identity<T>(T value){return value;}
T recurse<T>(T value){return recurse<T>(value);}
struct Pair<T,U>{T first;U second;}
int main(){
    int a=identity<int>(20);int b=identity<int>(21);int inferred=identity(1);
    float64 f=identity<float64>(2.0);
    Pair<int8,int8> small=Pair<int8,int8>(1,2);
    Pair<int8,float64> wide=Pair<int8,float64>(1,2.0);
    if(false){return recurse<int>(0);}
    return a+b+inferred;
}
",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let identity = hir
        .signatures()
        .iter()
        .find(|signature| signature.name == "identity")
        .unwrap();
    let instances = hir
        .instances()
        .iter()
        .filter(|instance| instance.function_id == identity.id)
        .collect::<Vec<_>>();
    assert_eq!(
        instances.len(),
        2,
        "repeated and inferred int calls reuse one instance"
    );
    assert_ne!(instances[0].id, instances[1].id);
    let recurse = hir
        .signatures()
        .iter()
        .find(|signature| signature.name == "recurse")
        .unwrap();
    assert_eq!(
        hir.instances()
            .iter()
            .filter(|instance| instance.function_id == recurse.id)
            .count(),
        1
    );
    let applications = hir
        .types()
        .entries()
        .filter_map(|(ty, data)| matches!(data, TypeData::StructInstance(_, _)).then_some(ty))
        .filter(|ty| !hir.types().contains_generic(*ty))
        .collect::<Vec<_>>();
    assert_eq!(applications.len(), 2);
    assert_ne!(applications[0], applications[1]);
    let layouts = applications
        .iter()
        .map(|ty| {
            layout_of(
                hir.types(),
                *ty,
                TargetProperties::LINUX_X86_64,
                hir.structs(),
                hir.enums(),
            )
            .unwrap()
        })
        .collect::<Vec<_>>();
    assert!(layouts.iter().any(|layout| layout.size == 2));
    assert!(layouts.iter().any(|layout| layout.size == 16));
}

#[test]
fn vertical8_generic_diagnostics_fail_closed() {
    for (text, code) in [
        ("T id<T,T>(T x){return x;}int main(){return 0;}", "E0260"),
        (
            "T id<T>(T x){return x;}int main(){return id<int,int>(1);}",
            "E0262",
        ),
        (
            "int id(int x){return x;}int main(){return id<int>(1);}",
            "E0262",
        ),
        (
            "T make<T>(){T x=make<T>();return x;}int main(){return make();}",
            "E0263",
        ),
        (
            "T add<T>(T a,T b){return a+b;}int main(){return 0;}",
            "E0268",
        ),
        (
            "bool same<T>(T a,T b){return a==b;}int main(){return 0;}",
            "E0268",
        ),
        (
            "struct Pair<T,U>{T a;U b;}int main(){Pair<int> p=Pair<int>(1);return 0;}",
            "E0261",
        ),
        ("struct Bad<T>{Bad<T> next;}int main(){return 0;}", "E0242"),
        (
            "struct Pair<T,U>{T a;U b;}int f<T>(){return f<Pair<T,T>>();}int main(){return f<int>();}",
            "E0265",
        ),
    ] {
        let Err(mut diagnostics) = compile_source(&SourceFile::new("v8-error.ae", text), &[])
        else {
            panic!("expected generic rejection: {text}");
        };
        let diagnostic = diagnostics.remove(0);
        assert_eq!(diagnostic.code, code, "{text}: {}", diagnostic.message);
        assert!(diagnostic.span.is_some() || code == "E0265");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical8_cross_module_generics_execute_natively() {
    let (compilation, status) = run_path(
        &module_program("v8_generics"),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(42));
    assert!(compilation.dumps[&Emit::Hir].contains("GenericParamId"));
    assert!(compilation.dumps[&Emit::Hir].contains("InstanceId"));
    assert!(compilation.llvm.contains("identity__g"));
    assert!(!compilation.dumps[&Emit::Mir].contains("GenericParam("));
    assert!(!compilation.dumps[&Emit::Ssa].contains("GenericParam("));
}

#[test]
fn vertical9_reference_types_are_canonical_and_capabilities_are_distinct() {
    let hir = analyze(
        parse_source(&SourceFile::new(
            "v9-types.ae",
            "int read(ref int x){return *x;}int main(){int x=1;ref int a=&x;ref int b=&x;ref mut int m=&mut x;return *a+*b+*m;}",
        ))
        .unwrap(),
    )
    .unwrap();
    let references = hir
        .types()
        .entries()
        .filter_map(|(ty, data)| matches!(data, TypeData::Reference { .. }).then_some(ty))
        .collect::<Vec<_>>();
    assert_eq!(references.len(), 2);
    let shared = references
        .iter()
        .find(|ty| {
            hir.types().reference_info(**ty) == Some((aether_frontend::TypeId::INT64, false))
        })
        .unwrap();
    let mutable = references
        .iter()
        .find(|ty| hir.types().reference_info(**ty) == Some((aether_frontend::TypeId::INT64, true)))
        .unwrap();
    assert_ne!(shared, mutable);
}

#[test]
fn vertical9_alias_aware_memory_boundary_is_explicit_and_selective() {
    let text = fs::read_to_string(program("v9_references.ae")).unwrap();
    let compilation = compile_source(
        &SourceFile::new("v9_references.ae", text),
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(compilation.dumps[&Emit::Ast].contains("AstReferenceType"));
    assert!(compilation.dumps[&Emit::Ast].contains("BorrowMutable"));
    assert!(compilation.dumps[&Emit::Hir].contains("address_taken: true"));
    assert!(compilation.dumps[&Emit::Hir].contains("ref mut"));
    assert!(compilation.dumps[&Emit::Mir].contains("Borrow"));
    assert!(compilation.dumps[&Emit::Mir].contains("Dereference"));
    assert!(compilation.dumps[&Emit::Ssa].contains("memory_locals"));
    assert!(compilation.dumps[&Emit::Ssa].contains("Store"));
    assert!(compilation.llvm.contains("alloca i64"));
    assert!(compilation.llvm.contains("load i64, ptr"));
    assert!(compilation.llvm.contains("store i64"));
    assert!(compilation.llvm.contains("_f4_getX(ptr %v0)"));
    assert!(!compilation.llvm.contains("_f4_getX(%aether.struct.0"));
    assert!(!compilation.llvm.contains("noalias"));

    let ordinary = compile_source(
        &SourceFile::new(
            "ordinary.ae",
            fs::read_to_string(program("v8_smoke.ae")).unwrap(),
        ),
        &[Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(!ordinary.llvm.contains("alloca"));
    assert!(!ordinary.dumps[&Emit::Ssa].contains("MemoryLocal("));
}

#[test]
fn vertical9_reference_diagnostics_fail_closed() {
    for (text, code) in [
        ("int main(){ref int r=&(1+2);return 0;}", "E0270"),
        ("int main(){int x=1;return *x;}", "E0271"),
        ("int main(){int x=1;ref int r=&x;*r=2;return x;}", "E0272"),
        (
            "ref int bad(ref int x){return x;}int main(){return 0;}",
            "E0273",
        ),
        (
            "struct Holder{ref int value;}int main(){return 0;}",
            "E0274",
        ),
        ("enum E{Some(ref int)}int main(){return 0;}", "E0275"),
        (
            "struct Pair<T,U>{T a;U b;}int main(){int x=1;ref int r=&x;Pair<ref int,int> p=Pair<ref int,int>(r,0);return 0;}",
            "E0276",
        ),
        (
            "T identity<T>(T x){return x;}int main(){int x=1;ref int r=&x;ref int copy=identity<ref int>(r);return *copy;}",
            "E0276",
        ),
        ("int main(){int x=1;ref int r=&x;r=&x;return 0;}", "E0277"),
        ("int main(){int x=1;ref int r=&x;return int(r);}", "E0278"),
        (
            "int main(){int x=1;ref int a=&x;ref int b=&x;if(a==b){return 1;}return 0;}",
            "E0279",
        ),
        (
            "int main(){int x=1;ref int s=&x;ref mut int m=&mut *s;return 0;}",
            "E0272",
        ),
        (
            "struct Point{int x;}int main(){ref Point p=&Point(1);return 0;}",
            "E0270",
        ),
        (
            "int identity(int x){return x;}int main(){ref int r=&identity(1);return 0;}",
            "E0270",
        ),
        (
            "int read(ref int x){return *x;}int main(){int x=1;return read(x);}",
            "E0214",
        ),
        ("int main(){ref int r=&missing;return 0;}", "E0202"),
    ] {
        let Err(mut diagnostics) = compile_source(&SourceFile::new("v9-error.ae", text), &[])
        else {
            panic!("expected reference rejection: {text}");
        };
        let diagnostic = diagnostics.remove(0);
        assert_eq!(diagnostic.code, code, "{text}: {}", diagnostic.message);
        assert!(diagnostic.span.is_some());
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical9_cross_module_reference_parameters_execute_natively() {
    let (compilation, status) = run_path(
        &module_program("v9_references"),
        &[Emit::Mir, Emit::Ssa, Emit::Llvm],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(9));
    assert!(compilation.llvm.contains("ptr %v"));
    assert!(!compilation.llvm.contains("noalias"));
}

#[test]
fn vertical10_buffer_types_are_canonical_and_lifecycle_properties_are_explicit() {
    let hir = analyze(
        parse_source(&SourceFile::new(
            "v10-types.ae",
            "int main(){Buffer<int> a=Buffer<int>(1,0);Buffer<int> b=Buffer<int>(2,0);View<int> r=view(a);ViewMut<int> w=view_mut(b);return r[0]+w[0];}",
        ))
        .unwrap(),
    )
    .unwrap();
    let buffers = hir
        .types()
        .entries()
        .filter_map(|(ty, data)| matches!(data, TypeData::Buffer { .. }).then_some(ty))
        .collect::<Vec<_>>();
    assert_eq!(buffers.len(), 1);
    assert_eq!(
        hir.types().buffer_element(buffers[0]),
        Some(aether_frontend::TypeId::INT64)
    );
    assert!(!hir.types().is_copy(buffers[0]));
    assert!(hir.types().needs_drop(buffers[0]));

    let views = hir
        .types()
        .entries()
        .filter_map(|(ty, data)| matches!(data, TypeData::View { .. }).then_some(ty))
        .collect::<Vec<_>>();
    assert_eq!(views.len(), 2);
    assert!(views.iter().all(|ty| hir.types().is_copy(*ty)));
    assert!(views.iter().all(|ty| !hir.types().needs_drop(*ty)));
    assert_ne!(views[0], views[1]);
}

#[test]
fn vertical10_dumps_expose_buffers_moves_cleanup_views_and_checked_indexing() {
    let text = fs::read_to_string(program("v10_buffers.ae")).unwrap();
    let compilation = compile_source(
        &SourceFile::new("v10_buffers.ae", text),
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(compilation.dumps[&Emit::Ast].contains("Index"));
    assert!(compilation.dumps[&Emit::Hir].contains("Buffer<int64>"));
    assert!(compilation.dumps[&Emit::Hir].contains("needs_drop: true"));
    assert!(compilation.dumps[&Emit::Hir].contains("Move"));
    assert!(compilation.dumps[&Emit::Hir].contains("ViewMut<int64>"));
    assert!(compilation.dumps[&Emit::Mir].contains("BufferAlloc"));
    assert!(compilation.dumps[&Emit::Mir].contains("Drop"));
    assert!(compilation.dumps[&Emit::Mir].contains("Index"));
    assert!(compilation.dumps[&Emit::Ssa].contains("BufferAlloc"));
    assert!(compilation.dumps[&Emit::Ssa].contains("bounds_trap: IndexOutOfBounds"));
    assert!(compilation.llvm.contains("@malloc"));
    assert!(compilation.llvm.contains("@free"));
    assert!(compilation.llvm.contains("{ ptr, i64 }"));
    assert!(compilation.llvm.contains("getelementptr inbounds"));
    assert!(compilation.llvm.contains("AllocationSizeOverflow"));
    assert!(compilation.llvm.contains("IndexOutOfBounds"));
    assert!(compilation.llvm.contains("@aether_allocation_balance"));
}

#[test]
fn vertical10_buffer_diagnostics_fail_closed() {
    for (text, code) in [
        (
            "int main(){Buffer<int> a=Buffer<int>(1,0);Buffer<int> b=a;return a[0];}",
            "E0291",
        ),
        (
            "int main(){Buffer<int> a=Buffer<int>(1,0);Buffer<int> b=a;Buffer<int> c=a;return 0;}",
            "E0291",
        ),
        (
            "int main(){Buffer<int> a=Buffer<int>(2,0);return a[2];}",
            "E0296",
        ),
        (
            "int main(){Buffer<int> a=Buffer<int>(2,0);float64 i=1.0;return a[i];}",
            "E0218",
        ),
        (
            "int main(){Buffer<int> a=Buffer<int>(1.0,0);return 0;}",
            "E0205",
        ),
        (
            "int main(){Buffer<int> a=Buffer<int>(18446744073709551615,0);return 0;}",
            "E0282",
        ),
        (
            "int main(){Buffer<Buffer<int>> a=Buffer<Buffer<int>>(1,Buffer<int>(1,0));return 0;}",
            "E0280",
        ),
        (
            "int main(){int x=0;ref int r=&x;Buffer<ref int> a=Buffer<ref int>(1,r);return 0;}",
            "E0280",
        ),
        (
            "int main(){Buffer<int> a=Buffer<int>(1,0);View<int> v=view(a);Buffer<View<int>> b=Buffer<View<int>>(1,v);return 0;}",
            "E0280",
        ),
        (
            "int main(){Buffer<int> a=Buffer<int>(1,0);ref int r=&a[0];Buffer<int> b=a;return *r;}",
            "E0292",
        ),
        (
            "int main(){Buffer<int> a=Buffer<int>(1,0);View<int> v=view(a);Buffer<int> b=a;return v[0];}",
            "E0292",
        ),
        (
            "int main(){Buffer<int> a=Buffer<int>(1,0);while(false){Buffer<int> b=a;}return 0;}",
            "E0295",
        ),
        (
            "View<int> bad(ref Buffer<int> a){return view(*a);}int main(){return 0;}",
            "E0273",
        ),
        (
            "struct Bad{View<int> values;}int main(){return 0;}",
            "E0285",
        ),
        (
            "Buffer<T> bad<T>(usize n,T value){return Buffer<T>(n,value);}int main(){return 0;}",
            "E0283",
        ),
        (
            "int main(){Buffer<int> a=Buffer<int>(1,0);View<int> v=view(a);v=view(a);return 0;}",
            "E0277",
        ),
        (
            "int main(){Buffer<int> a=Buffer<int>(1,0);View<int> v=view(a);v[0]=1;return 0;}",
            "E0288",
        ),
    ] {
        let Err(mut diagnostics) = compile_source(&SourceFile::new("v10-error.ae", text), &[])
        else {
            panic!("expected Buffer rejection: {text}");
        };
        let diagnostic = diagnostics.remove(0);
        assert_eq!(diagnostic.code, code, "{text}: {}", diagnostic.message);
        assert!(diagnostic.span.is_some());
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical10_buffers_views_moves_and_exact_cleanup_execute_natively() {
    let (compilation, status) = run_path(
        &program("v10_buffers.ae"),
        &[Emit::Mir, Emit::Ssa, Emit::Llvm],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(78));
    assert!(compilation.llvm.contains("@aether_heap_alloc_count"));
    assert!(compilation.llvm.contains("@aether_heap_free_count"));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical10_runtime_bounds_and_allocation_overflow_trap() {
    for source in ["v10_dynamic_oob.ae", "v10_allocation_overflow.ae"] {
        let (_, status) = run_path(&program(source), &[], &ClangToolchain::default()).unwrap();
        assert!(!status.success(), "{source} must trap");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical10_cross_module_buffer_transfer_executes_natively() {
    let (compilation, status) = run_path(
        &module_program("v10_buffers"),
        &[Emit::Mir, Emit::Ssa, Emit::Llvm],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(33));
    assert!(compilation.llvm.contains("storage"));
    assert!(compilation.dumps[&Emit::Mir].contains("Move"));
    assert!(compilation.dumps[&Emit::Ssa].contains("Drop"));
}

#[test]
fn vertical11_type_properties_are_structural_and_concrete() {
    let source = SourceFile::new(
        "v11-properties.ae",
        "struct Point{int x;} struct Points{Buffer<Point> values;} struct Holder<T>{T value;} enum Maybe<T>{None,Some(T)} int main(){Points points=Points(Buffer<Point>(1,Point(7)));Holder<int> a=Holder<int>(1);Holder<Holder<int>> nested=Holder<Holder<int>>(a);Holder<Buffer<int>> b=Holder<Buffer<int>>(Buffer<int>(1,2));Maybe<int> c=Maybe<int>.Some(3);Maybe<Buffer<int>> d=Maybe<Buffer<int>>.Some(Buffer<int>(1,4));return points.values[0].x+nested.value.value;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mut saw_holder_copy = false;
    let mut saw_holder_owner = false;
    let mut saw_nested_copy = false;
    let mut saw_maybe_copy = false;
    let mut saw_maybe_owner = false;
    let mut saw_unknown_parameter = false;
    for (ty, data) in hir.types().entries() {
        let properties = hir.types().properties(ty).unwrap();
        match data {
            TypeData::GenericParam(_) => {
                saw_unknown_parameter |= !properties.is_known && !properties.is_copy;
            }
            TypeData::StructInstance(_, args) => {
                let argument = hir.types().arguments(*args).unwrap()[0];
                if argument == aether_frontend::TypeId::INT64 {
                    saw_holder_copy |=
                        properties.is_known && properties.is_copy && !properties.needs_drop;
                } else if hir.types().buffer_element(argument).is_some() {
                    saw_holder_owner |=
                        properties.is_known && !properties.is_copy && properties.needs_drop;
                } else if matches!(
                    hir.types().get(argument),
                    Some(TypeData::StructInstance(..))
                ) {
                    saw_nested_copy |=
                        properties.is_known && properties.is_copy && !properties.needs_drop;
                }
            }
            TypeData::EnumInstance(_, args) => {
                let argument = hir.types().arguments(*args).unwrap()[0];
                if argument == aether_frontend::TypeId::INT64 {
                    saw_maybe_copy |=
                        properties.is_known && properties.is_copy && !properties.needs_drop;
                } else if hir.types().buffer_element(argument).is_some() {
                    saw_maybe_owner |=
                        properties.is_known && !properties.is_copy && properties.needs_drop;
                }
            }
            _ => {}
        }
    }
    assert!(
        saw_holder_copy
            && saw_holder_owner
            && saw_nested_copy
            && saw_maybe_copy
            && saw_maybe_owner
            && saw_unknown_parameter
    );
}

#[test]
fn vertical11_aggregate_ownership_diagnostics_fail_closed() {
    for (text, code) in [
        (
            "struct S{Buffer<int> b;}int main(){S a=S(Buffer<int>(1,0));S c=a;return a.b[0];}",
            "E0291",
        ),
        (
            "struct S{Buffer<int> b;}int main(){S a=S(Buffer<int>(1,0));S b=a;S c=a;return 0;}",
            "E0291",
        ),
        (
            "struct S{Buffer<int> b;}int main(){S a=S(Buffer<int>(1,0));Buffer<int> b=a.b;return 0;}",
            "E0293",
        ),
        (
            "struct S{Buffer<int> a;Buffer<int> b;}int main(){Buffer<int> x=Buffer<int>(1,0);S s=S(x,x);return 0;}",
            "E0291",
        ),
        (
            "struct Pair<T>{T a;T b;}Pair<T> duplicate<T>(T x){return Pair<T>(x,x);}int main(){return 0;}",
            "E0291",
        ),
        (
            "struct S{Buffer<int> b;}int main(){S a=S(Buffer<int>(1,0));ref int r=&a.b[0];S c=a;return *r;}",
            "E0292",
        ),
        (
            "struct S{Buffer<int> b;}int main(){S a=S(Buffer<int>(1,0));while(false){S c=a;}return 0;}",
            "E0295",
        ),
        (
            "enum E{Empty,Owned(Buffer<int>)}int main(){E e=E.Owned(Buffer<int>(1,0));E moved=e;match(e){E.Empty=>{return 0;}E.Owned=>{return 0;}}}",
            "E0291",
        ),
        (
            "struct H<T>{T value;}int main(){Buffer<H<Buffer<int>>> bad=Buffer<H<Buffer<int>>>(1,H<Buffer<int>>(Buffer<int>(1,0)));return 0;}",
            "E0280",
        ),
        (
            "struct Borrowed{ref int value;}struct Outer{Borrowed value;}int main(){return 0;}",
            "E0274",
        ),
    ] {
        let diagnostics =
            compile_source(&SourceFile::new("v11-error.ae", text), &[]).expect_err(text);
        assert_eq!(
            diagnostics[0].code, code,
            "{text}: {}",
            diagnostics[0].message
        );
        assert!(diagnostics[0].span.is_some(), "{text}");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical11_owned_aggregates_execute_and_drop_exactly_once() {
    let (compilation, status) = run_path(
        &program("v11_aggregates.ae"),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(42));
    assert!(compilation.dumps[&Emit::Hir].contains("is_copy: false"));
    assert!(compilation.dumps[&Emit::Mir].contains("Drop"));
    assert!(compilation.dumps[&Emit::Mir].contains("needs_drop: true"));
    assert!(compilation.dumps[&Emit::Ssa].contains("EnumConstruct"));
    assert!(compilation.dumps[&Emit::Ssa].contains("is_copy: false"));
    assert!(
        compilation
            .llvm
            .contains("define internal void @aether_drop_e")
    );
    assert!(compilation.llvm.contains("switch i32 %tag"));
    assert!(compilation.llvm.contains("@aether_heap_alloc_count"));
    assert!(compilation.llvm.contains("@aether_heap_free_count"));

    let (_, status) = run_path(
        &program("v11_control_flow.ae"),
        &[],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(43));

    let (reassignment, status) = run_path(
        &program("v11_reassignment.ae"),
        &[Emit::Llvm],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(42));
    assert_eq!(
        reassignment
            .llvm
            .matches("call void @aether_drop_s0(")
            .count(),
        2
    );
    assert_eq!(
        reassignment.llvm.matches("call void @aether_free(").count(),
        1
    );

    let one = SourceFile::new(
        "v11-one.ae",
        "struct S{Buffer<int> value;}int main(){S value=S(Buffer<int>(1,1));return value.value[0];}",
    );
    let compiled = compile_source(&one, &[]).unwrap();
    assert_eq!(
        compiled
            .llvm
            .matches("call { ptr, i64 } @aether_buffer_new_")
            .count(),
        1
    );
    assert_eq!(compiled.llvm.matches("call void @aether_free(").count(), 1);

    let two = SourceFile::new(
        "v11-two.ae",
        "struct S{Buffer<int> a;Buffer<int> b;}int main(){S value=S(Buffer<int>(1,1),Buffer<int>(1,2));return 0;}",
    );
    let compiled = compile_source(&two, &[]).unwrap();
    assert_eq!(
        compiled
            .llvm
            .matches("call { ptr, i64 } @aether_buffer_new_")
            .count(),
        2
    );
    assert_eq!(compiled.llvm.matches("call void @aether_free(").count(), 1);
    let second = compiled.llvm.find("%field1 = extractvalue").unwrap();
    let first = compiled.llvm.find("%field0 = extractvalue").unwrap();
    assert!(
        second < first,
        "struct fields must drop in reverse declaration order"
    );
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical11_cross_module_aggregate_transfer_executes_natively() {
    let (compilation, status) = run_path(
        &module_program("v11_aggregates"),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(42));
    assert!(compilation.dumps[&Emit::Hir].contains("Packet"));
    assert!(compilation.dumps[&Emit::Mir].contains("Move"));
    assert!(compilation.dumps[&Emit::Ssa].contains("Drop"));
}

#[test]
fn vertical12_match_modes_and_conditional_drop_dumps_are_explicit_and_sparse() {
    let match_source = SourceFile::new(
        "v12_match_ownership.ae",
        fs::read_to_string(program("v12_match_ownership.ae")).unwrap(),
    );
    let matched = compile_source(
        &match_source,
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(matched.dumps[&Emit::Ast].contains("MutableRef"));
    assert!(matched.dumps[&Emit::Hir].contains("mode: SharedRef"));
    assert!(matched.dumps[&Emit::Hir].contains("mode: Value"));
    assert!(matched.dumps[&Emit::Mir].contains("ConsumeEnum"));
    assert!(matched.dumps[&Emit::Mir].contains("mode: MutableRef"));
    assert!(matched.dumps[&Emit::Ssa].contains("ConsumeEnum"));
    assert!(matched.llvm.contains("match_tag_ptr"));
    assert!(matched.llvm.contains("getelementptr inbounds %aether.enum"));
    assert!(!matched.llvm.contains("noalias"));
    assert_eq!(matched.dumps[&Emit::Mir].matches("MirDropFlag").count(), 0);

    let conditional_source = SourceFile::new(
        "v12_conditional_drop.ae",
        fs::read_to_string(program("v12_conditional_drop.ae")).unwrap(),
    );
    let conditional = compile_source(
        &conditional_source,
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(conditional.dumps[&Emit::Hir].contains("Conditional"));
    assert_eq!(
        conditional.dumps[&Emit::Mir].matches("MirDropFlag").count(),
        4
    );
    assert_eq!(
        conditional.dumps[&Emit::Ssa].matches("MirDropFlag").count(),
        4
    );
    assert!(conditional.llvm.contains("phi i1"));

    let early_return = SourceFile::new(
        "v12-early-return.ae",
        "int main(){Buffer<int> value=Buffer<int>(1,42);if(true){Buffer<int> moved=value;return moved[0];}return value[0];}",
    );
    let early = compile_source(&early_return, &[Emit::Mir]).unwrap();
    assert_eq!(early.dumps[&Emit::Mir].matches("MirDropFlag").count(), 0);
}

#[test]
fn vertical12_match_and_maybe_moved_diagnostics_fail_closed() {
    for (text, code) in [
        (
            "enum E{None,Some(Buffer<int>)}int main(){E e=E.Some(Buffer<int>(1,0));match(e){E.None=>{}E.Some(value)=>{}}match(ref e){E.None=>{}E.Some(value)=>{}}return 0;}",
            "E0291",
        ),
        (
            "enum E{None,Some(Buffer<int>)}int main(){match(ref E.Some(Buffer<int>(1,0))){E.None=>{}E.Some(value)=>{}}return 0;}",
            "E0301",
        ),
        (
            "enum E{None,Some(Buffer<int>)}int main(){E e=E.Some(Buffer<int>(1,0));match(ref e){E.None=>{}E.Some(value)=>{(*value)[0]=1;}}return 0;}",
            "E0272",
        ),
        (
            "enum E{None,Some(Buffer<int>)}int main(){E e=E.Some(Buffer<int>(1,0));ref E shared=&e;match(ref mut *shared){E.None=>{}E.Some(value)=>{}}return 0;}",
            "E0302",
        ),
        (
            "int take(Buffer<int> value){return value[0];}int main(){Buffer<int> value=Buffer<int>(1,0);if(true){int used=take(value);}return value[0];}",
            "E0303",
        ),
        (
            "int take(Buffer<int> value){return value[0];}int main(){Buffer<int> value=Buffer<int>(1,0);if(true){int used=take(value);}Buffer<int> twice=value;return 0;}",
            "E0303",
        ),
        (
            "int take(Buffer<int> value){return value[0];}int main(){Buffer<int> value=Buffer<int>(1,0);if(true){int used=take(value);}ref Buffer<int> borrowed=&value;return 0;}",
            "E0303",
        ),
        (
            "int take(Buffer<int> value){return value[0];}int main(){Buffer<int> value=Buffer<int>(1,0);ref int borrowed=&value[0];if(true){int used=take(value);}return *borrowed;}",
            "E0292",
        ),
        (
            "int take(Buffer<int> value){return value[0];}int main(){Buffer<int> value=Buffer<int>(1,0);while(false){int used=take(value);}return 0;}",
            "E0295",
        ),
    ] {
        let diagnostics =
            compile_source(&SourceFile::new("v12-error.ae", text), &[]).expect_err(text);
        assert_eq!(
            diagnostics[0].code, code,
            "{text}: {}",
            diagnostics[0].message
        );
        assert!(diagnostics[0].span.is_some());
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical12_matches_and_conditional_cleanup_execute_exactly_once() {
    for source in ["v12_match_ownership.ae", "v12_conditional_drop.ae"] {
        let (compilation, status) = run_path(
            &program(source),
            &[Emit::Mir, Emit::Ssa, Emit::Llvm],
            &ClangToolchain::default(),
        )
        .unwrap();
        assert_eq!(status.code(), Some(42), "{source}");
        assert!(compilation.llvm.contains("@aether_heap_alloc_count"));
        assert!(compilation.llvm.contains("@aether_heap_free_count"));
    }
    let (compilation, status) = run_path(
        &module_program("v12_match"),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(42));
    assert!(compilation.dumps[&Emit::Hir].contains("MutableRef"));
    assert!(compilation.dumps[&Emit::Mir].contains("ConsumeEnum"));
}

#[test]
fn vertical13_array_type_is_canonical_distinct_and_move_owned() {
    let source = SourceFile::new(
        "v13-types.ae",
        "int main(){Array<int> a={1};Array<int> b={2};Buffer<int> raw=Buffer<int>(1,3);return a[0]+b[0]+raw[0];}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let arrays = hir
        .types()
        .entries()
        .filter_map(|(ty, data)| matches!(data, TypeData::Array { .. }).then_some(ty))
        .collect::<Vec<_>>();
    let buffers = hir
        .types()
        .entries()
        .filter_map(|(ty, data)| matches!(data, TypeData::Buffer { .. }).then_some(ty))
        .collect::<Vec<_>>();
    assert_eq!(arrays.len(), 1);
    assert_eq!(buffers.len(), 1);
    assert_ne!(arrays[0], buffers[0]);
    assert_eq!(
        hir.types().array_element(arrays[0]),
        Some(aether_frontend::TypeId::INT64)
    );
    assert!(!hir.types().is_copy(arrays[0]));
    assert!(hir.types().needs_drop(arrays[0]));
}

#[test]
fn vertical13_collection_literal_and_array_operations_survive_every_ir() {
    let source = SourceFile::new(
        "v13_arrays.ae",
        fs::read_to_string(program("v13_arrays.ae")).unwrap(),
    );
    let compilation = compile_source(
        &source,
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(compilation.dumps[&Emit::Ast].contains("CollectionLiteral"));
    assert!(compilation.dumps[&Emit::Hir].contains("Array<int64>"));
    assert!(compilation.dumps[&Emit::Hir].contains("ArrayInit"));
    assert!(compilation.dumps[&Emit::Hir].contains("ArrayFill"));
    assert!(compilation.dumps[&Emit::Hir].contains("ArrayLength"));
    assert!(compilation.dumps[&Emit::Mir].contains("ArrayInit"));
    assert!(compilation.dumps[&Emit::Mir].contains("ArrayFill"));
    assert!(compilation.dumps[&Emit::Mir].contains("ArrayLength"));
    assert!(compilation.dumps[&Emit::Ssa].contains("ArrayInit"));
    assert!(compilation.dumps[&Emit::Ssa].contains("ArrayFill"));
    assert!(compilation.dumps[&Emit::Ssa].contains("ArrayLength"));
    assert!(compilation.llvm.contains("@aether_fixed_new_"));
    assert!(compilation.llvm.contains("extractvalue { ptr, i64 }"));
    assert!(compilation.llvm.contains("IndexOutOfBounds"));
    assert!(compilation.llvm.contains("@aether_allocation_balance"));
}

#[test]
fn vertical13_array_diagnostics_fail_closed() {
    for (text, code) in [
        ("int main(){Array<int> a={1,2};return a[2];}", "E0296"),
        ("int main(){Array<int> a={1};int i=0;return a[i];}", "E0218"),
        ("int main(){Array<int> a={true};return 0;}", "E0205"),
        (
            "int main(){int x=1;Array<float64> a={x};return 0;}",
            "E0218",
        ),
        ("int main(){int value={1};return value;}", "E0305"),
        (
            "int main(){Array<int> a=Array<int>(18446744073709551615,0);return 0;}",
            "E0282",
        ),
        (
            "int main(){Buffer<int> b=Buffer<int>(1,0);Array<Buffer<int>> a=Array<Buffer<int>>(2,b);return 0;}",
            "E0314",
        ),
        (
            "Array<T> bad<T>(T value){Array<T> a={value};return a;}int main(){return 0;}",
            "E0304",
        ),
        (
            "int main(){Array<int> a={1};Array<int> b=a;return a[0];}",
            "E0291",
        ),
        (
            "int main(){Array<int> a={1};ref int r=&a[0];Array<int> b=a;return *r;}",
            "E0292",
        ),
        (
            "int main(){Array<int> a={1};View<int> v=view(a);Array<int> b=a;return v[0];}",
            "E0292",
        ),
        ("int main(){Array<int> a={1};return push(a,2);}", "E0212"),
        ("int main(){Array<int> a={1};return pop(a);}", "E0318"),
        ("int main(){Array<int> a={1};return reserve(a,2);}", "E0212"),
        ("int main(){Array<int> a={1};return resize(a,2);}", "E0212"),
        (
            "int main(){Array<int> a=Buffer<int>(1,0);return 0;}",
            "E0205",
        ),
        ("int main(){Array<int> a={1};return length(a,2);}", "E0307"),
        ("int main(){int x=1;return length(x);}", "E0307"),
    ] {
        let diagnostics =
            compile_source(&SourceFile::new("v13-error.ae", text), &[]).expect_err(text);
        assert_eq!(
            diagnostics[0].code, code,
            "{text}: {}",
            diagnostics[0].message
        );
        assert!(diagnostics[0].span.is_some());
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical13_arrays_execute_with_balanced_exact_cleanup() {
    for (source, expected) in [
        ("v13_arrays.ae", 45),
        ("v13_array_ownership.ae", 18),
        ("v13_empty_array.ae", 0),
        ("v13_literal_array.ae", 42),
        ("v13_fill_array.ae", 42),
        ("v13_index_ref_loop.ae", 42),
    ] {
        let (compilation, status) = run_path(
            &program(source),
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            &ClangToolchain::default(),
        )
        .unwrap();
        assert_eq!(status.code(), Some(expected), "{source}");
        assert!(compilation.llvm.contains("@aether_heap_alloc_count"));
        assert!(compilation.llvm.contains("@aether_heap_free_count"));
        assert!(compilation.dumps[&Emit::Mir].contains("Drop"));
        if source == "v13_array_ownership.ae" {
            assert!(compilation.dumps[&Emit::Hir].contains("Conditional"));
            assert!(compilation.dumps[&Emit::Mir].contains("MirDropFlag"));
            assert!(compilation.dumps[&Emit::Ssa].contains("MirDropFlag"));
        }
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical13_empty_array_dynamic_index_traps() {
    for source in ["v13_empty_oob.ae", "v13_allocation_overflow.ae"] {
        let (_, status) = run_path(&program(source), &[], &ClangToolchain::default()).unwrap();
        assert!(!status.success(), "{source} must trap");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical13_cross_module_array_transfer_executes_natively() {
    let (compilation, status) = run_path(
        &module_program("v13_arrays"),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(33));
    assert!(compilation.dumps[&Emit::Hir].contains("Array<int64>"));
    assert!(compilation.dumps[&Emit::Mir].contains("Move"));
    assert!(compilation.dumps[&Emit::Ssa].contains("Drop"));
}

#[test]
fn vertical14_list_type_is_canonical_distinct_and_move_owned() {
    let source = SourceFile::new(
        "v14-types.ae",
        "int main(){List<int> a={1};List<int> b={2};Array<int> fixed={3};Buffer<int> raw=Buffer<int>(1,4);return a[0]+b[0]+fixed[0]+raw[0];}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let lists = hir
        .types()
        .entries()
        .filter_map(|(ty, data)| matches!(data, TypeData::List { .. }).then_some(ty))
        .collect::<Vec<_>>();
    let arrays = hir
        .types()
        .entries()
        .filter_map(|(ty, data)| matches!(data, TypeData::Array { .. }).then_some(ty))
        .collect::<Vec<_>>();
    let buffers = hir
        .types()
        .entries()
        .filter_map(|(ty, data)| matches!(data, TypeData::Buffer { .. }).then_some(ty))
        .collect::<Vec<_>>();
    assert_eq!(lists.len(), 1);
    assert_eq!(arrays.len(), 1);
    assert_eq!(buffers.len(), 1);
    assert_ne!(lists[0], arrays[0]);
    assert_ne!(lists[0], buffers[0]);
    assert_eq!(
        hir.types().list_element(lists[0]),
        Some(aether_frontend::TypeId::INT64)
    );
    assert!(!hir.types().is_copy(lists[0]));
    assert!(hir.types().needs_drop(lists[0]));
}

#[test]
fn vertical14_collection_literal_and_list_operations_survive_every_ir() {
    let source = SourceFile::new(
        "v14_lists.ae",
        fs::read_to_string(program("v14_lists.ae")).unwrap(),
    );
    let compilation = compile_source(
        &source,
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(compilation.dumps[&Emit::Ast].contains("CollectionLiteral"));
    assert!(compilation.dumps[&Emit::Hir].contains("List<int64>"));
    for operation in [
        "ListInit",
        "ListLength",
        "ListCapacity",
        "ListPush",
        "ListReserve",
    ] {
        assert!(
            compilation.dumps[&Emit::Hir].contains(operation),
            "HIR missing {operation}"
        );
        assert!(
            compilation.dumps[&Emit::Mir].contains(operation),
            "MIR missing {operation}"
        );
        assert!(
            compilation.dumps[&Emit::Ssa].contains(operation),
            "SSA missing {operation}"
        );
    }
    assert!(compilation.dumps[&Emit::Hir].contains("mutation: Push"));
    assert!(compilation.llvm.contains("{ ptr, i64, i64 }"));
    assert!(compilation.llvm.contains("@aether_list_push_"));
    assert!(compilation.llvm.contains("@aether_list_reserve_"));
    assert!(compilation.llvm.contains("@aether_list_index_"));
    assert!(compilation.llvm.contains("@aether_allocation_balance"));
}

#[test]
fn vertical14_list_diagnostics_fail_closed() {
    for (text, code) in [
        (
            "List<T> bad<T>(T value){List<T> a={value};return a;}int main(){return 0;}",
            "E0310",
        ),
        ("int main(){List<int> a={true};return 0;}", "E0205"),
        ("int main(){List<int> a={1,2};return a[2];}", "E0296"),
        (
            "int bad(ref List<int> a){push(*a,2);return 0;}int main(){return 0;}",
            "E0272",
        ),
        (
            "int bad(ref List<int> a){reserve(*a,2);return 0;}int main(){return 0;}",
            "E0272",
        ),
        (
            "int main(){List<int> a={1};ref int r=&a[0];push(a,2);return *r;}",
            "E0313",
        ),
        (
            "int main(){List<int> a={1};reserve(a,8);ref int r=&a[0];push(a,2);return *r;}",
            "E0313",
        ),
        (
            "int main(){List<int> a={1};ref int r=&a[0];reserve(a,1);return *r;}",
            "E0313",
        ),
        (
            "int main(){List<int> a={1};View<int> v=view(a);push(a,2);return v[0];}",
            "E0313",
        ),
        (
            "int main(){List<int> a={1};ViewMut<int> v=view_mut(a);reserve(a,4);return v[0];}",
            "E0313",
        ),
        (
            "int main(){List<int> a={1};ref int r=&a[0];List<int> b=a;return *r;}",
            "E0292",
        ),
        (
            "int main(){List<int> a={1};List<int> b=a;return a[0];}",
            "E0291",
        ),
        (
            "int mutate(ref mut List<int> a){push(*a,2);return 0;}int main(){List<int> a={1};ref int r=&a[0];int x=mutate(&mut a);return *r+x;}",
            "E0313",
        ),
        (
            "int bad(ref mut List<int> a){ref int r=&(*a)[0];push(*a,2);return *r;}int main(){return 0;}",
            "E0313",
        ),
        (
            "int mutate(ref mut List<int> a){return 0;}int main(){List<int> a={1};ref mut List<int> h=&mut a;ref int r=&a[0];int x=mutate(h);return *r+x;}",
            "E0313",
        ),
        ("int main(){Array<int> a={1};push(a,2);return 0;}", "E0311"),
        ("int main(){List<int> a={1};return capacity(a,2);}", "E0312"),
    ] {
        let diagnostics =
            compile_source(&SourceFile::new("v14-error.ae", text), &[]).expect_err(text);
        assert_eq!(
            diagnostics[0].code, code,
            "{text}: {}",
            diagnostics[0].message
        );
        assert!(diagnostics[0].span.is_some());
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical14_lists_execute_with_growth_and_balanced_cleanup() {
    for source in [
        "v14_lists.ae",
        "v14_literal_list.ae",
        "v14_list_ownership.ae",
        "v14_empty_list.ae",
        "v14_repeated_push.ae",
        "v14_reserved_push.ae",
        "v14_list_view_index.ae",
    ] {
        let (compilation, status) = run_path(
            &program(source),
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            &ClangToolchain::default(),
        )
        .unwrap();
        assert_eq!(status.code(), Some(0), "{source}");
        assert!(compilation.llvm.contains("@aether_heap_alloc_count"));
        assert!(compilation.llvm.contains("@aether_heap_free_count"));
        assert!(compilation.dumps[&Emit::Mir].contains("Drop"));
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical14_exact_allocation_and_free_counts_match_growth_model() {
    let toolchain = ClangToolchain::default();
    for (source, expected) in [
        ("v14_empty_list.ae", 0),
        ("v14_literal_list.ae", 1),
        ("v14_repeated_push.ae", 5),
        ("v14_reserved_push.ae", 1),
        ("v14_list_ownership.ae", 9),
    ] {
        let session = CompilationSession::discover(&program(source)).unwrap();
        let compilation = compile_session(session, &[]).unwrap();
        for counter in ["@aether_heap_alloc_count", "@aether_heap_free_count"] {
            let observed = format!(
                "  %observed_count = load i64, ptr {counter}\n  %process_status = trunc i64 %observed_count to i32"
            );
            let llvm = compilation.llvm.replace(
                "  %process_status = trunc i64 %aether_result to i32",
                &observed,
            );
            let artifact = temporary("v14-count");
            toolchain.link_executable(&llvm, &artifact).unwrap();
            let status = Command::new(&artifact).status().unwrap();
            let _ = fs::remove_file(&artifact);
            assert_eq!(status.code(), Some(expected), "{source} {counter}");
        }
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical14_list_bounds_and_allocation_overflow_trap() {
    for source in ["v14_list_dynamic_oob.ae", "v14_list_allocation_overflow.ae"] {
        let (_, status) = run_path(&program(source), &[], &ClangToolchain::default()).unwrap();
        assert!(!status.success(), "{source} must trap");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical14_cross_module_list_transfer_executes_natively() {
    let (compilation, status) = run_path(
        &module_program("v14_lists"),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(40));
    assert!(compilation.dumps[&Emit::Hir].contains("List<int64>"));
    assert!(compilation.dumps[&Emit::Mir].contains("ListPush"));
    assert!(compilation.dumps[&Emit::Ssa].contains("Drop"));
}

#[test]
fn vertical15_constraint_syntax_resolves_to_declaration_owned_capabilities() {
    let source = SourceFile::new(
        "v15-syntax.ae",
        "T select<T: Copy + Relocatable, U: Relocatable>(T value,U other){return value;}int main(){return select<int,Buffer<int>>(42,Buffer<int>(1,0));}",
    );
    let ast = parse_source(&source).unwrap();
    let parameters = &ast.functions()[0].generic_parameters;
    assert_eq!(parameters[0].constraints.len(), 2);
    assert_eq!(parameters[0].constraints[0].name, "Copy");
    assert!(parameters[0].constraints[0].span.start > parameters[0].span.start);
    let hir = analyze(ast).unwrap();
    let signature = &hir.signatures()[0];
    assert_eq!(signature.generic_parameters[0].capabilities.len(), 2);
    assert!(
        signature.generic_parameters[0]
            .capabilities
            .contains(&Capability::Copy)
    );
    assert!(
        signature.generic_parameters[1]
            .capabilities
            .contains(&Capability::Relocatable)
    );
    assert!(hir.dump().contains("Relocatable"));
}

#[test]
fn vertical15_concrete_and_symbolic_capabilities_are_distinct_and_structural() {
    let source = SourceFile::new(
        "v15-properties.ae",
        "struct Holder<T>{T value;}enum Maybe<T>{None,Some(T)}struct Owner{Buffer<int> value;}Holder<T> copyHolder<T: Copy>(Holder<T> value){Holder<T> other=value;return value;}Maybe<T> moveMaybe<T: Relocatable>(Maybe<T> value){return value;}int main(){Buffer<int> b=Buffer<int>(0,0);Array<int> a={};List<int> l={};return 0;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mut symbolic_holder = false;
    let mut symbolic_maybe = false;
    let mut owner_relocatable = false;
    for (ty, data) in hir.types().entries() {
        match data {
            TypeData::GenericParam(parameter) => {
                let properties = hir.types().properties(ty).unwrap();
                assert!(!properties.is_known);
                if hir.types().generic_name(*parameter) == Some("T") {
                    let capabilities = hir.types().generic_capabilities(*parameter).unwrap();
                    assert!(
                        capabilities.is_empty()
                            || capabilities.contains(&Capability::Copy)
                            || capabilities.contains(&Capability::Relocatable)
                    );
                }
            }
            TypeData::StructInstance(_, _) if hir.types().contains_generic(ty) => {
                symbolic_holder |= hir.types().guarantees_capability(ty, Capability::Copy);
            }
            TypeData::EnumInstance(_, _) if hir.types().contains_generic(ty) => {
                symbolic_maybe |= hir
                    .types()
                    .guarantees_capability(ty, Capability::Relocatable);
            }
            TypeData::Struct(_) => {
                let properties = hir.types().properties(ty).unwrap();
                owner_relocatable |= properties.is_known
                    && !properties.is_copy
                    && properties.is_relocatable
                    && properties.needs_drop;
            }
            _ => {}
        }
    }
    assert!(symbolic_holder && symbolic_maybe && owner_relocatable);

    for data in [
        TypeData::Buffer {
            element: aether_frontend::TypeId::INT64,
        },
        TypeData::Array {
            element: aether_frontend::TypeId::INT64,
        },
        TypeData::List {
            element: aether_frontend::TypeId::INT64,
        },
    ] {
        let ty = hir
            .types()
            .id_of(data)
            .unwrap_or_else(|| panic!("fixture should intern {data:?}"));
        assert!(!hir.types().is_copy(ty));
        assert!(hir.types().is_relocatable(ty));
    }
}

#[test]
fn vertical15_capability_diagnostics_fail_closed() {
    for (text, code) in [
        (
            "T duplicate<T: Copy>(T x){T y=x;return x;}int main(){Buffer<int> a=Buffer<int>(1,0);Buffer<int> b=duplicate<Buffer<int>>(a);return 0;}",
            "E0316",
        ),
        (
            "T duplicate<T: Copy>(T x){T y=x;return x;}int main(){Array<int> a={1};Array<int> b=duplicate<Array<int>>(a);return 0;}",
            "E0316",
        ),
        (
            "T duplicate<T: Copy>(T x){T y=x;return x;}int main(){List<int> a={1};List<int> b=duplicate<List<int>>(a);return 0;}",
            "E0316",
        ),
        (
            "T bad<T>(T x){T y=x;return x;}int main(){return 0;}",
            "E0291",
        ),
        (
            "T duplicate<T: Copy>(T x){T y=x;return x;}T outer<T>(T x){return duplicate<T>(x);}int main(){return 0;}",
            "E0316",
        ),
        (
            "T bad<T: Foo>(T x){return x;}int main(){return 0;}",
            "E0314",
        ),
        (
            "T bad<T: Copy + Copy>(T x){return x;}int main(){return 0;}",
            "E0315",
        ),
        (
            "struct Box<T: Copy>{T value;}int main(){Box<Buffer<int>> b=Box<Buffer<int>>(Buffer<int>(1,0));return 0;}",
            "E0316",
        ),
        (
            "enum Maybe<T: Copy>{None,Some(T)}int main(){Maybe<Buffer<int>> b=Maybe<Buffer<int>>.None;return 0;}",
            "E0316",
        ),
        (
            "T duplicate<T: Copy>(T x){T y=x;return x;}int main(){Buffer<int> a=Buffer<int>(1,0);Buffer<int> b=duplicate(a);return 0;}",
            "E0317",
        ),
        (
            "T bad<T: Relocatable>(T x){T y=x;return x;}int main(){return 0;}",
            "E0291",
        ),
        (
            "ref T bad<T: Copy>(ref T x){return x;}int main(){return 0;}",
            "E0273",
        ),
        (
            "Array<T> bad<T: Copy>(T x){Array<T> a={x};return a;}int main(){return 0;}",
            "E0304",
        ),
        (
            "List<T> bad<T: Relocatable>(T x){List<T> a={};return a;}int main(){return 0;}",
            "E0310",
        ),
        (
            "Buffer<T> bad<T: Copy>(usize n,T x){return Buffer<T>(n,x);}int main(){return 0;}",
            "E0283",
        ),
    ] {
        let diagnostics = compile_source(&SourceFile::new("v15-error.ae", text), &[])
            .expect_err("expected capability rejection");
        assert_eq!(
            diagnostics[0].code, code,
            "{text}: {}",
            diagnostics[0].message
        );
        assert!(diagnostics[0].span.is_some());
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical15_capability_programs_execute_without_runtime_capability_artifacts() {
    for (path, expected) in [
        (program("v15_capabilities.ae"), 42),
        (module_program("v15_capabilities"), 42),
    ] {
        let (compilation, status) = run_path(
            &path,
            &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            &ClangToolchain::default(),
        )
        .unwrap();
        assert_eq!(status.code(), Some(expected), "{}", path.display());
        assert!(compilation.dumps[&Emit::Ast].contains("constraints"));
        assert!(compilation.dumps[&Emit::Hir].contains("Relocatable"));
        assert!(!compilation.dumps[&Emit::Mir].contains("Capability"));
        assert!(!compilation.dumps[&Emit::Ssa].contains("Capability"));
        assert!(!compilation.llvm.contains("capability"));
    }
}

#[test]
fn vertical16_owned_collection_ir_and_diagnostics_are_explicit() {
    let session = CompilationSession::discover(&program("v16_owned_collections.ae")).unwrap();
    let compilation =
        compile_session(session, &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm]).unwrap();
    assert!(compilation.dumps[&Emit::Hir].contains("Array<Buffer<int64>>"));
    assert!(compilation.dumps[&Emit::Hir].contains("List<List<int64>>"));
    assert!(compilation.dumps[&Emit::Mir].contains("Relocate"));
    assert!(compilation.dumps[&Emit::Mir].contains("ListInitializedPrefix"));
    assert!(compilation.dumps[&Emit::Ssa].contains("source_after: Uninitialized"));
    assert!(compilation.llvm.contains("@aether_relocate_BiInt64"));
    assert!(compilation.llvm.contains("@aether_drop_LBiInt64"));
    assert!(compilation.llvm.contains("@aether_relocation_count"));
    assert!(compilation.llvm.contains("%relocate_header"));
    assert!(compilation.llvm.contains("%previous = sub i64 %index, 1"));
    assert!(!compilation.llvm.contains("@aether_fixed_fill_BiInt64"));

    for (text, code, detail) in [
        (
            "int main(){Buffer<int> b=Buffer<int>(1,1);Array<Buffer<int>> a={b};return b[0];}",
            "E0291",
            "use after move",
        ),
        (
            "int main(){List<Buffer<int>> a={};Buffer<int> b=Buffer<int>(1,1);push(a,b);return b[0];}",
            "E0291",
            "use after move",
        ),
        (
            "int main(){Buffer<int> b=Buffer<int>(1,1);Array<Buffer<int>> a=Array<Buffer<int>>(2,b);return 0;}",
            "E0314",
            "requires Copy",
        ),
        (
            "int main(){int x=1;Array<ref int> a={&x};return 0;}",
            "E0304",
            "stored references and views",
        ),
        (
            "List<T> bad<T: Relocatable>(T x){List<T> a={};return a;}int main(){return 0;}",
            "E0310",
            "cannot be proven",
        ),
    ] {
        let diagnostics = compile_source(&SourceFile::new("v16-error.ae", text), &[])
            .expect_err("expected Vertical-16 rejection");
        assert_eq!(diagnostics[0].code, code, "{text}");
        assert!(
            diagnostics[0].message.contains(detail),
            "{text}: {}",
            diagnostics[0].message
        );
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical16_owned_collections_relocate_and_drop_exactly_once() {
    let source = program("v16_owned_collections.ae");
    let (compilation, status) = run_path(
        &source,
        &[Emit::Mir, Emit::Ssa, Emit::Llvm],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(0));

    let toolchain = ClangToolchain::default();
    for (counter, expected) in [
        ("@aether_heap_alloc_count", 43),
        ("@aether_heap_free_count", 43),
        ("@aether_relocation_count", 12),
    ] {
        let observed = format!(
            "  %observed_count = load i64, ptr {counter}\n  %process_status = trunc i64 %observed_count to i32"
        );
        let llvm = compilation.llvm.replace(
            "  %process_status = trunc i64 %aether_result to i32",
            &observed,
        );
        let artifact = temporary("v16-count");
        toolchain.link_executable(&llvm, &artifact).unwrap();
        let status = Command::new(&artifact).status().unwrap();
        let _ = fs::remove_file(&artifact);
        assert_eq!(status.code(), Some(expected), "{counter}");
    }
}

#[test]
#[allow(clippy::too_many_lines)] // Table covers independent storage, move and lifetime failures.
fn vertical17_storable_diagnostics_and_parametric_ownership() {
    for (source, code, detail) in [
        (
            "int f<T: Storable>(T x){return 0;}int main(){int x=0;return f<ref int>(&x);}",
            "E0316",
            "`Storable`; required by generic parameter `T`",
        ),
        (
            "int f<T: Storable>(T x){return 0;}int main(){int x=0;return f<ref mut int>(&mut x);}",
            "E0316",
            "ref mut int64",
        ),
        (
            "int f<T: Storable>(T x){return 0;}int main(){Buffer<int> b=Buffer<int>(1,0);return f<View<int>>(view(b));}",
            "E0316",
            "View<int64>",
        ),
        (
            "int f<T: Storable>(T x){return 0;}int main(){Buffer<int> b=Buffer<int>(1,0);return f<ViewMut<int>>(view_mut(b));}",
            "E0316",
            "ViewMut<int64>",
        ),
        (
            "Array<T> f<T>(T x){Array<T> a={x};return a;}int main(){return 0;}",
            "E0304",
            "does not satisfy `Storable`",
        ),
        (
            "Array<T> f<T: Relocatable>(T x){Array<T> a={x};return a;}int main(){return 0;}",
            "E0304",
            "does not satisfy `Storable`",
        ),
        (
            "List<T> f<T: Relocatable>(T x){List<T> a={};return a;}int main(){return 0;}",
            "E0310",
            "Storable",
        ),
        (
            "List<T> f<T: Storable>(T x){List<T> a={};return a;}int main(){return 0;}",
            "E0310",
            "element type `T` does not satisfy `Relocatable`",
        ),
        (
            "struct Box<T: Storable>{T x;}int main(){Box<ref int> x=Box<ref int>();return 0;}",
            "E0316",
            "Storable",
        ),
        (
            "enum Box<T: Storable>{None,Some(T)}int main(){Box<ref int> x=Box<ref int>.None;return 0;}",
            "E0316",
            "Storable",
        ),
        (
            "T helper<T: Storable>(T x){return x;}T f<T: Relocatable>(T x){return helper<T>(x);}int main(){return 0;}",
            "E0316",
            "Storable",
        ),
        (
            "Array<T> f<T: Storable>(T x){return Array<T>(2,x);}int main(){return 0;}",
            "E0314",
            "requires Copy",
        ),
        (
            "T f<T: Storable>(T x){T y=x;return x;}int main(){return 0;}",
            "E0291",
            "use after move",
        ),
        (
            "T f<T: Storable>(T x){Array<T> a={x};return x;}int main(){return 0;}",
            "E0291",
            "use after move",
        ),
        (
            "T f<T: Storable + Relocatable>(T x){List<T> a={x};return x;}int main(){return 0;}",
            "E0291",
            "use after move",
        ),
        (
            "T f<T: Storable + Relocatable>(T x){List<T> a={};push(a,x);return x;}int main(){return 0;}",
            "E0291",
            "use after move",
        ),
        (
            "ref T f<T: Storable>(ref T x){return x;}int main(){return 0;}",
            "E0273",
            "reference",
        ),
        (
            "struct Bad<T: Storable>{ref T x;}int main(){return 0;}",
            "E0274",
            "reference",
        ),
        (
            "int main(){int x=0;Array<ref int> a={&x};return 0;}",
            "E0304",
            "does not satisfy `Storable`",
        ),
        (
            "int main(){List<ViewMut<int>> a={};return 0;}",
            "E0310",
            "Storable",
        ),
        (
            "T f<T: Storable + Storable>(T x){return x;}int main(){return 0;}",
            "E0315",
            "duplicate `Storable`",
        ),
        (
            "T f<T: Storeable>(T x){return x;}int main(){return 0;}",
            "E0314",
            "Storeable",
        ),
        (
            "int f<T: Copy>(T x){return 0;}int main(){return f(Buffer<int>(1,0));}",
            "E0317",
            "inferred type",
        ),
        (
            "int f<T: Storable>(T x){ref T r=&x;Array<T> a={x};return 0;}int main(){return 0;}",
            "E0292",
            "derived reference",
        ),
        (
            "int f<T: Storable + Relocatable>(T x,T y){List<T> a={x};ref T r=&a[0];push(a,y);return 0;}int main(){return 0;}",
            "E0313",
            "derived element reference",
        ),
        (
            "struct Holder<T>{T x;}struct Bad<T: Relocatable>{Array<Holder<T>> x;}int main(){return 0;}",
            "E0304",
            "does not satisfy `Storable`",
        ),
    ] {
        let diagnostics =
            compile_source(&SourceFile::new("v17-error.ae", source), &[]).expect_err(source);
        assert_eq!(
            diagnostics[0].code, code,
            "{source}: {}",
            diagnostics[0].message
        );
        assert!(
            diagnostics[0].message.contains(detail),
            "{source}: {}",
            diagnostics[0].message
        );
        assert!(diagnostics[0].span.is_some());
    }
}

#[test]
fn vertical17_hir_retains_guarantees_requirements_and_consumption() {
    let session = CompilationSession::discover(&program("v17_storable.ae")).unwrap();
    let compilation = compile_session(session, &[Emit::Hir, Emit::Mir, Emit::Ssa]).unwrap();
    let hir = &compilation.dumps[&Emit::Hir];
    assert!(hir.contains("Storable"));
    assert!(hir.contains("is_storable: true"));
    assert!(hir.contains("element_requirements=[Storable]; element_admission=Admitted"));
    assert!(
        hir.contains("element_requirements=[Storable, Relocatable]; element_admission=Admitted")
    );
    let generic = hir
        .split("generic HIR:")
        .nth(1)
        .unwrap()
        .split("instances (")
        .next()
        .unwrap();
    for operation in ["ArrayInit", "ArrayFill", "ListInit", "ListPush", "Move("] {
        assert!(generic.contains(operation), "{operation}");
    }
    for phase in [Emit::Mir, Emit::Ssa] {
        assert!(compilation.dumps[&phase].contains("Drop"));
        assert!(compilation.dumps[&phase].contains("Relocate"));
        assert!(!compilation.dumps[&phase].contains("Capability::Storable"));
    }
    assert!(!compilation.llvm.contains("Storable"));
    assert!(!compilation.llvm.contains("@aether_storable"));
    assert!(!compilation.llvm.contains("GenericParam"));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical17_symbolic_collections_execute_natively_and_drop_owners() {
    for (path, expected) in [
        (program("v17_storable.ae"), 0),
        (module_program("v17_storable"), 42),
    ] {
        let (_, status) = run_path(&path, &[], &ClangToolchain::default()).unwrap();
        assert_eq!(status.code(), Some(expected), "{}", path.display());
    }
}

#[test]
fn vertical17_independent_instances_are_not_expanding_recursion() {
    let source = "T keep<T: Storable>(T x){return x;}int main(){int a=keep(1);Array<int> b=keep<Array<int>>({a});Array<Array<int>> c=keep<Array<Array<int>>>({b});return c[0][0];}";
    compile_source(&SourceFile::new("v17-finite.ae", source), &[]).unwrap();
    let recursive = "int grow<T: Storable>(T x){Array<T> a={x};return grow<Array<T>>(a);}int main(){return grow(1);}";
    let diagnostics =
        compile_source(&SourceFile::new("v17-recursive.ae", recursive), &[]).unwrap_err();
    assert_eq!(diagnostics[0].code, "E0265");
}

#[test]
fn vertical17_all_borrowed_collection_elements_fail_storable() {
    for (collection, code) in [("Array", "E0304"), ("List", "E0310")] {
        for element in ["ref int", "ref mut int", "View<int>", "ViewMut<int>"] {
            let source = format!("int main(){{{collection}<{element}> a={{}};return 0;}}");
            let diagnostics =
                compile_source(&SourceFile::new("v17-borrow.ae", source), &[]).unwrap_err();
            assert_eq!(diagnostics[0].code, code);
            assert!(diagnostics[0].message.contains("Storable"));
        }
    }
    let source = "int accept<T: Storable>(T x){return 0;}int main(){int x=0;return accept(&x);}";
    let diagnostics =
        compile_source(&SourceFile::new("v17-inferred-ref.ae", source), &[]).unwrap_err();
    assert_eq!(diagnostics[0].code, "E0317");
    assert!(diagnostics[0].message.contains("inferred type `ref int64`"));
    assert!(diagnostics[0].message.contains("Storable"));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical17_repeated_nominal_binders_derive_storage_without_capture() {
    let source = SourceFile::new(
        "v17-nested.ae",
        "struct Holder<T>{T value;}Array<Holder<Holder<T>>> wrap<T: Storable>(T x){Array<Holder<Holder<T>>> a={Holder<Holder<T>>(Holder<T>(x))};return a;}int main(){Array<Holder<Holder<Buffer<int>>>> a=wrap(Buffer<int>(1,42));return a[0].value.value[0];}",
    );
    let compilation = compile_source(&source, &[]).unwrap();
    let artifact = temporary("v17-nested");
    ClangToolchain::default()
        .link_executable(&compilation.llvm, &artifact)
        .unwrap();
    let status = Command::new(&artifact).status().unwrap();
    let _ = fs::remove_file(artifact);
    assert_eq!(status.code(), Some(42));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical17_exact_cleanup_and_relocation_counts() {
    let session = CompilationSession::discover(&program("v17_storable.ae")).unwrap();
    let compilation = compile_session(session, &[]).unwrap();
    for (counter, expected) in [
        ("@aether_heap_alloc_count", 67),
        ("@aether_heap_free_count", 67),
        ("@aether_relocation_count", 56),
    ] {
        let observed = format!(
            "  %observed_count = load i64, ptr {counter}\n  %process_status = trunc i64 %observed_count to i32"
        );
        let llvm = compilation.llvm.replace(
            "  %process_status = trunc i64 %aether_result to i32",
            &observed,
        );
        let artifact = temporary("v17-count");
        ClangToolchain::default()
            .link_executable(&llvm, &artifact)
            .unwrap();
        let status = Command::new(&artifact).status().unwrap();
        let _ = fs::remove_file(artifact);
        assert_eq!(status.code(), Some(expected), "{counter}");
    }
}

#[test]
fn vertical17_semantic_detail_timers_have_explicit_scope() {
    let session = CompilationSession::discover(&program("v17_storable.ae")).unwrap();
    let compilation = compile_session(session, &[]).unwrap();
    for name in [
        "constraint_resolution",
        "symbolic_property_derivation",
        "collection_admission",
        "nominal_second_pass",
    ] {
        let key = format!("frontend.detail.{name}");
        assert!(compilation.timings_ns[key.as_str()] > 0, "{key}");
    }
    // These inclusive details overlap existing phase measurements. The driver
    // retains the eight original core timers rather than replacing them.
    for key in [
        "frontend.parse",
        "frontend.signature_collection",
        "frontend.semantic_bodies",
        "middle.mir_lower",
        "middle.mir_verify",
        "middle.ssa_build",
        "middle.ssa_verify",
        "backend.llvm",
    ] {
        assert!(compilation.timings_ns.contains_key(key));
    }
}

#[test]
fn vertical17_verifiers_reject_symbolic_collection_runtime_types() {
    use aether_middle::{build_ssa, lower_hir, verify_mir, verify_ssa};
    let source = SourceFile::new(
        "v17-concrete.ae",
        "Array<T> singleton<T: Storable>(T x){Array<T> a={x};return a;}int main(){Array<int> a=singleton(1);return a[0];}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let symbolic = hir
        .types()
        .entries()
        .find_map(|(ty, data)| {
            (matches!(data, TypeData::Array { .. }) && hir.types().contains_generic(ty))
                .then_some(ty)
        })
        .unwrap();
    let raw = lower_hir(hir);
    let mut corrupt = raw.clone();
    corrupt.functions[0].locals[0].ty = symbolic;
    let errors = verify_mir(corrupt).unwrap_err();
    assert!(errors[0].message.contains("unresolved generic"));
    let mir = verify_mir(raw).unwrap();
    let mut ssa = build_ssa(&mir);
    ssa.functions[0].blocks[0].instructions[0].ty = symbolic;
    let errors = verify_ssa(ssa).unwrap_err();
    assert!(errors[0].message.contains("unresolved generic"));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical18_pop_native_owners_and_exact_counts() {
    for (fixture, count, relocations) in [
        ("v18_pop_int.ae", 1, 0),
        ("v18_pop_buffer.ae", 4, 0),
        ("v18_pop_nested.ae", 3, 0),
        ("v18_pop_reuse.ae", 4, 2),
        ("v18_pop_owners.ae", 14, 0),
        ("v18_pop_conditional.ae", 8, 0),
    ] {
        let compilation = compile_session(
            CompilationSession::discover(&program(fixture)).unwrap(),
            &[],
        )
        .unwrap();
        for (counter, expected) in [
            (None, 0),
            (Some("@aether_heap_alloc_count"), count),
            (Some("@aether_heap_free_count"), count),
            (Some("@aether_relocation_count"), relocations),
        ] {
            let llvm = counter.map_or_else(|| compilation.llvm.clone(), |counter| compilation.llvm.replace(
                "  %process_status = trunc i64 %aether_result to i32",
                &format!("  %observed_count = load i64, ptr {counter}\n  %process_status = trunc i64 %observed_count to i32"),
            ));
            let artifact = temporary("v18-count");
            ClangToolchain::default()
                .link_executable(&llvm, &artifact)
                .unwrap();
            let status = Command::new(&artifact).status().unwrap();
            let _ = fs::remove_file(artifact);
            assert_eq!(status.code(), Some(expected), "{fixture}: {counter:?}");
        }
    }
    let (_, status) =
        run_path(&module_program("v18_pop"), &[], &ClangToolchain::default()).unwrap();
    assert_eq!(status.code(), Some(42));
}

#[test]
fn vertical18_pop_borrow_and_capability_diagnostics() {
    let cases = [
        (
            "int f(ref List<int> x){return pop(*x);}int main(){List<int>x={1};return f(&x);}",
            "E0318",
        ),
        (
            "int main(){List<int>x={1,2,3};ref int r=&x[2];int v=pop(x);return *r;}",
            "E0319",
        ),
        (
            "int main(){List<int>x={1,2,3};ref mut int r=&mut x[2];int v=pop(x);return *r;}",
            "E0319",
        ),
        (
            "int main(){List<int>x={1,2,3};usize i=1;ref int r=&x[i];int v=pop(x);return *r;}",
            "E0319",
        ),
        (
            "int main(){List<int>x={1,2,3};View<int>v=view(x);int y=pop(x);return v[0];}",
            "E0319",
        ),
        (
            "int main(){List<int>x={1,2,3};ViewMut<int>v=view_mut(x);int y=pop(x);return v[0];}",
            "E0319",
        ),
        (
            "int main(){List<Buffer<int>>x={Buffer<int>(1,1),Buffer<int>(1,2)};ref int r=&x[0][0];Buffer<int>v=pop(x);return *r;}",
            "E0319",
        ),
        (
            "int main(){List<int>x={1,2};ref int r=&x[0];int a=pop(x);int b=pop(x);return *r;}",
            "E0319",
        ),
        (
            "int main(){List<int>x={1,2};ref int r=&x[0];while(length(x)>0){int a=pop(x);}return *r;}",
            "E0319",
        ),
        (
            "T f<T: Storable>(ref mut List<T> x){return pop(*x);}int main(){return 0;}",
            "E0310",
        ),
        (
            "T f<T: Relocatable>(ref mut List<T> x){return pop(*x);}int main(){return 0;}",
            "E0310",
        ),
        ("int main(){List<int>x={1};return pop(x,1);}", "E0318"),
        (
            "int f(ref mut List<int>x,ref int r){int a=pop(*x);return *r;}int main(){List<int>x={1,2};return f(&mut x,&x[1]);}",
            "E0313",
        ),
        (
            "struct Wrap{List<int> x;}int f(ref mut Wrap w){return pop((*w).x);}int main(){Wrap w=Wrap({1,2});ref int r=&w.x[1];return f(&mut w);}",
            "E0313",
        ),
        (
            "int use(ref int r,int v){return *r+v;}int main(){List<int>x={1,2};return use(&x[1],pop(x));}",
            "E0319",
        ),
        (
            "int shrink(ref mut List<int>x){return pop(*x);}int main(){List<int>x={1,2};int a=shrink(&mut x);ref int r=&x[0];int b=pop(x);return *r;}",
            "E0319",
        ),
    ];
    for (source, expected) in cases {
        let errors = compile_source(&SourceFile::new("v18-borrow.ae", source), &[]).unwrap_err();
        assert_eq!(errors[0].code, expected, "{source}: {}", errors[0].message);
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical18_pop_scopes_aliases_loops_and_conditional_cleanup() {
    let cases = [
        "int main(){List<int>x={1,2,3};if(true){ref int r=&x[2];int a=*r;}return pop(x);}",
        "int main(){List<int>x={1,2,3};if(true){View<int>v=view(x);int a=v[2];}return pop(x);}",
        "int main(){List<int>x={1,2,3};if(true){ViewMut<int>v=view_mut(x);v[2]=3;}return pop(x);}",
        "int main(){List<int>x={1,2,3};ref mut List<int> handle=&mut x;ref int r=&x[0];int a=pop(*handle);return a+*r-1;}",
        "int main(){List<int>x={1,2};ref int r=&x[0];ref int other=r;int a=pop(x);return *other+a;}",
        "int inc(ref mut int x){*x=*x+1;return 0;}int main(){List<int>x={0,2};ref int r=&x[0];int ignored=inc(&mut x[0]);int a=pop(x);return *r+a;}",
        "struct Point{int value;}int set(ref mut Point x){(*x).value=1;return 0;}int main(){List<Point>x={Point(0),Point(2)};int ignored=set(&mut x[0]);Point tail=pop(x);return x[0].value+tail.value;}",
        "int main(){List<int>x={1,2};ref int r=&x[0];ref mut List<int>handle=&mut x;ref mut List<int>other=handle;int a=pop(*other);return *r+a;}",
        "int main(){List<int>x={1,2};int sum=0;while(length(x)>0){sum=sum+pop(x);}push(x,sum);return pop(x);}",
        "int consume(Buffer<int>x){return x[0];}int main(){List<Buffer<int>>x={Buffer<int>(1,3)};Buffer<int>b=pop(x);if(length(x)==0){int r=consume(b);}return 3;}",
        "List<int> take(List<int>x){int a=pop(x);return x;}int main(){List<int>x={3,4};List<int>y=take(x);return y[0];}",
        "int main(){List<List<int>>x={{3,4}};int a=pop(x[0]);return a-1;}",
        "int use(ref int r,int v){return *r+v;}int main(){List<int>x={1,2};return use(&x[0],pop(x));}",
    ];
    for source in cases {
        let compilation = compile_source(&SourceFile::new("v18-scope.ae", source), &[]).unwrap();
        let artifact = temporary("v18-scope");
        ClangToolchain::default()
            .link_executable(&compilation.llvm, &artifact)
            .unwrap();
        let status = Command::new(&artifact).status().unwrap();
        let _ = fs::remove_file(artifact);
        assert_eq!(status.code(), Some(3), "{source}");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical18_empty_pop_traps_before_extraction() {
    for source in [
        "int f(ref mut List<int>x){return pop(*x);}int main(){List<int>x={};return f(&mut x);}",
        "int main(){List<Buffer<int>>x={};Buffer<int>b=pop(x);return b[0];}",
    ] {
        let compilation = compile_source(
            &SourceFile::new("v18-empty.ae", source),
            &[Emit::Mir, Emit::Ssa],
        )
        .unwrap();
        assert!(compilation.dumps[&Emit::Mir].contains("ListEmpty"));
        assert!(compilation.dumps[&Emit::Ssa].contains("ListEmpty"));
        let artifact = temporary("v18-empty");
        ClangToolchain::default()
            .link_executable(&compilation.llvm, &artifact)
            .unwrap();
        let status = Command::new(&artifact).status().unwrap();
        let _ = fs::remove_file(artifact);
        assert!(!status.success());
    }
}

#[test]
fn vertical18_dumps_retain_slot_ownership_and_stable_effect() {
    let source = SourceFile::new(
        "v18-dump.ae",
        "int main(){List<Buffer<int>>x={Buffer<int>(1,42)};Buffer<int>b=pop(x);return b[0];}",
    );
    let phases = [Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let compilation = compile_source(&source, &phases).unwrap();
    let again = compile_source(&source, &phases).unwrap();
    assert_eq!(compilation.dumps, again.dumps);
    assert!(compilation.dumps[&Emit::Hir].contains("ListPop"));
    assert!(compilation.dumps[&Emit::Hir].contains("StableStructuralMutation"));
    for phase in [Emit::Mir, Emit::Ssa] {
        for text in [
            "TailIndex",
            "Take",
            "SlotPlace",
            "before: Initialized",
            "after: Uninitialized",
            "ListSetLength",
            "ListEmpty",
        ] {
            assert!(
                compilation.dumps[&phase].contains(text),
                "{phase:?}: {text}"
            );
        }
    }
    assert!(compilation.llvm.contains("checked nonempty tail"));
    assert!(compilation.llvm.contains("Take: source slot Uninitialized"));
    assert!(compilation.llvm.contains("commit initialized prefix"));
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical18_verifiers_reject_corrupt_extraction_transactions() {
    use aether_middle::{
        ElementInitialization, Operand, Rvalue, SsaOp, SsaOperand, Terminator, build_ssa,
        lower_hir, verify_mir, verify_ssa,
    };
    let source = SourceFile::new(
        "v18-corrupt.ae",
        "int main(){List<Buffer<int>>x={Buffer<int>(1,42)};Buffer<int>b=pop(x);return b[0];}",
    );
    let raw = lower_hir(analyze(parse_source(&source).unwrap()).unwrap());
    let success = raw.functions[0]
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.value, Rvalue::Take { .. }))
        })
        .unwrap();
    for mutation in 0..10 {
        let mut corrupt = raw.clone();
        let block = &mut corrupt.functions[0].blocks[success];
        match mutation {
            0 => {
                if let Rvalue::Take { state, .. } = &mut block.instructions[1].value {
                    state.before = ElementInitialization::Uninitialized;
                }
            }
            1 => {
                if let Rvalue::Take { state, .. } = &mut block.instructions[1].value {
                    state.after = ElementInitialization::Initialized;
                }
            }
            2 => {
                block.instructions.insert(2, block.instructions[1].clone());
            }
            3 => {
                block.instructions.remove(2);
            }
            4 => {
                if let Rvalue::ListSetLength { length, .. } = &mut block.instructions[2].value {
                    *length = Operand::Int {
                        value: 1,
                        ty: aether_frontend::TypeId::USIZE,
                    };
                }
            }
            5 => {
                if let Rvalue::Take { slot, .. } = &mut block.instructions[1].value {
                    slot.index = Operand::Int {
                        value: 8,
                        ty: aether_frontend::TypeId::USIZE,
                    };
                }
            }
            6 => {
                block.instructions.swap(1, 2);
            }
            7 => {
                corrupt.functions[0].blocks[0].terminator = Some(Terminator::Goto(
                    aether_middle::BlockId(u32::try_from(success).unwrap()),
                ));
            }
            8 => {
                if let Rvalue::Take { state, .. } = &mut block.instructions[1].value {
                    state.non_trapping = false;
                }
            }
            9 => {
                let Rvalue::Take { slot, .. } = block.instructions[1].value.clone() else {
                    unreachable!()
                };
                let mut owner = slot.root;
                owner
                    .projections
                    .push(aether_middle::PlaceProjection::Index {
                        index: slot.index,
                        element_type: slot.type_id,
                        semantics: aether_frontend::IndexSemantics::ZeroBased,
                        column: None,
                        bounds_trap: aether_middle::TrapKind::IndexOutOfBounds,
                    });
                let drop = block
                    .instructions
                    .iter_mut()
                    .find(|i| matches!(i.value, Rvalue::Drop { .. }))
                    .unwrap();
                drop.value = Rvalue::Drop { owner };
            }
            _ => unreachable!(),
        }
        assert!(verify_mir(corrupt).is_err(), "MIR mutation {mutation}");
    }
    let ssa = build_ssa(&verify_mir(raw).unwrap());
    for mutation in 0..10 {
        let mut corrupt = ssa.clone();
        let block = &mut corrupt.functions[0].blocks[success];
        match mutation {
            0 => {
                if let SsaOp::Take { state, .. } = &mut block.instructions[1].op {
                    state.before = ElementInitialization::Uninitialized;
                }
            }
            1 => {
                if let SsaOp::Take { state, .. } = &mut block.instructions[1].op {
                    state.after = ElementInitialization::Initialized;
                }
            }
            2 => {
                block.instructions.insert(2, block.instructions[1].clone());
            }
            3 => {
                block.instructions.remove(2);
            }
            4 => {
                if let SsaOp::ListSetLength { length, .. } = &mut block.instructions[2].op {
                    *length = SsaOperand::Int {
                        value: 1,
                        ty: aether_frontend::TypeId::USIZE,
                    };
                }
            }
            5 => {
                if let SsaOp::Take { slot, .. } = &mut block.instructions[1].op {
                    slot.index = SsaOperand::Int {
                        value: 8,
                        ty: aether_frontend::TypeId::USIZE,
                    };
                }
            }
            6 => {
                block.instructions.swap(1, 2);
            }
            7 => {
                block.instructions[1].op =
                    SsaOp::Use(SsaOperand::Value(block.instructions[1].result));
            }
            8 => {
                if let SsaOp::Take { state, .. } = &mut block.instructions[1].op {
                    state.non_trapping = false;
                }
            }
            9 => {
                let SsaOp::Take { slot, .. } = block.instructions[1].op.clone() else {
                    unreachable!()
                };
                let mut owner = slot.root;
                owner
                    .projections
                    .push(aether_middle::SsaPlaceProjection::Index {
                        index: slot.index,
                        element_type: slot.type_id,
                        semantics: aether_frontend::IndexSemantics::ZeroBased,
                        column: None,
                        bounds_trap: aether_middle::TrapKind::IndexOutOfBounds,
                    });
                let drop = block
                    .instructions
                    .iter_mut()
                    .find(|i| matches!(i.op, SsaOp::Drop { .. }))
                    .unwrap();
                drop.op = SsaOp::Drop { owner };
            }
            _ => unreachable!(),
        }
        assert!(verify_ssa(corrupt).is_err(), "SSA mutation {mutation}");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical18_each_pop_preserves_pointer_capacity_and_heap_counters() {
    for fixture in [
        "v18_pop_int.ae",
        "v18_pop_buffer.ae",
        "v18_pop_nested.ae",
        "v18_pop_reuse.ae",
        "v18_pop_owners.ae",
        "v18_pop_conditional.ae",
    ] {
        let compilation = compile_session(
            CompilationSession::discover(&program(fixture)).unwrap(),
            &[],
        )
        .unwrap();
        let mut llvm = String::new();
        let mut pending = None;
        let mut probes = 0;
        for line in compilation.llvm.lines() {
            if line.starts_with("  %take") && line.contains("_data = extractvalue") {
                let id = line
                    .trim()
                    .strip_prefix("%take")
                    .unwrap()
                    .split('_')
                    .next()
                    .unwrap();
                let descriptor = line
                    .split_once("} ")
                    .unwrap()
                    .1
                    .strip_suffix(", 0")
                    .unwrap();
                write!(llvm, "  %probe{id}_alloc = load i64, ptr @aether_heap_alloc_count\n  %probe{id}_free = load i64, ptr @aether_heap_free_count\n  %probe{id}_cap = extractvalue {{ ptr, i64, i64 }} {descriptor}, 2\n").unwrap();
                pending = Some(id.to_string());
            }
            llvm.push_str(line);
            llvm.push('\n');
            if line.contains("; commit initialized prefix") {
                let id = pending.take().expect("Take precedes every length commit");
                let length_pointer = line
                    .split_once("ptr ")
                    .unwrap()
                    .1
                    .split(" ;")
                    .next()
                    .unwrap();
                writeln!(llvm, "  call void @v18_assert_pop(ptr %take{id}_data, i64 %probe{id}_cap, i64 %probe{id}_alloc, i64 %probe{id}_free, ptr {length_pointer})").unwrap();
                probes += 1;
            }
        }
        assert!(probes > 0);
        assert!(pending.is_none());
        llvm.push_str(r"
define internal void @v18_assert_pop(ptr %old_data, i64 %old_cap, i64 %old_alloc, i64 %old_free, ptr %length_field) {
entry:
  %data_field = getelementptr i64, ptr %length_field, i64 -1
  %capacity_field = getelementptr i64, ptr %length_field, i64 1
  %data = load ptr, ptr %data_field
  %capacity = load i64, ptr %capacity_field
  %allocs = load i64, ptr @aether_heap_alloc_count
  %frees = load i64, ptr @aether_heap_free_count
  %same_data = icmp eq ptr %data, %old_data
  %same_capacity = icmp eq i64 %capacity, %old_cap
  %same_allocs = icmp eq i64 %allocs, %old_alloc
  %same_frees = icmp eq i64 %frees, %old_free
  %storage_ok = and i1 %same_data, %same_capacity
  %heap_ok = and i1 %same_allocs, %same_frees
  %ok = and i1 %storage_ok, %heap_ok
  br i1 %ok, label %done, label %failed
failed:
  call void @llvm.trap()
  unreachable
done:
  ret void
}
");
        let artifact = temporary("v18-stable-storage");
        ClangToolchain::default()
            .link_executable(&llvm, &artifact)
            .unwrap();
        let status = Command::new(&artifact).status().unwrap();
        let _ = fs::remove_file(artifact);
        assert_eq!(status.code(), Some(0), "{fixture}");
    }
}

#[test]
fn vertical18_push_reinitialization_and_effect_contracts() {
    use aether_frontend::{MutationEffect, StructuralMutation};
    use aether_middle::{
        ElementInitialization, Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa,
    };
    assert_eq!(
        StructuralMutation::Pop.effect(),
        MutationEffect::StableStructuralMutation
    );
    assert_eq!(
        StructuralMutation::Push.effect(),
        MutationEffect::PotentiallyRelocatingMutation
    );
    assert_eq!(
        StructuralMutation::Reserve.effect(),
        MutationEffect::PotentiallyRelocatingMutation
    );
    let source = SourceFile::new(
        "v18-push.ae",
        "int main(){List<int>x={1};int a=pop(x);push(x,a);return x[0];}",
    );
    let raw = lower_hir(analyze(parse_source(&source).unwrap()).unwrap());
    let mut corrupt = raw.clone();
    let initialization = corrupt.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|b| &mut b.instructions)
        .find_map(|i| {
            if let Rvalue::ListPush { initialization, .. } = &mut i.value {
                Some(initialization)
            } else {
                None
            }
        })
        .unwrap();
    initialization.before = ElementInitialization::Initialized;
    assert!(verify_mir(corrupt).is_err());
    let mir = verify_mir(raw).unwrap();
    assert!(mir.dump().contains("PushInit"));
    let mut ssa = build_ssa(&mir);
    let initialization = ssa.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|b| &mut b.instructions)
        .find_map(|i| {
            if let SsaOp::ListPush { initialization, .. } = &mut i.op {
                Some(initialization)
            } else {
                None
            }
        })
        .unwrap();
    initialization.after = ElementInitialization::Uninitialized;
    assert!(verify_ssa(ssa).is_err());
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical19_swap_remove_native_owners_and_exact_counts() {
    for (fixture, count, relocations) in [
        ("v19_swap_remove_int.ae", 1, 1),
        ("v19_swap_remove_buffer.ae", 5, 1),
        ("v19_swap_remove_nested.ae", 5, 2),
        ("v19_swap_remove_reuse.ae", 5, 4),
        ("v19_swap_remove_dataset.ae", 4, 1),
        ("v19_swap_remove_enum.ae", 3, 2),
        ("v19_swap_remove_array.ae", 4, 1),
        ("v19_swap_remove_return.ae", 3, 1),
        ("v19_swap_remove_consume.ae", 3, 1),
        ("v19_swap_remove_conditional.ae", 10, 4),
        ("v19_swap_remove_tail.ae", 3, 0),
    ] {
        let compilation = compile_session(
            CompilationSession::discover(&program(fixture)).unwrap(),
            &[],
        )
        .unwrap();
        for (counter, expected) in [
            (None, 0),
            (Some("@aether_heap_alloc_count"), count),
            (Some("@aether_heap_free_count"), count),
            (Some("@aether_relocation_count"), relocations),
        ] {
            let llvm = counter.map_or_else(|| compilation.llvm.clone(), |counter| compilation.llvm.replace(
                "  %process_status = trunc i64 %aether_result to i32",
                &format!("  %observed_count = load i64, ptr {counter}\n  %process_status = trunc i64 %observed_count to i32"),
            ));
            let artifact = temporary("v19-count");
            ClangToolchain::default()
                .link_executable(&llvm, &artifact)
                .unwrap();
            let status = Command::new(&artifact).status().unwrap();
            let _ = fs::remove_file(artifact);
            assert_eq!(status.code(), Some(expected), "{fixture}: {counter:?}");
        }
    }
    let (_, status) = run_path(
        &module_program("v19_swap_remove"),
        &[],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(42));
}

#[test]
fn vertical19_swap_remove_diagnostics() {
    for source in [
        "int main(){int x=1;return swap_remove(x,0);}",
        "int main(){Array<int>x={1};return swap_remove(x,0);}",
        "int main(){List<int>x={1};return swap_remove(x);}",
        "int f(ref List<int>x){return swap_remove(*x,0);}int main(){List<int>x={1};return f(&x);}",
    ] {
        let errors = compile_source(&SourceFile::new("v19-target.ae", source), &[]).unwrap_err();
        assert_eq!(errors[0].code, "E0320", "{source}: {errors:?}");
    }
    for source in [
        "int main(){List<int>x={10,20,30,40};ref int r=&x[1];int v=swap_remove(x,1);return *r;}",
        "int main(){List<int>x={10,20,30,40};ref mut int r=&mut x[1];int v=swap_remove(x,1);return *r;}",
        "int main(){List<int>x={10,20,30,40};ref int r=&x[3];int v=swap_remove(x,1);return *r;}",
        "int main(){List<int>x={10,20,30,40};usize i=0;ref int r=&x[i];int v=swap_remove(x,1);return *r;}",
        "int main(){List<int>x={10,20,30,40};usize i=1;ref int r=&x[0];int v=swap_remove(x,i);return *r;}",
        "int main(){List<int>x={10,20,30,40};View<int>v=view(x);int r=swap_remove(x,1);return v[0];}",
        "int main(){List<int>x={10,20,30,40};ViewMut<int>v=view_mut(x);int r=swap_remove(x,1);return v[0];}",
        "int main(){List<Buffer<int>>x={Buffer<int>(1,1),Buffer<int>(1,2),Buffer<int>(1,3)};ref int r=&x[0][0];Buffer<int>v=swap_remove(x,1);return *r;}",
        "int main(){List<int>x={10,20,30,40};ref mut List<int>a=&mut x;ref int r=&x[3];int v=swap_remove(*a,1);return *r;}",
        "int main(){List<int>x={10,20,30};ref int r=&x[1];int a=swap_remove(x,2);int b=swap_remove(x,0);return *r;}",
        "int main(){List<int>x={10,20,30};ref int r=&x[0];while(length(x)>1){int a=swap_remove(x,1);}return *r;}",
    ] {
        let errors = compile_source(&SourceFile::new("v19-borrow.ae", source), &[]).unwrap_err();
        assert_eq!(errors[0].code, "E0321", "{source}: {errors:?}");
    }
    for source in [
        "int main(){List<int>x={1};int i=0;return swap_remove(x,i);}",
        "int main(){List<int>x={1};return swap_remove(x,true);}",
        "int main(){List<int>x={1};return swap_remove(x,-1);}",
        "T f<T: Storable>(ref mut List<T>x,usize i){return swap_remove(*x,i);}int main(){return 0;}",
        "T f<T: Relocatable>(ref mut List<T>x,usize i){return swap_remove(*x,i);}int main(){return 0;}",
        "int f(ref int r,int x){return *r;}int main(){List<int>x={1,2,3};return f(&x[1],swap_remove(x,1));}",
    ] {
        assert!(
            compile_source(&SourceFile::new("v19-type.ae", source), &[]).is_err(),
            "{source}"
        );
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical19_scopes_aliases_and_descriptor_freshness() {
    for source in [
        "int main(){List<int>x={10,20,30,40};if(true){ref int r=&x[1];if(*r!=20){return 1;}}int v=swap_remove(x,1);return x[1]-40;}",
        "int main(){List<int>x={10,20,30,40};if(true){View<int>v=view(x);if(v[1]!=20){return 1;}}int v=swap_remove(x,1);return x[1]-40;}",
        "int main(){List<int>x={10,20,30,40};if(true){ViewMut<int>v=view_mut(x);v[1]=21;}int v=swap_remove(x,1);return v-21;}",
        "int main(){List<int>x={10,20,30,40};ref mut List<int>a=&mut x;ref int r=&x[0];int v=swap_remove(*a,1);if(*r!=10){return 1;}if(length(*a)!=3){return 2;}return x[1]-40;}",
        "List<int> f(){List<int>x={10,20,30};int v=swap_remove(x,0);return x;}int main(){List<int>x=f();if(length(x)!=2){return 1;}return x[0]-30;}",
        "int main(){List<List<int>>x={{10,20,30},{40}};int v=swap_remove(x[0],0);if(length(x[0])!=2){return 1;}push(x[0],v);return x[0][2]-10;}",
        "int pick(ref mut int calls){*calls=*calls+1;return 1;}int main(){int calls=0;List<int>x={10,20,30};int v=swap_remove(x,usize(pick(&mut calls)));if(calls!=1){return 1;}return v-20;}",
    ] {
        let compilation = compile_source(&SourceFile::new("v19-scope.ae", source), &[]).unwrap();
        let artifact = temporary("v19-scope");
        ClangToolchain::default()
            .link_executable(&compilation.llvm, &artifact)
            .unwrap();
        let status = Command::new(&artifact).status().unwrap();
        let _ = fs::remove_file(artifact);
        assert_eq!(status.code(), Some(0), "{source}");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical19_bounds_trap_before_transaction() {
    for source in [
        "int f(ref mut List<int>x,usize i){return swap_remove(*x,i);}int main(){List<int>x={};return f(&mut x,0);}",
        "int main(){List<int>x={1,2};return swap_remove(x,2);}",
        "int main(){List<Buffer<int>>x={};Buffer<int>b=swap_remove(x,0);return b[0];}",
        "int main(){List<int>x={1};usize i=18446744073709551615;return swap_remove(x,i);}",
    ] {
        let compilation = compile_source(
            &SourceFile::new("v19-bounds.ae", source),
            &[Emit::Mir, Emit::Ssa],
        )
        .unwrap();
        for phase in [Emit::Mir, Emit::Ssa] {
            assert!(compilation.dumps[&phase].contains("IndexOutOfBounds"));
        }
        let artifact = temporary("v19-bounds");
        ClangToolchain::default()
            .link_executable(&compilation.llvm, &artifact)
            .unwrap();
        let status = Command::new(&artifact).status().unwrap();
        let _ = fs::remove_file(artifact);
        assert!(!status.success(), "{source}");
    }
}

#[test]
fn vertical19_deterministic_semantic_dumps() {
    let source = SourceFile::new(
        "v19-dump.ae",
        "int main(){List<Buffer<int>>x={Buffer<int>(1,10),Buffer<int>(1,20)};Buffer<int>b=swap_remove(x,0);return b[0];}",
    );
    let phases = [Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let compilation = compile_source(&source, &phases).unwrap();
    assert_eq!(
        compilation.dumps,
        compile_source(&source, &phases).unwrap().dumps
    );
    for text in ["ListSwapRemove", "StableStructuralMutation", "IndexAndTail"] {
        assert!(compilation.dumps[&Emit::Hir].contains(text), "{text}");
    }
    for phase in [Emit::Mir, Emit::Ssa] {
        for text in [
            "Take",
            "Relocate",
            "SingleSlot",
            "TailIndex",
            "IndexOutOfBounds",
            "ListSetLength",
            "destination_after: Initialized",
            "source_after: Uninitialized",
        ] {
            assert!(
                compilation.dumps[&phase].contains(text),
                "{phase:?}: {text}"
            );
        }
    }
    assert!(compilation.llvm.contains("hole Initialized"));
    assert!(compilation.llvm.contains("icmp eq i64"));
    assert_eq!(
        aether_frontend::StructuralMutation::SwapRemove.effect(),
        aether_frontend::MutationEffect::StableStructuralMutation
    );
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[allow(clippy::too_many_lines)]
fn vertical19_each_swap_remove_preserves_storage_heap_and_relocation_counts() {
    for fixture in [
        "v19_swap_remove_int.ae",
        "v19_swap_remove_buffer.ae",
        "v19_swap_remove_nested.ae",
        "v19_swap_remove_reuse.ae",
        "v19_swap_remove_dataset.ae",
        "v19_swap_remove_enum.ae",
        "v19_swap_remove_array.ae",
        "v19_swap_remove_return.ae",
        "v19_swap_remove_consume.ae",
        "v19_swap_remove_conditional.ae",
        "v19_swap_remove_tail.ae",
    ] {
        let compilation = compile_session(
            CompilationSession::discover(&program(fixture)).unwrap(),
            &[],
        )
        .unwrap();
        let mut llvm = String::new();
        let mut pending = None;
        let mut probes = 0;
        for line in compilation.llvm.lines() {
            if line.starts_with("  %take") && line.contains("_data = extractvalue") {
                let id = line
                    .trim()
                    .strip_prefix("%take")
                    .unwrap()
                    .split('_')
                    .next()
                    .unwrap();
                let descriptor = line
                    .split_once("} ")
                    .unwrap()
                    .1
                    .strip_suffix(", 0")
                    .unwrap();
                write!(llvm, "  %probe{id}_alloc = load i64, ptr @aether_heap_alloc_count\n  %probe{id}_free = load i64, ptr @aether_heap_free_count\n  %probe{id}_cap = extractvalue {{ ptr, i64, i64 }} {descriptor}, 2\n").unwrap();
                pending = Some(id.to_string());
            }
            if line.starts_with("  %take") && line.contains("_slot = getelementptr") {
                let id = pending.as_ref().unwrap();
                let index = line.rsplit_once("i64 ").unwrap().1;
                writeln!(
                    llvm,
                    "  %probe{id}_reloc = load i64, ptr @aether_relocation_count"
                )
                .unwrap();
                writeln!(llvm, "  %probe{id}_index = add i64 {index}, 0").unwrap();
            }
            llvm.push_str(line);
            llvm.push('\n');
            if line.contains("; commit initialized prefix") {
                let id = pending.take().expect("Take precedes every length commit");
                let length_pointer = line
                    .split_once("ptr ")
                    .unwrap()
                    .1
                    .split(" ;")
                    .next()
                    .unwrap();
                writeln!(llvm, "  call void @v19_assert_pop(ptr %take{id}_data, i64 %probe{id}_cap, i64 %probe{id}_alloc, i64 %probe{id}_free, i64 %probe{id}_reloc, i64 %probe{id}_index, ptr {length_pointer})").unwrap();
                probes += 1;
            }
        }
        assert!(probes > 0);
        assert!(pending.is_none());
        llvm.push_str(r"
define internal void @v19_assert_pop(ptr %old_data, i64 %old_cap, i64 %old_alloc, i64 %old_free, i64 %old_reloc, i64 %removed_index, ptr %length_field) {
entry:
  %data_field = getelementptr i64, ptr %length_field, i64 -1
  %capacity_field = getelementptr i64, ptr %length_field, i64 1
  %data = load ptr, ptr %data_field
  %capacity = load i64, ptr %capacity_field
  %allocs = load i64, ptr @aether_heap_alloc_count
  %frees = load i64, ptr @aether_heap_free_count
  %same_data = icmp eq ptr %data, %old_data
  %same_capacity = icmp eq i64 %capacity, %old_cap
  %same_allocs = icmp eq i64 %allocs, %old_alloc
  %same_frees = icmp eq i64 %frees, %old_free
  %storage_ok = and i1 %same_data, %same_capacity
  %heap_ok = and i1 %same_allocs, %same_frees
  %new_length = load i64, ptr %length_field
  %non_tail = icmp ne i64 %removed_index, %new_length
  %expected_reloc = zext i1 %non_tail to i64
  %relocs = load i64, ptr @aether_relocation_count
  %delta_reloc = sub i64 %relocs, %old_reloc
  %reloc_ok = icmp eq i64 %delta_reloc, %expected_reloc
  %stable = and i1 %storage_ok, %heap_ok
  %ok = and i1 %stable, %reloc_ok
  br i1 %ok, label %done, label %failed
failed:
  call void @llvm.trap()
  unreachable
done:
  ret void
}
");
        let artifact = temporary("v19-stable-storage");
        ClangToolchain::default()
            .link_executable(&llvm, &artifact)
            .unwrap();
        let status = Command::new(&artifact).status().unwrap();
        let _ = fs::remove_file(artifact);
        assert_eq!(status.code(), Some(0), "{fixture}");
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical19_mir_rejects_corrupt_slot_transactions() {
    use aether_middle::{
        ElementInitialization, Operand, PlaceProjection, Rvalue, Terminator, TrapKind, lower_hir,
        verify_mir,
    };
    let source = SourceFile::new(
        "v19-corrupt.ae",
        "int main(){List<Buffer<int>>other={Buffer<int>(1,9)};List<Buffer<int>>x={Buffer<int>(1,10),Buffer<int>(1,20),Buffer<int>(1,30)};Buffer<int>b=swap_remove(x,1);return b[0];}",
    );
    let raw = lower_hir(analyze(parse_source(&source).unwrap()).unwrap());
    verify_mir(raw.clone()).unwrap();
    let function = &raw.functions[0];
    let transaction = function
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.value, Rvalue::Take { .. }))
        })
        .unwrap();
    let transfer = function
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.value, Rvalue::Relocate { .. }))
        })
        .unwrap();
    let commit = function
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.value, Rvalue::ListSetLength { .. }))
        })
        .unwrap();
    let Terminator::Branch { then_block, .. } =
        function.blocks[transaction].terminator.as_ref().unwrap()
    else {
        panic!()
    };
    let tail_path = then_block.0 as usize;
    let guard=function.blocks.iter().position(|b|matches!(&b.terminator,Some(Terminator::Branch{then_block,..}) if then_block.0 as usize==transaction)).unwrap();
    let Rvalue::Take { slot, .. } = &function.blocks[transaction].instructions[1].value else {
        panic!()
    };
    let removed = slot.clone();
    let Rvalue::Relocate { source: tail, .. } = &function.blocks[transfer].instructions[0].value
    else {
        panic!()
    };
    let tail = tail.clone();
    let wrong_root = function.blocks[0]
        .instructions
        .iter()
        .find(|i| matches!(i.value, Rvalue::ListInit { .. }))
        .unwrap()
        .destination
        .clone();
    for mutation in 0..23 {
        let mut corrupt = raw.clone();
        let blocks = &mut corrupt.functions[0].blocks;
        match mutation {
            0 => {
                if let Rvalue::Take { slot, .. } = &mut blocks[transaction].instructions[1].value {
                    slot.root = wrong_root.clone();
                }
            }
            1 => {
                if let Rvalue::Take { slot, .. } = &mut blocks[transaction].instructions[1].value {
                    slot.index = tail.index.clone();
                }
            }
            2 => {
                if let Rvalue::Take { state, .. } = &mut blocks[transaction].instructions[1].value {
                    state.before = ElementInitialization::Uninitialized;
                }
            }
            3 => {
                let i = blocks[transfer].instructions.remove(0);
                blocks[transaction].instructions.insert(1, i);
            }
            4 => {
                if let Rvalue::Relocate { source, .. } = &mut blocks[transfer].instructions[0].value
                {
                    source.index = removed.index.clone();
                }
            }
            5 => {
                if let Rvalue::Relocate { destination, .. } =
                    &mut blocks[transfer].instructions[0].value
                {
                    destination.index = tail.index.clone();
                }
            }
            6 => {
                let i = blocks[transfer].instructions.remove(0);
                blocks[tail_path].instructions.push(i);
            }
            7 => {
                blocks[transfer].instructions.clear();
            }
            8 => {
                let i = blocks[transfer].instructions[0].clone();
                blocks[transfer].instructions.push(i);
            }
            9 => {
                if let Rvalue::Relocate { relocation, .. } =
                    &mut blocks[transfer].instructions[0].value
                {
                    relocation.source_after = ElementInitialization::Initialized;
                }
            }
            10 => {
                if let Rvalue::Relocate { relocation, .. } =
                    &mut blocks[transfer].instructions[0].value
                {
                    relocation.destination_after = ElementInitialization::Uninitialized;
                }
            }
            11 => {
                if let Rvalue::ListSetLength { length, .. } =
                    &mut blocks[commit].instructions[0].value
                {
                    *length = removed.index.clone();
                }
            }
            12 => {
                let i = blocks[commit].instructions.remove(0);
                blocks[transfer].instructions.insert(0, i);
            }
            13 => {
                if let Rvalue::TailIndex { length } = &mut blocks[transaction].instructions[0].value
                {
                    *length = Operand::Int {
                        value: 3,
                        ty: aether_frontend::TypeId::USIZE,
                    };
                }
            }
            14 => {
                if let Rvalue::Binary { left, .. } =
                    &mut blocks[guard].instructions.last_mut().unwrap().value
                {
                    *left = Operand::Int {
                        value: 0,
                        ty: aether_frontend::TypeId::USIZE,
                    };
                }
            }
            15 => {
                let mut owner = tail.root.clone();
                owner.projections.push(PlaceProjection::Index {
                    index: tail.index.clone(),
                    element_type: tail.type_id,
                    semantics: aether_frontend::IndexSemantics::ZeroBased,
                    column: None,
                    bounds_trap: TrapKind::IndexOutOfBounds,
                });
                let mut i = blocks[transfer].instructions[0].clone();
                i.value = Rvalue::Drop { owner };
                blocks[transfer].instructions.push(i);
            }
            16 => {
                let operand =
                    Operand::Local(match blocks[transaction].instructions[1].destination.base {
                        aether_middle::PlaceBase::Local(l) => l,
                        aether_middle::PlaceBase::Dereference { .. } => panic!(),
                    });
                let i = blocks[commit]
                    .instructions
                    .iter_mut()
                    .find(|i| matches!(i.value, Rvalue::Move { .. }))
                    .unwrap();
                i.value = Rvalue::Use(operand);
            }
            17 => {
                if let Rvalue::Relocate { source, .. } = &mut blocks[transfer].instructions[0].value
                {
                    source.type_id = aether_frontend::TypeId::BOOL;
                }
            }
            18 => {
                if let Rvalue::Relocate { relocation, .. } =
                    &mut blocks[transfer].instructions[0].value
                {
                    relocation.non_trapping = false;
                }
            }
            19 => {
                if let Some(Terminator::Branch {
                    then_block,
                    else_block,
                    ..
                }) = &mut blocks[transaction].terminator
                {
                    std::mem::swap(then_block, else_block);
                }
            }
            20 => {
                let mut i = blocks[commit].instructions[0].clone();
                i.value = Rvalue::Use(Operand::Bool(true));
                let n = blocks[guard].instructions.len();
                blocks[guard].instructions.insert(n - 1, i);
            }
            21 => {
                blocks[tail_path].terminator = Some(Terminator::Return(Operand::Int {
                    value: 0,
                    ty: aether_frontend::TypeId::INT64,
                }));
            }
            22 => {
                if let Rvalue::Take { state, .. } = &mut blocks[transaction].instructions[1].value {
                    state.after = ElementInitialization::Initialized;
                }
            }
            _ => unreachable!(),
        }
        let errors = verify_mir(corrupt).unwrap_err();
        assert_eq!(
            errors[0].phase,
            aether_frontend::Phase::Mir,
            "mutation {mutation}: {errors:?}"
        );
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical19_ssa_rejects_corrupt_slot_transactions() {
    use aether_middle::{
        ElementInitialization, SsaOp, SsaOperand, SsaPlaceProjection, SsaTerminator, TrapKind,
        build_ssa, lower_hir, verify_mir, verify_ssa,
    };
    let source = SourceFile::new(
        "v19-corrupt.ae",
        "int main(){List<Buffer<int>>other={Buffer<int>(1,9)};List<Buffer<int>>x={Buffer<int>(1,10),Buffer<int>(1,20),Buffer<int>(1,30)};Buffer<int>b=swap_remove(x,1);return b[0];}",
    );
    let raw = build_ssa(
        &verify_mir(lower_hir(analyze(parse_source(&source).unwrap()).unwrap())).unwrap(),
    );
    verify_ssa(raw.clone()).unwrap();
    let function = &raw.functions[0];
    let transaction = function
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.op, SsaOp::Take { .. }))
        })
        .unwrap();
    let transfer = function
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.op, SsaOp::Relocate { .. }))
        })
        .unwrap();
    let commit = function
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.op, SsaOp::ListSetLength { .. }))
        })
        .unwrap();
    let SsaTerminator::Branch { then_block, .. } = &function.blocks[transaction].terminator else {
        panic!()
    };
    let tail_path = then_block.0 as usize;
    let guard=function.blocks.iter().position(|b|matches!(&b.terminator,SsaTerminator::Branch{then_block,..} if then_block.0 as usize==transaction)).unwrap();
    let SsaOp::Take { slot, .. } = &function.blocks[transaction].instructions[1].op else {
        panic!()
    };
    let removed = slot.clone();
    let SsaOp::Relocate { source: tail, .. } = &function.blocks[transfer].instructions[0].op else {
        panic!()
    };
    let tail = tail.clone();
    let wrong_root = aether_middle::SsaPlace {
        base: aether_middle::SsaPlaceBase::Value(SsaOperand::Value(
            function.blocks[0]
                .instructions
                .iter()
                .find(|i| matches!(i.op, SsaOp::ListInit { .. }))
                .unwrap()
                .result,
        )),
        projections: vec![],
    };
    for mutation in 0..23 {
        let mut corrupt = raw.clone();
        let blocks = &mut corrupt.functions[0].blocks;
        match mutation {
            0 => {
                if let SsaOp::Take { slot, .. } = &mut blocks[transaction].instructions[1].op {
                    slot.root = wrong_root.clone();
                }
            }
            1 => {
                if let SsaOp::Take { slot, .. } = &mut blocks[transaction].instructions[1].op {
                    slot.index = tail.index.clone();
                }
            }
            2 => {
                if let SsaOp::Take { state, .. } = &mut blocks[transaction].instructions[1].op {
                    state.before = ElementInitialization::Uninitialized;
                }
            }
            3 => {
                let i = blocks[transfer].instructions.remove(0);
                blocks[transaction].instructions.insert(1, i);
            }
            4 => {
                if let SsaOp::Relocate { source, .. } = &mut blocks[transfer].instructions[0].op {
                    source.index = removed.index.clone();
                }
            }
            5 => {
                if let SsaOp::Relocate { destination, .. } =
                    &mut blocks[transfer].instructions[0].op
                {
                    destination.index = tail.index.clone();
                }
            }
            6 => {
                let i = blocks[transfer].instructions.remove(0);
                blocks[tail_path].instructions.push(i);
            }
            7 => {
                blocks[transfer].instructions.clear();
            }
            8 => {
                let i = blocks[transfer].instructions[0].clone();
                blocks[transfer].instructions.push(i);
            }
            9 => {
                if let SsaOp::Relocate { relocation, .. } = &mut blocks[transfer].instructions[0].op
                {
                    relocation.source_after = ElementInitialization::Initialized;
                }
            }
            10 => {
                if let SsaOp::Relocate { relocation, .. } = &mut blocks[transfer].instructions[0].op
                {
                    relocation.destination_after = ElementInitialization::Uninitialized;
                }
            }
            11 => {
                if let SsaOp::ListSetLength { length, .. } = &mut blocks[commit].instructions[0].op
                {
                    *length = removed.index.clone();
                }
            }
            12 => {
                let i = blocks[commit].instructions.remove(0);
                blocks[transfer].instructions.insert(0, i);
            }
            13 => {
                if let SsaOp::TailIndex { length } = &mut blocks[transaction].instructions[0].op {
                    *length = SsaOperand::Int {
                        value: 3,
                        ty: aether_frontend::TypeId::USIZE,
                    };
                }
            }
            14 => {
                if let SsaOp::Binary { left, .. } =
                    &mut blocks[guard].instructions.last_mut().unwrap().op
                {
                    *left = SsaOperand::Int {
                        value: 0,
                        ty: aether_frontend::TypeId::USIZE,
                    };
                }
            }
            15 => {
                let mut owner = tail.root.clone();
                owner.projections.push(SsaPlaceProjection::Index {
                    index: tail.index.clone(),
                    element_type: tail.type_id,
                    semantics: aether_frontend::IndexSemantics::ZeroBased,
                    column: None,
                    bounds_trap: TrapKind::IndexOutOfBounds,
                });
                let mut i = blocks[transfer].instructions[0].clone();
                i.op = SsaOp::Drop { owner };
                blocks[transfer].instructions.push(i);
            }
            16 => {
                let operand = SsaOperand::Value(blocks[transaction].instructions[1].result);
                let i = blocks[commit]
                    .instructions
                    .iter_mut()
                    .find(|i| matches!(i.op, SsaOp::Move { .. }))
                    .unwrap();
                i.op = SsaOp::Use(operand);
            }
            17 => {
                if let SsaOp::Relocate { source, .. } = &mut blocks[transfer].instructions[0].op {
                    source.type_id = aether_frontend::TypeId::BOOL;
                }
            }
            18 => {
                if let SsaOp::Relocate { relocation, .. } = &mut blocks[transfer].instructions[0].op
                {
                    relocation.non_trapping = false;
                }
            }
            19 => {
                if let SsaTerminator::Branch {
                    then_block,
                    else_block,
                    ..
                } = &mut blocks[transaction].terminator
                {
                    std::mem::swap(then_block, else_block);
                }
            }
            20 => {
                let mut i = blocks[commit].instructions[0].clone();
                i.op = SsaOp::Use(SsaOperand::Bool(true));
                let n = blocks[guard].instructions.len();
                blocks[guard].instructions.insert(n - 1, i);
            }
            21 => {
                blocks[tail_path].terminator = SsaTerminator::Return(SsaOperand::Int {
                    value: 0,
                    ty: aether_frontend::TypeId::INT64,
                });
            }
            22 => {
                if let SsaOp::Take { state, .. } = &mut blocks[transaction].instructions[1].op {
                    state.after = ElementInitialization::Initialized;
                }
            }
            _ => unreachable!(),
        }
        let errors = verify_ssa(corrupt).unwrap_err();
        assert_eq!(
            errors[0].phase,
            aether_frontend::Phase::Ssa,
            "mutation {mutation}: {errors:?}"
        );
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical19_drop_order_uses_reverse_final_indices() {
    let compilation = compile_session(
        CompilationSession::discover(&program("v19_swap_remove_buffer.ae")).unwrap(),
        &[],
    )
    .unwrap();
    let mut llvm = compilation.llvm.replace(
        "call void @free(ptr %ptr)",
        "call void @v19_note_free(ptr %ptr, i64 %size)\n  call void @free(ptr %ptr)",
    ).replace(
        "  %process_status = trunc i64 %aether_result to i32",
        "  %trace = load i64, ptr @v19_drop_trace\n  %ordered = icmp eq i64 %trace, 20304010\n  %process_status = select i1 %ordered, i32 0, i32 99",
    );
    // The extracted 20 drops first. The final List [10,40,30] drops 30,40,10.
    // Only the four one-int Buffer allocations have size 8.
    llvm.push_str(
        r"
@v19_drop_trace = internal global i64 0
define internal void @v19_note_free(ptr %data, i64 %size) {
entry:
  %buffer = icmp eq i64 %size, 8
  br i1 %buffer, label %record, label %done
record:
  %payload = load i64, ptr %data
  %old = load i64, ptr @v19_drop_trace
  %shift = mul i64 %old, 100
  %next = add i64 %shift, %payload
  store i64 %next, ptr @v19_drop_trace
  br label %done
done:
  ret void
}
",
    );
    let artifact = temporary("v19-drop-order");
    ClangToolchain::default()
        .link_executable(&llvm, &artifact)
        .unwrap();
    let status = Command::new(&artifact).status().unwrap();
    let _ = fs::remove_file(artifact);
    assert_eq!(status.code(), Some(0));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical20_remove_native_owners_and_exact_counts() {
    for (fixture, count, relocations) in [
        ("v20_remove_int.ae", 1, 2),
        ("v20_remove_first.ae", 1, 3),
        ("v20_remove_middle.ae", 1, 2),
        ("v20_remove_last.ae", 1, 0),
        ("v20_remove_single.ae", 1, 0),
        ("v20_remove_buffer.ae", 5, 2),
        ("v20_remove_nested.ae", 5, 4),
        ("v20_remove_reuse.ae", 5, 4),
        ("v20_remove_dataset.ae", 4, 2),
        ("v20_remove_enum.ae", 3, 3),
        ("v20_remove_array.ae", 4, 1),
        ("v20_remove_return.ae", 3, 1),
        ("v20_remove_consume.ae", 3, 1),
        ("v20_remove_conditional.ae", 10, 5),
        ("v20_remove_tail.ae", 3, 0),
    ] {
        let compilation = compile_session(
            CompilationSession::discover(&program(fixture)).unwrap(),
            &[],
        )
        .unwrap();
        for (counter, expected) in [
            (None, 0),
            (Some("@aether_heap_alloc_count"), count),
            (Some("@aether_heap_free_count"), count),
            (Some("@aether_relocation_count"), relocations),
        ] {
            let llvm = counter.map_or_else(|| compilation.llvm.clone(), |counter| compilation.llvm.replace(
                "  %process_status = trunc i64 %aether_result to i32",
                &format!("  %observed_count = load i64, ptr {counter}\n  %process_status = trunc i64 %observed_count to i32"),
            ));
            let artifact = temporary("v20-count");
            ClangToolchain::default()
                .link_executable(&llvm, &artifact)
                .unwrap();
            let status = Command::new(&artifact).status().unwrap();
            let _ = fs::remove_file(artifact);
            assert_eq!(status.code(), Some(expected), "{fixture}: {counter:?}");
        }
    }
    let (_, status) = run_path(
        &module_program("v20_remove"),
        &[],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(42));
}

#[test]
fn vertical20_remove_diagnostics() {
    for source in [
        "int main(){int x=1;return remove(x,0);}",
        "int main(){Array<int>x={1};return remove(x,0);}",
        "int main(){List<int>x={1};return remove(x);}",
        "int f(ref List<int>x){return remove(*x,0);}int main(){List<int>x={1};return f(&x);}",
    ] {
        let errors = compile_source(&SourceFile::new("v20-target.ae", source), &[]).unwrap_err();
        assert_eq!(errors[0].code, "E0322", "{source}: {errors:?}");
    }
    for source in [
        "int main(){List<int>x={10,20,30,40};ref int r=&x[1];int v=remove(x,1);return *r;}",
        "int main(){List<int>x={10,20,30,40};ref mut int r=&mut x[1];int v=remove(x,1);return *r;}",
        "int main(){List<int>x={10,20,30,40};ref int r=&x[2];int v=remove(x,1);return *r;}",
        "int main(){List<int>x={10,20,30,40};ref mut int r=&mut x[2];int v=remove(x,1);return *r;}",
        "int main(){List<int>x={10,20,30,40};usize i=0;ref int r=&x[i];int v=remove(x,1);return *r;}",
        "int main(){List<int>x={10,20,30,40};usize i=1;ref int r=&x[0];int v=remove(x,i);return *r;}",
        "int main(){List<int>x={10,20,30,40};View<int>v=view(x);int r=remove(x,1);return v[0];}",
        "int main(){List<int>x={10,20,30,40};ViewMut<int>v=view_mut(x);int r=remove(x,1);return v[0];}",
        "int main(){List<Buffer<int>>x={Buffer<int>(1,1),Buffer<int>(1,2),Buffer<int>(1,3)};ref int r=&x[0][0];Buffer<int>v=remove(x,1);return *r;}",
        "int main(){List<int>x={10,20,30,40};ref mut List<int>a=&mut x;ref int r=&x[3];int v=remove(*a,1);return *r;}",
        "int main(){List<int>x={10,20,30};ref int r=&x[1];int a=remove(x,2);int b=remove(x,0);return *r;}",
    ] {
        let errors = compile_source(&SourceFile::new("v20-borrow.ae", source), &[]).unwrap_err();
        assert_eq!(errors[0].code, "E0323", "{source}: {errors:?}");
    }
    for source in [
        "int main(){List<int>x={1};int i=0;return remove(x,i);}",
        "int main(){List<int>x={1};return remove(x,true);}",
        "int main(){List<int>x={1};return remove(x,-1);}",
        "T f<T: Storable>(ref mut List<T>x,usize i){return remove(*x,i);}int main(){return 0;}",
        "T f<T: Relocatable>(ref mut List<T>x,usize i){return remove(*x,i);}int main(){return 0;}",
        "int f(ref int r,int x){return *r;}int main(){List<int>x={1,2,3};return f(&x[1],remove(x,1));}",
    ] {
        assert!(
            compile_source(&SourceFile::new("v20-type.ae", source), &[]).is_err(),
            "{source}"
        );
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical20_scopes_aliases_and_descriptor_freshness() {
    for source in [
        "int main(){List<int>x={10,20,30,40};if(true){ref int r=&x[1];if(*r!=20){return 1;}}int v=remove(x,1);return x[1]-30;}",
        "int main(){List<int>x={10,20,30,40};if(true){View<int>v=view(x);if(v[1]!=20){return 1;}}int v=remove(x,1);return x[1]-30;}",
        "int main(){List<int>x={10,20,30,40};if(true){ViewMut<int>v=view_mut(x);v[1]=21;}int v=remove(x,1);return v-21;}",
        "int main(){List<int>x={10,20,30,40};ref mut List<int>a=&mut x;ref int r=&x[0];int v=remove(*a,1);if(*r!=10){return 1;}if(length(*a)!=3){return 2;}return x[1]-30;}",
        "List<int> f(){List<int>x={10,20,30};int v=remove(x,0);return x;}int main(){List<int>x=f();if(length(x)!=2){return 1;}return x[0]-20;}",
        "int main(){List<List<int>>x={{10,20,30},{40}};int v=remove(x[0],0);if(length(x[0])!=2){return 1;}push(x[0],v);return x[0][2]-10;}",
        "int pick(ref mut int calls){*calls=*calls+1;return 1;}int main(){int calls=0;List<int>x={10,20,30};int v=remove(x,usize(pick(&mut calls)));if(calls!=1){return 1;}return v-20;}",
        "int main(){List<int>x={10,20,30};ref int r=&x[0];while(length(x)>1){int a=remove(x,1);}return *r-10;}",
        "int pick(ref mut List<int>x){return pop(*x);}int main(){List<int>x={10,20,1};int y=remove(x,usize(pick(&mut x)));if(y!=20){return 1;}return int(length(x))-1;}",
        "int main(){List<int>x={10,20,30,40};ref mut List<int>a=&mut x;int r=remove(*a,1);int p=pop(*a);int s=swap_remove(*a,0);push(*a,r);int t=remove(*a,0);if(p!=40){return 1;}if(s!=10){return 2;}if(t!=30){return 3;}return x[0]-20;}",
        "struct Owner{List<int>v;}int main(){Array<Owner>x={Owner({10,20,30,40})};int y=remove(x[0].v,1);if(length(x[0].v)!=3){return 1;}push(x[0].v,y);return x[0].v[2]-40;}",
    ] {
        let compilation = compile_source(&SourceFile::new("v20-scope.ae", source), &[]).unwrap();
        let artifact = temporary("v20-scope");
        ClangToolchain::default()
            .link_executable(&compilation.llvm, &artifact)
            .unwrap();
        let status = Command::new(&artifact).status().unwrap();
        let _ = fs::remove_file(artifact);
        assert_eq!(status.code(), Some(0), "{source}");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical20_bounds_trap_before_transaction() {
    for source in [
        "int f(ref mut List<int>x,usize i){return remove(*x,i);}int main(){List<int>x={};return f(&mut x,0);}",
        "int main(){List<int>x={1,2};return remove(x,2);}",
        "int main(){List<Buffer<int>>x={};Buffer<int>b=remove(x,0);return b[0];}",
        "int main(){List<int>x={1};usize i=18446744073709551615;return remove(x,i);}",
    ] {
        let compilation = compile_source(
            &SourceFile::new("v20-bounds.ae", source),
            &[Emit::Mir, Emit::Ssa],
        )
        .unwrap();
        for phase in [Emit::Mir, Emit::Ssa] {
            assert!(compilation.dumps[&phase].contains("IndexOutOfBounds"));
        }
        let artifact = temporary("v20-bounds");
        ClangToolchain::default()
            .link_executable(&compilation.llvm, &artifact)
            .unwrap();
        let status = Command::new(&artifact).status().unwrap();
        let _ = fs::remove_file(artifact);
        assert!(!status.success(), "{source}");
    }
}

#[test]
fn vertical20_deterministic_semantic_dumps() {
    let source = SourceFile::new(
        "v20-dump.ae",
        "int main(){List<Buffer<int>>x={Buffer<int>(1,10),Buffer<int>(1,20)};Buffer<int>b=remove(x,0);return b[0];}",
    );
    let phases = [Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let compilation = compile_source(&source, &phases).unwrap();
    assert_eq!(
        compilation.dumps,
        compile_source(&source, &phases).unwrap().dumps
    );
    for text in ["ListRemove", "StableStructuralMutation", "SuffixFrom"] {
        assert!(compilation.dumps[&Emit::Hir].contains(text), "{text}");
    }
    for phase in [Emit::Mir, Emit::Ssa] {
        for text in [
            "Take",
            "Relocate",
            "SingleSlot",
            "TailIndex",
            "IndexOutOfBounds",
            "ListSetLength",
            "destination_after: Initialized",
            "source_after: Uninitialized",
        ] {
            assert!(
                compilation.dumps[&phase].contains(text),
                "{phase:?}: {text}"
            );
        }
    }
    assert!(compilation.llvm.contains("hole Initialized"));
    assert!(compilation.llvm.contains("forward hole successor"));
    assert!(compilation.dumps[&Emit::Ssa].contains("Phi"));
    assert_eq!(
        aether_frontend::StructuralMutation::Remove.effect(),
        aether_frontend::MutationEffect::StableStructuralMutation
    );
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[allow(clippy::too_many_lines)]
fn vertical20_each_remove_preserves_storage_heap_and_relocation_counts() {
    for fixture in [
        "v20_remove_int.ae",
        "v20_remove_first.ae",
        "v20_remove_middle.ae",
        "v20_remove_last.ae",
        "v20_remove_single.ae",
        "v20_remove_buffer.ae",
        "v20_remove_nested.ae",
        "v20_remove_reuse.ae",
        "v20_remove_dataset.ae",
        "v20_remove_enum.ae",
        "v20_remove_array.ae",
        "v20_remove_return.ae",
        "v20_remove_consume.ae",
        "v20_remove_conditional.ae",
        "v20_remove_tail.ae",
    ] {
        let compilation = compile_session(
            CompilationSession::discover(&program(fixture)).unwrap(),
            &[],
        )
        .unwrap();
        let mut llvm = String::new();
        let mut pending = None;
        let mut probes = 0;
        for line in compilation.llvm.lines() {
            if line.starts_with("  %take") && line.contains("_data = extractvalue") {
                let id = line
                    .trim()
                    .strip_prefix("%take")
                    .unwrap()
                    .split('_')
                    .next()
                    .unwrap();
                let descriptor = line
                    .split_once("} ")
                    .unwrap()
                    .1
                    .strip_suffix(", 0")
                    .unwrap();
                write!(llvm, "  %probe{id}_alloc = load i64, ptr @aether_heap_alloc_count\n  %probe{id}_free = load i64, ptr @aether_heap_free_count\n  %probe{id}_cap = extractvalue {{ ptr, i64, i64 }} {descriptor}, 2\n").unwrap();
                pending = Some(id.to_string());
            }
            if line.starts_with("  %take") && line.contains("_slot = getelementptr") {
                let id = pending.as_ref().unwrap();
                let index = line.rsplit_once("i64 ").unwrap().1;
                writeln!(
                    llvm,
                    "  %probe{id}_reloc = load i64, ptr @aether_relocation_count"
                )
                .unwrap();
                writeln!(llvm, "  %probe{id}_index = add i64 {index}, 0").unwrap();
            }
            llvm.push_str(line);
            llvm.push('\n');
            if line.contains("; commit initialized prefix") {
                let id = pending.take().expect("Take precedes every length commit");
                let length_pointer = line
                    .split_once("ptr ")
                    .unwrap()
                    .1
                    .split(" ;")
                    .next()
                    .unwrap();
                writeln!(llvm, "  call void @v20_assert_pop(ptr %take{id}_data, i64 %probe{id}_cap, i64 %probe{id}_alloc, i64 %probe{id}_free, i64 %probe{id}_reloc, i64 %probe{id}_index, ptr {length_pointer})").unwrap();
                probes += 1;
            }
        }
        assert!(probes > 0);
        assert!(pending.is_none());
        llvm.push_str(r"
define internal void @v20_assert_pop(ptr %old_data, i64 %old_cap, i64 %old_alloc, i64 %old_free, i64 %old_reloc, i64 %removed_index, ptr %length_field) {
entry:
  %data_field = getelementptr i64, ptr %length_field, i64 -1
  %capacity_field = getelementptr i64, ptr %length_field, i64 1
  %data = load ptr, ptr %data_field
  %capacity = load i64, ptr %capacity_field
  %allocs = load i64, ptr @aether_heap_alloc_count
  %frees = load i64, ptr @aether_heap_free_count
  %same_data = icmp eq ptr %data, %old_data
  %same_capacity = icmp eq i64 %capacity, %old_cap
  %same_allocs = icmp eq i64 %allocs, %old_alloc
  %same_frees = icmp eq i64 %frees, %old_free
  %storage_ok = and i1 %same_data, %same_capacity
  %heap_ok = and i1 %same_allocs, %same_frees
  %new_length = load i64, ptr %length_field
  %expected_reloc = sub i64 %new_length, %removed_index
  %relocs = load i64, ptr @aether_relocation_count
  %delta_reloc = sub i64 %relocs, %old_reloc
  %reloc_ok = icmp eq i64 %delta_reloc, %expected_reloc
  %stable = and i1 %storage_ok, %heap_ok
  %ok = and i1 %stable, %reloc_ok
  br i1 %ok, label %done, label %failed
failed:
  call void @llvm.trap()
  unreachable
done:
  ret void
}
");
        let artifact = temporary("v20-stable-storage");
        ClangToolchain::default()
            .link_executable(&llvm, &artifact)
            .unwrap();
        let status = Command::new(&artifact).status().unwrap();
        let _ = fs::remove_file(artifact);
        assert_eq!(status.code(), Some(0), "{fixture}");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical20_drop_order_uses_reverse_final_indices() {
    let compilation = compile_session(
        CompilationSession::discover(&program("v20_remove_buffer.ae")).unwrap(),
        &[],
    )
    .unwrap();
    let mut llvm = compilation.llvm.replace(
        "call void @free(ptr %ptr)",
        "call void @v20_note_free(ptr %ptr, i64 %size)\n  call void @free(ptr %ptr)",
    ).replace(
        "  %process_status = trunc i64 %aether_result to i32",
        "  %trace = load i64, ptr @v20_drop_trace\n  %ordered = icmp eq i64 %trace, 20403010\n  %process_status = select i1 %ordered, i32 0, i32 99",
    );
    // The extracted 20 drops first. The final List [10,30,40] drops 40,30,10.
    // Only the four one-int Buffer allocations have size 8.
    llvm.push_str(
        r"
@v20_drop_trace = internal global i64 0
define internal void @v20_note_free(ptr %data, i64 %size) {
entry:
  %buffer = icmp eq i64 %size, 8
  br i1 %buffer, label %record, label %done
record:
  %payload = load i64, ptr %data
  %old = load i64, ptr @v20_drop_trace
  %shift = mul i64 %old, 100
  %next = add i64 %shift, %payload
  store i64 %next, ptr @v20_drop_trace
  br label %done
done:
  ret void
}
",
    );
    let artifact = temporary("v20-drop-order");
    ClangToolchain::default()
        .link_executable(&llvm, &artifact)
        .unwrap();
    let status = Command::new(&artifact).status().unwrap();
    let _ = fs::remove_file(artifact);
    assert_eq!(status.code(), Some(0));
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical20_mir_rejects_corrupt_shift_transactions() {
    use aether_middle::{
        BinaryOp, BlockId, ElementInitialization, Operand, Rvalue, Terminator, TrapKind, lower_hir,
        verify_mir,
    };
    let source = SourceFile::new(
        "v20_corrupt.ae",
        "int main(){List<Buffer<int>>other={Buffer<int>(1,9)};List<Buffer<int>>x={Buffer<int>(1,10),Buffer<int>(1,20),Buffer<int>(1,30),Buffer<int>(1,40)};Buffer<int>b=remove(x,1);return b[0];}",
    );
    let raw = lower_hir(analyze(parse_source(&source).unwrap()).unwrap());
    verify_mir(raw.clone()).unwrap();
    let f = &raw.functions[0];
    let transaction = f
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.value, Rvalue::Take { .. }))
        })
        .unwrap();
    let body = f
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.value, Rvalue::Relocate { .. }))
        })
        .unwrap();
    let commit = f
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.value, Rvalue::ListSetLength { .. }))
        })
        .unwrap();
    let Terminator::Goto(header_id) = f.blocks[transaction].terminator.as_ref().unwrap() else {
        panic!()
    };
    let header = header_id.0 as usize;
    let guard = f.blocks.iter().position(|b| matches!(&b.terminator, Some(Terminator::Branch {then_block,..}) if then_block.0 as usize == transaction)).unwrap();
    let Rvalue::Take { slot, .. } = &f.blocks[transaction].instructions[1].value else {
        panic!()
    };
    let removed = slot.clone();
    let Rvalue::Relocate {
        source,
        destination,
        ..
    } = &f.blocks[body].instructions[1].value
    else {
        panic!()
    };
    let shifted = source.clone();
    let hole = destination.index.clone();
    let Rvalue::TailIndex { length: old_length } = &f.blocks[transaction].instructions[0].value
    else {
        panic!()
    };
    let old_length = old_length.clone();
    let Rvalue::ListSetLength { length: tail, .. } = &f.blocks[commit].instructions[0].value else {
        panic!()
    };
    let tail = tail.clone();
    let wrong_root = f.blocks[0]
        .instructions
        .iter()
        .find(|i| matches!(i.value, Rvalue::ListInit { .. }))
        .unwrap()
        .destination
        .clone();
    for mutation in 0..40 {
        let mut corrupt = raw.clone();
        let blocks = &mut corrupt.functions[0].blocks;
        match mutation {
            0 => {
                if let Rvalue::Take { slot, .. } = &mut blocks[transaction].instructions[1].value {
                    slot.root = wrong_root.clone();
                }
            }
            1 => {
                if let Rvalue::Take { slot, .. } = &mut blocks[transaction].instructions[1].value {
                    slot.index = tail.clone();
                }
            }
            2 => {
                if let Rvalue::Take { state, .. } = &mut blocks[transaction].instructions[1].value {
                    state.before = ElementInitialization::Uninitialized;
                }
            }
            3 => blocks[transaction].instructions[2].value = Rvalue::Use(tail.clone()),
            4 => {
                blocks[transaction].instructions[2].value = Rvalue::Use(Operand::Int {
                    value: 0,
                    ty: aether_frontend::TypeId::USIZE,
                });
            }
            5 => blocks[body].instructions[0].value = Rvalue::HoleNext { hole: tail.clone() },
            6 => {
                if let Rvalue::Relocate { source, .. } = &mut blocks[body].instructions[1].value {
                    source.index = hole.clone();
                }
            }
            7 => {
                if let Rvalue::Relocate { destination, .. } =
                    &mut blocks[body].instructions[1].value
                {
                    destination.index = shifted.index.clone();
                }
            }
            8 => {
                if let Rvalue::Relocate {
                    source,
                    destination,
                    ..
                } = &mut blocks[body].instructions[1].value
                {
                    std::mem::swap(source, destination);
                }
            }
            9 => {
                if let Rvalue::Relocate { source, .. } = &mut blocks[body].instructions[1].value {
                    source.root = wrong_root.clone();
                }
            }
            10 => {
                if let Rvalue::Relocate { relocation, .. } = &mut blocks[body].instructions[1].value
                {
                    relocation.source_after = ElementInitialization::Initialized;
                }
            }
            11 => {
                if let Rvalue::Relocate { relocation, .. } = &mut blocks[body].instructions[1].value
                {
                    relocation.destination_before = ElementInitialization::Initialized;
                }
            }
            12 => {
                if let Rvalue::Relocate { relocation, .. } = &mut blocks[body].instructions[1].value
                {
                    relocation.destination_after = ElementInitialization::Uninitialized;
                }
            }
            13 => {
                if let Rvalue::Relocate { relocation, .. } = &mut blocks[body].instructions[1].value
                {
                    relocation.non_trapping = false;
                }
            }
            14 => {
                if let Rvalue::Relocate { relocation, .. } = &mut blocks[body].instructions[1].value
                {
                    relocation.increasing_order = false;
                }
            }
            15 => {
                blocks[body].instructions.remove(1);
            }
            16 => {
                let duplicate = blocks[body].instructions[1].clone();
                blocks[body].instructions.insert(2, duplicate);
            }
            17 => {
                blocks[body].instructions[0].value = Rvalue::Binary {
                    op: BinaryOp::AddIntegerChecked,
                    left: hole.clone(),
                    right: Operand::Int {
                        value: 1,
                        ty: aether_frontend::TypeId::USIZE,
                    },
                    trap: Some(TrapKind::IntegerOverflow),
                    secondary_trap: None,
                }
            }
            18 => blocks[body].instructions[2].value = Rvalue::Use(hole.clone()),
            19 => blocks[body].instructions[2].value = Rvalue::Use(tail.clone()),
            20 => {
                if let Rvalue::Binary { op, .. } = &mut blocks[header].instructions[0].value {
                    *op = BinaryOp::LessEqual;
                }
            }
            21 => {
                if let Rvalue::Binary { left, .. } = &mut blocks[header].instructions[0].value {
                    *left = tail.clone();
                }
            }
            22 => {
                if let Terminator::Branch {
                    then_block,
                    else_block,
                    ..
                } = blocks[header].terminator.as_mut().unwrap()
                {
                    std::mem::swap(then_block, else_block);
                }
            }
            23 => {
                blocks[body].terminator =
                    Some(Terminator::Goto(BlockId(u32::try_from(commit).unwrap())));
            }
            24 => {
                if let Rvalue::ListSetLength { length, .. } =
                    &mut blocks[commit].instructions[0].value
                {
                    *length = old_length.clone();
                }
            }
            25 => {
                let early = blocks[commit].instructions.remove(0);
                blocks[transaction].instructions.push(early);
            }
            26 => {
                let mut drop = blocks[body].instructions[1].clone();
                drop.value = Rvalue::Drop {
                    owner: removed.root.clone(),
                };
                blocks[body].instructions.insert(2, drop);
            }
            27 => {
                let n = blocks[guard].instructions.len();
                if let Rvalue::ListLength { source } = &mut blocks[guard].instructions[n - 2].value
                {
                    *source = wrong_root.clone();
                }
            }
            28 => {
                let n = blocks[guard].instructions.len();
                if let Rvalue::Binary { right, .. } = &mut blocks[guard].instructions[n - 1].value {
                    *right = removed.index.clone();
                }
            }
            29 => {
                let n = blocks[guard].instructions.len();
                let stale = blocks[guard].instructions[n - 3].clone();
                blocks[guard].instructions.insert(n - 1, stale);
            }
            30 => {
                let early = blocks[transaction].instructions.remove(0);
                blocks[guard].instructions.push(early);
            }
            31 => {
                blocks[body].terminator = Some(Terminator::Trap(TrapKind::IndexOutOfBounds));
            }
            32 => {
                let escape = blocks[body].instructions[0].clone();
                blocks[commit].instructions.insert(1, escape);
            }
            33 => {
                if let Terminator::Branch { then_block, .. } =
                    blocks[guard].terminator.as_mut().unwrap()
                {
                    *then_block = BlockId(u32::try_from(body).unwrap());
                }
            }
            34 => {
                if let Rvalue::Take { state, .. } = &mut blocks[transaction].instructions[1].value {
                    state.after = ElementInitialization::Initialized;
                }
            }
            35 => {
                if let Rvalue::Relocate { source, .. } = &mut blocks[body].instructions[1].value {
                    source.type_id = aether_frontend::TypeId::USIZE;
                }
            }
            36 => {
                let duplicate = blocks[transaction].instructions[1].clone();
                blocks[transaction].instructions.insert(2, duplicate);
            }
            37 => {
                if let Rvalue::ListSetLength { source, .. } =
                    &mut blocks[commit].instructions[0].value
                {
                    *source = wrong_root.clone();
                }
            }
            38 => blocks[body].instructions.swap(1, 2),
            39 => {
                blocks[body].instructions[2].value = Rvalue::HoleNext {
                    hole: shifted.index.clone(),
                }
            }
            _ => unreachable!(),
        }
        let errors =
            verify_mir(corrupt).expect_err(&format!("accepted shift corruption {mutation}"));
        assert_eq!(
            errors[0].phase,
            aether_frontend::Phase::Mir,
            "mutation {mutation}: {errors:?}"
        );
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical20_ssa_rejects_corrupt_shift_transactions() {
    use aether_middle::{
        BinaryOp, BlockId, ElementInitialization, SsaOp, SsaOperand, SsaTerminator, TrapKind,
        build_ssa, lower_hir, verify_mir, verify_ssa,
    };
    let source = SourceFile::new(
        "v20_corrupt.ae",
        "int main(){List<Buffer<int>>other={Buffer<int>(1,9)};List<Buffer<int>>x={Buffer<int>(1,10),Buffer<int>(1,20),Buffer<int>(1,30),Buffer<int>(1,40)};Buffer<int>b=remove(x,1);return b[0];}",
    );
    let raw = build_ssa(
        &verify_mir(lower_hir(analyze(parse_source(&source).unwrap()).unwrap())).unwrap(),
    );
    verify_ssa(raw.clone()).unwrap();
    let f = &raw.functions[0];
    let transaction = f
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.op, SsaOp::Take { .. }))
        })
        .unwrap();
    let body = f
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.op, SsaOp::Relocate { .. }))
        })
        .unwrap();
    let commit = f
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.op, SsaOp::ListSetLength { .. }))
        })
        .unwrap();
    let SsaTerminator::Goto(header_id) = &f.blocks[transaction].terminator else {
        panic!()
    };
    let header = header_id.0 as usize;
    let guard = f.blocks.iter().position(|b| matches!(&b.terminator, SsaTerminator::Branch {then_block,..} if then_block.0 as usize == transaction)).unwrap();
    let SsaOp::Take { slot, .. } = &f.blocks[transaction].instructions[1].op else {
        panic!()
    };
    let removed = slot.clone();
    let SsaOp::Relocate {
        source,
        destination,
        ..
    } = &f.blocks[body].instructions[1].op
    else {
        panic!()
    };
    let shifted = source.clone();
    let hole = destination.index.clone();
    let SsaOp::TailIndex { length: old_length } = &f.blocks[transaction].instructions[0].op else {
        panic!()
    };
    let old_length = old_length.clone();
    let SsaOp::ListSetLength { length: tail, .. } = &f.blocks[commit].instructions[0].op else {
        panic!()
    };
    let tail = tail.clone();
    let wrong_root = aether_middle::SsaPlace {
        base: aether_middle::SsaPlaceBase::Value(SsaOperand::Value(
            f.blocks[0]
                .instructions
                .iter()
                .find(|i| matches!(i.op, SsaOp::ListInit { .. }))
                .unwrap()
                .result,
        )),
        projections: vec![],
    };
    for mutation in 0..40 {
        let mut corrupt = raw.clone();
        let blocks = &mut corrupt.functions[0].blocks;
        match mutation {
            0 => {
                if let SsaOp::Take { slot, .. } = &mut blocks[transaction].instructions[1].op {
                    slot.root = wrong_root.clone();
                }
            }
            1 => {
                if let SsaOp::Take { slot, .. } = &mut blocks[transaction].instructions[1].op {
                    slot.index = tail.clone();
                }
            }
            2 => {
                if let SsaOp::Take { state, .. } = &mut blocks[transaction].instructions[1].op {
                    state.before = ElementInitialization::Uninitialized;
                }
            }
            3 => blocks[transaction].instructions[2].op = SsaOp::Use(tail.clone()),
            4 => {
                blocks[transaction].instructions[2].op = SsaOp::Use(SsaOperand::Int {
                    value: 0,
                    ty: aether_frontend::TypeId::USIZE,
                });
            }
            5 => blocks[body].instructions[0].op = SsaOp::HoleNext { hole: tail.clone() },
            6 => {
                if let SsaOp::Relocate { source, .. } = &mut blocks[body].instructions[1].op {
                    source.index = hole.clone();
                }
            }
            7 => {
                if let SsaOp::Relocate { destination, .. } = &mut blocks[body].instructions[1].op {
                    destination.index = shifted.index.clone();
                }
            }
            8 => {
                if let SsaOp::Relocate {
                    source,
                    destination,
                    ..
                } = &mut blocks[body].instructions[1].op
                {
                    std::mem::swap(source, destination);
                }
            }
            9 => {
                if let SsaOp::Relocate { source, .. } = &mut blocks[body].instructions[1].op {
                    source.root = wrong_root.clone();
                }
            }
            10 => {
                if let SsaOp::Relocate { relocation, .. } = &mut blocks[body].instructions[1].op {
                    relocation.source_after = ElementInitialization::Initialized;
                }
            }
            11 => {
                if let SsaOp::Relocate { relocation, .. } = &mut blocks[body].instructions[1].op {
                    relocation.destination_before = ElementInitialization::Initialized;
                }
            }
            12 => {
                if let SsaOp::Relocate { relocation, .. } = &mut blocks[body].instructions[1].op {
                    relocation.destination_after = ElementInitialization::Uninitialized;
                }
            }
            13 => {
                if let SsaOp::Relocate { relocation, .. } = &mut blocks[body].instructions[1].op {
                    relocation.non_trapping = false;
                }
            }
            14 => {
                if let SsaOp::Relocate { relocation, .. } = &mut blocks[body].instructions[1].op {
                    relocation.increasing_order = false;
                }
            }
            15 => {
                blocks[body].instructions.remove(1);
            }
            16 => {
                let duplicate = blocks[body].instructions[1].clone();
                blocks[body].instructions.insert(2, duplicate);
            }
            17 => {
                blocks[body].instructions[0].op = SsaOp::Binary {
                    op: BinaryOp::AddIntegerChecked,
                    left: hole.clone(),
                    right: SsaOperand::Int {
                        value: 1,
                        ty: aether_frontend::TypeId::USIZE,
                    },
                    trap: Some(TrapKind::IntegerOverflow),
                    secondary_trap: None,
                }
            }
            18 => blocks[body].instructions[2].op = SsaOp::Use(hole.clone()),
            19 => blocks[body].instructions[2].op = SsaOp::Use(tail.clone()),
            20 => {
                if let SsaOp::Binary { op, .. } = &mut blocks[header].instructions[0].op {
                    *op = BinaryOp::LessEqual;
                }
            }
            21 => {
                if let SsaOp::Binary { left, .. } = &mut blocks[header].instructions[0].op {
                    *left = tail.clone();
                }
            }
            22 => {
                if let SsaTerminator::Branch {
                    then_block,
                    else_block,
                    ..
                } = &mut blocks[header].terminator
                {
                    std::mem::swap(then_block, else_block);
                }
            }
            23 => {
                blocks[body].terminator =
                    SsaTerminator::Goto(BlockId(u32::try_from(commit).unwrap()));
            }
            24 => {
                if let SsaOp::ListSetLength { length, .. } = &mut blocks[commit].instructions[0].op
                {
                    *length = old_length.clone();
                }
            }
            25 => {
                let early = blocks[commit].instructions.remove(0);
                blocks[transaction].instructions.push(early);
            }
            26 => {
                let mut drop = blocks[body].instructions[1].clone();
                drop.op = SsaOp::Drop {
                    owner: removed.root.clone(),
                };
                blocks[body].instructions.insert(2, drop);
            }
            27 => {
                let n = blocks[guard].instructions.len();
                if let SsaOp::ListLength { source } = &mut blocks[guard].instructions[n - 2].op {
                    *source = wrong_root.clone();
                }
            }
            28 => {
                let n = blocks[guard].instructions.len();
                if let SsaOp::Binary { right, .. } = &mut blocks[guard].instructions[n - 1].op {
                    *right = removed.index.clone();
                }
            }
            29 => {
                let n = blocks[guard].instructions.len();
                let stale = blocks[guard].instructions[n - 3].clone();
                blocks[guard].instructions.insert(n - 1, stale);
            }
            30 => {
                let early = blocks[transaction].instructions.remove(0);
                blocks[guard].instructions.push(early);
            }
            31 => {
                blocks[body].terminator = SsaTerminator::Trap(TrapKind::IndexOutOfBounds);
            }
            32 => {
                let escape = blocks[body].instructions[0].clone();
                blocks[commit].instructions.insert(1, escape);
            }
            33 => {
                if let SsaTerminator::Branch { then_block, .. } = &mut blocks[guard].terminator {
                    *then_block = BlockId(u32::try_from(body).unwrap());
                }
            }
            34 => {
                if let SsaOp::Take { state, .. } = &mut blocks[transaction].instructions[1].op {
                    state.after = ElementInitialization::Initialized;
                }
            }
            35 => {
                if let SsaOp::Relocate { source, .. } = &mut blocks[body].instructions[1].op {
                    source.type_id = aether_frontend::TypeId::USIZE;
                }
            }
            36 => {
                let duplicate = blocks[transaction].instructions[1].clone();
                blocks[transaction].instructions.insert(2, duplicate);
            }
            37 => {
                if let SsaOp::ListSetLength { source, .. } = &mut blocks[commit].instructions[0].op
                {
                    *source = wrong_root.clone();
                }
            }
            38 => blocks[body].instructions.swap(1, 2),
            39 => {
                blocks[body].instructions[2].op = SsaOp::HoleNext {
                    hole: shifted.index.clone(),
                }
            }
            _ => unreachable!(),
        }
        let errors =
            verify_ssa(corrupt).expect_err(&format!("accepted shift corruption {mutation}"));
        assert_eq!(
            errors[0].phase,
            aether_frontend::Phase::Ssa,
            "mutation {mutation}: {errors:?}"
        );
    }
}

#[test]
fn vertical20_ssa_rejects_hole_and_owner_phi_corruption() {
    use aether_middle::{SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};
    let source = SourceFile::new(
        "v20_phi.ae",
        "int main(){List<Buffer<int>>x={Buffer<int>(1,10),Buffer<int>(1,20),Buffer<int>(1,30)};Buffer<int>b=remove(x,0);return b[0];}",
    );
    let raw = build_ssa(
        &verify_mir(lower_hir(analyze(parse_source(&source).unwrap()).unwrap())).unwrap(),
    );
    verify_ssa(raw.clone()).unwrap();
    let f = &raw.functions[0];
    let header = f.blocks.iter().position(|b| !b.phis.is_empty()).unwrap();
    let tail = f
        .blocks
        .iter()
        .flat_map(|b| &b.instructions)
        .find(|i| matches!(i.op, SsaOp::TailIndex { .. }))
        .unwrap()
        .result;
    let take = f
        .blocks
        .iter()
        .flat_map(|b| &b.instructions)
        .find(|i| matches!(i.op, SsaOp::Take { .. }))
        .unwrap();
    let commit = f
        .blocks
        .iter()
        .position(|b| {
            b.instructions
                .iter()
                .any(|i| matches!(i.op, SsaOp::ListSetLength { .. }))
        })
        .unwrap();
    let fresh = aether_middle::ValueId(
        f.blocks
            .iter()
            .flat_map(|b| {
                b.instructions
                    .iter()
                    .map(|i| i.result.0)
                    .chain(b.phis.iter().map(|p| p.result.0))
            })
            .max()
            .unwrap()
            + 1,
    );
    for mutation in 0..5 {
        let mut corrupt = raw.clone();
        let blocks = &mut corrupt.functions[0].blocks;
        match mutation {
            0 => blocks[header].phis[0].incoming[0].1 = tail,
            1 => blocks[header].phis[0].incoming[1].1 = tail,
            2 => {
                blocks[header].phis.clear();
            }
            3 => {
                let mut duplicate = blocks[header].phis[0].clone();
                duplicate.result = fresh;
                duplicate.local.0 += 1;
                blocks[header].phis.push(duplicate);
            }
            4 => {
                let mut owner_phi = blocks[header].phis[0].clone();
                owner_phi.result = fresh;
                owner_phi.ty = take.ty;
                owner_phi.incoming = vec![(blocks[header].id, take.result)];
                blocks[commit].phis.push(owner_phi);
            }
            _ => unreachable!(),
        }
        let errors = verify_ssa(corrupt).expect_err(&format!("accepted phi corruption {mutation}"));
        if mutation != 2 {
            assert!(
                errors[0].message.contains("invalid remove transaction"),
                "mutation {mutation}: {errors:?}"
            );
        }
    }
}

#[test]
fn vertical20_projected_descriptor_is_resolved_before_hole_exists() {
    let source = SourceFile::new(
        "v20_projection.ae",
        "int main(){List<List<Buffer<int>>>x={{Buffer<int>(1,10),Buffer<int>(1,20),Buffer<int>(1,30)}};Buffer<int>b=remove(x[0],0);return b[0];}",
    );
    let compilation = compile_source(&source, &[Emit::Mir, Emit::Ssa]).unwrap();
    // Nested bounds/address computation precedes Take. From the successor through
    // commit there are only stable descriptor loads, GEPs and non-trapping glue.
    let suffix = compilation
        .llvm
        .split_once("; forward hole successor")
        .unwrap()
        .1;
    let transaction = suffix.split_once("; commit initialized prefix").unwrap().0;
    for forbidden in [
        "@aether_list_index_",
        "@aether_index_",
        "@malloc",
        "@free",
        "@llvm.trap",
        "@aether_drop_",
    ] {
        assert!(!transaction.contains(forbidden), "{forbidden}");
    }
    assert!(compilation.dumps[&Emit::Mir].contains("Borrow"));
}

#[test]
fn vertical21_orientation_identity_and_symbolic_storage() {
    use aether_frontend::{
        GenericOwner, GenericParamId, IndexSemantics, Orientation, TypeArena, TypeId,
    };
    let mut types = TypeArena::new();
    let row = types.intern_vector(TypeId::INT64, Orientation::Row);
    let column = types.intern_vector(TypeId::INT64, Orientation::Column);
    assert_eq!(row, types.intern_vector(TypeId::INT64, Orientation::Row));
    assert_ne!(row, column);
    assert_ne!(row, types.intern_array(TypeId::INT64));
    assert_eq!(types.index_semantics(row), Some(IndexSemantics::OneBased));
    assert_eq!(
        types.index_semantics(column),
        Some(IndexSemantics::OneBased)
    );
    let properties = types.properties(row).unwrap();
    assert!(!properties.is_copy && properties.needs_drop && properties.is_storable);
    let parameter = GenericParamId {
        owner: GenericOwner::Function(0),
        index: 0,
    };
    types.register_generic_capabilities(parameter, "T".into(), [Capability::Storable]);
    let element = types.intern(TypeData::GenericParam(parameter));
    assert!(!types.guarantees_relocatable(element));
    assert!(types.is_admitted_vector_element(element));
    let symbolic = types.intern_vector(element, Orientation::Row);
    let substitution = aether_frontend::Substitution::new([parameter], [TypeId::INT64]);
    assert_eq!(types.substitute(symbolic, &substitution).unwrap(), row);
    assert_eq!(
        types.substituted_existing(symbolic, &substitution).unwrap(),
        row
    );
    assert_eq!(
        types.index_semantics(symbolic),
        Some(IndexSemantics::OneBased)
    );
}

#[test]
fn vertical21_deterministic_mathematical_ir() {
    let source = SourceFile::new(
        "v21.ae",
        fs::read_to_string(program("v21_vector_row.ae")).unwrap(),
    );
    let phases = [Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let first = compile_source(&source, &phases).unwrap();
    assert_eq!(first.dumps, compile_source(&source, &phases).unwrap().dumps);
    assert!(first.dumps[&Emit::Ast].contains("MathematicalLiteral"));
    assert!(!first.dumps[&Emit::Ast].contains("CollectionLiteral"));
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &first.dumps[&phase];
        for expected in ["VectorInit", "VectorDimension", "OneBased"] {
            assert!(dump.contains(expected), "{phase:?}: {expected}");
        }
        assert!(!dump.contains("ArrayInit"));
        assert!(!dump.contains("ArrayLength"));
    }
    assert!(first.dumps[&Emit::Hir].contains("Vector<int64, Row>"));
    assert!(first.dumps[&Emit::Hir].contains("element_requirements=[Storable]"));
    let helper = first
        .llvm
        .split("define internal ptr @aether_vector_index_")
        .nth(1)
        .unwrap()
        .split("\n}")
        .next()
        .unwrap();
    let lower = helper.find("icmp uge i64 %index, 1").unwrap();
    let upper = helper.find("icmp ule i64 %index, %length").unwrap();
    let valid = helper.find("\nvalid:").unwrap();
    let offset = helper.find("%offset = sub i64 %index, 1").unwrap();
    let gep = helper.find("getelementptr inbounds").unwrap();
    assert!(lower < upper && upper < valid && valid < offset && offset < gep);
    assert!(helper.contains("br i1 %lower, label %upper_bound, label %trap_index_out_of_bounds"));
    assert!(helper.contains("br i1 %in_bounds, label %valid, label %trap_index_out_of_bounds"));
    assert!(helper.contains("ptr %data, i64 %offset"));
}

#[test]
fn vertical21_diagnostics_and_matrix_reservation() {
    for text in [
        "int main(){Vector<int,Row> v=[1,2];return v[0];}",
        "int main(){Vector<int,Column> v=[1,2];return v[3];}",
        "int main(){Vector<int,Row> v=[1];int i=1;return v[i];}",
        "int main(){Vector<int,Row> v=[1];return v[-1];}",
        "int main(){Vector<int,Row> v=[1];return v[true];}",
        "int main(){Vector<int,Row> r=[1];Vector<int,Column> c=r;return 0;}",
        "int main(){Vector<int,Column> c=[1];Vector<int,Row> r=c;return 0;}",
        "int main(){Vector<int,Diagonal> v=[];return 0;}",
        "int main(){Vector<int,ref Row> v=[];return 0;}",
        "int main(){Vector<int,Row<int>> v=[];return 0;}",
        "int main(){Vector<int> v=[];return 0;}",
        "int main(){Vector<int,Row,int> v=[];return 0;}",
        "int main(){Vector v=[];return 0;}",
        "Vector<T,Row> bad<T>(T x){return [x];}int main(){return 0;}",
        "Vector<T,Row> bad<T:Copy>(T x){return [x];}int main(){return 0;}",
        "int main(){Vector<ref int,Row> v=[];return 0;}",
        "int main(){Vector<int,Row> v={};return 0;}",
        "int main(){Array<int> v=[];return 0;}",
        "int main(){List<int> v=[];return 0;}",
        "int main(){auto v=[1,2];return 0;}",
        "int main(){return [1,2];}",
        "T id<T>(T x){return x;}int main(){return id([1,2]);}",
        "int main(){Vector<int,Row> v=[1];ref int r=&v[1];Vector<int,Row> moved=v;return *r;}",
        "int main(){Vector<int,Row> v=[1];ref mut int r=&mut v[1];Vector<int,Row> moved=v;return *r;}",
        "int main(){Vector<Buffer<int>,Row> v=[Buffer<int>(1,1)];Buffer<int> x=v[1];return 0;}",
        "int main(){Vector<Buffer<int>,Row> v=[Buffer<int>(1,1)];v[1]=Buffer<int>(1,2);return 0;}",
        "int main(){Vector<int,Row> v=[];View<int> x=view(v);return 0;}",
        "int main(){Vector<int,Row> v=[];ViewMut<int> x=view_mut(v);return 0;}",
        "int main(){Array<int> a={1};Vector<int,Row> v=a;return 0;}",
        "int main(){Vector<int,Row> v=[1];Array<int> a=v;return 0;}",
        "int main(){Vector<int,Row> v=[1];push(v,2);return 0;}",
        "int main(){Vector<int,Row> v=[1];reserve(v,2);return 0;}",
        "int main(){Vector<int,Row> v=[1];return pop(v);}",
        "int main(){Vector<int,Row> v=[1];return remove(v,0);}",
        "int main(){Vector<int,Row> v=[1];return swap_remove(v,0);}",
        "int main(){Vector<int,Row> v=[1];return int(length(v));}",
        "int main(){Vector<int,Row> v=[1];return int(capacity(v));}",
        "int main(){Array<int> v={1};return int(dimension(v));}",
        "int main(){Vector<int,Row> v=[1];return int(dimension(v,v));}",
        "int main(){Vector<int,Row> v=[1];return int(dimension<int>(v));}",
        "int main(){Vector<int,Row> v=[1];Vector<int,Row> w=v*v;return 0;}",
        "int main(){Vector<bool,Row> v=[1];return 0;}",
        "int main(){Vector<int,Row> v=[true];return 0;}",
        "int main(){Vector<int,Row> v=[1];Vector<int,Row> w=v;return v[1];}",
        "struct Vector { int x; } int main(){return 0;}",
    ] {
        let errors = compile_source(&SourceFile::new("v21-error.ae", text), &[]).expect_err(text);
        assert!(errors[0].span.is_some(), "{text}");
    }
    let errors = compile_source(
        &SourceFile::new(
            "matrix.ae",
            "int main(){Vector<int,Row> v=[1,2;3,4];return 0;}",
        ),
        &[],
    )
    .unwrap_err();
    assert_eq!(errors[0].code, "E0332");
    for (source, expected) in [
        ("int main(){Vector<int,Bad> v=[];return 0;}", "E0324"),
        (
            "Vector<T,Row> bad<T>(T x){return [x];}int main(){return 0;}",
            "E0325",
        ),
        ("int main(){Array<int> v=[];return 0;}", "E0326"),
        ("int main(){return int(dimension(1));}", "E0270"),
    ] {
        assert_eq!(
            compile_source(&SourceFile::new("error.ae", source), &[]).unwrap_err()[0].code,
            expected
        );
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical21_native_values_and_exact_heap_counts() {
    for (fixture, count) in [
        ("empty_row", 0),
        ("empty_column", 0),
        ("row", 1),
        ("column", 1),
        ("widening", 1),
        ("refs", 1),
        ("loop", 1),
        ("move", 1),
        ("return", 1),
        ("struct", 1),
        ("enum", 1),
        ("generic", 2),
        ("owning", 3),
        ("conditional", 4),
        ("nested", 10),
        ("non_numeric", 3),
        ("index_once", 1),
    ] {
        let compilation = compile_session(
            CompilationSession::discover(&program(&format!("v21_vector_{fixture}.ae"))).unwrap(),
            &[],
        )
        .unwrap();
        for (counter, expected) in [
            (None, 0),
            (Some("@aether_heap_alloc_count"), count),
            (Some("@aether_heap_free_count"), count),
        ] {
            let llvm=counter.map_or_else(||compilation.llvm.clone(),|counter|compilation.llvm.replace(
                "  %process_status = trunc i64 %aether_result to i32",
                &format!("  %observed = load i64, ptr {counter}\n  %process_status = trunc i64 %observed to i32")));
            let artifact = temporary("v21-count");
            ClangToolchain::default()
                .link_executable(&llvm, &artifact)
                .unwrap();
            let status = Command::new(&artifact).status().unwrap();
            let _ = fs::remove_file(artifact);
            assert_eq!(status.code(), Some(expected), "{fixture}: {counter:?}");
        }
    }
    let (_, status) = run_path(
        &module_program("v21_vectors"),
        &[],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(0));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical21_runtime_bounds_read_write_and_borrow() {
    use std::os::unix::process::ExitStatusExt;
    for orientation in ["Row", "Column"] {
        for (literal, index) in [
            ("[10,20]", "0"),
            ("[10,20]", "3"),
            ("[10,20]", "18446744073709551615"),
            ("[]", "0"),
            ("[]", "1"),
        ] {
            for operation in [
                "return v[i];",
                "v[i]=42;return 0;",
                "ref int r=&v[i];return *r;",
                "ref mut int r=&mut v[i];*r=42;return 0;",
            ] {
                let source = format!(
                    "int main(){{Vector<int,{orientation}> v={literal};usize i={index};{operation}}}"
                );
                let compilation =
                    compile_source(&SourceFile::new("v21-trap.ae", source), &[]).unwrap();
                let artifact = temporary("v21-trap");
                ClangToolchain::default()
                    .link_executable(&compilation.llvm, &artifact)
                    .unwrap();
                let status = Command::new(&artifact).status().unwrap();
                let _ = fs::remove_file(artifact);
                assert_eq!(
                    status.signal(),
                    Some(4),
                    "{orientation} {literal} {index} {operation}"
                );
            }
        }
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical21_collections_keep_zero_based_indices() {
    let text = "int main(){Array<int> a={10,20};List<int> l={30,40};Vector<int,Row> r=[50,60];Vector<int,Column> c=[70,80];a[0]=11;l[0]=31;if(a[0]+l[0]+r[1]+c[1]!=162){return 1;}return a[1]+l[1]+r[2]+c[2]-200;}";
    let compiled = compile_source(&SourceFile::new("bases.ae", text), &[Emit::Ssa]).unwrap();
    assert!(compiled.dumps[&Emit::Ssa].contains("ZeroBased"));
    assert!(compiled.dumps[&Emit::Ssa].contains("OneBased"));
    let artifact = temporary("v21-bases");
    ClangToolchain::default()
        .link_executable(&compiled.llvm, &artifact)
        .unwrap();
    let status = Command::new(&artifact).status().unwrap();
    let _ = fs::remove_file(artifact);
    assert_eq!(status.code(), Some(0));
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical21_verifiers_reject_erased_index_and_vector_contracts() {
    use aether_frontend::{IndexSemantics, TypeId};
    use aether_middle::{
        PlaceProjection, Rvalue, SsaOp, SsaPlaceProjection, TrapKind, build_ssa, lower_hir,
        verify_mir, verify_ssa,
    };
    let source = SourceFile::new(
        "v21-verify.ae",
        "int main(){Vector<int,Row> v=[10,20];usize n=dimension(v);int x=v[1];return x+int(n);}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = lower_hir(hir);
    let ssa = build_ssa(&verify_mir(mir.clone()).unwrap());
    for case in 0..6 {
        let mut corrupt = mir.clone();
        let mut changed = false;
        for instruction in corrupt.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
        {
            match (&mut instruction.value, case) {
                (
                    Rvalue::VectorInit {
                        element_type,
                        elements,
                        size_trap,
                        failure_trap,
                    },
                    0,
                ) => {
                    instruction.value = Rvalue::ArrayInit {
                        element_type: *element_type,
                        elements: elements.clone(),
                        size_trap: *size_trap,
                        failure_trap: *failure_trap,
                    };
                    changed = true;
                }
                (Rvalue::VectorDimension { source }, 1) => {
                    instruction.value = Rvalue::ArrayLength {
                        source: source.clone(),
                    };
                    changed = true;
                }
                (Rvalue::Load(place), 2) => {
                    for projection in &mut place.projections {
                        if let PlaceProjection::Index { semantics, .. } = projection {
                            *semantics = IndexSemantics::ZeroBased;
                            changed = true;
                        }
                    }
                }
                (Rvalue::VectorInit { element_type, .. }, 3) => {
                    *element_type = TypeId::BOOL;
                    changed = true;
                }
                (Rvalue::VectorInit { size_trap, .. }, 4) => {
                    *size_trap = TrapKind::IndexOutOfBounds;
                    changed = true;
                }
                (Rvalue::Load(place), 5) => {
                    for projection in &mut place.projections {
                        if let PlaceProjection::Index { bounds_trap, .. } = projection {
                            *bounds_trap = TrapKind::AllocationFailure;
                            changed = true;
                        }
                    }
                }
                _ => {}
            }
        }
        assert!(changed, "MIR case {case}");
        assert!(verify_mir(corrupt).is_err(), "MIR case {case}");
        let mut corrupt = ssa.clone();
        let mut changed = false;
        for instruction in corrupt.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
        {
            match (&mut instruction.op, case) {
                (
                    SsaOp::VectorInit {
                        element_type,
                        elements,
                        size_trap,
                        failure_trap,
                    },
                    0,
                ) => {
                    instruction.op = SsaOp::ArrayInit {
                        element_type: *element_type,
                        elements: elements.clone(),
                        size_trap: *size_trap,
                        failure_trap: *failure_trap,
                    };
                    changed = true;
                }
                (SsaOp::VectorDimension { source }, 1) => {
                    instruction.op = SsaOp::ArrayLength {
                        source: source.clone(),
                    };
                    changed = true;
                }
                (SsaOp::Load { place }, 2) => {
                    for projection in &mut place.projections {
                        if let SsaPlaceProjection::Index { semantics, .. } = projection {
                            *semantics = IndexSemantics::ZeroBased;
                            changed = true;
                        }
                    }
                }
                (SsaOp::VectorInit { element_type, .. }, 3) => {
                    *element_type = TypeId::BOOL;
                    changed = true;
                }
                (SsaOp::VectorInit { size_trap, .. }, 4) => {
                    *size_trap = TrapKind::IndexOutOfBounds;
                    changed = true;
                }
                (SsaOp::Load { place }, 5) => {
                    for projection in &mut place.projections {
                        if let SsaPlaceProjection::Index { bounds_trap, .. } = projection {
                            *bounds_trap = TrapKind::AllocationFailure;
                            changed = true;
                        }
                    }
                }
                _ => {}
            }
        }
        assert!(changed, "SSA case {case}");
        assert!(verify_ssa(corrupt).is_err(), "SSA case {case}");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical21_drop_order_is_reverse_logical_index() {
    for orientation in ["Row", "Column"] {
        let source = format!(
            "int main(){{Vector<Buffer<int>,{orientation}> v=[Buffer<int>(1,10),Buffer<int>(1,20),Buffer<int>(1,30)];return v[1][0]-10;}}"
        );
        let compilation = compile_source(&SourceFile::new("drop.ae", source), &[]).unwrap();
        let mut llvm=compilation.llvm.replace("call void @free(ptr %ptr)","call void @v21_note_free(ptr %ptr, i64 %size)\n  call void @free(ptr %ptr)").replace(
            "  %process_status = trunc i64 %aether_result to i32",
            "  %trace = load i64, ptr @v21_trace\n  %ordered = icmp eq i64 %trace, 302010\n  %process_status = select i1 %ordered, i32 0, i32 99");
        llvm.push_str(
            r"
@v21_trace = internal global i64 0
define internal void @v21_note_free(ptr %data, i64 %size) {
entry:
  %buffer = icmp eq i64 %size, 8
  br i1 %buffer, label %record, label %done
record:
  %payload = load i64, ptr %data
  %old = load i64, ptr @v21_trace
  %shift = mul i64 %old, 100
  %next = add i64 %shift, %payload
  store i64 %next, ptr @v21_trace
  br label %done
done:
  ret void
}
",
        );
        let artifact = temporary("v21-drop-order");
        ClangToolchain::default()
            .link_executable(&llvm, &artifact)
            .unwrap();
        let status = Command::new(&artifact).status().unwrap();
        let _ = fs::remove_file(artifact);
        assert_eq!(status.code(), Some(0), "{orientation}");
    }
}

#[test]
fn vertical21_cross_module_orientation_rejection_and_mangling() {
    let compilation = compile_session(
        CompilationSession::discover(&module_program("v21_vectors")).unwrap(),
        &[Emit::Hir, Emit::Ssa],
    )
    .unwrap();
    assert!(compilation.llvm.contains("QRow"));
    assert!(compilation.llvm.contains("QColumn"));
    let directory = temporary("v21-modules");
    fs::create_dir_all(&directory).unwrap();
    fs::copy(
        module_program("v21_vectors").with_file_name("storage.ae"),
        directory.join("storage.ae"),
    )
    .unwrap();
    for text in [
        "import storage;int main(){Vector<int,Column> c=storage.row(1,2);return 0;}",
        "import storage;int main(){Vector<int,Row> r=storage.column(1,2);return 0;}",
        "import storage;int main(){Vector<int,Row> r=[1,2];return storage.readColumn(&r,1);}",
        "import storage;int main(){storage.Holder<Vector<int,Row>> r=storage.Holder<Vector<int,Row>>([1]);storage.Holder<Vector<int,Column>> c=r;return 0;}",
    ] {
        fs::write(directory.join("main.ae"), text).unwrap();
        assert!(
            compile_session(
                CompilationSession::discover(&directory.join("main.ae")).unwrap(),
                &[]
            )
            .is_err(),
            "{text}"
        );
    }
    fs::remove_dir_all(directory).unwrap();
}

#[test]
fn vertical22_deterministic_consuming_ir() {
    let source = SourceFile::new(
        "transpose.ae",
        "Vector<T,Column> turn<T:Storable>(Vector<T,Row> v){return transpose(v);}int main(){Vector<int,Row> r=[10,20,30];Vector<int,Column> c=turn(r);return c[1]-10;}",
    );
    let emits = [Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let first = compile_source(&source, &emits).unwrap();
    let second = compile_source(&source, &emits).unwrap();
    assert_eq!(first.dumps, second.dumps);
    assert!(first.dumps[&Emit::Ast].contains("transpose"));
    assert!(!first.dumps[&Emit::Ast].contains("VectorTranspose"));
    for emit in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        assert!(first.dumps[&emit].contains("VectorTranspose"));
        assert!(first.dumps[&emit].contains("Row"));
        assert!(first.dumps[&emit].contains("Column"));
        assert!(first.dumps[&emit].contains("source_type"));
    }
    let helper = first
        .llvm
        .split("define ")
        .find(|part| part.contains("; VectorTransposeMove"))
        .unwrap();
    let body = helper.split("\n}").next().unwrap();
    for forbidden in [
        "call ",
        "getelementptr",
        "alloca",
        "extractvalue",
        "insertvalue",
        "br ",
        "memcpy",
        "conjugate",
    ] {
        assert!(!body.contains(forbidden), "{forbidden}: {body}");
    }
    assert!(body.contains("ret { ptr, i64 }"));
}

#[test]
fn vertical22_structured_diagnostics_and_parametric_checking() {
    for (prefix, argument) in [
        ("Array<int> a={1};", "a"),
        ("List<int> a={1};", "a"),
        ("Buffer<int> a=Buffer<int>(1,1);", "a"),
        ("", "1"),
        ("Vector<int,Row> a=[1];", "&a"),
    ] {
        let text =
            format!("int main(){{{prefix}Vector<int,Column> c=transpose({argument});return 0;}}");
        let errors = compile_source(&SourceFile::new("invalid.ae", text), &[]).unwrap_err();
        assert_eq!(errors[0].code, "E0328");
        assert!(errors[0].message.contains("Vector transpose"));
        assert!(errors[0].span.is_some());
    }
    for call in ["transpose()", "transpose(a,a)", "transpose<int>(a)"] {
        let text =
            format!("int main(){{Vector<int,Row> a=[1];Vector<int,Column> c={call};return 0;}}");
        assert_eq!(
            compile_source(&SourceFile::new("arity.ae", text), &[]).unwrap_err()[0].code,
            "E0328"
        );
    }
    for text in [
        "int main(){Vector<int,Row> r=[1];Vector<int,Column> c=r;return 0;}",
        "int main(){Vector<int,Row> r=[1];Vector<int,Row> c=transpose(r);return 0;}",
        "int main(){Vector<int,Row> r=[1];Vector<double,Column> c=transpose(r);return 0;}",
        "int main(){Vector<int,Row> r=[1];Vector<int,Column> c=transpose(r);return r[1];}",
        "int main(){Vector<int,Row> r=[1];Vector<int,Column> c=transpose(r);return int(dimension(r));}",
        "int main(){Vector<int,Row> r=[1];ref int x=&r[1];Vector<int,Column> c=transpose(r);return *x;}",
        "int main(){Vector<int,Row> r=[1];ref mut int x=&mut r[1];Vector<int,Column> c=transpose(r);return *x;}",
        "struct H{Vector<int,Row> v;}int main(){H h=H([1]);Vector<int,Column> c=transpose(h.v);return 0;}",
        "int main(){Array<Vector<int,Row>> a={[1]};Vector<int,Column> c=transpose(a[0]);return 0;}",
        "int f(ref Vector<int,Row> v){Vector<int,Column> c=transpose(*v);return 0;}int main(){return 0;}",
        "int branch(bool b){Vector<int,Row> r=[1];if(b){Vector<int,Column> c=transpose(r);}return r[1];}int main(){return branch(true);}",
        "Vector<T,Row> wrong<T:Storable>(Vector<T,Row> v){return transpose(v);}int main(){return 0;}",
        "Vector<T,Column> wrong<T:Copy>(Vector<T,Row> v){return transpose(v);}int main(){return 0;}",
        "int use(ref int x,Vector<int,Column> c){return *x;}int main(){Vector<int,Row> r=[1];return use(&r[1],transpose(r));}",
    ] {
        let errors = compile_source(&SourceFile::new("ownership.ae", text), &[]).expect_err(text);
        assert!(errors[0].span.is_some(), "{text}");
    }
    for (text, code) in [
        (
            "int main(){Vector<int,Row> r=[1];Vector<int,Column> c=transpose(r);return r[1];}",
            "E0291",
        ),
        (
            "int main(){Vector<int,Row> r=[1];ref int x=&r[1];Vector<int,Column> c=transpose(r);return *x;}",
            "E0292",
        ),
        (
            "int main(){Vector<int,Row> r=[1];ref mut int x=&mut r[1];Vector<int,Column> c=transpose(r);return *x;}",
            "E0292",
        ),
        (
            "struct H{Vector<int,Row> v;}int main(){H h=H([1]);Vector<int,Column> c=transpose(h.v);return 0;}",
            "E0293",
        ),
        (
            "int main(){Vector<int,Row> r=[1];transpose(r);return 0;}",
            "E0311",
        ),
        (
            "Vector<int,Column> f(Vector<int,Column> v){return v;}int main(){Vector<int,Row> r=[1];f(transpose(r));return 0;}",
            "E0311",
        ),
    ] {
        assert_eq!(
            compile_source(&SourceFile::new("diagnostic.ae", text), &[]).unwrap_err()[0].code,
            code,
            "{text}"
        );
    }
    // An unused generic body is checked with only its symbolic Storable proof.
    compile_source(&SourceFile::new("generic.ae", "Vector<T,Column> turn<T:Storable>(Vector<T,Row> v){return transpose(v);}Vector<T,Row> back<T:Storable>(Vector<T,Column> v){return transpose(v);}int main(){return 0;}"), &[]).unwrap();
}

/// Qualification-only instrumentation; no source-language/runtime API.
fn instrument_v22_transposes(llvm: &str, expected_heap: u64) -> String {
    let mut output = String::new();
    let mut count = 0;
    for line in llvm.lines() {
        if line.ends_with("; VectorTransposeMove") {
            let id = count;
            count += 1;
            let result = line.trim().split(" = ").next().unwrap();
            let operand = line
                .split("{ ptr, i64 } ")
                .nth(1)
                .unwrap()
                .split(',')
                .next()
                .unwrap();
            for (suffix, global) in [("a", "heap_alloc"), ("f", "heap_free"), ("r", "relocation")] {
                writeln!(
                    output,
                    "  %q{id}_{suffix}0 = load i64, ptr @aether_{global}_count"
                )
                .unwrap();
            }
            writeln!(output, "  %q{id}_p0 = extractvalue {{ ptr, i64 }} {operand}, 0\n  %q{id}_n0 = extractvalue {{ ptr, i64 }} {operand}, 1").unwrap();
            writeln!(output, "{line}").unwrap();
            for (suffix, global) in [("a", "heap_alloc"), ("f", "heap_free"), ("r", "relocation")] {
                writeln!(output, "  %q{id}_{suffix}1 = load i64, ptr @aether_{global}_count\n  %q{id}_{suffix}ok = icmp eq i64 %q{id}_{suffix}0, %q{id}_{suffix}1").unwrap();
            }
            writeln!(output, "  %q{id}_p1 = extractvalue {{ ptr, i64 }} {result}, 0\n  %q{id}_n1 = extractvalue {{ ptr, i64 }} {result}, 1\n  %q{id}_pok = icmp eq ptr %q{id}_p0, %q{id}_p1\n  %q{id}_nok = icmp eq i64 %q{id}_n0, %q{id}_n1").unwrap();
            writeln!(output, "  %q{id}_af = and i1 %q{id}_aok, %q{id}_fok\n  %q{id}_afr = and i1 %q{id}_af, %q{id}_rok\n  %q{id}_pn = and i1 %q{id}_pok, %q{id}_nok\n  %q{id}_ok = and i1 %q{id}_afr, %q{id}_pn\n  %q{id}_prior = load i1, ptr @v22_ok\n  %q{id}_all = and i1 %q{id}_prior, %q{id}_ok\n  store i1 %q{id}_all, ptr @v22_ok\n  %q{id}_seen = load i64, ptr @v22_seen\n  %q{id}_next = add i64 %q{id}_seen, 1\n  store i64 %q{id}_next, ptr @v22_seen").unwrap();
        } else if line == "  %process_status = trunc i64 %aether_result to i32" {
            writeln!(output, "  %qok = load i1, ptr @v22_ok\n  %qseen = load i64, ptr @v22_seen\n  %qran = icmp ugt i64 %qseen, 0\n  %qa = load i64, ptr @aether_heap_alloc_count\n  %qf = load i64, ptr @aether_heap_free_count\n  %qr = load i64, ptr @aether_relocation_count\n  %qaok = icmp eq i64 %qa, {expected_heap}\n  %qfok = icmp eq i64 %qf, {expected_heap}\n  %qrok = icmp eq i64 %qr, 0\n  %qaf = and i1 %qaok, %qfok\n  %qafr = and i1 %qaf, %qrok\n  %qopr = and i1 %qok, %qran\n  %qpass = and i1 %qafr, %qopr\n  %qresult = trunc i64 %aether_result to i32\n  %process_status = select i1 %qpass, i32 %qresult, i32 99").unwrap();
        } else {
            writeln!(output, "{line}").unwrap();
        }
    }
    assert!(count > 0);
    output.push_str("\n@v22_ok = internal global i1 true\n@v22_seen = internal global i64 0\n");
    output
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical22_native_data_ownership_and_per_transpose_zero_cost() {
    for (fixture, heap) in [
        ("row", 1),
        ("column", 1),
        ("empty", 0),
        ("owning", 4),
        ("double", 1),
        ("refs", 3),
        ("generic", 4),
        ("conditional", 6),
        ("aggregate", 3),
        ("non_numeric", 3),
        ("loop", 6),
    ] {
        let compilation = compile_session(
            CompilationSession::discover(&program(&format!("v22_transpose_{fixture}.ae"))).unwrap(),
            &[],
        )
        .unwrap();
        for llvm in [
            compilation.llvm.clone(),
            instrument_v22_transposes(&compilation.llvm, heap),
        ] {
            let artifact = temporary("v22-native");
            ClangToolchain::default()
                .link_executable(&llvm, &artifact)
                .unwrap();
            let status = Command::new(&artifact).status().unwrap();
            fs::remove_file(artifact).unwrap();
            assert_eq!(status.code(), Some(0), "{fixture}");
        }
    }
    let compilation = compile_session(
        CompilationSession::discover(&module_program("v22_transpose")).unwrap(),
        &[],
    )
    .unwrap();
    assert!(compilation.llvm.contains("QRow"));
    assert!(compilation.llvm.contains("QColumn"));
    let artifact = temporary("v22-module");
    ClangToolchain::default()
        .link_executable(&instrument_v22_transposes(&compilation.llvm, 2), &artifact)
        .unwrap();
    assert_eq!(Command::new(&artifact).status().unwrap().code(), Some(0));
    fs::remove_file(artifact).unwrap();
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical22_mir_ssa_reject_corrupt_type_and_owner_transfers() {
    use aether_frontend::{Orientation, TypeId};
    use aether_middle::{PlaceBase, Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};
    let source = SourceFile::new(
        "verify.ae",
        "int main(){Vector<int,Row> r=[10];Vector<int,Column> c=transpose(r);Vector<int,Row> back=transpose(c);return back[1]-10;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = lower_hir(hir);
    let ssa = build_ssa(&verify_mir(mir.clone()).unwrap());
    for case in 0..5 {
        let mut corrupt = mir.clone();
        let changed_type = match case {
            0 => std::sync::Arc::make_mut(&mut corrupt.types)
                .intern_vector(TypeId::INT64, Orientation::Row),
            1 => std::sync::Arc::make_mut(&mut corrupt.types)
                .intern_vector(TypeId::FLOAT64, Orientation::Column),
            _ => TypeId::INT64,
        };
        let function = &mut corrupt.functions[0];
        let instruction = function
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
            .find(|i| matches!(i.value, Rvalue::VectorTransposeMove { .. }))
            .unwrap();
        if case <= 2 {
            let PlaceBase::Local(local) = instruction.destination.base else {
                panic!()
            };
            function.locals[local.0 as usize].ty = changed_type;
        } else if let Rvalue::VectorTransposeMove {
            operand,
            source_type,
        } = &mut instruction.value
        {
            if case == 3 {
                *source_type = TypeId::BOOL;
            } else {
                instruction.value = Rvalue::Use(operand.clone());
            }
        }
        assert!(verify_mir(corrupt).is_err(), "MIR {case}");
        let mut corrupt = ssa.clone();
        let changed_type = match case {
            0 => std::sync::Arc::make_mut(&mut corrupt.types)
                .intern_vector(TypeId::INT64, Orientation::Row),
            1 => std::sync::Arc::make_mut(&mut corrupt.types)
                .intern_vector(TypeId::FLOAT64, Orientation::Column),
            _ => TypeId::INT64,
        };
        let instruction = corrupt.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
            .find(|i| matches!(i.op, SsaOp::VectorTransposeMove { .. }))
            .unwrap();
        if case <= 2 {
            instruction.ty = changed_type;
        } else if let SsaOp::VectorTransposeMove {
            operand,
            source_type,
        } = &mut instruction.op
        {
            if case == 3 {
                *source_type = TypeId::BOOL;
            } else {
                instruction.op = SsaOp::Use(operand.clone());
            }
        }
        assert!(verify_ssa(corrupt).is_err(), "SSA {case}");
    }
    // Duplicate a valid transfer with a fresh destination/value: type checking
    // succeeds, so rejection must come from the independent owner audit.
    let mut corrupt = mir;
    let f = &mut corrupt.functions[0];
    let b = &mut f.blocks[0];
    let index = b
        .instructions
        .iter()
        .position(|i| matches!(i.value, Rvalue::VectorTransposeMove { .. }))
        .unwrap();
    let mut duplicate = b.instructions[index].clone();
    let PlaceBase::Local(local) = duplicate.destination.base else {
        panic!()
    };
    let mut new_local = f.locals[local.0 as usize].clone();
    new_local.id = aether_frontend::LocalId(u32::try_from(f.locals.len()).unwrap());
    duplicate.destination.base = PlaceBase::Local(new_local.id);
    f.locals.push(new_local);
    b.instructions.insert(index + 1, duplicate);
    let errors = verify_mir(corrupt).unwrap_err();
    assert!(
        errors[0].message.contains("moved") || errors[0].message.contains("owned"),
        "{errors:?}"
    );
    let mut corrupt = ssa;
    let f = &mut corrupt.functions[0];
    let fresh = f
        .blocks
        .iter()
        .flat_map(|b| &b.instructions)
        .map(|i| i.result.0)
        .max()
        .unwrap()
        + 1;
    let b = &mut f.blocks[0];
    let index = b
        .instructions
        .iter()
        .position(|i| matches!(i.op, SsaOp::VectorTransposeMove { .. }))
        .unwrap();
    let mut duplicate = b.instructions[index].clone();
    duplicate.result = aether_middle::ValueId(fresh);
    b.instructions.insert(index + 1, duplicate);
    let errors = verify_ssa(corrupt).unwrap_err();
    assert!(
        errors[0].message.contains("transfer exactly once"),
        "{errors:?}"
    );
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical22_final_drop_is_once_in_reverse_order() {
    for (from, to) in [("Row", "Column"), ("Column", "Row")] {
        let source = format!(
            "int main(){{Vector<Buffer<int>,{from}> v=[Buffer<int>(1,10),Buffer<int>(1,20),Buffer<int>(1,30)];Vector<Buffer<int>,{to}> result=transpose(v);return result[1][0]-10;}}"
        );
        let compilation = compile_source(&SourceFile::new("drop.ae", source), &[]).unwrap();
        let mut llvm = instrument_v22_transposes(&compilation.llvm, 4)
            .replace("call void @free(ptr %ptr)", "call void @v22_note_free(ptr %ptr, i64 %size)\n  call void @free(ptr %ptr)")
            .replace("  %qpass = and i1 %qafr, %qopr", "  %qbase = and i1 %qafr, %qopr\n  %qtrace = load i64, ptr @v22_trace\n  %qordered = icmp eq i64 %qtrace, 302010\n  %qpass = and i1 %qbase, %qordered");
        llvm.push_str(
            r"
@v22_trace = internal global i64 0
define internal void @v22_note_free(ptr %data, i64 %size) {
entry:
  %buffer = icmp eq i64 %size, 8
  br i1 %buffer, label %record, label %done
record:
  %payload = load i64, ptr %data
  %old = load i64, ptr @v22_trace
  %shift = mul i64 %old, 100
  %next = add i64 %shift, %payload
  store i64 %next, ptr @v22_trace
  br label %done
done:
  ret void
}
",
        );
        let artifact = temporary("v22-drop");
        ClangToolchain::default()
            .link_executable(&llvm, &artifact)
            .unwrap();
        let status = Command::new(&artifact).status().unwrap();
        fs::remove_file(artifact).unwrap();
        assert_eq!(status.code(), Some(0), "{from}");
    }
}

#[test]
fn vertical22_cross_module_orientation_and_layout() {
    use aether_frontend::{Orientation, TypeArena, TypeId};
    let mut types = TypeArena::new();
    let row = types.intern_vector(TypeId::INT64, Orientation::Row);
    let column = types.intern_vector(TypeId::INT64, Orientation::Column);
    assert_ne!(row, column);
    assert_eq!(
        layout_of(&types, row, TargetProperties::LINUX_X86_64, &[], &[]).unwrap(),
        layout_of(&types, column, TargetProperties::LINUX_X86_64, &[], &[]).unwrap()
    );
    assert!(!types.is_copy(row));
    assert!(!types.is_copy(column));
    let directory = temporary("v22-module-errors");
    fs::create_dir_all(&directory).unwrap();
    fs::copy(
        module_program("v22_transpose").with_file_name("storage.ae"),
        directory.join("storage.ae"),
    )
    .unwrap();
    for text in [
        "import storage;int main(){Vector<int,Row> r=[1];Vector<int,Row> bad=storage.toColumn(r);return 0;}",
        "import storage;int main(){Vector<int,Column> c=[1];Vector<int,Column> bad=storage.toRow(c);return 0;}",
        "import storage;int main(){Vector<int,Column> c=[1];Vector<int,Column> bad=storage.toColumn(c);return 0;}",
    ] {
        fs::write(directory.join("main.ae"), text).unwrap();
        assert!(
            compile_session(
                CompilationSession::discover(&directory.join("main.ae")).unwrap(),
                &[]
            )
            .is_err(),
            "{text}"
        );
    }
    fs::remove_dir_all(directory).unwrap();
}

#[test]
fn vertical23_identity_context_and_deterministic_ir() {
    use aether_frontend::{IndexSemantics, Orientation, TypeArena, TypeId};
    let mut types = TypeArena::new();
    let matrix = types.intern_matrix(TypeId::INT64);
    assert_eq!(matrix, types.intern_matrix(TypeId::INT64));
    for other in [
        types.intern_array(TypeId::INT64),
        types.intern_list(TypeId::INT64),
        types.intern_vector(TypeId::INT64, Orientation::Row),
        types.intern_vector(TypeId::INT64, Orientation::Column),
    ] {
        assert_ne!(matrix, other);
    }
    assert!(!types.is_copy(matrix));
    assert!(types.needs_drop(matrix));
    assert_eq!(
        types.index_semantics(matrix),
        Some(IndexSemantics::OneBased2D)
    );
    assert_eq!(
        layout_of(&types, matrix, TargetProperties::LINUX_X86_64, &[], &[])
            .unwrap()
            .size,
        24
    );
    let source = SourceFile::new(
        "matrix.ae",
        "int main(){Matrix<int> a=[1,2,3;4,5,6];Vector<int,Row> v=[1,2,3];Vector<int,Column> w=transpose(v);return a[2,3]+int(rows(a)+columns(a)+dimension(w))-14;}",
    );
    let emits = [Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let first = compile_source(&source, &emits).unwrap();
    assert_eq!(first.dumps, compile_source(&source, &emits).unwrap().dumps);
    assert!(first.dumps[&Emit::Ast].contains("MathematicalLiteral"));
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        for name in [
            "MatrixInit",
            "MatrixRows",
            "MatrixColumns",
            "OneBased2D",
            "VectorInit",
        ] {
            assert!(first.dumps[&phase].contains(name), "{phase:?}: {name}");
        }
    }
    let helper = first
        .llvm
        .split("define internal ptr @aether_matrix_index_")
        .nth(1)
        .unwrap()
        .split("\n}")
        .next()
        .unwrap();
    let mut previous = 0;
    for guard in [
        "%row_lower =",
        "%row_upper =",
        "%column_lower =",
        "%column_upper =",
        "%row0 = sub",
        "%column0 = sub",
        "%linear = add",
        "getelementptr inbounds",
    ] {
        let position = helper.find(guard).unwrap();
        assert!(position > previous);
        previous = position;
    }
    assert!(helper.contains("call void @llvm.trap()"));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical23_native_shapes_ownership_and_exact_heap_counts() {
    for (fixture, count) in [
        ("empty", 0),
        ("empty_owning", 0),
        ("row", 1),
        ("column", 1),
        ("square", 1),
        ("rectangular", 1),
        ("widening", 2),
        ("refs", 1),
        ("move", 1),
        ("return", 1),
        ("struct", 1),
        ("enum", 1),
        ("generic", 4),
        ("owning", 5),
        ("conditional", 2),
        ("nested", 11),
        ("loop", 1),
        ("evaluation", 1),
    ] {
        let compiled = compile_session(
            CompilationSession::discover(&program(&format!("v23_matrix_{fixture}.ae"))).unwrap(),
            &[],
        )
        .unwrap();
        let llvm = v23_heap_guard(&compiled.llvm, count);
        let status = v23_execute(&llvm);
        assert_eq!(status.code(), Some(0), "{fixture}");
    }
    let compiled = compile_session(
        CompilationSession::discover(&module_program("v23_matrix")).unwrap(),
        &[],
    )
    .unwrap();
    assert!(compiled.llvm.contains("MiInt64"));
    assert!(compiled.llvm.contains("MBiInt64"));
    assert_eq!(
        v23_execute(&v23_heap_guard(&compiled.llvm, 4)).code(),
        Some(0)
    );
}

fn v23_heap_guard(llvm: &str, count: u64) -> String {
    llvm.replace("  %process_status = trunc i64 %aether_result to i32",&format!("  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, {count}\n  %free_ok = icmp eq i64 %frees, {count}\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99"))
}
fn v23_execute(llvm: &str) -> std::process::ExitStatus {
    let artifact = temporary("v23");
    ClangToolchain::default()
        .link_executable(llvm, &artifact)
        .unwrap();
    let status = Command::new(&artifact).status().unwrap();
    fs::remove_file(artifact).unwrap();
    status
}

#[test]
fn vertical23_structured_diagnostics() {
    for (body, code) in [
        ("Matrix<int,int> a=[];", "E0261"),
        ("Matrix<int,Missing> a=[];", "E0261"),
        ("Matrix a=[];", "E0261"),
        ("Matrix<ref int> a=[];", "E0331"),
        ("Matrix<int> a=[1,2;3,4,5];", "E0333"),
        ("Vector<int,Row> a=[1;2];", "E0332"),
        ("int a=[1;2];", "E0326"),
        ("Matrix<int> a=[1,2;3,4];int x=a[1];", "E0334"),
        ("Matrix<int> a=[1];int x=a[1,1,1];", "E0334"),
        ("Matrix<int> a=[1];int x=a[0,1];", "E0296"),
        ("Matrix<int> a=[1];int x=a[1,0];", "E0296"),
        ("Matrix<int> a=[1,2,3;4,5,6];int x=a[3,1];", "E0296"),
        ("Matrix<int> a=[1,2,3;4,5,6];int x=a[1,4];", "E0296"),
        ("Matrix<int> a=[];int x=a[1,1];", "E0296"),
        ("Vector<int,Row> a=[1];usize n=rows(a);", "E0335"),
        ("Array<int> a={1};usize n=columns(a);", "E0335"),
        ("Matrix<int> a=[1];Matrix<int> b=transpose(a);", "E0328"),
        ("Matrix<int> a=[1];Matrix<int> b=a;int x=a[1,1];", "E0291"),
        (
            "Matrix<int> a=[1];ref int x=&a[1,1];Matrix<int> b=a;",
            "E0292",
        ),
        (
            "Matrix<int> a=[1];ref mut int x=&mut a[1,1];Matrix<int> b=a;",
            "E0292",
        ),
        ("Matrix<int> a=[1];View<int> v=view(a);", "E0289"),
        ("Matrix<int> a=[1];ViewMut<int> v=view_mut(a);", "E0289"),
        ("Matrix<int> a=[1;];", "E0330"),
    ] {
        let source = format!("int main(){{{body}return 0;}}");
        let errors = compile_source(&SourceFile::new("error.ae", source), &[]).expect_err(body);
        assert_eq!(errors[0].code, code, "{body}: {errors:?}");
        assert!(errors[0].span.is_some());
    }
    for source in [
        "Matrix<T> bad<T>(T x){return [x];}int main(){return 0;}",
        "Matrix<T> bad<T:Copy>(T x){return [x];}int main(){return 0;}",
        "int main(){Matrix<int> a=[1];int i=1;return a[i,1];}",
        "int main(){Matrix<int> a=[1];int i=1;return a[1,i];}",
        "int main(){Matrix<int> a=[1];return a[-1,1];}",
        "int main(){Matrix<int> a=[1];return a[1,true];}",
        "usize take(Matrix<int> a){return 1;}int main(){Matrix<int> a=[1];return a[1,take(a)];}",
        "int main(){Matrix<Buffer<int>> a=[Buffer<int>(1,10)];Buffer<int> b=a[1,1];return 0;}",
        "int main(){Matrix<Buffer<int>> a=[Buffer<int>(1,10)];a[1,1]=Buffer<int>(1,20);return 0;}",
    ] {
        assert!(
            compile_source(&SourceFile::new("error.ae", source), &[]).is_err(),
            "{source}"
        );
    }
    compile_source(
        &SourceFile::new(
            "symbolic.ae",
            "Matrix<T> make<T:Storable>(T a,T b){return [a,b];}int main(){return 0;}",
        ),
        &[],
    )
    .unwrap();
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical23_runtime_bounds_all_axes_and_access_modes() {
    use std::os::unix::process::ExitStatusExt;
    for (literal, m, n) in [
        ("[]", 0, 0),
        ("[1,2,3]", 1, 3),
        ("[1;2;3]", 3, 1),
        ("[1,2,3;4,5,6]", 2, 3),
    ] {
        for (row, column) in [
            (0, 1),
            (1, 0),
            (m + 1, 1),
            (1, n + 1),
            (u64::MAX, 1),
            (1, u64::MAX),
        ] {
            for operation in [
                "return a[i,j];",
                "a[i,j]=42;return 0;",
                "ref int x=&a[i,j];return *x;",
                "ref mut int x=&mut a[i,j];*x=42;return 0;",
            ] {
                let source = format!(
                    "int main(){{Matrix<int> a={literal};usize i={row};usize j={column};{operation}}}"
                );
                let compiled = compile_source(&SourceFile::new("bounds.ae", source), &[]).unwrap();
                assert_eq!(
                    v23_execute(&compiled.llvm).signal(),
                    Some(4),
                    "{literal}: {row},{column}: {operation}"
                );
            }
        }
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical23_independent_hir_mir_ssa_contract_verifiers() {
    use aether_frontend::{IndexSemantics, TypeId};
    use aether_middle::{
        PlaceProjection, Rvalue, SsaOp, SsaPlaceProjection, TrapKind, build_ssa, lower_hir,
        verify_mir, verify_ssa,
    };
    let source = SourceFile::new(
        "verify.ae",
        "int main(){Matrix<int> a=[1,2,3;4,5,6];usize n=rows(a);usize m=columns(a);int x=a[2,3];return x+int(n+m);}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = lower_hir(hir);
    let ssa = build_ssa(&verify_mir(mir.clone()).unwrap());
    for case in 0..11 {
        let mut corrupt = mir.clone();
        let mut changed = false;
        for instruction in corrupt.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
        {
            match (&mut instruction.value, case) {
                (Rvalue::MatrixInit { rows, columns, .. }, 0) => {
                    std::mem::swap(rows, columns);
                    changed = true;
                }
                (Rvalue::MatrixInit { element_type, .. }, 1) => {
                    *element_type = TypeId::BOOL;
                    changed = true;
                }
                (Rvalue::MatrixInit { row_ends, .. }, 2) => {
                    row_ends[0] += 1;
                    changed = true;
                }
                (
                    Rvalue::MatrixInit {
                        element_type,
                        elements,
                        size_trap,
                        failure_trap,
                        ..
                    },
                    3,
                ) => {
                    instruction.value = Rvalue::VectorInit {
                        element_type: *element_type,
                        elements: elements.clone(),
                        size_trap: *size_trap,
                        failure_trap: *failure_trap,
                    };
                    changed = true;
                }
                (Rvalue::MatrixRows { source }, 4) => {
                    instruction.value = Rvalue::VectorDimension {
                        source: source.clone(),
                    };
                    changed = true;
                }
                (Rvalue::Load(place), 5..=7) => {
                    for projection in &mut place.projections {
                        if let PlaceProjection::Index {
                            column,
                            semantics,
                            bounds_trap,
                            ..
                        } = projection
                        {
                            match case {
                                5 => *column = None,
                                6 => *semantics = IndexSemantics::OneBased,
                                _ => *bounds_trap = TrapKind::AllocationFailure,
                            }
                            changed = true;
                        }
                    }
                }
                (Rvalue::MatrixInit { size_trap, .. }, 8) => {
                    *size_trap = TrapKind::IndexOutOfBounds;
                    changed = true;
                }
                (Rvalue::MatrixInit { failure_trap, .. }, 9) => {
                    *failure_trap = TrapKind::IndexOutOfBounds;
                    changed = true;
                }
                (Rvalue::MatrixInit { rows, columns, .. }, 10) => {
                    *rows = u64::MAX;
                    *columns = 2;
                    changed = true;
                }
                _ => {}
            }
        }
        assert!(changed, "MIR {case}");
        assert!(verify_mir(corrupt).is_err(), "MIR {case}");
        let mut corrupt = ssa.clone();
        let mut changed = false;
        for instruction in corrupt.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
        {
            match (&mut instruction.op, case) {
                (SsaOp::MatrixInit { rows, columns, .. }, 0) => {
                    std::mem::swap(rows, columns);
                    changed = true;
                }
                (SsaOp::MatrixInit { element_type, .. }, 1) => {
                    *element_type = TypeId::BOOL;
                    changed = true;
                }
                (SsaOp::MatrixInit { row_ends, .. }, 2) => {
                    row_ends[0] += 1;
                    changed = true;
                }
                (
                    SsaOp::MatrixInit {
                        element_type,
                        elements,
                        size_trap,
                        failure_trap,
                        ..
                    },
                    3,
                ) => {
                    instruction.op = SsaOp::VectorInit {
                        element_type: *element_type,
                        elements: elements.clone(),
                        size_trap: *size_trap,
                        failure_trap: *failure_trap,
                    };
                    changed = true;
                }
                (SsaOp::MatrixRows { source }, 4) => {
                    instruction.op = SsaOp::VectorDimension {
                        source: source.clone(),
                    };
                    changed = true;
                }
                (SsaOp::Load { place }, 5..=7) => {
                    for projection in &mut place.projections {
                        if let SsaPlaceProjection::Index {
                            column,
                            semantics,
                            bounds_trap,
                            ..
                        } = projection
                        {
                            match case {
                                5 => *column = None,
                                6 => *semantics = IndexSemantics::OneBased,
                                _ => *bounds_trap = TrapKind::AllocationFailure,
                            }
                            changed = true;
                        }
                    }
                }
                (SsaOp::MatrixInit { size_trap, .. }, 8) => {
                    *size_trap = TrapKind::IndexOutOfBounds;
                    changed = true;
                }
                (SsaOp::MatrixInit { failure_trap, .. }, 9) => {
                    *failure_trap = TrapKind::IndexOutOfBounds;
                    changed = true;
                }
                (SsaOp::MatrixInit { rows, columns, .. }, 10) => {
                    *rows = u64::MAX;
                    *columns = 2;
                    changed = true;
                }
                _ => {}
            }
        }
        assert!(changed, "SSA {case}");
        assert!(verify_ssa(corrupt).is_err(), "SSA {case}");
    }
    let owning = analyze(
        parse_source(&SourceFile::new(
            "owner.ae",
            "int main(){Matrix<Buffer<int>> a=[Buffer<int>(1,10),Buffer<int>(1,20)];return 0;}",
        ))
        .unwrap(),
    )
    .unwrap();
    let mut mir = lower_hir(owning);
    let mut ssa = build_ssa(&verify_mir(mir.clone()).unwrap());
    for instruction in mir.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|b| &mut b.instructions)
    {
        if let Rvalue::MatrixInit { elements, .. } = &mut instruction.value {
            elements[1] = elements[0].clone();
        }
    }
    assert!(verify_mir(mir).is_err());
    for instruction in ssa.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|b| &mut b.instructions)
    {
        if let SsaOp::MatrixInit { elements, .. } = &mut instruction.op {
            elements[1] = elements[0].clone();
        }
    }
    assert!(verify_ssa(ssa).is_err());
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical23_owning_payload_drop_order() {
    let compilation = compile_session(
        CompilationSession::discover(&program("v23_matrix_owning.ae")).unwrap(),
        &[],
    )
    .unwrap();
    let mut llvm=v23_heap_guard(&compilation.llvm,5).replace("call void @free(ptr %ptr)","call void @v23_note_free(ptr %ptr, i64 %size)\n  call void @free(ptr %ptr)").replace("  %all_ok = and i1 %heap_ok, %result_ok", "  %trace = load i64, ptr @v23_trace\n  %ordered = icmp eq i64 %trace, 40302010\n  %base_ok = and i1 %heap_ok, %result_ok\n  %all_ok = and i1 %base_ok, %ordered");
    llvm.push_str(
        r"
@v23_trace = internal global i64 0
define internal void @v23_note_free(ptr %data, i64 %size) {
entry:
  %buffer = icmp eq i64 %size, 8
  br i1 %buffer, label %record, label %done
record:
  %payload = load i64, ptr %data
  %old = load i64, ptr @v23_trace
  %shift = mul i64 %old, 100
  %next = add i64 %shift, %payload
  store i64 %next, ptr @v23_trace
  br label %done
done:
  ret void
}
",
    );
    assert_eq!(v23_execute(&llvm).code(), Some(0));
}

#[test]
fn vertical23_cross_module_signature_rejections() {
    let directory = temporary("v23-modules");
    fs::create_dir_all(&directory).unwrap();
    fs::copy(
        module_program("v23_matrix").with_file_name("storage.ae"),
        directory.join("storage.ae"),
    )
    .unwrap();
    for text in [
        "import storage;int main(){Vector<int,Row> a=storage.pair(1,2);return 0;}",
        "import storage;int main(){Array<int> a=storage.pair(1,2);return 0;}",
        "import storage;int main(){Matrix<double> a=storage.pair<int>(1,2);return 0;}",
        "import storage;int main(){Vector<int,Row> a=[1,2];return storage.read(&a,1,1);}",
    ] {
        fs::write(directory.join("main.ae"), text).unwrap();
        assert!(
            compile_session(
                CompilationSession::discover(&directory.join("main.ae")).unwrap(),
                &[]
            )
            .is_err(),
            "{text}"
        );
    }
    fs::remove_dir_all(directory).unwrap();
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical24_native_mapping_borrows_and_heap_counts() {
    for (name, heap) in [
        ("normal", 1),
        ("mutable", 1),
        ("transpose", 1),
        ("transpose_mut", 1),
        ("double", 1),
        ("empty", 0),
        ("owning", 5),
        ("projected", 5),
        ("refs", 1),
        ("copy", 1),
        ("scope", 1),
        ("generic", 1),
    ] {
        let compiled = compile_session(
            CompilationSession::discover(&program(&format!("v24_matrix_view_{name}.ae"))).unwrap(),
            &[],
        )
        .unwrap_or_else(|e| panic!("{name}: {e:?}"));
        assert_eq!(
            v23_execute(&v23_heap_guard(&compiled.llvm, heap)).code(),
            Some(0),
            "{name}"
        );
    }
    let compiled = compile_session(
        CompilationSession::discover(&module_program("v24_matrix_views")).unwrap(),
        &[],
    )
    .unwrap();
    assert_eq!(
        v23_execute(&v23_heap_guard(&compiled.llvm, 1)).code(),
        Some(0)
    );
}

#[test]
fn vertical24_identity_and_deterministic_ir() {
    use aether_frontend::{IndexSemantics, TypeArena, TypeId};
    let mut types = TypeArena::new();
    let v = types.intern_matrix_view(TypeId::INT64, false);
    let w = types.intern_matrix_view(TypeId::INT64, true);
    assert_eq!(v, types.intern_matrix_view(TypeId::INT64, false));
    assert_ne!(v, w);
    for t in [v, w] {
        assert_ne!(t, types.intern_matrix(TypeId::INT64));
        assert_ne!(t, types.intern_view(TypeId::INT64, false));
        assert_ne!(t, types.intern_view(TypeId::INT64, true));
        let p = types.properties(t).unwrap();
        assert!(p.is_copy && p.is_relocatable && !p.is_storable && !p.needs_drop);
        assert!(types.contains_view(t));
        assert_eq!(types.index_semantics(t), Some(IndexSemantics::OneBased2D));
        assert_eq!(
            layout_of(&types, t, TargetProperties::LINUX_X86_64, &[], &[])
                .unwrap()
                .size,
            40
        );
    }
    let source = SourceFile::new(
        "view.ae",
        fs::read_to_string(program("v24_matrix_view_double.ae")).unwrap(),
    );
    let emits = [Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let first = compile_source(&source, &emits).unwrap();
    assert_eq!(first.dumps, compile_source(&source, &emits).unwrap().dumps);
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        for word in [
            "MatrixView",
            "row_stride",
            "column_stride",
            "OneBased2D",
            "transpose: true",
        ] {
            assert!(first.dumps[&phase].contains(word), "{phase:?}: {word}");
        }
    }
    assert!(!first.llvm.contains("noalias"));
    let helper = first
        .llvm
        .split("define internal ptr @aether_matrix_view_index_")
        .nth(1)
        .unwrap()
        .split("\n}")
        .next()
        .unwrap();
    assert!(helper.find("column_upper_check:").unwrap() < helper.find("%row0 = sub").unwrap());
    assert!(helper.contains("mul i64 %row0, %row_stride"));
    assert!(helper.contains("mul i64 %column0, %column_stride"));
    assert!(!helper.contains("getelementptr inbounds"));
}

#[test]
fn vertical24_structured_diagnostics_and_owner_liveness() {
    for (body, code) in [
        (
            "Array<int> a={1};MatrixView<int> v=matrix_view(a);",
            "E0336",
        ),
        (
            "Vector<int,Row> a=[1];MatrixView<int> v=matrix_view(a);",
            "E0336",
        ),
        (
            "Array<int> a={1};MatrixView<int> v=transpose_view(a);",
            "E0336",
        ),
        (
            "Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);v[1,1]=2;",
            "E0288",
        ),
        (
            "Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);MatrixViewMut<int> w=matrix_view_mut(v);",
            "E0337",
        ),
        (
            "Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);int x=v[1];",
            "E0334",
        ),
        (
            "Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);int x=v[1,1,1];",
            "E0334",
        ),
        (
            "Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);int x=v[0,1];",
            "E0296",
        ),
        (
            "Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);a=[2];",
            "E0292",
        ),
        (
            "Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);consume(a);",
            "E0292",
        ),
        (
            "Matrix<int> a=[1];MatrixViewMut<int> v=matrix_view_mut(a);consume(a);",
            "E0292",
        ),
        (
            "Matrix<int> a=[1];MatrixView<int> v=transpose_view(a);MatrixView<int> w=v;consume(a);",
            "E0292",
        ),
        (
            "Matrix<int> a=[1];MatrixViewMut<int> v=transpose_view_mut(a);MatrixView<int> w=transpose_view(v);consume(a);",
            "E0292",
        ),
        ("Matrix<int> a=[1];Matrix<int> b=transpose(a);", "E0328"),
        (
            "Matrix<int> a=[1];MatrixView<int> v=MatrixView<int>(a,1,1,1,1);",
            "E0212",
        ),
    ] {
        let source =
            format!("int consume(Matrix<int> a){{return 0;}}int main(){{{body}return 0;}}");
        let e = compile_source(&SourceFile::new("bad.ae", source), &[])
            .err()
            .unwrap_or_else(|| panic!("accepted {body}"));
        assert!(
            e.iter().any(|d| d.code == code),
            "{body}: expected {code}, got {e:?}"
        );
    }
    for source in [
        "int main(){Matrix<int> a=[1];ref Matrix<int> r=&a;MatrixViewMut<int> v=matrix_view_mut(*r);return 0;}",
        "int main(){Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);ref mut int r=&mut v[1,1];return 0;}",
        "MatrixView<int> bad(){Matrix<int> a=[1];return matrix_view(a);}int main(){return 0;}",
        "MatrixViewMut<int> bad(MatrixViewMut<int> v){return v;}int main(){return 0;}",
        "struct H{MatrixView<int> v;}int main(){return 0;}",
        "struct H{MatrixViewMut<int> v;}int main(){return 0;}",
        "int main(){Array<MatrixView<int>> a={};return 0;}",
        "int main(){List<MatrixView<int>> a={};return 0;}",
        "int main(){Matrix<MatrixView<int>> a=[];return 0;}",
        "int main(){Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);bool b=true;return v[b,1];}",
        "int main(){Matrix<Buffer<int>> a=[Buffer<int>(1,2)];MatrixView<Buffer<int>> v=matrix_view(a);Buffer<int> b=v[1,1];return 0;}",
        "int main(){Matrix<Buffer<int>> a=[Buffer<int>(1,2)];MatrixViewMut<Buffer<int>> v=matrix_view_mut(a);v[1,1]=Buffer<int>(1,3);return 0;}",
        "struct H{Matrix<int> a;}int consume(H h){return 0;}int main(){H h=H([1]);MatrixView<int> v=matrix_view(h.a);consume(h);return 0;}",
        "int main(){List<Matrix<int>> a={[1]};MatrixView<int> v=matrix_view(a[0]);push(a,[2]);return 0;}",
    ] {
        assert!(
            compile_source(&SourceFile::new("bad.ae", source), &[]).is_err(),
            "accepted {source}"
        );
    }
}

/// Observe each descriptor transform, including its backing pointer, with no
/// changes to the production runtime or source API.
fn v24_zero_cost_guard(llvm: &str, heap: u64) -> String {
    let mut output = String::new();
    let mut count = 0;
    let mut inside = false;
    for line in llvm.lines() {
        if let Some(source) = line.trim().strip_prefix("; MatrixViewBegin ") {
            assert!(!inside);
            inside = true;
            let (ty, value) = source.split_once('|').unwrap();
            for (suffix, global) in [("a", "heap_alloc"), ("f", "heap_free"), ("r", "relocation")] {
                writeln!(
                    output,
                    "  %qv{count}_{suffix}0 = load i64, ptr @aether_{global}_count"
                )
                .unwrap();
            }
            writeln!(output, "  %qv{count}_p0 = extractvalue {ty} {value}, 0").unwrap();
        } else if let Some(result) = line.trim().strip_prefix("; MatrixViewEnd ") {
            assert!(inside);
            inside = false;
            for (suffix, global) in [("a", "heap_alloc"), ("f", "heap_free"), ("r", "relocation")] {
                writeln!(output,"  %qv{count}_{suffix}1 = load i64, ptr @aether_{global}_count\n  %qv{count}_{suffix}ok = icmp eq i64 %qv{count}_{suffix}0, %qv{count}_{suffix}1").unwrap();
            }
            writeln!(output,"  %qv{count}_p1 = extractvalue {{ ptr, i64, i64, i64, i64 }} {result}, 0\n  %qv{count}_pok = icmp eq ptr %qv{count}_p0, %qv{count}_p1\n  %qv{count}_af = and i1 %qv{count}_aok, %qv{count}_fok\n  %qv{count}_rp = and i1 %qv{count}_rok, %qv{count}_pok\n  %qv{count}_ok = and i1 %qv{count}_af, %qv{count}_rp\n  %qv{count}_prior = load i1, ptr @v24_ok\n  %qv{count}_all = and i1 %qv{count}_prior, %qv{count}_ok\n  store i1 %qv{count}_all, ptr @v24_ok\n  %qv{count}_seen = load i64, ptr @v24_seen\n  %qv{count}_next = add i64 %qv{count}_seen, 1\n  store i64 %qv{count}_next, ptr @v24_seen").unwrap();
            count += 1;
        } else if line == "  %process_status = trunc i64 %aether_result to i32" {
            writeln!(output,"  %qv_ok = load i1, ptr @v24_ok\n  %qv_seen = load i64, ptr @v24_seen\n  %qv_ran = icmp ugt i64 %qv_seen, 0\n  %qv_a = load i64, ptr @aether_heap_alloc_count\n  %qv_f = load i64, ptr @aether_heap_free_count\n  %qv_r = load i64, ptr @aether_relocation_count\n  %qv_aok = icmp eq i64 %qv_a, {heap}\n  %qv_fok = icmp eq i64 %qv_f, {heap}\n  %qv_rok = icmp eq i64 %qv_r, 0\n  %qv_af = and i1 %qv_aok, %qv_fok\n  %qv_afr = and i1 %qv_af, %qv_rok\n  %qv_op = and i1 %qv_ok, %qv_ran\n  %qv_pass = and i1 %qv_afr, %qv_op\n  %qv_result = trunc i64 %aether_result to i32\n  %process_status = select i1 %qv_pass, i32 %qv_result, i32 99").unwrap();
        } else {
            if inside {
                assert!(
                    line.contains("extractvalue") || line.contains("insertvalue"),
                    "element/storage operation during view transform: {line}"
                );
            }
            writeln!(output, "{line}").unwrap();
        }
    }
    assert!(count > 0 && !inside);
    output.push_str("\n@v24_ok = internal global i1 true\n@v24_seen = internal global i64 0\n");
    output
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical24_each_view_has_zero_heap_relocation_and_pointer_delta() {
    for (name, heap) in [
        ("normal", 1),
        ("mutable", 1),
        ("transpose", 1),
        ("transpose_mut", 1),
        ("double", 1),
        ("empty", 0),
        ("owning", 5),
        ("projected", 5),
        ("refs", 1),
        ("copy", 1),
        ("scope", 1),
        ("generic", 1),
    ] {
        let compiled = compile_source(
            &SourceFile::new(
                "cost.ae",
                fs::read_to_string(program(&format!("v24_matrix_view_{name}.ae"))).unwrap(),
            ),
            &[],
        )
        .unwrap();
        assert_eq!(
            v23_execute(&v24_zero_cost_guard(&compiled.llvm, heap)).code(),
            Some(0),
            "{name}"
        );
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical24_runtime_bounds_all_axes_and_capabilities() {
    use std::os::unix::process::ExitStatusExt;
    for (literal, r, c) in [("[]", 0, 0), ("[1,2,3;4,5,6]", 2, 3)] {
        for (ty, create, transpose) in [
            ("MatrixView", "matrix_view", false),
            ("MatrixView", "transpose_view", true),
            ("MatrixViewMut", "matrix_view_mut", false),
            ("MatrixViewMut", "transpose_view_mut", true),
        ] {
            let (r, c) = if transpose { (c, r) } else { (r, c) };
            for (i, j) in [
                (0, 1),
                (1, 0),
                (r + 1, 1),
                (1, c + 1),
                (u64::MAX, 1),
                (1, u64::MAX),
            ] {
                let operations = if ty == "MatrixViewMut" {
                    vec![
                        "return v[i,j];",
                        "v[i,j]=42;return 0;",
                        "ref int x=&v[i,j];return *x;",
                        "ref mut int x=&mut v[i,j];*x=42;return 0;",
                    ]
                } else {
                    vec!["return v[i,j];", "ref int x=&v[i,j];return *x;"]
                };
                for operation in operations {
                    let source = format!(
                        "int main(){{Matrix<int> a={literal};{ty}<int> v={create}(a);usize i={i};usize j={j};{operation}}}"
                    );
                    let compiled =
                        compile_source(&SourceFile::new("bounds.ae", source), &[]).unwrap();
                    assert_eq!(
                        v23_execute(&compiled.llvm).signal(),
                        Some(4),
                        "{literal} {create} {i},{j} {operation}"
                    );
                }
            }
        }
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical24_mir_ssa_reject_corrupt_descriptor_contracts() {
    use aether_frontend::{IndexSemantics, MatrixViewField};
    use aether_middle::{
        PlaceProjection, Rvalue, SsaOp, SsaPlaceProjection, build_ssa, lower_hir, verify_mir,
        verify_ssa,
    };
    let source = SourceFile::new(
        "corrupt.ae",
        "int main(){Matrix<int> a=[1,2,3;4,5,6];MatrixView<int> v=transpose_view(a);MatrixView<int> u=transpose_view(v);MatrixView<int> w=u;return w[1,2];}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = lower_hir(hir);
    let ssa = build_ssa(&verify_mir(mir.clone()).unwrap());
    for case in 0..7 {
        let mut m = mir.clone();
        let mut changed = false;
        for i in m.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
        {
            if let Rvalue::MatrixView {
                source,
                mutable,
                transpose,
                descriptor,
            } = &mut i.value
            {
                match case {
                    0 => std::mem::swap(&mut descriptor.rows, &mut descriptor.columns),
                    1 => descriptor.row_stride = MatrixViewField::Rows,
                    2 => descriptor.column_stride = MatrixViewField::One,
                    3 => *mutable = !*mutable,
                    4 => *transpose = !*transpose,
                    5 => {
                        i.value = Rvalue::View {
                            source: source.clone(),
                            mutable: *mutable,
                        };
                    }
                    _ => continue,
                }
                changed = true;
                break;
            }
            if case == 6
                && let Rvalue::Load(place) = &mut i.value
            {
                for p in &mut place.projections {
                    if let PlaceProjection::Index { semantics, .. } = p {
                        *semantics = IndexSemantics::ZeroBased;
                        changed = true;
                    }
                }
            }
        }
        assert!(changed, "MIR {case}");
        assert!(verify_mir(m).is_err(), "MIR accepted {case}");
        let mut s = ssa.clone();
        let mut changed = false;
        for i in s.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
        {
            if let SsaOp::MatrixView {
                source,
                mutable,
                transpose,
                descriptor,
            } = &mut i.op
            {
                match case {
                    0 => std::mem::swap(&mut descriptor.rows, &mut descriptor.columns),
                    1 => descriptor.row_stride = MatrixViewField::Rows,
                    2 => descriptor.column_stride = MatrixViewField::One,
                    3 => *mutable = !*mutable,
                    4 => *transpose = !*transpose,
                    5 => {
                        i.op = SsaOp::View {
                            source: source.clone(),
                            mutable: *mutable,
                        };
                    }
                    _ => continue,
                }
                changed = true;
                break;
            }
            if case == 6
                && let SsaOp::Load { place } = &mut i.op
            {
                for p in &mut place.projections {
                    if let SsaPlaceProjection::Index { semantics, .. } = p {
                        *semantics = IndexSemantics::ZeroBased;
                        changed = true;
                    }
                }
            }
        }
        assert!(changed, "SSA {case}");
        assert!(verify_ssa(s).is_err(), "SSA accepted {case}");
    }
}

#[test]
fn vertical24_projected_provenance_and_cross_module_rejections() {
    for source in [
        "int eat(Matrix<int> a){return 1;}int main(){Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);return v[usize(eat(a)),1];}",
        "int eat(Array<Matrix<int>> a){return 0;}int main(){Array<Matrix<int>> a={[1]};MatrixView<int> v=matrix_view(a[usize(eat(a))]);return 0;}",
        "int consume(Matrix<int> a){return 0;}int read(MatrixView<int> v,int x){return v[1,1];}int main(){Matrix<int> a=[1];return read(transpose_view(a),consume(a));}",
        "int main(){Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);return v[2,1];}",
        "int main(){Matrix<int> a=[1];MatrixView<int> v=transpose_view(a);return v[1,2];}",
        "int main(){Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);int i=1;return v[i,1];}",
        "int main(){Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);MatrixView<int> u=matrix_view(a);v=u;return 0;}",
        "int grow(MatrixViewMut<List<int>> v){push(v[1,1],42);return 0;}int main(){Matrix<List<int>> a=[{1}];ref int x=&a[1,1][0];grow(matrix_view_mut(a));return *x;}",
        "int bad(MatrixViewMut<List<int>> v){ref int x=&v[1,1][0];MatrixViewMut<List<int>> w=v;push(w[1,1],42);return *x;}int main(){return 0;}",
        "int grow(ref MatrixViewMut<List<int>> r){MatrixViewMut<List<int>> v=*r;push(v[1,1],42);return 0;}int main(){Matrix<List<int>> a=[{1}];MatrixViewMut<List<int>> v=matrix_view_mut(a);ref int x=&a[1,1][0];grow(&v);return *x;}",
        "enum E{V(MatrixView<int>)}int main(){return 0;}",
        "int inspect<V:Copy>(V v){return 0;}int main(){Matrix<int> a=[1];return inspect<MatrixView<int>>(matrix_view(a));}",
    ] {
        assert!(
            compile_source(&SourceFile::new("bad.ae", source), &[]).is_err(),
            "accepted {source}"
        );
    }
    let directory = temporary("v24-modules");
    fs::create_dir_all(&directory).unwrap();
    fs::write(directory.join("helper.ae"),"int read(MatrixView<int> v){return v[1,1];}int write(MatrixViewMut<int> v){v[1,1]=42;return 0;}").unwrap();
    for source in [
        "import helper;int main(){Matrix<int> a=[1];return helper.read(a);}",
        "import helper;int main(){Array<int> a={1};return helper.read(view(a));}",
        "import helper;int main(){Matrix<int> a=[1];return helper.write(matrix_view(a));}",
        "import helper;int main(){Matrix<double> a=[1];return helper.read(matrix_view(a));}",
    ] {
        fs::write(directory.join("main.ae"), source).unwrap();
        assert!(
            compile_session(
                CompilationSession::discover(&directory.join("main.ae")).unwrap(),
                &[]
            )
            .is_err(),
            "accepted {source}"
        );
    }
    fs::remove_dir_all(directory).unwrap();
    let compiled = compile_source(
        &SourceFile::new(
            "view-only.ae",
            "int read(MatrixView<int> v){return v[1,1];}int main(){return 0;}",
        ),
        &[],
    )
    .unwrap();
    assert!(compiled.llvm.contains("@aether_matrix_view_index_"));
    assert!(!compiled.llvm.contains("@malloc"));
    assert!(!compiled.llvm.contains("@free"));
    compile_source(&SourceFile::new("symbolic.ae","int shape<T:Storable>(ref Matrix<T> a){MatrixView<T> v=matrix_view(*a);return int(rows(v));}int main(){Matrix<Buffer<int>> a=[Buffer<int>(1,2)];return shape(&a)-1;}"),&[]).unwrap();
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical25_native_mapping_borrows_and_heap_counts() {
    for (name, heap) in [
        ("normal", 1),
        ("column", 1),
        ("column_mut", 1),
        ("mutable", 1),
        ("transpose", 2),
        ("transpose_mut", 1),
        ("double", 1),
        ("empty", 0),
        ("owning", 3),
        ("projected", 5),
        ("refs", 1),
        ("copy", 1),
        ("scope", 1),
        ("generic", 1),
    ] {
        let compiled = compile_session(
            CompilationSession::discover(&program(&format!("v25_vector_view_{name}.ae"))).unwrap(),
            &[],
        )
        .unwrap_or_else(|e| panic!("{name}: {e:?}"));
        assert_eq!(
            v23_execute(&v23_heap_guard(&compiled.llvm, heap)).code(),
            Some(0),
            "{name}"
        );
    }
    let compiled = compile_session(
        CompilationSession::discover(&module_program("v25_vector_views")).unwrap(),
        &[],
    )
    .unwrap();
    assert_eq!(
        v23_execute(&v23_heap_guard(&compiled.llvm, 1)).code(),
        Some(0)
    );
}

#[test]
fn vertical25_identity_and_deterministic_ir() {
    use aether_frontend::{IndexSemantics, TypeArena, TypeId};
    let mut types = TypeArena::new();
    let v = types.intern_vector_view(TypeId::INT64, aether_frontend::Orientation::Row, false);
    let w = types.intern_vector_view(TypeId::INT64, aether_frontend::Orientation::Row, true);
    assert_eq!(
        v,
        types.intern_vector_view(TypeId::INT64, aether_frontend::Orientation::Row, false)
    );
    assert_ne!(v, w);
    assert_ne!(
        v,
        types.intern_vector_view(TypeId::INT64, aether_frontend::Orientation::Column, false)
    );
    assert_ne!(v, types.intern_matrix_view(TypeId::INT64, false));
    for t in [v, w] {
        assert_ne!(
            t,
            types.intern_vector(TypeId::INT64, aether_frontend::Orientation::Row)
        );
        assert_ne!(t, types.intern_view(TypeId::INT64, false));
        assert_ne!(t, types.intern_view(TypeId::INT64, true));
        let p = types.properties(t).unwrap();
        assert!(p.is_copy && p.is_relocatable && !p.is_storable && !p.needs_drop);
        assert!(types.contains_view(t));
        assert_eq!(types.index_semantics(t), Some(IndexSemantics::OneBased));
        assert_eq!(
            layout_of(&types, t, TargetProperties::LINUX_X86_64, &[], &[])
                .unwrap()
                .size,
            24
        );
    }
    let source = SourceFile::new(
        "view.ae",
        fs::read_to_string(program("v25_vector_view_double.ae")).unwrap(),
    );
    let emits = [Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let first = compile_source(&source, &emits).unwrap();
    assert_eq!(first.dumps, compile_source(&source, &emits).unwrap().dumps);
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        for word in [
            "VectorView",
            "stride",
            "dimension",
            "OneBased",
            "transpose: true",
        ] {
            assert!(first.dumps[&phase].contains(word), "{phase:?}: {word}");
        }
    }
    assert!(!first.llvm.contains("noalias"));
    let helper = first
        .llvm
        .split("define internal ptr @aether_vector_view_index_")
        .nth(1)
        .unwrap()
        .split("\n}")
        .next()
        .unwrap();
    assert!(helper.find("upper_check:").unwrap() < helper.find("%index0 = sub").unwrap());
    assert!(helper.contains("mul i64 %index0, %stride"));
    assert!(!helper.contains("getelementptr inbounds"));
}

fn v25_zero_cost_guard(llvm: &str, heap: u64) -> String {
    let mut output = String::new();
    let mut count = 0;
    let mut inside = false;
    for line in llvm.lines() {
        if let Some(source) = line.trim().strip_prefix("; VectorViewBegin ") {
            assert!(!inside);
            inside = true;
            let (ty, value) = source.split_once('|').unwrap();
            for (suffix, global) in [("a", "heap_alloc"), ("f", "heap_free"), ("r", "relocation")] {
                writeln!(
                    output,
                    "  %qv{count}_{suffix}0 = load i64, ptr @aether_{global}_count"
                )
                .unwrap();
            }
            writeln!(output, "  %qv{count}_p0 = extractvalue {ty} {value}, 0").unwrap();
            writeln!(output, "  %qv{count}_d0 = extractvalue {ty} {value}, 1").unwrap();
            if ty == "{ ptr, i64, i64 }" {
                writeln!(output, "  %qv{count}_s0 = extractvalue {ty} {value}, 2").unwrap();
            } else {
                writeln!(output, "  %qv{count}_s0 = add i64 0, 1").unwrap();
            }
        } else if let Some(result) = line.trim().strip_prefix("; VectorViewEnd ") {
            assert!(inside);
            inside = false;
            for (suffix, global) in [("a", "heap_alloc"), ("f", "heap_free"), ("r", "relocation")] {
                writeln!(output,"  %qv{count}_{suffix}1 = load i64, ptr @aether_{global}_count\n  %qv{count}_{suffix}ok = icmp eq i64 %qv{count}_{suffix}0, %qv{count}_{suffix}1").unwrap();
            }
            writeln!(output,"  %qv{count}_p1 = extractvalue {{ ptr, i64, i64 }} {result}, 0\n  %qv{count}_pok = icmp eq ptr %qv{count}_p0, %qv{count}_p1\n  %qv{count}_af = and i1 %qv{count}_aok, %qv{count}_fok\n  %qv{count}_rp = and i1 %qv{count}_rok, %qv{count}_pok\n  %qv{count}_ok = and i1 %qv{count}_af, %qv{count}_rp\n  %qv{count}_prior = load i1, ptr @v25_ok\n  %qv{count}_all = and i1 %qv{count}_prior, %qv{count}_ok\n  store i1 %qv{count}_all, ptr @v25_ok\n  %qv{count}_seen = load i64, ptr @v25_seen\n  %qv{count}_next = add i64 %qv{count}_seen, 1\n  store i64 %qv{count}_next, ptr @v25_seen").unwrap();
            writeln!(output, "  %qv{count}_d1 = extractvalue {{ ptr, i64, i64 }} {result}, 1\n  %qv{count}_s1 = extractvalue {{ ptr, i64, i64 }} {result}, 2\n  %qv{count}_dok = icmp eq i64 %qv{count}_d0, %qv{count}_d1\n  %qv{count}_sok = icmp eq i64 %qv{count}_s0, %qv{count}_s1\n  %qv{count}_ds = and i1 %qv{count}_dok, %qv{count}_sok\n  %qv{count}_metadata = and i1 %qv{count}_all, %qv{count}_ds\n  store i1 %qv{count}_metadata, ptr @v25_ok").unwrap();
            count += 1;
        } else if line == "  %process_status = trunc i64 %aether_result to i32" {
            writeln!(output,"  %qv_ok = load i1, ptr @v25_ok\n  %qv_seen = load i64, ptr @v25_seen\n  %qv_ran = icmp ugt i64 %qv_seen, 0\n  %qv_a = load i64, ptr @aether_heap_alloc_count\n  %qv_f = load i64, ptr @aether_heap_free_count\n  %qv_r = load i64, ptr @aether_relocation_count\n  %qv_aok = icmp eq i64 %qv_a, {heap}\n  %qv_fok = icmp eq i64 %qv_f, {heap}\n  %qv_rok = icmp eq i64 %qv_r, 0\n  %qv_af = and i1 %qv_aok, %qv_fok\n  %qv_afr = and i1 %qv_af, %qv_rok\n  %qv_op = and i1 %qv_ok, %qv_ran\n  %qv_pass = and i1 %qv_afr, %qv_op\n  %qv_result = trunc i64 %aether_result to i32\n  %process_status = select i1 %qv_pass, i32 %qv_result, i32 99").unwrap();
        } else {
            if inside {
                assert!(
                    line.contains("extractvalue") || line.contains("insertvalue"),
                    "element/storage operation during view transform: {line}"
                );
            }
            writeln!(output, "{line}").unwrap();
        }
    }
    assert!(count > 0 && !inside);
    output.push_str("\n@v25_ok = internal global i1 true\n@v25_seen = internal global i64 0\n");
    output
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical25_each_view_has_zero_heap_relocation_and_pointer_delta() {
    for (name, heap) in [
        ("normal", 1),
        ("column", 1),
        ("column_mut", 1),
        ("mutable", 1),
        ("transpose", 2),
        ("transpose_mut", 1),
        ("double", 1),
        ("empty", 0),
        ("owning", 3),
        ("projected", 5),
        ("refs", 1),
        ("copy", 1),
        ("scope", 1),
        ("generic", 1),
    ] {
        let compiled = compile_source(
            &SourceFile::new(
                "cost.ae",
                fs::read_to_string(program(&format!("v25_vector_view_{name}.ae"))).unwrap(),
            ),
            &[],
        )
        .unwrap();
        assert_eq!(
            v23_execute(&v25_zero_cost_guard(&compiled.llvm, heap)).code(),
            Some(0),
            "{name}"
        );
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical25_mir_ssa_reject_corrupt_descriptor_contracts() {
    use aether_frontend::{IndexSemantics, VectorViewField};
    use aether_middle::{
        PlaceProjection, Rvalue, SsaOp, SsaPlaceProjection, build_ssa, lower_hir, verify_mir,
        verify_ssa,
    };
    let source = SourceFile::new(
        "corrupt.ae",
        "int main(){Vector<int,Row> a=[1,2,3];VectorView<int,Column> v=transpose_view(a);VectorView<int,Row> u=transpose_view(v);VectorView<int,Row> w=u;return w[2];}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = lower_hir(hir);
    let ssa = build_ssa(&verify_mir(mir.clone()).unwrap());
    for case in 0..7 {
        let mut m = mir.clone();
        let mut changed = false;
        for i in m.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
        {
            if let Rvalue::VectorView {
                source,
                mutable,
                transpose,
                descriptor,
            } = &mut i.value
            {
                match case {
                    0 => std::mem::swap(&mut descriptor.dimension, &mut descriptor.stride),
                    1 => descriptor.stride = VectorViewField::Dimension,
                    2 => descriptor.dimension = VectorViewField::One,
                    3 => *mutable = !*mutable,
                    4 => *transpose = !*transpose,
                    5 => {
                        i.value = Rvalue::View {
                            source: source.clone(),
                            mutable: *mutable,
                        };
                    }
                    _ => continue,
                }
                changed = true;
                break;
            }
            if case == 6
                && let Rvalue::Load(place) = &mut i.value
            {
                for p in &mut place.projections {
                    if let PlaceProjection::Index { semantics, .. } = p {
                        *semantics = IndexSemantics::ZeroBased;
                        changed = true;
                    }
                }
            }
        }
        assert!(changed, "MIR {case}");
        assert!(verify_mir(m).is_err(), "MIR accepted {case}");
        let mut s = ssa.clone();
        let mut changed = false;
        for i in s.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
        {
            if let SsaOp::VectorView {
                source,
                mutable,
                transpose,
                descriptor,
            } = &mut i.op
            {
                match case {
                    0 => std::mem::swap(&mut descriptor.dimension, &mut descriptor.stride),
                    1 => descriptor.stride = VectorViewField::Dimension,
                    2 => descriptor.dimension = VectorViewField::One,
                    3 => *mutable = !*mutable,
                    4 => *transpose = !*transpose,
                    5 => {
                        i.op = SsaOp::View {
                            source: source.clone(),
                            mutable: *mutable,
                        };
                    }
                    _ => continue,
                }
                changed = true;
                break;
            }
            if case == 6
                && let SsaOp::Load { place } = &mut i.op
            {
                for p in &mut place.projections {
                    if let SsaPlaceProjection::Index { semantics, .. } = p {
                        *semantics = IndexSemantics::ZeroBased;
                        changed = true;
                    }
                }
            }
        }
        assert!(changed, "SSA {case}");
        assert!(verify_ssa(s).is_err(), "SSA accepted {case}");
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical25_structured_diagnostics_and_owner_liveness() {
    for (body, code) in [
        (
            "Array<int> a={1};VectorView<int,Row> v=vector_view(a);",
            "E0338",
        ),
        (
            "Matrix<int> a=[1];VectorView<int,Row> v=vector_view(a);",
            "E0338",
        ),
        (
            "Array<int> a={1};VectorView<int,Row> v=transpose_view(a);",
            "E0336",
        ),
        (
            "Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);v[1]=2;",
            "E0288",
        ),
        (
            "Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);VectorViewMut<int,Row> w=vector_view_mut(v);",
            "E0339",
        ),
        (
            "Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);int x=v[1,1];",
            "E0334",
        ),
        (
            "Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);int x=v[0];",
            "E0296",
        ),
        (
            "Vector<int,Row> a=[1];VectorView<int,Column> v=transpose_view(a);int x=v[2];",
            "E0296",
        ),
        (
            "Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);a=[2];",
            "E0292",
        ),
        (
            "Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);consume(a);",
            "E0292",
        ),
        (
            "Vector<int,Row> a=[1];VectorViewMut<int,Row> v=vector_view_mut(a);consume(a);",
            "E0292",
        ),
        (
            "Vector<int,Row> a=[1];VectorView<int,Column> v=transpose_view(a);VectorView<int,Column> w=v;consume(a);",
            "E0292",
        ),
        (
            "Vector<int,Row> a=[1];VectorViewMut<int,Column> v=transpose_view_mut(a);VectorViewMut<int,Row> w=transpose_view_mut(v);consume(a);",
            "E0292",
        ),
        (
            "Vector<int,Row> a=[1];VectorViewMut<int,Row> v=vector_view_mut(a);VectorViewMut<int,Row> w=v;consume(a);",
            "E0292",
        ),
        (
            "Vector<int,Row> a=[1];VectorView<int,Row> v=VectorView<int,Row>(a,1,1);",
            "E0338",
        ),
    ] {
        let source =
            format!("int consume(Vector<int,Row> a){{return 0;}}int main(){{{body}return 0;}}");
        let errors = compile_source(&SourceFile::new("bad.ae", source), &[])
            .err()
            .unwrap_or_else(|| panic!("accepted {body}"));
        assert!(
            errors.iter().any(|d| d.code == code),
            "{body}: expected {code}: {errors:?}"
        );
    }
    for source in [
        "int main(){Vector<int,Row> a=[1];ref Vector<int,Row> r=&a;VectorViewMut<int,Row> v=vector_view_mut(*r);return 0;}",
        "int main(){Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);ref mut int x=&mut v[1];return 0;}",
        "int main(){Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);ref VectorView<int,Row> r=&v;ref mut int x=&mut (*r)[1];return 0;}",
        "int main(){Vector<int,Row> a=[1];VectorView<int,Column> v=vector_view(a);return 0;}",
        "int main(){Vector<int,Row> a=[1];VectorView<int,Row> v=transpose_view(a);return 0;}",
        "int main(){Vector<int,Row> a=[1];Vector<int,Column> b=a;return 0;}",
        "VectorView<int,Row> bad(){Vector<int,Row> a=[1];return vector_view(a);}int main(){return 0;}",
        "VectorViewMut<int,Row> bad(VectorViewMut<int,Row> v){return v;}int main(){return 0;}",
        "struct H{VectorView<int,Row> v;}int main(){return 0;}",
        "enum E{V(VectorViewMut<int,Column>)}int main(){return 0;}",
        "int main(){Array<VectorView<int,Row>> a={};return 0;}",
        "int main(){List<VectorViewMut<int,Column>> a={};return 0;}",
        "int main(){Matrix<VectorView<int,Row>> a=[];return 0;}",
        "int main(){Vector<VectorView<int,Row>,Column> a=[];return 0;}",
        "int main(){Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);int i=1;return v[i];}",
        "int main(){Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);bool i=true;return v[i];}",
        "int main(){Vector<Buffer<int>,Row> a=[Buffer<int>(1,2)];VectorView<Buffer<int>,Row> v=vector_view(a);Buffer<int> b=v[1];return 0;}",
        "int main(){Vector<Buffer<int>,Row> a=[Buffer<int>(1,2)];VectorViewMut<Buffer<int>,Row> v=vector_view_mut(a);v[1]=Buffer<int>(1,3);return 0;}",
        "int main(){Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);VectorView<int,Row> w=v;v=w;return 0;}",
        "int inspect<V:Copy>(V v){return 0;}int main(){Vector<int,Row> a=[1];return inspect<VectorView<int,Row>>(vector_view(a));}",
        "int main(){Vector<int,Row> a=[1];View<int> v=view(a);return 0;}",
        "int main(){Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);View<int> w=v;return 0;}",
        "int main(){Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);Vector<int,Column> w=transpose(v);return 0;}",
        "int main(){Vector<int,Row> a=[1];Vector<int,Column> b=transpose(a);return a[1];}",
        "int main(){Vector<int,Row> a=[1];VectorView<int> v=vector_view(a);return 0;}",
        "int main(){Vector<int,Row> a=[1];VectorView<int,int> v=vector_view(a);return 0;}",
    ] {
        assert!(
            compile_source(&SourceFile::new("bad.ae", source), &[]).is_err(),
            "accepted {source}"
        );
    }
}

#[test]
fn vertical25_nested_provenance_and_call_effects() {
    for source in [
        "struct H{Vector<int,Row> v;}int eat(H h){return 0;}int main(){H h=H([1]);VectorView<int,Row> v=vector_view(h.v);eat(h);return 0;}",
        "int main(){List<Vector<int,Row>> a={[1]};VectorView<int,Row> v=vector_view(a[0]);push(a,[2]);return 0;}",
        "int eat(Vector<int,Row> a){return 1;}int main(){Vector<int,Row> a=[1];VectorView<int,Row> v=vector_view(a);return v[usize(eat(a))];}",
        "int eat(Array<Vector<int,Row>> a){return 0;}int main(){Array<Vector<int,Row>> a={[1]};VectorView<int,Row> v=vector_view(a[usize(eat(a))]);return 0;}",
        "int eat(Vector<int,Row> a){return 0;}int read(VectorView<int,Column> v,int x){return v[1];}int main(){Vector<int,Row> a=[1];return read(transpose_view(a),eat(a));}",
        "int grow(VectorViewMut<List<int>,Row> v){push(v[1],42);return 0;}int main(){Vector<List<int>,Row> a=[{1}];ref int x=&a[1][0];grow(vector_view_mut(a));return *x;}",
        "int grow(ref VectorViewMut<List<int>,Row> r){VectorViewMut<List<int>,Row> v=*r;push(v[1],42);return 0;}int main(){Vector<List<int>,Row> a=[{1}];VectorViewMut<List<int>,Row> v=vector_view_mut(a);ref int x=&a[1][0];grow(&v);return *x;}",
        "int bad(ref MatrixViewMut<List<int>> r){MatrixViewMut<List<int>> v=*r;ref int x=&v[1,1][0];MatrixViewMut<List<int>> w=*r;push(w[1,1],42);return *x;}int main(){return 0;}",
        "int bad(ref VectorViewMut<List<int>,Row> r){VectorViewMut<List<int>,Row> v=*r;ref int x=&v[1][0];VectorViewMut<List<int>,Row> w=*r;push(w[1],42);return *x;}int main(){return 0;}",
        "int bad(VectorViewMut<List<int>,Row> v){ref int x=&v[1][0];VectorViewMut<List<int>,Column> w=transpose_view_mut(v);push(w[1],42);return *x;}int main(){return 0;}",
        "struct H{List<int> l;}int grow(VectorViewMut<H,Row> v){push(v[1].l,42);return 0;}int main(){Vector<H,Row> a=[H({1})];grow(vector_view_mut(a));return 0;}",
    ] {
        assert!(
            compile_source(&SourceFile::new("alias.ae", source), &[]).is_err(),
            "accepted {source}"
        );
    }
    let compiled = compile_source(
        &SourceFile::new(
            "only_view.ae",
            "int read(VectorView<int,Row> v){return v[1];}int main(){return 0;}",
        ),
        &[],
    )
    .unwrap();
    assert!(compiled.llvm.contains("@aether_vector_view_index_"));
    assert!(!compiled.llvm.contains("@malloc") && !compiled.llvm.contains("@free"));
    compile_source(&SourceFile::new("symbolic.ae", "int shape<T:Storable>(ref Vector<T,Row> a){VectorView<T,Row> v=vector_view(*a);return int(dimension(v));}int main(){Vector<Buffer<int>,Row> a=[Buffer<int>(1,2)];return shape(&a)-1;}"), &[]).unwrap();
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical25_runtime_bounds_orientations_and_capabilities() {
    use std::os::unix::process::ExitStatusExt;
    for orientation in ["Row", "Column"] {
        for (literal, dimension) in [("[]", 0), ("[1,2,3]", 3)] {
            for (ty, create, transpose) in [
                ("VectorView", "vector_view", false),
                ("VectorView", "transpose_view", true),
                ("VectorViewMut", "vector_view_mut", false),
                ("VectorViewMut", "transpose_view_mut", true),
            ] {
                let result_orientation = if transpose {
                    if orientation == "Row" {
                        "Column"
                    } else {
                        "Row"
                    }
                } else {
                    orientation
                };
                for index in [0, dimension + 1, u64::MAX] {
                    let operations = if ty == "VectorViewMut" {
                        vec![
                            "return v[i];",
                            "v[i]=42;return 0;",
                            "ref int x=&v[i];return *x;",
                            "ref mut int x=&mut v[i];*x=42;return 0;",
                        ]
                    } else {
                        vec!["return v[i];", "ref int x=&v[i];return *x;"]
                    };
                    for operation in operations {
                        let source = format!(
                            "int main(){{Vector<int,{orientation}> a={literal};{ty}<int,{result_orientation}> v={create}(a);usize i={index};{operation}}}"
                        );
                        let compiled =
                            compile_source(&SourceFile::new("bounds.ae", source), &[]).unwrap();
                        assert_eq!(
                            v23_execute(&compiled.llvm).signal(),
                            Some(4),
                            "{literal} {orientation} {create} {index} {operation}"
                        );
                    }
                }
            }
        }
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical25_nonunit_stride_backend_contract() {
    // Test-only verified backing: three logical elements at offsets 0, S, 2S.
    // There is deliberately no source-level descriptor/stride constructor.
    let compiled = compile_source(&SourceFile::new("stride.ae", "int probe(VectorViewMut<int,Row> v){VectorViewMut<int,Column> t=transpose_view_mut(v);VectorView<int,Row> back=transpose_view(t);ref int first=&back[1];ref mut int last=&mut t[3];*last=40;return *first+back[3]+int(dimension(t))-45;}int main(){return 0;}"), &[]).unwrap();
    let symbol = compiled
        .llvm
        .lines()
        .find(|line| line.starts_with("define i64 @") && line.contains("{ ptr, i64, i64 }"))
        .unwrap()
        .split('@')
        .nth(1)
        .unwrap()
        .split('(')
        .next()
        .unwrap();
    for stride in [2, 3, 5] {
        let count = 2 * stride + 1;
        let harness = format!(
            "  %backing = alloca [{count} x i64]\n  store [{count} x i64] zeroinitializer, ptr %backing\n  store i64 2, ptr %backing\n  %descriptor0 = insertvalue {{ ptr, i64, i64 }} poison, ptr %backing, 0\n  %descriptor1 = insertvalue {{ ptr, i64, i64 }} %descriptor0, i64 3, 1\n  %descriptor2 = insertvalue {{ ptr, i64, i64 }} %descriptor1, i64 {stride}, 2\n  %probe_result = call i64 @{symbol}({{ ptr, i64, i64 }} %descriptor2)\n  %last_ptr = getelementptr i64, ptr %backing, i64 {}\n  %last_value = load i64, ptr %last_ptr\n  %last_ok = icmp eq i64 %last_value, 40\n  %probe_status = trunc i64 %probe_result to i32\n  %process_status = select i1 %last_ok, i32 %probe_status, i32 99",
            2 * stride
        );
        let llvm = compiled.llvm.replace(
            "  %process_status = trunc i64 %aether_result to i32",
            &harness,
        );
        assert_ne!(llvm, compiled.llvm);
        assert_eq!(v23_execute(&llvm).code(), Some(0), "stride {stride}");
    }
}

#[test]
fn vertical25_cross_module_type_capability_rejections() {
    let directory = temporary("v25-modules");
    fs::create_dir_all(&directory).unwrap();
    fs::write(directory.join("helper.ae"), "int read(VectorView<int,Row> v){return v[1];}int write(VectorViewMut<int,Column> v){v[1]=42;return 0;}").unwrap();
    for source in [
        "import helper;int main(){Vector<int,Row> a=[1];return helper.write(transpose_view(a));}",
        "import helper;int main(){Vector<int,Row> a=[1];return helper.read(transpose_view(a));}",
        "import helper;int main(){Vector<double,Row> a=[1];return helper.read(vector_view(a));}",
        "import helper;int main(){Array<int> a={1};return helper.read(view(a));}",
    ] {
        fs::write(directory.join("main.ae"), source).unwrap();
        assert!(
            compile_session(
                CompilationSession::discover(&directory.join("main.ae")).unwrap(),
                &[]
            )
            .is_err(),
            "accepted {source}"
        );
    }
    fs::remove_dir_all(directory).unwrap();
}

#[test]
fn vertical25_mir_ssa_reject_mutable_from_shared_with_matching_result() {
    use aether_frontend::VectorViewDescriptor;
    use aether_middle::{
        Rvalue, SsaOp, SsaOperand, SsaPlace, SsaPlaceBase, build_ssa, lower_hir, verify_mir,
        verify_ssa,
    };
    let source = SourceFile::new(
        "capability.ae",
        "int main(){Vector<int,Row> a=[1];VectorView<int,Row> shared=vector_view(a);VectorViewMut<int,Column> writable=transpose_view_mut(a);return writable[1];}",
    );
    let mut mir = lower_hir(analyze(parse_source(&source).unwrap()).unwrap());
    let mut ssa = build_ssa(&verify_mir(mir.clone()).unwrap());
    let mut shared_place = None;
    let mut changed = false;
    for instruction in mir.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|b| &mut b.instructions)
    {
        match &mut instruction.value {
            Rvalue::VectorView { mutable: false, .. } => {
                shared_place = Some(instruction.destination.clone());
            }
            Rvalue::VectorView {
                source,
                mutable: true,
                descriptor,
                ..
            } => {
                *source = shared_place.clone().unwrap();
                *descriptor = VectorViewDescriptor::derived(true);
                changed = true;
            }
            _ => {}
        }
    }
    assert!(changed);
    let errors = verify_mir(mir).unwrap_err();
    assert!(
        errors
            .iter()
            .any(|e| e.message.contains("capability contract")),
        "{errors:?}"
    );
    let mut shared_value = None;
    let mut changed = false;
    for instruction in ssa.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|b| &mut b.instructions)
    {
        match &mut instruction.op {
            SsaOp::VectorView { mutable: false, .. } => shared_value = Some(instruction.result),
            SsaOp::VectorView {
                source,
                mutable: true,
                descriptor,
                ..
            } => {
                *source = SsaPlace {
                    base: SsaPlaceBase::Value(SsaOperand::Value(shared_value.unwrap())),
                    projections: vec![],
                };
                *descriptor = VectorViewDescriptor::derived(true);
                changed = true;
            }
            _ => {}
        }
    }
    assert!(changed);
    let errors = verify_ssa(ssa).unwrap_err();
    assert!(
        errors
            .iter()
            .any(|e| e.message.contains("capability contract")),
        "{errors:?}"
    );
}

const V26_FIXTURES: &[(&str, u64)] = &[
    ("row", 1),
    ("column", 1),
    ("row_mut", 1),
    ("column_mut", 1),
    ("normal", 1),
    ("transpose_row", 1),
    ("transpose_column", 1),
    ("transpose_mut", 1),
    ("owning", 5),
    ("projected", 5),
    ("refs", 1),
    ("copy", 1),
    ("scope", 1),
    ("generic", 3),
    ("control_flow", 1),
    ("evaluation", 3),
];

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical26_native_mapping_borrows_and_heap_counts() {
    for &(name, heap) in V26_FIXTURES {
        let compiled = compile_session(
            CompilationSession::discover(&program(&format!("v26_matrix_axis_{name}.ae"))).unwrap(),
            &[],
        )
        .unwrap_or_else(|e| panic!("{name}: {e:?}"));
        assert_eq!(
            v23_execute(&v23_heap_guard(&compiled.llvm, heap)).code(),
            Some(0),
            "{name}"
        );
    }
    let compiled = compile_session(
        CompilationSession::discover(&module_program("v26_matrix_axes")).unwrap(),
        &[],
    )
    .unwrap();
    assert_eq!(
        v23_execute(&v23_heap_guard(&compiled.llvm, 1)).code(),
        Some(0)
    );
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical26_structured_diagnostics_and_provenance() {
    for (body, code) in [
        (
            "Vector<int,Row> a=[1];VectorView<int,Row> r=row(a,1);",
            "E0340",
        ),
        (
            "Array<int> a={1};VectorView<int,Column> c=column(a,1);",
            "E0340",
        ),
        ("Matrix<int> a=[1];VectorView<int,Row> r=row(a);", "E0340"),
        (
            "Matrix<int> a=[1];VectorView<int,Row> r=row<int>(a,1);",
            "E0340",
        ),
        (
            "Matrix<int> a=[1];VectorView<int,Column> c=column(a,1,1);",
            "E0340",
        ),
        (
            "Matrix<int> a=[1];MatrixView<int> v=matrix_view(a);VectorViewMut<int,Row> r=row_mut(v,1);",
            "E0341",
        ),
        (
            "Matrix<int> a=[1];ref Matrix<int> p=&a;VectorViewMut<int,Column> c=column_mut(*p,1);",
            "E0272",
        ),
        (
            "Matrix<int> a=[1];MatrixViewMut<int> v=matrix_view_mut(a);ref MatrixViewMut<int> p=&v;VectorViewMut<int,Row> r=row_mut(*p,1);",
            "E0272",
        ),
        ("Matrix<int> a=[1];VectorView<int,Row> r=row(a,0);", "E0296"),
        ("Matrix<int> a=[1];VectorView<int,Row> r=row(a,2);", "E0296"),
        (
            "Matrix<int> a=[1];VectorView<int,Column> c=column(a,0);",
            "E0296",
        ),
        (
            "Matrix<int> a=[1];VectorView<int,Column> c=column(a,2);",
            "E0296",
        ),
        ("Matrix<int> a=[];VectorView<int,Row> r=row(a,1);", "E0296"),
        (
            "Matrix<int> a=[];VectorView<int,Column> c=column(a,1);",
            "E0296",
        ),
        (
            "Matrix<int> a=[1,2,3;4,5,6];MatrixView<int> t=transpose_view(a);VectorView<int,Column> c=column(t,3);",
            "E0296",
        ),
        (
            "Matrix<int> a=[1];VectorView<int,Row> r=row(a,1);r[1]=2;",
            "E0288",
        ),
        (
            "Matrix<int> a=[1];VectorView<int,Row> r=row(a,1);consume(a);",
            "E0292",
        ),
        (
            "Matrix<int> a=[1];VectorViewMut<int,Column> c=column_mut(a,1);consume(a);",
            "E0292",
        ),
        (
            "Matrix<int> a=[1];MatrixView<int> t=transpose_view(a);VectorView<int,Row> r=row(t,1);VectorView<int,Row> copy=r;consume(a);",
            "E0292",
        ),
        (
            "Matrix<int> a=[1];VectorView<int,Row> r=row(a,1);a=[2];",
            "E0292",
        ),
        (
            "Matrix<int> a=[1];VectorView<int,Row> r=row(a,1);VectorView<int,Row> v=r;r=v;",
            "E0277",
        ),
        (
            "Matrix<int> a=[1];VectorView<int,Row> r=row(a,usize(consume(a)));",
            "E0292",
        ),
        (
            "List<Matrix<int>> a={[1]};VectorView<int,Row> r=row(a[0],1);push(a,[2]);",
            "E0313",
        ),
    ] {
        let source =
            format!("int consume(Matrix<int> a){{return 1;}}int main(){{{body}return 0;}}");
        let errors = compile_source(&SourceFile::new("bad.ae", source), &[])
            .err()
            .unwrap_or_else(|| panic!("accepted {body}"));
        assert!(
            errors.iter().any(|e| e.code == code),
            "expected {code}: {body}: {errors:?}"
        );
    }
    for source in [
        "int main(){Matrix<int> a=[1];int i=1;VectorView<int,Row> r=row(a,i);return 0;}",
        "int main(){Matrix<int> a=[1];VectorView<int,Row> r=row(a,true);return 0;}",
        "int main(){Matrix<int> a=[1];VectorView<int,Column> r=row(a,1);return 0;}",
        "int main(){Matrix<int> a=[1];VectorViewMut<int,Row> r=row(a,1);return 0;}",
        "int main(){Matrix<int> a=[1];View<int> r=row(a,1);return 0;}",
        "int main(){Matrix<int> a=[1];Vector<int,Row> r=row(a,1);return 0;}",
        "int main(){Matrix<int> a=[1];VectorView<int,Column> r=transpose_view(row(a,1));return 0;}",
        "VectorView<int,Row> bad(){Matrix<int> a=[1];return row(a,1);}int main(){return 0;}",
        "struct H{VectorView<int,Row> v;}int main(){return 0;}",
        "int main(){Matrix<int> a=[1];Array<VectorView<int,Column>> c={column(a,1)};return 0;}",
        "int main(){Matrix<Buffer<int>> a=[Buffer<int>(1,1)];VectorView<Buffer<int>,Row> r=row(a,1);Buffer<int> b=r[1];return 0;}",
        "int main(){Matrix<Buffer<int>> a=[Buffer<int>(1,1)];VectorViewMut<Buffer<int>,Row> r=row_mut(a,1);r[1]=Buffer<int>(1,2);return 0;}",
        "int eat(Array<Matrix<int>> a){return 0;}int main(){Array<Matrix<int>> a={[1]};VectorView<int,Row> r=row(a[usize(eat(a))],1);return 0;}",
        "int grow(ref mut List<Matrix<int>> a){push(*a,[2]);return 1;}int main(){List<Matrix<int>> a={[1]};VectorView<int,Row> r=row(a[0],usize(grow(&mut a)));return 0;}",
        "int grow(VectorViewMut<List<int>,Row> r){push(r[1],2);return 0;}int main(){Matrix<List<int>> a=[{1}];grow(row_mut(a,1));return 0;}",
        "int grow(ref VectorViewMut<List<int>,Row> r){VectorViewMut<List<int>,Row> c=*r;push(c[1],2);return 0;}int main(){Matrix<List<int>> a=[{1}];VectorViewMut<List<int>,Row> r=row_mut(a,1);grow(&r);return 0;}",
        "int main(){Matrix<List<int>> a=[{1}];MatrixViewMut<List<int>> t=transpose_view_mut(a);VectorViewMut<List<int>,Row> r=row_mut(t,1);ref VectorViewMut<List<int>,Row> p=&r;VectorViewMut<List<int>,Row> c=*p;ref int x=&r[1][0];push(c[1],2);return *x;}",
        "int bad(MatrixViewMut<List<int>> t){VectorViewMut<List<int>,Column> c=column_mut(t,1);ref int x=&c[1][0];VectorViewMut<List<int>,Column> copy=c;push(copy[1],2);return *x;}int main(){return 0;}",
        "int eat(Matrix<int> a){return 0;}int read(VectorView<int,Row> r,int x){return r[1];}int main(){Matrix<int> a=[1];return read(row(a,1),eat(a));}",
        "int main(){Matrix<int> a=[1];Matrix<int> b=transpose(a);return 0;}",
    ] {
        assert!(
            compile_source(&SourceFile::new("bad.ae", source), &[]).is_err(),
            "accepted {source}"
        );
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical26_mir_ssa_reject_corrupt_recipes() {
    use aether_frontend::{MatrixViewField, Orientation};
    use aether_middle::{Rvalue, SsaOp, TrapKind, build_ssa, lower_hir, verify_mir, verify_ssa};
    // Both axes: corrupt selectors individually, orientation, capability, index,
    // source rank, raw-View substitution, and the structured trap.
    for (operation, orientation) in [("row", "Row"), ("column", "Column")] {
        let source = SourceFile::new(
            "corrupt.ae",
            format!(
                "int main(){{Matrix<int> a=[1,2;3,4];VectorView<int,{orientation}> r={operation}(a,1);return r[1];}}"
            ),
        );
        let hir = analyze(parse_source(&source).unwrap()).unwrap();
        let mir = lower_hir(hir.clone());
        let ssa = build_ssa(&verify_mir(mir.clone()).unwrap());
        for case in 0..10 {
            let mut m = mir.clone();
            let instruction = m.functions[0]
                .blocks
                .iter_mut()
                .flat_map(|b| &mut b.instructions)
                .find(|i| matches!(i.value, Rvalue::MatrixAxisVectorView { .. }))
                .unwrap();
            let Rvalue::MatrixAxisVectorView {
                source,
                fixed_index,
                axis,
                mutable,
                descriptor,
                bounds_trap,
            } = &mut instruction.value
            else {
                panic!()
            };
            match case {
                0 => descriptor.fixed_extent = MatrixViewField::One,
                1 => {
                    descriptor.base_stride = if *axis == Orientation::Row {
                        MatrixViewField::ColumnStride
                    } else {
                        MatrixViewField::RowStride
                    }
                }
                2 => descriptor.dimension = descriptor.fixed_extent,
                3 => descriptor.stride = descriptor.base_stride,
                4 => *axis = axis.transposed(),
                5 => *mutable = true,
                6 => *fixed_index = aether_middle::Operand::Bool(true),
                7 => source.base = aether_middle::PlaceBase::Local(aether_frontend::LocalId(9999)),
                8 => {
                    instruction.value = Rvalue::View {
                        source: source.clone(),
                        mutable: false,
                    }
                }
                9 => *bounds_trap = TrapKind::IntegerOverflow,
                _ => unreachable!(),
            }
            assert!(verify_mir(m).is_err(), "MIR accepted {operation} {case}");
            let mut s = ssa.clone();
            let instruction = s.functions[0]
                .blocks
                .iter_mut()
                .flat_map(|b| &mut b.instructions)
                .find(|i| matches!(i.op, SsaOp::MatrixAxisVectorView { .. }))
                .unwrap();
            let SsaOp::MatrixAxisVectorView {
                source,
                fixed_index,
                axis,
                mutable,
                descriptor,
                bounds_trap,
            } = &mut instruction.op
            else {
                panic!()
            };
            match case {
                0 => descriptor.fixed_extent = MatrixViewField::One,
                1 => {
                    descriptor.base_stride = if *axis == Orientation::Row {
                        MatrixViewField::ColumnStride
                    } else {
                        MatrixViewField::RowStride
                    }
                }
                2 => descriptor.dimension = descriptor.fixed_extent,
                3 => descriptor.stride = descriptor.base_stride,
                4 => *axis = axis.transposed(),
                5 => *mutable = true,
                6 => *fixed_index = aether_middle::SsaOperand::Bool(true),
                7 => {
                    source.base =
                        aether_middle::SsaPlaceBase::Value(aether_middle::SsaOperand::Bool(true));
                }
                8 => {
                    instruction.op = SsaOp::View {
                        source: source.clone(),
                        mutable: false,
                    }
                }
                9 => *bounds_trap = TrapKind::IntegerOverflow,
                _ => unreachable!(),
            }
            assert!(verify_ssa(s).is_err(), "SSA accepted {operation} {case}");
        }
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical26_runtime_fixed_axis_and_result_bounds() {
    use std::os::unix::process::ExitStatusExt;
    for (literal, rows, columns) in [
        ("[]", 0, 0),
        ("[1,2,3]", 1, 3),
        ("[1;2;3]", 3, 1),
        ("[1,2,3;4,5,6]", 2, 3),
    ] {
        for (setup, target, transposed) in [
            ("", "a", false),
            ("MatrixView<int> v=matrix_view(a);", "v", false),
            ("MatrixView<int> v=transpose_view(a);", "v", true),
            ("MatrixViewMut<int> v=matrix_view_mut(a);", "v", false),
            ("MatrixViewMut<int> v=transpose_view_mut(a);", "v", true),
        ] {
            for operation in ["row", "column", "row_mut", "column_mut"] {
                if operation.ends_with("_mut") && setup.contains("MatrixView<int>") {
                    continue;
                }
                let row = operation.starts_with("row");
                let orientation = if row { "Row" } else { "Column" };
                let view = if operation.ends_with("_mut") {
                    "VectorViewMut"
                } else {
                    "VectorView"
                };
                let (r, c) = if transposed {
                    (columns, rows)
                } else {
                    (rows, columns)
                };
                let extent = if row { r } else { c };
                for index in [0, extent + 1, u64::MAX] {
                    let source = format!(
                        "int main(){{Matrix<int> a={literal};{setup}usize i={index};{view}<int,{orientation}> x={operation}({target},i);return int(dimension(x));}}"
                    );
                    let compiled =
                        compile_source(&SourceFile::new("bounds.ae", source), &[]).unwrap();
                    assert_eq!(
                        v23_execute(&compiled.llvm).signal(),
                        Some(4),
                        "{literal} {setup} {operation} {index}"
                    );
                }
                // Projection validates only the fixed axis; V25 checks the remaining axis.
                if extent > 0 {
                    let dimension = if row { c } else { r };
                    for index in [0, dimension + 1, u64::MAX] {
                        let access = if operation.ends_with("_mut") {
                            "x[k]=99;return 0;"
                        } else {
                            "return x[k];"
                        };
                        let source = format!(
                            "int main(){{Matrix<int> a={literal};{setup}{view}<int,{orientation}> x={operation}({target},1);usize k={index};{access}}}"
                        );
                        let compiled =
                            compile_source(&SourceFile::new("bounds.ae", source), &[]).unwrap();
                        assert_eq!(
                            v23_execute(&compiled.llvm).signal(),
                            Some(4),
                            "result {literal} {setup} {operation} {index}"
                        );
                    }
                }
            }
        }
    }
}

#[test]
fn vertical26_deterministic_ir_and_ordered_bounds() {
    let source = SourceFile::new(
        "dump.ae",
        fs::read_to_string(program("v26_matrix_axis_transpose_mut.ae")).unwrap(),
    );
    let emits = [Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let first = compile_source(&source, &emits).unwrap();
    assert_eq!(first.dumps, compile_source(&source, &emits).unwrap().dumps);
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        for word in [
            "MatrixAxisVectorView",
            "fixed_index",
            "axis: Row",
            "axis: Column",
            "mutable: true",
            "fixed_extent",
            "base_stride",
            "dimension",
            "stride",
            "VectorView",
        ] {
            assert!(
                first.dumps[&phase].contains(word),
                "{phase:?}: missing {word}"
            );
        }
    }
    for phase in [Emit::Mir, Emit::Ssa] {
        assert!(first.dumps[&phase].contains("IndexOutOfBounds"));
    }
    for section in first.llvm.split("; MatrixAxisVectorViewBegin ").skip(1) {
        let section = section.split("; MatrixAxisVectorViewEnd").next().unwrap();
        assert!(section.find("icmp uge").unwrap() < section.find("icmp ule").unwrap());
        assert!(section.find("icmp ule").unwrap() < section.find(" = sub i64").unwrap());
        assert!(section.find(" = sub i64").unwrap() < section.find(" = mul i64").unwrap());
        assert!(section.find(" = mul i64").unwrap() < section.find("getelementptr").unwrap());
        assert!(
            !section.contains("inbounds") && !section.contains("nsw") && !section.contains("nuw")
        );
        assert!(section.contains("insertvalue { ptr, i64, i64 }"));
        assert!(section.contains("trap_index_out_of_bounds"));
    }
    assert!(!first.llvm.contains("noalias"));
    let compiled=compile_source(&SourceFile::new("view-only.ae","int read(MatrixView<int> a,usize i){VectorView<int,Row> r=row(a,i);return r[1];}int main(){return 0;}"),&[]).unwrap();
    assert!(!compiled.llvm.contains("@malloc") && !compiled.llvm.contains("@free"));
}

// Independently derive the expected projection from the source descriptor,
// then check pointer/dimension/stride and each operation's heap counters.
#[allow(clippy::too_many_lines)]
fn v26_zero_cost_guard(llvm: &str, heap: u64) -> String {
    let mut output = String::new();
    let mut count = 0;
    let mut source_fields: Option<Vec<String>> = None;
    for line in llvm.lines() {
        if let Some(source) = line.trim().strip_prefix("; MatrixAxisVectorViewBegin ") {
            assert!(source_fields.is_none());
            source_fields = Some(source.split('|').map(str::to_string).collect());
            for (suffix, global) in [("a", "heap_alloc"), ("f", "heap_free"), ("r", "relocation")] {
                writeln!(
                    output,
                    "  %ax{count}_{suffix}0 = load i64, ptr @aether_{global}_count"
                )
                .unwrap();
            }
        } else if let Some(result) = line.trim().strip_prefix("; MatrixAxisVectorViewEnd ") {
            let fields = source_fields.take().unwrap();
            let (ty, value, axis, index, element) =
                (&fields[0], &fields[1], &fields[2], &fields[3], &fields[4]);
            for (suffix, global) in [("a", "heap_alloc"), ("f", "heap_free"), ("r", "relocation")] {
                writeln!(output,"  %ax{count}_{suffix}1 = load i64, ptr @aether_{global}_count\n  %ax{count}_{suffix}ok = icmp eq i64 %ax{count}_{suffix}0, %ax{count}_{suffix}1").unwrap();
            }
            writeln!(output,"  %ax{count}_p0 = extractvalue {ty} {value}, 0\n  %ax{count}_rows = extractvalue {ty} {value}, 1\n  %ax{count}_columns = extractvalue {ty} {value}, 2").unwrap();
            if ty == "{ ptr, i64, i64 }" {
                writeln!(output,"  %ax{count}_rs = add i64 0, %ax{count}_columns\n  %ax{count}_cs = add i64 0, 1").unwrap();
            } else {
                writeln!(output,"  %ax{count}_rs = extractvalue {ty} {value}, 3\n  %ax{count}_cs = extractvalue {ty} {value}, 4").unwrap();
            }
            let (base, dimension, stride) = if axis == "Row" {
                ("rs", "columns", "cs")
            } else {
                ("cs", "rows", "rs")
            };
            writeln!(output,"  %ax{count}_i0 = sub i64 {index}, 1\n  %ax{count}_offset = mul i64 %ax{count}_i0, %ax{count}_{base}\n  %ax{count}_expected = getelementptr {element}, ptr %ax{count}_p0, i64 %ax{count}_offset\n  %ax{count}_p1 = extractvalue {{ ptr, i64, i64 }} {result}, 0\n  %ax{count}_d1 = extractvalue {{ ptr, i64, i64 }} {result}, 1\n  %ax{count}_s1 = extractvalue {{ ptr, i64, i64 }} {result}, 2\n  %ax{count}_pok = icmp eq ptr %ax{count}_expected, %ax{count}_p1\n  %ax{count}_dok = icmp eq i64 %ax{count}_{dimension}, %ax{count}_d1\n  %ax{count}_sok = icmp eq i64 %ax{count}_{stride}, %ax{count}_s1").unwrap();
            writeln!(output,"  %ax{count}_af = and i1 %ax{count}_aok, %ax{count}_fok\n  %ax{count}_rp = and i1 %ax{count}_rok, %ax{count}_pok\n  %ax{count}_ds = and i1 %ax{count}_dok, %ax{count}_sok\n  %ax{count}_afrp = and i1 %ax{count}_af, %ax{count}_rp\n  %ax{count}_ok = and i1 %ax{count}_afrp, %ax{count}_ds\n  %ax{count}_prior = load i1, ptr @v26_ok\n  %ax{count}_all = and i1 %ax{count}_prior, %ax{count}_ok\n  store i1 %ax{count}_all, ptr @v26_ok\n  %ax{count}_seen = load i64, ptr @v26_seen\n  %ax{count}_next = add i64 %ax{count}_seen, 1\n  store i64 %ax{count}_next, ptr @v26_seen").unwrap();
            count += 1;
        } else if line == "  %process_status = trunc i64 %aether_result to i32" {
            writeln!(output,"  %ax_ok = load i1, ptr @v26_ok\n  %ax_seen = load i64, ptr @v26_seen\n  %ax_ran = icmp ugt i64 %ax_seen, 0\n  %ax_a = load i64, ptr @aether_heap_alloc_count\n  %ax_f = load i64, ptr @aether_heap_free_count\n  %ax_r = load i64, ptr @aether_relocation_count\n  %ax_aok = icmp eq i64 %ax_a, {heap}\n  %ax_fok = icmp eq i64 %ax_f, {heap}\n  %ax_rok = icmp eq i64 %ax_r, 0\n  %ax_af = and i1 %ax_aok, %ax_fok\n  %ax_afr = and i1 %ax_af, %ax_rok\n  %ax_op = and i1 %ax_ok, %ax_ran\n  %ax_pass = and i1 %ax_afr, %ax_op\n  %ax_result = trunc i64 %aether_result to i32\n  %process_status = select i1 %ax_pass, i32 %ax_result, i32 99").unwrap();
        } else {
            if source_fields.is_some() {
                assert!(
                    [
                        "extractvalue",
                        "insertvalue",
                        "icmp",
                        "br i1",
                        " = sub i64",
                        " = mul i64",
                        "getelementptr"
                    ]
                    .iter()
                    .any(|op| line.contains(op))
                        || line.ends_with(':'),
                    "unexpected element/storage operation: {line}"
                );
                assert!(
                    !line.contains("inbounds")
                        && !line.contains(" call ")
                        && !line.contains(" load ")
                        && !line.contains(" store ")
                );
            }
            writeln!(output, "{line}").unwrap();
        }
    }
    assert!(count > 0 && source_fields.is_none());
    output.push_str("\n@v26_ok = internal global i1 true\n@v26_seen = internal global i64 0\n");
    output
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn vertical26_each_projection_zero_cost_and_exact_pointer_metadata() {
    for &(name, heap) in V26_FIXTURES {
        let compiled = compile_session(
            CompilationSession::discover(&program(&format!("v26_matrix_axis_{name}.ae"))).unwrap(),
            &[],
        )
        .unwrap();
        assert_eq!(
            v23_execute(&v26_zero_cost_guard(&compiled.llvm, heap)).code(),
            Some(0),
            "{name}"
        );
    }
    let compiled = compile_session(
        CompilationSession::discover(&module_program("v26_matrix_axes")).unwrap(),
        &[],
    )
    .unwrap();
    assert_eq!(
        v23_execute(&v26_zero_cost_guard(&compiled.llvm, 1)).code(),
        Some(0)
    );
}

#[test]
fn vertical26_mir_ssa_reject_shared_source_with_matching_mutable_result() {
    use aether_middle::{
        Rvalue, SsaOp, SsaOperand, SsaPlace, SsaPlaceBase, build_ssa, lower_hir, verify_mir,
        verify_ssa,
    };
    for operation in ["row_mut", "column_mut"] {
        let orientation = if operation == "row_mut" {
            "Row"
        } else {
            "Column"
        };
        let source = SourceFile::new(
            "capability.ae",
            format!(
                "int main(){{Matrix<int> a=[1];MatrixView<int> shared=matrix_view(a);VectorViewMut<int,{orientation}> w={operation}(a,1);return w[1];}}"
            ),
        );
        let mut mir = lower_hir(analyze(parse_source(&source).unwrap()).unwrap());
        let mut ssa = build_ssa(&verify_mir(mir.clone()).unwrap());
        let mut shared = None;
        let mut changed = false;
        for i in mir.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
        {
            match &mut i.value {
                Rvalue::MatrixView { mutable: false, .. } => shared = Some(i.destination.clone()),
                Rvalue::MatrixAxisVectorView { source, .. } => {
                    *source = shared.clone().unwrap();
                    changed = true;
                }
                _ => {}
            }
        }
        assert!(changed);
        let errors = verify_mir(mir).unwrap_err();
        assert!(
            errors
                .iter()
                .any(|e| e.message.contains("capability contract")),
            "{errors:?}"
        );
        let mut shared = None;
        let mut changed = false;
        for i in ssa.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
        {
            match &mut i.op {
                SsaOp::MatrixView { mutable: false, .. } => shared = Some(i.result),
                SsaOp::MatrixAxisVectorView { source, .. } => {
                    *source = SsaPlace {
                        base: SsaPlaceBase::Value(SsaOperand::Value(shared.unwrap())),
                        projections: vec![],
                    };
                    changed = true;
                }
                _ => {}
            }
        }
        assert!(changed);
        let errors = verify_ssa(ssa).unwrap_err();
        assert!(
            errors
                .iter()
                .any(|e| e.message.contains("capability contract")),
            "{errors:?}"
        );
    }
}

const V27_FIXTURES: &[(&str, u64)] = &[
    ("vector_contiguous", 4),
    ("vector_strided", 4),
    ("matrix_contiguous", 4),
    ("matrix_transposed", 4),
    ("empty", 0),
    ("floats", 8),
    ("control_flow", 18),
    ("projected", 9),
    ("ieee", 4),
    ("evaluation", 6),
];

// Qualification-only probes bracket exactly the arithmetic expression, after
// operand evaluation. Count actual executed element operations/stores, not IR size.
fn v27_instrument(llvm: &str, heap: u64) -> String {
    let mut output = String::new();
    for line in llvm.lines() {
        writeln!(output, "{line}").unwrap();
        if let Some(id) = line.trim().strip_prefix("; ElementwiseBegin ") {
            writeln!(output,"  %q{id}_a0 = load i64, ptr @aether_heap_alloc_count\n  %q{id}_f0 = load i64, ptr @aether_heap_free_count\n  %q{id}_o0 = load i64, ptr @v27_ops\n  %q{id}_s0 = load i64, ptr @v27_stores").unwrap();
        }
        if line.contains("; InitializeNext") {
            let id = line
                .trim()
                .split("%ew")
                .nth(1)
                .unwrap()
                .split('_')
                .next()
                .unwrap();
            writeln!(output,"  %q{id}_sn = load i64, ptr @v27_stores\n  %q{id}_sn1 = add i64 %q{id}_sn, 1\n  store i64 %q{id}_sn1, ptr @v27_stores").unwrap();
        }
        if line.trim().starts_with("%ew")
            && (line.contains("_checked = call")
                || line.contains("_value = fadd")
                || line.contains("_value = fsub")
                || line.contains("_value = fmul"))
        {
            let id = line
                .trim()
                .strip_prefix("%ew")
                .unwrap()
                .split('_')
                .next()
                .unwrap();
            writeln!(output,"  %q{id}_on = load i64, ptr @v27_ops\n  %q{id}_on1 = add i64 %q{id}_on, 1\n  store i64 %q{id}_on1, ptr @v27_ops").unwrap();
        }
        if let Some(id) = line.trim().strip_prefix("; ElementwiseEnd ") {
            let side = if output.contains(&format!("%ew{id}_Left_ptr =")) {
                "Left"
            } else {
                "Right"
            };
            let matrix = output.contains(&format!("%ew{id}_{side}_Rows ="));
            if matrix {
                writeln!(
                    output,
                    "  %q{id}_count = mul i64 %ew{id}_{side}_Rows, %ew{id}_{side}_Columns"
                )
                .unwrap();
            } else {
                writeln!(
                    output,
                    "  %q{id}_count = add i64 %ew{id}_{side}_Dimension, 0"
                )
                .unwrap();
            }
            writeln!(output,"  %q{id}_nonempty = icmp ne i64 %q{id}_count, 0\n  %q{id}_expected = zext i1 %q{id}_nonempty to i64").unwrap();
            for (short, global, expected) in [
                ("a", "aether_heap_alloc_count", format!("%q{id}_expected")),
                ("f", "aether_heap_free_count", "0".into()),
                ("o", "v27_ops", format!("%q{id}_count")),
                ("s", "v27_stores", format!("%q{id}_count")),
            ] {
                writeln!(output,"  %q{id}_{short}1 = load i64, ptr @{global}\n  %q{id}_{short}delta = sub i64 %q{id}_{short}1, %q{id}_{short}0\n  %q{id}_{short}ok = icmp eq i64 %q{id}_{short}delta, {expected}").unwrap();
            }
            writeln!(output,"  %q{id}_af = and i1 %q{id}_aok, %q{id}_fok\n  %q{id}_os = and i1 %q{id}_ook, %q{id}_sok\n  %q{id}_all = and i1 %q{id}_af, %q{id}_os\n  %q{id}_old = load i1, ptr @v27_ok\n  %q{id}_ok = and i1 %q{id}_all, %q{id}_old\n  store i1 %q{id}_ok, ptr @v27_ok").unwrap();
        }
    }
    output.push_str("@v27_ok = internal global i1 true\n@v27_ops = internal global i64 0\n@v27_stores = internal global i64 0\n");
    v23_heap_guard(&output, heap).replace("  %all_ok = and i1 %heap_ok, %result_ok", "  %v27_pass = load i1, ptr @v27_ok\n  %v27_heap = and i1 %heap_ok, %v27_pass\n  %all_ok = and i1 %v27_heap, %result_ok")
}

#[test]
fn vertical27_native_values_and_exact_operation_allocation_counts() {
    for &(name, heap) in V27_FIXTURES {
        let compiled = compile_source(
            &SourceFile::new(
                name,
                fs::read_to_string(program(&format!("v27_{name}.ae"))).unwrap(),
            ),
            &[],
        )
        .unwrap_or_else(|e| panic!("{name}: {e:?}"));
        let operations = match name {
            "vector_contiguous" | "vector_strided" => 6,
            "matrix_contiguous" => 12,
            "matrix_transposed" | "floats" => 10,
            "empty" => 0,
            "control_flow" => 26,
            "projected" => 14,
            "ieee" => 5,
            "evaluation" => 8,
            _ => unreachable!(),
        };
        let instrumented = v27_instrument(&compiled.llvm, heap).replace("  %v27_pass = load i1, ptr @v27_ok", &format!("  %v27_local = load i1, ptr @v27_ok\n  %v27_total = load i64, ptr @v27_ops\n  %v27_total_ok = icmp eq i64 %v27_total, {operations}\n  %v27_pass = and i1 %v27_local, %v27_total_ok"));
        assert_eq!(v23_execute(&instrumented).code(), Some(0), "{name}");
    }
}

#[test]
fn vertical27_all_readable_pairs_and_scalar_types() {
    for matrix in [false, true] {
        for left in 0..3 {
            for right in 0..3 {
                for op in ["+", "-"] {
                    let ty = if matrix {
                        "Matrix<int>"
                    } else {
                        "Vector<int,Row>"
                    };
                    let literal = if matrix { "[1,2;3,4]" } else { "[1,2,3,4]" };
                    let view = if matrix { "matrix_view" } else { "vector_view" };
                    let read = |n: &str, index| match index {
                        0 => n.to_string(),
                        1 => format!("{view}({n})"),
                        _ => format!("{view}_mut({n})"),
                    };
                    let idx = if matrix { "2,2" } else { "4" };
                    let expected = if op == "+" { 8 } else { 0 };
                    let source = format!(
                        "int main(){{{ty} a={literal};{ty} b={literal};{ty} c={} {op} {};if(c[{idx}]!={expected}){{return 1;}}return a[{idx}]+b[{idx}]-8;}}",
                        read("a", left),
                        read("b", right)
                    );
                    let compiled =
                        compile_source(&SourceFile::new("pairs.ae", source), &[]).unwrap();
                    assert_eq!(
                        v23_execute(&v27_instrument(&compiled.llvm, 3)).code(),
                        Some(0),
                        "{matrix} {left} {right} {op}"
                    );
                }
            }
        }
    }
    for scalar in [
        "int8", "int16", "int32", "int64", "isize", "uint8", "uint16", "uint32", "uint64", "usize",
        "float32", "float64",
    ] {
        let source = format!(
            "int main(){{Vector<{scalar},Column> a=[4,7];Vector<{scalar},Column> b=a+a;Matrix<{scalar}> m=[2,3;4,5];Matrix<{scalar}> n=m-m;if(b[2]!=14){{return 1;}}if(n[2,2]!=0){{return 2;}}return 0;}}"
        );
        let compiled = compile_source(&SourceFile::new("scalar.ae", source), &[]).unwrap();
        assert_eq!(
            v23_execute(&v27_instrument(&compiled.llvm, 4)).code(),
            Some(0),
            "{scalar}"
        );
    }
}

#[test]
fn vertical27_structured_rejections_and_evaluation_borrows() {
    for (body, code) in [
        (
            "Vector<int,Row>a=[1];Vector<int,Column>b=[1];Vector<int,Row>c=a+b;",
            "E0344",
        ),
        (
            "Vector<int,Column>a=[1];Vector<int,Row>b=[1];Vector<int,Column>c=a-b;",
            "E0344",
        ),
        (
            "Vector<int,Row>a=[1];Vector<double,Row>b=[1];Vector<int,Row>c=a+b;",
            "E0343",
        ),
        (
            "Vector<float32,Row>a=[1];Vector<float64,Row>b=[1];Vector<float32,Row>c=a-b;",
            "E0343",
        ),
        (
            "Vector<int,Row>a=[1];Matrix<int>b=[1];Vector<int,Row>c=a+b;",
            "E0342",
        ),
        (
            "Matrix<int>a=[1];Vector<int,Row>b=[1];Matrix<int>c=a-vector_view(b);",
            "E0342",
        ),
        (
            "Matrix<int>a=[1];Matrix<double>b=[1];Matrix<int>c=a+b;",
            "E0343",
        ),
        ("Vector<bool,Row>a=[true];Vector<bool,Row>c=a+a;", "E0346"),
        ("Matrix<bool>a=[true];Matrix<bool>c=a-a;", "E0346"),
        (
            "Vector<Buffer<int>,Row>a=[Buffer<int>(1,2)];Vector<Buffer<int>,Row>c=a+a;",
            "E0346",
        ),
        (
            "Vector<int,Row>a=[1];Vector<int,Row>b=[1,2];Vector<int,Row>c=a+b;",
            "E0345",
        ),
        (
            "Matrix<int>a=[1,2];Matrix<int>b=[1,2;3,4];Matrix<int>c=a+b;",
            "E0345",
        ),
        (
            "Matrix<int>a=[1,2];Matrix<int>b=[1,2,3];Matrix<int>c=a+b;",
            "E0345",
        ),
        (
            "Matrix<int>a=[1,2,3;4,5,6];Matrix<int>b=[1,2;3,4;5,6];Matrix<int>c=a+b;",
            "E0345",
        ),
        (
            "Vector<int,Row>a=[];Vector<int,Row>b=[1];Vector<int,Row>c=a-b;",
            "E0345",
        ),
        ("Vector<int,Row>a=[1];Vector<int,Row>c=a*a;", "E0342"),
        ("Matrix<int>a=[1];Matrix<int>c=a/a;", "E0342"),
    ] {
        let errors = compile_source(
            &SourceFile::new("negative.ae", format!("int main(){{{body}return 0;}}")),
            &[],
        )
        .unwrap_err();
        assert!(errors.iter().any(|e| e.code == code), "{body}: {errors:?}");
    }
    for source in [
        "Vector<T,Row> add<T:Storable>(ref Vector<T,Row> a){return *a+*a;}int main(){return 0;}",
        "Matrix<T> sub<T:Storable>(ref Matrix<T> a){return *a-*a;}int main(){return 0;}",
        "Vector<T,Row> add<T:Copy+Storable>(VectorView<T,Row> a){Vector<T,Row> b=a+a;return b;}int main(){return 0;}",
    ] {
        assert!(
            compile_source(&SourceFile::new("generic.ae", source), &[])
                .unwrap_err()
                .iter()
                .any(|e| e.code == "E0346"),
            "{source}"
        );
    }
    for source in [
        "Vector<int,Row> take(Vector<int,Row> a){return a;}int main(){Vector<int,Row>a=[1];Vector<int,Row>b=a+take(a);return 0;}",
        "Matrix<int> take(Matrix<int> a){return a;}int main(){Matrix<int>a=[1];Matrix<int>b=a+take(a);return 0;}",
        "Vector<int,Column> take(Matrix<int> a){Vector<int,Column>b=[1];return b;}int main(){Matrix<int>a=[1];Vector<int,Column>b=column(a,1)+take(a);return 0;}",
    ] {
        let errors = compile_source(&SourceFile::new("borrow.ae", source), &[]).unwrap_err();
        assert!(
            errors.iter().any(|e| e.code == "E0292"),
            "{source}: {errors:?}"
        );
    }
}

#[test]
fn vertical27_runtime_shape_checks_precede_allocation_and_element_access() {
    use std::os::unix::process::ExitStatusExt;
    for (ty, view, lhs, rhs) in [
        ("Vector<int,Row>", "VectorView<int,Row>", "[1,2]", "[1]"),
        ("Vector<int,Row>", "VectorView<int,Row>", "[]", "[1]"),
        ("Vector<int,Row>", "VectorView<int,Row>", "[1]", "[]"),
        ("Matrix<int>", "MatrixView<int>", "[1,2]", "[1,2;3,4]"),
        ("Matrix<int>", "MatrixView<int>", "[1,2]", "[1,2,3]"),
        (
            "Matrix<int>",
            "MatrixView<int>",
            "[1,2,3;4,5,6]",
            "[1,2;3,4;5,6]",
        ),
        ("Matrix<int>", "MatrixView<int>", "[]", "[1]"),
    ] {
        for op in ["+", "-"] {
            let make_view = if ty.starts_with("Vector") {
                "vector_view"
            } else {
                "matrix_view"
            };
            let source = format!(
                "{ty} math({view} a,{view} b){{return a{op}b;}}int main(){{{ty} a={lhs};{ty} b={rhs};{ty} c=math({make_view}(a),{make_view}(b));return 0;}}"
            );
            let compiled = compile_source(&SourceFile::new("shape.ae", source), &[]).unwrap();
            assert_eq!(v23_execute(&compiled.llvm).signal(), Some(4));
            let mut llvm = String::new();
            for line in compiled.llvm.lines() {
                writeln!(llvm, "{line}").unwrap();
                if let Some(id) = line.trim().strip_prefix("; ElementwiseBegin ") {
                    writeln!(llvm,"  %probe{id} = load i64, ptr @aether_heap_alloc_count\n  store i64 %probe{id}, ptr @v27_start").unwrap();
                }
            }
            llvm.push_str("@v27_start = internal global i64 0\ndeclare void @exit(i32) noreturn\n");
            llvm=llvm.replace("trap_shape_mismatch:\n  ; structured Aether trap: ShapeMismatch\n  call void @llvm.trap()", "trap_shape_mismatch:\n  %before = load i64, ptr @v27_start\n  %after = load i64, ptr @aether_heap_alloc_count\n  %same = icmp eq i64 %before, %after\n  %code = select i1 %same, i32 73, i32 99\n  call void @exit(i32 %code)");
            assert_eq!(v23_execute(&llvm).code(), Some(73));
        }
    }
}

#[test]
fn vertical27_integer_overflow_uses_scalar_checked_traps() {
    use std::os::unix::process::ExitStatusExt;
    for (scalar, a, b, op) in [
        ("int8", "127", "1", "+"),
        ("int8", "-128", "1", "-"),
        ("uint8", "255", "1", "+"),
        ("uint8", "0", "1", "-"),
        ("int64", "9223372036854775807", "1", "+"),
    ] {
        for matrix in [false, true] {
            let ty = if matrix {
                format!("Matrix<{scalar}>")
            } else {
                format!("Vector<{scalar},Row>")
            };
            let source =
                format!("int main(){{{ty} a=[1,{a}];{ty} b=[1,{b}];{ty} c=a{op}b;return 0;}}");
            let compiled = compile_source(&SourceFile::new("overflow.ae", source), &[]).unwrap();
            assert_eq!(v23_execute(&compiled.llvm).signal(), Some(4));
            let llvm = format!("{}\ndeclare void @exit(i32) noreturn\n", compiled.llvm).replace(
                "trap_integer_overflow:\n  call void @llvm.trap()",
                "trap_integer_overflow:\n  call void @exit(i32 74)",
            );
            assert_eq!(v23_execute(&llvm).code(), Some(74));
        }
    }
}

fn v27_corrupt_kernel(kernel: &mut aether_middle::ElementwiseKernel, case: usize) {
    use aether_middle::{BinaryOp, MathStep, MathStride, TrapKind};
    match case {
        0 => {
            kernel.program.remove(0);
        }
        1 => kernel.program.swap(0, usize::from(kernel.matrix) + 1),
        2 => {
            if let MathStep::ShapeGuard { trap, .. } = &mut kernel.program[0] {
                *trap = TrapKind::IndexOutOfBounds;
            }
        }
        3 => {
            if let MathStep::Allocate { extents, .. } =
                &mut kernel.program[usize::from(kernel.matrix) + 1]
            {
                extents.clear();
            }
        }
        4 => {
            if let MathStep::Allocate { size_trap, .. } =
                &mut kernel.program[usize::from(kernel.matrix) + 1]
            {
                *size_trap = TrapKind::IntegerOverflow;
            }
        }
        5 => {
            if let MathStep::Allocate { failure_trap, .. } =
                &mut kernel.program[usize::from(kernel.matrix) + 1]
            {
                *failure_trap = TrapKind::ShapeMismatch;
            }
        }
        6 => {
            kernel.program.pop();
        }
        7 => {
            kernel.op = BinaryOp::MultiplyIntegerChecked;
        }
        8 => {
            kernel.element_type = aether_frontend::TypeId::BOOL;
        }
        _ => {
            let mut body = &mut kernel.program;
            while let Some(index) = body.iter().position(|s| matches!(s, MathStep::For { .. })) {
                let MathStep::For {
                    start,
                    step,
                    body: inner,
                    ..
                } = &mut body[index]
                else {
                    unreachable!()
                };
                if case == 9 {
                    *start = 1;
                    return;
                }
                if case == 10 {
                    *step = 2;
                    return;
                }
                body = inner;
            }
            match case {
                11 => {
                    body.pop();
                }
                12 => {
                    body.push(MathStep::InitializeNext);
                }
                13 => {
                    body.swap(0, 3);
                }
                14 => {
                    if let MathStep::StridedLoad { offset, .. } = &mut body[0] {
                        offset[0].1 = MathStride::ColumnStride;
                    }
                }
                15 => {
                    if let MathStep::ScalarBinary { op, .. } = &mut body[2] {
                        *op = BinaryOp::SubtractFloat;
                    }
                }
                16 => {
                    if let MathStep::ScalarBinary { trap, .. } = &mut body[2] {
                        *trap = None;
                    }
                }
                _ => unreachable!(),
            }
        }
    }
}

#[test]
fn vertical27_mir_ssa_independently_verify_executable_loop_and_types() {
    use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};
    for matrix in [false, true] {
        let ty = if matrix {
            "Matrix<int>"
        } else {
            "Vector<int,Row>"
        };
        let hir = analyze(
            parse_source(&SourceFile::new(
                "corrupt.ae",
                format!("int main(){{{ty} a=[1,2];{ty} b=a+a;return 0;}}"),
            ))
            .unwrap(),
        )
        .unwrap();
        let mir = lower_hir(hir);
        let ssa = build_ssa(&verify_mir(mir.clone()).unwrap());
        for case in 0..19 {
            let mut m = mir.clone();
            let owner = m.functions[0]
                .locals
                .iter()
                .find(|l| l.name.as_deref() == Some("a"))
                .unwrap()
                .id;
            let instruction = m.functions[0]
                .blocks
                .iter_mut()
                .flat_map(|b| &mut b.instructions)
                .find(|i| matches!(i.value, Rvalue::ElementwiseBinary { .. }))
                .unwrap();
            let Rvalue::ElementwiseBinary { left, kernel, .. } = &mut instruction.value else {
                unreachable!()
            };
            match case {
                0..=16 => v27_corrupt_kernel(kernel, case),
                17 => *left = aether_middle::Operand::Local(owner),
                _ => *left = aether_middle::Operand::Local(aether_frontend::LocalId(99999)),
            }
            assert!(verify_mir(m).is_err(), "MIR {matrix} {case}");
            let mut s = ssa.clone();
            let owner = s.functions[0]
                .blocks
                .iter()
                .flat_map(|b| &b.instructions)
                .find(|i| matches!(i.op, SsaOp::MatrixInit { .. } | SsaOp::VectorInit { .. }))
                .unwrap()
                .result;
            let instruction = s.functions[0]
                .blocks
                .iter_mut()
                .flat_map(|b| &mut b.instructions)
                .find(|i| matches!(i.op, SsaOp::ElementwiseBinary { .. }))
                .unwrap();
            let SsaOp::ElementwiseBinary { left, kernel, .. } = &mut instruction.op else {
                unreachable!()
            };
            match case {
                0..=16 => v27_corrupt_kernel(kernel, case),
                17 => *left = aether_middle::SsaOperand::Value(owner),
                _ => instruction.ty = aether_frontend::TypeId::BOOL,
            }
            assert!(verify_ssa(s).is_err(), "SSA {matrix} {case}");
        }
    }
}

#[test]
fn vertical27_deterministic_dumps_and_logical_codegen() {
    for name in [
        "vector_contiguous",
        "vector_strided",
        "matrix_transposed",
        "control_flow",
    ] {
        let source = SourceFile::new(
            name,
            fs::read_to_string(program(&format!("v27_{name}.ae"))).unwrap(),
        );
        let emits = [Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
        let a = compile_source(&source, &emits).unwrap();
        let b = compile_source(&source, &emits).unwrap();
        assert_eq!(a.dumps, b.dumps);
        assert_eq!(a.llvm, b.llvm);
        for dump in [Emit::Mir, Emit::Ssa] {
            for required in [
                "ShapeGuard",
                "ShapeMismatch",
                "Allocate",
                "For",
                "StridedLoad",
                "ScalarBinary",
                "InitializeNext",
                "YieldOwner",
            ] {
                assert!(
                    a.dumps[&dump].contains(required),
                    "{name} {dump:?} {required}"
                );
            }
        }
        let hir_name = if name == "matrix_transposed" {
            "MatrixElementwiseBinary"
        } else {
            "VectorElementwiseBinary"
        };
        assert!(a.dumps[&Emit::Hir].contains(hir_name));
        for region in a.llvm.split("; ElementwiseBegin ").skip(1) {
            let region = region.split("; ElementwiseEnd ").next().unwrap();
            assert!(region.find("_equal_").unwrap() < region.find("_allocated = call").unwrap());
            assert!(
                region.find("_allocated = call").unwrap()
                    < region.find("_Left_value = load").unwrap()
            );
            assert!(!region.contains("nsw"));
            assert!(!region.contains("nuw"));
            assert!(!region.contains("inbounds"));
            assert!(!region.contains("@aether_free"));
            assert!(!region.contains("@aether_relocate"));
            if name == "matrix_transposed" {
                assert!(region.contains("RowStride"));
                assert!(region.contains("ColumnStride"));
                assert!(region.contains("_Rows_index = phi"));
                assert!(region.contains("_Columns_index = phi"));
            }
        }
    }
}

#[test]
fn vertical27_allocation_traps_after_shape_and_before_access() {
    qualify_math_allocation_traps(false);
}

#[test]
fn vertical28_allocation_traps_before_element_access() {
    qualify_math_allocation_traps(true);
}

fn qualify_math_allocation_traps(scalar_multiply: bool) {
    for matrix in [false, true] {
        let ty = if matrix {
            "Matrix<int>"
        } else {
            "Vector<int,Row>"
        };
        let previous_allocations = if scalar_multiply { 1 } else { 2 };
        let expression = if scalar_multiply {
            format!("int main(){{{ty} a=[1,2];{ty} c=2*a;return 0;}}")
        } else {
            format!("int main(){{{ty} a=[1,2];{ty} b=[3,4];{ty} c=a+b;return 0;}}")
        };
        let source = SourceFile::new("allocation.ae", expression);
        let compiled = compile_source(&source, &[]).unwrap();
        // Inject impossible extents only into LLVM qualification. Equal oversized
        // shapes must fail the checked allocation before any backing/element access.
        let mut oversized = String::new();
        for line in compiled.llvm.lines() {
            if line.contains("%ew")
                && line.contains(" = extractvalue")
                && (line.contains("_Left_Dimension =")
                    || line.contains("_Right_Dimension =")
                    || line.contains("_Left_Rows =")
                    || line.contains("_Right_Rows ="))
            {
                writeln!(
                    oversized,
                    "{} = add i64 -1, 0",
                    line.split(" = ").next().unwrap()
                )
                .unwrap();
            } else {
                writeln!(oversized, "{line}").unwrap();
            }
        }
        oversized.push_str("declare void @exit(i32) noreturn\n");
        oversized=oversized.replace("trap_allocation_size_overflow:\n  ; structured Aether trap: AllocationSizeOverflow\n  call void @llvm.trap()", "trap_allocation_size_overflow:\n  %allocs = load i64, ptr @aether_heap_alloc_count\n  %ok = icmp eq i64 %allocs, 2\n  %status = select i1 %ok, i32 75, i32 99\n  call void @exit(i32 %status)");
        oversized = oversized.replace("%allocs, 2", &format!("%allocs, {previous_allocations}"));
        assert_eq!(v23_execute(&oversized).code(), Some(75), "size {matrix}");
        let mut failure = String::new();
        for line in compiled.llvm.lines() {
            writeln!(failure, "{line}").unwrap();
            if line.trim().starts_with("; ElementwiseBegin ") {
                failure.push_str("  store i1 true, ptr @v27_fail_malloc\n");
            }
        }
        failure = failure.replace(
            "%alloc_ptr = call ptr @malloc(i64 %alloc_actual)",
            "%alloc_ptr = call ptr @v27_malloc(i64 %alloc_actual)",
        );
        failure=failure.replace("; structured Aether trap: AllocationFailure\ncall void @llvm.trap()", "; structured Aether trap: AllocationFailure\n%allocs = load i64, ptr @aether_heap_alloc_count\n%ok = icmp eq i64 %allocs, 2\n%status = select i1 %ok, i32 76, i32 99\ncall void @exit(i32 %status)");
        failure.push_str("\n@v27_fail_malloc = internal global i1 false\ndeclare void @exit(i32) noreturn\ndefine ptr @v27_malloc(i64 %size) {\nentry:\n  %fail = load i1, ptr @v27_fail_malloc\n  br i1 %fail, label %failed, label %allocate\nfailed:\n  ret ptr null\nallocate:\n  %ptr = call ptr @malloc(i64 %size)\n  ret ptr %ptr\n}\n");
        failure = failure.replace("%allocs, 2", &format!("%allocs, {previous_allocations}"));
        assert_eq!(v23_execute(&failure).code(), Some(76), "failure {matrix}");
    }
}

#[test]
fn vertical27_nested_elements_remain_storage_without_arithmetic() {
    for (prefix, element, value) in [
        ("struct S {int x;}", "S", "S(1)"),
        ("enum E {A}", "E", "E.A"),
        ("", "Array<int>", "{1}"),
        ("", "List<int>", "{1}"),
        ("", "Vector<int,Row>", "[1]"),
        ("", "Matrix<int>", "[1]"),
        ("", "Buffer<int>", "Buffer<int>(1,1)"),
    ] {
        for matrix in [false, true] {
            let ty = if matrix {
                format!("Matrix<{element}>")
            } else {
                format!("Vector<{element},Row>")
            };
            let source = SourceFile::new(
                "element.ae",
                format!("{prefix}int main(){{{ty} a=[{value}];{ty} b=a+a;return 0;}}"),
            );
            let errors = compile_source(&source, &[]).unwrap_err();
            assert!(
                errors.iter().any(|e| e.code == "E0346"),
                "{element} {matrix}: {errors:?}"
            );
        }
    }
}

#[test]
fn vertical28_native_values_and_exact_allocation_operation_counts() {
    for (name, heap, operations) in [
        ("vector_contiguous", 6, 10),
        ("vector_strided", 5, 12),
        ("matrix_contiguous", 3, 12),
        ("matrix_transposed", 5, 14),
        ("empty", 0, 0),
        ("evaluation", 15, 18),
        ("control_flow", 16, 20),
        ("projected", 10, 12),
        ("floats", 6, 8),
    ] {
        let compiled = compile_source(
            &SourceFile::new(
                name,
                fs::read_to_string(program(&format!("v28_{name}.ae"))).unwrap(),
            ),
            &[],
        )
        .unwrap_or_else(|e| panic!("{name}: {e:?}"));
        let instrumented = v27_instrument(&compiled.llvm, heap).replace("  %v27_pass = load i1, ptr @v27_ok", &format!("  %v28_local = load i1, ptr @v27_ok\n  %v28_total = load i64, ptr @v27_ops\n  %v28_total_ok = icmp eq i64 %v28_total, {operations}\n  %v27_pass = and i1 %v28_local, %v28_total_ok"));
        assert_eq!(v23_execute(&instrumented).code(), Some(0), "{name}");
    }
}

#[test]
fn vertical28_all_readable_inputs_types_and_orders() {
    for matrix in [false, true] {
        for orientation in ["Row", "Column"] {
            if matrix && orientation == "Column" {
                continue;
            }
            for view in 0..5 {
                for scalar_left in [false, true] {
                    let ty = if matrix {
                        "Matrix<int>".to_owned()
                    } else {
                        format!("Vector<int,{orientation}>")
                    };
                    let (view_ty, intrinsic) = if matrix {
                        ("MatrixView".to_owned(), "matrix_view")
                    } else {
                        ("VectorView".to_owned(), "vector_view")
                    };
                    let view_ty = format!(
                        "{view_ty}{}<int{}>",
                        if view == 2 { "Mut" } else { "" },
                        if matrix {
                            String::new()
                        } else {
                            format!(",{orientation}")
                        }
                    );
                    let binding = if view == 0 || view >= 3 {
                        String::new()
                    } else {
                        format!(
                            "{view_ty} v={intrinsic}{}(a);",
                            if view == 2 { "_mut" } else { "" }
                        )
                    };
                    let input = match view {
                        0 => "a".to_owned(),
                        1 | 2 => "v".to_owned(),
                        _ => format!("{intrinsic}{}(a)", if view == 4 { "_mut" } else { "" }),
                    };
                    let expr = if scalar_left {
                        format!("3*{input}")
                    } else {
                        format!("{input}*3")
                    };
                    let index = if matrix { "1,2" } else { "2" };
                    let source = format!(
                        "int main(){{{ty} a=[2,4];{binding}{ty} b={expr};if(b[{index}]!=12){{return 1;}}return a[{index}]-4;}}"
                    );
                    let c = compile_source(&SourceFile::new("inputs.ae", &source), &[])
                        .unwrap_or_else(|e| panic!("{source}: {e:?}"));
                    assert_eq!(
                        v23_execute(&v27_instrument(&c.llvm, 2)).code(),
                        Some(0),
                        "{source}"
                    );
                }
            }
        }
        for element in [
            "int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "isize",
            "usize", "float32", "float64", "int", "float", "double",
        ] {
            let ty = if matrix {
                format!("Matrix<{element}>")
            } else {
                format!("Vector<{element},Row>")
            };
            let index = if matrix { "1,2" } else { "2" };
            let source = format!(
                "int main(){{{ty}a=[2,4];{element} s=3;{ty}b=s*a;{ty}c=a*s;if(b[{index}]!=12){{return 1;}}if(c[{index}]!=12){{return 2;}}return 0;}}"
            );
            let c = compile_source(&SourceFile::new("types.ae", &source), &[])
                .unwrap_or_else(|e| panic!("{source}: {e:?}"));
            assert_eq!(
                v23_execute(&v27_instrument(&c.llvm, 3)).code(),
                Some(0),
                "{source}"
            );
        }
    }
}

#[test]
fn vertical28_structured_rejections_and_temporary_borrows() {
    for (body, code) in [
        ("Vector<bool,Row>a=[true];Vector<bool,Row>b=2*a;", "E0346"),
        (
            "Vector<int,Row>a=[1];int s=2;ref int r=&s;Vector<int,Row>b=r*a;",
            "E0343",
        ),
        ("Vector<int,Row>a=[1];Vector<int,Row>b=a*a;", "E0342"),
        (
            "Vector<int,Row>a=[1];Vector<int,Row>b=vector_view(a)*a;",
            "E0342",
        ),
        ("Matrix<int>a=[1];Vector<int,Row>b=a*a;", "E0218"),
        (
            "Matrix<int>a=[1];Vector<int,Column>b=matrix_view(a)*a;",
            "E0218",
        ),
        (
            "Vector<int,Row>a=[1];Matrix<int>b=[1];Matrix<int>c=a*b;",
            "E0218",
        ),
        (
            "Vector<int,Row>a=[1];Matrix<int>b=[1];Matrix<int>c=b*a;",
            "E0342",
        ),
        (
            "Vector<bool,Row>a=[true];Vector<bool,Row>b=true*a;",
            "E0346",
        ),
        ("Matrix<bool>a=[true];Matrix<bool>b=a*true;", "E0346"),
        ("Vector<int,Row>a=[1];Vector<int,Row>b=true*a;", "E0343"),
        (
            "Vector<double,Row>a=[1];int s=2;Vector<double,Row>b=s*a;",
            "E0343",
        ),
        ("Matrix<int8>a=[1];int s=2;Matrix<int8>b=a*s;", "E0343"),
        (
            "Matrix<float32>a=[1];float64 s=2;Matrix<float32>b=s*a;",
            "E0343",
        ),
        ("Vector<int,Row>a=[1];Vector<int,Column>b=2*a;", "E0218"),
        ("Vector<int,Row>a=[1];Matrix<int>b=2*a;", "E0218"),
        ("Matrix<int>a=[1];Matrix<int>b=a/2;", "E0342"),
        ("Vector<int,Row>a=[1];Vector<int,Row>b=2/a;", "E0342"),
    ] {
        let e = compile_source(
            &SourceFile::new("negative.ae", format!("int main(){{{body}return 0;}}")),
            &[],
        )
        .unwrap_err();
        assert!(e.iter().any(|e| e.code == code), "{body}: {e:?}");
    }
    for matrix in [false, true] {
        for bounds in ["Storable", "Copy+Storable"] {
            let ty = if matrix { "Matrix<T>" } else { "Vector<T,Row>" };
            let source =
                format!("{ty} scale<T:{bounds}>(T s,{ty} v){{return s*v;}}int main(){{return 0;}}");
            let e = compile_source(&SourceFile::new("generic.ae", &source), &[]).unwrap_err();
            assert!(e.iter().any(|e| e.code == "E0346"), "{source}: {e:?}");
        }
        let ty = if matrix {
            "Matrix<int>"
        } else {
            "Vector<int,Row>"
        };
        for expr in ["a*take(a)", "take(a)*a"] {
            let source = format!(
                "int take({ty} a){{return 2;}}int main(){{{ty}a=[1];{ty}b={expr};return 0;}}"
            );
            assert!(compile_source(&SourceFile::new("borrow.ae", source), &[]).is_err());
        }
    }
    for expr in ["column(a,1)*take(a)", "take(a)*column(a,1)"] {
        let source = format!(
            "int take(Matrix<int>a){{return 2;}}int main(){{Matrix<int>a=[1];Vector<int,Column>b={expr};return 0;}}"
        );
        assert!(compile_source(&SourceFile::new("borrow.ae", source), &[]).is_err());
    }
    for (prefix, element, value) in [
        ("struct S {int x;}", "S", "S(1)"),
        ("enum E {A}", "E", "E.A"),
        ("", "Buffer<int>", "Buffer<int>(1,1)"),
        ("", "Array<int>", "{1}"),
        ("", "List<int>", "{1}"),
        ("", "Vector<int,Row>", "[1]"),
        ("", "Matrix<int>", "[1]"),
    ] {
        for ty in [
            format!("Vector<{element},Row>"),
            format!("Matrix<{element}>"),
        ] {
            let source =
                format!("{prefix}int main(){{{ty}a=[{value}];int s=2;{ty}b=s*a;return 0;}}");
            let e = compile_source(&SourceFile::new("element.ae", &source), &[]).unwrap_err();
            assert!(e.iter().any(|e| e.code == "E0346"), "{source}: {e:?}");
        }
    }
}

#[test]
fn vertical28_checked_overflow_after_initialized_slot() {
    use std::os::unix::process::ExitStatusExt;
    for (element, max) in [
        ("int8", "127"),
        ("uint8", "255"),
        ("int16", "32767"),
        ("uint16", "65535"),
        ("int32", "2147483647"),
        ("uint32", "4294967295"),
        ("int64", "9223372036854775807"),
        ("uint64", "18446744073709551615"),
        ("isize", "9223372036854775807"),
        ("usize", "18446744073709551615"),
    ] {
        for matrix in [false, true] {
            let ty = if matrix {
                format!("Matrix<{element}>")
            } else {
                format!("Vector<{element},Row>")
            };
            let expr = if matrix { "a*2" } else { "2*a" };
            let source = format!("int main(){{{ty}a=[1,{max}];{ty}b={expr};return 0;}}");
            let c = compile_source(&SourceFile::new("overflow.ae", source), &[]).unwrap();
            assert_eq!(v23_execute(&c.llvm).signal(), Some(4), "{element} {matrix}");
            let mut llvm = String::new();
            for line in c.llvm.lines() {
                writeln!(llvm, "{line}").unwrap();
                if line.contains("; InitializeNext") {
                    llvm.push_str("  store i32 1, ptr @v28_initialized\n");
                }
            }
            llvm.push_str(
                "@v28_initialized = internal global i32 0\ndeclare void @exit(i32) noreturn\n",
            );
            llvm=llvm.replace("trap_integer_overflow:\n  call void @llvm.trap()", "trap_integer_overflow:\n  %v28_prior = load i32, ptr @v28_initialized\n  %v28_status = add i32 %v28_prior, 73\n  call void @exit(i32 %v28_status)");
            assert_eq!(v23_execute(&llvm).code(), Some(74), "{element} {matrix}");
        }
    }
}

#[test]
fn vertical28_ieee_floats_both_ranks_and_orders() {
    for element in ["float32", "float64", "float", "double"] {
        for matrix in [false, true] {
            for left in [false, true] {
                let ty = if matrix {
                    format!("Matrix<{element}>")
                } else {
                    format!("Vector<{element},Row>")
                };
                let idx = if matrix { "1," } else { "" };
                let expr = if left { "2*a" } else { "a*2" };
                let source = format!(
                    "int main(){{{element} z=0.0;{element} inf=1.0/z;{element} nan=z/z;{ty}a=[-z,z,inf,-inf,nan];{ty}b={expr};if(1.0/b[{idx}1]!=-inf){{return 1;}}if(1.0/b[{idx}2]!=inf){{return 2;}}if(b[{idx}3]!=inf){{return 3;}}if(b[{idx}4]!=-inf){{return 4;}}if(b[{idx}5]==b[{idx}5]){{return 5;}}return 0;}}"
                );
                let c = compile_source(&SourceFile::new("ieee.ae", source), &[]).unwrap();
                assert!(c.llvm.contains(" = fmul "));
                assert!(!c.llvm.contains("fmul fast"));
                assert_eq!(
                    v23_execute(&v27_instrument(&c.llvm, 2)).code(),
                    Some(0),
                    "{element} {matrix} {left}"
                );
            }
        }
    }
}

fn v28_corrupt_kernel(kernel: &mut aether_middle::ElementwiseKernel, case: usize) {
    use aether_middle::{BinaryOp, MathAxis, MathInput, MathStep, MathStride, TrapKind};
    match case {
        0 => kernel.program.insert(
            0,
            MathStep::ShapeGuard {
                axis: MathAxis::Dimension,
                trap: TrapKind::ShapeMismatch,
            },
        ),
        1 => kernel.op = BinaryOp::AddIntegerChecked,
        2 => {
            kernel.scalar_side = Some(if kernel.scalar_side == Some(MathInput::Left) {
                MathInput::Right
            } else {
                MathInput::Left
            });
        }
        3 => kernel.element_type = aether_frontend::TypeId::BOOL,
        4 => {
            kernel.program.remove(0);
        }
        5 => {
            if let MathStep::Allocate { extents, .. } = &mut kernel.program[0] {
                extents.clear();
            }
        }
        11 => kernel.program.insert(0, MathStep::InitializeNext),
        12 => {
            if let MathStep::Allocate { size_trap, .. } = &mut kernel.program[0] {
                *size_trap = TrapKind::ShapeMismatch;
            }
        }
        _ => {
            let mut body = &mut kernel.program;
            while let Some(index) = body.iter().position(|s| matches!(s, MathStep::For { .. })) {
                let MathStep::For {
                    step, body: inner, ..
                } = &mut body[index]
                else {
                    unreachable!()
                };
                if case == 6 {
                    *step = 2;
                    return;
                }
                body = inner;
            }
            match case {
                7 => {
                    for step in body {
                        if let MathStep::StridedLoad { offset, .. } = step {
                            offset[0].1 = MathStride::ColumnStride;
                        }
                    }
                }
                8 => {
                    for step in body {
                        if let MathStep::ScalarBinary { op, .. } = step {
                            *op = BinaryOp::AddIntegerChecked;
                        }
                    }
                }
                9 => body.push(MathStep::InitializeNext),
                10 => {
                    for step in body {
                        if let MathStep::InvariantScalar { input } = step {
                            *input = if *input == MathInput::Left {
                                MathInput::Right
                            } else {
                                MathInput::Left
                            };
                        }
                    }
                }
                _ => unreachable!(),
            }
        }
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical28_mir_ssa_independently_reject_corruption() {
    use aether_frontend::TypeId;
    use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};
    for matrix in [false, true] {
        for scalar_left in [false, true] {
            let ty = if matrix {
                "Matrix<int>"
            } else {
                "Vector<int,Row>"
            };
            let expr = if scalar_left { "2*a" } else { "a*2" };
            let hir = analyze(
                parse_source(&SourceFile::new(
                    "corrupt.ae",
                    format!("int main(){{{ty}a=[1,2];{ty}b={expr};Vector<int,Column>other=[1];return 0;}}"),
                ))
                .unwrap(),
            )
            .unwrap();
            let mir = lower_hir(hir);
            let ssa = build_ssa(&verify_mir(mir.clone()).unwrap());
            let wrong_result = mir.functions[0]
                .locals
                .iter()
                .find(|l| l.name.as_deref() == Some("other"))
                .unwrap()
                .ty;
            for case in 0..17 {
                let mut m = mir.clone();
                let owner = m.functions[0]
                    .locals
                    .iter()
                    .find(|l| l.name.as_deref() == Some("a"))
                    .unwrap()
                    .id;
                let instruction = m.functions[0]
                    .blocks
                    .iter_mut()
                    .flat_map(|b| &mut b.instructions)
                    .find(|i| matches!(i.value, Rvalue::ElementwiseBinary { .. }))
                    .unwrap();
                let aether_middle::PlaceBase::Local(destination) = instruction.destination.base
                else {
                    unreachable!()
                };
                let Rvalue::ElementwiseBinary {
                    left,
                    right,
                    kernel,
                } = &mut instruction.value
                else {
                    unreachable!()
                };
                match case {
                    0..=12 => v28_corrupt_kernel(kernel, case),
                    13 => {
                        let source = if scalar_left { right } else { left };
                        *source = aether_middle::Operand::Local(owner);
                    }
                    14 => {
                        let scalar = if scalar_left { left } else { right };
                        *scalar = aether_middle::Operand::Bool(true);
                    }
                    15 => kernel.matrix = !matrix,
                    _ => {}
                }
                if case == 16 {
                    m.functions[0].locals[destination.0 as usize].ty = wrong_result;
                }
                assert!(verify_mir(m).is_err(), "MIR {matrix} {scalar_left} {case}");
                let mut s = ssa.clone();
                let owner = s.functions[0]
                    .blocks
                    .iter()
                    .flat_map(|b| &b.instructions)
                    .find(|i| matches!(i.op, SsaOp::VectorInit { .. } | SsaOp::MatrixInit { .. }))
                    .unwrap()
                    .result;
                let instruction = s.functions[0]
                    .blocks
                    .iter_mut()
                    .flat_map(|b| &mut b.instructions)
                    .find(|i| matches!(i.op, SsaOp::ElementwiseBinary { .. }))
                    .unwrap();
                let SsaOp::ElementwiseBinary {
                    left,
                    right,
                    kernel,
                } = &mut instruction.op
                else {
                    unreachable!()
                };
                match case {
                    0..=12 => v28_corrupt_kernel(kernel, case),
                    13 => {
                        let source = if scalar_left { right } else { left };
                        *source = aether_middle::SsaOperand::Value(owner);
                    }
                    14 => {
                        let scalar = if scalar_left { left } else { right };
                        *scalar = aether_middle::SsaOperand::Bool(true);
                    }
                    15 => instruction.ty = TypeId::BOOL,
                    _ => instruction.ty = wrong_result,
                }
                assert!(verify_ssa(s).is_err(), "SSA {matrix} {scalar_left} {case}");
            }
        }
    }
}

#[test]
fn vertical28_deterministic_dumps_and_single_descriptor_codegen() {
    for name in [
        "vector_contiguous",
        "vector_strided",
        "matrix_contiguous",
        "matrix_transposed",
        "empty",
        "evaluation",
        "control_flow",
        "floats",
    ] {
        let source = SourceFile::new(
            name,
            fs::read_to_string(program(&format!("v28_{name}.ae"))).unwrap(),
        );
        let emits = [Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
        let a = compile_source(&source, &emits).unwrap();
        let b = compile_source(&source, &emits).unwrap();
        assert_eq!(a.dumps, b.dumps);
        assert_eq!(a.llvm, b.llvm);
        assert!(a.dumps[&Emit::Hir].contains("ScalarMultiply"));
        assert!(a.dumps[&Emit::Hir].contains("scalar_side"));
        for dump in [Emit::Mir, Emit::Ssa] {
            for required in [
                "InvariantScalar",
                "scalar_side",
                "Allocate",
                "For",
                "StridedLoad",
                "Multiply",
                "InitializeNext",
                "YieldOwner",
            ] {
                assert!(
                    a.dumps[&dump].contains(required),
                    "{name} {dump:?} {required}"
                );
            }
            assert!(!a.dumps[&dump].contains("ShapeMismatch"));
        }
        for region in a.llvm.split("; ElementwiseBegin ").skip(1) {
            let region = region.split("; ElementwiseEnd ").next().unwrap();
            assert!(!region.contains("shape_mismatch"));
            assert_eq!(region.matches("_value = load ").count(), 1);
            assert_eq!(region.matches("_allocated = call ").count(), 1);
            assert!(
                region.find("_allocated = call").unwrap() < region.find("_value = load").unwrap()
            );
            assert!(region.contains("mul.with.overflow.") || region.contains(" = fmul "));
            for forbidden in [
                "nsw",
                "nuw",
                "noalias",
                "inbounds",
                "fmul fast",
                "@aether_free",
                "@aether_relocate",
            ] {
                assert!(!region.contains(forbidden), "{name} {forbidden}");
            }
            if name == "matrix_transposed" {
                for required in [
                    "RowStride",
                    "ColumnStride",
                    "_Rows_index = phi",
                    "_Columns_index = phi",
                ] {
                    assert!(region.contains(required));
                }
            }
        }
    }
}

#[test]
fn vertical28_noninvalidating_scalar_effects_follow_existing_alias_policy() {
    for (ty, index) in [("Vector<int,Row>", "1"), ("Matrix<int>", "1,1")] {
        let source = format!(
            "int mutate(ref mut int s){{*s=9;return 2;}}int main(){{{ty}a=[1];{ty}b=a*mutate(&mut a[{index}]);if(a[{index}]!=9){{return 1;}}return b[{index}]-18;}}"
        );
        let c = compile_source(&SourceFile::new("mutation.ae", source), &[]).unwrap();
        assert_eq!(v23_execute(&v27_instrument(&c.llvm, 2)).code(), Some(0));
    }
}

#[test]
fn vertical29_native_behavior_and_cross_module_forwarding() {
    for path in [
        program("v29_behavior.ae"),
        program("v29_add_int.ae"),
        program("v29_affine_int.ae"),
        program("v29_affine_float.ae"),
        module_program("v29_behavior"),
    ] {
        let (compiled, status) = run_path(
            &path,
            &[Emit::Hir, Emit::Mir, Emit::Ssa],
            &ClangToolchain::default(),
        )
        .unwrap();
        assert_eq!(status.code(), Some(0), "{}", path.display());
        assert!(compiled.dumps[&Emit::Hir].contains("CapabilityBinary"));
        assert!(compiled.dumps[&Emit::Hir].contains("behavioral guarantees=[Add"));
        for phase in [Emit::Mir, Emit::Ssa] {
            assert!(!compiled.dumps[&phase].contains("CapabilityBinary"));
        }
        assert!(!compiled.llvm.contains("Capability"));
        assert!(!compiled.llvm.contains("vtable"));
        assert!(!compiled.llvm.contains("witness"));
    }
}

#[test]
fn vertical29_all_builtin_scalars_reify_each_independent_behavior() {
    for ty in [
        "int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "isize", "usize",
        "float32", "float64", "int", "float", "double",
    ] {
        let source = format!(
            "T add<T:Add>(T a,T b){{return a+b;}}T sub<T:Sub>(T a,T b){{return a-b;}}T mul<T:Mul>(T a,T b){{return a*b;}}int main(){{if(add<{ty}>(6,2)!=8){{return 1;}}if(sub<{ty}>(6,2)!=4){{return 2;}}if(mul<{ty}>(6,2)!=12){{return 3;}}return 0;}}"
        );
        let compiled =
            compile_source(&SourceFile::new("scalars.ae", source), &[Emit::Hir]).unwrap();
        let float = ty.starts_with("float") || ty == "double";
        for op in if float {
            ["AddFloat", "SubtractFloat", "MultiplyFloat"]
        } else {
            [
                "AddIntegerChecked",
                "SubtractIntegerChecked",
                "MultiplyIntegerChecked",
            ]
        } {
            assert!(compiled.dumps[&Emit::Hir].contains(op), "{ty} {op}");
        }
        assert_eq!(v23_execute(&compiled.llvm).code(), Some(0), "{ty}");
    }
}

#[test]
#[allow(clippy::too_many_lines)] // One table keeps the diagnostic contract together.
fn vertical29_structured_rejections_even_without_instances() {
    for (caps, op, required) in [
        ("Storable", "+", "Add"),
        ("Copy", "+", "Add"),
        ("Add", "-", "Sub"),
        ("Mul", "+", "Add"),
        ("Add", "*", "Mul"),
        ("Sub", "*", "Mul"),
        ("Sub", "+", "Add"),
    ] {
        let source = format!("T bad<T:{caps}>(T a,T b){{return a{op}b;}}int main(){{return 0;}}");
        let errors = compile_source(&SourceFile::new("missing.ae", source), &[]).unwrap_err();
        assert_eq!(errors[0].code, "E0268");
        assert!(
            errors[0]
                .message
                .contains(&format!("requires capability {required}"))
        );
        assert!(errors[0].message.contains(&format!("operator '{op}'")));
        assert_eq!(
            errors[0].category,
            aether_frontend::DiagnosticCategory::Type
        );
    }
    for (source, code, detail) in [
        (
            "T add<T:Add>(T a,T b){return a+b;}int main(){bool b=add<bool>(true,false);return 0;}",
            "E0316",
            "Add",
        ),
        (
            "T add<T:Add>(T a,T b){return a+b;}int main(){bool b=add(true,false);return 0;}",
            "E0317",
            "Add",
        ),
        (
            "T mul<T:Mul>(T a,T b){return a*b;}int main(){Buffer<int> b=mul(Buffer<int>(0,0),Buffer<int>(0,0));return 0;}",
            "E0317",
            "Mul",
        ),
        (
            "struct Point{double x;double y;}T add<T:Add>(T a,T b){return a+b;}int main(){Point p=add(Point(1.0,2.0),Point(3.0,4.0));return 0;}",
            "E0317",
            "Add",
        ),
        (
            "T inner<T:Add>(T a,T b){return a+b;}T outer<T:Storable>(T a,T b){return inner(a,b);}int main(){return 0;}",
            "E0317",
            "Add",
        ),
        (
            "T inner<T:Add+Mul>(T a,T b){return a*b;}T outer<T:Add>(T a,T b){return inner<T>(a,b);}int main(){return 0;}",
            "E0316",
            "Mul",
        ),
        (
            "T bad<T:Numeric>(T a){return a;}int main(){return 0;}",
            "E0314",
            "Numeric",
        ),
        (
            "T bad<T:Add+Add>(T a){return a;}int main(){return 0;}",
            "E0315",
            "Add",
        ),
        (
            "struct Holder<T:Add>{T value;}int main(){Holder<bool> h=Holder<bool>(true);return 0;}",
            "E0316",
            "Add",
        ),
        (
            "enum E<T:Mul>{Some(T)}int main(){E<bool> e=E<bool>.Some(true);return 0;}",
            "E0316",
            "Mul",
        ),
        (
            "struct Holder<T:Add>{T value;}T add<T:Add>(T a,T b){return a+b;}int main(){Holder<int> h=add(Holder<int>(1),Holder<int>(2));return 0;}",
            "E0317",
            "Add",
        ),
        (
            "T bad<T:Add,U:Add>(T a,U b){return a+b;}int main(){return 0;}",
            "E0347",
            "homogeneous",
        ),
        (
            "T bad<T:Add>(T a,int b){return a+b;}int main(){return 0;}",
            "E0347",
            "homogeneous",
        ),
        (
            "Vector<T,Row> bad<T:Storable+Add>(Vector<T,Row> a,Vector<T,Row> b){return a+b;}int main(){return 0;}",
            "E0346",
            "missing Copy",
        ),
        (
            "T twice<T:Add>(T a){return a+a;}int main(){return 0;}",
            "E0291",
            "use after move",
        ),
    ] {
        let errors = compile_source(&SourceFile::new("bad.ae", source), &[]).unwrap_err();
        assert_eq!(errors[0].code, code, "{source}: {errors:?}");
        assert!(errors[0].message.contains(detail), "{source}: {errors:?}");
    }
}

#[test]
fn vertical29_integer_overflow_and_underflow_remain_checked() {
    use std::os::unix::process::ExitStatusExt;
    for (ty, max, min) in [
        ("int8", "127", "-128"),
        ("int16", "32767", "-32768"),
        ("int32", "2147483647", "-2147483648"),
        ("int64", "9223372036854775807", "-9223372036854775808"),
        ("uint8", "255", "0"),
        ("uint16", "65535", "0"),
        ("uint32", "4294967295", "0"),
        ("uint64", "18446744073709551615", "0"),
        ("isize", "9223372036854775807", "-9223372036854775808"),
        ("usize", "18446744073709551615", "0"),
    ] {
        for (cap, op, lhs, rhs, intrinsic) in [
            ("Add", "+", max, "1", "add"),
            ("Sub", "-", min, "1", "sub"),
            ("Mul", "*", max, "2", "mul"),
        ] {
            let source = format!(
                "T operation<T:{cap}>(T a,T b){{return a{op}b;}}int main(){{{ty} x=operation<{ty}>({lhs},{rhs});return int(x);}}"
            );
            let compiled = compile_source(
                &SourceFile::new("overflow.ae", source),
                &[Emit::Mir, Emit::Ssa],
            )
            .unwrap();
            let signed = if ty.starts_with('u') { 'u' } else { 's' };
            assert!(
                compiled
                    .llvm
                    .contains(&format!("llvm.{signed}{intrinsic}.with.overflow"))
            );
            for phase in [Emit::Mir, Emit::Ssa] {
                assert!(compiled.dumps[&phase].contains("IntegerOverflow"));
            }
            assert_eq!(v23_execute(&compiled.llvm).signal(), Some(4), "{ty} {cap}");
        }
    }
}

#[test]
fn vertical29_ieee_zero_infinity_nan_and_no_fast_math() {
    for ty in ["float32", "float64", "float", "double"] {
        for (cap, op, exprs, instruction) in [
            (
                "Add",
                "+",
                [
                    "operation(-z,-z)",
                    "operation(z,z)",
                    "operation(inf,z)",
                    "operation(-inf,z)",
                    "operation(inf,-inf)",
                ],
                "fadd",
            ),
            (
                "Sub",
                "-",
                [
                    "operation(-z,z)",
                    "operation(z,z)",
                    "operation(inf,z)",
                    "operation(-inf,z)",
                    "operation(inf,inf)",
                ],
                "fsub",
            ),
            (
                "Mul",
                "*",
                [
                    "operation(-z,one)",
                    "operation(z,one)",
                    "operation(inf,one)",
                    "operation(-inf,one)",
                    "operation(inf,z)",
                ],
                "fmul",
            ),
        ] {
            let [nz, pz, pi, ni, nan] = exprs;
            let source = format!(
                "T operation<T:{cap}>(T a,T b){{return a{op}b;}}int main(){{{ty} z=0.0;{ty} one=1.0;{ty} inf=one/z;{ty} a={nz};{ty} b={pz};{ty} c={pi};{ty} d={ni};{ty} n={nan};if(one/a!=-inf){{return 1;}}if(one/b!=inf){{return 2;}}if(c!=inf){{return 3;}}if(d!=-inf){{return 4;}}if(n==n){{return 5;}}return 0;}}"
            );
            let compiled = compile_source(&SourceFile::new("ieee.ae", source), &[]).unwrap();
            for line in compiled
                .llvm
                .lines()
                .filter(|line| line.contains(&format!(" = {instruction} ")))
            {
                assert!(
                    line.contains(&format!(
                        "{instruction} {} ",
                        if ty == "float32" || ty == "float" {
                            "float"
                        } else {
                            "double"
                        }
                    )),
                    "{line}"
                );
            }
            assert!(compiled.llvm.contains(&format!(" = {instruction} ")));
            assert_eq!(v23_execute(&compiled.llvm).code(), Some(0), "{ty} {cap}");
        }
    }
}

#[test]
fn vertical29_deterministic_dumps_and_unchanged_instance_abi() {
    let text = fs::read_to_string(program("v29_behavior.ae")).unwrap();
    let source = SourceFile::new("determinism.ae", text);
    let phases = [Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm];
    let first = compile_source(&source, &phases).unwrap();
    let second = compile_source(&source, &phases).unwrap();
    assert_eq!(first.dumps, second.dumps);
    let compile = |caps| {
        compile_source(
            &SourceFile::new(
                "abi.ae",
                format!("T add<T:{caps}>(T a,T b){{return a+b;}}int main(){{return add(20,22);}}"),
            ),
            &[],
        )
        .unwrap()
        .llvm
    };
    assert_eq!(compile("Add"), compile("Copy+Storable+Add+Mul"));
    assert_eq!(compile("Add+Mul"), compile("Mul+Add"));
}

#[test]
fn vertical29_mir_ssa_reject_unresolved_behavioral_scalar_types() {
    use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};
    for (capability, operator) in [("Add", "+"), ("Sub", "-"), ("Mul", "*")] {
        let source = SourceFile::new(
            "v29-runtime.ae",
            format!(
                "T operation<T:{capability}>(T a,T b){{return a{operator}b;}}int main(){{return operation(6,2);}}"
            ),
        );
        let hir = analyze(parse_source(&source).unwrap()).unwrap();
        let symbolic = hir.signatures()[0].generic_parameters[0].ty;
        let raw = lower_hir(hir);
        let function = raw
            .functions
            .iter()
            .position(|f| {
                f.blocks
                    .iter()
                    .flat_map(|b| &b.instructions)
                    .any(|i| matches!(i.value, Rvalue::Binary { .. }))
            })
            .unwrap();
        let mut corrupt = raw.clone();
        corrupt.functions[function].locals[0].ty = symbolic;
        assert!(
            verify_mir(corrupt).unwrap_err()[0]
                .message
                .contains("unresolved generic")
        );
        let mir = verify_mir(raw).unwrap();
        let mut ssa = build_ssa(&mir);
        let operation = ssa.functions[function]
            .blocks
            .iter_mut()
            .flat_map(|b| &mut b.instructions)
            .find(|i| matches!(i.op, SsaOp::Binary { .. }))
            .unwrap();
        operation.ty = symbolic;
        assert!(
            verify_ssa(ssa).unwrap_err()[0]
                .message
                .contains("unresolved generic")
        );
    }
}

#[test]
fn vertical30_native_strides_forwarding_empty_and_exact_counters() {
    for (name, heap, operations) in [
        ("vector_add", 2, 3),
        ("vector_scale", 2, 3),
        ("matrix_add", 2, 6),
        ("matrix_transposed", 3, 12),
        ("vector_strided", 2, 2),
        ("empty", 0, 0),
    ] {
        let source = SourceFile::new(
            name,
            fs::read_to_string(program(&format!("v30_{name}.ae"))).unwrap(),
        );
        let c = compile_source(&source, &[Emit::Hir, Emit::Mir, Emit::Ssa]).unwrap();
        assert!(c.dumps[&Emit::Hir].contains("op: Behavioral("));
        assert!(c.dumps[&Emit::Hir].contains("op: Concrete("));
        for phase in [Emit::Mir, Emit::Ssa] {
            assert!(!c.dumps[&phase].contains("Behavioral("));
            assert!(!c.dumps[&phase].contains("CapabilityBinary"));
        }
        assert!(!c.llvm.contains("Capability"));
        let llvm = v27_instrument(&c.llvm, heap).replace("  %v27_pass = load i1, ptr @v27_ok", &format!("  %v30_local = load i1, ptr @v27_ok\n  %v30_total = load i64, ptr @v27_ops\n  %v30_total_ok = icmp eq i64 %v30_total, {operations}\n  %v27_pass = and i1 %v30_local, %v30_total_ok"));
        assert_eq!(v23_execute(&llvm).code(), Some(0), "{name}");
    }
}

#[test]
fn vertical30_all_readable_families_orientations_and_behaviors() {
    for rank in ["Row", "Column", "Matrix"] {
        for scalar in ["int", "uint64", "float32", "double"] {
            let owner = if rank == "Matrix" {
                "Matrix<T>".to_owned()
            } else {
                format!("Vector<T,{rank}>")
            };
            let view = owner
                .replace("Matrix<", "MatrixView<")
                .replace("Vector<", "VectorView<");
            let view_mut = view.replace("View<", "ViewMut<");
            let concrete = owner.replace('T', scalar);
            let index = if rank == "Matrix" { "2,2" } else { "2" };
            let literal = if rank == "Matrix" {
                "[2,4;6,8]"
            } else {
                "[6,8]"
            };
            let intrinsic = if rank == "Matrix" {
                "matrix_view"
            } else {
                "vector_view"
            };
            let forms = [
                (format!("ref {owner}"), "*a", "&x".to_owned()),
                (view, "a", format!("{intrinsic}(x)")),
                (view_mut, "a", format!("{intrinsic}_mut(x)")),
            ];
            let mut helpers = String::new();
            let mut main = format!("int main(){{{concrete} x={literal};");
            for (i, (param_a, expr_a, arg_a)) in forms.iter().enumerate() {
                for (j, (param_b, expr_b, arg_b)) in forms.iter().enumerate() {
                    for (cap, op, expected) in [("Add", "+", 16), ("Sub", "-", 0)] {
                        let name = format!("f{cap}{i}{j}");
                        let expr_b = expr_b.replace('a', "b");
                        write!(helpers, "{owner} {name}<T:Storable+Copy+{cap}>({param_a} a,{param_b} b){{return {expr_a}{op}{expr_b};}}").unwrap();
                        write!(main, "if(true){{{concrete} r={name}({arg_a},{arg_b});if(r[{index}]!={expected}){{return 1;}}}}").unwrap();
                    }
                }
                for left in [false, true] {
                    let name = format!("s{i}{}", usize::from(left));
                    let expr = if left {
                        format!("s*{expr_a}")
                    } else {
                        format!("{expr_a}*s")
                    };
                    write!(
                        helpers,
                        "{owner} {name}<T:Storable+Copy+Mul>({param_a} a,T s){{return {expr};}}"
                    )
                    .unwrap();
                    write!(main, "if(true){{{concrete} r={name}<{scalar}>({arg_a},2);if(r[{index}]!=16){{return 2;}}}}").unwrap();
                }
            }
            write!(main, "if(x[{index}]!=8){{return 3;}}return 0;}}").unwrap();
            let c = compile_source(&SourceFile::new("families.ae", helpers + &main), &[])
                .unwrap_or_else(|e| panic!("{rank} {scalar}: {e:?}"));
            assert_eq!(v23_execute(&c.llvm).code(), Some(0), "{rank} {scalar}");
        }
    }
}

#[test]
fn vertical30_missing_independent_guarantees_and_invalid_instances() {
    for rank in ["Vector<T,Row>", "Matrix<T>"] {
        for (caps, op, missing) in [
            ("Storable+Add", "+", "Copy"),
            ("Storable+Copy", "+", "Add"),
            ("Copy+Add", "+", "Storable"),
            ("Storable+Copy+Add+Mul", "-", "Sub"),
            ("Storable+Copy+Mul", "+", "Add"),
            ("Storable+Mul", "*", "Copy"),
            ("Storable+Copy", "*", "Mul"),
        ] {
            let (param, expr) = if op == "*" {
                ("T b".to_owned(), "*a*b".to_owned())
            } else {
                (format!("ref {rank} b"), format!("*a{op}*b"))
            };
            // Never instantiated: concrete Copy types cannot rescue this body.
            let source = format!(
                "{rank} bad<T:{caps}>(ref {rank} a,{param}){{return {expr};}}int main(){{return 0;}}"
            );
            let errors = compile_source(&SourceFile::new("missing.ae", source), &[]).unwrap_err();
            assert!(
                errors.iter().any(|e| e.message.contains(missing)),
                "{errors:?}"
            );
            if missing != "Storable" {
                assert_eq!(errors[0].code, "E0346");
            }
        }
        for (required, provided, missing) in [
            ("Copy+Add", "Add", "Copy"),
            ("Copy+Add", "Copy", "Add"),
            ("Copy+Sub", "Copy+Add+Mul", "Sub"),
            ("Copy+Mul", "Copy+Add", "Mul"),
        ] {
            let source = format!(
                "{rank} inner<T:Storable+{required}>(ref {rank} a){{return [];}}{rank} outer<T:Storable+{provided}>(ref {rank} a){{return inner(a);}}int main(){{return 0;}}"
            );
            let e = compile_source(&SourceFile::new("forward.ae", source), &[]).unwrap_err();
            assert_eq!(e[0].code, "E0317");
            assert!(e[0].message.contains(missing));
        }
    }
    for (prefix, element, value) in [
        ("", "bool", "true"),
        ("struct Point{int x;}", "Point", "Point(2)"),
    ] {
        let src = format!(
            "{prefix}Matrix<T> add<T:Storable+Copy+Add>(ref Matrix<T> a){{return *a+*a;}}int main(){{Matrix<{element}> a=[{value}];Matrix<{element}>b=add(&a);return 0;}}"
        );
        let e = compile_source(&SourceFile::new("instance.ae", src), &[]).unwrap_err();
        assert_eq!(e[0].code, "E0317");
        assert!(e[0].message.contains("Add"));
    }
}

#[test]
fn vertical30_checked_integer_kernels_trap_after_first_slot() {
    use std::os::unix::process::ExitStatusExt;
    for rank in ["Vector<T,Row>", "Matrix<T>"] {
        for (scalar, value, cap, op, rhs) in [
            ("int8", "127", "Add", "+", "1"),
            ("uint8", "255", "Add", "+", "1"),
            ("int8", "-128", "Sub", "-", "1"),
            ("uint8", "0", "Sub", "-", "1"),
            ("int8", "127", "Mul", "*", "2"),
            ("uint8", "255", "Mul", "*", "2"),
        ] {
            let concrete = rank.replace('T', scalar);
            let (param, expr, init, arg) = if cap == "Mul" {
                (
                    "T b".to_owned(),
                    "*a*b".to_owned(),
                    String::new(),
                    rhs.to_owned(),
                )
            } else {
                (
                    format!("ref {rank} b"),
                    format!("*a{op}*b"),
                    format!("{concrete} b=[1,{rhs}];"),
                    "&b".to_owned(),
                )
            };
            let src = format!(
                "{rank} kernel<T:Storable+Copy+{cap}>(ref {rank} a,{param}){{return {expr};}}int main(){{{concrete}a=[1,{value}];{init}{concrete}c=kernel<{scalar}>(&a,{arg});return 0;}}"
            );
            let c = compile_source(
                &SourceFile::new("overflow.ae", src),
                &[Emit::Mir, Emit::Ssa],
            )
            .unwrap();
            for phase in [Emit::Mir, Emit::Ssa] {
                assert!(c.dumps[&phase].contains("IntegerOverflow"));
            }
            assert_eq!(v23_execute(&c.llvm).signal(), Some(4));
            let llvm = format!("{}\ndeclare void @exit(i32) noreturn\n", c.llvm).replace(
                "trap_integer_overflow:\n  call void @llvm.trap()",
                "trap_integer_overflow:\n  call void @exit(i32 74)",
            );
            assert_eq!(v23_execute(&llvm).code(), Some(74));
        }
    }
}

#[test]
fn vertical30_ieee_kernels_preserve_signed_zero_infinity_and_nan() {
    for ty in ["float32", "float64"] {
        for rank in ["Vector<T,Row>", "Matrix<T>"] {
            for (cap, op, a, b, instruction) in [
                ("Add", "+", "[-z,z,inf,-inf,inf]", "[-z,z,z,z,-inf]", "fadd"),
                ("Sub", "-", "[-z,z,inf,-inf,inf]", "[z,z,z,z,inf]", "fsub"),
                ("Mul", "*", "[-z,z,inf,-inf,nan]", "", "fmul"),
            ] {
                let concrete = rank.replace('T', ty);
                let (param, expr, init, arg) = if cap == "Mul" {
                    ("T b".to_owned(), "*a*b".to_owned(), String::new(), "one")
                } else {
                    (
                        format!("ref {rank} b"),
                        format!("*a{op}*b"),
                        format!("{concrete}b={b};"),
                        "&b",
                    )
                };
                let idx = if rank.starts_with("Matrix") { "1," } else { "" };
                let src = format!(
                    "{rank} kernel<T:Storable+Copy+{cap}>(ref {rank} a,{param}){{return {expr};}}int main(){{{ty} z=0;{ty} one=1;{ty} inf=one/z;{ty} nan=inf-inf;{concrete}a={a};{init}{concrete}r=kernel(&a,{arg});if(one/r[{idx}1]!=-inf){{return 1;}}if(one/r[{idx}2]!=inf){{return 2;}}if(r[{idx}3]!=inf){{return 3;}}if(r[{idx}4]!=-inf){{return 4;}}if(r[{idx}5]==r[{idx}5]){{return 5;}}return 0;}}"
                );
                let c = compile_source(&SourceFile::new("ieee.ae", src), &[]).unwrap();
                let llvm_type = if ty == "float32" { "float" } else { "double" };
                assert!(
                    c.llvm
                        .contains(&format!("_value = {instruction} {llvm_type} "))
                );
                assert_eq!(v23_execute(&c.llvm).code(), Some(0), "{ty} {rank} {cap}");
            }
        }
    }
}

#[test]
fn vertical30_mir_ssa_reject_symbolic_types_and_corrupt_kernel_schedules() {
    use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};
    for rank in ["Vector<T,Row>", "Matrix<T>"] {
        for scaling in [false, true] {
            let concrete = rank.replace('T', "int");
            let expr = if scaling { "a*s" } else { "a+a" };
            let cap = if scaling { "Mul" } else { "Add" };
            let src = format!(
                "{rank} kernel<T:Storable+Copy+{cap}>({rank} a,T s){{return {expr};}}int main(){{{concrete}a=[1,2];{concrete}b=kernel<int>(a,2);return 0;}}"
            );
            let hir = analyze(parse_source(&SourceFile::new("corrupt.ae", src)).unwrap()).unwrap();
            let symbolic = hir.signatures()[0].generic_parameters[0].ty;
            let raw = lower_hir(hir);
            let fi = raw
                .functions
                .iter()
                .position(|f| {
                    f.blocks
                        .iter()
                        .flat_map(|b| &b.instructions)
                        .any(|i| matches!(i.value, Rvalue::ElementwiseBinary { .. }))
                })
                .unwrap();
            let ssa = build_ssa(&verify_mir(raw.clone()).unwrap());
            for case in 0..19 {
                // Scaling's closed tree has its own thirteen corruption recipes.
                if scaling && (13..17).contains(&case) {
                    continue;
                }
                let mut m = raw.clone();
                let owner = m.functions[fi].parameters[0].local;
                let inst = m.functions[fi]
                    .blocks
                    .iter_mut()
                    .flat_map(|b| &mut b.instructions)
                    .find(|i| matches!(i.value, Rvalue::ElementwiseBinary { .. }))
                    .unwrap();
                let Rvalue::ElementwiseBinary { left, kernel, .. } = &mut inst.value else {
                    panic!()
                };
                match case {
                    17 => kernel.element_type = symbolic,
                    18 => *left = aether_middle::Operand::Local(owner),
                    _ if scaling => v28_corrupt_kernel(kernel, case),
                    _ => v27_corrupt_kernel(kernel, case),
                }
                assert!(verify_mir(m).is_err(), "MIR {rank} {scaling} {case}");
                let mut s = ssa.clone();
                let owner = s.functions[fi].parameters[0].value;
                let inst = s.functions[fi]
                    .blocks
                    .iter_mut()
                    .flat_map(|b| &mut b.instructions)
                    .find(|i| matches!(i.op, SsaOp::ElementwiseBinary { .. }))
                    .unwrap();
                let SsaOp::ElementwiseBinary { left, kernel, .. } = &mut inst.op else {
                    panic!()
                };
                match case {
                    17 => kernel.element_type = symbolic,
                    18 => *left = aether_middle::SsaOperand::Value(owner),
                    _ if scaling => v28_corrupt_kernel(kernel, case),
                    _ => v27_corrupt_kernel(kernel, case),
                }
                assert!(verify_ssa(s).is_err(), "SSA {rank} {scaling} {case}");
            }
        }
    }
}

#[test]
fn vertical30_codegen_equivalence_and_deterministic_dumps() {
    use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir};
    for (rank, scalar, params, expr, args, cap) in [
        (
            "Vector<T,Row>",
            "int",
            "ref Vector<T,Row> b",
            "*a+*b",
            "&a",
            "Add",
        ),
        ("Matrix<T>", "double", "T b", "b * *a", "2.0", "Mul"),
    ] {
        let generic = format!(
            "{rank} kernel<T:Storable+Copy+{cap}>(ref {rank} a,{params}){{return {expr};}}"
        );
        let concrete = generic
            .replace(&format!("<T:Storable+Copy+{cap}>"), "")
            .replace('T', scalar);
        let ty = rank.replace('T', scalar);
        let main = format!("int main(){{{ty} a=[1,2];{ty} b=kernel(&a,{args});return 0;}}");
        let mut kernels = Vec::new();
        let mut ssa_kernels = Vec::new();
        let mut llvm_functions = Vec::new();
        for helper in [generic, concrete] {
            let source = SourceFile::new("equivalent.ae", helper + &main);
            let hir = analyze(parse_source(&source).unwrap()).unwrap();
            let m = verify_mir(lower_hir(hir)).unwrap();
            let kernel = m
                .as_mir()
                .functions
                .iter()
                .flat_map(|f| &f.blocks)
                .flat_map(|b| &b.instructions)
                .find_map(|i| match &i.value {
                    Rvalue::ElementwiseBinary { kernel, .. } => Some(kernel.clone()),
                    _ => None,
                })
                .unwrap();
            kernels.push(kernel);
            let s = build_ssa(&m);
            ssa_kernels.push(
                s.functions
                    .iter()
                    .flat_map(|f| &f.blocks)
                    .flat_map(|b| &b.instructions)
                    .find_map(|i| match &i.op {
                        SsaOp::ElementwiseBinary { kernel, .. } => Some(kernel.clone()),
                        _ => None,
                    })
                    .unwrap(),
            );
            let c = compile_source(&source, &[Emit::Hir, Emit::Mir, Emit::Ssa]).unwrap();
            let repeat = compile_source(&source, &[Emit::Hir, Emit::Mir, Emit::Ssa]).unwrap();
            assert_eq!(c.dumps, repeat.dumps);
            assert_eq!(c.llvm, repeat.llvm);
            let function = c
                .llvm
                .split("define ")
                .find(|f| f.contains("; ElementwiseBegin "))
                .unwrap()
                .split("\n}")
                .next()
                .unwrap();
            let (return_type, rest) = function.split_once('@').unwrap();
            let (_, body) = rest.split_once('(').unwrap();
            llvm_functions.push(format!("{return_type}@kernel({body}"));
        }
        assert_eq!(kernels[0], kernels[1]);
        assert_eq!(ssa_kernels[0], ssa_kernels[1]);
        assert_eq!(llvm_functions[0], llvm_functions[1]);
    }
}

#[test]
fn vertical30_shape_mismatch_precedes_result_allocation() {
    for (rank, lhs, rhs) in [
        ("Vector<T,Row>", "[1,2]", "[1]"),
        ("Vector<T,Column>", "[]", "[1]"),
        ("Matrix<T>", "[1,2,3;4,5,6]", "[1,2;3,4;5,6]"),
        ("Matrix<T>", "[1,2]", "[1,2,3]"),
        ("Matrix<T>", "[1]", "[]"),
    ] {
        for (cap, op) in [("Add", "+"), ("Sub", "-")] {
            let ty = rank.replace('T', "int");
            let source = format!(
                "{rank} kernel<T:Storable+Copy+{cap}>(ref {rank} a,ref {rank} b){{return *a{op}*b;}}int main(){{{ty}a={lhs};{ty}b={rhs};{ty}c=kernel(&a,&b);return 0;}}"
            );
            let c = compile_source(&SourceFile::new("shape.ae", source), &[]).unwrap();
            let mut llvm = String::new();
            for line in c.llvm.lines() {
                writeln!(llvm, "{line}").unwrap();
                if let Some(id) = line.trim().strip_prefix("; ElementwiseBegin ") {
                    writeln!(llvm,"  %probe{id} = load i64, ptr @aether_heap_alloc_count\n  store i64 %probe{id}, ptr @v30_start").unwrap();
                }
            }
            llvm.push_str("@v30_start = internal global i64 0\ndeclare void @exit(i32) noreturn\n");
            llvm=llvm.replace("trap_shape_mismatch:\n  ; structured Aether trap: ShapeMismatch\n  call void @llvm.trap()", "trap_shape_mismatch:\n  %before = load i64, ptr @v30_start\n  %after = load i64, ptr @aether_heap_alloc_count\n  %same = icmp eq i64 %before, %after\n  %code = select i1 %same, i32 73, i32 99\n  call void @exit(i32 %code)");
            assert_eq!(v23_execute(&llvm).code(), Some(73));
        }
    }
}

#[test]
fn vertical30_cross_module_strided_kernels() {
    let (_, status) = run_path(
        &module_program("v30_kernels"),
        &[],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(0));
}

mod vertical31;

mod vertical32;

mod vertical33;

#[test]
fn math_arch_1_double_transpose_preserves_product_and_owners() {
    let (_, status) = run_path(
        &program("math_arch_1_double_transpose.ae"),
        &[],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(status.code(), Some(0));
}
