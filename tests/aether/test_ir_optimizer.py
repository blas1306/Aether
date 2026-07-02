from __future__ import annotations

import pytest

from aether.ir import (
    BoolType,
    DoubleType,
    FloatType,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
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
    IntType,
    StringType,
    VoidType,
    print_ir,
)
from aether.ir.optimizer import (
    AlgebraicSimplifier,
    ConstantFolder,
    DeadCodeEliminator,
    DeadStoreEliminator,
    LocalConstantPropagator,
    OptimizerPipeline,
)


def _optimize(module: IRModule) -> IRModule:
    return ConstantFolder().run(module).module


def _dce(module: IRModule) -> IRModule:
    return DeadCodeEliminator().run(module).module


def _dse(module: IRModule) -> IRModule:
    return DeadStoreEliminator().run(module).module


def _simplify(module: IRModule) -> IRModule:
    return AlgebraicSimplifier().run(module).module


def _propagate(module: IRModule) -> IRModule:
    return LocalConstantPropagator().run(module).module


def _single_block_module(instructions: list[object], return_value: IRValue) -> IRModule:
    return IRModule(
        [
            IRFunction(
                "main",
                [],
                return_value.type,
                [IRBasicBlock("entry", [*instructions, IRReturn(return_value)])],
            )
        ]
    )


@pytest.mark.parametrize(
    ("operator", "left_value", "right_value", "expected"),
    [
        ("add", 2, 3, 5),
        ("sub", 8, 3, 5),
        ("mul", 4, 6, 24),
        ("mod", 17, 5, 2),
        ("rem", -7, 3, -1),
    ],
)
def test_constant_folding_arithmetic_int_ops(
    operator: str,
    left_value: int,
    right_value: int,
    expected: int,
) -> None:
    int_type = IntType()
    left = IRValue("0", int_type)
    right = IRValue("1", int_type)
    result = IRValue("2", int_type)
    module = _single_block_module(
        [
            IRConst(left, left_value),
            IRConst(right, right_value),
            IRBinaryOp(result, operator, left, right),
        ],
        result,
    )

    optimized = _optimize(module)

    assert optimized is not module
    assert print_ir(module) == (
        "func @main() -> int {\n"
        "entry:\n"
        f"    %0: int = const {left_value}\n"
        f"    %1: int = const {right_value}\n"
        f"    %2: int = {operator} %0, %1\n"
        "    return %2\n"
        "}"
    )
    assert print_ir(optimized) == (
        "func @main() -> int {\n"
        "entry:\n"
        f"    %0: int = const {left_value}\n"
        f"    %1: int = const {right_value}\n"
        f"    %2: int = const {expected}\n"
        "    return %2\n"
        "}"
    )


def test_constant_folding_division() -> None:
    int_type = IntType()
    double_type = DoubleType()
    left = IRValue("0", int_type)
    right = IRValue("1", int_type)
    result = IRValue("2", double_type)
    module = _single_block_module(
        [
            IRConst(left, 9),
            IRConst(right, 2),
            IRBinaryOp(result, "div", left, right),
        ],
        result,
    )

    assert print_ir(_optimize(module)) == (
        "func @main() -> double {\n"
        "entry:\n"
        "    %0: int = const 9\n"
        "    %1: int = const 2\n"
        "    %2: double = const 4.5\n"
        "    return %2\n"
        "}"
    )


@pytest.mark.parametrize(
    ("operator", "left_value", "right_value", "expected"),
    [
        ("lt", 2, 5, True),
        ("le", 5, 5, True),
        ("gt", 7, 3, True),
        ("ge", 7, 7, True),
        ("eq", 4, 4, True),
        ("ne", 4, 5, True),
    ],
)
def test_constant_folding_comparisons(
    operator: str,
    left_value: int,
    right_value: int,
    expected: bool,
) -> None:
    int_type = IntType()
    bool_type = BoolType()
    left = IRValue("0", int_type)
    right = IRValue("1", int_type)
    result = IRValue("2", bool_type)
    module = _single_block_module(
        [
            IRConst(left, left_value),
            IRConst(right, right_value),
            IRCompareOp(result, operator, left, right),
        ],
        result,
    )

    assert print_ir(_optimize(module)) == (
        "func @main() -> bool {\n"
        "entry:\n"
        f"    %0: int = const {left_value}\n"
        f"    %1: int = const {right_value}\n"
        f"    %2: bool = const {str(expected).lower()}\n"
        "    return %2\n"
        "}"
    )


