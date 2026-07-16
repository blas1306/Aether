from __future__ import annotations

from io import StringIO
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBuilder
from aether.cli import main as cli_main
from aether.errors import AetherRuntimeError, AetherTypeError
from aether.language_service import completion_items
from aether.pipeline import IRBackend, prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker
from aether.types import ArrayType


SOURCE = """
import System;
int main() {
    Array<string> args = System.args();
    println(args.length);
    for string arg in args {
        println(arg);
    }
    return 0;
}
"""


def _typed(source: str = SOURCE, *, root: Path | None = None):
    return prepare_typed_program(source, TypeChecker(source_root=root))


def _run_cli(tmp_path: Path, arguments: list[str], *, backend: str = "ast"):
    program = tmp_path / "Main.ae"
    program.write_text(SOURCE, encoding="utf-8")
    stdout = StringIO()
    stderr = StringIO()
    argv = ["run", f"--backend={backend}", str(program), *arguments]
    code = cli_main(argv, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_system_args_is_namespaced_zero_arity_array_string_and_completed() -> None:
    typed = _typed()
    call = typed.program.statements[-1].body[0].initializer
    assert typed.checker.type_of_expression(call) == ArrayType("string")
    assert "System.args" in {item.label for item in completion_items("", 0, 0)}

    with pytest.raises(AetherTypeError, match=r"System\.args\(\) expects zero arguments"):
        _typed("import System; int main() { Array<string> bad = System.args(1); return 0; }")


def test_ast_program_arguments_are_explicit_and_each_call_is_independent() -> None:
    source = """
import System;
int main() {
    Array<string> first = System.args();
    Array<string> second = System.args();
    Array<string> slice = first[0:2];
    Array<string> copied = first.copy();
    first[0] = "changed";
    println(second[0] == " 41 ");
    println(slice[1] == "2.5");
    println(copied[2] == "café");
    println(parseInt(second[0].trim()).value);
    println(parseDouble(second[1]).value);
    return second.length;
}
"""
    result = run_aether(
        source,
        program_arguments=[" 41 ", "2.5", "café"],
    )
    assert result.exit_code == 3
    assert result.output.splitlines() == ["true", "true", "true", "41", "2.5"]


def test_programmatic_ast_rejects_non_utf8_surrogate_at_startup() -> None:
    with pytest.raises(
        AetherRuntimeError,
        match="process argument 1 is not valid UTF-8",
    ):
        run_aether("int main() { return 0; }", program_arguments=["ok", "\udcff"])


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["--"], ["0"]),
        (["--", "one", "two", "three"], ["3", "one", "two", "three"]),
        (["--", "hello world"], ["1", "hello world"]),
        (["--", "--flag"], ["1", "--flag"]),
        (["--", "--backend=ir", ""], ["2", "--backend=ir", ""]),
        (["--", "áéí🙂"], ["1", "áéí🙂"]),
    ],
)
def test_cli_run_separator_forwards_exact_ast_arguments(
    tmp_path: Path,
    arguments: list[str],
    expected: list[str],
) -> None:
    code, stdout, stderr = _run_cli(tmp_path, arguments)
    assert code == 0
    assert stdout.splitlines() == expected
    assert stderr == ""


def test_cli_without_separator_preserves_zero_argument_policy(tmp_path: Path) -> None:
    code, stdout, stderr = _run_cli(tmp_path, [])
    assert code == 0
    assert stdout.splitlines() == ["0"]
    assert stderr == ""


def test_ir_backend_receives_injected_arguments_and_preserves_order() -> None:
    output = StringIO()
    backend = IRBackend(
        output_writer=output.write,
        program_arguments=("first", "second"),
    )
    env = backend.run(_typed())
    assert output.getvalue().splitlines() == ["2", "first", "second"]
    assert env.lookup("__ir_main_result").value == 0


