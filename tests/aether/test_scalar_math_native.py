from __future__ import annotations

from io import StringIO
import math
from pathlib import Path
import shutil

import pytest

from aether.backend.llvm import LLVMBuilder, LLVMRunner
from aether.errors import AetherRuntimeError, AetherTypeError
from aether.integer_arithmetic import INTEGER_OVERFLOW_MESSAGE
from aether.ir import IRCall, IRExecutionError, IRInterpreter
from aether.ir.optimizer import DeadCodeEliminator
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import SSACall
from aether.typechecker import TypeChecker


IMPORTS = "import Math; from Math import floor; from Math import pi as circle;"
BODY = """
println(circle);
println(sqrt(9.0));
println(sin(0.0));
println(cos(0.0));
println(tan(0.0));
println(exp(0.0));
println(ln(exp(1.0)));
println(log(100.0));
println(floor(3.9));
println(Math.ceil(-1.2));
println(abs(-5));
println(abs(-2.5));
println(Math.factorial(5));
println(Math.mod(-5, 3));
println(Math.mod(5.5, 2.0));
"""
NATIVE_SOURCE = f"{IMPORTS} int main() {{ {BODY} return 0; }}"
AST_SOURCE = f"{IMPORTS} {BODY}"


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _numeric_lines(output: str) -> list[float]:
    return [float(line) for line in output.strip().splitlines()]


def test_scalar_math_existing_type_rules_are_preserved() -> None:
    result = run_aether(
        """
import Math;
float single = 1.0;
double transcendental = sin(single);
int integer_abs = abs(-3);
float float_abs = abs(single);
int rounded = Math.floor(3.5);
double mixed_mod = Math.mod(5, 2.0);
"""
    )
    assert result.env["transcendental"].type_name == "double"
    assert result.env["integer_abs"].type_name == "int"
    assert result.env["float_abs"].type_name == "float"
    assert result.env["rounded"].type_name == "int"
    assert result.env["mixed_mod"].type_name == "double"

    with pytest.raises(AetherTypeError, match="real numeric argument"):
        run_aether("println(sin(true));")
    with pytest.raises(AetherTypeError, match="Undefined function 'round'"):
        run_aether("println(round(1.5));")


def test_scalar_math_ast_ir_and_native_lowering_inventory() -> None:
    expected = _numeric_lines(run_aether(AST_SOURCE).output)

    ir_module = IRBackend().lower_verified(_typed(NATIVE_SOURCE))
    ir = IRInterpreter(ir_module)
    assert ir.call("main") == 0
    assert _numeric_lines(ir.output) == pytest.approx(expected)

    ir_calls = [
        instruction
        for function in ir_module.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCall)
    ]
    assert {call.builtin for call in ir_calls} >= {
        "sqrt",
        "sin",
        "cos",
        "tan",
        "exp",
        "ln",
        "log",
        "abs",
        "Math.floor",
        "Math.ceil",
        "Math.factorial",
        "Math.mod",
    }

    ssa = lower_to_verified_ssa(_typed(NATIVE_SOURCE))
    assert all(
        call.builtin == call.function
        for function in ssa.functions
        for block in function.blocks
        for call in block.instructions
        if isinstance(call, SSACall) and call.builtin is not None
    )

    llvm = LLVMBuilder().emit_llvm(_typed(NATIVE_SOURCE))
    assert "@llvm.sqrt.f64" in llvm
    assert "@llvm.fabs.f64" in llvm
    assert "declare double @sin(double)" in llvm
    assert "declare double @log(double)" in llvm
    assert "declare double @log10(double)" in llvm
    assert "@aether_checked_abs_i32" in llvm
    assert "@aether_checked_factorial_i32" in llvm


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_scalar_math_native_matches_ast_for_ordinary_and_ieee_values() -> None:
    stdout = StringIO()
    stderr = StringIO()
    exit_code = LLVMRunner().run(_typed(NATIVE_SOURCE), stdout=stdout, stderr=stderr)

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert _numeric_lines(stdout.getvalue()) == pytest.approx(
        _numeric_lines(run_aether(AST_SOURCE).output),
        rel=1e-14,
        abs=1e-14,
    )

    edge_body = """
println(ln(0.0));
println(log(-1.0));
println(exp(1000.0));
println(sin(1.0 / 0.0));
"""
    edge_native = f"int main() {{ {edge_body} return 0; }}"
    edge_stdout = StringIO()
    assert LLVMRunner().run(_typed(edge_native), stdout=edge_stdout, stderr=StringIO()) == 0
    ast_values = _numeric_lines(run_aether(edge_body).output)
    native_values = _numeric_lines(edge_stdout.getvalue())
    assert ast_values[0] == native_values[0] == float("-inf")
    assert math.isnan(ast_values[1]) and math.isnan(native_values[1])
    assert ast_values[2] == native_values[2] == float("inf")
    assert math.isnan(ast_values[3]) and math.isnan(native_values[3])

    # The legacy AST contract dynamically returns complex here despite the
    # static result type being double. Native cannot reproduce that without a
    # complex ABI, so its documented real-only fallback is IEEE NaN.
    assert run_aether("println(sqrt(-1.0));").output == "im\n"
    negative_sqrt = StringIO()
    assert LLVMRunner().run(
        _typed("int main() { println(sqrt(-1.0)); return 0; }"),
        stdout=negative_sqrt,
        stderr=StringIO(),
    ) == 0
    assert math.isnan(float(negative_sqrt.getvalue()))


