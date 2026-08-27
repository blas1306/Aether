#!/usr/bin/env python3
"""Fail-closed checker for the checked-in RUST-4.1 evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = (
    ROOT / "docs/compiler/rust_ssa_independent_refinement_verifier.json"
)
DEFAULT_REPORT = (
    ROOT / "docs/compiler/RUST_SSA_INDEPENDENT_REFINEMENT_VERIFIER.md"
)
DECISION = "RUST_SSA_INDEPENDENT_REFINEMENT_VERIFIER_QUALIFIED"
RUST_4_0_SHADOW_ONLY = {
    "missing_phi",
    "extra_phi",
    "incorrect_phi_incoming",
    "incorrect_value_rename",
    "unreachable_block_incorrectly_preserved",
    "missing_instruction",
    "duplicated_instruction",
    "incorrect_return_value",
}
REQUIRED_EXPANDED = {
    "wrong_phi_incoming_value",
    "wrong_phi_predecessor",
    "duplicate_phi",
    "missing_preserved_instruction",
    "duplicated_preserved_instruction",
    "reordered_side_effecting_instructions",
    "wrong_constant",
    "wrong_call_target",
    "wrong_call_argument",
    "wrong_branch_target",
    "wrong_return",
    "wrong_parameter",
    "wrong_type",
    "missing_reachable_block",
    "retained_unreachable_block",
    "duplicated_block",
    "incorrect_promoted_value",
    "incorrect_rename_structurally_valid",
}
LAYERS = {
    "SCHEMA_IMPORTER",
    "EXISTING_SSA_VERIFIER",
    "REFINEMENT_VERIFIER",
    "PYTHON_SHADOW",
    "OTHER",
}


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    rows = evidence.get("mutation_campaign", [])
    indexed = {
        row.get("mutation"): row for row in rows if isinstance(row, dict)
    }
    semantic = [
        row for row in rows if isinstance(row, dict) and row.get("semantic") is True
    ]
    production = evidence.get("production_invariants", {})
    audit = evidence.get("independence_audit", {})
    verifier_source = (
        ROOT / "src/aether/ssa/refinement_verifier.py"
    ).read_text(encoding="utf-8")
    shadow_source = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    checks = {
        "milestone_baseline_decision": evidence.get("artifact_schema_version") == 1
        and evidence.get("milestone") == "RUST-4.1"
        and evidence.get("baseline_revision")
        == "7500d66a0d830542d2436b22356e0c34698f076f"
        and evidence.get("decision") == DECISION,
        "rust_4_0_evidence_consumed_exactly": set(indexed) >= RUST_4_0_SHADOW_ONLY
        and set(evidence.get("rust_4_0_shadow_only", {}).get("before", []))
        == RUST_4_0_SHADOW_ONLY
        and evidence.get("rust_4_0_shadow_only", {}).get("before_count") == 8
        and evidence.get("rust_4_0_shadow_only", {}).get("after_count") == 0,
        "expanded_campaign_complete": set(indexed) >= REQUIRED_EXPANDED
        and all(set(row.get("detected_by", [])) <= LAYERS for row in semantic),
        "no_semantic_shadow_only": bool(semantic)
        and not evidence.get("new_semantic_shadow_only")
        and all(row.get("python_shadow_only") is False for row in semantic)
        and all("REFINEMENT_VERIFIER" in row.get("detected_by", []) for row in semantic),
        "false_positive_qualification": evidence.get(
            "false_positive_qualification", {}
        ).get("status")
        == "PASS"
        and evidence.get("false_positive_qualification", {}).get(
            "false_positive_count"
        )
        == 0
        and evidence.get("false_positive_qualification", {}).get(
            "seeded_randomized_cfgs"
        )
        >= 32
        and {
            row.get("blocks")
            for row in evidence.get("false_positive_qualification", {}).get(
                "deep_cfg", []
            )
        }
        == {100, 1000, 5000, 10000},
        "historical_116_of_116": evidence.get("historical_qualification", {}).get(
            "denominator"
        )
        == 116
        and evidence.get("historical_qualification", {}).get("passed") == 116
        and evidence.get("historical_qualification", {}).get("failed") == 0
        and evidence.get("historical_qualification", {}).get("status") == "PASS",
        "formal_relation_complete": len(evidence.get("formal_transformations", []))
        == 14
        and all(
            set(row) == {"transformation", "relation"}
            for row in evidence.get("formal_transformations", [])
        )
        and len(evidence.get("effectful_instruction_coverage", [])) >= 7,
        "independence_strong": audit.get("classification") == "STRONG"
        and audit.get("consumes_producer_intermediates") is False
        and audit.get("shared_algorithms") == []
        and len(audit.get("common_mode_failures", [])) >= 5
        and "from .general_builder" not in verifier_source
        and "from aether.analysis" not in verifier_source
        and "phi_placement" not in verifier_source
        and "renaming" not in verifier_source,
        "production_frozen": production
        == {
            "production_changed": False,
            "authority_changed": False,
            "python_shadow_remains_mandatory": True,
            "fail_closed_changed": False,
            "schemas_or_protocol_changed": False,
            "rust_ssa_algorithm_changed": False,
            "python_ssa_algorithm_changed": False,
            "optimizer_backend_changed": False,
            "rollback_modes_changed": False,
            "refinement_verifier_mode": "QUALIFICATION_TEST_EXPLICIT_OPT_IN_ONLY",
        }
        and "SSARefinementVerifier" not in shadow_source
        and "python_ssa = run_python()" in shadow_source,
        "negative_qualification": evidence.get("negative_qualification", {}).get(
            "status"
        )
        == "PASS",
        "report_complete": report.startswith(
            "# Independent SSA refinement verifier — RUST-4.1"
        )
        and DECISION in report
        and "Python shadow remains mandatory: yes." in report
        and "No commit was created." in report,
    }
    return {
        "milestone": "RUST-4.1",
        "decision": (
            DECISION
            if all(checks.values())
            else "RUST_SSA_INDEPENDENT_REFINEMENT_VERIFIER_INCOMPLETE"
        ),
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
        print(f"{record['milestone']}: {record['decision']}")
        for name, passed in record["checks"].items():
            print(f"  {'PASS' if passed else 'FAIL'} {name}")
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
