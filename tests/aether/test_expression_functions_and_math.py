from __future__ import annotations

import pytest

from aether import ast
from aether.backend.llvm.build import LLVMBuilder
from aether.errors import AetherRuntimeError, AetherSyntaxError, AetherTypeError
from aether.interpreter import Interpreter
from aether.ir.interpreter import IRInterpreter
from aether.lexer import lex
from aether.parser import Parser
from aether.pipeline import IRBackend, SSAPipeline, prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker


def test_global_math_builtins() -> None:
    result = run_aether(
        """
println(sqrt(9.0));
println(sin(0.0));
println(cos(0.0));
println(exp(0.0));
println(ln(exp(1.0)));
println(abs(-5));
"""
    )

    values = [float(line) for line in result.output.strip().splitlines()]
    assert values[0] == pytest.approx(3.0)
    assert values[1] == pytest.approx(0.0)
    assert values[2] == pytest.approx(1.0)
    assert values[3] == pytest.approx(1.0)
    assert values[4] == pytest.approx(1.0)
    assert values[5] == pytest.approx(5.0)


def test_log_is_base_10_and_ln_is_natural_log() -> None:
    result = run_aether("println(log(100.0)); println(ln(exp(1.0)));")

    values = [float(line) for line in result.output.strip().splitlines()]
    assert values == pytest.approx([2.0, 1.0])


def test_math_selective_import_exposes_pi_constant() -> None:
    result = run_aether("import Math\nfrom Math import pi\nprintln(pi); println(Math.pi);")

    values = [float(line) for line in result.output.strip().splitlines()]
    assert values == pytest.approx([3.141592653589793, 3.141592653589793])


def test_math_factorial_function() -> None:
    result = run_aether(
        """
import Math
from Math import factorial
println(factorial(5));
println(Math.factorial(6));
"""
    )

    assert result.output == "120\n720\n"


def test_math_floor_and_ceil_names() -> None:
    result = run_aether(
        """
import Math
from Math import floor
from Math import ceil
println(floor(3.9));
println(ceil(3.1));
println(Math.floor(-1.2));
println(Math.ceil(-1.2));
"""
    )

    assert result.output == "3\n4\n-2\n-1\n"


def test_factorial_rejects_non_int_and_negative_values() -> None:
    with pytest.raises(AetherTypeError, match="expects an int argument"):
        run_aether("from Math import factorial\nprintln(factorial(5.0));")

    with pytest.raises(AetherRuntimeError, match="requires a non-negative integer"):
        run_aether("from Math import factorial\nprintln(factorial(-1));")


def test_abbreviated_function_desugars_to_normal_function_declaration() -> None:
    program = Parser(lex("double f(double x) = x^2 + 1.0;")).parse()

    declaration = program.statements[0]
    assert isinstance(declaration, ast.FunctionDeclaration)
    assert declaration.return_type == "double"
    assert declaration.parameters == [ast.Parameter("double", "x")]
    assert len(declaration.body) == 1
    assert isinstance(declaration.body[0], ast.ReturnStatement)
    assert isinstance(declaration.body[0].expression, ast.BinaryExpression)


def test_abbreviated_function_infers_and_materializes_return_type() -> None:
    program = Parser(lex("f(double x) = x * exp(x) - 1.0;")).parse()
    declaration = program.statements[0]

    assert isinstance(declaration, ast.FunctionDeclaration)
    assert declaration.return_type is None

    TypeChecker().check(program)

    assert declaration.return_type == "double"


def test_abbreviated_function_uses_unchanged_ir_and_ssa_function_pipeline() -> None:
    typed = prepare_typed_program(
        "f(double x) = x * x + 1.0; int main() { return int(f(3.0)); }",
        TypeChecker(),
    )

    declaration = typed.program.statements[0]
    assert isinstance(declaration, ast.FunctionDeclaration)
    assert declaration.return_type == "double"

    ir_module = IRBackend().lower_verified(typed)
    assert IRInterpreter(ir_module).call("main") == 10
    assert len(SSAPipeline().run(typed).ssa_module.functions) == 2
    assert "define double @f(double %x)" in LLVMBuilder().emit_llvm(typed)


def test_abbreviated_function_single_parameter() -> None:
    result = run_aether("f(int x) = x^2 + 1; println(f(3));")

    assert result.output == "10\n"


