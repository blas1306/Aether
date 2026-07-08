from __future__ import annotations

import pytest

from aether.ir import (
    BoolType,
    DoubleType,
    IRBinaryOp,
    IRBranch,
    IRCast,
    IRCall,
    IRCompareOp,
    IRConst,
    IRJump,
    IRLoad,
    IRLowerer,
    IRReturn,
    IRStore,
    IRVectorNew,
    IntType,
    StringType,
    VectorType,
    print_ir,
)
from aether.errors import IRBackendUnsupportedFeatureError
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


def test_lower_row_vector_literal() -> None:
    module = _lower(
        """
int main() {
    Vector<int, Row> v = [1, 2, 3];
    return 0;
}
"""
    )

    instructions = module.functions[0].blocks[0].instructions
    vector_new = next(instruction for instruction in instructions if isinstance(instruction, IRVectorNew))

    assert vector_new.result.type == VectorType(IntType(), "row")
    assert vector_new.orientation == "row"
    assert [element.type for element in vector_new.elements] == [IntType(), IntType(), IntType()]
    assert "vector_new row" in print_ir(module)
    assert "vector<int, row>" in print_ir(module)


def test_lower_column_vector_literal_from_expected_type() -> None:
    module = _lower(
        """
int main() {
    Vector<int, Column> v = [1, 2, 3];
    return 0;
}
"""
    )

    instructions = module.functions[0].blocks[0].instructions
    vector_new = next(instruction for instruction in instructions if isinstance(instruction, IRVectorNew))

    assert vector_new.result.type == VectorType(IntType(), "column")
    assert vector_new.orientation == "column"
    assert [element.type for element in vector_new.elements] == [IntType(), IntType(), IntType()]
    assert "vector_new column" in print_ir(module)
    assert "vector<int, column>" in print_ir(module)


def test_lower_column_vector_literal_from_semicolon_syntax() -> None:
    module = _lower(
        """
int main() {
    Vector<int> v = [1; 2; 3];
    return 0;
}
"""
    )

    instructions = module.functions[0].blocks[0].instructions
    vector_new = next(instruction for instruction in instructions if isinstance(instruction, IRVectorNew))

    assert vector_new.result.type == VectorType(IntType(), "column")
    assert vector_new.orientation == "column"
    assert [element.type for element in vector_new.elements] == [IntType(), IntType(), IntType()]
    assert "vector_new column" in print_ir(module)
    assert "vector<int, column>" in print_ir(module)


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


@pytest.mark.parametrize(
    ("source", "source_type", "target_type"),
    [
        ("double widen(int value) { return double(value); }", IntType(), DoubleType()),
        ("int narrow(double value) { return int(value); }", DoubleType(), IntType()),
    ],
)
def test_lower_numeric_cast(
    source: str,
    source_type: object,
    target_type: object,
) -> None:
    module = _lower(source)

    function = module.functions[0]
    cast, terminator = function.blocks[0].instructions

    assert isinstance(cast, IRCast)
    assert cast.value == function.parameters[0]
    assert cast.value.type == source_type
    assert cast.result.type == target_type
    assert terminator == IRReturn(cast.result)


def test_lower_rejects_unsupported_cast() -> None:
    with pytest.raises(
        IRBackendUnsupportedFeatureError,
        match=r"IR backend does not support cast from 'bool' to 'int' yet",
    ):
        _lower("int bad(boolean value) { return int(value); }")


@pytest.mark.parametrize(
    ("source", "operator", "parameter_types"),
    [
        ("boolean compare(int a, int b) { return a < b; }", "lt", [IntType(), IntType()]),
        ("boolean compare(int a, int b) { return a <= b; }", "le", [IntType(), IntType()]),
        ("boolean compare(int a, int b) { return a > b; }", "gt", [IntType(), IntType()]),
        ("boolean compare(int a, int b) { return a >= b; }", "ge", [IntType(), IntType()]),
        ("boolean compare(int a, int b) { return a == b; }", "eq", [IntType(), IntType()]),
        ("boolean compare(int a, int b) { return a != b; }", "ne", [IntType(), IntType()]),
        ("boolean compare(boolean a, boolean b) { return a == b; }", "eq", [BoolType(), BoolType()]),
        ("boolean compare(boolean a, boolean b) { return a != b; }", "ne", [BoolType(), BoolType()]),
        ("boolean compare(string a, string b) { return a == b; }", "eq", [StringType(), StringType()]),
        ("boolean compare(string a, string b) { return a != b; }", "ne", [StringType(), StringType()]),
    ],
)
def test_lower_simple_comparison(
    source: str,
    operator: str,
    parameter_types: list[object],
) -> None:
    module = _lower(source)

    function = module.functions[0]
    comparison, terminator = function.blocks[0].instructions

    assert function.return_type == BoolType()
    assert [parameter.type for parameter in function.parameters] == parameter_types
    assert comparison == IRCompareOp(
        comparison.result,
        operator,
        function.parameters[0],
        function.parameters[1],
    )
    assert comparison.result.type == BoolType()
    assert terminator == IRReturn(comparison.result)


def test_lower_comparison_used_as_call_argument() -> None:
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

    comparison, call, terminator = module.functions[1].blocks[0].instructions

    assert comparison == IRCompareOp(
        comparison.result,
        "lt",
        module.functions[1].parameters[0],
        module.functions[1].parameters[1],
    )
    assert call == IRCall("identity", (comparison.result,), call.result)
    assert terminator == IRReturn(call.result)


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


def test_pretty_print_lowered_comparison_ir() -> None:
    module = _lower(
        """
boolean less(int a, int b) {
    return a < b;
}
"""
    )

    assert print_ir(module) == (
        "func @less(%a: int, %b: int) -> bool {\n"
        "entry:\n"
        "    %0: bool = cmp_lt %a, %b\n"
        "    return %0\n"
        "}"
    )


