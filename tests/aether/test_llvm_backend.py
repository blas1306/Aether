from __future__ import annotations

import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackendError, print_llvm
from aether.ir import BoolType, DoubleType, IntType, MatrixType, StringType, VectorType, VoidType
from aether.ssa import (
    SSABasicBlock,
    SSABinaryOp,
    SSABranch,
    SSACast,
    SSACall,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAJump,
    SSAMatrixNew,
    SSAModule,
    SSAParameter,
    SSAPhi,
    SSAReturn,
    SSAValue,
    SSAVectorNew,
)


def test_prints_main_returning_int_constant() -> None:
    int_type = IntType()
    value = SSAValue("0", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [SSABasicBlock("entry", [SSAConst(value, 5), SSAReturn(value)])],
            )
        ]
    )

    assert print_llvm(module) == (
        "define i32 @main() {\n"
        "entry:\n"
        "  ret i32 5\n"
        "}"
    )


def test_prints_main_returning_sum() -> None:
    int_type = IntType()
    left = SSAValue("0", int_type)
    right = SSAValue("1", int_type)
    result = SSAValue("2", int_type)
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
                            SSAConst(left, 2),
                            SSAConst(right, 3),
                            SSABinaryOp(result, "add", left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    llvm = print_llvm(module)

    assert "@llvm.sadd.with.overflow.i32" in llvm
    assert "define private i32 @aether_checked_add_i32" in llvm
    assert (
        "define i32 @main() {\n"
        "entry:\n"
        "  %0 = call i32 @aether_checked_add_i32(i32 2, i32 3)\n"
        "  ret i32 %0\n"
        "}"
    ) in llvm


def test_prints_column_vector_literal_as_contiguous_array() -> None:
    int_type = IntType()
    first = SSAValue("0", int_type)
    second = SSAValue("1", int_type)
    third = SSAValue("2", int_type)
    vector = SSAValue("3", VectorType(int_type, "column"))
    return_value = SSAValue("4", int_type)
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
                            SSAConst(first, 1),
                            SSAConst(second, 2),
                            SSAConst(third, 3),
                            SSAVectorNew(vector, (first, second, third), "column"),
                            SSAConst(return_value, 0),
                            SSAReturn(return_value),
                        ],
                    )
                ],
            )
        ]
    )

    llvm = print_llvm(module)

    assert "@aether_array_new(i64 4, i64 3)" in llvm
    assert "store i32 1" in llvm
    assert "store i32 2" in llvm
    assert "store i32 3" in llvm


def test_prints_matrix_literal_as_contiguous_array() -> None:
    int_type = IntType()
    first = SSAValue("0", int_type)
    second = SSAValue("1", int_type)
    third = SSAValue("2", int_type)
    fourth = SSAValue("3", int_type)
    matrix = SSAValue("4", MatrixType(int_type))
    return_value = SSAValue("5", int_type)
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
                            SSAConst(first, 1),
                            SSAConst(second, 2),
                            SSAConst(third, 3),
                            SSAConst(fourth, 4),
                            SSAMatrixNew(matrix, (first, second, third, fourth), 2, 2),
                            SSAConst(return_value, 0),
                            SSAReturn(return_value),
                        ],
                    )
                ],
            )
        ]
    )

    llvm = print_llvm(module)

    assert "@aether_array_new(i64 4, i64 4)" in llvm
    assert "store i32 1" in llvm
    assert "store i32 2" in llvm
    assert "store i32 3" in llvm
    assert "store i32 4" in llvm


def test_rejects_vector_new_orientation_mismatch() -> None:
    int_type = IntType()
    value = SSAValue("0", int_type)
    vector = SSAValue("1", VectorType(int_type, "column"))
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
                            SSAConst(value, 1),
                            SSAVectorNew(vector, (value,), "row"),
                            SSAReturn(value),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(LLVMBackendError, match="instruction orientation must match"):
        print_llvm(module)


def test_prints_add_function_with_int_parameters() -> None:
    int_type = IntType()
    left = SSAParameter("a", int_type)
    right = SSAParameter("b", int_type)
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

    llvm = print_llvm(module)

    assert "@llvm.sadd.with.overflow.i32" in llvm
    assert (
        "define i32 @add(i32 %a, i32 %b) {\n"
        "entry:\n"
        "  %0 = call i32 @aether_checked_add_i32(i32 %a, i32 %b)\n"
        "  ret i32 %0\n"
        "}"
    ) in llvm