def test_process_arguments_flow_through_modules_returns_and_structs(tmp_path: Path) -> None:
    (tmp_path / "Reader.ae").write_text(
        """
package Reader;
import System;
public Array<string> readArgs() { return System.args(); }
""",
        encoding="utf-8",
    )
    source = """
from Reader import readArgs;
struct Payload { string text; }
int main() {
    Array<string> args = readArgs();
    Payload payload = Payload(args[0]);
    println(payload.text);
    return 0;
}
"""
    result = run_aether(
        source,
        source_root=tmp_path,
        program_arguments=["from module"],
    )
    assert result.exit_code == 0
    assert result.output == "from module\n"


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_process_arguments_flow_through_module_return(tmp_path: Path) -> None:
    (tmp_path / "Reader.ae").write_text(
        """
package Reader;
import System;
public Array<string> readArgs() { return System.args(); }
""",
        encoding="utf-8",
    )
    program = tmp_path / "Main.ae"
    program.write_text(
        """
from Reader import readArgs;
int main() {
    Array<string> args = readArgs();
    println(args[0]);
    return 0;
}
""",
        encoding="utf-8",
    )
    stdout = StringIO()
    stderr = StringIO()
    code = cli_main(
        ["run", str(program), "--", "native module"],
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0
    assert stdout.getvalue() == "native module\n"
    assert stderr.getvalue() == ""


def test_ir_ssa_and_llvm_keep_process_args_effectful_and_typed() -> None:
    from aether.backend.llvm import LLVMBackend
    from aether.ir import print_ir
    from aether.ir.optimizer import build_optimizer_pipeline
    from aether.pipeline import lower_to_verified_ssa
    from aether.ssa import print_ssa
    from aether.ssa.optimizer import SSAOptimizerPipeline

    source = "import System; int main() { System.args(); System.args(); return 0; }"
    typed = _typed(source)
    ir = IRBackend().lower_verified(typed)
    for profile in ("O0", "O1", "O2"):
        optimized = ir if profile == "O0" else IRBackend().optimize_verified(
            ir, optimizer=build_optimizer_pipeline(profile)
        )
        assert print_ir(optimized).count("builtin @System.args()") == 2

    ssa = SSAOptimizerPipeline(verify_after_each=True).run(lower_to_verified_ssa(typed))
    assert print_ssa(ssa).count("builtin @System.args()") == 2
    llvm = LLVMBackend().emit(ssa, native_entry=True)
    assert "define i32 @__aether_program_main()" in llvm
    assert "define i32 @main(i32 %argc, ptr %argv)" in llvm
    assert llvm.count("call ptr @aether_process_args_snapshot()") >= 2


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_cli_argument_parity_for_many_and_long_values(tmp_path: Path) -> None:
    values = [f"arg-{index}" for index in range(40)] + ["x" * 8192, "café🙂"]
    code, stdout, stderr = _run_cli(tmp_path, ["--", *values], backend="llvm")
    assert code == 0
    assert stdout.splitlines() == [str(len(values)), *values]
    assert stderr == ""


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_entry_wrapper_avoids_user_symbol_collision(tmp_path: Path) -> None:
    source = """
int __aether_program_main() { return 9; }
int main() { return __aether_program_main(); }
"""
    executable = tmp_path / "collision"
    LLVMBuilder().build(_typed(source), output_path=executable)
    completed = subprocess.run([str(executable)], check=False)
    assert completed.returncode == 9


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("clang") is None,
    reason="POSIX argv bytes and clang are required",
)
def test_native_startup_rejects_invalid_utf8_with_argument_index(tmp_path: Path) -> None:
    executable = tmp_path / "args"
    LLVMBuilder().build(_typed(), output_path=executable)
    completed = subprocess.run(
        [os.fsencode(executable), b"valid", b"invalid-\xff"],
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert completed.stdout == b""
    assert completed.stderr == (
        b"Aether startup error: process argument 1 is not valid UTF-8.\n"
    )


@pytest.mark.parametrize("level", ("0", "1", "2"))
@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_process_arguments_compile_and_run_with_clang_optimization_levels(
    tmp_path: Path,
    level: str,
) -> None:
    llvm_path = tmp_path / f"args-O{level}.ll"
    executable = tmp_path / f"args-O{level}"
    llvm_path.write_text(LLVMBuilder().emit_llvm(_typed()), encoding="utf-8")
    compiled = subprocess.run(
        [shutil.which("clang"), f"-O{level}", str(llvm_path), "-o", str(executable)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    completed = subprocess.run(
        [str(executable), "one", "two words", "café"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.splitlines() == ["3", "one", "two words", "café"]
    assert completed.stderr == ""
