from __future__ import annotations

import pytest

from aether.errors import AetherInputError, AetherRuntimeError, AetherTypeError
from aether.runner import run_aether


def _reader(*lines: str):
    pending = list(lines)

    def read_line() -> str:
        return pending.pop(0) if pending else ""

    return read_line


def test_aether_error_formats_line_column_hint_and_kind() -> None:
    error = AetherTypeError(
        "Cannot add Matrix(2x3) and Matrix(3x2).",
        line=4,
        column=12,
        hint="matrix addition requires equal shapes.",
        kind="shape",
    )

    assert str(error) == (
        "AetherTypeError at line 4, column 12 [shape]:\n"
        "  Cannot add Matrix(2x3) and Matrix(3x2).\n"
        "  Hint: matrix addition requires equal shapes."
    )


def test_aether_error_without_line_column_keeps_legacy_message() -> None:
    error = AetherRuntimeError("Something went wrong.")

    assert str(error) == "Something went wrong."
    assert error.message == "Something went wrong."
    assert error.line is None
    assert error.column is None


def test_aether_error_without_line_column_can_still_show_hint() -> None:
    error = AetherRuntimeError("Something went wrong.", hint="try a smaller step.")

    assert str(error) == "AetherRuntimeError:\n  Something went wrong.\n  Hint: try a smaller step."


def test_undefined_variable_error_includes_source_location_and_hint() -> None:
    with pytest.raises(AetherTypeError) as raised:
        run_aether("println(missing);")

    error = raised.value
    assert error.line == 1
    assert error.column >= 1
    assert error.kind == "name"
    assert "Undefined variable 'missing'." in str(error)
    assert "Hint:" in str(error)


def test_function_arity_error_includes_source_location_and_hint() -> None:
    source = """
int add(int a, int b) {
    return a + b;
}

add(1);
"""

    with pytest.raises(AetherTypeError) as raised:
        run_aether(source)

    error = raised.value
    assert error.line == 6
    assert error.kind == "arity"
    assert "Function 'add' expects 2 arguments but got 1." in str(error)
    assert "Hint:" in str(error)


def test_invalid_type_operation_includes_source_location() -> None:
    with pytest.raises(AetherTypeError) as raised:
        run_aether("value = true + 1;")

    error = raised.value
    assert error.line == 1
    assert error.kind == "operator"
    assert "Operator '+' cannot be applied to boolean values." in str(error)


def test_matrix_shape_mismatch_error_includes_shapes_and_hint() -> None:
    source = """
A = [1 2; 3 4];
B = [1 2 3; 4 5 6];
C = A + B;
"""

    with pytest.raises(AetherTypeError) as raised:
        run_aether(source)

    error = raised.value
    assert error.line == 4
    assert error.kind == "shape"
    assert "Matrix<int>(2x2) and Matrix<int>(2x3)" in str(error)
    assert "Hint: matrix addition and elementwise operations require equal shapes." in str(error)


def test_invalid_input_error_includes_source_location_and_hint() -> None:
    with pytest.raises(AetherInputError) as raised:
        run_aether("int n = input();", input_reader=_reader("hola\n"))

    error = raised.value
    assert error.line == 1
    assert error.kind == "input"
    assert 'cannot convert "hola" to int' in str(error)
    assert "Hint: enter a whole number" in str(error)
