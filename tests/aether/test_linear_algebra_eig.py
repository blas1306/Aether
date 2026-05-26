from __future__ import annotations

import numpy as np
import pytest

from aether.errors import AetherTypeError
from aether.runner import run_aether
from aether.types import MatrixType


def _matrix_values(result, name: str) -> list[list[float]]:
    value = result.env[name]
    assert isinstance(value.type_name, MatrixType)
    return [[element.value for element in row.value] for row in value.value]


def test_eig_returns_real_diagonalization_for_imported_short_name() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [1 1; 0 2];
S, D = eig(A);
left = A * S;
right = S * D;
"""
    )

    left = np.array(_matrix_values(result, "left"))
    right = np.array(_matrix_values(result, "right"))

    assert result.env["S"].type_name == MatrixType("double", 2, 2)
    assert result.env["D"].type_name == MatrixType("double", 2, 2)
    assert np.allclose(left, right, atol=1e-10)
    assert np.allclose(np.diag(_matrix_values(result, "D")), [1.0, 2.0], atol=1e-10)


def test_eig_returns_real_diagonalization_for_qualified_name() -> None:
    result = run_aether(
        """
A = [2 0; 0 3];
S, D = Math.LinearAlgebra.eig(A);
"""
    )

    assert np.allclose(_matrix_values(result, "S"), np.eye(2), atol=1e-10)
    assert np.allclose(_matrix_values(result, "D"), [[2.0, 0.0], [0.0, 3.0]], atol=1e-10)


def test_eig_returns_complex_diagonalization_for_complex_matrix() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [im 0; 0 2];
S, D = eig(A);
left = A * S;
right = S * D;
"""
    )

    left = np.array(_matrix_values(result, "left"), dtype=np.complex128)
    right = np.array(_matrix_values(result, "right"), dtype=np.complex128)

    assert result.env["S"].type_name == MatrixType("complex", 2, 2)
    assert result.env["D"].type_name == MatrixType("complex", 2, 2)
    assert np.allclose(left, right, atol=1e-10)
    assert np.allclose(np.diag(np.array(_matrix_values(result, "D"), dtype=np.complex128)), [1j, 2.0], atol=1e-10)


def test_eig_can_return_complex_diagonalization_for_real_matrix() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [0 -1; 1 0];
S, D = eig(A);
left = A * S;
right = S * D;
"""
    )

    assert result.env["S"].type_name == MatrixType("complex", 2, 2)
    assert result.env["D"].type_name == MatrixType("complex", 2, 2)
    assert np.allclose(
        np.array(_matrix_values(result, "left"), dtype=np.complex128),
        np.array(_matrix_values(result, "right"), dtype=np.complex128),
        atol=1e-10,
    )


def test_eig_rejects_defective_matrix() -> None:
    with pytest.raises(AetherTypeError, match="not diagonalizable"):
        run_aether(
            """
import Math.LinearAlgebra
S, D = eig([1 1; 0 1]);
"""
        )


def test_eig_rejects_non_square_matrix() -> None:
    with pytest.raises(AetherTypeError, match="expects a square matrix"):
        run_aether(
            """
import Math.LinearAlgebra
S, D = eig([1 2 3; 4 5 6]);
"""
        )
