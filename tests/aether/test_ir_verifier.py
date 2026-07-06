from __future__ import annotations

import re

import pytest

from aether.ir import (
    BoolType,
    DoubleType,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRJump,
    IRLoad,
    IRLowerer,
    IRModule,
    IRParameter,
    IRReturn,
    IRStore,
    IRValue,
    IRVerificationError,
    IRVerifier,
    IntType,
    StringType,
    VoidType,
)
from aether.pipeline import parse_source
from aether.typechecker import TypeChecker


def _lower(source: str) -> IRModule:
    program = parse_source(source)
    TypeChecker().check(program)
    return IRLowerer().lower(program)


def _assert_verification_error(module: IRModule, message: str) -> None:
    with pytest.raises(IRVerificationError, match=re.escape(message)):
        IRVerifier(module).verify()


def test_verifies_lowered_add_function() -> None:
    module = _lower(
        """
int add(int a, int b) {
    return a + b;
}
"""
    )

    assert IRVerifier(module).verify() is module


def test_verifies_function_with_local_store_and_load() -> None:
    module = _lower(
        """
int identity(int value) {
    int result = value;
    return result;
}
"""
    )

    assert IRVerifier(module).verify() is module


def test_verifies_function_calling_another_function() -> None:
    module = _lower(
        """
int increment(int value) {
    return value + 1;
}

int twiceIncrement(int value) {
    return increment(increment(value));
}
"""
    )

    assert IRVerifier(module).verify() is module


@pytest.mark.parametrize(
    "source",
    [
        "boolean compare(int a, int b) { return a < b; }",
        "boolean compare(int a, int b) { return a <= b; }",
        "boolean compare(int a, int b) { return a > b; }",
        "boolean compare(int a, int b) { return a >= b; }",
        "boolean compare(int a, int b) { return a == b; }",
        "boolean compare(int a, int b) { return a != b; }",
        "boolean compare(boolean a, boolean b) { return a == b; }",
        "boolean compare(boolean a, boolean b) { return a != b; }",
        "boolean compare(string a, string b) { return a == b; }",
        "boolean compare(string a, string b) { return a != b; }",
    ],
)
def test_verifies_lowered_comparison_function(source: str) -> None:
    module = _lower(source)

    assert IRVerifier(module).verify() is module


def test_verifies_lowered_if_else_function() -> None:
    module = _lower(
        """
int f(int x) {
    int y = 0;
    if x > 0 {
        y = 1;
    } else {
        y = 2;
    }
    return y;
}
"""
    )

    assert IRVerifier(module).verify() is module


def test_verifies_lowered_while_function() -> None:
    module = _lower(
        """
int sumTo(int n) {
    int i = 0;
    int sum = 0;

    while i < n {
        sum = sum + i;
        i = i + 1;
    }

    return sum;
}
"""
    )

    assert IRVerifier(module).verify() is module


def test_verifies_void_function_with_bare_return() -> None:
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

    assert IRVerifier(module).verify() is module


def test_verifies_module_with_multiple_functions() -> None:
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
                [IRBasicBlock("entry", [IRBinaryOp(result, "add", left, right), IRReturn(result)])],
            ),
            IRFunction(
                "main",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn()])],
            ),
        ]
    )

    assert IRVerifier(module).verify() is module


def test_duplicate_function_error() -> None:
    module = IRModule(
        [
            IRFunction("add", [], VoidType(), [IRBasicBlock("entry", [IRReturn()])]),
            IRFunction("add", [], VoidType(), [IRBasicBlock("entry", [IRReturn()])]),
        ]
    )

    _assert_verification_error(module, "Duplicate function 'add'")


def test_missing_entry_block_error() -> None:
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [IRBasicBlock("body", [IRReturn()])],
            )
        ]
    )

    _assert_verification_error(module, "Function 'main' has no entry block")


