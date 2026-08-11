from __future__ import annotations

from aether.ir.types import BoolType, ClassRefType, IntType, InterfaceType, StructType, VoidType
from aether.ssa.model import (
    SSAClassNew, SSAClassSet, SSABasicBlock, SSABranch, SSACall, SSACompareOp,
    SSAConst, SSAFunction, SSAJump, SSAModule, SSAParameter, SSAPhi, SSAReturn,
    SSAValue,
)
from aether.ssa.optimizer import LocalARCEliminator
from aether.ssa.verifier import SSAVerifier


I, B, BOX = IntType(), BoolType(), ClassRefType("Box")


def v(name, type_=I):
    return SSAValue(name, type_)


def retain(value):
    return SSACall("__aether_retain", (value,), builtin="__aether_retain")


def release(value):
    return SSACall("__aether_release", (value,), builtin="__aether_release")


def run(function, *, verify=True):
    result = LocalARCEliminator().run(SSAModule([function]))
    if verify:
        SSAVerifier(result.module).verify()
    return result


def arc_builtins(result):
    return [
        instruction.builtin
        for block in result.module.functions[0].blocks
        for instruction in block.instructions
        if isinstance(instruction, SSACall)
        and instruction.builtin in {"__aether_retain", "__aether_release"}
    ]


def test_eliminates_same_block_pair_across_scalar_operations():
    obj, one = v("obj", BOX), v("one")
    function = SSAFunction("local", [], VoidType(), [SSABasicBlock("entry", [
        SSAClassNew(obj), retain(obj), SSAConst(one, 1), release(obj), SSAReturn(),
    ])])
    result = run(function)
    assert result.changed
    assert arc_builtins(result) == []
    assert result.stats["phase1_eligible_pairs"] == 1
    assert result.stats["pairs_eliminated"] == 1


def test_eliminates_multiple_independent_pairs_and_iteration_local_loop_pair():
    first, second, loop_obj = v("first", BOX), v("second", BOX), v("loop_obj", BOX)
    condition = SSAParameter("condition", B)
    function = SSAFunction("pairs", [condition], VoidType(), [
        SSABasicBlock("entry", [
            SSAClassNew(first), SSAClassNew(second), retain(first), release(first),
            retain(second), release(second), SSAJump("loop"),
        ]),
        SSABasicBlock("loop", [
            SSAClassNew(loop_obj), retain(loop_obj), release(loop_obj),
            SSABranch(condition, "loop", "exit"),
        ]),
        SSABasicBlock("exit", [SSAReturn()]),
    ])
    result = run(function)
    assert arc_builtins(result) == []
    assert result.stats["pairs_eliminated"] == 3


def test_preserves_pair_across_any_call():
    obj = v("obj", BOX)
    function = SSAFunction("call", [], VoidType(), [SSABasicBlock("entry", [
        SSAClassNew(obj), retain(obj), SSACall("observe", (obj,)),
        release(obj), SSAReturn(),
    ])])
    result = run(function, verify=False)
    assert not result.changed
    assert arc_builtins(result) == ["__aether_retain", "__aether_release"]
    assert result.stats["blocked_by_call"] == 1


def test_preserves_field_escape_and_eliminates_cross_block_pair():
    owner, child = v("owner", BOX), v("child", BOX)
    field = SSAFunction("field", [], VoidType(), [SSABasicBlock("entry", [
        SSAClassNew(owner), SSAClassNew(child), retain(child),
        SSAClassSet(owner, 0, "child", child), release(child), SSAReturn(),
    ])])
    field_result = run(field, verify=False)
    assert not field_result.changed
    assert field_result.stats["blocked_by_escape"] == 1

    cross = SSAFunction("cross", [], VoidType(), [
        SSABasicBlock("entry", [SSAClassNew(child), retain(child), SSAJump("exit")]),
        SSABasicBlock("exit", [release(child), SSAReturn()]),
    ])
    cross_result = run(cross)
    assert cross_result.changed
    assert arc_builtins(cross_result) == []
    assert cross_result.stats["multi_block_candidates"] == 1
    assert cross_result.stats["multi_block_eliminated"] == 1


