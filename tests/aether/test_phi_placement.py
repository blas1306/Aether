from __future__ import annotations

from aether.analysis.cfg import CFGBuilder
from aether.analysis.dominance_frontier import DominanceFrontierAnalysis
from aether.analysis.dominators import DominatorAnalysis
from aether.ir import (
    BoolType,
    IntType,
    IRBasicBlock,
    IRBranch,
    IRConst,
    IRFunction,
    IRJump,
    IRLoad,
    IRReturn,
    IRStore,
    IRValue,
)
from aether.ssa import PhiPlacement


def _place(function: IRFunction) -> dict[str, set[str]]:
    cfg = CFGBuilder().build(function)
    dominators = DominatorAnalysis(cfg).compute()
    dominance_frontier = DominanceFrontierAnalysis(cfg, dominators).compute()
    return PhiPlacement(function, cfg, dominators, dominance_frontier).place()


def _value(name: str) -> IRValue:
    return IRValue(name, IntType())


def _condition(name: str = "cond") -> IRValue:
    return IRValue(name, BoolType())


def test_linear_function_has_no_phi_placements() -> None:
    x = _value("x")
    stored = _value("0")
    loaded = _value("1")
    function = IRFunction(
        "linear",
        [],
        IntType(),
        [
            IRBasicBlock(
                "entry",
                [
                    IRConst(stored, 1),
                    IRStore(x, stored),
                    IRLoad(loaded, x),
                    IRReturn(loaded),
                ],
            )
        ],
    )

    assert _place(function) == {}


def test_if_else_assigning_both_branches_places_phi_in_merge() -> None:
    x = _value("x")
    then_value = _value("then_value")
    else_value = _value("else_value")
    loaded = _value("loaded")
    function = IRFunction(
        "choose",
        [],
        IntType(),
        [
            IRBasicBlock("entry", [IRBranch(_condition(), "then0", "else0")]),
            IRBasicBlock(
                "then0",
                [IRConst(then_value, 1), IRStore(x, then_value), IRJump("merge0")],
            ),
            IRBasicBlock(
                "else0",
                [IRConst(else_value, 2), IRStore(x, else_value), IRJump("merge0")],
            ),
            IRBasicBlock("merge0", [IRLoad(loaded, x), IRReturn(loaded)]),
        ],
    )

    assert _place(function) == {"x": {"merge0"}}


def test_if_else_assigning_one_branch_places_phi_in_merge() -> None:
    x = _value("x")
    then_value = _value("then_value")
    loaded = _value("loaded")
    function = IRFunction(
        "maybeAssign",
        [],
        IntType(),
        [
            IRBasicBlock("entry", [IRBranch(_condition(), "then0", "else0")]),
            IRBasicBlock(
                "then0",
                [IRConst(then_value, 1), IRStore(x, then_value), IRJump("merge0")],
            ),
            IRBasicBlock("else0", [IRJump("merge0")]),
            IRBasicBlock("merge0", [IRLoad(loaded, x), IRReturn(loaded)]),
        ],
    )

    assert _place(function) == {"x": {"merge0"}}


def test_while_countdown_places_phi_in_condition() -> None:
    n = _value("n")
    initial = _value("initial")
    next_value = _value("next")
    loaded = _value("loaded")
    function = IRFunction(
        "countdown",
        [],
        IntType(),
        [
            IRBasicBlock(
                "entry",
                [IRConst(initial, 3), IRStore(n, initial), IRJump("cond0")],
            ),
            IRBasicBlock("cond0", [IRBranch(_condition(), "body0", "exit0")]),
            IRBasicBlock(
                "body0",
                [IRConst(next_value, 2), IRStore(n, next_value), IRJump("cond0")],
            ),
            IRBasicBlock("exit0", [IRLoad(loaded, n), IRReturn(loaded)]),
        ],
    )

    assert _place(function) == {"n": {"cond0"}}


def test_sum_to_places_phi_for_i_and_sum_in_condition() -> None:
    i = _value("i")
    total = _value("sum")
    zero = _value("zero")
    one = _value("one")
    next_i = _value("next_i")
    next_sum = _value("next_sum")
    loaded = _value("loaded")
    function = IRFunction(
        "sumTo",
        [],
        IntType(),
        [
            IRBasicBlock(
                "entry",
                [
                    IRConst(zero, 0),
                    IRConst(one, 1),
                    IRStore(i, one),
                    IRStore(total, zero),
                    IRJump("cond0"),
                ],
            ),
            IRBasicBlock("cond0", [IRBranch(_condition(), "body0", "exit0")]),
            IRBasicBlock(
                "body0",
                [
                    IRConst(next_i, 2),
                    IRStore(i, next_i),
                    IRConst(next_sum, 3),
                    IRStore(total, next_sum),
                    IRJump("cond0"),
                ],
            ),
            IRBasicBlock("exit0", [IRLoad(loaded, total), IRReturn(loaded)]),
        ],
    )

    assert _place(function) == {"i": {"cond0"}, "sum": {"cond0"}}


def test_nested_if_places_phis_at_inner_and_outer_merges() -> None:
    x = _value("x")
    inner_then_value = _value("inner_then")
    inner_else_value = _value("inner_else")
    outer_else_value = _value("outer_else")
    loaded = _value("loaded")
    function = IRFunction(
        "nested",
        [],
        IntType(),
        [
            IRBasicBlock("entry", [IRBranch(_condition("outer"), "then0", "else0")]),
            IRBasicBlock("then0", [IRBranch(_condition("inner"), "then1", "else1")]),
            IRBasicBlock(
                "then1",
                [
                    IRConst(inner_then_value, 1),
                    IRStore(x, inner_then_value),
                    IRJump("merge_inner"),
                ],
            ),
            IRBasicBlock(
                "else1",
                [
                    IRConst(inner_else_value, 2),
                    IRStore(x, inner_else_value),
                    IRJump("merge_inner"),
                ],
            ),
            IRBasicBlock("merge_inner", [IRJump("merge_outer")]),
            IRBasicBlock(
                "else0",
                [
                    IRConst(outer_else_value, 3),
                    IRStore(x, outer_else_value),
                    IRJump("merge_outer"),
                ],
            ),
            IRBasicBlock("merge_outer", [IRLoad(loaded, x), IRReturn(loaded)]),
        ],
    )

    assert _place(function) == {"x": {"merge_inner", "merge_outer"}}


def test_unreachable_blocks_do_not_break_phi_placement() -> None:
    x = _value("x")
    dead_value = _value("dead_value")
    function = IRFunction(
        "hasDeadBlocks",
        [],
        IntType(),
        [
            IRBasicBlock("entry", [IRReturn()]),
            IRBasicBlock(
                "dead_left",
                [IRConst(dead_value, 1), IRStore(x, dead_value), IRJump("dead_merge")],
            ),
            IRBasicBlock("dead_right", [IRJump("dead_merge")]),
            IRBasicBlock("dead_merge", [IRReturn()]),
        ],
    )

    assert _place(function) == {}