@pytest.mark.parametrize(
    ("operator", "helper", "result_type"),
    [
        ("sub", "sub", IntType()),
        ("mul", "mul", IntType()),
        ("div", "div", DoubleType()),
        ("mod", "rem", IntType()),
        ("rem", "rem", IntType()),
    ],
)
def test_prints_checked_int_binary_operations(operator: str, helper: str, result_type) -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    result = SSAValue("result", result_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                result_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(left, 8),
                            SSAConst(right, 2),
                            SSABinaryOp(result, operator, left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    llvm = print_llvm(module)
    llvm_result_type = "double" if isinstance(result_type, DoubleType) else "i32"

    assert (
        f"define {llvm_result_type} @main() {{\n"
        "entry:\n"
        f"  %0 = call {llvm_result_type} @aether_checked_{helper}_i32(i32 8, i32 2)\n"
        f"  ret {llvm_result_type} %0\n"
        "}"
    ) in llvm


@pytest.mark.parametrize(
    ("operator", "llvm_operator"),
    [
        ("add", "fadd"),
        ("sub", "fsub"),
        ("mul", "fmul"),
        ("div", "fdiv"),
    ],
)
def test_prints_double_binary_operations(operator: str, llvm_operator: str) -> None:
    double_type = DoubleType()
    left = SSAValue("left", double_type)
    right = SSAValue("right", double_type)
    result = SSAValue("result", double_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                double_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(left, 8.5),
                            SSAConst(right, 2.0),
                            SSABinaryOp(result, operator, left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_llvm(module) == (
        "define double @main() {\n"
        "entry:\n"
        f"  %0 = {llvm_operator} double 8.5, 2.0\n"
        "  ret double %0\n"
        "}"
    )


def test_prints_void_function() -> None:
    module = SSAModule(
        [
            SSAFunction(
                "nothing",
                [],
                VoidType(),
                [SSABasicBlock("entry", [SSAReturn()])],
            )
        ]
    )

    assert print_llvm(module) == (
        "define void @nothing() {\n"
        "entry:\n"
        "  ret void\n"
        "}"
    )


@pytest.mark.parametrize(
    ("operator", "predicate"),
    [
        ("lt", "slt"),
        ("le", "sle"),
        ("gt", "sgt"),
        ("ge", "sge"),
        ("eq", "eq"),
        ("ne", "ne"),
    ],
)
def test_prints_int_compare_operations(operator: str, predicate: str) -> None:
    int_type = IntType()
    bool_type = BoolType()
    left = SSAParameter("a", int_type)
    right = SSAParameter("b", int_type)
    result = SSAValue("0", bool_type)
    module = SSAModule(
        [
            SSAFunction(
                "compare",
                [left, right],
                bool_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSACompareOp(result, operator, left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_llvm(module) == (
        "define i1 @compare(i32 %a, i32 %b) {\n"
        "entry:\n"
        f"  %0 = icmp {predicate} i32 %a, %b\n"
        "  ret i1 %0\n"
        "}"
    )


@pytest.mark.parametrize(
    ("operator", "predicate"),
    [
        ("lt", "olt"),
        ("le", "ole"),
        ("gt", "ogt"),
        ("ge", "oge"),
        ("eq", "oeq"),
        ("ne", "one"),
    ],
)
def test_prints_double_compare_operations(operator: str, predicate: str) -> None:
    double_type = DoubleType()
    bool_type = BoolType()
    left = SSAParameter("a", double_type)
    right = SSAParameter("b", double_type)
    result = SSAValue("0", bool_type)
    module = SSAModule(
        [
            SSAFunction(
                "compare",
                [left, right],
                bool_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSACompareOp(result, operator, left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_llvm(module) == (
        "define i1 @compare(double %a, double %b) {\n"
        "entry:\n"
        f"  %0 = fcmp {predicate} double %a, %b\n"
        "  ret i1 %0\n"
        "}"
    )


def test_prints_int_to_double_cast() -> None:
    int_type = IntType()
    double_type = DoubleType()
    parameter = SSAParameter("x", int_type)
    result = SSAValue("0", double_type)
    module = SSAModule(
        [
            SSAFunction(
                "widen",
                [parameter],
                double_type,
                [SSABasicBlock("entry", [SSACast(result, parameter), SSAReturn(result)])],
            )
        ]
    )

    assert print_llvm(module) == (
        "define double @widen(i32 %x) {\n"
        "entry:\n"
        "  %0 = sitofp i32 %x to double\n"
        "  ret double %0\n"
        "}"
    )


def test_prints_double_to_int_cast() -> None:
    double_type = DoubleType()
    int_type = IntType()
    parameter = SSAParameter("x", double_type)
    result = SSAValue("0", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "narrow",
                [parameter],
                int_type,
                [SSABasicBlock("entry", [SSACast(result, parameter), SSAReturn(result)])],
            )
        ]
    )

    assert print_llvm(module) == (
        "define i32 @narrow(double %x) {\n"
        "entry:\n"
        "  %0 = fptosi double %x to i32\n"
        "  ret i32 %0\n"
        "}"
    )


def test_rejects_unsupported_cast() -> None:
    bool_type = BoolType()
    int_type = IntType()
    parameter = SSAParameter("flag", bool_type)
    result = SSAValue("0", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "bad",
                [parameter],
                int_type,
                [SSABasicBlock("entry", [SSACast(result, parameter), SSAReturn(result)])],
            )
        ]
    )

    with pytest.raises(
        LLVMBackendError,
        match="LLVM backend only supports casts from i32 to double or double to i32",
    ):
        print_llvm(module)


def test_prints_comparison_as_return_value() -> None:
    int_type = IntType()
    bool_type = BoolType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    result = SSAValue("result", bool_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                bool_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(left, 3),
                            SSAConst(right, 2),
                            SSACompareOp(result, "gt", left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_llvm(module) == (
        "define i1 @main() {\n"
        "entry:\n"
        "  %0 = icmp sgt i32 3, 2\n"
        "  ret i1 %0\n"
        "}"
    )


def test_prints_simple_jump() -> None:
    int_type = IntType()
    value = SSAValue("0", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock("entry", [SSAJump("exit0")]),
                    SSABasicBlock("exit0", [SSAConst(value, 7), SSAReturn(value)]),
                ],
            )
        ]
    )

    assert print_llvm(module) == (
        "define i32 @main() {\n"
        "entry:\n"
        "  br label %exit0\n"
        "exit0:\n"
        "  ret i32 7\n"
        "}"
    )


def test_prints_branch_with_comparison_condition() -> None:
    int_type = IntType()
    bool_type = BoolType()
    left = SSAParameter("x", int_type)
    zero = SSAValue("0", int_type)
    condition = SSAValue("1", bool_type)
    then_value = SSAValue("2", int_type)
    else_value = SSAValue("3", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "choose",
                [left],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(zero, 0),
                            SSACompareOp(condition, "gt", left, zero),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock(
                        "then0",
                        [SSAConst(then_value, 1), SSAReturn(then_value)],
                    ),
                    SSABasicBlock(
                        "else0",
                        [SSAConst(else_value, 2), SSAReturn(else_value)],
                    ),
                ],
            )
        ]
    )

    assert print_llvm(module) == (
        "define i32 @choose(i32 %x) {\n"
        "entry:\n"
        "  %0 = icmp sgt i32 %x, 0\n"
        "  br i1 %0, label %then0, label %else0\n"
        "then0:\n"
        "  ret i32 1\n"
        "else0:\n"
        "  ret i32 2\n"
        "}"
    )


def test_prints_branch_with_bool_parameter_condition() -> None:
    int_type = IntType()
    flag = SSAParameter("flag", BoolType())
    then_value = SSAValue("0", int_type)
    else_value = SSAValue("1", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "choose",
                [flag],
                int_type,
                [
                    SSABasicBlock("entry", [SSABranch(flag, "then0", "else0")]),
                    SSABasicBlock(
                        "then0",
                        [SSAConst(then_value, 1), SSAReturn(then_value)],
                    ),
                    SSABasicBlock(
                        "else0",
                        [SSAConst(else_value, 2), SSAReturn(else_value)],
                    ),
                ],
            )
        ]
    )

    assert "  br i1 %flag, label %then0, label %else0" in print_llvm(module)


def test_prints_int_phi_with_two_incoming_values() -> None:
    int_type = IntType()
    flag = SSAParameter("flag", BoolType())
    then_value = SSAValue("then_value", int_type)
    else_value = SSAValue("else_value", int_type)
    phi_value = SSAValue("phi_value", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "choose",
                [flag],
                int_type,
                [
                    SSABasicBlock("entry", [SSABranch(flag, "then0", "else0")]),
                    SSABasicBlock(
                        "then0",
                        [SSAConst(then_value, 1), SSAJump("merge0")],
                    ),
                    SSABasicBlock(
                        "else0",
                        [SSAConst(else_value, 2), SSAJump("merge0")],
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

    assert print_llvm(module) == (
        "define i32 @choose(i1 %flag) {\n"
        "entry:\n"
        "  br i1 %flag, label %then0, label %else0\n"
        "then0:\n"
        "  br label %merge0\n"
        "else0:\n"
        "  br label %merge0\n"
        "merge0:\n"
        "  %0 = phi i32 [ 1, %then0 ], [ 2, %else0 ]\n"
        "  ret i32 %0\n"
        "}"
    )


def test_prints_bool_phi() -> None:
    bool_type = BoolType()
    flag = SSAParameter("flag", bool_type)
    then_value = SSAValue("then_value", bool_type)
    else_value = SSAValue("else_value", bool_type)
    phi_value = SSAValue("phi_value", bool_type)
    module = SSAModule(
        [
            SSAFunction(
                "choose_flag",
                [flag],
                bool_type,
                [
                    SSABasicBlock("entry", [SSABranch(flag, "then0", "else0")]),
                    SSABasicBlock(
                        "then0",
                        [SSAConst(then_value, True), SSAJump("merge0")],
                    ),
                    SSABasicBlock(
                        "else0",
                        [SSAConst(else_value, False), SSAJump("merge0")],
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

    llvm_ir = print_llvm(module)

    assert "  %0 = phi i1 [ 1, %then0 ], [ 0, %else0 ]\n" in llvm_ir
    assert "  ret i1 %0" in llvm_ir


def test_prints_int_call_without_arguments() -> None:
    int_type = IntType()
    result = SSAValue("result", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [SSABasicBlock("entry", [SSACall("one", (), result), SSAReturn(result)])],
            )
        ]
    )

    assert print_llvm(module) == (
        "define i32 @main() {\n"
        "entry:\n"
        "  %0 = call i32 @one()\n"
        "  ret i32 %0\n"
        "}"
    )


def test_prints_int_call_with_arguments() -> None:
    int_type = IntType()
    left = SSAParameter("a", int_type)
    right = SSAParameter("b", int_type)
    result = SSAValue("result", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [left, right],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [SSACall("add", (left, right), result), SSAReturn(result)],
                    )
                ],
            )
        ]
    )

    assert print_llvm(module) == (
        "define i32 @main(i32 %a, i32 %b) {\n"
        "entry:\n"
        "  %0 = call i32 @add(i32 %a, i32 %b)\n"
        "  ret i32 %0\n"
        "}"
    )


def test_prints_bool_call() -> None:
    bool_type = BoolType()
    result = SSAValue("result", bool_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                bool_type,
                [
                    SSABasicBlock(
                        "entry",
                        [SSACall("ready", (), result), SSAReturn(result)],
                    )
                ],
            )
        ]
    )

    assert print_llvm(module) == (
        "define i1 @main() {\n"
        "entry:\n"
        "  %0 = call i1 @ready()\n"
        "  ret i1 %0\n"
        "}"
    )


def test_prints_double_call() -> None:
    double_type = DoubleType()
    result = SSAValue("result", double_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                double_type,
                [
                    SSABasicBlock(
                        "entry",
                        [SSACall("value", (), result), SSAReturn(result)],
                    )
                ],
            )
        ]
    )

    assert print_llvm(module) == (
        "define double @main() {\n"
        "entry:\n"
        "  %0 = call double @value()\n"
        "  ret double %0\n"
        "}"
    )


