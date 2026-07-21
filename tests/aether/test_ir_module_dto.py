from __future__ import annotations

import json
import re
from dataclasses import fields
from pathlib import Path
from typing import get_type_hints

import pytest

from aether.ir.dto import (
    IR_SCHEMA_VERSION,
    IRDTOError,
    IRDTOSchemaVersionError,
    IRModuleDTO,
    ir_module_from_dto,
    ir_module_to_dto,
    ir_struct_definition_from_dto,
    ir_struct_definition_to_dto,
)
from aether.ir.model import (
    IRBasicBlock,
    IRConst,
    IRFunction,
    IRInitDefault,
    IRModule,
    IRReturn,
    IRSourceLocation,
    IRStorage,
    IRStructDefinition,
)
from aether.ir.types import (
    ArrayType,
    IntType,
    IRType,
    ListType,
    StringType,
    StructType,
    VoidType,
)
from aether.ir.verification_result import verify_module_normalized


RUST_IR_SOURCE = Path(__file__).parents[2] / "compiler-rs" / "crates" / "aether-ir" / "src"


def _empty_module_dto() -> IRModuleDTO:
    return {"schema_version": IR_SCHEMA_VERSION, "functions": [], "structs": []}


def _function(name: str) -> IRFunction:
    return IRFunction(name, [], VoidType(), [IRBasicBlock("entry", [IRReturn()])])


def _function_dto(name: str) -> dict[str, object]:
    return {
        "name": name,
        "parameters": [],
        "return_type": {"tag": "void"},
        "blocks": [
            {
                "name": "entry",
                "instructions": [
                    {"kind": "return", "value": None, "transferred_storage": None}
                ],
            }
        ],
    }


def _struct_dto(name: str, field_name: str = "value") -> dict[str, object]:
    return {
        "name": name,
        "fields": [{"name": field_name, "type": {"tag": "int"}}],
    }


def _assert_schema_version_only_at_root(value: object, *, root: bool = True) -> None:
    if isinstance(value, dict):
        assert ("schema_version" in value) is root
        for child in value.values():
            _assert_schema_version_only_at_root(child, root=False)
    elif isinstance(value, list):
        for child in value:
            _assert_schema_version_only_at_root(child, root=False)


def test_smallest_structurally_representable_module_has_stable_root_shape() -> None:
    module = IRModule()

    dto = ir_module_to_dto(module)

    assert dto == _empty_module_dto()
    assert ir_module_from_dto(dto) == module


@pytest.mark.parametrize("functions", [[], [_function("main")], [_function("a"), _function("b")]])
def test_empty_and_non_empty_function_collections_round_trip(
    functions: list[IRFunction],
) -> None:
    module = IRModule(functions)

    dto = ir_module_to_dto(module)
    decoded = ir_module_from_dto(dto)

    assert decoded == module
    assert decoded.functions == functions


def test_function_order_is_preserved_and_distinguishes_module_dtos() -> None:
    first = _function("first")
    second = _function("second")

    forward = ir_module_to_dto(IRModule([first, second]))
    reverse = ir_module_to_dto(IRModule([second, first]))

    assert forward != reverse
    assert [function["name"] for function in forward["functions"]] == [  # type: ignore[index]
        "first",
        "second",
    ]
    assert [function["name"] for function in reverse["functions"]] == [  # type: ignore[index]
        "second",
        "first",
    ]


@pytest.mark.parametrize(
    "definitions",
    [
        [],
        [IRStructDefinition("Empty", ())],
        [
            IRStructDefinition("Point", (("x", IntType()), ("y", IntType()))),
            IRStructDefinition(
                "Container",
                (
                    ("point", StructType("Point")),
                    ("labels", ListType(StringType())),
                    ("points", ArrayType(StructType("Point"))),
                ),
            ),
        ],
    ],
)
def test_empty_populated_and_nested_struct_definitions_round_trip(
    definitions: list[IRStructDefinition],
) -> None:
    module = IRModule(structs=definitions)

    dto = ir_module_to_dto(module)
    decoded = ir_module_from_dto(dto)

    assert decoded == module
    assert decoded.structs == definitions


