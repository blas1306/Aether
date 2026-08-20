from pathlib import Path

from aether.o2_evidence_materialization import (
    clear_materialization_cache,
    optimized_ssa,
)
from aether.optimization import optimization_profile
from aether.ssa.optimizer import build_ssa_optimizer_pipeline
from scripts.o2_13_performance_audit import audit
from scripts.o2_measurement import load_manifest


ROOT = Path(__file__).resolve().parents[2]


def test_audit_counts_structure_without_touching_canonical_evidence():
    before = (ROOT / "docs/compiler/o2_measurement_baseline.json").read_bytes()
    report = audit(ROOT, workload_limit=1)
    assert report["scope"] == {"workloads": 1, "full_manifest": False}
    assert report["operations"]["counts"]["initial_ir"] == 1
    assert report["operations"]["counts"]["json_rendering"] == 1
    assert report["native_compiler_invocations"] == 0
    assert report["native_executable_invocations"] == 0
    assert (ROOT / "docs/compiler/o2_measurement_baseline.json").read_bytes() == before


def test_o2_trace_does_not_mutate_shared_o0_ssa():
    config = load_manifest(ROOT)["workloads"][0]
    path = ROOT / config["path"]
    clear_materialization_cache()
    try:
        shared = optimized_ssa(path.read_text(), path, optimization_profile("O0"))
        before = repr(shared)
        traced = build_ssa_optimizer_pipeline("O2").run_with_trace(shared)
        assert repr(shared) == before
        assert traced[0].module is shared
        assert optimized_ssa(path.read_text(), path, optimization_profile("O0")) is shared
    finally:
        clear_materialization_cache()
