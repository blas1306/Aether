from __future__ import annotations

import re

import pytest

from aether.ir import BoolType, DoubleType, IntType, ListType, MatrixType, StringType, VectorType, VoidType
from aether.ssa import (
    SSABasicBlock,
    SSABinaryOp,
    SSABranch,
    SSACast,
    SSACall,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAJump,
    SSAListNew,
    SSAListClear,
    SSAListPop,
    SSAListPush,
    SSAListInsert,
    SSAListRemoveAt,
    SSAListSet,
    SSAMatrixNew,
    SSAModule,
    SSAParameter,
    SSAPhi,
    SSAReturn,
    SSAValue,
    SSAVectorNew,
    SSAVerificationError,
    SSAVerifier,
)


def _assert_verification_error(module: SSAModule, message: str) -> None:
    with pytest.raises(SSAVerificationError, match=re.escape(message)):
        SSAVerifier(module).verify()


def test_verifies_linear_function() -> None:
    int_type = IntType()
    left = SSAParameter("left", int_type)
    right = SSAParameter("right", int_type)
    result = SSAValue("0", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "add",
                [left, right],
                int_type,
                [SSABasicBlock("entry", [SSABinaryOp(result, "add", left, right), SSAReturn(result)])],
            )
        ]
    )

    assert SSAVerifier(module).verify() is module


def test_rejects_list_set_with_incompatible_value_type() -> None:
    int_type = IntType()
    double_type = DoubleType()
    element = SSAValue("0", int_type)
    list_value = SSAValue("1", ListType(int_type))
    index = SSAValue("2", int_type)
    value = SSAValue("3", double_type)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(element, 1),
                            SSAListNew(list_value, (element,)),
                            SSAConst(index, 0),
                            SSAConst(value, 2.0),
                            SSAListSet(list_value, index, value),
                            SSAReturn(element),
                        ],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(module, "List set value type mismatch: expected int, got double")


def test_rejects_list_clear_with_non_list_operand() -> None:
    int_type = IntType()
    value = SSAValue("0", int_type)
    module = SSAModule(
        [SSAFunction("main", [], int_type, [SSABasicBlock("entry", [SSAConst(value, 1), SSAListClear(value), SSAReturn(value)])])]
    )

    _assert_verification_error(module, "List clear expects list value, got int")


def test_rejects_list_push_with_incompatible_value_type() -> None:
    int_type = IntType()
    double_type = DoubleType()
    element = SSAValue("0", int_type)
    list_value = SSAValue("1", ListType(int_type))
    value = SSAValue("2", double_type)
    module = SSAModule([SSAFunction("main", [], int_type, [SSABasicBlock("entry", [SSAConst(element, 1), SSAListNew(list_value, (element,)), SSAConst(value, 2.0), SSAListPush(list_value, value), SSAReturn(element)])])])

    _assert_verification_error(module, "List push value type mismatch: expected int, got double")


def test_rejects_list_insert_with_non_int_index() -> None:
    int_type = IntType()
    element = SSAValue("0", int_type)
    list_value = SSAValue("1", ListType(int_type))
    index = SSAValue("2", DoubleType())
    module = SSAModule([SSAFunction("main", [], int_type, [SSABasicBlock("entry", [SSAConst(element, 1), SSAListNew(list_value, (element,)), SSAConst(index, 0.0), SSAListInsert(list_value, index, element), SSAReturn(element)])])])

    _assert_verification_error(module, "List insert index must be int, got double")


def test_rejects_list_pop_with_incompatible_result_type() -> None:
    int_type = IntType()
    element = SSAValue("0", int_type)
    list_value = SSAValue("1", ListType(int_type))
    result = SSAValue("2", DoubleType())
    module = SSAModule([SSAFunction("main", [], int_type, [SSABasicBlock("entry", [SSAConst(element, 1), SSAListNew(list_value, (element,)), SSAListPop(result, list_value), SSAReturn(element)])])])

    _assert_verification_error(module, "List pop result type mismatch: expected int, got double")


def test_rejects_list_remove_at_with_non_int_index() -> None:
    int_type = IntType()
    element = SSAValue("0", int_type)
    list_value = SSAValue("1", ListType(int_type))
    index = SSAValue("2", DoubleType())
    result = SSAValue("3", int_type)
    module = SSAModule([SSAFunction("main", [], int_type, [SSABasicBlock("entry", [SSAConst(element, 1), SSAListNew(list_value, (element,)), SSAConst(index, 0.0), SSAListRemoveAt(result, list_value, index), SSAReturn(result)])])])

    _assert_verification_error(module, "List remove_at index must be int, got double")


