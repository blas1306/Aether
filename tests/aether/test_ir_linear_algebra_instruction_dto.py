from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest

from aether.ir.dto import (
    IRDTOError,
    IRDTOSchemaVersionError,
    ir_instruction_from_dto,
    ir_instruction_to_dto,
)
from aether.ir.model import (
    IRBasicBlock,
    IRBranch,
    IRConst,
    IRCopyInit,
    IRFunction,
    IRInstruction,
    IRMatrixAdd,
    IRMatrixColumns,
    IRMatrixGet,
    IRMatrixMatMul,
    IRMatrixNew,
    IRMatrixRows,
    IRMatrixScale,
    IRMatrixSet,
    IRMatrixSub,
    IRMatrixVectorMul,
    IRModule,
    IROuterProduct,
    IRReturn,
    IRStorage,
    IRValue,
    IRVectorAdd,
    IRVectorDot,
    IRVectorGet,
    IRVectorLength,
    IRVectorMatrixMul,
    IRVectorNew,
    IRVectorScale,
    IRVectorSet,
    IRVectorSub,
)
from aether.ir.types import BoolType, IntType, MatrixType, VectorType
from aether.ir.verifier import IRVerificationError, IRVerifier


INT = IntType()
ROW_VECTOR_TYPE = VectorType(INT, "row")
COLUMN_VECTOR_TYPE = VectorType(INT, "column")
MATRIX_TYPE = MatrixType(INT)

RESULT = IRValue("result", INT)
INDEX = IRValue("index", INT)
ROW_INDEX = IRValue("row_index", INT)
COLUMN_INDEX = IRValue("column_index", INT)
SCALAR = IRValue("scalar", INT)
FIRST = IRValue("first", INT)
SECOND = IRValue("second", INT)
THIRD = IRValue("third", INT)
FOURTH = IRValue("fourth", INT)
ROW_VECTOR = IRValue("row_vector", ROW_VECTOR_TYPE)
OTHER_ROW_VECTOR = IRValue("other_row_vector", ROW_VECTOR_TYPE)
COLUMN_VECTOR = IRValue("column_vector", COLUMN_VECTOR_TYPE)
OTHER_COLUMN_VECTOR = IRValue("other_column_vector", COLUMN_VECTOR_TYPE)
ROW_RESULT = IRValue("row_result", ROW_VECTOR_TYPE)
COLUMN_RESULT = IRValue("column_result", COLUMN_VECTOR_TYPE)
MATRIX = IRValue("matrix", MATRIX_TYPE)
OTHER_MATRIX = IRValue("other_matrix", MATRIX_TYPE)
MATRIX_RESULT = IRValue("matrix_result", MATRIX_TYPE)

INT_DTO = {"tag": "int"}
ROW_VECTOR_TYPE_DTO = {
    "tag": "vector",
    "element": INT_DTO,
    "orientation": "row",
}
COLUMN_VECTOR_TYPE_DTO = {
    "tag": "vector",
    "element": INT_DTO,
    "orientation": "column",
}
MATRIX_TYPE_DTO = {"tag": "matrix", "element": INT_DTO}


def _value_dto(name: str, type_dto: object = INT_DTO) -> dict[str, object]:
    return {"tag": "value", "name": name, "type": type_dto}


