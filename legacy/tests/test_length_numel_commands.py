from __future__ import annotations

import io
from contextlib import redirect_stdout

import numpy as np
import pytest

from autocomplete_engine import filter_command_suggestions
from command_catalog import COMMAND_CATALOG
from latex_lang import _mt_length, _mt_numel, env_ast, ejecutar_linea, reset_environment


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


def test_length_and_numel_on_scalar():
    _run("a = 5;")

    assert _run(r"\length(a)").strip() == "1"
    assert _run(r"\numel(a)").strip() == "1"


def test_length_and_numel_on_row_vector():
    _run("v = [1, 2, 3];")

    assert _run(r"\length(v)").strip() == "3"
    assert _run(r"\numel(v)").strip() == "3"


def test_length_and_numel_on_column_vector():
    _run("v = [1; 2; 3];")

    assert _run(r"\length(v)").strip() == "3"
    assert _run(r"\numel(v)").strip() == "3"


def test_numel_accepts_matrix_and_length_rejects_it_cleanly():
    _run("A = [1,2,3;4,5,6];")

    assert _run(r"\numel(A)").strip() == "6"

    output = _run(r"\length(A)")
    assert "Error" in output
    assert "length only accepts scalars or vectors." in output


def test_length_and_numel_work_in_assignments():
    _run(r"n = \length([1;2;3]);")
    _run(r"m = \numel([1,2;3,4]);")

    assert int(env_ast["n"]) == 3
    assert int(env_ast["m"]) == 4


def test_numpy_helpers_follow_vector_and_total_element_rules():
    row = np.array([[1, 2, 3]], dtype=object)
    col = np.array([[1], [2], [3]], dtype=object)
    mat = np.array([[1, 2, 3], [4, 5, 6]], dtype=object)
    cube = np.arange(8).reshape(2, 2, 2)

    assert int(_mt_length(np.array(5, dtype=object))) == 1
    assert int(_mt_numel(np.array(5, dtype=object))) == 1
    assert int(_mt_length(row)) == 3
    assert int(_mt_numel(row)) == 3
    assert int(_mt_length(col)) == 3
    assert int(_mt_numel(col)) == 3
    assert int(_mt_numel(mat)) == 6
    assert int(_mt_numel(cube)) == 8

    with pytest.raises(ValueError, match="length only accepts scalars or vectors\\."):
        _mt_length(mat)

    with pytest.raises(ValueError, match="length only accepts scalars or vectors\\."):
        _mt_length(cube)


def test_catalog_and_autocomplete_include_length_and_numel():
    descriptions = {entry.name: entry.description for entry in COMMAND_CATALOG}

    assert descriptions[r"\length()"] == "Return the length of a vector. Scalars return 1; matrices are not accepted."
    assert descriptions[r"\numel()"] == "Return the total number of elements."

    length_names = {item.name for item in filter_command_suggestions(r"\len")}
    numel_names = {item.name for item in filter_command_suggestions(r"\num")}

    assert r"\length()" in length_names
    assert r"\numel()" in numel_names
