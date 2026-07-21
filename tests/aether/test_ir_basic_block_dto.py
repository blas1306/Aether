from __future__ import annotations

import json
import re
from dataclasses import fields
from pathlib import Path
from typing import cast, get_type_hints

import pytest

from aether.ir.dto import (
    IRDTOError,
    IRDTOSchemaVersionError,
    ir_basic_block_from_dto,
    ir_basic_block_to_dto,
)
from aether.ir.model import (
    IRBasicBlock,
    IRBranch,
    IRConst,
    IRFunction,
    IRInstruction,
    IRJump,
    IRModule,
    IRReturn,
    IRValue,
)
from aether.ir.types import BoolType, IntType, VoidType
from aether.ir.verification_result import verify_module_normalized


RUST_BLOCK_SOURCE = (
    Path(__file__).parents[2]
    / "compiler-rs"
    / "crates"
    / "aether-ir"
    / "src"
    / "block.rs"
)

CONDITION = IRValue("condition", BoolType())
FIRST = IRValue("first", IntType())
SECOND = IRValue("second", IntType())


def _value_dto(name: str, type_tag: str = "int") -> dict[str, object]:
    return {"tag": "value", "name": name, "type": {"tag": type_tag}}


def test_empty_basic_block_has_stable_shape_and_round_trips() -> None:
    block = IRBasicBlock("entry")

    dto = ir_basic_block_to_dto(block)

    assert dto == {"name": "entry", "instructions": []}
    assert "schema_version" not in dto
    assert ir_basic_block_from_dto(dto) == block


def test_basic_block_with_one_instruction_round_trips() -> None:
    block = IRBasicBlock("exit", [IRReturn()])

    dto = ir_basic_block_to_dto(block)

    assert dto == {
        "name": "exit",
        "instructions": [
            {"kind": "return", "value": None, "transferred_storage": None}
        ],
    }
    assert ir_basic_block_from_dto(dto) == block


def test_multiple_instructions_preserve_exact_order() -> None:
    block = IRBasicBlock(
        "entry",
        [IRConst(FIRST, 1), IRConst(SECOND, 2), IRReturn(SECOND)],
    )

    dto = ir_basic_block_to_dto(block)
    decoded = ir_basic_block_from_dto(dto)
    instructions = cast(list[dict[str, object]], dto["instructions"])

    assert [instruction["kind"] for instruction in instructions] == [
        "const",
        "const",
        "return",
    ]
    results = [
        cast(dict[str, object], instruction["result"])["name"]
        for instruction in instructions[:2]
    ]
    assert results == ["first", "second"]
    assert decoded == block
    assert decoded.instructions == block.instructions


@pytest.mark.parametrize(
    ("terminator", "expected"),
    [
        (
            IRBranch(CONDITION, "then", "else"),
            {
                "kind": "branch",
                "condition": _value_dto("condition", "bool"),
                "true_target": "then",
                "false_target": "else",
            },
        ),
        (IRJump("exit"), {"kind": "jump", "target": "exit"}),
        (
            IRReturn(FIRST),
            {
                "kind": "return",
                "value": _value_dto("first"),
                "transferred_storage": None,
            },
        ),
    ],
)
def test_each_control_flow_terminator_family_uses_instruction_dto(
    terminator: IRInstruction,
    expected: dict[str, object],
) -> None:
    block = IRBasicBlock("control", [terminator])

    dto = ir_basic_block_to_dto(block)

    assert dto["instructions"] == [expected]
    assert ir_basic_block_from_dto(dto) == block


