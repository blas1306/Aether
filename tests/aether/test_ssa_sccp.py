from __future__ import annotations

from aether.ir import BoolType, DoubleType, IntType, VoidType
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
from aether.ssa.analysis import Constant, Overdefined, Unknown
from aether.ssa.optimizer.sccp import SCCPAnalyzer, SCCPResult, SCCPTransformer


def _verify(module: SSAModule) -> SSAModule:
    return SSAVerifier(module).verify()


def _analyze(function: SSAFunction):
    return SCCPAnalyzer(function).analyze()


def _transform(module: SSAModule, result: SCCPResult):
    return SCCPTransformer(module, result).run()


def _block(function: SSAFunction, name: str) -> SSABasicBlock:
    return next(block for block in function.blocks if block.name == name)


def _manual_result(states):
    return SCCPResult(states, {"entry"}, set())


def _manual_result_for_blocks(states, blocks: set[str]):
    return SCCPResult(states, blocks, set())


def _stats(
    replaced_constants: int = 0,
    simplified_branches: int = 0,
    removed_blocks: int = 0,
    removed_phi_incomings: int = 0,
) -> dict[str, int]:
    return {
        "replaced_constants": replaced_constants,
        "simplified_branches": simplified_branches,
        "removed_blocks": removed_blocks,
        "removed_phi_incomings": removed_phi_incomings,
    }


def test_sccp_return_constant_value_state_is_constant() -> None:
    int_type = IntType()
    value = SSAValue("value", int_type)
    function = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    int_type,
                    [SSABasicBlock("entry", [SSAConst(value, 42), SSAReturn(value)])],
                )
            ]
        )
    ).functions[0]

    result = _analyze(function)

    assert result.state(value) == Constant(42)


def test_sccp_parameter_state_is_overdefined() -> None:
    int_type = IntType()
    parameter = SSAParameter("parameter", int_type)
    function = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [parameter],
                    int_type,
                    [SSABasicBlock("entry", [SSAReturn(parameter)])],
                )
            ]
        )
    ).functions[0]

    result = _analyze(function)

    assert result.state(parameter) == Overdefined()


def test_sccp_binary_fold_in_analysis() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    total = SSAValue("total", int_type)
    function = _verify(
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
                                SSABinaryOp(total, "add", left, right),
                                SSAReturn(total),
                            ],
                        )
                    ],
                )
            ]
        )
    ).functions[0]

    result = _analyze(function)

    assert result.state(total) == Constant(5)


def test_sccp_division_by_zero_is_overdefined() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    quotient = SSAValue("quotient", DoubleType())
    function = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    DoubleType(),
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(left, 2),
                                SSAConst(right, 0),
                                SSABinaryOp(quotient, "div", left, right),
                                SSAReturn(quotient),
                            ],
                        )
                    ],
                )
            ]
        )
    ).functions[0]

    result = _analyze(function)

    assert result.state(quotient) == Overdefined()


def test_sccp_compare_fold_in_analysis() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    comparison = SSAValue("comparison", BoolType())
    function = _verify(
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
                                SSAConst(left, 2),
                                SSAConst(right, 3),
                                SSACompareOp(comparison, "lt", left, right),
                                SSAReturn(comparison),
                            ],
                        )
                    ],
                )
            ]
        )
    ).functions[0]

    result = _analyze(function)

    assert result.state(comparison) == Constant(True)


def test_sccp_call_result_is_overdefined() -> None:
    int_type = IntType()
    call_result = SSAValue("call_result", int_type)
    source_value = SSAValue("source_value", int_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "source",
                    [],
                    int_type,
                    [SSABasicBlock("entry", [SSAConst(source_value, 1), SSAReturn(source_value)])],
                ),
                SSAFunction(
                    "main",
                    [],
                    int_type,
                    [
                        SSABasicBlock(
                            "entry",
                            [SSACall("source", (), call_result), SSAReturn(call_result)],
                        )
                    ],
                ),
            ]
        )
    )

    result = _analyze(module.functions[1])

    assert result.state(call_result) == Overdefined()


