#!/usr/bin/env python3
"""Fail-closed reconciler for the permanent RUST-4.4 evidence artifact."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ssa_shadow_independent_production_qualification.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_QUALIFICATION.md"
EXACT_BASELINE = "a81a67b3b9618b5af379714874eb1650623d66da"
REQUIRED_PLATFORMS = {"linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64"}
REQUIRED_DEEP = {100, 1000, 5000, 10000}
VALID_DECISIONS = {
    "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_BLOCKED",
    "RUST_SSA_SHADOW_INDEPENDENT_VALIDATION_GAP_FOUND",
    "RUST_SSA_SHADOW_INDEPENDENT_QUALIFICATION_INCOMPLETE",
    "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_QUALIFIED",
}
PATH_B = [
    "initial_ir_verification",
    "lifecycle_normalization",
    "rust_ssa_lowering_and_verification",
    "schema_v2_import",
    "imported_ssa_verification",
    "same_input_integrity_before_refinement",
    "independent_refinement_verification",
    "same_input_integrity_after_refinement",
    "final_generic_verification",
    "accept",
]


def _valid_success_trace(trace: object) -> bool:
    return (
        isinstance(trace, dict)
        and trace.get("accepted") is True
        and trace.get("completed_stages") == PATH_B
        and trace.get("failed_stage") is None
        and trace.get("rust_ssa_lowering_executed") is True
        and trace.get("rust_side_verification_succeeded") is True
        and trace.get("refinement_verification_executed") is True
        and trace.get("final_generic_verification_executed") is True
        and trace.get("python_general_ssa_builder_instantiated") is False
        and trace.get("python_ssa_lowering_executed") is False
        and trace.get("canonical_rust_python_comparison_executed") is False
        and set(trace.get("stage_execution_counts", {}).values()) == {1}
    )


def _valid_ab(row: object) -> bool:
    return (
        isinstance(row, dict)
        and row.get("production_a_accepts") is True
        and row.get("qualification_b_accepts") is True
        and row.get("authoritative_ssa_equal") is True
        and row.get("authoritative_rust_ssa_a") == row.get("authoritative_rust_ssa_b")
        and row.get("refinement_result") == "PASS"
        and row.get("final_generic_verification_result") == "PASS"
        and row.get("input_integrity_result") == "PASS"
        and _valid_success_trace(row.get("qualification_trace"))
    )


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    positives = evidence.get("positive_case_results", [])
    historical = evidence.get("historical_results", {})
    random = evidence.get("randomized_qualification", {})
    random_rows = random.get("results", []) if isinstance(random, dict) else []
    mutations = evidence.get("mutation_results", [])
    mutation_ids = [row.get("mutation_id") for row in mutations]
    classifications = Counter(row.get("classification") for row in mutations)
    dependency_ids = [
        row.get("mutation_id")
        for row in mutations
        if row.get("classification") == "PRODUCTION_SHADOW_DEPENDENCY"
    ]
    gap_ids = [
        row.get("mutation_id")
        for row in mutations
        if row.get("classification") == "ACCEPTED_BY_BOTH_INVALID"
    ]
    deep = evidence.get("deep_cfg_results", [])
    failures = evidence.get("fail_closed_injection_results", [])
    platforms = evidence.get("platform_results", [])
    passing_platforms = {
        row.get("platform") for row in platforms if row.get("status") == "PASS"
    }
    gates = evidence.get("regression_gate_results", {})
    all_gates = bool(gates) and all(value == "PASS" for value in gates.values())
    semantic_complete = (
        len(positives) >= 13
        and all(_valid_ab(row) for row in positives)
        and historical.get("passed") == historical.get("denominator") == 116
        and len(random_rows) >= 32
        and random.get("generated") == len(random.get("seeds", [])) == len(random_rows)
        and all(_valid_ab(row) for row in random_rows)
        and len(mutations) >= 58
        and len(mutation_ids) == len(set(mutation_ids))
        and all(row.get("applicable") is True for row in mutations)
        and not dependency_ids
        and not gap_ids
        and {row.get("blocks") for row in deep} == REQUIRED_DEEP
        and all(_valid_ab(row) for row in deep)
        and evidence.get("persistent_and_soak_results", {}).get("status") == "PASS"
        and evidence.get("concurrency_results", {}).get("status") == "PASS"
        and len(failures) >= 7
        and all(
            row.get("rejected") is True
            and row.get("python_fallback_executed") is False
            for row in failures
        )
        and evidence.get("independence_audit", {}).get("status") == "PASS"
        and evidence.get("independence_audit", {}).get("classification") == "STRONG"
        and evidence.get("production_non_regression_results", {}).get("status") == "PASS"
    )
    platform_complete = passing_platforms == REQUIRED_PLATFORMS
    expected_decision = (
        "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_BLOCKED"
        if dependency_ids
        else "RUST_SSA_SHADOW_INDEPENDENT_VALIDATION_GAP_FOUND"
        if gap_ids
        else "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_QUALIFIED"
        if semantic_complete and platform_complete and all_gates
        else "RUST_SSA_SHADOW_INDEPENDENT_QUALIFICATION_INCOMPLETE"
    )
    non_execution = evidence.get("path_b_non_execution_contract", {})
    checks = {
        "identity_and_exact_revision": evidence.get("artifact_schema_version") == 1
        and evidence.get("milestone") == "RUST-4.4"
        and evidence.get("baseline_revision") == EXACT_BASELINE
        and evidence.get("qualification_revision") == 1
        and evidence.get("decision") in VALID_DECISIONS,
        "production_policy_unchanged": evidence.get("production_policy_unchanged") is True
        and "mandatory synchronous" in str(evidence.get("production_policy_declaration", ""))
        and evidence.get("production_non_regression_results", {}).get("status") == "PASS",
        "qualification_explicitly_non_production": "Explicit direct-call diagnostic API" in str(evidence.get("qualification_only_path_declaration", ""))
        and "qualification" not in " ".join(evidence.get("path_a_stage_manifest", [])).lower(),
        "path_b_manifest_exact": evidence.get("path_b_stage_manifest") == PATH_B,
        "python_not_executed_by_b": non_execution
        == {
            "python_general_ssa_builder_instantiated": False,
            "python_ssa_lowering_executed": False,
            "canonical_rust_python_comparison_executed": False,
        },
        "positive_controls_reconcile": len(positives) >= 13
        and all(_valid_ab(row) for row in positives),
        "historical_116_reconciles": historical.get("expected") == 116
        and historical.get("denominator") == 116
        and historical.get("passed") == 116
        and historical.get("failed") == 0
        and len(historical.get("results", [])) == 116,
        "randomized_reconciles": random.get("generated") == len(random.get("seeds", [])) == len(random_rows)
        and len(random_rows) >= 32
        and len(random.get("seeds", [])) == len(set(random.get("seeds", [])))
        and all(_valid_ab(row) for row in random_rows),
        "mutations_reconcile": len(mutations) >= 58
        and len(mutation_ids) == len(set(mutation_ids))
        and all(
            set(row) >= {
                "mutation_id",
                "family",
                "applicable",
                "expected_semantic_invalidity",
                "first_non_shadow_rejection_layer",
                "shadow_independent_rejects",
                "current_production_rejects",
                "decisions_agree",
                "classification",
            }
            and row.get("applicable") is True
            and row.get("expected_semantic_invalidity") is True
            for row in mutations
        )
        and evidence.get("mutation_classification_totals") == dict(classifications),
        "dependency_ids_reconcile": evidence.get("PRODUCTION_SHADOW_DEPENDENCY_count") == len(dependency_ids)
        and evidence.get("PRODUCTION_SHADOW_DEPENDENCY_ids") == dependency_ids,
        "accepted_invalid_ids_reconcile": evidence.get("accepted_by_both_invalid_count") == len(gap_ids)
        and evidence.get("accepted_by_both_invalid_ids") == gap_ids,
        "deep_cfg_reconciles": {row.get("blocks") for row in deep} == REQUIRED_DEEP
        and all(_valid_ab(row) for row in deep),
        "operational_reconciles": evidence.get("persistent_and_soak_results", {}).get("status") == "PASS"
        and evidence.get("persistent_and_soak_results", {}).get("soak_requests", 0) >= 64
        and evidence.get("persistent_and_soak_results", {}).get("soak_passed") == evidence.get("persistent_and_soak_results", {}).get("soak_requests")
        and evidence.get("persistent_and_soak_results", {}).get("no_restart_during_soak") is True
        and {
            row.get("sequence")
            for row in evidence.get("persistent_and_soak_results", {}).get(
                "valid_invalid_transition_results", []
            )
            if row.get("status") == "PASS"
        }
        == {"valid_invalid_valid", "invalid_valid_invalid"},
        "concurrency_reconciles": evidence.get("concurrency_results", {}).get("status") == "PASS"
        and evidence.get("concurrency_results", {}).get("passed") == evidence.get("concurrency_results", {}).get("requests"),
        "fail_closed_reconciles": len(failures) >= 7
        and all(row.get("rejected") is True and row.get("python_fallback_executed") is False for row in failures),
        "independence_reconciles": evidence.get("independence_audit", {}).get("status") == "PASS"
        and evidence.get("independence_audit", {}).get("classification") == "STRONG"
        and evidence.get("independence_audit", {}).get("forbidden_import_or_call_hits") == []
        and evidence.get("independence_audit", {}).get("consumes_python_ssa_artifact") is False,
        "platform_claims_not_fabricated": len(platforms) == len({row.get("platform") for row in platforms})
        and {row.get("platform") for row in platforms} <= REQUIRED_PLATFORMS
        and evidence.get("required_platforms") == sorted(REQUIRED_PLATFORMS)
        and evidence.get("cross_platform_qualification_complete") is platform_complete,
        "semantic_completion_recomputes": evidence.get("local_semantic_qualification_complete") is semantic_complete,
        "decision_recomputes": evidence.get("decision") == expected_decision,
        "qualified_requires_every_gate": evidence.get("decision") != "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_QUALIFIED"
        or (semantic_complete and platform_complete and all_gates),
        "report_complete": report.startswith("# Shadow-independent production qualification — RUST-4.4")
        and str(evidence.get("decision")) in report
        and "does not change production policy" in report,
    }
    return {
        "milestone": "RUST-4.4",
        "decision": evidence.get("decision") if all(checks.values()) else DECISION_INCOMPLETE,
        "passed": all(checks.values()),
        "checks": checks,
        "recomputed": {
            "semantic_complete": semantic_complete,
            "platform_complete": platform_complete,
            "all_regression_gates_pass": all_gates,
            "PRODUCTION_SHADOW_DEPENDENCY_ids": dependency_ids,
            "accepted_by_both_invalid_ids": gap_ids,
            "expected_decision": expected_decision,
        },
    }


DECISION_INCOMPLETE = "RUST_SSA_SHADOW_INDEPENDENT_QUALIFICATION_INCOMPLETE"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()
    record = build_record(args.evidence, args.report)
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print(f"RUST-4.4: {record['decision']}")
        for name, passed in record["checks"].items():
            print(f"  {'PASS' if passed else 'FAIL'} {name}")
    if not record["passed"]:
        return 1
    if args.require_qualified and record["decision"] != "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_QUALIFIED":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