def test_constant_folding_multiple_folds_in_one_function() -> None:
    int_type = IntType()
    two = IRValue("0", int_type)
    three = IRValue("1", int_type)
    five = IRValue("2", int_type)
    total = IRValue("3", int_type)
    module = _single_block_module(
        [
            IRConst(two, 2),
            IRConst(three, 3),
            IRBinaryOp(five, "add", two, three),
            IRBinaryOp(total, "mul", five, three),
        ],
        total,
    )

    assert print_ir(_optimize(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %0: int = const 2\n"
        "    %1: int = const 3\n"
        "    %2: int = const 5\n"
        "    %3: int = const 15\n"
        "    return %3\n"
        "}"
    )


def test_optimizer_pipeline_runs_constant_folding_then_dead_code_elimination() -> None:
    int_type = IntType()
    one = IRValue("0", int_type)
    two = IRValue("1", int_type)
    three = IRValue("2", int_type)
    result = IRValue("3", int_type)
    module = _single_block_module(
        [
            IRConst(one, 1),
            IRConst(two, 2),
            IRConst(three, 3),
            IRBinaryOp(result, "add", one, three),
        ],
        result,
    )

    assert print_ir(OptimizerPipeline().run(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %3: int = const 4\n"
        "    return %3\n"
        "}"
    )


def test_optimization_pass_reports_when_it_changes_ir() -> None:
    int_type = IntType()
    left = IRValue("0", int_type)
    right = IRValue("1", int_type)
    result = IRValue("2", int_type)
    module = _single_block_module(
        [
            IRConst(left, 2),
            IRConst(right, 3),
            IRBinaryOp(result, "add", left, right),
        ],
        result,
    )

    optimization = ConstantFolder().run(module)

    assert optimization.changed is True
    assert "%2: int = const 5" in print_ir(optimization.module)


def test_optimization_pass_reports_when_ir_is_unchanged() -> None:
    int_type = IntType()
    parameter = IRParameter("x", int_type)
    one = IRValue("0", int_type)
    result = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "addOne",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(one, 1),
                            IRBinaryOp(result, "add", parameter, one),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    optimization = ConstantFolder().run(module)

    assert optimization.changed is False
    assert print_ir(optimization.module) == print_ir(module)


def test_optimizer_pipeline_trace_includes_every_default_pass_and_final_ir() -> None:
    int_type = IntType()
    parameter = IRParameter("x", int_type)
    one = IRValue("0", int_type)
    result = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(one, 1),
                            IRBinaryOp(result, "add", parameter, one),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    trace = OptimizerPipeline().run_with_trace(module)

    assert [name for name, _ in trace] == [
        "Lowered IR",
        "ConstantFolder",
        "LocalConstantPropagator",
        "ConstantFolder",
        "AlgebraicSimplifier",
        "DeadCodeEliminator",
        "DeadStoreEliminator",
        "DeadCodeEliminator",
        "Final IR",
    ]
    assert print_ir(trace[0][1]) == print_ir(module)
    assert print_ir(trace[-1][1]) == print_ir(OptimizerPipeline().run(module))


def test_constant_folding_does_not_fold_expression_with_variable() -> None:
    int_type = IntType()
    parameter = IRParameter("x", int_type)
    one = IRValue("0", int_type)
    result = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "addOne",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(one, 1),
                            IRBinaryOp(result, "add", parameter, one),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_optimize(module)) == print_ir(module)


def test_constant_folding_does_not_evaluate_division_by_zero() -> None:
    int_type = IntType()
    double_type = DoubleType()
    one = IRValue("0", int_type)
    zero = IRValue("1", int_type)
    result = IRValue("2", double_type)
    module = _single_block_module(
        [
            IRConst(one, 1),
            IRConst(zero, 0),
            IRBinaryOp(result, "div", one, zero),
        ],
        result,
    )

    assert print_ir(_optimize(module)) == print_ir(module)


def test_constant_folding_does_not_fold_function_calls() -> None:
    int_type = IntType()
    value = IRValue("0", int_type)
    result = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "identity",
                [IRParameter("value", int_type)],
                int_type,
                [IRBasicBlock("entry", [IRReturn(IRParameter("value", int_type))])],
            ),
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(value, 3),
                            IRCall("identity", (value,), result),
                            IRReturn(result),
                        ],
                    )
                ],
            ),
        ]
    )

    assert print_ir(_optimize(module)) == print_ir(module)


