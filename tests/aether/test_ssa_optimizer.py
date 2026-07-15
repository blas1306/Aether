from __future__ import annotations

import pytest

from aether.ir import BoolType, DoubleType, FloatType, IntType, IRType, StringType, VoidType
from aether.ssa import (
    SSABasicBlock,
    SSABinaryOp,
    SSABranch,
    SSACall,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAInstruction,
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
    SCCPPass,
    SSAAlgebraicSimplifier,
    SSAConstantFolder,
    SSADeadCodeEliminator,
    SSAGlobalConstantPropagator,
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


def _constant_phi_module(
    then_constant: int,
    else_constant: int | None,
    *,
    use: str = "return",
) -> SSAModule:
    int_type = IntType()
    parameter = SSAParameter("parameter", int_type)
    condition = SSAValue("condition", BoolType())
    then_value = SSAValue("then_value", int_type)
    else_value = SSAValue("else_value", int_type)
    phi_value = SSAValue("phi_value", int_type)
    one = SSAValue("one", int_type)
    result = SSAValue("result", int_type)

    else_instructions: list[SSAInstruction] = []
    else_incoming = parameter
    if else_constant is not None:
        else_instructions.append(SSAConst(else_value, else_constant))
        else_incoming = else_value
    else_instructions.append(SSAJump("merge0"))

    merge_instructions: list[SSAInstruction] = [
        SSAPhi(phi_value, (("then0", then_value), ("else0", else_incoming))),
    ]
    if use == "binary":
        merge_instructions.extend(
            [
                SSAConst(one, 1),
                SSABinaryOp(result, "add", phi_value, one),
                SSAReturn(result),
            ]
        )
    elif use == "call":
        merge_instructions.extend(
            [
                SSACall("sink", (phi_value,)),
                SSAReturn(),
            ]
        )
    else:
        merge_instructions.append(SSAReturn(phi_value))

    functions = [
        SSAFunction(
            "main",
            [parameter],
            VoidType() if use == "call" else int_type,
            [
                SSABasicBlock(
                    "entry",
                    [
                        SSAConst(condition, True),
                        SSABranch(condition, "then0", "else0"),
                    ],
                ),
                SSABasicBlock("then0", [SSAConst(then_value, then_constant), SSAJump("merge0")]),
                SSABasicBlock("else0", else_instructions),
                SSABasicBlock("merge0", merge_instructions),
            ],
        )
    ]
    if use == "call":
        sink_parameter = SSAParameter("value", int_type)
        functions.insert(
            0,
            SSAFunction(
                "sink",
                [sink_parameter],
                VoidType(),
                [SSABasicBlock("entry", [SSAReturn()])],
            ),
        )

    return _verify(SSAModule(functions))


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
    alternate = SSAValue("alternate", int_type)
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
                            SSABranch(condition, "path0", "alt0"),
                        ],
                    ),
                    SSABasicBlock(
                        "path0",
                        [SSABranch(condition, "then0", "else0")],
                    ),
                    SSABasicBlock("then0", [SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(trivial_phi, (("then0", common), ("else0", common))),
                            SSAJump("final0"),
                        ],
                    ),
                    SSABasicBlock(
                        "alt0",
                        [SSAConst(alternate, 9), SSAJump("final0")],
                    ),
                    SSABasicBlock(
                        "final0",
                        [
                            SSAPhi(
                                dead_phi,
                                (("merge0", trivial_phi), ("alt0", alternate)),
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
                            SSAJump("loop0"),
                        ],
                    ),
                    SSABasicBlock(
                        "loop0",
                        [
                            SSAPhi(phi_value, (("entry", common), ("loop0", phi_value))),
                            SSABranch(condition, "loop0", "exit0"),
                        ],
                    ),
                    SSABasicBlock("exit0", [SSAReturn(phi_value)]),
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


def _sccp_phi_cleanup_module() -> SSAModule:
    int_type = IntType()
    condition = SSAValue("condition", BoolType())
    parameter = SSAParameter("parameter", int_type)
    else_value = SSAValue("else_value", int_type)
    phi_value = SSAValue("phi_value", int_type)

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [parameter],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(condition, True),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAConst(else_value, 2), SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(
                                phi_value,
                                (("then0", parameter), ("else0", else_value)),
                            ),
                            SSAReturn(phi_value),
                        ],
                    ),
                ],
            )
        ]
    )
    return _verify(module)


