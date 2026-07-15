from __future__ import annotations

from pathlib import Path

from aether.runner import run_aether


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "numerical_methods"


def test_numerical_methods_dogfood_program_validates_all_cases() -> None:
    source = (EXAMPLE / "main.ae").read_text(encoding="utf-8")

    result = run_aether(source, source_root=EXAMPLE)

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "bisection converged: true",
        "bisection accurate: true",
        "newton converged: true",
        "newton accurate: true",
        "secant converged: true",
        "secant accurate: true",
        "invalid bracket rejected: true",
        "zero derivative rejected: true",
        "zero secant denominator rejected: true",
        "trapezoid accurate: true",
        "simpson accurate: true",
        "invalid Simpson rejected: true",
    ]
