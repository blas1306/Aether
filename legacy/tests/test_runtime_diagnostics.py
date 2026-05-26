from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest
import sympy as sp

from diagnostics import MathTeXRuntimeError
from latex_lang import (
    _mt_apply_symbol,
    _mt_call,
    _mt_mul,
    _oct_get1,
    _oct_get2,
    _oct_set1,
    env_ast,
    ejecutar_linea,
    reset_environment,
)


@pytest.fixture(autouse=True)
def _fresh_runtime():
    reset_environment()
    yield
    reset_environment()


def _run(line: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ejecutar_linea(line)
    return buffer.getvalue()


def test_mt_call_undefined_function_raises_runtime_diagnostic():
    with pytest.raises(MathTeXRuntimeError) as exc_info:
        _mt_call("foo", 1)

    err = exc_info.value
    assert err.kind == "undefined-function"
    assert "Function foo is not defined." in str(err)


def test_mt_apply_symbol_on_scalar_reports_not_callable():
    env_ast["x"] = 5

    with pytest.raises(MathTeXRuntimeError) as exc_info:
        _mt_apply_symbol("x", 1)

    err = exc_info.value
    assert err.kind == "not-callable"
    assert "x is not callable." in str(err)


def test_oct_get2_out_of_range_reports_runtime_diagnostic():
    env_ast["A"] = sp.Matrix([[1, 2], [3, 4]])

    with pytest.raises(MathTeXRuntimeError) as exc_info:
        _oct_get2("A", 3, 1)

    err = exc_info.value
    assert err.kind == "index-out-of-range"
    assert "Index (3, 1) is out of range for A." in str(err)


def test_oct_get1_on_scalar_reports_invalid_index_target():
    env_ast["x"] = 5

    with pytest.raises(MathTeXRuntimeError) as exc_info:
        _oct_get1("x", 1)

    err = exc_info.value
    assert err.kind == "invalid-index-target"
    assert "x is not a vector/matrix." in str(err)


def test_oct_set1_out_of_range_reports_runtime_diagnostic():
    env_ast["v"] = sp.Matrix([[1], [2], [3]])

    with pytest.raises(MathTeXRuntimeError) as exc_info:
        _oct_set1("v", 10, 99)

    err = exc_info.value
    assert err.kind == "index-out-of-range"
    assert "Index 10 is out of range for v." in str(err)


def test_mt_mul_incompatible_dimensions_raises_runtime_diagnostic():
    with pytest.raises(MathTeXRuntimeError) as exc_info:
        _mt_mul(sp.Matrix([[1, 2], [3, 4]]), sp.Matrix([[1, 2, 3]]))

    err = exc_info.value
    assert err.kind == "incompatible-dimensions"
    assert "matrix multiplication" in str(err)


def test_runtime_assignment_reports_undefined_variable_cleanly():
    output = _run("a = foo + 1;")

    assert "Error defining variable" in output
    assert "Variable foo is not defined." in output
    assert "a" not in env_ast


def test_runtime_assignment_reports_undefined_function_cleanly():
    output = _run("a = foo(1);")

    assert "Error defining variable" in output
    assert "Function foo is not defined." in output
    assert "a" not in env_ast


def test_runtime_assignment_reports_not_callable_cleanly():
    _run("f = 99;")
    output = _run("a = f(2);")

    assert "Error defining variable" in output
    assert "f is not callable." in output
    assert "a" not in env_ast


def test_runtime_assignment_reports_out_of_range_index_cleanly():
    _run("A = [1,2;3,4];")
    output = _run("x = A(3,1);")

    assert "Error defining variable" in output
    assert "Index (3, 1) is out of range for A." in output
    assert "x" not in env_ast


def test_runtime_assignment_reports_incompatible_dimensions_cleanly():
    _run("A = [1,2;3,4];")
    _run("B = [1,2,3];")
    output = _run("C = A * B;")

    assert "Error defining variable" in output
    assert "Incompatible dimensions for matrix multiplication." in output
    assert "C" not in env_ast


def test_runtime_recovers_cleanly_after_error():
    failure_output = _run("bad = foo(1);")
    success_output = _run("good = 2 + 2;")

    assert "Function foo is not defined." in failure_output
    assert success_output == ""
    assert env_ast["good"] == 4
    assert "bad" not in env_ast


def test_complex_abs_command_uses_user_function_dispatch_in_console():
    _run("f(x) = x + 1;")
    _run("xN = 2;")

    output = _run(r"\abs(f(xN))")

    assert "Error while evaluating abs" not in output
    assert output.strip() == "3"