def test_constant_folding_does_not_fold_load_or_store() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    result = IRValue("2", int_type)
    module = _single_block_module(
        [
            IRConst(stored, 4),
            IRStore(slot, stored),
            IRLoad(loaded, slot),
            IRBinaryOp(result, "add", loaded, stored),
        ],
        result,
    )

    assert print_ir(_optimize(module)) == print_ir(module)


def test_local_constant_propagation_replaces_same_block_load() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = _single_block_module(
        [
            IRConst(stored, 5),
            IRStore(slot, stored),
            IRLoad(loaded, slot),
        ],
        loaded,
    )

    assert print_ir(_propagate(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %0: int = const 5\n"
        "    store %x, %0\n"
        "    %1: int = const 5\n"
        "    return %1\n"
        "}"
    )


def test_local_constant_propagation_enables_later_constant_folding() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    five = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    seven = IRValue("2", int_type)
    result = IRValue("3", int_type)
    module = _single_block_module(
        [
            IRConst(five, 5),
            IRStore(slot, five),
            IRLoad(loaded, slot),
            IRConst(seven, 7),
            IRBinaryOp(result, "add", loaded, seven),
        ],
        result,
    )

    assert print_ir(OptimizerPipeline().run(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %3: int = const 12\n"
        "    return %3\n"
        "}"
    )


def test_local_constant_propagation_updates_slot_with_new_constant() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    five = IRValue("0", int_type)
    seven = IRValue("1", int_type)
    loaded = IRValue("2", int_type)
    module = _single_block_module(
        [
            IRConst(five, 5),
            IRStore(slot, five),
            IRConst(seven, 7),
            IRStore(slot, seven),
            IRLoad(loaded, slot),
        ],
        loaded,
    )

    assert "%2: int = const 7" in print_ir(_propagate(module))


def test_local_constant_propagation_handles_string_slots() -> None:
    string_type = StringType()
    slot = IRValue("message", string_type)
    stored = IRValue("0", string_type)
    loaded = IRValue("1", string_type)
    module = _single_block_module(
        [
            IRConst(stored, "hello"),
            IRStore(slot, stored),
            IRLoad(loaded, slot),
        ],
        loaded,
    )

    assert "%1: string = const \"hello\"" in print_ir(_propagate(module))


def test_local_constant_propagation_handles_bool_slots() -> None:
    bool_type = BoolType()
    slot = IRValue("flag", bool_type)
    stored = IRValue("0", bool_type)
    loaded = IRValue("1", bool_type)
    module = _single_block_module(
        [
            IRConst(stored, True),
            IRStore(slot, stored),
            IRLoad(loaded, slot),
        ],
        loaded,
    )

    assert "%1: bool = const true" in print_ir(_propagate(module))


def test_local_constant_propagation_tracks_multiple_slots_independently() -> None:
    int_type = IntType()
    left_slot = IRValue("left", int_type)
    right_slot = IRValue("right", int_type)
    one = IRValue("0", int_type)
    two = IRValue("1", int_type)
    left = IRValue("2", int_type)
    right = IRValue("3", int_type)
    module = _single_block_module(
        [
            IRConst(one, 1),
            IRConst(two, 2),
            IRStore(left_slot, one),
            IRStore(right_slot, two),
            IRLoad(left, left_slot),
            IRLoad(right, right_slot),
        ],
        right,
    )

    optimized = print_ir(_propagate(module))

    assert "%2: int = const 1" in optimized
    assert "%3: int = const 2" in optimized


def test_local_constant_propagation_combines_with_dce() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = _single_block_module(
        [
            IRConst(stored, 9),
            IRStore(slot, stored),
            IRLoad(loaded, slot),
        ],
        loaded,
    )

    assert print_ir(OptimizerPipeline().run(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %1: int = const 9\n"
        "    return %1\n"
        "}"
    )


def test_dead_store_eliminates_store_never_read() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    value = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(value, 7), IRStore(slot, value), IRReturn()],
                    )
                ],
            )
        ]
    )

    optimization = DeadStoreEliminator().run(module)

    assert optimization.changed is True
    assert print_ir(optimization.module) == (
        "func @main() -> void {\n"
        "entry:\n"
        "    %0: int = const 7\n"
        "    return\n"
        "}"
    )