def test_struct_and_field_order_is_preserved_and_distinguishes_dtos() -> None:
    first = IRStructDefinition("First", (("left", IntType()), ("right", StringType())))
    second = IRStructDefinition("Second", (("value", IntType()),))

    forward = ir_module_to_dto(IRModule(structs=[first, second]))
    reverse = ir_module_to_dto(IRModule(structs=[second, first]))
    reversed_fields = ir_module_to_dto(
        IRModule(
            structs=[
                IRStructDefinition(
                    "First",
                    (("right", StringType()), ("left", IntType())),
                ),
                second,
            ]
        )
    )

    assert forward != reverse
    assert forward != reversed_fields
    assert [definition["name"] for definition in forward["structs"]] == [  # type: ignore[index]
        "First",
        "Second",
    ]


def test_struct_definition_leaf_has_no_duplicate_schema_version() -> None:
    definition = IRStructDefinition("Point", (("x", IntType()), ("y", IntType())))

    dto = ir_struct_definition_to_dto(definition)

    assert dto == {
        "name": "Point",
        "fields": [
            {"name": "x", "type": {"tag": "int"}},
            {"name": "y", "type": {"tag": "int"}},
        ],
    }
    assert "schema_version" not in dto
    assert ir_struct_definition_from_dto(dto) == definition


def test_complete_module_round_trip_preserves_every_current_entity() -> None:
    result = IRStorage("result", IntType())
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRInitDefault(
                                result,
                                IRSourceLocation(3, 9, "src/main.ae"),
                            ),
                            IRConst(result, 42),
                            IRReturn(result, result),
                        ],
                    )
                ],
            ),
            _function("helper"),
        ],
        [
            IRStructDefinition("Inner", (("text", StringType()),)),
            IRStructDefinition(
                "Outer",
                (("inner", StructType("Inner")), ("values", ArrayType(IntType()))),
            ),
        ],
    )

    dto = ir_module_to_dto(module)

    assert ir_module_from_dto(dto) == module
    _assert_schema_version_only_at_root(dto)


def test_module_encoding_is_deterministic() -> None:
    module = IRModule(
        [_function("first"), _function("second")],
        [
            IRStructDefinition("A", (("value", IntType()),)),
            IRStructDefinition("B", (("a", StructType("A")),)),
        ],
    )

    first = ir_module_to_dto(module)
    second = ir_module_to_dto(module)

    assert first == second
    assert json.dumps(first, separators=(",", ":")) == json.dumps(
        second,
        separators=(",", ":"),
    )


