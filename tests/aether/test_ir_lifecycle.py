from __future__ import annotations

import pytest

from aether.ir import (
    BoolType,
    ClassRefType,
    DoubleType,
    IRAssign,
    IRBasicBlock,
    IRBranch,
    IRConst,
    IRCopyInit,
    IRDestroy,
    IRFunction,
    IRInitDefault,
    IRInterpreter,
    IRJump,
    IRLowerer,
    IRLoad,
    IRModule,
    IRMoveInit,
    IRParameter,
    IRRelocate,
    IRReturn,
    IRStorage,
    IRStructDefinition,
    IRValue,
    IRVerificationError,
    IRVerifier,
    IntType,
    LifecycleTypeRegistry,
    StringType,
    StructType,
    VoidType,
    expand_lifecycle,
)
from aether.pipeline import parse_source
from aether.ir.optimizer import OptimizerPipeline
from aether.typechecker import TypeChecker


def _verify(instructions, return_type=VoidType(), parameters=(), structs=()):
    module = IRModule(
        [IRFunction("main", list(parameters), return_type, [IRBasicBlock("entry", instructions)])],
        list(structs),
    )
    return IRVerifier(module).verify()


def _error(instructions, text: str, *, parameters=()):
    with pytest.raises(IRVerificationError, match=text):
        _verify(instructions, parameters=parameters)


def _lower_source(source: str) -> IRModule:
    program = parse_source(source)
    TypeChecker().check(program)
    return IRVerifier(IRLowerer().lower(program)).verify()


def test_all_lifecycle_operations_verify_and_expand_before_ssa() -> None:
    one = IRValue("one", IntType())
    first = IRStorage("first", IntType())
    second = IRStorage("second", IntType())
    third = IRStorage("third", IntType())
    loaded = IRValue("loaded", IntType())
    module = _verify(
        [
            IRConst(one, 1),
            IRInitDefault(first),
            IRAssign(first, one),
            IRCopyInit(second, first),
            IRDestroy(first),
            IRRelocate(third, second, 1),
            IRLoad(loaded, third),
            IRDestroy(third),
            IRReturn(),
        ]
    )

    expanded = expand_lifecycle(module)
    names = {type(item).__name__ for item in expanded.functions[0].blocks[0].instructions}
    assert not names & {
        "IRInitDefault",
        "IRCopyInit",
        "IRMoveInit",
        "IRAssign",
        "IRDestroy",
        "IRRelocate",
    }


def test_ir_optimizers_preserve_unexpanded_lifecycle_effects() -> None:
    storage = IRStorage("slot", IntType())
    module = _verify([IRInitDefault(storage), IRDestroy(storage), IRReturn()])
    optimized = OptimizerPipeline(iterative=True).run(module)
    instructions = optimized.functions[0].blocks[0].instructions
    assert any(isinstance(item, IRInitDefault) for item in instructions)
    assert any(isinstance(item, IRDestroy) for item in instructions)


def test_move_init_transfers_return_storage() -> None:
    value = IRValue("value", IntType())
    source = IRStorage("source", IntType())
    result = IRStorage("result", IntType())
    returned = IRValue("returned", IntType())
    module = _verify(
        [
            IRConst(value, 7),
            IRCopyInit(source, value),
            IRMoveInit(result, source),
            IRLoad(returned, result),
            IRReturn(returned, result),
        ],
        IntType(),
    )
    assert IRInterpreter(module).call("main") == 7


def test_struct_lifecycle_traits_are_recursive_and_source_ordered() -> None:
    inner = IRStructDefinition("Inner", (("text", StringType()),))
    outer = IRStructDefinition(
        "Outer",
        (("count", IntType()), ("inner", StructType("Inner"))),
    )
    registry = LifecycleTypeRegistry([inner, outer])
    traits = registry.traits(StructType("Outer"))
    assert not traits.trivially_copyable
    assert traits.trivially_relocatable
    assert traits.needs_destroy
    assert traits.fields == outer.fields
    assert [step.path for step in registry.synthesis_plan(StructType("Outer"), "copy_init")] == [
        ("count",),
        ("inner", "text"),
    ]
    assert [step.path for step in registry.synthesis_plan(StructType("Outer"), "destroy")] == [
        ("inner", "text"),
        ("count",),
    ]


def test_struct_init_default_and_destroy_execute_recursively() -> None:
    definition = IRStructDefinition(
        "Record", (("count", IntType()), ("text", StringType()))
    )
    storage = IRStorage("record", StructType("Record"))
    module = _verify(
        [IRInitDefault(storage), IRDestroy(storage), IRReturn()],
        structs=(definition,),
    )
    assert IRInterpreter(module).call("main") is None


def test_self_assignment_is_valid_and_safe() -> None:
    storage = IRStorage("value", IntType())
    module = _verify(
        [
            IRInitDefault(storage),
            IRAssign(storage, storage),
            IRDestroy(storage),
            IRReturn(),
        ]
    )
    assert IRInterpreter(module).call("main") is None


def test_copy_init_rejects_live_destination() -> None:
    value = IRValue("value", IntType())
    storage = IRStorage("slot", IntType())
    _error(
        [IRConst(value, 1), IRCopyInit(storage, value), IRCopyInit(storage, value), IRReturn()],
        "copy_init destination.*already alive",
    )


