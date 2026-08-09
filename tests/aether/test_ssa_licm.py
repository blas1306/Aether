from __future__ import annotations

from aether.ir.types import (
    ArrayType, BoolType, DoubleType, IntType, ListType, MatrixType, VectorType,
    VoidType,
)
from aether.ssa.model import (
    SSAArrayLength, SSABasicBlock, SSABinaryOp, SSABranch, SSACompareOp,
    SSAConst, SSAFunction, SSAJump, SSAListLength, SSAListNew, SSAListPush,
    SSAMatrixRows, SSAModule, SSAParameter, SSAPhi, SSAReturn, SSAValue,
    SSAVectorLength,
)
from aether.ssa.optimizer import LoopInvariantCodeMotion
from aether.ssa.verifier import SSAVerifier


I, D, B = IntType(), DoubleType(), BoolType()


def v(name, type_=I):
    return SSAValue(name, type_)


def run(function):
    result = LoopInvariantCodeMotion().run(SSAModule([function]))
    SSAVerifier(result.module).verify()
    return result


def block(result, name):
    return next(item for item in result.module.functions[0].blocks if item.name == name)


def scalar_loop(*body_instructions):
    zero, one, limit = v("zero"), v("one"), v("limit")
    i, next_i, condition = v("i"), v("next_i"), v("condition", B)
    return SSAFunction("loop", [], VoidType(), [
        SSABasicBlock("entry", [SSAConst(zero, 0), SSAConst(one, 1), SSAConst(limit, 4), SSAJump("header")]),
        SSABasicBlock("header", [
            SSAPhi(i, (("entry", zero), ("latch", next_i))),
            *body_instructions,
            SSACompareOp(condition, "lt", i, limit),
            SSABranch(condition, "latch", "exit"),
        ]),
        SSABasicBlock("latch", [SSABinaryOp(next_i, "add", i, one), SSAJump("header")]),
        SSABasicBlock("exit", [SSAReturn()]),
    ])


def test_hoists_float_dependency_chain_in_source_order() -> None:
    left, right, first, second = v("left", D), v("right", D), v("first", D), v("second", D)
    fn = scalar_loop(SSAConst(left, 1.5), SSAConst(right, 2.0),
                     SSABinaryOp(first, "mul", left, right),
                     SSABinaryOp(second, "add", first, right))
    result = run(fn)
    assert result.changed
    assert [getattr(item, "result", None) for item in block(result, "entry").instructions[-5:-1]] == [left, right, first, second]
    assert all(item not in block(result, "header").instructions for item in (
        fn.blocks[1].instructions[1], fn.blocks[1].instructions[2],
        fn.blocks[1].instructions[3], fn.blocks[1].instructions[4]))
    assert result.stats["instructions_hoisted"] == 4


def test_preserves_checked_integer_and_induction_dependent_operations() -> None:
    constant, overflow, dependent = v("constant"), v("overflow"), v("dependent")
    fn = scalar_loop(SSAConst(constant, 7),
                     SSABinaryOp(overflow, "add", constant, constant),
                     SSABinaryOp(dependent, "sub", v("i"), constant))
    result = run(fn)
    header_results = [getattr(item, "result", None) for item in block(result, "header").instructions]
    assert constant not in header_results
    assert overflow in header_results and dependent in header_results
    assert result.stats["blocked_by_may_trap"] >= 2


def test_does_not_hoist_from_conditional_only_block() -> None:
    condition, left, right, product = v("external", B), v("left", D), v("right", D), v("product", D)
    fn = SSAFunction("conditional", [condition, left, right], VoidType(), [
        SSABasicBlock("entry", [SSAJump("header")]),
        SSABasicBlock("header", [SSABranch(condition, "optional", "latch")]),
        SSABasicBlock("optional", [SSABinaryOp(product, "mul", left, right), SSAJump("latch")]),
        SSABasicBlock("latch", [SSABranch(condition, "header", "exit")]),
        SSABasicBlock("exit", [SSAReturn()]),
    ])
    result = run(fn)
    assert not result.changed
    assert result.stats["blocked_by_control_speculation"] == 1


