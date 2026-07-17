from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil

import pytest

from aether import ast
from aether.backend.llvm import LLVMRunner
from aether.cli import main as cli_main
from aether.errors import AetherTypeError
from aether.pipeline import (
    IRBackend,
    IR_MAIN_RESULT_NAME,
    lower_to_verified_ssa,
    prepare_typed_program,
)
from aether.runner import run_aether
from aether.typechecker import TypeChecker


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _run_ir(source: str) -> tuple[str, int]:
    backend = IRBackend()
    env = backend.run(_typed(source))
    return backend.output, int(env.values[IR_MAIN_RESULT_NAME].value)


def _run_cli(arguments: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    code = cli_main(arguments, stdin=StringIO(), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_script_is_normalized_to_marked_synthetic_main() -> None:
    typed = _typed('println("Hola");')

    assert typed.program.entry_point == "main"
    assert len(typed.program.statements) == 1
    main = typed.program.statements[0]
    assert isinstance(main, ast.FunctionDeclaration)
    assert main.name == "main"
    assert main.return_type == "int"
    assert main.parameters == []
    assert main.synthetic is True
    assert isinstance(main.body[-1], ast.ReturnStatement)


@pytest.mark.parametrize(
    ("source", "output", "exit_code"),
    [
        ('println("Hola");', "Hola\n", 0),
        (
            """
boolean esMayor(int x) {
    return x >= 18;
}
println(esMayor(19));
println(esMayor(17));
""",
            "true\nfalse\n",
            0,
        ),
        ('int main() { println("Hola"); }', "Hola\n", 0),
        ("int main() { return 7; }", "", 7),
        (
            """
int add(int a, int b) {
    return a + b;
}
int main() {
    println(add(2, 3));
}
""",
            "5\n",
            0,
        ),
    ],
)
def test_ast_and_ir_share_entry_point_output_and_exit_code(
    source: str,
    output: str,
    exit_code: int,
) -> None:
    ast_result = run_aether(source)
    ir_output, ir_exit = _run_ir(source)

    assert (ast_result.output, ast_result.exit_code) == (output, exit_code)
    assert (ir_output, ir_exit) == (output, exit_code)


def test_synthetic_main_passes_through_verified_ssa() -> None:
    module = lower_to_verified_ssa(_typed('println("ssa");'))

    assert [function.name for function in module.functions] == ["main"]


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_script_and_explicit_main_run_natively(tmp_path: Path) -> None:
    for source, expected_output, expected_exit in (
        ('println("script");', "script\n", 0),
        ('int main() { println("explicit"); }', "explicit\n", 0),
        ("int main() { return 7; }", "", 7),
    ):
        stdout = StringIO()
        stderr = StringIO()
        exit_code = LLVMRunner().run(_typed(source), stdout=stdout, stderr=stderr)
        assert (stdout.getvalue(), stderr.getvalue(), exit_code) == (
            expected_output,
            "",
            expected_exit,
        )


@pytest.mark.parametrize("backend", ["ast", "ir", "llvm"])
def test_cli_runs_minimal_script_with_each_backend(
    backend: str,
    tmp_path: Path,
) -> None:
    if backend == "llvm" and shutil.which("clang") is None:
        pytest.skip("clang is required")
    program = tmp_path / f"script_{backend}.ae"
    program.write_text('println("Hola");\n', encoding="utf-8")

    exit_code, stdout, stderr = _run_cli([f"--backend={backend}", str(program)])

    assert (exit_code, stdout, stderr) == (0, "Hola\n", "")


def test_default_cli_backend_runs_script(tmp_path: Path) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is required")
    program = tmp_path / "default_script.ae"
    program.write_text('println("default");\n', encoding="utf-8")

    assert _run_cli([str(program)]) == (0, "default\n", "")


@pytest.mark.parametrize("backend", ["ast", "ir", "llvm"])
def test_script_panic_has_exit_code_one_for_every_backend(
    backend: str,
    tmp_path: Path,
) -> None:
    if backend == "llvm" and shutil.which("clang") is None:
        pytest.skip("clang is required")
    program = tmp_path / f"panic_{backend}.ae"
    program.write_text(
        "Array<int> values = {1};\nprintln(values[2]);\n",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _run_cli([f"--backend={backend}", str(program)])

    assert exit_code == 1
    if backend in {"ast", "llvm"}:
        assert stdout == "Aether panic: Array index out of bounds\n"
        assert stderr == ""
    else:
        assert "out of bounds" in stdout + stderr


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("void main() {}", "main must return int"),
        ("double main() { return 0.0; }", "main must return int"),
        ("int main(int argc) { return argc; }", "main must not declare parameters"),
        (
            "int main() { return 0; } int main() { return 1; }",
            "Program entry point 'main' is already defined",
        ),
        (
            'println("top-level"); int main() {}',
            "Cannot combine top-level executable statements with an explicit main function",
        ),
    ],
)
def test_invalid_entry_point_models_have_precise_diagnostics(
    source: str,
    message: str,
) -> None:
    with pytest.raises(AetherTypeError, match=message):
        _typed(source)


def test_implicit_return_is_exclusive_to_main() -> None:
    explicit = _typed('int main() { println("ok"); }')
    main = explicit.program.statements[0]
    assert isinstance(main, ast.FunctionDeclaration)
    assert isinstance(main.body[-1], ast.ReturnStatement)

    with pytest.raises(AetherTypeError, match="Function 'f' may not return"):
        _typed('int f() { println("bad"); } int main() {}')


def test_explicit_return_does_not_gain_dead_synthetic_return() -> None:
    typed = _typed("int main() { return 4; }")
    main = typed.program.statements[0]

    assert isinstance(main, ast.FunctionDeclaration)
    assert len(main.body) == 1


def test_script_execution_order_is_preserved() -> None:
    source = """
println("a");
void f() {
    println("f");
}
f();
println("b");
"""

    assert (run_aether(source).output, _run_ir(source)[0]) == (
        "a\nf\nb\n",
        "a\nf\nb\n",
    )


def test_wrapped_statement_keeps_original_error_location() -> None:
    with pytest.raises(AetherTypeError) as raised:
        _typed('\nprintln("ok");\nprintln(missing);\n')

    assert raised.value.line == 3


def test_top_level_return_is_rejected_before_normalization() -> None:
    with pytest.raises(AetherTypeError, match="Cannot return outside of a function"):
        _typed("return 7;")


def test_top_level_const_is_available_to_explicit_main() -> None:
    source = "const int VALUE = 5; int main() { println(VALUE); }"

    assert (run_aether(source).output, _run_ir(source)[0]) == ("5\n", "5\n")
