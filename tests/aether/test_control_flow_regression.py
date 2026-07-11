from __future__ import annotations

import shutil

import pytest

from aether.backend.llvm import LLVMRunner, print_llvm
from aether.errors import AetherTypeError
from aether.ir import (
    CFGBuilder,
    IRBranch,
    IRInterpreter,
    IRJump,
    IRLowerer,
    IRReturn,
    IRVerifier,
    print_ir,
)
from aether.pipeline import lower_to_verified_ssa, prepare_typed_program
from aether.ssa import SSAPhi, SSAVerifier, print_ssa
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.ssa.optimizer.sccp_pass import SCCPPass
from aether.typechecker import TypeChecker


_HAS_CLANG = shutil.which("clang") is not None


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _lower(source: str):
    typed = _typed(source)
    return IRVerifier(IRLowerer().lower(typed.program)).verify()


def _ssa(source: str):
    return lower_to_verified_ssa(_lower(source))


def _optimized_ssa(source: str):
    return SSAVerifier(SSAOptimizerPipeline(iterative=True).run(_ssa(source))).verify()


def _block(module, name: str):
    return next(block for block in module.functions[0].blocks if block.name == name)


def _terminators(block):
    return [
        instruction
        for instruction in block.instructions
        if isinstance(instruction, (IRBranch, IRJump, IRReturn))
    ]


def _assert_full_main_pipeline(source: str, expected: int) -> None:
    module = _lower(source)
    assert IRInterpreter(module).call("main") == expected

    ssa_module = lower_to_verified_ssa(module)
    optimized = SSAVerifier(
        SSAOptimizerPipeline(iterative=True).run(ssa_module)
    ).verify()

    llvm = print_llvm(optimized)
    assert "define i32 @main()" in llvm

    if _HAS_CLANG:
        assert LLVMRunner().run(_typed(source)) == expected


def test_empty_for_range_verifies_ssa_and_executes_full_pipeline() -> None:
    source = """
int main() {
    for i in 0:2 {
    }
    return 11;
}
"""

    module = _lower(source)
    body = _block(module, "for.body0")

    assert body.instructions == [IRJump("for.inc0")]
    assert "for.cond0:" in print_ir(module)
    _assert_full_main_pipeline(source, 11)


def test_continue_as_last_for_statement_emits_single_body_jump() -> None:
    module = _lower(
        """
int main() {
    int hits = 0;
    for i in 0:2 {
        hits = hits + 1;
        continue;
    }
    return hits;
}
"""
    )

    body = _block(module, "for.body0")
    terminators = _terminators(body)

    assert terminators == [IRJump("for.inc0")]
    assert body.instructions[-1] == IRJump("for.inc0")
    assert IRInterpreter(module).call("main") == 3
    SSAVerifier(lower_to_verified_ssa(module)).verify()


def test_unconditional_break_as_for_body_targets_loop_exit() -> None:
    module = _lower(
        """
int main() {
    for i in 0:9 {
        break;
    }
    return 5;
}
"""
    )

    cfg = CFGBuilder().build(module.functions[0])
    edges = {(edge.source, edge.target) for edge in cfg.edges}

    assert _block(module, "for.body0").instructions == [IRJump("for.exit0")]
    assert ("for.body0", "for.exit0") in edges
    assert ("for.body0", "for.inc0") not in edges
    assert IRInterpreter(module).call("main") == 5


def test_early_return_inside_for_survives_full_pipeline() -> None:
    _assert_full_main_pipeline(
        """
int f() {
    for i in 0:9 {
        return i;
    }
    return -1;
}

int main() {
    return f();
}
""",
        0,
    )


def test_early_return_inside_while_survives_full_pipeline() -> None:
    _assert_full_main_pipeline(
        """
int f() {
    int i = 0;
    while i < 10 {
        return i;
    }
    return -1;
}

int main() {
    return f();
}
""",
        0,
    )


def test_nested_break_only_exits_inner_loop() -> None:
    source = """
int main() {
    int count = 0;
    for i in 0:2 {
        for j in 0:4 {
            if j == 2 {
                break;
            }
            count = count + 1;
        }
    }
    return count;
}
"""
    module = _lower(source)
    then_block = _block(module, "then0")

    assert then_block.instructions[-1] == IRJump("for.exit1")
    assert IRInterpreter(module).call("main") == 6
    if _HAS_CLANG:
        assert LLVMRunner().run(_typed(source)) == 6


def test_nested_continue_targets_inner_loop_increment() -> None:
    source = """
int main() {
    int total = 0;
    for i in 0:2 {
        for j in 0:2 {
            if j == 1 {
                continue;
            }
            total = total + i * 10 + j;
        }
    }
    return total;
}
"""
    module = _lower(source)
    then_block = _block(module, "then0")

    assert then_block.instructions[-1] == IRJump("for.inc1")
    assert IRInterpreter(module).call("main") == 66
    SSAVerifier(lower_to_verified_ssa(module)).verify()


