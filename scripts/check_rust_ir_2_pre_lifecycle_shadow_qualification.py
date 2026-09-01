#!/usr/bin/env python3
"""Fail-closed checker for official RUST-IR-2 qualification artifacts."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rust_ir_2_artifacts import (  # noqa: E402
    BASELINE_REVISION,
    BASELINE_SUBJECT,
    BLOCKED,
    MILESTONE,
    PLATFORMS,
    PYTHONS,
    QUALIFIED,
    TARGETS,
    expected,
    mandatory_jobs,
)


EXPECTED_ORDER = [
    "python_ir_verifier_pass",
    "rust_verify_module_executed",
    "rust_verify_module_pass",
    "python_lifecycle_expander_executed",
]
KNOWN_DIAGNOSTICS = {
    "undefined-slot": ("IRV-031", "IRV-032"),
    "return-storage-after-move": ("IRV-050", "IRV-026"),
    "inconsistent-branch-initialization": ("IRV-036", "IRV-028"),
}
DOMAIN_EXCLUSIONS = {
    "lifecycle-non-storage-destination",
    "integer-constant-out-of-range",
}
CRITICAL_TESTS = {
    "test_borrow_to_owned_local_and_return_survive_iteration_and_container_clear",
    "test_profile_22_ast_native_observations_match_at_every_optimization_level",
}
MUTATION_COVERAGE_CASES = {
    "functions": "duplicate-function",
    "blocks": "duplicate-block",
    "entry": "missing-entry-block",
    "cfg": "missing-jump-target",
    "terminators": "instruction-after-terminator",
    "types": "unsupported-cast",
    "calls": "call-wrong-arity",
    "returns": "return-type-mismatch",
    "slots_storage": "undefined-slot",
    "lifecycle_pseudo_ops": "missing-lifecycle-cleanup",
    "move_use_after_move": "load-after-move",
    "borrow_escape": "borrowed-value-return",
    "transferred_storage": "return-storage-after-move",
    "structs": "recursive-by-value-struct",
    "collections": "list-set-value-type",
    "semantically_relevant_metadata": "critical-ssa-aggregate-compare-shape",
    "exceptions": "supplemental-exception-irv149",
}


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _resolved_child(root: Path, raw: str) -> Path | None:
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    return path


def _artifact_records(
    manifest_path: Path,
    manifest: dict[str, Any],
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        errors.append("artifact manifest has no artifact list")
        return {}
    names = [row.get("name") for row in entries if isinstance(row, dict)]
    if len(names) != len(set(names)):
        errors.append("artifact names are duplicated")
    indexed = {row.get("name"): row for row in entries if isinstance(row, dict)}
    required = expected()
    if set(indexed) != set(required):
        errors.append("mandatory artifact set mismatch")
    records: dict[str, dict[str, Any]] = {}
    for name, (job, kind) in required.items():
        row = indexed.get(name)
        if not isinstance(row, dict):
            errors.append(f"missing artifact: {name}")
            continue
        expected_role = (
            "platform"
            if kind == "platform_qualification"
            else "python_compatibility"
            if kind == "python_compatibility"
            else "dedicated"
        )
        if not isinstance(row.get("artifact_id"), int):
            errors.append(f"{name}: missing artifact ID")
        if row.get("source_job") != job:
            errors.append(f"{name}: wrong source job")
        if row.get("kind") != kind:
            errors.append(f"{name}: wrong artifact kind")
        if row.get("role") != expected_role:
            errors.append(f"{name}: wrong artifact role")
        if row.get("revision") != manifest.get("revision"):
            errors.append(f"{name}: wrong revision")
        if str(row.get("run_id")) != str(manifest.get("run_id")):
            errors.append(f"{name}: wrong run")
        if row.get("status") != "PASS":
            errors.append(f"{name}: status is not PASS")
        archive_raw = row.get("downloaded_zip")
        evidence_raw = row.get("extracted_evidence")
        if not isinstance(archive_raw, str) or not isinstance(evidence_raw, str):
            errors.append(f"{name}: missing downloaded paths")
            continue
        archive = _resolved_child(manifest_path.parent, archive_raw)
        evidence = _resolved_child(manifest_path.parent, evidence_raw)
        if archive is None or evidence is None:
            errors.append(f"{name}: artifact path escapes aggregate root")
            continue
        if not archive.is_file() or not evidence.is_file():
            errors.append(f"{name}: downloaded ZIP or evidence absent")
            continue
        zip_hash = _hash(archive)
        evidence_hash = _hash(evidence)
        if row.get("downloaded_zip_sha256") != zip_hash:
            errors.append(f"{name}: ZIP SHA-256 mismatch")
        if row.get("extracted_evidence_sha256") != evidence_hash:
            errors.append(f"{name}: evidence SHA-256 mismatch")
        if row.get("github_digest") != f"sha256:{zip_hash}":
            errors.append(f"{name}: GitHub digest mismatch")
        try:
            record = json.loads(evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append(f"{name}: invalid evidence JSON")
            continue
        if record.get("milestone") != MILESTONE or record.get("kind") != kind:
            errors.append(f"{name}: evidence identity mismatch")
        if record.get("revision") != manifest.get("revision"):
            errors.append(f"{name}: evidence revision mismatch")
        if str(record.get("run_id")) != str(manifest.get("run_id")):
            errors.append(f"{name}: evidence run mismatch")
        if record.get("status") != "PASS" or record.get("passed") is not True:
            errors.append(f"{name}: evidence does not pass")
        records[name] = record
    return records


def _environment_checks(
    row: dict[str, Any],
    errors: list[str],
    label: str,
    *,
    clean: bool,
) -> None:
    valid = row.get("valid_case", {})
    invalid = row.get("invalid_case", {})
    metadata = row.get("native_manifest", {})
    if not row.get("product_binding") or not row.get("initial_ir_verifier_installed"):
        errors.append(f"{label}: native Initial IR verifier is absent")
    if row.get("discovery_same_after_cwd_change") is not True:
        errors.append(f"{label}: discovery depends on CWD")
    if row.get("discovery_depends_on_cargo_target") is not False:
        errors.append(f"{label}: discovery depends on Cargo target")
    if metadata.get("build_identity") != row.get("revision"):
        errors.append(f"{label}: native build identity mismatch")
    if metadata.get("initial_ir_verifier_binary") not in {
        "aether-ir-verifier",
        "aether-ir-verifier.exe",
    }:
        errors.append(f"{label}: native manifest omits verifier executable")
    if valid != {
        "python_ir_verifier": "PASS",
        "rust_pre_lifecycle_verifier": "PASS",
        "lifecycle_after_rust": True,
        "full_compilation": "PASS",
    }:
        errors.append(f"{label}: valid product gate evidence is incomplete")
    if (
        invalid.get("python_rejected") is not True
        or invalid.get("rust_rejected") is not True
        or invalid.get("fail_closed") is not True
    ):
        errors.append(f"{label}: invalid case was not fail-closed")
    if row.get("next_valid_request_succeeds") is not True:
        errors.append(f"{label}: next valid request did not recover")
    if row.get("acceptance_divergences") != 0:
        errors.append(f"{label}: acceptance divergence observed")
    if row.get("exact_dependency_resolution") is not True:
        errors.append(f"{label}: exact language/native dependency is absent")
    if clean:
        if row.get("checkout_importable") is not False or row.get("discovery_depends_on_checkout") is not False:
            errors.append(f"{label}: clean consumer depends on checkout")
        if row.get("cargo_available_to_consumer") is not False or row.get("rustc_available_to_consumer") is not False:
            errors.append(f"{label}: clean consumer exposes Cargo/rustc")


def _semantic_checks(records: dict[str, dict[str, Any]], errors: list[str]) -> None:
    def need(name: str) -> dict[str, Any]:
        return records.get(name, {})

    contract = need("rust-ir-2-contract")
    if contract.get("rust_ir_1") != {
        "revision": BASELINE_REVISION,
        "subject": BASELINE_SUBJECT,
        "branch": "main",
    }:
        errors.append("RUST-IR-1 prerequisite identity mismatch")
    if contract.get("origin_main") != contract.get("revision"):
        errors.append("qualification revision was not origin/main")
    checks = contract.get("checks", {})
    required_contract_checks = {
        "run_revision_is_head",
        "baseline_exact",
        "baseline_subject_exact",
        "baseline_is_ancestor",
        "official_revision_is_origin_main",
        "working_tree_clean_at_start",
        "rust_ir_1_product_files_unchanged",
        "python_ir_verifier_mandatory",
        "rust_verifier_mandatory",
        "double_fail_closed_product",
        "product_gate_in_lower_verified",
        "initial_stage_at_call_site",
        "post_optimization_python_only",
        "python_lifecycle_connected",
        "installed_verifier_discovery",
        "no_checkout_or_path_fallback",
        "rust_refinement_authority_preserved",
        "python_lifecycle_in_refinement_path",
    }
    if set(checks) != required_contract_checks or any(value is not True for value in checks.values()):
        errors.append("contract/call-site baseline is incomplete")
    authority = contract.get("authority", {})
    if (
        authority.get("initial_ir") != "python_IRVerifier_AND_rust_verify_module"
        or authority.get("lifecycle") != "python_LifecycleExpander"
        or authority.get("rust_initial_ir_exclusive_authority_promoted") is not False
        or authority.get("post_lifecycle_rust_gate") is not False
    ):
        errors.append("Initial IR or lifecycle authority changed")
    if any(
        contract.get(field) is not False
        for field in ("schema_changed", "protocol_changed", "transport_selection_changed", "pyo3_changed")
    ):
        errors.append("a forbidden contract surface changed")

    rust = need("rust-ir-2-rust-validation")
    if rust.get("decision") != "RUST_IR_2_CLIPPY_DELTA_CLEAN" or rust.get("current_only_count") != 0:
        errors.append("RUST_IR_2_CLIPPY_DELTA_CLEAN is absent")
    for field in (
        "cargo_fmt_all_check",
        "cargo_test_workspace_locked",
        "rust_verify_module_tests",
        "qualification_adversarial_tests",
    ):
        if rust.get(field) != "PASS":
            errors.append(f"Rust validation missing: {field}")

    valid = need("rust-ir-2-valid-corpus")
    valid_rows = valid.get("rows", [])
    if valid.get("case_count", 0) < 65 or len(valid_rows) != valid.get("case_count"):
        errors.append("valid corpus does not contain at least 65 cases")
    if valid.get("acceptance_divergences") != []:
        errors.append("valid corpus contains acceptance divergence")
    if any(
        row.get("phase") != "pre_lifecycle"
        or row.get("python", {}).get("accepted") is not True
        or row.get("rust", {}).get("accepted") is not True
        or row.get("classification") != "match_accepted"
        for row in valid_rows
    ):
        errors.append("valid corpus has a wrong phase or rejection")

    mutations = need("rust-ir-2-mutations")
    mutation_rows = mutations.get("rows", [])
    if mutations.get("mutation_count") != 75 or len(mutation_rows) != 75:
        errors.append("mutation campaign is not the exact 75-case transportable set")
    supplemental = mutations.get("supplemental_rows", [])
    if (
        mutations.get("qualified_case_count") != 77
        or {row.get("case_id") for row in supplemental}
        != {
            "supplemental-structured-source-location",
            "supplemental-exception-irv149",
        }
        or any(
            row.get("phase") != "pre_lifecycle"
            or row.get("python", {}).get("accepted") is not False
            or row.get("rust", {}).get("accepted") is not False
            for row in supplemental
        )
    ):
        errors.append("supplemental structured-error/exception mutations failed")
    if mutations.get("coverage_cases") != MUTATION_COVERAGE_CASES:
        errors.append("mandatory semantic mutation families are incomplete")
    qualified_ids = {
        row.get("mutation_id") for row in mutation_rows
    } | {row.get("case_id") for row in supplemental}
    if not set(MUTATION_COVERAGE_CASES.values()) <= qualified_ids:
        errors.append("mutation coverage claims do not name executed cases")
    if mutations.get("acceptance_divergences") != []:
        errors.append("mutation campaign contains acceptance divergence")
    if any(
        row.get("representation_phase") != "pre_lifecycle"
        or row.get("python", {}).get("accepted") is not False
        or row.get("rust", {}).get("accepted") is not False
        for row in mutation_rows
    ):
        errors.append("a semantic mutation was accepted or ran at the wrong phase")
    known = mutations.get("known_diagnostic_differences", {})
    for case_id, pair in KNOWN_DIAGNOSTICS.items():
        if known.get(case_id, {}).get("python") != pair[0] or known.get(case_id, {}).get("rust") != pair[1]:
            errors.append(f"known diagnostic difference changed: {case_id}")
    structured = mutations.get("structured_error_field_counts", {})
    if any(structured.get(field, 0) <= 0 for field in ("category", "phase", "code", "function", "block", "instruction", "source_location")):
        errors.append("structured Rust error fields were not observed")
    if mutations.get("structured_error_limitations") != {
        "source_location": "recovered_from_unchanged_python_snapshot_when_instruction_context_exists",
        "diagnostic_prose_is_semantic_identity": False,
        "protocol_or_schema_changed_for_qualification": False,
    }:
        errors.append("structured error limitations are absent or misrepresented")
    exclusions = mutations.get("representation_domain_exclusions", [])
    if {row.get("case_id") for row in exclusions} != DOMAIN_EXCLUSIONS:
        errors.append("representation-domain exclusions changed")
    if any(
        row.get("classification") != "representation_domain_difference"
        or row.get("verifier_divergence") is not False
        or row.get("product_corpus_affected") is not False
        for row in exclusions
    ) or mutations.get("product_corpus_domain_impact") is not False:
        errors.append("representation-domain difference affects the product corpus")

    irv041 = need("rust-ir-2-irv041")
    if (
        irv041.get("pre_lifecycle_python") != "ACCEPT"
        or irv041.get("pre_lifecycle_rust") != "ACCEPT"
        or irv041.get("product_rust_verification_phase") != "pre_lifecycle"
        or irv041.get("post_lifecycle_rust_observation")
        != {"result": "REJECT", "code": "IRV-041", "qualification_only": True, "productive_gate": False}
    ):
        errors.append("critical IRV-041 boundary regression failed")

    provenance = need("rust-ir-2-provenance").get("provenance", {})
    if (
        provenance.get("events") != EXPECTED_ORDER
        or provenance.get("expected_order") != EXPECTED_ORDER
        or provenance.get("representation_phase") != "pre_lifecycle"
        or provenance.get("same_python_object_reaches_lifecycle") is not True
        or provenance.get("canonical_request_sha256") != provenance.get("independently_recomputed_request_sha256")
        or not re.fullmatch(r"[0-9a-f]{64}", str(provenance.get("canonical_request_sha256", "")))
        or provenance.get("classification") != "match_accepted"
        or provenance.get("stage") != "initial"
        or provenance.get("lifecycle_observed_after_rust") is not True
    ):
        errors.append("execution-derived pre-lifecycle provenance failed")

    lifecycle = need("rust-ir-2-lifecycle-boundary")
    cases = lifecycle.get("cases", [])
    if {row.get("test") for row in cases} != CRITICAL_TESTS:
        errors.append("critical lifecycle regression set is incomplete")
    if any(
        row.get("pre_lifecycle_python") != "ACCEPT"
        or row.get("pre_lifecycle_rust") != "ACCEPT"
        or row.get("product_execution") != "PASS"
        for row in cases
    ):
        errors.append("critical lifecycle regression rejected pre-lifecycle IR or product execution")
    if (
        lifecycle.get("productive_gate_phase") != "pre_lifecycle"
        or lifecycle.get("python_lifecycle_authority") is not True
        or lifecycle.get("post_lifecycle_rust_product_gate") is not False
        or lifecycle.get("observed_order") != EXPECTED_ORDER
    ):
        errors.append("lifecycle authority boundary moved")

    packaged = need("rust-ir-2-packaged-consumer")
    _environment_checks(packaged, errors, "packaged clean consumer", clean=True)
    if len(packaged.get("wheels", [])) != 2:
        errors.append("packaged clean consumer lacks both wheel hashes/origins")

    source = need("rust-ir-2-source-install")
    _environment_checks(source, errors, "source/development install", clean=False)
    raw_summary = source.get("full_python_suite_summary")
    summary = raw_summary if isinstance(raw_summary, dict) else {}
    if source.get("full_python_suite") != "PASS" or summary.get("passed", 0) <= 0 or not {"passed", "skipped", "warnings"} <= set(summary):
        errors.append("canonical full Python suite evidence is incomplete")

    recovery = need("rust-ir-2-recovery")
    if (
        recovery.get("sequence") != ["valid_accept", "invalid_reject", "valid_accept"]
        or recovery.get("rust_results") != ["accept", "reject", "accept"]
        or recovery.get("persistent_process_starts") != 1
        or recovery.get("state_contaminated") is not False
    ):
        errors.append("next-request recovery failed")

    transport = need("rust-ir-2-transport")
    transport_rows = transport.get("rows", [])
    if {row.get("requested_transport") for row in transport_rows} != {"in_process", "companion"}:
        errors.append("SSA transport continuity set is incomplete")
    if any(
        row.get("requested_transport") != row.get("observed_transport")
        or row.get("pre_lifecycle_rust_verification") != "PASS"
        or row.get("final_compilation_result") != "PASS"
        or row.get("automatic_fallback") is not False
        or row.get("initial_ir_verifier_transport") != "independent_subprocess_operation"
        for row in transport_rows
    ) or transport.get("verifier_uses_both_ssa_transports_claimed") is not False:
        errors.append("transport continuity failed or misrepresented verifier architecture")

    performance = need("rust-ir-2-performance")
    perf_rows = performance.get("categories", [])
    if {row.get("size") for row in perf_rows} != {"small", "medium", "large"}:
        errors.append("performance size characterization is incomplete")
    if any(
        row.get("samples", 0) < 3
        or row.get("cold_import_median_ms", -1) < 0
        or row.get("serialization_median_ms", -1) < 0
        or row.get("rust_invocation_median_ms", -1) < 0
        or row.get("total_gate_median_ms", -1) < 0
        for row in perf_rows
    ):
        errors.append("performance measurements are incomplete")
    if performance.get("correctness_threshold_enforced") is not False or performance.get("operationally_pathological") is not False:
        errors.append("performance gate is missing or incorrectly treated as correctness")
    if set(performance.get("measurement_boundaries", {})) != {
        "dto_preparation",
        "rust_invocation",
        "verify_module",
        "import",
        "total_added_gate",
    }:
        errors.append("performance component boundaries are incomplete")

    for platform in PLATFORMS:
        row = need(f"rust-ir-2-platform-{platform}")
        _environment_checks(row, errors, f"platform {platform}", clean=True)
        if row.get("platform") != platform or row.get("role") != "platform":
            errors.append(f"platform identity mismatch: {platform}")
        if row.get("native_manifest", {}).get("target") != TARGETS[platform]:
            errors.append(f"native target mismatch: {platform}")
    for version in PYTHONS:
        row = need(f"rust-ir-2-python-{version}")
        _environment_checks(row, errors, f"CPython {version}", clean=True)
        if row.get("python_minor") != version or row.get("role") != "python_compatibility":
            errors.append(f"Python matrix identity mismatch: {version}")
        if row.get("implementation") != "CPython" or not re.fullmatch(re.escape(version) + r"\.\d+", str(row.get("python_patch", ""))):
            errors.append(f"exact CPython patch version absent: {version}")


def check(manifest_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {
            "artifact_schema_version": 1,
            "milestone": MILESTONE,
            "revision": None,
            "run_id": None,
            "decision": BLOCKED,
            "passed": False,
            "errors": [f"invalid manifest: {error}"],
            "python_ir_verifier_remains_mandatory": True,
            "python_lifecycle_expander_remains_authority": True,
            "rust_initial_ir_authority_promoted": False,
        }
    if (
        manifest.get("artifact_schema_version") != 1
        or manifest.get("milestone") != MILESTONE
        or manifest.get("kind") != "official_artifact_manifest"
    ):
        errors.append("manifest identity mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("revision", ""))):
        errors.append("manifest revision is not an exact SHA")
    if not str(manifest.get("run_id", "")).isdigit():
        errors.append("manifest run ID is invalid")
    jobs = manifest.get("job_results", {})
    if not isinstance(jobs, dict) or set(jobs) != mandatory_jobs():
        errors.append("mandatory job set mismatch")
    elif any(status != "success" for status in jobs.values()):
        errors.append("mandatory job was missing, skipped, cancelled, neutral, or failed")
    records = _artifact_records(manifest_path, manifest, errors)
    _semantic_checks(records, errors)
    decision = QUALIFIED if not errors else BLOCKED
    if manifest.get("aggregate_claim") != decision:
        errors.append("aggregate claim is inconsistent")
        decision = BLOCKED
    return {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "revision": manifest.get("revision"),
        "run_id": str(manifest.get("run_id")),
        "decision": decision,
        "passed": decision == QUALIFIED,
        "errors": errors,
        "python_ir_verifier_remains_mandatory": True,
        "python_lifecycle_expander_remains_authority": True,
        "rust_initial_ir_authority_promoted": False,
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
    for error in result["errors"]:
        print(f"BLOCKED: {error}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
