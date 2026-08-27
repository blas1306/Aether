#!/usr/bin/env python3
"""Recompute the permanent RUST-4.5 promotion decision from raw evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = (
    ROOT
    / "docs/compiler/rust_ssa_shadow_independent_production_promotion.json"
)
DEFAULT_REPORT = (
    ROOT / "docs/compiler/RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION.md"
)
BASELINE = "c524d9be54d2e23f865f45583b59ce88ba7233ef"
REQUIRED_MODES = {
    "PYTHON_SSA_ONLY",
    "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
    "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
    "RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED",
}
REQUIRED_PLATFORMS = {
    "linux-x86_64",
    "windows-x86_64",
    "macos-x86_64",
    "macos-arm64",
}
VALID_DECISIONS = {
    "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTED",
    "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_PENDING_CI",
    "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_BLOCKED",
}


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    mutations = evidence.get("mutation_results", [])
    historical = evidence.get("historical_results", {})
    deep = evidence.get("deep_cfg_results", [])
    proof = evidence.get("structural_no_shadow_proof", {})
    differential = evidence.get("differential_mode_proof", {})
    platforms = evidence.get("platform_results", [])
    passing_platforms = {
        row.get("platform")
        for row in platforms
        if row.get("status") == "PASS" and row.get("revision") == BASELINE
    }
    semantic = bool(
        historical.get("passed") == historical.get("denominator") == 116
        and len(mutations) == 58
        and len({row.get("mutation_id") for row in mutations}) == 58
        and Counter(row.get("classification") for row in mutations)
        == Counter({"REJECTED_BY_BOTH": 58})
        and evidence.get("PRODUCTION_SHADOW_DEPENDENCY_count") == 0
        and evidence.get("accepted_by_both_invalid_count") == 0
        and {row.get("blocks") for row in deep} == {993, 1000, 5000, 10000}
        and all(
            row.get("production_a_accepts") is True
            and row.get("qualification_b_accepts") is True
            and row.get("authoritative_ssa_equal") is True
            for row in deep
        )
        and evidence.get("persistent_and_soak_results", {}).get("status") == "PASS"
        and evidence.get("concurrency_results", {}).get("status") == "PASS"
        and evidence.get("adversarial", {}).get("status") == "PASS"
    )
    no_shadow = proof == {
        "python_general_ssa_builder_instantiated": False,
        "python_ssa_lowering_executed": False,
        "python_comparison_dto_constructed": False,
        "canonical_rust_python_comparison_executed": False,
        "refinement_verification_executed": True,
        "imported_ssa_verification_executed": True,
        "final_generic_verification_executed": True,
    }
    differential_preserved = all(
        differential.get(key) is True
        for key in (
            "python_general_ssa_builder_executed",
            "canonical_comparison_executed",
            "canonical_mismatch_fail_closed",
            "refinement_failure_fail_closed",
        )
    )
    local_complete = bool(
        semantic
        and no_shadow
        and differential_preserved
        and evidence.get("focused_policy_tests", {}).get("status") == "PASS"
        and evidence.get("full_suite", {}).get("status") == "PASS"
        and evidence.get("cargo_workspace", {}).get("status") == "PASS"
        and evidence.get("clean_install", {}).get("status") == "PASS"
    )
    platform_complete = passing_platforms == REQUIRED_PLATFORMS
    expected_decision = (
        "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_BLOCKED"
        if not local_complete
        else "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTED"
        if platform_complete
        else "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_PENDING_CI"
    )
    checks = {
        "identity": evidence.get("artifact_schema_version") == 1
        and evidence.get("milestone") == "RUST-4.5"
        and evidence.get("baseline_revision") == BASELINE
        and evidence.get("decision") in VALID_DECISIONS,
        "policy": evidence.get("old_default") == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
        and evidence.get("new_default")
        == "RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED"
        and set(evidence.get("mode_matrix", [])) == REQUIRED_MODES,
        "ordering": evidence.get("production_ordering", [])[-2:]
        == ["final_generic_verification", "accept"],
        "no_shadow": no_shadow,
        "differential_preserved": differential_preserved,
        "semantic": semantic,
        "rollback": all(
            evidence.get("rollback", {}).get(key) == "PASS"
            for key in (
                "differential",
                "python_authority_rust_shadow",
                "python_only",
            )
        ),
        "compatibility": evidence.get("protocol_version") == 1
        and evidence.get("ssa_schema_version") == 2
        and evidence.get("response_shape_changed") is False,
        "handoff": evidence.get("optimizer_backend_handoff", {}).get(
            "rust_origin_preserved"
        )
        is True
        and evidence.get("optimizer_backend_handoff", {}).get(
            "reconstructed_from_canonical_form"
        )
        is False,
        "python_retained": evidence.get("python_ssa_deleted") is False,
        "platform_claims": passing_platforms <= REQUIRED_PLATFORMS
        and evidence.get("cross_platform_qualification_complete")
        is platform_complete,
        "local_recomputes": evidence.get("local_qualification_complete")
        is local_complete,
        "decision_recomputes": evidence.get("decision") == expected_decision,
        "report": report.startswith("# RUST-4.5")
        and str(evidence.get("decision")) in report
        and "not a formal proof" in report,
    }
    return {
        "milestone": "RUST-4.5",
        "passed": all(checks.values()),
        "decision": evidence.get("decision"),
        "expected_decision": expected_decision,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--require-promoted", action="store_true")
    args = parser.parse_args()
    record = build_record(args.evidence, args.report)
    print(f"RUST-4.5: {record['decision']}")
    for name, passed in record["checks"].items():
        print(f"  {'PASS' if passed else 'FAIL'} {name}")
    if not record["passed"]:
        return 1
    if args.require_promoted and record["decision"] != (
        "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTED"
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
