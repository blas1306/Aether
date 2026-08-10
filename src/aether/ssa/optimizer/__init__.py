from __future__ import annotations

from .algebraic_simplification import SSAAlgebraicSimplifier
from .constant_folding import SSAConstantFolder
from .dead_code import SSADeadCodeEliminator
from .dead_phi import DeadPhiEliminator
from .global_constant_propagation import SSAGlobalConstantPropagator
from .proven_bounds import ProvenBoundsCheckEliminator
from .licm import LoopInvariantCodeMotion
from .local_arc import LocalARCEliminator
from .pipeline import (
    SSAOptimizationConvergenceError,
    SSAOptimizationPass,
    SSAOptimizerPipeline,
    build_ssa_optimizer_pipeline,
)
from .result import SSAOptimizationResult, SSAOptimizationTraceStep
from .sccp import SCCPAnalyzer, SCCPResult, SCCPTransformer
from .sccp_pass import SCCPPass
from .trivial_phi import TrivialPhiEliminator

__all__ = [
    "DeadPhiEliminator",
    "SCCPAnalyzer",
    "SCCPPass",
    "SCCPResult",
    "SCCPTransformer",
    "SSAAlgebraicSimplifier",
    "SSAConstantFolder",
    "SSADeadCodeEliminator",
    "SSAGlobalConstantPropagator",
    "ProvenBoundsCheckEliminator",
    "LoopInvariantCodeMotion",
    "LocalARCEliminator",
    "SSAOptimizationConvergenceError",
    "SSAOptimizationPass",
    "SSAOptimizationResult",
    "SSAOptimizationTraceStep",
    "SSAOptimizerPipeline",
    "build_ssa_optimizer_pipeline",
    "TrivialPhiEliminator",
]
