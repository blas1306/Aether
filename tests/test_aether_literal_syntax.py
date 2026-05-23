from __future__ import annotations

import sympy as sp

from latex_lang import ejecutar_linea, env_ast, reset_environment
from numeric_format import matrix_to_latex


def _run(line: str) -> None:
    ejecutar_linea(line)


def setup_function() -> None:
    reset_environment()


def teardown_function() -> None:
    reset_environment()


def test_tuple_literals_are_python_tuples_and_can_be_heterogeneous():
    _run("t = (1, 2, 3);")
    _run('mixed = (1, "hola", true);')

    assert env_ast["t"] == (1, 2, 3)
    assert env_ast["mixed"] == (1, "hola", True)


def test_singleton_tuple_is_distinct_from_parenthesized_group():
    _run("t = (1,);")
    _run("x = (1 + 2);")

    assert env_ast["t"] == (1,)
    assert env_ast["x"] == 3


def test_comma_brackets_keep_vector_runtime_compatibility():
    _run("v = [1, 2, 3];")

    assert isinstance(env_ast["v"], sp.MatrixBase)
    assert env_ast["v"].shape == (1, 3)
    assert env_ast["v"].tolist() == [[1, 2, 3]]


def test_julia_style_matrix_row_column_and_2d_literals():
    _run("A = [1 2; 3 4];")
    _run("r = [1 2 3];")
    _run("c = [1; 2; 3];")

    assert env_ast["A"] == sp.Matrix([[1, 2], [3, 4]])
    assert env_ast["r"] == sp.Matrix([[1, 2, 3]])
    assert env_ast["c"] == sp.Matrix([[1], [2], [3]])


def test_nested_matrix_compatibility_and_string_lists():
    _run("legacy = [[1, 2], [3, 4]];")
    _run('labels = ["a", "b"];')

    assert env_ast["legacy"] == sp.Matrix([[1, 2], [3, 4]])
    assert env_ast["labels"] == ["a", "b"]


def test_tuple_display_is_not_forced_to_matrix_latex():
    rendered = matrix_to_latex((1, 2, 3))

    assert r"\begin{matrix}" not in rendered
    assert rendered == "(1, 2, 3)"
