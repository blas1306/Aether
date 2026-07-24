from __future__ import annotations

import pytest

from aether.ir import (
    EnumType,
    IRBasicBlock,
    IRCall,
    IRConst,
    IRFunction,
    IRInstruction,
    IRMethodResultNew,
    IRModule,
    IRParameter,
    IRReturn,
    IRStorage,
    IRStore,
    IRStructDefinition,
    IRStructGet,
    IRStructNew,
    IRStructSet,
    IRValue,
    IRVerificationError,
    IRVerifier,
    IntType,
    MethodResultType,
    StringType,
    StructType,
    VoidType,
)


def _assert_rejected(module: IRModule, invariant: str) -> None:
    with pytest.raises(IRVerificationError) as raised:
        IRVerifier(module).verify()

    failure = raised.value.normalized_failure
    assert failure is not None
    assert failure.invariant_id == invariant


def _single_block_module(
    instructions: list[IRInstruction],
    *,
    parameters: tuple[IRParameter, ...] = (),
    structs: tuple[IRStructDefinition, ...] = (),
) -> IRModule:
    return IRModule(
        [
            IRFunction(
                "critical_case",
                list(parameters),
                VoidType(),
                [IRBasicBlock("entry", [*instructions, IRReturn()])],
            )
        ],
        list(structs),
    )


def _pair_definition() -> IRStructDefinition:
    return IRStructDefinition(
        "Pair",
        (("left", IntType()), ("right", IntType())),
    )


def test_critical_ssa_rejects_duplicate_function_wide_value() -> None:
    parameter = IRParameter("duplicate", IntType())
    duplicate = IRValue("duplicate", IntType())
    module = _single_block_module(
        [IRConst(duplicate, 1)],
        parameters=(parameter,),
    )

    _assert_rejected(module, "IRV-009")


def test_critical_storage_rejects_inconsistent_slot_type() -> None:
    integer = IRParameter("integer", IntType())
    text = IRParameter("text", StringType())
    module = _single_block_module(
        [
            IRStore(IRStorage("slot", IntType()), integer),
            IRStore(IRStorage("slot", StringType()), text),
        ],
        parameters=(integer, text),
    )

    _assert_rejected(module, "IRV-010")


def test_critical_ssa_rejects_invalid_declared_type() -> None:
    unresolved = IRParameter("unresolved", StructType("Missing"))
    module = _single_block_module([], parameters=(unresolved,))

    _assert_rejected(module, "IRV-011")


def test_critical_builtins_rejects_noncanonical_read_result_layout() -> None:
    path = IRParameter("path", StringType())
    result = IRValue("result", StructType("FileReadResult"))
    result_definition = IRStructDefinition(
        "FileReadResult",
        (
            ("content", StringType()),
            ("status", EnumType("WrongStatus", ("failure",))),
        ),
    )
    module = _single_block_module(
        [IRCall("io.readText", (path,), result, "io.readText")],
        parameters=(path,),
        structs=(result_definition,),
    )

    _assert_rejected(module, "IRV-063")


def test_critical_structs_rejects_incomplete_construction() -> None:
    left = IRParameter("left", IntType())
    result = IRValue("result", StructType("Pair"))
    module = _single_block_module(
        [IRStructNew(result, (left,))],
        parameters=(left,),
        structs=(_pair_definition(),),
    )

    _assert_rejected(module, "IRV-079")


def test_critical_structs_rejects_field_read_result_type() -> None:
    pair = IRParameter("pair", StructType("Pair"))
    result = IRValue("result", StringType())
    module = _single_block_module(
        [IRStructGet(result, pair, 0, "left")],
        parameters=(pair,),
        structs=(_pair_definition(),),
    )

    _assert_rejected(module, "IRV-080")


def test_critical_structs_rejects_field_update_value_type() -> None:
    pair = IRParameter("pair", StructType("Pair"))
    text = IRParameter("text", StringType())
    result = IRValue("result", StructType("Pair"))
    module = _single_block_module(
        [IRStructSet(result, pair, 0, "left", text)],
        parameters=(pair, text),
        structs=(_pair_definition(),),
    )

    _assert_rejected(module, "IRV-081")


def test_critical_method_result_rejects_missing_nonvoid_value() -> None:
    pair = IRParameter("pair", StructType("Pair"))
    result = IRValue(
        "result",
        MethodResultType(StructType("Pair"), IntType()),
    )
    module = _single_block_module(
        [IRMethodResultNew(result, pair)],
        parameters=(pair,),
        structs=(_pair_definition(),),
    )

    _assert_rejected(module, "IRV-082")
