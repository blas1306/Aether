from __future__ import annotations

from io import StringIO
from pathlib import Path

from aether.cli import EXIT_LANGUAGE_ERROR, EXIT_SUCCESS, EXIT_USAGE_ERROR, main


DEFAULT_OPTIMIZER_PASSES = [
    "ConstantFolder",
    "LocalConstantPropagator",
    "ConstantFolder",
    "AlgebraicSimplifier",
    "DeadCodeEliminator",
    "DeadStoreEliminator",
    "DeadCodeEliminator",
]


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


def _trace_titles(stdout: str) -> list[str]:
    return [
        line.removeprefix("=== ").removesuffix(" ===")
        for line in stdout.splitlines()
        if line.startswith("=== ") and line.endswith(" ===")
    ]


def _trace_header(stdout: str, title: str) -> str:
    for line in stdout.splitlines():
        if not line.startswith("=== ") or not line.endswith(" ==="):
            continue
        trace_title = line.removeprefix("=== ").removesuffix(" ===")
        if trace_title == title or trace_title.startswith(f"{title} ["):
            return line
    raise AssertionError(f"trace section not found: {title}")


def _trace_section(stdout: str, title: str) -> str:
    marker = _trace_header(stdout, title)
    title_start = stdout.index(marker)
    content_start = stdout.index("\n\n", title_start) + 2
    next_section = stdout.find("\n========================================\n===", content_start)
    if next_section == -1:
        return stdout[content_start:].strip()
    return stdout[content_start:next_section].strip()


def _iteration_titles(iteration: int) -> list[str]:
    stats_by_pass = [
        ("folded", 0),
        ("propagated", 0),
        ("folded", 0),
        ("simplified", 0),
        ("removed", 0),
        ("removed_stores", 0),
        ("removed", 0),
    ]
    return [
        f"Iteration {iteration} / After {pass_name} [no changes, {stat}={value}]"
        for pass_name, (stat, value) in zip(
            DEFAULT_OPTIMIZER_PASSES,
            stats_by_pass,
        )
    ]


def _changed_constant_folding_iteration_titles() -> list[str]:
    return [
        "Iteration 1 / After ConstantFolder [changed, folded=2]",
        "Iteration 1 / After LocalConstantPropagator [no changes, propagated=0]",
        "Iteration 1 / After ConstantFolder [no changes, folded=0]",
        "Iteration 1 / After AlgebraicSimplifier [no changes, simplified=0]",
        "Iteration 1 / After DeadCodeEliminator [changed, removed=4]",
        "Iteration 1 / After DeadStoreEliminator [no changes, removed_stores=0]",
        "Iteration 1 / After DeadCodeEliminator [no changes, removed=0]",
    ]


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
    assert "--opt-level" in stdout
    assert "--show-passes" in stdout
    assert "bench" in stdout
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


def test_emit_ir_o0_preserves_unoptimized_ir(tmp_path: Path) -> None:
    program = tmp_path / "o0_ir.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )

    default_exit, default_stdout, default_stderr = run_cli(["--emit-ir", str(program)])
    o0_exit, o0_stdout, o0_stderr = run_cli(["--emit-ir", "-O0", str(program)])

    assert (o0_exit, o0_stdout, o0_stderr) == (
        default_exit,
        default_stdout,
        default_stderr,
    )
    assert "%3: int = mul %1, %2" in o0_stdout
    assert "%4: int = add %0, %3" in o0_stdout
    assert "%4: int = const 14" not in o0_stdout


def test_emit_ir_with_opt_shows_constant_folding_and_dead_code_elimination(
    tmp_path: Path,
) -> None:
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
    assert "%4: int = const 14" in stdout
    assert "%3: int = const 12" not in stdout
    assert " = mul " not in stdout
    assert " = add " not in stdout
    assert stderr == ""


