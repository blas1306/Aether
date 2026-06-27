from __future__ import annotations

import pytest

from aether.ir import (
    BoolType,
    DoubleType,
    IRBasicBlock,
    IRBinaryOp,
    IRCall,
    IRCompareOp,
    IRConst,
    IRExecutionError,
    IRFunction,
    IRInterpreter,
    IRLoad,
    IRLowerer,
    IRModule,
    IRParameter,
    IRReturn,
    IRStore,
    IRValue,
    IntType,
    VoidType,
)
from aether.pipeline import parse_source
from aether.runner import run_aether
from aether.typechecker import TypeChecker


def _lower(source: str) -> IRModule:
    program = parse_source(source)
    TypeChecker().check(program)
    return IRLowerer().lower(program)


def _reference_result(source: str, call: str) -> object:
    result = run_aether(f"{source}\nobserved = {call};")
    return result.env["observed"].value


def test_execute_manually_built_add_function() -> None:
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
                        [
                            IRBinaryOp(result, "add", left, right),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    assert IRInterpreter(module).call("add", [2, 3]) == 5


def test_execute_manually_built_store_and_load() -> None:
    int_type = IntType()
    parameter = IRParameter("value", int_type)
    slot = IRValue("local", int_type)
    loaded = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "identity",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRStore(slot, parameter),
                            IRLoad(loaded, slot),
                            IRReturn(loaded),
                        ],
                    )
                ],
            )
        ]
    )

    assert IRInterpreter(module).call("identity", [17]) == 17


def test_execute_manually_built_call_between_functions() -> None:
    int_type = IntType()
    left = IRParameter("left", int_type)
    right = IRParameter("right", int_type)
    sum_value = IRValue("0", int_type)
    caller_left = IRParameter("left", int_type)
    caller_right = IRParameter("right", int_type)
    call_result = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "add",
                [left, right],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRBinaryOp(sum_value, "add", left, right),
                            IRReturn(sum_value),
                        ],
                    )
                ],
            ),
            IRFunction(
                "callAdd",
                [caller_left, caller_right],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRCall(
                                "add",
                                (caller_left, caller_right),
                                call_result,
                            ),
                            IRReturn(call_result),
                        ],
                    )
                ],
            ),
        ]
    )

    assert IRInterpreter(module).call("callAdd", [8, 5]) == 13


def test_execute_ir_generated_by_lowering() -> None:
    module = _lower(
        """
double calculate(int a, int b) {
    int total = (a + b) * 2 - b;
    return total / b;
}
"""
    )

    assert IRInterpreter(module).call("calculate", [4, 2]) == 5.0


@pytest.mark.parametrize(
    ("source", "function_name", "arguments", "expected"),
    [
        ("boolean enabled() { return true; }", "enabled", [], True),
        ('string name() { return "Aether"; }', "name", [], "Aether"),
        ("int remainder(int value, int divisor) { return value % divisor; }", "remainder", [-7, 3], -1),
    ],
)
def test_execute_lowered_literals_and_remainder(
    source: str,
    function_name: str,
    arguments: list[object],
    expected: object,
) -> None:
    assert IRInterpreter(_lower(source)).call(function_name, arguments) == expected


@pytest.mark.parametrize(
    ("source", "function_name", "arguments", "expected"),
    [
        ("boolean compare(int a, int b) { return a < b; }", "compare", [1, 2], True),
        ("boolean compare(int a, int b) { return a <= b; }", "compare", [2, 2], True),
        ("boolean compare(int a, int b) { return a > b; }", "compare", [3, 2], True),
        ("boolean compare(int a, int b) { return a >= b; }", "compare", [2, 2], True),
        ("boolean compare(int a, int b) { return a == b; }", "compare", [2, 2], True),
        ("boolean compare(int a, int b) { return a != b; }", "compare", [2, 3], True),
        (
            "boolean compare(boolean a, boolean b) { return a == b; }",
            "compare",
            [True, True],
            True,
        ),
        (
            "boolean compare(boolean a, boolean b) { return a != b; }",
            "compare",
            [True, False],
            True,
        ),
        (
            'boolean compare(string a, string b) { return a == b; }',
            "compare",
            ["Aether", "Aether"],
            True,
        ),
        (
            'boolean compare(string a, string b) { return a != b; }',
            "compare",
            ["Aether", "IR"],
            True,
        ),
    ],
)
def test_execute_lowered_comparisons(
    source: str,
    function_name: str,
    arguments: list[object],
    expected: object,
) -> None:
    assert IRInterpreter(_lower(source)).call(function_name, arguments) == expected


