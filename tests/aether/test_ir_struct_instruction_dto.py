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
    IRInstruction,
    IRMethodResultNew,
    IRMethodResultReceiver,
    IRMethodResultValue,
    IRStructGet,
    IRStructNew,
    IRStructSet,
    IRValue,
)
from aether.ir.types import (
    BoolType,
    IntType,
    MethodResultType,
    StringType,
    StructType,
    VoidType,
)


INNER_TYPE = StructType("Inner")
OUTER_TYPE = StructType("Outer")
INNER = IRValue("inner", INNER_TYPE)
COUNT = IRValue("count", IntType())
LABEL = IRValue("label", StringType())
OUTER = IRValue("outer", OUTER_TYPE)
UPDATED_OUTER = IRValue("updated_outer", OUTER_TYPE)
METHOD_RESULT_TYPE = MethodResultType(OUTER_TYPE, StringType())
METHOD_RESULT = IRValue("method_result", METHOD_RESULT_TYPE)


ROUND_TRIP_CASES: tuple[tuple[IRInstruction, dict[str, object]], ...] = (
    (
        IRStructNew(OUTER, (INNER, COUNT, LABEL)),
        {
            "kind": "struct_new",
            "result": {
                "tag": "value",
                "name": "outer",
                "type": {"tag": "struct", "name": "Outer"},
            },
            "fields": [
                {
                    "tag": "value",
                    "name": "inner",
                    "type": {"tag": "struct", "name": "Inner"},
                },
                {"tag": "value", "name": "count", "type": {"tag": "int"}},
                {"tag": "value", "name": "label", "type": {"tag": "string"}},
            ],
        },
    ),
    (
        IRStructGet(COUNT, OUTER, 1, "count"),
        {
            "kind": "struct_get",
            "result": {"tag": "value", "name": "count", "type": {"tag": "int"}},
            "struct": {
                "tag": "value",
                "name": "outer",
                "type": {"tag": "struct", "name": "Outer"},
            },
            "field_index": 1,
            "field_name": "count",
        },
    ),
    (
        IRStructSet(UPDATED_OUTER, OUTER, 0, "inner", INNER),
        {
            "kind": "struct_set",
            "result": {
                "tag": "value",
                "name": "updated_outer",
                "type": {"tag": "struct", "name": "Outer"},
            },
            "struct": {
                "tag": "value",
                "name": "outer",
                "type": {"tag": "struct", "name": "Outer"},
            },
            "field_index": 0,
            "field_name": "inner",
            "value": {
                "tag": "value",
                "name": "inner",
                "type": {"tag": "struct", "name": "Inner"},
            },
        },
    ),
    (
        IRMethodResultNew(METHOD_RESULT, OUTER, LABEL),
        {
            "kind": "method_result_new",
            "result": {
                "tag": "value",
                "name": "method_result",
                "type": {
                    "tag": "method_result",
                    "receiver": {"tag": "struct", "name": "Outer"},
                    "value": {"tag": "string"},
                },
            },
            "receiver": {
                "tag": "value",
                "name": "outer",
                "type": {"tag": "struct", "name": "Outer"},
            },
            "value": {"tag": "value", "name": "label", "type": {"tag": "string"}},
        },
    ),
    (
        IRMethodResultReceiver(OUTER, METHOD_RESULT),
        {
            "kind": "method_result_receiver",
            "result": {
                "tag": "value",
                "name": "outer",
                "type": {"tag": "struct", "name": "Outer"},
            },
            "method_result": {
                "tag": "value",
                "name": "method_result",
                "type": {
                    "tag": "method_result",
                    "receiver": {"tag": "struct", "name": "Outer"},
                    "value": {"tag": "string"},
                },
            },
        },
    ),
    (
        IRMethodResultValue(LABEL, METHOD_RESULT),
        {
            "kind": "method_result_value",
            "result": {"tag": "value", "name": "label", "type": {"tag": "string"}},
            "method_result": {
                "tag": "value",
                "name": "method_result",
                "type": {
                    "tag": "method_result",
                    "receiver": {"tag": "struct", "name": "Outer"},
                    "value": {"tag": "string"},
                },
            },
        },
    ),
)


