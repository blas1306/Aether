from __future__ import annotations

import pytest

from aether.ir import BoolType, IntType, VoidType
from aether.ssa import (
    SSABasicBlock,
    SSABinaryOp,
    SSABranch,
    SSACall,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAJump,
    SSAModule,
    SSAParameter,
    SSAPhi,
    SSAReturn,
    SSAValue,
    SSAVerifier,
)
from aether.ssa.optimizer import (
    DeadPhiEliminator,
    SSADeadCodeEliminator,
    SSAOptimizationConvergenceError,
    SSAOptimizationResult,
    SSAOptimizerPipeline,
    TrivialPhiEliminator,
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


def _verify(module: SSAModule) -> SSAModule:
    return SSAVerifier(module).verify()


def _phi_merge_module(*, use: str = "unused") -> SSAModule:
    int_type = IntType()
    bool_type = BoolType()
    condition = SSAValue("condition", bool_type)
    then_value = SSAValue("then_value", int_type)
    else_value = SSAValue("else_value", int_type)
    phi_value = SSAValue("phi_value", int_type)
    fallback = SSAValue("fallback", int_type)
    one = SSAValue("one", int_type)
    binary_result = SSAValue("binary_result", int_type)

    merge_instructions = [
        SSAPhi(phi_value, (("then0", then_value), ("else0", else_value))),
    ]
    return_type = int_type

    if use == "return":
        merge_instructions.append(SSAReturn(phi_value))
    elif use == "binary":
        merge_instructions.extend(
            [
                SSAConst(one, 1),
                SSABinaryOp(binary_result, "add", phi_value, one),
                SSAReturn(binary_result),
            ]
        )
    else:
        merge_instructions.extend([SSAConst(fallback, 0), SSAReturn(fallback)])

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                return_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(condition, True),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAConst(then_value, 1), SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAConst(else_value, 2), SSAJump("merge0")]),
                    SSABasicBlock("merge0", merge_instructions),
                ],
            )
        ]
    )
    return _verify(module)


def _branch_condition_phi_module() -> SSAModule:
    bool_type = BoolType()
    entry_condition = SSAValue("entry_condition", bool_type)
    then_value = SSAValue("then_value", bool_type)
    else_value = SSAValue("else_value", bool_type)
    phi_value = SSAValue("phi_value", bool_type)

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                VoidType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(entry_condition, True),
                            SSABranch(entry_condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAConst(then_value, True), SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAConst(else_value, False), SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(phi_value, (("then0", then_value), ("else0", else_value))),
                            SSABranch(phi_value, "true0", "false0"),
                        ],
                    ),
                    SSABasicBlock("true0", [SSAReturn()]),
                    SSABasicBlock("false0", [SSAReturn()]),
                ],
            )
        ]
    )
    return _verify(module)


def _phi_chain_module() -> SSAModule:
    int_type = IntType()
    bool_type = BoolType()
    condition = SSAValue("condition", bool_type)
    then_value = SSAValue("then_value", int_type)
    else_value = SSAValue("else_value", int_type)
    first_phi = SSAValue("first_phi", int_type)
    second_phi = SSAValue("second_phi", int_type)
    fallback = SSAValue("fallback", int_type)

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(condition, True),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAConst(then_value, 1), SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAConst(else_value, 2), SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(first_phi, (("then0", then_value), ("else0", else_value))),
                            SSAJump("exit0"),
                        ],
                    ),
                    SSABasicBlock(
                        "exit0",
                        [
                            SSAPhi(second_phi, (("merge0", first_phi),)),
                            SSAConst(fallback, 0),
                            SSAReturn(fallback),
                        ],
                    ),
                ],
            )
        ]
    )
    return _verify(module)


def _call_argument_phi_module() -> SSAModule:
    int_type = IntType()
    bool_type = BoolType()
    condition = SSAValue("condition", bool_type)
    then_value = SSAValue("then_value", int_type)
    else_value = SSAValue("else_value", int_type)
    phi_value = SSAValue("phi_value", int_type)
    parameter = SSAParameter("value", int_type)

    module = SSAModule(
        [
            SSAFunction(
                "sink",
                [parameter],
                VoidType(),
                [SSABasicBlock("entry", [SSAReturn()])],
            ),
            SSAFunction(
                "main",
                [],
                VoidType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(condition, True),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAConst(then_value, 1), SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAConst(else_value, 2), SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(phi_value, (("then0", then_value), ("else0", else_value))),
                            SSACall("sink", (phi_value,)),
                            SSAReturn(),
                        ],
                    ),
                ],
            ),
        ]
    )
    return _verify(module)


