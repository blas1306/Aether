#!/usr/bin/env python3
"""Validate the permanent evidence and source contracts for RUST-3.15."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ssa_transport_representation_reaudit.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_TRANSPORT_REPRESENTATION_REAUDIT.md"
BASELINE_REVISION = "7500d66a0d830542d2436b22356e0c34698f076f"
DECISIONS = {
    "RUST_SSA_TRANSPORT_REPRESENTATION_REAUDITED_OPTIMIZATION_JUSTIFIED",
    "RUST_SSA_TRANSPORT_REPRESENTATION_REAUDITED_NO_MATERIAL_SAFE_OPTIMIZATION",
    "RUST_SSA_TRANSPORT_REPRESENTATION_REAUDIT_BLOCKED",
}
CLASSIFICATIONS = {
    "PROVEN_REDUNDANT_REPRESENTATION", "PROVEN_REDUNDANT_TRAVERSAL",
    "SAFE_IMMUTABLE_REUSE", "PROTOCOL_INHERENT", "SAFETY_BOUNDARY",
    "CANONICAL_COMPARISON_REQUIRED", "SHADOW_POLICY",
    "INSUFFICIENT_EVIDENCE", "NOT_MATERIAL",
}
FLOW_FIELDS = {
    "source", "destination", "full_traversal", "allocation", "deep_copy",
    "json_encode_decode", "validation", "trust_boundary", "consumer",
    "used_more_than_once", "equivalent_already_materialized", "mutates_source",
    "classification",
}
DEEP_SIZES = {100, 1000, 5000, 10000}
PHASE_CLASSIFICATIONS = {
    "python_result_dto_serialization", "initial_ir_snapshot_preparation",
    "response_json_decode", "rust_input_parsing", "rust_transport_serialization",
    "request_response_transport_and_serialization", "rust_schema_v2_materialization",
    "companion_process_startup", "rust_schema_v2_import",
}
CANDIDATES = {
    "remaining representation redundancy", "schema-v2 importer internal efficiency",
    "Python shadow DTO creation", "canonicalization", "JSON protocol itself",
    "verifier architecture", "policy/shadow evolution",
}


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def _summary_valid(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    samples = value.get("raw_samples_seconds")
    if not isinstance(samples, list) or not samples or not all(_number(item) for item in samples):
        return False
    return (
        value.get("sample_count") == len(samples)
        and value.get("median_seconds") == statistics.median(samples)
        and value.get("min_seconds") == min(samples)
        and value.get("max_seconds") == max(samples)
    )


def _workloads_valid(evidence: dict[str, object]) -> bool:
    method = evidence.get("methodology")
    rows = evidence.get("ordinary_workloads")
    if not isinstance(method, dict) or not isinstance(rows, list) or len(rows) != 8:
        return False
    rounds = method.get("ordinary_measured_rounds")
    if not isinstance(rounds, int) or rounds < 15:
        return False
    for row in rows:
        if not isinstance(row, dict) or not _summary_valid(row.get("wall_summary")):
            return False
        samples = row.get("samples")
        volume = row.get("shape_and_volume")
        if not isinstance(samples, list) or len(samples) != rounds or not isinstance(volume, dict):
            return False
        if not all(
            _number(sample.get("observed_wall_seconds"))
            and _number(sample.get("accounted_seconds"))
            and _number(sample.get("residual_seconds"))
            and 99.999 <= float(sample.get("reconciled_percent", 0)) <= 100.001
            and isinstance(sample.get("additive_phases_seconds"), dict)
            for sample in samples if isinstance(sample, dict)
        ) or len([sample for sample in samples if isinstance(sample, dict)]) != rounds:
            return False
        required_volume = {
            "functions", "blocks", "instructions", "distinct_ir_values",
            "request_json_bytes", "response_json_bytes", "request_raw_tree",
            "response_raw_tree", "approximate_dataclass_objects",
            "imported_ssa_approximate_dataclass_objects",
        }
        if not required_volume <= set(volume):
            return False
    return True


def _deep_valid(evidence: dict[str, object]) -> bool:
    method = evidence.get("methodology")
    rows = evidence.get("deep_cfg")
    if not isinstance(method, dict) or not isinstance(rows, list):
        return False
    rounds = method.get("deep_cfg_measured_rounds")
    indexed = {row.get("blocks"): row for row in rows if isinstance(row, dict)}
    if not isinstance(rounds, int) or rounds < 7 or not DEEP_SIZES <= set(indexed):
        return False
    return all(
        isinstance(indexed[size].get("samples"), list)
        and len(indexed[size]["samples"]) == rounds
        and _summary_valid(indexed[size].get("wall_summary"))
        and _summary_valid(indexed[size].get("transport_representation_summary"))
        and indexed[size].get("shape_and_volume", {}).get("blocks") == size
        for size in DEEP_SIZES
    )


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    baseline = evidence.get("baseline", {})
    answer = evidence.get("answer", {})
    flow = evidence.get("representation_flow", [])
    candidates = evidence.get("candidate_ranking", [])
    audited_candidates = evidence.get("candidate_audit", [])
    import_rows = evidence.get("schema_v2_import_decomposition", [])
    historical = evidence.get("historical_removed_work_regression", {})
    production = evidence.get("production_invariants", {})
    qualification = evidence.get("qualification", {})
    shadow = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    companion = (
        ROOT / "compiler-rs/crates/aether-verifier/src/bin/aether-ssa-shadow.rs"
    ).read_text(encoding="utf-8")

    headline = sum(
        float(answer.get(key, -1))
        for key in (
            "proven_redundant_percent_of_dual_lane",
            "protocol_inherent_percent_of_dual_lane",
            "safety_associated_percent_of_dual_lane",
            "uncertain_percent_of_dual_lane",
        )
    )
    checks = {
        "milestone_baseline_decision": evidence.get("milestone") == "RUST-3.15"
        and evidence.get("baseline_milestone") == "RUST-3.14"
        and evidence.get("baseline_revision") == BASELINE_REVISION
        and evidence.get("decision") in DECISIONS
        and evidence.get("decision")
        == "RUST_SSA_TRANSPORT_REPRESENTATION_REAUDITED_NO_MATERIAL_SAFE_OPTIMIZATION",
        "observational_release_method": evidence.get("measurement_kind")
        == "observational_only_no_hardware_dependent_thresholds"
        and evidence.get("environment", {}).get("build_mode") == "release"
        and evidence.get("methodology", {}).get("warmups", 0) >= 2
        and evidence.get("methodology", {}).get("raw_samples_retained") is True
        and evidence.get("methodology", {}).get("absolute_speed_thresholds") is False
        and evidence.get("methodology", {}).get("no_invasive_production_instrumentation") is True,
        "baseline_17_60_and_schema_separate": _number(baseline.get("implementation_surface_percent_excluding_schema_import"))
        and abs(float(baseline.get("implementation_surface_percent_excluding_schema_import")) - 17.600340538800534) < 1e-9
        and abs(float(baseline.get("schema_v2_import_percent")) - 14.826150662275102) < 1e-9
        and set(baseline.get("phases", {})) == PHASE_CLASSIFICATIONS,
        "exclusive_answer_reconciles": all(
            _number(answer.get(key))
            for key in (
                "proven_redundant_percent_of_dual_lane",
                "protocol_inherent_percent_of_dual_lane",
                "safety_associated_percent_of_dual_lane",
                "uncertain_percent_of_dual_lane",
                "maximum_plausible_low_risk_speedup_percent",
            )
        )
        and abs(headline - float(answer.get("surface_percent_of_dual_lane"))) < 1e-9
        and answer.get("proven_redundant_percent_of_dual_lane") == 0.0,
        "complete_exclusive_flow_map": isinstance(flow, list) and len(flow) >= 18
        and all(isinstance(row, dict) and set(row) == FLOW_FIELDS for row in flow)
        and all(row.get("classification") in CLASSIFICATIONS for row in flow)
        and evidence.get("traversal_census", {}).get("ordinary_full_tree_transitions")
        == sum(bool(row.get("full_traversal")) for row in flow),
        "explicit_candidate_audit": isinstance(audited_candidates, list)
        and len(audited_candidates) >= 12
        and all(
            isinstance(row, dict)
            and set(row) == {"candidate", "classification", "finding"}
            and row.get("classification") in CLASSIFICATIONS
            for row in audited_candidates
        )
        and {
            "PROVEN_REDUNDANT_REPRESENTATION", "PROVEN_REDUNDANT_TRAVERSAL",
            "SAFE_IMMUTABLE_REUSE", "PROTOCOL_INHERENT", "SAFETY_BOUNDARY",
            "CANONICAL_COMPARISON_REQUIRED", "INSUFFICIENT_EVIDENCE", "NOT_MATERIAL",
        } <= {row.get("classification") for row in audited_candidates if isinstance(row, dict)},
        "ordinary_raw_samples_and_census": _workloads_valid(evidence),
        "deep_100_1000_5000_10000": _deep_valid(evidence),
        "scaling_against_all_volume_proxies": evidence.get("scaling_analysis", {}).get("formal_complexity_claimed") is False
        and {row.get("metric") for row in evidence.get("scaling_analysis", {}).get("metric_comparisons_best_ratio_first", []) if isinstance(row, dict)}
        == {"request_bytes", "response_bytes", "instructions", "blocks", "values"}
        and _number(evidence.get("scaling_analysis", {}).get("transport_time_endpoint_growth_100_to_10000")),
        "schema_import_decomposed": isinstance(import_rows, list) and len(import_rows) == 12
        and {row.get("workload") for row in import_rows if isinstance(row, dict)}
        >= {"deep_100", "deep_1000", "deep_5000", "deep_10000"}
        and all(
            isinstance(row.get("profile"), dict)
            and set(row["profile"].get("buckets", {})) == {
                "raw_structure_and_validation", "type_and_nominal_reconstruction",
                "python_object_and_container_allocation", "metadata_reconstruction",
                "unattributed_profiler_self_time",
            }
            and abs(sum(
                bucket.get("percent_of_profiled_self_time", -100)
                for bucket in row["profile"]["buckets"].values()
            ) - 100.0) < 1e-6
            for row in import_rows if isinstance(row, dict)
        ),
        "candidate_ranking_complete": isinstance(candidates, list)
        and {row.get("candidate") for row in candidates if isinstance(row, dict)} == CANDIDATES
        and sorted(row.get("rank") for row in candidates) == list(range(1, 8))
        and all(row.get("classification") in CLASSIFICATIONS for row in candidates),
        "historical_removed_work_stays_absent": len(historical) == 5
        and all(value is True for value in historical.values())
        and "json.loads(json.dumps" not in shadow
        and "serde_json::to_value(owned.to_schema_v2())" not in companion
        and "ssa: aether_ir::wire::SSAModuleV2DTO" in companion
        and "python_input = module" in shadow
        and "rust_dto = rust_comparison_dto" in shadow,
        "mandatory_shadow_fail_closed_import_and_comparison": "value = ssa_module_from_dto(rust_comparison_dto)" in shadow
        and "SSAVerifier(value).verify()" in shadow
        and "python_ssa = run_python()" in shadow
        and "difference = _difference(python_canonical, rust_canonical)" in shadow,
        "production_frozen": production == {
            "authority": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "python_shadow": "MANDATORY_SYNCHRONOUS_INDEPENDENT",
            "fail_closed": True, "schemas_changed": False,
            "protocol_v1_changed": False, "schema_v2_semantics_changed": False,
            "schema_import_validation_changed": False, "lifecycle_changed": False,
            "dominators_or_ssa_changed": False, "verifiers_changed": False,
            "canonical_comparison_changed": False, "optimizer_backend_changed": False,
            "rollback_modes_changed": False, "production_files_changed_by_milestone": False,
            "optimization_implemented": False,
        },
        "persistent_companion": evidence.get("startup_and_persistence", {}).get("persistent") is True
        and evidence.get("startup_and_persistence", {}).get("process_start_count") == 1
        and evidence.get("startup_and_persistence", {}).get("request_count", 0) > 1,
        "regression_contracts": len(evidence.get("regression_contracts", {})) == 8
        and all(value == "PASS" for value in evidence.get("regression_contracts", {}).values()),
        "qualification_gates": isinstance(qualification, dict) and len(qualification) == 11
        and all(value == "PASS" for value in qualification.values()),
        "report_complete": report.startswith("# Transport and representation reaudit — RUST-3.15")
        and "Production unchanged: yes." in report
        and "No commit was created." in report
        and evidence.get("decision") in report,
    }
    passed = all(checks.values())
    return {
        "milestone": "RUST-3.15",
        "decision": evidence.get("decision") if passed else "RUST_SSA_TRANSPORT_REPRESENTATION_REAUDIT_BLOCKED",
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--require-reaudited", action="store_true")
    args = parser.parse_args()
    record = build_record(args.evidence, args.report)
    print(json.dumps(record, indent=2, sort_keys=True))
    return int(args.require_reaudited and record["decision"] == "RUST_SSA_TRANSPORT_REPRESENTATION_REAUDIT_BLOCKED")


if __name__ == "__main__":
    raise SystemExit(main())
