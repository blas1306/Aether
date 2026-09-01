#!/usr/bin/env python3
"""Fail-closed checker for official RUST-IR-3 authority-promotion artifacts."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


MILESTONE = "RUST-IR-3"
WORKFLOW = ".github/workflows/rust-ir-authority-promotion.yml"
PROMOTED = "RUST_INITIAL_IR_AUTHORITY_PROMOTED"
BLOCKED = "RUST_INITIAL_IR_AUTHORITY_PROMOTION_BLOCKED"
EXPECTED = {
    "rust-ir-3-prerequisite": ("prerequisite-rust-ir-2", "prerequisite_rust_ir_2", "prerequisite"),
    "rust-ir-3-contract": ("authority-contract", "authority_contract_and_invariant_audit", "contract"),
    "rust-ir-3-false-negative": ("directed-false-negative-search", "directed_false_negative_search", "differential"),
    "rust-ir-3-rust-stricter": ("directed-rust-stricter-search", "directed_rust_stricter_search", "differential"),
    "rust-ir-3-positive": ("positive-regression", "positive_regression", "regression"),
    "rust-ir-3-mutations": ("mutation-campaign", "mutation_campaign_post_switch_differential", "mutation"),
    "rust-ir-3-irv041": ("critical-irv041", "critical_irv041", "regression"),
    "rust-ir-3-provenance": ("product-authority-provenance", "product_authority_provenance", "product"),
    "rust-ir-3-no-rescue": ("no-python-rescue", "no_python_rescue", "product"),
    "rust-ir-3-lifecycle": ("lifecycle-boundary", "lifecycle_boundary", "lifecycle"),
    "rust-ir-3-packaged": ("packaged-clean-consumer", "packaged_clean_consumer", "environment"),
    "rust-ir-3-source": ("source-development-install", "source_development_install", "environment"),
    "rust-ir-3-recovery": ("next-request-recovery", "next_request_recovery", "product"),
    "rust-ir-3-transport": ("transport-continuity", "transport_continuity", "transport"),
    "rust-ir-3-deep": ("deep-stress", "deep_stress", "stress"),
    "rust-ir-3-performance": ("performance-characterization", "performance_characterization", "performance"),
    "rust-ir-3-platform-linux-x86_64": ("platform-linux-x86_64", "platform_qualification", "platform"),
    "rust-ir-3-platform-windows-x86_64": ("platform-windows-x86_64", "platform_qualification", "platform"),
    "rust-ir-3-platform-macos-x86_64": ("platform-macos-x86_64", "platform_qualification", "platform"),
    "rust-ir-3-platform-macos-arm64": ("platform-macos-arm64", "platform_qualification", "platform"),
    "rust-ir-3-python-3.11": ("python-3.11", "python_compatibility", "python"),
    "rust-ir-3-python-3.12": ("python-3.12", "python_compatibility", "python"),
    "rust-ir-3-python-3.13": ("python-3.13", "python_compatibility", "python"),
    "rust-ir-3-python-3.14": ("python-3.14", "python_compatibility", "python"),
}
EXPECTED_JOBS = {value[0] for value in EXPECTED.values()} | {"aggregate-fail-closed"}
GIT_SHA = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")


class CheckFailure(ValueError):
    """One fail-closed manifest or evidence violation."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def _product_evidence(evidence: dict[str, Any]) -> None:
    product = evidence.get("product_authority_provenance", {})
    rescue = evidence.get("no_python_rescue", {})
    oracle = evidence.get("explicit_python_oracle", {})
    compile_result = evidence.get("full_compile", {})
    _require(product.get("product_authority") == "rust", "Rust product authority not observed")
    _require(product.get("rust_verify_module_executed") is True, "Rust verifier did not execute")
    _require(product.get("rust_verify_module_accepted") is True, "Rust valid acceptance absent")
    _require(product.get("python_ir_verifier_consulted") is False, "Python remained product authority")
    _require(product.get("python_ir_verifier_calls") == 0, "Python IRVerifier entered product path")
    _require(product.get("python_lifecycle_calls") == 1, "LifecycleExpander order/authority changed")
    _require(product.get("post_lifecycle_rust_product_gate") is False, "wrong Rust verifier phase")
    _require(rescue.get("python_rescue_attempted") is False, "Python rescue/fallback observed")
    _require(rescue.get("automatic_fallback") is False, "automatic fallback observed")
    _require(rescue.get("lifecycle_calls_during_admission") == 0, "lifecycle ran after Rust rejection")
    _require(rescue.get("ssa_construction_calls_after_rejection") == 0, "SSA built after Rust rejection")
    _require(rescue.get("next_valid_request_succeeds") is True, "next request recovery failed")
    _require(oracle.get("role") == "qualification_oracle", "Python oracle unavailable")
    _require(oracle.get("affected_product_decision") is False, "oracle affected product decision")
    _require(compile_result.get("python_lifecycle_authority_observed") is True, "Python lifecycle authority absent")


