from __future__ import annotations

import pytest

from aether.ir import (
    BoolType,
    IntType,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRJump,
    IRLoad,
    IRModule,
    IRParameter,
    IRReturn,
    IRStore,
    IRValue,
)
from aether.ssa import (
    GeneralSSABuilder,
    SSABranch,
    SSABuildError,
    SSABuilder,
    SSAFunction,
    SSAInstruction,
    SSAJump,
    SSAModule,
    SSAPhi,
    SSAReturn,
    SSAVerifier,
    print_ssa,
)


def _int_value(name: str) -> IRValue:
    return IRValue(name, IntType())


def _bool_parameter(name: str = "condition") -> IRParameter:
    return IRParameter(name, BoolType())


def _build_pattern(module: IRModule) -> SSAModule:
    ssa_module = SSABuilder().build(module)
    assert SSAVerifier(ssa_module).verify() is ssa_module
    return ssa_module


def _build_general(module: IRModule) -> SSAModule:
    ssa_module = GeneralSSABuilder().build_module(module)
    assert SSAVerifier(ssa_module).verify() is ssa_module
    return ssa_module


def _compare_builders(module: IRModule) -> None:
    pattern = _build_pattern(module)
    general = _build_general(module)

    _assert_no_slot_traffic(pattern)
    _assert_no_slot_traffic(general)
    _assert_function_sets_match(pattern, general)

    pattern_functions = {function.name: function for function in pattern.functions}
    general_functions = {function.name: function for function in general.functions}
    for name, pattern_function in pattern_functions.items():
        general_function = general_functions[name]
        _assert_signature_matches(pattern_function, general_function)
        _assert_blocks_match(pattern_function, general_function)
        _assert_phi_counts_match(pattern_function, general_function)
        _assert_terminators_match(pattern_function, general_function)


def _assert_no_slot_traffic(module: SSAModule) -> None:
    printed = print_ssa(module)
    assert " load " not in printed
    assert " store " not in printed
    assert "\n    load " not in printed
    assert "\n    store " not in printed


def _assert_function_sets_match(pattern: SSAModule, general: SSAModule) -> None:
    assert [function.name for function in general.functions] == [
        function.name for function in pattern.functions
    ]


def _assert_signature_matches(pattern: SSAFunction, general: SSAFunction) -> None:
    assert [(parameter.name, parameter.type) for parameter in general.parameters] == [
        (parameter.name, parameter.type) for parameter in pattern.parameters
    ]
    assert general.return_type == pattern.return_type


def _assert_blocks_match(pattern: SSAFunction, general: SSAFunction) -> None:
    assert [block.name for block in general.blocks] == [
        block.name for block in pattern.blocks
    ]


def _assert_phi_counts_match(pattern: SSAFunction, general: SSAFunction) -> None:
    assert _phi_counts_by_block(general) == _phi_counts_by_block(pattern)


def _phi_counts_by_block(function: SSAFunction) -> dict[str, int]:
    return {
        block.name: sum(
            isinstance(instruction, SSAPhi) for instruction in block.instructions
        )
        for block in function.blocks
    }


def _assert_terminators_match(pattern: SSAFunction, general: SSAFunction) -> None:
    pattern_blocks = {block.name: block for block in pattern.blocks}
    general_blocks = {block.name: block for block in general.blocks}

    for name, pattern_block in pattern_blocks.items():
        pattern_terminator = pattern_block.instructions[-1]
        general_terminator = general_blocks[name].instructions[-1]
        assert _terminator_shape(general_terminator) == _terminator_shape(
            pattern_terminator
        )


def _terminator_shape(instruction: SSAInstruction) -> tuple[object, ...]:
    if isinstance(instruction, SSABranch):
        return (
            SSABranch,
            instruction.condition.type,
            instruction.true_target,
            instruction.false_target,
        )
    if isinstance(instruction, SSAJump):
        return (SSAJump, instruction.target)
    if isinstance(instruction, SSAReturn):
        return (
            SSAReturn,
            None if instruction.value is None else instruction.value.type,
        )
    raise AssertionError(f"Expected terminator, got {type(instruction).__name__}")


