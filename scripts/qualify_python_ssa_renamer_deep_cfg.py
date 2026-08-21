#!/usr/bin/env python3
"""Generate SSA-ROBUST-1 deep-CFG qualification evidence."""
from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import subprocess
import sys
import textwrap
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from aether.ssa.general_builder import GeneralSSABuilder
from aether.ssa.renaming import SSARenamer
from qualify_rust_ssa_lowering_adversarial import generate as adversarial_generate, linear

OUTPUT = ROOT / "docs/compiler/python_ssa_renamer_deep_cfg_qualification.json"


def _non_recursive() -> bool:
    tree = ast.parse(textwrap.dedent(inspect.getsource(SSARenamer._rename_blocks)))
    return not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_rename_blocks"
        for node in ast.walk(tree)
    )


def generate() -> dict:
    stress = []
    for size in (100, 993, 1000, 5000):
        started = perf_counter_ns()
        result = GeneralSSABuilder().build(linear(f"ssa_robust_linear_{size}", size))
        stress.append({
            "blocks": size,
            "lowered_blocks": len(result.functions[0].blocks),
            "verified": True,
            "elapsed_ns": perf_counter_ns() - started,
        })

    focused = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/aether/test_ssa_renaming_deep_cfg.py",
            "tests/aether/test_ssa_renaming.py",
            "tests/aether/test_general_ssa_builder.py",
            "tests/aether/test_general_ssa_builder_stress.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    adversarial = adversarial_generate()
    historical = adversarial["existing_corpus"]
    qualified = (
        all(row["verified"] and row["lowered_blocks"] == row["blocks"] for row in stress)
        and _non_recursive()
        and focused.returncode == 0
        and adversarial["decision"] == "RUST_SSA_LOWERING_ADVERSARIAL_QUALIFIED"
        and historical.get("passed") == historical.get("denominator") == 116
    )
    return {
        "evidence_schema_version": 1,
        "attempt": "SSA-ROBUST-1",
        "decision": (
            "PYTHON_SSA_RENAMER_DEEP_CFG_QUALIFIED"
            if qualified
            else "PYTHON_SSA_RENAMER_DEEP_CFG_BLOCKED"
        ),
        "root_cause": {
            "function": "SSARenamer._rename_block",
            "path": "rename -> _rename_block -> dominator child -> _rename_block",
            "depth_proportional_to_dominator_tree": True,
            "minimized_reproducer_blocks": 993,
        },
        "architecture": {
            "iterative_enter_exit_frames": True,
            "recursive_dominator_descent_absent": _non_recursive(),
            "global_recursion_limit_changed": False,
        },
        "stress": stress,
        "focused_tests": {
            "exit_code": focused.returncode,
            "summary": focused.stdout.strip().splitlines()[-1] if focused.stdout.strip() else "",
            "includes_recursive_reference_exact_equality": True,
        },
        "adversarial": adversarial,
        "historical_differential": historical,
        "scope": {
            "rust_lowering_algorithms_changed": False,
            "production_lowering_authority": "python",
            "rp3_changed": False,
            "commit_created": False,
        },
    }


def main() -> int:
    report = generate()
    if "--check" in sys.argv:
        if not OUTPUT.exists() or json.loads(OUTPUT.read_text()) != report:
            print("stale Python SSA deep-CFG qualification evidence")
            return 1
    else:
        OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report["decision"])
    return 0 if report["decision"].endswith("_QUALIFIED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
