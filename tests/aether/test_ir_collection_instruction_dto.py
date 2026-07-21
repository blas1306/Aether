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
    IRArrayCopy,
    IRArrayGet,
    IRArrayLength,
    IRArrayNew,
    IRArraySet,
    IRArraySlice,
    IRInstruction,
    IRListClear,
    IRListContains,
    IRListCopy,
    IRListGet,
    IRListIndexOf,
    IRListInsert,
    IRListIsEmpty,
    IRListLength,
    IRListNew,
    IRListPop,
    IRListPush,
    IRListRemoveAt,
    IRListReverse,
    IRListSet,
    IRListSlice,
    IRSequenceSort,
    IRSourceLocation,
    IRValue,
    IRVectorNew,
)
from aether.ir.types import ArrayType, BoolType, IntType, ListType, VectorType


INT = IntType()
BOOL = BoolType()
ARRAY_TYPE = ArrayType(INT)
LIST_TYPE = ListType(INT)
RESULT = IRValue("result", INT)
BOOL_RESULT = IRValue("matches", BOOL)
INDEX = IRValue("index", INT)
START = IRValue("start", INT)
END = IRValue("end", INT)
VALUE = IRValue("value", INT)
OTHER = IRValue("other", INT)
ARRAY = IRValue("array", ARRAY_TYPE)
ARRAY_COPY = IRValue("array_copy", ARRAY_TYPE)
LIST = IRValue("list", LIST_TYPE)
LIST_COPY = IRValue("list_copy", LIST_TYPE)
LOCATION = IRSourceLocation(12, 34, "collections.ae")


def _type_dto(tag: str, element: object | None = None) -> dict[str, object]:
    dto: dict[str, object] = {"tag": tag}
    if element is not None:
        dto["element"] = element
    return dto


INT_DTO = _type_dto("int")
BOOL_DTO = _type_dto("bool")
ARRAY_TYPE_DTO = _type_dto("array", INT_DTO)
LIST_TYPE_DTO = _type_dto("list", INT_DTO)


def _value_dto(name: str, type_dto: object = INT_DTO) -> dict[str, object]:
    return {"tag": "value", "name": name, "type": type_dto}


def _location_dto() -> dict[str, object]:
    return {
        "tag": "source_location",
        "line": 12,
        "column": 34,
        "path": "collections.ae",
    }


