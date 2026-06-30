from __future__ import annotations

import pytest

from aether.ir import (
    BoolType,
    DoubleType,
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
    IntType,
    VoidType,
    print_ir,
)
from aether.ir.optimizer import ConstantFolder, DeadCodeEliminator, OptimizerPipeline


def _optimize(module: IRModule) -> IRModule:
    return ConstantFolder().run(module)


def _dce(module: IRModule) -> IRModule:
    return DeadCodeEliminator().run(module)


def _single_block_module(instructions: list[object], return_value: IRValue) -> IRModule:
    return IRModule(
        [
            IRFunction(
                "main",
                [],
                return_value.type,
                [IRBasicBlock("entry", [*instructions, IRReturn(return_value)])],
            )
        ]
    )


@pytest.mark.parametrize(
    ("operator", "left_value", "right_value", "expected"),
    [
        ("add", 2, 3, 5),
        ("sub", 8, 3, 5),
        ("mul", 4, 6, 24),
        ("mod", 17, 5, 2),
        ("rem", -7, 3, -1),
    ],
)
def test_constant_folding_arithmetic_int_ops(
    operator: str,
    left_value: int,
    right_value: int,
    expected: int,
) -> None:
    int_type = IntType()
    left = IRValue("0", int_type)
    right = IRValue("1", int_type)
    result = IRValue("2", int_type)
    module = _single_block_module(
        [
            IRConst(left, left_value),
            IRConst(right, right_value),
            IRBinaryOp(result, operator, left, right),
        ],
        result,
    )

    optimized = _optimize(module)

    assert optimized is not module
    assert print_ir(module) == (
        "func @main() -> int {\n"
        "entry:\n"
        f"    %0: int = const {left_value}\n"
        f"    %1: int = const {right_value}\n"
        f"    %2: int = {operator} %0, %1\n"
        "    return %2\n"
        "}"
    )
    assert print_ir(optimized) == (
        "func @main() -> int {\n"
        "entry:\n"
        f"    %0: int = const {left_value}\n"
        f"    %1: int = const {right_value}\n"
        f"    %2: int = const {expected}\n"
        "    return %2\n"
        "}"
    )


def test_constant_folding_division() -> None:
    int_type = IntType()
    double_type = DoubleType()
    left = IRValue("0", int_type)
    right = IRValue("1", int_type)
    result = IRValue("2", double_type)
    module = _single_block_module(
        [
            IRConst(left, 9),
            IRConst(right, 2),
            IRBinaryOp(result, "div", left, right),
        ],
        result,
    )

    assert print_ir(_optimize(module)) == (
        "func @main() -> double {\n"
        "entry:\n"
        "    %0: int = const 9\n"
        "    %1: int = const 2\n"
        "    %2: double = const 4.5\n"
        "    return %2\n"
        "}"
    )


@pytest.mark.parametrize(
    ("operator", "left_value", "right_value", "expected"),
    [
        ("lt", 2, 5, True),
        ("le", 5, 5, True),
        ("gt", 7, 3, True),
        ("ge", 7, 7, True),
        ("eq", 4, 4, True),
        ("ne", 4, 5, True),
    ],
)
def test_constant_folding_comparisons(
    operator: str,
    left_value: int,
    right_value: int,
    expected: bool,
) -> None:
    int_type = IntType()
    bool_type = BoolType()
    left = IRValue("0", int_type)
    right = IRValue("1", int_type)
    result = IRValue("2", bool_type)
    module = _single_block_module(
        [
            IRConst(left, left_value),
            IRConst(right, right_value),
            IRCompareOp(result, operator, left, right),
        ],
        result,
    )

    assert print_ir(_optimize(module)) == (
        "func @main() -> bool {\n"
        "entry:\n"
        f"    %0: int = const {left_value}\n"
        f"    %1: int = const {right_value}\n"
        f"    %2: bool = const {str(expected).lower()}\n"
        "    return %2\n"
        "}"
    )


