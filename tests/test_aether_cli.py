from __future__ import annotations

from io import StringIO
from pathlib import Path

from aether.cli import EXIT_LANGUAGE_ERROR, EXIT_SUCCESS, EXIT_USAGE_ERROR, main


def run_cli(
    argv: list[str],
    *,
    stdin_text: str = "",
) -> tuple[int, str, str]:
    stdin = StringIO(stdin_text)
    stdout = StringIO()
    stderr = StringIO()
    exit_code = main(argv, stdin=stdin, stdout=stdout, stderr=stderr)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_executes_valid_file(tmp_path: Path) -> None:
    program = tmp_path / "hello.ae"
    program.write_text('println("hello");\n', encoding="utf-8")

    exit_code, stdout, stderr = run_cli([str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == "hello\n"
    assert stderr == ""


def test_missing_file_reports_read_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.ae"

    exit_code, stdout, stderr = run_cli([str(missing)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "aether: cannot read" in stderr
    assert str(missing) in stderr


def test_help_describes_direct_execution_and_tools() -> None:
    exit_code, stdout, stderr = run_cli(["--help"])

    assert exit_code == EXIT_SUCCESS
    assert "usage: aether" in stdout
    assert "aether program.ae" in stdout
    assert "--repl" in stdout
    assert "--tokens" in stdout
    assert "--ast" in stdout
    assert stderr == ""


def test_version_reports_language_version() -> None:
    exit_code, stdout, stderr = run_cli(["--version"])

    assert exit_code == EXIT_SUCCESS
    assert stdout == "Aether v0\n"
    assert stderr == ""


def test_tokens_prints_lexer_output(tmp_path: Path) -> None:
    program = tmp_path / "tokens.ae"
    program.write_text("x = 42;\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--tokens", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "1:1 IDENTIFIER 'x'" in stdout
    assert "1:5 INT_LITERAL '42' literal=42" in stdout
    assert "EOF ''" in stdout
    assert stderr == ""


def test_ast_prints_parsed_program(tmp_path: Path) -> None:
    program = tmp_path / "ast.ae"
    program.write_text("int x = 42;\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--ast", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout.startswith("Program(")
    assert "VarDeclaration(" in stdout
    assert "name='x'" in stdout
    assert stderr == ""


def test_repl_uses_persistent_session() -> None:
    exit_code, stdout, stderr = run_cli(
        ["--repl"],
        stdin_text="x = 5;\nprintln(x);\n\\exit\n",
    )

    assert exit_code == EXIT_SUCCESS
    assert "Aether v0 REPL" in stdout
    assert "5\n" in stdout
    assert stdout.count("aether> ") == 3
    assert stderr == ""


def test_typechecker_error_is_reported_without_execution(tmp_path: Path) -> None:
    program = tmp_path / "type_error.ae"
    program.write_text('int x = "wrong";\nprintln("not reached");\n', encoding="utf-8")

    exit_code, stdout, stderr = run_cli([str(program)])

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert "AetherTypeError" in stderr
    assert "not reached" not in stdout
