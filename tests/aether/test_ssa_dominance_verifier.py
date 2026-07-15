from __future__ import annotations

import re

import pytest

from aether.ir import BoolType, IntType, VoidType
from aether.ssa import (
    SSABasicBlock,
    SSABinaryOp,
    SSABranch,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAJump,
    SSAModule,
    SSAParameter,
    SSAPhi,
    SSAReturn,
    SSAValue,
    SSAVerificationError,
    SSAVerifier,
)
from aether.ssa.optimizer import SSAOptimizationResult, SSAOptimizerPipeline


def _verify(function: SSAFunction) -> SSAFunction:
    module = SSAModule([function])
    assert SSAVerifier(module).verify() is module
    return function


def _reject(function: SSAFunction, message: str) -> None:
    with pytest.raises(SSAVerificationError, match=re.escape(message)):
        SSAVerifier(SSAModule([function])).verify()


def test_verifies_nested_loops_with_header_phis_and_backedges() -> None:
    int_type = IntType()
    bool_type = BoolType()
    zero = SSAValue("zero", int_type)
    one = SSAValue("one", int_type)
    limit = SSAValue("limit", int_type)
    outer_i = SSAValue("outer_i", int_type)
    outer_cond = SSAValue("outer_cond", bool_type)
    inner_i = SSAValue("inner_i", int_type)
    inner_cond = SSAValue("inner_cond", bool_type)
    inner_next = SSAValue("inner_next", int_type)
    outer_next = SSAValue("outer_next", int_type)

    _verify(
        SSAFunction(
            "nested",
            [],
            int_type,
            [
                SSABasicBlock(
                    "entry",
                    [
                        SSAConst(zero, 0),
                        SSAConst(one, 1),
                        SSAConst(limit, 3),
                        SSAJump("outer_header"),
                    ],
                ),
                SSABasicBlock(
                    "outer_header",
                    [
                        SSAPhi(
                            outer_i,
                            (("entry", zero), ("outer_latch", outer_next)),
                        ),
                        SSACompareOp(outer_cond, "lt", outer_i, limit),
                        SSABranch(outer_cond, "inner_header", "exit"),
                    ],
                ),
                SSABasicBlock(
                    "inner_header",
                    [
                        SSAPhi(
                            inner_i,
                            (("outer_header", zero), ("inner_body", inner_next)),
                        ),
                        SSACompareOp(inner_cond, "lt", inner_i, limit),
                        SSABranch(inner_cond, "inner_body", "outer_latch"),
                    ],
                ),
                SSABasicBlock(
                    "inner_body",
                    [
                        SSABinaryOp(inner_next, "add", inner_i, one),
                        SSAJump("inner_header"),
                    ],
                ),
                SSABasicBlock(
                    "outer_latch",
                    [
                        SSABinaryOp(outer_next, "add", outer_i, one),
                        SSAJump("outer_header"),
                    ],
                ),
                SSABasicBlock("exit", [SSAReturn(outer_i)]),
            ],
        )
    )


def test_parameter_and_entry_definition_dominate_multiple_blocks() -> None:
    int_type = IntType()
    parameter = SSAParameter("parameter", int_type)
    one = SSAValue("one", int_type)
    left = SSAValue("left", int_type)
    right = SSAValue("right", int_type)
    condition = SSAParameter("condition", BoolType())

    _verify(
        SSAFunction(
            "fanout",
            [parameter, condition],
            int_type,
            [
                SSABasicBlock(
                    "entry",
                    [SSAConst(one, 1), SSABranch(condition, "left", "right")],
                ),
                SSABasicBlock(
                    "left",
                    [SSABinaryOp(left, "add", parameter, one), SSAReturn(left)],
                ),
                SSABasicBlock(
                    "right",
                    [SSABinaryOp(right, "add", parameter, one), SSAReturn(right)],
                ),
            ],
        )
    )


def test_rejects_use_before_definition_in_same_block() -> None:
    int_type = IntType()
    value = SSAValue("value", int_type)
    result = SSAValue("result", int_type)
    _reject(
        SSAFunction(
            "bad_order",
            [],
            int_type,
            [
                SSABasicBlock(
                    "entry",
                    [
                        SSABinaryOp(result, "add", value, value),
                        SSAConst(value, 1),
                        SSAReturn(result),
                    ],
                )
            ],
        ),
        "SSA value '%value' is used before its definition in block 'entry'",
    )


