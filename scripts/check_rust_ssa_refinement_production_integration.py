#!/usr/bin/env python3
"""Fail-closed checker for RUST-4.2 production integration evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ssa_refinement_production_integration.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_REFINEMENT_PRODUCTION_INTEGRATION.md"
DECISION = "RUST_SSA_REFINEMENT_PRODUCTION_INTEGRATION_QUALIFIED"
REQUIRED_MUTATIONS = {
    "missing_phi",
    "extra_phi",
    "wrong_phi_incoming_value",
    "wrong_return",
    "missing_preserved_instruction",
    "duplicated_preserved_instruction",
    "retained_unreachable_block",
    "wrong_branch_target",
    "wrong_call_target",
    "wrong_call_argument",
    "incorrect_promoted_value",
}


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    production = evidence.get("production_invariants", {})
    same_input = evidence.get("same_input_guarantee", {})
    campaign = evidence.get("mutation_campaign", [])
    indexed = {row.get("mutation"): row for row in campaign if isinstance(row, dict)}
    positive = evidence.get("positive_qualification", {})
    historical = evidence.get("historical_qualification", {})
    operational = evidence.get("operational_qualification", {})
    rollback = evidence.get("rollback_modes", {})
    response = evidence.get("response_compatibility", {})
    platform = evidence.get("platform_status", {})
    gates = evidence.get("gates", {})
    shadow_source = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    checks = {
        "identity": evidence.get("artifact_schema_version") == 1
        and evidence.get("milestone") == "RUST-4.2"
        and evidence.get("baseline_revision")
        == "7a864686ec2698467f092a42efbe7982aede2018"
        and evidence.get("decision") == DECISION,
        "production_fail_closed": production
        == {
            "rust_authority": True,
            "python_shadow": "mandatory_synchronous_independent_fail_closed",
            "canonical_comparison": "mandatory_fail_closed",
            "ordinary_response_shape_changed": False,
            "schema_changed": False,
            "protocol_changed": False,
        }
        and '"refinement_verifier_failure"' in shadow_source
        and "verify_ssa_refinement(normalized_module, rust_ssa)" in shadow_source
        and "python_ssa = run_python()" in shadow_source,
        "production_ordering": len(evidence.get("production_ordering", [])) == 12
        and "before run_python" in evidence.get("integration_point", ""),
        "same_input": same_input.get("status") == "PASS"
        and same_input.get("normalized_object_reused_by_refinement_and_python") is True
        and same_input.get("rust_payload_serialized_once_from_normalized_snapshot") is True
        and set(same_input.get("integrity_checkpoints", []))
        == {
            "before_refinement_verification",
            "before_python_shadow",
            "input_snapshot",
        }
        and len(same_input.get("regressions", [])) == 5,
        "failure_injection": set(indexed) >= REQUIRED_MUTATIONS
        and all(
            indexed[name].get("refinement_failed_before_python") is True
            and indexed[name].get("python_shadow_would_detect") is True
            and indexed[name].get("first_failure") == "refinement_verifier_failure"
            for name in REQUIRED_MUTATIONS
        ),
        "rust_4_0_coverage": len(evidence.get("rust_4_0_shadow_only_covered", [])) == 8,
        "positive_qualification": positive.get("status") == "PASS"
        and positive.get("randomized_cfgs") >= 32
        and positive.get("refinement_failures") == 0
        and {row.get("blocks") for row in positive.get("deep_cfg", [])}
        == {993, 1000, 5000, 10000}
        and all(row.get("status") == "PASS" for row in positive.get("deep_cfg", [])),
        "historical_116": historical.get("status") == "PASS"
        and historical.get("denominator") == 116
        and historical.get("passed") == 116
        and historical.get("failed") == 0,
        "operational": operational.get("status") == "PASS"
        and operational.get("deterministic_failures") == 0
        and operational.get("state_leakage") == 0
        and operational.get("refinement_failures_on_valid_inputs") == 0
        and operational.get("shadow_mismatches") == 0
        and operational.get("infrastructure_failures") == 0,
        "clean_and_reused_process": operational.get("clean_process") == "PASS"
        and operational.get("reused_process") == "PASS"
        and operational.get("persistent_process_starts") == 1
        and operational.get("persistent_requests", 0) > 1,
        "performance": evidence.get("performance", {}).get("status") == "PASS"
        and evidence.get("performance", {}).get("threshold_enforced") is False
        and {row.get("workload") for row in evidence.get("performance", {}).get("workloads", [])}
        == {"ordinary", "deep_100", "deep_1000", "deep_5000", "deep_10000"}
        and all(
            set(row) >= {
                "before_seconds",
                "after_seconds",
                "refinement_seconds",
                "refinement_share_of_after",
                "dual_lane_total_seconds",
            }
            for row in evidence.get("performance", {}).get("workloads", [])
        ),
        "response_compatibility": response.get("status") == "PASS"
        and response.get("ordinary_ssa_schema_v2") == "unchanged"
        and response.get("SSAShadowReport_fields") == "unchanged"
        and response.get("companion_protocol_identity") == "unchanged_v1",
        "rollback": rollback
        == {
            "rust_authority_python_shadow": "refinement_mandatory",
            "python_authority_rust_shadow": "unchanged_no_refinement",
            "python_only": "unchanged_no_refinement",
            "status": "PASS",
        },
        "platform_ci": set(platform.get("ci_matrix", []))
        == {
            "linux-x86_64",
            "windows-x86_64",
            "macos-x86_64",
            "macos-arm64",
        }
        and platform.get("non_local_results")
        == "CI prepared; no local result invented",
        "historical_evidence_preserved": "preserved without rewriting"
        in evidence.get("historical_evidence", ""),
        "required_gates": gates.get("rust_4_2_checker") == "PASS"
        and gates.get("rust_4_0_mutation_contracts") == "PASS"
        and gates.get("rust_4_1_verifier_contracts") == "PASS"
        and gates.get("production_failure_injection") == "PASS"
        and gates.get("historical_116") == "PASS"
        and gates.get("adversarial_random_deep") == "PASS"
        and gates.get("operational_soak_persistent_concurrency") == "PASS"
        and str(gates.get("full_python_suite", "")).startswith("PASS_")
        and gates.get("cargo_test_workspace_locked") == "PASS"
        and gates.get("cargo_fmt_check") == "PASS"
        and gates.get("git_diff_check") == "PASS",
        "report_complete": report.startswith(
            "# Refinement verifier production integration — RUST-4.2"
        )
        and DECISION in report
        and "Python shadow remains mandatory" in report
        and "No commit was created." in report,
        "no_commit_claim": evidence.get("commit_created") is False,
    }
    return {
        "milestone": "RUST-4.2",
        "decision": DECISION if all(checks.values()) else (
            "RUST_SSA_REFINEMENT_PRODUCTION_INTEGRATION_INCOMPLETE"
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
        print(f"RUST-4.2: {record['decision']}")
        for name, passed in record["checks"].items():
            print(f"  {'PASS' if passed else 'FAIL'} {name}")
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
