from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/characterize_rust_ssa_post_dominator.py"
CHECKER = ROOT / "scripts/check_rust_ssa_post_dominator_performance.py"
EVIDENCE = (
    ROOT / "docs/compiler/rust_ssa_post_dominator_performance_characterization.json"
)
REPORT = ROOT / "docs/compiler/RUST_SSA_POST_DOMINATOR_PERFORMANCE_CHARACTERIZATION.md"
COMPANION = ROOT / "compiler-rs/target/release/aether-ssa-shadow"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_additive_category_model_reconciles_exactly() -> None:
    runner = _module("rust_3_10_runner", RUNNER)
    phases = {
        phase: (index + 1) / 10_000
        for index, phase in enumerate(sorted(runner.PHASE_CATEGORY))
        if phase not in {"clock_domain_rounding_adjustment"}
    }
    residual = 0.0003
    sample = {
        "phases_seconds": phases,
        "residual_unattributed_seconds": residual,
        "total_wall_seconds": sum(phases.values()) + residual,
    }
    evidence = [
        {"samples": {"rust_authority_python_shadow": [sample]}}
    ]

    model = runner._category_accounting(evidence)

    assert model["percent_sum"] == pytest.approx(100.0)
    assert sum(
        row["observed_seconds"] for row in model["categories"].values()
    ) == pytest.approx(sample["total_wall_seconds"])


def test_checked_in_rust_3_10_evidence_is_characterized() -> None:
    checked = _module("rust_3_10_checker", CHECKER).build_record(EVIDENCE, REPORT)

    assert checked["decision"] == "RUST_SSA_POST_DOMINATOR_PERFORMANCE_CHARACTERIZED"
    assert all(checked["checks"].values())


def test_instrumentation_is_exclusive_to_explicit_companion_mode() -> None:
    source = (
        ROOT / "compiler-rs/crates/aether-verifier/src/bin/aether-ssa-shadow.rs"
    ).read_text(encoding="utf-8")
    production_branch, diagnostic_branch = source.split(
        "let request_started = Instant::now();", 1
    )

    assert "lower_verified_ir_to_ssa_v1(&initial, 1, 1)?" in production_branch
    assert "performance: None" in production_branch
    assert "characterize_lower_normalized_ir_to_ssa_v1" in diagnostic_branch
    assert "ssa_lowering_phases" in diagnostic_branch

    dominance = (
        ROOT / "compiler-rs/crates/aether-ir/src/dominance.rs"
    ).read_text(encoding="utf-8")
    ordinary_compute = dominance.split(
        "pub(crate) fn compute(successors", 1
    )[1].split("pub(crate) fn compute_characterized", 1)[0]
    assert "Instant::now" not in ordinary_compute
    assert "timings" not in ordinary_compute
    assert "compute_instrumented" not in ordinary_compute


@pytest.mark.skipif(not COMPANION.is_file(), reason="release companion is not built")
def test_ordinary_companion_response_shape_and_persistent_session() -> None:
    runner = _module("rust_3_10_runner_companion", RUNNER)
    from aether.ir.dto import ir_module_to_dto
    from aether.ssa.shadow import PersistentRustSSALoweringClient

    module, _ = runner.base._load_module("benchmarks/arithmetic.ae")
    payload = json.dumps(ir_module_to_dto(module), separators=(",", ":")).encode()
    with PersistentRustSSALoweringClient(COMPANION) as client:
        first = client.lower(payload)
        process_id = client.process_id
        second = client.lower(payload)

        assert set(first) == {"ok", "ssa"}
        assert set(second) == {"ok", "ssa"}
        assert "performance" not in first
        assert client.process_id == process_id
        assert client.process_start_count == 1
        assert client.request_count == 2


def test_no_new_authority_mode_or_production_optimization() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    from aether.ssa.shadow import SSALoweringAuthorityMode

    assert {mode.name for mode in SSALoweringAuthorityMode} == {
        "PYTHON_SSA_ONLY",
        "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
        "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
    }
    assert evidence["production_invariants"]["production_optimization_implemented"] is False
    assert evidence["production_invariants"]["ordinary_characterization_fields"] is False
