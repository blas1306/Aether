//! End-to-end tests for the real stdin/stdout executable.

use std::io::Write as _;
use std::process::{Command, Output, Stdio};

use serde_json::Value;

const ACCEPTED: &[u8] = include_bytes!("fixtures/accepted.json");
const REJECTED: &[u8] = include_bytes!("fixtures/rejected.json");
const IRV_026: &[u8] = include_bytes!("fixtures/irv_026_storage_return.json");
const INTENTIONAL_IRV_024: &[u8] = include_bytes!("fixtures/intentional_irv_024.json");
const MALFORMED: &[u8] = include_bytes!("fixtures/malformed.json");
const UNSUPPORTED_PROTOCOL: &[u8] = include_bytes!("fixtures/unsupported_protocol.json");
const UNSUPPORTED_SCHEMA: &[u8] = include_bytes!("fixtures/unsupported_schema.json");
const IMPORT_FAILURE: &[u8] = include_bytes!("fixtures/import_failure.json");
const INVALID_OPERATION: &[u8] = include_bytes!("fixtures/invalid_operation.json");
const SCHEMA_BOUNDARY_INTEGER: &[u8] = include_bytes!("fixtures/schema_boundary_integer.json");

fn run(input: &[u8]) -> Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_aether-ir-verifier"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("verifier binary must start");
    child
        .stdin
        .take()
        .expect("stdin must be piped")
        .write_all(input)
        .expect("request must be written");
    child.wait_with_output().expect("verifier must terminate")
}

fn value(output: &Output) -> Value {
    serde_json::from_slice(&output.stdout).expect("stdout must be one JSON response")
}

fn assert_normal_process_result(output: &Output) {
    assert_eq!(output.status.code(), Some(0));
    assert!(output.stderr.is_empty());
    let body = output
        .stdout
        .strip_suffix(b"\n")
        .expect("stdout must end with one newline");
    assert!(!body.contains(&b'\n'));
}

#[test]
fn accepted_request_uses_exact_stdin_stdout_contract() {
    let output = run(ACCEPTED);

    assert_normal_process_result(&output);
    assert_eq!(
        output.stdout,
        b"{\"protocol_version\":1,\"status\":\"accepted\"}\n"
    );
}

#[test]
fn semantic_rejections_are_successful_protocol_results() {
    for (fixture, invariant, instruction_kind) in [
        (REJECTED, "IRV-018", None),
        (IRV_026, "IRV-026", Some("return")),
    ] {
        let output = run(fixture);
        assert_normal_process_result(&output);
        let response = value(&output);

        assert_eq!(response["status"], "rejected");
        assert_eq!(response["diagnostic"]["invariant"], invariant);
        assert_eq!(
            response["diagnostic"]["context"]["instruction_kind"].as_str(),
            instruction_kind
        );
    }
}

#[test]
fn intentional_irv_024_cycle_is_accepted_by_the_rust_graph_analysis() {
    let output = run(INTENTIONAL_IRV_024);

    assert_normal_process_result(&output);
    assert_eq!(value(&output)["status"], "accepted");
}

#[test]
fn infrastructure_failures_have_distinct_stable_kinds() {
    for (fixture, kind) in [
        (b"".as_slice(), "empty_input"),
        (MALFORMED, "malformed_json"),
        (UNSUPPORTED_PROTOCOL, "unsupported_protocol_version"),
        (UNSUPPORTED_SCHEMA, "unsupported_ir_schema_version"),
        (IMPORT_FAILURE, "module_import"),
        (INVALID_OPERATION, "unsupported_operation"),
        (SCHEMA_BOUNDARY_INTEGER, "module_schema"),
    ] {
        let output = run(fixture);
        assert_normal_process_result(&output);
        let response = value(&output);

        assert_eq!(response["status"], "error");
        assert_eq!(response["error"]["kind"], kind);
    }
}

#[test]
fn repeated_execution_is_byte_for_byte_deterministic() {
    for fixture in [ACCEPTED, REJECTED, IRV_026, MALFORMED, IMPORT_FAILURE] {
        let first = run(fixture);
        let second = run(fixture);

        assert_normal_process_result(&first);
        assert_normal_process_result(&second);
        assert_eq!(first.stdout, second.stdout);
    }
}