def test_prints_function_returning_string_literal_global() -> None:
    string_type = StringType()
    value = SSAValue("0", string_type)
    module = SSAModule(
        [
            SSAFunction(
                "hello",
                [],
                string_type,
                [SSABasicBlock("entry", [SSAConst(value, "hello"), SSAReturn(value)])],
            )
        ]
    )

    assert print_llvm(module) == (
        '@.str.0 = private unnamed_addr constant [6 x i8] c"hello\\00"\n'
        "\n"
        "define ptr @hello() {\n"
        "entry:\n"
        "  ret ptr @.str.0\n"
        "}"
    )


def test_prints_two_distinct_string_literals_as_two_globals() -> None:
    string_type = StringType()
    alpha = SSAValue("alpha", string_type)
    beta = SSAValue("beta", string_type)
    module = SSAModule(
        [
            SSAFunction(
                "alpha",
                [],
                string_type,
                [SSABasicBlock("entry", [SSAConst(alpha, "alpha"), SSAReturn(alpha)])],
            ),
            SSAFunction(
                "beta",
                [],
                string_type,
                [SSABasicBlock("entry", [SSAConst(beta, "beta"), SSAReturn(beta)])],
            ),
        ]
    )

    llvm_ir = print_llvm(module)

    assert '@.str.0 = private unnamed_addr constant [6 x i8] c"alpha\\00"' in llvm_ir
    assert '@.str.1 = private unnamed_addr constant [5 x i8] c"beta\\00"' in llvm_ir
    assert "  ret ptr @.str.0\n" in llvm_ir
    assert "  ret ptr @.str.1\n" in llvm_ir


