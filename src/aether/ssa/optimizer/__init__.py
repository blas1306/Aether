from __future__ import annotations

from .algebraic_simplification import SSAAlgebraicSimplifier
from .constant_folding import SSAConstantFolder
from .dead_code import SSADeadCodeEliminator
from .dead_phi import DeadPhiEliminator
from .pipeline import (
    SSAOptimizationConvergenceError,
    SSAOptimizationPass,
    SSAOptimizerPipeline,
)
from .result import SSAOptimizationResult, SSAOptimizationTraceStep
from .trivial_phi import TrivialPhiEliminator

__all__ = [
    "DeadPhiEliminator",
    "SSAAlgebraicSimplifier",
    "SSAConstantFolder",
    "SSADeadCodeEliminator",
    "SSAOptimizationConvergenceError",
    "SSAOptimizationPass",
    "SSAOptimizationResult",
    "SSAOptimizationTraceStep",
    "SSAOptimizerPipeline",
    "TrivialPhiEliminator",
]
