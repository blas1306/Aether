from __future__ import annotations

from math import inf

import pytest

from aether.ir import (
    ArrayType,
    BoolType,
    DoubleType,
    IRArrayGet,
    IRArrayNew,
    IRArraySet,
    IRArraySlice,
    IRBasicBlock,
    IRBinaryOp,
    IRCall,
    IRCast,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRListContains,
    IRListPush,
    IRMatrixGet,
    IRModule,
    IRPrint,
    IRReturn,
    IRValue,
    IRVectorGet,
    IntType,
    ListType,
    MatrixType,
    VectorType,
    VoidType,
)
from aether.ir.optimizer import ConstantFolder, DeadCodeEliminator
from aether.ssa import (
    SSAArrayGet,
    SSAArrayNew,
    SSAArraySet,
    SSAArraySlice,
    SSABasicBlock,
    SSABinaryOp,
    SSACall,
    SSACast,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAListContains,
    SSAListPush,
    SSAMatrixGet,
    SSAModule,
    SSAPrint,
    SSAReturn,
    SSAValue,
    SSAVectorGet,
)
from aether.ssa.optimizer import (
    SCCPPass,
    SSAConstantFolder,
    SSADeadCodeEliminator,
    SSAGlobalConstantPropagator,
)


EffectFlags = tuple[bool, bool, bool, bool, bool, bool]


def _flags(instruction: object) -> EffectFlags:
    return (
        instruction.has_side_effects,
        instruction.may_trap,
        instruction.reads_memory,
        instruction.writes_memory,
        instruction.allocates,
        instruction.must_preserve,
    )


def _paired_values(type_: object, name: str = "value") -> tuple[IRValue, SSAValue]:
    return IRValue(name, type_), SSAValue(name, type_)


def _effect_cases() -> list[tuple[object, object, EffectFlags]]:
    int_type = IntType()
    double_type = DoubleType()
    bool_type = BoolType()
    array_type = ArrayType(int_type)
    list_type = ListType(int_type)
    vector_type = VectorType(int_type, "row")
    matrix_type = MatrixType(int_type)

    ir_int, ssa_int = _paired_values(int_type, "int")
    ir_rhs, ssa_rhs = _paired_values(int_type, "rhs")
    ir_double, ssa_double = _paired_values(double_type, "double")
    ir_double_rhs, ssa_double_rhs = _paired_values(double_type, "double_rhs")
    ir_double_result, ssa_double_result = _paired_values(
        double_type,
        "double_result",
    )
    ir_bool, ssa_bool = _paired_values(bool_type, "bool")
    ir_array, ssa_array = _paired_values(array_type, "array")
    ir_list, ssa_list = _paired_values(list_type, "list")
    ir_vector, ssa_vector = _paired_values(vector_type, "vector")
    ir_matrix, ssa_matrix = _paired_values(matrix_type, "matrix")

    pure = (False, False, False, False, False, False)
    trap = (False, True, False, False, False, True)
    read = (False, False, True, False, False, False)
    read_trap = (False, True, True, False, False, True)
    write_trap = (False, True, True, True, False, True)
    allocation = (False, True, False, False, True, True)
    reading_allocation = (False, True, True, False, True, True)
    mutation_allocation = (False, True, True, True, True, True)

    return [
        (IRConst(ir_int, 1), SSAConst(ssa_int, 1), pure),
        (
            IRBinaryOp(ir_int, "add", ir_int, ir_rhs),
            SSABinaryOp(ssa_int, "add", ssa_int, ssa_rhs),
            trap,
        ),
        (
            IRBinaryOp(ir_double_result, "add", ir_double, ir_double_rhs),
            SSABinaryOp(ssa_double_result, "add", ssa_double, ssa_double_rhs),
            pure,
        ),
        (
            IRCompareOp(ir_bool, "eq", ir_int, ir_rhs),
            SSACompareOp(ssa_bool, "eq", ssa_int, ssa_rhs),
            pure,
        ),
        (IRCast(ir_int, ir_double), SSACast(ssa_int, ssa_double), trap),
        (
            IRArrayGet(ir_int, ir_array, ir_int),
            SSAArrayGet(ssa_int, ssa_array, ssa_int),
            read_trap,
        ),
        (
            IRArraySet(ir_array, ir_int, ir_rhs),
            SSAArraySet(ssa_array, ssa_int, ssa_rhs),
            write_trap,
        ),
        (
            IRArraySlice(ir_array, ir_array, ir_int, ir_rhs),
            SSAArraySlice(ssa_array, ssa_array, ssa_int, ssa_rhs),
            reading_allocation,
        ),
        (
            IRListContains(ir_bool, ir_list, ir_int),
            SSAListContains(ssa_bool, ssa_list, ssa_int),
            read,
        ),
        (
            IRListPush(ir_list, ir_int),
            SSAListPush(ssa_list, ssa_int),
            mutation_allocation,
        ),
        (
            IRPrint(ir_int, True),
            SSAPrint(ssa_int, True),
            (True, False, False, False, False, True),
        ),
        (
            IRCall("unknown", (ir_int,), ir_rhs),
            SSACall("unknown", (ssa_int,), ssa_rhs),
            (True, True, True, True, True, True),
        ),
        (
            IRVectorGet(ir_int, ir_vector, ir_rhs),
            SSAVectorGet(ssa_int, ssa_vector, ssa_rhs),
            read_trap,
        ),
        (
            IRMatrixGet(ir_int, ir_matrix, ir_int, ir_rhs, 2),
            SSAMatrixGet(ssa_int, ssa_matrix, ssa_int, ssa_rhs, 2),
            read_trap,
        ),
        (
            IRArrayNew(ir_array, (ir_int,)),
            SSAArrayNew(ssa_array, (ssa_int,)),
            allocation,
        ),
    ]