def test_constant_folding_multiple_folds_in_one_function() -> None:
    int_type = IntType()
    two = IRValue("0", int_type)
    three = IRValue("1", int_type)
    five = IRValue("2", int_type)
    total = IRValue("3", int_type)
    module = _single_block_module(
        [
            IRConst(two, 2),
            IRConst(three, 3),
            IRBinaryOp(five, "add", two, three),
            IRBinaryOp(total, "mul", five, three),
        ],
        total,
    )

    assert print_ir(_optimize(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %0: int = const 2\n"
        "    %1: int = const 3\n"
        "    %2: int = const 5\n"
        "    %3: int = const 15\n"
        "    return %3\n"
        "}"
    )


def test_optimizer_pipeline_runs_constant_folding_then_dead_code_elimination() -> None:
    int_type = IntType()
    one = IRValue("0", int_type)
    two = IRValue("1", int_type)
    three = IRValue("2", int_type)
    result = IRValue("3", int_type)
    module = _single_block_module(
        [
            IRConst(one, 1),
            IRConst(two, 2),
            IRConst(three, 3),
            IRBinaryOp(result, "add", one, three),
        ],
        result,
    )

    assert print_ir(OptimizerPipeline().run(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %3: int = const 4\n"
        "    return %3\n"
        "}"
    )


def test_constant_folding_does_not_fold_expression_with_variable() -> None:
    int_type = IntType()
    parameter = IRParameter("x", int_type)
    one = IRValue("0", int_type)
    result = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "addOne",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(one, 1),
                            IRBinaryOp(result, "add", parameter, one),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_optimize(module)) == print_ir(module)


def test_constant_folding_does_not_evaluate_division_by_zero() -> None:
    int_type = IntType()
    double_type = DoubleType()
    one = IRValue("0", int_type)
    zero = IRValue("1", int_type)
    result = IRValue("2", double_type)
    module = _single_block_module(
        [
            IRConst(one, 1),
            IRConst(zero, 0),
            IRBinaryOp(result, "div", one, zero),
        ],
        result,
    )

    assert print_ir(_optimize(module)) == print_ir(module)


def test_constant_folding_does_not_fold_function_calls() -> None:
    int_type = IntType()
    value = IRValue("0", int_type)
    result = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "identity",
                [IRParameter("value", int_type)],
                int_type,
                [IRBasicBlock("entry", [IRReturn(IRParameter("value", int_type))])],
            ),
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(value, 3),
                            IRCall("identity", (value,), result),
                            IRReturn(result),
                        ],
                    )
                ],
            ),
        ]
    )

    assert print_ir(_optimize(module)) == print_ir(module)


def test_constant_folding_does_not_fold_load_or_store() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    result = IRValue("2", int_type)
    module = _single_block_module(
        [
            IRConst(stored, 4),
            IRStore(slot, stored),
            IRLoad(loaded, slot),
            IRBinaryOp(result, "add", loaded, stored),
        ],
        result,
    )

    assert print_ir(_optimize(module)) == print_ir(module)


def test_dead_code_eliminates_unused_constant_after_folding() -> None:
    int_type = IntType()
    two = IRValue("0", int_type)
    three = IRValue("1", int_type)
    four = IRValue("2", int_type)
    twelve = IRValue("3", int_type)
    result = IRValue("4", int_type)
    module = _single_block_module(
        [
            IRConst(two, 2),
            IRConst(three, 3),
            IRConst(four, 4),
            IRBinaryOp(twelve, "mul", three, four),
            IRBinaryOp(result, "add", two, twelve),
        ],
        result,
    )

    assert print_ir(OptimizerPipeline().run(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %4: int = const 14\n"
        "    return %4\n"
        "}"
    )


def test_dead_code_eliminates_unused_arithmetic_operation() -> None:
    int_type = IntType()
    left = IRParameter("a", int_type)
    right = IRParameter("b", int_type)
    unused = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [left, right],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRBinaryOp(unused, "add", left, right), IRReturn(left)],
                    )
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == (
        "func @main(%a: int, %b: int) -> int {\n"
        "entry:\n"
        "    return %a\n"
        "}"
    )


