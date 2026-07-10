from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from aether.backend.llvm import print_llvm
from aether.cli import EXIT_SUCCESS, main
from aether.errors import AetherTypeError
from aether.ir import IRInterpreter, IRLowerer, IRVectorDot, IRVerifier, IntType
from aether.pipeline import parse_source
from aether.runner import run_aether
from aether.ssa import SSABuilder, SSAVectorDot, SSAVerifier, print_ssa
from aether.typechecker import TypeChecker


def _lower(source: str):
    program = parse_source(source)
    TypeChecker().check(program)
    return IRLowerer().lower(program)


def _emit_llvm(path: Path) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    exit_code = main(["--emit-llvm", str(path)], stdout=stdout, stderr=stderr)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_row_column_vector_product_typechecks_and_runs() -> None:
    result = run_aether(
        """
Vector<int, Row> r = [1, 2, 3];
Vector<int, Column> c = [4; 5; 6];
x = r * c;
"""
    )

    assert result.env["x"].type_name == "int"
    assert result.env["x"].value == 32


@pytest.mark.parametrize(
    "source",
    [
        "Vector<int, Row> a = [1, 2]; Vector<int, Row> b = [3, 4]; x = a * b;",
        "Vector<int, Column> a = [1; 2]; Vector<int, Column> b = [3; 4]; x = a * b;",
        "Matrix<int> A = [1, 2; 3, 4]; Vector<int, Row> r = [5, 6]; y = A * r;",
        "Vector<int, Column> c = [1; 2]; Matrix<int> A = [3, 4; 5, 6]; y = c * A;",
    ],
)
def test_vector_dot_rejects_invalid_star_combinations(source: str) -> None:
    with pytest.raises(AetherTypeError):
        run_aether(source)


def test_vector_dot_lowers_to_ir_instruction_and_interprets() -> None:
    module = _lower(
        """
int dot() {
    Vector<int, Row> r = [1, 2, 3];
    Vector<int, Column> c = [4; 5; 6];
    return r * c;
}
"""
    )

    assert IRVerifier(module).verify() is module
    instructions = module.functions[0].blocks[0].instructions
    dot = next(instruction for instruction in instructions if isinstance(instruction, IRVectorDot))

    assert dot.result.type == IntType()
    assert dot.length == 3
    assert IRInterpreter(module).call("dot", []) == 32


def test_vector_dot_builds_ssa_and_verifies() -> None:
    module = _lower(
        """
int dot() {
    Vector<int, Row> r = [1, 2, 3];
    Vector<int, Column> c = [4; 5; 6];
    return r * c;
}
"""
    )

    ssa_module = SSABuilder().build(module)
    assert SSAVerifier(ssa_module).verify() is ssa_module
    dot = next(
        instruction
        for instruction in ssa_module.functions[0].blocks[0].instructions
        if isinstance(instruction, SSAVectorDot)
    )

    assert dot.result.type == IntType()
    assert dot.length == 3
    assert "vector_dot row_column" in print_ssa(ssa_module)


def test_vector_dot_llvm_text_uses_loop_over_contiguous_storage() -> None:
    module = _lower(
        """
int main() {
    Vector<int, Row> r = [1, 2, 3];
    Vector<int, Column> c = [4; 5; 6];
    return r * c;
}
"""
    )
    llvm = print_llvm(SSABuilder().build(module))

    assert "vector.dot.loop" in llvm
    assert "getelementptr i32" in llvm
    assert "load i32" in llvm
    assert "mul i32" in llvm
    assert "add i32" in llvm
    assert "ret i32" in llvm


def test_emit_llvm_prints_vector_dot(tmp_path: Path) -> None:
    program = tmp_path / "vector_dot.ae"
    program.write_text(
        """
int main() {
    Vector<int, Row> r = [1, 2, 3];
    Vector<int, Column> c = [4; 5; 6];
    return r * c;
}
""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = _emit_llvm(program)

    assert exit_code == EXIT_SUCCESS
    assert "vector.dot.loop" in stdout
    assert "mul i32" in stdout
    assert "ret i32" in stdout
    assert stderr == ""
