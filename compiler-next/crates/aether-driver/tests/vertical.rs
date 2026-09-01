//! Cross-layer and native qualification for NEXT-VERTICAL-2.

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
