from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil

import pytest

from aether.backend.llvm import LLVMBackend, LLVMRunner
from aether.cli import EXIT_SUCCESS, main as cli_main
from aether.errors import AetherRuntimeError, AetherTypeError
from aether.ir import (
    IRBinaryOp,
    IRBranch,
    IRExecutionError,
    IRInterpreter,
    IRLoad,
    IRStore,
)
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import SSABinaryOp, SSABranch, SSACall, SSAPhi, SSAVerifier
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _ir(source: str):
    return IRBackend().lower_verified(_typed(source))


def _instructions(module):
    return [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    ]


BASIC_PROGRAM = """
int main() {
    println(false && false);
    println(false && true);
    println(true && false);
    println(true && true);
    println(false || false);
    println(false || true);
    println(true || false);
    println(true || true);
    return 0;
}
"""

BASIC_OUTPUT = "false\nfalse\nfalse\ntrue\nfalse\ntrue\ntrue\ntrue\n"


def test_boolean_truth_table_matches_ast_and_ir_interpreters() -> None:
    assert run_aether(BASIC_PROGRAM).output == BASIC_OUTPUT

    interpreter = IRInterpreter(_ir(BASIC_PROGRAM))
    assert interpreter.call("main") == 0
    assert interpreter.output == BASIC_OUTPUT


def test_precedence_of_not_and_or_is_preserved() -> None:
    result = run_aether(
        """
boolean a = true;
boolean b = false;
boolean c = false;
println(!a && b);
println(a || b && c);
println(!(a || b));
"""
    )

    assert result.output == "false\ntrue\nfalse\n"


def test_compiled_logical_values_work_in_assignments_if_and_while() -> None:
    source = """
int main() {
    boolean enabled = true;
    boolean selected = enabled && true;
    int i = 0;
    while i < 2 && selected {
        println(i);
        i = i + 1;
    }
    if selected && i == 2 {
        println("ok");
    }
    return 0;
}
"""

    interpreter = IRInterpreter(_ir(source))
    assert interpreter.call("main") == 0
    assert interpreter.output == "0\n1\nok\n"
    SSAVerifier(lower_to_verified_ssa(_typed(source))).verify()


def test_short_circuit_calls_only_the_required_right_operands_in_ast_and_ir() -> None:
    source = """
boolean mark() {
    println("called");
    return true;
}
int main() {
    println(false && mark());
    println(true || mark());
    println(true && mark());
    println(false || mark());
    return 0;
}
"""
    expected = "false\ntrue\ncalled\ntrue\ncalled\ntrue\n"

    assert run_aether(source).output == expected
    interpreter = IRInterpreter(_ir(source))
    assert interpreter.call("main") == 0
    assert interpreter.output == expected


def test_non_taken_array_access_does_not_panic_in_ast_or_ir() -> None:
    source = """
int main() {
    Array<int> values = {1};
    println(false && values[100] == 1);
    println(true || values[100] == 1);
    return 0;
}
"""

    assert run_aether(source).output == "false\ntrue\n"
    interpreter = IRInterpreter(_ir(source))
    assert interpreter.call("main") == 0
    assert interpreter.output == "false\ntrue\n"


@pytest.mark.parametrize(
    "expression",
    ["true && values[100] == 1", "false || values[100] == 1"],
)
def test_taken_array_access_panics_in_ast_and_ir(expression: str) -> None:
    source = f"int main() {{ Array<int> values = {{1}}; println({expression}); return 0; }}"

    with pytest.raises(AetherRuntimeError, match="Aether panic: Array index out of bounds"):
        run_aether(source)
    with pytest.raises(IRExecutionError, match="Aether panic: Array index out of bounds"):
        IRInterpreter(_ir(source)).call("main")