@pytest.mark.parametrize(("instruction", "expected"), ROUND_TRIP_CASES)
def test_every_struct_and_method_result_variant_round_trips(
    instruction: IRInstruction,
    expected: dict[str, object],
) -> None:
    dto = ir_instruction_to_dto(instruction)

    assert dto == expected
    assert ir_instruction_from_dto(dto) == instruction
    assert type(ir_instruction_from_dto(dto)) is type(instruction)
    _assert_neutral(dto)


def test_empty_struct_construction_round_trips() -> None:
    instruction = IRStructNew(IRValue("empty", StructType("Empty")))

    dto = ir_instruction_to_dto(instruction)

    assert dto["fields"] == []
    assert ir_instruction_from_dto(dto) == instruction


def test_nested_struct_identity_and_field_order_are_preserved() -> None:
    fields = (
        IRValue("third", StructType("Third")),
        IRValue("first", StructType("First")),
        IRValue("second", StructType("Second")),
    )
    instruction = IRStructNew(IRValue("nested", StructType("Nested")), fields)

    dto = ir_instruction_to_dto(instruction)
    decoded = ir_instruction_from_dto(dto)

    assert [field["name"] for field in dto["fields"]] == ["third", "first", "second"]
    assert [field["type"]["name"] for field in dto["fields"]] == [
        "Third",
        "First",
        "Second",
    ]
    assert isinstance(decoded, IRStructNew)
    assert decoded.fields == fields


def test_void_method_result_preserves_absent_source_value() -> None:
    instruction = IRMethodResultNew(
        IRValue("method_result", MethodResultType(OUTER_TYPE, VoidType())),
        OUTER,
    )

    dto = ir_instruction_to_dto(instruction)

    assert "value" in dto
    assert dto["value"] is None
    assert ir_instruction_from_dto(dto) == instruction


def test_method_result_reconstruction_preserves_nested_contents() -> None:
    nested_receiver = IRValue("receiver", StructType("Container"))
    nested_value = IRValue("payload", StructType("Payload"))
    instruction = IRMethodResultNew(
        IRValue(
            "pair",
            MethodResultType(StructType("Container"), StructType("Payload")),
        ),
        nested_receiver,
        nested_value,
    )

    decoded = ir_instruction_from_dto(ir_instruction_to_dto(instruction))

    assert decoded == instruction
    assert isinstance(decoded, IRMethodResultNew)
    assert decoded.result.type == MethodResultType(
        StructType("Container"),
        StructType("Payload"),
    )
    assert decoded.receiver == nested_receiver
    assert decoded.value == nested_value


def test_struct_and_method_result_encoding_is_deterministic() -> None:
    for instruction, _ in ROUND_TRIP_CASES:
        first = ir_instruction_to_dto(instruction)
        second = ir_instruction_to_dto(instruction)

        assert first == second
        assert json.dumps(first, separators=(",", ":")) == json.dumps(
            second,
            separators=(",", ":"),
        )


def _value_dto(
    name: str = "value",
    type_dto: object | None = None,
) -> dict[str, object]:
    return {
        "tag": "value",
        "name": name,
        "type": {"tag": "int"} if type_dto is None else type_dto,
    }


def _struct_get_dto() -> dict[str, object]:
    return {
        "kind": "struct_get",
        "result": _value_dto("result"),
        "struct": _value_dto("struct", {"tag": "struct", "name": "Record"}),
        "field_index": 0,
        "field_name": "field",
    }


