from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pytest

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
)
from aether.ssa import (
    GeneralSSABuildError,
    GeneralSSABuilder,
    SSABranch,
    SSABuildError,
    SSABuilder,
    SSAModule,
    SSAPhi,
    SSAReturn,
    SSAVerifier,
    print_ssa,
)


SUPPORTED = "SUPPORTED"
PATTERN_ONLY = "PATTERN_ONLY"
GENERAL_ONLY = "GENERAL_ONLY"
UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class BuildResult:
    module: SSAModule | None
    error: Exception | None

    @property
    def ok(self) -> bool:
        return self.module is not None


@dataclass(frozen=True)
class StressCase:
    name: str
    module_factory: Callable[[], IRModule]
    classification: str
    general_phi_counts: dict[str, int] | None = None
    general_error_contains: str | None = None


def _int_value(name: str) -> IRValue:
    return IRValue(name, IntType())


def _bool_value(name: str) -> IRValue:
    return IRValue(name, BoolType())


def _int_parameter(name: str) -> IRParameter:
    return IRParameter(name, IntType())


def _bool_parameter(name: str) -> IRParameter:
    return IRParameter(name, BoolType())


def _build_pattern(module: IRModule) -> BuildResult:
    try:
        ssa_module = SSABuilder().build(module)
        assert SSAVerifier(ssa_module).verify() is ssa_module
        return BuildResult(ssa_module, None)
    except Exception as error:
        return BuildResult(None, error)


def _build_general(module: IRModule) -> BuildResult:
    try:
        ssa_module = GeneralSSABuilder().build_module(module)
        assert SSAVerifier(ssa_module).verify() is ssa_module
        return BuildResult(ssa_module, None)
    except Exception as error:
        return BuildResult(None, error)


def _classification(pattern: BuildResult, general: BuildResult) -> str:
    if pattern.ok and general.ok:
        return SUPPORTED
    if pattern.ok:
        return PATTERN_ONLY
    if general.ok:
        return GENERAL_ONLY
    return UNSUPPORTED


def _phi_counts_by_block(module: SSAModule) -> dict[str, int]:
    counts: dict[str, int] = {}
    for function in module.functions:
        for block in function.blocks:
            counts[block.name] = sum(
                isinstance(instruction, SSAPhi)
                for instruction in block.instructions
            )
    return counts


def _assert_no_slot_traffic(module: SSAModule) -> None:
    printed = print_ssa(module)
    assert " load " not in printed
    assert " store " not in printed
    assert "\n    load " not in printed
    assert "\n    store " not in printed


def _assert_cfg_targets_exist(module: SSAModule) -> None:
    for function in module.functions:
        block_names = {block.name for block in function.blocks}
        for block in function.blocks:
            assert block.instructions
            terminator = block.instructions[-1]
            if isinstance(terminator, SSABranch):
                assert terminator.true_target in block_names
                assert terminator.false_target in block_names
            elif isinstance(terminator, SSAReturn):
                continue
            else:
                assert terminator.target in block_names


