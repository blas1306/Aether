from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from latex_lang import _run_oct_block, env_ast, ejecutar_linea, reset_environment


def _run(line: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ejecutar_linea(line)
    return buffer.getvalue()


def _run_block(*lines: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _run_oct_block(list(lines))
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _fresh_runtime():
    reset_environment()
    yield
    reset_environment()


def test_unclosed_parenthesis_fails_cleanly():
    output = _run("a = (2 + 3;")

    assert "Error defining variable" in output
    assert "never closed" in output
    assert "a" not in env_ast


def test_unclosed_matrix_literal_fails_cleanly():
    output = _run("A = [1, 2; 3, 4;")

    assert "Error defining variable" in output
    assert "Matrix literal '[' was never closed" in output
    assert "A" not in env_ast


def test_malformed_control_blocks_fail_cleanly():
    unclosed_if_output = _run_block("if 1 < 2", "x = 1;")
    assert "missing 'end'" in unclosed_if_output
    assert "x" not in env_ast

    invalid_for_output = _run_block("for i 1:5", "x = 1;", "end")
    assert "Invalid for syntax" in invalid_for_output
    assert "x" not in env_ast


def test_bad_dot_operator_expression_fails_cleanly():
    output = _run("a = 2 .^;")

    assert "Error defining variable" in output
    assert "right operand" in output
    assert "a" not in env_ast