def test_deduplicates_repeated_string_literals_by_value() -> None:
    string_type = StringType()
    first = SSAValue("first", string_type)
    second = SSAValue("second", string_type)
    module = SSAModule(
        [
            SSAFunction(
                "first",
                [],
                string_type,
                [SSABasicBlock("entry", [SSAConst(first, "same"), SSAReturn(first)])],
            ),
            SSAFunction(
                "second",
                [],
                string_type,
                [SSABasicBlock("entry", [SSAConst(second, "same"), SSAReturn(second)])],
            ),
        ]
    )

    llvm_ir = print_llvm(module)

    assert llvm_ir.count("private unnamed_addr constant") == 1
    assert llvm_ir.count("ret ptr @.str.0") == 2


def test_escapes_string_literal_bytes_for_llvm_c_string() -> None:
    string_type = StringType()
    value = SSAValue("value", string_type)
    module = SSAModule(
        [
            SSAFunction(
                "escaped",
                [],
                string_type,
                [
                    SSABasicBlock(
                        "entry",
                        [SSAConst(value, 'a\n\t"\\\x01é'), SSAReturn(value)],
                    )
                ],
            )
        ]
    )

    assert (
        '@.str.0 = private unnamed_addr constant [9 x i8] '
        'c"a\\0A\\09\\22\\5C\\01\\C3\\A9\\00"'
    ) in print_llvm(module)


