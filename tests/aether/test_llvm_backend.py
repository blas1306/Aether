from __future__ import annotations

import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackendError, print_llvm
from aether.ir import BoolType, IntType, StringType, VoidType
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

    assert print_llvm(module) == (
        "define i32 @main() {\n"
        "entry:\n"
        "  %0 = add i32 2, 3\n"
        "  ret i32 %0\n"
        "}"
    )


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

    assert print_llvm(module) == (
        "define i32 @add(i32 %a, i32 %b) {\n"
        "entry:\n"
        "  %0 = add i32 %a, %b\n"
        "  ret i32 %0\n"
        "}"
    )


@pytest.mark.parametrize(
    ("operator", "llvm_operator"),
    [
        ("sub", "sub"),
        ("mul", "mul"),
        ("div", "sdiv"),
        ("mod", "srem"),
        ("rem", "srem"),
    ],
)
def test_prints_int_binary_operations(operator: str, llvm_operator: str) -> None:
    int_type = IntType()
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    result = SSAValue("result", int_type)
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

    assert print_llvm(module) == (
        "define i32 @main() {\n"
        "entry:\n"
        f"  %0 = {llvm_operator} i32 8, 2\n"
        "  ret i32 %0\n"
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


def test_call_result_with_unsupported_type_has_clear_error() -> None:
    result = SSAValue("result", StringType())
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                IntType(),
                [SSABasicBlock("entry", [SSACall("text", (), result)])],
            )
        ]
    )

    with pytest.raises(
        LLVMBackendError,
        match="LLVM backend does not support type string",
    ):
        print_llvm(module)


def test_call_argument_with_unsupported_type_has_clear_error() -> None:
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

    with pytest.raises(
        LLVMBackendError,
        match="LLVM backend does not support type string",
    ):
        print_llvm(module)


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


def test_unsupported_phi_type_has_clear_error() -> None:
    phi_value = SSAValue("phi_value", StringType())
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                StringType(),
                [SSABasicBlock("entry", [SSAPhi(phi_value, (("entry", phi_value),))])],
            )
        ]
    )

    with pytest.raises(
        LLVMBackendError,
        match="LLVM backend does not support type string",
    ):
        print_llvm(module)


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


def test_string_type_has_clear_error() -> None:
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

    with pytest.raises(
        LLVMBackendError,
        match="LLVM backend does not support type string",
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
        match="LLVM backend only supports i32 integer comparisons producing i1",
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
