from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from latex_lang import (
    env_ast,
    ejecutar_linea,
    reset_environment,
    set_plot_mode,
)
from mtex_executor import ejecutar_mtex


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


def test_user_variable_does_not_permanently_shadow_core_builtin_after_reset():
    _run("sin = 3;")

    shadowed_output = _run(r"a = \sin(0);")
    assert "Error defining variable" in shadowed_output
    assert "a" not in env_ast

    reset_environment()

    _run(r"b = \sin(0);")
    assert env_ast["b"] == 0


def test_user_function_and_variable_name_collision_behaves_consistently():
    _run("x = 1;")
    _run("function y = x(t)")
    _run("y = t + 1;")
    _run("end")
    _run("fx = x(2);")
    assert float(env_ast["fx"]) == pytest.approx(3.0)

    _run("function y = f(t)")
    _run("y = t + 1;")
    _run("end")
    _run("f = 99;")
    variable_collision_output = _run("after_override = f(2);")

    assert "Error defining variable" in variable_collision_output
    assert "after_override" not in env_ast
    assert env_ast["f"] == 99


def test_multiple_document_runs_do_not_leak_last_plot(tmp_path: Path):
    first = _write_doc(
        tmp_path,
        "first.mtex",
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\codeblock\n"
        '\\plot([0,1],[0,1], name="uno");\n'
        "\\endcodeblock\n"
        "\\plot{last_plot}\n"
        "\\end{document}\n",
    )
    second = _write_doc(
        tmp_path,
        "second.mtex",
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\plot{last_plot}\n"
        "\\end{document}\n",
    )

    with patch("mtex_executor._run_pdflatex", side_effect=_successful_pdflatex()):
        ejecutar_mtex(str(first), env_ast, abrir_pdf=False, build_dir=tmp_path / "build_first")
        ejecutar_mtex(str(second), env_ast, abrir_pdf=False, build_dir=tmp_path / "build_second")

    second_tex = (tmp_path / "build_second" / "second.tex").read_text(encoding="utf-8")

    assert r"\textcolor{red}{[No se encontr" in second_tex
    assert r"last\_plot" in second_tex
    assert env_ast.get("last_plot") is None
    assert env_ast.get("_plot_files") in (None, {})
    assert env_ast.get("plots") in (None, [])


def test_failed_execution_does_not_leave_half_broken_user_state():
    failure_output = _run("a = 2 .^;")
    assert "Error defining variable" in failure_output
    assert "a" not in env_ast

    _run("b = 2 + 2;")
    assert env_ast["b"] == 4
