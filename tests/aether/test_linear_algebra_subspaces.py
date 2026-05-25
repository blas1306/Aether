from __future__ import annotations

import numpy as np
import pytest

from aether.errors import AetherTypeError
from aether.runner import run_aether
from aether.types import MatrixType, VectorType


def _matrix_values(result, name: str) -> list[list[float]]:
    value = result.env[name]
    assert isinstance(value.type_name, MatrixType)
    return [[element.value for element in row.value] for row in value.value]


def _vector_values(result, name: str) -> list[int]:
    value = result.env[name]
    assert isinstance(value.type_name, VectorType)
    return [element.value for element in value.value]


def test_null_space_returns_kernel_basis_columns() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [1 1 1; 0 1 1];
K = N(A);
Z = A * K;
s = size(K);
"""
    )

    kernel = np.array(_matrix_values(result, "K"))
    residual = np.array(_matrix_values(result, "Z"))

    assert result.env["K"].type_name == MatrixType("double", 3, 1)
    assert _vector_values(result, "s") == [3, 1]
    assert np.allclose(residual, np.zeros((2, 1)), atol=1e-10)
    assert np.allclose(kernel.T @ kernel, np.eye(1), atol=1e-10)


def test_null_space_of_full_rank_matrix_has_zero_columns() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
K = N([1 0; 0 1]);
s = size(K);
"""
    )

    assert result.env["K"].type_name == MatrixType("double", 2, 0)
    assert _matrix_values(result, "K") == [[], []]
    assert _vector_values(result, "s") == [2, 0]


def test_range_returns_column_space_basis_columns() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [1 2; 0 0; 0 0];
B = R(A);
s = size(B);
"""
    )

    original = np.array([[1.0, 2.0], [0.0, 0.0], [0.0, 0.0]])
    basis = np.array(_matrix_values(result, "B"))
    projection = basis @ basis.T @ original

    assert result.env["B"].type_name == MatrixType("double", 3, 1)
    assert _vector_values(result, "s") == [3, 1]
    assert np.allclose(basis.T @ basis, np.eye(1), atol=1e-10)
    assert np.allclose(projection, original, atol=1e-10)


def test_rank_returns_matrix_rank_as_int() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [1 2 3; 2 4 6; 1 1 1];
r1 = rank(A);
r2 = Math.LinearAlgebra.rank([1 0; 0 1; 0 0]);
println(r1);
println(r2);
"""
    )

    assert result.env["r1"].type_name == "int"
    assert result.env["r1"].value == 2
    assert result.env["r2"].type_name == "int"
    assert result.env["r2"].value == 2
    assert result.output == "2\n2\n"


def test_rank_of_zero_matrix_is_zero() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
Z = zeros(3, 4);
r = rank(Z);
"""
    )

    assert result.env["r"].type_name == "int"
    assert result.env["r"].value == 0


def test_subspace_functions_reject_non_matrix_arguments() -> None:
    with pytest.raises(AetherTypeError, match="expects a mathematical matrix argument"):
        run_aether(
            """
import Math.LinearAlgebra
K = N([1, 2, 3]);
"""
        )

    with pytest.raises(AetherTypeError, match="expects a mathematical matrix argument"):
        run_aether(
            """
import Math.LinearAlgebra
B = R(1);
"""
        )

    with pytest.raises(AetherTypeError, match="expects a mathematical matrix argument"):
        run_aether(
            """
import Math.LinearAlgebra
r = rank([1, 2, 3]);
"""
        )
