from __future__ import annotations

import pytest

from aether.errors import AetherTypeError
from aether.runner import run_aether as _run_aether
from aether.stdlib.math.linear_algebra import inner_builtin, norm_builtin
from aether.types import AetherValue, TransposeVectorType, VectorType


def run_aether(source: str):
    return _run_aether("import Math.LinearAlgebra;\n" + source)


def test_inner_row_vectors() -> None:
    result = run_aether("x = Math.LinearAlgebra.inner([1, 2, 3], [4, 5, 6]);")

    assert result.env["x"].type_name == "int"
    assert result.env["x"].value == 32


def test_inner_column_vectors() -> None:
    result = run_aether("x = Math.LinearAlgebra.inner([1; 2; 3], [4; 5; 6]);")

    assert result.env["x"].type_name == "int"
    assert result.env["x"].value == 32


@pytest.mark.parametrize(
    "source",
    [
        "Math.LinearAlgebra.inner([1, 2, 3], [4; 5; 6]);",
        "Math.LinearAlgebra.inner([1; 2; 3], [4, 5, 6]);",
    ],
)
def test_inner_rejects_mixed_row_column_vectors(source: str) -> None:
    with pytest.raises(AetherTypeError, match="same orientation"):
        run_aether(source)


def test_inner_rejects_matrix_operands() -> None:
    with pytest.raises(AetherTypeError, match="does not accept Matrix operands"):
        run_aether("Math.LinearAlgebra.inner([1 2; 3 4], [1 2; 3 4]);")


def test_inner_rejects_legacy_unoriented_vector_values() -> None:
    left = AetherValue(
        VectorType("int", 2),
        [AetherValue("int", 1), AetherValue("int", 2)],
    )
    right = AetherValue(
        VectorType("int", 2, "row"),
        [AetherValue("int", 3), AetherValue("int", 4)],
    )

    with pytest.raises(AetherTypeError, match="Row or Column orientation"):
        inner_builtin([left, right])


def test_inner_rejects_legacy_transpose_vector_values() -> None:
    vector = AetherValue(
        VectorType("int", 2, "row"),
        [AetherValue("int", 1), AetherValue("int", 2)],
    )
    legacy = AetherValue(TransposeVectorType("int", 2), vector)

    with pytest.raises(AetherTypeError, match="legacy TransposeVector"):
        inner_builtin([legacy, vector])


def test_norm_row_vector() -> None:
    result = run_aether("x = Math.LinearAlgebra.norm([3, 4]);")

    assert result.env["x"].type_name == "double"
    assert result.env["x"].value == pytest.approx(5.0)


def test_norm_column_vector() -> None:
    result = run_aether("x = Math.LinearAlgebra.norm([1; 2; 2]);")

    assert result.env["x"].type_name == "double"
    assert result.env["x"].value == pytest.approx(3.0)


def test_norm_rejects_matrix_operand() -> None:
    with pytest.raises(AetherTypeError, match="does not accept Matrix operands"):
        run_aether("Math.LinearAlgebra.norm([1 2; 3 4]);")


def test_norm_rejects_legacy_unoriented_vector_values() -> None:
    vector = AetherValue(
        VectorType("int", 2),
        [AetherValue("int", 3), AetherValue("int", 4)],
    )

    with pytest.raises(AetherTypeError, match="Row or Column orientation"):
        norm_builtin([vector])


def test_norm_rejects_legacy_transpose_vector_values() -> None:
    vector = AetherValue(
        VectorType("int", 2, "row"),
        [AetherValue("int", 3), AetherValue("int", 4)],
    )
    legacy = AetherValue(TransposeVectorType("int", 2), vector)

    with pytest.raises(AetherTypeError, match="legacy TransposeVector"):
        norm_builtin([legacy])
