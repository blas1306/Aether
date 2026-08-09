from __future__ import annotations

from io import StringIO
import json
import math
from pathlib import Path
import shutil

import pytest

from aether.backend.llvm import LLVMBuilder, LLVMRunner
from aether.capabilities import BackendIdentity, backend_capability_issues
from aether.errors import AetherRuntimeError, AetherTypeError
from aether.integer_arithmetic import (
    INTEGER_OVERFLOW_MESSAGE,
    NEGATIVE_INTEGER_EXPONENT_MESSAGE,
)
from aether.ir import IRCast, IRExecutionError
from aether.ir.interpreter import IRInterpreter
from aether.ir.optimizer import OptimizerPipeline
from aether.pipeline import IRBackend, prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads(
    (ROOT / "examples" / "v1_examples_manifest.json").read_text(encoding="utf-8")
)
NUMERIC_DOGFOOD_PATHS = {
    "examples/FormulaNumerosPrimos.ae",
    "examples/ProbandoNR/probandoNR2.ae",
    "examples/ProbandoNR/probandoNR3.ae",
}
NUMERIC_DOGFOOD_ENTRIES = [
    entry for entry in MANIFEST["entries"] if entry["path"] in NUMERIC_DOGFOOD_PATHS
]


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _native_output(source: str) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    code = LLVMRunner().run(_typed(source), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def _ir_output(source: str) -> tuple[int, str]:
    interpreter = IRInterpreter(IRBackend().lower_verified(_typed(source)))
    result = interpreter.call("main")
    return result, interpreter.output


def _assert_observations_match(actual: str, expected: str) -> None:
    actual_lines = actual.splitlines()
    expected_lines = expected.splitlines()
    assert len(actual_lines) == len(expected_lines)
    for actual_line, expected_line in zip(actual_lines, expected_lines):
        actual_prefix, separator, actual_value = actual_line.rpartition(" = ")
        expected_prefix, expected_separator, expected_value = expected_line.rpartition(" = ")
        if separator or expected_separator:
            assert (actual_prefix, separator) == (expected_prefix, expected_separator)
        else:
            actual_value = actual_line
            expected_value = expected_line
        try:
            actual_number = float(actual_value)
            expected_number = float(expected_value)
        except ValueError:
            assert actual_value == expected_value
            continue
        if math.isnan(expected_number):
            assert math.isnan(actual_number)
        else:
            assert actual_number == pytest.approx(expected_number, rel=1e-14, abs=1e-14)


CONTEXTUAL_PROMOTION_SOURCE = """
struct Point { double x; }

double forwarded() { return later(7); }
double later(double value) { return value; }
double invoke(Function<(double), double> operation) { return operation(6); }
void consume(double value) { println(value); }

int main() {
    double variable = 1;
    variable = 2;
    consume(3);
    Point point = Point(4);
    point.x = 5;
    List<double> list = {8, 9};
    Array<double> array = {10, 11};
    Vector<double, Row> vector = [12, 13];
    println(forwarded());
    println(invoke(later));
    println(variable);
    println(point.x);
    println(list[0]);
    println(array[0]);
    println(vector[1]);
    return 0;
}
"""


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_contextual_int_to_double_promotion_matches_all_backends() -> None:
    expected = "3.0\n7.0\n6.0\n2.0\n5.0\n8.0\n10.0\n12.0\n"
    _assert_observations_match(run_aether(CONTEXTUAL_PROMOTION_SOURCE).output, expected)
    ir_code, ir_output = _ir_output(CONTEXTUAL_PROMOTION_SOURCE)
    native_code, native_output, native_error = _native_output(CONTEXTUAL_PROMOTION_SOURCE)
    assert (ir_code, native_code, native_error) == (0, 0, "")
    _assert_observations_match(ir_output, expected)
    _assert_observations_match(native_output, expected)


def test_contextual_int_to_double_promotion_applies_to_class_fields_in_ast_profile() -> None:
    source = """
class Point { public double x; }
Point point = Point(1);
point.x = 2;
println(point.x);
"""
    assert run_aether(source).output == "2.0\n"


@pytest.mark.parametrize(
    "source",
    [
        "int main() { int value = 1.5; return value; }",
        "int main() { int value = 1; value = 1.5; return value; }",
        "int take(int value) { return value; } int main() { return take(1.5); }",
        "int take() { return 1.5; } int main() { return take(); }",
        "struct P { int x; } int main() { P p = P(1.5); return 0; }",
    ],
)
def test_double_to_int_still_requires_an_explicit_cast(source: str) -> None:
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert"):
        _typed(source)


MIXED_NUMERIC_SOURCE = """
int main() {
    println(2 + 0.5); println(0.5 + 2);
    println(2 - 0.5); println(2.5 - 2);
    println(2 * 0.5); println(0.5 * 2);
    println(5 / 2.0); println(5.0 / 2);
    println(5 % 2.0); println(5.0 % 2);
    println(2 ^ 3.0); println(2.0 ^ 3);
    println(1 < 1.5); println(1.5 > 1);
    println(2 == 2.0); println(2.0 != 3);
    println(5 / 2);
    return 0;
}
"""


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_mixed_numeric_operations_match_all_backends_in_both_orders() -> None:
    expected = run_aether(MIXED_NUMERIC_SOURCE).output
    assert expected.splitlines()[-1] == "2.5"
    ir_code, ir_output = _ir_output(MIXED_NUMERIC_SOURCE)
    native_code, native_output, native_error = _native_output(MIXED_NUMERIC_SOURCE)
    assert (ir_code, native_code, native_error) == (0, 0, "")
    _assert_observations_match(ir_output, expected)
    _assert_observations_match(native_output, expected)


def test_mixed_numeric_lowering_inserts_explicit_homogeneous_casts() -> None:
    module = IRBackend().lower_verified(
        _typed("double f(double x) { return x - 1; } int main() { return int(f(3)); }")
    )
    casts = [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCast)
    ]
    assert any(str(cast.value.type) == "int" and str(cast.result.type) == "double" for cast in casts)
    for function in module.functions:
        for block in function.blocks:
            for instruction in block.instructions:
                if hasattr(instruction, "left") and hasattr(instruction, "right"):
                    assert instruction.left.type == instruction.right.type


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_identity_casts_accept_constants_and_non_constants() -> None:
    source = """
int same_int(int value) { return int(value); }
double same_double(double value) { return double(value); }
int main() {
    println(int(1)); println(double(1.5));
    println(same_int(2)); println(same_double(2.5));
    return 0;
}
"""
    expected = "1\n1.5\n2\n2.5\n"
    assert run_aether(source).output == expected
    assert _ir_output(source) == (0, expected)
    assert _native_output(source) == (0, expected, "")


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_integer_power_table_and_i32_boundaries_match_all_backends() -> None:
    source = """
int main() {
    println(2^0); println(2^1); println(2^10); println(0^0);
    println((-2)^3); println((-2)^4); println(2^30); println((-2)^31);
    return 0;
}
"""
    expected = "1\n2\n1024\n1\n-8\n16\n1073741824\n-2147483648\n"
    assert run_aether(source).output == expected
    assert _ir_output(source) == (0, expected)
    assert _native_output(source) == (0, expected, "")