def _semantic_check(kind: str, evidence: dict[str, Any]) -> None:
    _require(evidence.get("passed") is True and evidence.get("status") == "PASS", f"{kind} not PASS")
    if kind == "prerequisite_rust_ir_2":
        _require(all(evidence.get("checks", {}).values()), "invalid RUST-IR-2 prerequisite")
        _require(evidence.get("official", {}).get("run_id") == "33465504645", "wrong RUST-IR-2 run")
    elif kind == "authority_contract_and_invariant_audit":
        _require(evidence.get("python_only_semantic_invariants") == [], "Python-only semantic invariant found")
        _require(evidence.get("desired_authority") == "rust_verify_module", "wrong desired authority")
        _require(evidence.get("lifecycle_authority") == "python_LifecycleExpander", "lifecycle authority changed")
        _require(len(evidence.get("rows", [])) >= 22, "invariant matrix incomplete")
    elif kind == "directed_false_negative_search":
        _require(evidence.get("case_count", 0) >= 150, "false-negative campaign too small")
        _require(evidence.get("false_negatives") == [], "Python reject / Rust accept found")
    elif kind == "directed_rust_stricter_search":
        _require(evidence.get("case_count", 0) >= 130, "Rust-stricter campaign too small")
        _require(evidence.get("rust_stricter_rejections") == [], "Rust rejected valid product input")
    elif kind in {"positive_regression", "mutation_campaign_post_switch_differential"}:
        _require(evidence.get("acceptance_divergences") == [], "post-switch acceptance divergence")
        if kind.startswith("positive"):
            _require(evidence.get("case_count", 0) >= 65, "positive corpus incomplete")
        else:
            _require(evidence.get("mutation_count", 0) >= 75, "mutation campaign incomplete")
    elif kind == "critical_irv041":
        _require(evidence.get("pre_lifecycle_python") == "ACCEPT", "Python IRV-041 boundary rejected")
        _require(evidence.get("pre_lifecycle_rust") == "ACCEPT", "Rust IRV-041 boundary rejected")
    elif kind in {"product_authority_provenance", "no_python_rescue", "lifecycle_boundary", "next_request_recovery"}:
        _product_evidence(evidence)
    elif kind in {"packaged_clean_consumer", "source_development_install", "platform_qualification", "python_compatibility"}:
        _require(evidence.get("verifier_installed") is True, "native verifier not installed")
        _product_evidence(evidence.get("evidence", {}))
        if kind == "packaged_clean_consumer":
            _require(evidence.get("checkout_imported") is False, "packaged consumer imported checkout")
            _require(evidence.get("cargo_available") is False, "Cargo available to clean consumer")
            _require(evidence.get("rustc_available") is False, "rustc available to clean consumer")
        if kind == "python_compatibility":
            _require(evidence.get("python_implementation") == "CPython", "non-CPython claim")
    elif kind == "transport_continuity":
        rows = evidence.get("rows", [])
        _require({row.get("requested_ssa_transport") for row in rows} == {"in_process", "companion"}, "transport matrix incomplete")
        _require(all(row.get("final_result") == "PASS" for row in rows), "transport compile failed")
    elif kind == "deep_stress":
        _require(evidence.get("exact_sizes", {}).get("cases", 0) >= 130, "deep/stress sizes absent")
    elif kind == "performance_characterization":
        _require(evidence.get("correction_gate") is False, "pathological performance regression")


def check_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    revision = manifest.get("revision")
    run_id = str(manifest.get("run_id"))
    _require(manifest.get("milestone") == MILESTONE, "wrong milestone")
    _require(manifest.get("workflow") == WORKFLOW, "wrong workflow")
    _require(manifest.get("run_conclusion") == "success", "workflow run not successful")
    _require(isinstance(revision, str) and GIT_SHA.fullmatch(revision) is not None, "wrong revision")
    _require(run_id.isdigit() and int(run_id) > 0, "wrong run")
    jobs = manifest.get("job_conclusions", {})
    _require(set(jobs) == EXPECTED_JOBS, "mandatory job set mismatch")
    _require(all(value == "success" for value in jobs.values()), "mandatory job not successful")
    records = manifest.get("artifacts", [])
    _require(len(records) == len(EXPECTED), "artifact count mismatch")
    by_name = {record.get("name"): record for record in records}
    _require(set(by_name) == set(EXPECTED), "artifact name set mismatch")
    _require(len({record.get("id") for record in records}) == len(records), "artifact IDs not unique")
    checked = []
    for name, (job, kind, role) in EXPECTED.items():
        record = by_name[name]
        _require(record.get("source_job") == job, f"{name}: wrong source job")
        _require(record.get("kind") == kind and record.get("role") == role, f"{name}: wrong artifact kind/role")
        _require(str(record.get("run_id")) == run_id and record.get("revision") == revision, f"{name}: wrong identity")
        _require(isinstance(record.get("id"), int) and record["id"] > 0, f"{name}: invalid artifact ID")
        github = str(record.get("github_digest", "")).removeprefix("sha256:")
        zipped = str(record.get("zip_sha256", ""))
        _require(SHA256.fullmatch(github) is not None and github == zipped, f"{name}: GitHub/ZIP digest mismatch")
        evidence_path = (manifest_path.parent / str(record.get("evidence_path"))).resolve()
        _require(evidence_path.is_file(), f"{name}: missing evidence")
        actual_evidence = sha256(evidence_path.read_bytes()).hexdigest()
        _require(actual_evidence == record.get("evidence_sha256"), f"{name}: evidence digest mismatch")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        _require(evidence.get("milestone") == MILESTONE, f"{name}: evidence milestone mismatch")
        _require(evidence.get("kind") == kind, f"{name}: evidence kind mismatch")
        _require(evidence.get("revision") == revision and str(evidence.get("run_id")) == run_id, f"{name}: evidence identity mismatch")
        _semantic_check(kind, evidence)
        checked.append(name)
    return {
        "milestone": MILESTONE,
        "revision": revision,
        "run_id": run_id,
        "passed": True,
        "status": "PASS",
        "decision": PROMOTED,
        "checked_artifacts": checked,
        "product_authority": "rust",
        "python_ir_verifier_role": "oracle_only",
        "lifecycle_authority": "python_LifecycleExpander",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = check_manifest(args.manifest.resolve())
    except (CheckFailure, OSError, ValueError, json.JSONDecodeError) as error:
        result = {"milestone": MILESTONE, "passed": False, "status": "FAIL", "decision": BLOCKED, "error": str(error)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["decision"])
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
