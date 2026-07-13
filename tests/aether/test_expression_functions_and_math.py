from __future__ import annotations

import pytest

from aether.errors import AetherRuntimeError, AetherSyntaxError, AetherTypeError
from aether.interpreter import Interpreter
from aether.lexer import lex
from aether.parser import Parser
from aether.runner import run_aether


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


def test_expression_function_single_parameter() -> None:
    result = run_aether("f(x) = x^2 + 1; println(f(3));")

    assert result.output == "10\n"


def test_expression_function_multiple_parameters() -> None:
    result = run_aether("g(x, y) = x^2 + y^2; println(g(3, 4));")

    assert result.output == "25\n"


def test_expression_function_can_call_math_builtins() -> None:
    result = run_aether("f(x) = sin(x)^2 + cos(x)^2; println(f(0.0));")

    assert float(result.output.strip()) == pytest.approx(1.0)


def test_expression_function_can_use_global_variable() -> None:
    result = run_aether("a = 2; f(x) = a*x + 1; println(f(3));")

    assert result.output == "7\n"


def test_expression_function_wrong_arity_is_error() -> None:
    with pytest.raises(AetherTypeError, match="expects 2 arguments but got 1"):
        run_aether("g(x, y) = x + y; println(g(1));")


def test_expression_function_runtime_wrong_arity_is_error() -> None:
    program = Parser(lex("g(x, y) = x + y; println(g(1));")).parse()

    with pytest.raises(AetherRuntimeError, match="Function 'g' expects 2 arguments but got 1."):
        Interpreter().interpret(program)


def test_expression_function_coexists_with_block_function() -> None:
    result = run_aether(
        """
f(x) = x + 1;
int g(int x) {
    return x * 2;
}
println(f(3));
println(g(3));
"""
    )

    assert result.output == "4\n6\n"


def test_expression_function_duplicate_name_is_error() -> None:
    with pytest.raises(AetherTypeError, match="already defined"):
        run_aether("f(x) = x + 1; int f(int x) { return x; }")


def test_expression_function_duplicate_expression_name_is_error() -> None:
    with pytest.raises(AetherTypeError, match="Function 'f' is already defined."):
        run_aether("f(x) = x + 1; f(x) = x - 1;")


def test_expression_function_duplicate_after_block_function_is_error() -> None:
    with pytest.raises(AetherTypeError, match="Function 'f' is already defined."):
        run_aether("int f(int x) { return x; } f(x) = x + 1;")


def test_expression_function_missing_body_expression_is_clear() -> None:
    with pytest.raises(AetherSyntaxError, match="Expected expression after '=' in expression function 'f'."):
        run_aether("f(x) = ;")


def test_expression_function_bad_parameter_separator_is_clear() -> None:
    with pytest.raises(
        AetherSyntaxError,
        match="Expected ',' or '\\)' in parameter list for expression function 'f'.",
    ):
        run_aether("f(x y) = x + y;")


def test_expression_function_incomplete_expression_is_clear() -> None:
    with pytest.raises(AetherSyntaxError, match="Expected expression after '\\+' in expression function 'f'."):
        run_aether("f(x) = x + ;")


def test_expression_function_missing_final_semicolon_is_clear() -> None:
    with pytest.raises(AetherSyntaxError, match="Expected ';' after expression function declaration."):
        run_aether("f(x) = x^2 + 1")


def test_expression_function_duplicate_parameter_is_clear() -> None:
    with pytest.raises(AetherSyntaxError, match="Duplicate parameter 'x' in expression function 'f'."):
        run_aether("f(x, x) = x + 1;")


def test_expression_function_keyword_parameter_is_clear() -> None:
    with pytest.raises(AetherSyntaxError, match="Invalid parameter name 'if' in expression function 'f'."):
        run_aether("f(if) = if + 1;")
