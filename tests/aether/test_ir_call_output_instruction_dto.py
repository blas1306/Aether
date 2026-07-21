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
    IRCall,
    IRCallIndirect,
    IRFunctionRef,
    IRInstruction,
    IRParameter,
    IRPrint,
    IRSourceLocation,
    IRValue,
)
from aether.ir.types import BoolType, FunctionType, IntType, StringType, VoidType


LOCATION = IRSourceLocation(31, 7, "src/calls.ae")
INT_ARGUMENT = IRParameter("integer", IntType())
TEXT_ARGUMENT = IRValue("text", StringType())
BOOL_ARGUMENT = IRValue("flag", BoolType())
INT_RESULT = IRValue("result", IntType())
SIGNATURE = FunctionType((IntType(), StringType()), BoolType())
CALLEE = IRValue("callback", SIGNATURE)


ROUND_TRIP_CASES: tuple[tuple[IRInstruction, dict[str, object]], ...] = (
    (
        IRCall("compute", (INT_ARGUMENT, TEXT_ARGUMENT), INT_RESULT, None, LOCATION),
        {
            "kind": "call",
            "function": "compute",
            "arguments": [
                {"tag": "parameter", "name": "integer", "type": {"tag": "int"}},
                {"tag": "value", "name": "text", "type": {"tag": "string"}},
            ],
            "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
            "builtin": None,
            "source_location": {
                "tag": "source_location",
                "line": 31,
                "column": 7,
                "path": "src/calls.ae",
            },
        },
    ),
    (
        IRFunctionRef(CALLEE, "predicate"),
        {
            "kind": "function_ref",
            "result": {
                "tag": "value",
                "name": "callback",
                "type": {
                    "tag": "function",
                    "parameter_types": [{"tag": "int"}, {"tag": "string"}],
                    "return_type": {"tag": "bool"},
                },
            },
            "function": "predicate",
        },
    ),
    (
        IRCallIndirect(CALLEE, (TEXT_ARGUMENT, INT_ARGUMENT), INT_RESULT),
        {
            "kind": "call_indirect",
            "callee": {
                "tag": "value",
                "name": "callback",
                "type": {
                    "tag": "function",
                    "parameter_types": [{"tag": "int"}, {"tag": "string"}],
                    "return_type": {"tag": "bool"},
                },
            },
            "arguments": [
                {"tag": "value", "name": "text", "type": {"tag": "string"}},
                {"tag": "parameter", "name": "integer", "type": {"tag": "int"}},
            ],
            "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
        },
    ),
    (
        IRPrint(TEXT_ARGUMENT, True, (2, 3)),
        {
            "kind": "print",
            "value": {"tag": "value", "name": "text", "type": {"tag": "string"}},
            "newline": True,
            "aggregate_shape": [2, 3],
        },
    ),
)


@pytest.mark.parametrize(("instruction", "expected"), ROUND_TRIP_CASES)
def test_call_and_output_variants_round_trip(
    instruction: IRInstruction,
    expected: dict[str, object],
) -> None:
    dto = ir_instruction_to_dto(instruction)

    assert dto == expected
    assert ir_instruction_from_dto(dto) == instruction
    assert type(ir_instruction_from_dto(dto)) is type(instruction)
    _assert_neutral(dto)


@pytest.mark.parametrize(
    "arguments",
    [(), (INT_ARGUMENT,), (INT_ARGUMENT, TEXT_ARGUMENT, BOOL_ARGUMENT)],
)
def test_direct_call_preserves_zero_one_and_multiple_ordered_arguments(
    arguments: tuple[IRValue, ...],
) -> None:
    instruction = IRCall("ordered", arguments, INT_RESULT)

    dto = ir_instruction_to_dto(instruction)

    assert [argument["name"] for argument in dto["arguments"]] == [
        argument.name for argument in arguments
    ]
    assert ir_instruction_from_dto(dto) == instruction