def test_prints_string_literal_as_call_argument() -> None:
    string_type = StringType()
    text = SSAParameter("text", string_type)
    literal = SSAValue("literal", string_type)
    result = SSAValue("result", string_type)
    module = SSAModule(
        [
            SSAFunction(
                "echo",
                [text],
                string_type,
                [SSABasicBlock("entry", [SSAReturn(text)])],
            ),
            SSAFunction(
                "main",
                [],
                string_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(literal, "hello"),
                            SSACall("echo", (literal,), result),
                            SSAReturn(result),
                        ],
                    )
                ],
            ),
        ]
    )

    assert print_llvm(module) == (
        '@.str.0 = private unnamed_addr constant [6 x i8] c"hello\\00"\n'
        "\n"
        "define ptr @echo(ptr %text) {\n"
        "entry:\n"
        "  ret ptr %text\n"
        "}\n"
        "\n"
        "define ptr @main() {\n"
        "entry:\n"
        "  %0 = call ptr @echo(ptr @.str.0)\n"
        "  ret ptr %0\n"
        "}"
    )


def test_prints_void_call_without_result() -> None:
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                VoidType(),
                [SSABasicBlock("entry", [SSACall("tick"), SSAReturn()])],
            )
        ]
    )

    assert print_llvm(module) == (
        "define void @main() {\n"
        "entry:\n"
        "  call void @tick()\n"
        "  ret void\n"
        "}"
    )


def test_prints_call_with_multiple_argument_types() -> None:
    int_type = IntType()
    bool_type = BoolType()
    count = SSAParameter("count", int_type)
    flag = SSAParameter("flag", bool_type)
    result = SSAValue("result", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [count, flag],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSACall("choose", (count, flag, count), result),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert (
        "  %0 = call i32 @choose(i32 %count, i1 %flag, i32 %count)\n"
        in print_llvm(module)
    )


def test_prints_function_that_calls_another_function() -> None:
    int_type = IntType()
    one_value = SSAValue("one", int_type)
    call_result = SSAValue("result", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "one",
                [],
                int_type,
                [SSABasicBlock("entry", [SSAConst(one_value, 1), SSAReturn(one_value)])],
            ),
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [SSACall("one", (), call_result), SSAReturn(call_result)],
                    )
                ],
            ),
        ]
    )

    assert print_llvm(module) == (
        "define i32 @one() {\n"
        "entry:\n"
        "  ret i32 1\n"
        "}\n"
        "\n"
        "define i32 @main() {\n"
        "entry:\n"
        "  %0 = call i32 @one()\n"
        "  ret i32 %0\n"
        "}"
    )


