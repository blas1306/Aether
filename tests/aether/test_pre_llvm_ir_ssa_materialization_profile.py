from pathlib import Path

from scripts.pre_llvm_ir_ssa_materialization_profile import LEVELS, profile


ROOT = Path(__file__).resolve().parents[2]


def test_profiler_records_complete_pre_llvm_structure_without_writing_evidence():
    canonical = ROOT / "docs/compiler/o2_measurement_baseline.json"
    before = canonical.read_bytes()
    timing, structural = profile(ROOT, workload_limit=1, include_cprofile=False)

    assert timing["scope"] == {
        "manifest_workloads": 1, "supported_workloads": 1, "profile_records": 3
    }
    assert {row["profile"] for row in timing["records"]} == set(LEVELS)
    assert timing["aggregate_operation_counts"]["parse"] == 1
    assert timing["aggregate_operation_counts"]["type_check"] == 1
    assert timing["aggregate_operation_counts"]["initial_ir_lowering"] == 3
    assert timing["aggregate_operation_counts"]["ssa_build"] == 3
    assert timing["aggregate_operation_counts"]["ssa_optimizer_run_O0"] == 1
    assert timing["aggregate_operation_counts"]["ssa_optimizer_run_O1"] == 1
    assert timing["aggregate_operation_counts"]["ssa_optimizer_run_O2"] == 1
    assert all(row["ast_nodes"] > 0 for row in structural["records"])
    assert canonical.read_bytes() == before


def test_timing_is_diagnostic_and_excluded_from_structural_records():
    timing, structural = profile(ROOT, workload_limit=1, include_cprofile=False)
    assert timing["aggregate_stage_seconds"]["initial_ir_lowering"] >= 0
    assert all("timings_seconds" not in row for row in structural["records"])
    assert structural["methodology"].endswith("TIMING_IS_LOCAL_SIDECAR")
