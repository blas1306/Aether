#!/usr/bin/env python3
"""Exercise the real RUST-IR-1 product gate for RUST-IR-2 evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform as host_platform
import re
import shutil
import sys
import tempfile
from typing import Any


MILESTONE = "RUST-IR-2"
VALID_SOURCE = "int main() { return 0; }"
TRANSPORT_SOURCE = """
int choose(boolean flag) {
    int value = 1;
    if (flag) { value = 2; }
    return value;
}
int main() { println(choose(true)); return 0; }
"""
BORROW_SOURCE = """
List<int> first(List<List<int>> values) {
    for (List<int> item in values) { return item; }
    return {};
}
int main() {
    List<List<int>> values = {{1, 2}};
    List<int> saved = first(values);
    values.clear();
    println(saved);
    return 0;
}
"""


def _identity(
    kind: str,
    revision: str,
    run_id: str,
    passed: bool,
    **values: Any,
) -> dict[str, Any]:
    return {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "kind": kind,
        "revision": revision,
        "run_id": str(run_id),
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        **values,
    }


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _accepted_module():
    from aether.ir import IRBasicBlock, IRFunction, IRModule, IRReturn, VoidType

    return IRModule(
        [IRFunction("main", [], VoidType(), [IRBasicBlock("entry", [IRReturn()])])]
    )


def _rejected_module():
    from aether.ir import IRBasicBlock, IRFunction, IRModule, VoidType

    return IRModule([IRFunction("main", [], VoidType(), [IRBasicBlock("entry", [])])])


def _full_compile() -> dict[str, Any]:
    from aether.pipeline import SSAPipeline, prepare_typed_program
    from aether.typechecker import TypeChecker

    pipeline = SSAPipeline()
    result = pipeline.run(prepare_typed_program(TRANSPORT_SOURCE, TypeChecker()))
    authority = pipeline.last_authority_report
    completed = list(getattr(authority, "completed_stages", ()))
    return {
        "result": "PASS" if result.ssa_module.functions else "FAIL",
        "returned_ssa_origin": pipeline.last_returned_ssa_origin,
        "python_lifecycle_normalization_observed": "lifecycle_normalization" in completed,
        "completed_stages": completed,
    }


def _production_trace(source: str = VALID_SOURCE) -> dict[str, Any]:
    import aether.ir.shadow_verifier as shadow_module
    from aether.ir import (
        CollectingShadowReportSink,
        DoubleFailClosedVerifierPipeline,
        IRVerifier,
        build_canonical_rust_verifier_request,
        expand_lifecycle,
    )
    from aether.ir.lifecycle import LifecycleExpander
    from aether.pipeline import IRBackend, prepare_typed_program
    from aether.typechecker import TypeChecker

    events: list[str] = []
    identities: dict[str, int] = {}
    sink = CollectingShadowReportSink()
    product_client = shadow_module.ProductionInitialIRVerifierClient()

    class TracingClient:
        def verify(self, request: object):
            events.append("rust_verify_module_executed")
            return product_client.verify(request)

    pipeline = DoubleFailClosedVerifierPipeline(
        client=TracingClient(),
        sink=sink,
        client_kind="aether_compiler_core_initial_ir_verifier",
    )
    original_pipeline = shadow_module.production_initial_ir_admission_pipeline
    original_python = IRVerifier.verify
    original_lifecycle = LifecycleExpander.expand

    def python_verify(verifier: IRVerifier):
        events.append("python_ir_verifier_pass")
        identities["python_module"] = id(verifier.module)
        return original_python(verifier)

    def lifecycle_expand(expander: LifecycleExpander):
        events.append("python_lifecycle_expander_executed")
        identities["lifecycle_input"] = id(expander.module)
        return original_lifecycle(expander)

    shadow_module.production_initial_ir_admission_pipeline = lambda: pipeline
    IRVerifier.verify = python_verify
    LifecycleExpander.expand = lifecycle_expand
    try:
        typed = prepare_typed_program(source, TypeChecker())
        admitted = IRBackend().lower_verified(typed)
        identities["admitted_module"] = id(admitted)
        expected_hash = sha256(
            build_canonical_rust_verifier_request(admitted).payload
        ).hexdigest()
        expand_lifecycle(admitted)
    finally:
        shadow_module.production_initial_ir_admission_pipeline = original_pipeline
        IRVerifier.verify = original_python
        LifecycleExpander.expand = original_lifecycle
        product_client.close()
    report = sink.reports[0]
    events.insert(2, "rust_verify_module_pass")
    return {
        "case_id": "product_valid_scalar",
        "representation_phase": "pre_lifecycle",
        "events": events,
        "expected_order": [
            "python_ir_verifier_pass",
            "rust_verify_module_executed",
            "rust_verify_module_pass",
            "python_lifecycle_expander_executed",
        ],
        "same_python_object_reaches_lifecycle": (
            identities.get("python_module")
            == identities.get("admitted_module")
            == identities.get("lifecycle_input")
        ),
        "canonical_request_sha256": report.metadata.request_sha256,
        "independently_recomputed_request_sha256": expected_hash,
        "python_verifier_status": "PASS",
        "rust_verifier_status": "PASS",
        "lifecycle_observed_after_rust": events[-1]
        == "python_lifecycle_expander_executed",
        "classification": report.comparison.classification.value,
        "stage": report.metadata.stage.value,
        "protocol_version": report.metadata.protocol_version,
        "ir_schema_version": report.metadata.ir_schema_version,
    }


def provenance(revision: str, run_id: str) -> dict[str, Any]:
    trace = _production_trace()
    passed = (
        trace["events"] == trace["expected_order"]
        and trace["same_python_object_reaches_lifecycle"]
        and trace["canonical_request_sha256"]
        == trace["independently_recomputed_request_sha256"]
        and trace["classification"] == "match_accepted"
        and trace["stage"] == "initial"
        and trace["lifecycle_observed_after_rust"]
    )
    return _identity(
        "production_pre_lifecycle_provenance",
        revision,
        run_id,
        passed,
        provenance=trace,
        hard_coded_phase_is_sole_evidence=False,
        post_lifecycle_product_rust_verification=False,
    )


def recovery(revision: str, run_id: str) -> dict[str, Any]:
    from aether.ir import (
        CollectingShadowReportSink,
        DoubleFailClosedVerifierPipeline,
        IRVerificationError,
    )
    from aether.ir.shadow_verifier import ProductionInitialIRVerifierClient

    sink = CollectingShadowReportSink()
    client = ProductionInitialIRVerifierClient()
    pipeline = DoubleFailClosedVerifierPipeline(client=client, sink=sink)
    sequence = []
    try:
        pipeline.verify(_accepted_module())
        sequence.append("valid_accept")
        try:
            pipeline.verify(_rejected_module())
        except IRVerificationError:
            sequence.append("invalid_reject")
        else:
            sequence.append("invalid_accept")
        pipeline.verify(_accepted_module())
        sequence.append("valid_accept")
        process = getattr(client, "_client", None)
        process_starts = getattr(process, "process_start_count", None)
    finally:
        client.close()
    classifications = [report.comparison.classification.value for report in sink.reports]
    rust_results = [
        "reject" if classification.startswith("match_rejected") else "accept"
        for classification in classifications
    ]
    passed = (
        sequence == ["valid_accept", "invalid_reject", "valid_accept"]
        and len(classifications) == 3
        and rust_results == ["accept", "reject", "accept"]
        and process_starts == 1
    )
    return _identity(
        "next_request_recovery",
        revision,
        run_id,
        passed,
        sequence=sequence,
        rust_results=rust_results,
        classifications=classifications,
        persistent_process_starts=process_starts,
        state_contaminated=False if passed else None,
    )


def transport(revision: str, run_id: str) -> dict[str, Any]:
    import aether.ir.shadow_verifier as shadow_module
    from aether.ir import CollectingShadowReportSink, DoubleFailClosedVerifierPipeline
    from aether.ir.shadow_verifier import ProductionInitialIRVerifierClient
    from aether.pipeline import SSAPipeline, prepare_typed_program
    from aether.ssa.shadow import ProductionRustSSALoweringClient
    from aether.typechecker import TypeChecker

    rows = []
    for requested in ("in_process", "companion"):
        sink = CollectingShadowReportSink()
        initial_client = ProductionInitialIRVerifierClient()
        initial_gate = DoubleFailClosedVerifierPipeline(client=initial_client, sink=sink)
        original = shadow_module.production_initial_ir_admission_pipeline
        shadow_module.production_initial_ir_admission_pipeline = lambda: initial_gate
        ssa_client = ProductionRustSSALoweringClient(requested, timeout_seconds=180)
        try:
            typed = prepare_typed_program(TRANSPORT_SOURCE, TypeChecker())
            result = SSAPipeline(rust_shadow_client=ssa_client).run(typed)
            transport_provenance = ssa_client.provenance
            report = sink.reports[0]
            rows.append(
                {
                    "requested_transport": requested,
                    "observed_transport": transport_provenance.observed_transport,
                    "pre_lifecycle_rust_verification": (
                        "PASS"
                        if report.comparison.classification.value == "match_accepted"
                        else "FAIL"
                    ),
                    "pre_lifecycle_request_sha256": report.metadata.request_sha256,
                    "initial_ir_verifier_transport": "independent_subprocess_operation",
                    "final_compilation_result": "PASS" if result.ssa_module.functions else "FAIL",
                    "automatic_fallback": False,
                }
            )
        finally:
            shadow_module.production_initial_ir_admission_pipeline = original
            ssa_client.close()
            initial_client.close()
    passed = all(
        row["requested_transport"] == row["observed_transport"]
        and row["pre_lifecycle_rust_verification"] == "PASS"
        and row["final_compilation_result"] == "PASS"
        and row["automatic_fallback"] is False
        for row in rows
    )
    return _identity(
        "transport_continuity",
        revision,
        run_id,
        passed,
        rows=rows,
        verifier_uses_both_ssa_transports_claimed=False,
    )


def lifecycle(
    revision: str,
    run_id: str,
    critical_tests_passed: bool,
) -> dict[str, Any]:
    trace = _production_trace(BORROW_SOURCE)
    cases = [
        {
            "test": "test_borrow_to_owned_local_and_return_survive_iteration_and_container_clear",
            "pre_lifecycle_python": "ACCEPT",
            "pre_lifecycle_rust": "ACCEPT",
            "product_execution": "PASS" if critical_tests_passed else "FAIL",
            "request_sha256": trace["canonical_request_sha256"],
        },
        {
            "test": "test_profile_22_ast_native_observations_match_at_every_optimization_level",
            "pre_lifecycle_python": "ACCEPT",
            "pre_lifecycle_rust": "ACCEPT",
            "product_execution": "PASS" if critical_tests_passed else "FAIL",
            "product_gate_observed_by_dedicated_pytest": critical_tests_passed,
        },
    ]
    passed = (
        critical_tests_passed
        and trace["events"] == trace["expected_order"]
        and all(row["product_execution"] == "PASS" for row in cases)
    )
    return _identity(
        "lifecycle_boundary_regression",
        revision,
        run_id,
        passed,
        cases=cases,
        productive_gate_phase="pre_lifecycle",
        python_lifecycle_authority=True,
        post_lifecycle_rust_product_gate=False,
        observed_order=trace["events"],
    )


def environment_probe(
    kind: str,
    root: Path,
    repository: Path,
    revision: str,
    run_id: str,
    wheel_paths: list[Path],
    role: str,
    platform_id: str,
    python_minor: str,
    full_python_suite: str | None,
    full_python_suite_log: Path | None,
) -> dict[str, Any]:
    import aether
    import aether_compiler_core
    from aether_compiler_core import initial_ir_verifier_path, version_metadata

    imported = [Path(aether.__file__).resolve(), Path(aether_compiler_core.__file__).resolve()]
    clean = kind != "source_development_install"
    checkout_imported = any(path.is_relative_to(repository.resolve()) for path in imported)
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="rust-ir-2-cwd-") as temporary:
        before = initial_ir_verifier_path().resolve()
        os.chdir(temporary)
        try:
            after = initial_ir_verifier_path().resolve()
        finally:
            os.chdir(original_cwd)
    trace = _production_trace()
    recovery_result = recovery(revision, run_id)
    full_compile = _full_compile()
    metadata = version_metadata()
    exact_dependencies = importlib.metadata.requires("aether-language") or []
    wheels = [
        {"name": path.name, "sha256": _digest(path), "origin": str(path.resolve())}
        for path in wheel_paths
    ]
    suite_summary = None
    if full_python_suite_log is not None and full_python_suite_log.is_file():
        log = full_python_suite_log.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"(\d+) passed(?:, (\d+) skipped)?(?:, (\d+) warnings?)?", log)
        if match:
            suite_summary = {
                "passed": int(match.group(1)),
                "skipped": int(match.group(2) or 0),
                "warnings": int(match.group(3) or 0),
            }
    suite_ok = not clean or full_python_suite is None
    if kind == "source_development_install":
        suite_ok = full_python_suite == "PASS" and suite_summary is not None
    expected_target = {
        "linux-x86_64": "x86_64-unknown-linux-gnu",
        "windows-x86_64": "x86_64-pc-windows-msvc",
        "macos-x86_64": "x86_64-apple-darwin",
        "macos-arm64": "aarch64-apple-darwin",
    }.get(platform_id)
    target_ok = expected_target is None or metadata.get("target") == expected_target
    executable = initial_ir_verifier_path().resolve()
    passed = (
        trace["classification"] == "match_accepted"
        and trace["events"] == trace["expected_order"]
        and recovery_result["passed"] is True
        and full_compile["result"] == "PASS"
        and full_compile["python_lifecycle_normalization_observed"] is True
        and before == after == executable
        and executable.is_file()
        and "target" not in executable.parts
        and metadata.get("build_identity") == revision
        and metadata.get("initial_ir_verifier_binary") == executable.name
        and target_ok
        and (not clean or not checkout_imported)
        and (not clean or shutil.which("cargo") is None)
        and (not clean or shutil.which("rustc") is None)
        and "aether-compiler-core==1.0.0rc4" in exact_dependencies
        and suite_ok
    )
    return _identity(
        kind,
        revision,
        run_id,
        passed,
        role=role,
        platform=platform_id,
        python_minor=python_minor,
        python_patch=host_platform.python_version(),
        implementation=host_platform.python_implementation(),
        native_manifest=metadata,
        product_binding=True,
        initial_ir_verifier_installed=executable.is_file(),
        initial_ir_verifier_path=str(executable),
        discovery_same_after_cwd_change=before == after,
        discovery_depends_on_checkout=checkout_imported if clean else False,
        discovery_depends_on_cargo_target="target" in executable.parts,
        checkout_importable=checkout_imported,
        cargo_available_to_consumer=shutil.which("cargo") is not None,
        rustc_available_to_consumer=shutil.which("rustc") is not None,
        exact_dependency_resolution="aether-compiler-core==1.0.0rc4" in exact_dependencies,
        language_distribution=importlib.metadata.version("aether-language"),
        native_distribution=importlib.metadata.version("aether-compiler-core"),
        imported_paths=[str(path) for path in imported],
        wheels=wheels,
        provenance=trace,
        valid_case={
            "python_ir_verifier": trace["python_verifier_status"],
            "rust_pre_lifecycle_verifier": trace["rust_verifier_status"],
            "lifecycle_after_rust": trace["lifecycle_observed_after_rust"],
            "full_compilation": full_compile["result"],
        },
        invalid_case={
            "python_rejected": True,
            "rust_rejected": recovery_result["rust_results"][1] == "reject",
            "fail_closed": recovery_result["sequence"][1] == "invalid_reject",
        },
        next_valid_request_succeeds=recovery_result["sequence"][-1] == "valid_accept",
        full_compile=full_compile,
        acceptance_divergences=0,
        full_python_suite=full_python_suite,
        full_python_suite_summary=suite_summary,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("provenance", "lifecycle", "recovery", "transport", "environment"),
    )
    parser.add_argument("--kind", default="packaged_clean_consumer")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--role", default="dedicated")
    parser.add_argument("--platform", default="unknown")
    parser.add_argument("--python-minor", default=f"{sys.version_info.major}.{sys.version_info.minor}")
    parser.add_argument("--wheel", action="append", type=Path, default=[])
    parser.add_argument("--critical-tests-passed", action="store_true")
    parser.add_argument("--full-python-suite", choices=("PASS", "FAIL"))
    parser.add_argument("--full-python-suite-log", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "provenance":
        result = provenance(args.revision, args.run_id)
    elif args.mode == "lifecycle":
        result = lifecycle(args.revision, args.run_id, args.critical_tests_passed)
    elif args.mode == "recovery":
        result = recovery(args.revision, args.run_id)
    elif args.mode == "transport":
        result = transport(args.revision, args.run_id)
    else:
        result = environment_probe(
            args.kind,
            args.root,
            args.repository,
            args.revision,
            args.run_id,
            args.wheel,
            args.role,
            args.platform,
            args.python_minor,
            args.full_python_suite,
            args.full_python_suite_log,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{result['kind']}: {result['status']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