def _trivial_phi_module(*, use: str = "return") -> SSAModule:
    int_type = IntType()
    bool_type = BoolType()
    condition = SSAValue("condition", bool_type)
    common = SSAValue("common", int_type)
    phi_value = SSAValue("phi_value", int_type)
    one = SSAValue("one", int_type)
    binary_result = SSAValue("binary_result", int_type)
    compare_result = SSAValue("compare_result", bool_type)

    merge_instructions = [
        SSAPhi(phi_value, (("then0", common), ("else0", common))),
    ]
    return_type = int_type

    if use == "binary":
        merge_instructions.extend(
            [
                SSAConst(one, 1),
                SSABinaryOp(binary_result, "add", phi_value, phi_value),
                SSAReturn(binary_result),
            ]
        )
    elif use == "compare":
        return_type = bool_type
        merge_instructions.extend(
            [
                SSACompareOp(compare_result, "eq", phi_value, common),
                SSAReturn(compare_result),
            ]
        )
    else:
        merge_instructions.append(SSAReturn(phi_value))

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                return_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(condition, True),
                            SSAConst(common, 7),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAJump("merge0")]),
                    SSABasicBlock("merge0", merge_instructions),
                ],
            )
        ]
    )
    return _verify(module)


def _trivial_bool_phi_branch_module() -> SSAModule:
    bool_type = BoolType()
    entry_condition = SSAValue("entry_condition", bool_type)
    common = SSAValue("common", bool_type)
    phi_value = SSAValue("phi_value", bool_type)

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                VoidType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(entry_condition, True),
                            SSAConst(common, False),
                            SSABranch(entry_condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(phi_value, (("then0", common), ("else0", common))),
                            SSABranch(phi_value, "true0", "false0"),
                        ],
                    ),
                    SSABasicBlock("true0", [SSAReturn()]),
                    SSABasicBlock("false0", [SSAReturn()]),
                ],
            )
        ]
    )
    return _verify(module)


def _trivial_phi_into_another_phi_module() -> SSAModule:
    int_type = IntType()
    bool_type = BoolType()
    condition = SSAValue("condition", bool_type)
    common = SSAValue("common", int_type)
    first_phi = SSAValue("first_phi", int_type)
    second_phi = SSAValue("second_phi", int_type)

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(condition, True),
                            SSAConst(common, 7),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(first_phi, (("then0", common), ("else0", common))),
                            SSABranch(condition, "exit0", "alt0"),
                        ],
                    ),
                    SSABasicBlock("alt0", [SSAJump("exit0")]),
                    SSABasicBlock(
                        "exit0",
                        [
                            SSAPhi(
                                second_phi,
                                (("merge0", first_phi), ("alt0", common)),
                            ),
                            SSAReturn(second_phi),
                        ],
                    ),
                ],
            )
        ]
    )
    return _verify(module)


def _trivial_phi_then_dead_phi_module() -> SSAModule:
    int_type = IntType()
    bool_type = BoolType()
    condition = SSAValue("condition", bool_type)
    common = SSAValue("common", int_type)
    trivial_phi = SSAValue("trivial_phi", int_type)
    dead_phi = SSAValue("dead_phi", int_type)

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(condition, True),
                            SSAConst(common, 7),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(trivial_phi, (("then0", common), ("else0", common))),
                            SSAPhi(
                                dead_phi,
                                (("then0", trivial_phi), ("else0", common)),
                            ),
                            SSAReturn(common),
                        ],
                    ),
                ],
            )
        ]
    )
    return _verify(module)


def _self_referential_phi_module() -> SSAModule:
    int_type = IntType()
    bool_type = BoolType()
    condition = SSAValue("condition", bool_type)
    common = SSAValue("common", int_type)
    phi_value = SSAValue("phi_value", int_type)

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(condition, True),
                            SSAConst(common, 7),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(phi_value, (("then0", common), ("else0", phi_value))),
                            SSAReturn(phi_value),
                        ],
                    ),
                ],
            )
        ]
    )
    return _verify(module)


