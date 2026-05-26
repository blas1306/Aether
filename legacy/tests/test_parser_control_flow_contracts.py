import sympy as sp
import pytest

from latex_lang import env_ast, ejecutar_linea, reset_environment


def _run_lines(*lines: str) -> None:
    for line in lines:
        ejecutar_linea(line)


@pytest.fixture(autouse=True)
def _fresh_environment():
    reset_environment()
    yield
    reset_environment()


def test_parser_operator_precedence_power_mul_add():
    _run_lines("a = 2 + 3 * 4 ^ 2;")

    assert env_ast["a"] == 50


def test_parser_unary_minus_vs_power():
    _run_lines("a = -2^2;")

    assert env_ast["a"] == -4


def test_parser_parenthesized_expression_overrides_precedence():
    _run_lines(
        "a = (2 + 3) * 4;",
        "b = 2 + 3 * 4;",
    )

    assert env_ast["a"] == 20
    assert env_ast["b"] == 14
    assert env_ast["a"] != env_ast["b"]


def test_parser_transpose_postfix_combined_expression():
    _run_lines(
        "A = [1,2;3,4];",
        "B = A.' * A;",
    )

    assert env_ast["B"] == sp.Matrix([[10, 14], [14, 20]])


def test_if_else_executes_correct_branch():
    _run_lines(
        "x = 0;",
        "if 1 < 2",
        "x = 10;",
        "else",
        "x = 20;",
        "end",
    )

    assert env_ast["x"] == 10


def test_if_elseif_else_selects_middle_branch():
    _run_lines(
        "x = 0;",
        "if 3 < 2",
        "x = 10;",
        "elseif 2 < 3",
        "x = 15;",
        "else",
        "x = 20;",
        "end",
    )

    assert env_ast["x"] == 15


def test_for_loop_accumulates_correctly():
    _run_lines(
        "s = 0;",
        "for i = 1:5",
        "s = s + i;",
        "end",
    )

    assert float(sp.N(env_ast["s"])) == pytest.approx(15.0)


def test_nested_control_blocks_work_correctly():
    _run_lines(
        "s = 0;",
        "for i = 1:4",
        "if i > 2",
        "s = s + i;",
        "end",
        "end",
    )

    assert float(sp.N(env_ast["s"])) == pytest.approx(7.0)
