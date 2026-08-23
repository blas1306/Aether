from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.general_builder import GeneralSSABuilder
from aether.ssa.shadow import (
    PersistentRustSSALoweringClient,
    SSAShadowFailure,
    lower_with_rust_authority,
)
from aether.ssa.verifier import SSAVerifier


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/characterize_rust_ssa_post_python_shadow.py"
CHECKER = ROOT / "scripts/check_rust_ssa_post_python_shadow_performance.py"
EVIDENCE = (
    ROOT
    / "docs/compiler/rust_ssa_post_python_shadow_performance_characterization.json"
)
REPORT = (
    ROOT / "docs/compiler/RUST_SSA_POST_PYTHON_SHADOW_PERFORMANCE_CHARACTERIZATION.md"
)
COMPANION = ROOT / "compiler-rs/target/release/aether-ssa-shadow"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_additive_categories_reconcile_and_keep_residual_explicit() -> None:
    runner = _module("rust_3_12_runner_model", RUNNER)
    phases = {
        phase: (index + 1) / 100_000
        for index, phase in enumerate(sorted(runner.PHASE_CATEGORY))
    }
    residual = 0.001
    sample = {
        "phases_seconds": phases,
        "measured_component_sum_seconds": sum(phases.values()),
        "residual_unattributed_seconds": residual,
        "total_wall_seconds": sum(phases.values()) + residual,
    }

    model = runner._category_model([sample])

    assert model["percent_sum"] == pytest.approx(100.0)
    assert model["reconciled_percent"] == pytest.approx(100.0)
    assert model["categories"]["ORCHESTRATION_RESIDUAL"]["observed_seconds"] >= residual


def test_checked_in_rust_3_12_evidence_is_characterized() -> None:
    record = _module("rust_3_12_checker", CHECKER).build_record(EVIDENCE, REPORT)

    assert record["decision"] == "RUST_SSA_POST_PYTHON_SHADOW_PERFORMANCE_CHARACTERIZED"
    assert all(record["checks"].values())


def test_checker_rejects_inconsistent_raw_sample_summary(tmp_path: Path) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence["ordinary_workloads"][0]["summary"]["python_only"]["median_seconds"] += 1.0
    corrupted = tmp_path / "evidence.json"
    corrupted.write_text(json.dumps(evidence), encoding="utf-8")

    record = _module("rust_3_12_checker_corrupt", CHECKER).build_record(
        corrupted, REPORT
    )

    assert record["checks"]["warmups_rounds_raw_samples"] is False


def test_detailed_instrumentation_is_opt_in_and_does_not_change_ssa() -> None:
    runner = _module("rust_3_12_runner_python", RUNNER)
    module, _digest = runner.base._load_module("benchmarks/arithmetic.ae")
    ordinary = GeneralSSABuilder().build(module)
    coarse: dict[str, float] = {}
    detailed: dict[str, float] = {}
    instrumented = GeneralSSABuilder(
        performance_timings=coarse, phase_timings=detailed
    ).build(module)

    assert ssa_module_to_dto(ordinary, schema_version=2) == ssa_module_to_dto(
        instrumented, schema_version=2
    )
    assert set(detailed) == set(runner.PYTHON_COMPONENTS)
    assert set(vars(GeneralSSABuilder())) == {"_performance_timings", "_phase_timings"}
    assert GeneralSSABuilder()._performance_timings is None
    assert GeneralSSABuilder()._phase_timings is None


def test_python_bit_masks_and_reference_analysis_remain_independent_of_rust_chk() -> None:
    from aether.analysis.dominators import (
        DominatorAnalysis,
        ReferenceDominatorAnalysis,
    )

    source = (ROOT / "src/aether/analysis/dominators.py").read_text(encoding="utf-8")
    production = source.split("class ReferenceDominatorAnalysis", 1)[0]

    assert DominatorAnalysis is not ReferenceDominatorAnalysis
    assert "_dominator_masks" in production
    assert "chk_idom" not in production
    assert "compiler-rs" not in production
    assert ReferenceDominatorAnalysis is not None


@pytest.mark.skipif(not COMPANION.is_file(), reason="release companion is not built")
def test_ordinary_response_has_no_instrumentation_and_session_persists() -> None:
    runner = _module("rust_3_12_runner_companion", RUNNER)
    from aether.ir.dto import ir_module_to_dto

    module, _digest = runner.base._load_module("benchmarks/arithmetic.ae")
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


@pytest.mark.skipif(not COMPANION.is_file(), reason="release companion is not built")
def test_instrumented_dual_lane_matches_ordinary_and_runs_required_checks() -> None:
    runner = _module("rust_3_12_runner_dual", RUNNER)
    module, _digest = runner.base._load_module("benchmarks/arithmetic.ae")
    builder_calls = 0
    verifier_calls = 0
    original_build = GeneralSSABuilder.build
    original_verify = SSAVerifier.verify

    def counted_build(self: GeneralSSABuilder, value: object):
        nonlocal builder_calls
        builder_calls += 1
        return original_build(self, value)  # type: ignore[arg-type]

    def counted_verify(self: SSAVerifier):
        nonlocal verifier_calls
        verifier_calls += 1
        return original_verify(self)

    with (
        PersistentRustSSALoweringClient(COMPANION) as ordinary_client,
        PersistentRustSSALoweringClient(
            COMPANION, characterize_performance=True
        ) as diagnostic_client,
        patch.object(GeneralSSABuilder, "build", counted_build),
        patch.object(SSAVerifier, "verify", counted_verify),
    ):
        ordinary, ordinary_report = lower_with_rust_authority(
            module, ordinary_client
        )
        instrumented, diagnostic_report = lower_with_rust_authority(
            module, diagnostic_client, characterize_performance=True
        )

    assert ssa_module_to_dto(ordinary, schema_version=2) == ssa_module_to_dto(
        instrumented, schema_version=2
    )
    assert ordinary_report.performance is None
    assert diagnostic_report.performance is not None
    assert set(diagnostic_report.performance.python_ssa_lowering_phases_seconds) == set(
        runner.PYTHON_COMPONENTS
    )
    assert builder_calls == 2
    assert verifier_calls >= 4


@pytest.mark.skipif(not COMPANION.is_file(), reason="release companion is not built")
def test_fail_closed_comparison_remains_active() -> None:
    runner = _module("rust_3_12_runner_fail_closed", RUNNER)
    module, _digest = runner.base._load_module("benchmarks/arithmetic.ae")
    with (
        PersistentRustSSALoweringClient(COMPANION) as client,
        patch("aether.ssa.shadow._difference", return_value=("$.forced", 1, 2)),
    ):
        with pytest.raises(SSAShadowFailure) as caught:
            lower_with_rust_authority(module, client)

    assert caught.value.report.classification == "semantic_mismatch"
    assert caught.value.report.phase == "canonical_comparison"