def test_abs_int_min_panics_in_ast_ir_and_native_when_available() -> None:
    body = "int value = -2147483648; println(abs(value));"
    with pytest.raises(AetherRuntimeError, match="Integer overflow"):
        run_aether(body)

    typed = _typed(f"int main() {{ {body} return 0; }}")
    interpreter = IRInterpreter(IRBackend().lower_verified(typed))
    with pytest.raises(IRExecutionError, match="Integer overflow"):
        interpreter.call("main")

    if shutil.which("clang") is not None:
        stdout = StringIO()
        assert LLVMRunner().run(typed, stdout=stdout, stderr=StringIO()) == 1
        assert stdout.getvalue() == f"{INTEGER_OVERFLOW_MESSAGE}\n"


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("Math.floor(1.0 / 0.0)", "Math.floor(...) cannot convert NaN or infinity to int."),
        ("Math.ceil(1.0 / 0.0)", "Math.ceil(...) cannot convert NaN or infinity to int."),
        ("Math.mod(1, 0)", "Math.mod(...) is undefined for divisor zero."),
        ("Math.factorial(-1)", "Math.factorial(...) requires a non-negative integer."),
        ("Math.factorial(13)", INTEGER_OVERFLOW_MESSAGE),
    ],
)
def test_checked_scalar_math_panics_match_ast_ir_and_native(
    expression: str,
    message: str,
) -> None:
    ast_source = f"import Math; {expression};"
    with pytest.raises(AetherRuntimeError) as ast_error:
        run_aether(ast_source)
    assert ast_error.value.message == message

    typed = _typed(f"import Math; int main() {{ {expression}; return 0; }}")
    with pytest.raises(IRExecutionError) as ir_error:
        IRInterpreter(IRBackend().lower_verified(typed)).call("main")
    assert str(ir_error.value) == message

    if shutil.which("clang") is not None:
        stdout = StringIO()
        assert LLVMRunner().run(typed, stdout=stdout, stderr=StringIO()) == 1
        assert stdout.getvalue() == f"{message}\n"


def test_dce_removes_pure_scalar_math_but_preserves_checked_abs() -> None:
    source = """
int main() {
    sin(0.0);
    int value = -2147483648;
    abs(value);
    return 0;
}
"""
    optimized = DeadCodeEliminator().run(IRBackend().lower_verified(_typed(source))).module
    calls = [
        instruction
        for function in optimized.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCall)
    ]
    assert [call.builtin for call in calls] == ["abs"]


def test_math_pi_is_a_direct_double_constant_without_module_global() -> None:
    llvm = LLVMBuilder().emit_llvm(
        _typed("import Math as M; int main() { println(M.pi); return 0; }")
    )
    assert "3.141592653589793" in llvm
    assert "@Math.pi" not in llvm


def test_user_function_with_similar_name_is_not_marked_as_builtin() -> None:
    source = """
double sine(double value) { return value + 1.0; }
int main() { println(sine(2.0)); println(sin(0.0)); return 0; }
"""
    module = IRBackend().lower_verified(_typed(source))
    calls = [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCall)
    ]
    assert next(call for call in calls if call.function == "sine").builtin is None
    assert next(call for call in calls if call.function == "sin").builtin == "sin"


def test_scalar_math_and_constant_aliases_survive_multi_module_rewriting(tmp_path: Path) -> None:
    (tmp_path / "Calc.ae").write_text(
        """
package Calc;
import Math as M;
from Math import pi as circle;
public double value() { return M.pi + circle + sin(0.0); }
""",
        encoding="utf-8",
    )
    typed = prepare_typed_program(
        "import Calc; int main() { println(Calc.value()); return 0; }",
        TypeChecker(source_root=tmp_path),
    )
    interpreter = IRInterpreter(IRBackend().lower_verified(typed))
    assert interpreter.call("main") == 0
    assert float(interpreter.output.strip()) == pytest.approx(2.0 * math.pi)
    assert "@Math.pi" not in LLVMBuilder().emit_llvm(typed)
