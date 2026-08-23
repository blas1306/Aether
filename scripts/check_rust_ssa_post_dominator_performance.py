#!/usr/bin/env python3
"""Check permanent RUST-3.10 characterization evidence contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVISION = "96c72ec9e72ad395a657c6f9aed1be19b45c95eb"
DEFAULT_EVIDENCE = (
    ROOT / "docs/compiler/rust_ssa_post_dominator_performance_characterization.json"
)
DEFAULT_REPORT = (
    ROOT / "docs/compiler/RUST_SSA_POST_DOMINATOR_PERFORMANCE_CHARACTERIZATION.md"
)
ROUTES = {
    "python_ssa_only",
    "diagnostic_rust_only",
    "rust_authority_python_shadow",
}
CATEGORIES = {
    "RUST_INTRINSIC",
    "PYTHON_SHADOW",
    "SAFETY_VERIFICATION",
    "TRANSPORT_REPRESENTATION",
    "CANONICAL_COMPARISON",
    "ORCHESTRATION",
}
LOWERING_COMPONENTS = {
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
REMOVED = {
    "python_initial_ir_reconstruction",
    "duplicate_python_ssa_verification",
    "rust_result_reserialization",
    "json_encode_decode_canonicalization",
    "serde_json_value_response_materialization",
    "sorted_request_key_serialization",
    "production_full_dominator_sets",
}
CANDIDATES = {
    "remaining Rust SSA core work",
    "schema-v2 import efficiency",
    "verifier/safety-boundary redundancy",
    "canonical comparison",
    "remaining transport/representation",
    "Python shadow performance preserving independence",
    "shadow-policy evolution",
    "companion/session architecture",
    "backend/optimizer work outside SSA",
}


def _profiles_valid(evidence: dict[str, object]) -> bool:
    methodology = evidence.get("methodology", {})
    rounds = methodology.get("ordinary_measured_rounds")
    workloads = evidence.get("workloads")
    if not isinstance(rounds, int) or rounds < 7 or not isinstance(workloads, list):
        return False
    for workload in workloads:
        samples = workload.get("samples", {})
        if set(samples) != ROUTES:
            return False
        for route, rows in samples.items():
            if not isinstance(rows, list) or len(rows) != rounds:
                return False
            for row in rows:
                phases = row.get("phases_seconds")
                total = row.get("total_wall_seconds")
                measured = row.get("measured_component_sum_seconds")
                residual = row.get("residual_unattributed_seconds")
                if not (
                    isinstance(phases, dict)
                    and isinstance(total, (int, float))
                    and isinstance(measured, (int, float))
                    and isinstance(residual, (int, float))
                    and abs(sum(phases.values()) - measured) <= max(1e-9, measured * 1e-9)
                    and abs(measured + residual - total) <= max(1e-9, total * 1e-9)
                ):
                    return False
                lowering = row.get("rust_ssa_lowering_phases_seconds")
                if route == "python_ssa_only":
                    if lowering != {}:
                        return False
                elif not isinstance(lowering, dict) or set(lowering) != LOWERING_COMPONENTS:
                    return False
    return True


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    categories = evidence.get("dual_lane_additive_categories", {}).get("categories", {})
    deep = evidence.get("deep_cfg", [])
    removed = evidence.get("removed_work_regression", [])
    candidates = evidence.get("candidate_ranking", [])
    safety = evidence.get("safety_boundary_analysis", [])
    copies = evidence.get("representation_copy_census", [])
    session = evidence.get("startup_session", {})
    production = evidence.get("production_invariants", {})
    lowering = evidence.get("rust_ssa_lowering_decomposition", {})
    qualification = evidence.get("qualification", {})
    checks = {
        "decision": evidence.get("decision")
        == "RUST_SSA_POST_DOMINATOR_PERFORMANCE_CHARACTERIZED",
        "exact_baseline": evidence.get("qualification_revision") == BASELINE_REVISION,
        "release_repeated_methodology": evidence.get("environment", {}).get(
            "companion_build_mode"
        )
        == "release"
        and evidence.get("methodology", {}).get("ordinary_measured_rounds", 0) >= 7
        and evidence.get("methodology", {}).get("deep_cfg_measured_rounds", 0) >= 7,
        "three_routes_and_raw_profiles": _profiles_valid(evidence),
        "representative_corpus": len(evidence.get("workload_manifest", [])) >= 7
        and {
            row.get("category") for row in evidence.get("workload_manifest", [])
        }
        >= {
            "numeric iterative",
            "collection-heavy",
            "struct-heavy",
            "class/interface-heavy",
            "function-value/indirect-call",
            "exception/lifecycle-heavy",
        },
        "additive_categories": set(categories) == CATEGORIES
        and abs(
            sum(row.get("percent_of_dual_lane", -1000) for row in categories.values())
            - 100.0
        )
        <= evidence.get("dual_lane_additive_categories", {}).get(
            "tolerance_percent", 0
        ),
        "lowering_components": set(lowering.get("components", {}))
        == LOWERING_COMPONENTS
        and isinstance(lowering.get("dominance_percent_of_rust_ssa_lowering"), (int, float)),
        "deep_required_sizes": {row.get("blocks") for row in deep}
        >= {100, 1000, 5000, 10000}
        and all(
            set(row.get("routes", {})) == ROUTES
            and row["routes"]["diagnostic_rust_only"].get("status") == "MEASURED"
            and len(row["routes"]["diagnostic_rust_only"].get("raw_samples", [])) >= 7
            for row in deep
        ),
        "startup_persistent_session": session.get("process_count") == 1
        and session.get("persistent_session_request_count", 0) > 1
        and session.get("ordinary_compilation_restarts_per_request") is False,
        "removed_work_gate": {row.get("work") for row in removed} == REMOVED
        and all(row.get("status") == "PASS_ABSENT_OR_NON_EXECUTING" for row in removed),
        "safety_classified": len(safety) >= 6
        and all(
            row.get("classification")
            in {"REQUIRED_INDEPENDENT", "POTENTIALLY_REDUNDANT", "UNKNOWN"}
            for row in safety
        ),
        "copy_census": len(copies) >= 8
        and all("classification" in row and "trust_boundary" in row for row in copies),
        "candidate_inventory": {row.get("candidate") for row in candidates}
        == CANDIDATES
        and [row.get("rank") for row in candidates] == list(range(1, 10)),
        "production_frozen": production
        == {
            "authority": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "python_shadow": "mandatory_synchronous",
            "failure_policy": "FAIL_CLOSED",
            "schemas": {"initial_ir": 1, "ssa": 2, "protocol": 1},
            "production_optimization_implemented": False,
            "ordinary_characterization_fields": False,
        },
        "correctness_qualification": qualification.get("cargo_test_workspace_locked")
        == "PASS"
        and qualification.get("cargo_fmt_all_check") == "PASS"
        and qualification.get("git_diff_check") == "PASS"
        and qualification.get("historical_116_of_116") == "PASS"
        and qualification.get("adversarial_ssa") == "PASS"
        and qualification.get("deep_cfg_993_1000_5000") == "PASS"
        and qualification.get("full_python_suite", {}).get("passed") >= 4891,
        "report_present": report_path.read_text(encoding="utf-8").startswith(
            "# Post-dominator SSA pipeline characterization — RUST-3.10"
        ),
    }
    passed = all(checks.values())
    return {
        "milestone": "RUST-3.10",
        "decision": (
            "RUST_SSA_POST_DOMINATOR_PERFORMANCE_CHARACTERIZED"
            if passed
            else "RUST_SSA_POST_DOMINATOR_CHARACTERIZATION_BLOCKED"
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
        and record["decision"] != "RUST_SSA_POST_DOMINATOR_PERFORMANCE_CHARACTERIZED"
    )


if __name__ == "__main__":
    raise SystemExit(main())