def test_abbreviated_function_multiple_parameters() -> None:
    result = run_aether("int g(int x, int y) = x^2 + y^2; println(g(3, 4));")

    assert result.output == "25\n"


def test_inferred_abbreviated_return_resolves_across_forward_function_call() -> None:
    result = run_aether(
        "g(int x) = f(x) + 1; f(int x) = x * 2; println(g(3));"
    )

    assert result.output == "7\n"


def test_forward_inferred_return_is_rechecked_against_explicit_caller_return() -> None:
    with pytest.raises(AetherTypeError, match="declares return type int but returned string"):
        run_aether('int g() { return f(1); } f(int x) = "wrong"; println(g());')


def test_abbreviated_function_can_call_math_builtins() -> None:
    result = run_aether("f(double x) = sin(x)^2 + cos(x)^2; println(f(0.0));")

    assert float(result.output.strip()) == pytest.approx(1.0)


def test_abbreviated_function_can_use_global_variable() -> None:
    result = run_aether("int a = 2; f(int x) = a*x + 1; println(f(3));")

    assert result.output == "7\n"


def test_abbreviated_function_wrong_arity_is_error() -> None:
    with pytest.raises(AetherTypeError, match="expects 2 arguments but got 1"):
        run_aether("g(int x, int y) = x + y; println(g(1));")


def test_abbreviated_function_runtime_wrong_arity_is_error() -> None:
    program = Parser(lex("g(int x, int y) = x + y; println(g(1));")).parse()

    with pytest.raises(AetherRuntimeError, match="Function 'g' expects 2 arguments but got 1."):
        Interpreter().interpret(program)


def test_abbreviated_function_coexists_with_block_function() -> None:
    result = run_aether(
        """
f(int x) = x + 1;
int g(int x) {
    return x * 2;
}
println(f(3));
println(g(3));
"""
    )

    assert result.output == "4\n6\n"


def test_abbreviated_function_duplicate_name_is_error() -> None:
    with pytest.raises(AetherTypeError, match="already defined"):
        run_aether("f(int x) = x + 1; int f(int x) { return x; }")


def test_abbreviated_function_duplicate_abbreviated_name_is_error() -> None:
    with pytest.raises(AetherTypeError, match="Function 'f' is already defined."):
        run_aether("f(int x) = x + 1; f(int x) = x - 1;")


def test_abbreviated_function_duplicate_after_block_function_is_error() -> None:
    with pytest.raises(AetherTypeError, match="Function 'f' is already defined."):
        run_aether("int f(int x) { return x; } f(int x) = x + 1;")


def test_abbreviated_function_missing_body_expression_is_clear() -> None:
    with pytest.raises(AetherSyntaxError, match="Expected expression after '=' in abbreviated function 'f'."):
        run_aether("f(double x) = ;")


def test_abbreviated_function_bad_parameter_separator_is_clear() -> None:
    with pytest.raises(
        AetherSyntaxError,
        match="Expected ',' or '\\)' in parameter list for abbreviated function 'f'.",
    ):
        run_aether("f(double x double y) = x + y;")


def test_abbreviated_function_incomplete_expression_is_clear() -> None:
    with pytest.raises(AetherSyntaxError, match="Expected expression after '\\+' in abbreviated function 'f'."):
        run_aether("f(double x) = x + ;")


def test_abbreviated_function_missing_final_semicolon_is_clear() -> None:
    with pytest.raises(AetherSyntaxError, match="Expected ';' after abbreviated function declaration."):
        run_aether("f(double x) = x^2 + 1")


def test_abbreviated_function_duplicate_parameter_is_clear() -> None:
    with pytest.raises(AetherSyntaxError, match="Duplicate parameter 'x' in abbreviated function 'f'."):
        run_aether("f(double x, double x) = x + 1.0;")


def test_abbreviated_function_requires_explicit_parameter_types() -> None:
    with pytest.raises(AetherSyntaxError, match="require explicit types and names"):
        run_aether("f(x) = x + 1;")


def test_abbreviated_function_keyword_parameter_is_clear() -> None:
    with pytest.raises(AetherSyntaxError, match="require explicit types and names"):
        run_aether("f(double if) = 1.0;")