ROUND_TRIP_CASES: tuple[tuple[IRInstruction, dict[str, object]], ...] = (
    (
        IRArrayNew(ARRAY, (VALUE, OTHER)),
        {
            "kind": "array_new",
            "result": _value_dto("array", ARRAY_TYPE_DTO),
            "elements": [_value_dto("value"), _value_dto("other")],
        },
    ),
    (
        IRListNew(LIST, (OTHER, VALUE)),
        {
            "kind": "list_new",
            "result": _value_dto("list", LIST_TYPE_DTO),
            "elements": [_value_dto("other"), _value_dto("value")],
        },
    ),
    (
        IRArrayCopy(ARRAY_COPY, ARRAY, LOCATION),
        {
            "kind": "array_copy",
            "result": _value_dto("array_copy", ARRAY_TYPE_DTO),
            "array": _value_dto("array", ARRAY_TYPE_DTO),
            "source_location": _location_dto(),
        },
    ),
    (
        IRListCopy(LIST_COPY, LIST, LOCATION),
        {
            "kind": "list_copy",
            "result": _value_dto("list_copy", LIST_TYPE_DTO),
            "list_value": _value_dto("list", LIST_TYPE_DTO),
            "source_location": _location_dto(),
        },
    ),
    (
        IRListContains(BOOL_RESULT, LIST, VALUE),
        {
            "kind": "list_contains",
            "result": _value_dto("matches", BOOL_DTO),
            "list_value": _value_dto("list", LIST_TYPE_DTO),
            "value": _value_dto("value"),
        },
    ),
    (
        IRListIndexOf(RESULT, LIST, VALUE),
        {
            "kind": "list_index_of",
            "result": _value_dto("result"),
            "list_value": _value_dto("list", LIST_TYPE_DTO),
            "value": _value_dto("value"),
        },
    ),
    (
        IRListClear(LIST),
        {
            "kind": "list_clear",
            "list_value": _value_dto("list", LIST_TYPE_DTO),
        },
    ),
    (
        IRListPush(LIST, VALUE),
        {
            "kind": "list_push",
            "list_value": _value_dto("list", LIST_TYPE_DTO),
            "value": _value_dto("value"),
        },
    ),
    (
        IRListInsert(LIST, INDEX, VALUE),
        {
            "kind": "list_insert",
            "list_value": _value_dto("list", LIST_TYPE_DTO),
            "index": _value_dto("index"),
            "value": _value_dto("value"),
        },
    ),
    (
        IRListRemoveAt(RESULT, LIST, INDEX),
        {
            "kind": "list_remove_at",
            "result": _value_dto("result"),
            "list_value": _value_dto("list", LIST_TYPE_DTO),
            "index": _value_dto("index"),
        },
    ),
    (
        IRListPop(RESULT, LIST),
        {
            "kind": "list_pop",
            "result": _value_dto("result"),
            "list_value": _value_dto("list", LIST_TYPE_DTO),
        },
    ),
    (
        IRListReverse(LIST),
        {
            "kind": "list_reverse",
            "list_value": _value_dto("list", LIST_TYPE_DTO),
        },
    ),
    (
        IRSequenceSort(ARRAY),
        {
            "kind": "sequence_sort",
            "sequence": _value_dto("array", ARRAY_TYPE_DTO),
        },
    ),
    (
        IRArrayGet(RESULT, ARRAY, INDEX, True, "loop", LOCATION),
        {
            "kind": "array_get",
            "result": _value_dto("result"),
            "array": _value_dto("array", ARRAY_TYPE_DTO),
            "index": _value_dto("index"),
            "borrowed": True,
            "borrow_scope": "loop",
            "source_location": _location_dto(),
        },
    ),
    (
        IRArraySlice(ARRAY_COPY, ARRAY, START, END, LOCATION),
        {
            "kind": "array_slice",
            "result": _value_dto("array_copy", ARRAY_TYPE_DTO),
            "array": _value_dto("array", ARRAY_TYPE_DTO),
            "start": _value_dto("start"),
            "end": _value_dto("end"),
            "source_location": _location_dto(),
        },
    ),
    (
        IRListSlice(LIST_COPY, LIST, START, END, LOCATION),
        {
            "kind": "list_slice",
            "result": _value_dto("list_copy", LIST_TYPE_DTO),
            "list_value": _value_dto("list", LIST_TYPE_DTO),
            "start": _value_dto("start"),
            "end": _value_dto("end"),
            "source_location": _location_dto(),
        },
    ),
    (
        IRListGet(RESULT, LIST, INDEX, True, "iteration", LOCATION),
        {
            "kind": "list_get",
            "result": _value_dto("result"),
            "list_value": _value_dto("list", LIST_TYPE_DTO),
            "index": _value_dto("index"),
            "borrowed": True,
            "borrow_scope": "iteration",
            "source_location": _location_dto(),
        },
    ),
    (
        IRArraySet(ARRAY, INDEX, VALUE),
        {
            "kind": "array_set",
            "array": _value_dto("array", ARRAY_TYPE_DTO),
            "index": _value_dto("index"),
            "value": _value_dto("value"),
        },
    ),
    (
        IRListSet(LIST, INDEX, VALUE),
        {
            "kind": "list_set",
            "list_value": _value_dto("list", LIST_TYPE_DTO),
            "index": _value_dto("index"),
            "value": _value_dto("value"),
        },
    ),
    (
        IRArrayLength(RESULT, ARRAY),
        {
            "kind": "array_length",
            "result": _value_dto("result"),
            "array": _value_dto("array", ARRAY_TYPE_DTO),
        },
    ),
    (
        IRListLength(RESULT, LIST),
        {
            "kind": "list_length",
            "result": _value_dto("result"),
            "list_value": _value_dto("list", LIST_TYPE_DTO),
        },
    ),
    (
        IRListIsEmpty(BOOL_RESULT, LIST),
        {
            "kind": "list_is_empty",
            "result": _value_dto("matches", BOOL_DTO),
            "list_value": _value_dto("list", LIST_TYPE_DTO),
        },
    ),
)