def test_duplicate_parameter_error() -> None:
    module = IRModule(
        [
            IRFunction(
                "identity",
                [IRParameter("value", IntType()), IRParameter("value", IntType())],
                IntType(),
                [IRBasicBlock("entry", [IRReturn(IRValue("value", IntType()))])],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Duplicate parameter 'value' in function 'identity'",
    )


def test_duplicate_block_error() -> None:
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRReturn()]),
                    IRBasicBlock("entry", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Duplicate block 'entry' in function 'main'")


def test_instruction_after_return_error() -> None:
    value = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn(), IRConst(value, 1)])],
            )
        ]
    )

    _assert_verification_error(module, "Instruction after terminator in block 'entry'")


def test_undefined_value_error() -> None:
    missing = IRValue("3", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRReturn(missing)])],
            )
        ]
    )

    _assert_verification_error(module, "Undefined value '%3'")


def test_undefined_slot_error() -> None:
    slot = IRValue("x", IntType())
    loaded = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "read",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRLoad(loaded, slot), IRReturn(loaded)])],
            )
        ]
    )

    _assert_verification_error(module, "Undefined slot '%x'")


def test_load_before_store_error() -> None:
    slot = IRValue("x", IntType())
    loaded = IRValue("0", IntType())
    value = IRValue("1", IntType())
    module = IRModule(
        [
            IRFunction(
                "read",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(value, 1),
                            IRLoad(loaded, slot),
                            IRStore(slot, value),
                            IRReturn(loaded),
                        ],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(module, "Slot '%x' loaded before store")


def test_call_to_missing_function_error() -> None:
    result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRCall("missing", (), result), IRReturn(result)])],
            )
        ]
    )

    _assert_verification_error(module, "Call to undefined function 'missing'")


def test_call_wrong_arity_error() -> None:
    parameter = IRParameter("value", IntType())
    call_result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "add",
                [IRParameter("left", IntType()), IRParameter("right", IntType())],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRBinaryOp(
                                IRValue("0", IntType()),
                                "add",
                                IRValue("left", IntType()),
                                IRValue("right", IntType()),
                            ),
                            IRReturn(IRValue("0", IntType())),
                        ],
                    )
                ],
            ),
            IRFunction(
                "main",
                [parameter],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCall("add", (parameter,), call_result), IRReturn(call_result)],
                    )
                ],
            ),
        ]
    )

    _assert_verification_error(module, "Function 'add' expects 2 arguments, got 1")


def test_call_wrong_argument_type_error() -> None:
    argument = IRParameter("value", StringType())
    call_result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "id",
                [IRParameter("value", IntType())],
                IntType(),
                [IRBasicBlock("entry", [IRReturn(IRValue("value", IntType()))])],
            ),
            IRFunction(
                "main",
                [argument],
                IntType(),
                [IRBasicBlock("entry", [IRCall("id", (argument,), call_result), IRReturn(call_result)])],
            ),
        ]
    )

    _assert_verification_error(
        module,
        "Argument 1 to function 'id' type mismatch: expected int, got string",
    )


def test_return_type_mismatch_error() -> None:
    value = IRValue("0", StringType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRConst(value, "oops"), IRReturn(value)])],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Return type mismatch: expected int, got string",
    )


def test_binary_op_incompatible_operand_error() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", StringType())
    result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [left, right],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRBinaryOp(result, "add", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Binary op 'add' requires compatible operands, got int and string",
    )


