from __future__ import annotations

import re

import pytest

from aether.ir import (
    BoolType,
    DoubleType,
    IntType,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCast,
    IRCall,
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
    GeneralSSABuildError,
    GeneralSSABuilder,
    SSABuilder,
    SSAModule,
    SSACast,
    SSAPhi,
    SSAVerifier,
    print_ssa,
)


def _build_and_verify(module: IRModule) -> SSAModule:
    ssa_module = GeneralSSABuilder().build_module(module)
    assert SSAVerifier(ssa_module).verify() is ssa_module
    return ssa_module


def _assert_build_error(module: IRModule, message: str) -> None:
    with pytest.raises(GeneralSSABuildError, match=re.escape(message)):
        GeneralSSABuilder().build_module(module)


def _value(name: str) -> IRValue:
    return IRValue(name, IntType())


def _condition(name: str = "condition") -> IRParameter:
    return IRParameter(name, BoolType())


def _phis(module: SSAModule) -> list[SSAPhi]:
    return [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSAPhi)
    ]


def _assert_no_slot_traffic(module: SSAModule) -> None:
    printed = print_ssa(module)
    assert "load" not in printed
    assert "store" not in printed


def _linear_module() -> IRModule:
    slot = _value("x")
    stored = _value("0")
    loaded = _value("1")
    return IRModule(
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


def _if_else_module() -> IRModule:
    int_type = IntType()
    x = IRParameter("x", int_type)
    y = IRValue("y", int_type)
    zero = IRValue("0", int_type)
    condition = IRValue("1", BoolType())
    one = IRValue("2", int_type)
    two = IRValue("3", int_type)
    loaded = IRValue("4", int_type)
    return IRModule(
        [
            IRFunction(
                "choose",
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


def _while_countdown_module() -> IRModule:
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
    return IRModule(
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


def test_builds_linear_function() -> None:
    ssa_module = _build_and_verify(_linear_module())

    assert print_ssa(ssa_module) == (
        "func @read_x() -> int {\n"
        "entry:\n"
        "    %0: int = const 5\n"
        "    return %0\n"
        "}"
    )
    _assert_no_slot_traffic(ssa_module)


def test_builds_numeric_cast() -> None:
    parameter = IRParameter("value", IntType())
    result = IRValue("0", DoubleType())
    module = IRModule(
        [
            IRFunction(
                "widen",
                [parameter],
                DoubleType(),
                [IRBasicBlock("entry", [IRCast(result, parameter), IRReturn(result)])],
            )
        ]
    )

    ssa_module = _build_and_verify(module)

    instruction = ssa_module.functions[0].blocks[0].instructions[0]
    assert instruction == SSACast(instruction.result, ssa_module.functions[0].parameters[0])
    assert instruction.result.type == DoubleType()


def test_builds_simple_if_else_with_phi() -> None:
    ssa_module = _build_and_verify(_if_else_module())

    assert len(_phis(ssa_module)) == 1
    assert "merge0:" in print_ssa(ssa_module)
    assert "phi(then0:" in print_ssa(ssa_module)
    _assert_no_slot_traffic(ssa_module)


def test_builds_while_countdown_with_loop_phi() -> None:
    ssa_module = _build_and_verify(_while_countdown_module())

    assert len(_phis(ssa_module)) == 1
    assert "cond0:" in print_ssa(ssa_module)
    assert "phi(entry:" in print_ssa(ssa_module)
    _assert_no_slot_traffic(ssa_module)


def test_builds_sum_to_with_i_and_sum_phis() -> None:
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
    module = IRModule(
        [
            IRFunction(
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
        ]
    )

    ssa_module = _build_and_verify(module)

    assert len(_phis(ssa_module)) == 2
    assert "return %3" in print_ssa(ssa_module)
    _assert_no_slot_traffic(ssa_module)


def test_builds_nested_if_manual() -> None:
    outer = _condition("outer")
    inner = _condition("inner")
    slot = _value("x")
    inner_then_value = _value("0")
    inner_else_value = _value("1")
    outer_else_value = _value("2")
    loaded = _value("3")
    module = IRModule(
        [
            IRFunction(
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
                    IRBasicBlock(
                        "merge_outer",
                        [IRLoad(loaded, slot), IRReturn(loaded)],
                    ),
                ],
            )
        ]
    )

    ssa_module = _build_and_verify(module)

    assert len(_phis(ssa_module)) == 2
    assert "merge_inner.x.phi: int = phi(then1: %0, else1: %1)" in print_ssa(
        ssa_module
    )
    assert "%3: int = phi(merge_inner: %merge_inner.x.phi, else0: %2)" in print_ssa(
        ssa_module
    )


def test_builds_module_with_multiple_functions() -> None:
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

    assert [function.name for function in ssa_module.functions] == ["increment", "main"]
    assert "call @increment" in print_ssa(ssa_module)


@pytest.mark.parametrize(
    "module",
    [_linear_module(), _if_else_module(), _while_countdown_module()],
)
def test_supported_pattern_cases_match_effective_builder_invariants(
    module: IRModule,
) -> None:
    general = _build_and_verify(module)
    effective = SSABuilder().build(module)

    assert SSAVerifier(effective).verify() is effective
    assert len(_phis(general)) == len(_phis(effective))
    _assert_no_slot_traffic(general)
    _assert_no_slot_traffic(effective)


def test_rejects_load_without_visible_value() -> None:
    slot = _value("x")
    loaded = _value("0")
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRLoad(loaded, slot), IRReturn(loaded)])],
            )
        ]
    )

    _assert_build_error(
        module,
        "General SSA build failed for function 'broken' during SSA renaming: "
        "Load from uninitialized slot '%x'.",
    )


def test_rejects_invalid_cfg() -> None:
    condition = _condition()
    module = IRModule(
        [
            IRFunction(
                "broken",
                [condition],
                IntType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then0", "missing")]),
                    IRBasicBlock("then0", [IRReturn(condition)]),
                ],
            )
        ]
    )

    _assert_build_error(
        module,
        "General SSA build failed for function 'broken' during SSA renaming: "
        "CFG edge references unknown target block 'missing'.",
    )


def test_rejects_incompatible_store_type() -> None:
    slot = _value("x")
    string_value = IRValue("0", StringType())
    module = IRModule(
        [
            IRFunction(
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
        ]
    )

    _assert_build_error(
        module,
        "General SSA build failed for function 'broken' during SSA renaming: "
        "Store to slot '%x' type mismatch: expected int, got string.",
    )


def test_rejects_renamer_duplicate_value_error_clearly() -> None:
    value = _value("0")
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(value, 1),
                            IRConst(value, 2),
                            IRReturn(value),
                        ],
                    )
                ],
            )
        ]
    )

    _assert_build_error(
        module,
        "General SSA build failed for function 'broken' during SSA renaming: "
        "Duplicate SSA value '%0'.",
    )
