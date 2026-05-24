from __future__ import annotations

import pytest

from aether.errors import AetherTypeError
from aether.runner import run_aether
from aether.types import MatrixType, TransposeVectorType, VectorType


def values(vector):
    return [element.value for element in vector.value]


def matrix_values(matrix):
    return [[element.value for element in row.value] for row in matrix.value]


def test_vectors_are_1d_values_and_simple_indexing_returns_scalar() -> None:
    result = run_aether("v = [1, 2, 3]; a = v[0]; println(a);")

    assert result.env["v"].type_name == VectorType("int", 3)
    assert result.env["a"].type_name == "int"
    assert result.output == "1\n"


def test_transpose_vector_is_a_view_orientation_and_double_transpose_returns_vector() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
v = [1, 2, 3];
t = transpose(v);
w = transpose(t);
a = t[0];
println(a);
"""
    )

    assert result.env["t"].type_name == TransposeVectorType("int", 3)
    assert result.env["w"].type_name == VectorType("int", 3)
    assert result.env["a"].type_name == "int"
    assert result.output == "1\n"


def test_star_dispatches_vector_dot_outer_and_matrix_vector_products() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
v = [1, 2, 3];
w = [4, 5, 6];
A = [1 2; 3 4];
x = transpose(v) * w;
O = v * transpose(w);
y = A * [5, 6];
"""
    )

    assert result.env["x"].type_name == "int"
    assert result.env["x"].value == 32
    assert result.env["O"].type_name == MatrixType("int", 3, 3)
    assert matrix_values(result.env["O"]) == [[4, 5, 6], [8, 10, 12], [12, 15, 18]]
    assert result.env["y"].type_name == VectorType("int", 2)
    assert values(result.env["y"]) == [17, 39]


def test_vector_star_vector_is_ambiguous() -> None:
    with pytest.raises(AetherTypeError, match="ambiguous"):
        run_aether("v = [1, 2, 3]; w = [4, 5, 6]; x = v * w;")


def test_dot_star_is_elementwise_for_vectors_and_matrices() -> None:
    result = run_aether(
        """
v = [1, 2, 3] .* [4, 5, 6];
A = [1 2; 3 4] .* [5 6; 7 8];
"""
    )

    assert result.env["v"].type_name == VectorType("int", 3)
    assert values(result.env["v"]) == [4, 10, 18]
    assert result.env["A"].type_name == MatrixType("int", 2, 2)
    assert matrix_values(result.env["A"]) == [[5, 12], [21, 32]]


def test_plus_minus_work_for_vectors_and_matrices() -> None:
    result = run_aether(
        """
v = [4, 5, 6] - [1, 2, 3];
w = [1, 2, 3] + [4, 5, 6];
A = [5 6; 7 8] - [1 2; 3 4];
B = [1 2; 3 4] + [5 6; 7 8];
"""
    )

    assert result.env["v"].type_name == VectorType("int", 3)
    assert values(result.env["v"]) == [3, 3, 3]
    assert values(result.env["w"]) == [5, 7, 9]
    assert matrix_values(result.env["A"]) == [[4, 4], [4, 4]]
    assert matrix_values(result.env["B"]) == [[6, 8], [10, 12]]


def test_dot_plus_minus_are_elementwise_and_broadcast_scalars() -> None:
    result = run_aether(
        """
v = [1, 2, 3] .+ 10;
w = 10 .- [1, 2, 3];
A = [1 2; 3 4] .+ 1;
B = 10 .- [1 2; 3 4];
"""
    )

    assert values(result.env["v"]) == [11, 12, 13]
    assert values(result.env["w"]) == [9, 8, 7]
    assert matrix_values(result.env["A"]) == [[2, 3], [4, 5]]
    assert matrix_values(result.env["B"]) == [[9, 8], [7, 6]]


def test_vector_subtraction_accepts_matrix_vector_product() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [1 2; 3 4];
z = [5, 6];
p = [17, 39];
err2 = norm(p - A*z)^2;
"""
    )

    assert result.env["err2"].type_name == "double"
    assert result.env["err2"].value == pytest.approx(0.0)


def test_matrix_indexing_slices_lower_or_preserve_dimension_like_julia() -> None:
    result = run_aether(
        """
A = [1 2 3; 4 5 6; 7 8 9];
a = A[0, 1];
col = A[:, 0];
row = A[0, :];
part = A[0:1, 1];
whole = A[:, :];
"""
    )

    assert result.env["a"].type_name == "int"
    assert result.env["a"].value == 2
    assert result.env["col"].type_name == VectorType("int", 3)
    assert values(result.env["col"]) == [1, 4, 7]
    assert result.env["row"].type_name == VectorType("int", 3)
    assert values(result.env["row"]) == [1, 2, 3]
    assert result.env["part"].type_name == VectorType("int", 2)
    assert values(result.env["part"]) == [2, 5]
    assert result.env["whole"].type_name == MatrixType("int", 3, 3)
    assert matrix_values(result.env["whole"]) == [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
