from __future__ import annotations

from aether.ir.types import ArrayType, BoolType, IntType, ListType, MatrixType, VectorType, VoidType
from aether.ssa.analysis import LoopAnalysis, ProofResult, RangeAnalysis, ShapeAnalysis
from aether.ssa.model import (
    SSAArrayLength, SSAArrayNew, SSABasicBlock, SSABinaryOp, SSABranch,
    SSACompareOp, SSAConst, SSAFunction, SSAJump, SSAListLength, SSAListNew,
    SSAListPush, SSAMatrixNew, SSAPhi, SSAReturn, SSAValue, SSAVectorNew,
)


I = IntType()


def value(name, type_=I): return SSAValue(name, type_)


def counted_loop() -> SSAFunction:
    zero, one, limit = value("zero"), value("one"), value("limit")
    i, next_i, condition = value("i"), value("next_i"), value("condition", BoolType())
    return SSAFunction("loop", [], VoidType(), [
        SSABasicBlock("entry", [SSAConst(zero, 0), SSAConst(one, 1), SSAConst(limit, 10), SSAJump("header")]),
        SSABasicBlock("header", [SSAPhi(i, (("entry", zero), ("latch", next_i))), SSACompareOp(condition, "lt", i, limit), SSABranch(condition, "body", "exit")]),
        SSABasicBlock("body", [SSAJump("latch")]),
        SSABasicBlock("latch", [SSABinaryOp(next_i, "add", i, one), SSAJump("header")]),
        SSABasicBlock("exit", [SSAReturn()]),
        SSABasicBlock("dead", [SSAJump("dead")]),
    ])


def test_natural_loop_preheader_iv_exits_and_unreachable_cycle() -> None:
    result = LoopAnalysis().compute(counted_loop())
    loop = result.loop_with_header("header")
    assert loop is not None
    assert loop.body == {"header", "body", "latch"}
    assert loop.preheader == "entry"
    assert loop.exiting_blocks == {"header"} and loop.exit_blocks == {"exit"}
    assert loop.depth == 1 and loop.induction_variables[0].step == 1
    assert result.loop_for_block("dead") is None


def test_multiple_latches_are_one_loop() -> None:
    fn = SSAFunction("multi", [], VoidType(), [
        SSABasicBlock("entry", [SSAJump("h")]),
        SSABasicBlock("h", [SSABranch(value("c", BoolType()), "left", "right")]),
        SSABasicBlock("left", [SSAJump("h")]), SSABasicBlock("right", [SSAJump("h")]),
    ])
    loop = LoopAnalysis().compute(fn).loop_with_header("h")
    assert loop is not None and loop.latches == {"left", "right"}


def test_nested_loop_forest() -> None:
    fn = SSAFunction("nested", [], VoidType(), [
        SSABasicBlock("entry", [SSAJump("outer")]),
        SSABasicBlock("outer", [SSABranch(value("a", BoolType()), "inner", "exit")]),
        SSABasicBlock("inner", [SSABranch(value("b", BoolType()), "inner_body", "outer_latch")]),
        SSABasicBlock("inner_body", [SSAJump("inner")]),
        SSABasicBlock("outer_latch", [SSAJump("outer")]), SSABasicBlock("exit", [SSAReturn()]),
    ])
    result = LoopAnalysis().compute(fn); outer = result.loop_with_header("outer"); inner = result.loop_with_header("inner")
    assert outer and inner and inner.parent_header == "outer" and inner.depth == 2
    assert outer.child_headers == ("inner",)


def test_branch_ranges_and_explicit_proofs() -> None:
    fn = counted_loop(); result = RangeAnalysis().compute(fn)
    header = fn.blocks[1]; i = header.instructions[0].result; limit = header.instructions[1].right
    assert result.prove_nonnegative(i, "header") is ProofResult.PROVEN_TRUE
    assert result.prove_less_than(i, limit, "body") is ProofResult.PROVEN_TRUE
    assert result.prove_less_than(i, limit, "exit") is ProofResult.PROVEN_FALSE


def test_checked_arithmetic_that_cannot_be_bounded_is_unknown() -> None:
    high, one, result_value = value("high"), value("one"), value("result")
    fn = SSAFunction("overflow", [], I, [SSABasicBlock("entry", [SSAConst(high, 2**31 - 1), SSAConst(one, 1), SSABinaryOp(result_value, "add", high, one), SSAReturn(result_value)])])
    assert RangeAnalysis().compute(fn).range_of(result_value, "entry").is_unknown


def test_length_shape_and_mutation_facts() -> None:
    array = value("array", ArrayType(I)); array_len = value("array_len")
    listing = value("list", ListType(I)); list_len = value("list_len"); item = value("item")
    vector = value("vector", VectorType(I, "row")); matrix = value("matrix", MatrixType(I))
    fn = SSAFunction("shapes", [], VoidType(), [SSABasicBlock("entry", [
        SSAConst(item, 1), SSAArrayNew(array, (item, item)), SSAArrayLength(array_len, array),
        SSAListNew(listing, (item,)), SSAListLength(list_len, listing), SSAListPush(listing, item),
        SSAVectorNew(vector, (item, item), "row"), SSAMatrixNew(matrix, (item,) * 6, 2, 3), SSAReturn(),
    ])])
    facts = ShapeAnalysis().compute(fn)
    assert facts.length_of(array, "entry").constant == 2
    assert facts.length_of(listing, "entry") is None
    assert facts.vector_shape_of(vector, "entry").orientation == "row"
    assert facts.matrix_shape_of(matrix, "entry").rows == 2


def test_debug_output_is_deterministic() -> None:
    assert LoopAnalysis().compute(counted_loop()).debug_string() == LoopAnalysis().compute(counted_loop()).debug_string()


def test_irreducible_region_is_reported_not_fabricated() -> None:
    condition = value("condition", BoolType())
    fn = SSAFunction("irreducible", [], VoidType(), [
        SSABasicBlock("entry", [SSABranch(condition, "a", "b")]),
        SSABasicBlock("a", [SSAJump("c")]),
        SSABasicBlock("b", [SSAJump("c")]),
        SSABasicBlock("c", [SSABranch(condition, "a", "b")]),
    ])
    analysis = LoopAnalysis().compute(fn)
    assert analysis.loops == ()
    assert analysis.irreducible_regions[0].entry_blocks == {"a", "b"}


def test_large_cfg_analysis_stress() -> None:
    blocks = [SSABasicBlock("entry", [SSAJump("header")])]
    blocks.append(SSABasicBlock("header", [SSAJump("body0")]))
    for index in range(100):
        target = f"body{index + 1}" if index < 99 else "header"
        blocks.append(SSABasicBlock(f"body{index}", [SSAJump(target)]))
    loop = LoopAnalysis().compute(SSAFunction("large", [], VoidType(), blocks)).loop_with_header("header")
    assert loop is not None and len(loop.body) == 101
