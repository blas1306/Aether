from __future__ import annotations

import pytest

from aether.errors import AetherSyntaxError, AetherTypeError
from aether.runner import run_aether
from aether.types import ListType, MatrixType, VectorType


def test_list_literal_declaration_and_zero_based_indexing() -> None:
    result = run_aether("List<int> xs = {1, 2, 3}; println(xs[0]);")

    assert result.env["xs"].type_name == ListType("int")
    assert result.output == "1\n"


def test_list_string_literal_and_formatting() -> None:
    result = run_aether('List<string> names = {"Ana", "Luis"}; println(names);')

    assert result.env["names"].type_name == ListType("string")
    assert result.output == '{"Ana", "Luis"}\n'


def test_list_literal_rejects_incompatible_elements() -> None:
    with pytest.raises(AetherTypeError, match="List literals must contain homogeneous compatible element types"):
        run_aether('List<int> xs = {1, "a"};')


def test_vector_and_list_literals_do_not_cross_assign() -> None:
    with pytest.raises(AetherTypeError, match="List<int>.*Vector<int>"):
        run_aether("Vector<int> v = {1, 2, 3};")

    with pytest.raises(AetherTypeError, match="Vector<int>.*List<int>"):
        run_aether("List<int> xs = [1, 2, 3];")


def test_row_vector_literals_use_commas_or_spaces() -> None:
    comma = run_aether("Vector<int> v = [1, 2, 3]; println(v); println(v[1]);")
    spaces = run_aether("Vector<int> v = [1 2 3]; println(v); println(v[1]);")

    assert comma.env["v"].type_name == VectorType("int", 3, "row")
    assert spaces.env["v"].type_name == VectorType("int", 3, "row")
    assert comma.output == "[1 2 3]\n1\n"
    assert spaces.output == "[1 2 3]\n1\n"


def test_column_vector_literal_uses_semicolons() -> None:
    result = run_aether("Vector<int> v = [1; 2; 3]; println(v); println(v[1]);")

    assert result.env["v"].type_name == VectorType("int", 3, "column")
    assert result.output == "[1; 2; 3]\n1\n"


def test_matrix_literal_and_one_based_indexing() -> None:
    result = run_aether("Matrix<int> A = [1 2; 3 4]; println(A[1, 1]);")

    assert result.env["A"].type_name == MatrixType("int", 2, 2)
    assert result.output == "1\n"


def test_list_and_vector_index_bases_are_distinct() -> None:
    result = run_aether(
        """
List<int> xs = {10, 20};
Vector<int> v = [10 20];
println(xs[0]);
println(v[1]);
"""
    )

    assert result.output == "10\n10\n"


def test_list_requires_commas() -> None:
    with pytest.raises(AetherSyntaxError, match="Expected ',' between list elements"):
        run_aether("x = {1 2 3};")


def test_ragged_matrix_literal_is_rejected() -> None:
    with pytest.raises(AetherTypeError, match="rectangular|ragged"):
        run_aether("Matrix<int> A = [1 2; 3];")
