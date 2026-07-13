from __future__ import annotations

import pytest

from aether.errors import AetherTypeError
from aether.runner import run_aether as _run_aether
from aether.stdlib.math.linear_algebra import matmul_builtin
from aether.types import AetherValue, MatrixType, TransposeVectorType, VectorType


def run_aether(source: str):
    return _run_aether("import Math.LinearAlgebra;\n" + source)


def matrix_values(value: AetherValue) -> list[list[object]]:
    return [[element.value for element in row.value] for row in value.value]


def vector_values(value: AetherValue) -> list[object]:
    return [element.value for element in value.value]


def test_matmul_row_times_column_returns_scalar() -> None:
    result = run_aether(
        """
r = [1, 2, 3];
c = [4; 5; 6];
x = Math.LinearAlgebra.matmul(r, c);
"""
    )

    assert result.env["x"].type_name == "int"
    assert result.env["x"].value == 32


def test_matmul_column_times_row_returns_matrix() -> None:
    result = run_aether(
        """
c = [1; 2; 3];
r = [4, 5];
A = Math.LinearAlgebra.matmul(c, r);
"""
    )

    assert result.env["A"].type_name == MatrixType("int", 3, 2)
    assert matrix_values(result.env["A"]) == [[4, 5], [8, 10], [12, 15]]


def test_matmul_matrix_times_matrix_returns_matrix() -> None:
    result = run_aether(
        """
A = [1 2; 3 4];
B = [5 6; 7 8];
C = Math.LinearAlgebra.matmul(A, B);
"""
    )

    assert result.env["C"].type_name == MatrixType("int", 2, 2)
    assert matrix_values(result.env["C"]) == [[19, 22], [43, 50]]


def test_matrix_multiplication_operator_matches_matmul_matrix_matrix() -> None:
    result = run_aether(
        """
A = [1 2 3; 4 5 6];
B = [7 8; 9 10; 11 12];
C = A * B;
D = Math.LinearAlgebra.matmul(A, B);
"""
    )

    assert result.env["C"].type_name == MatrixType("int", 2, 2)
    assert matrix_values(result.env["C"]) == [[58, 64], [139, 154]]
    assert result.env["C"].type_name == result.env["D"].type_name
    assert matrix_values(result.env["C"]) == matrix_values(result.env["D"])


def test_matrix_multiplication_operator_uses_matmul_type_promotion() -> None:
    result = run_aether(
        """
Matrix<double> A = [1.0 2.0; 3.0 4.0];
Matrix<int> B = [5 6; 7 8];
C = A * B;
"""
    )

    assert result.env["C"].type_name == MatrixType("double", 2, 2)
    assert matrix_values(result.env["C"]) == [[19.0, 22.0], [43.0, 50.0]]


def test_matmul_matrix_times_column_returns_column() -> None:
    result = run_aether(
        """
A = [1 2; 3 4];
c = [5; 6];
y = Math.LinearAlgebra.matmul(A, c);
"""
    )

    assert result.env["y"].type_name == VectorType("int", 2, "column")
    assert result.env["y"].type_name.orientation == "column"
    assert vector_values(result.env["y"]) == [17, 39]


def test_matmul_row_times_matrix_returns_row() -> None:
    result = run_aether(
        """
r = [1, 2];
A = [3 4; 5 6];
y = Math.LinearAlgebra.matmul(r, A);
"""
    )

    assert result.env["y"].type_name == VectorType("int", 2, "row")
    assert result.env["y"].type_name.orientation == "row"
    assert vector_values(result.env["y"]) == [13, 16]


@pytest.mark.parametrize(
    "source",
    [
        "Math.LinearAlgebra.matmul([1, 2], [3, 4]);",
        "Math.LinearAlgebra.matmul([1; 2], [3; 4]);",
        "Math.LinearAlgebra.matmul([1; 2], [3 4; 5 6]);",
        "Math.LinearAlgebra.matmul([1 2; 3 4], [5, 6]);",
    ],
)
def test_matmul_rejects_invalid_orientation_combinations(source: str) -> None:
    with pytest.raises(AetherTypeError, match="no multiplication rule"):
        run_aether(source)


def test_matmul_rejects_legacy_unoriented_vector_values() -> None:
    left = AetherValue(
        VectorType("int", 2),
        [AetherValue("int", 1), AetherValue("int", 2)],
    )
    right = AetherValue(
        VectorType("int", 2, "column"),
        [AetherValue("int", 3), AetherValue("int", 4)],
    )

    with pytest.raises(AetherTypeError, match="Row or Column orientation"):
        matmul_builtin([left, right])


def test_matmul_rejects_legacy_transpose_vector_values() -> None:
    vector = AetherValue(
        VectorType("int", 2, "row"),
        [AetherValue("int", 1), AetherValue("int", 2)],
    )
    legacy = AetherValue(TransposeVectorType("int", 2), vector)
    column = AetherValue(
        VectorType("int", 2, "column"),
        [AetherValue("int", 3), AetherValue("int", 4)],
    )

    with pytest.raises(AetherTypeError, match="legacy TransposeVector"):
        matmul_builtin([legacy, column])