@pytest.mark.parametrize(
    ("dto", "message"),
    [
        ({"kind": "struct_new", "result": _value_dto("result")}, "missing fields: fields"),
        ({**_struct_get_dto(), "extra": None}, "unexpected fields: extra"),
        (
            {"kind": "struct_new", "result": _value_dto("result"), "fields": "value"},
            "fields must be a sequence",
        ),
        (
            {"kind": "struct_new", "result": _value_dto("result"), "fields": [7]},
            "IR value DTO must be a mapping",
        ),
        (
            {
                "kind": "struct_new",
                "result": _value_dto("result"),
                "fields": [{"tag": "value", "name": "nested"}],
            },
            "missing fields: type",
        ),
        (
            {
                "kind": "struct_new",
                "result": _value_dto("result"),
                "fields": [
                    _value_dto("nested", {"tag": "struct"}),
                ],
            },
            "missing fields: name",
        ),
        ({**_struct_get_dto(), "field_index": True}, "signed 64-bit integer"),
        ({**_struct_get_dto(), "field_index": 2**63}, "signed 64-bit integer"),
        ({**_struct_get_dto(), "field_name": 0}, "field_name must be a string"),
        (
            {
                "kind": "struct_set",
                "result": _value_dto("updated"),
                "struct": _value_dto("struct"),
                "field_index": 0,
                "field_name": "field",
                "value": {"tag": "value", "name": "replacement", "type": []},
            },
            "IR type DTO must be a mapping",
        ),
        (
            {
                "kind": "method_result_new",
                "result": _value_dto("pair"),
                "receiver": _value_dto("receiver"),
            },
            "missing fields: value",
        ),
        (
            {
                "kind": "method_result_new",
                "result": _value_dto("pair"),
                "receiver": _value_dto("receiver"),
                "value": False,
            },
            "IR value DTO must be a mapping",
        ),
        (
            {
                "kind": "method_result_receiver",
                "result": _value_dto("receiver"),
                "method_result": _value_dto(
                    "pair",
                    {
                        "tag": "method_result",
                        "receiver": {"tag": "struct", "name": "Record"},
                    },
                ),
            },
            "missing fields: value",
        ),
        (
            {
                "kind": "method_result_value",
                "result": _value_dto("result"),
                "method_result": None,
            },
            "IR value DTO must be a mapping",
        ),
    ],
)
def test_malformed_struct_and_method_result_dtos_are_rejected(
    dto: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_instruction_from_dto(dto)


def test_decoder_leaves_struct_semantics_to_the_verifier() -> None:
    dto = {
        **_struct_get_dto(),
        "result": _value_dto("result", {"tag": "bool"}),
        "field_index": -9,
        "field_name": "",
    }

    assert ir_instruction_from_dto(dto) == IRStructGet(
        IRValue("result", BoolType()),
        IRValue("struct", StructType("Record")),
        -9,
        "",
    )


@pytest.mark.parametrize(
    ("instruction", "message"),
    [
        (IRStructGet(COUNT, OUTER, True, "count"), "signed 64-bit integer"),
        (IRStructGet(COUNT, OUTER, 1, False), "field_name must be a string"),
        (
            IRStructSet(UPDATED_OUTER, OUTER, 2**63, "count", COUNT),
            "signed 64-bit integer",
        ),
    ],
)
def test_encoder_rejects_invalid_python_primitive_fields(
    instruction: IRInstruction,
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_instruction_to_dto(instruction)


@pytest.mark.parametrize("instruction", [case[0] for case in ROUND_TRIP_CASES])
def test_struct_variants_reject_incompatible_schema_versions(
    instruction: IRInstruction,
) -> None:
    dto = ir_instruction_to_dto(instruction)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_instruction_to_dto(instruction, schema_version=2)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_instruction_from_dto(dto, schema_version=2)


def test_unsupported_instruction_classes_are_rejected() -> None:
    class FutureStructNew(IRStructNew):
        pass

    with pytest.raises(
        TypeError,
        match=r"Unsupported IR instruction for schema v1: FutureStructNew",
    ):
        ir_instruction_to_dto(FutureStructNew(OUTER))

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
