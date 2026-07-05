from __future__ import annotations

from .algebraic_simplification import SSAAlgebraicSimplifier
from .constant_folding import SSAConstantFolder
from .dead_code import SSADeadCodeEliminator
from .dead_phi import DeadPhiEliminator
from .global_constant_propagation import SSAGlobalConstantPropagator
from .pipeline import (
    SSAOptimizationConvergenceError,
    SSAOptimizationPass,
    SSAOptimizerPipeline,
)
from .result import SSAOptimizationResult, SSAOptimizationTraceStep
from .sccp import SCCPAnalyzer, SCCPResult, SCCPTransformer
from .trivial_phi import TrivialPhiEliminator

__all__ = [
    "DeadPhiEliminator",
    "SCCPAnalyzer",
    "SCCPResult",
    "SCCPTransformer",
    "SSAAlgebraicSimplifier",
    "SSAConstantFolder",
    "SSADeadCodeEliminator",
    "SSAGlobalConstantPropagator",
    "SSAOptimizationConvergenceError",
    "SSAOptimizationPass",
    "SSAOptimizationResult",
    "SSAOptimizationTraceStep",
    "SSAOptimizerPipeline",
    "TrivialPhiEliminator",
]
