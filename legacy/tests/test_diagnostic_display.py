from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from diagnostics import MathTeXDiagnostic, diagnostic_line_offset, render_diagnostic, render_error_for_display
from latex_lang import ejecutar_linea, reset_environment


@pytest.fixture(autouse=True)
def _fresh_runtime():
    reset_environment()
    yield
    reset_environment()


def _run(line: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ejecutar_linea(line)
    return buffer.getvalue()


def test_render_diagnostic_includes_category_kind_location_hint_and_snippet():
    diag = MathTeXDiagnostic(
        category="parser",
        kind="unclosed-delimiter",
        message="Parenthesis '(' was never closed.",
        line=1,
        column=5,
        hint="Add ')' to close the expression.",
        snippet="a = (1 + 2",
    )

    text = render_diagnostic(diag)

    assert "Parse error [unclosed-delimiter]" in text
    assert "line 1, column 5" in text
    assert "Hint: Add ')'" in text
    assert "Snippet: a = (1 + 2" in text


def test_render_error_for_display_falls_back_for_plain_exceptions():
    assert render_error_for_display(ValueError("plain failure")) == "plain failure"


def test_assignment_parse_error_uses_structured_display_text():
    output = _run("a = ;")

    assert "Error defining variable: Parse error [incomplete-assignment]:" in output
    assert "Hint:" in output
    assert "Snippet:" in output
    assert output.count("Parse error [incomplete-assignment]") == 1


def test_assignment_runtime_error_uses_runtime_category():
    output = _run("a = foo + 1;")

    assert "Error defining variable: Runtime error [undefined-variable]:" in output
    assert "Hint:" in output
    assert "Snippet:" in output


def test_multiline_runtime_error_uses_absolute_line_offset():
    buffer = io.StringIO()
    block = "a = [\n  1,\n  foo\n]"

    with redirect_stdout(buffer):
        with diagnostic_line_offset(19):
            ejecutar_linea(block)

    output = buffer.getvalue()

    assert "line 22" in output
    assert "undefined-variable" in output


def test_multiline_parse_error_uses_absolute_line_offset():
    buffer = io.StringIO()
    block = "a = [\n  1,\n"

    with redirect_stdout(buffer):
        with diagnostic_line_offset(19):
            ejecutar_linea(block)

    output = buffer.getvalue()

    assert "line 20" in output
    assert "Parse error" in output
