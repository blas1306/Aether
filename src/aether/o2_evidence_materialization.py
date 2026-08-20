"""Session-local materialization shared by the read-only O2 audit tools.

The optimizer mutates its inputs while constructing the final module.  Only the
fully optimized, verified result is cached here.  O2 audits must treat the
returned module as immutable; analyses may allocate their own CFG/result data
but must not edit the SSA module.

The key includes source contents, the canonical diagnostic path, and the full
optimization profile.  Consequently edits and configuration changes invalidate
an entry without a persistent disk cache or explicit invalidation protocol.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path

from .benchmark import _optimized_ssa as _build_optimized_ssa
from .optimization import OptimizationProfile
from .ssa.model import SSAModule


_COUNTS: Counter[str] = Counter()


@lru_cache(maxsize=None)
def _materialize(
    source: str, canonical_path: str, profile: OptimizationProfile
) -> SSAModule:
    _COUNTS["ssa_builds"] += 1
    _COUNTS[f"ssa_builds_{profile.name}"] += 1
    return _build_optimized_ssa(source, Path(canonical_path), profile)


def optimized_ssa(
    source: str, path: Path, profile: OptimizationProfile
) -> SSAModule:
    """Return one verified SSA snapshot per content/path/profile in this process."""
    _COUNTS["requests"] += 1
    before = _materialize.cache_info().hits
    module = _materialize(source, str(path.resolve()), profile)
    if _materialize.cache_info().hits != before:
        _COUNTS["cache_hits"] += 1
    return module


def materialization_counts() -> dict[str, int]:
    """Expose stable structural counters for performance regression tests."""
    return dict(_COUNTS)


def clear_materialization_cache() -> None:
    """Clear process-local evidence state (primarily for isolated tests)."""
    _materialize.cache_clear()
    _COUNTS.clear()