def _constant_binary_module(
    operator: str,
    left_value: object,
    right_value: object,
    *,
    result_type: IRType | None = None,
) -> SSAModule:
    int_type = IntType()
    actual_result_type = result_type or int_type
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    result = SSAValue("result", actual_result_type)

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                actual_result_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(left, left_value),
                            SSAConst(right, right_value),
                            SSABinaryOp(result, operator, left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )
    return _verify(module)


def _constant_compare_module(
    operator: str,
    left_value: object,
    right_value: object,
) -> SSAModule:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    result = SSAValue("result", BoolType())

    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                BoolType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(left, left_value),
                            SSAConst(right, right_value),
                            SSACompareOp(result, operator, left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )
    return _verify(module)


def _integer_identity_module(
    operator: str,
    constant_value: int,
    *,
    constant_on_left: bool = False,
    result_type: IRType | None = None,
    verify: bool = True,
) -> SSAModule:
    int_type = IntType()
    actual_result_type = result_type or int_type
    parameter = SSAParameter("x", int_type)
    constant = SSAValue("constant", int_type)
    result = SSAValue("result", actual_result_type)
    left = constant if constant_on_left else parameter
    right = parameter if constant_on_left else constant
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [parameter],
                actual_result_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(constant, constant_value),
                            SSABinaryOp(result, operator, left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )
    if not verify:
        return module
    return _verify(module)


def _folded_result_instruction(module: SSAModule) -> SSAInstruction:
    return module.functions[0].blocks[0].instructions[2]


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


@pytest.mark.parametrize(
    ("operator", "left", "right", "result_type", "expected"),
    [
        ("add", 2, 3, IntType(), 5),
        ("sub", 8, 3, IntType(), 5),
        ("mul", 4, 3, IntType(), 12),
        ("div", 5, 2, DoubleType(), 2.5),
        ("mod", 5, 3, IntType(), 2),
        ("rem", 5, 3, IntType(), 2),
    ],
)
def test_ssa_constant_folder_folds_binary_ops(
    operator: str,
    left: int,
    right: int,
    result_type: IRType,
    expected: int | float,
) -> None:
    module = _constant_binary_module(
        operator,
        left,
        right,
        result_type=result_type,
    )

    result = SSAConstantFolder().run(module)

    assert result.changed is True
    assert result.stats == {"folded": 1}
    folded = _folded_result_instruction(result.module)
    assert folded == SSAConst(SSAValue("result", result_type), expected)
    _verify(result.module)


@pytest.mark.parametrize(
    ("operator", "left", "right", "expected"),
    [
        ("lt", 2, 3, True),
        ("le", 3, 3, True),
        ("gt", 4, 3, True),
        ("ge", 3, 3, True),
        ("eq", 3, 3, True),
        ("ne", 3, 4, True),
    ],
)
def test_ssa_constant_folder_folds_compare_ops(
    operator: str,
    left: int,
    right: int,
    expected: bool,
) -> None:
    module = _constant_compare_module(operator, left, right)

    result = SSAConstantFolder().run(module)

    assert result.changed is True
    assert result.stats == {"folded": 1}
    folded = _folded_result_instruction(result.module)
    assert folded == SSAConst(SSAValue("result", BoolType()), expected)
    _verify(result.module)


def test_ssa_constant_folder_does_not_fold_string_binary_ops() -> None:
    string_type = StringType()
    left = SSAValue("left", string_type)
    right = SSAValue("right", string_type)
    result_value = SSAValue("result", string_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    string_type,
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(left, "a"),
                                SSAConst(right, "b"),
                                SSABinaryOp(result_value, "add", left, right),
                                SSAReturn(result_value),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    result = SSAConstantFolder().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"folded": 0}


