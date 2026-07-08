from __future__ import annotations

import re

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
    IRInstruction,
    IRJump,
    IRLoad,
    IRModule,
    IRParameter,
    IRReturn,
    IRStore,
    IRValue,
    IRVectorNew,
    VectorType,
    VoidType,
)
from aether.ssa import (
    SSABranch,
    SSABinaryOp,
    SSABuildError,
    SSABuilder,
    SSACall,
    SSACompareOp,
    SSAConst,
    SSAJump,
    SSAPhi,
    SSAReturn,
    SSAVectorNew,
    SSAVerifier,
    print_ssa,
)


PHASE_3_MESSAGE = (
    "SSA builder phase 3 only supports linear functions, simple acyclic "
    "if/else, and simple while loops."
)


def _build_and_verify(module: IRModule):
    ssa_module = SSABuilder().build(module)
    assert SSAVerifier(ssa_module).verify() is ssa_module
    return ssa_module


def _assert_build_error(module: IRModule, message: str) -> None:
    with pytest.raises(SSABuildError, match=re.escape(message)):
        SSABuilder().build(module)


def test_builds_function_returning_literal() -> None:
    int_type = IntType()
    value = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "answer",
                [],
                int_type,
                [IRBasicBlock("entry", [IRConst(value, 42), IRReturn(value)])],
            )
        ]
    )

    ssa_module = _build_and_verify(module)
    instructions = ssa_module.functions[0].blocks[0].instructions

    assert isinstance(instructions[0], SSAConst)
    assert instructions[0].result.name == "0"
    assert instructions[0].value == 42
    assert isinstance(instructions[1], SSAReturn)
    assert instructions[1].value is not None
    assert instructions[1].value.name == "0"


def test_builds_add_with_parameters() -> None:
    int_type = IntType()
    left = IRParameter("left", int_type)
    right = IRParameter("right", int_type)
    result = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "add",
                [left, right],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRBinaryOp(result, "add", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)
    function = ssa_module.functions[0]

    assert function.parameters[0].name == "left"
    assert function.parameters[1].name == "right"
    assert isinstance(function.blocks[0].instructions[0], SSABinaryOp)
    assert print_ssa(ssa_module) == (
        "func @add(%left: int, %right: int) -> int {\n"
        "entry:\n"
        "    %0: int = add %left, %right\n"
        "    return %0\n"
        "}"
    )


def test_builds_column_vector_new_with_orientation() -> None:
    int_type = IntType()
    vector_type = VectorType(int_type, "column")
    first = IRValue("0", int_type)
    second = IRValue("1", int_type)
    vector = IRValue("2", vector_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(first, 1),
                            IRConst(second, 2),
                            IRVectorNew(vector, (first, second), "column"),
                            IRReturn(first),
                        ],
                    )
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)
    vector_new = next(
        instruction
        for instruction in ssa_module.functions[0].blocks[0].instructions
        if isinstance(instruction, SSAVectorNew)
    )

    assert vector_new.result.type == vector_type
    assert vector_new.orientation == "column"
    assert "vector_new column" in print_ssa(ssa_module)


def test_promotes_simple_local_store_and_load() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "read_x",
                [],
                int_type,
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

    ssa_module = _build_and_verify(module)

    assert print_ssa(ssa_module) == (
        "func @read_x() -> int {\n"
        "entry:\n"
        "    %0: int = const 5\n"
        "    return %0\n"
        "}"
    )


def test_promotes_latest_store_when_slot_is_overwritten() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    first = IRValue("0", int_type)
    second = IRValue("1", int_type)
    loaded = IRValue("2", int_type)
    module = IRModule(
        [
            IRFunction(
                "overwrite",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(first, 1),
                            IRStore(slot, first),
                            IRConst(second, 2),
                            IRStore(slot, second),
                            IRLoad(loaded, slot),
                            IRReturn(loaded),
                        ],
                    )
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)

    assert print_ssa(ssa_module) == (
        "func @overwrite() -> int {\n"
        "entry:\n"
        "    %0: int = const 1\n"
        "    %1: int = const 2\n"
        "    return %1\n"
        "}"
    )


