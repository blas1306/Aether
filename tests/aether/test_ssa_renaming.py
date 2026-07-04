from __future__ import annotations

import re

import pytest

from aether.analysis.cfg import CFG, CFGBuilder, CFGEdge, CFGNode
from aether.analysis.dominance_frontier import DominanceFrontierAnalysis
from aether.analysis.dominators import DominatorAnalysis
from aether.ir import (
    BoolType,
    IntType,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRJump,
    IRLoad,
    IRModule,
    IRParameter,
    IRReturn,
    IRStore,
    IRValue,
    StringType,
)
from aether.ssa import (
    PhiPlacement,
    SSABuilder,
    SSAModule,
    SSAPhi,
    SSARenameError,
    SSARenamer,
    SSAVerifier,
    print_ssa,
)


def _rename(function: IRFunction) -> SSAModule:
    cfg = CFGBuilder().build(function)
    dominators = DominatorAnalysis(cfg).compute()
    dominance_frontier = DominanceFrontierAnalysis(cfg, dominators).compute()
    placement = PhiPlacement(function, cfg, dominators, dominance_frontier).place()
    result = SSARenamer(function, cfg, dominators, placement).rename()
    module = SSAModule([result.function])
    assert SSAVerifier(module).verify() is module
    return module


def _assert_rename_error(function: IRFunction, message: str) -> None:
    cfg = CFGBuilder().build(function)
    dominators = DominatorAnalysis(cfg).compute()
    dominance_frontier = DominanceFrontierAnalysis(cfg, dominators).compute()
    placement = PhiPlacement(function, cfg, dominators, dominance_frontier).place()

    with pytest.raises(SSARenameError, match=re.escape(message)):
        SSARenamer(function, cfg, dominators, placement).rename()


def _value(name: str) -> IRValue:
    return IRValue(name, IntType())


def _condition(name: str = "condition") -> IRParameter:
    return IRParameter(name, BoolType())


def test_renames_linear_store_and_load() -> None:
    slot = _value("x")
    stored = _value("0")
    loaded = _value("1")
    function = IRFunction(
        "read_x",
        [],
        IntType(),
        [
            IRBasicBlock(
                "entry",
                [
                    IRConst(stored, 5),
                    IRStore(slot, stored),
                    IRLoad(loaded, slot),
                    IRReturn(loaded),
                ],
            )
        ],
    )

    assert print_ssa(_rename(function)) == (
        "func @read_x() -> int {\n"
        "entry:\n"
        "    %0: int = const 5\n"
        "    return %0\n"
        "}"
    )


def test_renames_if_else_with_general_phi_placement() -> None:
    condition = _condition()
    slot = _value("x")
    then_value = _value("0")
    else_value = _value("1")
    loaded = _value("2")
    function = IRFunction(
        "choose",
        [condition],
        IntType(),
        [
            IRBasicBlock("entry", [IRBranch(condition, "then0", "else0")]),
            IRBasicBlock(
                "then0",
                [IRConst(then_value, 1), IRStore(slot, then_value), IRJump("merge0")],
            ),
            IRBasicBlock(
                "else0",
                [IRConst(else_value, 2), IRStore(slot, else_value), IRJump("merge0")],
            ),
            IRBasicBlock("merge0", [IRLoad(loaded, slot), IRReturn(loaded)]),
        ],
    )

    module = _rename(function)
    merge_instructions = module.functions[0].blocks[3].instructions

    assert isinstance(merge_instructions[0], SSAPhi)
    assert print_ssa(module) == (
        "func @choose(%condition: bool) -> int {\n"
        "entry:\n"
        "    branch %condition, then0, else0\n"
        "\n"
        "then0:\n"
        "    %0: int = const 1\n"
        "    jump merge0\n"
        "\n"
        "else0:\n"
        "    %1: int = const 2\n"
        "    jump merge0\n"
        "\n"
        "merge0:\n"
        "    %2: int = phi(then0: %0, else0: %1)\n"
        "    return %2\n"
        "}"
    )


