from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from aether.ir.model import IRModule

from .constant_folding import ConstantFolder


class OptimizationPass(Protocol):
    def run(self, module: IRModule) -> IRModule:
        ...


class OptimizerPipeline:
    """Run IR optimization passes in a deterministic order."""

    def __init__(self, passes: Iterable[OptimizationPass] | None = None) -> None:
        self._passes = tuple(passes) if passes is not None else (ConstantFolder(),)

    def run(self, module: IRModule) -> IRModule:
        optimized = module
        for optimization_pass in self._passes:
            optimized = optimization_pass.run(optimized)
        return optimized
