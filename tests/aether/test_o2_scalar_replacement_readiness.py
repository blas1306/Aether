from pathlib import Path

from aether.ir.model import IRStructDefinition
from aether.ir.types import IntType, StringType, StructType
from aether.ssa import model as m
from aether.ssa.analysis.scalar_replacement import (
    FieldUseKind, aggregate_field_uses, aggregate_reconstruction_boundaries,
    classify_scalar_replacement, scalar_replacement_profitability,
    scalar_replacement_region,
)
from scripts.o2_scalar_replacement_readiness import generate


PROBE_CASES = {
    "scalar-only struct", "unused scalar field", "repeated struct_get",
    "struct_set chain", "scalar-only loop-carried aggregate", "aggregate phi",
    "aggregate passed to function", "aggregate returned", "aggregate equality",
    "String-containing struct", "List-containing struct", "nested struct",
    "method receiver", "collection storage", "escaping aggregate",
}


def _field_only(field_types=(IntType(), IntType()), repeated=False):
    struct = IRStructDefinition("Pair", tuple((f"f{n}", type_) for n, type_ in enumerate(field_types)))
    value = m.SSAParameter("pair", StructType("Pair"))
    instructions = [m.SSAStructGet(m.SSAValue("x", field_types[0]), value, 0, "f0")]
    if repeated:
        instructions.append(m.SSAStructGet(m.SSAValue("y", field_types[0]), value, 0, "f0"))
    function = m.SSAFunction("probe", [value], IntType(), [m.SSABasicBlock("entry", instructions)])
    return function, value, (struct,)


def test_o210_declares_all_required_synthetic_probe_shapes() -> None:
    assert len(PROBE_CASES) == 15
    assert "scalar-only loop-carried aggregate" in PROBE_CASES
    assert "escaping aggregate" in PROBE_CASES


def test_scalar_only_field_use_is_ready_and_repeated_get_is_profitable() -> None:
    function, value, structs = _field_only(repeated=True)
    assert classify_scalar_replacement(function, value, structs) == "SAFE_SCALAR_ONLY"
    assert [use.kind for use in aggregate_field_uses(function, value)] == [
        FieldUseKind.FIELD_READ, FieldUseKind.FIELD_READ]
    assert scalar_replacement_profitability(function, value)["field_read"] == 2
    assert scalar_replacement_region(function, value) == "SAME_BLOCK"
    assert aggregate_reconstruction_boundaries(function, value) == ()


def test_owned_component_requires_ownership_aware_replacement() -> None:
    function, value, structs = _field_only((StringType(), IntType()))
    assert classify_scalar_replacement(function, value, structs) == "OWNERSHIP_AWARE_REQUIRED"


def test_o210_freezes_and_classifies_the_exact_o298_candidates() -> None:
    root = Path(__file__).resolve().parents[2]
    report = generate(root, ("examples/expense_tracker/Main.ae",))
    candidates = report["exact_four_candidates"]
    assert [(row["candidate_id"], row["ssa_value"]) for row in candidates] == [
        ("SR-001", "336"), ("SR-002", "437"), ("SR-003", "516"), ("SR-004", "791")]
    assert {row["readiness_class"] for row in candidates} == {"OWNERSHIP_AWARE_REQUIRED"}
    assert all(row["field_only"] and row["escape"] == "NO_ESCAPE" for row in candidates)
    assert all(row["ownership_bearing_field_count"] == 1 for row in candidates)
    assert report["recommendation"] == "PROCEED_TO_AGGREGATE_COPY_ELISION_INSTEAD"
    assert report["production_behavior_changed"] is False
