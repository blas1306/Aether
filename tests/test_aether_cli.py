from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

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


def fake_native_toolchain(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    stdout_bytes: bytes = b"",
    stderr_bytes: bytes = b"",
) -> tuple[list[list[str]], list[list[str]]]:
    clang_commands: list[list[str]] = []
    program_commands: list[list[str]] = []

    monkeypatch.setattr(
        "aether.backend.llvm.build.shutil.which",
        lambda _name: "/usr/bin/clang",
    )

    def fake_subprocess_run(command, **_kwargs):
        if command[0] != "/usr/bin/clang":
            program_commands.append(command)
            return subprocess.CompletedProcess(
                command,
                returncode,
                stdout_bytes,
                stderr_bytes,
            )
        clang_commands.append(command)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(
        "aether.backend.llvm.build.subprocess.run",
        fake_subprocess_run,
    )
    return clang_commands, program_commands


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


def test_executes_valid_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    program = tmp_path / "return_0.ae"
    program.write_text("int main() { return 0; }\n", encoding="utf-8")
    fake_native_toolchain(monkeypatch, returncode=0)

    exit_code, stdout, stderr = run_cli([str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == ""
    assert stderr == ""


def test_default_backend_runs_with_llvm_and_propagates_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "return_5.ae"
    program.write_text("int main() { return 5; }\n", encoding="utf-8")
    fake_native_toolchain(monkeypatch, returncode=5)

    exit_code, stdout, stderr = run_cli([str(program)])

    assert exit_code == 5
    assert stdout == ""
    assert stderr == ""


def test_backend_ast_remains_explicit_file_execution(tmp_path: Path) -> None:
    program = tmp_path / "backend_ast.ae"
    program.write_text('println("ast");\n', encoding="utf-8")

    ast_exit, ast_stdout, ast_stderr = run_cli(["--backend=ast", str(program)])

    assert ast_exit == EXIT_SUCCESS
    assert ast_stdout == "ast\n"
    assert ast_stderr == ""


def test_default_llvm_execution_preserves_program_stdout_and_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "stdio.ae"
    program.write_text("int main() { return 0; }\n", encoding="utf-8")
    fake_native_toolchain(
        monkeypatch,
        returncode=0,
        stdout_bytes=b"program stdout\n",
        stderr_bytes=b"program stderr\n",
    )

    exit_code, stdout, stderr = run_cli([str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == "program stdout\n"
    assert stderr == "program stderr\n"


def test_default_llvm_execution_reports_missing_clang_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "no_clang.ae"
    program.write_text("int main() { return 0; }\n", encoding="utf-8")
    monkeypatch.setattr("aether.backend.llvm.build.shutil.which", lambda _name: None)

    exit_code, stdout, stderr = run_cli([str(program)])

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert "clang is required to build native executables." in stderr
    assert "Traceback" not in stderr


def test_default_llvm_execution_removes_temporaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "temporaries.ae"
    program.write_text("int main() { return 5; }\n", encoding="utf-8")
    clang_commands, program_commands = fake_native_toolchain(
        monkeypatch,
        returncode=5,
    )

    exit_code, stdout, stderr = run_cli([str(program)])

    llvm_path = Path(clang_commands[0][1])
    executable_path = Path(program_commands[0][0])
    assert exit_code == 5
    assert stdout == ""
    assert stderr == ""
    assert not llvm_path.exists()
    assert not executable_path.exists()
    assert not executable_path.parent.exists()


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
    assert "llvm (default)" in stdout
    assert "--emit-ir" in stdout
    assert "--emit-cfg" in stdout
    assert "--emit-ssa" in stdout
    assert "--emit-llvm" in stdout
    assert "--ssa-builder" in stdout
    assert "general (default)" in stdout
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


def test_emit_ssa_prints_linear_function(tmp_path: Path) -> None:
    program = tmp_path / "emit_ssa_linear.ae"
    program.write_text(
        """
int add(int a, int b) {
    return a + b;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-ssa", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == (
        "func @add(%a: int, %b: int) -> int {\n"
        "entry:\n"
        "    %0: int = add %a, %b\n"
        "    return %0\n"
        "}\n"
    )
    assert stderr == ""


def test_emit_ssa_prints_simple_if_else_with_phi(tmp_path: Path) -> None:
    program = tmp_path / "emit_ssa_phi.ae"
    program.write_text(
        """
int f(int x) {
    int y = 0;
    if x > 0 {
        y = 1;
    } else {
        y = 2;
    }
    return y;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-ssa", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == (
        "func @f(%x: int) -> int {\n"
        "entry:\n"
        "    %0: int = const 0\n"
        "    %1: int = const 0\n"
        "    %2: bool = cmp_gt %x, %1\n"
        "    branch %2, then0, else0\n"
        "\n"
        "then0:\n"
        "    %3: int = const 1\n"
        "    jump merge0\n"
        "\n"
        "else0:\n"
        "    %4: int = const 2\n"
        "    jump merge0\n"
        "\n"
        "merge0:\n"
        "    %5: int = phi(then0: %3, else0: %4)\n"
        "    return %5\n"
        "}\n"
    )
    assert stderr == ""


def test_emit_ssa_prints_simple_while_with_phi(tmp_path: Path) -> None:
    program = tmp_path / "emit_ssa_while.ae"
    program.write_text(
        """
int sumTo(int n) {
    int i = 0;
    int sum = 0;
    while i <= n {
        sum = sum + i;
        i = i + 1;
    }
    return sum;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-ssa", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == (
        "func @sumTo(%n: int) -> int {\n"
        "entry:\n"
        "    %0: int = const 0\n"
        "    %1: int = const 0\n"
        "    jump cond0\n"
        "\n"
        "cond0:\n"
        "    %2: int = phi(entry: %0, body0: %9)\n"
        "    %cond0.sum.phi: int = phi(entry: %1, body0: %6)\n"
        "    %3: bool = cmp_le %2, %n\n"
        "    branch %3, body0, exit0\n"
        "\n"
        "body0:\n"
        "    %6: int = add %cond0.sum.phi, %2\n"
        "    %8: int = const 1\n"
        "    %9: int = add %2, %8\n"
        "    jump cond0\n"
        "\n"
        "exit0:\n"
        "    return %cond0.sum.phi\n"
        "}\n"
    )
    assert stderr == ""


def test_emit_ssa_without_selector_uses_general_builder(tmp_path: Path) -> None:
    program = tmp_path / "emit_ssa_default_general.ae"
    program.write_text(
        """
int nested(int x, int y) {
    int z = 0;
    if x > 0 {
        if y > 0 {
            z = 1;
        } else {
            z = 2;
        }
    } else {
        z = 3;
    }
    return z;
}
""",
        encoding="utf-8",
    )

    default_result = run_cli(["--emit-ssa", str(program)])
    explicit_general_result = run_cli(
        ["--emit-ssa", "--ssa-builder=general", str(program)]
    )

    assert default_result == explicit_general_result
    assert default_result[0] == EXIT_SUCCESS
    assert "merge1.z.phi" in default_result[1]


def test_emit_ssa_pattern_builder_remains_explicit_fallback(
    tmp_path: Path,
) -> None:
    program = tmp_path / "emit_ssa_explicit_pattern.ae"
    program.write_text(
        """
int add(int a, int b) {
    return a + b;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(
        ["--emit-ssa", "--ssa-builder=pattern", str(program)]
    )

    assert exit_code == EXIT_SUCCESS
    assert stdout == (
        "func @add(%a: int, %b: int) -> int {\n"
        "entry:\n"
        "    %0: int = add %a, %b\n"
        "    return %0\n"
        "}\n"
    )
    assert stderr == ""


@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [
        (
            "linear",
            """
int add(int a, int b) {
    return a + b;
}
""",
            "func @add(%a: int, %b: int) -> int",
        ),
        (
            "if_else",
            """
int f(int x) {
    int y = 0;
    if x > 0 {
        y = 1;
    } else {
        y = 2;
    }
    return y;
}
""",
            "phi(then0:",
        ),
        (
            "while",
            """
int sumTo(int n) {
    int i = 0;
    int sum = 0;
    while i <= n {
        sum = sum + i;
        i = i + 1;
    }
    return sum;
}
""",
            "phi(entry:",
        ),
        (
            "nested_if",
            """
int nested(int x, int y) {
    int z = 0;
    if x > 0 {
        if y > 0 {
            z = 1;
        } else {
            z = 2;
        }
    } else {
        z = 3;
    }
    return z;
}
""",
            "merge1.z.phi",
        ),
    ],
)
def test_emit_ssa_general_builder_supported_shapes(
    tmp_path: Path,
    name: str,
    source: str,
    expected: str,
) -> None:
    program = tmp_path / f"emit_ssa_general_{name}.ae"
    program.write_text(source, encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        ["--emit-ssa", "--ssa-builder=general", str(program)]
    )

    assert exit_code == EXIT_SUCCESS
    assert expected in stdout
    assert "load" not in stdout
    assert "store" not in stdout
    assert stderr == ""


def test_emit_ssa_pattern_rejects_nested_if_that_general_supports(
    tmp_path: Path,
) -> None:
    program = tmp_path / "emit_ssa_nested_if.ae"
    program.write_text(
        """
int nested(int x, int y) {
    int z = 0;
    if x > 0 {
        if y > 0 {
            z = 1;
        } else {
            z = 2;
        }
    } else {
        z = 3;
    }
    return z;
}
""",
        encoding="utf-8",
    )

    pattern_exit, pattern_stdout, pattern_stderr = run_cli(
        ["--emit-ssa", "--ssa-builder=pattern", str(program)]
    )
    general_exit, general_stdout, general_stderr = run_cli(
        ["--emit-ssa", "--ssa-builder=general", str(program)]
    )

    assert pattern_exit == EXIT_LANGUAGE_ERROR
    assert pattern_stdout == ""
    assert "SSA builder phase 3 only supports" in pattern_stderr
    assert "Traceback" not in pattern_stderr
    assert general_exit == EXIT_SUCCESS
    assert "merge1.z.phi" in general_stdout
    assert general_stderr == ""


def test_ssa_builder_without_emit_ssa_reports_usage_error(tmp_path: Path) -> None:
    program = tmp_path / "ssa_builder_without_emit.ae"
    program.write_text("int main() { return 42; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--ssa-builder=general", str(program)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "--ssa-builder is only supported with --emit-ssa." in stderr


def test_invalid_ssa_builder_reports_usage_error(tmp_path: Path) -> None:
    program = tmp_path / "invalid_ssa_builder.ae"
    program.write_text("int main() { return 42; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        ["--emit-ssa", "--ssa-builder=cytron", str(program)]
    )

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "invalid choice" in stderr
    assert "--ssa-builder" in stderr


def test_emit_ssa_general_builder_error_reports_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aether.ssa import GeneralSSABuildError

    def fail_general_build(*args, **kwargs):
        raise GeneralSSABuildError("original construction detail")

    program = tmp_path / "emit_ssa_general_error.ae"
    program.write_text("int main() { return 42; }\n", encoding="utf-8")
    monkeypatch.setattr("aether.cli.lower_to_verified_ssa", fail_general_build)

    exit_code, stdout, stderr = run_cli(
        ["--emit-ssa", "--ssa-builder=general", str(program)]
    )

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert "General SSA builder failed: original construction detail" in stderr
    assert "Traceback" not in stderr


def test_non_ssa_modes_remain_unchanged_after_adding_ssa_builder_selector(
    tmp_path: Path,
) -> None:
    program = tmp_path / "non_ssa_modes.ae"
    program.write_text("int main() { return 42; }\n", encoding="utf-8")

    emit_ir_exit, emit_ir_stdout, emit_ir_stderr = run_cli(
        ["--emit-ir", str(program)]
    )
    emit_cfg_exit, emit_cfg_stdout, emit_cfg_stderr = run_cli(
        ["--emit-cfg", str(program)]
    )
    backend_ir_exit, backend_ir_stdout, backend_ir_stderr = run_cli(
        ["--backend=ir", str(program)]
    )
    bench_exit, bench_stdout, bench_stderr = run_cli(
        ["bench", "benchmarks/sum_to.ae", "--iterations", "1", "--backend", "ast"]
    )

    assert emit_ir_exit == EXIT_SUCCESS
    assert "func @main" in emit_ir_stdout
    assert emit_ir_stderr == ""
    assert emit_cfg_exit == EXIT_SUCCESS
    assert "digraph main {" in emit_cfg_stdout
    assert emit_cfg_stderr == ""
    assert backend_ir_exit == EXIT_SUCCESS
    assert backend_ir_stdout == ""
    assert backend_ir_stderr == ""
    assert bench_exit == EXIT_SUCCESS
    assert "Benchmark: benchmarks/sum_to.ae" in bench_stdout
    assert "AST backend:" in bench_stdout
    assert bench_stderr == ""


def test_emit_ssa_pattern_unsupported_program_reports_builder_error_without_traceback(
    tmp_path: Path,
) -> None:
    program = tmp_path / "emit_ssa_nested_while.ae"
    program.write_text(
        """
int nested(int n) {
    while n > 0 {
        while n > 1 {
            n = n - 1;
        }
        n = n - 1;
    }
    return n;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(
        ["--emit-ssa", "--ssa-builder=pattern", str(program)]
    )

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert (
        "SSA builder phase 3 only supports linear functions, simple acyclic "
        "if/else, and simple while loops."
    ) in stderr
    assert "Traceback" not in stderr


def test_emit_ssa_rejects_emit_ir_combination(tmp_path: Path) -> None:
    program = tmp_path / "emit_ssa_emit_ir.ae"
    program.write_text("int main() { return 42; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--emit-ssa", "--emit-ir", str(program)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "not allowed with argument --emit-ssa" in stderr


def test_emit_ssa_rejects_emit_cfg_combination(tmp_path: Path) -> None:
    program = tmp_path / "emit_ssa_emit_cfg.ae"
    program.write_text("int main() { return 42; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--emit-ssa", "--emit-cfg", str(program)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "not allowed with argument --emit-ssa" in stderr


def test_emit_ssa_rejects_show_passes_combination(tmp_path: Path) -> None:
    program = tmp_path / "emit_ssa_show_passes.ae"
    program.write_text("int main() { return 42; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--emit-ssa", "--show-passes", str(program)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "--emit-ssa cannot be combined with --show-passes." in stderr


def test_emit_ssa_missing_file_reports_read_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing_ssa.ae"

    exit_code, stdout, stderr = run_cli(["--emit-ssa", str(missing)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "aether: cannot read" in stderr
    assert str(missing) in stderr


def test_emit_llvm_prints_llvm_ir(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm.ae"
    program.write_text("int main() { return 0; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout.startswith("define i32 @main() {")
    assert "ret i32 0" in stdout
    assert "func @main" not in stdout
    assert stderr == ""


def test_emit_llvm_prints_constant_function(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_constant.ae"
    program.write_text("int main() { return 42; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == (
        "define i32 @main() {\n"
        "entry:\n"
        "  ret i32 42\n"
        "}\n"
    )
    assert stderr == ""


def test_emit_llvm_prints_row_vector_literal(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_vector_literal.ae"
    program.write_text(
        "int main() { Vector<int, Row> v = [1, 2, 3]; return 0; }\n",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "@aether_array_new(i64 4, i64 3)" in stdout
    assert "store i32 1" in stdout
    assert "store i32 2" in stdout
    assert "store i32 3" in stdout
    assert "ret i32 0" in stdout
    assert stderr == ""


def test_emit_llvm_prints_column_vector_literal_from_expected_type(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_vector_column_literal.ae"
    program.write_text(
        "int main() { Vector<int, Column> v = [1, 2, 3]; return 0; }\n",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "@aether_array_new(i64 4, i64 3)" in stdout
    assert "store i32 1" in stdout
    assert "store i32 2" in stdout
    assert "store i32 3" in stdout
    assert "ret i32 0" in stdout
    assert stderr == ""


def test_emit_llvm_prints_column_vector_literal_from_semicolon_syntax(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_vector_column_inferred.ae"
    program.write_text(
        "int main() { Vector<int> v = [1; 2; 3]; return 0; }\n",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "@aether_array_new(i64 4, i64 3)" in stdout
    assert "store i32 1" in stdout
    assert "store i32 2" in stdout
    assert "store i32 3" in stdout
    assert "ret i32 0" in stdout
    assert stderr == ""


def test_emit_llvm_prints_matrix_literal(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_matrix_literal.ae"
    program.write_text(
        "int main() { Matrix<int> A = [1, 2; 3, 4]; return 0; }\n",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "@aether_array_new(i64 4, i64 4)" in stdout
    assert "store i32 1" in stdout
    assert "store i32 2" in stdout
    assert "store i32 3" in stdout
    assert "store i32 4" in stdout
    assert "ret i32 0" in stdout
    assert stderr == ""


def test_emit_llvm_prints_vector_and_matrix_index_reads(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_index_reads.ae"
    program.write_text(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    return v[1] + A[1, 0];
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "load i32" in stdout
    assert "mul i64 %matrix.row64" in stdout
    assert ", 2" in stdout
    assert "ret i32" in stdout
    assert stderr == ""


def test_emit_llvm_prints_vector_and_matrix_index_writes(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_index_writes.ae"
    program.write_text(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    v[1] = 9;
    A[1, 0] = v[1];
    return A[1, 0];
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "store i32 9" in stdout
    assert "ptr %matrix.elem" in stdout
    assert "mul i64 %matrix.row64" in stdout
    assert "ret i32" in stdout
    assert stderr == ""


def test_emit_llvm_prints_vector_and_matrix_dimension_properties(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_dimension_properties.ae"
    program.write_text(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4; 5, 6];
    return v.length + A.rows + A.columns;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "vector.len64" in stdout
    assert "trunc i64" in stdout
    assert "add i32 0, 3" in stdout
    assert "add i32 0, 2" in stdout
    assert "ret i32" in stdout
    assert stderr == ""


def test_emit_llvm_prints_string_literal_global(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_string.ae"
    program.write_text(
        """
string hello() {
    return "hello";
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == (
        '@.str.0 = private unnamed_addr constant [6 x i8] c"hello\\00"\n'
        "\n"
        "define ptr @hello() {\n"
        "entry:\n"
        "  ret ptr @.str.0\n"
        "}\n"
    )
    assert stderr == ""


def test_emit_llvm_deduplicates_repeated_string_literals(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_string_dedup.ae"
    program.write_text(
        """
string first() {
    return "same";
}

string second() {
    return "same";
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout.count("private unnamed_addr constant") == 1
    assert stdout.count("ret ptr @.str.0") == 2
    assert stderr == ""


def test_emit_llvm_prints_string_literal_call_argument(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_string_call.ae"
    program.write_text(
        """
string echo(string text) {
    return text;
}

string caller() {
    return echo("hi");
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert '@.str.0 = private unnamed_addr constant [3 x i8] c"hi\\00"\n' in stdout
    assert "define ptr @echo(ptr %text)" in stdout
    assert "  %0 = call ptr @echo(ptr @.str.0)\n" in stdout
    assert stderr == ""


def test_emit_llvm_prints_string_variable_return(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_string_variable.ae"
    program.write_text(
        """
string hello() {
    string text = "hello";
    return text;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert '@.str.0 = private unnamed_addr constant [6 x i8] c"hello\\00"\n' in stdout
    assert "define ptr @hello()" in stdout
    assert "  ret ptr @.str.0\n" in stdout
    assert stderr == ""


def test_emit_llvm_prints_string_assignment_return(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_string_assignment.ae"
    program.write_text(
        """
string copy() {
    string source = "hello";
    string target = source;
    return target;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert '@.str.0 = private unnamed_addr constant [6 x i8] c"hello\\00"\n' in stdout
    assert "define ptr @copy()" in stdout
    assert "  ret ptr @.str.0\n" in stdout
    assert stderr == ""


def test_emit_llvm_prints_string_call_with_variable_argument(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_string_variable_call.ae"
    program.write_text(
        """
string identity(string value) {
    return value;
}

string caller() {
    string text = "hello";
    return identity(text);
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "define ptr @identity(ptr %value)" in stdout
    assert "  ret ptr %value\n" in stdout
    assert "  %0 = call ptr @identity(ptr @.str.0)\n" in stdout
    assert "  ret ptr %0\n" in stdout
    assert stderr == ""


def test_emit_llvm_prints_string_phi_for_if_else(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_string_phi.ae"
    program.write_text(
        """
string choose(boolean flag) {
    string result = "hello";
    if flag {
        result = "world";
    } else {
        result = "hello";
    }
    return result;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert '@.str.0 = private unnamed_addr constant [6 x i8] c"world\\00"\n' in stdout
    assert '@.str.1 = private unnamed_addr constant [6 x i8] c"hello\\00"\n' in stdout
    assert "merge0:\n" in stdout
    assert "  %0 = phi ptr [ @.str.0, %then0 ], [ @.str.1, %else0 ]\n" in stdout
    assert "  ret ptr %0\n" in stdout
    assert stderr == ""


def test_emit_llvm_rejects_string_arithmetic_with_clear_error(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_string_add.ae"
    program.write_text(
        """
string bad(string x) {
    return x + "b";
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert "LLVM backend does not support string binary operations yet" in stderr


def test_emit_llvm_rejects_constant_string_arithmetic_without_folding(
    tmp_path: Path,
) -> None:
    program = tmp_path / "emit_llvm_constant_string_add.ae"
    program.write_text(
        """
string bad() {
    return "a" + "b";
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert "LLVM backend does not support string binary operations yet" in stderr


def test_emit_llvm_rejects_constant_string_comparison_without_folding(
    tmp_path: Path,
) -> None:
    program = tmp_path / "emit_llvm_constant_string_eq.ae"
    program.write_text(
        """
boolean bad() {
    return "a" == "a";
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert "LLVM backend does not support string comparisons yet" in stderr


def test_emit_llvm_prints_sum(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_sum.ae"
    program.write_text("int inc(int x) { return x + 1; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == (
        "define i32 @inc(i32 %x) {\n"
        "entry:\n"
        "  %0 = add i32 %x, 1\n"
        "  ret i32 %0\n"
        "}\n"
    )
    assert stderr == ""


def test_emit_llvm_prints_add_int_int(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_add.ae"
    program.write_text(
        """
int add(int a, int b) {
    return a + b;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == (
        "define i32 @add(i32 %a, i32 %b) {\n"
        "entry:\n"
        "  %0 = add i32 %a, %b\n"
        "  ret i32 %0\n"
        "}\n"
    )
    assert stderr == ""


def test_emit_llvm_prints_call(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_call.ae"
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

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "define i32 @add(i32 %a, i32 %b)" in stdout
    assert "define i32 @main()" in stdout
    assert "  %0 = call i32 @add(i32 2, i32 3)\n" in stdout
    assert "  ret i32 %0\n" in stdout
    assert stderr == ""


def test_emit_llvm_prints_int_compare(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_compare.ae"
    program.write_text(
        """
boolean greater(int a, int b) {
    return a > b;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == (
        "define i1 @greater(i32 %a, i32 %b) {\n"
        "entry:\n"
        "  %0 = icmp sgt i32 %a, %b\n"
        "  ret i1 %0\n"
        "}\n"
    )
    assert stderr == ""


def test_emit_llvm_prints_double_arithmetic_and_compare(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_double.ae"
    program.write_text(
        """
boolean greater_sum(double a, double b, double limit) {
    return a + b > limit;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == (
        "define i1 @greater_sum(double %a, double %b, double %limit) {\n"
        "entry:\n"
        "  %0 = fadd double %a, %b\n"
        "  %1 = fcmp ogt double %0, %limit\n"
        "  ret i1 %1\n"
        "}\n"
    )
    assert stderr == ""


def test_emit_llvm_prints_int_to_double_cast(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_int_to_double.ae"
    program.write_text(
        """
double widen(int x) {
    return double(x);
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "  %0 = sitofp i32 %x to double\n" in stdout
    assert "  ret double %0\n" in stdout
    assert stderr == ""


def test_emit_llvm_prints_double_to_int_cast(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_double_to_int.ae"
    program.write_text(
        """
int narrow(double x) {
    return int(x);
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "  %0 = fptosi double %x to i32\n" in stdout
    assert "  ret i32 %0\n" in stdout
    assert stderr == ""


def test_emit_llvm_prints_cast_used_in_arithmetic(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_cast_arithmetic.ae"
    program.write_text(
        """
double add_cast(int x, double y) {
    return double(x) + y;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "  %0 = sitofp i32 %x to double\n" in stdout
    assert "  %1 = fadd double %0, %y\n" in stdout
    assert "  ret double %1\n" in stdout
    assert stderr == ""


def test_emit_llvm_rejects_unsupported_cast(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_bad_cast.ae"
    program.write_text(
        """
int bad(boolean flag) {
    return int(flag);
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert "IR backend does not support cast from 'bool' to 'int' yet" in stderr


def test_emit_llvm_prints_branch_with_comparison(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_branch_compare.ae"
    program.write_text(
        """
int choose(int x) {
    if x > 0 {
        return 1;
    } else {
        return 2;
    }
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "entry:\n" in stdout
    assert "then0:\n" in stdout
    assert "else0:\n" in stdout
    assert "  %0 = icmp sgt i32 %x, 0\n" in stdout
    assert "  br i1 %0, label %then0, label %else0\n" in stdout
    assert stderr == ""


def test_emit_llvm_prints_branch_with_boolean_parameter(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_branch_bool.ae"
    program.write_text(
        """
int choose(boolean flag) {
    if flag {
        return 1;
    } else {
        return 2;
    }
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "  br i1 %flag, label %then0, label %else0\n" in stdout
    assert stderr == ""


def test_emit_llvm_prints_jump_for_constant_branch(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_jump.ae"
    program.write_text(
        """
int main() {
    if true {
        return 1;
    } else {
        return 2;
    }
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "  br label %then0\n" in stdout
    assert stderr == ""


def test_emit_llvm_missing_file_reports_read_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing_llvm.ae"

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(missing)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "aether: cannot read" in stderr
    assert str(missing) in stderr


def test_emit_llvm_prints_if_else_merge_phi(
    tmp_path: Path,
) -> None:
    program = tmp_path / "emit_llvm_phi.ae"
    program.write_text(
        """
int choose(int x) {
    int y = 0;
    if x > 0 {
        y = 1;
    } else {
        y = 2;
    }
    return y;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "merge0:\n" in stdout
    assert "  %1 = phi i32 [ 1, %then0 ], [ 2, %else0 ]\n" in stdout
    assert "  ret i32 %1\n" in stdout
    assert stderr == ""


def test_emit_llvm_prints_loop_carried_phi_with_defined_incoming(
    tmp_path: Path,
) -> None:
    program = tmp_path / "emit_llvm_countdown.ae"
    program.write_text(
        """
int countdown(int n) {
    while n > 0 {
        n = n - 1;
    }
    return n;
}

int main() {
    return countdown(5);
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "cond0:\n" in stdout
    assert "body0:\n" in stdout
    assert "  %0 = phi i32 [ %n, %entry ], [ %2, %body0 ]\n" in stdout
    assert "  %2 = sub i32 %0, 1\n" in stdout
    assert "  %0 = call i32 @countdown(i32 5)\n" in stdout
    assert "%5" not in stdout
    assert stderr == ""


@pytest.mark.parametrize(
    "other_flag",
    ["--emit-ir", "--emit-ssa", "--emit-cfg"],
)
def test_emit_llvm_rejects_other_emit_modes(
    tmp_path: Path,
    other_flag: str,
) -> None:
    program = tmp_path / "emit_llvm_incompatible.ae"
    program.write_text("int main() { return 42; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--emit-llvm", other_flag, str(program)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "not allowed with argument --emit-llvm" in stderr


def test_emit_llvm_rejects_show_passes_combination(tmp_path: Path) -> None:
    program = tmp_path / "emit_llvm_show_passes.ae"
    program.write_text("int main() { return 42; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        ["--emit-llvm", "--show-passes", str(program)]
    )

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "--emit-llvm cannot be combined with --show-passes." in stderr


def test_build_missing_file_reports_read_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing_build.ae"

    exit_code, stdout, stderr = run_cli(["build", str(missing)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "aether: cannot read" in stderr
    assert str(missing) in stderr


def test_build_accepts_function_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "build_call.ae"
    output = tmp_path / "build_call"
    commands: list[list[str]] = []
    program.write_text(
        """
int identity(int x) {
    return x;
}

int main() {
    return identity(5);
}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "aether.backend.llvm.build.shutil.which",
        lambda _name: "/usr/bin/clang",
    )

    def fake_run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("aether.backend.llvm.build.subprocess.run", fake_run)

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert len(commands) == 1
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""


def test_build_accepts_matrix_literal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "build_matrix_literal.ae"
    output = tmp_path / "build_matrix_literal"
    program.write_text(
        "int main() { Matrix<int> A = [1, 2; 3, 4]; return 0; }\n",
        encoding="utf-8",
    )
    clang_commands, _program_commands = fake_native_toolchain(monkeypatch)

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert len(clang_commands) == 1
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""


def test_build_accepts_vector_and_matrix_index_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "build_index_reads.ae"
    output = tmp_path / "build_index_reads"
    program.write_text(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    return v[1] + A[1, 0];
}
""",
        encoding="utf-8",
    )
    clang_commands, _program_commands = fake_native_toolchain(monkeypatch)

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert len(clang_commands) == 1
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""


def test_build_accepts_vector_and_matrix_index_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "build_index_writes.ae"
    output = tmp_path / "build_index_writes"
    program.write_text(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    v[1] = 9;
    A[1, 0] = v[1];
    return A[1, 0];
}
""",
        encoding="utf-8",
    )
    clang_commands, _program_commands = fake_native_toolchain(monkeypatch)

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert len(clang_commands) == 1
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""


def test_build_accepts_vector_and_matrix_dimension_properties(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "build_dimension_properties.ae"
    output = tmp_path / "build_dimension_properties"
    program.write_text(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4; 5, 6];
    return v.length + A.rows + A.columns;
}
""",
        encoding="utf-8",
    )
    clang_commands, _program_commands = fake_native_toolchain(monkeypatch)

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert len(clang_commands) == 1
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""


def test_build_reports_clear_error_when_clang_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "build_no_clang.ae"
    program.write_text("int main() { return 5; }\n", encoding="utf-8")
    monkeypatch.setattr("aether.backend.llvm.build.shutil.which", lambda _name: None)

    exit_code, stdout, stderr = run_cli(["build", str(program)])

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert "clang is required to build native executables." in stderr
    assert "Traceback" not in stderr


def test_build_accepts_output_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "build_output.ae"
    output = tmp_path / "custom_output"
    commands: list[list[str]] = []
    program.write_text("int main() { return 5; }\n", encoding="utf-8")
    monkeypatch.setattr(
        "aether.backend.llvm.build.shutil.which",
        lambda _name: "/usr/bin/clang",
    )

    def fake_run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("aether.backend.llvm.build.subprocess.run", fake_run)

    exit_code, stdout, stderr = run_cli(
        ["build", str(program), "-o", str(output)]
    )

    assert exit_code == EXIT_SUCCESS
    assert len(commands) == 1
    assert commands[0][0] == "/usr/bin/clang"
    assert commands[0][1].endswith(".ll")
    assert commands[0][2:] == ["-o", str(output.resolve())]
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""


def test_build_reports_clang_stderr_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "build_clang_failure.ae"
    program.write_text("int main() { return 5; }\n", encoding="utf-8")
    monkeypatch.setattr(
        "aether.backend.llvm.build.shutil.which",
        lambda _name: "/usr/bin/clang",
    )
    monkeypatch.setattr(
        "aether.backend.llvm.build.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            1,
            "",
            "clang failed loudly",
        ),
    )

    exit_code, stdout, stderr = run_cli(["build", str(program)])

    assert exit_code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert "clang failed loudly" in stderr
    assert "Traceback" not in stderr


def test_build_accepts_keep_llvm_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "build_keep_llvm.ae"
    output = tmp_path / "kept_output"
    llvm_path = tmp_path / "kept_output.ll"
    program.write_text("int main() { return 5; }\n", encoding="utf-8")
    monkeypatch.setattr(
        "aether.backend.llvm.build.shutil.which",
        lambda _name: "/usr/bin/clang",
    )
    monkeypatch.setattr(
        "aether.backend.llvm.build.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )

    exit_code, stdout, stderr = run_cli(
        ["build", str(program), "-o", str(output), "--keep-llvm"]
    )

    assert exit_code == EXIT_SUCCESS
    assert llvm_path.read_text(encoding="utf-8") == (
        "define i32 @main() {\n"
        "entry:\n"
        "  ret i32 5\n"
        "}"
    )
    assert f"Built executable: {output.resolve()}\n" in stdout
    assert f"Kept LLVM IR: {llvm_path.resolve()}\n" in stdout
    assert stderr == ""


def test_build_keep_llvm_default_output_uses_build_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "default_keep_llvm.ae"
    expected_output = tmp_path / "build" / "default_keep_llvm"
    llvm_path = tmp_path / "build" / "default_keep_llvm.ll"
    program.write_text("int main() { return 5; }\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "aether.backend.llvm.build.shutil.which",
        lambda _name: "/usr/bin/clang",
    )
    monkeypatch.setattr(
        "aether.backend.llvm.build.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )

    exit_code, stdout, stderr = run_cli(["build", str(program), "--keep-llvm"])

    assert exit_code == EXIT_SUCCESS
    assert llvm_path.read_text(encoding="utf-8") == (
        "define i32 @main() {\n"
        "entry:\n"
        "  ret i32 5\n"
        "}"
    )
    assert f"Built executable: {expected_output.resolve()}\n" in stdout
    assert f"Kept LLVM IR: {llvm_path.resolve()}\n" in stdout
    assert stderr == ""


def test_build_default_output_uses_build_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "default_output.ae"
    expected_output = tmp_path / "build" / "default_output"
    commands: list[list[str]] = []
    program.write_text("int main() { return 5; }\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "aether.backend.llvm.build.shutil.which",
        lambda _name: "/usr/bin/clang",
    )

    def fake_run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("aether.backend.llvm.build.subprocess.run", fake_run)

    exit_code, stdout, stderr = run_cli(["build", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert commands[0][-1] == str(expected_output.resolve())
    assert stdout == f"Built executable: {expected_output.resolve()}\n"
    assert stderr == ""


def test_build_creates_nested_output_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "nested_output.ae"
    output = tmp_path / "out" / "linux" / "release" / "nested_output"
    program.write_text("int main() { return 5; }\n", encoding="utf-8")
    monkeypatch.setattr(
        "aether.backend.llvm.build.shutil.which",
        lambda _name: "/usr/bin/clang",
    )
    monkeypatch.setattr(
        "aether.backend.llvm.build.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert output.parent.is_dir()
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""


def test_build_smoke_compiles_and_runs_with_clang_if_available(tmp_path: Path) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    program = tmp_path / "return_5.ae"
    output = tmp_path / "return_5"
    program.write_text("int main() { return 5; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""
    completed = subprocess.run([str(output)], check=False)
    assert completed.returncode == 5


def test_build_matrix_literal_smoke_compiles_and_runs_with_clang_if_available(tmp_path: Path) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    program = tmp_path / "matrix_literal.ae"
    output = tmp_path / "matrix_literal"
    program.write_text(
        "int main() { Matrix<int> A = [1, 2; 3, 4]; return 0; }\n",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""
    completed = subprocess.run([str(output)], check=False)
    assert completed.returncode == 0


def test_build_index_reads_smoke_compiles_and_runs_with_clang_if_available(tmp_path: Path) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    program = tmp_path / "index_reads.ae"
    output = tmp_path / "index_reads"
    program.write_text(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    return v[1] + A[1, 0];
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""
    completed = subprocess.run([str(output)], check=False)
    assert completed.returncode == 8


def test_build_index_writes_smoke_compiles_and_runs_with_clang_if_available(tmp_path: Path) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    program = tmp_path / "index_writes.ae"
    output = tmp_path / "index_writes"
    program.write_text(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4];
    v[1] = 9;
    A[1, 0] = v[1];
    return A[1, 0];
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""
    completed = subprocess.run([str(output)], check=False)
    assert completed.returncode == 9


def test_build_dimension_properties_smoke_compiles_and_runs_with_clang_if_available(tmp_path: Path) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    program = tmp_path / "dimension_properties.ae"
    output = tmp_path / "dimension_properties"
    program.write_text(
        """
int main() {
    Vector<int, Row> v = [4, 5, 6];
    Matrix<int> A = [1, 2; 3, 4; 5, 6];
    return v.length + A.rows + A.columns;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""
    completed = subprocess.run([str(output)], check=False)
    assert completed.returncode == 8


def test_build_call_smoke_compiles_and_runs_with_clang_if_available(
    tmp_path: Path,
) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    program = tmp_path / "identity.ae"
    output = tmp_path / "identity"
    program.write_text(
        """
int identity(int x) {
    return x;
}

int main() {
    return identity(5);
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""
    completed = subprocess.run([str(output)], check=False)
    assert completed.returncode == 5


def test_build_string_flow_smoke_compiles_and_runs_with_clang_if_available(
    tmp_path: Path,
) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    program = tmp_path / "string_flow.ae"
    output = tmp_path / "string_flow"
    program.write_text(
        """
string identity(string value) {
    return value;
}

string choose(boolean flag) {
    string result = "hello";
    if flag {
        result = identity("world");
    } else {
        result = identity("hello");
    }
    return result;
}

int main() {
    string selected = choose(true);
    return 0;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""
    completed = subprocess.run([str(output)], check=False)
    assert completed.returncode == 0


def test_build_countdown_smoke_compiles_and_runs_with_clang_if_available(
    tmp_path: Path,
) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    program = tmp_path / "countdown.ae"
    output = tmp_path / "countdown"
    program.write_text(
        """
int countdown(int n) {
    while n > 0 {
        n = n - 1;
    }
    return n;
}

int main() {
    return countdown(5);
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""
    completed = subprocess.run([str(output)], check=False)
    assert completed.returncode == 0


def test_build_bool_compare_smoke_compiles_and_runs_with_clang_if_available(
    tmp_path: Path,
) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    program = tmp_path / "return_compare.ae"
    output = tmp_path / "return_compare"
    program.write_text("boolean main() { return 3 > 2; }\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["build", str(program), "-o", str(output)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""
    completed = subprocess.run([str(output)], check=False)
    assert completed.returncode == 1


def test_normal_cli_execution_is_unchanged_after_emit_llvm(tmp_path: Path) -> None:
    program = tmp_path / "normal_after_emit_llvm.ae"
    program.write_text('println("normal");\n', encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--backend=ast", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == "normal\n"
    assert stderr == ""


def test_normal_cli_execution_is_unchanged_after_emit_ssa(tmp_path: Path) -> None:
    program = tmp_path / "normal_after_emit_ssa.ae"
    program.write_text('println("normal");\n', encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["--backend=ast", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == "normal\n"
    assert stderr == ""


def test_emit_cfg_prints_graphviz_dot(tmp_path: Path) -> None:
    program = tmp_path / "emit_cfg.ae"
    program.write_text(
        """
int sumTo(int n) {
    int i = 0;
    int sum = 0;

    while i < n {
        sum = sum + i;
        i = i + 1;
    }

    return sum;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-cfg", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout.startswith("digraph sumTo {")
    assert "    entry;" in stdout
    assert "    cond0;" in stdout
    assert "    body0;" in stdout
    assert "    exit0;" in stdout
    assert "    entry -> cond0;" in stdout
    assert "    cond0 -> body0;" in stdout
    assert "    cond0 -> exit0;" in stdout
    assert "    body0 -> cond0;" in stdout
    assert "func @sumTo" not in stdout
    assert stderr == ""


def test_emit_cfg_prints_one_dot_graph_per_function(tmp_path: Path) -> None:
    program = tmp_path / "emit_cfg_multiple.ae"
    program.write_text(
        """
int first() {
    return 1;
}

int second(int x) {
    if x > 0 {
        return 1;
    } else {
        return 0;
    }
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-cfg", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "digraph first {" in stdout
    assert "digraph second {" in stdout
    assert "    entry -> then0;" in stdout
    assert "    entry -> else0;" in stdout
    assert stderr == ""


def test_backend_ir_with_emit_cfg_prints_cfg_without_execution(tmp_path: Path) -> None:
    program = tmp_path / "backend_emit_cfg.ae"
    program.write_text(
        """
int main() {
    return 42;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--backend=ir", "--emit-cfg", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "digraph main {" in stdout
    assert "    entry;" in stdout
    assert stderr == ""


def test_emit_cfg_with_show_passes_reports_clear_usage_error(tmp_path: Path) -> None:
    program = tmp_path / "emit_cfg_show_passes.ae"
    program.write_text(
        """
int main() {
    return 42;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["--emit-cfg", "--show-passes", str(program)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "--show-passes requires --emit-ir --opt." in stderr


def test_emit_cfg_missing_file_reports_read_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing_cfg.ae"

    exit_code, stdout, stderr = run_cli(["--emit-cfg", str(missing)])

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout == ""
    assert "aether: cannot read" in stderr
    assert str(missing) in stderr


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

    exit_code, stdout, stderr = run_cli(["--backend=ast", str(program)])

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

    exit_code, stdout, stderr = run_cli(["--backend=ast", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert stdout == "normal\n"
    assert stderr == ""