def test_assign_rejects_uninitialized_destination() -> None:
    value = IRValue("value", IntType())
    storage = IRStorage("slot", IntType())
    _error(
        [IRConst(value, 1), IRAssign(storage, value), IRReturn()],
        "assign destination.*before initialization",
    )


def test_double_destroy_is_rejected() -> None:
    storage = IRStorage("slot", IntType())
    _error(
        [IRInitDefault(storage), IRDestroy(storage), IRDestroy(storage), IRReturn()],
        "destroy operand.*after destroy",
    )


def test_load_after_destroy_is_rejected() -> None:
    storage = IRStorage("slot", IntType())
    loaded = IRValue("loaded", IntType())
    _error(
        [IRInitDefault(storage), IRDestroy(storage), IRLoad(loaded, storage), IRReturn()],
        "after destroy",
    )


def test_load_and_destroy_after_move_are_rejected() -> None:
    source = IRStorage("source", IntType())
    destination = IRStorage("destination", IntType())
    loaded = IRValue("loaded", IntType())
    _error(
        [
            IRInitDefault(source),
            IRMoveInit(destination, source),
            IRLoad(loaded, source),
            IRDestroy(destination),
            IRReturn(),
        ],
        "after move",
    )

    _error(
        [
            IRInitDefault(source),
            IRMoveInit(destination, source),
            IRDestroy(destination),
            IRReturn(source),  # type: ignore[arg-type]
        ],
        "returned storage.*after move",
    )

    _error(
        [
            IRInitDefault(source),
            IRMoveInit(destination, source),
            IRDestroy(source),
            IRDestroy(destination),
            IRReturn(),
        ],
        "after move",
    )


def test_missing_cleanup_is_rejected() -> None:
    storage = IRStorage("slot", IntType())
    _error(
        [IRInitDefault(storage), IRReturn()],
        "live owning storage lacking cleanup",
    )


def test_inconsistent_branch_initialization_is_rejected() -> None:
    condition = IRParameter("condition", BoolType())
    storage = IRStorage("slot", IntType())
    module = IRModule(
        [
            IRFunction(
                "main",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then", "else")]),
                    IRBasicBlock("then", [IRInitDefault(storage), IRJump("merge")]),
                    IRBasicBlock("else", [IRJump("merge")]),
                    IRBasicBlock("merge", [IRReturn()]),
                ],
            )
        ]
    )
    with pytest.raises(IRVerificationError, match="inconsistent across control-flow paths"):
        IRVerifier(module).verify()


def test_relocation_rejects_non_relocatable_type_and_invalid_count() -> None:
    parameter = IRParameter("value", ClassRefType("Object"))
    source = IRStorage("source", parameter.type)
    destination = IRStorage("destination", parameter.type)
    _error(
        [IRCopyInit(source, parameter), IRRelocate(destination, source, 1), IRReturn()],
        "non-relocatable type",
        parameters=(parameter,),
    )

    source_int = IRStorage("source", IntType())
    destination_int = IRStorage("destination", IntType())
    _error(
        [IRInitDefault(source_int), IRRelocate(destination_int, source_int, 0), IRReturn()],
        "count must be positive",
    )


def test_lifecycle_requires_exact_types_and_real_storage() -> None:
    source = IRValue("source", DoubleType())
    destination = IRStorage("destination", IntType())
    _error(
        [IRConst(source, 1.0), IRCopyInit(destination, source), IRReturn()],
        "copy_init type mismatch",
    )

    fake_storage = IRValue("fake", IntType())
    _error(
        [IRInitDefault(fake_storage), IRReturn()],  # type: ignore[arg-type]
        "must be IRStorage",
    )


def test_ast_lowering_moves_a_local_into_return_storage() -> None:
    module = _lower_source("int identity(int value) { int x = value; return x; }")
    instructions = module.functions[0].blocks[0].instructions
    move = next(item for item in instructions if isinstance(item, IRMoveInit))
    returned = instructions[-1]
    assert move.source.name == "x"
    assert isinstance(returned, IRReturn)
    assert returned.transferred_storage == move.destination
    assert not any(
        isinstance(item, IRDestroy) and item.value == move.source
        for item in instructions
    )


def test_nested_scope_and_loop_exits_emit_reverse_cleanup() -> None:
    module = _lower_source(
        """
int f(int n) {
    int i = 0;
    while (i < n) {
        int first = i;
        int second = first;
        i = i + 1;
        if (i == 2) { continue; }
        if (i == 4) { break; }
    }
    return i;
}
"""
    )
    function = module.functions[0]
    cleanup_pairs = []
    for block in function.blocks:
        destroyed = [
            item.value.name
            for item in block.instructions
            if isinstance(item, IRDestroy)
        ]
        if destroyed:
            cleanup_pairs.append(destroyed)
    assert cleanup_pairs
    assert all(names[:2] == ["second", "first"] for names in cleanup_pairs)


def test_early_return_cleans_outer_and_inner_scopes() -> None:
    module = _lower_source(
        """
int f(int n) {
    int outer = n;
    if (n > 0) {
        int inner = outer;
        return inner + outer;
    }
    return outer;
}
"""
    )
    then_block = next(block for block in module.functions[0].blocks if block.name == "then0")
    destroyed = [
        item.value.name for item in then_block.instructions if isinstance(item, IRDestroy)
    ]
    assert destroyed == ["inner", "outer"]