def test_dead_store_eliminates_only_overwritten_store_before_load() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    first = IRValue("0", int_type)
    second = IRValue("1", int_type)
    loaded = IRValue("2", int_type)
    module = _single_block_module(
        [
            IRConst(first, 5),
            IRStore(slot, first),
            IRConst(second, 8),
            IRStore(slot, second),
            IRLoad(loaded, slot),
        ],
        loaded,
    )

    assert print_ir(_dse(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %0: int = const 5\n"
        "    %1: int = const 8\n"
        "    store %x, %1\n"
        "    %2: int = load %x\n"
        "    return %2\n"
        "}"
    )


def test_dead_store_eliminates_two_consecutive_stores_before_return() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    first = IRValue("0", int_type)
    second = IRValue("1", int_type)
    result = IRValue("2", int_type)
    module = _single_block_module(
        [
            IRConst(first, 5),
            IRStore(slot, first),
            IRConst(second, 8),
            IRStore(slot, second),
            IRConst(result, 13),
        ],
        result,
    )

    assert print_ir(_dse(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %0: int = const 5\n"
        "    %1: int = const 8\n"
        "    %2: int = const 13\n"
        "    return %2\n"
        "}"
    )


def test_dead_store_tracks_multiple_slots_independently() -> None:
    int_type = IntType()
    left_slot = IRValue("left", int_type)
    right_slot = IRValue("right", int_type)
    left_value = IRValue("0", int_type)
    right_value = IRValue("1", int_type)
    loaded = IRValue("2", int_type)
    module = _single_block_module(
        [
            IRConst(left_value, 1),
            IRConst(right_value, 2),
            IRStore(left_slot, left_value),
            IRStore(right_slot, right_value),
            IRLoad(loaded, left_slot),
        ],
        loaded,
    )

    assert print_ir(_dse(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %0: int = const 1\n"
        "    %1: int = const 2\n"
        "    store %left, %0\n"
        "    %2: int = load %left\n"
        "    return %2\n"
        "}"
    )


def test_dead_store_eliminates_store_after_local_constant_propagation() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = _single_block_module(
        [
            IRConst(stored, 5),
            IRStore(slot, stored),
            IRLoad(loaded, slot),
        ],
        loaded,
    )

    assert print_ir(OptimizerPipeline().run(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %1: int = const 5\n"
        "    return %1\n"
        "}"
    )


def test_dead_store_keeps_store_followed_by_load() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = _single_block_module(
        [IRConst(stored, 5), IRStore(slot, stored), IRLoad(loaded, slot)],
        loaded,
    )

    assert print_ir(_dse(module)) == print_ir(module)


def test_dead_store_keeps_store_read_before_later_store() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    first = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    second = IRValue("2", int_type)
    module = _single_block_module(
        [
            IRConst(first, 5),
            IRStore(slot, first),
            IRLoad(loaded, slot),
            IRConst(second, 8),
            IRStore(slot, second),
        ],
        loaded,
    )

    assert print_ir(_dse(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %0: int = const 5\n"
        "    store %x, %0\n"
        "    %1: int = load %x\n"
        "    %2: int = const 8\n"
        "    return %1\n"
        "}"
    )


def test_dead_store_keeps_store_in_other_block_before_load() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(stored, 5), IRStore(slot, stored), IRJump("exit")],
                    ),
                    IRBasicBlock("exit", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )

    assert print_ir(_dse(module)) == print_ir(module)


def test_dead_store_keeps_store_before_branch() -> None:
    int_type = IntType()
    bool_type = BoolType()
    slot = IRValue("x", int_type)
    value = IRValue("0", int_type)
    condition = IRValue("1", bool_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(value, 5),
                            IRStore(slot, value),
                            IRConst(condition, True),
                            IRBranch(condition, "then", "else"),
                        ],
                    ),
                    IRBasicBlock("then", [IRReturn()]),
                    IRBasicBlock("else", [IRReturn()]),
                ],
            )
        ]
    )

    assert print_ir(_dse(module)) == print_ir(module)


