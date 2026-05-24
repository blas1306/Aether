from __future__ import annotations

import pytest

from aether.ast import ForInStatement, RangeExpression
from aether.errors import AetherTypeError
from aether.lexer import lex
from aether.parser import Parser
from aether.runner import run_aether


def test_parser_builds_for_in_and_range_nodes() -> None:
    program = Parser(lex("for i in 1:2:9 { println(i); }")).parse()

    statement = program.statements[0]
    assert isinstance(statement, ForInStatement)
    assert statement.variable == "i"
    assert isinstance(statement.iterable, RangeExpression)
    assert statement.iterable.step is not None


def test_for_range_inclusive() -> None:
    result = run_aether("for i in 1:5 { println(i); }")

    assert result.output == "1\n2\n3\n4\n5\n"


def test_for_range_with_step() -> None:
    result = run_aether("for i in 1:2:9 { println(i); }")

    assert result.output == "1\n3\n5\n7\n9\n"


def test_for_descending_range_with_negative_step() -> None:
    result = run_aether("for i in 10:-1:1 { println(i); }")

    assert result.output == "10\n9\n8\n7\n6\n5\n4\n3\n2\n1\n"


def test_for_range_wrong_step_sign_is_empty() -> None:
    result = run_aether("for i in 1:-1:10 { println(i); } for j in 10:1 { println(j); }")

    assert result.output == ""


def test_for_accumulates_range_values() -> None:
    result = run_aether("s = 0; for i in 1:5 { s = s + i; } println(s);")

    assert result.output == "15\n"
    assert result.env["s"].value == 15


def test_nested_for_loops_accumulate() -> None:
    result = run_aether(
        """
s = 0;
for i in 1:3 {
    for j in 1:2 {
        s = s + i * j;
    }
}
println(s);
"""
    )

    assert result.output == "18\n"


def test_for_iterates_vector_literal() -> None:
    result = run_aether("v = [10, 20, 30]; for x in v { println(x); }")

    assert result.output == "10\n20\n30\n"


def test_for_iterates_column_vector_literal() -> None:
    result = run_aether("v = [10; 20; 30]; for x in v { println(x); }")

    assert result.output == "10\n20\n30\n"


def test_for_loop_variable_does_not_escape() -> None:
    with pytest.raises(AetherTypeError, match="Undefined variable 'i'"):
        run_aether("for i in 1:3 { println(i); } println(i);")


def test_for_loop_variable_cannot_be_reassigned() -> None:
    with pytest.raises(AetherTypeError, match="Cannot assign to loop variable 'i' inside its own for-loop."):
        run_aether("for i in 1:10 { i = 100; }")


def test_for_loop_variable_cannot_be_reassigned_with_plus_equal() -> None:
    with pytest.raises(AetherTypeError, match="Cannot assign to loop variable 'i' inside its own for-loop."):
        run_aether("for i in 1:10 { i += 1; }")


def test_for_works_in_function_with_plus_equal_accumulation() -> None:
    result = run_aether(
        """
int sumaCuadrados(int n) {
    int suma = 0;

    for i in 1:n {
        suma += i^2;
    }

    return suma;
}

println(sumaCuadrados(3));
"""
    )

    assert result.output == "14\n"


def test_for_rejects_2d_matrix_iteration_for_now() -> None:
    with pytest.raises(AetherTypeError, match="Cannot iterate over value of type 'Matrix<int>'"):
        run_aether("A = [1 2; 3 4]; for x in A { println(x); }")