def test_rejects_normal_use_of_value_from_sibling_branch() -> None:
    int_type = IntType()
    condition = SSAParameter("condition", BoolType())
    left_value = SSAValue("left_value", int_type)
    _reject(
        SSAFunction(
            "sibling_use",
            [condition],
            int_type,
            [
                SSABasicBlock("entry", [SSABranch(condition, "left", "right")]),
                SSABasicBlock("left", [SSAConst(left_value, 1), SSAJump("merge")]),
                SSABasicBlock("right", [SSAJump("merge")]),
                SSABasicBlock("merge", [SSAReturn(left_value)]),
            ],
        ),
        "SSA value '%left_value' used in block 'merge' is not dominated by "
        "its definition in block 'left'",
    )


def test_rejects_phi_missing_real_predecessor() -> None:
    int_type = IntType()
    condition = SSAParameter("condition", BoolType())
    left_value = SSAValue("left_value", int_type)
    right_value = SSAValue("right_value", int_type)
    merged = SSAValue("merged", int_type)
    _reject(
        SSAFunction(
            "missing_incoming",
            [condition],
            int_type,
            [
                SSABasicBlock("entry", [SSABranch(condition, "left", "right")]),
                SSABasicBlock("left", [SSAConst(left_value, 1), SSAJump("merge")]),
                SSABasicBlock("right", [SSAConst(right_value, 2), SSAJump("merge")]),
                SSABasicBlock(
                    "merge",
                    [SSAPhi(merged, (("left", left_value),)), SSAReturn(merged)],
                ),
            ],
        ),
        "Phi '%merged' in block 'merge' is missing an incoming value for "
        "predecessor 'right'",
    )


def test_rejects_phi_value_not_available_on_its_edge() -> None:
    int_type = IntType()
    condition = SSAParameter("condition", BoolType())
    left_value = SSAValue("left_value", int_type)
    right_value = SSAValue("right_value", int_type)
    merged = SSAValue("merged", int_type)
    _reject(
        SSAFunction(
            "bad_phi_edge",
            [condition],
            int_type,
            [
                SSABasicBlock("entry", [SSABranch(condition, "left", "right")]),
                SSABasicBlock("left", [SSAConst(left_value, 1), SSAJump("merge")]),
                SSABasicBlock("right", [SSAConst(right_value, 2), SSAJump("merge")]),
                SSABasicBlock(
                    "merge",
                    [
                        SSAPhi(
                            merged,
                            (("left", left_value), ("right", left_value)),
                        ),
                        SSAReturn(merged),
                    ],
                ),
            ],
        ),
        "Phi '%merged' in block 'merge' uses value '%left_value' for "
        "predecessor 'right', but that value is not available at the end of "
        "the predecessor; its definition is in block 'left'",
    )


def test_rejects_phi_with_invalid_backedge_value() -> None:
    int_type = IntType()
    initial = SSAValue("initial", int_type)
    loop_value = SSAValue("loop_value", int_type)
    late = SSAValue("late", int_type)
    condition = SSAParameter("condition", BoolType())
    _reject(
        SSAFunction(
            "bad_backedge",
            [condition],
            int_type,
            [
                SSABasicBlock("entry", [SSAConst(initial, 0), SSAJump("loop")]),
                SSABasicBlock(
                    "loop",
                    [
                        SSAPhi(loop_value, (("entry", initial), ("body", late))),
                        SSABranch(condition, "body", "exit"),
                    ],
                ),
                SSABasicBlock("body", [SSAJump("loop")]),
                SSABasicBlock("exit", [SSAConst(late, 1), SSAReturn(loop_value)]),
            ],
        ),
        "Phi '%loop_value' in block 'loop' uses value '%late' for predecessor "
        "'body', but that value is not available at the end of the predecessor",
    )


def test_rejects_phi_in_block_without_predecessors() -> None:
    int_type = IntType()
    value = SSAValue("value", int_type)
    merged = SSAValue("merged", int_type)
    _reject(
        SSAFunction(
            "orphan_phi",
            [],
            VoidType(),
            [
                SSABasicBlock("entry", [SSAConst(value, 1), SSAReturn()]),
                SSABasicBlock(
                    "orphan",
                    [SSAPhi(merged, (("entry", value),)), SSAReturn()],
                ),
            ],
        ),
        "Phi '%merged' in block 'orphan' has no CFG predecessors",
    )


def test_rejects_phi_in_entry_block() -> None:
    int_type = IntType()
    value = SSAValue("value", int_type)
    merged = SSAValue("merged", int_type)
    _reject(
        SSAFunction(
            "entry_phi",
            [],
            int_type,
            [
                SSABasicBlock(
                    "entry",
                    [
                        SSAPhi(merged, (("backedge", value),)),
                        SSAJump("backedge"),
                    ],
                ),
                SSABasicBlock(
                    "backedge",
                    [SSAConst(value, 1), SSAJump("entry")],
                ),
            ],
        ),
        "Phi '%merged' is not allowed in entry block 'entry'",
    )