def test_verifies_if_else_with_phi() -> None:
    int_type = IntType()
    bool_type = BoolType()
    parameter = SSAParameter("x", int_type)
    zero = SSAValue("0", int_type)
    condition = SSAValue("1", bool_type)
    then_value = SSAValue("2", int_type)
    else_value = SSAValue("3", int_type)
    merged = SSAValue("4", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "choose",
                [parameter],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(zero, 0),
                            SSACompareOp(condition, "gt", parameter, zero),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAConst(then_value, 1), SSAJump("merge0")]),
                    SSABasicBlock("else0", [SSAConst(else_value, 2), SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(merged, (("then0", then_value), ("else0", else_value))),
                            SSAReturn(merged),
                        ],
                    ),
                ],
            )
        ]
    )

    assert SSAVerifier(module).verify() is module


def test_verifies_while_with_phi() -> None:
    int_type = IntType()
    bool_type = BoolType()
    initial_i = SSAValue("0", int_type)
    loop_i = SSAValue("1", int_type)
    limit = SSAValue("2", int_type)
    condition = SSAValue("3", bool_type)
    one = SSAValue("4", int_type)
    next_i = SSAValue("5", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "count",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(initial_i, 0),
                            SSAConst(limit, 3),
                            SSAJump("loop0"),
                        ],
                    ),
                    SSABasicBlock(
                        "loop0",
                        [
                            SSAPhi(loop_i, (("entry", initial_i), ("body0", next_i))),
                            SSACompareOp(condition, "lt", loop_i, limit),
                            SSABranch(condition, "body0", "exit0"),
                        ],
                    ),
                    SSABasicBlock(
                        "body0",
                        [
                            SSAConst(one, 1),
                            SSABinaryOp(next_i, "add", loop_i, one),
                            SSAJump("loop0"),
                        ],
                    ),
                    SSABasicBlock("exit0", [SSAReturn(loop_i)]),
                ],
            )
        ]
    )

    assert SSAVerifier(module).verify() is module


def test_verifies_call_between_functions() -> None:
    int_type = IntType()
    value = SSAParameter("value", int_type)
    one = SSAValue("0", int_type)
    incremented = SSAValue("1", int_type)
    argument = SSAValue("2", int_type)
    call_result = SSAValue("3", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "increment",
                [value],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(one, 1),
                            SSABinaryOp(incremented, "add", value, one),
                            SSAReturn(incremented),
                        ],
                    )
                ],
            ),
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(argument, 41),
                            SSACall("increment", (argument,), call_result),
                            SSAReturn(call_result),
                        ],
                    )
                ],
            ),
        ]
    )

    assert SSAVerifier(module).verify() is module


def test_verifies_column_vector_new() -> None:
    int_type = IntType()
    first = SSAValue("0", int_type)
    second = SSAValue("1", int_type)
    vector = SSAValue("2", VectorType(int_type, "column"))
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(first, 1),
                            SSAConst(second, 2),
                            SSAVectorNew(vector, (first, second), "column"),
                            SSAReturn(first),
                        ],
                    )
                ],
            )
        ]
    )

    assert SSAVerifier(module).verify() is module


def test_verifies_matrix_new() -> None:
    int_type = IntType()
    first = SSAValue("0", int_type)
    second = SSAValue("1", int_type)
    third = SSAValue("2", int_type)
    fourth = SSAValue("3", int_type)
    matrix = SSAValue("4", MatrixType(int_type))
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(first, 1),
                            SSAConst(second, 2),
                            SSAConst(third, 3),
                            SSAConst(fourth, 4),
                            SSAMatrixNew(matrix, (first, second, third, fourth), 2, 2),
                            SSAReturn(first),
                        ],
                    )
                ],
            )
        ]
    )

    assert SSAVerifier(module).verify() is module


def test_rejects_vector_new_orientation_mismatch() -> None:
    int_type = IntType()
    first = SSAValue("0", int_type)
    vector = SSAValue("1", VectorType(int_type, "column"))
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(first, 1),
                            SSAVectorNew(vector, (first,), "row"),
                            SSAReturn(first),
                        ],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(module, "Vector new orientation mismatch")


def test_verifies_double_to_int_cast() -> None:
    parameter = SSAParameter("value", DoubleType())
    result = SSAValue("0", IntType())
    module = SSAModule(
        [
            SSAFunction(
                "narrow",
                [parameter],
                IntType(),
                [SSABasicBlock("entry", [SSACast(result, parameter), SSAReturn(result)])],
            )
        ]
    )

    assert SSAVerifier(module).verify() is module


def test_verifies_identity_cast_and_integer_power() -> None:
    int_type = IntType()
    base = SSAParameter("base", int_type)
    exponent = SSAParameter("exponent", int_type)
    identity = SSAValue("identity", int_type)
    result = SSAValue("result", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "power",
                [base, exponent],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [SSACast(identity, base), SSABinaryOp(result, "pow", identity, exponent), SSAReturn(result)],
                    )
                ],
            )
        ]
    )

    assert SSAVerifier(module).verify() is module


