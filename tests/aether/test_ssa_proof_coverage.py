from __future__ import annotations

from aether.ir.types import ArrayType, BoolType, IntType, ListType, VoidType
from aether.ssa.analysis import ProofCoverageAudit
from aether.ssa.model import (
    SSAArrayGet, SSAArrayNew, SSAArraySlice, SSABasicBlock, SSAConst,
    SSAFunction, SSAInvoke, SSAListGet, SSAListNew, SSAListPush, SSAModule,
    SSAReturn, SSAValue,
)


I = IntType()


def value(name, type_=I):
    return SSAValue(name, type_)


def test_discovers_and_classifies_safe_unsafe_and_unknown_checks() -> None:
    item, zero, two, three, unknown = (value(name) for name in ("item", "zero", "two", "three", "unknown"))
    array = value("array", ArrayType(I))
    function = SSAFunction("coverage", [unknown], VoidType(), [SSABasicBlock("entry", [
        SSAConst(item, 7), SSAConst(zero, 0), SSAConst(two, 2), SSAConst(three, 3),
        SSAArrayNew(array, (item, item)),
        SSAArrayGet(value("safe"), array, zero),
        SSAArrayGet(value("unsafe"), array, three),
        SSAArrayGet(value("unknown_result"), array, unknown),
        SSAReturn(),
    ])])

    report = ProofCoverageAudit().audit(SSAModule([function]))

    assert [check.proof for check in report.checks] == ["PROVEN_SAFE", "PROVEN_UNSAFE", "UNKNOWN"]
    assert report.checks[-1].unknown_reason == "UNKNOWN_RANGE"
    assert report.summary()["domains"]["Array"] == {
        "total": 3, "PROVEN_SAFE": 1, "PROVEN_UNSAFE": 1, "UNKNOWN": 1,
        "unknown_reasons": {"UNKNOWN_RANGE": 1}, "safe_percentage": 33.33,
    }


def test_slice_accepts_half_open_end_equal_to_length() -> None:
    item, zero, two = value("item"), value("zero"), value("two")
    array = value("array", ArrayType(I))
    sliced = value("sliced", ArrayType(I))
    function = SSAFunction("slice", [], VoidType(), [SSABasicBlock("entry", [
        SSAConst(item, 1), SSAConst(zero, 0), SSAConst(two, 2),
        SSAArrayNew(array, (item, item)), SSAArraySlice(sliced, array, zero, two), SSAReturn(),
    ])])
    check = ProofCoverageAudit().audit([function]).checks[0]
    assert check.kind == "array_slice" and check.proof == "PROVEN_SAFE"


def test_list_mutation_attribution_is_conservative() -> None:
    item, zero = value("item"), value("zero")
    listing = value("list", ListType(I))
    function = SSAFunction("mutation", [], VoidType(), [SSABasicBlock("entry", [
        SSAConst(item, 1), SSAConst(zero, 0), SSAListNew(listing, (item,)),
        SSAListPush(listing, item), SSAListGet(value("result"), listing, zero), SSAReturn(),
    ])])
    check = ProofCoverageAudit().audit([function]).checks[0]
    assert check.proof == "UNKNOWN" and check.unknown_reason == "MUTATION_INVALIDATION"


def test_json_is_stable_and_audit_does_not_transform_ssa() -> None:
    item, zero = value("item"), value("zero")
    array = value("array", ArrayType(I))
    block = SSABasicBlock("entry", [SSAConst(item, 1), SSAConst(zero, 0), SSAArrayNew(array, (item,)), SSAArrayGet(value("result"), array, zero), SSAReturn()])
    module = SSAModule([SSAFunction("stable", [], VoidType(), [block])])
    before = tuple(block.instructions)
    first = ProofCoverageAudit().audit(module).to_json()
    second = ProofCoverageAudit().audit(module).to_json()
    assert first == second and tuple(block.instructions) == before
    assert '"schema_version": 1' in first


def test_exceptional_call_attribution() -> None:
    item, zero, event = value("item"), value("zero"), value("event")
    listing = value("list", ListType(I))
    function = SSAFunction("exception", [], VoidType(), [
        SSABasicBlock("entry", [
            SSAConst(item, 1), SSAConst(zero, 0), SSAListNew(listing, (item,)),
            SSAInvoke("unknown", (listing,), None, event, "normal", "handler"),
        ]),
        SSABasicBlock("normal", [SSAListGet(value("result"), listing, zero), SSAReturn()]),
        SSABasicBlock("handler", [SSAReturn()]),
    ], may_throw=True)
    check = ProofCoverageAudit().audit([function]).checks[0]
    assert check.proof == "UNKNOWN" and check.unknown_reason == "CALL_INVALIDATION"
