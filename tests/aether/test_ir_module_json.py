from __future__ import annotations

from pathlib import Path

import pytest

from aether.ir.dto import (
    IRDTOError,
    IRDTOJSONError,
    IRDTOSchemaVersionError,
    ir_module_from_json,
    ir_module_to_json,
)
from aether.ir.model import (
    IRBasicBlock,
    IRBranch,
    IRConst,
    IRFunction,
    IRInitDefault,
    IRModule,
    IRParameter,
    IRReturn,
    IRSourceLocation,
    IRStorage,
    IRStructDefinition,
)
from aether.ir.types import ArrayType, BoolType, IntType, ListType, StringType, StructType


GOLDEN_PATH = Path(__file__).parent / "rust_migration" / "fixtures" / "ir_module_v1_golden.json"


def _golden_module() -> IRModule:
    answer = IRStorage("answer", IntType())
    condition = IRParameter("condition", BoolType())
    return IRModule(
        functions=[
            IRFunction(
                "choose",
                [condition],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRInitDefault(
                                answer,
                                IRSourceLocation(4, 3, "fixtures/golden.ae"),
                            ),
                            IRBranch(condition, "selected", "selected"),
                        ],
                    ),
                    IRBasicBlock(
                        "selected",
                        [IRConst(answer, 7), IRReturn(answer, answer)],
                    ),
                ],
            )
        ],
        structs=[
            IRStructDefinition(
                "Envelope",
                (
                    ("payload", ArrayType(StructType("Point"))),
                    ("labels", ListType(StringType())),
                ),
            )
        ],
    )


def test_python_model_canonical_json_matches_checked_in_v1_golden() -> None:
    expected = GOLDEN_PATH.read_text(encoding="utf-8")

    assert ir_module_to_json(_golden_module()) == expected


def test_v1_golden_decodes_and_reencodes_byte_for_byte() -> None:
    expected = GOLDEN_PATH.read_bytes()

    module = ir_module_from_json(expected)

    assert module == _golden_module()
    assert ir_module_to_json(module).encode("utf-8") == expected


def test_canonical_json_is_deterministic_utf8_sorted_and_preserves_list_order() -> None:
    module = _golden_module()

    first = ir_module_to_json(module)
    second = ir_module_to_json(module)

    assert first == second
    assert first.encode("utf-8").decode("utf-8") == first
    assert first.endswith("\n")
    assert first.index('"functions"') < first.index('"schema_version"') < first.index('"structs"')
    decoded = ir_module_from_json(first)
    assert [function.name for function in decoded.functions] == ["choose"]
    assert [block.name for block in decoded.functions[0].blocks] == ["entry", "selected"]
    assert [name for name, _type in decoded.structs[0].fields] == ["payload", "labels"]


def test_canonical_json_emits_non_ascii_text_as_utf8() -> None:
    module = IRModule(structs=[IRStructDefinition("Señal", (("año", IntType()),))])

    encoded = ir_module_to_json(module)

    assert '"Señal"' in encoded
    assert '"año"' in encoded
    assert "\\u00f1" not in encoded
    assert ir_module_from_json(encoded.encode("utf-8")) == module


def test_decoder_accepts_noncanonical_spacing_but_reencodes_canonically() -> None:
    noncanonical = '{ "structs": [], "functions": [], "schema_version": 1 }'

    module = ir_module_from_json(noncanonical)

    assert ir_module_to_json(module) == (
        '{\n  "functions": [],\n  "schema_version": 1,\n  "structs": []\n}\n'
    )


@pytest.mark.parametrize(
    "payload",
    [
        '{"schema_version":1,"schema_version":1,"functions":[],"structs":[]}',
        '{"schema_version":1,"functions":[],"structs":[],"extra":{"x":1,"x":2}}',
    ],
)
def test_duplicate_json_object_keys_are_rejected_at_every_depth(payload: str) -> None:
    with pytest.raises(IRDTOJSONError, match="Duplicate IR module JSON object key"):
        ir_module_from_json(payload)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_nonstandard_or_nonfinite_json_numbers_are_rejected(number: str) -> None:
    payload = f'{{"schema_version":1,"functions":[],"structs":[],"number":{number}}}'

    with pytest.raises(IRDTOJSONError, match="(Non-standard|Non-finite) JSON"):
        ir_module_from_json(payload)


def test_encoder_rejects_nonfinite_model_constants_with_dto_error() -> None:
    result = IRStorage("result", IntType())
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRConst(result, float("nan"))])],
            )
        ]
    )

    with pytest.raises(IRDTOJSONError, match="Cannot encode IR module as canonical JSON"):
        ir_module_to_json(module)


@pytest.mark.parametrize(
    "payload",
    ["", "{", "[] trailing", b"\xff"],
)
def test_malformed_or_non_utf8_json_never_leaks_raw_json_errors(payload: object) -> None:
    with pytest.raises(IRDTOJSONError):
        ir_module_from_json(payload)  # type: ignore[arg-type]


def test_escaped_unpaired_surrogate_is_rejected_as_non_utf8_text() -> None:
    payload = '{"schema_version":1,"functions":[],"structs":[{"name":"\\ud800","fields":[]}]}'

    with pytest.raises(IRDTOJSONError, match="contains non-UTF-8 text"):
        ir_module_from_json(payload)


@pytest.mark.parametrize("payload", [None, 1, {}, []])
def test_json_decoder_rejects_non_text_inputs_with_dto_error(payload: object) -> None:
    with pytest.raises(IRDTOJSONError, match="input must be str, bytes, or bytearray"):
        ir_module_from_json(payload)  # type: ignore[arg-type]


def test_json_root_schema_version_is_validated_by_dto_boundary() -> None:
    payload = '{"schema_version":2,"functions":[],"structs":[]}'

    with pytest.raises(IRDTOSchemaVersionError, match="schema version 2; expected 1"):
        ir_module_from_json(payload)

    with pytest.raises(IRDTOSchemaVersionError, match="schema version 2; expected 1"):
        ir_module_to_json(IRModule(), schema_version=2)


def test_json_shape_errors_remain_dto_specific() -> None:
    with pytest.raises(IRDTOError, match="missing fields: structs"):
        ir_module_from_json('{"schema_version":1,"functions":[]}')


def test_semantically_invalid_but_structurally_valid_json_still_decodes() -> None:
    function = (
        '{"blocks":[],"name":"duplicate","parameters":[],"return_type":{"tag":"void"}}'
    )
    payload = (
        '{"functions":['
        + function
        + ","
        + function
        + '],"schema_version":1,"structs":[]}'
    )

    module = ir_module_from_json(payload)

    assert [item.name for item in module.functions] == ["duplicate", "duplicate"]
