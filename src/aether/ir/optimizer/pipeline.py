from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, Protocol

from aether.errors import AetherRuntimeError
from aether.ir.model import IRModule

from .algebraic_simplification import AlgebraicSimplifier
from .constant_folding import ConstantFolder
from .dead_code import DeadCodeEliminator
from .dead_store import DeadStoreEliminator
from .local_constant_propagation import LocalConstantPropagator
from .result import OptimizationResult, OptimizationTraceStep


class OptimizationPass(Protocol):
    def run(self, module: IRModule) -> OptimizationResult | IRModule:
        ...


OptimizationProfile = Literal["O0", "O1", "O2"]


class OptimizationConvergenceError(AetherRuntimeError):
    """Raised when an iterative optimizer pipeline does not reach a fixed point."""

    def __init__(self, max_iterations: int) -> None:
        super().__init__(
            "OptimizerPipeline did not reach a fixed point "
            f"after {max_iterations} iteration(s).",
            kind="optimizer",
        )
        self.max_iterations = max_iterations


class OptimizerPipeline:
    """Run IR optimization passes in a deterministic order."""

    def __init__(
        self,
        passes: Iterable[OptimizationPass] | None = None,
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
                ConstantFolder(),
                LocalConstantPropagator(),
                ConstantFolder(),
                AlgebraicSimplifier(),
                DeadCodeEliminator(),
                DeadStoreEliminator(),
                DeadCodeEliminator(),
            )
        )
        self._iterative = iterative
        self._max_iterations = max_iterations

    def run(self, module: IRModule) -> IRModule:
        if self._iterative:
            return self._run_iterative(module)
        optimized, _changed = self._run_iteration(module)
        return optimized

    def run_with_trace(self, module: IRModule) -> list[OptimizationTraceStep]:
        if self._iterative:
            return self._run_iterative_with_trace(module)

        trace = [OptimizationTraceStep("Lowered IR", module)]
        optimized, _changed = self._run_iteration(module, trace=trace)
        trace.append(OptimizationTraceStep("Final IR", optimized))
        return trace

    def _run_iterative(self, module: IRModule) -> IRModule:
        optimized = module
        for _iteration in range(1, self._max_iterations + 1):
            optimized, changed = self._run_iteration(optimized)
            if not changed:
                return optimized
        raise OptimizationConvergenceError(self._max_iterations)

    def _run_iterative_with_trace(self, module: IRModule) -> list[OptimizationTraceStep]:
        optimized = module
        trace = [OptimizationTraceStep("Lowered IR", optimized)]

        for iteration in range(1, self._max_iterations + 1):
            optimized, changed = self._run_iteration(
                optimized,
                trace=trace,
                iteration=iteration,
            )
            if not changed:
                trace.append(OptimizationTraceStep("Final IR", optimized))
                return trace

        raise OptimizationConvergenceError(self._max_iterations)

    def _run_iteration(
        self,
        module: IRModule,
        *,
        trace: list[OptimizationTraceStep] | None = None,
        iteration: int | None = None,
    ) -> tuple[IRModule, bool]:
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
                    OptimizationTraceStep(
                        name,
                        optimized,
                        changed=result.changed,
                        stats=dict(result.stats),
                    )
                )

        return optimized, changed

    @staticmethod
    def _run_pass(
        optimization_pass: OptimizationPass,
        module: IRModule,
    ) -> OptimizationResult:
        result = optimization_pass.run(module)
        if isinstance(result, OptimizationResult):
            return result
        return OptimizationResult(result, changed=result != module, stats={})


def build_optimizer_pipeline(level: OptimizationProfile | str) -> OptimizerPipeline:
    """Build the optimizer pipeline for a compiler-style optimization profile."""
    normalized = _normalize_optimization_profile(level)
    if normalized == "O0":
        return OptimizerPipeline(passes=())
    if normalized in {"O1", "O2"}:
        return OptimizerPipeline(iterative=True)
    raise ValueError(f"Unknown optimization profile '{level}'.")


def _normalize_optimization_profile(level: OptimizationProfile | str) -> OptimizationProfile:
    normalized = level.upper()
    if normalized in {"0", "O0"}:
        return "O0"
    if normalized in {"1", "O1"}:
        return "O1"
    if normalized in {"2", "O2"}:
        return "O2"
    raise ValueError(f"Unknown optimization profile '{level}'.")