def test_ssa_constant_folder_does_not_fold_string_compare_ops() -> None:
    string_type = StringType()
    left = SSAValue("left", string_type)
    right = SSAValue("right", string_type)
    result_value = SSAValue("result", BoolType())
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    BoolType(),
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(left, "a"),
                                SSAConst(right, "a"),
                                SSACompareOp(result_value, "eq", left, right),
                                SSAReturn(result_value),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    result = SSAConstantFolder().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"folded": 0}


def test_ssa_constant_folder_folds_chain_in_single_pass() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    first = SSAValue("first", int_type)
    second = SSAValue("second", int_type)
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
                                SSAConst(left, 2),
                                SSAConst(right, 3),
                                SSABinaryOp(first, "add", left, right),
                                SSABinaryOp(second, "mul", first, right),
                                SSAReturn(second),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    result = SSAConstantFolder().run(module)

    assert result.changed is True
    assert result.stats == {"folded": 2}
    assert module.functions[0].blocks[0].instructions[2] == SSABinaryOp(
        first,
        "add",
        left,
        right,
    )
    assert result.module.functions[0].blocks[0].instructions[2] == SSAConst(first, 5)
    assert result.module.functions[0].blocks[0].instructions[3] == SSAConst(second, 15)
    _verify(result.module)


def test_default_pipeline_folding_then_dce_removes_dead_constants() -> None:
    module = _constant_binary_module("add", 2, 3)

    optimized = SSAOptimizerPipeline().run(module)

    [function] = optimized.functions
    assert function.blocks[0].instructions == [
        SSAConst(SSAValue("result", IntType()), 5),
        SSAReturn(SSAValue("result", IntType())),
    ]
    _verify(optimized)


def test_default_iterative_pipeline_folds_trivial_phi_result_chain() -> None:
    int_type = IntType()
    bool_type = BoolType()
    condition = SSAValue("condition", bool_type)
    common = SSAValue("common", int_type)
    one = SSAValue("one", int_type)
    phi_value = SSAValue("phi_value", int_type)
    result = SSAValue("result", int_type)
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
                                SSAConst(condition, True),
                                SSAConst(common, 4),
                                SSAConst(one, 1),
                                SSABranch(condition, "then0", "else0"),
                            ],
                        ),
                        SSABasicBlock("then0", [SSAJump("merge0")]),
                        SSABasicBlock("else0", [SSAJump("merge0")]),
                        SSABasicBlock(
                            "merge0",
                            [
                                SSAPhi(phi_value, (("then0", common), ("else0", common))),
                                SSABinaryOp(result, "add", phi_value, one),
                                SSAReturn(result),
                            ],
                        ),
                    ],
                )
            ]
        )
    )

    optimized = SSAOptimizerPipeline(iterative=True).run(module)

    [function] = optimized.functions
    assert function.blocks[-1].instructions == [
        SSAConst(result, 5),
        SSAReturn(result),
    ]
    assert "SSAPhi" not in _instruction_names(optimized)
    _verify(optimized)


@pytest.mark.parametrize("operator", ["div", "mod", "rem"])
def test_ssa_constant_folder_does_not_fold_division_or_modulo_by_zero(
    operator: str,
) -> None:
    result_type: IRType = DoubleType() if operator == "div" else IntType()
    module = _constant_binary_module(operator, 5, 0, result_type=result_type)

    result = SSAConstantFolder().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"folded": 0}
    assert isinstance(_folded_result_instruction(result.module), SSABinaryOp)
    _verify(result.module)


def test_ssa_constant_folder_does_not_fold_unknown_operand() -> None:
    int_type = IntType()
    parameter = SSAParameter("value", int_type)
    one = SSAValue("one", int_type)
    result_value = SSAValue("result", int_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [parameter],
                    int_type,
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(one, 1),
                                SSABinaryOp(result_value, "add", parameter, one),
                                SSAReturn(result_value),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    result = SSAConstantFolder().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"folded": 0}
    _verify(result.module)


