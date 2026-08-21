"""Versioned, descriptive contract for Initial IR to SSA lowering.

This module does not perform lowering.  It loads the frozen policy artifact and
checks the small set of structural facts that can usefully be checked without
trying to prove equivalence with the Python implementation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aether.ir.lifecycle import LIFECYCLE_INSTRUCTIONS
from aether.ssa.dto import SSA_SCHEMA_VERSION


LOWERING_POLICY_VERSION = 1
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LOWERING_POLICY_PATH = _REPOSITORY_ROOT / "docs/compiler/ssa_lowering_policy_v1.json"


class LoweringPolicyError(ValueError):
    """The requested policy is unsupported or the frozen artifact has drifted."""


def load_lowering_policy(version: int = LOWERING_POLICY_VERSION) -> dict[str, Any]:
    if version != LOWERING_POLICY_VERSION:
        raise LoweringPolicyError(
            f"Unsupported SSA lowering policy version {version!r}; "
            f"expected {LOWERING_POLICY_VERSION}"
        )
    policy = json.loads(LOWERING_POLICY_PATH.read_text(encoding="utf-8"))
    if policy.get("lowering_policy_version") != version:
        raise LoweringPolicyError("lowering policy artifact version does not match")
    return policy


def check_lowering_policy_v1() -> tuple[str, ...]:
    """Return deterministic structural drift diagnostics; empty means qualified."""

    policy = load_lowering_policy()
    errors: list[str] = []
    expected_lifecycle = [type_.__name__ for type_ in LIFECYCLE_INSTRUCTIONS]
    if policy["lifecycle_normalization"]["input_kinds"] != expected_lifecycle:
        errors.append("lifecycle normalization inventory drifted")
    if policy["serialization_reference"]["ssa_schema_version"] != SSA_SCHEMA_VERSION:
        errors.append("SSA serialization reference drifted")
    expected_bounds_kinds = [
        "IRArrayGet", "IRArraySet", "IRListGet", "IRListSet",
        "IRVectorGet", "IRVectorSet", "IRMatrixGet", "IRMatrixSet",
    ]
    synthesis = policy.get("bounds_checked_synthesis", {})
    if synthesis.get("affected_initial_ir_kinds") != expected_bounds_kinds:
        errors.append("bounds_checked synthesis inventory drifted")
    if "bounds_checked=true" not in synthesis.get("rule", ""):
        errors.append("bounds_checked synthesis value drifted")

    from aether.analysis.cfg import CFGBuilder
    from aether.ssa.general_builder import GeneralSSABuilder
    from aether.ssa.renaming import SSARenamer

    checks = {
        "CFGBuilder": (CFGBuilder.build, policy["implementation_anchors"]["cfg_tokens"]),
        "GeneralSSABuilder": (
            GeneralSSABuilder.build_module,
            policy["implementation_anchors"]["pipeline_tokens"],
        ),
        "SSARenamerNaming": (
            SSARenamer._fresh_name,
            policy["implementation_anchors"]["naming_tokens"],
        ),
        "SSARenamerBoundsSynthesis": (
            SSARenamer._convert_instruction,
            ["bounds_checked=True"],
        ),
    }
    import inspect

    for owner, (callable_, tokens) in checks.items():
        source = inspect.getsource(callable_)
        missing = [token for token in tokens if token not in source]
        if missing:
            errors.append(f"{owner} structural anchors drifted: {', '.join(missing)}")
    return tuple(sorted(errors))


def canonical_policy_json() -> str:
    """Return the canonical deterministic representation used by CI."""

    return json.dumps(load_lowering_policy(), indent=2, sort_keys=True) + "\n"