def test_eliminates_three_block_pair_across_scalar_work():
    obj, one = v("obj", BOX), v("one")
    function = SSAFunction("linear", [], VoidType(), [
        SSABasicBlock("entry", [SSAClassNew(obj), retain(obj), SSAJump("work")]),
        SSABasicBlock("work", [SSAConst(one, 1), SSAJump("exit")]),
        SSABasicBlock("exit", [release(obj), SSAReturn()]),
    ])
    result = run(function)
    assert arc_builtins(result) == []
    assert result.stats["multi_block_eliminated"] == 1


def test_preserves_multiblock_pair_at_branch_and_join():
    condition = SSAParameter("condition", B)
    obj = v("obj", BOX)
    function = SSAFunction("diamond", [condition], VoidType(), [
        SSABasicBlock("entry", [SSAClassNew(obj), retain(obj),
                                SSABranch(condition, "left", "right")]),
        SSABasicBlock("left", [SSAJump("exit")]),
        SSABasicBlock("right", [SSAJump("exit")]),
        SSABasicBlock("exit", [release(obj), SSAReturn()]),
    ])
    result = run(function)
    assert not result.changed
    assert arc_builtins(result) == ["__aether_retain", "__aether_release"]
    # Post-dominance holds, but the structural proof independently rejects it.
    assert result.stats["blocked_by_branch"] == 1


def test_preserves_multiblock_pair_with_join_predecessor():
    condition = SSAParameter("condition", B)
    obj = v("obj", BOX)
    function = SSAFunction("join", [condition], VoidType(), [
        SSABasicBlock("entry", [SSAClassNew(obj),
                                SSABranch(condition, "retain", "other")]),
        SSABasicBlock("retain", [retain(obj), SSAJump("exit")]),
        SSABasicBlock("other", [SSAJump("exit")]),
        SSABasicBlock("exit", [release(obj), SSAReturn()]),
    ])
    result = run(function, verify=False)
    assert not result.changed
    assert result.stats["blocked_by_missing_dominance"] == 1


def test_preserves_multiblock_pair_across_call():
    obj = v("obj", BOX)
    function = SSAFunction("cross_call", [], VoidType(), [
        SSABasicBlock("entry", [SSAClassNew(obj), retain(obj), SSAJump("work")]),
        SSABasicBlock("work", [SSACall("observe", (obj,)), SSAJump("exit")]),
        SSABasicBlock("exit", [release(obj), SSAReturn()]),
    ])
    result = run(function, verify=False)
    assert not result.changed
    assert result.stats["blocked_by_call"] == 1


def test_preserves_phi_aggregate_interface_and_constructor_contexts():
    condition = SSAParameter("condition", B)
    left, right, merged = v("left", BOX), v("right", BOX), v("merged", BOX)
    phi = SSAFunction("phi", [condition], VoidType(), [
        SSABasicBlock("entry", [SSAClassNew(left), SSAClassNew(right), SSABranch(condition, "a", "b")]),
        SSABasicBlock("a", [SSAJump("merge")]),
        SSABasicBlock("b", [SSAJump("merge")]),
        SSABasicBlock("merge", [SSAPhi(merged, (("a", left), ("b", right))), retain(merged), release(merged), SSAReturn()]),
    ])
    assert run(phi).stats["blocked_by_different_identity"] == 1

    for name, type_, expected in (
        ("aggregate", StructType("Owned"), "blocked_by_aggregate"),
        ("interface", InterfaceType("Display"), "blocked_by_interface"),
        ("thing.__init__", BOX, "blocked_by_methodresult_constructor"),
    ):
        item = v(name.replace(".", "_"), type_)
        function = SSAFunction(name, [], VoidType(), [SSABasicBlock("entry", [
            SSAClassNew(item), retain(item), release(item), SSAReturn(),
        ])])
        result = run(function, verify=False)
        assert not result.changed
        assert result.stats[expected] == 1