def test_ssa_constant_folder_does_not_fold_call() -> None:
    module = _unused_call_result_module()

    result = SSAConstantFolder().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"folded": 0}
    assert "SSACall" in _instruction_names(result.module)
    _verify(result.module)


def test_ssa_constant_folder_does_not_fold_phi() -> None:
    module = _phi_merge_module(use="return")

    result = SSAConstantFolder().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"folded": 0}
    assert "SSAPhi" in _instruction_names(result.module)
    _verify(result.module)


def test_ssa_constant_folder_does_not_change_module_without_fold() -> None:
    module = _module_with_function()

    result = SSAConstantFolder().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"folded": 0}
    _verify(result.module)


def test_ssa_global_constant_propagator_replaces_phi_with_same_constants() -> None:
    module = _constant_phi_module(7, 7)

    result = SSAGlobalConstantPropagator().run(module)

    assert result.changed is True
    assert result.stats == {"propagated": 1}
    [function] = result.module.functions
    assert function.blocks[-1].instructions == [
        SSAConst(SSAValue("phi_value", IntType()), 7),
        SSAReturn(SSAValue("phi_value", IntType())),
    ]
    _verify(result.module)


def test_ssa_global_constant_propagator_keeps_phi_with_different_constants() -> None:
    module = _constant_phi_module(7, 8)

    result = SSAGlobalConstantPropagator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"propagated": 0}
    assert "SSAPhi" in _instruction_names(result.module)
    _verify(result.module)


def test_ssa_global_constant_propagator_keeps_phi_with_unknown_incoming() -> None:
    module = _constant_phi_module(7, None)

    result = SSAGlobalConstantPropagator().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"propagated": 0}
    assert "SSAPhi" in _instruction_names(result.module)
    _verify(result.module)


def test_ssa_global_constant_propagator_folds_after_phi_constant() -> None:
    module = _constant_phi_module(7, 7, use="binary")

    result = SSAGlobalConstantPropagator().run(module)

    assert result.changed is True
    assert result.stats == {"propagated": 2}
    [function] = result.module.functions
    assert function.blocks[-1].instructions == [
        SSAConst(SSAValue("phi_value", IntType()), 7),
        SSAConst(SSAValue("one", IntType()), 1),
        SSAConst(SSAValue("result", IntType()), 8),
        SSAReturn(SSAValue("result", IntType())),
    ]
    _verify(result.module)


def test_default_pipeline_global_constant_propagation_then_dce() -> None:
    module = _constant_phi_module(7, 7, use="binary")

    optimized = SSAOptimizerPipeline().run(module)

    [function] = optimized.functions
    assert function.blocks[-1].instructions == [
        SSAConst(SSAValue("result", IntType()), 8),
        SSAReturn(SSAValue("result", IntType())),
    ]
    assert "SSAPhi" not in _instruction_names(optimized)
    assert "SSABinaryOp" not in _instruction_names(optimized)
    _verify(optimized)


def test_ssa_global_constant_propagator_does_not_propagate_calls() -> None:
    int_type = IntType()
    call_result = SSAValue("call_result", int_type)
    one = SSAValue("one", int_type)
    result_value = SSAValue("result", int_type)
    source_value = SSAValue("source_value", int_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "source",
                    [],
                    int_type,
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(source_value, 7),
                                SSAReturn(source_value),
                            ],
                        )
                    ],
                ),
                SSAFunction(
                    "main",
                    [],
                    int_type,
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSACall("source", (), call_result),
                                SSAConst(one, 1),
                                SSABinaryOp(result_value, "add", call_result, one),
                                SSAReturn(result_value),
                            ],
                        )
                    ],
                ),
            ]
        )
    )

    propagation = SSAGlobalConstantPropagator().run(module)

    assert propagation.changed is False
    assert propagation.module is module
    assert propagation.stats == {"propagated": 0}
    assert "SSACall" in _instruction_names(propagation.module)
    assert "SSABinaryOp" in _instruction_names(propagation.module)
    _verify(propagation.module)