def _dead_binary_chain_module() -> SSAModule:
    int_type = IntType()
    seed = SSAValue("seed", int_type)
    first = SSAValue("first", int_type)
    second = SSAValue("second", int_type)

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                VoidType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(seed, 1),
                            SSABinaryOp(first, "add", seed, seed),
                            SSABinaryOp(second, "add", first, first),
                            SSAReturn(),
                        ],
                    )
                ],
            )
        ]
    )
    return _verify(module)


def _used_indirectly_module() -> SSAModule:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    total = SSAValue("total", int_type)

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(left, 1),
                            SSAConst(right, 2),
                            SSABinaryOp(total, "add", left, right),
                            SSAReturn(total),
                        ],
                    )
                ],
            )
        ]
    )
    return _verify(module)


def _unused_call_result_module() -> SSAModule:
    int_type = IntType()
    value = SSAValue("value", int_type)
    call_result = SSAValue("call_result", int_type)

    module = SSAModule(
        [
            SSAFunction(
                "source",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(value, 1),
                            SSAReturn(value),
                        ],
                    )
                ],
            ),
            SSAFunction(
                "main",
                [],
                VoidType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSACall("source", (), call_result),
                            SSAReturn(),
                        ],
                    )
                ],
            ),
        ]
    )
    return _verify(module)


def _branch_jump_return_module() -> SSAModule:
    bool_type = BoolType()
    condition = SSAValue("condition", bool_type)

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                VoidType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(condition, True),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAJump("exit0")]),
                    SSABasicBlock("else0", [SSAJump("exit0")]),
                    SSABasicBlock("exit0", [SSAReturn()]),
                ],
            )
        ]
    )
    return _verify(module)


def _call_argument_const_module() -> SSAModule:
    int_type = IntType()
    argument = SSAValue("argument", int_type)
    parameter = SSAParameter("value", int_type)

    module = SSAModule(
        [
            SSAFunction(
                "sink",
                [parameter],
                VoidType(),
                [SSABasicBlock("entry", [SSAReturn()])],
            ),
            SSAFunction(
                "main",
                [],
                VoidType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(argument, 1),
                            SSACall("sink", (argument,)),
                            SSAReturn(),
                        ],
                    )
                ],
            ),
        ]
    )
    return _verify(module)


def _instruction_names(module: SSAModule) -> list[str]:
    return [
        type(instruction).__name__
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    ]


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

    assert [step.label for step in trace] == [
        "Initial SSA",
        "TrivialPhiEliminator",
        "DeadPhiEliminator",
        "SSADeadCodeEliminator",
        "Final SSA",
    ]
    assert trace[0].module is module
    assert trace[0].changed is False
    assert trace[0].stats == {}
    assert trace[1].module is module
    assert trace[1].changed is False
    assert trace[1].stats == {"removed_trivial_phis": 0, "rewritten_uses": 0}
    assert trace[2].module is module
    assert trace[2].changed is False
    assert trace[2].stats == {"removed_phis": 0}
    assert trace[3].module is module
    assert trace[3].changed is False
    assert trace[3].stats == {"removed": 0}
    assert trace[4].module is module
    assert trace[4].changed is False
    assert trace[4].stats == {}


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


def test_trivial_phi_eliminator_removes_phi_used_by_return() -> None:
    module = _trivial_phi_module(use="return")

    result = TrivialPhiEliminator().run(module)

    assert result.changed is True
    assert result.stats == {"removed_trivial_phis": 1, "rewritten_uses": 1}
    assert "SSAPhi" not in _instruction_names(result.module)
    [function] = result.module.functions
    return_instruction = function.blocks[-1].instructions[-1]
    assert return_instruction == SSAReturn(SSAValue("common", IntType()))
    _verify(result.module)


def test_trivial_phi_eliminator_removes_phi_used_by_binary_op() -> None:
    module = _trivial_phi_module(use="binary")

    result = TrivialPhiEliminator().run(module)

    assert result.changed is True
    assert result.stats == {"removed_trivial_phis": 1, "rewritten_uses": 2}
    [function] = result.module.functions
    binary_instruction = function.blocks[-1].instructions[-2]
    assert isinstance(binary_instruction, SSABinaryOp)
    assert binary_instruction.left == SSAValue("common", IntType())
    assert binary_instruction.right == SSAValue("common", IntType())
    _verify(result.module)