def test_sccp_branch_constant_true_marks_only_true_edge() -> None:
    function = _branch_function_with_constant(True)

    result = _analyze(function)

    assert ("entry", "then0") in result.executable_edges
    assert ("entry", "else0") not in result.executable_edges


def test_sccp_branch_constant_false_marks_only_false_edge() -> None:
    function = _branch_function_with_constant(False)

    result = _analyze(function)

    assert ("entry", "then0") not in result.executable_edges
    assert ("entry", "else0") in result.executable_edges


def test_sccp_branch_overdefined_marks_both_edges() -> None:
    condition = SSAParameter("condition", BoolType())
    function = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [condition],
                    VoidType(),
                    [
                        SSABasicBlock("entry", [SSABranch(condition, "then0", "else0")]),
                        SSABasicBlock("then0", [SSAReturn()]),
                        SSABasicBlock("else0", [SSAReturn()]),
                    ],
                )
            ]
        )
    ).functions[0]

    result = _analyze(function)

    assert result.executable_edges == {("entry", "then0"), ("entry", "else0")}


def test_sccp_branch_unknown_marks_no_edges_yet() -> None:
    bool_type = BoolType()
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    condition = SSAValue("condition", bool_type)
    function = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    VoidType(),
                    [
                        SSABasicBlock("entry", [SSAReturn()]),
                        SSABasicBlock(
                            "dead0",
                            [
                                SSAConst(left, 1),
                                SSAConst(right, 1),
                                SSACompareOp(condition, "eq", left, right),
                                SSABranch(condition, "then0", "else0"),
                            ],
                        ),
                        SSABasicBlock("then0", [SSAReturn()]),
                        SSABasicBlock("else0", [SSAReturn()]),
                    ],
                )
            ]
        )
    ).functions[0]

    result = _analyze(function)

    assert result.state(condition) == Unknown()
    assert result.executable_edges == set()
    assert result.executable_blocks == {"entry"}


def test_sccp_phi_only_considers_executable_incoming_edges() -> None:
    function, phi_value = _phi_diamond_function(True, 1, 2)

    result = _analyze(function)

    assert result.state(phi_value) == Constant(1)
    assert ("else0", "merge0") not in result.executable_edges


def test_sccp_phi_with_two_equal_executable_constants_is_constant() -> None:
    function, phi_value = _overdefined_branch_phi_function(7, 7)

    result = _analyze(function)

    assert result.state(phi_value) == Constant(7)


def test_sccp_phi_with_different_executable_constants_is_overdefined() -> None:
    function, phi_value = _overdefined_branch_phi_function(7, 9)

    result = _analyze(function)

    assert result.state(phi_value) == Overdefined()


def test_sccp_simple_loop_reaches_fixed_point() -> None:
    int_type = IntType()
    bool_type = BoolType()
    zero = SSAValue("zero", int_type)
    one = SSAValue("one", int_type)
    loop_i = SSAValue("loop_i", int_type)
    next_i = SSAValue("next_i", int_type)
    condition = SSAValue("condition", bool_type)
    function = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    int_type,
                    [
                        SSABasicBlock(
                            "entry",
                            [SSAConst(zero, 0), SSAConst(one, 1), SSAJump("loop0")],
                        ),
                        SSABasicBlock(
                            "loop0",
                            [
                                SSAPhi(loop_i, (("entry", zero), ("body0", next_i))),
                                SSACompareOp(condition, "lt", loop_i, one),
                                SSABranch(condition, "body0", "exit0"),
                            ],
                        ),
                        SSABasicBlock(
                            "body0",
                            [SSABinaryOp(next_i, "add", loop_i, one), SSAJump("loop0")],
                        ),
                        SSABasicBlock("exit0", [SSAReturn(loop_i)]),
                    ],
                )
            ]
        )
    ).functions[0]

    result = _analyze(function)

    assert result.state(loop_i) == Overdefined()
    assert result.state(condition) == Overdefined()
    assert result.executable_blocks == {"entry", "loop0", "body0", "exit0"}
    assert result.executable_edges == {
        ("entry", "loop0"),
        ("loop0", "body0"),
        ("body0", "loop0"),
        ("loop0", "exit0"),
    }