@pytest.mark.parametrize(
    ("operator", "constant_value", "constant_on_left"),
    [
        ("add", 0, False),
        ("add", 0, True),
        ("sub", 0, False),
        ("mul", 1, False),
        ("mul", 1, True),
    ],
)
def test_ssa_algebraic_simplifier_integer_identity_rules(
    operator: str,
    constant_value: int,
    constant_on_left: bool,
) -> None:
    module = _integer_identity_module(
        operator,
        constant_value,
        constant_on_left=constant_on_left,
    )

    result = SSAAlgebraicSimplifier().run(module)

    assert result.changed is True
    assert result.stats == {"simplified": 1}
    [function] = result.module.functions
    assert function.blocks[0].instructions == [
        SSAConst(SSAValue("constant", IntType()), constant_value),
        SSAReturn(SSAParameter("x", IntType())),
    ]
    _verify(result.module)


def test_ssa_algebraic_simplifier_type_preserving_division_by_one() -> None:
    module = _integer_identity_module("div", 1, verify=False)

    result = SSAAlgebraicSimplifier().run(module)

    assert result.changed is True
    assert result.stats == {"simplified": 1}
    [function] = result.module.functions
    assert function.blocks[0].instructions == [
        SSAConst(SSAValue("constant", IntType()), 1),
        SSAReturn(SSAParameter("x", IntType())),
    ]
    _verify(result.module)


@pytest.mark.parametrize(
    ("operator", "constant_value", "constant_on_left"),
    [
        ("mul", 0, False),
        ("mul", 0, True),
        ("mod", 1, False),
        ("rem", 1, False),
    ],
)
def test_ssa_algebraic_simplifier_integer_zero_result_rules(
    operator: str,
    constant_value: int,
    constant_on_left: bool,
) -> None:
    module = _integer_identity_module(
        operator,
        constant_value,
        constant_on_left=constant_on_left,
    )

    result = SSAAlgebraicSimplifier().run(module)

    assert result.changed is True
    assert result.stats == {"simplified": 1}
    [function] = result.module.functions
    assert function.blocks[0].instructions == [
        SSAConst(SSAValue("constant", IntType()), constant_value),
        SSAConst(SSAValue("result", IntType()), 0),
        SSAReturn(SSAValue("result", IntType())),
    ]
    _verify(result.module)


def test_default_pipeline_algebraic_simplification_then_dce_removes_dead_const() -> None:
    module = _integer_identity_module("add", 0)

    optimized = SSAOptimizerPipeline().run(module)

    [function] = optimized.functions
    assert function.blocks[0].instructions == [
        SSAReturn(SSAParameter("x", IntType())),
    ]
    _verify(optimized)


@pytest.mark.parametrize("operator", ["sub", "div", "mod", "rem"])
def test_ssa_algebraic_simplifier_does_not_fold_same_operand_rules(
    operator: str,
) -> None:
    int_type = IntType()
    result_type: IRType = DoubleType() if operator == "div" else int_type
    parameter = SSAParameter("x", int_type)
    result_value = SSAValue("result", result_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [parameter],
                    result_type,
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSABinaryOp(
                                    result_value,
                                    operator,
                                    parameter,
                                    parameter,
                                ),
                                SSAReturn(result_value),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    result = SSAAlgebraicSimplifier().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"simplified": 0}
    _verify(result.module)


def test_ssa_algebraic_simplifier_does_not_simplify_division_if_type_changes() -> None:
    module = _integer_identity_module("div", 1, result_type=DoubleType())

    result = SSAAlgebraicSimplifier().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"simplified": 0}
    _verify(result.module)


