from __future__ import annotations

import pytest

from aether.errors import AetherInputError, AetherTypeError
from aether.runner import run_aether
from aether.types import MatrixType, VectorType


def _reader(*lines: str):
    pending = list(lines)

    def read_line() -> str:
        return pending.pop(0) if pending else ""

    return read_line


def _vector_values(value):
    return [element.value for element in value.value]


def _matrix_values(value):
    return [[element.value for element in row.value] for row in value.value]


def test_input_int_valid():
    result = run_aether("int n = input();", input_reader=_reader("42\n"))

    assert result.env["n"].type_name == "int"
    assert result.env["n"].value == 42


def test_input_float_valid():
    result = run_aether('float x = input("x = ");', input_reader=_reader("3.5\n"))

    assert result.output == "x = "
    assert result.env["x"].type_name == "float"
    assert result.env["x"].value == pytest.approx(3.5)


def test_input_string_valid():
    result = run_aether('string name = input("Nombre: ");', input_reader=_reader("Ada\n"))

    assert result.output == "Nombre: "
    assert result.env["name"].type_name == "string"
    assert result.env["name"].value == "Ada"


def test_input_boolean_valid():
    result = run_aether('boolean ok = input("Continuar? ");', input_reader=_reader("true\n"))

    assert result.output == "Continuar? "
    assert result.env["ok"].type_name == "boolean"
    assert result.env["ok"].value is True


def test_input_vector_valid():
    result = run_aether('Vector<double> v = input("v = ");', input_reader=_reader("[1, 2.5, 3]\n"))

    assert result.output == "v = "
    assert result.env["v"].type_name == VectorType("double", 3)
    assert _vector_values(result.env["v"]) == pytest.approx([1.0, 2.5, 3.0])


def test_input_matrix_valid():
    result = run_aether('Matrix<double> A = input("A = ");', input_reader=_reader("[1 2; 3.5 4]\n"))

    assert result.output == "A = "
    assert result.env["A"].type_name == MatrixType("double", 2, 2)
    assert _matrix_values(result.env["A"]) == [[1.0, 2.0], [3.5, 4.0]]


def test_input_matrix_assignment_uses_existing_type():
    result = run_aether(
        "Matrix<int> A = [0 0; 0 0]; A = input();",
        input_reader=_reader("[1 2; 3 4]\n"),
    )

    assert result.env["A"].type_name == MatrixType("int", 2, 2)
    assert _matrix_values(result.env["A"]) == [[1, 2], [3, 4]]


def test_input_invalid_int_conversion_raises_input_error():
    with pytest.raises(AetherInputError, match='cannot convert "hola" to int'):
        run_aether("int n = input();", input_reader=_reader("hola\n"))


def test_input_invalid_float_conversion_raises_input_error():
    with pytest.raises(AetherInputError, match='cannot convert "hola" to float'):
        run_aether("float x = input();", input_reader=_reader("hola\n"))


def test_input_invalid_boolean_conversion_raises_input_error():
    with pytest.raises(AetherInputError, match='cannot convert "yes" to boolean'):
        run_aether("boolean ok = input();", input_reader=_reader("yes\n"))


def test_input_invalid_vector_conversion_raises_input_error():
    with pytest.raises(AetherInputError, match=r'cannot convert "\[1 2; 3 4\]" to Vector<double>'):
        run_aether("Vector<double> v = input();", input_reader=_reader("[1 2; 3 4]\n"))


def test_input_requires_typed_assignment_context():
    with pytest.raises(AetherTypeError, match="typed assignment context"):
        run_aether("x = input();", input_reader=_reader("42\n"))


def test_input_uses_existing_assignment_type():
    result = run_aether("int n = 0; n = input();", input_reader=_reader("7\n"))

    assert result.env["n"].type_name == "int"
    assert result.env["n"].value == 7


def test_input_prompt_must_be_string():
    with pytest.raises(AetherTypeError, match="prompt must be string"):
        run_aether("int n = input(1);", input_reader=_reader("42\n"))