def test_sccp_executable_blocks_are_correct() -> None:
    function, _phi_value = _phi_diamond_function(True, 1, 2)

    result = _analyze(function)

    assert result.executable_blocks == {"entry", "then0", "merge0"}


def test_sccp_executable_edges_are_correct() -> None:
    function, _phi_value = _phi_diamond_function(True, 1, 2)

    result = _analyze(function)

    assert result.executable_edges == {("entry", "then0"), ("then0", "merge0")}


def test_sccp_transformer_replaces_binary_with_const() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    total = SSAValue("total", int_type)
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
                                SSABinaryOp(total, "add", left, right),
                                SSAReturn(total),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    transform = _transform(module, _analyze(module.functions[0]))

    instruction = transform.module.functions[0].blocks[0].instructions[2]
    assert transform.changed is True
    assert transform.stats == _stats(replaced_constants=1)
    assert instruction == SSAConst(total, 5)


def test_sccp_transformer_replaces_compare_with_const() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    comparison = SSAValue("comparison", BoolType())
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
                                SSAConst(left, 2),
                                SSAConst(right, 3),
                                SSACompareOp(comparison, "lt", left, right),
                                SSAReturn(comparison),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    transform = _transform(module, _analyze(module.functions[0]))

    instruction = transform.module.functions[0].blocks[0].instructions[2]
    assert transform.changed is True
    assert transform.stats == _stats(replaced_constants=1)
    assert instruction == SSAConst(comparison, True)


def test_sccp_transformer_replaces_phi_with_const() -> None:
    function, phi_value = _phi_diamond_function(True, 1, 2)
    module = SSAModule([function])

    transform = _transform(module, _analyze(function))

    merge_block = _block(transform.module.functions[0], "merge0")
    assert transform.changed is True
    assert transform.stats == _stats(
        replaced_constants=1,
        simplified_branches=1,
        removed_blocks=1,
    )
    assert merge_block.instructions[0] == SSAConst(phi_value, 1)


def test_sccp_analysis_plus_transform_result_passes_verifier() -> None:
    function, _phi_value = _phi_diamond_function(True, 1, 2)
    module = SSAModule([function])

    transform = _transform(module, _analyze(function))

    assert _verify(transform.module) is transform.module


def test_sccp_transformer_preserves_replaced_producer_result_value() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    total = SSAValue("total", int_type)
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
                                SSAConst(left, 20),
                                SSAConst(right, 22),
                                SSABinaryOp(total, "add", left, right),
                                SSAReturn(total),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    transform = _transform(module, _analyze(module.functions[0]))

    instruction = transform.module.functions[0].blocks[0].instructions[2]
    assert isinstance(instruction, SSAConst)
    assert instruction.result is total
    assert instruction.result.type is int_type


def test_sccp_transformer_does_not_change_call() -> None:
    int_type = IntType()
    source_value = SSAValue("source_value", int_type)
    call_result = SSAValue("call_result", int_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "source",
                    [],
                    int_type,
                    [SSABasicBlock("entry", [SSAConst(source_value, 1), SSAReturn(source_value)])],
                ),
                SSAFunction(
                    "main",
                    [],
                    int_type,
                    [
                        SSABasicBlock(
                            "entry",
                            [SSACall("source", (), call_result), SSAReturn(call_result)],
                        )
                    ],
                ),
            ]
        )
    )

    transform = _transform(module, _manual_result({call_result: Constant(7)}))

    assert transform.changed is False
    assert transform.stats == _stats()
    assert isinstance(transform.module.functions[1].blocks[0].instructions[0], SSACall)


