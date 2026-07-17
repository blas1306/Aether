from __future__ import annotations

import pytest

from aether.ast import BinaryExpression, IfStatement, WhileStatement
from aether.errors import AetherSyntaxError, AetherTypeError
from aether.lexer import lex
from aether.parser import Parser
from aether.runner import run_aether


def _parse_expression(source: str) -> BinaryExpression:
    program = Parser(lex(source)).parse()
    statement = program.statements[0]
    assert isinstance(statement, IfStatement)
    assert isinstance(statement.condition, BinaryExpression)
    return statement.condition


def test_parser_logical_precedence_matches_c_style_rules() -> None:
    condition = _parse_expression("if (a > 0 && b < 10 || c == 5) { }")

    assert condition.operator == "||"
    assert isinstance(condition.left, BinaryExpression)
    assert condition.left.operator == "&&"
    assert isinstance(condition.right, BinaryExpression)
    assert condition.right.operator == "=="


def test_parser_parentheses_group_logical_expressions() -> None:
    condition = _parse_expression("if ((a > 0 && b < 10) || c == 5) { }")

    assert condition.operator == "||"
    assert isinstance(condition.left, BinaryExpression)
    assert condition.left.operator == "&&"


def test_parser_while_accepts_complex_logical_condition() -> None:
    program = Parser(lex("while (x > 0 && y != 0) { x = x - 1; }")).parse()

    statement = program.statements[0]
    assert isinstance(statement, WhileStatement)
    assert isinstance(statement.condition, BinaryExpression)
    assert statement.condition.operator == "&&"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = true && true;", True),
        ("x = true && false;", False),
        ("x = true || false;", True),
        ("x = false || false;", False),
    ],
)
def test_logical_operators_evaluate_booleans(source: str, expected: bool) -> None:
    result = run_aether(source)

    assert result.env["x"].type_name == "boolean"
    assert result.env["x"].value is expected


def test_logical_and_short_circuits_false_lhs() -> None:
    result = run_aether(
        """
count = 0;
boolean side_effect() {
    count = count + 1;
    return true;
}
x = false && side_effect();
println(count);
"""
    )

    assert result.env["x"].value is False
    assert result.env["count"].value == 0
    assert result.output == "0\n"


def test_logical_or_short_circuits_true_lhs() -> None:
    result = run_aether(
        """
count = 0;
boolean side_effect() {
    count = count + 1;
    return false;
}
x = true || side_effect();
println(count);
"""
    )

    assert result.env["x"].value is True
    assert result.env["count"].value == 0
    assert result.output == "0\n"


def test_if_and_while_use_complex_logical_conditions() -> None:
    result = run_aether(
        """
a = 1;
b = 9;
c = 0;
if (a > 0 && b < 10) {
    println("if");
}
x = 2;
y = 1;
while (x > 0 && y != 0) {
    println(x);
    x = x - 1;
}
"""
    )

    assert result.output == "if\n2\n1\n"
    assert result.env["x"].value == 0


def test_parenthesized_or_condition_runs_expected_branch() -> None:
    result = run_aether(
        """
a = -1;
b = 20;
c = 5;
if ((a > 0 && b < 10) || c == 5) {
    println("ok");
}
"""
    )

    assert result.output == "ok\n"


def test_logical_operators_require_boolean_operands() -> None:
    with pytest.raises(AetherTypeError, match="Operator '&&' requires boolean operands"):
        run_aether("x = 1 && true;")


def test_single_ampersand_is_syntax_error() -> None:
    with pytest.raises(AetherSyntaxError, match="Did you mean '&&'"):
        lex("x = true & false;")
