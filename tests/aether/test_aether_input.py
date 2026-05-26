from __future__ import annotations

import pytest

from aether.errors import AetherInputError, AetherTypeError
from aether.runner import run_aether


def _reader(*lines: str):
    pending = list(lines)

    def read_line() -> str:
        return pending.pop(0) if pending else ""

    return read_line


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


def test_input_invalid_int_conversion_raises_input_error():
    with pytest.raises(AetherInputError, match='cannot convert "hola" to int'):
        run_aether("int n = input();", input_reader=_reader("hola\n"))


def test_input_invalid_float_conversion_raises_input_error():
    with pytest.raises(AetherInputError, match='cannot convert "hola" to float'):
        run_aether("float x = input();", input_reader=_reader("hola\n"))


def test_input_invalid_boolean_conversion_raises_input_error():
    with pytest.raises(AetherInputError, match='cannot convert "yes" to boolean'):
        run_aether("boolean ok = input();", input_reader=_reader("yes\n"))


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