def test_sccp_transformer_simplifies_true_branch_to_jump() -> None:
    function = _branch_function_with_constant(True)
    module = SSAModule([function])

    transform = _transform(module, _analyze(function))

    instruction = transform.module.functions[0].blocks[0].instructions[1]
    assert transform.changed is True
    assert transform.stats == _stats(simplified_branches=1, removed_blocks=1)
    assert instruction == SSAJump("then0")
    assert _verify(transform.module) is transform.module


def test_sccp_transformer_simplifies_false_branch_to_jump() -> None:
    function = _branch_function_with_constant(False)
    module = SSAModule([function])

    transform = _transform(module, _analyze(function))

    instruction = transform.module.functions[0].blocks[0].instructions[1]
    assert transform.changed is True
    assert transform.stats == _stats(simplified_branches=1, removed_blocks=1)
    assert instruction == SSAJump("else0")
    assert _verify(transform.module) is transform.module


def test_sccp_analysis_plus_transform_simplifies_if_true() -> None:
    function, _phi_value = _phi_diamond_function(True, 1, 2)
    module = SSAModule([function])

    transform = _transform(module, _analyze(function))

    instruction = transform.module.functions[0].blocks[0].instructions[1]
    assert instruction == SSAJump("then0")
    assert transform.stats == _stats(
        replaced_constants=1,
        simplified_branches=1,
        removed_blocks=1,
    )
    assert _verify(transform.module) is transform.module


def test_sccp_analysis_plus_transform_simplifies_if_false() -> None:
    function, _phi_value = _phi_diamond_function(False, 1, 2)
    module = SSAModule([function])

    transform = _transform(module, _analyze(function))

    instruction = transform.module.functions[0].blocks[0].instructions[1]
    assert instruction == SSAJump("else0")
    assert transform.stats == _stats(
        replaced_constants=1,
        simplified_branches=1,
        removed_blocks=1,
    )
    assert _verify(transform.module) is transform.module


def test_sccp_transformer_removes_unreachable_else_block() -> None:
    function = _branch_function_with_constant(True)
    module = SSAModule([function])

    transform = _transform(module, _analyze(function))

    block_names = [block.name for block in transform.module.functions[0].blocks]
    assert block_names == ["entry", "then0"]
    assert transform.stats == _stats(simplified_branches=1, removed_blocks=1)
    assert _verify(transform.module) is transform.module


def test_sccp_transformer_removes_unreachable_then_block() -> None:
    function = _branch_function_with_constant(False)
    module = SSAModule([function])

    transform = _transform(module, _analyze(function))

    block_names = [block.name for block in transform.module.functions[0].blocks]
    assert block_names == ["entry", "else0"]
    assert transform.stats == _stats(simplified_branches=1, removed_blocks=1)
    assert _verify(transform.module) is transform.module


def test_sccp_transformer_removes_phi_incoming_from_unreachable_block() -> None:
    int_type = IntType()
    condition = SSAValue("condition", BoolType())
    parameter = SSAParameter("parameter", int_type)
    else_value = SSAValue("else_value", int_type)
    phi_value = SSAValue("phi_value", int_type)
    function = _verify(
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
                                SSAConst(condition, True),
                                SSABranch(condition, "then0", "else0"),
                            ],
                        ),
                        SSABasicBlock("then0", [SSAJump("merge0")]),
                        SSABasicBlock(
                            "else0",
                            [SSAConst(else_value, 2), SSAJump("merge0")],
                        ),
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
    ).functions[0]

    transform = _transform(SSAModule([function]), _analyze(function))

    merge_block = _block(transform.module.functions[0], "merge0")
    phi = merge_block.instructions[0]
    assert isinstance(phi, SSAPhi)
    assert phi.incoming == (("then0", parameter),)
    assert transform.stats == _stats(
        simplified_branches=1,
        removed_blocks=1,
        removed_phi_incomings=1,
    )
    assert _verify(transform.module) is transform.module