def test_emit_ir_o1_shows_constant_folding_and_dead_code_elimination(
    tmp_path: Path,
) -> None:
    program = tmp_path / "o1_ir.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-ir", "-O1", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "%4: int = const 14" in stdout
    assert " = mul " not in stdout
    assert " = add " not in stdout
    assert stderr == ""


def test_emit_ir_o2_aliases_o1_for_now(tmp_path: Path) -> None:
    program = tmp_path / "o2_alias_ir.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )

    o1_exit, o1_stdout, o1_stderr = run_cli(["--emit-ir", "-O1", str(program)])
    o2_exit, o2_stdout, o2_stderr = run_cli(["--emit-ir", "-O2", str(program)])

    assert (o2_exit, o2_stdout, o2_stderr) == (o1_exit, o1_stdout, o1_stderr)


def test_emit_ir_opt_is_equivalent_to_o1(tmp_path: Path) -> None:
    program = tmp_path / "opt_equals_o1_ir.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )

    opt_exit, opt_stdout, opt_stderr = run_cli(["--emit-ir", "--opt", str(program)])
    o1_exit, o1_stdout, o1_stderr = run_cli(["--emit-ir", "-O1", str(program)])

    assert (opt_exit, opt_stdout, opt_stderr) == (o1_exit, o1_stdout, o1_stderr)


def test_emit_ir_with_opt_normal_output_does_not_show_pass_trace(tmp_path: Path) -> None:
    program = tmp_path / "optimized_ir_without_trace.ae"
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
    assert "=== Lowered IR ===" not in stdout
    assert "=== After ConstantFolder ===" not in stdout
    assert "folded=" not in stdout
    assert "%4: int = const 14" in stdout
    assert stderr == ""


def test_emit_ir_with_opt_show_passes_prints_all_pipeline_stages(
    tmp_path: Path,
) -> None:
    program = tmp_path / "optimized_ir_trace.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(
        ["--emit-ir", "--opt", "--show-passes", str(program)]
    )

    assert exit_code == EXIT_SUCCESS
    assert _trace_titles(stdout) == [
        "Lowered IR",
        *_changed_constant_folding_iteration_titles(),
        *_iteration_titles(2),
        "Final IR",
    ]
    assert stdout.count("========================================") == 32
    assert stderr == ""


def test_emit_ir_o0_show_passes_prints_only_lowered_and_final_ir(
    tmp_path: Path,
) -> None:
    program = tmp_path / "o0_ir_trace.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(
        ["--emit-ir", "-O0", "--show-passes", str(program)]
    )

    assert exit_code == EXIT_SUCCESS
    assert _trace_titles(stdout) == ["Lowered IR", "Final IR"]
    assert _trace_section(stdout, "Lowered IR") == _trace_section(stdout, "Final IR")
    assert "After ConstantFolder" not in stdout
    assert stderr == ""


def test_emit_ir_o1_show_passes_prints_optimizer_stages(
    tmp_path: Path,
) -> None:
    program = tmp_path / "o1_ir_trace.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(
        ["--emit-ir", "-O1", "--show-passes", str(program)]
    )

    assert exit_code == EXIT_SUCCESS
    assert _trace_titles(stdout) == [
        "Lowered IR",
        *_changed_constant_folding_iteration_titles(),
        *_iteration_titles(2),
        "Final IR",
    ]
    assert stderr == ""


