from __future__ import annotations

from dataclasses import fields
import json

import pytest

from aether.analysis.cfg import CFGBuilder
from aether.analysis.dominators import DominatorAnalysis
from aether.ir.model import (
    IRArrayGet, IRArraySet, IRBasicBlock, IRBranch, IRConst, IRFunction,
    IRInvokeIndirect, IRJump, IRListGet, IRListSet, IRMatrixGet, IRMatrixSet,
    IRParameter, IRReturn, IRThrow, IRValue, IRVectorGet, IRVectorSet,
)
from aether.ir.types import (
    ArrayType, BoolType, IntType, ListType, MatrixType, VectorType, VoidType,
)
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto
from aether.ssa.general_builder import GeneralSSABuilder
from aether.ssa.lowering_policy import (
    LOWERING_POLICY_PATH, LoweringPolicyError, canonical_policy_json,
    check_lowering_policy_v1, load_lowering_policy,
)
from aether.ssa.model import (
    SSAArrayGet, SSAArraySet, SSAListGet, SSAListSet, SSAMatrixGet,
    SSAMatrixSet, SSAPhi, SSAVectorGet, SSAVectorSet,
)
import aether.ssa.renaming as renaming


def _void_function(blocks):
    return IRFunction("f", [], VoidType(), blocks)


def test_policy_artifact_is_canonical_and_structurally_current():
    parsed = json.loads(LOWERING_POLICY_PATH.read_text(encoding="utf-8"))
    assert parsed["lowering_policy_version"] == 1
    assert canonical_policy_json() == json.dumps(parsed, indent=2, sort_keys=True) + "\n"
    assert check_lowering_policy_v1() == ()


def test_unknown_policy_version_is_rejected():
    with pytest.raises(LoweringPolicyError, match="Unsupported SSA lowering policy"):
        load_lowering_policy(2)


def test_cfg_table_normal_exception_and_optional_exit_edges():
    i, b = IntType(), BoolType()
    callee = IRValue("callee", i)
    function = _void_function([
        IRBasicBlock("entry", [IRConst(callee, 0), IRInvokeIndirect(callee, (), None, IRValue("exc", i), "ok", "catch", IRValue("catch.event", i))]),
        IRBasicBlock("ok", [IRBranch(IRValue("cond", b), "exit", "catch")]),
        IRBasicBlock("catch", [IRThrow(IRValue("exc", i), None)]),
        IRBasicBlock("exit", [IRReturn(None)]),
    ])
    edges = CFGBuilder().build(function).edges
    assert [(e.source, e.target, e.kind) for e in edges] == [
        ("entry", "ok", "normal"), ("entry", "catch", "exceptional"),
        ("ok", "exit", "normal"), ("ok", "catch", "normal"),
    ]


def test_unreachable_block_is_isolated_and_omitted_from_ssa():
    function = _void_function([
        IRBasicBlock("entry", [IRJump("exit")]),
        IRBasicBlock("dead", [IRReturn(None)]),
        IRBasicBlock("exit", [IRReturn(None)]),
    ])
    dom = DominatorAnalysis(CFGBuilder().build(function)).compute()
    assert dom.dominators("dead") == {"dead"}
    assert dom.immediate_dominator("dead") is None
    ssa = GeneralSSABuilder().build_function(function)
    assert [block.name for block in ssa.blocks] == ["entry", "exit"]


def test_repeated_lowering_and_schema_v2_round_trip_are_identical():
    function = _void_function([IRBasicBlock("entry", [IRReturn(None)])])
    first = GeneralSSABuilder().build_function(function)
    second = GeneralSSABuilder().build_function(function)
    from aether.ssa.model import SSAModule
    first_dto = ssa_module_to_dto(SSAModule([first]), schema_version=2)
    second_dto = ssa_module_to_dto(SSAModule([second]), schema_version=2)
    assert first_dto == second_dto
    assert ssa_module_to_dto(ssa_module_from_dto(first_dto), schema_version=2) == first_dto


def test_policy_freezes_phi_predecessor_labels():
    policy = load_lowering_policy()
    assert "predecessor labels" in policy["phi_placement"]["operand_order"]
    assert SSAPhi.__dataclass_fields__["incoming"]


@pytest.mark.parametrize(
    ("ir_type", "ssa_type", "collection_type", "arguments"),
    [
        (IRArrayGet, SSAArrayGet, ArrayType(IntType()), "get"),
        (IRArraySet, SSAArraySet, ArrayType(IntType()), "set"),
        (IRListGet, SSAListGet, ListType(IntType()), "get"),
        (IRListSet, SSAListSet, ListType(IntType()), "set"),
        (IRVectorGet, SSAVectorGet, VectorType(IntType(), "row"), "get"),
        (IRVectorSet, SSAVectorSet, VectorType(IntType(), "row"), "set"),
        (IRMatrixGet, SSAMatrixGet, MatrixType(IntType()), "matrix_get"),
        (IRMatrixSet, SSAMatrixSet, MatrixType(IntType()), "matrix_set"),
    ],
)
def test_all_initial_ir_collection_accesses_explicitly_synthesize_checked(
    monkeypatch, ir_type, ssa_type, collection_type, arguments
):
    collection = IRParameter("collection", collection_type)
    index = IRParameter("index", IntType())
    value = IRParameter("value", IntType())
    result = IRValue("result", IntType())
    if arguments == "get":
        instruction = ir_type(result, collection, index)
    elif arguments == "set":
        instruction = ir_type(collection, index, value)
    elif arguments == "matrix_get":
        instruction = ir_type(result, collection, index, index, 2)
    else:
        instruction = ir_type(collection, index, index, value, 2)

    seen = []
    original = ssa_type

    def constructor(*args, **kwargs):
        seen.append(kwargs.get("bounds_checked", "omitted"))
        kwargs.setdefault("bounds_checked", False)
        return original(*args, **kwargs)

    monkeypatch.setattr(renaming, ssa_type.__name__, constructor)
    function = IRFunction(
        "checked", [collection, index, value], VoidType(),
        [IRBasicBlock("entry", [instruction, IRReturn()])],
    )
    lowered = GeneralSSABuilder().build_function(function)
    access = next(item for item in lowered.blocks[0].instructions if isinstance(item, ssa_type))
    assert seen == [True]
    assert access.bounds_checked is True


def test_policy_classifies_bounds_checked_as_synthesis_not_preservation():
    rule = load_lowering_policy()["bounds_checked_synthesis"]
    assert rule["classification"] == "synthesis, not preservation"
    assert rule["initial_ir_schema_v1_field"] == "absent"
    assert rule["ssa_constructor_default_is_authority"] is False


def test_initial_ir_collection_shapes_still_have_no_bounds_checked_field():
    initial_types = (
        IRArrayGet, IRArraySet, IRListGet, IRListSet,
        IRVectorGet, IRVectorSet, IRMatrixGet, IRMatrixSet,
    )
    assert all("bounds_checked" not in {field.name for field in fields(kind)} for kind in initial_types)
