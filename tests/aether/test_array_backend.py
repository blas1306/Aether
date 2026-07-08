from __future__ import annotations

import shutil

import pytest

from aether.backend.llvm import LLVMRunner
from aether.ir import (
    IRArrayGet,
    IRArrayLength,
    IRArrayNew,
    IRArraySet,
    IRInterpreter,
    IRLowerer,
)
from aether.pipeline import lower_to_verified_ssa, parse_source, prepare_typed_program
from aether.ssa import SSAArrayGet, SSAArrayLength, SSAArrayNew, SSAArraySet
from aether.typechecker import TypeChecker


def _lower(source: str):
    program = parse_source(source)
    TypeChecker().check(program)
    return IRLowerer().lower(program)


def test_lower_array_literal_index_assignment_and_length() -> None:
    module = _lower(
        """
int main() {
    Array<int> xs = {1, 2, 3};
    xs[1] = 10;
    return xs.length + xs[1];
}
"""
    )

    instructions = module.functions[0].blocks[0].instructions

    assert any(isinstance(instruction, IRArrayNew) for instruction in instructions)
    assert any(isinstance(instruction, IRArraySet) for instruction in instructions)
    assert any(isinstance(instruction, IRArrayLength) for instruction in instructions)
    assert any(isinstance(instruction, IRArrayGet) for instruction in instructions)


def test_ir_interpreter_executes_arrays() -> None:
    module = _lower(
        """
int main() {
    Array<int> xs = {1, 2, 3};
    xs[1] = 10;
    return xs[0] + xs[1] + xs.length;
}
"""
    )

    assert IRInterpreter(module).call("main") == 14


def test_ssa_preserves_array_instructions() -> None:
    typed_program = prepare_typed_program(
        """
int main() {
    Array<int> xs = {1, 2, 3};
    xs[1] = 10;
    return xs.length + xs[1];
}
""",
        TypeChecker(),
    )

    ssa = lower_to_verified_ssa(typed_program)
    instructions = ssa.functions[0].blocks[0].instructions

    assert any(isinstance(instruction, SSAArrayNew) for instruction in instructions)
    assert any(isinstance(instruction, SSAArraySet) for instruction in instructions)
    assert any(isinstance(instruction, SSAArrayLength) for instruction in instructions)
    assert any(isinstance(instruction, SSAArrayGet) for instruction in instructions)


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is not available")
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            """
int main() {
    Array<int> xs = {1, 2, 3};
    return xs[0] + xs[1] + xs[2];
}
""",
            6,
        ),
        (
            """
int main() {
    Array<int> xs = {1, 2, 3};
    xs[1] = 10;
    return xs[1];
}
""",
            10,
        ),
        (
            """
int main() {
    Array<int> xs = {1, 2, 3};
    return xs.length;
}
""",
            3,
        ),
        (
            """
int sumFirstTwo(Array<int> xs) {
    return xs[0] + xs[1];
}

int main() {
    Array<int> xs = {4, 5, 6};
    return sumFirstTwo(xs);
}
""",
            9,
        ),
    ],
)
def test_llvm_runner_executes_arrays(source: str, expected: int) -> None:
    typed_program = prepare_typed_program(source, TypeChecker())

    assert LLVMRunner().run(typed_program) == expected
