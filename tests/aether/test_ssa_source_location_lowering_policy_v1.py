from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from aether.ir.model import (
    IRArrayCopy, IRArrayGet, IRArraySlice, IRBasicBlock, IRFunction,
    IRListCopy, IRListGet, IRListSlice, IRParameter, IRReturn,
    IRSourceLocation, IRValue,
)
from aether.ir.types import ArrayType, IntType, ListType, VoidType
from aether.ssa.general_builder import GeneralSSABuilder

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/check_ssa_source_location_lowering_policy_v1.py"
SPEC = importlib.util.spec_from_file_location("source_location_policy", CHECKER)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def _lower_six(locations):
    integer = IntType()
    array_type = ArrayType(integer)
    list_type = ListType(integer)
    array = IRParameter("array", array_type)
    list_value = IRParameter("list", list_type)
    index = IRParameter("index", integer)
    instructions = [
        IRArrayCopy(IRValue("ac", array_type), array, locations[0]),
        IRArrayGet(IRValue("ag", integer), array, index, False, None, locations[1]),
        IRArraySlice(IRValue("as", array_type), array, index, index, locations[2]),
        IRListCopy(IRValue("lc", list_type), list_value, locations[3]),
        IRListGet(IRValue("lg", integer), list_value, index, False, None, locations[4]),
        IRListSlice(IRValue("ls", list_type), list_value, index, index, locations[5]),
        IRReturn(),
    ]
    function = IRFunction(
        "collections", [array, list_value, index], VoidType(),
        [IRBasicBlock("entry", instructions)],
    )
    return GeneralSSABuilder().build_function(function).blocks[0].instructions[:-1]


def test_complete_policy_inventory_and_implementation_are_current():
    assert checker.check() == ()


def test_six_collection_mappings_preserve_distinct_locations_exactly():
    locations = tuple(
        IRSourceLocation(101 + offset, 201 + offset, f"collection-{offset}.ae")
        for offset in range(6)
    )
    assert tuple(item.source_location for item in _lower_six(locations)) == locations


@pytest.mark.parametrize("missing", range(6))
def test_absent_location_is_not_inherited_from_neighbor(missing):
    locations = [IRSourceLocation(301 + offset, 401 + offset, None) for offset in range(6)]
    locations[missing] = None
    lowered = _lower_six(locations)
    assert lowered[missing].source_location is None
    assert [item.source_location for index, item in enumerate(lowered) if index != missing] == [
        location for index, location in enumerate(locations) if index != missing
    ]
