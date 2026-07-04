from __future__ import annotations

import re

import pytest

from aether.ir import (
    BoolType,
    IntType,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRInstruction,
    IRJump,
    IRLoad,
    IRModule,
    IRParameter,
    IRReturn,
    IRStore,
    IRValue,
    VoidType,
)
from aether.ssa import (
    SSABinaryOp,
    SSABuildError,
    SSABuilder,
    SSACall,
    SSACompareOp,
    SSAConst,
    SSAReturn,
    SSAVerifier,
    print_ssa,
)


def _build_and_verify(module: IRModule):
    ssa_module = SSABuilder().build(module)
    assert SSAVerifier(ssa_module).verify() is ssa_module
    return ssa_module


def _assert_build_error(module: IRModule, message: str) -> None:
    with pytest.raises(SSABuildError, match=re.escape(message)):
        SSABuilder().build(module)


def test_builds_function_returning_literal() -> None:
    int_type = IntType()
    value = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "answer",
                [],
                int_type,
                [IRBasicBlock("entry", [IRConst(value, 42), IRReturn(value)])],
            )
        ]
    )

    ssa_module = _build_and_verify(module)
    instructions = ssa_module.functions[0].blocks[0].instructions

    assert isinstance(instructions[0], SSAConst)
    assert instructions[0].result.name == "0"
    assert instructions[0].value == 42
    assert isinstance(instructions[1], SSAReturn)
    assert instructions[1].value is not None
    assert instructions[1].value.name == "0"


def test_builds_add_with_parameters() -> None:
    int_type = IntType()
    left = IRParameter("left", int_type)
    right = IRParameter("right", int_type)
    result = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "add",
                [left, right],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRBinaryOp(result, "add", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)
    function = ssa_module.functions[0]

    assert function.parameters[0].name == "left"
    assert function.parameters[1].name == "right"
    assert isinstance(function.blocks[0].instructions[0], SSABinaryOp)
    assert print_ssa(ssa_module) == (
        "func @add(%left: int, %right: int) -> int {\n"
        "entry:\n"
        "    %0: int = add %left, %right\n"
        "    return %0\n"
        "}"
    )


def test_promotes_simple_local_store_and_load() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "read_x",
                [],
                int_type,
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

    ssa_module = _build_and_verify(module)

    assert print_ssa(ssa_module) == (
        "func @read_x() -> int {\n"
        "entry:\n"
        "    %0: int = const 5\n"
        "    return %0\n"
        "}"
    )


def test_promotes_latest_store_when_slot_is_overwritten() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    first = IRValue("0", int_type)
    second = IRValue("1", int_type)
    loaded = IRValue("2", int_type)
    module = IRModule(
        [
            IRFunction(
                "overwrite",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(first, 1),
                            IRStore(slot, first),
                            IRConst(second, 2),
                            IRStore(slot, second),
                            IRLoad(loaded, slot),
                            IRReturn(loaded),
                        ],
                    )
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)

    assert print_ssa(ssa_module) == (
        "func @overwrite() -> int {\n"
        "entry:\n"
        "    %0: int = const 1\n"
        "    %1: int = const 2\n"
        "    return %1\n"
        "}"
    )


def test_builds_call_between_functions() -> None:
    int_type = IntType()
    parameter = IRParameter("value", int_type)
    one = IRValue("0", int_type)
    incremented = IRValue("1", int_type)
    argument = IRValue("2", int_type)
    call_result = IRValue("3", int_type)
    module = IRModule(
        [
            IRFunction(
                "increment",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(one, 1),
                            IRBinaryOp(incremented, "add", parameter, one),
                            IRReturn(incremented),
                        ],
                    )
                ],
            ),
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(argument, 41),
                            IRCall("increment", (argument,), call_result),
                            IRReturn(call_result),
                        ],
                    )
                ],
            ),
        ]
    )

    ssa_module = _build_and_verify(module)
    call = ssa_module.functions[1].blocks[0].instructions[1]

    assert isinstance(call, SSACall)
    assert call.function == "increment"
    assert call.arguments[0].name == "2"
    assert call.result is not None
    assert call.result.name == "3"


def test_builds_comparison() -> None:
    int_type = IntType()
    bool_type = BoolType()
    left = IRParameter("left", int_type)
    right = IRParameter("right", int_type)
    result = IRValue("0", bool_type)
    module = IRModule(
        [
            IRFunction(
                "less",
                [left, right],
                bool_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(result, "lt", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)

    assert isinstance(ssa_module.functions[0].blocks[0].instructions[0], SSACompareOp)
    assert print_ssa(ssa_module) == (
        "func @less(%left: int, %right: int) -> bool {\n"
        "entry:\n"
        "    %0: bool = cmp_lt %left, %right\n"
        "    return %0\n"
        "}"
    )


def test_builds_void_function_with_return() -> None:
    module = IRModule(
        [
            IRFunction(
                "nothing",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn()])],
            )
        ]
    )

    ssa_module = _build_and_verify(module)

    assert ssa_module.functions[0].blocks[0].instructions == [SSAReturn()]


def test_printer_shows_no_load_or_store_after_promotion() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    three = IRValue("2", int_type)
    result = IRValue("3", int_type)
    module = IRModule(
        [
            IRFunction(
                "example",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(stored, 5),
                            IRStore(slot, stored),
                            IRLoad(loaded, slot),
                            IRConst(three, 3),
                            IRBinaryOp(result, "add", loaded, three),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    printed = print_ssa(_build_and_verify(module))

    assert "load" not in printed
    assert "store" not in printed
    assert printed == (
        "func @example() -> int {\n"
        "entry:\n"
        "    %0: int = const 5\n"
        "    %2: int = const 3\n"
        "    %3: int = add %0, %2\n"
        "    return %3\n"
        "}"
    )


def test_rejects_function_with_branch() -> None:
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    module = IRModule(
        [
            IRFunction(
                "choose",
                [condition],
                bool_type,
                [IRBasicBlock("entry", [IRBranch(condition, "then", "else")])],
            )
        ]
    )

    _assert_build_error(
        module,
        "SSA builder phase 1 only supports linear functions.",
    )


def test_rejects_function_with_jump() -> None:
    module = IRModule(
        [
            IRFunction(
                "loop",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRJump("entry")])],
            )
        ]
    )

    _assert_build_error(
        module,
        "SSA builder phase 1 only supports linear functions.",
    )


def test_rejects_load_from_uninitialized_slot() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    loaded = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                int_type,
                [IRBasicBlock("entry", [IRLoad(loaded, slot), IRReturn(loaded)])],
            )
        ]
    )

    _assert_build_error(module, "Load from uninitialized slot '%x'.")


def test_rejects_unsupported_ir_instruction() -> None:
    class IRUnsupported(IRInstruction):
        pass

    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRUnsupported()])],
            )
        ]
    )

    _assert_build_error(module, "Unsupported IR instruction 'IRUnsupported'.")


def test_rejects_multiple_blocks() -> None:
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRReturn()]),
                    IRBasicBlock("other", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_build_error(
        module,
        "SSA builder phase 1 only supports linear functions.",
    )
