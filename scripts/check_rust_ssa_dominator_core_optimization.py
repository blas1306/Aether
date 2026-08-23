#!/usr/bin/env python3
"""Check the permanent RUST-3.9b implementation and evidence contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = (
    ROOT / "docs/compiler/rust_ssa_dominator_core_optimization.json"
)


def build_record(evidence_path: Path = DEFAULT_EVIDENCE) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    dominance = (
        ROOT / "compiler-rs/crates/aether-ir/src/dominance.rs"
    ).read_text(encoding="utf-8")
    lowering = (
        ROOT / "compiler-rs/crates/aether-ir/src/lowering.rs"
    ).read_text(encoding="utf-8")
    qualification = evidence.get("qualification", {})
    scaling = evidence.get("performance", {}).get("optimized_dominator_ns", {})
    expected_sizes = {"100", "1000", "5000", "10000", "25000"}
    checks = {
        "decision": evidence.get("decision")
        == "RUST_SSA_DOMINATOR_CORE_OPTIMIZED",
        "baseline_revision": evidence.get("baseline_revision")
        == "173383a4cab02a4239e2716574716176e1e3d337",
        "algorithm": evidence.get("algorithm", {}).get("selected")
        == "Cooper-Harvey-Kennedy immediate-dominator iteration",
        "linear_structural_memory": evidence.get("algorithm", {}).get(
            "production_structural_memory"
        )
        == "O(V+E)",
        "authority_unchanged": evidence.get("invariants", {}).get("authority")
        == "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        "shadow_mandatory": evidence.get("invariants", {}).get("python_shadow")
        == "mandatory_synchronous",
        "fail_closed": evidence.get("invariants", {}).get("failure_policy")
        == "FAIL_CLOSED",
        "schemas_unchanged": evidence.get("invariants", {}).get("schemas")
        == {"initial_ir": 1, "ssa": 2},
        "production_has_chk": all(
            token in dominance
            for token in ("reverse_postorder", "fn intersect", "rpo_number")
        ),
        "full_sets_absent_from_hot_path": "compute_dominators" not in lowering,
        "reference_test_only": "#[cfg(test)]\nmod tests" in dominance
        and "fn reference_dominance" in dominance,
        "seeded_differential": qualification.get("seeded_cfgs")
        == {"cases": 400, "seeds": 5, "status": "PASS"},
        "adversarial_differential": qualification.get("adversarial_cfg_families", {}).get(
            "status"
        )
        == "PASS",
        "full_dominance_compared": qualification.get("comparisons")
        == ["reachable", "dominance_relation", "idom", "tree", "frontier"],
        "deep_10000": qualification.get("deep_cfg", {}).get("10000") == "PASS",
        "ssa_parity": qualification.get("ssa_parity", {}).get("status") == "PASS",
        "full_python_suite": qualification.get("full_python_suite", {}).get("status")
        == "PASS"
        and qualification.get("full_python_suite", {}).get("passed") == 4886,
        "cargo_workspace_locked": qualification.get("cargo_workspace_locked")
        == "PASS",
        "required_scaling_sizes": set(scaling) == expected_sizes,
        "material_scaling_improvement": evidence.get("performance", {}).get(
            "optimized_ratio_1000_to_5000"
        )
        < evidence.get("performance", {}).get("baseline_ratio_1000_to_5000"),
        "reference_not_production_selectable": evidence.get("rollback", {}).get(
            "production_algorithm_switch"
        )
        is False,
    }
    passed = all(checks.values())
    return {
        "milestone": "RUST-3.9b",
        "decision": (
            "RUST_SSA_DOMINATOR_CORE_OPTIMIZED"
            if passed
            else "RUST_SSA_DOMINATOR_CORE_OPTIMIZATION_BLOCKED"
        ),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--require-optimized", action="store_true")
    args = parser.parse_args()
    record = build_record(args.evidence)
    print(json.dumps(record, indent=2, sort_keys=True))
    return int(
        args.require_optimized
        and record["decision"] != "RUST_SSA_DOMINATOR_CORE_OPTIMIZED"
    )


if __name__ == "__main__":
    raise SystemExit(main())