def test_rejects_parallel_edges_not_representable_by_phi_model() -> None:
    condition = SSAParameter("condition", BoolType())
    _reject(
        SSAFunction(
            "parallel_edges",
            [condition],
            VoidType(),
            [
                SSABasicBlock(
                    "entry",
                    [SSABranch(condition, "exit", "exit")],
                ),
                SSABasicBlock("exit", [SSAReturn()]),
            ],
        ),
        "Branch in function 'parallel_edges' has duplicate target 'exit'",
    )


def test_unreachable_block_allows_ordered_local_uses() -> None:
    int_type = IntType()
    value = SSAValue("value", int_type)
    result = SSAValue("result", int_type)
    _verify(
        SSAFunction(
            "dead_local",
            [],
            VoidType(),
            [
                SSABasicBlock("entry", [SSAReturn()]),
                SSABasicBlock(
                    "dead",
                    [
                        SSAConst(value, 1),
                        SSABinaryOp(result, "add", value, value),
                        SSAReturn(),
                    ],
                ),
            ],
        )
    )


def test_unreachable_block_rejects_cross_block_definition() -> None:
    int_type = IntType()
    value = SSAValue("value", int_type)
    _reject(
        SSAFunction(
            "dead_cross_block",
            [],
            int_type,
            [
                SSABasicBlock("entry", [SSAConst(value, 1), SSAReturn(value)]),
                SSABasicBlock("dead", [SSAReturn(value)]),
            ],
        ),
        "SSA value '%value' used in block 'dead' is not dominated by its "
        "definition in block 'entry'",
    )


class _LeaveStalePhiPass:
    def run(self, module: SSAModule) -> SSAOptimizationResult:
        [function] = module.functions
        blocks = list(function.blocks)
        entry = blocks[0]
        right = blocks[2]
        updated = SSAFunction(
            function.name,
            list(function.parameters),
            function.return_type,
            [
                SSABasicBlock(entry.name, [SSAJump("left")]),
                blocks[1],
                SSABasicBlock(
                    right.name,
                    [
                        right.instructions[0],
                        SSAReturn(right.instructions[0].result),
                    ],
                ),
                blocks[3],
            ],
            function.entry_block,
        )
        return SSAOptimizationResult(SSAModule([updated]), changed=True)


class _BreakDominancePass:
    def run(self, module: SSAModule) -> SSAOptimizationResult:
        [function] = module.functions
        left_value = function.blocks[1].instructions[0].result
        merge = function.blocks[3]
        updated_merge = SSABasicBlock(
            merge.name,
            [merge.instructions[0], SSAReturn(left_value)],
        )
        updated = SSAFunction(
            function.name,
            list(function.parameters),
            function.return_type,
            [*function.blocks[:3], updated_merge],
            function.entry_block,
        )
        return SSAOptimizationResult(SSAModule([updated]), changed=True)


def _valid_diamond_module() -> SSAModule:
    int_type = IntType()
    condition = SSAParameter("condition", BoolType())
    left_value = SSAValue("left_value", int_type)
    right_value = SSAValue("right_value", int_type)
    merged = SSAValue("merged", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "diamond",
                [condition],
                int_type,
                [
                    SSABasicBlock("entry", [SSABranch(condition, "left", "right")]),
                    SSABasicBlock("left", [SSAConst(left_value, 1), SSAJump("merge")]),
                    SSABasicBlock("right", [SSAConst(right_value, 2), SSAJump("merge")]),
                    SSABasicBlock(
                        "merge",
                        [
                            SSAPhi(
                                merged,
                                (("left", left_value), ("right", right_value)),
                            ),
                            SSAReturn(merged),
                        ],
                    ),
                ],
            )
        ]
    )
    SSAVerifier(module).verify()
    return module


def test_optimizer_pipeline_rejects_edge_removal_with_stale_phi() -> None:
    with pytest.raises(
        SSAVerificationError,
        match="is not a predecessor of block 'merge'",
    ):
        SSAOptimizerPipeline(passes=[_LeaveStalePhiPass()]).run(
            _valid_diamond_module()
        )


def test_optimizer_pipeline_rejects_substitution_that_breaks_dominance() -> None:
    with pytest.raises(
        SSAVerificationError,
        match="is not dominated by its definition in block 'left'",
    ):
        SSAOptimizerPipeline(passes=[_BreakDominancePass()]).run(
            _valid_diamond_module()
        )
