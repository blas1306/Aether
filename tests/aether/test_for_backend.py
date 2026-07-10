from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import print_llvm
from aether.cli import EXIT_SUCCESS, main
from aether.ir import (
    IRBranch,
    IRInterpreter,
    IRJump,
    IRLowerer,
    IRVerifier,
    print_ir,
)
from aether.ir.optimizer import OptimizerPipeline
from aether.pipeline import lower_to_verified_ssa, parse_source
from aether.ssa import SSAVerifier, print_ssa
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


def _lower(source: str):
    program = parse_source(source)
    TypeChecker().check(program)
    return IRVerifier(IRLowerer().lower(program)).verify()


def _ssa(source: str):
    return lower_to_verified_ssa(_lower(source))


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    exit_code = main(argv, stdout=stdout, stderr=stderr)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_lowers_simple_for_range_to_ir_cfg() -> None:
    module = _lower(
        """
int main() {
    int sum = 0;
    for i in 1:5 {
        sum = sum + i;
    }
    return sum;
}
"""
    )

    ir = print_ir(module)

    assert "for.cond0:" in ir
    assert "for.body0:" in ir
    assert "for.inc0:" in ir
    assert "for.exit0:" in ir
    assert "branch %5, for.body0, for.exit0" in ir
    assert "jump for.inc0" in ir
    assert IRInterpreter(module).call("main") == 15


def test_lowers_nested_for_ranges_and_executes_ir() -> None:
    module = _lower(
        """
int main() {
    int sum = 0;
    for i in 1:2 {
        for j in 1:3 {
            sum = sum + i * j;
        }
    }
    return sum;
}
"""
    )

    assert "for.cond0:" in print_ir(module)
    assert "for.cond1:" in print_ir(module)
    assert IRInterpreter(module).call("main") == 18


def test_lowers_for_range_with_dynamic_step() -> None:
    module = _lower(
        """
int sumStep(int step) {
    int sum = 0;
    for i in 1:step:5 {
        sum = sum + i;
    }
    return sum;
}
"""
    )

    ir = print_ir(module)

    assert "for.pos0:" in ir
    assert "for.neg0:" in ir
    assert IRInterpreter(module).call("sumStep", [2]) == 9
    assert IRInterpreter(module).call("sumStep", [-1]) == 0


def test_lowers_break_and_continue_inside_if() -> None:
    module = _lower(
        """
int main() {
    int sum = 0;
    for i in 1:10 {
        if i == 7 {
            break;
        }
        if i % 2 == 0 {
            continue;
        }
        sum = sum + i;
    }
    return sum;
}
"""
    )

    jumps = [
        instruction
        for block in module.functions[0].blocks
        for instruction in block.instructions
        if isinstance(instruction, IRJump)
    ]

    assert any(jump.target == "for.exit0" for jump in jumps)
    assert any(jump.target == "for.inc0" for jump in jumps)
    assert IRInterpreter(module).call("main") == 9


def test_break_and_continue_work_for_while_lowering_too() -> None:
    module = _lower(
        """
int main() {
    int i = 0;
    int sum = 0;
    while i < 6 {
        i = i + 1;
        if i == 5 {
            break;
        }
        if i == 3 {
            continue;
        }
        sum = sum + i;
    }
    return sum;
}
"""
    )

    jumps = [
        instruction
        for block in module.functions[0].blocks
        for instruction in block.instructions
        if isinstance(instruction, IRJump)
    ]

    assert any(jump.target == "exit0" for jump in jumps)
    assert any(jump.target == "cond0" for jump in jumps)
    assert IRInterpreter(module).call("main") == 7


def test_for_builds_verified_ssa_with_liveness_pruned_nested_loop_phis() -> None:
    ssa_module = _ssa(
        """
int main() {
    int sum = 0;
    for i in 1:2 {
        for j in 1:4 {
            if j == 3 {
                break;
            }
            sum = sum + i * j;
        }
    }
    return sum;
}
"""
    )

    ssa_text = print_ssa(SSAVerifier(ssa_module).verify())

    assert "for.cond0:" in ssa_text
    assert "for.cond1:" in ssa_text
    assert "for.cond0.j.phi" not in ssa_text
    assert "for.cond1.j.phi" in ssa_text or "%9: int = phi" in ssa_text


def test_for_survives_ir_and_ssa_optimizers() -> None:
    module = _lower(
        """
int main() {
    int sum = 0;
    for i in 1:5 {
        if i == 3 {
            continue;
        }
        sum = sum + i;
    }
    return sum;
}
"""
    )

    optimized_ir = IRVerifier(OptimizerPipeline(iterative=True).run(module)).verify()
    ssa_module = lower_to_verified_ssa(optimized_ir)
    optimized_ssa = SSAVerifier(SSAOptimizerPipeline(iterative=True).run(ssa_module)).verify()

    assert IRInterpreter(optimized_ir).call("main") == 12
    assert "for.cond0:" in print_ssa(optimized_ssa)


def test_for_emits_textual_llvm_control_flow() -> None:
    llvm = print_llvm(
        _ssa(
            """
int main() {
    int sum = 0;
    for i in 1:5 {
        sum = sum + i;
    }
    return sum;
}
"""
        )
    )

    assert "for.cond0:" in llvm
    assert "for.body0:" in llvm
    assert "for.inc0:" in llvm
    assert "for.exit0:" in llvm
    assert "br i1" in llvm
    assert "br label %for.inc0" in llvm


def test_emit_llvm_cli_supports_for_break_continue(tmp_path: Path) -> None:
    program = tmp_path / "for_break_continue.ae"
    program.write_text(
        """
int main() {
    int sum = 0;
    for i in 1:10 {
        if i == 7 {
            break;
        }
        if i % 2 == 0 {
            continue;
        }
        sum = sum + i;
    }
    return sum;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _run_cli(["--emit-llvm", str(program)])

    assert exit_code == EXIT_SUCCESS
    assert "define i32 @main()" in stdout
    assert "for.cond0:" in stdout
    assert stderr == ""


def test_default_llvm_run_and_build_support_for(tmp_path: Path) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    program = tmp_path / "for_sum.ae"
    output = tmp_path / "for_sum"
    program.write_text(
        """
int main() {
    int sum = 0;
    for i in 1:5 {
        sum = sum + i;
    }
    return sum;
}
""",
        encoding="utf-8",
    )

    run_exit_code, run_stdout, run_stderr = _run_cli([str(program)])
    build_exit_code, build_stdout, build_stderr = _run_cli(
        ["build", str(program), "-o", str(output)]
    )
    completed = subprocess.run(
        [str(output)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert run_exit_code == 15
    assert run_stdout == ""
    assert run_stderr == ""
    assert build_exit_code == EXIT_SUCCESS
    assert build_stdout == f"Built executable: {output.resolve()}\n"
    assert build_stderr == ""
    assert completed.returncode == 15
    assert completed.stdout == ""
    assert completed.stderr == ""