@pytest.mark.parametrize(("instruction", "expected"), ROUND_TRIP_CASES)
def test_every_collection_instruction_variant_round_trips(
    instruction: IRInstruction,
    expected: dict[str, object],
) -> None:
    dto = ir_instruction_to_dto(instruction)

    assert dto == expected
    decoded = ir_instruction_from_dto(dto)
    assert decoded == instruction
    assert type(decoded) is type(instruction)
    _assert_neutral(dto)


@pytest.mark.parametrize(
    "instruction",
    [IRArrayNew(ARRAY), IRListNew(LIST)],
)
def test_empty_collection_construction_round_trips(instruction: IRInstruction) -> None:
    dto = ir_instruction_to_dto(instruction)

    assert dto["elements"] == []
    assert ir_instruction_from_dto(dto) == instruction


def test_nested_collection_types_and_element_order_are_preserved() -> None:
    inner_type = ListType(INT)
    nested_type = ArrayType(inner_type)
    third = IRValue("third", inner_type)
    first = IRValue("first", inner_type)
    instruction = IRArrayNew(IRValue("nested", nested_type), (third, first))

    dto = ir_instruction_to_dto(instruction)
    decoded = ir_instruction_from_dto(dto)

    assert dto["result"]["type"] == {
        "tag": "array",
        "element": {"tag": "list", "element": {"tag": "int"}},
    }
    assert [element["name"] for element in dto["elements"]] == ["third", "first"]
    assert decoded == instruction


@pytest.mark.parametrize(
    "instruction",
    [
        IRListInsert(LIST, IRValue("negative_index", INT), VALUE),
        IRListRemoveAt(RESULT, LIST, IRValue("large_index", INT)),
        IRArrayGet(RESULT, ARRAY, IRValue("array_index", INT)),
        IRListGet(RESULT, LIST, IRValue("list_index", INT)),
        IRArraySet(ARRAY, IRValue("set_array_index", INT), VALUE),
        IRListSet(LIST, IRValue("set_list_index", INT), VALUE),
    ],
)
def test_index_values_are_preserved(instruction: IRInstruction) -> None:
    decoded = ir_instruction_from_dto(ir_instruction_to_dto(instruction))

    assert decoded == instruction
    assert decoded.index == instruction.index


@pytest.mark.parametrize(
    "instruction",
    [
        IRArraySlice(ARRAY_COPY, ARRAY, START, END),
        IRListSlice(LIST_COPY, LIST, END, START),
    ],
)
def test_slice_bounds_and_absent_location_are_preserved(
    instruction: IRInstruction,
) -> None:
    dto = ir_instruction_to_dto(instruction)
    decoded = ir_instruction_from_dto(dto)

    assert dto["source_location"] is None
    assert decoded == instruction
    assert decoded.start == instruction.start
    assert decoded.end == instruction.end


@pytest.mark.parametrize(
    "instruction",
    [
        IRArrayGet(RESULT, ARRAY, INDEX),
        IRListGet(RESULT, LIST, INDEX),
        IRArrayCopy(ARRAY_COPY, ARRAY),
        IRListCopy(LIST_COPY, LIST),
    ],
)
def test_optional_collection_fields_preserve_explicit_absence(
    instruction: IRInstruction,
) -> None:
    dto = ir_instruction_to_dto(instruction)

    assert dto["source_location"] is None
    if "borrow_scope" in dto:
        assert dto["borrow_scope"] is None
        assert dto["borrowed"] is False
    assert ir_instruction_from_dto(dto) == instruction


def test_collection_encoding_is_deterministic() -> None:
    for instruction, _ in ROUND_TRIP_CASES:
        first = ir_instruction_to_dto(instruction)
        second = ir_instruction_to_dto(instruction)

        assert first == second
        assert json.dumps(first, separators=(",", ":")) == json.dumps(
            second,
            separators=(",", ":"),
        )


