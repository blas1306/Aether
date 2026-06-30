from __future__ import annotations

import pytest

from aether.ir import (
    BoolType,
    DoubleType,
    IRBasicBlock,
    IRBinaryOp,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRLoad,
    IRModule,
    IRParameter,
    IRReturn,
    IRStore,
    IRValue,
    IntType,
    print_ir,
)
from aether.ir.optimizer import ConstantFolder, OptimizerPipeline


def _optimize(module: IRModule) -> IRModule:
    return ConstantFolder().run(module)


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


def test_constant_folding_function_with_several_constants() -> None:
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
        "    %0: int = const 1\n"
        "    %1: int = const 2\n"
        "    %2: int = const 3\n"
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