def test_trivial_phi_eliminator_rewrites_compare_operands() -> None:
    module = _trivial_phi_module(use="compare")

    result = TrivialPhiEliminator().run(module)

    assert result.changed is True
    assert result.stats == {"removed_trivial_phis": 1, "rewritten_uses": 1}
    [function] = result.module.functions
    compare_instruction = function.blocks[-1].instructions[-2]
    assert isinstance(compare_instruction, SSACompareOp)
    assert compare_instruction.left == SSAValue("common", IntType())
    assert compare_instruction.right == SSAValue("common", IntType())
    _verify(result.module)


def test_trivial_phi_eliminator_removes_phi_used_by_branch_condition() -> None:
    module = _trivial_bool_phi_branch_module()

    result = TrivialPhiEliminator().run(module)

    assert result.changed is True
    assert result.stats == {"removed_trivial_phis": 1, "rewritten_uses": 1}
    [function] = result.module.functions
    branch_instruction = function.blocks[3].instructions[0]
    assert branch_instruction == SSABranch(
        SSAValue("common", BoolType()),
        "true0",
        "false0",
    )
    _verify(result.module)


def test_trivial_phi_eliminator_rewrites_phi_incoming_values() -> None:
    module = _trivial_phi_into_another_phi_module()

    result = TrivialPhiEliminator().run(module)

    assert result.changed is True
    assert result.stats == {"removed_trivial_phis": 1, "rewritten_uses": 1}
    [function] = result.module.functions
    remaining_phi = function.blocks[-1].instructions[0]
    assert isinstance(remaining_phi, SSAPhi)
    assert remaining_phi.incoming == (
        ("merge0", SSAValue("common", IntType())),
        ("alt0", SSAValue("common", IntType())),
    )
    _verify(result.module)


def test_trivial_phi_eliminator_rewrites_call_arguments() -> None:
    int_type = IntType()
    bool_type = BoolType()
    condition = SSAValue("condition", bool_type)
    common = SSAValue("common", int_type)
    phi_value = SSAValue("phi_value", int_type)
    parameter = SSAParameter("value", int_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "sink",
                    [parameter],
                    VoidType(),
                    [SSABasicBlock("entry", [SSAReturn()])],
                ),
                SSAFunction(
                    "main",
                    [],
                    VoidType(),
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(condition, True),
                                SSAConst(common, 7),
                                SSABranch(condition, "then0", "else0"),
                            ],
                        ),
                        SSABasicBlock("then0", [SSAJump("merge0")]),
                        SSABasicBlock("else0", [SSAJump("merge0")]),
                        SSABasicBlock(
                            "merge0",
                            [
                                SSAPhi(
                                    phi_value,
                                    (("then0", common), ("else0", common)),
                                ),
                                SSACall("sink", (phi_value,)),
                                SSAReturn(),
                            ],
                        ),
                    ],
                ),
            ]
        )
    )

    result = TrivialPhiEliminator().run(module)

    assert result.changed is True
    assert result.stats == {"removed_trivial_phis": 1, "rewritten_uses": 1}
    call_instruction = result.module.functions[1].blocks[-1].instructions[0]
    assert call_instruction == SSACall("sink", (common,))
    _verify(result.module)


def test_default_pipeline_removes_trivial_phi_then_dead_phi() -> None:
    module = _trivial_phi_then_dead_phi_module()

    optimized = SSAOptimizerPipeline().run(module)

    assert "SSAPhi" not in _instruction_names(optimized)
    _verify(optimized)


def test_trivial_phi_eliminator_reports_stats() -> None:
    result = TrivialPhiEliminator().run(_trivial_phi_module(use="binary"))

    assert result.stats["removed_trivial_phis"] == 1
    assert result.stats["rewritten_uses"] == 2


def test_trivial_phi_eliminator_keeps_phi_with_distinct_incoming_values() -> None:
    module = _phi_merge_module(use="return")

    result = TrivialPhiEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed_trivial_phis": 0, "rewritten_uses": 0}
    assert "SSAPhi" in _instruction_names(result.module)
    _verify(result.module)


