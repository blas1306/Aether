from __future__ import annotations

import pytest

from aether.ir import IntType, VoidType
from aether.ssa import (
    SSABasicBlock,
    SSAFunction,
    SSAModule,
    SSAParameter,
    SSAReturn,
)
from aether.ssa.optimizer import (
    SSAOptimizationConvergenceError,
    SSAOptimizationResult,
    SSAOptimizerPipeline,
)


def _empty_module() -> SSAModule:
    return SSAModule()


def _function(name: str) -> SSAFunction:
    return SSAFunction(
        name,
        [],
        VoidType(),
        [SSABasicBlock("entry", [SSAReturn()])],
    )


def _module_with_function(name: str = "main") -> SSAModule:
    return SSAModule([_function(name)])


class _NoOpPass:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        self.calls += 1
        return SSAOptimizationResult(module, changed=False, stats={"noop": 1})


class _AddFunctionUntilPass:
    def __init__(self, target_count: int) -> None:
        self.target_count = target_count
        self.calls = 0

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        self.calls += 1
        if len(module.functions) >= self.target_count:
            return SSAOptimizationResult(
                module,
                changed=False,
                stats={"added": 0},
            )

        index = len(module.functions)
        return SSAOptimizationResult(
            SSAModule([*module.functions, _function(f"generated{index}")]),
            changed=True,
            stats={"added": 1},
        )


class _RenameFirstFunctionPass:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        self.calls += 1
        [function] = module.functions
        renamed = SSAFunction(
            self.name,
            list(function.parameters),
            function.return_type,
            list(function.blocks),
            function.entry_block,
        )
        return SSAOptimizationResult(
            SSAModule([renamed, *module.functions[1:]]),
            changed=True,
            stats={self.name: 1},
        )


class _AddParameterPass:
    def run(self, module: SSAModule) -> SSAOptimizationResult:
        [function] = module.functions
        updated = SSAFunction(
            function.name,
            [*function.parameters, SSAParameter("value", IntType())],
            function.return_type,
            list(function.blocks),
            function.entry_block,
        )
        return SSAOptimizationResult(SSAModule([updated]), changed=True)


def test_empty_ssa_optimizer_pipeline_returns_same_module() -> None:
    module = _module_with_function()

    optimized = SSAOptimizerPipeline().run(module)

    assert optimized is module


def test_empty_ssa_optimizer_trace_has_initial_and_final_ssa() -> None:
    module = _module_with_function()

    trace = SSAOptimizerPipeline().run_with_trace(module)

    assert [step.label for step in trace] == ["Initial SSA", "Final SSA"]
    assert trace[0].module is module
    assert trace[0].changed is False
    assert trace[0].stats == {}
    assert trace[1].module is module
    assert trace[1].changed is False
    assert trace[1].stats == {}


def test_ssa_optimizer_pipeline_runs_fake_changing_pass() -> None:
    optimization_pass = _AddFunctionUntilPass(target_count=1)

    optimized = SSAOptimizerPipeline(passes=[optimization_pass]).run(_empty_module())

    assert [function.name for function in optimized.functions] == ["generated0"]
    assert optimization_pass.calls == 1


def test_ssa_optimizer_pipeline_runs_fake_unchanged_pass() -> None:
    module = _module_with_function()
    optimization_pass = _NoOpPass()

    optimized = SSAOptimizerPipeline(passes=[optimization_pass]).run(module)

    assert optimized is module
    assert optimization_pass.calls == 1


def test_ssa_optimizer_pipeline_iterative_converges() -> None:
    optimization_pass = _AddFunctionUntilPass(target_count=2)

    optimized = SSAOptimizerPipeline(
        passes=[optimization_pass],
        iterative=True,
    ).run(_empty_module())

    assert [function.name for function in optimized.functions] == [
        "generated0",
        "generated1",
    ]
    assert optimization_pass.calls == 3


def test_ssa_optimizer_pipeline_iterative_honors_max_iterations() -> None:
    optimization_pass = _AddFunctionUntilPass(target_count=3)
    pipeline = SSAOptimizerPipeline(
        passes=[optimization_pass],
        iterative=True,
        max_iterations=2,
    )

    with pytest.raises(SSAOptimizationConvergenceError, match="fixed point"):
        pipeline.run(_empty_module())

    assert optimization_pass.calls == 2


def test_ssa_optimizer_pipeline_trace_preserves_stats() -> None:
    trace = SSAOptimizerPipeline(
        passes=[_AddFunctionUntilPass(target_count=1)],
    ).run_with_trace(_empty_module())

    assert [step.label for step in trace] == [
        "Initial SSA",
        "_AddFunctionUntilPass",
        "Final SSA",
    ]
    assert trace[1].changed is True
    assert trace[1].stats == {"added": 1}


def test_ssa_optimizer_pipeline_respects_pass_order() -> None:
    module = _module_with_function("start")

    optimized = SSAOptimizerPipeline(
        passes=[
            _RenameFirstFunctionPass("first"),
            _RenameFirstFunctionPass("second"),
            _AddParameterPass(),
        ],
    ).run(module)

    [function] = optimized.functions
    assert function.name == "second"
    assert [parameter.name for parameter in function.parameters] == ["value"]