def test_nested_value_moves_only_to_inner_preheader() -> None:
    outer_condition, inner_condition = v("outer_condition", B), v("inner_condition", B)
    outer_value, factor, product = v("outer_value", D), v("factor", D), v("product", D)
    fn = SSAFunction("nested", [outer_condition, inner_condition, outer_value, factor], VoidType(), [
        SSABasicBlock("entry", [SSAJump("outer")]),
        SSABasicBlock("outer", [SSABranch(outer_condition, "inner_pre", "exit")]),
        SSABasicBlock("inner_pre", [SSAJump("inner")]),
        SSABasicBlock("inner", [SSABinaryOp(product, "mul", outer_value, factor), SSABranch(inner_condition, "inner_latch", "outer_latch")]),
        SSABasicBlock("inner_latch", [SSAJump("inner")]),
        SSABasicBlock("outer_latch", [SSAJump("outer")]),
        SSABasicBlock("exit", [SSAReturn()]),
    ])
    result = run(fn)
    assert product in [getattr(item, "result", None) for item in block(result, "inner_pre").instructions]
    assert product not in [getattr(item, "result", None) for item in block(result, "entry").instructions]


def collection_loop(parameter, *body_instructions):
    condition = SSAParameter("condition", B)
    return SSAFunction("collection_loop", [parameter, condition], VoidType(), [
        SSABasicBlock("entry", [SSAJump("header")]),
        SSABasicBlock("header", [*body_instructions, SSABranch(condition, "latch", "exit")]),
        SSABasicBlock("latch", [SSAJump("header")]),
        SSABasicBlock("exit", [SSAReturn()]),
    ])


def test_hoists_array_and_readonly_list_lengths() -> None:
    array = SSAParameter("array", ArrayType(I)); array_length = v("array_length")
    result = run(collection_loop(array, SSAArrayLength(array_length, array)))
    assert array_length in [getattr(item, "result", None) for item in block(result, "entry").instructions]
    assert result.stats["array_length_reads_hoisted"] == 1

    listing = SSAParameter("listing", ListType(I)); list_length = v("list_length")
    result = run(collection_loop(listing, SSAListLength(list_length, listing)))
    assert list_length in [getattr(item, "result", None) for item in block(result, "entry").instructions]
    assert result.stats["list_length_reads_hoisted"] == 1


def test_list_length_respects_alias_specific_mutation() -> None:
    list_type = ListType(I)
    listing, other, item, length = v("listing", list_type), v("other", list_type), v("item"), v("length")
    fn = SSAFunction("no_alias", [], VoidType(), [
        SSABasicBlock("entry", [SSAListNew(listing), SSAListNew(other), SSAConst(item, 1), SSAJump("header")]),
        SSABasicBlock("header", [SSAListLength(length, listing), SSAListPush(other, item), SSAJump("latch")]),
        SSABasicBlock("latch", [SSAJump("header")]),
    ])
    result = run(fn)
    assert length in [getattr(value, "result", None) for value in block(result, "entry").instructions]

    parameter = SSAParameter("parameter", list_type); blocked_length = v("blocked_length")
    blocked = run(collection_loop(parameter, SSAListLength(blocked_length, parameter), SSAListPush(parameter, blocked_length)))
    assert blocked_length in [getattr(value, "result", None) for value in block(blocked, "header").instructions]
    assert blocked.stats["blocked_by_may_modify"] == 1


def test_hoists_existing_vector_and_matrix_metadata_reads() -> None:
    vector = SSAParameter("vector", VectorType(I)); vector_length = v("vector_length")
    result = run(collection_loop(vector, SSAVectorLength(vector_length, vector)))
    assert result.stats["vector_matrix_metadata_reads_hoisted"] == 1

    matrix = SSAParameter("matrix", MatrixType(I)); rows = v("rows")
    result = run(collection_loop(matrix, SSAMatrixRows(rows, matrix, 2)))
    assert rows in [getattr(item, "result", None) for item in block(result, "entry").instructions]