def test_dead_store_keeps_store_before_while_edge() -> None:
    int_type = IntType()
    bool_type = BoolType()
    slot = IRValue("x", int_type)
    value = IRValue("0", int_type)
    condition = IRValue("1", bool_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(value, 5), IRStore(slot, value), IRJump("cond")],
                    ),
                    IRBasicBlock(
                        "cond",
                        [IRConst(condition, False), IRBranch(condition, "body", "exit")],
                    ),
                    IRBasicBlock("body", [IRJump("cond")]),
                    IRBasicBlock("exit", [IRReturn()]),
                ],
            )
        ]
    )

    assert print_ir(_dse(module)) == print_ir(module)


def test_dead_store_keeps_store_before_jump() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    value = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(value, 5), IRStore(slot, value), IRJump("exit")],
                    ),
                    IRBasicBlock("exit", [IRReturn()]),
                ],
            )
        ]
    )

    assert print_ir(_dse(module)) == print_ir(module)


def test_dead_store_preserves_calls() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    call_result = IRValue("0", int_type)
    answer = IRValue("answer", int_type)
    module = IRModule(
        [
            IRFunction(
                "value",
                [],
                int_type,
                [IRBasicBlock("entry", [IRConst(answer, 1), IRReturn(answer)])],
            ),
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRCall("value", (), call_result),
                            IRStore(slot, call_result),
                            IRReturn(),
                        ],
                    )
                ],
            ),
        ]
    )

    optimized = print_ir(_dse(module))

    assert "call @value()" in optimized
    assert "store %x, %0" not in optimized


def test_local_constant_propagation_forgets_non_constant_store() -> None:
    int_type = IntType()
    parameter = IRParameter("value", int_type)
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(stored, 5),
                            IRStore(slot, stored),
                            IRStore(slot, parameter),
                            IRLoad(loaded, slot),
                            IRReturn(loaded),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_propagate(module)) == print_ir(module)


def test_local_constant_propagation_does_not_cross_basic_blocks() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(stored, 5), IRStore(slot, stored), IRJump("exit")],
                    ),
                    IRBasicBlock("exit", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )

    assert print_ir(_propagate(module)) == print_ir(module)


def test_local_constant_propagation_does_not_cross_if_else_merge() -> None:
    int_type = IntType()
    bool_type = BoolType()
    slot = IRValue("x", int_type)
    condition = IRValue("0", bool_type)
    one = IRValue("1", int_type)
    two = IRValue("2", int_type)
    loaded = IRValue("3", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(condition, True), IRBranch(condition, "then", "else")],
                    ),
                    IRBasicBlock(
                        "then",
                        [IRConst(one, 1), IRStore(slot, one), IRJump("merge")],
                    ),
                    IRBasicBlock(
                        "else",
                        [IRConst(two, 2), IRStore(slot, two), IRJump("merge")],
                    ),
                    IRBasicBlock("merge", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )

    assert "%3: int = load %x" in print_ir(_propagate(module))


