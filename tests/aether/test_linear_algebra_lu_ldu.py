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


def test_lu_returns_permutation_lower_and_upper_factors_after_import() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [2 1; 4 5];
P, L, U = LU(A);
PA = P * A;
R = L * U;
"""
    )

    assert result.env["P"].type_name == MatrixType("double", 2, 2)
    assert result.env["L"].type_name == MatrixType("double", 2, 2)
    assert result.env["U"].type_name == MatrixType("double", 2, 2)
    assert np.allclose(_matrix_values(result, "P"), [[0.0, 1.0], [1.0, 0.0]], atol=1e-10)
    assert np.allclose(_matrix_values(result, "L"), [[1.0, 0.0], [0.5, 1.0]], atol=1e-10)
    assert np.allclose(_matrix_values(result, "U"), [[4.0, 5.0], [0.0, -1.5]], atol=1e-10)
    assert np.allclose(_matrix_values(result, "R"), _matrix_values(result, "PA"), atol=1e-10)


def test_ldu_returns_permutation_unit_triangular_factors_and_diagonal_factor() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [4 8; 2 6];
P, L, D, U = LDU(A);
PA = P * A;
R = L * D * U;
"""
    )

    assert result.env["P"].type_name == MatrixType("double", 2, 2)
    assert result.env["L"].type_name == MatrixType("double", 2, 2)
    assert result.env["D"].type_name == MatrixType("double", 2, 2)
    assert result.env["U"].type_name == MatrixType("double", 2, 2)
    assert np.allclose(_matrix_values(result, "P"), [[1.0, 0.0], [0.0, 1.0]], atol=1e-10)
    assert np.allclose(_matrix_values(result, "L"), [[1.0, 0.0], [0.5, 1.0]], atol=1e-10)
    assert np.allclose(_matrix_values(result, "D"), [[4.0, 0.0], [0.0, 2.0]], atol=1e-10)
    assert np.allclose(_matrix_values(result, "U"), [[1.0, 2.0], [0.0, 1.0]], atol=1e-10)
    assert np.allclose(_matrix_values(result, "R"), _matrix_values(result, "PA"), atol=1e-10)


def test_lu_and_ldu_work_with_qualified_names() -> None:
    result = run_aether(
        """
A = [3 6; 1 5];
P1, L1, U1 = Math.LinearAlgebra.LU(A);
P2, L2, D2, U2 = Math.LinearAlgebra.LDU(A);
PA1 = P1 * A;
PA2 = P2 * A;
R1 = L1 * U1;
R2 = L2 * D2 * U2;
"""
    )

    assert np.allclose(_matrix_values(result, "R1"), _matrix_values(result, "PA1"), atol=1e-10)
    assert np.allclose(_matrix_values(result, "R2"), _matrix_values(result, "PA2"), atol=1e-10)


def test_lu_and_ldu_include_permutation_for_row_swaps() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [0 1; 1 0];
P1, L1, U1 = LU(A);
P2, L2, D2, U2 = LDU(A);
PA1 = P1 * A;
PA2 = P2 * A;
R1 = L1 * U1;
R2 = L2 * D2 * U2;
"""
    )

    assert np.allclose(_matrix_values(result, "P1"), [[0.0, 1.0], [1.0, 0.0]], atol=1e-10)
    assert np.allclose(_matrix_values(result, "P2"), [[0.0, 1.0], [1.0, 0.0]], atol=1e-10)
    assert np.allclose(_matrix_values(result, "R1"), _matrix_values(result, "PA1"), atol=1e-10)
    assert np.allclose(_matrix_values(result, "R2"), _matrix_values(result, "PA2"), atol=1e-10)


def test_lu_returns_complex_factors_for_complex_matrix() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [0 1 + im; 2 3];
P, L, U = LU(A);
PA = P * A;
R = L * U;
"""
    )

    assert result.env["P"].type_name == MatrixType("double", 2, 2)
    assert result.env["L"].type_name == MatrixType("complex", 2, 2)
    assert result.env["U"].type_name == MatrixType("complex", 2, 2)
    assert np.allclose(
        np.array(_matrix_values(result, "R"), dtype=np.complex128),
        np.array(_matrix_values(result, "PA"), dtype=np.complex128),
        atol=1e-10,
    )


def test_ldu_returns_complex_factors_for_complex_matrix() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [2 1 + im; 4 3];
P, L, D, U = LDU(A);
PA = P * A;
R = L * D * U;
"""
    )

    assert result.env["P"].type_name == MatrixType("double", 2, 2)
    assert result.env["L"].type_name == MatrixType("complex", 2, 2)
    assert result.env["D"].type_name == MatrixType("complex", 2, 2)
    assert result.env["U"].type_name == MatrixType("complex", 2, 2)
    assert np.allclose(
        np.array(_matrix_values(result, "R"), dtype=np.complex128),
        np.array(_matrix_values(result, "PA"), dtype=np.complex128),
        atol=1e-10,
    )


def test_lu_and_ldu_reject_non_square_matrices() -> None:
    with pytest.raises(AetherTypeError, match="expects a square matrix"):
        run_aether(
            """
import Math.LinearAlgebra
P, L, U = LU([1 2 3; 4 5 6]);
"""
        )

    with pytest.raises(AetherTypeError, match="expects a square matrix"):
        run_aether(
            """
import Math.LinearAlgebra
P, L, D, U = LDU([1 2 3; 4 5 6]);
"""
        )


def test_ldu_reports_when_zero_diagonal_prevents_unit_upper_factor() -> None:
    with pytest.raises(AetherTypeError, match="requires nonzero pivots"):
        run_aether(
            """
import Math.LinearAlgebra
P, L, D, U = LDU([0 1; 0 0]);
"""
        )
