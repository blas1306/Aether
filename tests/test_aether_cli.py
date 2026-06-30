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


def test_default_backend_is_ast_for_file_execution(tmp_path: Path) -> None:
    program = tmp_path / "default_ast.ae"
    program.write_text('println("ast");\n', encoding="utf-8")

    exit_code, stdout, stderr = run_cli([str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == "ast\n"
    assert stderr == ""


def test_backend_ast_matches_default_file_execution(tmp_path: Path) -> None:
    program = tmp_path / "backend_ast.ae"
    program.write_text('println("ast");\n', encoding="utf-8")

    default_exit, default_stdout, default_stderr = run_cli([str(program)])
    ast_exit, ast_stdout, ast_stderr = run_cli(["--backend=ast", str(program)])

    assert (ast_exit, ast_stdout, ast_stderr) == (
        default_exit,
        default_stdout,
        default_stderr,
    )


def test_backend_ir_executes_supported_subset(tmp_path: Path) -> None:
    program = tmp_path / "backend_ir.ae"
    program.write_text(
        """
int add(int a, int b) {
    return a + b;
}

int main() {
    return add(2, 3);
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--backend=ir", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == ""
    assert stderr == ""


def test_invalid_backend_reports_clear_usage_error(tmp_path: Path) -> None:
    program = tmp_path / "invalid_backend.ae"
    program.write_text('println("not reached");\n', encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--backend=wat", str(program)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "invalid choice" in stderr
    assert "wat" in stderr


def test_backend_ir_unsupported_feature_reports_without_traceback(tmp_path: Path) -> None:
    program = tmp_path / "unsupported_ir.ae"
    program.write_text("class Counter { int value; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--backend=ir", str(program)])

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert "IR backend does not support class declarations yet." in stderr
    assert "Supported IR backend subset:" in stderr
    assert "Traceback" not in stderr


def test_repl_rejects_ir_backend_for_now() -> None:
    exit_code, stdout, stderr = run_cli(["--backend=ir", "--repl"])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "--repl only supports --backend=ast" in stderr


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
    assert "--backend" in stdout
    assert "--emit-ir" in stdout
    assert "--opt" in stdout
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


def test_emit_ir_prints_verified_ir(tmp_path: Path) -> None:
    program = tmp_path / "emit_ir.ae"
    program.write_text(
        """
int add(int a, int b) {
    return a + b;
}

int main() {
    return add(2, 3);
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-ir", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "func @add" in stdout
    assert "func @main" in stdout
    assert "call @add" in stdout
    assert stderr == ""


def test_emit_ir_without_opt_preserves_unoptimized_ir(tmp_path: Path) -> None:
    program = tmp_path / "unoptimized_ir.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-ir", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "%3: int = mul %1, %2" in stdout
    assert "%4: int = add %0, %3" in stdout
    assert "%4: int = const 14" not in stdout
    assert stderr == ""


def test_emit_ir_with_opt_shows_constant_folding(tmp_path: Path) -> None:
    program = tmp_path / "optimized_ir.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-ir", "--opt", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "%3: int = const 12" in stdout
    assert "%4: int = const 14" in stdout
    assert " = mul " not in stdout
    assert " = add " not in stdout
    assert stderr == ""


def test_opt_before_emit_ir_also_shows_constant_folding(tmp_path: Path) -> None:
    program = tmp_path / "opt_before_emit_ir.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--opt", "--emit-ir", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "%4: int = const 14" in stdout
    assert " = mul " not in stdout
    assert " = add " not in stdout
    assert stderr == ""


def test_opt_without_emit_ir_reports_clear_usage_error(tmp_path: Path) -> None:
    program = tmp_path / "opt_without_emit_ir.ae"
    program.write_text(
        """
int main() {
    return 14;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--opt", str(program)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "--opt is currently only supported with --emit-ir." in stderr


def test_backend_ir_does_not_run_optimizer_yet(tmp_path: Path, monkeypatch) -> None:
    program = tmp_path / "backend_ir_unoptimized.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )
    calls = []

    def fail_if_called(self, module):
        calls.append(module)
        raise AssertionError("optimizer should not run for --backend=ir")

    monkeypatch.setattr(
        "aether.ir.optimizer.pipeline.OptimizerPipeline.run",
        fail_if_called,
    )

    exit_code, stdout, stderr = run_cli(["--backend=ir", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == ""
    assert stderr == ""
    assert calls == []


def test_default_ast_backend_still_executes_without_optimizer(tmp_path: Path) -> None:
    program = tmp_path / "default_ast_after_opt_flag.ae"
    program.write_text("value = 2 + 3 * 4; println(value);\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli([str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == "14\n"
    assert stderr == ""


def test_backend_ir_with_emit_ir_prints_ir_without_execution(tmp_path: Path) -> None:
    program = tmp_path / "backend_emit_ir.ae"
    program.write_text(
        """
int main() {
    return 42;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--backend=ir", "--emit-ir", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "func @main" in stdout
    assert stderr == ""


def test_emit_ir_unsupported_feature_reports_clear_error(tmp_path: Path) -> None:
    program = tmp_path / "emit_ir_unsupported.ae"
    program.write_text("class Counter { int value; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--emit-ir", str(program)])

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert "IR backend does not support class declarations yet." in stderr
    assert "Traceback" not in stderr


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