def test_local_constant_propagation_does_not_cross_while_blocks() -> None:
    int_type = IntType()
    bool_type = BoolType()
    slot = IRValue("x", int_type)
    condition = IRValue("0", bool_type)
    stored = IRValue("1", int_type)
    loaded = IRValue("2", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock("entry", [IRJump("cond")]),
                    IRBasicBlock(
                        "cond",
                        [IRConst(condition, False), IRBranch(condition, "body", "exit")],
                    ),
                    IRBasicBlock(
                        "body",
                        [IRConst(stored, 5), IRStore(slot, stored), IRJump("cond")],
                    ),
                    IRBasicBlock("exit", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )

    assert "%2: int = load %x" in print_ir(_propagate(module))


def test_local_constant_propagation_does_not_remove_store() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = _single_block_module(
        [
            IRConst(stored, 5),
            IRStore(slot, stored),
            IRLoad(loaded, slot),
        ],
        loaded,
    )

    assert "store %x, %0" in print_ir(_propagate(module))


def test_local_constant_propagation_does_not_propagate_call_results() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    call_result = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "identity",
                [IRParameter("value", int_type)],
                int_type,
                [IRBasicBlock("entry", [IRReturn(IRParameter("value", int_type))])],
            ),
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRCall("identity", (), call_result),
                            IRStore(slot, call_result),
                            IRLoad(loaded, slot),
                            IRReturn(loaded),
                        ],
                    )
                ],
            ),
        ]
    )

    assert print_ir(_propagate(module)) == print_ir(module)


def test_local_constant_propagation_does_not_propagate_between_functions() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "write",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(stored, 5), IRStore(slot, stored), IRReturn()],
                    )
                ],
            ),
            IRFunction(
                "read",
                [],
                int_type,
                [IRBasicBlock("entry", [IRLoad(loaded, slot), IRReturn(loaded)])],
            ),
        ]
    )

    assert "%1: int = load %x" in print_ir(_propagate(module))


