"""Versioned contract checks for lifecycle normalization before SSA.

This module is deliberately not the production normalizer.  It makes the
contract independently loadable and validates the facts which bind that
normalizer to policy version 1.
"""

from __future__ import annotations

from dataclasses import fields
import inspect
import json
from pathlib import Path
from typing import Any

from aether.ir.lifecycle import LIFECYCLE_INSTRUCTIONS, LifecycleExpander


LIFECYCLE_NORMALIZATION_POLICY_VERSION = 1
_ROOT = Path(__file__).resolve().parents[3]
LIFECYCLE_NORMALIZATION_POLICY_PATH = (
    _ROOT / "docs/compiler/lifecycle_normalization_policy_v1.json"
)


class LifecycleNormalizationPolicyError(ValueError):
    """An unsupported version or drift in the frozen policy artifact."""


def load_lifecycle_normalization_policy(
    version: int = LIFECYCLE_NORMALIZATION_POLICY_VERSION,
) -> dict[str, Any]:
    if version != LIFECYCLE_NORMALIZATION_POLICY_VERSION:
        raise LifecycleNormalizationPolicyError(
            f"Unsupported lifecycle normalization policy version {version!r}; "
            f"expected {LIFECYCLE_NORMALIZATION_POLICY_VERSION}"
        )
    policy = json.loads(
        LIFECYCLE_NORMALIZATION_POLICY_PATH.read_text(encoding="utf-8")
    )
    if policy.get("lifecycle_normalization_policy_version") != version:
        raise LifecycleNormalizationPolicyError(
            "lifecycle normalization policy artifact version does not match"
        )
    return policy


def check_lifecycle_normalization_policy_v1() -> tuple[str, ...]:
    """Return stable, sorted diagnostics; an empty tuple means qualified."""

    policy = load_lifecycle_normalization_policy()
    errors: list[str] = []
    actual = [kind.__name__ for kind in LIFECYCLE_INSTRUCTIONS]
    declared = list(policy.get("instruction_inventory", ()))
    if declared != actual:
        errors.append("lifecycle pseudo-instruction inventory drifted")

    expansions = policy.get("expansions", {})
    if sorted(expansions) != sorted(actual):
        errors.append("expansion definitions are incomplete")
    required_fields = {
        kind.__name__: [field.name for field in fields(kind)]
        for kind in LIFECYCLE_INSTRUCTIONS
    }
    if policy.get("input_fields") != required_fields:
        errors.append("lifecycle input field inventory drifted")

    required_sections = {
        "abstract_contract", "ordering", "type_traits", "ownership_state",
        "cfg_and_exceptions", "metadata", "deterministic_errors",
        "idempotence", "dependencies", "qualification",
    }
    missing = sorted(required_sections - policy.keys())
    if missing:
        errors.append(f"policy sections missing: {', '.join(missing)}")

    source = inspect.getsource(LifecycleExpander._expand_instruction)
    for kind in actual:
        if kind not in source:
            errors.append(f"production expansion anchor missing: {kind}")
    helper_source = inspect.getsource(LifecycleExpander._default_value)
    for token in policy.get("implementation_anchors", {}).get("default_tokens", ()):
        if token not in helper_source:
            errors.append(f"default-value anchor missing: {token}")
    return tuple(sorted(errors))


def canonical_lifecycle_normalization_policy_json() -> str:
    return json.dumps(
        load_lifecycle_normalization_policy(), indent=2, sort_keys=True
    ) + "\n"
