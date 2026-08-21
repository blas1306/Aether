from __future__ import annotations

import copy
import pytest

from aether.ir.types import IntType
from aether.ssa.dto import (
    SSADTOError, ssa_module_from_dto, ssa_module_to_dto, ssa_module_to_json,
)
from aether.ssa.model import (
    SSAArrayGet, SSAArraySet, SSABasicBlock, SSAFunction, SSAListGet, SSAListSet,
    SSAMatrixGet, SSAMatrixSet, SSAModule, SSAValue, SSAVectorGet, SSAVectorSet,
)


def _value(name: str) -> SSAValue:
    return SSAValue(name, IntType())


FACTORIES = {
    "array_get": lambda checked: SSAArrayGet(_value("r"), _value("a"), _value("i"), bounds_checked=checked),
    "array_set": lambda checked: SSAArraySet(_value("a"), _value("i"), _value("v"), checked),
    "list_get": lambda checked: SSAListGet(_value("r"), _value("l"), _value("i"), bounds_checked=checked),
    "list_set": lambda checked: SSAListSet(_value("l"), _value("i"), _value("v"), checked),
    "vector_get": lambda checked: SSAVectorGet(_value("r"), _value("v"), _value("i"), checked),
    "vector_set": lambda checked: SSAVectorSet(_value("v"), _value("i"), _value("x"), checked),
    "matrix_get": lambda checked: SSAMatrixGet(_value("r"), _value("m"), _value("row"), _value("col"), 4, checked),
    "matrix_set": lambda checked: SSAMatrixSet(_value("m"), _value("row"), _value("col"), _value("v"), 4, checked),
}


def _module(instruction) -> SSAModule:
    return SSAModule([SSAFunction("f", [], IntType(), [SSABasicBlock("entry", [instruction])], "entry")], [])


@pytest.mark.parametrize("kind", FACTORIES)
@pytest.mark.parametrize("checked", [False, True])
def test_all_bounds_checked_values_round_trip_in_schema_v2(kind: str, checked: bool) -> None:
    dto = ssa_module_to_dto(_module(FACTORIES[kind](checked)))
    encoded = dto["functions"][0]["blocks"][0]["instructions"][0]
    assert dto["schema_version"] == 2
    assert encoded["kind"] == kind
    assert encoded["bounds_checked"] is checked
    assert ssa_module_to_dto(ssa_module_from_dto(dto)) == dto


def test_v1_is_explicit_and_does_not_manufacture_missing_semantics() -> None:
    dto = ssa_module_to_dto(_module(FACTORIES["array_get"](True)))
    dto["schema_version"] = 1
    dto["functions"][0]["blocks"][0]["instructions"][0].pop("bounds_checked")
    with pytest.raises(SSADTOError, match="cannot be decoded losslessly"):
        ssa_module_from_dto(dto)
    with pytest.raises(SSADTOError, match="cannot represent required field"):
        ssa_module_to_dto(_module(FACTORIES["array_get"](True)), schema_version=1)


def test_frozen_v1_empty_envelope_and_v2_serialization_are_deterministic() -> None:
    empty = SSAModule([], [])
    assert ssa_module_to_dto(empty, schema_version=1) == {
        "schema_version": 1,
        "representation": "aether_ssa",
        "functions": [],
        "structs": [],
    }
    module = _module(FACTORIES["matrix_set"](False))
    assert ssa_module_to_dto(module) == ssa_module_to_dto(module)
    assert ssa_module_to_json(module, indent=None) == ssa_module_to_json(module, indent=None)


def test_version_dispatch_and_required_v2_field_are_strict() -> None:
    dto = ssa_module_to_dto(_module(FACTORIES["vector_get"](False)))
    missing = copy.deepcopy(dto)
    missing["functions"][0]["blocks"][0]["instructions"][0].pop("bounds_checked")
    with pytest.raises(SSADTOError, match="missing bounds_checked"):
        ssa_module_from_dto(missing)
    malformed = copy.deepcopy(dto)
    malformed["functions"][0]["blocks"][0]["instructions"][0]["bounds_checked"] = 1
    with pytest.raises(SSADTOError, match="must be boolean"):
        ssa_module_from_dto(malformed)
    for version in (0, 3, "2"):
        unsupported = {**dto, "schema_version": version}
        with pytest.raises(SSADTOError, match="Unsupported SSA schema version"):
            ssa_module_from_dto(unsupported)
