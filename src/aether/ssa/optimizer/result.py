from __future__ import annotations

from dataclasses import dataclass, field

from aether.ssa.model import SSAModule


@dataclass(frozen=True)
class SSAOptimizationResult:
    """Result produced by a single SSA optimization pass."""

    module: SSAModule
    changed: bool
    stats: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SSAOptimizationTraceStep:
    """SSA optimizer trace entry for development inspection tools."""

    label: str
    module: SSAModule
    changed: bool = False
    stats: dict[str, int] = field(default_factory=dict)
