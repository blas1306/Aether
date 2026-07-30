from __future__ import annotations

import json
import re
from dataclasses import fields
from pathlib import Path
from typing import get_type_hints

import pytest

from aether.ir.dto import (
    IRDTOError,
    IRDTOSchemaVersionError,
    ir_function_from_dto,
    ir_function_to_dto,
)
from aether.ir.model import (
    IRBasicBlock,
    IRFunction,
    IRInitDefault,
    IRModule,
    IRParameter,
    IRReturn,
    IRSourceLocation,
    IRStorage,
)
from aether.ir.types import BoolType, IntType, IRType, StringType, VoidType
from aether.ir.verification_result import verify_module_normalized


RUST_FUNCTION_SOURCE = (
    Path(__file__).parents[2]
    / "compiler-rs"
    / "crates"
    / "aether-ir"
    / "src"
    / "function.rs"
)


def _parameter_dto(name: str, type_tag: str = "int") -> dict[str, object]:
    return {
        "tag": "parameter",
        "name": name,
        "type": {"tag": type_tag},
    }


def _empty_function_dto() -> dict[str, object]:
    return {
        "name": "empty",
        "parameters": [],
        "return_type": {"tag": "void"},
        "blocks": [],
    }


def test_smallest_structurally_representable_function_has_stable_shape() -> None:
    function = IRFunction("empty", [], VoidType())

    dto = ir_function_to_dto(function)

    assert dto == _empty_function_dto()
    assert "schema_version" not in dto
    assert ir_function_from_dto(dto) == function


@pytest.mark.parametrize(
    "parameters",
    [
        [],
        [IRParameter("only", IntType())],
        [
            IRParameter("first", IntType()),
            IRParameter("second", StringType()),
            IRParameter("third", BoolType()),
        ],
    ],
)
def test_zero_one_and_multiple_parameters_round_trip_in_exact_order(
    parameters: list[IRParameter],
) -> None:
    function = IRFunction("ordered", parameters, VoidType())

    dto = ir_function_to_dto(function)
    decoded = ir_function_from_dto(dto)

    assert [item["name"] for item in dto["parameters"]] == [  # type: ignore[index]
        parameter.name for parameter in parameters
    ]
    assert decoded == function
    assert decoded.parameters == parameters


def test_parameter_order_is_semantic_to_the_dto() -> None:
    first = IRParameter("first", IntType())
    second = IRParameter("second", StringType())

    forward = ir_function_to_dto(IRFunction("ordered", [first, second], VoidType()))
    reverse = ir_function_to_dto(IRFunction("ordered", [second, first], VoidType()))

    assert forward != reverse
    assert forward["parameters"] == [_parameter_dto("first"), _parameter_dto("second", "string")]
    assert reverse["parameters"] == [_parameter_dto("second", "string"), _parameter_dto("first")]


@pytest.mark.parametrize("return_type", [VoidType(), IntType()])
def test_void_and_non_void_return_types_round_trip(return_type: IRType) -> None:
    function = IRFunction("returns", [], return_type)

    dto = ir_function_to_dto(function)

    assert ir_function_from_dto(dto) == function
    assert dto["return_type"] == {
        "tag": "void" if isinstance(return_type, VoidType) else "int"
    }


@pytest.mark.parametrize(
    "blocks",
    [
        [],
        [IRBasicBlock("entry", [IRReturn()])],
        [
            IRBasicBlock("entry", [IRReturn()]),
            IRBasicBlock("middle"),
            IRBasicBlock("exit", [IRReturn()]),
        ],
    ],
)
def test_zero_one_and_multiple_blocks_round_trip_in_exact_order(
    blocks: list[IRBasicBlock],
) -> None:
    function = IRFunction("blocks", [], VoidType(), blocks)

    dto = ir_function_to_dto(function)
    decoded = ir_function_from_dto(dto)

    assert [item["name"] for item in dto["blocks"]] == [  # type: ignore[index]
        block.name for block in blocks
    ]
    assert decoded == function
    assert decoded.blocks == blocks


def test_block_order_is_semantic_to_the_dto() -> None:
    entry = IRBasicBlock("entry", [IRReturn()])
    exit_block = IRBasicBlock("exit", [IRReturn()])

    forward = ir_function_to_dto(
        IRFunction("ordered", [], VoidType(), [entry, exit_block])
    )
    reverse = ir_function_to_dto(
        IRFunction("ordered", [], VoidType(), [exit_block, entry])
    )

    assert forward != reverse
    assert [item["name"] for item in forward["blocks"]] == ["entry", "exit"]  # type: ignore[index]
    assert [item["name"] for item in reverse["blocks"]] == ["exit", "entry"]  # type: ignore[index]


