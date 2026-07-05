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
            lambda condition, value: SSABranch(condition, "then0", "else0"),
            "LLVM backend does not support branch",
        ),
        (
            lambda condition, value: SSAJump("exit0"),
            "LLVM backend does not support jump",
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