def test_unsupported_cast_error() -> None:
    parameter = SSAParameter("value", BoolType())
    result = SSAValue("0", IntType())
    module = SSAModule(
        [
            SSAFunction(
                "bad",
                [parameter],
                IntType(),
                [SSABasicBlock("entry", [SSACast(result, parameter), SSAReturn(result)])],
            )
        ]
    )

    _assert_verification_error(module, "Cast requires int/double operands, got bool to int")


def test_verifies_void_function() -> None:
    module = SSAModule(
        [
            SSAFunction(
                "nothing",
                [],
                VoidType(),
                [SSABasicBlock("entry", [SSAReturn()])],
            )
        ]
    )

    assert SSAVerifier(module).verify() is module


def test_duplicate_function_error() -> None:
    module = SSAModule(
        [
            SSAFunction("main", [], VoidType(), [SSABasicBlock("entry", [SSAReturn()])]),
            SSAFunction("main", [], VoidType(), [SSABasicBlock("entry", [SSAReturn()])]),
        ]
    )

    _assert_verification_error(module, "Duplicate function 'main'")


def test_missing_entry_error() -> None:
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                VoidType(),
                [SSABasicBlock("body", [SSAReturn()])],
            )
        ]
    )

    _assert_verification_error(module, "Function 'main' has no entry block")


