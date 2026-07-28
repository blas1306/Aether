from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace

import pytest

from aether.ir.dto import (
    IR_INSTRUCTION_TAGS,
    IRDTOError,
    IRDTOSchemaVersionError,
    ir_instruction_from_dto,
    ir_instruction_to_dto,
)
from aether.ir.model import (
    IRAssign,
    IRArrayCopy,
    IRArrayGet,
    IRArrayLength,
    IRArrayNew,
    IRArraySet,
    IRArraySlice,
    IRBinaryOp,
    IRBranch,
    IRCall,
    IRCallIndirect,
    IRClassNew,
    IRClassGet,
    IRClassSet,
    IRCast,
    IRCompareOp,
    IRConst,
    IRCopyInit,
    IRDestroy,
    IREnumConstant,
    IRFunctionRef,
    IRInterfaceCall,
    IRInterfaceConstruct,
    IRInitDefault,
    IRInstruction,
    IRJump,
    IRLoad,
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
    IRMethodResultNew,
    IRMethodResultReceiver,
    IRMethodResultValue,
    IRMoveInit,
    IROuterProduct,
    IRPrint,
    IRRelocate,
    IRReturn,
    IRSequenceSort,
    IRSourceLocation,
    IRStorage,
    IRStore,
    IRStructGet,
    IRStructNew,
    IRStructSet,
    IRUnaryOp,
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
from aether.ir.types import ClassRefType, EnumType, IntType, ListType, StringType


LOCATION = IRSourceLocation(14, 9, "src/lifecycle.ae")
RESULT = IRValue("result", EnumType("Color", ("RED", "GREEN"), None))
SLOT = IRValue("slot", IntType())
VALUE = IRValue("value", ListType(StringType()))
DESTINATION = IRStorage("destination", ListType(StringType()))
SOURCE = IRStorage("source", ListType(StringType()))
ENUM_CONSTANT = IREnumConstant("Color", "GREEN", 1, 7)
CLASS_OBJECT = IRValue("object", ClassRefType("pkg.Widget"))
CLASS_FIELD = IRValue("field", IntType())


ROUND_TRIP_CASES: tuple[tuple[IRInstruction, dict[str, object]], ...] = (
    (
        IRClassNew(CLASS_OBJECT),
        {
            "kind": "class_new",
            "result": {
                "tag": "value",
                "name": "object",
                "type": {"tag": "class_ref", "name": "pkg.Widget"},
            },
        },
    ),
    (
        IRClassGet(CLASS_FIELD, CLASS_OBJECT, 0, "value"),
        {
            "kind": "class_get",
            "result": {
                "tag": "value",
                "name": "field",
                "type": {"tag": "int"},
            },
            "object": {
                "tag": "value",
                "name": "object",
                "type": {"tag": "class_ref", "name": "pkg.Widget"},
            },
            "field_index": 0,
            "field_name": "value",
        },
    ),
    (
        IRClassSet(CLASS_OBJECT, 0, "value", CLASS_FIELD, True),
        {
            "kind": "class_set",
            "object": {
                "tag": "value",
                "name": "object",
                "type": {"tag": "class_ref", "name": "pkg.Widget"},
            },
            "field_index": 0,
            "field_name": "value",
            "value": {
                "tag": "value",
                "name": "field",
                "type": {"tag": "int"},
            },
            "initialize": True,
        },
    ),
    (
        IRConst(RESULT, ENUM_CONSTANT),
        {
            "kind": "const",
            "result": {
                "tag": "value",
                "name": "result",
                "type": {
                    "tag": "enum",
                    "name": "Color",
                    "variants": ["RED", "GREEN"],
                    "display_name": None,
                },
            },
            "value": {
                "tag": "enum",
                "value": {
                    "tag": "enum_constant",
                    "enum_name": "Color",
                    "member_name": "GREEN",
                    "member_id": 1,
                    "discriminant": 7,
                },
            },
        },
    ),
    (
        IRLoad(RESULT, SLOT),
        {
            "kind": "load",
            "result": {
                "tag": "value",
                "name": "result",
                "type": {
                    "tag": "enum",
                    "name": "Color",
                    "variants": ["RED", "GREEN"],
                    "display_name": None,
                },
            },
            "slot": {"tag": "value", "name": "slot", "type": {"tag": "int"}},
        },
    ),
    (
        IRStore(SLOT, VALUE),
        {
            "kind": "store",
            "slot": {"tag": "value", "name": "slot", "type": {"tag": "int"}},
            "value": {
                "tag": "value",
                "name": "value",
                "type": {"tag": "list", "element": {"tag": "string"}},
            },
        },
    ),
    (
        IRInitDefault(DESTINATION, LOCATION),
        {
            "kind": "init_default",
            "destination": {
                "tag": "storage",
                "name": "destination",
                "type": {"tag": "list", "element": {"tag": "string"}},
            },
            "source_location": {
                "tag": "source_location",
                "line": 14,
                "column": 9,
                "path": "src/lifecycle.ae",
            },
        },
    ),
    (
        IRCopyInit(DESTINATION, VALUE, LOCATION),
        {
            "kind": "copy_init",
            "destination": {
                "tag": "storage",
                "name": "destination",
                "type": {"tag": "list", "element": {"tag": "string"}},
            },
            "source": {
                "tag": "value",
                "name": "value",
                "type": {"tag": "list", "element": {"tag": "string"}},
            },
            "source_location": {
                "tag": "source_location",
                "line": 14,
                "column": 9,
                "path": "src/lifecycle.ae",
            },
        },
    ),
    (
        IRMoveInit(DESTINATION, SOURCE, LOCATION),
        {
            "kind": "move_init",
            "destination": {
                "tag": "storage",
                "name": "destination",
                "type": {"tag": "list", "element": {"tag": "string"}},
            },
            "source": {
                "tag": "storage",
                "name": "source",
                "type": {"tag": "list", "element": {"tag": "string"}},
            },
            "source_location": {
                "tag": "source_location",
                "line": 14,
                "column": 9,
                "path": "src/lifecycle.ae",
            },
        },
    ),
    (
        IRAssign(DESTINATION, VALUE, LOCATION),
        {
            "kind": "assign",
            "destination": {
                "tag": "storage",
                "name": "destination",
                "type": {"tag": "list", "element": {"tag": "string"}},
            },
            "source": {
                "tag": "value",
                "name": "value",
                "type": {"tag": "list", "element": {"tag": "string"}},
            },
            "source_location": {
                "tag": "source_location",
                "line": 14,
                "column": 9,
                "path": "src/lifecycle.ae",
            },
        },
    ),
    (
        IRDestroy(DESTINATION, LOCATION),
        {
            "kind": "destroy",
            "value": {
                "tag": "storage",
                "name": "destination",
                "type": {"tag": "list", "element": {"tag": "string"}},
            },
            "source_location": {
                "tag": "source_location",
                "line": 14,
                "column": 9,
                "path": "src/lifecycle.ae",
            },
        },
    ),
    (
        IRRelocate(DESTINATION, SOURCE, -(2**63), LOCATION),
        {
            "kind": "relocate",
            "destination": {
                "tag": "storage",
                "name": "destination",
                "type": {"tag": "list", "element": {"tag": "string"}},
            },
            "source": {
                "tag": "storage",
                "name": "source",
                "type": {"tag": "list", "element": {"tag": "string"}},
            },
            "count": -(2**63),
            "source_location": {
                "tag": "source_location",
                "line": 14,
                "column": 9,
                "path": "src/lifecycle.ae",
            },
        },
    ),
)


def test_supported_instruction_tags_are_explicit_and_stable() -> None:
    assert dict(IR_INSTRUCTION_TAGS) == {
        IRConst: "const",
        IRLoad: "load",
        IRStore: "store",
        IRInitDefault: "init_default",
        IRCopyInit: "copy_init",
        IRMoveInit: "move_init",
        IRAssign: "assign",
        IRDestroy: "destroy",
        IRRelocate: "relocate",
        IRBinaryOp: "binary_op",
        IRUnaryOp: "unary_op",
        IRCompareOp: "compare_op",
        IRCast: "cast",
        IRCall: "call",
        IRFunctionRef: "function_ref",
        IRCallIndirect: "call_indirect",
        IRPrint: "print",
        IRStructNew: "struct_new",
        IRClassNew: "class_new",
        IRClassGet: "class_get",
        IRClassSet: "class_set",
        IRInterfaceConstruct: "interface_construct",
        IRInterfaceCall: "interface_call",
        IRStructGet: "struct_get",
        IRStructSet: "struct_set",
        IRMethodResultNew: "method_result_new",
        IRMethodResultReceiver: "method_result_receiver",
        IRMethodResultValue: "method_result_value",
        IRArrayNew: "array_new",
        IRListNew: "list_new",
        IRArrayCopy: "array_copy",
        IRListCopy: "list_copy",
        IRListContains: "list_contains",
        IRListIndexOf: "list_index_of",
        IRListClear: "list_clear",
        IRListPush: "list_push",
        IRListInsert: "list_insert",
        IRListRemoveAt: "list_remove_at",
        IRListPop: "list_pop",
        IRListReverse: "list_reverse",
        IRSequenceSort: "sequence_sort",
        IRArrayGet: "array_get",
        IRArraySlice: "array_slice",
        IRListSlice: "list_slice",
        IRListGet: "list_get",
        IRArraySet: "array_set",
        IRListSet: "list_set",
        IRArrayLength: "array_length",
        IRListLength: "list_length",
        IRListIsEmpty: "list_is_empty",
        IRVectorNew: "vector_new",
        IRMatrixNew: "matrix_new",
        IRVectorAdd: "vector_add",
        IRVectorSub: "vector_sub",
        IRVectorScale: "vector_scale",
        IRVectorDot: "vector_dot",
        IROuterProduct: "outer_product",
        IRMatrixAdd: "matrix_add",
        IRMatrixSub: "matrix_sub",
        IRMatrixScale: "matrix_scale",
        IRMatrixMatMul: "matrix_mat_mul",
        IRMatrixVectorMul: "matrix_vector_mul",
        IRVectorMatrixMul: "vector_matrix_mul",
        IRVectorGet: "vector_get",
        IRMatrixGet: "matrix_get",
        IRVectorLength: "vector_length",
        IRMatrixRows: "matrix_rows",
        IRMatrixColumns: "matrix_columns",
        IRVectorSet: "vector_set",
        IRMatrixSet: "matrix_set",
        IRBranch: "branch",
        IRJump: "jump",
        IRReturn: "return",
    }


@pytest.mark.parametrize(("instruction", "expected"), ROUND_TRIP_CASES)
def test_every_supported_instruction_round_trips(
    instruction: IRInstruction,
    expected: dict[str, object],
) -> None:
    dto = ir_instruction_to_dto(instruction)

    assert dto == expected
    assert ir_instruction_from_dto(dto) == instruction
    assert type(ir_instruction_from_dto(dto)) is type(instruction)
    assert "schema_version" not in dto
    _assert_neutral(dto)


@pytest.mark.parametrize(
    "instruction",
    [case[0] for case in ROUND_TRIP_CASES if hasattr(case[0], "source_location")],
)
def test_every_optional_instruction_location_preserves_explicit_absence(
    instruction: IRInstruction,
) -> None:
    without_location = replace(instruction, source_location=None)

    dto = ir_instruction_to_dto(without_location)

    assert "source_location" in dto
    assert dto["source_location"] is None
    assert ir_instruction_from_dto(dto) == without_location


def test_instruction_output_is_deterministic() -> None:
    instruction = IRRelocate(DESTINATION, SOURCE, 12, LOCATION)

    first = ir_instruction_to_dto(instruction)
    second = ir_instruction_to_dto(instruction)

    assert first == second
    assert json.dumps(first, separators=(",", ":")) == json.dumps(second, separators=(",", ":"))


def _value_dto(name: str) -> dict[str, object]:
    return {"tag": "value", "name": name, "type": {"tag": "int"}}


def _storage_dto(name: str) -> dict[str, object]:
    return {"tag": "storage", "name": name, "type": {"tag": "int"}}


@pytest.mark.parametrize(
    ("dto", "message"),
    [
        ({}, "missing fields: kind"),
        ({"kind": "load", "result": _value_dto("result")}, "missing fields: slot"),
        (
            {
                "kind": "destroy",
                "value": _storage_dto("destination"),
                "source_location": None,
                "extra": False,
            },
            "unexpected fields: extra",
        ),
        (
            {"kind": "const", "result": _value_dto("result"), "value": {"tag": "int", "value": True}},
            "signed 32-bit integer",
        ),
        ({"kind": "load", "result": 1, "slot": _value_dto("slot")}, "IR value DTO must be a mapping"),
        (
            {
                "kind": "move_init",
                "destination": _value_dto("destination"),
                "source": _storage_dto("source"),
                "source_location": None,
            },
            "requires tag 'storage'",
        ),
        (
            {
                "kind": "assign",
                "destination": _storage_dto("destination"),
                "source": {"tag": "value", "name": 3, "type": {"tag": "int"}},
                "source_location": None,
            },
            "name must be a string",
        ),
        (
            {
                "kind": "init_default",
                "destination": _storage_dto("destination"),
                "source_location": {
                    "tag": "source_location",
                    "line": "14",
                    "column": 9,
                    "path": None,
                },
            },
            "signed 64-bit integer",
        ),
        (
            {
                "kind": "relocate",
                "destination": _storage_dto("destination"),
                "source": _storage_dto("source"),
                "count": True,
                "source_location": None,
            },
            "signed 64-bit integer",
        ),
    ],
)
def test_malformed_instruction_dtos_are_rejected(dto: dict[str, object], message: str) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_instruction_from_dto(dto)


def test_unknown_instruction_tags_are_rejected() -> None:
    with pytest.raises(IRDTOError, match=r"Unknown IR instruction DTO tag: 'future'"):
        ir_instruction_from_dto({"kind": "future"})


@pytest.mark.parametrize("kind", [None, 1, True, ["const"]])
def test_instruction_kind_rejects_wrong_primitive_types(kind: object) -> None:
    with pytest.raises(IRDTOError, match=r"IR instruction.kind must be a string"):
        ir_instruction_from_dto({"kind": kind})


def test_semantically_distinct_lifecycle_instructions_have_distinct_dtos() -> None:
    instructions = (
        IRCopyInit(DESTINATION, SOURCE, LOCATION),
        IRMoveInit(DESTINATION, SOURCE, LOCATION),
        IRAssign(DESTINATION, SOURCE, LOCATION),
    )

    encoded = [ir_instruction_to_dto(instruction) for instruction in instructions]

    assert {dto["kind"] for dto in encoded} == {"copy_init", "move_init", "assign"}
    assert len({json.dumps(dto, separators=(",", ":")) for dto in encoded}) == len(instructions)


def test_unsupported_instruction_subclasses_are_rejected() -> None:
    class FutureConst(IRConst):
        pass

    with pytest.raises(TypeError, match=r"Unsupported IR instruction for schema v1: FutureConst"):
        ir_instruction_to_dto(FutureConst(RESULT, 1))


def test_instruction_converters_reject_incompatible_schema_versions() -> None:
    instruction = IRConst(IRValue("answer", IntType()), 42)
    dto = ir_instruction_to_dto(instruction)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_instruction_to_dto(instruction, schema_version=2)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_instruction_from_dto(dto, schema_version=2)


def test_instruction_encoder_rejects_invalid_python_primitive_fields() -> None:
    with pytest.raises(IRDTOError, match=r"signed 64-bit integer"):
        ir_instruction_to_dto(IRRelocate(DESTINATION, SOURCE, True))


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
