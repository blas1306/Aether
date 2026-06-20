from __future__ import annotations

import pytest

from aether.ir import (
    BoolType,
    IRBinaryOp,
    IRCall,
    IRConst,
    IRLoad,
    IRLowerer,
    IRReturn,
    IRStore,
    IntType,
    StringType,
    print_ir,
)
from aether.pipeline import parse_source
from aether.typechecker import TypeChecker


def _lower(source: str):
    program = parse_source(source)
    TypeChecker().check(program)
    return IRLowerer().lower(program)


def test_lower_simple_add_function() -> None:
    module = _lower(
        """
int add(int a, int b) {
    return a + b;
}
"""
    )

    function = module.functions[0]
    operation, terminator = function.blocks[0].instructions

    assert function.name == "add"
    assert function.return_type == IntType()
    assert [parameter.name for parameter in function.parameters] == ["a", "b"]
    assert operation == IRBinaryOp(
        operation.result,
        "add",
        function.parameters[0],
        function.parameters[1],
    )
    assert terminator == IRReturn(operation.result)


def test_lower_function_with_multiple_operations() -> None:
    module = _lower(
        """
int calculate(int a, int b) {
    return (a + b) * (a - b) % b;
}
"""
    )

    instructions = module.functions[0].blocks[0].instructions

    assert [instruction.operator for instruction in instructions[:-1]] == [
        "add",
        "sub",
        "mul",
        "rem",
    ]
    assert isinstance(instructions[-1], IRReturn)


def test_lower_division_and_unary_minus() -> None:
    module = _lower(
        """
double negativeRatio(int a, int b) {
    return -(a / b);
}
"""
    )

    divide, zero, negate, terminator = module.functions[0].blocks[0].instructions

    assert divide.operator == "div"
    assert str(divide.result.type) == "double"
    assert zero == IRConst(zero.result, 0)
    assert zero.result.type == divide.result.type
    assert negate == IRBinaryOp(negate.result, "sub", zero.result, divide.result)
    assert terminator == IRReturn(negate.result)


@pytest.mark.parametrize(
    ("source", "expected_type", "expected_value"),
    [
        ("int answer() { return 42; }", IntType(), 42),
        ("boolean enabled() { return true; }", BoolType(), True),
        ('string name() { return "Aether"; }', StringType(), "Aether"),
    ],
)
def test_lower_return_literal(source: str, expected_type, expected_value: object) -> None:
    module = _lower(source)

    constant, terminator = module.functions[0].blocks[0].instructions

    assert constant == IRConst(constant.result, expected_value)
    assert constant.result.type == expected_type
    assert terminator == IRReturn(constant.result)


def test_lower_simple_local_variable() -> None:
    module = _lower(
        """
int identity(int value) {
    int result = value;
    return result;
}
"""
    )

    parameter = module.functions[0].parameters[0]
    store, load, terminator = module.functions[0].blocks[0].instructions

    assert store == IRStore(store.slot, parameter)
    assert store.slot.name == "result"
    assert store.slot.type == IntType()
    assert load == IRLoad(load.result, store.slot)
    assert terminator == IRReturn(load.result)


def test_lower_simple_call_between_user_functions() -> None:
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

    calls = [
        instruction
        for instruction in module.functions[1].blocks[0].instructions
        if isinstance(instruction, IRCall)
    ]

    assert [call.function for call in calls] == ["increment", "increment"]
    assert calls[1].arguments == (calls[0].result,)
    assert module.functions[1].blocks[0].instructions[-1] == IRReturn(calls[1].result)


def test_pretty_print_lowered_ir() -> None:
    module = _lower(
        """
int add(int a, int b) {
    return a + b;
}
"""
    )

    assert print_ir(module) == (
        "func @add(%a: int, %b: int) -> int {\n"
        "entry:\n"
        "    %0: int = add %a, %b\n"
        "    return %0\n"
        "}"
    )


@pytest.mark.parametrize(
    ("source", "node_name"),
    [
        (
            """
int choose(boolean flag) {
    if flag {
        return 1;
    }
    return 0;
}
""",
            "IfStatement",
        ),
        (
            """
int wait(boolean flag) {
    while flag {
        return 1;
    }
    return 0;
}
""",
            "WhileStatement",
        ),
        ("struct Point { int x; }", "StructDeclaration"),
        ("class Counter { int value; }", "ClassDeclaration"),
    ],
)
def test_unsupported_constructs_have_clear_lowering_errors(
    source: str,
    node_name: str,
) -> None:
    program = parse_source(source)
    TypeChecker().check(program)

    with pytest.raises(
        NotImplementedError,
        match=rf"IR lowering not implemented for {node_name}",
    ):
        IRLowerer().lower(program)