def test_trivial_phi_eliminator_keeps_self_referential_phi() -> None:
    module = _self_referential_phi_module()

    result = TrivialPhiEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed_trivial_phis": 0, "rewritten_uses": 0}
    assert "SSAPhi" in _instruction_names(result.module)
    _verify(result.module)


def test_trivial_phi_eliminator_does_not_change_module_without_phis() -> None:
    module = _module_with_function()

    result = TrivialPhiEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed_trivial_phis": 0, "rewritten_uses": 0}
    _verify(result.module)


def test_trivial_phi_eliminator_does_not_touch_non_phi_instructions() -> None:
    module = _module_with_function()
    original_instructions = list(module.functions[0].blocks[0].instructions)

    result = TrivialPhiEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.module.functions[0].blocks[0].instructions == original_instructions
    _verify(result.module)


def test_ssa_dead_code_eliminator_removes_unused_const() -> None:
    int_type = IntType()
    unused = SSAValue("unused", int_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    VoidType(),
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(unused, 1),
                                SSAReturn(),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    result = SSADeadCodeEliminator().run(module)

    assert result.changed is True
    assert result.stats == {"removed": 1}
    assert _instruction_names(result.module) == ["SSAReturn"]
    _verify(result.module)


def test_ssa_dead_code_eliminator_removes_unused_binary_op() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    unused_binary = SSAValue("unused_binary", int_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    VoidType(),
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(left, 1),
                                SSAConst(right, 2),
                                SSABinaryOp(unused_binary, "add", left, right),
                                SSAReturn(),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    result = SSADeadCodeEliminator().run(module)

    assert result.changed is True
    assert result.stats == {"removed": 1}
    assert "SSABinaryOp" not in _instruction_names(result.module)
    _verify(result.module)


def test_ssa_dead_code_eliminator_removes_unused_compare_op() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    unused_compare = SSAValue("unused_compare", BoolType())
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    VoidType(),
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(left, 1),
                                SSAConst(right, 2),
                                SSACompareOp(unused_compare, "lt", left, right),
                                SSAReturn(),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    result = SSADeadCodeEliminator().run(module)

    assert result.changed is True
    assert result.stats == {"removed": 1}
    assert "SSACompareOp" not in _instruction_names(result.module)
    _verify(result.module)


def test_ssa_dead_code_eliminator_removes_unused_phi() -> None:
    module = _phi_merge_module()

    result = SSADeadCodeEliminator().run(module)

    assert result.changed is True
    assert result.stats == {"removed": 1}
    assert "SSAPhi" not in _instruction_names(result.module)
    _verify(result.module)


def test_default_iterative_pipeline_removes_dead_instruction_chain() -> None:
    module = _dead_binary_chain_module()

    optimized = SSAOptimizerPipeline(iterative=True).run(module)

    assert _instruction_names(optimized) == ["SSAReturn"]
    _verify(optimized)


def test_ssa_dead_code_eliminator_keeps_returned_value() -> None:
    int_type = IntType()
    returned = SSAValue("returned", int_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    int_type,
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(returned, 1),
                                SSAReturn(returned),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    result = SSADeadCodeEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed": 0}
    _verify(result.module)


def test_ssa_dead_code_eliminator_keeps_branch_condition() -> None:
    module = _branch_jump_return_module()

    result = SSADeadCodeEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed": 0}
    assert "SSAConst" in _instruction_names(result.module)
    _verify(result.module)


def test_ssa_dead_code_eliminator_keeps_call_argument() -> None:
    module = _call_argument_const_module()

    result = SSADeadCodeEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed": 0}
    assert "SSAConst" in _instruction_names(result.module)
    _verify(result.module)


def test_ssa_dead_code_eliminator_does_not_remove_unused_call() -> None:
    module = _unused_call_result_module()

    result = SSADeadCodeEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed": 0}
    assert "SSACall" in _instruction_names(result.module)
    _verify(result.module)


def test_ssa_dead_code_eliminator_does_not_remove_branch_jump_return() -> None:
    module = _branch_jump_return_module()

    result = SSADeadCodeEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert "SSABranch" in _instruction_names(result.module)
    assert "SSAJump" in _instruction_names(result.module)
    assert "SSAReturn" in _instruction_names(result.module)
    _verify(result.module)


def test_ssa_dead_code_eliminator_does_not_change_module_without_dead_code() -> None:
    module = _used_indirectly_module()

    result = SSADeadCodeEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed": 0}
    _verify(result.module)


def test_ssa_dead_code_eliminator_keeps_indirectly_used_instructions() -> None:
    module = _used_indirectly_module()

    result = SSADeadCodeEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert "SSAConst" in _instruction_names(result.module)
    assert "SSABinaryOp" in _instruction_names(result.module)
    _verify(result.module)


def test_dead_phi_eliminator_removes_unused_phi() -> None:
    module = _phi_merge_module()

    result = DeadPhiEliminator().run(module)

    assert result.changed is True
    assert result.stats == {"removed_phis": 1}
    assert "SSAPhi" not in _instruction_names(result.module)
    _verify(result.module)


def test_dead_phi_eliminator_keeps_phi_used_by_return() -> None:
    module = _phi_merge_module(use="return")

    result = DeadPhiEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed_phis": 0}
    assert "SSAPhi" in _instruction_names(result.module)
    _verify(result.module)


def test_dead_phi_eliminator_keeps_phi_used_by_binary_op() -> None:
    module = _phi_merge_module(use="binary")

    result = DeadPhiEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed_phis": 0}
    assert "SSAPhi" in _instruction_names(result.module)
    _verify(result.module)


def test_dead_phi_eliminator_keeps_phi_used_by_branch_condition() -> None:
    module = _branch_condition_phi_module()

    result = DeadPhiEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed_phis": 0}
    assert "SSAPhi" in _instruction_names(result.module)
    _verify(result.module)


def test_dead_phi_eliminator_keeps_phi_used_by_another_phi() -> None:
    module = _phi_chain_module()

    result = DeadPhiEliminator().run(module)

    assert result.changed is True
    assert result.stats == {"removed_phis": 1}
    assert _instruction_names(result.module).count("SSAPhi") == 1
    _verify(result.module)


def test_default_iterative_pipeline_removes_dead_phi_chain() -> None:
    module = _phi_chain_module()

    optimized = SSAOptimizerPipeline(iterative=True).run(module)

    assert "SSAPhi" not in _instruction_names(optimized)
    _verify(optimized)


def test_dead_phi_eliminator_reports_removed_phi_stats() -> None:
    result = DeadPhiEliminator().run(_phi_merge_module())

    assert result.stats["removed_phis"] == 1


def test_default_ssa_optimizer_trace_shows_dead_phi_changes() -> None:
    module = _phi_merge_module()

    trace = SSAOptimizerPipeline().run_with_trace(module)

    assert [step.label for step in trace] == [
        "Initial SSA",
        "TrivialPhiEliminator",
        "DeadPhiEliminator",
        "SSADeadCodeEliminator",
        "Final SSA",
    ]
    assert trace[1].changed is False
    assert trace[1].stats == {"removed_trivial_phis": 0, "rewritten_uses": 0}
    assert trace[2].changed is True
    assert trace[2].stats == {"removed_phis": 1}
    assert trace[3].changed is True
    assert trace[3].stats == {"removed": 2}
    _verify(trace[-1].module)


def test_dead_phi_eliminator_does_not_remove_non_phi_instructions() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    unused_binary = SSAValue("unused_binary", int_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    int_type,
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(left, 1),
                                SSAConst(right, 2),
                                SSABinaryOp(unused_binary, "add", left, right),
                                SSAReturn(left),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    result = DeadPhiEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert "SSABinaryOp" in _instruction_names(result.module)
    _verify(result.module)


def test_dead_phi_eliminator_does_not_change_module_without_phis() -> None:
    module = _module_with_function()

    result = DeadPhiEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed_phis": 0}
    _verify(result.module)


def test_dead_phi_eliminator_keeps_phi_used_by_call_argument() -> None:
    module = _call_argument_phi_module()

    result = DeadPhiEliminator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"removed_phis": 0}
    assert "SSAPhi" in _instruction_names(result.module)
    _verify(result.module)
