from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from aether.ir.model import IRModule

from .algebraic_simplification import AlgebraicSimplifier
from .constant_folding import ConstantFolder
from .dead_code import DeadCodeEliminator
from .dead_store import DeadStoreEliminator
from .local_constant_propagation import LocalConstantPropagator
from .result import OptimizationResult


class OptimizationPass(Protocol):
    def run(self, module: IRModule) -> OptimizationResult | IRModule:
        ...


class OptimizerPipeline:
    """Run IR optimization passes in a deterministic order."""

    def __init__(self, passes: Iterable[OptimizationPass] | None = None) -> None:
        self._passes = (
            tuple(passes)
            if passes is not None
            else (
                ConstantFolder(),
                LocalConstantPropagator(),
                ConstantFolder(),
                AlgebraicSimplifier(),
                DeadCodeEliminator(),
                DeadStoreEliminator(),
                DeadCodeEliminator(),
            )
        )

    def run(self, module: IRModule) -> IRModule:
        optimized = module
        for optimization_pass in self._passes:
            optimized = self._run_pass(optimization_pass, optimized).module
        return optimized

    def run_with_trace(self, module: IRModule) -> list[tuple[str, IRModule]]:
        optimized = module
        trace = [("Lowered IR", optimized)]

        for optimization_pass in self._passes:
            result = self._run_pass(optimization_pass, optimized)
            optimized = result.module
            trace.append((type(optimization_pass).__name__, optimized))

        trace.append(("Final IR", optimized))
        return trace

    @staticmethod
    def _run_pass(
        optimization_pass: OptimizationPass,
        module: IRModule,
    ) -> OptimizationResult:
        result = optimization_pass.run(module)
        if isinstance(result, OptimizationResult):
            return result
        return OptimizationResult(result, changed=result != module)
