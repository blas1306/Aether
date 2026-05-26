from __future__ import annotations

import pytest

from aether import analyze_source, run_aether
from aether.ast import Assignment, BinaryExpression
from aether.errors import AetherRuntimeError
from aether.lexer import lex
from aether.parser import Parser


def test_percent_parses_as_binary_operator() -> None:
    program = Parser(lex("x = a % b;")).parse()

    statement = program.statements[0]
    assert isinstance(statement, Assignment)
    expression = statement.expression
    assert isinstance(expression, BinaryExpression)
    assert expression.operator == "%"


def test_percent_uses_truncating_remainder_for_ints() -> None:
    result = run_aether(
        """
a = 5 % 3;
b = -5 % 3;
c = 5 % -3;
d = -5 % -3;
"""
    )

    assert result.env["a"].value == 2
    assert result.env["b"].value == -2
    assert result.env["c"].value == 2
    assert result.env["d"].value == -2
    assert result.env["a"].type_name == "int"


def test_math_mod_uses_floor_modulo_for_ints() -> None:
    result = run_aether(
        """
a = Math.mod(5, 3);
b = Math.mod(-5, 3);
c = Math.mod(5, -3);
d = Math.mod(-5, -3);
"""
    )

    assert result.env["a"].value == 2
    assert result.env["b"].value == 1
    assert result.env["c"].value == -1
    assert result.env["d"].value == -2
    assert result.env["a"].type_name == "int"


def test_percent_and_math_mod_support_decimals() -> None:
    result = run_aether(
        """
truncated = -5.5 % 2.0;
floored = Math.mod(-5.5, 2.0);
"""
    )

    assert result.env["truncated"].value == pytest.approx(-1.5)
    assert result.env["floored"].value == pytest.approx(0.5)
    assert result.env["truncated"].type_name == "double"
    assert result.env["floored"].type_name == "double"


def test_percent_rejects_divisor_zero() -> None:
    with pytest.raises(AetherRuntimeError, match="divisor zero"):
        run_aether("x = 5 % 0;")


def test_math_mod_rejects_divisor_zero() -> None:
    with pytest.raises(AetherRuntimeError, match="divisor zero"):
        run_aether("x = Math.mod(5, 0);")


def test_modulo_rejects_non_numeric_operands_in_lsp() -> None:
    percent_diagnostics = analyze_source('x = "a" % 2;')
    builtin_diagnostics = analyze_source("x = Math.mod([1 2], 2);")

    assert len(percent_diagnostics) == 1
    assert "requires real numeric operands" in percent_diagnostics[0].message
    assert len(builtin_diagnostics) == 1
    assert "expects real numeric arguments" in builtin_diagnostics[0].message


def test_unqualified_mod_is_not_a_builtin() -> None:
    diagnostics = analyze_source("x = mod(5, 3);")

    assert len(diagnostics) == 1
    assert "Undefined function 'mod'" in diagnostics[0].message
