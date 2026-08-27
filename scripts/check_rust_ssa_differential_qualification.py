#!/usr/bin/env python3
"""Fail closed unless a RUST-4.5 differential artifact is qualified."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "qualification/rust45/differential.json"
QUALIFIED = "RUST_SSA_DIFFERENTIAL_SHADOW_QUALIFIED"
BLOCKED = "RUST_SSA_DIFFERENTIAL_SHADOW_BLOCKED"
DEFAULT_MODE = "RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED"
DIFFERENTIAL_MODE = "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
DIFFERENTIAL_MODE_VALUE = "rust_ssa_authority_python_shadow"


def build_record(evidence_path: Path = DEFAULT_EVIDENCE) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    production = evidence.get("production_default_observation", {})
    differential = evidence.get("differential_mode_observation", {})
    historical = evidence.get("historical_results", {})
    mutations = evidence.get("mutation_results", [])
    deep = evidence.get("deep_cfg_results", [])

    semantic_campaign = bool(
        historical.get("passed") == historical.get("denominator") == 116
        and len(mutations) == 58
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
        and all(
            row.get("rejected") is True
            for row in evidence.get("fail_closed_injection_results", [])
        )
    )
    production_default = bool(
        production.get("status") == "PASS"
        and production.get("mode") == DEFAULT_MODE
        and production.get("authority") == "rust"
        and production.get("refinement_mandatory") is True
        and production.get("python_general_ssa_builder_executed") is False
        and production.get("canonical_comparison_executed") is False
        and production.get("environment", {}).get("effective_value") is None
        and production.get("focused_policy_tests", {}).get("returncode") == 0
    )
    differential_mode = bool(
        differential.get("status") == "PASS"
        and differential.get("mode") == DIFFERENTIAL_MODE
        and differential.get("authority") == "rust"
        and differential.get("refinement_mandatory") is True
        and differential.get("python_general_ssa_builder_executed") is True
        and differential.get("canonical_comparison_executed") is True
        and differential.get("canonical_mismatch_fail_closed") is True
        and differential.get("refinement_failure_fail_closed") is True
        and differential.get("environment", {}).get("effective_value")
        == DIFFERENTIAL_MODE_VALUE
        and differential.get("focused_differential_tests", {}).get("returncode") == 0
    )
    rollback = all(
        evidence.get("rollback", {}).get(mode) == "PASS"
        for mode in ("differential", "python_authority_rust_shadow", "python_only")
    )
    complete = semantic_campaign and production_default and differential_mode and rollback
    expected_decision = QUALIFIED if complete else BLOCKED
    checks = {
        "identity": evidence.get("artifact_schema_version") == 1
        and evidence.get("milestone") == "RUST-4.5"
        and evidence.get("qualification_scope") == "differential",
        "semantic_campaign": semantic_campaign,
        "production_default_observation": production_default,
        "differential_mode_observation": differential_mode,
        "rollback": rollback,
        "completion_recomputes": evidence.get("differential_qualification_complete")
        is complete,
        "decision_recomputes": evidence.get("decision") == expected_decision,
    }
    return {
        "milestone": "RUST-4.5A",
        "passed": all(checks.values()),
        "qualified": all(checks.values()) and expected_decision == QUALIFIED,
        "decision": evidence.get("decision"),
        "expected_decision": expected_decision,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    record = build_record(args.evidence)
    print(f"RUST-4.5A: {record['decision']}")
    for name, passed in record["checks"].items():
        print(f"  {'PASS' if passed else 'FAIL'} {name}")
    return 0 if record["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