def test_renames_while_countdown_with_loop_carried_phi() -> None:
    int_type = IntType()
    parameter = IRParameter("n", int_type)
    slot = IRValue("n", int_type)
    loop_value = _value("0")
    zero = _value("1")
    condition = IRValue("2", BoolType())
    body_value = _value("3")
    one = _value("4")
    next_value = _value("5")
    result = _value("6")
    function = IRFunction(
        "countdown",
        [parameter],
        int_type,
        [
            IRBasicBlock("entry", [IRStore(slot, parameter), IRJump("cond0")]),
            IRBasicBlock(
                "cond0",
                [
                    IRLoad(loop_value, slot),
                    IRConst(zero, 0),
                    IRCompareOp(condition, "gt", loop_value, zero),
                    IRBranch(condition, "body0", "exit0"),
                ],
            ),
            IRBasicBlock(
                "body0",
                [
                    IRLoad(body_value, slot),
                    IRConst(one, 1),
                    IRBinaryOp(next_value, "sub", body_value, one),
                    IRStore(slot, next_value),
                    IRJump("cond0"),
                ],
            ),
            IRBasicBlock("exit0", [IRLoad(result, slot), IRReturn(result)]),
        ],
    )

    assert print_ssa(_rename(function)) == (
        "func @countdown(%n: int) -> int {\n"
        "entry:\n"
        "    jump cond0\n"
        "\n"
        "cond0:\n"
        "    %0: int = phi(entry: %n, body0: %5)\n"
        "    %1: int = const 0\n"
        "    %2: bool = cmp_gt %0, %1\n"
        "    branch %2, body0, exit0\n"
        "\n"
        "body0:\n"
        "    %4: int = const 1\n"
        "    %5: int = sub %0, %4\n"
        "    jump cond0\n"
        "\n"
        "exit0:\n"
        "    return %0\n"
        "}"
    )


def test_renames_sum_to_with_i_and_sum_phis() -> None:
    int_type = IntType()
    n = IRParameter("n", int_type)
    i = _value("i")
    total = _value("sum")
    zero = _value("0")
    one = _value("1")
    loaded_i = _value("2")
    loaded_sum = _value("3")
    condition = IRValue("4", BoolType())
    body_sum = _value("5")
    next_sum = _value("6")
    body_i = _value("7")
    next_i = _value("8")
    result = _value("9")
    function = IRFunction(
        "sumTo",
        [n],
        int_type,
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
            IRBasicBlock(
                "cond0",
                [
                    IRLoad(loaded_i, i),
                    IRLoad(loaded_sum, total),
                    IRCompareOp(condition, "le", loaded_i, n),
                    IRBranch(condition, "body0", "exit0"),
                ],
            ),
            IRBasicBlock(
                "body0",
                [
                    IRLoad(body_sum, total),
                    IRBinaryOp(next_sum, "add", body_sum, loaded_i),
                    IRStore(total, next_sum),
                    IRLoad(body_i, i),
                    IRBinaryOp(next_i, "add", body_i, one),
                    IRStore(i, next_i),
                    IRJump("cond0"),
                ],
            ),
            IRBasicBlock("exit0", [IRLoad(result, total), IRReturn(result)]),
        ],
    )

    printed = print_ssa(_rename(function))

    assert "%2: int = phi(entry: %1, body0: %8)" in printed
    assert "%3: int = phi(entry: %0, body0: %6)" in printed
    assert "return %3" in printed


def test_renames_nested_if_with_inner_and_outer_phis() -> None:
    outer = _condition("outer")
    inner = _condition("inner")
    slot = _value("x")
    inner_then_value = _value("0")
    inner_else_value = _value("1")
    outer_else_value = _value("2")
    loaded = _value("3")
    function = IRFunction(
        "nested",
        [outer, inner],
        IntType(),
        [
            IRBasicBlock("entry", [IRBranch(outer, "then0", "else0")]),
            IRBasicBlock("then0", [IRBranch(inner, "then1", "else1")]),
            IRBasicBlock(
                "then1",
                [
                    IRConst(inner_then_value, 1),
                    IRStore(slot, inner_then_value),
                    IRJump("merge_inner"),
                ],
            ),
            IRBasicBlock(
                "else1",
                [
                    IRConst(inner_else_value, 2),
                    IRStore(slot, inner_else_value),
                    IRJump("merge_inner"),
                ],
            ),
            IRBasicBlock("merge_inner", [IRJump("merge_outer")]),
            IRBasicBlock(
                "else0",
                [
                    IRConst(outer_else_value, 3),
                    IRStore(slot, outer_else_value),
                    IRJump("merge_outer"),
                ],
            ),
            IRBasicBlock("merge_outer", [IRLoad(loaded, slot), IRReturn(loaded)]),
        ],
    )

    printed = print_ssa(_rename(function))

    assert "merge_inner.x.phi: int = phi(then1: %0, else1: %1)" in printed
    assert "%3: int = phi(merge_inner: %merge_inner.x.phi, else0: %2)" in printed
    assert "return %3" in printed


def test_rejects_load_from_slot_without_visible_value() -> None:
    slot = _value("x")
    loaded = _value("0")
    function = IRFunction(
        "broken",
        [],
        IntType(),
        [IRBasicBlock("entry", [IRLoad(loaded, slot), IRReturn(loaded)])],
    )

    _assert_rename_error(function, "Load from uninitialized slot '%x'.")


