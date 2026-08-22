from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/characterize_rust_ssa_post_3_8a.py"
CHECKER = ROOT / "scripts/check_rust_ssa_post_3_8a_performance.py"
EVIDENCE = (
    ROOT / "docs/compiler/rust_ssa_post_3_8a_performance_characterization.json"
)
REPORT = ROOT / "docs/compiler/RUST_SSA_POST_3_8A_PERFORMANCE_CHARACTERIZATION.md"
REMOVED = {
    "python_shadow_input_reconstruction",
    "python_shadow_verification",
    "rust_result_dto_serialization",
}


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_category_accounting_is_mutually_exclusive_and_complete() -> None:
    runner = _module("rust_3_8b_runner", RUNNER)
    phases = {
        phase: (index + 1) / 1000
        for index, phase in enumerate(
            sorted(
                phase
                for phase in runner.PHASE_CATEGORIES
                if phase not in REMOVED
                and phase
                not in {
                    "rust_transport_and_compute_combined",
                    "clock_domain_rounding_adjustment",
                    "residual_unattributed",
                }
            )
        )
    }
    residual = 0.001
    sample = {
        "phases_seconds": phases,
        "residual_unattributed_seconds": residual,
        "total_wall_seconds": sum(phases.values()) + residual,
    }
    workloads = [
        {"samples": {"rust_authority_python_shadow": [sample]}}
    ]

    model = runner._category_model(workloads)

    assert model["percent_sum"] == pytest.approx(100.0)
    assert sum(
        row["observed_seconds"] for row in model["categories"].values()
    ) == pytest.approx(sample["total_wall_seconds"])
    assert set(model["observed_phases"]) == set(phases)


def test_checked_in_post_3_8a_evidence_is_characterized() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    checked = _module("rust_3_8b_checker", CHECKER).build_record(
        EVIDENCE,
        REPORT,
        revision=evidence["qualification_revision"],
    )

    assert checked["decision"] == "RUST_SSA_POST_3_8A_PERFORMANCE_CHARACTERIZED"
    assert all(checked["checks"].values())
    assert evidence["methodology"]["measured_rounds_per_workload"] >= 3
    assert evidence["methodology"]["warmup_rounds_per_workload"] >= 1
    assert evidence["production_invariants"]["behavior_changed"] is False


def test_removed_rust_3_8a_phases_are_recorded_but_never_measured() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    measured = {row["phase"] for row in evidence["bottleneck_ranking"]}
    removed = {
        row["phase"]
        for row in evidence["phase_inventory"]["removed_by_rust_3_8a"]
    }

    assert removed == REMOVED
    assert measured.isdisjoint(REMOVED)
    for workload in evidence["workloads"]:
        for sample in workload["samples"]["rust_authority_python_shadow"]:
            assert set(sample["phases_seconds"]).isdisjoint(REMOVED)


def test_candidate_audit_covers_required_inventory_without_optimization() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    candidates = evidence["candidate_audit"]

    assert len(candidates) == 10
    assert all(row["classification"] in {
        "LOW_RISK_REDUNDANCY",
        "LOW_RISK_ARCHITECTURAL",
        "ALGORITHMIC_CORE",
        "SAFETY_BOUNDARY",
        "SHADOW_POLICY",
        "NOT_WORTH_OPTIMIZING",
    } for row in candidates)
    assert evidence["production_invariants"]["optimization_implemented"] is False
