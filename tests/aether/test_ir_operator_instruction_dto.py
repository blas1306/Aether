from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

import pytest

from aether.ir.dto import IRDTOError, ir_instruction_from_dto, ir_instruction_to_dto
from aether.ir.model import (
    IRBinaryOp,
    IRCast,
    IRCompareOp,
    IRInstruction,
    IRSourceLocation,
    IRUnaryOp,
    IRValue,
)
from aether.ir.types import BoolType, DoubleType, IntType, VectorType


LOCATION = IRSourceLocation(23, 17, "src/operators.ae")
INT_RESULT = IRValue("result", IntType())
LEFT = IRValue("left", IntType())
RIGHT = IRValue("right", IntType())
BOOL_RESULT = IRValue("condition", BoolType())
VECTOR_LEFT = IRValue("vector_left", VectorType(DoubleType(), "column"))
VECTOR_RIGHT = IRValue("vector_right", VectorType(DoubleType(), "column"))


ROUND_TRIP_CASES: tuple[tuple[IRInstruction, dict[str, object]], ...] = (
    (
        IRBinaryOp(INT_RESULT, "add", LEFT, RIGHT, LOCATION),
        {
            "kind": "binary_op",
            "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
            "operator": "add",
            "left": {"tag": "value", "name": "left", "type": {"tag": "int"}},
            "right": {"tag": "value", "name": "right", "type": {"tag": "int"}},
            "source_location": {
                "tag": "source_location",
                "line": 23,
                "column": 17,
                "path": "src/operators.ae",
            },
        },
    ),
    (
        IRUnaryOp(INT_RESULT, "neg", LEFT),
        {
            "kind": "unary_op",
            "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
            "operator": "neg",
            "operand": {"tag": "value", "name": "left", "type": {"tag": "int"}},
        },
    ),
    (
        IRCompareOp(BOOL_RESULT, "eq", VECTOR_LEFT, VECTOR_RIGHT, (3,)),
        {
            "kind": "compare_op",
            "result": {"tag": "value", "name": "condition", "type": {"tag": "bool"}},
            "operator": "eq",
            "left": {
                "tag": "value",
                "name": "vector_left",
                "type": {
                    "tag": "vector",
                    "element": {"tag": "double"},
                    "orientation": "column",
                },
            },
            "right": {
                "tag": "value",
                "name": "vector_right",
                "type": {
                    "tag": "vector",
                    "element": {"tag": "double"},
                    "orientation": "column",
                },
            },
            "aggregate_shape": [3],
        },
    ),
    (
        IRCast(IRValue("double_result", DoubleType()), LEFT),
        {
            "kind": "cast",
            "result": {
                "tag": "value",
                "name": "double_result",
                "type": {"tag": "double"},
            },
            "value": {"tag": "value", "name": "left", "type": {"tag": "int"}},
        },
    ),
)


@pytest.mark.parametrize(("instruction", "expected"), ROUND_TRIP_CASES)
def test_every_operator_instruction_round_trips(
    instruction: IRInstruction,
    expected: dict[str, object],
) -> None:
    dto = ir_instruction_to_dto(instruction)

    assert dto == expected
    assert ir_instruction_from_dto(dto) == instruction
    assert type(ir_instruction_from_dto(dto)) is type(instruction)
    _assert_neutral(dto)


@pytest.mark.parametrize(
    "operator",
    [
        "add",
        "sub",
        "mul",
        "div",
        "rem",
        "mod",
        "pow",
        "eq",
        "ne",
        "lt",
        "le",
        "gt",
        "ge",
        "and",
        "or",
    ],
)
def test_binary_operator_tags_round_trip_verbatim(operator: str) -> None:
    instruction = IRBinaryOp(INT_RESULT, operator, LEFT, RIGHT)
    assert ir_instruction_from_dto(ir_instruction_to_dto(instruction)) == instruction


@pytest.mark.parametrize("operator", ["neg", "not"])
def test_unary_operator_tags_round_trip_verbatim(operator: str) -> None:
    instruction = IRUnaryOp(INT_RESULT, operator, LEFT)
    assert ir_instruction_from_dto(ir_instruction_to_dto(instruction)) == instruction