def test_compare_op_int_less_than_string_error() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", StringType())
    result = IRValue("0", BoolType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [left, right],
                BoolType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(result, "lt", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Compare op 'lt' requires int operands, got int and string",
    )


def test_compare_op_bool_less_than_bool_error() -> None:
    left = IRParameter("left", BoolType())
    right = IRParameter("right", BoolType())
    result = IRValue("0", BoolType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [left, right],
                BoolType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(result, "lt", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Compare op 'lt' requires int operands, got bool and bool",
    )


def test_compare_op_string_less_than_string_error() -> None:
    left = IRParameter("left", StringType())
    right = IRParameter("right", StringType())
    result = IRValue("0", BoolType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [left, right],
                BoolType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(result, "lt", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Compare op 'lt' requires int operands, got string and string",
    )


def test_compare_op_result_type_must_be_bool_error() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", IntType())
    result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [left, right],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(result, "lt", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Compare op 'lt' result type mismatch: expected bool, got int",
    )


def test_compare_op_unknown_operator_error() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", IntType())
    result = IRValue("0", BoolType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [left, right],
                BoolType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(result, "unknown", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(module, "Unsupported compare operator 'unknown'")


def test_branch_condition_must_be_bool_error() -> None:
    condition = IRParameter("condition", IntType())
    module = IRModule(
        [
            IRFunction(
                "choose",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then", "else")]),
                    IRBasicBlock("then", [IRReturn()]),
                    IRBasicBlock("else", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Branch condition must be bool")


def test_loop_branch_condition_must_be_bool_error() -> None:
    condition = IRParameter("condition", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "exit0")]),
                    IRBasicBlock("body0", [IRJump("cond0")]),
                    IRBasicBlock("exit0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Branch condition must be bool")


def test_jump_target_must_exist_error() -> None:
    module = IRModule(
        [
            IRFunction(
                "loop",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRJump("missing")])],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Unknown jump target 'missing' in function 'loop'",
    )


def test_branch_target_must_exist_error() -> None:
    condition = IRParameter("condition", BoolType())
    module = IRModule(
        [
            IRFunction(
                "choose",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then", "missing")]),
                    IRBasicBlock("then", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Unknown branch target 'missing' in function 'choose'",
    )


def test_loop_branch_target_must_exist_error() -> None:
    condition = IRParameter("condition", BoolType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "missing")]),
                    IRBasicBlock("body0", [IRJump("cond0")]),
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Unknown branch target 'missing' in function 'broken'",
    )


def test_load_after_merge_requires_store_on_all_incoming_paths() -> None:
    condition = IRParameter("condition", BoolType())
    slot = IRValue("y", IntType())
    one = IRValue("0", IntType())
    loaded = IRValue("1", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [condition],
                IntType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then", "merge")]),
                    IRBasicBlock(
                        "then",
                        [IRConst(one, 1), IRStore(slot, one), IRJump("merge")],
                    ),
                    IRBasicBlock("merge", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Slot '%y' loaded before store")


def test_load_after_loop_requires_store_before_loop() -> None:
    condition = IRParameter("condition", BoolType())
    slot = IRValue("x", IntType())
    one = IRValue("0", IntType())
    loaded = IRValue("1", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [condition],
                IntType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "exit0")]),
                    IRBasicBlock(
                        "body0",
                        [IRConst(one, 1), IRStore(slot, one), IRJump("cond0")],
                    ),
                    IRBasicBlock("exit0", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Slot '%x' loaded before store")


def test_loop_body_must_have_terminator_error() -> None:
    condition = IRParameter("condition", BoolType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "exit0")]),
                    IRBasicBlock("body0", []),
                    IRBasicBlock("exit0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Block 'body0' in function 'broken' has no terminator",
    )


def test_non_void_function_must_return_on_all_paths_error() -> None:
    condition = IRParameter("condition", BoolType())
    value = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "choose",
                [condition],
                IntType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then", "else")]),
                    IRBasicBlock("then", [IRConst(value, 1), IRReturn(value)]),
                    IRBasicBlock("else", [IRJump("entry")]),
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Function 'choose' may exit without returning a value",
    )


def test_division_result_type_must_match_error() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", IntType())
    result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "divide",
                [left, right],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRBinaryOp(result, "div", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Binary op 'div' result type mismatch: expected double, got int",
    )


def test_call_result_type_must_match_error() -> None:
    result = IRValue("0", DoubleType())
    module = IRModule(
        [
            IRFunction(
                "answer",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRConst(IRValue("0", IntType()), 1), IRReturn(IRValue("0", IntType()))])],
            ),
            IRFunction(
                "main",
                [],
                DoubleType(),
                [IRBasicBlock("entry", [IRCall("answer", (), result), IRReturn(result)])],
            ),
        ]
    )

    _assert_verification_error(
        module,
        "Call result type mismatch: expected int, got double",
    )
