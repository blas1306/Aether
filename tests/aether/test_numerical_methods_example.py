from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil

import pytest

from aether.backend.llvm import LLVMRunner
from aether.pipeline import prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "numerical_methods"
EXPECTED_OUTPUT = [
    "bisection converged: true",
    "bisection accurate: true",
    "newton converged: true",
    "newton accurate: true",
    "secant converged: true",
    "secant accurate: true",
    "invalid bracket rejected: true",
    "zero derivative rejected: true",
    "zero secant denominator rejected: true",
    "trapezoid succeeded: true",
    "trapezoid accurate: true",
    "simpson succeeded: true",
    "simpson accurate: true",
    "invalid trapezoid count rejected: true",
    "invalid Simpson count rejected: true",
    "odd Simpson count rejected: true",
    "reversed trapezoid preserves sign: true",
    "reversed Simpson preserves sign: true",
]


def test_numerical_methods_dogfood_program_validates_all_cases() -> None:
    source = (EXAMPLE / "main.ae").read_text(encoding="utf-8")

    result = run_aether(source, source_root=EXAMPLE)

    assert result.exit_code == 0
    assert result.output.splitlines() == EXPECTED_OUTPUT


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_numerical_methods_dogfood_program_matches_native_backend() -> None:
    source = (EXAMPLE / "main.ae").read_text(encoding="utf-8")
    typed = prepare_typed_program(source, TypeChecker(source_root=EXAMPLE))
    stdout = StringIO()
    stderr = StringIO()

    assert LLVMRunner().run(typed, stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue().splitlines() == EXPECTED_OUTPUT
    assert stderr.getvalue() == ""