@pytest.mark.parametrize(
    ("operator", "constant_value", "constant_on_left"),
    [
        ("add", 0, False),
        ("add", 0, True),
        ("sub", 0, False),
        ("mul", 1, False),
        ("mul", 1, True),
        ("div", 1, False),
    ],
)
def test_algebraic_simplification_integer_identity_rules(
    operator: str,
    constant_value: int,
    constant_on_left: bool,
) -> None:
    int_type = IntType()
    parameter = IRParameter("x", int_type)
    constant = IRValue("0", int_type)
    result = IRValue("1", int_type)
    left = constant if constant_on_left else parameter
    right = parameter if constant_on_left else constant
    module = IRModule(
        [
            IRFunction(
                "main",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(constant, constant_value),
                            IRBinaryOp(result, operator, left, right),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_simplify(module)) == (
        "func @main(%x: int) -> int {\n"
        "entry:\n"
        f"    %0: int = const {constant_value}\n"
        "    return %x\n"
        "}"
    )


@pytest.mark.parametrize(
    ("operator", "constant_value", "constant_on_left"),
    [
        ("mul", 0, False),
        ("mul", 0, True),
        ("mod", 1, False),
        ("rem", 1, False),
    ],
)
def test_algebraic_simplification_integer_zero_result_rules(
    operator: str,
    constant_value: int,
    constant_on_left: bool,
) -> None:
    int_type = IntType()
    parameter = IRParameter("x", int_type)
    constant = IRValue("0", int_type)
    result = IRValue("1", int_type)
    left = constant if constant_on_left else parameter
    right = parameter if constant_on_left else constant
    module = IRModule(
        [
            IRFunction(
                "main",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(constant, constant_value),
                            IRBinaryOp(result, operator, left, right),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_simplify(module)) == (
        "func @main(%x: int) -> int {\n"
        "entry:\n"
        f"    %0: int = const {constant_value}\n"
        "    %1: int = const 0\n"
        "    return %1\n"
        "}"
    )


def test_algebraic_simplification_combines_with_dead_code_elimination() -> None:
    int_type = IntType()
    parameter = IRParameter("x", int_type)
    zero = IRValue("0", int_type)
    result = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(zero, 0),
                            IRBinaryOp(result, "add", parameter, zero),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(OptimizerPipeline().run(module)) == (
        "func @main(%x: int) -> int {\n"
        "entry:\n"
        "    return %x\n"
        "}"
    )


@pytest.mark.parametrize("operator", ["sub", "div", "mod", "rem"])
def test_algebraic_simplification_does_not_fold_same_operand_rules(
    operator: str,
) -> None:
    int_type = IntType()
    parameter = IRParameter("x", int_type)
    result = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRBinaryOp(result, operator, parameter, parameter),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_simplify(module)) == print_ir(module)


@pytest.mark.parametrize(
    ("type_", "constant_value", "operator"),
    [
        (FloatType(), 0.0, "add"),
        (DoubleType(), 1.0, "mul"),
    ],
)
def test_algebraic_simplification_does_not_simplify_float_or_double(
    type_,
    constant_value: float,
    operator: str,
) -> None:
    parameter = IRParameter("x", type_)
    constant = IRValue("0", type_)
    result = IRValue("1", type_)
    module = IRModule(
        [
            IRFunction(
                "main",
                [parameter],
                type_,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(constant, constant_value),
                            IRBinaryOp(result, operator, parameter, constant),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_simplify(module)) == print_ir(module)


def test_algebraic_simplification_does_not_simplify_non_identity_constant() -> None:
    int_type = IntType()
    parameter = IRParameter("x", int_type)
    two = IRValue("0", int_type)
    result = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(two, 2),
                            IRBinaryOp(result, "add", parameter, two),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_simplify(module)) == print_ir(module)


def test_algebraic_simplification_does_not_simplify_valid_int_division_to_double() -> None:
    int_type = IntType()
    double_type = DoubleType()
    parameter = IRParameter("x", int_type)
    one = IRValue("0", int_type)
    result = IRValue("1", double_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [parameter],
                double_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(one, 1),
                            IRBinaryOp(result, "div", parameter, one),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_simplify(module)) == print_ir(module)


def test_algebraic_simplification_preserves_effectful_and_control_instructions() -> None:
    int_type = IntType()
    bool_type = BoolType()
    slot = IRValue("slot", int_type)
    value = IRValue("0", int_type)
    condition = IRValue("1", bool_type)
    module = IRModule(
        [
            IRFunction(
                "effect",
                [IRParameter("value", int_type)],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn()])],
            ),
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(value, 7),
                            IRConst(condition, True),
                            IRStore(slot, value),
                            IRCall("effect", (value,)),
                            IRBranch(condition, "then", "else"),
                        ],
                    ),
                    IRBasicBlock("then", [IRJump("exit")]),
                    IRBasicBlock("else", [IRJump("exit")]),
                    IRBasicBlock("exit", [IRReturn()]),
                ],
            ),
        ]
    )

    assert print_ir(_simplify(module)) == print_ir(module)


def test_dead_code_eliminates_unused_constant_after_folding() -> None:
    int_type = IntType()
    two = IRValue("0", int_type)
    three = IRValue("1", int_type)
    four = IRValue("2", int_type)
    twelve = IRValue("3", int_type)
    result = IRValue("4", int_type)
    module = _single_block_module(
        [
            IRConst(two, 2),
            IRConst(three, 3),
            IRConst(four, 4),
            IRBinaryOp(twelve, "mul", three, four),
            IRBinaryOp(result, "add", two, twelve),
        ],
        result,
    )

    assert print_ir(OptimizerPipeline().run(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %4: int = const 14\n"
        "    return %4\n"
        "}"
    )


def test_dead_code_eliminates_unused_arithmetic_operation() -> None:
    int_type = IntType()
    left = IRParameter("a", int_type)
    right = IRParameter("b", int_type)
    unused = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [left, right],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRBinaryOp(unused, "add", left, right), IRReturn(left)],
                    )
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == (
        "func @main(%a: int, %b: int) -> int {\n"
        "entry:\n"
        "    return %a\n"
        "}"
    )


def test_dead_code_eliminates_unused_comparison() -> None:
    int_type = IntType()
    bool_type = BoolType()
    left = IRParameter("a", int_type)
    right = IRParameter("b", int_type)
    unused = IRValue("0", bool_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [left, right],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(unused, "lt", left, right), IRReturn(left)],
                    )
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == (
        "func @main(%a: int, %b: int) -> int {\n"
        "entry:\n"
        "    return %a\n"
        "}"
    )


