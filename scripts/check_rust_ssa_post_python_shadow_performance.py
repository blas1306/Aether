#!/usr/bin/env python3
"""Check permanent structural RUST-3.12 characterization contracts."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVISION = "ec4cfea41b5ae49b0038b63d39cadaf0715d6494"
DEFAULT_EVIDENCE = (
    ROOT
    / "docs/compiler/rust_ssa_post_python_shadow_performance_characterization.json"
)
DEFAULT_REPORT = (
    ROOT / "docs/compiler/RUST_SSA_POST_PYTHON_SHADOW_PERFORMANCE_CHARACTERIZATION.md"
)
ROUTES = {
    "python_only",
    "diagnostic_rust_only",
    "rust_authority_mandatory_python_shadow",
}
CATEGORIES = {
    "RUST_INTRINSIC",
    "PYTHON_SHADOW",
    "SAFETY_VERIFICATION",
    "TRANSPORT_REPRESENTATION",
    "COMPARISON",
    "ORCHESTRATION_RESIDUAL",
}
RUST_COMPONENTS = {
    "cfg_construction",
    "reachability_and_rpo",
    "chk_idom",
    "dominator_tree",
    "dominance_frontier",
    "liveness",
    "definite_initialization",
    "phi_placement",
    "renaming",
    "remaining_lowering",
}
PYTHON_COMPONENTS = {
    "python_lifecycle_normalization",
    "python_cfg_construction",
    "python_cfg_indexing",
    "python_reachability",
    "python_dominator_computation",
    "python_immediate_dominator_derivation",
    "python_dominator_tree",
    "python_dominance_frontiers",
    "python_definition_collection",
    "python_liveness",
    "python_definite_initialization",
    "python_phi_placement",
    "python_renaming",
    "python_result_assembly",
    "python_builder_verification",
}
CANDIDATES = {
    "Python lifecycle normalization",
    "Python lifecycle verification",
    "Python renaming",
    "schema-v2 import",
    "imported Rust SSA verification",
    "canonical comparison",
    "DTO/serialization/transport",
    "remaining Python shadow lowering",
    "remaining Rust SSA lowering",
    "dual-lane architecture/policy",
}
CLASSIFICATIONS = {
    "LOW_RISK_IMPLEMENTATION",
    "LOW_RISK_ARCHITECTURAL",
    "SAFETY_BOUNDARY",
    "SHADOW_POLICY",
    "ALGORITHMIC_CORE",
    "NOT_CURRENT_BOTTLENECK",
}


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def _summary_valid(summary: object, expected_count: int) -> bool:
    if not isinstance(summary, dict):
        return False
    required = {
        "sample_count",
        "median_seconds",
        "min_seconds",
        "max_seconds",
        "total_wall_seconds",
    }
    return (
        required <= set(summary)
        and summary["sample_count"] == expected_count
        and all(_number(summary[name]) for name in required - {"sample_count"})
        and summary["min_seconds"] <= summary["median_seconds"] <= summary["max_seconds"]
    )


def _summary_matches(summary: object, profiles: list[object]) -> bool:
    if not _summary_valid(summary, len(profiles)) or not isinstance(summary, dict):
        return False
    values = [float(profile["total_wall_seconds"]) for profile in profiles if isinstance(profile, dict)]
    if len(values) != len(profiles):
        return False
    expected = {
        "min_seconds": min(values),
        "max_seconds": max(values),
        "total_wall_seconds": sum(values),
        "median_seconds": sorted(values)[len(values) // 2]
        if len(values) % 2
        else (sorted(values)[len(values) // 2 - 1] + sorted(values)[len(values) // 2]) / 2,
    }
    return all(
        abs(float(summary[name]) - value) <= max(1e-9, value * 1e-9)
        for name, value in expected.items()
    )


def _profile_valid(profile: object, route: str) -> bool:
    if not isinstance(profile, dict):
        return False
    phases = profile.get("phases_seconds")
    rust = profile.get("rust_ssa_lowering_phases_seconds")
    python = profile.get("python_ssa_lowering_phases_seconds")
    total = profile.get("total_wall_seconds")
    measured = profile.get("measured_component_sum_seconds")
    residual = profile.get("residual_unattributed_seconds")
    if not (
        isinstance(phases, dict)
        and isinstance(rust, dict)
        and isinstance(python, dict)
        and all(_number(value) for value in phases.values())
        and all(_number(value) for value in rust.values())
        and all(_number(value) for value in python.values())
        and _number(total)
        and _number(measured)
        and _number(residual)
    ):
        return False
    tolerance = max(1e-9, float(total) * 1e-8)
    if abs(sum(phases.values()) - float(measured)) > tolerance:
        return False
    if abs(float(measured) + float(residual) - float(total)) > tolerance:
        return False
    if route == "python_only":
        return not rust and set(python) == PYTHON_COMPONENTS
    if set(rust) != RUST_COMPONENTS:
        return False
    if route == "diagnostic_rust_only":
        return not python
    return set(python) == PYTHON_COMPONENTS


def _workloads_valid(evidence: Mapping[str, object]) -> bool:
    methodology = evidence.get("methodology")
    workloads = evidence.get("ordinary_workloads")
    if not isinstance(methodology, dict) or not isinstance(workloads, list):
        return False
    rounds = methodology.get("ordinary_measured_rounds")
    if not isinstance(rounds, int) or rounds < 15 or len(workloads) < 7:
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
            if not all(_profile_valid(profile, route) for profile in rows):
                return False
            if not _summary_matches(summaries.get(route), rows):
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
    if not {100, 1000, 5000, 10000} <= set(indexed):
        return False
    for size in (100, 1000, 5000, 10000):
        routes = indexed[size].get("routes")
        if not isinstance(routes, dict) or set(routes) != ROUTES:
            return False
        for route in ROUTES:
            route_row = routes[route]
            if not isinstance(route_row, dict) or route_row.get("status") != "MEASURED":
                return False
            raw = route_row.get("raw_samples")
            if not isinstance(raw, list) or len(raw) != rounds:
                return False
            if not all(_profile_valid(profile, route) for profile in raw):
                return False
            if not _summary_matches(route_row.get("summary"), raw):
                return False
    return True


def _category_valid(model: object) -> bool:
    if not isinstance(model, dict):
        return False
    categories = model.get("categories")
    observed = model.get("total_observed_seconds")
    accounted = model.get("accounted_seconds")
    reconciled = model.get("reconciled_percent")
    percent_sum = model.get("percent_sum")
    if not (
        isinstance(categories, dict)
        and set(categories) == CATEGORIES
        and _number(observed)
        and _number(accounted)
        and _number(reconciled)
        and _number(percent_sum)
    ):
        return False
    if abs(float(accounted) - float(observed)) > max(1e-8, float(observed) * 1e-8):
        return False
    if abs(float(reconciled) - 100.0) > 1e-6 or abs(float(percent_sum) - 100.0) > 1e-6:
        return False
    return all(
        _number(row.get("observed_seconds"))
        and _number(row.get("percent_of_dual_lane"))
        and isinstance(row.get("constituent_seconds"), dict)
        for row in categories.values()
        if isinstance(row, dict)
    ) and all(isinstance(row, dict) for row in categories.values())


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    methodology = evidence.get("methodology", {})
    manifest = evidence.get("workload_manifest", [])
    deep = evidence.get("deep_cfg", [])
    startup = evidence.get("startup_and_persistence", {})
    memory = evidence.get("memory_rss", {})
    candidates = evidence.get("candidate_ranking", [])
    production = evidence.get("production_invariants", {})
    regressions = evidence.get("regression_contracts", {})
    qualification = evidence.get("qualification", {})
    checks = {
        "milestone_and_decision": evidence.get("milestone") == "RUST-3.12"
        and evidence.get("decision")
        == "RUST_SSA_POST_PYTHON_SHADOW_PERFORMANCE_CHARACTERIZED",
        "exact_revision": evidence.get("qualification_revision") == BASELINE_REVISION,
        "observational_no_speed_thresholds": evidence.get("measurement_kind")
        == "observational_only_no_hardware_dependent_thresholds"
        and methodology.get("observational") is True
        and methodology.get("absolute_speed_thresholds") is False,
        "warmups_rounds_raw_samples": methodology.get("warmups", 0) >= 2
        and methodology.get("raw_samples_retained") is True
        and _workloads_valid(evidence),
        "three_routes": set(evidence.get("routes", [])) == ROUTES,
        "representative_ordinary_corpus": len(manifest) >= 7
        and {
            row.get("category") for row in manifest if isinstance(row, dict)
        }
        >= {
            "numeric iterative",
            "collection-heavy",
            "struct-heavy",
            "class/interface-heavy",
            "function-value/indirect-call",
            "exception/lifecycle-heavy",
        },
        "deep_cfg_all_routes": _deep_valid(evidence),
        "ordinary_additive_reconciliation": _category_valid(
            evidence.get("ordinary_dual_lane_categories")
        ),
        "deep_additive_reconciliation": isinstance(deep, list)
        and all(
            isinstance(row, dict) and _category_valid(row.get("dual_lane_categories"))
            for row in deep
        ),
        "explicit_residual": "ORCHESTRATION_RESIDUAL"
        in evidence.get("ordinary_dual_lane_categories", {}).get("categories", {})
        and all(
            _number(profile.get("residual_unattributed_seconds"))
            for workload in evidence.get("ordinary_workloads", [])
            for rows in workload.get("samples", {}).values()
            for profile in rows
        ),
        "startup_persistence": startup.get("persistent") is True
        and startup.get("process_start_count") == 1
        and startup.get("request_count", 0) > 1
        and _number(startup.get("startup_seconds"))
        and _number(startup.get("first_request_total_seconds"))
        and startup.get("startup_included_in_steady_per_request") is False,
        "rss_reproducible": memory.get("status") == "MEASURED"
        and len(memory.get("measurements", [])) >= 4
        and all(
            set(row.get("routes", {})) == ROUTES
            and all(
                _number(route.get("parent_peak_rss_kib"))
                and _number(route.get("companion_peak_rss_kib"))
                and _number(route.get("process_family_conservative_sum_kib"))
                for route in row.get("routes", {}).values()
            )
            for row in memory.get("measurements", [])
        ),
        "historical_3_10_3_11": {
            row.get("milestone") for row in evidence.get("historical_comparison", [])
        }
        == {"RUST-3.10", "RUST-3.11"}
        and all(
            "MACHINE_SENSITIVE" in row.get("compatibility", "")
            for row in evidence.get("historical_comparison", [])
        ),
        "candidate_inventory_and_classification": {
            row.get("candidate") for row in candidates
        }
        == CANDIDATES
        and sorted(row.get("rank") for row in candidates) == list(range(1, 11))
        and all(row.get("classification") in CLASSIFICATIONS for row in candidates)
        and any(row.get("recommendation") == "NEXT_DIAGNOSTIC_MILESTONE" for row in candidates),
        "evidence_based_answer": isinstance(evidence.get("measured_answer", {}).get("central_question"), str)
        and _number(evidence.get("measured_answer", {}).get("deliberate_safety_policy_percent_ordinary"))
        and _number(evidence.get("measured_answer", {}).get("implementation_candidate_percent_ordinary"))
        and _number(evidence.get("measured_answer", {}).get("inherent_rust_ssa_percent_ordinary"))
        and abs(
            evidence.get("measured_answer", {}).get("deliberate_safety_policy_percent_ordinary", 0)
            + evidence.get("measured_answer", {}).get("implementation_candidate_percent_ordinary", 0)
            + evidence.get("measured_answer", {}).get("inherent_rust_ssa_percent_ordinary", 0)
            - 100.0
        )
        <= 1e-6
        and abs(
            evidence.get("measured_answer", {}).get("deliberate_safety_policy_percent_deep_10000", 0)
            + evidence.get("measured_answer", {}).get("implementation_candidate_percent_deep_10000", 0)
            + evidence.get("measured_answer", {}).get("inherent_rust_ssa_percent_deep_10000", 0)
            - 100.0
        )
        <= 1e-6
        and evidence.get("measured_answer", {}).get("recommended_next_milestone")
        == "Python lifecycle normalization audit and qualification",
        "production_frozen": production
        == {
            "authority": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "python_shadow": "mandatory_synchronous",
            "failure_policy": "FAIL_CLOSED",
            "schemas": {"initial_ir": 1, "protocol": 1, "ssa": 2},
            "canonicalization_changed": False,
            "comparison_rules_changed": False,
            "verifiers_changed": False,
            "optimizer_backend_changed": False,
            "lifecycle_phi_renaming_changed": False,
            "dominator_algorithms_changed": False,
            "rollback_modes_changed": False,
            "production_optimization_implemented": False,
            "ordinary_instrumentation_fields": False,
        },
        "regression_contracts": len(regressions) == 10
        and all(value == "PASS" for value in regressions.values()),
        "qualification_gates": qualification.get("new_checker") == "PASS"
        and qualification.get("focused_tests") == "PASS"
        and qualification.get("historical_116_of_116") == "PASS"
        and qualification.get("adversarial_ssa") == "PASS"
        and qualification.get("deep_cfg_993_1000_5000_10000") == "PASS"
        and qualification.get("production_stabilization_regressions") == "PASS"
        and qualification.get("contracts_rust_3_8a_through_3_11") == "PASS"
        and qualification.get("cargo_test_workspace_locked") == "PASS"
        and qualification.get("full_python_suite", {}).get("status") == "PASS"
        and qualification.get("full_python_suite", {}).get("passed", 0) > 0
        and qualification.get("full_python_suite", {}).get("updated_after_gate") is True
        and qualification.get("cargo_fmt_check") == "PASS"
        and qualification.get("git_diff_check") == "PASS",
        "report_present": report_path.read_text(encoding="utf-8").startswith(
            "# Post-Python-shadow SSA performance characterization — RUST-3.12"
        )
        and "Production behavior did not change." in report_path.read_text(encoding="utf-8"),
    }
    passed = all(checks.values())
    return {
        "milestone": "RUST-3.12",
        "decision": (
            "RUST_SSA_POST_PYTHON_SHADOW_PERFORMANCE_CHARACTERIZED"
            if passed
            else "RUST_SSA_POST_PYTHON_SHADOW_PERFORMANCE_BLOCKED"
        ),
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
    return int(
        args.require_characterized
        and record["decision"]
        != "RUST_SSA_POST_PYTHON_SHADOW_PERFORMANCE_CHARACTERIZED"
    )


if __name__ == "__main__":
    raise SystemExit(main())
