from __future__ import annotations

import pytest

from aether.errors import AetherSyntaxError, AetherTypeError
from aether.runner import run_aether


def test_normal_string_still_prints_unchanged():
    result = run_aether('println("hola");')

    assert result.output == "hola\n"


def test_interpolates_simple_variable():
    result = run_aether('n = 4; println("n = $n$");')

    assert result.output == "n = 4\n"


def test_interpolates_expression():
    result = run_aether('x = 2; println("x^2 = $x^2$");')

    assert result.output == "x^2 = 4\n"


def test_interpolates_function_call():
    result = run_aether(
        """
int fib(int k) {
    if (k <= 1) {
        return k;
    }
    return fib(k - 1) + fib(k - 2);
}
n = 4;
println("El $n$-esimo numero de fibonacci es $fib(n)$");
"""
    )

    assert result.output == "El 4-esimo numero de fibonacci es 3\n"


def test_interpolates_multiple_expressions():
    result = run_aether(
        """
int fib(int k) {
    if (k <= 1) {
        return k;
    }
    return fib(k - 1) + fib(k - 2);
}
n = 4;
println("fib($n$) = $fib(n)$");
"""
    )

    assert result.output == "fib(4) = 3\n"


def test_escaped_dollar_is_literal():
    result = run_aether('println("Precio: \\$10");')

    assert result.output == "Precio: $10\n"


def test_unclosed_interpolation_reports_clear_parse_error():
    with pytest.raises(AetherSyntaxError, match="Interpolacion de string sin cerrar"):
        run_aether('x = 1; println("x = $x");')


def test_empty_interpolation_reports_clear_parse_error():
    with pytest.raises(AetherSyntaxError, match="Interpolacion de string vacia"):
        run_aether('println("bad = $$");')


def test_whitespace_only_interpolation_reports_clear_parse_error():
    with pytest.raises(AetherSyntaxError, match="Interpolacion de string vacia"):
        run_aether('println("bad = $   $");')


def test_invalid_interpolation_expression_reports_clear_parse_error():
    with pytest.raises(AetherSyntaxError, match="Expresion de interpolacion invalida"):
        run_aether('println("bad = $1 +$");')


def test_unsupported_escape_sequence_reports_clear_parse_error():
    with pytest.raises(AetherSyntaxError, match="Unsupported escape sequence"):
        run_aether('println("bad = \\q");')


def test_interpolation_expression_is_typechecked():
    with pytest.raises(AetherTypeError, match="Undefined variable 'missing'"):
        run_aether('println("missing = $missing$");')


def test_strings_inside_collection_literals_still_parse():
    result = run_aether('println(["a", "b"]); println(["a" "b"]);')

    assert result.output == '["a" "b"]\n["a" "b"]\n'


def test_interpolates_matrix_using_current_aether_format():
    result = run_aether('A = [1 2; 3 4]; println("A = $A$");')

    assert result.output == "A = [1 2; 3 4]\n"