def test_dead_code_eliminates_unused_load() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    value = IRValue("0", int_type)
    unused = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(value, 10),
                            IRStore(slot, value),
                            IRLoad(unused, slot),
                            IRReturn(),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == (
        "func @main() -> void {\n"
        "entry:\n"
        "    %0: int = const 10\n"
        "    store %x, %0\n"
        "    return\n"
        "}"
    )


def test_dead_code_keeps_returned_value() -> None:
    int_type = IntType()
    value = IRValue("0", int_type)
    module = _single_block_module([IRConst(value, 42)], value)

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_keeps_value_used_by_store() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    value = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(value, 7), IRStore(slot, value), IRReturn()],
                    )
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_keeps_value_used_as_call_argument_and_keeps_call() -> None:
    int_type = IntType()
    argument = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "consume",
                [IRParameter("value", int_type)],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn()])],
            ),
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(argument, 5), IRCall("consume", (argument,)), IRReturn()],
                    )
                ],
            ),
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_keeps_value_used_by_branch_condition() -> None:
    bool_type = BoolType()
    condition = IRValue("0", bool_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(condition, True), IRBranch(condition, "then", "else")],
                    ),
                    IRBasicBlock("then", [IRReturn()]),
                    IRBasicBlock("else", [IRReturn()]),
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_works_across_multiple_blocks() -> None:
    int_type = IntType()
    bool_type = BoolType()
    unused = IRValue("0", int_type)
    condition = IRValue("1", bool_type)
    then_value = IRValue("2", int_type)
    else_value = IRValue("3", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(unused, 99),
                            IRConst(condition, True),
                            IRBranch(condition, "then", "else"),
                        ],
                    ),
                    IRBasicBlock(
                        "then",
                        [IRConst(then_value, 1), IRReturn(then_value)],
                    ),
                    IRBasicBlock(
                        "else",
                        [IRConst(else_value, 2), IRReturn(else_value)],
                    ),
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %1: bool = const true\n"
        "    branch %1, then, else\n"
        "\n"
        "then:\n"
        "    %2: int = const 1\n"
        "    return %2\n"
        "\n"
        "else:\n"
        "    %3: int = const 2\n"
        "    return %3\n"
        "}"
    )


def test_dead_code_does_not_remove_call_with_unused_result() -> None:
    int_type = IntType()
    argument = IRValue("0", int_type)
    call_result = IRValue("1", int_type)
    return_value = IRValue("2", int_type)
    module = IRModule(
        [
            IRFunction(
                "identity",
                [IRParameter("value", int_type)],
                int_type,
                [IRBasicBlock("entry", [IRReturn(IRParameter("value", int_type))])],
            ),
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(argument, 5),
                            IRCall("identity", (argument,), call_result),
                            IRConst(return_value, 0),
                            IRReturn(return_value),
                        ],
                    )
                ],
            ),
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_does_not_remove_terminators() -> None:
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("exit")]),
                    IRBasicBlock("exit", [IRReturn()]),
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_does_not_remove_used_load() -> None:
    int_type = IntType()
    slot = IRValue("x", int_type)
    stored = IRValue("0", int_type)
    loaded = IRValue("1", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(stored, 4),
                            IRStore(slot, stored),
                            IRLoad(loaded, slot),
                            IRReturn(loaded),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)


def test_dead_code_keeps_chain_needed_to_calculate_return_when_not_folded() -> None:
    int_type = IntType()
    parameter = IRParameter("x", int_type)
    one = IRValue("0", int_type)
    sum_ = IRValue("1", int_type)
    doubled = IRValue("2", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(one, 1),
                            IRBinaryOp(sum_, "add", parameter, one),
                            IRBinaryOp(doubled, "mul", sum_, parameter),
                            IRReturn(doubled),
                        ],
                    )
                ],
            )
        ]
    )

    assert print_ir(_dce(module)) == print_ir(module)
