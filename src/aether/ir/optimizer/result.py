from __future__ import annotations

from dataclasses import dataclass

from aether.ir.model import IRModule


@dataclass(frozen=True)
class OptimizationResult:
    """Result produced by a single IR optimization pass."""

    module: IRModule
    changed: bool