ROUND_TRIP_CASES: tuple[tuple[IRInstruction, dict[str, object]], ...] = (
    (
        IRVectorNew(ROW_RESULT, (FIRST, SECOND), "row"),
        {
            "kind": "vector_new",
            "result": _value_dto("row_result", ROW_VECTOR_TYPE_DTO),
            "elements": [_value_dto("first"), _value_dto("second")],
            "orientation": "row",
        },
    ),
    (
        IRMatrixNew(MATRIX_RESULT, (FIRST, SECOND, THIRD, FOURTH), 2, 2),
        {
            "kind": "matrix_new",
            "result": _value_dto("matrix_result", MATRIX_TYPE_DTO),
            "elements": [
                _value_dto("first"),
                _value_dto("second"),
                _value_dto("third"),
                _value_dto("fourth"),
            ],
            "shape": [2, 2],
        },
    ),
    (
        IRVectorAdd(ROW_RESULT, ROW_VECTOR, OTHER_ROW_VECTOR, 4, "row"),
        {
            "kind": "vector_add",
            "result": _value_dto("row_result", ROW_VECTOR_TYPE_DTO),
            "left": _value_dto("row_vector", ROW_VECTOR_TYPE_DTO),
            "right": _value_dto("other_row_vector", ROW_VECTOR_TYPE_DTO),
            "shape": [4],
            "orientation": "row",
        },
    ),
    (
        IRVectorSub(ROW_RESULT, OTHER_ROW_VECTOR, ROW_VECTOR, 4, "row"),
        {
            "kind": "vector_sub",
            "result": _value_dto("row_result", ROW_VECTOR_TYPE_DTO),
            "left": _value_dto("other_row_vector", ROW_VECTOR_TYPE_DTO),
            "right": _value_dto("row_vector", ROW_VECTOR_TYPE_DTO),
            "shape": [4],
            "orientation": "row",
        },
    ),
    (
        IRVectorScale(COLUMN_RESULT, COLUMN_VECTOR, SCALAR, 3, "column"),
        {
            "kind": "vector_scale",
            "result": _value_dto("column_result", COLUMN_VECTOR_TYPE_DTO),
            "vector": _value_dto("column_vector", COLUMN_VECTOR_TYPE_DTO),
            "scalar": _value_dto("scalar"),
            "shape": [3],
            "orientation": "column",
        },
    ),
    (
        IRVectorDot(RESULT, ROW_VECTOR, COLUMN_VECTOR, 3),
        {
            "kind": "vector_dot",
            "result": _value_dto("result"),
            "left": _value_dto("row_vector", ROW_VECTOR_TYPE_DTO),
            "right": _value_dto("column_vector", COLUMN_VECTOR_TYPE_DTO),
            "shape": [3],
        },
    ),
    (
        IROuterProduct(MATRIX_RESULT, COLUMN_VECTOR, ROW_VECTOR, 3, 4),
        {
            "kind": "outer_product",
            "result": _value_dto("matrix_result", MATRIX_TYPE_DTO),
            "column": _value_dto("column_vector", COLUMN_VECTOR_TYPE_DTO),
            "row": _value_dto("row_vector", ROW_VECTOR_TYPE_DTO),
            "shape": [3, 4],
        },
    ),
    (
        IRMatrixAdd(MATRIX_RESULT, MATRIX, OTHER_MATRIX, 2, 3),
        {
            "kind": "matrix_add",
            "result": _value_dto("matrix_result", MATRIX_TYPE_DTO),
            "left": _value_dto("matrix", MATRIX_TYPE_DTO),
            "right": _value_dto("other_matrix", MATRIX_TYPE_DTO),
            "shape": [2, 3],
        },
    ),
    (
        IRMatrixSub(MATRIX_RESULT, OTHER_MATRIX, MATRIX, 2, 3),
        {
            "kind": "matrix_sub",
            "result": _value_dto("matrix_result", MATRIX_TYPE_DTO),
            "left": _value_dto("other_matrix", MATRIX_TYPE_DTO),
            "right": _value_dto("matrix", MATRIX_TYPE_DTO),
            "shape": [2, 3],
        },
    ),
    (
        IRMatrixScale(MATRIX_RESULT, MATRIX, SCALAR, 2, 3),
        {
            "kind": "matrix_scale",
            "result": _value_dto("matrix_result", MATRIX_TYPE_DTO),
            "matrix": _value_dto("matrix", MATRIX_TYPE_DTO),
            "scalar": _value_dto("scalar"),
            "shape": [2, 3],
        },
    ),
    (
        IRMatrixMatMul(MATRIX_RESULT, MATRIX, OTHER_MATRIX, 2, 3, 4),
        {
            "kind": "matrix_mat_mul",
            "result": _value_dto("matrix_result", MATRIX_TYPE_DTO),
            "left": _value_dto("matrix", MATRIX_TYPE_DTO),
            "right": _value_dto("other_matrix", MATRIX_TYPE_DTO),
            "shape": [2, 3, 4],
        },
    ),
    (
        IRMatrixVectorMul(COLUMN_RESULT, MATRIX, COLUMN_VECTOR, 2, 3),
        {
            "kind": "matrix_vector_mul",
            "result": _value_dto("column_result", COLUMN_VECTOR_TYPE_DTO),
            "matrix": _value_dto("matrix", MATRIX_TYPE_DTO),
            "vector": _value_dto("column_vector", COLUMN_VECTOR_TYPE_DTO),
            "shape": [2, 3],
        },
    ),
    (
        IRVectorMatrixMul(ROW_RESULT, ROW_VECTOR, MATRIX, 3, 4),
        {
            "kind": "vector_matrix_mul",
            "result": _value_dto("row_result", ROW_VECTOR_TYPE_DTO),
            "vector": _value_dto("row_vector", ROW_VECTOR_TYPE_DTO),
            "matrix": _value_dto("matrix", MATRIX_TYPE_DTO),
            "shape": [3, 4],
        },
    ),
    (
        IRVectorGet(RESULT, ROW_VECTOR, INDEX),
        {
            "kind": "vector_get",
            "result": _value_dto("result"),
            "vector": _value_dto("row_vector", ROW_VECTOR_TYPE_DTO),
            "index": _value_dto("index"),
        },
    ),
    (
        IRMatrixGet(RESULT, MATRIX, ROW_INDEX, COLUMN_INDEX, 7),
        {
            "kind": "matrix_get",
            "result": _value_dto("result"),
            "matrix": _value_dto("matrix", MATRIX_TYPE_DTO),
            "row": _value_dto("row_index"),
            "column": _value_dto("column_index"),
            "shape": [7],
        },
    ),
    (
        IRVectorLength(RESULT, COLUMN_VECTOR),
        {
            "kind": "vector_length",
            "result": _value_dto("result"),
            "vector": _value_dto("column_vector", COLUMN_VECTOR_TYPE_DTO),
        },
    ),
    (
        IRMatrixRows(RESULT, MATRIX, 5),
        {
            "kind": "matrix_rows",
            "result": _value_dto("result"),
            "matrix": _value_dto("matrix", MATRIX_TYPE_DTO),
            "shape": [5],
        },
    ),
    (
        IRMatrixColumns(RESULT, MATRIX, 7),
        {
            "kind": "matrix_columns",
            "result": _value_dto("result"),
            "matrix": _value_dto("matrix", MATRIX_TYPE_DTO),
            "shape": [7],
        },
    ),
    (
        IRVectorSet(ROW_VECTOR, INDEX, SCALAR),
        {
            "kind": "vector_set",
            "vector": _value_dto("row_vector", ROW_VECTOR_TYPE_DTO),
            "index": _value_dto("index"),
            "value": _value_dto("scalar"),
        },
    ),
    (
        IRMatrixSet(MATRIX, ROW_INDEX, COLUMN_INDEX, SCALAR, 7),
        {
            "kind": "matrix_set",
            "matrix": _value_dto("matrix", MATRIX_TYPE_DTO),
            "row": _value_dto("row_index"),
            "column": _value_dto("column_index"),
            "value": _value_dto("scalar"),
            "shape": [7],
        },
    ),
)


