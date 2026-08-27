#!/usr/bin/env python3
"""Validate the fail-closed, official-evidence RUST-4.5 closure record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = (
    ROOT
    / "docs/compiler/rust_ssa_shadow_independent_production_promotion_closure.json"
)
DEFAULT_REPORT = (
    ROOT
    / "docs/compiler/RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE.md"
)
WORKFLOW = ROOT / ".github/workflows/rust-ssa-shadow.yml"

RUN_ID = 33110365185
REVISION = "b7362b06ead8da36d3ad3a97351fd5813c258590"
PRIOR_DECISION = "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_PENDING_CI"
PROMOTED = "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTED"
BLOCKED = "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTION_CLOSURE_BLOCKED"
DEFAULT_MODE = "RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED"
DIFFERENTIAL_MODE = "RUST_SSA_AUTHORITY_PYTHON_SHADOW"

REQUIRED_PLATFORMS = {
    "linux-x86_64",
    "windows-x86_64",
    "macos-x86_64",
    "macos-arm64",
}
REQUIRED_JOBS = {
    "rust-4.5-production-default-no-python-shadow",
    "rust-4.5-ci-differential-rust-refinement-python-shadow",
    "rust-4.5-shadow-independent-clean-install-linux-x86_64",
    "rust-4.5-shadow-independent-clean-install-windows-x86_64",
    "rust-4.5-shadow-independent-clean-install-macos-x86_64",
    "rust-4.5-shadow-independent-clean-install-macos-arm64",
    "rust-authority-linux-x86_64",
    "rust-authority-windows-x86_64",
    "rust-authority-macos-x86_64",
    "rust-authority-macos-arm64",
    "rust-4.4-shadow-independent-linux-x86_64",
    "rust-4.4-shadow-independent-windows-x86_64",
    "rust-4.4-shadow-independent-macos-x86_64",
    "rust-4.4-shadow-independent-macos-arm64",
    "rust-4-4-full-local-qualification",
    "promotion-fixtures",
    "historical-116",
    "adversarial",
    "deep-cfg",
    "authority-soak",
    "full-suite-rust-default",
    "production-stabilization-operational",
    "production-stabilization-regressions",
    "production-stabilization-full-suite",
    "rust-stabilization-linux-x86_64",
    "rust-stabilization-windows-x86_64",
    "rust-stabilization-macos-x86_64",
    "rust-stabilization-macos-arm64",
    "python-authority-rust-shadow",
    "python-only",
    "production-stabilization-aggregate",
    "aggregate",
    "performance",
}
REQUIRED_ARTIFACTS = {
    "rust-4.5-differential-shadow",
    "rust-4.5-clean-install-linux-x86_64",
    "rust-4.5-clean-install-windows-x86_64",
    "rust-4.5-clean-install-macos-x86_64",
    "rust-4.5-clean-install-macos-arm64",
    "promotion-fixtures",
    "historical-116",
    "adversarial",
    "deep-cfg",
    "authority-soak",
    "full-suite-rust-default",
    "production-stabilization-operational",
    "production-stabilization-regressions",
    "production-stabilization-full-suite",
    "production-stabilization-platform-linux-x86_64",
    "production-stabilization-platform-windows-x86_64",
    "production-stabilization-platform-macos-x86_64",
    "production-stabilization-platform-macos-arm64",
    "rust-ssa-production-stabilization",
    "rust-ssa-authority-promotion-v2",
}
EXPECTED_ORDERING = [
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
SHA256 = re.compile(r"[0-9a-f]{64}")


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
    workflow_path: Path = WORKFLOW,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    workflow = workflow_path.read_text(encoding="utf-8")

    jobs = evidence.get("required_job_results", {})
    artifacts = evidence.get("artifact_manifest", [])
    artifact_by_name = {
        row.get("artifact_name"): row
        for row in artifacts
        if isinstance(row, dict)
    }
    platforms = evidence.get("platform_matrix", [])
    platform_by_name = {
        row.get("platform"): row
        for row in platforms
        if isinstance(row, dict)
    }
    default = evidence.get("default_mode", {})
    differential = evidence.get("differential_mode", {})
    historical = evidence.get("historical_result", {})
    mutations = evidence.get("mutation_result", {})
    deep = evidence.get("deep_cfg_result", {})
    soak = evidence.get("soak_result", {})
    full_suite = evidence.get("full_suite_result", {})
    stabilization = evidence.get("stabilization_result", {})
    aggregate = evidence.get("aggregate_result", {})

    default_workflow = workflow.split(
        "  rust-4-5-shadow-independent-default:", 1
    )[-1].split("  rust-4-5-mandatory-differential-shadow:", 1)[0]
    differential_workflow = workflow.split(
        "  rust-4-5-mandatory-differential-shadow:", 1
    )[-1].split("  rust-4-5-clean-install-platform:", 1)[0]

    exact_artifacts = bool(
        REQUIRED_ARTIFACTS <= artifact_by_name.keys()
        and len(artifacts) == len(artifact_by_name)
        and evidence.get("artifact_hashes", {}).get("manifest_entries")
        == len(artifacts)
    ) and all(
        row.get("source_run_id") == RUN_ID
        and row.get("source_revision") == REVISION
        and row.get("artifact_conclusion") == "success"
        and bool(row.get("platform"))
        and bool(row.get("decision_or_status"))
        and bool(row.get("gate"))
        and _is_sha256(row.get("artifact_zip_sha256"))
        and bool(row.get("files"))
        and all(
            bool(item.get("path")) and _is_sha256(item.get("sha256"))
            for item in row["files"]
        )
        for row in artifact_by_name.values()
    )
    clean_platforms = bool(platform_by_name.keys() == REQUIRED_PLATFORMS) and all(
        row.get("revision") == REVISION
        and row.get("status") == "PASS"
        and row.get("default_mode") == DEFAULT_MODE
        and row.get("shadow") == "not_executed_by_default"
        and row.get("python_shadow_executions_in_default") == 0
        and row.get("canonical_comparisons_in_default") == 0
        for row in platform_by_name.values()
    )
    jobs_green = REQUIRED_JOBS <= jobs.keys() and all(
        jobs[name] == "success" for name in REQUIRED_JOBS
    )
    default_pass = bool(
        default.get("mode") == DEFAULT_MODE
        and default.get("job_conclusion") == "success"
        and default.get("job_environment_override") is False
        and default.get("python_shadow_executed") is False
        and default.get("canonical_comparison_executed") is False
        and default.get("imported_ssa_verification_executed") is True
        and default.get("independent_refinement_verification_executed") is True
        and default.get("final_generic_verification_executed") is True
        and default.get("production_ordering") == EXPECTED_ORDERING
        and default.get("focused_policy_tests", {}).get("passed") == 42
        and default.get("focused_policy_tests", {}).get("failed") == 0
        and default.get("full_repository_suite", {}).get("passed") == 5020
        and default.get("full_repository_suite", {}).get("failed") == 0
    )
    differential_functional_pass = bool(
        differential.get("mode") == DIFFERENTIAL_MODE
        and differential.get("environment_override")
        == "AETHER_SSA_AUTHORITY_MODE=rust_ssa_authority_python_shadow"
        and differential.get("job_conclusion") == "success"
        and differential.get("python_general_ssa_builder_executed") is True
        and differential.get("canonical_comparison_executed") is True
        and differential.get("canonical_mismatch_fail_closed") is True
        and differential.get("refinement_failure_fail_closed") is True
        and differential.get("focused_differential_tests", {}).get("passed") == 2
    )
    # A green upload job is not a qualified RUST-4.5 artifact. Promotion requires
    # the artifact's own recomputed decision and focused policy result to pass.
    differential_artifact_qualified = bool(
        differential.get("artifact_decision") == PROMOTED
        and differential.get("artifact_focused_policy_tests", {}).get("status")
        == "PASS"
        and differential.get("artifact_focused_policy_tests", {}).get("returncode")
        == 0
        and differential.get("artifact_observed_new_default") == DEFAULT_MODE
    )
    semantic_pass = bool(
        historical
        == {
            "decision": "RUST_SSA_AUTHORITY_HISTORICAL_PASS",
            "passed": 116,
            "failed": 0,
            "denominator": 116,
        }
        and mutations.get("total") == 58
        and mutations.get("unique_ids") == 58
        and mutations.get("rejected_by_both") == 58
        and mutations.get("production_shadow_dependencies") == 0
        and mutations.get("invalid_accepted_by_both") == 0
        and deep.get("status") == "PASS"
        and deep.get("blocks") == [993, 1000, 5000, 10000]
        and deep.get("authoritative_ssa_equal") is True
    )
    soak_pass = bool(
        soak.get("status") == "PASS"
        and soak.get("differential_requests_passed") == 64
        and soak.get("differential_requests") == 64
        and soak.get("authority_soak_decision")
        == "RUST_SSA_AUTHORITY_SOAK_PASS"
        and soak.get("semantic_mismatches") == 0
    )
    full_suite_pass = bool(
        full_suite.get("production_default_job", {}).get("passed") == 5020
        and full_suite.get("production_default_job", {}).get("failed") == 0
        and full_suite.get("historical_differential_artifact", {}).get("passed")
        == 5020
        and full_suite.get("historical_differential_artifact", {}).get("failed")
        == 0
    )
    rollback_pass = bool(
        evidence.get("rollback_modes")
        == {
            "rust_authority_python_differential_shadow": "PASS",
            "python_authority_rust_shadow": "PASS",
            "python_only": "PASS",
        }
    )
    stabilization_pass = bool(
        stabilization.get("decision") == "RUST_SSA_PRODUCTION_STABILIZED"
        and stabilization.get("qualification_revision") == REVISION
        and stabilization.get("blockers") == []
        and stabilization.get("all_17_gates_passed") is True
        and set(stabilization.get("platforms", [])) == REQUIRED_PLATFORMS
    )
    aggregate_pass = bool(
        aggregate.get("authority_decision") == "RUST_SSA_AUTHORITY_PROMOTED_V2"
        and aggregate.get("stabilization_decision")
        == "RUST_SSA_PRODUCTION_STABILIZED"
        and aggregate.get("qualification_revision") == REVISION
    )

    eligibility_checks = {
        "four_clean_installs": clean_platforms,
        "default_no_python_shadow": default_pass,
        "differential_mode_functional": differential_functional_pass,
        "differential_artifact_qualified": differential_artifact_qualified,
        "historical_mutation_deep_cfg": semantic_pass,
        "authority_soak": soak_pass,
        "rollback_modes": rollback_pass,
        "full_default_suite": full_suite_pass,
        "stabilization": stabilization_pass,
        "aggregate_exact_revision": aggregate_pass,
        "required_jobs_green": jobs_green,
        "required_artifacts_exact_revision": exact_artifacts,
        "no_relevant_skips": evidence.get("relevant_skipped_jobs") == [],
    }
    promotion_eligible = all(eligibility_checks.values())
    expected_decision = PROMOTED if promotion_eligible else BLOCKED

    recorded_eligibility = evidence.get("promotion_eligibility", {})
    integrity_checks = {
        "identity": evidence.get("artifact_schema_version") == 1
        and evidence.get("milestone") == "RUST-4.5"
        and evidence.get("closure_revision") == REVISION
        and evidence.get("exact_revision") == REVISION
        and evidence.get("source_run_id") == RUN_ID
        and evidence.get("source_run_conclusion") == "success",
        "prior_decision_preserved": evidence.get("prior_decision")
        == PRIOR_DECISION,
        "job_evidence": jobs_green,
        "artifact_manifest": exact_artifacts,
        "platform_truth": clean_platforms,
        "default_evidence": default_pass,
        "differential_functional_evidence": differential_functional_pass,
        "semantic_evidence": semantic_pass,
        "soak_evidence": soak_pass,
        "full_suite_evidence": full_suite_pass,
        "rollback_evidence": rollback_pass,
        "stabilization_evidence": stabilization_pass,
        "aggregate_evidence": aggregate_pass,
        "decision_recomputes": evidence.get("final_decision")
        == expected_decision,
        "eligibility_recomputes": recorded_eligibility.get("eligible")
        is promotion_eligible
        and recorded_eligibility.get("checks") == eligibility_checks
        and (
            promotion_eligible
            or bool(recorded_eligibility.get("blockers"))
        ),
        "production_freeze": evidence.get("production_code_changed") is False
        and evidence.get("python_ssa_retained") is True
        and evidence.get("differential_ci_retained") is True,
        "workflow_permanence": (
            "AETHER_SSA_AUTHORITY_MODE" not in default_workflow
            and "AETHER_SSA_AUTHORITY_MODE: rust_ssa_authority_python_shadow"
            in differential_workflow
            and "rust-4.5-differential-shadow" in differential_workflow
        ),
        "report": report.startswith(
            "# RUST-4.5 — shadow-independent production promotion closure"
        )
        and str(evidence.get("final_decision")) in report
        and "does not formally prove" in report,
    }
    return {
        "milestone": "RUST-4.5",
        "passed": all(integrity_checks.values()),
        "decision": evidence.get("final_decision"),
        "expected_decision": expected_decision,
        "promotion_eligible": promotion_eligible,
        "eligibility_checks": eligibility_checks,
        "checks": integrity_checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--workflow", type=Path, default=WORKFLOW)
    parser.add_argument("--require-promoted", action="store_true")
    args = parser.parse_args()
    record = build_record(args.evidence, args.report, args.workflow)
    print(f"RUST-4.5 closure: {record['decision']}")
    for name, passed in record["checks"].items():
        print(f"  {'PASS' if passed else 'FAIL'} {name}")
    for name, passed in record["eligibility_checks"].items():
        print(f"  {'PASS' if passed else 'BLOCK'} gate:{name}")
    if not record["passed"]:
        return 1
    if args.require_promoted and not record["promotion_eligible"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
