from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from aether.errors import AetherRuntimeError
from aether.ssa.model import SSAModule

from .dead_code import SSADeadCodeEliminator
from .dead_phi import DeadPhiEliminator
from .result import SSAOptimizationResult, SSAOptimizationTraceStep
from .trivial_phi import TrivialPhiEliminator


class SSAOptimizationPass(Protocol):
    def run(self, module: SSAModule) -> SSAOptimizationResult | SSAModule:
        ...


class SSAOptimizationConvergenceError(AetherRuntimeError):
    """Raised when an iterative SSA optimizer pipeline does not reach a fixed point."""

    def __init__(self, max_iterations: int) -> None:
        super().__init__(
            "SSAOptimizerPipeline did not reach a fixed point "
            f"after {max_iterations} iteration(s).",
            kind="ssa-optimizer",
        )
        self.max_iterations = max_iterations


class SSAOptimizerPipeline:
    """Run SSA optimization passes in a deterministic order."""

    def __init__(
        self,
        passes: Iterable[SSAOptimizationPass] | None = None,
        *,
        iterative: bool = False,
        max_iterations: int = 10,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least 1.")
        self._passes = (
            tuple(passes)
            if passes is not None
            else (
                TrivialPhiEliminator(),
                DeadPhiEliminator(),
                SSADeadCodeEliminator(),
            )
        )
        self._iterative = iterative
        self._max_iterations = max_iterations

    def run(self, module: SSAModule) -> SSAModule:
        if self._iterative:
            return self._run_iterative(module)
        optimized, _changed = self._run_iteration(module)
        return optimized

    def run_with_trace(self, module: SSAModule) -> list[SSAOptimizationTraceStep]:
        if self._iterative:
            return self._run_iterative_with_trace(module)

        trace = [SSAOptimizationTraceStep("Initial SSA", module)]
        optimized, _changed = self._run_iteration(module, trace=trace)
        trace.append(SSAOptimizationTraceStep("Final SSA", optimized))
        return trace

    def _run_iterative(self, module: SSAModule) -> SSAModule:
        optimized = module
        for _iteration in range(1, self._max_iterations + 1):
            optimized, changed = self._run_iteration(optimized)
            if not changed:
                return optimized
        raise SSAOptimizationConvergenceError(self._max_iterations)

    def _run_iterative_with_trace(
        self,
        module: SSAModule,
    ) -> list[SSAOptimizationTraceStep]:
        optimized = module
        trace = [SSAOptimizationTraceStep("Initial SSA", optimized)]

        for iteration in range(1, self._max_iterations + 1):
            optimized, changed = self._run_iteration(
                optimized,
                trace=trace,
                iteration=iteration,
            )
            if not changed:
                trace.append(SSAOptimizationTraceStep("Final SSA", optimized))
                return trace

        raise SSAOptimizationConvergenceError(self._max_iterations)

    def _run_iteration(
        self,
        module: SSAModule,
        *,
        trace: list[SSAOptimizationTraceStep] | None = None,
        iteration: int | None = None,
    ) -> tuple[SSAModule, bool]:
        optimized = module
        changed = False
        for optimization_pass in self._passes:
            result = self._run_pass(optimization_pass, optimized)
            optimized = result.module
            changed = changed or result.changed
            if trace is not None:
                name = type(optimization_pass).__name__
                if iteration is not None:
                    name = f"Iteration {iteration} / {name}"
                trace.append(
                    SSAOptimizationTraceStep(
                        name,
                        optimized,
                        changed=result.changed,
                        stats=dict(result.stats),
                    )
                )

        return optimized, changed

    @staticmethod
    def _run_pass(
        optimization_pass: SSAOptimizationPass,
        module: SSAModule,
    ) -> SSAOptimizationResult:
        result = optimization_pass.run(module)
        if isinstance(result, SSAOptimizationResult):
            return result
        return SSAOptimizationResult(result, changed=result != module, stats={})
