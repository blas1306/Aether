from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aether.ir.dto import ir_module_to_dto
from aether.ir.lifecycle import LifecycleExpander, expand_lifecycle
from aether.ir.model import IRBasicBlock, IRConst, IRFunction, IRModule, IRReturn, IRValue
from aether.ir.types import IntType, VoidType
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.general_builder import GeneralSSABuilder
from aether.ssa.performance import characterize_python_ssa_only
from aether.ssa.shadow import PersistentRustSSALoweringClient, SSAShadowFailure, lower_with_rust_authority


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/characterize_rust_ssa_post_lifecycle.py"
CHECKER = ROOT / "scripts/check_rust_ssa_post_lifecycle_performance.py"
EVIDENCE = ROOT / "docs/compiler/rust_ssa_post_lifecycle_performance_characterization.json"
REPORT = ROOT / "docs/compiler/RUST_SSA_POST_LIFECYCLE_PERFORMANCE_CHARACTERIZATION.md"
COMPANION = ROOT / "compiler-rs/target/release/aether-ssa-shadow"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _small_module() -> IRModule:
    value = IRValue("value", IntType())
    return IRModule([
        IRFunction("small", [], VoidType(), [
            IRBasicBlock("entry", [IRConst(value, 1), IRReturn()])
        ])
    ])


def test_lifecycle_instrumentation_is_opt_in_complete_and_observational() -> None:
    module = _small_module()
    ordinary = expand_lifecycle(module)
    timings: dict[str, float] = {}
    instrumented = expand_lifecycle(module, performance_timings=timings)
    runner = _module("rust_3_14_lifecycle_phases", RUNNER)

    assert ir_module_to_dto(instrumented) == ir_module_to_dto(ordinary)
    assert set(timings) == set(runner.LIFECYCLE_PHASES)
    assert all(value >= 0 for value in timings.values())
    first_timings = dict(timings)
    repeated = expand_lifecycle(module, performance_timings=timings)
    assert ir_module_to_dto(repeated) == ir_module_to_dto(ordinary)
    assert all(timings[phase] >= value for phase, value in first_timings.items())
    assert (
        inspect.signature(expand_lifecycle).parameters["performance_timings"].kind
        is inspect.Parameter.KEYWORD_ONLY
    )


def test_detailed_observer_does_not_reintroduce_operand_rescans() -> None:
    module = _small_module()

    class CountingExpander(LifecycleExpander):
        walks = 0

        def _instruction_operand_occurrences(self, instruction):
            self.walks += 1
            return super()._instruction_operand_occurrences(instruction)

    timings: dict[str, float] = {}
    expander = CountingExpander(module, performance_timings=timings)
    expander.expand()

    assert expander.walks == 2
    assert set(timings) == set(_module("rust_3_14_runner_rescan", RUNNER).LIFECYCLE_PHASES)


def test_python_profile_contains_separate_non_additive_lifecycle_detail() -> None:
    value, profile = characterize_python_ssa_only(_small_module())
    ordinary = GeneralSSABuilder().build(_small_module())
    runner = _module("rust_3_14_profile", RUNNER)

    assert ssa_module_to_dto(value, schema_version=2) == ssa_module_to_dto(ordinary, schema_version=2)
    assert set(profile.python_lifecycle_phases_seconds) == set(runner.LIFECYCLE_PHASES)
    assert "python_lifecycle_phases_seconds" in profile.to_dict()
    assert sum(profile.python_lifecycle_phases_seconds.values()) <= (
        profile.phases_seconds["python_lifecycle_normalization"] + 1e-6
    )
    assert set(vars(GeneralSSABuilder())) == {"_performance_timings", "_phase_timings"}


