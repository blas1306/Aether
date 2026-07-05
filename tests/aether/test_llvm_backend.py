from __future__ import annotations

from collections.abc import Callable
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
    SSAInstruction,
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


@pytest.mark.parametrize(
    ("instruction", "message"),
    [
        (
            lambda condition, value: SSAPhi(value, (("entry", value),)),
            "LLVM backend does not support phi",
        ),
        (
            lambda condition, value: SSACall("other", (), value),
            "LLVM backend does not support call",
        ),
    ],
)
def test_unsupported_control_and_call_instructions_have_clear_errors(
    instruction: Callable[[SSAParameter, SSAValue], SSAInstruction],
    message: str,
) -> None:
    int_type = IntType()
    condition = SSAParameter("condition", BoolType())
    value = SSAValue("0", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [condition],
                int_type,
                [SSABasicBlock("entry", [instruction(condition, value)])],
            )
        ]
    )

    with pytest.raises(LLVMBackendError, match=message):
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