def test_builds_call_between_functions() -> None:
    int_type = IntType()
    parameter = IRParameter("value", int_type)
    one = IRValue("0", int_type)
    incremented = IRValue("1", int_type)
    argument = IRValue("2", int_type)
    call_result = IRValue("3", int_type)
    module = IRModule(
        [
            IRFunction(
                "increment",
                [parameter],
                int_type,
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
                int_type,
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

    ssa_module = _build_and_verify(module)
    call = ssa_module.functions[1].blocks[0].instructions[1]

    assert isinstance(call, SSACall)
    assert call.function == "increment"
    assert call.arguments[0].name == "2"
    assert call.result is not None
    assert call.result.name == "3"


def test_builds_comparison() -> None:
    int_type = IntType()
    bool_type = BoolType()
    left = IRParameter("left", int_type)
    right = IRParameter("right", int_type)
    result = IRValue("0", bool_type)
    module = IRModule(
        [
            IRFunction(
                "less",
                [left, right],
                bool_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(result, "lt", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)

    assert isinstance(ssa_module.functions[0].blocks[0].instructions[0], SSACompareOp)
    assert print_ssa(ssa_module) == (
        "func @less(%left: int, %right: int) -> bool {\n"
        "entry:\n"
        "    %0: bool = cmp_lt %left, %right\n"
        "    return %0\n"
        "}"
    )


def test_builds_void_function_with_return() -> None:
    module = IRModule(
        [
            IRFunction(
                "nothing",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn()])],
            )
        ]
    )

    ssa_module = _build_and_verify(module)

    assert ssa_module.functions[0].blocks[0].instructions == [SSAReturn()]


def test_builds_simple_if_else_with_phi() -> None:
    int_type = IntType()
    bool_type = BoolType()
    x = IRParameter("x", int_type)
    y = IRValue("y", int_type)
    zero = IRValue("0", int_type)
    condition = IRValue("1", bool_type)
    one = IRValue("2", int_type)
    two = IRValue("3", int_type)
    loaded = IRValue("4", int_type)
    module = IRModule(
        [
            IRFunction(
                "f",
                [x],
                int_type,
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
                        [IRConst(one, 1), IRStore(y, one), IRJump("merge0")],
                    ),
                    IRBasicBlock(
                        "else0",
                        [IRConst(two, 2), IRStore(y, two), IRJump("merge0")],
                    ),
                    IRBasicBlock("merge0", [IRLoad(loaded, y), IRReturn(loaded)]),
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)
    merge_instructions = ssa_module.functions[0].blocks[3].instructions

    assert isinstance(ssa_module.functions[0].blocks[0].instructions[-1], SSABranch)
    assert isinstance(ssa_module.functions[0].blocks[1].instructions[-1], SSAJump)
    assert isinstance(ssa_module.functions[0].blocks[2].instructions[-1], SSAJump)
    assert isinstance(merge_instructions[0], SSAPhi)
    assert print_ssa(ssa_module) == (
        "func @f(%x: int) -> int {\n"
        "entry:\n"
        "    %0: int = const 0\n"
        "    %1: bool = cmp_gt %x, %0\n"
        "    branch %1, then0, else0\n"
        "\n"
        "then0:\n"
        "    %2: int = const 1\n"
        "    jump merge0\n"
        "\n"
        "else0:\n"
        "    %3: int = const 2\n"
        "    jump merge0\n"
        "\n"
        "merge0:\n"
        "    %4: int = phi(then0: %2, else0: %3)\n"
        "    return %4\n"
        "}"
    )


def test_simple_if_else_reuses_same_value_without_phi() -> None:
    int_type = IntType()
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    slot = IRValue("x", int_type)
    value = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "same",
                [condition],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(value, 7), IRBranch(condition, "then0", "else0")],
                    ),
                    IRBasicBlock(
                        "then0",
                        [IRStore(slot, value), IRJump("merge0")],
                    ),
                    IRBasicBlock(
                        "else0",
                        [IRStore(slot, value), IRJump("merge0")],
                    ),
                    IRBasicBlock("merge0", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )

    printed = print_ssa(_build_and_verify(module))

    assert "phi" not in printed
    assert printed == (
        "func @same(%condition: bool) -> int {\n"
        "entry:\n"
        "    %0: int = const 7\n"
        "    branch %condition, then0, else0\n"
        "\n"
        "then0:\n"
        "    jump merge0\n"
        "\n"
        "else0:\n"
        "    jump merge0\n"
        "\n"
        "merge0:\n"
        "    return %0\n"
        "}"
    )


def test_simple_if_else_uses_previous_value_for_unassigned_branch() -> None:
    int_type = IntType()
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    slot = IRValue("x", int_type)
    initial = IRValue("0", int_type)
    updated = IRValue("1", int_type)
    loaded = IRValue("2", int_type)
    module = IRModule(
        [
            IRFunction(
                "maybe_update",
                [condition],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(initial, 0),
                            IRStore(slot, initial),
                            IRBranch(condition, "then0", "else0"),
                        ],
                    ),
                    IRBasicBlock(
                        "then0",
                        [IRConst(updated, 1), IRStore(slot, updated), IRJump("merge0")],
                    ),
                    IRBasicBlock("else0", [IRJump("merge0")]),
                    IRBasicBlock("merge0", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)

    assert print_ssa(ssa_module) == (
        "func @maybe_update(%condition: bool) -> int {\n"
        "entry:\n"
        "    %0: int = const 0\n"
        "    branch %condition, then0, else0\n"
        "\n"
        "then0:\n"
        "    %1: int = const 1\n"
        "    jump merge0\n"
        "\n"
        "else0:\n"
        "    jump merge0\n"
        "\n"
        "merge0:\n"
        "    %2: int = phi(then0: %1, else0: %0)\n"
        "    return %2\n"
        "}"
    )


def test_merge_store_completes_partially_defined_slot_before_load() -> None:
    int_type = IntType()
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    slot = IRValue("x", int_type)
    branch_value = IRValue("0", int_type)
    merge_value = IRValue("1", int_type)
    loaded = IRValue("2", int_type)
    module = IRModule(
        [
            IRFunction(
                "repair",
                [condition],
                int_type,
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then0", "else0")]),
                    IRBasicBlock(
                        "then0",
                        [
                            IRConst(branch_value, 1),
                            IRStore(slot, branch_value),
                            IRJump("merge0"),
                        ],
                    ),
                    IRBasicBlock("else0", [IRJump("merge0")]),
                    IRBasicBlock(
                        "merge0",
                        [
                            IRConst(merge_value, 2),
                            IRStore(slot, merge_value),
                            IRLoad(loaded, slot),
                            IRReturn(loaded),
                        ],
                    ),
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)

    assert "phi" not in print_ssa(ssa_module)
    assert print_ssa(ssa_module) == (
        "func @repair(%condition: bool) -> int {\n"
        "entry:\n"
        "    branch %condition, then0, else0\n"
        "\n"
        "then0:\n"
        "    %0: int = const 1\n"
        "    jump merge0\n"
        "\n"
        "else0:\n"
        "    jump merge0\n"
        "\n"
        "merge0:\n"
        "    %1: int = const 2\n"
        "    return %1\n"
        "}"
    )


def test_builds_if_else_with_return_in_both_branches() -> None:
    int_type = IntType()
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    one = IRValue("0", int_type)
    two = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "choose",
                [condition],
                int_type,
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then0", "else0")]),
                    IRBasicBlock("then0", [IRConst(one, 1), IRReturn(one)]),
                    IRBasicBlock("else0", [IRConst(two, 2), IRReturn(two)]),
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)

    assert isinstance(ssa_module.functions[0].blocks[0].instructions[0], SSABranch)
    assert not any(
        isinstance(instruction, SSAPhi)
        for block in ssa_module.functions[0].blocks
        for instruction in block.instructions
    )
    assert print_ssa(ssa_module) == (
        "func @choose(%condition: bool) -> int {\n"
        "entry:\n"
        "    branch %condition, then0, else0\n"
        "\n"
        "then0:\n"
        "    %0: int = const 1\n"
        "    return %0\n"
        "\n"
        "else0:\n"
        "    %1: int = const 2\n"
        "    return %1\n"
        "}"
    )


def test_printer_shows_no_load_or_store_after_promotion() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    three = IRValue("2", int_type)
    result = IRValue("3", int_type)
    module = IRModule(
        [
            IRFunction(
                "example",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(stored, 5),
                            IRStore(slot, stored),
                            IRLoad(loaded, slot),
                            IRConst(three, 3),
                            IRBinaryOp(result, "add", loaded, three),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    printed = print_ssa(_build_and_verify(module))

    assert "load" not in printed
    assert "store" not in printed
    assert printed == (
        "func @example() -> int {\n"
        "entry:\n"
        "    %0: int = const 5\n"
        "    %2: int = const 3\n"
        "    %3: int = add %0, %2\n"
        "    return %3\n"
        "}"
    )


def test_builds_simple_while_countdown_with_phi() -> None:
    int_type = IntType()
    bool_type = BoolType()
    parameter = IRParameter("n", int_type)
    slot = IRValue("n", int_type)
    loop_value = IRValue("0", int_type)
    zero = IRValue("1", int_type)
    condition = IRValue("2", bool_type)
    body_value = IRValue("3", int_type)
    one = IRValue("4", int_type)
    next_value = IRValue("5", int_type)
    result = IRValue("6", int_type)
    module = IRModule(
        [
            IRFunction(
                "countdown",
                [parameter],
                int_type,
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

    ssa_module = _build_and_verify(module)
    condition_instructions = ssa_module.functions[0].blocks[1].instructions

    assert isinstance(condition_instructions[0], SSAPhi)
    assert print_ssa(ssa_module) == (
        "func @countdown(%n: int) -> int {\n"
        "entry:\n"
        "    jump cond0\n"
        "\n"
        "cond0:\n"
        "    %0: int = phi(entry: %n, body0: %5)\n"
        "    %1: int = const 0\n"
        "    %2: bool = cmp_gt %0, %1\n"
        "    branch %2, body0, exit0\n"
        "\n"
        "body0:\n"
        "    %4: int = const 1\n"
        "    %5: int = sub %0, %4\n"
        "    jump cond0\n"
        "\n"
        "exit0:\n"
        "    return %0\n"
        "}"
    )


def test_builds_simple_while_with_empty_body_without_phi() -> None:
    int_type = IntType()
    bool_type = BoolType()
    parameter = IRParameter("n", int_type)
    zero = IRValue("0", int_type)
    condition = IRValue("1", bool_type)
    module = IRModule(
        [
            IRFunction(
                "empty_loop",
                [parameter],
                int_type,
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock(
                        "cond0",
                        [
                            IRConst(zero, 0),
                            IRCompareOp(condition, "lt", parameter, zero),
                            IRBranch(condition, "body0", "exit0"),
                        ],
                    ),
                    IRBasicBlock("body0", [IRJump("cond0")]),
                    IRBasicBlock("exit0", [IRReturn(parameter)]),
                ],
            )
        ]
    )

    printed = print_ssa(_build_and_verify(module))

    assert "phi" not in printed
    assert printed == (
        "func @empty_loop(%n: int) -> int {\n"
        "entry:\n"
        "    jump cond0\n"
        "\n"
        "cond0:\n"
        "    %0: int = const 0\n"
        "    %1: bool = cmp_lt %n, %0\n"
        "    branch %1, body0, exit0\n"
        "\n"
        "body0:\n"
        "    jump cond0\n"
        "\n"
        "exit0:\n"
        "    return %n\n"
        "}"
    )


def test_rejects_function_with_branch() -> None:
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    module = IRModule(
        [
            IRFunction(
                "choose",
                [condition],
                bool_type,
                [IRBasicBlock("entry", [IRBranch(condition, "then", "else")])],
            )
        ]
    )

    _assert_build_error(
        module,
        PHASE_3_MESSAGE,
    )


def test_rejects_function_with_jump() -> None:
    module = IRModule(
        [
            IRFunction(
                "loop",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRJump("entry")])],
            )
        ]
    )

    _assert_build_error(
        module,
        PHASE_3_MESSAGE,
    )


def test_rejects_load_from_uninitialized_slot() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    loaded = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                int_type,
                [IRBasicBlock("entry", [IRLoad(loaded, slot), IRReturn(loaded)])],
            )
        ]
    )

    _assert_build_error(module, "Load from uninitialized slot '%x'.")


def test_rejects_unsupported_ir_instruction() -> None:
    class IRUnsupported(IRInstruction):
        pass

    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRUnsupported()])],
            )
        ]
    )

    _assert_build_error(module, "Unsupported IR instruction 'IRUnsupported'.")