def test_sccp_transformer_removes_unreachable_block_without_phis() -> None:
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    VoidType(),
                    [
                        SSABasicBlock("entry", [SSAReturn()]),
                        SSABasicBlock("dead0", [SSAReturn()]),
                    ],
                )
            ]
        )
    )

    transform = _transform(module, _analyze(module.functions[0]))

    block_names = [block.name for block in transform.module.functions[0].blocks]
    assert block_names == ["entry"]
    assert transform.stats == _stats(removed_blocks=1)
    assert _verify(transform.module) is transform.module


def test_sccp_transformer_does_not_remove_entry_block() -> None:
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    VoidType(),
                    [SSABasicBlock("entry", [SSAReturn()])],
                )
            ]
        )
    )

    transform = _transform(module, SCCPResult({}, set(), set()))

    block_names = [block.name for block in transform.module.functions[0].blocks]
    assert block_names == ["entry"]
    assert transform.changed is False
    assert transform.stats == _stats()
    assert _verify(transform.module) is transform.module


def test_sccp_transformer_leaves_module_without_unreachable_blocks_unchanged() -> None:
    module = _jump_module()

    transform = _transform(module, _analyze(module.functions[0]))

    block_names = [block.name for block in transform.module.functions[0].blocks]
    assert block_names == ["entry", "exit0"]
    assert transform.changed is False
    assert transform.stats == _stats()
    assert transform.module is module


def test_sccp_transformer_does_not_change_unknown_branch() -> None:
    function = _branch_function_with_constant(True)
    module = SSAModule([function])

    transform = _transform(
        module,
        _manual_result_for_blocks({}, {"entry", "then0", "else0"}),
    )

    assert transform.changed is False
    assert transform.stats == _stats()
    assert isinstance(transform.module.functions[0].blocks[0].instructions[1], SSABranch)


def test_sccp_transformer_does_not_change_overdefined_branch() -> None:
    condition = SSAParameter("condition", BoolType())
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [condition],
                    VoidType(),
                    [
                        SSABasicBlock("entry", [SSABranch(condition, "then0", "else0")]),
                        SSABasicBlock("then0", [SSAReturn()]),
                        SSABasicBlock("else0", [SSAReturn()]),
                    ],
                )
            ]
        )
    )

    transform = _transform(module, _analyze(module.functions[0]))

    assert transform.changed is False
    assert transform.stats == _stats()
    assert isinstance(transform.module.functions[0].blocks[0].instructions[0], SSABranch)


def test_sccp_transformer_does_not_change_non_bool_constant_branch() -> None:
    condition = SSAParameter("condition", BoolType())
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [condition],
                    VoidType(),
                    [
                        SSABasicBlock("entry", [SSABranch(condition, "then0", "else0")]),
                        SSABasicBlock("then0", [SSAReturn()]),
                        SSABasicBlock("else0", [SSAReturn()]),
                    ],
                )
            ]
        )
    )

    transform = _transform(
        module,
        _manual_result_for_blocks({condition: Constant(1)}, {"entry", "then0", "else0"}),
    )

    assert transform.changed is False
    assert transform.stats == _stats()
    assert isinstance(transform.module.functions[0].blocks[0].instructions[0], SSABranch)


def test_sccp_transformer_does_not_change_jump() -> None:
    module = _jump_module()

    transform = _transform(module, _analyze(module.functions[0]))

    assert transform.changed is False
    assert transform.stats == _stats()
    assert isinstance(transform.module.functions[0].blocks[0].instructions[1], SSAJump)


def test_sccp_transformer_does_not_change_return() -> None:
    int_type = IntType()
    value = SSAValue("value", int_type)
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    int_type,
                    [SSABasicBlock("entry", [SSAConst(value, 42), SSAReturn(value)])],
                )
            ]
        )
    )

    transform = _transform(module, _analyze(module.functions[0]))

    assert transform.changed is False
    assert transform.stats == _stats()
    assert isinstance(transform.module.functions[0].blocks[0].instructions[1], SSAReturn)


