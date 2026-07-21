from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest

from aether.ir.dto import (
    IRDTOError,
    IRDTOSchemaVersionError,
    ir_constant_from_dto,
    ir_constant_to_dto,
    ir_enum_constant_from_dto,
    ir_enum_constant_to_dto,
    ir_parameter_from_dto,
    ir_parameter_to_dto,
    ir_source_location_from_dto,
    ir_source_location_to_dto,
    ir_storage_from_dto,
    ir_storage_to_dto,
    ir_value_from_dto,
    ir_value_to_dto,
)
from aether.ir.model import IREnumConstant, IRParameter, IRSourceLocation, IRStorage, IRValue
from aether.ir.types import EnumType, FunctionType, IntType, ListType, StringType


ENUM_CONSTANT = IREnumConstant("Color", "GREEN", 1, 1)


@pytest.mark.parametrize(
    ("constant", "expected"),
    [
        (False, {"tag": "bool", "value": False}),
        (42, {"tag": "int", "value": 42}),
        (-3.5, {"tag": "float", "value": -3.5}),
        (complex(1.25, -2.5), {"tag": "complex", "real": 1.25, "imaginary": -2.5}),
        ("aether", {"tag": "string", "value": "aether"}),
        (
            ENUM_CONSTANT,
            {
                "tag": "enum",
                "value": {
                    "tag": "enum_constant",
                    "enum_name": "Color",
                    "member_name": "GREEN",
                    "member_id": 1,
                    "discriminant": 1,
                },
            },
        ),
    ],
)
def test_every_ir_constant_variant_round_trips(
    constant: bool | int | float | complex | str | IREnumConstant,
    expected: dict[str, object],
) -> None:
    dto = ir_constant_to_dto(constant)

    assert dto == expected
    assert ir_constant_from_dto(dto) == constant
    _assert_neutral(dto)


def test_enum_constant_round_trips_independently() -> None:
    dto = ir_enum_constant_to_dto(ENUM_CONSTANT)

    assert dto == {
        "tag": "enum_constant",
        "enum_name": "Color",
        "member_name": "GREEN",
        "member_id": 1,
        "discriminant": 1,
    }
    assert ir_enum_constant_from_dto(dto) == ENUM_CONSTANT


@pytest.mark.parametrize(
    ("value", "tag"),
    [
        (IRValue("temporary", ListType(StringType())), "value"),
        (IRStorage("slot", FunctionType((IntType(),), StringType())), "storage"),
        (IRParameter("color", EnumType("Color", ("RED", "GREEN"), None)), "parameter"),
    ],
)
def test_every_named_value_kind_round_trips_with_nested_types(value: IRValue, tag: str) -> None:
    dto = ir_value_to_dto(value)

    assert dto["tag"] == tag
    assert ir_value_from_dto(dto) == value
    assert type(ir_value_from_dto(dto)) is type(value)
    _assert_neutral(dto)


def test_storage_and_parameter_specific_converters_round_trip() -> None:
    storage = IRStorage("items", ListType(StringType()))
    parameter = IRParameter("callback", FunctionType((IntType(),), StringType()))

    assert ir_storage_from_dto(ir_storage_to_dto(storage)) == storage
    assert ir_parameter_from_dto(ir_parameter_to_dto(parameter)) == parameter


def test_source_location_round_trip_preserves_path_and_explicit_absence() -> None:
    location = IRSourceLocation(12, 7, "src/main.ae")

    assert ir_source_location_to_dto(location) == {
        "tag": "source_location",
        "line": 12,
        "column": 7,
        "path": "src/main.ae",
    }
    assert ir_source_location_from_dto(ir_source_location_to_dto(location)) == location
    assert ir_source_location_to_dto(None) is None
    assert ir_source_location_from_dto(None) is None


def test_source_location_round_trip_preserves_absent_path() -> None:
    location = IRSourceLocation(1, 2)

    assert ir_source_location_to_dto(location)["path"] is None  # type: ignore[index]
    assert ir_source_location_from_dto(ir_source_location_to_dto(location)) == location


@pytest.mark.parametrize(
    ("converter", "dto", "message"),
    [
        (ir_constant_from_dto, {"tag": "int", "value": True}, "signed 32-bit integer"),
        (ir_constant_from_dto, {"tag": "float", "value": 1}, "floating-point value"),
        (ir_constant_from_dto, {"tag": "string"}, "missing fields: value"),
        (
            ir_enum_constant_from_dto,
            {
                "tag": "enum_constant",
                "enum_name": "Color",
                "member_name": "RED",
                "member_id": 0,
                "discriminant": 0,
                "extra": None,
            },
            "unexpected fields: extra",
        ),
        (ir_value_from_dto, {"tag": "value", "name": 1, "type": {"tag": "int"}}, "name must be a string"),
        (ir_storage_from_dto, {"tag": "value", "name": "x", "type": {"tag": "int"}}, "requires tag 'storage'"),
        (
            ir_source_location_from_dto,
            {"tag": "source_location", "line": True, "column": 1, "path": None},
            "signed 64-bit integer",
        ),
        (
            ir_source_location_from_dto,
            {"tag": "source_location", "line": 1, "column": 1},
            "missing fields: path",
        ),
    ],
)
def test_malformed_dtos_raise_clear_dto_errors(converter: object, dto: dict[str, object], message: str) -> None:
    with pytest.raises(IRDTOError, match=message):
        converter(dto)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("converter", "dto", "entity"),
    [
        (ir_constant_from_dto, {"tag": "future"}, "IR constant"),
        (ir_enum_constant_from_dto, {"tag": "future"}, "IR enum constant"),
        (ir_value_from_dto, {"tag": "future"}, "IR value"),
        (ir_source_location_from_dto, {"tag": "future"}, "IR source location"),
    ],
)
def test_unknown_tags_are_rejected(converter: object, dto: dict[str, object], entity: str) -> None:
    with pytest.raises(IRDTOError, match=rf"Unknown {entity} DTO tag: 'future'"):
        converter(dto)  # type: ignore[operator]


def test_unsupported_constant_values_are_rejected() -> None:
    with pytest.raises(TypeError, match=r"Unsupported IR constant for schema v1: NoneType"):
        ir_constant_to_dto(None)  # type: ignore[arg-type]

    with pytest.raises(IRDTOError, match=r"signed 32-bit integer"):
        ir_constant_to_dto(2**31)


def test_output_is_deterministic() -> None:
    value = IRParameter("color", EnumType("Color", ("RED", "GREEN"), "DisplayColor"))
    first = ir_value_to_dto(value)
    second = ir_value_to_dto(value)

    assert first == second
    assert json.dumps(first, separators=(",", ":")) == json.dumps(second, separators=(",", ":"))


@pytest.mark.parametrize(
    ("converter", "argument"),
    [
        (ir_constant_to_dto, 1),
        (ir_constant_from_dto, {"tag": "int", "value": 1}),
        (ir_value_to_dto, IRValue("x", IntType())),
        (ir_value_from_dto, {"tag": "value", "name": "x", "type": {"tag": "int"}}),
        (ir_source_location_to_dto, None),
        (ir_source_location_from_dto, None),
    ],
)
def test_converters_reject_incompatible_schema_versions(converter: object, argument: object) -> None:
    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        converter(argument, schema_version=2)  # type: ignore[operator]


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