def test_nested_storage_and_source_location_round_trip_through_blocks() -> None:
    storage = IRStorage("local", StringType())
    location = IRSourceLocation(12, 7, "src/main.ae")
    function = IRFunction(
        "with_local",
        [],
        VoidType(),
        [IRBasicBlock("entry", [IRInitDefault(storage, location), IRReturn()])],
    )

    dto = ir_function_to_dto(function)

    assert ir_function_from_dto(dto) == function
    assert dto["blocks"] == [
        {
            "name": "entry",
            "instructions": [
                {
                    "kind": "init_default",
                    "destination": {
                        "tag": "storage",
                        "name": "local",
                        "type": {"tag": "string"},
                    },
                    "source_location": {
                        "tag": "source_location",
                        "line": 12,
                        "column": 7,
                        "path": "src/main.ae",
                    },
                },
                {"kind": "return", "value": None, "transferred_storage": None},
            ],
        }
    ]


def test_function_encoding_is_deterministic() -> None:
    function = IRFunction(
        "deterministic",
        [IRParameter("left", IntType()), IRParameter("right", IntType())],
        IntType(),
        [IRBasicBlock("entry", [IRReturn()]), IRBasicBlock("exit")],
    )

    first = ir_function_to_dto(function)
    second = ir_function_to_dto(function)

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
                **_empty_function_dto(),
                "parameters": [{"tag": "parameter", "name": "value"}],
            },
            "missing fields: type",
        ),
        (
            {
                **_empty_function_dto(),
                "parameters": [
                    {"tag": "storage", "name": "value", "type": {"tag": "int"}}
                ],
            },
            "requires tag 'parameter'",
        ),
        (
            {
                **_empty_function_dto(),
                "blocks": [{"name": "entry"}],
            },
            "missing fields: instructions",
        ),
        (
            {
                **_empty_function_dto(),
                "blocks": [["entry"]],
            },
            "IR basic block DTO must be a mapping",
        ),
    ],
)
def test_malformed_nested_parameters_and_blocks_are_rejected(
    dto: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_function_from_dto(dto)


@pytest.mark.parametrize(
    ("dto", "message"),
    [
        (
            {"parameters": [], "return_type": {"tag": "void"}, "blocks": []},
            "missing fields: name",
        ),
        (
            {"name": "f", "return_type": {"tag": "void"}, "blocks": []},
            "missing fields: parameters",
        ),
        (
            {"name": "f", "parameters": [], "blocks": []},
            "missing fields: return_type",
        ),
        (
            {"name": "f", "parameters": [], "return_type": {"tag": "void"}},
            "missing fields: blocks",
        ),
        (
            {**_empty_function_dto(), "metadata": {}},
            "unexpected fields: metadata",
        ),
        ({**_empty_function_dto(), "name": 1}, "name must be a string"),
        (
            {**_empty_function_dto(), "parameters": "value"},
            "parameters must be a sequence",
        ),
        (
            {**_empty_function_dto(), "return_type": "void"},
            "IR type DTO must be a mapping",
        ),
        (
            {**_empty_function_dto(), "blocks": {"name": "entry"}},
            "blocks must be a sequence",
        ),
    ],
)
def test_malformed_function_dtos_are_rejected(
    dto: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_function_from_dto(dto)


def test_function_converters_reject_incompatible_schema_versions() -> None:
    function = IRFunction("empty", [], VoidType())
    dto = ir_function_to_dto(function)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_function_to_dto(function, schema_version=2)

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_function_from_dto(dto, schema_version=2)


def test_encoder_rejects_unsupported_subclasses_and_invalid_top_level_objects() -> None:
    class FutureFunction(IRFunction):
        pass

    with pytest.raises(
        TypeError,
        match=r"Unsupported IR function for schema v1: FutureFunction",
    ):
        ir_function_to_dto(FutureFunction("future", [], VoidType()))

    with pytest.raises(
        TypeError,
        match=r"Unsupported IR function for schema v1: object",
    ):
        ir_function_to_dto(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("function", "message"),
    [
        (IRFunction(1, [], VoidType()), "name must be a string"),  # type: ignore[arg-type]
        (
            IRFunction("bad", None, VoidType()),  # type: ignore[arg-type]
            "parameters must be a sequence",
        ),
        (
            IRFunction("bad", [], VoidType(), None),  # type: ignore[arg-type]
            "blocks must be a sequence",
        ),
    ],
)
def test_encoder_rejects_invalid_python_function_fields(
    function: IRFunction,
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_function_to_dto(function)


@pytest.mark.parametrize("value", [None, [], "function", object()])
def test_decoder_rejects_invalid_top_level_objects(value: object) -> None:
    with pytest.raises(IRDTOError, match="IR function DTO must be a mapping"):
        ir_function_from_dto(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("dto", "invariant_id"),
    [
        (_empty_function_dto(), "IRV-016"),
        (
            {
                "name": "missing_entry",
                "parameters": [],
                "return_type": {"tag": "void"},
                "blocks": [
                    {
                        "name": "not_entry",
                        "instructions": [
                            {
                                "kind": "return",
                                "value": None,
                                "transferred_storage": None,
                            }
                        ],
                    }
                ],
            },
            "IRV-017",
        ),
        (
            {
                "name": "duplicate_parameters",
                "parameters": [_parameter_dto("value"), _parameter_dto("value")],
                "return_type": {"tag": "void"},
                "blocks": [],
            },
            "IRV-007",
        ),
    ],
)
def test_semantically_invalid_functions_survive_dto_for_verifier_diagnostics(
    dto: dict[str, object],
    invariant_id: str,
) -> None:
    function = ir_function_from_dto(dto)

    result = verify_module_normalized(IRModule([function]))

    assert not result.accepted
    assert result.failures[0].invariant_id == invariant_id


def test_python_and_rust_function_shapes_are_synchronized() -> None:
    expected_python = {
        "name": str,
        "parameters": list[IRParameter],
        "return_type": IRType,
        "blocks": list[IRBasicBlock],
        "may_throw": bool,
    }
    expected_rust = {
        "name": "String",
        "parameters": "Vec<IRParameter>",
        "return_type": "IRType",
        "blocks": "Vec<IRBasicBlock>",
        "may_throw": "bool",
    }
    python_fields = [field.name for field in fields(IRFunction)]
    python_hints = get_type_hints(IRFunction)

    rust_source = RUST_FUNCTION_SOURCE.read_text(encoding="utf-8")
    declaration = re.search(
        r"pub struct IRFunction\s*\{(?P<body>.*?)\n\}",
        rust_source,
        flags=re.DOTALL,
    )
    assert declaration is not None, "Rust IRFunction struct declaration not found"
    rust_field_items = re.findall(
        r"pub\s+(\w+):\s*([^,\n]+),",
        declaration.group("body"),
    )
    rust_fields = dict(rust_field_items)
    rust_field_names = [name for name, _type in rust_field_items]

    diagnostics: list[str] = []
    expected_names = list(expected_python)
    missing_python = [name for name in expected_names if name not in python_fields]
    unexpected_python = [name for name in python_fields if name not in expected_python]
    missing_rust = [name for name in expected_names if name not in rust_fields]
    unexpected_rust = [name for name in rust_fields if name not in expected_rust]
    if missing_python:
        diagnostics.append(f"Python missing fields: {', '.join(missing_python)}")
    if unexpected_python:
        diagnostics.append(f"Python unexpected fields: {', '.join(unexpected_python)}")
    if missing_rust:
        diagnostics.append(f"Rust missing fields: {', '.join(missing_rust)}")
    if unexpected_rust:
        diagnostics.append(f"Rust unexpected fields: {', '.join(unexpected_rust)}")
    if python_fields != expected_names:
        diagnostics.append(
            f"Python field order mismatch: expected {expected_names!r}, got {python_fields!r}"
        )
    if rust_field_names != expected_names:
        diagnostics.append(
            f"Rust field order mismatch: expected {expected_names!r}, "
            f"got {rust_field_names!r}"
        )
    for name, expected_type in expected_python.items():
        actual_type = python_hints.get(name)
        if actual_type != expected_type:
            diagnostics.append(
                f"Python field {name!r} type mismatch: "
                f"expected {expected_type!r}, got {actual_type!r}"
            )
    for name, expected_type in expected_rust.items():
        actual_type = rust_fields.get(name)
        if actual_type != expected_type:
            diagnostics.append(
                f"Rust field {name!r} type mismatch: "
                f"expected {expected_type!r}, got {actual_type!r}"
            )

    assert not diagnostics, "IRFunction model synchronization errors:\n- " + "\n- ".join(
        diagnostics
    )