@pytest.mark.parametrize(
    ("type_", "constant_value", "operator"),
    [
        (FloatType(), 0.0, "add"),
        (DoubleType(), 0.0, "add"),
        (DoubleType(), 1.0, "mul"),
    ],
)
def test_ssa_algebraic_simplifier_does_not_simplify_float_or_double(
    type_: IRType,
    constant_value: float,
    operator: str,
) -> None:
    parameter = SSAParameter("x", type_)
    constant = SSAValue("constant", type_)
    result_value = SSAValue("result", type_)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [parameter],
                    type_,
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(constant, constant_value),
                                SSABinaryOp(
                                    result_value,
                                    operator,
                                    parameter,
                                    constant,
                                ),
                                SSAReturn(result_value),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    result = SSAAlgebraicSimplifier().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"simplified": 0}
    _verify(result.module)


def test_ssa_algebraic_simplifier_does_not_simplify_boolean_compare() -> None:
    bool_type = BoolType()
    parameter = SSAParameter("x", bool_type)
    true_value = SSAValue("true_value", bool_type)
    result_value = SSAValue("result", bool_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [parameter],
                    bool_type,
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(true_value, True),
                                SSACompareOp(result_value, "eq", parameter, true_value),
                                SSAReturn(result_value),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    result = SSAAlgebraicSimplifier().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"simplified": 0}
    _verify(result.module)


def test_ssa_algebraic_simplifier_does_not_simplify_non_identity_constant() -> None:
    module = _integer_identity_module("add", 2)

    result = SSAAlgebraicSimplifier().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {"simplified": 0}
    _verify(result.module)


def test_empty_ssa_optimizer_pipeline_returns_same_module() -> None:
    module = _module_with_function()

    optimized = SSAOptimizerPipeline().run(module)

    assert optimized is module


