from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/check_rust_ssa_redundant_work_optimization.py"
EVIDENCE = ROOT / "docs/compiler/rust_ssa_redundant_work_optimization.json"
REPORT = ROOT / "docs/compiler/RUST_SSA_REDUNDANT_WORK_OPTIMIZATION.md"


def _checker_module():
    spec = importlib.util.spec_from_file_location("rust_3_8a_checker", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_in_redundant_work_evidence_is_optimized() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    checked = _checker_module().build_record(EVIDENCE)

    assert checked["decision"] == "RUST_SSA_REDUNDANT_WORK_OPTIMIZED"
    assert all(checked["checks"].values())
    assert evidence["performance"]["methodology"]["warmup_rounds"] >= 1
    assert evidence["performance"]["methodology"]["measured_rounds"] >= 3
    assert evidence["correctness"]["historical"] == "116/116 PASS"
    assert evidence["correctness"]["stabilization_exact_accounting"] == "PASS"
    assert REPORT.read_text(encoding="utf-8").startswith(
        "# Rust SSA redundant-work optimization — RUST-3.8a"
    )
