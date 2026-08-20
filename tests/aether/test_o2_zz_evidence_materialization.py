from pathlib import Path

from aether.o2_evidence_materialization import (
    clear_materialization_cache,
    materialization_counts,
    optimized_ssa,
)
from aether.optimization import optimization_profile


def test_identical_evidence_is_built_once_per_process(monkeypatch) -> None:
    import aether.o2_evidence_materialization as materialization

    sentinel = object()
    calls = []
    monkeypatch.setattr(
        materialization,
        "_build_optimized_ssa",
        lambda source, path, profile: calls.append((source, path, profile)) or sentinel,
    )
    clear_materialization_cache()
    try:
        first = optimized_ssa("fn main() {}", Path("same.ae"), optimization_profile("O2"))
        second = optimized_ssa("fn main() {}", Path("same.ae"), optimization_profile("O2"))
        assert first is sentinel and second is sentinel
        assert len(calls) == 1
        assert materialization_counts() == {
            "requests": 2,
            "ssa_builds": 1,
            "ssa_builds_O2": 1,
            "cache_hits": 1,
        }
    finally:
        clear_materialization_cache()


def test_content_and_full_profile_invalidate_materialized_evidence(monkeypatch) -> None:
    import aether.o2_evidence_materialization as materialization

    calls = []
    monkeypatch.setattr(
        materialization,
        "_build_optimized_ssa",
        lambda source, path, profile: calls.append((source, path, profile)) or object(),
    )
    clear_materialization_cache()
    try:
        path = Path("workload.ae")
        optimized_ssa("source-a", path, optimization_profile("O1"))
        optimized_ssa("source-b", path, optimization_profile("O1"))
        optimized_ssa("source-b", path, optimization_profile("O2"))
        assert len(calls) == 3
    finally:
        clear_materialization_cache()
