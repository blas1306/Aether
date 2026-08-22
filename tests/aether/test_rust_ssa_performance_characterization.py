from __future__ import annotations

from pathlib import Path
import json

import pytest

import aether.ssa.shadow as shadow_module
from aether.ir.model import IRModule
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.performance import characterize_python_ssa_only
from aether.ssa.shadow import (
    PersistentRustSSALoweringClient,
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    SSAShadowFailure,
    diagnostic_lower_with_rust_authority_without_python_shadow,
    lower_with_rust_authority,
)


EMPTY_SSA = {
    "schema_version": 2,
    "representation": "aether_ssa",
    "functions": [],
    "structs": [],
}
ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/compiler/rust_ssa_authority_performance_characterization.json"
REPORT = ROOT / "docs/compiler/RUST_SSA_AUTHORITY_PERFORMANCE_CHARACTERIZATION.md"


class CharacterizedClient:
    process_start_count = 1
    last_startup_seconds = 0.0
    last_response_decode_seconds = 0.0

    def __init__(self, response=None) -> None:
        self.request_count = 0
        self.response = response or {
            "ok": True,
            "ssa": EMPTY_SSA,
            "performance": {
                "clock": "std::time::Instant",
                "unit": "nanoseconds",
                "phases": {
                    "rust_input_parsing": 100,
                    "rust_lifecycle_normalization": 200,
                    "rust_ssa_lowering": 300,
                    "rust_owned_ssa_verification": 400,
                    "rust_schema_v2_materialization": 500,
                    "rust_orchestration_unattributed": 100,
                },
                "request_compute_total": 1600,
            },
        }

    def lower(self, _payload: bytes):
        self.request_count += 1
        return self.response


def _assert_consistent(profile) -> None:
    assert profile.measured_component_sum_seconds == pytest.approx(
        sum(profile.phases_seconds.values())
    )
    assert profile.total_wall_seconds == pytest.approx(
        profile.measured_component_sum_seconds
        + profile.residual_unattributed_seconds
    )


def test_opt_in_instrumentation_is_complete_and_does_not_change_returned_ssa() -> None:
    client = CharacterizedClient()
    ordinary, ordinary_report = lower_with_rust_authority(IRModule(), client)
    instrumented, instrumented_report = lower_with_rust_authority(
        IRModule(), client, characterize_performance=True
    )

    assert ordinary_report.performance is None
    assert ssa_module_to_dto(ordinary) == ssa_module_to_dto(instrumented) == EMPTY_SSA
    profile = instrumented_report.performance
    assert profile is not None
    assert {
        "initial_ir_snapshot_preparation",
        "rust_transport_serialization",
        "companion_process_startup",
        "rust_input_parsing",
        "rust_lifecycle_normalization",
        "rust_ssa_lowering",
        "rust_owned_ssa_verification",
        "rust_schema_v2_materialization",
        "request_response_transport_and_serialization",
        "response_json_decode",
        "rust_schema_v2_import",
        "imported_rust_python_verification",
        "python_lifecycle_normalization",
        "python_ssa_lowering",
        "python_builder_verification",
        "python_result_dto_serialization",
        "rust_result_canonicalization",
        "python_result_canonicalization",
        "canonical_comparison",
    } <= set(profile.phases_seconds)
    assert "python_shadow_input_reconstruction" not in profile.phases_seconds
    assert "python_shadow_verification" not in profile.phases_seconds
    assert "rust_result_dto_serialization" not in profile.phases_seconds
    _assert_consistent(profile)


def test_python_only_profile_matches_uninstrumented_builder_result() -> None:
    ordinary = shadow_module.GeneralSSABuilder().build(IRModule())
    instrumented, profile = characterize_python_ssa_only(IRModule())

    assert ssa_module_to_dto(ordinary) == ssa_module_to_dto(instrumented)
    assert profile.mode == "python_ssa_only"
    assert "python_lifecycle_normalization" in profile.phases_seconds
    assert "python_ssa_lowering" in profile.phases_seconds
    assert "python_builder_verification" in profile.phases_seconds
    _assert_consistent(profile)


