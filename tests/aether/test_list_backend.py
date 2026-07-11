from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether.backend.llvm import LLVMRunner, print_llvm
from aether.cli import EXIT_SUCCESS, main
from aether.errors import AetherTypeError
from aether.ir import (
    IRInterpreter,
    IRListGet,
    IRListIsEmpty,
    IRListLength,
    IRListNew,
    IRListSet,
    IRLowerer,
    IRVerifier,
    print_ir,
)
from aether.ir.optimizer import OptimizerPipeline
from aether.pipeline import lower_to_verified_ssa, parse_source, prepare_typed_program
from aether.ssa import (
    SSAListGet,
    SSAListIsEmpty,
    SSAListLength,
    SSAListNew,
    SSAListSet,
    SSAVerifier,
    print_ssa,
)
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _lower(source: str):
    typed = _typed(source)
    return IRVerifier(IRLowerer().lower(typed.program)).verify()


def _ssa(source: str):
    return lower_to_verified_ssa(_typed(source))


def _instructions(module):
    return [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    ]


def test_lowers_list_literals_length_is_empty_and_for_to_ir() -> None:
    module = _lower(
        """
int main() {
    List<int> xs = {1, 2, 3};
    int sum = 0;
    for int x in xs {
        sum = sum + x;
    }
    if (xs.is_empty) {
        return 99;
    }
    return sum + xs.length;
}
"""
    )
    instructions = _instructions(module)
    ir = print_ir(module)

    assert any(isinstance(instruction, IRListNew) for instruction in instructions)
    assert any(isinstance(instruction, IRListLength) for instruction in instructions)
    assert any(isinstance(instruction, IRListIsEmpty) for instruction in instructions)
    assert any(isinstance(instruction, IRListGet) for instruction in instructions)
    assert "list_new" in ir
    assert "list_length" in ir
    assert "list_is_empty" in ir
    assert IRInterpreter(module).call("main") == 9


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int main() { List<int> xs = {1, 2, 3}; return xs.length; }", 3),
        ("int main() { List<double> xs = {1.5, 2.5}; return xs.length; }", 2),
        ("int main() { List<int> xs = {}; return xs.length; }", 0),
        ("int main() { List<int> xs = {}; if (xs.is_empty) { return 7; } return 1; }", 7),
        ("int main() { List<int> xs = {4}; if (xs.is_empty) { return 1; } return 8; }", 8),
    ],
)
def test_ir_interpreter_executes_list_phase_one(source: str, expected: int) -> None:
    assert IRInterpreter(_lower(source)).call("main") == expected


def test_list_assignment_parameter_and_return_preserve_single_allocation_in_ir_ssa_llvm() -> None:
    source = """
List<int> identity(List<int> xs) {
    return xs;
}

int use(List<int> xs) {
    return xs.length;
}

int main() {
    List<int> a = {1, 2, 3};
    List<int> b = a;
    List<int> c = identity(b);
    return use(c);
}
"""
    ir = _lower(source)
    ssa = _ssa(source)
    llvm = print_llvm(ssa)

    assert sum(isinstance(instruction, IRListNew) for instruction in _instructions(ir)) == 1
    assert sum(isinstance(instruction, SSAListNew) for instruction in _instructions(ssa)) == 1
    assert llvm.count("@aether_list_new(i64 4, i64 3)") == 1
    assert "@identity(ptr %xs)" in llvm
    assert "call ptr @identity(ptr" in llvm
    assert "call i32 @use(ptr" in llvm


def test_for_over_empty_list_executes_zero_iterations() -> None:
    module = _lower(
        """
int main() {
    List<int> xs = {};
    int sum = 5;
    for int x in xs {
        sum = sum + x;
    }
    return sum;
}
"""
    )

    assert IRInterpreter(module).call("main") == 5


def test_ssa_builder_verifier_and_printer_preserve_list_instructions() -> None:
    ssa = _ssa(
        """
int main() {
    List<int> xs = {1, 2};
    return xs.length;
}
"""
    )
    instructions = _instructions(SSAVerifier(ssa).verify())
    printed = print_ssa(ssa)

    assert any(isinstance(instruction, SSAListNew) for instruction in instructions)
    assert any(isinstance(instruction, SSAListLength) for instruction in instructions)
    assert "list_new" in printed
    assert "list_length" in printed


def test_optimizers_preserve_observable_list_allocation() -> None:
    source = """
int main() {
    List<int> xs = {1, 2, 3};
    return 0;
}
"""
    ir_result = OptimizerPipeline().run(_lower(source))
    ssa_result = SSAOptimizerPipeline().run(_ssa(source))

    assert any(isinstance(instruction, IRListNew) for instruction in _instructions(ir_result))
    assert any(isinstance(instruction, SSAListNew) for instruction in _instructions(ssa_result))


def test_llvm_text_uses_distinct_list_layout_and_operations() -> None:
    llvm = print_llvm(
        _ssa(
            """
int main() {
    List<int> xs = {1, 2, 3};
    if (xs.is_empty) {
        return 0;
    }
    return xs.length;
}
"""
        )
    )

    assert "%AetherList = type { i64, i64, ptr }" in llvm
    assert "%AetherArray = type" not in llvm
    assert "define private ptr @aether_list_new" in llvm
    assert "@aether_list_new(i64 4, i64 3)" in llvm
    assert "getelementptr %AetherList" in llvm
    assert "icmp eq i64" in llvm


