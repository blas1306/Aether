#!/usr/bin/env python3
"""Validate the checked-in RUST-4.0 trust-model qualification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ssa_independent_authority_qualification.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_INDEPENDENT_AUTHORITY_QUALIFICATION.md"
DECISION = "RUST_SSA_INDEPENDENT_AUTHORITY_REQUIRES_VERIFIER_HARDENING"
CLASSIFICATIONS = {
    "INDEPENDENTLY_VERIFIED",
    "DIFFERENTIALLY_VERIFIED_ONLY",
    "SELF_VERIFIED",
    "TEST_ONLY",
    "SHADOW_ONLY",
    "REDUNDANTLY_VERIFIED",
    "INSUFFICIENT_EVIDENCE",
}
REQUIRED_PROPERTIES = {
    "CFG preservation", "reachability", "predecessor/successor consistency",
    "dominance", "immediate dominators", "dominance frontiers", "phi placement",
    "exact phi predecessor labels", "SSA single definition",
    "use dominated by definition", "phi incoming dominance", "type preservation",
    "parameter preservation", "block ordering/determinism",
    "unreachable block handling", "lifecycle/ownership invariants",
    "schema-v2 integrity", "canonical deterministic output",
}
REQUIRED_MUTATIONS = {
    "missing_phi", "extra_phi", "incorrect_phi_incoming", "incorrect_predecessor",
    "duplicate_definition", "use_before_definition", "definition_not_dominating_use",
    "phi_incoming_not_dominating_edge", "incorrect_type", "incorrect_value_rename",
    "incorrect_block_target", "unreachable_block_incorrectly_preserved",
    "missing_instruction", "duplicated_instruction", "incorrect_return_value",
    "ownership_lifecycle_corruption",
}
LAYERS = {
    "RUST_VERIFIER", "PYTHON_IMPORTED_SSA_VERIFIER", "SCHEMA_IMPORTER",
    "CANONICAL_COMPARISON", "PYTHON_SHADOW_ONLY", "OTHER",
}


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    inventory = evidence.get("trust_inventory", [])
    properties = evidence.get("property_matrix", [])
    mutations = evidence.get("mutation_campaign", [])
    history = evidence.get("historical_mismatch_audit", [])
    gaps = evidence.get("verifier_completeness_gaps", [])
    production = evidence.get("production_invariants", {})
    qualification = evidence.get("qualification", {})
    indexed_properties = {
        row.get("property"): row for row in properties if isinstance(row, dict)
    }
    indexed_mutations = {
        row.get("mutation"): row for row in mutations if isinstance(row, dict)
    }
    shadow_only = {
        row.get("mutation") for row in mutations
        if isinstance(row, dict) and row.get("python_shadow_only") is True
    }
    critical = [
        row for row in gaps
        if isinstance(row, dict) and row.get("severity") == "CRITICAL"
    ]
    source = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    checks = {
        "milestone_baseline_decision": evidence.get("artifact_schema_version") == 1
        and evidence.get("milestone") == "RUST-4.0"
        and evidence.get("baseline_milestone") == "RUST-3.15"
        and evidence.get("baseline_revision") == "7500d66a0d830542d2436b22356e0c34698f076f"
        and evidence.get("decision") == DECISION,
        "trust_inventory_complete": isinstance(inventory, list)
        and len(inventory) == 16
        and all(
            isinstance(row, dict)
            and {
                "layer", "properties", "producer_and_verifier_share_implementation",
                "share_algorithm", "share_representation", "common_mode_risk",
                "without_python_shadow",
            } == set(row)
            for row in inventory
        ),
        "property_matrix_complete": set(indexed_properties) == REQUIRED_PROPERTIES
        and all(row.get("classification") in CLASSIFICATIONS for row in indexed_properties.values())
        and all(
            {
                "property", "classification", "producer", "verifiers",
                "producer_verifier_shared_implementation",
                "producer_verifier_shared_algorithm",
                "producer_verifier_shared_representation", "common_mode_bug",
                "python_shadow_independence", "without_python_shadow", "basis",
            } == set(row)
            for row in indexed_properties.values()
        )
        and indexed_properties.get("unreachable block handling", {}).get("classification") == "SHADOW_ONLY",
        "mutation_campaign_complete": set(indexed_mutations) == REQUIRED_MUTATIONS
        and all(
            isinstance(row.get("detected_by"), list)
            and set(row["detected_by"]) <= LAYERS
            and row.get("rust_verifier_executed") is True
            for row in indexed_mutations.values()
        )
        and indexed_mutations.get("ownership_lifecycle_corruption", {}).get("applicable_to_fixture") is False
        and indexed_mutations.get("ownership_lifecycle_corruption", {}).get("detected_by") == ["OTHER"],
        "concrete_shadow_only_found": len(shadow_only) >= 5
        and shadow_only == set(evidence.get("shadow_only_mutations", []))
        and evidence.get("shadow_dependency_analysis", {}).get("answer") is True
        and set(evidence.get("shadow_dependency_analysis", {}).get("concrete_cases", [])) == shadow_only
        and len(evidence.get("shadow_only_properties", [])) >= 5
        and all(
            isinstance(row, dict) and set(row) == {"guarantee", "replacement"}
            for row in evidence.get("shadow_only_properties", [])
        )
        and {"missing_phi", "extra_phi", "incorrect_return_value"} <= shadow_only
        and all(
            "CANONICAL_COMPARISON" in indexed_mutations[name]["detected_by"]
            and not {
                "RUST_VERIFIER", "PYTHON_IMPORTED_SSA_VERIFIER", "SCHEMA_IMPORTER"
            } & set(indexed_mutations[name]["detected_by"])
            for name in shadow_only
        ),
        "historical_audit_grounded": isinstance(history, list)
        and {row.get("id") for row in history if isinstance(row, dict)}
        == {"RC1", "RC2", "RC3", "RC4", "RC5", "RC6"}
        and any(
            row.get("id") == "RC5"
            and "PYTHON_IMPORTED_SSA_VERIFIER" in row.get("detected_by", [])
            and row.get("would_escape_without_shadow_at_discovery") is True
            for row in history if isinstance(row, dict)
        ),
        "critical_gaps_and_replacements": len(critical) >= 2
        and all(row.get("replacement") for row in gaps if isinstance(row, dict))
        and len(evidence.get("required_verifier_hardening", [])) >= 4,
        "common_mode_and_oracle_analysis": len(evidence.get("common_mode_failures", [])) >= 5
        and set(evidence.get("independent_oracle_analysis", {})) == {
            "implementation_diversity", "correctness_evidence",
            "python_shadow_unique_guarantee",
        },
        "future_architecture_is_design_only": evidence.get("future_architecture", {}).get("promotion_allowed_by_rust_4_0") is False
        and len(evidence.get("future_architecture", {}).get("flow", [])) == 4,
        "production_frozen": production == {
            "production_changed": False,
            "authority_changed": False,
            "shadow_remains_mandatory": True,
            "fail_closed_changed": False,
            "schemas_changed": False,
            "ssa_algorithms_changed": False,
            "lifecycle_changed": False,
            "verifier_semantics_changed": False,
            "optimizer_backend_changed": False,
            "rollback_modes_changed": False,
        }
        and "python_ssa = run_python()" in source
        and "difference = _difference(python_canonical, rust_canonical)" in source,
        "qualification_recorded": isinstance(qualification, dict)
        and len(qualification) == 12
        and all(
            value == "PASS" or value == "PASS_INHERITED_RUST_3_15"
            for value in qualification.values()
        ),
        "report_complete": report.startswith("# SSA independent authority qualification — RUST-4.0")
        and DECISION in report
        and "Production unchanged: yes." in report
        and "Python shadow remains mandatory: yes." in report
        and "No commit was created." in report,
    }
    passed = all(checks.values())
    return {
        "milestone": "RUST-4.0",
        "decision": evidence.get("decision") if passed else "RUST_SSA_INDEPENDENT_AUTHORITY_QUALIFICATION_BLOCKED",
        "passed": passed,
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
