from pathlib import Path

from scripts.post_lifecycle_index_performance_reassessment import profile


ROOT = Path(__file__).resolve().parents[2]


def test_reassessment_records_stage_and_structural_lifecycle_evidence() -> None:
    result = profile(ROOT, workload_limit=1)
    assert result["scope"]["profile_records"] == 3
    assert set(result["stage_seconds"]) == {
        "frontend_parsing_type_analysis", "initial_ir_construction",
        "initial_ir_verification", "lifecycle_ownership_processing",
        "ssa_construction", "ssa_verification", "optimization",
        "llvm_backend_emit", "audit_test_harness_overhead",
    }
    assert result["lifecycle_index"]["index_constructions"] == result["lifecycle_index"]["full_ir_scans"]
    assert result["lifecycle_index"]["functions_indexed"] == result["lifecycle_index"]["index_constructions"]
    assert result["lifecycle_index"]["lifecycle_queries"] >= result["lifecycle_index"]["index_constructions"]
    assert result["expense_tracker_lifecycle_index"] == {}
    assert 99.0 <= sum(result["stage_percent_of_wall"].values()) <= 101.0


def test_prefix_audit_does_not_claim_profile_specific_ssa_is_shareable() -> None:
    result = profile(ROOT, workload_limit=1)
    prefix = result["prefix_sharing"]
    assert prefix["theoretical_upper_bound_saving_seconds"] >= 0
    assert prefix["realistically_recoverable_saving_seconds"] <= prefix["theoretical_upper_bound_saving_seconds"]
    assert prefix["base_ssa_shareable_without_clone_or_pipeline_change"] is False
