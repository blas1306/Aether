#!/usr/bin/env python3
"""Fail-closed checker for the RUST-4.3 qualification artifact."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ssa_shadow_redundancy_qualification.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_SHADOW_REDUNDANCY_QUALIFICATION.md"
VALID_DECISIONS = {
    "PYTHON_SSA_SHADOW_NO_UNIQUE_COVERAGE_DEMONSTRATED",
    "PYTHON_SSA_SHADOW_UNIQUE_COVERAGE_DEMONSTRATED_RETAIN",
}
REQUIRED_FAMILIES = {
    "cfg_reachability",
    "phi",
    "value_provenance",
    "instruction_preservation",
    "effects",
    "return_termination",
    "slot_promotion",
    "generated_randomized",
}
REQUIRED_LAYERS = [
    "schema_import",
    "rust_companion_verification",
    "imported_ssa_verification",
    "same_input_integrity",
    "independent_refinement",
    "final_generic_verification",
    "python_shadow_canonical_comparison",
]


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    rows = evidence.get("per_mutation_results", [])
    ids = [row.get("mutation_id") for row in rows]
    classifications = Counter(row.get("classification") for row in rows)
    shadow_only = [row.get("mutation_id") for row in rows if row.get("classification") == "SHADOW_ONLY_AFTER_REFINEMENT"]
    accepted = [row.get("mutation_id") for row in rows if row.get("classification") == "ACCEPTED_BY_ALL"]
    families = {row.get("family") for row in rows}
    positives = evidence.get("positive_controls", {})
    deep = evidence.get("deep_cfg_results", [])
    independence = evidence.get("independence_assessment", {})
    gates = evidence.get("regression_gate_results", {})
    decision = evidence.get("decision")
    expected_decision = (
        "PYTHON_SSA_SHADOW_UNIQUE_COVERAGE_DEMONSTRATED_RETAIN"
        if shadow_only
        else "PYTHON_SSA_SHADOW_NO_UNIQUE_COVERAGE_DEMONSTRATED"
    )
    checks = {
        "identity": evidence.get("artifact_schema_version") == 1
        and evidence.get("milestone") == "RUST-4.3"
        and evidence.get("qualification_revision") == 1
        and evidence.get("baseline_revision") == "07a372da7f9b80dbc079b2f27c43d091b256f0b8"
        and decision in VALID_DECISIONS,
        "production_unchanged": evidence.get("production_mode") == "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
        and evidence.get("production_policy_unchanged") is True
        and evidence.get("production_changes") == [],
        "campaign_broad": len(rows) >= 40
        and families >= REQUIRED_FAMILIES
        and len(ids) == len(set(ids))
        and all(isinstance(value, str) and value.startswith("R43-") for value in ids),
        "raw_rows_complete": all(
            set(row) >= {
                "mutation_id",
                "family",
                "source_fixture",
                "semantic_intent",
                "applicable",
                "first_rejection_layer",
                "refinement_rejected",
                "python_shadow_rejected",
                "accepted_without_shadow",
                "classification",
                "validation_layers",
            }
            and row.get("applicable") is True
            and [layer.get("layer") for layer in row.get("validation_layers", [])]
            == REQUIRED_LAYERS
            for row in rows
        ),
        "summary_recomputes": evidence.get("classification_totals") == dict(classifications)
        and evidence.get("SHADOW_ONLY_AFTER_REFINEMENT_count") == len(shadow_only)
        and evidence.get("SHADOW_ONLY_AFTER_REFINEMENT_ids") == shadow_only
        and evidence.get("ACCEPTED_BY_ALL_semantic_mutation_count") == len(accepted)
        and evidence.get("ACCEPTED_BY_ALL_semantic_mutation_ids") == accepted,
        "decision_recomputes": decision == expected_decision,
        "randomized": evidence.get("randomized_campaign", {}).get("programs", 0) >= 8
        and evidence.get("randomized_campaign", {}).get("bounded") is True
        and evidence.get("randomized_campaign", {}).get("reproducible") is True
        and set(evidence.get("randomized_campaign", {}).get("cfg_shapes", []))
        == {"diamond_merge", "loop_backedge_phi"}
        and len(evidence.get("randomized_seeds", [])) >= 8,
        "positive_controls": positives.get("attempted", 0) >= 8
        and positives.get("passed") == positives.get("attempted")
        and all(row.get("non_shadow_accepted") and row.get("canonical_equivalent") for row in positives.get("results", [])),
        "deep_cfg": {row.get("blocks") for row in deep} == {100, 1000, 5000, 10000}
        and all(row.get("status") == "PASS" for row in deep),
        "independence": independence.get("status") == "PASS"
        and independence.get("classification") == "IMPLEMENTATION_INDEPENDENT"
        and independence.get("forbidden_import_or_oracle_hits") == []
        and independence.get("uses_python_shadow_as_oracle") is False
        and independence.get("consumes_rust_producer_intermediates") is False,
        "historical": evidence.get("historical_results", {}).get("real_corpus_116", {}).get("passed") == 116
        and evidence.get("historical_results", {}).get("real_corpus_116", {}).get("denominator") == 116,
        "regression_gates": gates.get("rust_4_0") == "PASS"
        and gates.get("rust_4_1") == "PASS"
        and gates.get("rust_4_2") == "PASS"
        and str(gates.get("rust_4_3_focused", "")).startswith("PASS_")
        and str(gates.get("full_python_suite", "")).startswith("PASS_4982")
        and gates.get("cargo_test_workspace_locked") == "PASS"
        and gates.get("cargo_fmt_all_check") == "PASS"
        and gates.get("git_diff_check") == "PASS",
        "recommendation_safe": "Retain" in str(evidence.get("recommendation", ""))
        and "not a proof" in report
        and "not authorization" in report,
        "report_complete": report.startswith("# Independent authority shadow redundancy qualification — RUST-4.3")
        and str(decision) in report
        and "No commit was created." in report,
    }
    return {
        "milestone": "RUST-4.3",
        "decision": decision if all(checks.values()) else "RUST_4_3_QUALIFICATION_INCOMPLETE",
        "passed": all(checks.values()),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    record = build_record(args.evidence, args.report)
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print(f"RUST-4.3: {record['decision']}")
        for name, passed in record["checks"].items():
            print(f"  {'PASS' if passed else 'FAIL'} {name}")
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
