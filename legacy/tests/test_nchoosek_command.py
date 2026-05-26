from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest
import sympy as sp

from autocomplete_engine import filter_command_suggestions
from command_catalog import COMMAND_CATALOG
from latex_lang import _mt_nchoosek, env_ast, ejecutar_linea, reset_environment


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


def test_nchoosek_basic_cases_return_exact_integers():
    assert _mt_nchoosek(5, 2) == sp.Integer(10)
    assert _mt_nchoosek(6, 0) == sp.Integer(1)
    assert _mt_nchoosek(6, 6) == sp.Integer(1)
    assert _mt_nchoosek(sp.Integer(10), sp.Integer(3)) == sp.Integer(120)

    result = _mt_nchoosek(10, 3)
    assert isinstance(result, sp.Integer)


def test_nchoosek_works_inside_assignments_and_preserves_exact_type():
    _run(r"a = \nchoosek(5,2);")

    assert env_ast["a"] == sp.Integer(10)
    assert isinstance(env_ast["a"], sp.Integer)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (r"\nchoosek(5,7)", "nchoosek only accepts nonnegative integers n and k with k <= n."),
        (r"\nchoosek(-1,0)", "nchoosek only accepts nonnegative integers n and k with k <= n."),
        (r"\nchoosek(5,-1)", "nchoosek only accepts nonnegative integers n and k with k <= n."),
        (r"\nchoosek(5.5,2)", "nchoosek only accepts nonnegative integers n and k with k <= n."),
        (r"\nchoosek(5,2.0)", "nchoosek only accepts nonnegative integers n and k with k <= n."),
        (r"\nchoosek(i,1)", "nchoosek only accepts nonnegative integers n and k with k <= n."),
        (r"\nchoosek(x,2)", "nchoosek only accepts nonnegative integers n and k with k <= n."),
    ],
)
def test_nchoosek_reports_clear_errors_for_invalid_domain_and_types(line: str, message: str):
    output = _run(line)

    assert "Error" in output
    assert message in output


def test_nchoosek_helper_rejects_invalid_values_directly():
    with pytest.raises(ValueError, match="nchoosek only accepts nonnegative integers n and k with k <= n\\."):
        _mt_nchoosek(5.5, 2)

    with pytest.raises(ValueError, match="nchoosek only accepts nonnegative integers n and k with k <= n\\."):
        _mt_nchoosek(sp.I, 1)

    with pytest.raises(ValueError, match="nchoosek only accepts nonnegative integers n and k with k <= n\\."):
        _mt_nchoosek(sp.Symbol("x"), 2)


def test_catalog_and_autocomplete_include_nchoosek():
    descriptions = {entry.name: entry.description for entry in COMMAND_CATALOG}

    assert descriptions[r"\nchoosek(n,k)"] == "Return the binomial coefficient C(n,k) for nonnegative integers with 0 <= k <= n."

    names = {item.name for item in filter_command_suggestions(r"\nch")}
    assert r"\nchoosek(n,k)" in names
