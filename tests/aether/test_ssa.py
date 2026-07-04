from __future__ import annotations

import aether.ssa as ssa
import aether.ssa.model as ssa_model
from aether.ir import BoolType, IntType, VoidType
from aether.ssa import (
    SSABasicBlock,
    SSABinaryOp,
    SSABranch,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAJump,
    SSAModule,
    SSAParameter,
    SSAPhi,
    SSAReturn,
    SSAValue,
    print_ssa,
)


def test_create_simple_ssa_module() -> None:
    int_type = IntType()
    value = SSAValue("0", int_type)
    function = SSAFunction(
        "answer",
        [],
        int_type,
        [SSABasicBlock("entry", [SSAConst(value, 42), SSAReturn(value)])],
    )
    module = SSAModule([function])

    assert module.functions == [function]
    assert function.entry_block == "entry"
    assert function.blocks[0].instructions[0] == SSAConst(value, 42)


def test_print_linear_function() -> None:
    int_type = IntType()
    left = SSAParameter("left", int_type)
    right = SSAParameter("right", int_type)
    result = SSAValue("0", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "add",
                [left, right],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSABinaryOp(result, "add", left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ssa(module) == (
        "func @add(%left: int, %right: int) -> int {\n"
        "entry:\n"
        "    %0: int = add %left, %right\n"
        "    return %0\n"
        "}"
    )


def test_print_if_else_with_manual_phi() -> None:
    int_type = IntType()
    bool_type = BoolType()
    parameter = SSAParameter("x", int_type)
    zero = SSAValue("0", int_type)
    condition = SSAValue("1", bool_type)
    then_value = SSAValue("2", int_type)
    else_value = SSAValue("3", int_type)
    merged = SSAValue("4", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "f",
                [parameter],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(zero, 0),
                            SSACompareOp(condition, "gt", parameter, zero),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock(
                        "then0",
                        [
                            SSAConst(then_value, 1),
                            SSAJump("merge0"),
                        ],
                    ),
                    SSABasicBlock(
                        "else0",
                        [
                            SSAConst(else_value, 2),
                            SSAJump("merge0"),
                        ],
                    ),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(merged, (("then0", then_value), ("else0", else_value))),
                            SSAReturn(merged),
                        ],
                    ),
                ],
            )
        ]
    )

    assert print_ssa(module) == (
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


def test_print_while_with_manual_phi() -> None:
    int_type = IntType()
    bool_type = BoolType()
    zero = SSAValue("0", int_type)
    initial_i = SSAValue("1", int_type)
    loop_i = SSAValue("2", int_type)
    limit = SSAValue("3", int_type)
    condition = SSAValue("4", bool_type)
    one = SSAValue("5", int_type)
    next_i = SSAValue("6", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "count",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(zero, 0),
                            SSAConst(initial_i, 0),
                            SSAConst(limit, 3),
                            SSAJump("loop0"),
                        ],
                    ),
                    SSABasicBlock(
                        "loop0",
                        [
                            SSAPhi(loop_i, (("entry", initial_i), ("body0", next_i))),
                            SSACompareOp(condition, "lt", loop_i, limit),
                            SSABranch(condition, "body0", "exit0"),
                        ],
                    ),
                    SSABasicBlock(
                        "body0",
                        [
                            SSAConst(one, 1),
                            SSABinaryOp(next_i, "add", loop_i, one),
                            SSAJump("loop0"),
                        ],
                    ),
                    SSABasicBlock("exit0", [SSAReturn(loop_i)]),
                ],
            )
        ]
    )

    assert print_ssa(module) == (
        "func @count() -> int {\n"
        "entry:\n"
        "    %0: int = const 0\n"
        "    %1: int = const 0\n"
        "    %3: int = const 3\n"
        "    jump loop0\n"
        "\n"
        "loop0:\n"
        "    %2: int = phi(entry: %1, body0: %6)\n"
        "    %4: bool = cmp_lt %2, %3\n"
        "    branch %4, body0, exit0\n"
        "\n"
        "body0:\n"
        "    %5: int = const 1\n"
        "    %6: int = add %2, %5\n"
        "    jump loop0\n"
        "\n"
        "exit0:\n"
        "    return %2\n"
        "}"
    )


def test_print_phi_with_multiple_incoming_values() -> None:
    int_type = IntType()
    first = SSAValue("0", int_type)
    second = SSAValue("1", int_type)
    third = SSAValue("2", int_type)
    merged = SSAValue("3", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "choose3",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(
                                merged,
                                (
                                    ("left0", first),
                                    ("middle0", second),
                                    ("right0", third),
                                ),
                            ),
                            SSAReturn(merged),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ssa(module) == (
        "func @choose3() -> int {\n"
        "merge0:\n"
        "    %3: int = phi(left0: %0, middle0: %1, right0: %2)\n"
        "    return %3\n"
        "}"
    )


def test_print_module_with_multiple_functions() -> None:
    void_type = VoidType()
    module = SSAModule(
        [
            SSAFunction("first", [], void_type, [SSABasicBlock("entry", [SSAReturn()])]),
            SSAFunction("second", [], void_type, [SSABasicBlock("entry", [SSAReturn()])]),
        ]
    )

    assert print_ssa(module) == (
        "func @first() -> void {\n"
        "entry:\n"
        "    return\n"
        "}\n"
        "\n"
        "func @second() -> void {\n"
        "entry:\n"
        "    return\n"
        "}"
    )


def test_ssa_model_does_not_expose_load_or_store() -> None:
    exported_names = set(ssa.__all__)
    package_names = set(dir(ssa))
    model_names = set(dir(ssa_model))

    assert "SSALoad" not in exported_names
    assert "SSAStore" not in exported_names
    assert "SSALoad" not in package_names
    assert "SSAStore" not in package_names
    assert "SSALoad" not in model_names
    assert "SSAStore" not in model_names