def test_empty_ssa_optimizer_trace_has_initial_and_final_ssa() -> None:
    module = _module_with_function()

    trace = SSAOptimizerPipeline().run_with_trace(module)

    assert [step.label for step in trace] == [
        "Initial SSA",
        "SSAConstantFolder",
        "SSAGlobalConstantPropagator",
        "SSAAlgebraicSimplifier",
        "SCCPPass",
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
    assert trace[1].stats == {"folded": 0}
    assert trace[2].module is module
    assert trace[2].changed is False
    assert trace[2].stats == {"propagated": 0}
    assert trace[3].module is module
    assert trace[3].changed is False
    assert trace[3].stats == {"simplified": 0}
    assert trace[4].module is module
    assert trace[4].changed is False
    assert trace[4].stats == {
        "replaced_constants": 0,
        "simplified_branches": 0,
        "removed_blocks": 0,
        "removed_phi_incomings": 0,
    }
    assert trace[5].module is module
    assert trace[5].changed is False
    assert trace[5].stats == {"removed_trivial_phis": 0, "rewritten_uses": 0}
    assert trace[6].module is module
    assert trace[6].changed is False
    assert trace[6].stats == {"removed_phis": 0}
    assert trace[7].module is module
    assert trace[7].changed is False
    assert trace[7].stats == {"removed": 0}
    assert trace[8].module is module
    assert trace[8].changed is False
    assert trace[8].stats == {}


def test_default_pipeline_executes_sccp() -> None:
    module = _phi_merge_module(use="return")

    trace = SSAOptimizerPipeline().run_with_trace(module)

    sccp_step = next(step for step in trace if step.label == "SCCPPass")
    assert sccp_step.changed is True
    assert sccp_step.stats == {
        "replaced_constants": 1,
        "simplified_branches": 1,
        "removed_blocks": 1,
        "removed_phi_incomings": 0,
    }
    _verify(sccp_step.module)


def test_sccp_pass_produces_real_changes() -> None:
    module = _phi_merge_module(use="return")

    result = SCCPPass().run(module)

    assert result.changed is True
    assert result.stats == {
        "replaced_constants": 1,
        "simplified_branches": 1,
        "removed_blocks": 1,
        "removed_phi_incomings": 0,
    }
    [function] = result.module.functions
    assert [block.name for block in function.blocks] == ["entry", "then0", "merge0"]
    assert function.blocks[0].instructions[-1] == SSAJump("then0")
    assert "SSAPhi" not in _instruction_names(result.module)
    _verify(result.module)


def test_default_iterative_pipeline_converges_with_sccp() -> None:
    module = _phi_merge_module(use="return")

    trace = SSAOptimizerPipeline(iterative=True).run_with_trace(module)

    sccp_steps = [step for step in trace if step.label.endswith("SCCPPass")]
    assert [step.label for step in sccp_steps] == [
        "Iteration 1 / SCCPPass",
        "Iteration 2 / SCCPPass",
    ]
    assert sccp_steps[0].changed is True
    assert sccp_steps[1].changed is False
    assert trace[-1].label == "Final SSA"
    _verify(trace[-1].module)


def test_default_pipeline_sccp_then_dce_cleans_dead_values() -> None:
    module = _phi_merge_module(use="return")

    optimized = SSAOptimizerPipeline().run(module)

    [function] = optimized.functions
    assert function.blocks == [
        SSABasicBlock("entry", [SSAJump("then0")]),
        SSABasicBlock("then0", [SSAJump("merge0")]),
        SSABasicBlock(
            "merge0",
            [
                SSAConst(SSAValue("phi_value", IntType()), 1),
                SSAReturn(SSAValue("phi_value", IntType())),
            ],
        ),
    ]
    assert "SSABranch" not in _instruction_names(optimized)
    assert "SSAPhi" not in _instruction_names(optimized)
    _verify(optimized)


def test_sccp_pass_does_not_change_module_without_opportunities() -> None:
    module = _module_with_function()

    result = SCCPPass().run(module)

    assert result.changed is False
    assert result.module is module
    assert result.stats == {
        "replaced_constants": 0,
        "simplified_branches": 0,
        "removed_blocks": 0,
        "removed_phi_incomings": 0,
    }
    _verify(result.module)


def test_default_pipeline_sccp_end_to_end_phi_cleanup_and_dce() -> None:
    module = _sccp_phi_cleanup_module()

    optimized = SSAOptimizerPipeline().run(module)

    [function] = optimized.functions
    parameter = SSAParameter("parameter", IntType())
    assert function.blocks == [
        SSABasicBlock("entry", [SSAJump("then0")]),
        SSABasicBlock("then0", [SSAJump("merge0")]),
        SSABasicBlock("merge0", [SSAReturn(parameter)]),
    ]
    assert "SSAConst" not in _instruction_names(optimized)
    assert "SSABranch" not in _instruction_names(optimized)
    assert "SSAPhi" not in _instruction_names(optimized)
    _verify(optimized)


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


def test_ssa_dead_code_eliminator_preserves_unused_int_binary_op_that_may_trap() -> None:
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

    assert result.changed is False
    assert result.stats == {"removed": 0}
    assert "SSABinaryOp" in _instruction_names(result.module)
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


def test_default_ssa_optimizer_trace_shows_sccp_changes() -> None:
    module = _phi_merge_module()

    trace = SSAOptimizerPipeline().run_with_trace(module)

    assert [step.label for step in trace] == [
        "Initial SSA",
        "SSAConstantFolder",
        "SSAGlobalConstantPropagator",
        "SSAAlgebraicSimplifier",
        "SCCPPass",
        "TrivialPhiEliminator",
        "DeadPhiEliminator",
        "SSADeadCodeEliminator",
        "Final SSA",
    ]
    assert trace[1].changed is False
    assert trace[1].stats == {"folded": 0}
    assert trace[2].changed is False
    assert trace[2].stats == {"propagated": 0}
    assert trace[3].changed is False
    assert trace[3].stats == {"simplified": 0}
    assert trace[4].changed is True
    assert trace[4].stats == {
        "replaced_constants": 1,
        "simplified_branches": 1,
        "removed_blocks": 1,
        "removed_phi_incomings": 0,
    }
    assert trace[5].changed is False
    assert trace[5].stats == {"removed_trivial_phis": 0, "rewritten_uses": 0}
    assert trace[6].changed is False
    assert trace[6].stats == {"removed_phis": 0}
    assert trace[7].changed is True
    assert trace[7].stats == {"removed": 3}
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