def _linear_function_module() -> IRModule:
    value = _int_value("0")
    return IRModule(
        [
            IRFunction(
                "answer",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRConst(value, 42), IRReturn(value)])],
            )
        ]
    )


def _add_with_parameters_module() -> IRModule:
    left = IRParameter("left", IntType())
    right = IRParameter("right", IntType())
    result = _int_value("0")
    return IRModule(
        [
            IRFunction(
                "add",
                [left, right],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRBinaryOp(result, "add", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )


def _local_store_load_module() -> IRModule:
    slot = _int_value("x")
    stored = _int_value("0")
    loaded = _int_value("1")
    return IRModule(
        [
            IRFunction(
                "read_x",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(stored, 5),
                            IRStore(slot, stored),
                            IRLoad(loaded, slot),
                            IRReturn(loaded),
                        ],
                    )
                ],
            )
        ]
    )


def _simple_if_else_with_phi_module() -> IRModule:
    x = IRParameter("x", IntType())
    slot = _int_value("y")
    zero = _int_value("0")
    condition = IRValue("1", BoolType())
    one = _int_value("2")
    two = _int_value("3")
    loaded = _int_value("4")
    return IRModule(
        [
            IRFunction(
                "choose",
                [x],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(zero, 0),
                            IRCompareOp(condition, "gt", x, zero),
                            IRBranch(condition, "then0", "else0"),
                        ],
                    ),
                    IRBasicBlock(
                        "then0",
                        [IRConst(one, 1), IRStore(slot, one), IRJump("merge0")],
                    ),
                    IRBasicBlock(
                        "else0",
                        [IRConst(two, 2), IRStore(slot, two), IRJump("merge0")],
                    ),
                    IRBasicBlock("merge0", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )


def _if_else_return_both_branches_module() -> IRModule:
    condition = _bool_parameter()
    one = _int_value("0")
    two = _int_value("1")
    return IRModule(
        [
            IRFunction(
                "choose_return",
                [condition],
                IntType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then0", "else0")]),
                    IRBasicBlock("then0", [IRConst(one, 1), IRReturn(one)]),
                    IRBasicBlock("else0", [IRConst(two, 2), IRReturn(two)]),
                ],
            )
        ]
    )


def _while_countdown_module() -> IRModule:
    parameter = IRParameter("n", IntType())
    slot = _int_value("n")
    loop_value = _int_value("0")
    zero = _int_value("1")
    condition = IRValue("2", BoolType())
    body_value = _int_value("3")
    one = _int_value("4")
    next_value = _int_value("5")
    result = _int_value("6")
    return IRModule(
        [
            IRFunction(
                "countdown",
                [parameter],
                IntType(),
                [
                    IRBasicBlock("entry", [IRStore(slot, parameter), IRJump("cond0")]),
                    IRBasicBlock(
                        "cond0",
                        [
                            IRLoad(loop_value, slot),
                            IRConst(zero, 0),
                            IRCompareOp(condition, "gt", loop_value, zero),
                            IRBranch(condition, "body0", "exit0"),
                        ],
                    ),
                    IRBasicBlock(
                        "body0",
                        [
                            IRLoad(body_value, slot),
                            IRConst(one, 1),
                            IRBinaryOp(next_value, "sub", body_value, one),
                            IRStore(slot, next_value),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock("exit0", [IRLoad(result, slot), IRReturn(result)]),
                ],
            )
        ]
    )


def _sum_to_module() -> IRModule:
    n = IRParameter("n", IntType())
    i = _int_value("i")
    total = _int_value("sum")
    zero = _int_value("0")
    one = _int_value("1")
    loaded_i = _int_value("2")
    loaded_sum = _int_value("3")
    condition = IRValue("4", BoolType())
    body_sum = _int_value("5")
    next_sum = _int_value("6")
    body_i = _int_value("7")
    next_i = _int_value("8")
    result = _int_value("9")
    return IRModule(
        [
            IRFunction(
                "sumTo",
                [n],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(zero, 0),
                            IRConst(one, 1),
                            IRStore(i, one),
                            IRStore(total, zero),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock(
                        "cond0",
                        [
                            IRLoad(loaded_i, i),
                            IRLoad(loaded_sum, total),
                            IRCompareOp(condition, "le", loaded_i, n),
                            IRBranch(condition, "body0", "exit0"),
                        ],
                    ),
                    IRBasicBlock(
                        "body0",
                        [
                            IRLoad(body_sum, total),
                            IRBinaryOp(next_sum, "add", body_sum, loaded_i),
                            IRStore(total, next_sum),
                            IRLoad(body_i, i),
                            IRBinaryOp(next_i, "add", body_i, one),
                            IRStore(i, next_i),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock("exit0", [IRLoad(result, total), IRReturn(result)]),
                ],
            )
        ]
    )


def _multiple_functions_module() -> IRModule:
    parameter = IRParameter("value", IntType())
    one = _int_value("0")
    incremented = _int_value("1")
    argument = _int_value("2")
    call_result = _int_value("3")
    return IRModule(
        [
            IRFunction(
                "increment",
                [parameter],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(one, 1),
                            IRBinaryOp(incremented, "add", parameter, one),
                            IRReturn(incremented),
                        ],
                    )
                ],
            ),
            IRFunction(
                "main",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(argument, 41),
                            IRCall("increment", (argument,), call_result),
                            IRReturn(call_result),
                        ],
                    )
                ],
            ),
        ]
    )


