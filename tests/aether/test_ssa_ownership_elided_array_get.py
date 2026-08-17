from aether.ir.types import ArrayType, BoolType, IntType, StringType, VoidType
from aether.ssa.model import (
    SSAArrayGet, SSABasicBlock, SSABranch, SSACall, SSACompareOp, SSAConst,
    SSAFunction, SSAJump, SSAModule, SSAParameter, SSAReturn, SSAValue,
)
from aether.ssa.optimizer.ownership_elided_array_get import OwnershipElidedArrayGet


def value(name, type_):
    return SSAValue(name, type_)


def module_with_use(use_factory):
    string = StringType()
    array = value("array", ArrayType(string))
    index = value("index", IntType())
    extracted = value("extracted", string)
    other = value("other", string)
    condition = value("condition", BoolType())
    use = use_factory(extracted, other, condition)
    function = SSAFunction("loop_get", [SSAParameter("array", array.type), SSAParameter("other", string)], VoidType(), [
        SSABasicBlock("entry", [SSAConst(index, 0), SSAJump("loop")]),
        SSABasicBlock("loop", [
            SSAArrayGet(extracted, array, index), use,
            SSACall("__aether_release", (extracted,), builtin="__aether_release"),
            SSABranch(condition, "loop", "exit"),
        ]),
        SSABasicBlock("exit", [SSAReturn()]),
    ])
    return SSAModule([function]), extracted


def test_direct_loop_string_comparison_becomes_borrowed_and_drops_release():
    module, extracted = module_with_use(
        lambda item, other, result: SSACompareOp(result, "==", item, other)
    )
    outcome = OwnershipElidedArrayGet().run(module)
    loop = outcome.module.functions[0].blocks[1]
    get = next(item for item in loop.instructions if isinstance(item, SSAArrayGet))
    assert get.borrowed and get.borrow_scope == "loop"
    assert not any(isinstance(item, SSACall) and item.builtin == "__aether_release"
                   for item in loop.instructions)
    assert outcome.stats["transformed"] == outcome.stats["retains_removed"] == 1
    assert outcome.stats["releases_removed"] == 1


def test_trusted_immediate_borrowing_call_becomes_borrowed():
    module, _ = module_with_use(
        lambda item, other, result: SSACall("length", (item,), value("length", IntType()),
                                     builtin="__aether_string_byte_length")
    )
    outcome = OwnershipElidedArrayGet().run(module)
    loop = outcome.module.functions[0].blocks[1]
    assert next(item for item in loop.instructions if isinstance(item, SSAArrayGet)).borrowed
    assert outcome.stats["immediate_candidates_examined"] == 1
    assert outcome.stats["immediate_qualified"] == outcome.stats["immediate_transformed"] == 1


def test_unknown_immediate_call_remains_owned():
    module, _ = module_with_use(
        lambda item, other, result: SSACall("observe", (item,), value("length", IntType()))
    )
    outcome = OwnershipElidedArrayGet().run(module)
    loop = outcome.module.functions[0].blocks[1]
    assert not next(item for item in loop.instructions if isinstance(item, SSAArrayGet)).borrowed
    assert outcome.stats["blocked_unknown_consumer"] == 1
