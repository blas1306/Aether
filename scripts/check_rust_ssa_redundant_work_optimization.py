#!/usr/bin/env python3
"""Check the permanent RUST-3.8a source and evidence contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs/compiler/rust_ssa_redundant_work_optimization.json"


def build_record(evidence_path: Path = DEFAULT_EVIDENCE) -> dict[str, object]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    shadow = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    builder = (ROOT / "src/aether/ssa/general_builder.py").read_text(
        encoding="utf-8"
    )
    targeted = evidence.get("performance", {}).get("targeted_phase_deltas", {})
    checks = {
        "decision": evidence.get("decision") == "RUST_SSA_REDUNDANT_WORK_OPTIMIZED",
        "authority_unchanged": evidence.get("invariants", {}).get("authority")
        == "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        "shadow_mandatory": evidence.get("invariants", {}).get("python_shadow")
        == "mandatory_synchronous",
        "fail_closed": evidence.get("invariants", {}).get("failure_policy")
        == "FAIL_CLOSED",
        "schemas_unchanged": evidence.get("invariants", {}).get("schemas")
        == {"initial_ir": 1, "ssa": 2, "protocol": 1},
        "original_ir_reused": "python_input = module" in shadow,
        "json_reconstruction_removed": "ir_module_from_dto(json.loads(payload))"
        not in shadow,
        "builder_non_mutation_contract": "never\n    mutates the supplied Initial IR graph"
        in builder,
        "one_shadow_file_verifier_call": shadow.count("SSAVerifier(value).verify()")
        == 1,
        "rust_transport_dto_reused": "rust_dto = rust_comparison_dto" in shadow,
        "integrity_check_retained": "unchanged = ir_module_to_dto(module) == snapshot"
        in shadow,
        "targeted_work_eliminated": set(targeted)
        == {
            "python_shadow_input_reconstruction",
            "python_shadow_verification",
            "rust_result_dto_serialization",
        }
        and all(
            row.get("before_median_seconds", 0) > 0
            and row.get("after_median_seconds") == 0
            and row.get("execution_after") == "eliminated"
            for row in targeted.values()
        ),
    }
    passed = all(checks.values())
    return {
        "milestone": "RUST-3.8a",
        "decision": (
            "RUST_SSA_REDUNDANT_WORK_OPTIMIZED"
            if passed
            else "RUST_SSA_REDUNDANT_WORK_OPTIMIZATION_BLOCKED"
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
        and record["decision"] != "RUST_SSA_REDUNDANT_WORK_OPTIMIZED"
    )


if __name__ == "__main__":
    raise SystemExit(main())