@pytest.mark.parametrize(
    "expression",
    ["1 && 2", "true || 1", '"hola" && false', "0 || false"],
)
def test_logical_binary_operators_require_exact_booleans(expression: str) -> None:
    operator = "&&" if "&&" in expression else "||"
    with pytest.raises(
        AetherTypeError,
        match=rf"Operator '{operator}' requires boolean operands\.",
    ):
        run_aether(f"println({expression});")


def test_ir_uses_cfg_and_a_merge_slot_instead_of_an_eager_binary_op() -> None:
    module = _ir("boolean both(boolean a, boolean b) { return a && b; }")
    function = module.functions[0]
    instructions = _instructions(module)

    assert [block.name for block in function.blocks] == [
        "entry",
        "logic.short0",
        "logic.rhs0",
        "logic.merge0",
    ]
    assert isinstance(function.blocks[0].instructions[-1], IRBranch)
    assert any(isinstance(instruction, IRStore) for instruction in instructions)
    assert any(isinstance(instruction, IRLoad) for instruction in instructions)
    assert not any(isinstance(instruction, IRBinaryOp) for instruction in instructions)


def test_ssa_and_llvm_expose_branch_merge_and_boolean_phi() -> None:
    ssa = lower_to_verified_ssa(
        _typed("boolean either(boolean a, boolean b) { return a || b; }")
    )
    instructions = _instructions(ssa)
    phi = next(
        instruction for instruction in instructions if isinstance(instruction, SSAPhi)
    )

    assert any(isinstance(instruction, SSABranch) for instruction in instructions)
    assert str(phi.result.type) == "bool"
    assert {block for block, _value in phi.incoming} == {
        "logic.short0",
        "logic.rhs0",
    }
    assert not any(isinstance(instruction, SSABinaryOp) for instruction in instructions)
    assert SSAVerifier(ssa).verify() is ssa

    llvm = LLVMBackend().emit(ssa)
    assert "br i1 %a, label %logic.short0, label %logic.rhs0" in llvm
    assert "phi i1" in llvm
    assert " and i1 " not in llvm
    assert " or i1 " not in llvm


def test_sccp_removes_only_unreachable_effectful_rhs_paths() -> None:
    source = """
boolean mark() { println("called"); return true; }
boolean skipped_and() { return false && mark(); }
boolean taken_and() { return true && mark(); }
boolean skipped_or() { return true || mark(); }
boolean taken_or() { return false || mark(); }
"""
    optimized = SSAOptimizerPipeline(iterative=True).run(
        lower_to_verified_ssa(_typed(source))
    )
    SSAVerifier(optimized).verify()

    calls_by_function = {
        function.name: sum(
            isinstance(instruction, SSACall)
            for block in function.blocks
            for instruction in block.instructions
        )
        for function in optimized.functions
    }
    assert calls_by_function["skipped_and"] == 0
    assert calls_by_function["skipped_or"] == 0
    assert calls_by_function["taken_and"] == 1
    assert calls_by_function["taken_or"] == 1


def test_native_backend_preserves_short_circuit_when_clang_is_available() -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is required for the native short-circuit test")

    source = """
boolean mark() { println("called"); return true; }
int main() {
    Array<int> values = {1};
    println(false && mark());
    println(true || values[100] == 1);
    println(false || mark());
    return 0;
}
"""
    stdout = StringIO()
    stderr = StringIO()

    assert LLVMRunner().run(_typed(source), stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue() == "false\ntrue\ncalled\ntrue\n"
    assert stderr.getvalue() == ""


def test_cli_emit_llvm_contains_short_circuit_cfg(tmp_path: Path) -> None:
    program = tmp_path / "logical.ae"
    program.write_text(
        "boolean either(boolean a, boolean b) { return a || b; }\n",
        encoding="utf-8",
    )
    stdout = StringIO()
    stderr = StringIO()

    exit_code = cli_main(
        ["--emit-llvm", str(program)],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_SUCCESS
    assert "br i1 %a, label %logic.short0, label %logic.rhs0" in stdout.getvalue()
    assert "phi i1" in stdout.getvalue()
    assert stderr.getvalue() == ""
