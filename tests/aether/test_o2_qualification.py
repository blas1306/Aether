from __future__ import annotations

import json
from pathlib import Path

from aether.optimization import IR_O1_PASSES, SSA_O1_PASSES, SSA_O2_PASSES, optimization_profile


ROOT = Path(__file__).resolve().parents[2]


def test_exact_profile_membership_and_order():
    assert optimization_profile("O0").ir_passes == ()
    assert optimization_profile("O0").ssa_passes == ()
    assert optimization_profile("O0").clang_level == "0"
    assert optimization_profile("O1").ir_passes == IR_O1_PASSES
    assert optimization_profile("O1").ssa_passes == SSA_O1_PASSES
    assert optimization_profile("O1").clang_level == "1"
    assert optimization_profile("O2").ir_passes == IR_O1_PASSES
    assert optimization_profile("O2").ssa_passes == SSA_O2_PASSES
    assert SSA_O2_PASSES == SSA_O1_PASSES + (
        "ProvenBoundsCheckEliminator", "LoopInvariantCodeMotion",
        "OwnershipElidedArrayGet", "LocalARCEliminator",
        "SSADeadCodeEliminator",
    )
    assert optimization_profile("O2").clang_level == "2"


def test_qualification_artifact_and_corpus_contract():
    qualification = json.loads((ROOT / "docs/compiler/o2_qualification.json").read_text())
    manifest = json.loads((ROOT / "benchmarks/o2_workloads.json").read_text())
    assert qualification["schema_version"] == 1
    assert qualification["final_decision"] in {"O2_FREEZE_QUALIFIED", "O2_FREEZE_BLOCKED"}
    assert qualification["workload_counts"] == {"total": 30, "supported": 26, "unsupported": 4, "benchmarkable": 20}
    assert len(manifest["workloads"]) == 30
    assert len({row["path"] for row in manifest["workloads"]}) == 30


def test_freeze_policy_and_history_are_present():
    qualification = json.loads((ROOT / "docs/compiler/o2_qualification.json").read_text())
    freeze = (ROOT / "docs/compiler/O2_OPTIMIZATION_PROFILE_FREEZE.md").read_text()
    assert "exact workload" in freeze and "exact SSA instruction" in freeze
    assert "HYPOTHESIS_ONLY" in freeze and "TRANSFORMABLE_NOW" in freeze
    assert "O2 is a higher optimization profile" in freeze
    assert "Reopen criteria" in freeze
    for relative in qualification["historical_artifacts"]:
        assert (ROOT / relative).is_file()


def test_static_qualification_checker_without_expensive_regeneration():
    from scripts.check_o2_qualification import check
    assert check(ROOT, regenerate=False) == []
