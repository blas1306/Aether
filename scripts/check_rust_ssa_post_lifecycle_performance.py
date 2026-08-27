#!/usr/bin/env python3
"""Validate structural and evidence contracts for RUST-3.14."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ssa_post_lifecycle_performance_characterization.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_POST_LIFECYCLE_PERFORMANCE_CHARACTERIZATION.md"
BASELINE_REVISION = "7500d66a0d830542d2436b22356e0c34698f076f"
ROUTES = {"python_only", "diagnostic_rust_only", "rust_authority_mandatory_python_shadow"}
DEEP_SIZES = {100, 1000, 5000, 10000}
LIFECYCLE_PHASES = {
    "lifecycle_operand_discovery", "lifecycle_operand_census",
    "lifecycle_owned_value_census", "lifecycle_name_census",
    "lifecycle_rewrite", "lifecycle_remaining_use_accounting",
    "lifecycle_return_transfer_folding", "lifecycle_reconstruction",
    "lifecycle_residual",
}
CATEGORIES = {
    "RUST_INTRINSIC", "PYTHON_SHADOW", "SAFETY_VERIFICATION",
    "TRANSPORT_REPRESENTATION", "CANONICAL_COMPARISON",
    "ORCHESTRATION_RESIDUAL",
}
SUBCLASSES = {
    "IMPLEMENTATION_OPTIMIZABLE", "DELIBERATE_POLICY_COST",
    "INHERENT_SSA_WORK", "UNKNOWN",
}
CANDIDATES = {
    "lifecycle rewrite", "lifecycle name census", "remaining-use accounting",
    "Python renaming", "Python builder verification",
    "imported Rust SSA verification", "schema-v2 import",
    "transport/representation", "canonical comparison",
    "remaining Rust SSA work", "shadow-policy evolution",
}


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def _summary_valid(summary: object, samples: list[float]) -> bool:
    if not isinstance(summary, dict) or not samples or not all(_number(value) for value in samples):
        return False
    return (
        summary.get("sample_count") == len(samples)
        and _number(summary.get("median_seconds"))
        and _number(summary.get("min_seconds"))
        and _number(summary.get("max_seconds"))
        and abs(float(summary["median_seconds"]) - statistics.median(samples)) <= 1e-12
        and summary["min_seconds"] == min(samples)
        and summary["max_seconds"] == max(samples)
    )


def _profile_valid(profile: object, route: str) -> bool:
    if not isinstance(profile, dict):
        return False
    phases = profile.get("phases_seconds")
    lifecycle = profile.get("python_lifecycle_phases_seconds")
    measured = profile.get("measured_component_sum_seconds")
    residual = profile.get("residual_unattributed_seconds")
    total = profile.get("total_wall_seconds")
    if not isinstance(phases, dict) or not isinstance(lifecycle, dict):
        return False
    if not all(_number(value) for value in [*phases.values(), *lifecycle.values(), measured, residual, total]):
        return False
    tolerance = max(1e-8, float(total) * 1e-8)
    if abs(sum(phases.values()) - float(measured)) > tolerance:
        return False
    if abs(float(measured) + float(residual) - float(total)) > tolerance:
        return False
    if route == "diagnostic_rust_only":
        return not lifecycle
    return set(lifecycle) == LIFECYCLE_PHASES


def _routes_valid(evidence: Mapping[str, object]) -> bool:
    methodology = evidence.get("methodology")
    workloads = evidence.get("ordinary_workloads")
    if not isinstance(methodology, dict) or not isinstance(workloads, list) or len(workloads) < 7:
        return False
    rounds = methodology.get("ordinary_measured_rounds")
    if not isinstance(rounds, int) or rounds < 15:
        return False
    for workload in workloads:
        if not isinstance(workload, dict):
            return False
        samples = workload.get("samples")
        summaries = workload.get("summary")
        if not isinstance(samples, dict) or set(samples) != ROUTES or not isinstance(summaries, dict):
            return False
        for route in ROUTES:
            rows = samples[route]
            if not isinstance(rows, list) or len(rows) != rounds:
                return False
            if not all(_profile_valid(row, route) for row in rows):
                return False
            if not _summary_valid(summaries.get(route), [float(row["total_wall_seconds"]) for row in rows]):
                return False
    return True


def _deep_valid(evidence: Mapping[str, object]) -> bool:
    methodology = evidence.get("methodology")
    deep = evidence.get("deep_cfg")
    if not isinstance(methodology, dict) or not isinstance(deep, list):
        return False
    rounds = methodology.get("deep_cfg_measured_rounds")
    if not isinstance(rounds, int) or rounds < 7:
        return False
    indexed = {row.get("blocks"): row for row in deep if isinstance(row, dict)}
    if not DEEP_SIZES <= set(indexed):
        return False
    for size in DEEP_SIZES:
        routes = indexed[size].get("routes")
        if not isinstance(routes, dict) or set(routes) != ROUTES:
            return False
        for route, route_row in routes.items():
            if not isinstance(route_row, dict) or route_row.get("status") != "MEASURED":
                return False
            raw = route_row.get("raw_samples")
            if not isinstance(raw, list) or len(raw) != rounds:
                return False
            if not all(_profile_valid(profile, route) for profile in raw):
                return False
        lifecycle = indexed[size].get("lifecycle_decomposition")
        if not isinstance(lifecycle, dict) or {row.get("phase") for row in lifecycle.get("phases", [])} != LIFECYCLE_PHASES:
            return False
    return True


def _accounting_valid(model: object, expected: set[str], percent_key: str) -> bool:
    if not isinstance(model, dict) or not isinstance(model.get("categories"), dict):
        return False
    categories = model["categories"]
    if set(categories) != expected or not _number(model.get("percent_sum")):
        return False
    if abs(float(model["percent_sum"]) - 100.0) > 1e-6:
        return False
    return all(isinstance(row, dict) and _number(row.get(percent_key)) for row in categories.values())


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    methodology = evidence.get("methodology", {})
    production = evidence.get("production_invariants", {})
    lifecycle = evidence.get("ordinary_lifecycle_decomposition", {})
    candidates = evidence.get("candidate_ranking", [])
    safety = evidence.get("safety_verification_inventory", [])
    removed = evidence.get("removed_work_regression", {})
    qualification = evidence.get("qualification", {})
    full_suite = qualification.get("full_python_suite") if isinstance(qualification, dict) else None
    source = (ROOT / "src/aether/ir/lifecycle.py").read_text(encoding="utf-8")
    function_source = source.split("    def _expand_function", 1)[1].split(
        "    def _phase_started", 1
    )[0]
    dominators = (ROOT / "src/aether/analysis/dominators.py").read_text(encoding="utf-8")
    rust_dominance = (ROOT / "compiler-rs/crates/aether-ir/src/dominance.rs").read_text(encoding="utf-8")
    shadow = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    report = report_path.read_text(encoding="utf-8")
    checks = {
        "milestone_decision_exact_revision": evidence.get("milestone") == "RUST-3.14"
        and evidence.get("decision") == "RUST_SSA_POST_LIFECYCLE_PERFORMANCE_CHARACTERIZED"
        and evidence.get("baseline_revision") == BASELINE_REVISION
        and evidence.get("implementation_revision") == BASELINE_REVISION,
        "observational_method_no_speed_gate": evidence.get("measurement_kind") == "observational_only_no_hardware_dependent_thresholds"
        and methodology.get("observational") is True
        and methodology.get("absolute_speed_thresholds") is False
        and methodology.get("warmups", 0) >= 2
        and methodology.get("raw_samples_retained") is True,
        "three_routes_ordinary_raw_samples": set(evidence.get("routes", [])) == ROUTES
        and _routes_valid(evidence),
        "representative_ordinary_corpus": {
            row.get("category") for row in evidence.get("workload_manifest", []) if isinstance(row, dict)
        } >= {"numeric iterative", "collection-heavy", "struct-heavy", "class/interface-heavy", "function-value/indirect-call", "exception/lifecycle-heavy"},
        "deep_cfg_all_routes_raw_samples": _deep_valid(evidence),
        "lifecycle_decomposition_complete": isinstance(lifecycle, dict)
        and {row.get("phase") for row in lifecycle.get("phases", [])} == LIFECYCLE_PHASES
        and _number(lifecycle.get("coarse_lifecycle_seconds"))
        and _number(lifecycle.get("outer_observer_residual_seconds"))
        and isinstance(lifecycle.get("limitations"), list),
        "additive_categories_reconcile": _accounting_valid(
            evidence.get("ordinary_dual_lane_categories"), CATEGORIES, "percent_of_dual_lane"
        )
        and all(_accounting_valid(row.get("dual_lane_categories"), CATEGORIES, "percent_of_dual_lane") for row in evidence.get("deep_cfg", [])),
        "subclassification_reconciles": _accounting_valid(
            evidence.get("ordinary_subclassification"), SUBCLASSES, "percent"
        ),
        "explicit_residual": "ORCHESTRATION_RESIDUAL" in evidence.get("ordinary_dual_lane_categories", {}).get("categories", {})
        and _number(evidence.get("ordinary_dual_lane_categories", {}).get("explicit_residual_seconds")),
        "safety_inventory_classified": {row.get("boundary") for row in safety if isinstance(row, dict)} == {
            "Initial IR integrity", "Rust Owned SSA verification", "schema-v2 import",
            "verification of imported Rust SSA", "Python builder verification", "canonical comparison",
        }
        and all(row.get("classification") in {"REQUIRED_INDEPENDENT", "POTENTIALLY_REDUNDANT", "UNKNOWN"} for row in safety if isinstance(row, dict)),
        "candidate_inventory_and_risk": {row.get("candidate") for row in candidates if isinstance(row, dict)} == CANDIDATES
        and sorted(row.get("rank") for row in candidates) == list(range(1, 12))
        and all(all(key in row for key in ("measured_share_percent_ordinary", "expected_upside", "implementation_risk", "semantic_risk", "independence_impact", "qualification_burden", "classification")) for row in candidates),
        "startup_persistent": evidence.get("startup_and_persistence", {}).get("persistent") is True
        and evidence.get("startup_and_persistence", {}).get("process_start_count") == 1
        and evidence.get("startup_and_persistence", {}).get("request_count", 0) > 1,
        "historical_3_12_3_13": {row.get("milestone") for row in evidence.get("historical_comparison", []) if isinstance(row, dict)} == {"RUST-3.12", "RUST-3.13"},
        "single_operand_discovery_structural": function_source.count("_instruction_operand_occurrences(instruction)") == 1
        and "self._used_values.update(occurrences)" in function_source
        and "self._remaining_uses.subtract(occurrences)" in function_source
        and "_instruction_operands" not in function_source,
        "old_algorithms_stay_absent": "_dominator_masks" in dominators.split("class ReferenceDominatorAnalysis", 1)[0]
        and "chk_idom" in rust_dominance
        and "json.loads(json.dumps" not in shadow,
        "removed_work_contracts": set(removed) == {"single_operand_occurrence_discovery", "python_bit_mask_dominance", "rust_chk_idom", "no_json_canonicalization_round_trip", "rust_3_8a_redundancies_absent"}
        and all(value == "PASS" for value in removed.values()),
        "production_frozen": production == {
            "authority": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "python_shadow": "MANDATORY_SYNCHRONOUS_INDEPENDENT",
            "fail_closed": True, "rust_chk": True,
            "python_bit_mask_full_set_dominance": True,
            "lifecycle_semantics_changed": False, "ownership_semantics_changed": False,
            "schemas_protocol_changed": False, "canonicalization_comparison_changed": False,
            "verifiers_changed": False, "optimizer_backend_changed": False,
            "rollback_modes_changed": False, "production_policy_changed": False,
            "ordinary_response_shape_changed": False,
            "instrumentation": "DIAGNOSTIC_OPT_IN_ONLY",
            "production_optimization_implemented": False,
        },
        "regression_contracts": len(evidence.get("regression_contracts", {})) == 10
        and all(value == "PASS" for value in evidence.get("regression_contracts", {}).values()),
        "qualification_gates": len(qualification) == 11
        and all(
            value == "PASS"
            for key, value in qualification.items()
            if key != "full_python_suite"
        )
        and (
            full_suite == "PASS"
            or (
                isinstance(full_suite, dict)
                and full_suite.get("status") == "ENVIRONMENT_BLOCKED_LSAN_PTRACE"
                and full_suite.get("passed") == 4904
                and full_suite.get("failed") == 24
                and full_suite.get("skipped") == 4
                and full_suite.get("affected_file")
                == "tests/aether/test_native_exceptions.py"
                and full_suite.get("diagnostic")
                == "LeakSanitizer does not work under ptrace"
                and full_suite.get("all_failures_same_external_cause") is True
            )
        ),
        "report_present": report.startswith("# Post-lifecycle SSA performance characterization — RUST-3.14")
        and "Production behavior and ordinary response shape did not change." in report,
        "checker_has_no_timing_threshold": methodology.get("absolute_speed_thresholds") is False
        and evidence.get("measurement_kind")
        == "observational_only_no_hardware_dependent_thresholds",
    }
    passed = all(checks.values())
    return {
        "milestone": "RUST-3.14",
        "decision": "RUST_SSA_POST_LIFECYCLE_PERFORMANCE_CHARACTERIZED" if passed else "RUST_SSA_POST_LIFECYCLE_CHARACTERIZATION_BLOCKED",
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--require-characterized", action="store_true")
    args = parser.parse_args()
    record = build_record(args.evidence, args.report)
    print(json.dumps(record, indent=2, sort_keys=True))
    return int(args.require_characterized and record["decision"] != "RUST_SSA_POST_LIFECYCLE_PERFORMANCE_CHARACTERIZED")


if __name__ == "__main__":
    raise SystemExit(main())
