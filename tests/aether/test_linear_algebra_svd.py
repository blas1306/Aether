from __future__ import annotations

import numpy as np
import pytest

from aether.errors import AetherTypeError
from aether.runner import run_aether as _run_aether
from aether.types import MatrixType


def run_aether(source: str):
    prefix = "" if "import Math.LinearAlgebra" in source else "import Math.LinearAlgebra;\n"
    return _run_aether(prefix + source)


def _matrix_values(result, name: str) -> list[list[float]]:
    value = result.env[name]
    assert isinstance(value.type_name, MatrixType)
    return [[element.value for element in row.value] for row in value.value]


def test_svd_returns_full_factors_for_imported_short_name() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [3 2; 1 0; 0 0];
U, S, V = Math.LinearAlgebra.SVD(A);
R = Math.LinearAlgebra.matmul(Math.LinearAlgebra.matmul(U, S), V');
"""
    )

    assert result.env["U"].type_name == MatrixType("double", 3, 3)
    assert result.env["S"].type_name == MatrixType("double", 3, 2)
    assert result.env["V"].type_name == MatrixType("double", 2, 2)
    assert np.allclose(_matrix_values(result, "R"), [[3.0, 2.0], [1.0, 0.0], [0.0, 0.0]], atol=1e-10)
    assert np.allclose(np.array(_matrix_values(result, "U")).T @ np.array(_matrix_values(result, "U")), np.eye(3), atol=1e-10)
    assert np.allclose(np.array(_matrix_values(result, "V")).T @ np.array(_matrix_values(result, "V")), np.eye(2), atol=1e-10)


def test_svd_returns_full_factors_for_qualified_name_and_wide_matrix() -> None:
    result = run_aether(
        """
A = [1 2 3; 4 5 6];
U, S, V = Math.LinearAlgebra.SVD(A);
R = Math.LinearAlgebra.matmul(Math.LinearAlgebra.matmul(U, S), Math.LinearAlgebra.transpose(V));
"""
    )

    assert result.env["U"].type_name == MatrixType("double", 2, 2)
    assert result.env["S"].type_name == MatrixType("double", 2, 3)
    assert result.env["V"].type_name == MatrixType("double", 3, 3)
    assert np.allclose(_matrix_values(result, "R"), [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], atol=1e-10)


def test_svd_returns_complex_unitary_factors_for_complex_matrix() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [1 im; 2 0; 0 1 - im];
U, S, V = Math.LinearAlgebra.SVD(A);
R = Math.LinearAlgebra.matmul(Math.LinearAlgebra.matmul(U, S), V');
"""
    )

    assert result.env["U"].type_name == MatrixType("complex", 3, 3)
    assert result.env["S"].type_name == MatrixType("double", 3, 2)
    assert result.env["V"].type_name == MatrixType("complex", 2, 2)
    assert np.allclose(
        np.array(_matrix_values(result, "R"), dtype=np.complex128),
        np.array([[1.0, 1j], [2.0, 0.0], [0.0, 1.0 - 1j]], dtype=np.complex128),
        atol=1e-10,
    )
    u_matrix = np.array(_matrix_values(result, "U"), dtype=np.complex128)
    v_matrix = np.array(_matrix_values(result, "V"), dtype=np.complex128)
    assert np.allclose(u_matrix.conj().T @ u_matrix, np.eye(3), atol=1e-10)
    assert np.allclose(v_matrix.conj().T @ v_matrix, np.eye(2), atol=1e-10)


def test_svd_rejects_non_matrix_arguments() -> None:
    with pytest.raises(AetherTypeError, match="expects a mathematical matrix argument"):
        run_aether(
            """
import Math.LinearAlgebra
U, S, V = Math.LinearAlgebra.SVD([1, 2, 3]);
"""
        )