def test_duplicate_block_error() -> None:
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                VoidType(),
                [
                    SSABasicBlock("entry", [SSAReturn()]),
                    SSABasicBlock("entry", [SSAReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Duplicate block 'entry' in function 'main'")


def test_duplicate_parameter_error() -> None:
    int_type = IntType()
    parameter = SSAParameter("value", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "identity",
                [parameter, SSAParameter("value", int_type)],
                int_type,
                [SSABasicBlock("entry", [SSAReturn(parameter)])],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Duplicate parameter 'value' in function 'identity'",
    )


def test_unknown_target_error() -> None:
    condition = SSAValue("0", BoolType())
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                VoidType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(condition, True),
                            SSABranch(condition, "then0", "missing"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Unknown branch target 'missing' in function 'main'")


def test_instruction_after_terminator_error() -> None:
    value = SSAValue("0", IntType())
    module = SSAModule(
        [
            SSAFunction(
                "broken",
                [],
                VoidType(),
                [SSABasicBlock("entry", [SSAReturn(), SSAConst(value, 1)])],
            )
        ]
    )

    _assert_verification_error(module, "Instruction after terminator in block 'entry'")


def test_duplicate_value_error() -> None:
    value = SSAValue("0", IntType())
    module = SSAModule(
        [
            SSAFunction(
                "broken",
                [],
                IntType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(value, 1),
                            SSAConst(value, 2),
                            SSAReturn(value),
                        ],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(module, "Duplicate value '%0' in function 'broken'")


def test_undefined_value_error() -> None:
    missing = SSAValue("missing", IntType())
    module = SSAModule(
        [
            SSAFunction(
                "broken",
                [],
                IntType(),
                [SSABasicBlock("entry", [SSAReturn(missing)])],
            )
        ]
    )

    _assert_verification_error(module, "Undefined value '%missing'")


def test_return_type_mismatch_error() -> None:
    value = SSAValue("0", IntType())
    module = SSAModule(
        [
            SSAFunction(
                "broken",
                [],
                BoolType(),
                [SSABasicBlock("entry", [SSAConst(value, 1), SSAReturn(value)])],
            )
        ]
    )

    _assert_verification_error(module, "Return type mismatch: expected bool, got int")


def test_branch_condition_must_be_bool_error() -> None:
    condition = SSAValue("0", IntType())
    module = SSAModule(
        [
            SSAFunction(
                "broken",
                [],
                VoidType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(condition, 1),
                            SSABranch(condition, "then0", "else0"),
                        ],
                    ),
                    SSABasicBlock("then0", [SSAReturn()]),
                    SSABasicBlock("else0", [SSAReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Branch condition must be bool")


def test_phi_incoming_block_must_exist_error() -> None:
    int_type = IntType()
    value = SSAValue("0", int_type)
    merged = SSAValue("1", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "broken",
                [],
                int_type,
                [
                    SSABasicBlock("entry", [SSAConst(value, 1), SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [SSAPhi(merged, (("missing", value),)), SSAReturn(merged)],
                    ),
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Phi incoming block 'missing' does not exist in function block 'merge0'",
    )


def test_phi_incoming_block_must_be_predecessor_error() -> None:
    int_type = IntType()
    value = SSAValue("0", int_type)
    merged = SSAValue("1", int_type)
    other_value = SSAValue("2", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "broken",
                [],
                int_type,
                [
                    SSABasicBlock("entry", [SSAConst(value, 1), SSAJump("merge0")]),
                    SSABasicBlock("other0", [SSAConst(other_value, 2), SSAReturn(other_value)]),
                    SSABasicBlock(
                        "merge0",
                        [SSAPhi(merged, (("other0", other_value),)), SSAReturn(merged)],
                    ),
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Phi incoming block 'other0' is not a predecessor of block 'merge0'",
    )


def test_phi_type_mismatch_error() -> None:
    int_value = SSAValue("0", IntType())
    string_value = SSAValue("1", StringType())
    merged = SSAValue("2", IntType())
    module = SSAModule(
        [
            SSAFunction(
                "broken",
                [],
                IntType(),
                [
                    SSABasicBlock("entry", [SSAConst(int_value, 1), SSAJump("left0")]),
                    SSABasicBlock("left0", [SSAJump("merge0")]),
                    SSABasicBlock("right0", [SSAConst(string_value, "x"), SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(
                                merged,
                                (("left0", int_value), ("right0", string_value)),
                            ),
                            SSAReturn(merged),
                        ],
                    ),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Phi '%2' type mismatch: expected int, got string")


def test_phi_duplicate_incoming_block_error() -> None:
    int_type = IntType()
    value = SSAValue("0", int_type)
    merged = SSAValue("1", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "broken",
                [],
                int_type,
                [
                    SSABasicBlock("entry", [SSAConst(value, 1), SSAJump("merge0")]),
                    SSABasicBlock(
                        "merge0",
                        [
                            SSAPhi(merged, (("entry", value), ("entry", value))),
                            SSAReturn(merged),
                        ],
                    ),
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Duplicate incoming block 'entry' for phi '%1'",
    )


def test_phi_requires_incoming_values_error() -> None:
    merged = SSAValue("0", IntType())
    module = SSAModule(
        [
            SSAFunction(
                "broken",
                [],
                IntType(),
                [SSABasicBlock("entry", [SSAPhi(merged, ()), SSAReturn(merged)])],
            )
        ]
    )

    _assert_verification_error(module, "Phi '%0' has no incoming values")


def test_phi_after_non_phi_error() -> None:
    int_type = IntType()
    value = SSAValue("0", int_type)
    merged = SSAValue("1", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "broken",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(value, 1),
                            SSAPhi(merged, (("entry", value),)),
                            SSAReturn(merged),
                        ],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Phi instruction after non-phi instruction in block 'entry'",
    )


def test_call_to_missing_function_error() -> None:
    result = SSAValue("0", IntType())
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                IntType(),
                [SSABasicBlock("entry", [SSACall("missing", (), result), SSAReturn(result)])],
            )
        ]
    )

    _assert_verification_error(module, "Call to undefined function 'missing'")


def test_call_wrong_arity_error() -> None:
    int_type = IntType()
    parameter = SSAParameter("value", int_type)
    result = SSAValue("0", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "identity",
                [parameter],
                int_type,
                [SSABasicBlock("entry", [SSAReturn(parameter)])],
            ),
            SSAFunction(
                "main",
                [],
                int_type,
                [SSABasicBlock("entry", [SSACall("identity", (), result), SSAReturn(result)])],
            ),
        ]
    )

    _assert_verification_error(module, "Function 'identity' expects 1 arguments, got 0")


def test_call_result_type_mismatch_error() -> None:
    int_type = IntType()
    parameter = SSAParameter("value", int_type)
    argument = SSAValue("0", int_type)
    result = SSAValue("1", BoolType())
    module = SSAModule(
        [
            SSAFunction(
                "identity",
                [parameter],
                int_type,
                [SSABasicBlock("entry", [SSAReturn(parameter)])],
            ),
            SSAFunction(
                "main",
                [],
                BoolType(),
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(argument, 1),
                            SSACall("identity", (argument,), result),
                            SSAReturn(result),
                        ],
                    )
                ],
            ),
        ]
    )

    _assert_verification_error(module, "Call result type mismatch: expected int, got bool")


def test_call_argument_type_mismatch_error() -> None:
    int_type = IntType()
    parameter = SSAParameter("value", int_type)
    argument = SSAValue("0", BoolType())
    result = SSAValue("1", int_type)
    module = SSAModule(
        [
            SSAFunction(
                "identity",
                [parameter],
                int_type,
                [SSABasicBlock("entry", [SSAReturn(parameter)])],
            ),
            SSAFunction(
                "main",
                [],
                int_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(argument, True),
                            SSACall("identity", (argument,), result),
                            SSAReturn(result),
                        ],
                    )
                ],
            ),
        ]
    )

    _assert_verification_error(
        module,
        "Argument 1 to function 'identity' type mismatch: expected int, got bool",
    )
