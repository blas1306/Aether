from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether.backend.llvm import LLVMRunner, print_llvm
from aether.cli import EXIT_SUCCESS, main
from aether.errors import AetherTypeError
from aether.ir import (
    IRInterpreter,
    IRListContains,
    IRListIndexOf,
    IRListCopy,
    IRListGet,
    IRListIsEmpty,
    IRListLength,
    IRListNew,
    IRListSet,
    IRListReverse,
    IRLowerer,
    IRVerifier,
    print_ir,
)
from aether.ir.optimizer import OptimizerPipeline
from aether.pipeline import lower_to_verified_ssa, parse_source, prepare_typed_program
from aether.ssa import (
    SSAListGet,
    SSAListContains,
    SSAListIndexOf,
    SSAListCopy,
    SSAListIsEmpty,
    SSAListLength,
    SSAListNew,
    SSAListSet,
    SSAListReverse,
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


def test_phase_3a_lowers_prints_and_verifies_explicit_ir_and_ssa() -> None:
    source = """
int main() {
    List<int> a = {1, 2, 3};
    List<int> b = a.copy();
    b.reverse();
    if (b.contains(2)) { return b[0]; }
    return 0;
}
"""
    ir = _lower(source)
    ssa = SSAVerifier(_ssa(source)).verify()

    assert any(isinstance(item, IRListCopy) for item in _instructions(ir))
    assert any(isinstance(item, IRListContains) for item in _instructions(ir))
    assert any(isinstance(item, IRListReverse) for item in _instructions(ir))
    assert any(isinstance(item, SSAListCopy) for item in _instructions(ssa))
    assert any(isinstance(item, SSAListContains) for item in _instructions(ssa))
    assert any(isinstance(item, SSAListReverse) for item in _instructions(ssa))
    assert "list_copy" in print_ir(ir) and "list_copy" in print_ssa(ssa)
    assert "list_contains" in print_ir(ir) and "list_contains" in print_ssa(ssa)
    assert "list_reverse" in print_ir(ir) and "list_reverse" in print_ssa(ssa)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int main(){ List<int> a={}; List<int> b=a.copy(); return b.length; }", 0),
        ("int main(){ List<int> a={1,2}; List<int> b=a.copy(); b[0]=9; return a[0]*10+b[0]; }", 19),
        ("int main(){ List<double> a={1.5,2.5}; List<double> b=a.copy(); b[0]=9.0; if(a[0]==1.5){return 4;} return 0; }", 4),
        ("int main(){ List<List<int>> a={{1},{2}}; List<List<int>> b=a.copy(); b[0][0]=5; return a[0][0]; }", 5),
        ("int main(){ List<int> a={1,2,3}; List<int> b=a.copy(); b.reverse(); return a[0]*10+b[0]; }", 13),
    ],
)
def test_list_copy_is_shallow_with_independent_outer_buffer(source: str, expected: int) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == expected
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int main(){ List<int> xs={1,2,3}; if(xs.contains(2)){return 1;} return 0; }", 1),
        ("int main(){ List<int> xs={1,2,3}; if(xs.contains(9)){return 1;} return 0; }", 0),
        ("int main(){ List<int> xs={}; if(xs.contains(1)){return 1;} return 0; }", 0),
        ("int main(){ List<double> xs={1.5,2.5}; if(xs.contains(2.5)){return 2;} return 0; }", 2),
        ("int main(){ List<boolean> xs={true,false}; if(xs.contains(false)){return 3;} return 0; }", 3),
        ('int main(){ List<string> xs={"a","bb"}; if(xs.contains("bb")){return 4;} return 0; }', 4),
        ("int main(){ List<List<int>> xs={{1}}; List<int> same=xs[0]; if(xs.contains(same)){return 5;} return 0; }", 5),
        ("int main(){ List<List<int>> xs={{1}}; List<int> other={1}; if(xs.contains(other)){return 5;} return 0; }", 0),
    ],
)
def test_list_contains_uses_language_equality(source: str, expected: int) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == expected
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int main(){ List<int> xs={10,20,30}; return xs.indexOf(10); }", 0),
        ("int main(){ List<int> xs={10,20,30}; return xs.indexOf(20); }", 1),
        ("int main(){ List<int> xs={10,20,30}; return xs.indexOf(30); }", 2),
        ("int main(){ List<int> xs={10,20,20,30}; return xs.indexOf(20); }", 1),
        ("int main(){ List<int> xs={10,20,30}; return xs.indexOf(99)+1; }", 0),
        ("int main(){ List<int> xs={}; return xs.indexOf(1)+1; }", 0),
        ("int main(){ List<double> xs={1.5,2.5}; return xs.indexOf(2.5); }", 1),
        ("int main(){ List<boolean> xs={true,false}; return xs.indexOf(false); }", 1),
        ('int main(){ List<string> xs={"a","bb"}; return xs.indexOf("bb"); }', 1),
        ("int main(){ List<List<int>> xs={{1}}; List<int> same=xs[0]; return xs.indexOf(same); }", 0),
        ("int main(){ List<List<int>> xs={{1}}; List<int> other={1}; return xs.indexOf(other)+1; }", 0),
    ],
)
def test_list_index_of_uses_language_equality(source: str, expected: int) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == expected
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == expected