def test_dead_code_eliminates_unused_comparison() -> None:
    int_type = IntType()
    bool_type = BoolType()
    left = IRParameter("a", int_type)
    right = IRParameter("b", int_type)
    unused = IRValue("0", bool_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [left, right],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(unused, "lt", left, right), IRReturn(left)],
                    )
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == (
        "func @main(%a: int, %b: int) -> int {\n"
        "entry:\n"
        "    return %a\n"
        "}"
    )


def test_dead_code_eliminates_unused_load() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    value = IRValue("0", int_type)
    unused = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(value, 10),
                            IRStore(slot, value),
                            IRLoad(unused, slot),
                            IRReturn(),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == (
        "func @main() -> void {\n"
        "entry:\n"
        "    %0: int = const 10\n"
        "    store %x, %0\n"
        "    return\n"
        "}"
    )


def test_dead_code_keeps_returned_value() -> None:
    int_type = IntType()
    value = IRValue("0", int_type)
    module = _single_block_module([IRConst(value, 42)], value)

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_keeps_value_used_by_store() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    value = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(value, 7), IRStore(slot, value), IRReturn()],
                    )
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_keeps_value_used_as_call_argument_and_keeps_call() -> None:
    int_type = IntType()
    argument = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "consume",
                [IRParameter("value", int_type)],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn()])],
            ),
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(argument, 5), IRCall("consume", (argument,)), IRReturn()],
                    )
                ],
            ),
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_keeps_value_used_by_branch_condition() -> None:
    bool_type = BoolType()
    condition = IRValue("0", bool_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(condition, True), IRBranch(condition, "then", "else")],
                    ),
                    IRBasicBlock("then", [IRReturn()]),
                    IRBasicBlock("else", [IRReturn()]),
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_works_across_multiple_blocks() -> None:
    int_type = IntType()
    bool_type = BoolType()
    unused = IRValue("0", int_type)
    condition = IRValue("1", bool_type)
    then_value = IRValue("2", int_type)
    else_value = IRValue("3", int_type)
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
                            IRConst(unused, 99),
                            IRConst(condition, True),
                            IRBranch(condition, "then", "else"),
                        ],
                    ),
                    IRBasicBlock(
                        "then",
                        [IRConst(then_value, 1), IRReturn(then_value)],
                    ),
                    IRBasicBlock(
                        "else",
                        [IRConst(else_value, 2), IRReturn(else_value)],
                    ),
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %1: bool = const true\n"
        "    branch %1, then, else\n"
        "\n"
        "then:\n"
        "    %2: int = const 1\n"
        "    return %2\n"
        "\n"
        "else:\n"
        "    %3: int = const 2\n"
        "    return %3\n"
        "}"
    )


def test_dead_code_does_not_remove_call_with_unused_result() -> None:
    int_type = IntType()
    argument = IRValue("0", int_type)
    call_result = IRValue("1", int_type)
    return_value = IRValue("2", int_type)
    module = IRModule(
        [
            IRFunction(
                "identity",
                [IRParameter("value", int_type)],
                int_type,
                [IRBasicBlock("entry", [IRReturn(IRParameter("value", int_type))])],
            ),
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(argument, 5),
                            IRCall("identity", (argument,), call_result),
                            IRConst(return_value, 0),
                            IRReturn(return_value),
                        ],
                    )
                ],
            ),
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_does_not_remove_terminators() -> None:
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("exit")]),
                    IRBasicBlock("exit", [IRReturn()]),
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_does_not_remove_used_load() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
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
                            IRConst(stored, 4),
                            IRStore(slot, stored),
                            IRLoad(loaded, slot),
                            IRReturn(loaded),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_keeps_chain_needed_to_calculate_return_when_not_folded() -> None:
    int_type = IntType()
    parameter = IRParameter("x", int_type)
    one = IRValue("0", int_type)
    sum_ = IRValue("1", int_type)
    doubled = IRValue("2", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(one, 1),
                            IRBinaryOp(sum_, "add", parameter, one),
                            IRBinaryOp(doubled, "mul", sum_, parameter),
                            IRReturn(doubled),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)
