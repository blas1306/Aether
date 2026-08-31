#!/usr/bin/env python3
"""Fail-closed checker for official RUST-REFINE-3 artifacts."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_rust_refine_3_artifact_manifest import (  # noqa: E402
    BASE,
    PLATFORMS,
    PYTHONS,
    expected,
)


PROMOTED = "RUST_REFINEMENT_AUTHORITY_PROMOTED"
BLOCKED = "RUST_REFINEMENT_AUTHORITY_PROMOTION_BLOCKED"
R2_RUN = "33321791729"
R2_REVISION = "0bff8c0a78005d97ee5c7c2e0eb09a6a6b3b1fef"


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _records(
    manifest_path: Path,
    manifest: dict[str, Any],
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        errors.append("artifact manifest has no artifact list")
        return {}
    indexed = {
        row.get("name"): row for row in entries if isinstance(row, dict)
    }
    required = expected()
    if set(indexed) != set(required):
        errors.append("mandatory artifact set mismatch")
    records: dict[str, dict[str, Any]] = {}
    for name, (job, kind) in required.items():
        row = indexed.get(name)
        if row is None:
            errors.append(f"missing artifact: {name}")
            continue
        if not isinstance(row.get("artifact_id"), int):
            errors.append(f"{name}: missing artifact ID")
        if row.get("source_job") != job:
            errors.append(f"{name}: wrong source job")
        if row.get("kind") != kind:
            errors.append(f"{name}: wrong artifact kind")
        if row.get("revision") != manifest.get("revision"):
            errors.append(f"{name}: wrong revision")
        if str(row.get("run_id")) != str(manifest.get("run_id")):
            errors.append(f"{name}: wrong run")
        archive_raw = row.get("downloaded_zip")
        evidence_raw = row.get("extracted_evidence")
        if not isinstance(archive_raw, str) or not isinstance(evidence_raw, str):
            errors.append(f"{name}: incomplete provenance paths")
            continue
        archive = (manifest_path.parent / archive_raw).resolve()
        evidence = (manifest_path.parent / evidence_raw).resolve()
        if not archive.is_file() or not evidence.is_file():
            errors.append(f"{name}: artifact ZIP or evidence absent")
            continue
        zip_hash = _hash(archive)
        evidence_hash = _hash(evidence)
        if row.get("downloaded_zip_sha256") != zip_hash:
            errors.append(f"{name}: ZIP SHA-256 mismatch")
        if row.get("github_digest") != f"sha256:{zip_hash}":
            errors.append(f"{name}: GitHub digest mismatch")
        if row.get("extracted_evidence_sha256") != evidence_hash:
            errors.append(f"{name}: evidence SHA-256 mismatch")
        try:
            record = json.loads(evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append(f"{name}: invalid evidence JSON")
            continue
        if record.get("milestone") != "RUST-REFINE-3":
            errors.append(f"{name}: wrong evidence milestone")
        if record.get("kind") != kind:
            errors.append(f"{name}: wrong evidence kind")
        if record.get("revision") != manifest.get("revision"):
            errors.append(f"{name}: evidence revision mismatch")
        if str(record.get("run_id")) != str(manifest.get("run_id")):
            errors.append(f"{name}: evidence run mismatch")
        if record.get("status") != "PASS" or record.get("passed") is not True:
            errors.append(f"{name}: evidence does not pass")
        records[name] = record
    return records


def _product(record: dict[str, Any], label: str, errors: list[str]) -> None:
    cases = record.get("cases", [])
    if not cases:
        errors.append(f"{label}: no productive cases")
    for row in cases:
        if (
            row.get("accepted") is not True
            or row.get("returned_ssa_origin") != "rust_schema_v2_import"
            or row.get("refinement_authority") != "rust"
            or row.get("rust_refinement_verification_observed") is not True
            or row.get("python_refinement_role") != "not_executed"
            or row.get("python_refinement_verification_executed") is not False
            or row.get("python_ssa_verifier_executed") is not True
        ):
            errors.append(f"{label}: invalid authority case provenance")
            break
    absence = record.get("python_refinement_absence", {})
    if (
        absence.get("compilation_accepted") is not True
        or absence.get("python_refinement_calls") != 0
        or absence.get("python_rejection_could_block") is not False
    ):
        errors.append(f"{label}: Python refinement remains productive")
    rescue = record.get("no_python_rescue", {})
    structured = rescue.get("structured_error", {})
    diagnostic = structured.get("diagnostic", {})
    if (
        rescue.get("rust_rejection_blocked") is not True
        or rescue.get("python_refinement_calls") != 0
        or rescue.get("python_rescue_attempted") is not False
        or rescue.get("subsequent_recovery_succeeded") is not True
        or rescue.get("automatic_fallback") is not False
        or structured.get("classification") != "rust_lowering_or_verifier_failure"
        or diagnostic.get("category") != "ssa_refinement_verification"
        or not diagnostic.get("code")
    ):
        errors.append(f"{label}: Rust rejection was rescued or recovery failed")
    provenance = record.get("authority_provenance", {})
    if (
        provenance.get("refinement_authority") != "rust"
        or provenance.get("python_refinement_role") != "not_executed"
        or provenance.get("derived_from_case_traces") is not True
        or provenance.get("constant_only_evidence") is not False
    ):
        errors.append(f"{label}: incomplete authority provenance")


def _environment(record: dict[str, Any], label: str, errors: list[str]) -> None:
    rows = record.get("transport_rows", [])
    if {row.get("requested_transport") for row in rows} != {
        "in_process",
        "companion",
    }:
        errors.append(f"{label}: transport matrix incomplete")
    for row in rows:
        valid = row.get("valid_case", {})
        rescue = row.get("no_python_rescue", {})
        oracle = row.get("qualification_oracle", {})
        if (
            row.get("requested_transport") != row.get("observed_transport")
            or row.get("automatic_fallback") is not False
            or valid.get("refinement_authority") != "rust"
            or valid.get("rust_refinement_verification_observed") is not True
            or valid.get("python_refinement_verification_executed") is not False
            or rescue.get("rust_rejection_blocked") is not True
            or rescue.get("python_rescue_attempted") is not False
            or oracle.get("accepted") is not True
            or oracle.get("refinement_authority") != "rust"
            or oracle.get("python_refinement_role") != "oracle_only"
            or oracle.get("python_refinement_verification_executed") is not True
        ):
            errors.append(f"{label}: invalid transport authority evidence")
            break
    if (
        record.get("product_binding") is not True
        or record.get("companion_installed") is not True
        or record.get("exact_dependency_resolution") is not True
    ):
        errors.append(f"{label}: native product contract incomplete")
    provenance = record.get("authority_provenance", {})
    if (
        provenance.get("refinement_authority") != "rust"
        or provenance.get("python_refinement_role") != "not_executed"
        or provenance.get("derived_from_case_traces") is not True
    ):
        errors.append(f"{label}: authority provenance absent")


def _semantic(records: dict[str, dict[str, Any]], errors: list[str]) -> None:
    def need(name: str) -> dict[str, Any]:
        return records.get(name, {})

    prerequisite = need("rust-refine-3-prerequisite").get("prerequisite", {})
    if (
        prerequisite.get("decision") != "RUST_REFINEMENT_SHADOW_QUALIFIED"
        or prerequisite.get("run_id") != R2_RUN
        or prerequisite.get("revision") != R2_REVISION
        or prerequisite.get("official_artifact_count") != 19
    ):
        errors.append("RUST-REFINE-2 prerequisite is invalid")
    historical = need("rust-refine-3-prerequisite").get("historical_runs", {})
    if historical != {
        "33319278847": "FAILED/BLOCKED",
        "33321279630": "FAILED/BLOCKED",
    }:
        errors.append("historical failed runs were reinterpreted")

    contract = need("rust-refine-3-contract")
    if contract.get("promoted_productive_refinement_authority") != "rust":
        errors.append("Rust refinement authority is not active")
    if contract.get("python_ssa_verifier_retired") is not False:
        errors.append("Python SSAVerifier was incorrectly retired")
    if contract.get("python_refinement_implementation_deleted") is not False:
        errors.append("Python refinement oracle was deleted")
    if contract.get("unexplained_semantic_contract_differences") != []:
        errors.append("unexplained semantic contract difference")
    if not contract.get("checks") or not all(contract["checks"].values()):
        errors.append("authority contract checks failed")

    differential = need("rust-refine-3-differential")
    if (
        differential.get("case_count", 0) < 220
        or differential.get("property_generated_case_count", 0) < 70
        or differential.get("rust_accept_python_reject") != []
        or differential.get("rust_reject_python_accept") != []
        or differential.get("acceptance_divergences") != []
        or differential.get("known_input_domain_divergence_fail_closed") is not True
    ):
        errors.append("directed differential failed")

    mutations = need("rust-refine-3-mutations")
    if (
        mutations.get("deterministic") is not True
        or mutations.get("generated_case_count", 0) < 400
        or mutations.get("rust_accept_python_reject") != []
        or mutations.get("rust_reject_python_accept") != []
        or mutations.get("accepted_mutations") != []
        or mutations.get("both_reject_count") != mutations.get("generated_case_count")
    ):
        errors.append("mutation/adversarial campaign failed")

    for name in (
        "rust-refine-3-production-authority",
        "rust-refine-3-no-python-rescue",
        "rust-refine-3-production-pipeline",
    ):
        _product(need(name), name, errors)

    transport = need("rust-refine-3-transport").get("rows", [])
    if (
        {row.get("requested_transport") for row in transport}
        != {"in_process", "companion"}
        or any(
            row.get("requested_transport") != row.get("observed_transport")
            or row.get("status") != "PASS"
            or row.get("automatic_fallback") is not False
            for row in transport
        )
        or len({row.get("valid_output_sha256") for row in transport}) != 1
        or len({row.get("rejection_classification") for row in transport}) != 1
    ):
        errors.append("transport parity failed")

    pipeline = need("rust-refine-3-production-pipeline").get("full_backend", {})
    if (
        pipeline.get("accepted") is not True
        or pipeline.get("llvm_generated") is not True
        or pipeline.get("returncode") != 0
    ):
        errors.append("productive end-to-end backend gate failed")

    packaged = need("rust-refine-3-packaged")
    _environment(packaged, "packaged clean consumer", errors)
    if (
        packaged.get("checkout_importable") is not False
        or packaged.get("cargo_required_by_consumer") is not False
        or packaged.get("rustc_required_by_consumer") is not False
        or len(packaged.get("wheels", [])) != 2
    ):
        errors.append("packaged clean consumer is not isolated")

    source = need("rust-refine-3-source")
    _environment(source, "source development", errors)
    if source.get("full_python_suite") != "PASS":
        errors.append("source/development full suite absent")

    deep = need("rust-refine-3-deep")
    if (
        deep.get("initial_ir_blocks") != 5000
        or deep.get("ssa_blocks") != 5000
        or deep.get("rust_result") != "accept"
        or deep.get("python_result") != "accept"
    ):
        errors.append("deep/stress gate failed")

    cost = need("rust-refine-3-cost")
    if (
        len(cost.get("samples", [])) < 4
        or cost.get("threshold_enforced") is not False
        or cost.get("universal_speedup_claimed") is not False
    ):
        errors.append("cost characterization incomplete")

    targets = {
        "linux-x86_64": "x86_64-unknown-linux-gnu",
        "windows-x86_64": "x86_64-pc-windows-msvc",
        "macos-x86_64": "x86_64-apple-darwin",
        "macos-arm64": "aarch64-apple-darwin",
    }
    for platform in PLATFORMS:
        row = need(f"rust-refine-3-platform-{platform}")
        _environment(row, f"platform {platform}", errors)
        if (
            row.get("platform") != platform
            or row.get("role") != "platform"
            or row.get("native_manifest", {}).get("target") != targets[platform]
        ):
            errors.append(f"platform identity failed: {platform}")

    for version in PYTHONS:
        row = need(f"rust-refine-3-python-{version}")
        _environment(row, f"Python {version}", errors)
        if (
            row.get("python_minor") != version
            or row.get("role") != "python_compatibility"
            or not re.fullmatch(
                re.escape(version) + r"\.\d+",
                str(row.get("python_patch", "")),
            )
        ):
            errors.append(f"Python identity failed: {version}")


def check(manifest_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {
            "artifact_schema_version": 1,
            "milestone": "RUST-REFINE-3",
            "decision": BLOCKED,
            "passed": False,
            "errors": [f"invalid manifest: {error}"],
        }
    if (
        manifest.get("artifact_schema_version") != 1
        or manifest.get("milestone") != "RUST-REFINE-3"
        or manifest.get("kind") != "official_artifact_manifest"
    ):
        errors.append("manifest identity mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("revision", ""))):
        errors.append("manifest revision is not an exact SHA")
    if not str(manifest.get("run_id", "")).isdigit():
        errors.append("manifest run ID is invalid")
    jobs = manifest.get("job_results", {})
    required_jobs = {job for job, _kind in BASE.values()} | {
        "platform-qualification",
        "python-compatibility",
    }
    if set(jobs) != required_jobs or any(
        value != "success" for value in jobs.values()
    ):
        errors.append("mandatory job missing, skipped, cancelled, neutral, or failed")
    records = _records(manifest_path, manifest, errors)
    _semantic(records, errors)
    computed = PROMOTED if not errors else BLOCKED
    if manifest.get("aggregate_claim") != computed:
        errors.append("aggregate claim is inconsistent")
        computed = BLOCKED
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-REFINE-3",
        "revision": manifest.get("revision"),
        "run_id": str(manifest.get("run_id")),
        "decision": computed,
        "passed": computed == PROMOTED,
        "errors": errors,
        "refinement_authority": "rust" if computed == PROMOTED else None,
        "python_refinement_role": "oracle_only" if computed == PROMOTED else None,
        "python_ssa_verifier_retired": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = check(args.manifest)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(result["decision"])
    for error in result["errors"]:
        print(f"BLOCKED: {error}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
