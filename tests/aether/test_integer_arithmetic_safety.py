from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether.backend.llvm import LLVMRunner, print_llvm
from aether.errors import AetherRuntimeError
from aether.integer_arithmetic import DIVISION_BY_ZERO_MESSAGE, INTEGER_OVERFLOW_MESSAGE
from aether.ir import (
    IRBasicBlock,
    IRBinaryOp,
    IRConst,
    IRExecutionError,
    IRFunction,
    IRInterpreter,
    IRModule,
    IRReturn,
    IRValue,
    IntType,
)
from aether.ir.optimizer import DeadCodeEliminator, OptimizerPipeline
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import SSABinaryOp, SSAValue
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


PANIC_CASES = [
    ("int x = 5; double result = x / 0;", DIVISION_BY_ZERO_MESSAGE),
    ("int x = 5; int result = x % 0;", DIVISION_BY_ZERO_MESSAGE),
    ("int x = 2147483647; int result = x + 1;", INTEGER_OVERFLOW_MESSAGE),
    ("int x = -2147483648; int result = x - 1;", INTEGER_OVERFLOW_MESSAGE),
    ("int x = 50000; int result = x * 50000;", INTEGER_OVERFLOW_MESSAGE),
    ("int x = -2147483648; int result = -x;", INTEGER_OVERFLOW_MESSAGE),
    ("int x = -2147483648; double result = x / -1;", INTEGER_OVERFLOW_MESSAGE),
]


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _compiled_source(body: str) -> str:
    return f"int main() {{ {body} return 0; }}"


@pytest.mark.parametrize(("body", "message"), PANIC_CASES)
def test_ast_and_ir_integer_panics_match(body: str, message: str) -> None:
    with pytest.raises(AetherRuntimeError) as ast_error:
        run_aether(body)
    assert str(ast_error.value) == message

    module = IRBackend().lower_verified(_typed(_compiled_source(body)))
    with pytest.raises(IRExecutionError) as ir_error:
        IRInterpreter(module).call("main")
    assert str(ir_error.value) == message


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize(("body", "message"), PANIC_CASES)
def test_native_integer_panics_match_ast_and_ir(body: str, message: str) -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = LLVMRunner().run(_typed(_compiled_source(body)), stdout=stdout, stderr=stderr)

    assert exit_code == 1
    assert stdout.getvalue() == f"{message}\n"
    assert stderr.getvalue() == ""


def test_non_overflowing_integer_operations_keep_their_values() -> None:
    body = """
println(40 + 2);
println(-2147483648 + 1);
println(50000 * 100);
println(-(-2147483647));
println(5 / 2);
println(-5 % 2);
"""
    expected = "42\n-2147483647\n5000000\n2147483647\n2.5\n-1\n"

    assert run_aether(body).output == expected

    interpreter = IRInterpreter(IRBackend().lower_verified(_typed(_compiled_source(body))))
    assert interpreter.call("main") == 0
    assert interpreter.output == expected


def test_float_division_by_zero_keeps_ieee_754_semantics() -> None:
    body = "println(1.0 / 0.0); println(0.0 / 0.0);"

    assert run_aether(body).output == "Infinity\nNaN\n"

    interpreter = IRInterpreter(IRBackend().lower_verified(_typed(_compiled_source(body))))
    assert interpreter.call("main") == 0
    assert interpreter.output == "Infinity\nNaN\n"


def test_int_binary_effect_is_derived_from_operand_types() -> None:
    int_type = IntType()
    ir_left = IRValue("left", int_type)
    ir_right = IRValue("right", int_type)
    ir_result = IRValue("result", int_type)
    ssa_left = SSAValue("left", int_type)
    ssa_right = SSAValue("right", int_type)
    ssa_result = SSAValue("result", int_type)

    ir_operation = IRBinaryOp(ir_result, "add", ir_left, ir_right)
    ssa_operation = SSABinaryOp(ssa_result, "add", ssa_left, ssa_right)

    assert ir_operation.may_trap is True
    assert ssa_operation.may_trap is True


def test_ir_optimizer_preserves_unused_overflowing_operation() -> None:
    int_type = IntType()
    left = IRValue("left", int_type)
    right = IRValue("right", int_type)
    result = IRValue("result", int_type)
    zero = IRValue("zero", int_type)
    operation = IRBinaryOp(result, "add", left, right)
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
                            IRConst(left, 2147483647),
                            IRConst(right, 1),
                            operation,
                            IRConst(zero, 0),
                            IRReturn(zero),
                        ],
                    )
                ],
            )
        ]
    )

    assert DeadCodeEliminator().run(module).module.functions[0].blocks[0].instructions[2] == operation
    optimized = OptimizerPipeline(iterative=True).run(module)
    assert any(isinstance(instruction, IRBinaryOp) for instruction in optimized.functions[0].blocks[0].instructions)


@pytest.mark.parametrize(
    ("type_name", "expression"),
    [("double", "5 / 0"), ("int", "5 % 0"), ("int", "2147483647 + 1")],
)
def test_unused_initialized_operation_survives_ir_and_ssa_optimization(
    type_name: str,
    expression: str,
) -> None:
    typed = _typed(f"int main() {{ {type_name} unused = {expression}; return 0; }}")
    backend = IRBackend()

    ir_module = backend.optimize_verified(backend.lower_verified(typed))
    ssa_module = SSAOptimizerPipeline().run(lower_to_verified_ssa(typed))

    assert any(
        isinstance(instruction, IRBinaryOp)
        for block in ir_module.functions[0].blocks
        for instruction in block.instructions
    )
    assert any(
        isinstance(instruction, SSABinaryOp)
        for block in ssa_module.functions[0].blocks
        for instruction in block.instructions
    )


def test_ssa_optimizer_preserves_unused_overflowing_operation() -> None:
    module = lower_to_verified_ssa(_typed("int main() { int unused = 2147483647 + 1; return 0; }"))

    optimized = SSAOptimizerPipeline().run(module)

    assert any(
        isinstance(instruction, SSABinaryOp)
        for block in optimized.functions[0].blocks
        for instruction in block.instructions
    )


def test_llvm_uses_overflow_intrinsics_and_explicit_division_checks() -> None:
    source = """
int add(int left, int right) { return left + right; }
int sub(int left, int right) { return left - right; }
int mul(int left, int right) { return left * right; }
double div(int left, int right) { return left / right; }
int rem(int left, int right) { return left % right; }
int main() { return 0; }
"""
    llvm = print_llvm(lower_to_verified_ssa(_typed(source)))

    assert "@llvm.sadd.with.overflow.i32" in llvm
    assert "@llvm.ssub.with.overflow.i32" in llvm
    assert "@llvm.smul.with.overflow.i32" in llvm
    assert "icmp eq i32 %right, 0" in llvm
    assert "icmp eq i32 %left, -2147483648" in llvm
    assert "call void @aether_integer_division_by_zero_panic()" in llvm
    assert "call void @aether_integer_overflow_panic()" in llvm