def test_execute_lowered_comparison_used_as_call_argument() -> None:
    module = _lower(
        """
boolean identity(boolean value) {
    return value;
}

boolean less(int a, int b) {
    return identity(a < b);
}
"""
    )

    assert IRInterpreter(module).call("less", [1, 2]) is True
    assert IRInterpreter(module).call("less", [2, 1]) is False


@pytest.mark.parametrize(
    ("source", "function_name", "arguments", "call"),
    [
        (
            "int add(int a, int b) { return a + b; }",
            "add",
            [2, 3],
            "add(2, 3)",
        ),
        (
            """
int addOffset(int value) {
    int offset = 4;
    int result = value + offset;
    return result;
}
""",
            "addOffset",
            [6],
            "addOffset(6)",
        ),
        (
            """
int increment(int value) {
    return value + 1;
}

int twiceIncrement(int value) {
    return increment(increment(value));
}
""",
            "twiceIncrement",
            [10],
            "twiceIncrement(10)",
        ),
    ],
)
def test_ir_interpreter_matches_current_interpreter(
    source: str,
    function_name: str,
    arguments: list[object],
    call: str,
) -> None:
    expected = _reference_result(source, call)

    assert IRInterpreter(_lower(source)).call(function_name, arguments) == expected


def test_missing_function_error() -> None:
    with pytest.raises(IRExecutionError, match="function 'missing' does not exist"):
        IRInterpreter(IRModule()).call("missing")


def test_wrong_arity_error() -> None:
    parameter = IRParameter("value", IntType())
    module = IRModule(
        [
            IRFunction(
                "identity",
                [parameter],
                IntType(),
                [IRBasicBlock("entry", [IRReturn(parameter)])],
            )
        ]
    )

    with pytest.raises(IRExecutionError, match="expects 1 arguments, got 0"):
        IRInterpreter(module).call("identity")


def test_uninitialized_slot_error() -> None:
    slot = IRValue("missing", IntType())
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

    with pytest.raises(IRExecutionError, match="slot '%missing' is not initialized"):
        IRInterpreter(module).call("read")


def test_unsupported_binary_operation_error() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", IntType())
    result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "compare",
                [left, right],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRBinaryOp(result, "lt", left, right),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(IRExecutionError, match="binary operation 'lt' is not supported"):
        IRInterpreter(module).call("compare", [1, 2])


def test_unsupported_compare_operation_error() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", IntType())
    result = IRValue("0", BoolType())
    module = IRModule(
        [
            IRFunction(
                "compare",
                [left, right],
                BoolType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRCompareOp(result, "unknown", left, right),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(IRExecutionError, match="compare operation 'unknown' is not supported"):
        IRInterpreter(module).call("compare", [1, 2])


def test_division_by_zero_error() -> None:
    numerator = IRParameter("numerator", IntType())
    denominator = IRParameter("denominator", IntType())
    result = IRValue("0", DoubleType())
    module = IRModule(
        [
            IRFunction(
                "divide",
                [numerator, denominator],
                DoubleType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRBinaryOp(result, "div", numerator, denominator),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(IRExecutionError, match="division by zero"):
        IRInterpreter(module).call("divide", [1, 0])


def test_non_void_function_ending_without_return_error() -> None:
    constant = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRConst(constant, 1)])],
            )
        ]
    )

    with pytest.raises(IRExecutionError, match="ended without return"):
        IRInterpreter(module).call("broken")


def test_void_return_produces_none() -> None:
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

    assert IRInterpreter(module).call("nothing") is None