def test_calls_differing_only_in_argument_order_have_distinct_dtos() -> None:
    left = IRCall("ordered", (INT_ARGUMENT, TEXT_ARGUMENT), INT_RESULT)
    right = IRCall("ordered", (TEXT_ARGUMENT, INT_ARGUMENT), INT_RESULT)

    left_dto = ir_instruction_to_dto(left)
    right_dto = ir_instruction_to_dto(right)

    assert left_dto != right_dto
    assert json.dumps(left_dto, separators=(",", ":")) != json.dumps(
        right_dto,
        separators=(",", ":"),
    )


@pytest.mark.parametrize(
    "instruction",
    [
        IRCall("procedure", (), None),
        IRCall("procedure", (), None, "io.writeText"),
        IRCallIndirect(IRValue("procedure", FunctionType((), VoidType())), (), None),
    ],
)
def test_calls_without_results_preserve_void_call_shape(instruction: IRInstruction) -> None:
    dto = ir_instruction_to_dto(instruction)

    assert dto["result"] is None
    assert ir_instruction_from_dto(dto) == instruction


def test_direct_call_preserves_optional_source_location() -> None:
    located = IRCall("located", (), INT_RESULT, None, LOCATION)
    unlocated = IRCall("located", (), INT_RESULT)

    assert ir_instruction_from_dto(ir_instruction_to_dto(located)) == located
    unlocated_dto = ir_instruction_to_dto(unlocated)
    assert unlocated_dto["source_location"] is None
    assert ir_instruction_from_dto(unlocated_dto) == unlocated


@pytest.mark.parametrize(
    "signature",
    [
        FunctionType((), VoidType()),
        FunctionType((IntType(),), StringType()),
        FunctionType((IntType(), StringType()), BoolType()),
    ],
)
def test_function_references_preserve_representative_signatures(signature: FunctionType) -> None:
    instruction = IRFunctionRef(IRValue("function", signature), "unknown.function")

    assert ir_instruction_from_dto(ir_instruction_to_dto(instruction)) == instruction


def test_distinct_function_signatures_remain_distinct() -> None:
    first = IRFunctionRef(
        IRValue("function", FunctionType((IntType(),), StringType())),
        "overload",
    )
    second = IRFunctionRef(
        IRValue("function", FunctionType((StringType(),), IntType())),
        "overload",
    )

    assert ir_instruction_to_dto(first) != ir_instruction_to_dto(second)


def test_indirect_call_preserves_target_value_and_dispatch_kind() -> None:
    direct = IRCall("predicate", (INT_ARGUMENT, TEXT_ARGUMENT), INT_RESULT)
    indirect = IRCallIndirect(CALLEE, (INT_ARGUMENT, TEXT_ARGUMENT), INT_RESULT)

    indirect_dto = ir_instruction_to_dto(indirect)

    assert indirect_dto["kind"] == "call_indirect"
    function_ref_dto = ir_instruction_to_dto(IRFunctionRef(CALLEE, "predicate"))
    assert indirect_dto["callee"] == function_ref_dto["result"]
    assert indirect_dto != ir_instruction_to_dto(direct)
    assert ir_instruction_from_dto(indirect_dto) == indirect


def test_structurally_valid_unknown_call_identity_and_signature_are_preserved() -> None:
    unknown_signature = FunctionType((BoolType(), StringType()), VoidType())
    instructions = (
        IRCall("missing.function", (INT_ARGUMENT,), None, "future.builtin"),
        IRFunctionRef(IRValue("function", unknown_signature), "missing.function"),
        IRCallIndirect(IRValue("callee", unknown_signature), (INT_ARGUMENT,), INT_RESULT),
    )

    for instruction in instructions:
        assert ir_instruction_from_dto(ir_instruction_to_dto(instruction)) == instruction