def test_emit_llvm_prints_list_ir(tmp_path) -> None:
    program = tmp_path / "list_emit.ae"
    program.write_text("int main() { List<int> xs = {1, 2, 3}; return xs.length; }\n", encoding="utf-8")
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(["--emit-llvm", str(program)], stdout=stdout, stderr=stderr)

    assert exit_code == EXIT_SUCCESS
    assert "%AetherList = type { i64, i64, ptr }" in stdout.getvalue()
    assert "@aether_list_new(i64 4, i64 3)" in stdout.getvalue()
    assert stderr.getvalue() == ""


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is not available")
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            """
int main() {
    List<int> xs = {1, 2, 3};
    int sum = 0;
    for int x in xs {
        sum = sum + x;
    }
    return sum + xs.length;
}
""",
            9,
        ),
        ("int main() { List<int> xs = {}; if (xs.is_empty) { return 12; } return 1; }", 12),
    ],
)
def test_llvm_runner_executes_list_phase_one(source: str, expected: int) -> None:
    assert LLVMRunner().run(_typed(source)) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int main() { List<int> xs = {1, 2, 3}; return xs[1]; }", 2),
        (
            "int main() { List<double> xs = {1.5, 2.5}; if (xs[0] > 1.0) { return 7; } return 0; }",
            7,
        ),
        ("int main() { List<int> xs = {1, 2, 3}; xs[1] = 9; return xs[1]; }", 9),
        (
            "int main() { List<double> xs = {1.5, 2.5}; xs[0] = 4.5; if (xs[0] > 4.0) { return 8; } return 0; }",
            8,
        ),
    ],
)
def test_ir_interpreter_reads_and_writes_list_elements(source: str, expected: int) -> None:
    assert IRInterpreter(_lower(source)).call("main") == expected


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "int main() { List<int> xs = {1}; return xs[1.0]; }",
            "Index must be int",
        ),
        (
            'int main() { List<int> xs = {1}; xs[0] = "bad"; return 0; }',
            "Cannot implicitly convert 'string' to 'int'",
        ),
        (
            "int main() { const List<int> xs = {1}; xs[0] = 2; return 0; }",
            "Cannot mutate constant 'xs'",
        ),
    ],
)
def test_list_index_type_rules(source: str, message: str) -> None:
    with pytest.raises(AetherTypeError, match=message):
        _typed(source)


@pytest.mark.parametrize(
    "source",
    [
        "int main() { List<int> a = {1, 2, 3}; List<int> b = a; b[0] = 9; return a[0]; }",
        "int set_first(List<int> xs) { xs[0] = 9; return 0; } int main() { List<int> a = {1, 2, 3}; int ignored = set_first(a); return a[0]; }",
        "List<int> identity(List<int> xs) { return xs; } int main() { List<int> a = {1, 2, 3}; List<int> b = identity(a); b[0] = 9; return a[0]; }",
    ],
)
def test_list_set_aliases_by_assignment_parameter_and_return(source: str) -> None:
    typed = _typed(source)
    assert IRInterpreter(IRVerifier(IRLowerer().lower(typed.program)).verify()).call("main") == 9
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == 9


def test_ir_ssa_builder_verifiers_and_printers_preserve_list_set() -> None:
    source = "int main() { List<int> xs = {1, 2}; xs[0] = 9; return xs[0]; }"
    ir = _lower(source)
    ssa = SSAVerifier(_ssa(source)).verify()

    assert any(isinstance(instruction, IRListGet) for instruction in _instructions(ir))
    assert any(isinstance(instruction, IRListSet) for instruction in _instructions(ir))
    assert any(isinstance(instruction, SSAListGet) for instruction in _instructions(ssa))
    assert any(isinstance(instruction, SSAListSet) for instruction in _instructions(ssa))
    assert "list_set" in print_ir(ir)
    assert "list_set" in print_ssa(ssa)


def test_optimizers_preserve_list_set_and_distinct_gets_around_it() -> None:
    source = "int main() { List<int> xs = {1}; int before = xs[0]; xs[0] = 9; return before + xs[0]; }"
    optimized_ir = OptimizerPipeline().run(_lower(source))
    optimized_ssa = SSAOptimizerPipeline().run(_ssa(source))

    assert IRInterpreter(optimized_ir).call("main") == 10
    assert any(isinstance(instruction, IRListSet) for instruction in _instructions(optimized_ir))
    assert any(isinstance(instruction, SSAListSet) for instruction in _instructions(optimized_ssa))
    assert sum(isinstance(instruction, SSAListGet) for instruction in _instructions(optimized_ssa)) == 2


def test_llvm_text_list_get_and_set_use_list_data_buffer() -> None:
    llvm = print_llvm(_ssa("int main() { List<int> xs = {1, 2}; xs[0] = 9; return xs[0]; }"))

    assert "%AetherList = type { i64, i64, ptr }" in llvm
    assert llvm.count("getelementptr %AetherList, ptr") >= 2
    assert "load ptr, ptr" in llvm
    assert "store i32" in llvm


def test_emit_llvm_prints_explicit_list_index_and_set(tmp_path) -> None:
    program = tmp_path / "list_index_set.ae"
    program.write_text(
        "int main() { List<int> xs = {1, 2}; xs[0] = 9; return xs[0]; }\n",
        encoding="utf-8",
    )
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(["--emit-llvm", str(program)], stdout=stdout, stderr=stderr)

    assert exit_code == EXIT_SUCCESS
    assert "store i32" in stdout.getvalue()
    assert "load i32" in stdout.getvalue()
    assert stderr.getvalue() == ""
