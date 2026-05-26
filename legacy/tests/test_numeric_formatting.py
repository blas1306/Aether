from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest
import sympy as sp

from latex_lang import env_ast, ejecutar_linea, reset_environment, set_plot_mode
from mtex_executor import ejecutar_mtex, reemplazar_vars
from numeric_format import format_value_for_display, set_numeric_format
from parsers import matrix_to_str


def _run(line: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ejecutar_linea(line)
    return buffer.getvalue()


def _write_doc(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _successful_pdflatex():
    class _Result:
        returncode = 0

    def _run_pdflatex(
        tex_filename: str,
        cwd: str,
        draftmode: bool = False,
        output_dir: str | None = None,
        synctex: bool = False,
    ):
        del synctex
        target_dir = Path(output_dir or cwd)
        target_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(tex_filename).stem
        (target_dir / f"{stem}.log").write_text("Compilation finished.\n", encoding="utf-8")
        if not draftmode:
            (target_dir / f"{stem}.pdf").write_bytes(b"%PDF-1.4\n%mock\n")
        return _Result()

    return _run_pdflatex


@pytest.fixture(autouse=True)
def _fresh_runtime():
    set_plot_mode("interactive")
    reset_environment()
    yield
    set_plot_mode("interactive")
    reset_environment()


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("short", "x = 0.3333\n"),
        ("long", "x = 0.333333333333333\n"),
        ("shorte", "x = 3.3333e-01\n"),
        ("longe", "x = 3.333333333333333e-01\n"),
        ("bank", "x = 0.33\n"),
    ],
)
def test_format_command_controls_scalar_display(mode: str, expected: str):
    _run(rf"\format({mode})")
    assert _run("x = 1/3") == expected


@pytest.mark.parametrize(
    ("mode", "tokens"),
    [
        ("short", ["0.3333", "2", "1.5000", "0.8000"]),
        ("long", ["0.333333333333333", "2", "1.500000000000000", "0.800000000000000"]),
        ("shorte", ["3.3333e-01", "2.0000e+00", "1.5000e+00", "8.0000e-01"]),
        ("longe", ["3.333333333333333e-01", "2.000000000000000e+00", "1.500000000000000e+00", "8.000000000000000e-01"]),
        ("bank", ["0.33", "2.00", "1.50", "0.80"]),
    ],
)
def test_matrix_formatting_respects_active_mode(mode: str, tokens: list[str]):
    set_numeric_format(mode)
    rendered = matrix_to_str(sp.Matrix([[sp.Rational(1, 3), 2], [sp.Rational(3, 2), sp.Rational(4, 5)]]))
    for token in tokens:
        assert token in rendered


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("short", "0.3333+2i"),
        ("long", "0.333333333333333+2i"),
        ("shorte", "3.3333e-01+2.0000e+00i"),
        ("longe", "3.333333333333333e-01+2.000000000000000e+00i"),
        ("bank", "0.33+2.00i"),
    ],
)
def test_complex_values_respect_active_mode(mode: str, expected: str):
    set_numeric_format(mode)
    value = sp.Rational(1, 3) + 2 * sp.I
    assert format_value_for_display(value) == expected


def test_var_placeholder_uses_active_scalar_format():
    set_numeric_format("bank")
    rendered = reemplazar_vars(r"\var{x}", {"x": sp.Rational(1, 3)})
    assert rendered == "0.33"


def test_var_placeholder_uses_active_matrix_format():
    set_numeric_format("bank")
    rendered = reemplazar_vars(r"\var{A}", {"A": sp.Matrix([[sp.Rational(1, 3), 2]])})
    assert "0.33" in rendered
    assert "2.00" in rendered


def test_symbolic_var_placeholder_remains_symbolic():
    set_numeric_format("bank")
    rendered = reemplazar_vars(r"\var{expr}", {"expr": sp.Symbol("x") + 1})
    assert rendered == "x + 1"


def test_reset_environment_restores_default_numeric_format():
    _run(r"\format(long)")
    reset_environment()
    assert _run("x = 1/3") == "x = 0.3333\n"


def test_print_command_uses_active_numeric_format():
    _run(r"\format(bank)")
    assert _run(r"\print(1/3)") == "0.33\n"


def test_document_var_output_respects_active_format_across_codeblocks(tmp_path: Path):
    source = _write_doc(
        tmp_path,
        "format_doc.mtex",
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\codeblock\n"
        "\\format(bank)\n"
        "a = 1/3;\n"
        "\\endcodeblock\n"
        "A=\\var{a}\n"
        "\\codeblock\n"
        "b = 1/6;\n"
        "A = [1/3, 2];\n"
        "\\endcodeblock\n"
        "B=\\var{b}\n"
        "M=\\var{A}\n"
        "\\end{document}\n",
    )

    with patch("mtex_executor._run_pdflatex", side_effect=_successful_pdflatex()):
        ejecutar_mtex(str(source), env_ast, abrir_pdf=False, build_dir=tmp_path / "build")

    generated_tex = (tmp_path / "build" / "format_doc.tex").read_text(encoding="utf-8")

    assert "A=0.33" in generated_tex
    assert "B=0.17" in generated_tex
    assert "0.33" in generated_tex
    assert "2.00" in generated_tex