def test_list_index_of_lowers_prints_and_verifies_ir_and_ssa() -> None:
    source = "int main(){ List<int> xs={1,2,3}; return xs.indexOf(2); }"
    ir = _lower(source)
    ssa = SSAVerifier(_ssa(source)).verify()

    assert any(isinstance(item, IRListIndexOf) for item in _instructions(ir))
    assert any(isinstance(item, SSAListIndexOf) for item in _instructions(ssa))
    assert "list_index_of" in print_ir(ir)
    assert "list_index_of" in print_ssa(ssa)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int main(){ List<int> xs={}; xs.reverse(); return xs.length; }", 0),
        ("int main(){ List<int> xs={7}; xs.reverse(); return xs[0]; }", 7),
        ("int main(){ List<int> xs={1,2,3,4}; xs.reverse(); return xs[0]*10+xs[3]; }", 41),
        ("int main(){ List<int> xs={1,2,3,4,5}; xs.reverse(); return xs[0]*10+xs[4]; }", 51),
        ("int main(){ List<int> xs={1,2,3}; xs.reverse(); xs.reverse(); return xs[0]*10+xs[2]; }", 13),
    ],
)
def test_list_reverse_swaps_in_place(source: str, expected: int) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == expected
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == expected


def test_phase_3a_optimizers_preserve_allocations_reads_and_mutations() -> None:
    source = """
int main() {
    List<int> a = {1, 2, 3};
    List<int> b = a.copy();
    boolean before = b.contains(1);
    b.reverse();
    boolean after = b.contains(1);
    if (before == after) { return b[0]; }
    return 0;
}
"""
    optimized_ir = OptimizerPipeline().run(_lower(source))
    optimized_ssa = SSAOptimizerPipeline().run(_ssa(source))

    assert any(isinstance(item, IRListCopy) for item in _instructions(optimized_ir))
    assert any(isinstance(item, IRListReverse) for item in _instructions(optimized_ir))
    assert sum(isinstance(item, IRListContains) for item in _instructions(optimized_ir)) == 2
    assert any(isinstance(item, SSAListCopy) for item in _instructions(optimized_ssa))
    assert any(isinstance(item, SSAListReverse) for item in _instructions(optimized_ssa))
    assert sum(isinstance(item, SSAListContains) for item in _instructions(optimized_ssa)) == 2


def test_list_index_of_reads_are_preserved_around_set_and_reverse() -> None:
    source = """
int main() {
    List<int> xs = {1, 2, 3};
    int before_set = xs.indexOf(1);
    xs[0] = 2;
    int after_set = xs.indexOf(1);
    int before_reverse = xs.indexOf(3);
    xs.reverse();
    int after_reverse = xs.indexOf(3);
    return (before_set + 1) * 1000 + (after_set + 1) * 100 + (before_reverse + 1) * 10 + after_reverse;
}
"""
    optimized_ir = OptimizerPipeline().run(_lower(source))
    optimized_ssa = SSAOptimizerPipeline().run(_ssa(source))

    assert sum(isinstance(item, IRListIndexOf) for item in _instructions(optimized_ir)) == 4
    assert sum(isinstance(item, SSAListIndexOf) for item in _instructions(optimized_ssa)) == 4
    assert IRInterpreter(optimized_ir).call("main") == 1030


def test_list_index_of_llvm_text_emit_and_clang(tmp_path) -> None:
    source = "int main(){ List<int> xs={9,8,7}; return xs.indexOf(8); }"
    typed = _typed(source)
    llvm = print_llvm(_ssa(source))

    assert "define private i32 @aether_list_index_of_int" in llvm
    assert "call i32 @aether_list_index_of_int" in llvm
    assert "ret i32 -1" in llvm

    program = tmp_path / "list_index_of.ae"
    program.write_text(source + "\n", encoding="utf-8")
    stdout = StringIO()
    stderr = StringIO()
    assert main(["--emit-llvm", str(program)], stdout=stdout, stderr=stderr) == EXIT_SUCCESS
    assert "@aether_list_index_of_int" in stdout.getvalue()
    assert stderr.getvalue() == ""
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == 1


def test_phase_3a_llvm_text_and_emit_llvm(tmp_path) -> None:
    source = "int main(){ List<int> a={1,2,3}; List<int> b=a.copy(); b.reverse(); if(b.contains(2)){return b[0];} return 0; }"
    llvm = print_llvm(_ssa(source))

    assert "define private ptr @aether_list_copy" in llvm
    assert "@llvm.memcpy.p0.p0.i64" in llvm
    assert "define private i1 @aether_list_contains_int" in llvm
    assert "define private void @aether_list_reverse" in llvm

    program = tmp_path / "list_phase_3a.ae"
    program.write_text(source + "\n", encoding="utf-8")
    stdout = StringIO()
    stderr = StringIO()
    assert main(["--emit-llvm", str(program)], stdout=stdout, stderr=stderr) == EXIT_SUCCESS
    assert "@aether_list_copy" in stdout.getvalue()
    assert "@aether_list_contains_int" in stdout.getvalue()
    assert "@aether_list_reverse" in stdout.getvalue()
    assert stderr.getvalue() == ""
