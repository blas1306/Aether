from __future__ import annotations

from aether.ir.types import ArrayType, IntType, ListType, MatrixType, VectorType, VoidType
from aether.ssa.analysis import ProofCoverageAudit
from aether.ssa.model import (
    SSAArrayGet, SSAArrayNew, SSABasicBlock, SSAConst, SSAFunction,
    SSAListGet, SSAListNew, SSAMatrixGet, SSAMatrixNew, SSAModule,
    SSAReturn, SSAValue, SSAVectorGet, SSAVectorNew,
)
from aether.ssa.optimizer import ProvenBoundsCheckEliminator, build_ssa_optimizer_pipeline


I = IntType()


def value(name, type_=I):
    return SSAValue(name, type_)


def optimized_instruction(instruction, setup, profile="O2", parameters=()):
    module = SSAModule([SSAFunction("case", list(parameters), VoidType(), [
        SSABasicBlock("entry", [*setup, instruction, SSAReturn()])
    ])])
    result = build_ssa_optimizer_pipeline(profile).run(module)
    return next(
        item for item in result.functions[0].blocks[0].instructions
        if isinstance(item, type(instruction))
    )


def test_o2_eliminates_proven_array_and_vector_checks_but_o1_does_not() -> None:
    item, zero, one = value("item"), value("zero"), value("one")
    array = value("array", ArrayType(I))
    vector = value("vector", VectorType(I, "row"))
    setup = [SSAConst(item, 7), SSAConst(zero, 0), SSAConst(one, 1)]
    array_get = SSAArrayGet(value("array_result"), array, zero)
    assert optimized_instruction(array_get, [*setup, SSAArrayNew(array, (item,))], "O1").bounds_checked
    assert not optimized_instruction(array_get, [*setup, SSAArrayNew(array, (item,))]).bounds_checked
    vector_get = SSAVectorGet(value("vector_result"), vector, one)
    assert not optimized_instruction(
        vector_get, [*setup, SSAVectorNew(vector, (item,), "row")]
    ).bounds_checked


def test_o2_requires_both_matrix_dimensions() -> None:
    item, one, unknown = value("item"), value("one"), value("unknown")
    matrix = value("matrix", MatrixType(I))
    setup = [SSAConst(item, 7), SSAConst(one, 1), SSAMatrixNew(matrix, (item,) * 4, 2, 2)]
    safe = SSAMatrixGet(value("safe"), matrix, one, one, 2)
    uncertain = SSAMatrixGet(value("uncertain"), matrix, one, unknown, 2)
    assert not optimized_instruction(safe, setup).bounds_checked
    assert optimized_instruction(uncertain, setup, parameters=(unknown,)).bounds_checked


def test_unknown_unsafe_and_list_checks_are_preserved() -> None:
    item, zero, out, unknown = value("item"), value("zero"), value("out"), value("unknown")
    array = value("array", ArrayType(I))
    setup = [SSAConst(item, 7), SSAConst(zero, 0), SSAConst(out, 2), SSAArrayNew(array, (item,))]
    assert optimized_instruction(
        SSAArrayGet(value("u"), array, unknown), setup, parameters=(unknown,)
    ).bounds_checked
    assert optimized_instruction(SSAArrayGet(value("o"), array, out), setup).bounds_checked
    listing = value("list", ListType(I))
    list_get = SSAListGet(value("l"), listing, zero)
    assert optimized_instruction(list_get, [SSAConst(item, 7), SSAConst(zero, 0), SSAListNew(listing, (item,))]).__class__ is SSAListGet


def test_statistics_and_audit_optimizer_agreement() -> None:
    item, zero = value("item"), value("zero")
    array = value("array", ArrayType(I))
    module = SSAModule([SSAFunction("stats", [], VoidType(), [SSABasicBlock("entry", [
        SSAConst(item, 1), SSAConst(zero, 0), SSAArrayNew(array, (item,)),
        SSAArrayGet(value("result"), array, zero), SSAReturn(),
    ])])])
    assert ProofCoverageAudit().audit(module).checks[0].proof == "PROVEN_SAFE"
    result = ProvenBoundsCheckEliminator().run(module)
    assert result.stats["checks_examined"] == 1
    assert result.stats["array_checks_removed"] == 1
    assert ProofCoverageAudit().audit(result.module).checks == ()