@pytest.mark.parametrize(("ir_instruction", "ssa_instruction", "expected"), _effect_cases())
def test_equivalent_ir_and_ssa_instructions_share_effects(
    ir_instruction: object,
    ssa_instruction: object,
    expected: EffectFlags,
) -> None:
    assert _flags(ir_instruction) == expected
    assert _flags(ssa_instruction) == expected


def _after_ir_dce(instruction: object) -> list[object]:
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [IRBasicBlock("entry", [instruction, IRReturn()])],
            )
        ]
    )
    return DeadCodeEliminator().run(module).module.functions[0].blocks[0].instructions


def _after_ssa_dce(instruction: object) -> list[object]:
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                VoidType(),
                [SSABasicBlock("entry", [instruction, SSAReturn()])],
            )
        ]
    )
    return SSADeadCodeEliminator().run(module).module.functions[0].blocks[0].instructions


@pytest.mark.parametrize(
    ("case_index", "preserved"),
    [
        (0, False),   # constant
        (1, True),    # checked integer arithmetic
        (2, False),   # pure double arithmetic
        (3, False),   # comparison
        (5, True),    # ArrayGet
        (6, True),    # ArraySet
        (7, True),    # ArraySlice
        (8, False),   # safe read
        (9, True),    # list mutation
        (10, True),   # print
        (11, True),   # conservative call
        (12, True),   # VectorGet regression
        (13, True),   # MatrixGet regression
        (14, True),   # allocation
    ],
)
def test_ir_and_ssa_dce_use_central_preservation_policy(
    case_index: int,
    preserved: bool,
) -> None:
    ir_instruction, ssa_instruction, _expected = _effect_cases()[case_index]

    assert (ir_instruction in _after_ir_dce(ir_instruction)) is preserved
    assert (ssa_instruction in _after_ssa_dce(ssa_instruction)) is preserved


def test_invalid_checked_cast_is_not_replaced_by_constant_optimizers() -> None:
    double_type = DoubleType()
    int_type = IntType()
    ir_source = IRValue("source", double_type)
    ir_result = IRValue("result", int_type)
    ir_cast = IRCast(ir_result, ir_source)
    ir_module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRConst(ir_source, inf), ir_cast, IRReturn()])],
            )
        ]
    )

    assert ir_cast in ConstantFolder().run(ir_module).module.functions[0].blocks[0].instructions

    ssa_source = SSAValue("source", double_type)
    ssa_result = SSAValue("result", int_type)
    ssa_cast = SSACast(ssa_result, ssa_source)
    ssa_module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                VoidType(),
                [SSABasicBlock("entry", [SSAConst(ssa_source, inf), ssa_cast, SSAReturn()])],
            )
        ]
    )

    for optimizer in (SSAConstantFolder(), SSAGlobalConstantPropagator(), SCCPPass()):
        optimized = optimizer.run(ssa_module).module
        assert ssa_cast in optimized.functions[0].blocks[0].instructions
