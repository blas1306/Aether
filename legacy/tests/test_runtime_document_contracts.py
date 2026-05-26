import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from latex_lang import (
    env_ast,
    ejecutar_linea,
    get_plot_mode,
    reset_environment,
    set_plot_mode,
    table as make_table,
)
from mtex_executor import ejecutar_mtex


def _run_lines(*lines: str) -> None:
    for line in lines:
        ejecutar_linea(line)


def _write_mtex(tmp_path: Path, filename: str, content: str) -> Path:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    return path


def _successful_pdflatex():
    class _Result:
        returncode = 0

    def _run(tex_filename: str, cwd: str, draftmode: bool = False, output_dir: str | None = None, synctex: bool = False):
        del synctex
        target_dir = Path(output_dir or cwd)
        target_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(tex_filename).stem
        (target_dir / f"{stem}.log").write_text("Compilation finished.\n", encoding="utf-8")
        if not draftmode:
            (target_dir / f"{stem}.pdf").write_bytes(b"%PDF-1.4\n%mock\n")
        return _Result()

    return _run


def _failing_pdflatex(log_text: str):
    class _Result:
        returncode = 1

    def _run(tex_filename: str, cwd: str, draftmode: bool = False, output_dir: str | None = None, synctex: bool = False):
        del draftmode, synctex
        target_dir = Path(output_dir or cwd)
        target_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(tex_filename).stem
        (target_dir / f"{stem}.log").write_text(log_text, encoding="utf-8")
        return _Result()

    return _run


def _failing_pdflatex_with_broken_pdf(log_text: str, broken_pdf: bytes = b"broken-pdf"):
    class _Result:
        returncode = 1

    def _run(tex_filename: str, cwd: str, draftmode: bool = False, output_dir: str | None = None, synctex: bool = False):
        del draftmode, synctex
        target_dir = Path(output_dir or cwd)
        target_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(tex_filename).stem
        (target_dir / f"{stem}.log").write_text(log_text, encoding="utf-8")
        (target_dir / f"{stem}.pdf").write_bytes(broken_pdf)
        return _Result()

    return _run


@pytest.fixture(autouse=True)
def _fresh_runtime():
    set_plot_mode("interactive")
    reset_environment()
    yield
    set_plot_mode("interactive")
    reset_environment()


def test_reset_environment_clears_user_variables():
    _run_lines(
        "x = 99;",
        "function y = inc(t)",
        "y = t + 1;",
        "end",
    )

    assert "x" in env_ast
    assert "inc" in env_ast

    reset_environment()

    assert "x" not in env_ast
    assert "inc" not in env_ast


def test_reset_environment_preserves_core_builtins_for_future_execution():
    _run_lines("x = 99;")

    reset_environment()
    ejecutar_linea(r"a = \sin(0);")

    assert env_ast["a"] == 0


def test_document_execution_does_not_leak_state_between_runs(tmp_path: Path):
    first_doc = _write_mtex(
        tmp_path,
        "first.mtex",
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\codeblock\n"
        "a = 7;\n"
        'T = table([1,2], name="tabla_uno", headers=["c1","c2"], booktabs=True);\n'
        "\\endcodeblock\n"
        "Valor: \\var{a}\n"
        "\\table{tabla_uno}\n"
        "\\end{document}\n",
    )
    second_doc = _write_mtex(
        tmp_path,
        "second.mtex",
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "Valor: \\var{a}\n"
        "\\table{tabla_uno}\n"
        "\\end{document}\n",
    )

    with patch("mtex_executor._run_pdflatex", side_effect=_successful_pdflatex()):
        ejecutar_mtex(str(first_doc), env_ast, abrir_pdf=False, build_dir=tmp_path / "build_first")
        ejecutar_mtex(str(second_doc), env_ast, abrir_pdf=False, build_dir=tmp_path / "build_second")

    second_tex = (tmp_path / "build_second" / "second.tex").read_text(encoding="utf-8")

    assert r"\textcolor{gray}{?a?}" in second_tex
    assert r"\textcolor{red}{[Table tabla\_uno not found]}" in second_tex
    assert r"\begin{tabular}" not in second_tex
    assert not env_ast.get("_table_blocks")