@pytest.mark.parametrize(("instruction", "expected"), ROUND_TRIP_CASES)
def test_every_linear_algebra_instruction_round_trips_with_exact_dto(
    instruction: IRInstruction,
    expected: dict[str, object],
) -> None:
    dto = ir_instruction_to_dto(instruction)

    assert dto == expected
    assert ir_instruction_from_dto(dto) == instruction
    assert type(ir_instruction_from_dto(dto)) is type(instruction)
    _assert_neutral(dto)


def test_empty_and_non_empty_constructions_preserve_flat_row_major_elements() -> None:
    unoriented_type = VectorType(INT)
    empty_vector = IRVectorNew(IRValue("empty_vector", unoriented_type), (), None)
    empty_matrix = IRMatrixNew(MATRIX_RESULT, (), 0, 0)

    assert ir_instruction_to_dto(empty_vector) == {
        "kind": "vector_new",
        "result": _value_dto(
            "empty_vector",
            {"tag": "vector", "element": INT_DTO, "orientation": None},
        ),
        "elements": [],
        "orientation": None,
    }
    assert ir_instruction_to_dto(empty_matrix)["elements"] == []
    assert ir_instruction_to_dto(empty_matrix)["shape"] == [0, 0]

    matrix_dto = ir_instruction_to_dto(ROUND_TRIP_CASES[1][0])
    assert [element["name"] for element in matrix_dto["elements"]] == [
        "first",
        "second",
        "third",
        "fourth",
    ]


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        (
            IRCopyInit(IRStorage("vector_copy", ROW_VECTOR_TYPE), ROW_VECTOR),
            {
                "kind": "copy_init",
                "destination": {
                    "tag": "storage",
                    "name": "vector_copy",
                    "type": ROW_VECTOR_TYPE_DTO,
                },
                "source": _value_dto("row_vector", ROW_VECTOR_TYPE_DTO),
                "source_location": None,
            },
        ),
        (
            IRCopyInit(IRStorage("matrix_copy", MATRIX_TYPE), MATRIX),
            {
                "kind": "copy_init",
                "destination": {
                    "tag": "storage",
                    "name": "matrix_copy",
                    "type": MATRIX_TYPE_DTO,
                },
                "source": _value_dto("matrix", MATRIX_TYPE_DTO),
                "source_location": None,
            },
        ),
    ],
)
def test_vector_and_matrix_copying_reuses_the_generic_storage_contract(
    instruction: IRCopyInit,
    expected: dict[str, object],
) -> None:
    dto = ir_instruction_to_dto(instruction)

    assert dto == expected
    assert ir_instruction_from_dto(dto) == instruction