def test_prints_string_call_result() -> None:
    result = SSAValue("result", StringType())
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                StringType(),
                [SSABasicBlock("entry", [SSACall("text", (), result), SSAReturn(result)])],
            )
        ]
    )

    assert "  %0 = call ptr @text()\n" in print_llvm(module)


def test_prints_string_call_argument() -> None:
    argument = SSAParameter("text", StringType())
    result = SSAValue("result", IntType())
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                IntType(),
                [SSABasicBlock("entry", [SSACall("length", (argument,), result)])],
            )
        ]
    )

    assert "  %0 = call i32 @length(ptr %text)\n" in print_llvm(module)


def test_prints_phi_incoming_values_in_original_order() -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    middle = SSAValue("middle", int_type)
    right = SSAValue("right", int_type)
    phi_value = SSAValue("phi_value", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "choose",
                [],
                int_type,
                [
                    SSABasicBlock("entry", [SSAJump("left0")]),
                    SSABasicBlock("left0", [SSAConst(left, 10), SSAJump("merge0")]),
                    SSABasicBlock(
                        "middle0",
                        [SSAConst(middle, 20), SSAJump("merge0")],
                    ),
                    SSABasicBlock("right0", [SSAConst(right, 30), SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(
                                phi_value,
                                (
                                    ("left0", left),
                                    ("middle0", middle),
                                    ("right0", right),
                                ),
                            ),
                            SSAReturn(phi_value),
                        ],
                    ),
                ],
            )
        ]
    )

    assert (
        "  %0 = phi i32 [ 10, %left0 ], [ 20, %middle0 ], [ 30, %right0 ]\n"
        in print_llvm(module)
    )


def test_loop_carried_phi_uses_same_name_as_later_definition() -> None:
    int_type = IntType()
    bool_type = BoolType()
    n = SSAParameter("n", int_type)
    zero = SSAValue("zero", int_type)
    one = SSAValue("one", int_type)
    current = SSAValue("current", int_type)
    condition = SSAValue("condition", bool_type)
    next_value = SSAValue("next", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "countdown",
                [n],
                int_type,
                [
                    SSABasicBlock("entry", [SSAJump("cond0")]),
                    SSABasicBlock(
                        "cond0",
                        [
                            SSAPhi(current, (("entry", n), ("body0", next_value))),
                            SSAConst(zero, 0),
                            SSACompareOp(condition, "gt", current, zero),
                            SSABranch(condition, "body0", "exit0"),
                        ],
                    ),
                    SSABasicBlock(
                        "body0",
                        [
                            SSAConst(one, 1),
                            SSABinaryOp(next_value, "sub", current, one),
                            SSAJump("cond0"),
                        ],
                    ),
                    SSABasicBlock("exit0", [SSAReturn(current)]),
                ],
            )
        ]
    )

    llvm_ir = print_llvm(module)
    sub_result = next(
        line.strip().split(" = ", 1)[0]
        for line in llvm_ir.splitlines()
        if " = call i32 @aether_checked_sub_i32" in line
    )

    assert f"[ {sub_result}, %body0 ]" in llvm_ir
    assert f"{sub_result} = call i32 @aether_checked_sub_i32" in llvm_ir


def test_empty_phi_incoming_has_clear_error() -> None:
    int_type = IntType()
    phi_value = SSAValue("phi_value", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [SSABasicBlock("entry", [SSAPhi(phi_value, ())])],
            )
        ]
    )

    with pytest.raises(
        LLVMBackendError,
        match="LLVM backend does not support phi with no incoming values",
    ):
        print_llvm(module)


