from __future__ import annotations

import pytest

from aether import ast
from aether.errors import AetherTypeError
from aether.lexer import lex
from aether.parser import Parser
from aether.runner import run_aether
from aether.types import MatrixType, TupleType


def _parse(source: str) -> ast.Program:
    return Parser(lex(source)).parse()


def test_parse_function_with_simple_return_type() -> None:
    program = _parse("int f() { return 1; }")

    declaration = program.statements[0]
    assert isinstance(declaration, ast.FunctionDeclaration)
    assert declaration.return_type == "int"
    assert declaration.name == "f"


def test_parse_function_with_tuple_return_type() -> None:
    program = _parse("(int, int) size(Matrix A) { return (1, 2); }")

    declaration = program.statements[0]
    assert isinstance(declaration, ast.FunctionDeclaration)
    assert declaration.return_type == TupleType(("int", "int"))
    assert declaration.parameters[0].type_name == MatrixType("double")
    assert isinstance(declaration.body[0], ast.ReturnStatement)
    assert isinstance(declaration.body[0].expression, ast.TupleLiteral)


def test_parse_function_with_named_tuple_return_type_elements() -> None:
    program = _parse(
        "(Matrix<double> u, Matrix<double> s, Matrix<double> v) f(Matrix<double> B) { return (B, B, B); }"
    )

    declaration = program.statements[0]
    assert isinstance(declaration, ast.FunctionDeclaration)
    assert declaration.return_type == TupleType(
        (MatrixType("double"), MatrixType("double"), MatrixType("double"))
    )
    assert declaration.name == "f"


def test_tuple_return_call_can_be_destructured() -> None:
    result = run_aether(
        """
(int, int) f() { return (3, 4); }
a, b = f();
println(a);
println(b);
"""
    )

    assert result.output == "3\n4\n"
    assert result.env["a"].type_name == "int"
    assert result.env["a"].value == 3
    assert result.env["b"].type_name == "int"
    assert result.env["b"].value == 4


def test_tuple_return_size_style_function_accepts_matrix_parameter_name() -> None:
    result = run_aether(
        """
(int, int) size2(Matrix A) {
    return (rows(A), columns(A));
}
A = [1 2; 3 4];
m, n = size2(A);
println(m);
println(n);
"""
    )

    assert result.output == "2\n2\n"


def test_vector_result_can_be_destructured() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [3 2; 1 0; 0 0];
m, n = size(A);
println(m);
println(n);
"""
    )

    assert result.output == "3\n2\n"
    assert result.env["m"].type_name == "int"
    assert result.env["n"].type_name == "int"


def test_eig_result_can_be_destructured() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [3 2; 1 0; 0 0];
Vec, Vap = eig(A' * A);
println(rows(Vec));
println(cols(Vec));
println(rows(Vap));
println(cols(Vap));
"""
    )

    assert result.output == "2\n2\n2\n2\n"


def test_named_tuple_return_type_elements_can_be_destructured() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra

(Matrix<double> u, Matrix<double> s, Matrix<double> v) f(Matrix<double> B) {
    int m = 3;
    int n = 2;

    u = zeros(m, m);
    s = zeros(m, n);
    v = zeros(n, n);

    return (u, s, v);
}

A = [3 2; 1 0; 0 0];
u, s, v = f(A);
println("u = ", u);
println("s = ", s);
println("v = ", v);
"""
    )

    assert "u = [0.0 0.0 0.0; 0.0 0.0 0.0; 0.0 0.0 0.0]\n" in result.output
    assert "s = [0.0 0.0; 0.0 0.0; 0.0 0.0]\n" in result.output
    assert "v = [0.0 0.0; 0.0 0.0]\n" in result.output


def test_scalar_return_in_tuple_function_is_error() -> None:
    with pytest.raises(
        AetherTypeError,
        match=r"Function f declares return type \(int, int\) but returned int",
    ):
        run_aether("(int, int) f() { return 3; }")


def test_tuple_return_in_scalar_function_is_error() -> None:
    with pytest.raises(
        AetherTypeError,
        match=r"Function f declares return type int but returned \(int, int\)",
    ):
        run_aether("int f() { return (1, 2); }")


def test_tuple_return_element_type_mismatch_is_error() -> None:
    with pytest.raises(
        AetherTypeError,
        match=r"Function f declares return type \(int, float\) but returned \(int, string\)",
    ):
        run_aether('(int, float) f() { return (1, "hola"); }')


def test_destructuring_arity_mismatch_is_error() -> None:
    with pytest.raises(AetherTypeError, match="Destructuring expected 2 values but got 3"):
        run_aether(
            """
(int, int) f() { return (1, 2); }
a, b, c = f();
"""
        )


def test_scalar_value_cannot_be_destructured() -> None:
    with pytest.raises(AetherTypeError, match="Cannot destructure value of type int"):
        run_aether(
            """
int f() { return 1; }
a, b = f();
"""
        )


def test_tuple_return_can_be_assigned_as_complete_value() -> None:
    result = run_aether(
        """
(int, int) f() { return (1, 2); }
t = f();
println(t);
"""
    )

    assert result.output == "(1, 2)\n"
    assert result.env["t"].type_name == TupleType(("int", "int"))
    assert [element.value for element in result.env["t"].value] == [1, 2]


def test_tuple_return_allows_float_literal_for_float_element() -> None:
    result = run_aether(
        """
(int, float, string) f() {
    return (3, 2.5, "hola");
}
a, b, c = f();
"""
    )

    assert result.env["a"].type_name == "int"
    assert result.env["b"].type_name == "float"
    assert result.env["b"].value == pytest.approx(2.5)
    assert result.env["c"].type_name == "string"