def test_integer_power_overflow_is_not_folded_away() -> None:
    source = "int main() { int value = 2 ^ 31; return value; }"
    with pytest.raises(AetherRuntimeError, match=INTEGER_OVERFLOW_MESSAGE):
        run_aether(source)
    optimized = OptimizerPipeline().run(IRBackend().lower_verified(_typed(source)))
    with pytest.raises(IRExecutionError, match=INTEGER_OVERFLOW_MESSAGE):
        IRInterpreter(optimized).call("main")


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_integer_power_overflow_survives_native_optimization() -> None:
    source = "int power(int base, int exponent) { return base ^ exponent; } int main() { return power(2, 31); }"
    assert _native_output(source) == (1, f"{INTEGER_OVERFLOW_MESSAGE}\n", "")


def test_negative_integer_exponent_has_static_and_dynamic_diagnostics() -> None:
    with pytest.raises(AetherTypeError, match="Integer exponent must be non-negative"):
        _typed("int main() { return 2 ^ -1; }")

    source = "int power(int base, int exponent) { return base ^ exponent; } int main() { return power(2, -1); }"
    with pytest.raises(AetherRuntimeError, match=NEGATIVE_INTEGER_EXPONENT_MESSAGE):
        run_aether(source)
    with pytest.raises(IRExecutionError, match=NEGATIVE_INTEGER_EXPONENT_MESSAGE):
        _ir_output(source)


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_floating_power_ieee_cases_match_all_backends() -> None:
    source = """
int main() {
    println(4.0^0.5); println(2.0^3); println(2^3.0);
    println((-1.0)^0.5); println(0.0^-1.0); println((-0.0)^-3.0);
    return 0;
}
"""
    expected = "2.0\n8.0\n8.0\nNaN\nInfinity\n-Infinity\n"
    _assert_observations_match(run_aether(source).output, expected)
    ir_code, ir_output = _ir_output(source)
    native_code, native_output, native_error = _native_output(source)
    assert (ir_code, native_code, native_error) == (0, 0, "")
    _assert_observations_match(ir_output, expected)
    _assert_observations_match(native_output, expected)


def test_llvm_uses_checked_i32_power_and_libm_double_power() -> None:
    source = """
int integer_power(int base, int exponent) { return base ^ exponent; }
double double_power(double base, double exponent) { return base ^ exponent; }
int main() { return integer_power(2, int(double_power(2.0, 3.0))); }
"""
    llvm = LLVMBuilder().emit_llvm(_typed(source))
    assert "@aether_checked_pow_i32" in llvm
    assert "declare double @pow(double, double)" in llvm
    assert "call double @pow(double %base, double %exponent)" in llvm


def test_native_capability_gate_accepts_numeric_parity_subset() -> None:
    source = "double f(double x) = x * exp(x) - 1.0; int main() { return int(f(0)); }"
    assert backend_capability_issues(_typed(source), BackendIdentity.NATIVE) == ()


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize(
    "entry",
    NUMERIC_DOGFOOD_ENTRIES,
    ids=[entry["path"] for entry in NUMERIC_DOGFOOD_ENTRIES],
)
def test_numeric_dogfood_examples_execute_natively(entry: dict[str, object]) -> None:
    relative_path = str(entry["path"])
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    stdout = StringIO()
    stderr = StringIO()
    code = LLVMRunner().run(
        _typed(source),
        stdout=stdout,
        stderr=stderr,
        timeout_seconds=int(entry["timeout_seconds"]),
    )
    assert code == 0
    assert stderr.getvalue() == ""
    if entry.get("ast_parity", True):
        _assert_observations_match(stdout.getvalue(), run_aether(source).output)
