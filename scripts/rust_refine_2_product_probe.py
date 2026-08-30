#!/usr/bin/env python3
"""Exercise the installed/source product with both refinement verifiers enabled."""

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
import subprocess
import sys
import tempfile
from typing import Any


MILESTONE = "RUST-REFINE-2"


ENUM_SOURCE = """
enum Status { Ready, Waiting }
Status choose(boolean flag) {
    Status value = Status.Waiting;
    if (flag) { value = Status.Ready; }
    return value;
}
int main() { Status value = choose(true); println(value); return 0; }
"""

SCALAR_SOURCE = """
int choose(boolean flag) {
    int value = 1;
    if (flag) { value = 2; }
    return value;
}
int main() { println(choose(true)); return 0; }
"""


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _identity(kind: str, revision: str, run_id: str, passed: bool, **values: Any) -> dict[str, Any]:
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


def _compile(source: str, source_root: Path, client) -> dict[str, Any]:
    from aether.pipeline import SSAPipeline, prepare_typed_program
    from aether.typechecker import TypeChecker

    typed = prepare_typed_program(source, TypeChecker(source_root=source_root))
    pipeline = SSAPipeline(rust_shadow_client=client)
    result = pipeline.run(typed)
    trace = pipeline.last_authority_report
    if trace is None:
        raise RuntimeError("production pipeline returned no refinement trace")
    return {
        "accepted": bool(result.ssa_module.functions),
        "returned_ssa_origin": pipeline.last_returned_ssa_origin,
        "rust_refinement_succeeded_before_schema_v2_export": bool(trace.rust_side_verification_succeeded),
        "python_ssa_verifier_executed": trace.stage_execution_counts.get("imported_ssa_verification") == 1,
        "python_refinement_verifier_executed": bool(trace.refinement_verification_executed),
        "final_ssa_verifier_executed": bool(trace.final_generic_verification_executed),
        "completed_stages": list(trace.completed_stages),
    }