@pytest.mark.parametrize(
    ("dto", "message"),
    [
        (
            {**_empty_module_dto(), "functions": [{"name": "broken"}]},
            "missing fields: blocks, parameters, return_type",
        ),
        (
            {**_empty_module_dto(), "functions": ["broken"]},
            "IR function DTO must be a mapping",
        ),
        (
            {**_empty_module_dto(), "structs": [{"name": "Broken"}]},
            "missing fields: fields",
        ),
        (
            {
                **_empty_module_dto(),
                "structs": [
                    {"name": "Broken", "fields": [{"name": "field"}]}
                ],
            },
            "missing fields: type",
        ),
        (
            {
                **_empty_module_dto(),
                "structs": [
                    {"name": "Broken", "fields": [{"name": "field", "type": "int"}]}
                ],
            },
            "IR type DTO must be a mapping",
        ),
    ],
)
def test_malformed_nested_functions_and_definitions_are_rejected(
    dto: IRModuleDTO,
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_module_from_dto(dto)


@pytest.mark.parametrize(
    ("dto", "message"),
    [
        ({"functions": [], "structs": []}, "missing fields: schema_version"),
        ({"schema_version": 1, "structs": []}, "missing fields: functions"),
        ({"schema_version": 1, "functions": []}, "missing fields: structs"),
        ({**_empty_module_dto(), "name": "invented"}, "unexpected fields: name"),
        ({**_empty_module_dto(), "functions": "main"}, "functions must be a sequence"),
        ({**_empty_module_dto(), "structs": {}}, "structs must be a sequence"),
    ],
)
def test_malformed_module_envelopes_are_rejected(
    dto: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_module_from_dto(dto)


@pytest.mark.parametrize("version", [0, 2, -1, True, "1", 1.0, None])
def test_module_decoder_rejects_unsupported_or_wrongly_typed_schema_versions(
    version: object,
) -> None:
    dto = {**_empty_module_dto(), "schema_version": version}

    with pytest.raises(
        IRDTOSchemaVersionError,
        match=rf"schema version {re.escape(repr(version))}; expected 1",
    ):
        ir_module_from_dto(dto)


def test_module_encoder_accepts_only_the_current_schema_version() -> None:
    assert ir_module_to_dto(IRModule(), schema_version=1) == _empty_module_dto()

    with pytest.raises(IRDTOSchemaVersionError, match=r"schema version 2; expected 1"):
        ir_module_to_dto(IRModule(), schema_version=2)


def test_encoder_rejects_unsupported_module_and_definition_subclasses() -> None:
    class FutureModule(IRModule):
        pass

    class FutureStructDefinition(IRStructDefinition):
        pass

    with pytest.raises(TypeError, match=r"Unsupported IR module for schema v1: FutureModule"):
        ir_module_to_dto(FutureModule())

    with pytest.raises(TypeError, match=r"Unsupported IR module for schema v1: object"):
        ir_module_to_dto(object())  # type: ignore[arg-type]

    with pytest.raises(
        TypeError,
        match=r"Unsupported IR struct definition for schema v1: FutureStructDefinition",
    ):
        ir_struct_definition_to_dto(FutureStructDefinition("Future", ()))


@pytest.mark.parametrize("value", [None, [], "module", object()])
def test_decoder_rejects_invalid_top_level_objects(value: object) -> None:
    with pytest.raises(IRDTOError, match="IR module DTO must be a mapping"):
        ir_module_from_dto(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("module", "message"),
    [
        (IRModule(None, []), "functions must be a sequence"),  # type: ignore[arg-type]
        (IRModule([], None), "structs must be a sequence"),  # type: ignore[arg-type]
    ],
)
def test_encoder_rejects_invalid_python_module_fields(
    module: IRModule,
    message: str,
) -> None:
    with pytest.raises(IRDTOError, match=message):
        ir_module_to_dto(module)


@pytest.mark.parametrize(
    ("dto", "invariant_id"),
    [
        (
            {
                "schema_version": 1,
                "functions": [_function_dto("duplicate"), _function_dto("duplicate")],
                "structs": [],
            },
            "IRV-006",
        ),
        (
            {
                "schema_version": 1,
                "functions": [],
                "structs": [_struct_dto("Duplicate"), _struct_dto("Duplicate")],
            },
            "IRV-001",
        ),
    ],
)
def test_semantically_invalid_modules_survive_dto_for_verifier_diagnostics(
    dto: IRModuleDTO,
    invariant_id: str,
) -> None:
    module = ir_module_from_dto(dto)

    result = verify_module_normalized(module)

    assert not result.accepted
    assert result.failures[0].invariant_id == invariant_id


def _rust_struct_fields(path: Path, struct_name: str) -> list[tuple[str, str]]:
    rust_source = path.read_text(encoding="utf-8")
    declaration = re.search(
        rf"pub struct {struct_name}\s*\{{(?P<body>.*?)\n\}}",
        rust_source,
        flags=re.DOTALL,
    )
    assert declaration is not None, f"Rust {struct_name} struct declaration not found"
    return re.findall(
        r"^\s*pub\s+(\w+):\s*(.+),\s*$",
        declaration.group("body"),
        flags=re.MULTILINE,
    )


def _model_sync_diagnostics(
    *,
    model_name: str,
    python_names: list[str],
    python_hints: dict[str, object],
    expected_python: dict[str, object],
    rust_fields: list[tuple[str, str]],
    expected_rust: dict[str, str],
) -> list[str]:
    diagnostics: list[str] = []
    expected_names = list(expected_python)
    rust_types = dict(rust_fields)
    rust_names = [name for name, _type in rust_fields]
    missing_python = [name for name in expected_names if name not in python_names]
    unexpected_python = [name for name in python_names if name not in expected_python]
    missing_rust = [name for name in expected_names if name not in rust_types]
    unexpected_rust = [name for name in rust_names if name not in expected_rust]
    if missing_python:
        diagnostics.append(f"{model_name} Python missing fields: {', '.join(missing_python)}")
    if unexpected_python:
        diagnostics.append(
            f"{model_name} Python unexpected fields: {', '.join(unexpected_python)}"
        )
    if missing_rust:
        diagnostics.append(f"{model_name} Rust missing fields: {', '.join(missing_rust)}")
    if unexpected_rust:
        diagnostics.append(
            f"{model_name} Rust unexpected fields: {', '.join(unexpected_rust)}"
        )
    if python_names != expected_names:
        diagnostics.append(
            f"{model_name} Python field order mismatch: expected {expected_names!r}, "
            f"got {python_names!r}"
        )
    if rust_names != expected_names:
        diagnostics.append(
            f"{model_name} Rust field order mismatch: expected {expected_names!r}, "
            f"got {rust_names!r}"
        )
    for name, expected_type in expected_python.items():
        actual_type = python_hints.get(name)
        if actual_type != expected_type:
            diagnostics.append(
                f"{model_name} Python field {name!r} type mismatch: "
                f"expected {expected_type!r}, got {actual_type!r}"
            )
    for name, expected_type in expected_rust.items():
        actual_type = rust_types.get(name)
        if actual_type != expected_type:
            diagnostics.append(
                f"{model_name} Rust field {name!r} type mismatch: "
                f"expected {expected_type!r}, got {actual_type!r}"
            )
    return diagnostics


def test_model_sync_diagnostics_name_missing_unexpected_and_mismatched_fields() -> None:
    diagnostics = _model_sync_diagnostics(
        model_name="IRModule",
        python_names=["functions", "metadata"],
        python_hints={"functions": tuple[IRFunction, ...], "metadata": dict[str, object]},
        expected_python={
            "functions": list[IRFunction],
            "structs": list[IRStructDefinition],
        },
        rust_fields=[("functions", "Vec<FutureFunction>"), ("imports", "Vec<String>")],
        expected_rust={
            "functions": "Vec<IRFunction>",
            "structs": "Vec<IRStructDefinition>",
        },
    )

    assert "IRModule Python missing fields: structs" in diagnostics
    assert "IRModule Python unexpected fields: metadata" in diagnostics
    assert "IRModule Rust missing fields: structs" in diagnostics
    assert "IRModule Rust unexpected fields: imports" in diagnostics
    assert any("Python field 'functions' type mismatch" in item for item in diagnostics)
    assert any("Rust field 'functions' type mismatch" in item for item in diagnostics)


def test_python_and_rust_module_models_have_synchronized_compatible_shapes() -> None:
    module_diagnostics = _model_sync_diagnostics(
        model_name="IRModule",
        python_names=[field.name for field in fields(IRModule)],
        python_hints=get_type_hints(IRModule),
        expected_python={
            "functions": list[IRFunction],
            "structs": list[IRStructDefinition],
        },
        rust_fields=_rust_struct_fields(RUST_IR_SOURCE / "module.rs", "IRModule"),
        expected_rust={
            "functions": "Vec<IRFunction>",
            "structs": "Vec<IRStructDefinition>",
        },
    )
    struct_diagnostics = _model_sync_diagnostics(
        model_name="IRStructDefinition",
        python_names=[field.name for field in fields(IRStructDefinition)],
        python_hints=get_type_hints(IRStructDefinition),
        expected_python={
            "name": str,
            "fields": tuple[tuple[str, IRType], ...],
        },
        rust_fields=_rust_struct_fields(
            RUST_IR_SOURCE / "structure.rs",
            "IRStructDefinition",
        ),
        expected_rust={"name": "String", "fields": "Vec<(String, IRType)>"},
    )

    diagnostics = [*module_diagnostics, *struct_diagnostics]
    assert not diagnostics, "IR module model synchronization errors:\n- " + "\n- ".join(
        diagnostics
    )