def _nested_if_module() -> IRModule:
    outer = _bool_parameter("outer")
    inner = _bool_parameter("inner")
    slot = _int_value("x")
    inner_then_value = _int_value("0")
    inner_else_value = _int_value("1")
    outer_else_value = _int_value("2")
    loaded = _int_value("3")
    return IRModule(
        [
            IRFunction(
                "nested_if",
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


def _sequential_ifs_module() -> IRModule:
    first = _bool_parameter("first")
    second = _bool_parameter("second")
    slot = _int_value("x")
    first_then = _int_value("0")
    first_else = _int_value("1")
    second_then = _int_value("2")
    second_else = _int_value("3")
    first_loaded = _int_value("4")
    result = _int_value("5")
    return IRModule(
        [
            IRFunction(
                "sequential_ifs",
                [first, second],
                IntType(),
                [
                    IRBasicBlock("entry", [IRBranch(first, "then0", "else0")]),
                    IRBasicBlock(
                        "then0",
                        [IRConst(first_then, 1), IRStore(slot, first_then), IRJump("merge0")],
                    ),
                    IRBasicBlock(
                        "else0",
                        [IRConst(first_else, 2), IRStore(slot, first_else), IRJump("merge0")],
                    ),
                    IRBasicBlock(
                        "merge0",
                        [IRLoad(first_loaded, slot), IRBranch(second, "then1", "else1")],
                    ),
                    IRBasicBlock(
                        "then1",
                        [
                            IRConst(second_then, 10),
                            IRStore(slot, second_then),
                            IRJump("merge1"),
                        ],
                    ),
                    IRBasicBlock(
                        "else1",
                        [
                            IRConst(second_else, 20),
                            IRStore(slot, second_else),
                            IRJump("merge1"),
                        ],
                    ),
                    IRBasicBlock("merge1", [IRLoad(result, slot), IRReturn(result)]),
                ],
            )
        ]
    )


def _if_in_while_module() -> IRModule:
    n = _int_parameter("n")
    choose = _bool_parameter("choose")
    i = _int_value("i")
    slot = _int_value("x")
    zero = _int_value("0")
    one = _int_value("1")
    loaded_i = _int_value("2")
    condition = _bool_value("3")
    then_value = _int_value("4")
    else_value = _int_value("5")
    loaded_x = _int_value("6")
    body_i = _int_value("7")
    next_i = _int_value("8")
    result = _int_value("9")
    return IRModule(
        [
            IRFunction(
                "if_in_while",
                [n, choose],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(zero, 0),
                            IRConst(one, 1),
                            IRStore(i, zero),
                            IRStore(slot, zero),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock(
                        "cond0",
                        [
                            IRLoad(loaded_i, i),
                            IRCompareOp(condition, "lt", loaded_i, n),
                            IRBranch(condition, "body0", "exit0"),
                        ],
                    ),
                    IRBasicBlock("body0", [IRBranch(choose, "then0", "else0")]),
                    IRBasicBlock(
                        "then0",
                        [IRConst(then_value, 10), IRStore(slot, then_value), IRJump("merge0")],
                    ),
                    IRBasicBlock(
                        "else0",
                        [IRConst(else_value, 20), IRStore(slot, else_value), IRJump("merge0")],
                    ),
                    IRBasicBlock(
                        "merge0",
                        [
                            IRLoad(loaded_x, slot),
                            IRLoad(body_i, i),
                            IRBinaryOp(next_i, "add", body_i, one),
                            IRStore(i, next_i),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock("exit0", [IRLoad(result, slot), IRReturn(result)]),
                ],
            )
        ]
    )


def _while_in_if_module() -> IRModule:
    choose = _bool_parameter("choose")
    n = _int_parameter("n")
    i = _int_value("i")
    slot = _int_value("x")
    zero = _int_value("0")
    one = _int_value("1")
    else_value = _int_value("2")
    loaded_i = _int_value("3")
    condition = _bool_value("4")
    loaded_x = _int_value("5")
    next_x = _int_value("6")
    body_i = _int_value("7")
    next_i = _int_value("8")
    result = _int_value("9")
    return IRModule(
        [
            IRFunction(
                "while_in_if",
                [choose, n],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(zero, 0),
                            IRConst(one, 1),
                            IRStore(i, zero),
                            IRStore(slot, zero),
                            IRBranch(choose, "then0", "else0"),
                        ],
                    ),
                    IRBasicBlock("then0", [IRJump("cond0")]),
                    IRBasicBlock(
                        "cond0",
                        [
                            IRLoad(loaded_i, i),
                            IRCompareOp(condition, "lt", loaded_i, n),
                            IRBranch(condition, "body0", "after_then"),
                        ],
                    ),
                    IRBasicBlock(
                        "body0",
                        [
                            IRLoad(loaded_x, slot),
                            IRBinaryOp(next_x, "add", loaded_x, one),
                            IRStore(slot, next_x),
                            IRLoad(body_i, i),
                            IRBinaryOp(next_i, "add", body_i, one),
                            IRStore(i, next_i),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock("after_then", [IRJump("merge0")]),
                    IRBasicBlock(
                        "else0",
                        [IRConst(else_value, 42), IRStore(slot, else_value), IRJump("merge0")],
                    ),
                    IRBasicBlock("merge0", [IRLoad(result, slot), IRReturn(result)]),
                ],
            )
        ]
    )


def _multi_loop_carried_slots_module() -> IRModule:
    n = _int_parameter("n")
    i = _int_value("i")
    total = _int_value("sum")
    maximum = _int_value("max")
    zero = _int_value("0")
    one = _int_value("1")
    loaded_i = _int_value("2")
    loaded_sum = _int_value("3")
    loaded_max = _int_value("4")
    condition = _bool_value("5")
    body_i = _int_value("6")
    next_i = _int_value("7")
    body_sum = _int_value("8")
    next_sum = _int_value("9")
    body_max = _int_value("10")
    next_max = _int_value("11")
    result = _int_value("12")
    return IRModule(
        [
            IRFunction(
                "multi_loop_carried_slots",
                [n],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(zero, 0),
                            IRConst(one, 1),
                            IRStore(i, zero),
                            IRStore(total, zero),
                            IRStore(maximum, zero),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock(
                        "cond0",
                        [
                            IRLoad(loaded_i, i),
                            IRLoad(loaded_sum, total),
                            IRLoad(loaded_max, maximum),
                            IRCompareOp(condition, "lt", loaded_i, n),
                            IRBranch(condition, "body0", "exit0"),
                        ],
                    ),
                    IRBasicBlock(
                        "body0",
                        [
                            IRLoad(body_i, i),
                            IRBinaryOp(next_i, "add", body_i, one),
                            IRStore(i, next_i),
                            IRLoad(body_sum, total),
                            IRBinaryOp(next_sum, "add", body_sum, next_i),
                            IRStore(total, next_sum),
                            IRLoad(body_max, maximum),
                            IRBinaryOp(next_max, "add", body_max, next_sum),
                            IRStore(maximum, next_max),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock("exit0", [IRLoad(result, maximum), IRReturn(result)]),
                ],
            )
        ]
    )


def _sequential_loops_module() -> IRModule:
    n = _int_parameter("n")
    m = _int_parameter("m")
    i = _int_value("i")
    total = _int_value("sum")
    zero = _int_value("0")
    one = _int_value("1")
    first_i = _int_value("2")
    first_condition = _bool_value("3")
    first_body_i = _int_value("4")
    first_next_i = _int_value("5")
    first_sum = _int_value("6")
    first_next_sum = _int_value("7")
    second_i = _int_value("8")
    second_condition = _bool_value("9")
    second_body_i = _int_value("10")
    second_next_i = _int_value("11")
    second_sum = _int_value("12")
    second_next_sum = _int_value("13")
    result = _int_value("14")
    return IRModule(
        [
            IRFunction(
                "sequential_loops",
                [n, m],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(zero, 0),
                            IRConst(one, 1),
                            IRStore(i, zero),
                            IRStore(total, zero),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock(
                        "cond0",
                        [
                            IRLoad(first_i, i),
                            IRCompareOp(first_condition, "lt", first_i, n),
                            IRBranch(first_condition, "body0", "after0"),
                        ],
                    ),
                    IRBasicBlock(
                        "body0",
                        [
                            IRLoad(first_body_i, i),
                            IRBinaryOp(first_next_i, "add", first_body_i, one),
                            IRStore(i, first_next_i),
                            IRLoad(first_sum, total),
                            IRBinaryOp(first_next_sum, "add", first_sum, first_next_i),
                            IRStore(total, first_next_sum),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock("after0", [IRStore(i, zero), IRJump("cond1")]),
                    IRBasicBlock(
                        "cond1",
                        [
                            IRLoad(second_i, i),
                            IRCompareOp(second_condition, "lt", second_i, m),
                            IRBranch(second_condition, "body1", "exit0"),
                        ],
                    ),
                    IRBasicBlock(
                        "body1",
                        [
                            IRLoad(second_body_i, i),
                            IRBinaryOp(second_next_i, "add", second_body_i, one),
                            IRStore(i, second_next_i),
                            IRLoad(second_sum, total),
                            IRBinaryOp(second_next_sum, "add", second_sum, second_next_i),
                            IRStore(total, second_next_sum),
                            IRJump("cond1"),
                        ],
                    ),
                    IRBasicBlock("exit0", [IRLoad(result, total), IRReturn(result)]),
                ],
            )
        ]
    )


def _several_merges_module() -> IRModule:
    first = _bool_parameter("first")
    second = _bool_parameter("second")
    x = _int_value("x")
    y = _int_value("y")
    first_then = _int_value("0")
    first_else = _int_value("1")
    second_then = _int_value("2")
    second_else = _int_value("3")
    loaded_x = _int_value("4")
    loaded_y = _int_value("5")
    result = _int_value("6")
    return IRModule(
        [
            IRFunction(
                "several_merges",
                [first, second],
                IntType(),
                [
                    IRBasicBlock("entry", [IRBranch(first, "then0", "else0")]),
                    IRBasicBlock(
                        "then0",
                        [IRConst(first_then, 1), IRStore(x, first_then), IRJump("merge0")],
                    ),
                    IRBasicBlock(
                        "else0",
                        [IRConst(first_else, 2), IRStore(x, first_else), IRJump("merge0")],
                    ),
                    IRBasicBlock("merge0", [IRBranch(second, "then1", "else1")]),
                    IRBasicBlock(
                        "then1",
                        [IRConst(second_then, 3), IRStore(y, second_then), IRJump("merge1")],
                    ),
                    IRBasicBlock(
                        "else1",
                        [IRConst(second_else, 4), IRStore(y, second_else), IRJump("merge1")],
                    ),
                    IRBasicBlock(
                        "merge1",
                        [
                            IRLoad(loaded_x, x),
                            IRLoad(loaded_y, y),
                            IRBinaryOp(result, "add", loaded_x, loaded_y),
                            IRReturn(result),
                        ],
                    ),
                ],
            )
        ]
    )


def _large_function_module() -> IRModule:
    first = _bool_parameter("first")
    second = _bool_parameter("second")
    n = _int_parameter("n")
    x = _int_value("x")
    y = _int_value("y")
    i = _int_value("i")
    z = _int_value("z")
    values = [_int_value(str(index)) for index in range(30)]
    loop_condition = _bool_value("5")
    return IRModule(
        [
            IRFunction(
                "large_general_cfg",
                [first, second, n],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(values[0], 0),
                            IRConst(values[1], 1),
                            IRStore(x, values[0]),
                            IRStore(y, values[1]),
                            IRStore(i, values[0]),
                            IRBranch(first, "then0", "else0"),
                        ],
                    ),
                    IRBasicBlock(
                        "then0",
                        [IRConst(values[2], 10), IRStore(x, values[2]), IRJump("merge0")],
                    ),
                    IRBasicBlock(
                        "else0",
                        [IRConst(values[3], 20), IRStore(x, values[3]), IRJump("merge0")],
                    ),
                    IRBasicBlock("merge0", [IRJump("cond0")]),
                    IRBasicBlock(
                        "cond0",
                        [
                            IRLoad(values[4], i),
                            IRCompareOp(loop_condition, "lt", values[4], n),
                            IRBranch(loop_condition, "body0", "after_loop"),
                        ],
                    ),
                    IRBasicBlock("body0", [IRBranch(second, "then1", "else1")]),
                    IRBasicBlock(
                        "then1",
                        [
                            IRLoad(values[6], x),
                            IRBinaryOp(values[7], "add", values[6], values[1]),
                            IRStore(x, values[7]),
                            IRJump("merge1"),
                        ],
                    ),
                    IRBasicBlock(
                        "else1",
                        [
                            IRLoad(values[8], y),
                            IRBinaryOp(values[9], "add", values[8], values[1]),
                            IRStore(y, values[9]),
                            IRJump("merge1"),
                        ],
                    ),
                    IRBasicBlock(
                        "merge1",
                        [
                            IRLoad(values[10], i),
                            IRBinaryOp(values[11], "add", values[10], values[1]),
                            IRStore(i, values[11]),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock(
                        "after_loop",
                        [IRBranch(first, "then2", "else2")],
                    ),
                    IRBasicBlock(
                        "then2",
                        [
                            IRLoad(values[12], x),
                            IRLoad(values[13], y),
                            IRBinaryOp(values[14], "add", values[12], values[13]),
                            IRStore(z, values[14]),
                            IRJump("merge2"),
                        ],
                    ),
                    IRBasicBlock(
                        "else2",
                        [
                            IRLoad(values[15], x),
                            IRBinaryOp(values[16], "add", values[15], values[0]),
                            IRStore(z, values[16]),
                            IRJump("merge2"),
                        ],
                    ),
                    IRBasicBlock("merge2", [IRLoad(values[17], z), IRReturn(values[17])]),
                ],
            )
        ]
    )


def _nested_while_module(*, initialize_inner_slot: bool) -> IRModule:
    n = _int_parameter("n")
    m = _int_parameter("m")
    i = _int_value("i")
    j = _int_value("j")
    total = _int_value("sum")
    zero = _int_value("0")
    one = _int_value("1")
    outer_i = _int_value("2")
    outer_condition = _bool_value("3")
    inner_j = _int_value("4")
    inner_condition = _bool_value("5")
    body_j = _int_value("6")
    next_j = _int_value("7")
    body_sum = _int_value("8")
    next_sum = _int_value("9")
    body_i = _int_value("10")
    next_i = _int_value("11")
    result = _int_value("12")
    entry_instructions = [
        IRConst(zero, 0),
        IRConst(one, 1),
        IRStore(i, zero),
        IRStore(total, zero),
    ]
    if initialize_inner_slot:
        entry_instructions.append(IRStore(j, zero))
    entry_instructions.append(IRJump("outer_cond"))
    return IRModule(
        [
            IRFunction(
                "nested_while",
                [n, m],
                IntType(),
                [
                    IRBasicBlock("entry", entry_instructions),
                    IRBasicBlock(
                        "outer_cond",
                        [
                            IRLoad(outer_i, i),
                            IRCompareOp(outer_condition, "lt", outer_i, n),
                            IRBranch(outer_condition, "outer_body", "exit0"),
                        ],
                    ),
                    IRBasicBlock(
                        "outer_body",
                        [IRStore(j, zero), IRJump("inner_cond")],
                    ),
                    IRBasicBlock(
                        "inner_cond",
                        [
                            IRLoad(inner_j, j),
                            IRCompareOp(inner_condition, "lt", inner_j, m),
                            IRBranch(inner_condition, "inner_body", "inner_exit"),
                        ],
                    ),
                    IRBasicBlock(
                        "inner_body",
                        [
                            IRLoad(body_j, j),
                            IRBinaryOp(next_j, "add", body_j, one),
                            IRStore(j, next_j),
                            IRLoad(body_sum, total),
                            IRBinaryOp(next_sum, "add", body_sum, next_j),
                            IRStore(total, next_sum),
                            IRJump("inner_cond"),
                        ],
                    ),
                    IRBasicBlock(
                        "inner_exit",
                        [
                            IRLoad(body_i, i),
                            IRBinaryOp(next_i, "add", body_i, one),
                            IRStore(i, next_i),
                            IRJump("outer_cond"),
                        ],
                    ),
                    IRBasicBlock("exit0", [IRLoad(result, total), IRReturn(result)]),
                ],
            )
        ]
    )


def _nested_while_with_initialized_inner_slot_module() -> IRModule:
    return _nested_while_module(initialize_inner_slot=True)


def _nested_while_with_loop_local_inner_slot_module() -> IRModule:
    return _nested_while_module(initialize_inner_slot=False)


def _while_in_if_with_branch_local_loop_slot_module() -> IRModule:
    choose = _bool_parameter("choose")
    n = _int_parameter("n")
    i = _int_value("i")
    slot = _int_value("x")
    zero = _int_value("0")
    one = _int_value("1")
    else_value = _int_value("2")
    loaded_i = _int_value("3")
    condition = _bool_value("4")
    loaded_x = _int_value("5")
    next_x = _int_value("6")
    body_i = _int_value("7")
    next_i = _int_value("8")
    result = _int_value("9")
    return IRModule(
        [
            IRFunction(
                "while_in_if_branch_local_loop_slot",
                [choose, n],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(zero, 0),
                            IRConst(one, 1),
                            IRStore(slot, zero),
                            IRBranch(choose, "then0", "else0"),
                        ],
                    ),
                    IRBasicBlock("then0", [IRStore(i, zero), IRJump("cond0")]),
                    IRBasicBlock(
                        "cond0",
                        [
                            IRLoad(loaded_i, i),
                            IRCompareOp(condition, "lt", loaded_i, n),
                            IRBranch(condition, "body0", "after_then"),
                        ],
                    ),
                    IRBasicBlock(
                        "body0",
                        [
                            IRLoad(loaded_x, slot),
                            IRBinaryOp(next_x, "add", loaded_x, one),
                            IRStore(slot, next_x),
                            IRLoad(body_i, i),
                            IRBinaryOp(next_i, "add", body_i, one),
                            IRStore(i, next_i),
                            IRJump("cond0"),
                        ],
                    ),
                    IRBasicBlock("after_then", [IRJump("merge0")]),
                    IRBasicBlock(
                        "else0",
                        [IRConst(else_value, 42), IRStore(slot, else_value), IRJump("merge0")],
                    ),
                    IRBasicBlock("merge0", [IRLoad(result, slot), IRReturn(result)]),
                ],
            )
        ]
    )


STRESS_CASES = [
    StressCase(
        "nested if",
        _nested_if_module,
        GENERAL_ONLY,
        {"merge_inner": 1, "merge_outer": 1},
    ),
    StressCase(
        "two sequential ifs",
        _sequential_ifs_module,
        GENERAL_ONLY,
        {"merge0": 1, "merge1": 1},
    ),
    StressCase(
        "if inside while",
        _if_in_while_module,
        GENERAL_ONLY,
        {"cond0": 2, "merge0": 1},
    ),
    StressCase(
        "while inside if",
        _while_in_if_module,
        GENERAL_ONLY,
        {"cond0": 2, "merge0": 2},
    ),
    StressCase(
        "while with multiple loop-carried slots",
        _multi_loop_carried_slots_module,
        SUPPORTED,
        {"cond0": 3},
    ),
    StressCase(
        "two sequential loops",
        _sequential_loops_module,
        GENERAL_ONLY,
        {"cond0": 2, "cond1": 2},
    ),
    StressCase(
        "several independent merges",
        _several_merges_module,
        GENERAL_ONLY,
        {"merge0": 1, "merge1": 1},
    ),
    StressCase(
        "large function",
        _large_function_module,
        GENERAL_ONLY,
        {"merge0": 1, "cond0": 3, "merge1": 2, "merge2": 1},
    ),
    StressCase(
        "nested while with initialized inner slot",
        _nested_while_with_initialized_inner_slot_module,
        GENERAL_ONLY,
        {"outer_cond": 3, "inner_cond": 2},
    ),
    StressCase(
        "nested while with loop-local inner slot",
        _nested_while_with_loop_local_inner_slot_module,
        GENERAL_ONLY,
        {"outer_cond": 2, "inner_cond": 2},
    ),
    StressCase(
        "while inside if with branch-local loop slot",
        _while_in_if_with_branch_local_loop_slot_module,
        GENERAL_ONLY,
        {"cond0": 2, "merge0": 1},
    ),
]


@pytest.mark.parametrize("case", STRESS_CASES, ids=lambda case: case.name)
def test_general_ssa_builder_stress_coverage(case: StressCase) -> None:
    pattern = _build_pattern(case.module_factory())
    general = _build_general(case.module_factory())

    assert _classification(pattern, general) == case.classification

    if pattern.ok:
        assert pattern.module is not None
        _assert_no_slot_traffic(pattern.module)
        _assert_cfg_targets_exist(pattern.module)
    else:
        assert isinstance(pattern.error, SSABuildError)

    if general.ok:
        assert general.module is not None
        _assert_no_slot_traffic(general.module)
        _assert_cfg_targets_exist(general.module)
        if case.general_phi_counts is not None:
            assert {
                block: count
                for block, count in _phi_counts_by_block(general.module).items()
                if count
            } == case.general_phi_counts
    else:
        assert isinstance(general.error, GeneralSSABuildError)
        assert case.general_error_contains is not None
        assert case.general_error_contains in str(general.error)

    if case.classification == SUPPORTED:
        assert pattern.module is not None
        assert general.module is not None
        assert _phi_counts_by_block(pattern.module) == _phi_counts_by_block(
            general.module
        )
