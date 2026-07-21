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
    IRFunction,
    IRInstruction,
    IRJump,
    IRModule,
    IRParameter,
    IRReturn,
    IRStorage,
    IRValue,
)
from aether.ir.types import BoolType, IntType, ListType, StringType, VoidType
from aether.ir.verifier import IRVerificationError, IRVerifier


CONDITION = IRValue("condition", BoolType())
RETURN_VALUE = IRValue("result", IntType())
TRANSFERRED_STORAGE = IRStorage("result_storage", ListType(StringType()))
TRANSFERRED_VALUE = IRValue("owned_result", ListType(StringType()))


def _value_dto(name: str, type_tag: str = "int") -> dict[str, object]:
    return {"tag": "value", "name": name, "type": {"tag": type_tag}}


def _storage_dto(name: str) -> dict[str, object]:
    return {
        "tag": "storage",
        "name": name,
        "type": {"tag": "list", "element": {"tag": "string"}},
    }


CONTROL_FLOW_CASES: tuple[tuple[IRInstruction, dict[str, object]], ...] = (
    (
        IRBranch(CONDITION, "then.block", "else.block"),
        {
            "kind": "branch",
            "condition": _value_dto("condition", "bool"),
            "true_target": "then.block",
            "false_target": "else.block",
        },
    ),
    (IRJump("loop.condition"), {"kind": "jump", "target": "loop.condition"}),
    (
        IRReturn(),
        {"kind": "return", "value": None, "transferred_storage": None},
    ),
    (
        IRReturn(RETURN_VALUE),
        {
            "kind": "return",
            "value": _value_dto("result"),
            "transferred_storage": None,
        },
    ),
    (
        IRReturn(TRANSFERRED_VALUE, TRANSFERRED_STORAGE),
        {
            "kind": "return",
            "value": {
                "tag": "value",
                "name": "owned_result",
                "type": {"tag": "list", "element": {"tag": "string"}},
            },
            "transferred_storage": _storage_dto("result_storage"),
        },
    ),
    (
        IRReturn(None, TRANSFERRED_STORAGE),
        {
            "kind": "return",
            "value": None,
            "transferred_storage": _storage_dto("result_storage"),
        },
    ),
)


@pytest.mark.parametrize(("instruction", "expected"), CONTROL_FLOW_CASES)
def test_every_control_flow_instruction_shape_round_trips(
    instruction: IRInstruction,
    expected: dict[str, object],
) -> None:
    dto = ir_instruction_to_dto(instruction)

    assert dto == expected
    assert ir_instruction_from_dto(dto) == instruction
    assert type(ir_instruction_from_dto(dto)) is type(instruction)
    assert "schema_version" not in dto
    _assert_neutral(dto)


def test_control_flow_encoding_is_deterministic() -> None:
    instructions = tuple(case[0] for case in CONTROL_FLOW_CASES)

    first = [ir_instruction_to_dto(instruction) for instruction in instructions]
    second = [ir_instruction_to_dto(instruction) for instruction in instructions]

    assert first == second
    assert json.dumps(first, separators=(",", ":")) == json.dumps(
        second,
        separators=(",", ":"),
    )


@pytest.mark.parametrize(
    ("dto", "message"),
    [
        (
            {
                "kind": "branch",
                "condition": _value_dto("condition", "bool"),
                "true_target": "then",
            },
            "missing fields: false_target",
        ),
        (
            {"kind": "jump", "target": "exit", "source_location": None},
            "unexpected fields: source_location",
        ),
        (
            {
                "kind": "branch",
                "condition": ["condition"],
                "true_target": "then",
                "false_target": "else",
            },
            "IR value DTO must be a mapping",
        ),
        (
            {
                "kind": "branch",
                "condition": {
                    "tag": "value",
                    "name": "condition",
                    "type": {"tag": "bool", "extra": True},
                },
                "true_target": "then",
                "false_target": "else",
            },
            "unexpected fields: extra",
        ),
        (
            {
                "kind": "return",
                "value": _value_dto("result"),
                "transferred_storage": _value_dto("result_storage"),
            },
            "requires tag 'storage'",
        ),
        (
            {
                "kind": "branch",
                "condition": _value_dto("condition", "bool"),
                "true_target": 3,
                "false_target": "else",
            },
            "true_target must be a string",
        ),
        ({"kind": "jump", "target": False}, "target must be a string"),
    ],
)
def test_malformed_control_flow_dtos_are_rejected(
    dto: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_instruction_from_dto(dto)


@pytest.mark.parametrize(
    "instruction",
    [
        IRBranch(CONDITION, 1, "else"),  # type: ignore[arg-type]
        IRJump(False),  # type: ignore[arg-type]
    ],
)
def test_control_flow_encoder_rejects_invalid_python_primitive_fields(
    instruction: IRInstruction,
) -> None:
    with pytest.raises(IRDTOError, match="must be a string"):
        ir_instruction_to_dto(instruction)


def test_unsupported_control_flow_subclass_is_rejected() -> None:
    class FutureBranch(IRBranch):
        pass

    with pytest.raises(
        TypeError,
        match=r"Unsupported IR instruction for schema v1: FutureBranch",
    ):
        ir_instruction_to_dto(FutureBranch(CONDITION, "then", "else"))


@pytest.mark.parametrize("instruction", [case[0] for case in CONTROL_FLOW_CASES])
def test_control_flow_converters_reject_incompatible_schema_versions(
    instruction: IRInstruction,
) -> None:
    dto = ir_instruction_to_dto(instruction)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_instruction_to_dto(instruction, schema_version=2)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_instruction_from_dto(dto, schema_version=2)


@pytest.mark.parametrize(
    ("dto", "expected"),
    [
        (
            {
                "kind": "branch",
                "condition": _value_dto("condition", "bool"),
                "true_target": "missing.true",
                "false_target": "missing.false",
            },
            IRBranch(CONDITION, "missing.true", "missing.false"),
        ),
        (
            {"kind": "jump", "target": "missing.jump"},
            IRJump("missing.jump"),
        ),
    ],
)
def test_unknown_successor_references_are_preserved_structurally(
    dto: dict[str, object],
    expected: IRInstruction,
) -> None:
    assert ir_instruction_from_dto(dto) == expected


def test_unknown_successor_reference_remains_a_verifier_diagnostic() -> None:
    decoded = ir_instruction_from_dto(
        {
            "kind": "branch",
            "condition": _value_dto("condition", "bool"),
            "true_target": "then",
            "false_target": "missing",
        }
    )
    condition = IRParameter("condition", BoolType())
    module = IRModule(
        [
            IRFunction(
                "choose",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [decoded]),
                    IRBasicBlock("then", [IRReturn()]),
                ],
            )
        ]
    )

    with pytest.raises(
        IRVerificationError,
        match=r"Unknown branch target 'missing' in function 'choose'",
    ):
        IRVerifier(module).verify()


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