def test_rejects_phi_incoming_without_visible_value() -> None:
    condition = _condition()
    slot = _value("x")
    then_value = _value("0")
    loaded = _value("1")
    function = IRFunction(
        "broken",
        [condition],
        IntType(),
        [
            IRBasicBlock("entry", [IRBranch(condition, "then0", "else0")]),
            IRBasicBlock(
                "then0",
                [IRConst(then_value, 1), IRStore(slot, then_value), IRJump("merge0")],
            ),
            IRBasicBlock("else0", [IRJump("merge0")]),
            IRBasicBlock("merge0", [IRLoad(loaded, slot), IRReturn(loaded)]),
        ],
    )

    _assert_rename_error(
        function,
        "Phi for slot '%x' in successor 'merge0' needs incoming from block "
        "'else0', but no value is visible.",
    )


def test_rejects_store_type_mismatch() -> None:
    slot = _value("x")
    string_value = IRValue("0", StringType())
    function = IRFunction(
        "broken",
        [],
        IntType(),
        [
            IRBasicBlock(
                "entry",
                [
                    IRConst(string_value, "wrong"),
                    IRStore(slot, string_value),
                    IRReturn(string_value),
                ],
            )
        ],
    )

    _assert_rename_error(
        function,
        "Store to slot '%x' type mismatch: expected int, got string.",
    )


def test_rejects_cfg_with_unknown_edge_target() -> None:
    function = IRFunction(
        "broken",
        [],
        IntType(),
        [IRBasicBlock("entry", [IRReturn()])],
    )
    cfg = CFG(
        "broken",
        (CFGNode("entry"),),
        (CFGEdge("entry", "missing"),),
    )
    dominators = DominatorAnalysis(cfg).compute()

    with pytest.raises(
        SSARenameError,
        match=re.escape("CFG edge references unknown target block 'missing'."),
    ):
        SSARenamer(function, cfg, dominators, {}).rename()


def test_linear_output_matches_pattern_builder() -> None:
    slot = _value("x")
    stored = _value("0")
    loaded = _value("1")
    module = IRModule(
        [
            IRFunction(
                "read_x",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(stored, 5),
                            IRStore(slot, stored),
                            IRLoad(loaded, slot),
                            IRReturn(loaded),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ssa(_rename(module.functions[0])) == print_ssa(SSABuilder().build(module))


def test_if_else_output_matches_pattern_builder() -> None:
    int_type = IntType()
    x = IRParameter("x", int_type)
    y = IRValue("y", int_type)
    zero = IRValue("0", int_type)
    condition = IRValue("1", BoolType())
    one = IRValue("2", int_type)
    two = IRValue("3", int_type)
    loaded = IRValue("4", int_type)
    module = IRModule(
        [
            IRFunction(
                "f",
                [x],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(zero, 0),
                            IRCompareOp(condition, "gt", x, zero),
                            IRBranch(condition, "then0", "else0"),
                        ],
                    ),
                    IRBasicBlock(
                        "then0",
                        [IRConst(one, 1), IRStore(y, one), IRJump("merge0")],
                    ),
                    IRBasicBlock(
                        "else0",
                        [IRConst(two, 2), IRStore(y, two), IRJump("merge0")],
                    ),
                    IRBasicBlock("merge0", [IRLoad(loaded, y), IRReturn(loaded)]),
                ],
            )
        ]
    )

    assert print_ssa(_rename(module.functions[0])) == print_ssa(SSABuilder().build(module))


def test_while_output_matches_pattern_builder() -> None:
    int_type = IntType()
    parameter = IRParameter("n", int_type)
    slot = IRValue("n", int_type)
    loop_value = IRValue("0", int_type)
    zero = IRValue("1", int_type)
    condition = IRValue("2", BoolType())
    body_value = IRValue("3", int_type)
    one = IRValue("4", int_type)
    next_value = IRValue("5", int_type)
    result = IRValue("6", int_type)
    module = IRModule(
        [
            IRFunction(
                "countdown",
                [parameter],
                int_type,
                [
                    IRBasicBlock("entry", [IRStore(slot, parameter), IRJump("cond0")]),
                    IRBasicBlock(
                        "cond0",
                        [
                            IRLoad(loop_value, slot),
                            IRConst(zero, 0),
                            IRCompareOp(condition, "gt", loop_value, zero),
                            IRBranch(condition, "body0", "exit0"),
                        ],
                    ),
                    IRBasicBlock(
                        "body0",
                        [
                            IRLoad(body_value, slot),
                            IRConst(one, 1),
                            IRBinaryOp(next_value, "sub", body_value, one),
                            IRStore(slot, next_value),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock("exit0", [IRLoad(result, slot), IRReturn(result)]),
                ],
            )
        ]
    )

    assert print_ssa(_rename(module.functions[0])) == print_ssa(SSABuilder().build(module))