def test_rejects_multiple_blocks() -> None:
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRReturn()]),
                    IRBasicBlock("other", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_build_error(
        module,
        PHASE_3_MESSAGE,
    )


def test_builds_minimal_simple_while_pattern() -> None:
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    module = IRModule(
        [
            IRFunction(
                "loop",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "exit0")]),
                    IRBasicBlock("body0", [IRJump("cond0")]),
                    IRBasicBlock("exit0", [IRReturn()]),
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)

    assert isinstance(ssa_module.functions[0].blocks[0].instructions[0], SSAJump)
    assert isinstance(ssa_module.functions[0].blocks[1].instructions[0], SSABranch)


def test_rejects_nested_if_pattern() -> None:
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    module = IRModule(
        [
            IRFunction(
                "nested",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then0", "else0")]),
                    IRBasicBlock("then0", [IRBranch(condition, "inner0", "inner1")]),
                    IRBasicBlock("inner0", [IRJump("merge0")]),
                    IRBasicBlock("inner1", [IRJump("merge0")]),
                    IRBasicBlock("else0", [IRJump("merge0")]),
                    IRBasicBlock("merge0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_build_error(module, PHASE_3_MESSAGE)


def test_rejects_control_flow_before_terminator_in_supported_shape() -> None:
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    module = IRModule(
        [
            IRFunction(
                "bad_terminator",
                [condition],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRBranch(condition, "then0", "else0"),
                            IRBranch(condition, "then0", "else0"),
                        ],
                    ),
                    IRBasicBlock("then0", [IRReturn()]),
                    IRBasicBlock("else0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_build_error(module, PHASE_3_MESSAGE)


def test_rejects_merge_with_more_than_two_predecessors() -> None:
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    module = IRModule(
        [
            IRFunction(
                "bad_merge",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then0", "else0")]),
                    IRBasicBlock("then0", [IRJump("merge0")]),
                    IRBasicBlock("else0", [IRJump("merge0")]),
                    IRBasicBlock("extra0", [IRJump("merge0")]),
                    IRBasicBlock("merge0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_build_error(module, PHASE_3_MESSAGE)


def test_rejects_merge_load_when_slot_is_not_defined_on_all_paths() -> None:
    int_type = IntType()
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    slot = IRValue("x", int_type)
    value = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "partial",
                [condition],
                int_type,
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then0", "else0")]),
                    IRBasicBlock(
                        "then0",
                        [IRConst(value, 1), IRStore(slot, value), IRJump("merge0")],
                    ),
                    IRBasicBlock("else0", [IRJump("merge0")]),
                    IRBasicBlock("merge0", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )

    _assert_build_error(
        module,
        "Load from slot '%x' is not defined on all paths.",
    )


def test_rejects_incompatible_phi_types() -> None:
    int_type = IntType()
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    slot = IRValue("x", int_type)
    int_value = IRValue("0", int_type)
    bool_value = IRValue("1", bool_type)
    loaded = IRValue("2", int_type)
    module = IRModule(
        [
            IRFunction(
                "bad_phi",
                [condition],
                int_type,
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then0", "else0")]),
                    IRBasicBlock(
                        "then0",
                        [IRConst(int_value, 1), IRStore(slot, int_value), IRJump("merge0")],
                    ),
                    IRBasicBlock(
                        "else0",
                        [
                            IRConst(bool_value, True),
                            IRStore(slot, bool_value),
                            IRJump("merge0"),
                        ],
                    ),
                    IRBasicBlock("merge0", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )

    _assert_build_error(
        module,
        "Cannot create phi for slot '%x' with incompatible types int and bool.",
    )


def test_rejects_non_matching_cfg_pattern() -> None:
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    module = IRModule(
        [
            IRFunction(
                "bad_cfg",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then0", "else0")]),
                    IRBasicBlock("then0", [IRJump("merge0")]),
                    IRBasicBlock("else0", [IRJump("other0")]),
                    IRBasicBlock("merge0", [IRReturn()]),
                    IRBasicBlock("other0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_build_error(module, PHASE_3_MESSAGE)


def test_rejects_nested_while_pattern() -> None:
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    module = IRModule(
        [
            IRFunction(
                "nested_loop",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "exit0")]),
                    IRBasicBlock("body0", [IRJump("cond1")]),
                    IRBasicBlock("cond1", [IRBranch(condition, "body1", "exit1")]),
                    IRBasicBlock("body1", [IRJump("cond1")]),
                    IRBasicBlock("exit1", [IRJump("cond0")]),
                    IRBasicBlock("exit0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_build_error(module, PHASE_3_MESSAGE)


def test_rejects_if_inside_while_pattern() -> None:
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    module = IRModule(
        [
            IRFunction(
                "if_in_loop",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "exit0")]),
                    IRBasicBlock("body0", [IRBranch(condition, "then0", "else0")]),
                    IRBasicBlock("then0", [IRJump("merge0")]),
                    IRBasicBlock("else0", [IRJump("merge0")]),
                    IRBasicBlock("merge0", [IRJump("cond0")]),
                    IRBasicBlock("exit0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_build_error(module, PHASE_3_MESSAGE)


def test_rejects_while_inside_if_pattern() -> None:
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    module = IRModule(
        [
            IRFunction(
                "loop_in_if",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then0", "else0")]),
                    IRBasicBlock("then0", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "exit0")]),
                    IRBasicBlock("body0", [IRJump("cond0")]),
                    IRBasicBlock("exit0", [IRJump("merge0")]),
                    IRBasicBlock("else0", [IRJump("merge0")]),
                    IRBasicBlock("merge0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_build_error(module, PHASE_3_MESSAGE)


def test_rejects_loop_carried_slot_without_initial_value() -> None:
    int_type = IntType()
    bool_type = BoolType()
    slot = IRValue("x", int_type)
    loaded = IRValue("0", int_type)
    zero = IRValue("1", int_type)
    condition = IRValue("2", bool_type)
    one = IRValue("3", int_type)
    module = IRModule(
        [
            IRFunction(
                "bad_loop",
                [],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock(
                        "cond0",
                        [
                            IRLoad(loaded, slot),
                            IRConst(zero, 0),
                            IRCompareOp(condition, "gt", loaded, zero),
                            IRBranch(condition, "body0", "exit0"),
                        ],
                    ),
                    IRBasicBlock(
                        "body0",
                        [IRConst(one, 1), IRStore(slot, one), IRJump("cond0")],
                    ),
                    IRBasicBlock("exit0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_build_error(
        module,
        "Loop-carried slot '%x' is not initialized before the loop.",
    )


def test_rejects_while_with_distinct_body_edge() -> None:
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    module = IRModule(
        [
            IRFunction(
                "bad_loop_edge",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "exit0")]),
                    IRBasicBlock("body0", [IRJump("exit0")]),
                    IRBasicBlock("exit0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_build_error(module, PHASE_3_MESSAGE)