@pytest.mark.parametrize("newline", [False, True])
@pytest.mark.parametrize("aggregate_shape", [None, (), (2, 3), (-(2**63), 2**63 - 1)])
def test_all_print_configurations_round_trip(
    newline: bool,
    aggregate_shape: tuple[int, ...] | None,
) -> None:
    instruction = IRPrint(TEXT_ARGUMENT, newline, aggregate_shape)

    dto = ir_instruction_to_dto(instruction)

    assert dto["newline"] is newline
    assert dto["aggregate_shape"] == (
        None if aggregate_shape is None else list(aggregate_shape)
    )
    assert ir_instruction_from_dto(dto) == instruction


def _value_dto(name: str = "value") -> dict[str, object]:
    return {"tag": "value", "name": name, "type": {"tag": "int"}}


def _call_dto(arguments: object = ()) -> dict[str, object]:
    return {
        "kind": "call",
        "function": "function",
        "arguments": arguments,
        "result": None,
        "builtin": None,
        "source_location": None,
    }


@pytest.mark.parametrize(
    ("dto", "message"),
    [
        ({"kind": "call"}, "missing fields"),
        ({**_call_dto(), "extra": None}, "unexpected fields: extra"),
        ({**_call_dto(), "function": True}, "function must be a string"),
        ({**_call_dto(), "builtin": 3}, "builtin must be a string"),
        ({**_call_dto(), "result": "result"}, "IR value DTO must be a mapping"),
        (_call_dto("not arguments"), "arguments must be a sequence"),
        (_call_dto({"first": _value_dto()}), "arguments must be a sequence"),
        (_call_dto([7]), "IR value DTO must be a mapping"),
        (_call_dto([{"tag": "value", "name": "x"}]), "missing fields: type"),
        (
            {
                "kind": "function_ref",
                "result": _value_dto(),
                "function": None,
            },
            "function must be a string",
        ),
        (
            {
                "kind": "call_indirect",
                "callee": {"tag": "value", "name": "callee", "type": {"tag": "future"}},
                "arguments": [],
                "result": None,
            },
            "Unknown IR type DTO tag",
        ),
        (
            {
                "kind": "call_indirect",
                "callee": _value_dto("callee"),
                "arguments": 1,
                "result": None,
            },
            "arguments must be a sequence",
        ),
        (
            {
                "kind": "print",
                "value": _value_dto(),
                "newline": 1,
                "aggregate_shape": None,
            },
            "newline must be a boolean",
        ),
        (
            {
                "kind": "print",
                "value": _value_dto(),
                "newline": False,
                "aggregate_shape": [2, True],
            },
            r"aggregate_shape\[1\] must be a signed 64-bit integer",
        ),
        (
            {
                "kind": "print",
                "value": _value_dto(),
                "newline": False,
                "aggregate_shape": [2**63],
            },
            r"aggregate_shape\[0\] must be a signed 64-bit integer",
        ),
    ],
)
def test_malformed_call_and_output_dtos_are_rejected(
    dto: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_instruction_from_dto(dto)


def test_call_and_output_encoding_is_deterministic() -> None:
    instructions = tuple(case[0] for case in ROUND_TRIP_CASES)

    for instruction in instructions:
        first = ir_instruction_to_dto(instruction)
        second = ir_instruction_to_dto(instruction)
        assert first == second
        assert json.dumps(first, separators=(",", ":")) == json.dumps(
            second,
            separators=(",", ":"),
        )


@pytest.mark.parametrize("instruction", [case[0] for case in ROUND_TRIP_CASES])
def test_call_and_output_variants_reject_incompatible_schema_versions(
    instruction: IRInstruction,
) -> None:
    dto = ir_instruction_to_dto(instruction)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_instruction_to_dto(instruction, schema_version=2)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_instruction_from_dto(dto, schema_version=2)


def test_supported_call_subclasses_remain_unsupported() -> None:
    class FutureCall(IRCall):
        pass

    with pytest.raises(TypeError, match=r"Unsupported IR instruction for schema v1: FutureCall"):
        ir_instruction_to_dto(FutureCall("future"))


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