def test_sccp_transformer_does_not_change_overdefined_value() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    quotient = SSAValue("quotient", DoubleType())
    module = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    DoubleType(),
                    [
                        SSABasicBlock(
                            "entry",
                            [
                                SSAConst(left, 2),
                                SSAConst(right, 0),
                                SSABinaryOp(quotient, "div", left, right),
                                SSAReturn(quotient),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    transform = _transform(module, _analyze(module.functions[0]))

    assert transform.changed is False
    assert isinstance(transform.module.functions[0].blocks[0].instructions[2], SSABinaryOp)


def test_sccp_transformer_does_not_change_unknown_value() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    total = SSAValue("total", int_type)
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
                                SSABinaryOp(total, "add", left, right),
                                SSAReturn(total),
                            ],
                        )
                    ],
                )
            ]
        )
    )

    transform = _transform(module, _manual_result({}))

    assert transform.changed is False
    assert isinstance(transform.module.functions[0].blocks[0].instructions[2], SSABinaryOp)


def _jump_module() -> SSAModule:
    int_type = IntType()
    value = SSAValue("value", int_type)
    return _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    int_type,
                    [
                        SSABasicBlock("entry", [SSAConst(value, 1), SSAJump("exit0")]),
                        SSABasicBlock("exit0", [SSAReturn(value)]),
                    ],
                )
            ]
        )
    )


def _branch_function_with_constant(value: bool) -> SSAFunction:
    condition = SSAValue("condition", BoolType())
    return _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [],
                    VoidType(),
                    [
                        SSABasicBlock(
                            "entry",
                            [SSAConst(condition, value), SSABranch(condition, "then0", "else0")],
                        ),
                        SSABasicBlock("then0", [SSAReturn()]),
                        SSABasicBlock("else0", [SSAReturn()]),
                    ],
                )
            ]
        )
    ).functions[0]


def _phi_diamond_function(
    condition_value: bool,
    then_constant: int,
    else_constant: int,
) -> tuple[SSAFunction, SSAValue]:
    int_type = IntType()
    condition = SSAValue("condition", BoolType())
    then_value = SSAValue("then_value", int_type)
    else_value = SSAValue("else_value", int_type)
    phi_value = SSAValue("phi_value", int_type)
    function = _verify(
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
                                SSAConst(condition, condition_value),
                                SSABranch(condition, "then0", "else0"),
                            ],
                        ),
                        SSABasicBlock(
                            "then0",
                            [SSAConst(then_value, then_constant), SSAJump("merge0")],
                        ),
                        SSABasicBlock(
                            "else0",
                            [SSAConst(else_value, else_constant), SSAJump("merge0")],
                        ),
                        SSABasicBlock(
                            "merge0",
                            [
                                SSAPhi(
                                    phi_value,
                                    (("then0", then_value), ("else0", else_value)),
                                ),
                                SSAReturn(phi_value),
                            ],
                        ),
                    ],
                )
            ]
        )
    ).functions[0]
    return function, phi_value


def _overdefined_branch_phi_function(
    then_constant: int,
    else_constant: int,
) -> tuple[SSAFunction, SSAValue]:
    int_type = IntType()
    condition = SSAParameter("condition", BoolType())
    then_value = SSAValue("then_value", int_type)
    else_value = SSAValue("else_value", int_type)
    phi_value = SSAValue("phi_value", int_type)
    function = _verify(
        SSAModule(
            [
                SSAFunction(
                    "main",
                    [condition],
                    int_type,
                    [
                        SSABasicBlock("entry", [SSABranch(condition, "then0", "else0")]),
                        SSABasicBlock(
                            "then0",
                            [SSAConst(then_value, then_constant), SSAJump("merge0")],
                        ),
                        SSABasicBlock(
                            "else0",
                            [SSAConst(else_value, else_constant), SSAJump("merge0")],
                        ),
                        SSABasicBlock(
                            "merge0",
                            [
                                SSAPhi(
                                    phi_value,
                                    (("then0", then_value), ("else0", else_value)),
                                ),
                                SSAReturn(phi_value),
                            ],
                        ),
                    ],
                )
            ]
        )
    ).functions[0]
    return function, phi_value
