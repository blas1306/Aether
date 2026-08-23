#!/usr/bin/env python3
"""Check permanent RUST-3.11 Python-shadow optimization contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVISION = "55dc4c5b12c6312fa8c1d143b964691c38c3c1de"
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ssa_python_shadow_optimization.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_PYTHON_SHADOW_OPTIMIZATION.md"
ROUTES = {"python_shadow", "diagnostic_rust_only", "dual_lane"}
PHASES = {
    "lifecycle_normalization",
    "cfg_construction",
    "reachability",
    "dominator_computation",
    "immediate_dominator_derivation",
    "dominator_tree",
    "dominance_frontiers",
    "liveness",
    "definite_initialization",
    "phi_placement",
    "renaming",
    "builder_verification",
    "result_assembly",
}
ALLOWED = {
    "REPRESENTATION_ONLY",
    "DATA_STRUCTURE_ONLY",
    "TRAVERSAL_OPTIMIZATION",
    "PYTHON_ALGORITHM_INDEPENDENT",
}


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    deep = {row["blocks"]: row for row in evidence.get("deep_cfg", [])}
    optimized = evidence.get("implemented_changes", [])
    production = evidence.get("production_invariants", {})
    qualification = evidence.get("qualification", {})
    checks = {
        "decision": evidence.get("decision") == "RUST_SSA_PYTHON_SHADOW_OPTIMIZED",
        "exact_baseline": evidence.get("baseline_revision") == BASELINE_REVISION,
        "audit_precedes_optimization": evidence.get("audit", {}).get("completed_before_change") is True,
        "complete_dependency_map": {row.get("phase") for row in evidence.get("dependency_map", [])} == PHASES,
        "implemented_classifications_safe": bool(optimized)
        and all(row.get("classification") in ALLOWED for row in optimized),
        "reference_path_and_parity": evidence.get("differential", {}).get("reference_path") == "ReferenceDominatorAnalysis"
        and evidence.get("differential", {}).get("exact_canonical_ssa_parity") is True
        and evidence.get("differential", {}).get("seeded_cfg_parity") is True,
        "deep_sizes_and_raw_samples": set(deep) == {100, 1000, 5000, 10000}
        and all(
            set(row.get("after", {})) == ROUTES
            and all(len(samples) >= 7 for samples in row["after"].values())
            for row in deep.values()
        )
        and all(
            set(deep[size].get("before", {})) == ROUTES
            and all(len(samples) >= 7 for samples in deep[size]["before"].values())
            for size in (100, 1000, 5000)
        )
        and deep[10000].get("before_status") == "NOT_RUN_OPERATIONALLY_IMPRACTICAL",
        "targeted_phase_improved": deep[5000].get("speedup", {}).get("python_shadow", 0) > 2.0,
        "dual_lane_improved": deep[5000].get("speedup", {}).get("dual_lane", 0) > 2.0,
        "ten_thousand_now_practical": deep[10000].get("after_summary", {}).get("python_shadow", {}).get("median_seconds", 999) < 5.0,
        "memory_reduced": evidence.get("memory", {}).get("deep_5000_peak_rss_kib_before", 0)
        > evidence.get("memory", {}).get("deep_5000_peak_rss_kib_after", 0) * 5,
        "independence": evidence.get("independence", {}).get("consumes_rust_analysis") is False
        and evidence.get("independence", {}).get("same_as_rust_chk") is False
        and evidence.get("independence", {}).get("mandatory_oracle_value_preserved") is True,
        "production_frozen": production == {
            "authority": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "python_shadow": "mandatory_synchronous",
            "failure_policy": "FAIL_CLOSED",
            "schemas": {"initial_ir": 1, "protocol": 1, "ssa": 2},
            "optimizer_backend_changed": False,
            "rollback_modes_changed": False,
        },
        "qualification": qualification.get("focused_python") == "PASS"
        and qualification.get("historical_116_of_116") == "PASS"
        and qualification.get("adversarial_ssa") == "PASS"
        and qualification.get("deep_cfg_993_1000_5000_10000") == "PASS"
        and qualification.get("full_python_suite", {}).get("status") == "PASS"
        and qualification.get("cargo_test_workspace_locked") == "PASS"
        and qualification.get("git_diff_check") == "PASS",
        "report_present": report_path.read_text(encoding="utf-8").startswith(
            "# Python shadow performance optimization — RUST-3.11"
        ),
    }
    passed = all(checks.values())
    return {
        "milestone": "RUST-3.11",
        "decision": (
            "RUST_SSA_PYTHON_SHADOW_OPTIMIZED"
            if passed
            else "RUST_SSA_PYTHON_SHADOW_BLOCKED"
        ),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--require-optimized", action="store_true")
    args = parser.parse_args()
    record = build_record(args.evidence, args.report)
    print(json.dumps(record, indent=2, sort_keys=True))
    return int(
        args.require_optimized
        and record["decision"] != "RUST_SSA_PYTHON_SHADOW_OPTIMIZED"
    )


if __name__ == "__main__":
    raise SystemExit(main())