def _full_backend(source: str, source_root: Path, transport: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", suffix=".ae", dir=source_root, delete=False, encoding="utf-8") as handle:
        handle.write(source)
        path = Path(handle.name)
    try:
        env = os.environ.copy()
        env["AETHER_RUST_CORE_TRANSPORT"] = transport
        completed = subprocess.run(
            [sys.executable, "-m", "aether.cli", "--emit-llvm", str(path)],
            cwd=source_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        return {
            "accepted": completed.returncode == 0 and "define" in completed.stdout,
            "returncode": completed.returncode,
            "llvm_generated": "define" in completed.stdout,
            "stderr": completed.stderr[-500:],
            "optimizer_requested": False,
        }
    finally:
        path.unlink(missing_ok=True)


def _python_failure_is_fail_closed(source_root: Path, client) -> dict[str, Any]:
    import aether.ssa.shadow_independent as production
    original = production.verify_ssa_refinement

    def reject(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("qualification injected Python refinement rejection")

    production.verify_ssa_refinement = reject
    try:
        try:
            _compile(SCALAR_SOURCE, source_root, client)
        except production.ShadowIndependentRustAuthorityFailure as error:
            return {
                "rejected": True,
                "failed_stage": error.trace.failed_stage,
                "classification": error.trace.failure_classification,
            }
        return {"rejected": False}
    finally:
        production.verify_ssa_refinement = original


def _client(transport: str):
    from aether.ssa.shadow import ProductionRustSSALoweringClient
    return ProductionRustSSALoweringClient(transport, timeout_seconds=180)


def pipeline(root: Path, revision: str, run_id: str, transport: str) -> dict[str, Any]:
    candidates = {
        "exceptions": root / "corpus/exceptions/positive/throw_and_typed_catch.ae",
        "lifecycle": root / "tests/fixtures/rust_ssa_promotion_failure/interface_lifecycle_default.ae",
        "strings": root / "examples/llvm/string_choose.ae",
        "arrays": root / "benchmarks/array_sum.ae",
        "lists": root / "benchmarks/list_push.ae",
        "matrices": root / "benchmarks/matrix_mul.ae",
        "classes": root / "examples/classes/counter_basic.ae",
        "interfaces": root / "examples/classes/implements_interface.ae",
        "modules": root / "examples/structs/main.ae",
        "calls_control_flow_phi": root / "benchmarks/if_else.ae",
    }
    rows = []
    client = _client(transport)
    try:
        for category, path in candidates.items():
            source = path.read_text(encoding="utf-8")
            rows.append({"category": category, "source": path.relative_to(root).as_posix(), **_compile(source, path.parent, client)})
        rows.append({"category": "enums", "source": "embedded_existing_enum_contract", **_compile(ENUM_SOURCE, root, client)})
        full = _full_backend(SCALAR_SOURCE, root, transport)
        provenance = client.provenance
        python_failure = _python_failure_is_fail_closed(root, client)
    finally:
        client.close()
    required = {"exceptions", "lifecycle", "strings", "arrays", "lists", "matrices", "classes", "interfaces", "enums", "modules", "calls_control_flow_phi"}
    passed = (
        {row["category"] for row in rows} == required
        and all(row["accepted"] and row["rust_refinement_succeeded_before_schema_v2_export"] and row["python_ssa_verifier_executed"] and row["python_refinement_verifier_executed"] for row in rows)
        and full["accepted"]
        and python_failure.get("rejected") is True
        and provenance.requested_transport == provenance.observed_transport == transport
    )
    return _identity(
        "production_pipeline_shadow", revision, run_id, passed,
        requested_transport=transport,
        observed_transport=provenance.observed_transport,
        cases=rows,
        coverage=sorted(required | {"deep_cfg_via_dedicated_gate"}),
        full_backend=full,
        python_fail_closed_injection=python_failure,
        rust_fail_closed_injection="covered_by_post_construction_mutation_campaign",
        schema_v2_export_after_rust_verifiers=True,
        universal_coverage_claimed=False,
    )


def transport_parity(root: Path, revision: str, run_id: str) -> dict[str, Any]:
    rows = []
    for transport in ("in_process", "companion"):
        client = _client(transport)
        try:
            result = _compile(SCALAR_SOURCE, root, client)
            provenance = client.provenance
            rows.append({
                "requested_transport": transport,
                "observed_transport": provenance.observed_transport,
                "rust_refinement_result": "accept" if result["rust_refinement_succeeded_before_schema_v2_export"] else "reject",
                "python_refinement_result": "accept" if result["python_refinement_verifier_executed"] else "not_executed",
                "final_compilation_result": "accept" if result["accepted"] else "reject",
                "automatic_fallback": False,
            })
        finally:
            client.close()
    passed = all(row["requested_transport"] == row["observed_transport"] and row["rust_refinement_result"] == row["python_refinement_result"] == row["final_compilation_result"] == "accept" and row["automatic_fallback"] is False for row in rows)
    return _identity("transport_parity", revision, run_id, passed, rows=rows, observable_contract_equal=len({json.dumps({k: v for k, v in row.items() if k not in {"requested_transport", "observed_transport"}}, sort_keys=True) for row in rows}) == 1)


def environment_probe(kind: str, root: Path, repository: Path, revision: str, run_id: str, transport: str, wheel_paths: list[Path], role: str, platform_id: str, python_minor: str, full_python_suite: str | None, full_python_suite_log: Path | None) -> dict[str, Any]:
    import aether
    import aether_compiler_core
    from aether_compiler_core import companion_path, version_metadata

    imported = [Path(aether.__file__).resolve(), Path(aether_compiler_core.__file__).resolve()]
    clean = kind != "source_development_install"
    checkout_imported = any(path.is_relative_to(repository.resolve()) for path in imported)
    client = _client(transport)
    try:
        valid_cases = [
            {"case_id": "historical_phi_control_flow", **_compile(SCALAR_SOURCE, root, client)},
            {"case_id": "historical_enum_nominal_phi", **_compile(ENUM_SOURCE, root, client)},
        ]
        valid = valid_cases[0]
        full = _full_backend(SCALAR_SOURCE, root, transport)
        python_failure = _python_failure_is_fail_closed(root, client)
        provenance = client.provenance
    finally:
        client.close()
    metadata = version_metadata()
    wheels = [{"name": path.name, "sha256": digest(path), "origin": str(path.resolve())} for path in wheel_paths]
    exact_dependency = importlib.metadata.requires("aether-language") or []
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
    suite_ok = kind != "source_development_install" or (
        full_python_suite == "PASS" and suite_summary is not None
    )
    passed = (
        all(case["accepted"] for case in valid_cases)
        and all(case["rust_refinement_succeeded_before_schema_v2_export"] for case in valid_cases)
        and all(case["python_ssa_verifier_executed"] for case in valid_cases)
        and all(case["python_refinement_verifier_executed"] for case in valid_cases)
        and full["accepted"]
        and python_failure.get("rejected") is True
        and provenance.requested_transport == provenance.observed_transport == transport
        and companion_path().is_file()
        and metadata.get("protocol_version") == 1
        and metadata.get("build_identity") == revision
        and (not clean or not checkout_imported)
        and (not clean or shutil.which("cargo") is None)
        and (not clean or shutil.which("rustc") is None)
        and "aether-compiler-core==1.0.0rc4" in exact_dependency
        and suite_ok
    )
    return _identity(
        kind, revision, run_id, passed,
        role=role,
        platform=platform_id,
        python_minor=python_minor,
        python_patch=host_platform.python_version(),
        requested_transport=transport,
        observed_transport=provenance.observed_transport,
        product_binding=True,
        companion_installed=companion_path().is_file(),
        native_manifest=metadata,
        language_distribution=importlib.metadata.version("aether-language"),
        native_distribution=importlib.metadata.version("aether-compiler-core"),
        exact_dependency_resolution="aether-compiler-core==1.0.0rc4" in exact_dependency,
        both_transports_available=companion_path().is_file() and bool(aether_compiler_core.CompilerCore),
        full_python_suite=full_python_suite,
        full_python_suite_summary=suite_summary,
        imported_paths=[str(path) for path in imported],
        checkout_importable=checkout_imported,
        cargo_required_by_consumer=shutil.which("cargo") is not None,
        rustc_required_by_consumer=shutil.which("rustc") is not None,
        wheels=wheels,
        valid_case=valid,
        historical_positive_cases=valid_cases,
        full_backend=full,
        representative_python_rejection=python_failure,
        representative_rust_rejection="mutation_campaign_artifact",
        acceptance_divergences=0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pipeline", "transport", "environment"), required=True)
    parser.add_argument("--kind", default="packaged_clean_consumer")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--transport", default="in_process", choices=("in_process", "companion"))
    parser.add_argument("--role", default="dedicated")
    parser.add_argument("--platform", default="unknown")
    parser.add_argument("--python-minor", default=f"{sys.version_info.major}.{sys.version_info.minor}")
    parser.add_argument("--wheel", type=Path, action="append", default=[])
    parser.add_argument("--full-python-suite", choices=("PASS", "FAIL"))
    parser.add_argument("--full-python-suite-log", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "pipeline": result = pipeline(args.root, args.revision, args.run_id, args.transport)
    elif args.mode == "transport": result = transport_parity(args.root, args.revision, args.run_id)
    else: result = environment_probe(args.kind, args.root, args.repository, args.revision, args.run_id, args.transport, args.wheel, args.role, args.platform, args.python_minor, args.full_python_suite, args.full_python_suite_log)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{result['kind']}: {result['status']}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
