from __future__ import annotations

import pytest

from aether.ir import (
    BoolType,
    IRBasicBlock,
    IRCompareOp,
    IRFunction,
    IRMatrixNew,
    IRModule,
    IRParameter,
    IRPrint,
    IRReturn,
    IRValue,
    IRVectorNew,
    IRVerificationError,
    IRVerifier,
    IntType,
    MatrixType,
    VectorType,
    VoidType,
)


def _verify(instruction: object, parameters: tuple[IRParameter, ...] = ()) -> None:
    module = IRModule(
        [
            IRFunction(
                "main",
                list(parameters),
                VoidType(),
                [IRBasicBlock("entry", [instruction, IRReturn()])],
            )
        ]
    )
    IRVerifier(module).verify()


@pytest.mark.parametrize(
    ("type_", "shape"),
    [
        (VectorType(IntType(), "row"), (0,)),
        (VectorType(IntType(), "column"), (-1,)),
        (MatrixType(IntType()), (0, 3)),
        (MatrixType(IntType()), (-1, 2)),
    ],
)
def test_print_shape_characterization_requires_rank_but_not_positivity(
    type_: VectorType | MatrixType,
    shape: tuple[int, ...],
) -> None:
    printed = IRParameter("printed", type_)

    _verify(IRPrint(printed, True, shape), (printed,))


def test_scalar_compare_characterization_rejects_even_an_empty_shape() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", IntType())
    result = IRValue("result", BoolType())

    with pytest.raises(IRVerificationError, match="Scalar compare must not carry"):
        _verify(IRCompareOp(result, "eq", left, right, ()), (left, right))


@pytest.mark.parametrize("shape", [None, (), (0,), (-1,), (1, 1)])
def test_vector_compare_characterization_requires_positive_rank_one_shape(
    shape: tuple[int, ...] | None,
) -> None:
    vector_type = VectorType(IntType(), "row")
    left = IRParameter("left", vector_type)
    right = IRParameter("right", vector_type)
    result = IRValue("result", BoolType())

    with pytest.raises(IRVerificationError, match="positive rank-1 shape"):
        _verify(IRCompareOp(result, "eq", left, right, shape), (left, right))


def test_vector_literal_characterization_accepts_zero_elements() -> None:
    result = IRValue("result", VectorType(IntType(), "row"))

    _verify(IRVectorNew(result, (), "row"))


@pytest.mark.parametrize("element_count", [5, 7])
def test_matrix_literal_characterization_requires_exact_flat_cardinality(
    element_count: int,
) -> None:
    elements = tuple(IRParameter(f"element{index}", IntType()) for index in range(element_count))
    result = IRValue("result", MatrixType(IntType()))

    with pytest.raises(IRVerificationError, match="expected 6"):
        _verify(IRMatrixNew(result, elements, 2, 3), elements)