def test_outer_loop_carried_variable_modified_by_inner_loop_gets_nested_phis() -> None:
    source = """
int main() {
    int sum = 0;
    for i in 0:2 {
        for j in 0:1 {
            sum = sum + i + j;
        }
    }
    return sum;
}
"""
    module = _lower(source)
    ssa_module = lower_to_verified_ssa(module)
    ssa_text = print_ssa(ssa_module)

    assert IRInterpreter(module).call("main") == 9
    assert "for.cond0.sum.phi" in ssa_text
    assert "for.cond1.sum.phi" in ssa_text
    _assert_full_main_pipeline(source, 9)


def test_variable_declared_inside_loop_and_used_only_inside_compiles() -> None:
    _assert_full_main_pipeline(
        """
int main() {
    int sum = 0;
    for i in 0:2 {
        int tmp = i + 1;
        sum = sum + tmp;
    }
    return sum;
}
""",
        6,
    )


def test_variable_declared_inside_loop_used_after_is_rejected_by_typechecker() -> None:
    # The frontend scope checker rejects the local before IR lowering runs.
    with pytest.raises(AetherTypeError, match="Undefined variable 'tmp'"):
        _typed(
            """
int main() {
    for i in 0:2 {
        int tmp = i;
    }
    return tmp;
}
"""
        )


def test_variable_modified_inside_loop_and_used_after_gets_phi() -> None:
    source = """
int main() {
    int x = 1;
    for i in 0:2 {
        x = x + i;
    }
    return x;
}
"""
    module = _lower(source)
    ssa_module = lower_to_verified_ssa(module)
    phis = [
        instruction
        for block in ssa_module.functions[0].blocks
        for instruction in block.instructions
        if isinstance(instruction, SSAPhi)
    ]

    assert IRInterpreter(module).call("main") == 4
    assert any(phi.result.name == "for.cond0.x.phi" for phi in phis)
    _assert_full_main_pipeline(source, 4)


def test_while_constant_false_body_is_removed_by_sccp() -> None:
    source = """
int main() {
    int x = 7;
    while false {
        x = 1;
    }
    return x;
}
"""
    ssa_module = _ssa(source)
    result = SCCPPass().run(ssa_module)
    optimized = SSAVerifier(result.module).verify()
    block_names = {block.name for block in optimized.functions[0].blocks}

    assert result.stats["simplified_branches"] == 1
    assert result.stats["removed_blocks"] == 1
    assert "body0" not in block_names
    assert IRInterpreter(_lower(source)).call("main") == 7


def test_while_constant_true_with_break_preserves_exit() -> None:
    _assert_full_main_pipeline(
        """
int main() {
    int x = 0;
    while true {
        x = 9;
        break;
    }
    return x;
}
""",
        9,
    )

    optimized = _optimized_ssa(
        """
int main() {
    int x = 0;
    while true {
        x = 9;
        break;
    }
    return x;
}
"""
    )

    assert any(block.name == "exit0" for block in optimized.functions[0].blocks)


@pytest.mark.parametrize(
    ("source", "expected", "length_instruction"),
    [
        (
            """
int main() {
    Array<int> xs = {1, 2, 3, 4, 5};
    int sum = 0;
    for x in xs {
        if x == 4 {
            break;
        }
        if x == 2 {
            continue;
        }
        sum = sum + x;
    }
    return sum;
}
""",
            4,
            "array_len",
        ),
        (
            """
int main() {
    Vector<int, Row> xs = [1, 2, 3, 4, 5];
    int sum = 0;
    for x in xs {
        if x == 4 {
            break;
        }
        if x == 2 {
            continue;
        }
        sum = sum + x;
    }
    return sum;
}
""",
            4,
            "vector_len",
        ),
    ],
)
def test_for_over_indexables_with_break_and_continue(
    source: str,
    expected: int,
    length_instruction: str,
) -> None:
    module = _lower(source)
    ir = print_ir(module)

    assert length_instruction in ir
    assert IRInterpreter(module).call("main") == expected
    SSAVerifier(lower_to_verified_ssa(module)).verify()
    if _HAS_CLANG:
        assert LLVMRunner().run(_typed(source)) == expected


def test_for_dynamic_negative_step_with_continue() -> None:
    source = """
int main() {
    int step = -1;
    int sum = 0;
    for i in 5:step:1 {
        if i == 3 {
            continue;
        }
        sum = sum + i;
    }
    return sum;
}
"""
    module = _lower(source)
    ir = print_ir(module)

    assert "for.pos0:" in ir
    assert "for.neg0:" in ir
    assert _block(module, "then0").instructions[-1] == IRJump("for.inc0")
    assert IRInterpreter(module).call("main") == 12
    _assert_full_main_pipeline(source, 12)