def test_table_creation_registers_generated_table_id_and_last_table():
    first_id = make_table([[1, 2]])
    second_id = make_table([[3, 4]])

    assert first_id == "table1"
    assert second_id == "table2"
    assert env_ast["last_table"] == "table2"
    assert set(env_ast["_table_blocks"]) == {"table1", "table2"}


def test_table_placeholder_is_replaced_in_document_and_adds_booktabs_package(tmp_path: Path):
    source = _write_mtex(
        tmp_path,
        "table_doc.mtex",
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\codeblock\n"
        'T = table([1,2], name="tabla_doc", headers=["a","b"], booktabs=True);\n'
        "\\endcodeblock\n"
        "\\table{tabla_doc}\n"
        "\\end{document}\n",
    )

    with patch("mtex_executor._run_pdflatex", side_effect=_successful_pdflatex()):
        ejecutar_mtex(str(source), env_ast, abrir_pdf=False, build_dir=tmp_path / "build")

    generated_tex = (tmp_path / "build" / "table_doc.tex").read_text(encoding="utf-8")

    assert r"\table{tabla_doc}" not in generated_tex
    assert r"\begin{tabular}{cc}" in generated_tex
    assert r"\toprule" in generated_tex
    assert r"\usepackage{booktabs}" in generated_tex


def test_matrix_placeholders_do_not_auto_add_amsmath_package(tmp_path: Path):
    source = _write_mtex(
        tmp_path,
        "matrix_doc.mtex",
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\codeblock\n"
        "A = [1, 2; 3, 4];\n"
        "b = [5; 6];\n"
        "x = A | b;\n"
        "\\endcodeblock\n"
        "\\var{A}\n"
        "\\var{b}\n"
        "\\var{x}\n"
        "\\end{document}\n",
    )

    with patch("mtex_executor._run_pdflatex", side_effect=_successful_pdflatex()):
        ejecutar_mtex(str(source), env_ast, abrir_pdf=False, build_dir=tmp_path / "build")

    generated_tex = (tmp_path / "build" / "matrix_doc.tex").read_text(encoding="utf-8")

    assert r"\begin{matrix}" in generated_tex
    assert r"\usepackage{amsmath}" not in generated_tex


def test_expr_placeholder_evaluates_codeblock_functions_and_vectors(tmp_path: Path):
    source = _write_mtex(
        tmp_path,
        "expr_doc.mtex",
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\codeblock\n"
        "f1(x) = x^2;\n"
        "b = [5; 6];\n"
        "\\endcodeblock\n"
        "E=\\expr{f1(2) + b(1)}\n"
        "\\end{document}\n",
    )

    with patch("mtex_executor._run_pdflatex", side_effect=_successful_pdflatex()):
        ejecutar_mtex(str(source), env_ast, abrir_pdf=False, build_dir=tmp_path / "build")

    generated_tex = (tmp_path / "build" / "expr_doc.tex").read_text(encoding="utf-8")

    assert "E=9" in generated_tex


def test_mtex_build_failure_reports_error_cleanly(tmp_path: Path):
    source = _write_mtex(
        tmp_path,
        "fail_doc.mtex",
        "\\documentclass{article}\n\\begin{document}\nHola\n\\end{document}\n",
    )
    build_dir = tmp_path / "build"
    output = io.StringIO()

    with patch("mtex_executor._run_pdflatex", side_effect=_failing_pdflatex("! Undefined control sequence\n")), redirect_stdout(output):
        result = ejecutar_mtex(str(source), env_ast, abrir_pdf=False, build_dir=build_dir)

    assert result is None
    stdout_text = output.getvalue()
    assert "Build error [latex-compilation-failed]: LaTeX compilation failed." in stdout_text
    assert "Snippet: ! Undefined control sequence" in stdout_text
    assert "Hint: Check compile.log for the full compiler output." in stdout_text
    assert not (build_dir / "fail_doc.pdf").exists()
    assert (build_dir / "compile.log").exists()
    assert "Undefined control sequence" in (build_dir / "compile.log").read_text(encoding="utf-8")


