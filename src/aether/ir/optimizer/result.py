from __future__ import annotations

from dataclasses import dataclass, field

from aether.ir.model import IRModule


@dataclass(frozen=True)
class OptimizationResult:
    """Result produced by a single IR optimization pass."""

    module: IRModule
    changed: bool
    stats: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class OptimizationTraceStep:
    """IR optimizer trace entry for development inspection tools."""

    label: str
    module: IRModule
    changed: bool = False
    stats: dict[str, int] = field(default_factory=dict)