@pytest.mark.parametrize(
    ("dto", "message"),
    [
        (
            {"kind": "array_new", "result": _value_dto("array", ARRAY_TYPE_DTO)},
            "missing fields: elements",
        ),
        (
            {
                "kind": "array_new",
                "result": _value_dto("array", ARRAY_TYPE_DTO),
                "elements": [],
                "capacity": 0,
            },
            "unexpected fields: capacity",
        ),
        (
            {
                "kind": "list_new",
                "result": _value_dto("list", LIST_TYPE_DTO),
                "elements": "value",
            },
            "elements must be a sequence",
        ),
        (
            {
                "kind": "array_new",
                "result": _value_dto("array", ARRAY_TYPE_DTO),
                "elements": [False],
            },
            "IR value DTO must be a mapping",
        ),
        (
            {
                "kind": "list_new",
                "result": _value_dto("list", LIST_TYPE_DTO),
                "elements": [{"tag": "value", "name": "nested"}],
            },
            "missing fields: type",
        ),
        (
            {
                "kind": "array_get",
                "result": _value_dto("result"),
                "array": _value_dto("array", ARRAY_TYPE_DTO),
                "index": _value_dto("index"),
                "borrowed": 1,
                "borrow_scope": None,
                "source_location": None,
            },
            "borrowed must be a boolean",
        ),
        (
            {
                "kind": "list_get",
                "result": _value_dto("result"),
                "list_value": _value_dto("list", LIST_TYPE_DTO),
                "index": _value_dto("index"),
                "borrowed": False,
                "borrow_scope": 7,
                "source_location": None,
            },
            "borrow_scope must be a string",
        ),
        (
            {
                "kind": "array_slice",
                "result": _value_dto("array_copy", ARRAY_TYPE_DTO),
                "array": _value_dto("array", ARRAY_TYPE_DTO),
                "start": _value_dto("start"),
                "end": {"tag": "value", "name": "end", "type": []},
                "source_location": None,
            },
            "IR type DTO must be a mapping",
        ),
        (
            {
                "kind": "list_copy",
                "result": _value_dto("list_copy", LIST_TYPE_DTO),
                "list_value": _value_dto("list", LIST_TYPE_DTO),
                "source_location": {"tag": "source_location", "line": 1, "column": 2},
            },
            "missing fields: path",
        ),
    ],
)
def test_malformed_collection_dtos_are_rejected(
    dto: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_instruction_from_dto(dto)


def test_decoder_leaves_collection_semantics_to_the_verifier() -> None:
    dto = {
        "kind": "array_get",
        "result": _value_dto("result", BOOL_DTO),
        "array": _value_dto("not_an_array"),
        "index": _value_dto("not_an_index", BOOL_DTO),
        "borrowed": False,
        "borrow_scope": "scope_without_borrow",
        "source_location": None,
    }

    assert ir_instruction_from_dto(dto) == IRArrayGet(
        IRValue("result", BOOL),
        IRValue("not_an_array", INT),
        IRValue("not_an_index", BOOL),
        False,
        "scope_without_borrow",
    )


def test_collection_encoder_rejects_invalid_python_primitive_fields() -> None:
    instruction = IRArrayGet(RESULT, ARRAY, INDEX, 1, None, None)

    with pytest.raises(IRDTOError, match="borrowed must be a boolean"):
        ir_instruction_to_dto(instruction)


def test_unsupported_collection_instruction_subclass_is_rejected() -> None:
    class FutureListResize(IRListNew):
        pass

    with pytest.raises(
        TypeError,
        match=r"Unsupported IR instruction for schema v1: FutureListResize",
    ):
        ir_instruction_to_dto(FutureListResize(LIST))


def test_out_of_scope_vector_instruction_remains_unsupported() -> None:
    vector = IRValue("vector", VectorType(INT))

    with pytest.raises(TypeError, match=r"Unsupported IR instruction for schema v1: IRVectorNew"):
        ir_instruction_to_dto(IRVectorNew(vector))


@pytest.mark.parametrize("instruction", [case[0] for case in ROUND_TRIP_CASES])
def test_collection_variants_reject_incompatible_schema_versions(
    instruction: IRInstruction,
) -> None:
    dto = ir_instruction_to_dto(instruction)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_instruction_to_dto(instruction, schema_version=2)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_instruction_from_dto(dto, schema_version=2)


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