def test_one_two_and_three_dimension_shapes_use_the_same_ordered_list_form() -> None:
    assert ir_instruction_to_dto(IRVectorDot(RESULT, ROW_VECTOR, COLUMN_VECTOR, 9))["shape"] == [9]
    assert ir_instruction_to_dto(IRMatrixAdd(MATRIX_RESULT, MATRIX, OTHER_MATRIX, 2, 7))["shape"] == [
        2,
        7,
    ]
    assert ir_instruction_to_dto(
        IRMatrixMatMul(MATRIX_RESULT, MATRIX, OTHER_MATRIX, 2, 5, 7)
    )["shape"] == [2, 5, 7]


def test_operand_and_row_column_order_are_preserved() -> None:
    subtraction = ir_instruction_to_dto(
        IRMatrixSub(MATRIX_RESULT, OTHER_MATRIX, MATRIX, 2, 3)
    )
    access = ir_instruction_to_dto(
        IRMatrixGet(RESULT, MATRIX, ROW_INDEX, COLUMN_INDEX, 7)
    )

    assert subtraction["left"]["name"] == "other_matrix"
    assert subtraction["right"]["name"] == "matrix"
    assert access["row"]["name"] == "row_index"
    assert access["column"]["name"] == "column_index"


@pytest.mark.parametrize("instruction", [case[0] for case in ROUND_TRIP_CASES])
def test_linear_algebra_encoding_is_deterministic(instruction: IRInstruction) -> None:
    first = ir_instruction_to_dto(instruction)
    second = ir_instruction_to_dto(instruction)

    assert first == second
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second,
        sort_keys=True,
        separators=(",", ":"),
    )


@pytest.mark.parametrize(
    "dimensions",
    [
        (0, 0),
        (-1, 3),
        (3, -1),
        (-(2**63), 2**63 - 1),
    ],
)
def test_structurally_valid_semantically_invalid_dimensions_round_trip(
    dimensions: tuple[int, int],
) -> None:
    instruction = IRMatrixNew(MATRIX_RESULT, (), *dimensions)

    dto = ir_instruction_to_dto(instruction)

    assert dto["shape"] == list(dimensions)
    assert ir_instruction_from_dto(dto) == instruction


def _matrix_new_dto() -> dict[str, object]:
    return {
        "kind": "matrix_new",
        "result": _value_dto("matrix_result", MATRIX_TYPE_DTO),
        "elements": [],
        "shape": [2, 3],
    }