@pytest.mark.parametrize("operator", ["eq", "ne", "lt", "le", "gt", "ge"])
def test_compare_operator_tags_round_trip_verbatim(operator: str) -> None:
    instruction = IRCompareOp(BOOL_RESULT, operator, LEFT, RIGHT)
    assert ir_instruction_from_dto(ir_instruction_to_dto(instruction)) == instruction


@pytest.mark.parametrize(
    "instruction",
    [
        IRBinaryOp(INT_RESULT, "future_binary", LEFT, RIGHT),
        IRUnaryOp(INT_RESULT, "future_unary", LEFT),
        IRCompareOp(BOOL_RESULT, "future_compare", LEFT, RIGHT),
    ],
)
def test_conversion_preserves_unknown_operator_for_verifier(instruction: IRInstruction) -> None:
    dto = ir_instruction_to_dto(instruction)

    assert ir_instruction_from_dto(dto) == instruction


def test_binary_operator_preserves_explicit_absent_location() -> None:
    instruction = replace(ROUND_TRIP_CASES[0][0], source_location=None)

    dto = ir_instruction_to_dto(instruction)

    assert dto["source_location"] is None
    assert ir_instruction_from_dto(dto) == instruction


@pytest.mark.parametrize(
    "shape",
    [None, (), (1,), (2, 3), (0,), (-1,), (-(2**63), 2**63 - 1)],
)
def test_compare_shape_round_trips_without_semantic_validation(
    shape: tuple[int, ...] | None,
) -> None:
    instruction = IRCompareOp(BOOL_RESULT, "eq", LEFT, RIGHT, shape)

    dto = ir_instruction_to_dto(instruction)

    assert dto["aggregate_shape"] == (None if shape is None else list(shape))
    assert ir_instruction_from_dto(dto) == instruction


def _value_dto(name: str) -> dict[str, object]:
    return {"tag": "value", "name": name, "type": {"tag": "int"}}


@pytest.mark.parametrize(
    ("dto", "message"),
    [
        (
            {
                "kind": "binary_op",
                "result": _value_dto("result"),
                "operator": "add",
                "left": _value_dto("left"),
                "right": _value_dto("right"),
            },
            "missing fields: source_location",
        ),
        (
            {
                "kind": "unary_op",
                "result": _value_dto("result"),
                "operator": "not",
                "operand": _value_dto("operand"),
                "extra": None,
            },
            "unexpected fields: extra",
        ),
        (
            {
                "kind": "binary_op",
                "result": _value_dto("result"),
                "operator": 1,
                "left": _value_dto("left"),
                "right": _value_dto("right"),
                "source_location": None,
            },
            "operator must be a string",
        ),
        (
            {
                "kind": "compare_op",
                "result": _value_dto("result"),
                "operator": "eq",
                "left": _value_dto("left"),
                "right": _value_dto("right"),
                "aggregate_shape": "2,3",
            },
            "aggregate_shape must be a sequence",
        ),
        (
            {
                "kind": "compare_op",
                "result": _value_dto("result"),
                "operator": "eq",
                "left": _value_dto("left"),
                "right": _value_dto("right"),
                "aggregate_shape": [2, True],
            },
            "aggregate_shape\\[1\\] must be a signed 64-bit integer",
        ),
        (
            {
                "kind": "cast",
                "result": _value_dto("result"),
                "value": 7,
            },
            "IR value DTO must be a mapping",
        ),
    ],
)
def test_malformed_operator_instruction_dtos_are_rejected(
    dto: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_instruction_from_dto(dto)


@pytest.mark.parametrize(
    "instruction",
    [
        IRBinaryOp(INT_RESULT, 1, LEFT, RIGHT),  # type: ignore[arg-type]
        IRUnaryOp(INT_RESULT, True, LEFT),  # type: ignore[arg-type]
        IRCompareOp(BOOL_RESULT, None, LEFT, RIGHT),  # type: ignore[arg-type]
    ],
)
def test_operator_encoders_reject_non_string_tags(instruction: IRInstruction) -> None:
    with pytest.raises(IRDTOError, match=r"operator must be a string"):
        ir_instruction_to_dto(instruction)


def test_compare_encoder_rejects_out_of_range_shape_values() -> None:
    instruction = IRCompareOp(BOOL_RESULT, "eq", LEFT, RIGHT, (2**63,))

    with pytest.raises(
        IRDTOError,
        match=r"aggregate_shape\[0\] must be a signed 64-bit integer",
    ):
        ir_instruction_to_dto(instruction)


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
