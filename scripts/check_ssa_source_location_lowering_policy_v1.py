#!/usr/bin/env python3
"""Deterministically check SSA source-location lowering policy v1."""
from __future__ import annotations

from dataclasses import fields
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ir import model as ir
from aether.ssa import model as ssa
from aether.ssa.renaming import SSARenamer

POLICY = ROOT / "docs/compiler/ssa_source_location_lowering_policy_v1.json"


def check() -> tuple[str, ...]:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    errors: list[str] = []
    groups = ("direct_preserve", "direct_without_source_location",
              "elided_storage", "lifecycle_pseudo_instructions")
    listed = [name for group in groups for name in policy[group]]
    concrete = sorted({name for name, kind in vars(ir).items()
                       if inspect.isclass(kind) and name.startswith("IR")
                       and issubclass(kind, ir.IRInstruction)
                       and kind is not ir.IRInstruction})
    if sorted(listed) != concrete or len(listed) != len(set(listed)):
        errors.append("Initial IR instruction inventory is incomplete or duplicated")
    for name in policy["direct_preserve"]:
        peer = getattr(ssa, "SSA" + name[2:], None)
        if "source_location" not in {f.name for f in fields(getattr(ir, name))}:
            errors.append(f"{name} no longer carries source_location")
        if peer is None or "source_location" not in {f.name for f in fields(peer)}:
            errors.append(f"{name} SSA peer no longer carries source_location")
    source = inspect.getsource(SSARenamer._convert_instruction)
    for token in ("SSAArrayCopy(result, array, instruction.source_location)",
                  "SSAListCopy(result, list_value, instruction.source_location)",
                  "instruction.source_location"):
        if token not in source:
            errors.append(f"Python preservation anchor missing: {token}")
    if policy["policy_version"] != 1 or policy["schema"]["ssa"] != 2:
        errors.append("policy/schema version drifted")
    return tuple(sorted(errors))


def main() -> int:
    errors = check()
    for error in errors:
        print(f"SSA_SOURCE_LOCATION_LOWERING_POLICY_V1_DRIFT: {error}")
    if errors:
        return 1
    print("SSA_SOURCE_LOCATION_LOWERING_POLICY_V1_QUALIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