@pytest.mark.parametrize(
    ("dto", "message"),
    [
        ({"kind": "matrix_new"}, "missing fields"),
        ({**_matrix_new_dto(), "extra": None}, "unexpected fields: extra"),
        ({**_matrix_new_dto(), "shape": "2x3"}, "shape must be a sequence"),
        ({**_matrix_new_dto(), "shape": {"rows": 2}}, "shape must be a sequence"),
        ({**_matrix_new_dto(), "shape": []}, "must contain exactly 2 dimensions"),
        ({**_matrix_new_dto(), "shape": [2]}, "must contain exactly 2 dimensions"),
        ({**_matrix_new_dto(), "shape": [2, 3, 4]}, "must contain exactly 2 dimensions"),
        ({**_matrix_new_dto(), "shape": [2, True]}, r"shape\[1\].*signed 64-bit integer"),
        ({**_matrix_new_dto(), "shape": [2, [3]]}, r"shape\[1\].*signed 64-bit integer"),
        ({**_matrix_new_dto(), "shape": [2, 2**63]}, r"shape\[1\].*signed 64-bit integer"),
        ({**_matrix_new_dto(), "elements": "values"}, "elements must be a sequence"),
        ({**_matrix_new_dto(), "elements": [7]}, "IR value DTO must be a mapping"),
        ({**_matrix_new_dto(), "result": 7}, "IR value DTO must be a mapping"),
        (
            {
                "kind": "vector_new",
                "result": _value_dto("row_result", ROW_VECTOR_TYPE_DTO),
                "elements": [],
                "orientation": False,
            },
            "orientation must be a string",
        ),
        (
            {
                "kind": "vector_get",
                "result": _value_dto("result"),
                "vector": _value_dto("row_vector", {"tag": "future"}),
                "index": _value_dto("index"),
            },
            "Unknown IR type DTO tag",
        ),
    ],
)
def test_malformed_linear_algebra_dtos_are_rejected(
    dto: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_instruction_from_dto(dto)


@pytest.mark.parametrize(
    "instruction",
    [
        IRMatrixNew(MATRIX_RESULT, (), True, 2),
        IRVectorDot(RESULT, ROW_VECTOR, COLUMN_VECTOR, 2**63),
        IRMatrixMatMul(MATRIX_RESULT, MATRIX, OTHER_MATRIX, 2, [3], 4),
        IRMatrixColumns(RESULT, MATRIX, False),
        IRVectorNew(ROW_RESULT, (), 1),
    ],
)
def test_encoder_rejects_wrong_dimension_and_optional_primitive_types(
    instruction: IRInstruction,
) -> None:
    with pytest.raises(IRDTOError):
        ir_instruction_to_dto(instruction)


@pytest.mark.parametrize("instruction", [case[0] for case in ROUND_TRIP_CASES])
def test_linear_algebra_variants_reject_incompatible_schema_versions(
    instruction: IRInstruction,
) -> None:
    dto = ir_instruction_to_dto(instruction)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_instruction_to_dto(instruction, schema_version=2)
    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_instruction_from_dto(dto, schema_version=2)


def test_semantically_invalid_dimensions_pass_through_to_the_verifier() -> None:
    first = IRValue("defined", INT)
    returned = IRValue("returned", INT)
    dto = {
        "kind": "matrix_new",
        "result": _value_dto("matrix_result", MATRIX_TYPE_DTO),
        "elements": [_value_dto("defined")],
        "shape": [-1, 1],
    }
    decoded = ir_instruction_from_dto(dto)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                INT,
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(first, 1), decoded, IRConst(returned, 0), IRReturn(returned)],
                    )
                ],
            )
        ]
    )

    assert isinstance(decoded, IRMatrixNew)
    assert (decoded.rows, decoded.cols) == (-1, 1)
    with pytest.raises(IRVerificationError, match="dimensions must be positive"):
        IRVerifier(module).verify()


def test_unsupported_linear_algebra_subclass_is_rejected() -> None:
    class FutureVectorAdd(IRVectorAdd):
        pass

    with pytest.raises(
        TypeError,
        match=r"Unsupported IR instruction for schema v1: FutureVectorAdd",
    ):
        ir_instruction_to_dto(
            FutureVectorAdd(ROW_RESULT, ROW_VECTOR, OTHER_ROW_VECTOR, 4, "row")
        )


def test_control_flow_instruction_remains_outside_the_dto_boundary() -> None:
    condition = IRValue("condition", BoolType())

    with pytest.raises(TypeError, match=r"Unsupported IR instruction for schema v1: IRBranch"):
        ir_instruction_to_dto(IRBranch(condition, "then", "else"))


def _assert_neutral(value: object) -> None:
    if value is None or type(value) in {str, bool, int, float}:
        return
    if isinstance(value, Mapping):
        assert all(type(key) is str for key in value)
        for item in value.values():
            _assert_neutral(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _assert_neutral(item)
        return
    pytest.fail(f"non-neutral DTO value: {type(value).__name__}")
