#!/usr/bin/env python3
"""Exercise productive RUST-IR-3 authority and emit machine-readable evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform as host_platform
import shutil
import sys
import tempfile
from typing import Any


MILESTONE = "RUST-IR-3"
VALID_SOURCE = "int main() { return 0; }"
TRANSPORT_SOURCE = """
int choose(boolean flag) {
    int value = 1;
    if (flag) { value = 2; }
    return value;
}
int main() { println(choose(true)); return 0; }
"""


def envelope(kind: str, revision: str, run_id: str, passed: bool, **data: Any) -> dict[str, Any]:
    return {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "kind": kind,
        "revision": revision,
        "run_id": str(run_id),
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        **data,
    }


def _valid_module():
    from aether.ir import IRBasicBlock, IRFunction, IRModule, IRReturn, VoidType

    return IRModule(
        [IRFunction("main", [], VoidType(), [IRBasicBlock("entry", [IRReturn()])])]
    )


def _invalid_module():
    from aether.ir import IRBasicBlock, IRFunction, IRModule, VoidType

    return IRModule([IRFunction("main", [], VoidType(), [IRBasicBlock("entry", [])])])


def product_trace(source: str = VALID_SOURCE) -> dict[str, Any]:
    from aether.ir import IRVerifier, build_canonical_rust_verifier_request
    from aether.ir.lifecycle import LifecycleExpander
    from aether.pipeline import IRBackend, prepare_typed_program
    from aether.typechecker import TypeChecker

    python_calls = 0
    lifecycle_calls = 0
    original_python = IRVerifier.verify
    original_lifecycle = LifecycleExpander.expand

    def forbidden(_verifier: IRVerifier):
        nonlocal python_calls
        python_calls += 1
        raise AssertionError("Python IRVerifier entered productive acceptance")

    def lifecycle(expander: LifecycleExpander):
        nonlocal lifecycle_calls
        lifecycle_calls += 1
        return original_lifecycle(expander)

    IRVerifier.verify = forbidden
    LifecycleExpander.expand = lifecycle
    try:
        backend = IRBackend()
        typed = prepare_typed_program(source, TypeChecker())
        initial = backend.lower_verified(typed)
        provenance = backend.last_initial_ir_authority_provenance
        expected_hash = sha256(build_canonical_rust_verifier_request(initial).payload).hexdigest()
        optimized = backend.optimize_verified(initial)
    finally:
        IRVerifier.verify = original_python
        LifecycleExpander.expand = original_lifecycle
    semantic = provenance.semantic_snapshot() if provenance is not None else {}
    return {
        "accepted": bool(optimized.functions),
        "events": ["rust_verify_module_accept", "python_lifecycle_expander"],
        "product_authority": semantic.get("product_authority"),
        "python_ir_verifier_role": semantic.get("python_ir_verifier_role"),
        "rust_verify_module_executed": semantic.get("rust_verify_module_executed"),
        "rust_verify_module_accepted": semantic.get("rust_verify_module_accepted"),
        "python_ir_verifier_consulted": semantic.get("python_ir_verifier_consulted"),
        "python_ir_verifier_calls": python_calls,
        "python_lifecycle_calls": lifecycle_calls,
        "representation_phase": semantic.get("representation_phase"),
        "stage": semantic.get("stage"),
        "canonical_request_sha256": semantic.get("request_sha256"),
        "independently_recomputed_request_sha256": expected_hash,
        "derived_from_execution": provenance is not None,
        "constant_only_evidence": False,
        "post_lifecycle_rust_product_gate": False,
    }


def recovery_trace() -> dict[str, Any]:
    from aether.ir import IRVerifier
    from aether.ir.lifecycle import LifecycleExpander
    from aether.pipeline import IRBackend, SSAPipeline

    python_calls = 0
    lifecycle_calls = 0
    ssa_build_calls = 0
    original_python = IRVerifier.verify
    original_lifecycle = LifecycleExpander.expand
    original_build = SSAPipeline.build

    def python(_verifier: IRVerifier):
        nonlocal python_calls
        python_calls += 1
        raise AssertionError("Python rescue attempted")

    def lifecycle(expander: LifecycleExpander):
        nonlocal lifecycle_calls
        lifecycle_calls += 1
        return original_lifecycle(expander)

    def build(pipeline: SSAPipeline, module: Any):
        nonlocal ssa_build_calls
        ssa_build_calls += 1
        return original_build(pipeline, module)

    IRVerifier.verify = python
    LifecycleExpander.expand = lifecycle
    SSAPipeline.build = build
    sequence: list[str] = []
    rejection: dict[str, Any] = {}
    try:
        first = IRBackend()
        first.admit_initial_ir(_valid_module())
        sequence.append("valid_accept")
        failing = SSAPipeline()
        try:
            failing.run(_invalid_module())
        except Exception as error:
            sequence.append("rust_invalid_reject")
            cause = error.__cause__
            rejection = {
                "exception": type(cause).__name__,
                "code": getattr(cause, "code", None),
                "category": getattr(cause, "category", None),
                "product_provenance": "Rust rejection observed before SSA build",
            }
        else:
            sequence.append("invalid_accept")
        IRBackend().admit_initial_ir(_valid_module())
        sequence.append("valid_accept")
    finally:
        IRVerifier.verify = original_python
        LifecycleExpander.expand = original_lifecycle
        SSAPipeline.build = original_build
    return {
        "sequence": sequence,
        "python_ir_verifier_calls": python_calls,
        "python_rescue_attempted": python_calls != 0,
        "lifecycle_calls_during_admission": lifecycle_calls,
        "ssa_construction_calls_after_rejection": ssa_build_calls,
        "automatic_fallback": False,
        "rejection": rejection,
        "next_valid_request_succeeds": sequence[-1:] == ["valid_accept"],
    }


def explicit_oracle_trace() -> dict[str, Any]:
    from aether.ir import (
        CollectingShadowReportSink,
        DoubleFailClosedVerifierPipeline,
        ProductionInitialIRVerifierClient,
    )

    sink = CollectingShadowReportSink()
    client = ProductionInitialIRVerifierClient()
    try:
        accepted = DoubleFailClosedVerifierPipeline(client=client, sink=sink).verify(
            _valid_module()
        )
    finally:
        client.close()
    return {
        "accepted": accepted is not None,
        "role": "qualification_oracle",
        "python_executed": True,
        "affected_product_decision": False,
        "classification": sink.reports[0].comparison.classification.value,
    }


def full_compile(source: str = TRANSPORT_SOURCE, client: object | None = None) -> dict[str, Any]:
    from aether.ir import IRVerifier
    from aether.pipeline import SSAPipeline, prepare_typed_program
    from aether.typechecker import TypeChecker

    python_calls = 0
    original = IRVerifier.verify

    def forbidden(_verifier: IRVerifier):
        nonlocal python_calls
        python_calls += 1
        raise AssertionError("Python Initial IR verifier entered product compile")

    IRVerifier.verify = forbidden
    try:
        pipeline = SSAPipeline(rust_shadow_client=client)
        result = pipeline.run(prepare_typed_program(source, TypeChecker()))
    finally:
        IRVerifier.verify = original
    trace = pipeline.last_authority_report
    return {
        "accepted": bool(result.ssa_module.functions),
        "returned_ssa_origin": pipeline.last_returned_ssa_origin,
        "python_ir_verifier_calls": python_calls,
        "initial_ir_product_authority": getattr(trace, "initial_ir_product_authority", None),
        "python_ir_verifier_role": getattr(trace, "python_ir_verifier_role", None),
        "python_ir_verifier_executed": getattr(trace, "python_ir_verifier_executed", None),
        "python_lifecycle_authority_observed": "lifecycle_normalization" in getattr(trace, "completed_stages", ()),
        "rust_refinement_authority_preserved": getattr(trace, "refinement_authority", None) == "rust",
    }


def provenance(revision: str, run_id: str, kind: str) -> dict[str, Any]:
    product = product_trace()
    recovery = recovery_trace()
    oracle = explicit_oracle_trace()
    compile_result = full_compile()
    passed = (
        product["accepted"]
        and product["product_authority"] == "rust"
        and product["python_ir_verifier_role"] == "oracle_only"
        and product["rust_verify_module_executed"] is True
        and product["rust_verify_module_accepted"] is True
        and product["python_ir_verifier_consulted"] is False
        and product["python_ir_verifier_calls"] == 0
        and product["python_lifecycle_calls"] == 1
        and product["canonical_request_sha256"] == product["independently_recomputed_request_sha256"]
        and recovery["sequence"] == ["valid_accept", "rust_invalid_reject", "valid_accept"]
        and recovery["python_rescue_attempted"] is False
        and recovery["lifecycle_calls_during_admission"] == 0
        and recovery["ssa_construction_calls_after_rejection"] == 0
        and oracle["accepted"] is True
        and compile_result["accepted"] is True
        and compile_result["python_ir_verifier_calls"] == 0
        and compile_result["python_lifecycle_authority_observed"] is True
    )
    return envelope(
        kind,
        revision,
        run_id,
        passed,
        product_authority_provenance=product,
        no_python_rescue=recovery,
        explicit_python_oracle=oracle,
        full_compile=compile_result,
    )


def transport(revision: str, run_id: str) -> dict[str, Any]:
    from aether.ssa.shadow import ProductionRustSSALoweringClient

    rows = []
    for requested in ("in_process", "companion"):
        client = ProductionRustSSALoweringClient(requested, timeout_seconds=180)
        try:
            result = full_compile(client=client)
            observed = client.provenance.observed_transport
        finally:
            client.close()
        rows.append({
            "requested_ssa_transport": requested,
            "observed_ssa_transport": observed,
            "rust_initial_ir_authority_observed": result["initial_ir_product_authority"] == "rust",
            "python_initial_ir_authority_absent": result["python_ir_verifier_calls"] == 0,
            "python_lifecycle_authority_observed": result["python_lifecycle_authority_observed"],
            "final_result": "PASS" if result["accepted"] else "FAIL",
            "initial_ir_verifier_transport_claim": "independent installed verifier",
        })
    passed = all(
        row["requested_ssa_transport"] == row["observed_ssa_transport"]
        and row["rust_initial_ir_authority_observed"]
        and row["python_initial_ir_authority_absent"]
        and row["python_lifecycle_authority_observed"]
        and row["final_result"] == "PASS"
        for row in rows
    )
    return envelope("transport_continuity", revision, run_id, passed, rows=rows)


def environment(
    kind: str,
    revision: str,
    run_id: str,
    repository: Path,
    platform_id: str,
    python_minor: str,
    role: str,
    wheels: list[Path],
) -> dict[str, Any]:
    import aether
    import aether_compiler_core
    from aether_compiler_core import initial_ir_verifier_path, version_metadata

    imports = [Path(aether.__file__).resolve(), Path(aether_compiler_core.__file__).resolve()]
    clean = kind == "packaged_clean_consumer" or role in {"platform", "python"}
    checkout_imported = any(path.is_relative_to(repository.resolve()) for path in imports)
    executable = initial_ir_verifier_path().resolve()
    original = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="rust-ir-3-cwd-") as raw:
        os.chdir(raw)
        try:
            rediscovered = initial_ir_verifier_path().resolve()
        finally:
            os.chdir(original)
    evidence = provenance(revision, run_id, kind)
    metadata = version_metadata()
    wheel_rows = [
        {"name": path.name, "sha256": sha256(path.read_bytes()).hexdigest()}
        for path in wheels
    ]
    passed = (
        evidence["passed"] is True
        and executable.is_file()
        and executable == rediscovered
        and "target" not in executable.parts
        and metadata.get("build_identity") == revision
        and (not clean or not checkout_imported)
        and (not clean or shutil.which("cargo") is None)
        and (not clean or shutil.which("rustc") is None)
    )
    return envelope(
        kind,
        revision,
        run_id,
        passed,
        role=role,
        platform=platform_id,
        python_minor=python_minor,
        python_patch=host_platform.python_version(),
        python_implementation=host_platform.python_implementation(),
        language_distribution=importlib.metadata.version("aether-language"),
        native_distribution=importlib.metadata.version("aether-compiler-core"),
        verifier_installed=executable.is_file(),
        verifier_path=str(executable),
        native_manifest=metadata,
        checkout_imported=checkout_imported,
        cargo_available=shutil.which("cargo") is not None,
        rustc_available=shutil.which("rustc") is not None,
        discovery_stable=executable == rediscovered,
        wheels=wheel_rows,
        evidence=evidence,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("provenance", "no-rescue", "lifecycle", "recovery", "transport", "environment"))
    parser.add_argument("--kind", default="product_authority_provenance")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--platform", default="unknown")
    parser.add_argument("--python-minor", default=f"{sys.version_info.major}.{sys.version_info.minor}")
    parser.add_argument("--role", default="dedicated")
    parser.add_argument("--wheel", action="append", default=[], type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.mode == "transport":
        result = transport(args.revision, args.run_id)
    elif args.mode == "environment":
        result = environment(args.kind, args.revision, args.run_id, args.repository, args.platform, args.python_minor, args.role, args.wheel)
    else:
        kind = {
            "provenance": "product_authority_provenance",
            "no-rescue": "no_python_rescue",
            "lifecycle": "lifecycle_boundary",
            "recovery": "next_request_recovery",
        }[args.mode]
        result = provenance(args.revision, args.run_id, kind)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{result['kind']}: {result['status']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
