from __future__ import annotations

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
    "SSAConstantFolder",
    "SSADeadCodeEliminator",
    "SSAOptimizationConvergenceError",
    "SSAOptimizationPass",
    "SSAOptimizationResult",
    "SSAOptimizationTraceStep",
    "SSAOptimizerPipeline",
    "TrivialPhiEliminator",
]