def test_prints_string_phi_as_ptr() -> None:
    string_type = StringType()
    flag = SSAParameter("flag", BoolType())
    then_value = SSAValue("then_value", string_type)
    else_value = SSAValue("else_value", string_type)
    phi_value = SSAValue("phi_value", string_type)
    module = SSAModule(
        [
            SSAFunction(
                "choose",
                [flag],
                string_type,
                [
                    SSABasicBlock("entry", [SSABranch(flag, "then0", "else0")]),
                    SSABasicBlock(
                        "then0",
                        [SSAConst(then_value, "yes"), SSAJump("merge0")],
                    ),
                    SSABasicBlock(
                        "else0",
                        [SSAConst(else_value, "no"), SSAJump("merge0")],
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

    llvm_ir = print_llvm(module)

    assert "  %0 = phi ptr [ @.str.0, %then0 ], [ @.str.1, %else0 ]\n" in llvm_ir
    assert "  ret ptr %0" in llvm_ir


def test_branch_condition_must_be_bool() -> None:
    int_type = IntType()
    condition = SSAParameter("condition", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [condition],
                int_type,
                [SSABasicBlock("entry", [SSABranch(condition, "then0", "else0")])],
            )
        ]
    )

    with pytest.raises(
        LLVMBackendError,
        match="LLVM backend only supports bool/i1 branch conditions",
    ):
        print_llvm(module)


def test_labels_and_label_references_are_printed_consistently() -> None:
    int_type = IntType()
    value = SSAValue("0", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock("custom.entry", [SSAJump("custom.exit")]),
                    SSABasicBlock(
                        "custom.exit",
                        [SSAConst(value, 9), SSAReturn(value)],
                    ),
                ],
            )
        ]
    )

    llvm_ir = print_llvm(module)

    assert "custom.entry:\n" in llvm_ir
    assert "  br label %custom.exit\n" in llvm_ir
    assert "custom.exit:\n" in llvm_ir


def test_string_type_maps_to_ptr() -> None:
    value = SSAValue("0", StringType())
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                StringType(),
                [SSABasicBlock("entry", [SSAConst(value, "hello"), SSAReturn(value)])],
            )
        ]
    )

    assert "define ptr @main()" in print_llvm(module)


def test_string_binary_operation_has_clear_error() -> None:
    string_type = StringType()
    left = SSAValue("left", string_type)
    right = SSAValue("right", string_type)
    result = SSAValue("result", string_type)
    module = SSAModule(
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
                            SSABinaryOp(result, "add", left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(
        LLVMBackendError,
        match="LLVM backend does not support string binary operations yet",
    ):
        print_llvm(module)


def test_string_comparison_has_clear_error() -> None:
    string_type = StringType()
    bool_type = BoolType()
    left = SSAValue("left", string_type)
    right = SSAValue("right", string_type)
    result = SSAValue("result", bool_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                bool_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(left, "a"),
                            SSAConst(right, "b"),
                            SSACompareOp(result, "eq", left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(
        LLVMBackendError,
        match="LLVM backend does not support string comparisons yet",
    ):
        print_llvm(module)


def test_unknown_binary_operator_has_clear_error() -> None:
    int_type = IntType()
    left = SSAParameter("a", int_type)
    right = SSAParameter("b", int_type)
    result = SSAValue("0", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [left, right],
                int_type,
                [SSABasicBlock("entry", [SSABinaryOp(result, "pow", left, right)])],
            )
        ]
    )

    with pytest.raises(
        LLVMBackendError,
        match="LLVM backend does not support binary operator 'pow'",
    ):
        print_llvm(module)


def test_unknown_compare_operator_has_clear_error() -> None:
    int_type = IntType()
    bool_type = BoolType()
    left = SSAParameter("a", int_type)
    right = SSAParameter("b", int_type)
    result = SSAValue("0", bool_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [left, right],
                bool_type,
                [SSABasicBlock("entry", [SSACompareOp(result, "same", left, right)])],
            )
        ]
    )

    with pytest.raises(
        LLVMBackendError,
        match="LLVM backend does not support compare operator 'same'",
    ):
        print_llvm(module)


def test_non_i32_compare_has_clear_error() -> None:
    bool_type = BoolType()
    left = SSAParameter("a", bool_type)
    right = SSAParameter("b", bool_type)
    result = SSAValue("0", bool_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [left, right],
                bool_type,
                [SSABasicBlock("entry", [SSACompareOp(result, "eq", left, right)])],
            )
        ]
    )

    with pytest.raises(
        LLVMBackendError,
        match="LLVM backend only supports i32 or double comparisons producing i1",
    ):
        print_llvm(module)


