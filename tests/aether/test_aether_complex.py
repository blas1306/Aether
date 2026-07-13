from __future__ import annotations

import pytest

from aether import run_aether
from aether.ast import BinaryExpression, Literal
from aether.errors import AetherTypeError
from aether.lexer import lex
from aether.parser import Parser
from aether.tokens import TokenType
from aether.types import MatrixType, VectorType


def test_imaginary_literals_lex_and_parse() -> None:
    tokens = lex("z = 1 + 2im; w = im;")

    assert any(token.type == TokenType.IMAG_LITERAL and token.literal == 2j for token in tokens)
    assert any(token.type == TokenType.IMAG_LITERAL and token.literal == 1j for token in tokens)

    expression = Parser(lex("1 + 2im")).parse_expression()
    assert isinstance(expression, BinaryExpression)
    assert isinstance(expression.right, Literal)
    assert expression.right.type_name == "complex"
    assert expression.right.value == 2j


def test_i_is_not_an_imaginary_alias() -> None:
    with pytest.raises(AetherTypeError, match="Undefined variable 'i'"):
        run_aether("z = 1 + 2 * i;")


def test_complex_scalar_inference_coercion_and_rejections() -> None:
    result = run_aether(
        """
z = 1 + 2im;
complex w = 3;
complex c = complex(4, -5);
println(z);
println(w);
println(c);
"""
    )

    assert result.env["z"].type_name == "complex"
    assert result.env["z"].value == complex(1, 2)
    assert result.env["w"].value == complex(3, 0)
    assert result.env["c"].value == complex(4, -5)
    assert result.output == "1.0 + 2.0im\n3.0\n4.0 - 5.0im\n"

    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'complex' to 'double'"):
        run_aether("complex z = im; double x = z;")
    with pytest.raises(AetherTypeError, match="Cannot explicitly convert 'complex' to 'double'"):
        run_aether("double x = double(im);")


def test_complex_scalar_operators_and_errors() -> None:
    result = run_aether(
        """
a = 1 + 2im;
b = 3 - im;
println(a + b);
println(a * b);
println(a / b);
println(a ^ 2);
println(a == 1 + 2im);
println(a != b);
"""
    )

    assert result.output == (
        "4.0 + im\n"
        "5.0 + 5.0im\n"
        "0.1 + 0.7im\n"
        "-3.0 + 4.0im\n"
        "true\n"
        "true\n"
    )

    with pytest.raises(AetherTypeError, match="requires real numeric operands"):
        run_aether("(1 + im) % 2;")
    with pytest.raises(AetherTypeError, match="requires real numeric operands"):
        run_aether("(1 + im) < 2;")


def test_complex_builtins() -> None:
    result = run_aether(
        """
z = 3 + 4im;
println(real(z));
println(imag(z));
println(conj(z));
println(abs(z));
println(angle(1 + im));
println(sqrt(-1));
println(sqrt(4));
"""
    )

    assert result.env["z"].type_name == "complex"
    lines = result.output.splitlines()
    assert lines[:4] == [
        "3.0",
        "4.0",
        "3.0 - 4.0im",
        "5.0",
    ]
    assert float(lines[4]) == pytest.approx(0.7853981633974483)
    assert lines[5:] == ["im", "2.0"]


def test_complex_matrix_and_vector_literals_and_assignment() -> None:
    result = run_aether(
        """
Matrix<complex> A = [1 2im; 3 4];
Vector<complex> v = [1, im, 3];
A[1, 1] = 5im;
v[2] = 2 + im;
println(A);
println(v);
"""
    )

    assert result.env["A"].type_name == MatrixType("complex", 2, 2)
    assert result.env["v"].type_name == VectorType("complex", 3)
    assert result.output == "[5.0im 2.0im; 3.0 4.0]\n[1.0 2.0 + im 3.0]\n"


def test_complex_linear_algebra_supported_surface() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [1 im; 2 3 - im];
v = [1 + im, 2];
t = Math.LinearAlgebra.transpose(A);
h = A';
m = Math.LinearAlgebra.matmul(A, [1; im]);
inner_value = Math.LinearAlgebra.inner(v, v);
norm_value = Math.LinearAlgebra.norm(v);
println(t);
println(h);
println(m);
println(inner_value);
println(norm_value);
"""
    )

    assert result.env["A"].type_name == MatrixType("complex", 2, 2)
    assert result.env["m"].type_name == VectorType("complex", 2, "column")
    assert result.env["m"].type_name.orientation == "column"
    assert result.env["inner_value"].type_name == "complex"
    assert result.env["inner_value"].value == pytest.approx(complex(6, 0))
    assert result.env["norm_value"].value == pytest.approx(6**0.5)
    assert result.output.splitlines()[:4] == [
        "[1.0 2.0; im 3.0 - im]",
        "[1.0 2.0; -im 3.0 + im]",
        "[0.0; 3.0 + 3.0im]",
        "6.0",
    ]
