#!/usr/bin/env python3
"""Check the frozen lowering-policy artifact against Python authorities."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ssa.lowering_policy import check_lowering_policy_v1


def main() -> int:
    errors = check_lowering_policy_v1()
    if errors:
        for error in errors:
            print(f"SSA_LOWERING_POLICY_V1_DRIFT: {error}")
        return 1
    print("SSA_LOWERING_POLICY_V1_QUALIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