def test_additive_and_subclassification_models_reconcile() -> None:
    runner = _module("rust_3_14_models", RUNNER)
    phases = {
        phase: (index + 1) / 1_000_000
        for index, phase in enumerate(sorted(
            set().union(*[
                {"rust_lifecycle_normalization", "rust_ssa_lowering"},
                {"python_lifecycle_normalization", "python_ssa_lowering"},
                {"rust_owned_ssa_verification", "imported_rust_python_verification", "python_builder_verification", "input_snapshot_integrity_check"},
                {"initial_ir_snapshot_preparation", "rust_transport_serialization", "rust_input_parsing", "rust_schema_v2_materialization", "companion_process_startup", "request_response_transport_and_serialization", "response_json_decode", "rust_schema_v2_import", "python_result_dto_serialization"},
                {"python_result_canonicalization", "rust_result_canonicalization", "canonical_comparison"},
                {"rust_orchestration_unattributed"},
            ])
        ))
    }
    lifecycle = {phase: 1e-7 for phase in runner.LIFECYCLE_PHASES}
    lowering = {"python_renaming": 2e-7}
    residual = 1e-6
    sample = {"phases_seconds": phases, "python_lifecycle_phases_seconds": lifecycle,
              "python_ssa_lowering_phases_seconds": lowering,
              "measured_component_sum_seconds": sum(phases.values()),
              "residual_unattributed_seconds": residual,
              "total_wall_seconds": sum(phases.values()) + residual}
    model = runner._category_model([sample])
    sub = runner._subclassification([sample], model)

    assert model["reconciled_percent"] == pytest.approx(100.0)
    assert model["percent_sum"] == pytest.approx(100.0)
    assert sub["percent_sum"] == pytest.approx(100.0)


def test_checked_in_evidence_is_characterized() -> None:
    record = _module("rust_3_14_checker", CHECKER).build_record(EVIDENCE, REPORT)

    assert record["decision"] == "RUST_SSA_POST_LIFECYCLE_PERFORMANCE_CHARACTERIZED"
    assert all(record["checks"].values())


def test_checker_rejects_corrupted_raw_summary(tmp_path: Path) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence["ordinary_workloads"][0]["summary"]["python_only"]["median_seconds"] += 1
    path = tmp_path / "corrupted.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")

    record = _module("rust_3_14_checker_corrupt", CHECKER).build_record(path, REPORT)

    assert record["checks"]["three_routes_ordinary_raw_samples"] is False


@pytest.mark.skipif(not COMPANION.is_file(), reason="release companion is not built")
def test_ordinary_response_shape_and_persistent_session_are_unchanged() -> None:
    runner = _module("rust_3_14_session", RUNNER)
    from aether.ir.dto import ir_module_to_dto

    module, _digest = runner.base._load_module("benchmarks/arithmetic.ae")
    payload = json.dumps(ir_module_to_dto(module), separators=(",", ":")).encode()
    with PersistentRustSSALoweringClient(COMPANION) as client:
        first = client.lower(payload)
        pid = client.process_id
        second = client.lower(payload)
        second_pid = client.process_id
        starts = client.process_start_count
        requests = client.request_count

    assert set(first) == {"ok", "ssa"}
    assert set(second) == {"ok", "ssa"}
    assert second_pid == pid
    assert starts == 1
    assert requests == 2


@pytest.mark.skipif(not COMPANION.is_file(), reason="release companion is not built")
def test_dual_lane_instrumentation_preserves_ssa_and_fail_closed() -> None:
    runner = _module("rust_3_14_dual", RUNNER)
    module, _digest = runner.base._load_module("benchmarks/arithmetic.ae")
    with (
        PersistentRustSSALoweringClient(COMPANION) as ordinary_client,
        PersistentRustSSALoweringClient(COMPANION, characterize_performance=True) as diagnostic_client,
    ):
        ordinary, ordinary_report = lower_with_rust_authority(module, ordinary_client)
        diagnostic, diagnostic_report = lower_with_rust_authority(module, diagnostic_client, characterize_performance=True)
    assert ssa_module_to_dto(ordinary, schema_version=2) == ssa_module_to_dto(diagnostic, schema_version=2)
    assert ordinary_report.performance is None
    assert set(diagnostic_report.performance.python_lifecycle_phases_seconds) == set(runner.LIFECYCLE_PHASES)

    with (
        PersistentRustSSALoweringClient(COMPANION) as client,
        patch("aether.ssa.shadow._difference", return_value=("$.forced", 1, 2)),
        pytest.raises(SSAShadowFailure),
    ):
        lower_with_rust_authority(module, client)