def test_generated_main_can_be_compiled_with_clang_if_available(tmp_path) -> None:
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("clang is not available")

    int_type = IntType()
    left = SSAValue("0", int_type)
    right = SSAValue("1", int_type)
    result = SSAValue("2", int_type)
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
                            SSAConst(left, 2),
                            SSAConst(right, 3),
                            SSABinaryOp(result, "add", left, right),
                            SSAReturn(result),
                        ],
                    )
                ],
            )
        ]
    )
    ir_path = tmp_path / "main.ll"
    exe_path = tmp_path / "main"
    ir_path.write_text(print_llvm(module), encoding="utf-8")

    subprocess.run([clang, str(ir_path), "-o", str(exe_path)], check=True)
    result_process = subprocess.run([str(exe_path)], check=False)

    assert result_process.returncode == 5


def test_generated_bool_main_compare_can_be_compiled_with_clang_if_available(
    tmp_path,
) -> None:
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("clang is not available")

    int_type = IntType()
    bool_type = BoolType()
    left = SSAValue("0", int_type)
    right = SSAValue("1", int_type)
    comparison = SSAValue("2", bool_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                bool_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(left, 3),
                            SSAConst(right, 2),
                            SSACompareOp(comparison, "gt", left, right),
                            SSAReturn(comparison),
                        ],
                    )
                ],
            )
        ]
    )
    ir_path = tmp_path / "bool_main.ll"
    exe_path = tmp_path / "bool_main"
    ir_path.write_text(print_llvm(module), encoding="utf-8")

    subprocess.run([clang, str(ir_path), "-o", str(exe_path)], check=True)
    result_process = subprocess.run([str(exe_path)], check=False)

    assert result_process.returncode == 1


def test_generated_string_literal_function_can_be_compiled_with_clang_if_available(
    tmp_path,
) -> None:
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("clang is not available")

    string_type = StringType()
    value = SSAValue("0", string_type)
    module = SSAModule(
        [
            SSAFunction(
                "hello",
                [],
                string_type,
                [SSABasicBlock("entry", [SSAConst(value, "hello"), SSAReturn(value)])],
            )
        ]
    )
    ir_path = tmp_path / "hello_string.ll"
    object_path = tmp_path / "hello_string.o"
    ir_path.write_text(print_llvm(module), encoding="utf-8")

    subprocess.run([clang, "-c", str(ir_path), "-o", str(object_path)], check=True)


def test_generated_phi_max_function_can_be_compiled_with_clang_if_available(
    tmp_path,
) -> None:
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("clang is not available")

    int_type = IntType()
    bool_type = BoolType()
    left = SSAParameter("a", int_type)
    right = SSAParameter("b", int_type)
    condition = SSAValue("0", bool_type)
    result = SSAValue("1", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "max",
                [left, right],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSACompareOp(condition, "gt", left, right),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(result, (("then0", left), ("else0", right))),
                            SSAReturn(result),
                        ],
                    ),
                ],
            )
        ]
    )
    llvm_ir = print_llvm(module)
    assert "phi i32 [ %a, %then0 ], [ %b, %else0 ]" in llvm_ir

    ir_path = tmp_path / "max.ll"
    object_path = tmp_path / "max.o"
    ir_path.write_text(llvm_ir, encoding="utf-8")

    subprocess.run([clang, "-c", str(ir_path), "-o", str(object_path)], check=True)


def test_generated_branch_main_can_be_compiled_with_clang_if_available(
    tmp_path,
) -> None:
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("clang is not available")

    int_type = IntType()
    bool_type = BoolType()
    condition = SSAValue("0", bool_type)
    then_value = SSAValue("1", int_type)
    else_value = SSAValue("2", int_type)
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
                    SSABasicBlock(
                        "then0",
                        [SSAConst(then_value, 1), SSAReturn(then_value)],
                    ),
                    SSABasicBlock(
                        "else0",
                        [SSAConst(else_value, 2), SSAReturn(else_value)],
                    ),
                ],
            )
        ]
    )
    ir_path = tmp_path / "branch_main.ll"
    exe_path = tmp_path / "branch_main"
    ir_path.write_text(print_llvm(module), encoding="utf-8")

    subprocess.run([clang, str(ir_path), "-o", str(exe_path)], check=True)
    result_process = subprocess.run([str(exe_path)], check=False)

    assert result_process.returncode == 1
