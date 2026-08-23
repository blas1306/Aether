from __future__ import annotations

import random
import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from aether.analysis.cfg import CFG, CFGEdge, CFGNode
from aether.analysis.dominance_frontier import DominanceFrontierAnalysis
from aether.analysis.dominators import (
    DominatorAnalysis,
    ReferenceDominatorAnalysis,
)
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.general_builder import GeneralSSABuilder


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
PHASES = {
    "python_lifecycle_normalization",
    "python_cfg_construction",
    "python_cfg_indexing",
    "python_reachability",
    "python_dominator_computation",
    "python_immediate_dominator_derivation",
    "python_dominator_tree",
    "python_dominance_frontiers",
    "python_definition_collection",
    "python_liveness",
    "python_definite_initialization",
    "python_phi_placement",
    "python_renaming",
    "python_result_assembly",
    "python_builder_verification",
}


def _load_checker():
    path = ROOT / "scripts/check_rust_ssa_python_shadow_optimization.py"
    spec = importlib.util.spec_from_file_location("rust_3_11_checker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _random_cfg(seed: int, size: int = 48) -> CFG:
    rng = random.Random(seed)
    names = tuple(f"b{index}" for index in range(size))
    edges: set[tuple[str, str]] = set()

    # A partial backbone supplies realistic reachable regions while deliberate
    # gaps retain unreachable nodes. Extra forward/back edges create joins and
    # loops. Fixed seeds make every failure exactly reproducible.
    for index in range(size - 1):
        if rng.random() < 0.82:
            edges.add((names[index], names[index + 1]))
    for _ in range(size * 3):
        source = rng.randrange(size)
        target = rng.randrange(size)
        if source != target:
            edges.add((names[source], names[target]))
    return CFG(
        f"seeded_{seed}",
        tuple(CFGNode(name) for name in names),
        tuple(CFGEdge(source, target) for source, target in sorted(edges)),
    )


@pytest.mark.parametrize("seed", [3, 11, 29, 47, 101])
def test_indexed_dominance_matches_frozen_reference_on_seeded_cfg(seed: int) -> None:
    cfg = _random_cfg(seed)
    optimized = DominatorAnalysis(cfg).compute()
    reference = ReferenceDominatorAnalysis(cfg).compute()
    optimized_frontier = DominanceFrontierAnalysis(cfg, optimized).compute()
    reference_frontier = DominanceFrontierAnalysis(cfg, reference).compute()

    for node in cfg.nodes:
        name = node.name
        assert optimized.is_reachable(name) == reference.is_reachable(name)
        assert optimized.dominators(name) == reference.dominators(name)
        assert optimized.immediate_dominator(name) == reference.immediate_dominator(name)
        assert (
            optimized.dominator_tree_children(name)
            == reference.dominator_tree_children(name)
        )
        assert optimized_frontier.frontier(name) == reference_frontier.frontier(name)


def test_reference_and_optimized_builders_have_exact_phi_focused_ssa_parity() -> None:
    from qualify_rust_ssa_lowering_adversarial import cases

    selected = {
        "diamond_phi_required",
        "diamond_multiple_phis",
        "nested_diamonds",
        "loop_multiple_backedge_path",
        "unreachable_cycle_colliding_names",
        "scale_linear_100",
    }
    for name, _tags, factory in cases():
        if name not in selected:
            continue
        module = factory()
        optimized = GeneralSSABuilder().build(module)
        with (
            patch(
                "aether.ssa.general_builder.DominatorAnalysis",
                ReferenceDominatorAnalysis,
            ),
            patch(
                "aether.ssa.verifier.DominatorAnalysis",
                ReferenceDominatorAnalysis,
            ),
        ):
            reference = GeneralSSABuilder().build(module)
        assert ssa_module_to_dto(optimized, schema_version=2) == ssa_module_to_dto(
            reference, schema_version=2
        ), name


def test_detailed_phase_instrumentation_is_opt_in_and_complete() -> None:
    from qualify_rust_ssa_lowering_adversarial import linear

    timings: dict[str, float] = {}
    GeneralSSABuilder(phase_timings=timings).build(linear("timed", 100))

    assert set(timings) == PHASES
    assert all(value >= 0.0 for value in timings.values())


def test_production_builder_does_not_read_performance_clock() -> None:
    from qualify_rust_ssa_lowering_adversarial import linear

    def forbidden_clock() -> float:
        raise AssertionError("production SSA builder read the diagnostic clock")

    with (
        patch("aether.analysis.dominators.perf_counter", forbidden_clock),
        patch("aether.ssa.general_builder.perf_counter", forbidden_clock),
        patch("aether.ssa.phi_placement.perf_counter", forbidden_clock),
        patch("aether.ssa.renaming.perf_counter", forbidden_clock),
    ):
        GeneralSSABuilder().build(linear("untimed", 100))


def test_python_dominance_uses_compact_masks_without_rust_analysis() -> None:
    source = (ROOT / "src/aether/analysis/dominators.py").read_text(
        encoding="utf-8"
    )
    production = source.split("class ReferenceDominatorAnalysis", 1)[0]

    assert "_dominator_masks" in production
    assert "ReferenceDominatorAnalysis" not in production
    assert "subprocess" not in production
    assert "ctypes" not in production
    assert "compiler-rs" not in production
    assert "aether_ir" not in production
    assert "chk_idom" not in production


def test_production_authority_shadow_and_fail_closed_contract_remain() -> None:
    source = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    production = source.split("def run_rust()", 1)[0]

    assert "GeneralSSABuilder().build(python_input)" in production
    assert "raise SSAShadowFailure" in production
    assert "execute_python_shadow: bool = True" in source


def test_checked_in_rust_3_11_evidence_is_optimized() -> None:
    record = _load_checker().build_record()

    assert record["decision"] == "RUST_SSA_PYTHON_SHADOW_OPTIMIZED"
    assert all(record["checks"].values())