def test_lower_if_else_with_return_in_both_branches() -> None:
    module = _lower(
        """
int sign(int x) {
    if x > 0 {
        return 1;
    } else {
        return -1;
    }
}
"""
    )

    function = module.functions[0]
    assert [block.name for block in function.blocks] == ["entry", "then0", "else0"]

    zero, comparison, branch = function.blocks[0].instructions
    assert zero == IRConst(zero.result, 0)
    assert comparison == IRCompareOp(
        comparison.result,
        "gt",
        function.parameters[0],
        zero.result,
    )
    assert branch == IRBranch(comparison.result, "then0", "else0")
    assert isinstance(function.blocks[1].instructions[-1], IRReturn)
    assert isinstance(function.blocks[2].instructions[-1], IRReturn)


def test_lower_if_without_else_continues_after_merge() -> None:
    module = _lower(
        """
int absLike(int x) {
    if x < 0 {
        x = 0 - x;
    }
    return x;
}
"""
    )

    function = module.functions[0]
    assert [block.name for block in function.blocks] == ["entry", "then0", "merge0"]

    initial_store, loaded_x, zero, comparison, branch = function.blocks[0].instructions
    assert initial_store == IRStore(initial_store.slot, function.parameters[0])
    assert loaded_x == IRLoad(loaded_x.result, initial_store.slot)
    assert zero == IRConst(zero.result, 0)
    assert comparison == IRCompareOp(
        comparison.result,
        "lt",
        loaded_x.result,
        zero.result,
    )
    assert branch == IRBranch(comparison.result, "then0", "merge0")
    assert function.blocks[1].instructions[-1] == IRJump("merge0")
    assert isinstance(function.blocks[2].instructions[-1], IRReturn)


def test_lower_if_else_assigns_local_and_returns_after_merge() -> None:
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

    function = module.functions[0]
    assert [block.name for block in function.blocks] == [
        "entry",
        "then0",
        "else0",
        "merge0",
    ]

    branch = function.blocks[0].instructions[-1]
    assert isinstance(branch, IRBranch)
    assert (branch.true_target, branch.false_target) == ("then0", "else0")
    assert function.blocks[1].instructions[-1] == IRJump("merge0")
    assert function.blocks[2].instructions[-1] == IRJump("merge0")
    load, terminator = function.blocks[3].instructions
    assert isinstance(load, IRLoad)
    assert terminator == IRReturn(load.result)


def test_pretty_print_lowered_if_else_with_jumps() -> None:
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

    assert print_ir(module) == (
        "func @f(%x: int) -> int {\n"
        "entry:\n"
        "    %0: int = const 0\n"
        "    store %y, %0\n"
        "    %1: int = const 0\n"
        "    %2: bool = cmp_gt %x, %1\n"
        "    branch %2, then0, else0\n"
        "\n"
        "then0:\n"
        "    %3: int = const 1\n"
        "    store %y, %3\n"
        "    jump merge0\n"
        "\n"
        "else0:\n"
        "    %4: int = const 2\n"
        "    store %y, %4\n"
        "    jump merge0\n"
        "\n"
        "merge0:\n"
        "    %5: int = load %y\n"
        "    return %5\n"
        "}"
    )


def test_lower_while_loop() -> None:
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

    function = module.functions[0]
    assert [block.name for block in function.blocks] == [
        "entry",
        "cond0",
        "body0",
        "exit0",
    ]

    assert function.blocks[0].instructions[-1] == IRJump("cond0")
    assert isinstance(function.blocks[1].instructions[-1], IRBranch)
    assert function.blocks[1].instructions[-1].true_target == "body0"
    assert function.blocks[1].instructions[-1].false_target == "exit0"
    assert function.blocks[2].instructions[-1] == IRJump("cond0")
    assert isinstance(function.blocks[3].instructions[-1], IRReturn)


def test_lower_while_with_empty_body() -> None:
    module = _lower(
        """
int emptyLoop(int n) {
    while n < 0 {
    }

    return n;
}
"""
    )

    function = module.functions[0]
    assert [block.name for block in function.blocks] == [
        "entry",
        "cond0",
        "body0",
        "exit0",
    ]
    assert function.blocks[0].instructions == [IRJump("cond0")]
    assert function.blocks[2].instructions == [IRJump("cond0")]
    assert function.blocks[3].instructions == [IRReturn(function.parameters[0])]


def test_pretty_print_lowered_while_loop() -> None:
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

    assert print_ir(module) == (
        "func @sumTo(%n: int) -> int {\n"
        "entry:\n"
        "    %0: int = const 0\n"
        "    store %i, %0\n"
        "    %1: int = const 0\n"
        "    store %sum, %1\n"
        "    jump cond0\n"
        "\n"
        "cond0:\n"
        "    %2: int = load %i\n"
        "    %3: bool = cmp_lt %2, %n\n"
        "    branch %3, body0, exit0\n"
        "\n"
        "body0:\n"
        "    %4: int = load %sum\n"
        "    %5: int = load %i\n"
        "    %6: int = add %4, %5\n"
        "    store %sum, %6\n"
        "    %7: int = load %i\n"
        "    %8: int = const 1\n"
        "    %9: int = add %7, %8\n"
        "    store %i, %9\n"
        "    jump cond0\n"
        "\n"
        "exit0:\n"
        "    %10: int = load %sum\n"
        "    return %10\n"
        "}"
    )


@pytest.mark.parametrize(
    ("source", "node_name"),
    [
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
        IRBackendUnsupportedFeatureError,
        match=rf"IR backend does not support .*{node_name.replace('Declaration', '').lower()}",
    ):
        IRLowerer().lower(program)