def test_emit_ir_with_opt_show_passes_shows_unchanged_pipeline_stages(
    tmp_path: Path,
) -> None:
    program = tmp_path / "unchanged_ir_trace.ae"
    program.write_text(
        """
int addOne(int value) {
    return value + 1;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(
        ["--emit-ir", "--opt", "--show-passes", str(program)]
    )

    assert exit_code == EXIT_SUCCESS
    assert _trace_titles(stdout) == [
        "Lowered IR",
        *_iteration_titles(1),
        "Final IR",
    ]
    assert _trace_section(stdout, "Lowered IR") == _trace_section(stdout, "Final IR")
    assert stderr == ""


def test_emit_ir_with_opt_show_passes_shows_changed_ir(tmp_path: Path) -> None:
    program = tmp_path / "changed_ir_trace.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(
        ["--emit-ir", "--opt", "--show-passes", str(program)]
    )

    lowered = _trace_section(stdout, "Lowered IR")
    final = _trace_section(stdout, "Final IR")
    assert exit_code == EXIT_SUCCESS
    assert lowered != final
    assert " = mul " in lowered
    assert " = add " in lowered
    assert "%4: int = const 14" in final
    assert " = mul " not in final
    assert " = add " not in final
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


def test_emit_ir_with_opt_shows_algebraic_simplification(tmp_path: Path) -> None:
    program = tmp_path / "algebraic_simplification_ir.ae"
    program.write_text(
        """
int identity(int value) {
    return value + 0;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-ir", "--opt", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "return %value" in stdout
    assert " = add " not in stdout
    assert "const 0" not in stdout
    assert stderr == ""


def test_emit_ir_with_opt_shows_local_constant_propagation(tmp_path: Path) -> None:
    program = tmp_path / "local_constant_propagation_ir.ae"
    program.write_text(
        """
int main() {
    int x = 5;
    return x;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-ir", "--opt", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "%1: int = const 5" in stdout
    assert "store %x, %0" not in stdout
    assert "load %x" not in stdout
    assert stderr == ""


def test_emit_ir_with_opt_keeps_local_const_example_output_correct() -> None:
    exit_code, stdout, stderr = run_cli(
        ["--emit-ir", "--opt", "examples/ir/local_const.ae"]
    )

    assert exit_code == EXIT_SUCCESS
    assert stdout.strip() == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %3: int = const 8\n"
        "    return %3\n"
        "}"
    )
    assert stderr == ""


def test_emit_ir_with_opt_show_passes_shows_dead_store_elimination(
    tmp_path: Path,
) -> None:
    program = tmp_path / "dead_store_elimination_ir.ae"
    program.write_text(
        """
int main() {
    int x = 5;
    return x + 3;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(
        ["--emit-ir", "--opt", "--show-passes", str(program)]
    )

    before_dse = _trace_section(stdout, "Iteration 1 / After DeadCodeEliminator")
    after_dse = _trace_section(stdout, "Iteration 1 / After DeadStoreEliminator")
    final = _trace_section(stdout, "Final IR")
    assert exit_code == EXIT_SUCCESS
    assert "store %x, %0" in before_dse
    assert "store %x, %0" not in after_dse
    assert final == (
        "func @main() -> int {\n"
        "entry:\n"
        "    %3: int = const 8\n"
        "    return %3\n"
        "}"
    )
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


def test_o_flag_without_emit_ir_reports_clear_usage_error(tmp_path: Path) -> None:
    program = tmp_path / "o_without_emit_ir.ae"
    program.write_text(
        """
int main() {
    return 14;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["-O1", str(program)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "-O flags are currently only supported with --emit-ir." in stderr


def test_opt_level_long_form_is_supported(tmp_path: Path) -> None:
    program = tmp_path / "opt_level_long_form.ae"
    program.write_text(
        """
int main() {
    return 2 + 3 * 4;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-ir", "--opt-level=1", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "%4: int = const 14" in stdout
    assert " = mul " not in stdout
    assert " = add " not in stdout
    assert stderr == ""


def test_show_passes_without_emit_ir_and_opt_reports_clear_usage_error(
    tmp_path: Path,
) -> None:
    program = tmp_path / "show_passes_without_flags.ae"
    program.write_text(
        """
int main() {
    return 14;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--show-passes", str(program)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "--show-passes requires --emit-ir --opt." in stderr


def test_show_passes_with_emit_ir_but_without_opt_reports_clear_usage_error(
    tmp_path: Path,
) -> None:
    program = tmp_path / "show_passes_without_opt.ae"
    program.write_text(
        """
int main() {
    return 14;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-ir", "--show-passes", str(program)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "--show-passes requires --emit-ir --opt." in stderr


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


def test_bench_sum_to_default_both_backends() -> None:
    exit_code, stdout, stderr = run_cli(["bench", "benchmarks/sum_to.ae"])

    assert exit_code == EXIT_SUCCESS
    assert "Benchmark: benchmarks/sum_to.ae" in stdout
    assert "Iterations: 10" in stdout
    assert "AST backend:" in stdout
    assert "IR backend:" in stdout
    assert "IR O1 optimizer (not executed):" in stdout
    assert stdout.count("  total: ") == 3
    assert stdout.count("  avg: ") == 3
    assert stderr == ""


def test_bench_accepts_iteration_count() -> None:
    exit_code, stdout, stderr = run_cli(
        ["bench", "benchmarks/sum_to.ae", "--iterations", "2"]
    )

    assert exit_code == EXIT_SUCCESS
    assert "Iterations: 2" in stdout
    assert "AST backend:" in stdout
    assert "IR backend:" in stdout
    assert stderr == ""


def test_bench_backend_ast_only() -> None:
    exit_code, stdout, stderr = run_cli(
        ["bench", "benchmarks/sum_to.ae", "--backend", "ast"]
    )

    assert exit_code == EXIT_SUCCESS
    assert "AST backend:" in stdout
    assert "IR backend:" not in stdout
    assert "IR O1 optimizer" not in stdout
    assert stderr == ""


def test_bench_backend_ir_only() -> None:
    exit_code, stdout, stderr = run_cli(
        ["bench", "benchmarks/sum_to.ae", "--backend", "ir"]
    )

    assert exit_code == EXIT_SUCCESS
    assert "AST backend:" not in stdout
    assert "IR backend:" in stdout
    assert "IR O1 optimizer (not executed):" in stdout
    assert stderr == ""


def test_bench_backend_both_explicit() -> None:
    exit_code, stdout, stderr = run_cli(
        ["bench", "benchmarks/sum_to.ae", "--backend", "both"]
    )

    assert exit_code == EXIT_SUCCESS
    assert "AST backend:" in stdout
    assert "IR backend:" in stdout
    assert "IR O1 optimizer (not executed):" in stdout
    assert stderr == ""


def test_bench_invalid_backend_reports_usage_error() -> None:
    exit_code, stdout, stderr = run_cli(
        ["bench", "benchmarks/sum_to.ae", "--backend", "wat"]
    )

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "invalid choice" in stderr
    assert "wat" in stderr


def test_bench_missing_file_reports_read_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.ae"

    exit_code, stdout, stderr = run_cli(["bench", str(missing)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "aether: cannot read" in stderr
    assert str(missing) in stderr


def test_bench_both_reports_ir_error_and_keeps_ast(tmp_path: Path) -> None:
    program = tmp_path / "ast_only.ae"
    program.write_text('println("ast still runs");\n', encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["bench", str(program), "--backend", "both"])

    assert exit_code == EXIT_SUCCESS
    assert f"Benchmark: {program}" in stdout
    assert "AST backend:" in stdout
    assert "IR backend:" in stdout
    assert "error:" in stdout
    assert "IR backend does not support" in stdout
    assert "Supported IR backend subset:" in stdout
    assert "Traceback" not in stdout
    assert stderr == ""


def test_bench_ir_only_unsupported_program_fails(tmp_path: Path) -> None:
    program = tmp_path / "ast_only_ir_fail.ae"
    program.write_text('println("unsupported");\n', encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["bench", str(program), "--backend", "ir"])

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert "Benchmark:" in stdout
    assert "IR backend:" in stdout
    assert "error:" in stdout
    assert "IR backend does not support" in stdout
    assert stderr == ""


def test_bench_does_not_break_existing_cli_execution(tmp_path: Path) -> None:
    program = tmp_path / "normal_cli_after_bench.ae"
    program.write_text('println("normal");\n', encoding="utf-8")

    exit_code, stdout, stderr = run_cli([str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == "normal\n"
    assert stderr == ""
