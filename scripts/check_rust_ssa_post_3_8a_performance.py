#!/usr/bin/env python3
"""Check permanent RUST-3.8b observational evidence contracts."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = (
    ROOT / "docs/compiler/rust_ssa_post_3_8a_performance_characterization.json"
)
DEFAULT_REPORT = (
    ROOT / "docs/compiler/RUST_SSA_POST_3_8A_PERFORMANCE_CHARACTERIZATION.md"
)
REMOVED_PHASES = {
    "python_shadow_input_reconstruction",
    "python_shadow_verification",
    "rust_result_dto_serialization",
}
REQUIRED_CANDIDATES = {
    "Rust SSA lowering",
    "Rust lifecycle normalization",
    "Rust Owned SSA verification",
    "request/response transport + serialization",
    "schema-v2 import",
    "Python verification of imported Rust SSA",
    "Python shadow lifecycle/lowering/verification",
    "canonicalization/comparison",
    "integrity check",
    "dominator implementation",
}
VALID_CLASSIFICATIONS = {
    "LOW_RISK_REDUNDANCY",
    "LOW_RISK_ARCHITECTURAL",
    "ALGORITHMIC_CORE",
    "SAFETY_BOUNDARY",
    "SHADOW_POLICY",
    "NOT_WORTH_OPTIMIZING",
}


def _head_revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _promotion_checker_module():
    path = ROOT / "scripts/check_rust_ssa_authority_promotion_v2.py"
    spec = importlib.util.spec_from_file_location("rust_ssa_pv2_checker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _profiles_consistent(evidence: dict[str, object]) -> bool:
    methodology = evidence.get("methodology")
    workloads = evidence.get("workloads")
    if not isinstance(methodology, dict) or not isinstance(workloads, list):
        return False
    rounds = methodology.get("measured_rounds_per_workload")
    if not isinstance(rounds, int) or rounds < 1:
        return False
    for workload in workloads:
        if not isinstance(workload, dict):
            return False
        samples = workload.get("samples", {})
        for mode in (
            "python_ssa_only",
            "diagnostic_rust_only",
            "rust_authority_python_shadow",
        ):
            rows = samples.get(mode)
            if not isinstance(rows, list) or len(rows) != rounds:
                return False
            for row in rows:
                phases = row.get("phases_seconds")
                measured = row.get("measured_component_sum_seconds")
                residual = row.get("residual_unattributed_seconds")
                total = row.get("total_wall_seconds")
                if not (
                    isinstance(phases, dict)
                    and all(isinstance(value, (int, float)) and value >= 0 for value in phases.values())
                    and isinstance(measured, (int, float))
                    and isinstance(residual, (int, float))
                    and isinstance(total, (int, float))
                    and abs(sum(phases.values()) - measured) <= max(1e-9, measured * 1e-9)
                    and abs(measured + residual - total) <= max(1e-9, total * 1e-9)
                ):
                    return False
    return True


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
    *,
    revision: str | None = None,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    expected_revision = revision or _head_revision()
    ranking = evidence.get("bottleneck_ranking", [])
    if not isinstance(ranking, list):
        ranking = []
    current_phases = {row.get("phase") for row in ranking if isinstance(row, dict)}
    inventory = evidence.get("phase_inventory")
    removed = (
        inventory.get("removed_by_rust_3_8a", [])
        if isinstance(inventory, dict)
        else []
    )
    if not isinstance(removed, list):
        removed = []
    removed_names = {row.get("phase") for row in removed if isinstance(row, dict)}
    category_breakdown = evidence.get("category_breakdown")
    categories = (
        category_breakdown.get("categories", {})
        if isinstance(category_breakdown, dict)
        else {}
    )
    if not isinstance(categories, dict):
        categories = {}
    candidates = evidence.get("candidate_audit", [])
    if not isinstance(candidates, list):
        candidates = []
    candidate_names = {
        row.get("candidate") for row in candidates if isinstance(row, dict)
    }
    classifications_valid = all(
        isinstance(row, dict)
        and row.get("classification") in VALID_CLASSIFICATIONS
        and isinstance(row.get("reason"), str)
        and bool(row["reason"])
        for row in candidates
    )
    deep_rows = evidence.get("deep_cfg_scaling", [])
    if not isinstance(deep_rows, list):
        deep_rows = []
    deep_sizes = {
        row.get("blocks")
        for row in deep_rows
        if isinstance(row, dict)
    }
    startup = evidence.get("startup_steady_state", {})
    if not isinstance(startup, dict):
        startup = {}
    invariants = evidence.get("production_invariants", {})
    pv2 = _promotion_checker_module()
    checks = {
        "decision": evidence.get("decision")
        == "RUST_SSA_POST_3_8A_PERFORMANCE_CHARACTERIZED",
        "exact_revision": evidence.get("qualification_revision")
        == expected_revision,
        "repeated_profiles_consistent": _profiles_consistent(evidence),
        "pv2_g15_accepts_exact_revision": pv2._performance_evidence_present(
            evidence, expected_revision
        ),
        "phase_ranking_complete": bool(ranking)
        and all(
            isinstance(row, dict)
            and isinstance(row.get("median_seconds"), (int, float))
            and isinstance(row.get("min_seconds"), (int, float))
            and isinstance(row.get("max_seconds"), (int, float))
            and isinstance(row.get("samples"), int)
            and isinstance(row.get("percent_of_dual_lane_median"), (int, float))
            and isinstance(row.get("category"), str)
            for row in ranking
        ),
        "removed_phases_absent": current_phases.isdisjoint(REMOVED_PHASES)
        and removed_names == REMOVED_PHASES,
        "categories_add_to_total": set(categories)
        == {
            "intrinsic_rust_work",
            "python_shadow_work",
            "safety_verification",
            "transport_import",
            "comparison",
            "orchestration",
        }
        and all(isinstance(row, dict) for row in categories.values())
        and abs(
            sum(row.get("percent_of_dual_lane", -1000) for row in categories.values())
            - 100.0
        )
        < 1e-8,
        "deep_cfg_required_sizes_and_modes": {1000, 5000} <= deep_sizes
        and all(
            isinstance(row, dict)
            and all(
                isinstance(row.get(mode), dict)
                and row[mode].get("samples", 0) >= 1
                for mode in (
                    "python_ssa_only",
                    "diagnostic_rust_only",
                    "rust_authority_python_shadow",
                )
            )
            for row in deep_rows
            if isinstance(row, dict)
            if row.get("blocks") in {1000, 5000}
        ),
        "startup_and_steady_state": isinstance(startup.get("startup_seconds"), (int, float))
        and startup.get("startup_seconds", -1) >= 0
        and startup.get("first_request_seconds", 0) > 0
        and startup.get("total_requests", 0) > 1
        and startup.get("process_starts") == 1
        and isinstance(startup.get("steady_state_representative"), dict),
        "candidate_inventory": candidate_names == REQUIRED_CANDIDATES
        and classifications_valid,
        "production_behavior_unchanged": invariants
        == {
            "authority": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "python_shadow": "mandatory_synchronous",
            "failure_policy": "FAIL_CLOSED",
            "schemas": {"initial_ir": 1, "ssa": 2, "protocol": 1},
            "behavior_changed": False,
            "optimization_implemented": False,
        },
        "report_present": report_path.read_text(encoding="utf-8").startswith(
            "# Rust SSA post-3.8a performance characterization — RUST-3.8b"
        ),
    }
    passed = all(checks.values())
    return {
        "milestone": "RUST-3.8b",
        "decision": (
            "RUST_SSA_POST_3_8A_PERFORMANCE_CHARACTERIZED"
            if passed
            else "RUST_SSA_POST_3_8A_PERFORMANCE_CHARACTERIZATION_BLOCKED"
        ),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--revision")
    parser.add_argument("--require-characterized", action="store_true")
    args = parser.parse_args()
    record = build_record(args.evidence, args.report, revision=args.revision)
    print(json.dumps(record, indent=2, sort_keys=True))
    return int(
        args.require_characterized
        and record["decision"]
        != "RUST_SSA_POST_3_8A_PERFORMANCE_CHARACTERIZED"
    )


if __name__ == "__main__":
    raise SystemExit(main())
