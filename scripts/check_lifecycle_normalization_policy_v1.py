#!/usr/bin/env python3
"""Deterministic qualification gate for lifecycle normalization policy v1."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ssa.lifecycle_normalization_policy import check_lifecycle_normalization_policy_v1, load_lifecycle_normalization_policy  # noqa: E402
from aether.ssa.lowering_policy import load_lowering_policy  # noqa: E402


def check() -> tuple[str, ...]:
    errors = list(check_lifecycle_normalization_policy_v1())
    lifecycle = load_lifecycle_normalization_policy()
    dependency = load_lowering_policy().get("lifecycle_normalization", {})
    if dependency.get("lifecycle_normalization_policy_version") != 1:
        errors.append("lowering_policy_v1 does not depend on lifecycle policy v1")
    if dependency.get("policy_path") != "docs/compiler/lifecycle_normalization_policy_v1.json":
        errors.append("lowering_policy_v1 lifecycle policy path drifted")
    required = {"instruction_inventory", "expansions", "ordering", "ownership_state", "metadata", "cfg_and_exceptions", "dependencies", "idempotence"}
    if not required <= lifecycle.keys():
        errors.append("normative lifecycle contract is incomplete")
    evidence_path = ROOT / "docs/compiler/lifecycle_normalization_policy_v1_qualification.json"
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"qualification evidence unavailable: {error}")
    else:
        summary = evidence.get("corpus", {}).get("summary", {})
        if summary.get("verified_initial_ir_denominator") != 116:
            errors.append("corpus denominator is not 116")
        if summary.get("policy_validation_passed") != 116:
            errors.append("corpus policy coverage is incomplete")
        if evidence.get("decision") != "LIFECYCLE_NORMALIZATION_POLICY_V1_QUALIFIED":
            errors.append("qualification decision is not qualified")
        if not evidence.get("adversarial", {}).get("passed"):
            errors.append("adversarial exact-sequence evidence failed")
    return tuple(sorted(errors))


def main() -> int:
    errors = check()
    if errors:
        print("\n".join(errors))
        print("LIFECYCLE_NORMALIZATION_POLICY_V1_BLOCKED")
        return 1
    print("LIFECYCLE_NORMALIZATION_POLICY_V1_QUALIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
