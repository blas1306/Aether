from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from diagnostics import MathTeXParseError
from latex_lang import _build_parser_context, _run_oct_block, env_ast, ejecutar_linea, parse_mathtex_line, reset_environment


@pytest.fixture(autouse=True)
def _fresh_runtime():
    reset_environment()
    yield
    reset_environment()


def _run_line(line: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ejecutar_linea(line)
    return buffer.getvalue()


def _run_block(*lines: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _run_oct_block(list(lines))
    return buffer.getvalue()


def test_unclosed_parenthesis_reports_diagnostic_metadata():
    ctx = _build_parser_context()

    with pytest.raises(MathTeXParseError) as exc_info:
        parse_mathtex_line("a = ((2 + 3) * 4", ctx)

    err = exc_info.value
    assert err.diagnostic.kind == "unclosed-delimiter"
    assert err.diagnostic.line == 1
    assert err.diagnostic.column == 1
    assert "never closed" in str(err)
    assert "Hint:" in str(err)


def test_unclosed_matrix_literal_reports_diagnostic_metadata():
    ctx = _build_parser_context()

    with pytest.raises(MathTeXParseError) as exc_info:
        parse_mathtex_line("A = [1, 2; 3, 4", ctx)

    err = exc_info.value
    assert err.diagnostic.kind == "unclosed-delimiter"
    assert err.diagnostic.line == 1
    assert err.diagnostic.column == 1
    assert "Matrix literal" in str(err)


def test_incomplete_assignment_reports_specific_error():
    ctx = _build_parser_context()

    with pytest.raises(MathTeXParseError) as exc_info:
        parse_mathtex_line("a =", ctx)

    err = exc_info.value
    assert err.diagnostic.kind == "incomplete-assignment"
    assert err.diagnostic.column == 3
    assert "right side" in str(err)


def test_empty_index_in_assignment_reports_specific_error():
    ctx = _build_parser_context()

    with pytest.raises(MathTeXParseError) as exc_info:
        parse_mathtex_line("A(,1) = 3", ctx)

    err = exc_info.value
    assert err.diagnostic.kind == "empty-index"
    assert "empty index" in str(err).lower()


def test_bad_dot_operator_reports_specific_error():
    ctx = _build_parser_context()

    with pytest.raises(MathTeXParseError) as exc_info:
        parse_mathtex_line("a = 2 .^", ctx)

    err = exc_info.value
    assert err.diagnostic.kind == "malformed-dot-operator"
    assert err.diagnostic.column == 3
    assert "right operand" in str(err)


def test_invalid_transpose_sequence_reports_specific_error():
    ctx = _build_parser_context()

    with pytest.raises(MathTeXParseError) as exc_info:
        parse_mathtex_line("A.''", ctx)

    err = exc_info.value
    assert err.diagnostic.kind == "invalid-transpose"
    assert "transpose" in str(err).lower()


def test_assignment_runtime_surfaces_parser_diagnostic_and_preserves_state():
    output = _run_line("a = ;")

    assert "Error defining variable" in output
    assert "missing the expression on the right side" in output
    assert "a" not in env_ast


def test_invalid_for_header_reports_diagnostic_and_preserves_state():
    output = _run_block("for i = 1::5", "x = 1;", "end")

    assert "Invalid for syntax" in output
    assert "line 1" in output
    assert "x" not in env_ast
    assert "i" not in env_ast


def test_else_without_if_reports_invalid_block_nesting():
    output = _run_block("else", "x = 1;", "end")

    assert "must appear inside an if block" in output
    assert "line 1" in output
    assert "x" not in env_ast


def test_missing_end_reports_opening_block_line_and_preserves_state():
    output = _run_block(
        "for i = 1:2",
        "if i > 1",
        "x = i;",
        "end",
    )

    assert "missing 'end'" in output
    assert "line 1" in output
    assert "x" not in env_ast
    assert "i" not in env_ast