@pytest.mark.parametrize(
    ("dto", "message"),
    [
        (
            {"name": "entry", "instructions": [{"kind": "jump"}]},
            "missing fields: target",
        ),
        (
            {"name": "entry", "instructions": [[]]},
            "IR instruction DTO must be a mapping",
        ),
        (
            {
                "name": "entry",
                "instructions": [
                    {
                        "kind": "jump",
                        "target": "exit",
                        "source_location": None,
                    }
                ],
            },
            "unexpected fields: source_location",
        ),
    ],
)
def test_malformed_nested_instruction_dtos_are_rejected(
    dto: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_basic_block_from_dto(dto)


@pytest.mark.parametrize(
    ("dto", "message"),
    [
        ({"instructions": []}, "missing fields: name"),
        ({"name": "entry"}, "missing fields: instructions"),
        (
            {"name": "entry", "instructions": [], "metadata": {}},
            "unexpected fields: metadata",
        ),
        ({"name": 1, "instructions": []}, "name must be a string"),
        (
            {"name": "entry", "instructions": "return"},
            "instructions must be a sequence",
        ),
        (
            {"name": "entry", "instructions": {"kind": "return"}},
            "instructions must be a sequence",
        ),
    ],
)
def test_malformed_basic_block_dtos_are_rejected(
    dto: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_basic_block_from_dto(dto)


def test_basic_block_converters_reject_incompatible_schema_versions() -> None:
    block = IRBasicBlock("entry", [IRReturn()])
    dto = ir_basic_block_to_dto(block)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_basic_block_to_dto(block, schema_version=2)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_basic_block_from_dto(dto, schema_version=2)


def test_basic_block_encoding_is_deterministic() -> None:
    block = IRBasicBlock(
        "entry",
        [IRConst(FIRST, 1), IRConst(SECOND, 2), IRReturn(SECOND)],
    )

    first = ir_basic_block_to_dto(block)
    second = ir_basic_block_to_dto(block)

    assert first == second
    assert json.dumps(first, separators=(",", ":")) == json.dumps(
        second,
        separators=(",", ":"),
    )


@pytest.mark.parametrize(
    ("dto", "invariant_id"),
    [
        (
            {
                "name": "entry",
                "instructions": [
                    {
                        "kind": "const",
                        "result": _value_dto("value"),
                        "value": {"tag": "int", "value": 1},
                    }
                ],
            },
            "IRV-018",
        ),
        (
            {
                "name": "entry",
                "instructions": [
                    {"kind": "return", "value": None, "transferred_storage": None},
                    {
                        "kind": "const",
                        "result": _value_dto("value"),
                        "value": {"tag": "int", "value": 1},
                    },
                ],
            },
            "IRV-019",
        ),
    ],
)
def test_semantically_invalid_blocks_survive_dto_for_verifier_diagnostics(
    dto: dict[str, object],
    invariant_id: str,
) -> None:
    block = ir_basic_block_from_dto(dto)
    module = IRModule([IRFunction("main", [], VoidType(), [block])])

    result = verify_module_normalized(module)

    assert not result.accepted
    assert result.failures[0].invariant_id == invariant_id


def test_encoder_rejects_unsupported_subclasses_and_invalid_top_level_objects() -> None:
    class FutureBasicBlock(IRBasicBlock):
        pass

    with pytest.raises(
        TypeError,
        match=r"Unsupported IR basic block for schema v1: FutureBasicBlock",
    ):
        ir_basic_block_to_dto(FutureBasicBlock("entry"))

    with pytest.raises(
        TypeError,
        match=r"Unsupported IR basic block for schema v1: object",
    ):
        ir_basic_block_to_dto(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("block", "message"),
    [
        (IRBasicBlock(1, []), "name must be a string"),  # type: ignore[arg-type]
        (
            IRBasicBlock("entry", None),  # type: ignore[arg-type]
            "instructions must be a sequence",
        ),
    ],
)
def test_encoder_rejects_invalid_python_block_fields(
    block: IRBasicBlock,
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_basic_block_to_dto(block)


@pytest.mark.parametrize("value", [None, [], "entry", object()])
def test_decoder_rejects_invalid_top_level_objects(value: object) -> None:
    with pytest.raises(IRDTOError, match="IR basic block DTO must be a mapping"):
        ir_basic_block_from_dto(value)  # type: ignore[arg-type]


def test_python_and_rust_basic_block_shapes_are_synchronized() -> None:
    python_hints = get_type_hints(IRBasicBlock)
    assert [field.name for field in fields(IRBasicBlock)] == ["name", "instructions"]
    assert python_hints == {"name": str, "instructions": list[IRInstruction]}

    rust_source = RUST_BLOCK_SOURCE.read_text(encoding="utf-8")
    declaration = re.search(
        r"pub struct IRBasicBlock\s*\{(?P<body>.*?)\n\}",
        rust_source,
        flags=re.DOTALL,
    )
    assert declaration is not None, "Rust IRBasicBlock struct declaration not found"
    rust_fields = re.findall(
        r"pub\s+(\w+):\s*([^,\n]+),",
        declaration.group("body"),
    )

    assert rust_fields == [
        ("name", "String"),
        ("instructions", "Vec<IRInstruction>"),
    ]