def test_mtex_build_failure_keeps_previous_pdf_if_policy_requires_it(tmp_path: Path):
    source = _write_mtex(
        tmp_path,
        "keep_pdf.mtex",
        "\\documentclass{article}\n\\begin{document}\nHola\n\\end{document}\n",
    )
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    previous_pdf = build_dir / "keep_pdf.pdf"
    previous_bytes = b"%PDF-1.4\n%previous\n"
    previous_pdf.write_bytes(previous_bytes)

    with patch("mtex_executor._run_pdflatex", side_effect=_failing_pdflatex("! Missing $ inserted.\n")):
        result = ejecutar_mtex(str(source), env_ast, abrir_pdf=False, build_dir=build_dir)

    assert result is None
    assert previous_pdf.read_bytes() == previous_bytes


def test_mtex_build_failure_restores_previous_pdf_if_failed_run_overwrites_it(tmp_path: Path):
    source = _write_mtex(
        tmp_path,
        "restore_pdf.mtex",
        "\\documentclass{article}\n\\begin{document}\nHola\n\\end{document}\n",
    )
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    previous_pdf = build_dir / "restore_pdf.pdf"
    previous_bytes = b"%PDF-1.4\n%stable\n"
    previous_pdf.write_bytes(previous_bytes)

    with patch(
        "mtex_executor._run_pdflatex",
        side_effect=_failing_pdflatex_with_broken_pdf("! Missing $ inserted.\n", broken_pdf=b"%PDF-1.4\n%broken\n"),
    ):
        result = ejecutar_mtex(str(source), env_ast, abrir_pdf=False, build_dir=build_dir)

    assert result is None
    assert previous_pdf.read_bytes() == previous_bytes


def test_document_execution_continues_after_runtime_error_in_one_statement(tmp_path: Path):
    source = _write_mtex(
        tmp_path,
        "recover_doc.mtex",
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\codeblock\n"
        "a = 1;\n"
        "bad = foo + 1;\n"
        "b = a + 1;\n"
        "\\endcodeblock\n"
        "A=\\var{a}\n"
        "B=\\var{b}\n"
        "\\end{document}\n",
    )

    output = io.StringIO()
    with patch("mtex_executor._run_pdflatex", side_effect=_successful_pdflatex()), redirect_stdout(output):
        ejecutar_mtex(str(source), env_ast, abrir_pdf=False, build_dir=tmp_path / "build")

    generated_tex = (tmp_path / "build" / "recover_doc.tex").read_text(encoding="utf-8")

    assert "Variable foo is not defined." in output.getvalue()
    assert "A=1" in generated_tex
    assert "B=2" in generated_tex


def test_empty_and_comment_only_code_blocks_do_not_emit_runtime_errors(tmp_path: Path):
    source = _write_mtex(
        tmp_path,
        "comments_only.mtex",
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\codeblock\n"
        "\n"
        "% comentario\n"
        "# another comment\n"
        "\\endcodeblock\n"
        "Texto estable\n"
        "\\end{document}\n",
    )

    with patch("mtex_executor._run_pdflatex", side_effect=_successful_pdflatex()):
        ejecutar_mtex(str(source), env_ast, abrir_pdf=False, build_dir=tmp_path / "build")

    generated_tex = (tmp_path / "build" / "comments_only.tex").read_text(encoding="utf-8")

    assert "Texto estable" in generated_tex
    assert "Runtime error" not in generated_tex


def test_compile_exception_still_writes_compile_log(tmp_path: Path):
    source = _write_mtex(
        tmp_path,
        "missing_pdflatex.mtex",
        "\\documentclass{article}\n\\begin{document}\nHola\n\\end{document}\n",
    )
    build_dir = tmp_path / "build"

    with patch("mtex_executor._run_pdflatex", side_effect=FileNotFoundError("pdflatex not found")):
        result = ejecutar_mtex(str(source), env_ast, abrir_pdf=False, build_dir=build_dir)

    assert result is None
    compile_log = (build_dir / "compile.log").read_text(encoding="utf-8")
    assert "pdflatex not found" in compile_log


def test_document_execution_restores_previous_plot_mode(tmp_path: Path):
    source = _write_mtex(
        tmp_path,
        "mode_doc.mtex",
        "\\documentclass{article}\n\\begin{document}\nHola\n\\end{document}\n",
    )
    set_plot_mode("interactive")

    with patch("mtex_executor._run_pdflatex", side_effect=_successful_pdflatex()):
        ejecutar_mtex(str(source), env_ast, abrir_pdf=False, build_dir=tmp_path / "build")

    assert get_plot_mode() == "interactive"