def _nested_if_module() -> IRModule:
    outer = _bool_parameter("outer")
    inner = _bool_parameter("inner")
    slot = _int_value("x")
    inner_then_value = _int_value("0")
    inner_else_value = _int_value("1")
    outer_else_value = _int_value("2")
    loaded = _int_value("3")
    return IRModule(
        [
            IRFunction(
                "nested",
                [outer, inner],
                IntType(),
                [
                    IRBasicBlock("entry", [IRBranch(outer, "then0", "else0")]),
                    IRBasicBlock("then0", [IRBranch(inner, "then1", "else1")]),
                    IRBasicBlock(
                        "then1",
                        [
                            IRConst(inner_then_value, 1),
                            IRStore(slot, inner_then_value),
                            IRJump("merge_inner"),
                        ],
                    ),
                    IRBasicBlock(
                        "else1",
                        [
                            IRConst(inner_else_value, 2),
                            IRStore(slot, inner_else_value),
                            IRJump("merge_inner"),
                        ],
                    ),
                    IRBasicBlock("merge_inner", [IRJump("merge_outer")]),
                    IRBasicBlock(
                        "else0",
                        [
                            IRConst(outer_else_value, 3),
                            IRStore(slot, outer_else_value),
                            IRJump("merge_outer"),
                        ],
                    ),
                    IRBasicBlock(
                        "merge_outer",
                        [IRLoad(loaded, slot), IRReturn(loaded)],
                    ),
                ],
            )
        ]
    )


@pytest.mark.parametrize(
    "module",
    [
        _linear_function_module(),
        _add_with_parameters_module(),
        _local_store_load_module(),
        _simple_if_else_with_phi_module(),
        _if_else_return_both_branches_module(),
        _while_countdown_module(),
        _sum_to_module(),
        _multiple_functions_module(),
    ],
)
def test_pattern_and_general_builders_match_supported_invariants(
    module: IRModule,
) -> None:
    _compare_builders(module)


def test_general_builder_accepts_nested_if_that_pattern_builder_rejects() -> None:
    module = _nested_if_module()

    with pytest.raises(SSABuildError):
        SSABuilder().build(module)

    general = _build_general(module)

    assert _phi_counts_by_block(general.functions[0]) == {
        "entry": 0,
        "then0": 0,
        "then1": 0,
        "else1": 0,
        "merge_inner": 1,
        "else0": 0,
        "merge_outer": 1,
    }
    _assert_no_slot_traffic(general)
