"""Opt-in timing support for diagnostic LLVM generation profiles.

The production backend never creates a profiler.  Keeping the hook explicit
also prevents performance evidence from turning into logging or a cache.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator


@dataclass
class LLVMGenerationProfiler:
    """Accumulate wall time and call counts for one LLVM emission."""

    seconds: Counter[str] = field(default_factory=Counter)
    calls: Counter[str] = field(default_factory=Counter)

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            self.calls[name] += 1
            self.seconds[name] += perf_counter() - started

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        return {
            name: {"calls": self.calls[name], "seconds": self.seconds[name]}
            for name in sorted(self.calls)
        }

    @staticmethod
    def start() -> float:
        return perf_counter()

    def finish(self, name: str, started: float) -> None:
        self.calls[name] += 1
        self.seconds[name] += perf_counter() - started