def test_diagnostic_rust_only_is_not_an_authority_mode_and_skips_python(monkeypatch) -> None:
    def forbidden_python(_self, _module):
        raise AssertionError("diagnostic Rust-only unexpectedly ran Python SSA")

    monkeypatch.setattr(shadow_module.GeneralSSABuilder, "build", forbidden_python)
    result, report = diagnostic_lower_with_rust_authority_without_python_shadow(
        IRModule(), CharacterizedClient()
    )

    assert ssa_module_to_dto(result) == EMPTY_SSA
    assert report.classification == "diagnostic_rust_only"
    assert report.performance is not None
    assert "RUST_SSA_AUTHORITY_WITHOUT_PYTHON_SHADOW" not in {
        mode.name for mode in SSALoweringAuthorityMode
    }
    assert (
        SSALoweringAuthorityConfiguration().mode
        is SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
    )


def test_instrumented_failure_still_fails_closed() -> None:
    client = CharacterizedClient({"ok": False, "error": "controlled"})
    with pytest.raises(SSAShadowFailure) as caught:
        lower_with_rust_authority(
            IRModule(), client, characterize_performance=True
        )
    assert caught.value.report.classification == "rust_lowering_or_verifier_failure"
    assert client.request_count == 1


def test_companion_performance_switch_is_explicit_and_diagnostic(tmp_path: Path) -> None:
    executable = tmp_path / "aether-ssa-shadow"
    production = PersistentRustSSALoweringClient(executable)
    diagnostic = PersistentRustSSALoweringClient(
        executable, characterize_performance=True
    )

    assert production.command == (str(executable), "--persistent")
    assert diagnostic.command == (
        str(executable),
        "--persistent",
        "--characterize-performance",
    )


def test_checked_in_evidence_has_complete_repeated_stratified_measurements() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    assert evidence["milestone"] == "RUST-3.7b"
    assert evidence["decision"] == "RUST_SSA_PERFORMANCE_CHARACTERIZED"
    assert evidence["qualification_revision"] == (
        "808f6a4ce97025ed203bd6f411ff7291db449211"
    )
    assert {row["category"] for row in evidence["workload_manifest"]} == {
        "tiny/scalar",
        "numeric iterative",
        "collection-heavy",
        "struct-heavy",
        "class/interface-heavy",
        "function-value/indirect-call",
        "exception/lifecycle-heavy",
        "realistic medium program",
    }
    assert evidence["methodology"]["warmup_rounds_per_workload"] >= 1
    assert evidence["methodology"]["measured_rounds_per_workload"] >= 3
    assert evidence["methodology"]["statistics"] == ["median", "min", "max"]
    assert [row["blocks"] for row in evidence["deep_cfg_scaling"]] == [993, 1000, 5000]
    assert evidence["persistent_companion"]["process_startups"] == 1
    assert evidence["persistent_companion"]["requests"] > 1

    categories = evidence["cost_model"]["categories"]
    assert sum(row["percent_of_dual_lane"] for row in categories.values()) == pytest.approx(100)
    assert evidence["optimization_candidates"][-1]["authorized_in_rust_3_7b"] is False
    assert REPORT.read_text(encoding="utf-8").startswith(
        "# Rust SSA authority performance characterization — RUST-3.7b"
    )

    rounds = evidence["methodology"]["measured_rounds_per_workload"]
    for workload in evidence["workloads"]:
        for mode in (
            "python_ssa_only",
            "diagnostic_rust_only",
            "rust_authority_python_shadow",
        ):
            samples = workload["samples"][mode]
            assert len(samples) == rounds
            for sample in samples:
                assert sample["total_wall_seconds"] == pytest.approx(
                    sample["measured_component_sum_seconds"]
                    + sample["residual_unattributed_seconds"]
                )
