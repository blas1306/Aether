#!/usr/bin/env python3
"""Fail-closed aggregate checker for official RUST-REFINE-2 artifacts."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_rust_refine_2_artifact_manifest import BASE, PLATFORMS, PYTHONS, expected


QUALIFIED = "RUST_REFINEMENT_SHADOW_QUALIFIED"
BLOCKED = "RUST_REFINEMENT_SHADOW_QUALIFICATION_BLOCKED"
BASELINE = "b5835a5cc3c947333e6576791149767713dd0689"


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _artifact_records(manifest_path: Path, manifest: dict[str, Any], errors: list[str]) -> dict[str, dict[str, Any]]:
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        errors.append("artifact manifest has no artifact list")
        return {}
    indexed = {row.get("name"): row for row in entries if isinstance(row, dict)}
    required = expected()
    if set(indexed) != set(required):
        errors.append("mandatory artifact set mismatch")
    records: dict[str, dict[str, Any]] = {}
    for name, (job, kind) in required.items():
        row = indexed.get(name)
        if row is None:
            errors.append(f"missing artifact: {name}")
            continue
        if not isinstance(row.get("artifact_id"), int): errors.append(f"{name}: missing artifact ID")
        if row.get("source_job") != job: errors.append(f"{name}: wrong source job")
        if row.get("kind") != kind: errors.append(f"{name}: wrong artifact kind")
        if row.get("revision") != manifest.get("revision"): errors.append(f"{name}: wrong revision")
        if str(row.get("run_id")) != str(manifest.get("run_id")): errors.append(f"{name}: wrong run")
        if row.get("status") != "PASS": errors.append(f"{name}: status is not PASS")
        archive_raw = row.get("downloaded_zip")
        evidence_raw = row.get("extracted_evidence")
        if not isinstance(archive_raw, str) or not isinstance(evidence_raw, str):
            errors.append(f"{name}: missing downloaded paths")
            continue
        archive = (manifest_path.parent / archive_raw).resolve()
        evidence = (manifest_path.parent / evidence_raw).resolve()
        if not archive.is_file() or not evidence.is_file():
            errors.append(f"{name}: downloaded artifact or evidence absent")
            continue
        zip_digest = _hash(archive)
        evidence_digest = _hash(evidence)
        if row.get("downloaded_zip_sha256") != zip_digest: errors.append(f"{name}: ZIP SHA-256 mismatch")
        if row.get("extracted_evidence_sha256") != evidence_digest: errors.append(f"{name}: evidence SHA-256 mismatch")
        github_digest = row.get("github_digest")
        if github_digest != f"sha256:{zip_digest}": errors.append(f"{name}: GitHub digest mismatch")
        try:
            record = json.loads(evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append(f"{name}: invalid evidence JSON")
            continue
        if record.get("milestone") != "RUST-REFINE-2" or record.get("kind") != kind: errors.append(f"{name}: evidence identity mismatch")
        if record.get("revision") != manifest.get("revision"): errors.append(f"{name}: evidence revision mismatch")
        if str(record.get("run_id")) != str(manifest.get("run_id")): errors.append(f"{name}: evidence run mismatch")
        if record.get("status") != "PASS" or record.get("passed") is not True: errors.append(f"{name}: evidence does not pass")
        records[name] = record
    return records


def _semantic_checks(records: dict[str, dict[str, Any]], errors: list[str]) -> None:
    def need(name: str) -> dict[str, Any]:
        return records.get(name, {})

    contract = need("rust-refine-2-contract")
    baseline = contract.get("baseline", {})
    contracts = contract.get("contracts", {})
    if baseline != {"revision": BASELINE, "branch": "main", "subject": "Implement Rust shadow SSA refinement verifier", "remote_main_at_start": BASELINE}: errors.append("baseline identity is not exact")
    if contract.get("core_pkg_1", {}).get("decision") != "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED": errors.append("CORE-PKG-1 prerequisite absent")
    if contracts.get("authority") != "rust_refinement_AND_python_SSARefinementVerifier" or contracts.get("python_authority_retired") is not False or contracts.get("promoted") is not False: errors.append("shadow-only authority contract changed")

    rust = need("rust-refine-2-rust-validation")
    if rust.get("current_only_count") != 0 or rust.get("decision") != "RUST_REFINE_2_CLIPPY_DELTA_CLEAN": errors.append("Clippy current-only delta is not clean")
    for field in ("cargo_fmt_check", "cargo_test_workspace_locked", "rust_refinement_tests", "adversarial_tests"):
        if rust.get(field) != "PASS": errors.append(f"Rust validation missing: {field}")

    historical = need("rust-refine-2-historical")
    if historical.get("case_count", 0) <= 0 or historical.get("acceptance_divergences") != []: errors.append("historical acceptance differential failed")
    if any(row.get("rust_accept") != row.get("python_accept") for row in historical.get("rows", [])): errors.append("historical row acceptance divergence")

    mutation = need("rust-refine-2-mutations")
    rows = mutation.get("rows", [])
    semantic = [row for row in rows if row.get("semantic") is True]
    controls = [row for row in rows if row.get("semantic") is False]
    if len(semantic) != 33 or any(row.get("rust_result") != "reject" or row.get("python_result") != "reject" for row in semantic): errors.append("33 semantic mutations were not reject/reject")
    if len(controls) != 1 or any(row.get("rust_result") != "accept" or row.get("python_result") != "accept" for row in controls): errors.append("non-semantic control was not accept/accept")
    domains = mutation.get("input_domain_divergences", [])
    if {row.get("mutation_id") for row in domains} != {"missing_reachable_block"}: errors.append("known input-domain divergence is missing or changed")
    if mutation.get("acceptance_divergences") != []: errors.append("mutation acceptance divergence")

    pipeline = need("rust-refine-2-production-pipeline")
    required_coverage = {"exceptions", "lifecycle", "strings", "arrays", "lists", "matrices", "classes", "interfaces", "enums", "modules", "calls_control_flow_phi", "deep_cfg_via_dedicated_gate"}
    if set(pipeline.get("coverage", [])) != required_coverage: errors.append("production pipeline coverage incomplete")
    if not pipeline.get("cases") or any(not row.get("rust_refinement_succeeded_before_schema_v2_export") or not row.get("python_ssa_verifier_executed") or not row.get("python_refinement_verifier_executed") for row in pipeline.get("cases", [])): errors.append("production pipeline did not execute both verifiers")
    if pipeline.get("python_fail_closed_injection", {}).get("rejected") is not True: errors.append("Python refinement fail-closed proof absent")

    transport = need("rust-refine-2-transport-parity")
    transport_rows = transport.get("rows", [])
    if {row.get("requested_transport") for row in transport_rows} != {"in_process", "companion"}: errors.append("transport parity set incomplete")
    if any(row.get("requested_transport") != row.get("observed_transport") or row.get("automatic_fallback") is not False for row in transport_rows): errors.append("transport fallback or mismatch observed")

    packaged = need("rust-refine-2-packaged-consumer")
    if packaged.get("checkout_importable") is not False or packaged.get("cargo_required_by_consumer") is not False or packaged.get("rustc_required_by_consumer") is not False: errors.append("packaged consumer depends on checkout or Rust tools")
    if not packaged.get("product_binding") or not packaged.get("companion_installed") or not packaged.get("exact_dependency_resolution") or len(packaged.get("wheels", [])) != 2: errors.append("packaged wheel contract incomplete")
    if packaged.get("native_manifest", {}).get("build_identity") != packaged.get("revision") or packaged.get("native_manifest", {}).get("protocol_version") != 1: errors.append("packaged native identity/protocol mismatch")
    if not packaged.get("valid_case", {}).get("python_refinement_verifier_executed"): errors.append("packaged Python refinement verifier absent")
    if len(packaged.get("historical_positive_cases", [])) < 2 or packaged.get("representative_python_rejection", {}).get("rejected") is not True: errors.append("packaged positive/adversarial qualification incomplete")

    source = need("rust-refine-2-source-install")
    if not source.get("product_binding") or not source.get("companion_installed") or not source.get("both_transports_available") or source.get("full_python_suite") != "PASS": errors.append("source/development qualification incomplete")
    summary = source.get("full_python_suite_summary", {})
    if summary.get("passed", 0) <= 0 or not {"passed", "skipped", "warnings"} <= set(summary): errors.append("full pytest pass/skip/warnings summary absent")
    if source.get("native_manifest", {}).get("build_identity") != source.get("revision"): errors.append("source native build identity mismatch")

    deep = need("rust-refine-2-deep-cfg")
    if deep.get("initial_ir_blocks") != 5000 or deep.get("ssa_blocks") != 5000 or deep.get("rust_result") != "accept" or deep.get("python_result") != "accept" or deep.get("optimizer_executed") is not False: errors.append("deep CFG 5000 contract failed")

    cost = need("rust-refine-2-cost")
    if len(cost.get("samples", [])) < 4 or cost.get("threshold_enforced") is not False or cost.get("rust_refinement_separately_measured_with_pair_verifier") is not True: errors.append("cost characterization incomplete")

    targets = {"linux-x86_64": "x86_64-unknown-linux-gnu", "windows-x86_64": "x86_64-pc-windows-msvc", "macos-x86_64": "x86_64-apple-darwin", "macos-arm64": "aarch64-apple-darwin"}
    for platform in PLATFORMS:
        row = need(f"rust-refine-2-platform-{platform}")
        if row.get("platform") != platform or row.get("role") != "platform" or row.get("acceptance_divergences") != 0: errors.append(f"platform gate failed: {platform}")
        if not row.get("valid_case", {}).get("rust_refinement_succeeded_before_schema_v2_export") or not row.get("valid_case", {}).get("python_refinement_verifier_executed"): errors.append(f"platform verifier missing: {platform}")
        if len(row.get("historical_positive_cases", [])) < 2 or row.get("representative_python_rejection", {}).get("rejected") is not True: errors.append(f"platform historical/adversarial cases missing: {platform}")
        if row.get("native_manifest", {}).get("target") != targets[platform] or row.get("native_manifest", {}).get("build_identity") != row.get("revision"): errors.append(f"platform native identity mismatch: {platform}")
    for version in PYTHONS:
        row = need(f"rust-refine-2-python-{version}")
        if row.get("python_minor") != version or row.get("role") != "python_compatibility" or row.get("acceptance_divergences") != 0: errors.append(f"Python gate failed: {version}")
        if not re.fullmatch(re.escape(version) + r"\.\d+", str(row.get("python_patch", ""))): errors.append(f"exact Python patch absent: {version}")
        if row.get("native_manifest", {}).get("build_identity") != row.get("revision") or not row.get("product_binding"): errors.append(f"Python native product identity missing: {version}")
        if not row.get("valid_case", {}).get("rust_refinement_succeeded_before_schema_v2_export") or row.get("representative_python_rejection", {}).get("rejected") is not True: errors.append(f"Python valid/adversarial verifier evidence missing: {version}")


def check(manifest_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_schema_version") != 1 or manifest.get("milestone") != "RUST-REFINE-2" or manifest.get("kind") != "official_artifact_manifest": errors.append("manifest identity mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("revision", ""))): errors.append("manifest revision is not an exact SHA")
    if not str(manifest.get("run_id", "")).isdigit(): errors.append("manifest run ID is invalid")
    job_results = manifest.get("job_results", {})
    required_jobs = {job for job, _kind in BASE.values()} | {"platform-qualification", "python-compatibility"}
    if set(job_results) != required_jobs or any(value != "success" for value in job_results.values()): errors.append("mandatory job was missing, skipped, cancelled, neutral, or failed")
    records = _artifact_records(manifest_path, manifest, errors)
    _semantic_checks(records, errors)
    computed = QUALIFIED if not errors else BLOCKED
    if manifest.get("aggregate_claim") != computed:
        errors.append("aggregate claim is inconsistent")
        computed = BLOCKED
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-REFINE-2",
        "revision": manifest.get("revision"),
        "run_id": str(manifest.get("run_id")),
        "decision": computed,
        "passed": computed == QUALIFIED,
        "errors": errors,
        "python_authority_retired": False,
        "promoted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = check(args.manifest)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["decision"])
    for error in result["errors"]: print(f"BLOCKED: {error}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
