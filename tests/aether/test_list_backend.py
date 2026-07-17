from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether.backend.llvm import LLVMRunner, print_llvm
from aether.cli import EXIT_SUCCESS, main
from aether.errors import AetherTypeError
from aether.ir import (
    IRInterpreter,
    IRExecutionError,
    IRListContains,
    IRListClear,
    IRListPop,
    IRListPush,
    IRListInsert,
    IRListRemoveAt,
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
    SSAListClear,
    SSAListPop,
    SSAListPush,
    SSAListInsert,
    SSAListRemoveAt,
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

    assert "%AetherList = type { i64, i64, ptr, i64 }" in llvm
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
    assert "%AetherList = type { i64, i64, ptr, i64 }" in stdout.getvalue()
    assert "@aether_list_new(i64 4, i64 3)" in stdout.getvalue()
    assert "@aether_checked_allocation_bytes" in stdout.getvalue()
    assert "call i32 @aether_list_length_to_int" in stdout.getvalue()
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

    assert "%AetherList = type { i64, i64, ptr, i64 }" in llvm
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
    assert "define private void @aether_list_check_index" in stdout.getvalue()
    assert stdout.getvalue().count("call void @aether_list_check_index") == 2
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
        ("int main(){ List<List<int>> xs={{1}}; List<int> other={1}; if(xs.contains(other)){return 5;} return 0; }", 5),
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
        ("int main(){ List<List<int>> xs={{1}}; List<int> other={1}; return xs.indexOf(other)+1; }", 1),
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
    assert "ret i64 -1" in llvm
    assert "call i32 @aether_list_index_to_int" in llvm

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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int main(){ List<int> xs={}; xs.clear(); return xs.length; }", 0),
        ("int main(){ List<int> xs={1,2,3}; xs.clear(); return xs.length; }", 0),
        ("int main(){ List<int> xs={1}; xs.clear(); xs.clear(); if(xs.is_empty){return 7;} return 0; }", 7),
        ("int main(){ List<int> xs={3,1,2}; xs[0]=9; xs.reverse(); xs.sort(); xs.clear(); return xs.length; }", 0),
        ("int main(){ List<int> xs={1,2}; xs.clear(); int count=0; for int x in xs { count=count+1; } return count; }", 0),
    ],
)
def test_list_clear_runtime_semantics(source: str, expected: int) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == expected
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == expected


@pytest.mark.parametrize(
    "source",
    [
        "int main(){ List<int> a={1,2,3}; List<int> b=a; b.clear(); return a.length+b.length; }",
        "int wipe(List<int> xs){ xs.clear(); return 0; } int main(){ List<int> a={1,2,3}; int ignored=wipe(a); return a.length; }",
        "List<int> identity(List<int> xs){ return xs; } int main(){ List<int> a={1,2,3}; List<int> b=identity(a); b.clear(); return a.length; }",
    ],
)
def test_list_clear_is_observed_through_aliases(source: str) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == 0
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == 0


def test_list_clear_is_void_and_rejects_const_receiver() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        _typed("int main(){ const List<int> xs={1,2,3}; xs.clear(); return 0; }")
    with pytest.raises(AetherTypeError, match="void"):
        _typed("int main(){ List<int> xs={1}; int result=xs.clear(); return result; }")


def test_list_clear_lowers_prints_and_verifies_ir_and_ssa() -> None:
    source = "int main(){ List<int> xs={1,2,3}; xs.clear(); return xs.length; }"
    ir = IRVerifier(_lower(source)).verify()
    ssa = SSAVerifier(_ssa(source)).verify()

    assert any(isinstance(item, IRListClear) for item in _instructions(ir))
    assert any(isinstance(item, SSAListClear) for item in _instructions(ssa))
    assert "list_clear" in print_ir(ir)
    assert "list_clear" in print_ssa(ssa)
    assert IRInterpreter(ir).call("main") == 0


def test_optimizers_preserve_clear_and_distinct_reads_around_it() -> None:
    source = "int main(){ List<int> xs={1,2,3}; int before=xs.length; xs.clear(); int after=xs.length; return before*10+after; }"
    optimized_ir = OptimizerPipeline().run(_lower(source))
    optimized_ssa = SSAOptimizerPipeline().run(_ssa(source))

    assert any(isinstance(item, IRListClear) for item in _instructions(optimized_ir))
    assert any(isinstance(item, SSAListClear) for item in _instructions(optimized_ssa))
    assert sum(isinstance(item, IRListLength) for item in _instructions(optimized_ir)) == 2
    assert sum(isinstance(item, SSAListLength) for item in _instructions(optimized_ssa)) == 2
    assert IRInterpreter(optimized_ir).call("main") == 30


def test_list_clear_llvm_only_stores_zero_to_length() -> None:
    llvm = print_llvm(_ssa("int main(){ List<int> xs={1,2,3}; xs.clear(); return xs.length; }"))
    clear_lines = [line.strip() for line in llvm.splitlines() if "list.clear." in line]

    assert clear_lines == [
        "%list.clear.length_field.5 = getelementptr %AetherList, ptr %0, i32 0, i32 0",
        "store i64 0, ptr %list.clear.length_field.5",
    ]
    assert "@aether_list_clear" not in llvm


def test_list_clear_emit_llvm_and_clang(tmp_path) -> None:
    source = "int main(){ List<int> xs={1,2,3}; xs.clear(); if(xs.is_empty){return 6;} return 0; }"
    program = tmp_path / "list_clear.ae"
    program.write_text(source + "\n", encoding="utf-8")
    stdout = StringIO()
    stderr = StringIO()

    assert main(["--emit-llvm", str(program)], stdout=stdout, stderr=stderr) == EXIT_SUCCESS
    emitted = stdout.getvalue()
    assert "store i64 0, ptr %list.clear.length_field." in emitted
    assert "@aether_list_clear" not in emitted
    assert stderr.getvalue() == ""
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(_typed(source)) == 6


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int main(){ List<int> xs={}; xs.push(10); return xs[0]; }", 10),
        ("int main(){ List<int> xs={}; xs.push(1); xs.push(2); return xs[1]; }", 2),
        ("int main(){ List<int> xs={7}; xs.push(xs[0]); return xs[1]; }", 7),
        ("int main(){ List<int> xs={}; xs.push(1); xs.push(2); xs.push(3); xs.push(4); xs.push(5); return xs[0]+xs[4]; }", 6),
        ("int main(){ List<int> xs={1,2,3}; xs.clear(); xs.push(9); return xs.length*10+xs[0]; }", 19),
        ("int main(){ List<int> xs={3,1,2}; xs.sort(); xs.push(4); xs.reverse(); xs.push(5); return xs[0]*10+xs[4]; }", 45),
        ("int main(){ List<int> xs={1}; xs.push(2); xs.push(3); int sum=0; for int x in xs { sum=sum+x; } return sum; }", 6),
        ("int main(){ List<List<int>> refs={}; List<int> inner={}; refs.push(inner); inner.push(7); return refs[0][0]; }", 7),
    ],
)
def test_list_push_runtime_semantics(source: str, expected: int) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == expected
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int main(){ List<int> a={1,2}; List<int> b=a; b.push(3); return a.length*10+a[2]; }", 33),
        ("int append(List<int> xs){ xs.push(3); return 0; } int main(){ List<int> a={1,2}; int ignored=append(a); return a.length*10+a[2]; }", 33),
        ("List<int> identity(List<int> xs){ return xs; } int main(){ List<int> a={1,2}; List<int> b=identity(a); b.push(3); return a.length*10+a[2]; }", 33),
    ],
)
def test_list_push_is_observed_through_aliases(source: str, expected: int) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == expected
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == expected


def test_list_push_is_void_typed_and_rejects_invalid_uses() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        _typed("int main(){ const List<int> xs={1}; xs.push(2); return 0; }")
    with pytest.raises(AetherTypeError, match="not assignable to 'int'"):
        _typed('int main(){ List<int> xs={1}; xs.push("bad"); return 0; }')
    with pytest.raises(AetherTypeError, match="void"):
        _typed("int main(){ List<int> xs={1}; int result=xs.push(2); return result; }")


def test_list_push_lowers_prints_and_verifies_ir_and_ssa() -> None:
    source = "int main(){ List<int> xs={}; xs.push(3); return xs[0]; }"
    ir = IRVerifier(_lower(source)).verify()
    ssa = SSAVerifier(_ssa(source)).verify()

    assert any(isinstance(item, IRListPush) for item in _instructions(ir))
    assert any(isinstance(item, SSAListPush) for item in _instructions(ssa))
    assert "list_push" in print_ir(ir)
    assert "list_push" in print_ssa(ssa)
    assert IRInterpreter(ir).call("main") == 3


def test_optimizers_preserve_push_and_reads_around_it() -> None:
    source = "int main(){ List<int> xs={1,2}; int before=xs.length; int old=xs[0]; xs.push(3); int after=xs.length; int now=xs[2]; return before*10+after+old+now; }"
    optimized_ir = OptimizerPipeline().run(_lower(source))
    optimized_ssa = SSAOptimizerPipeline().run(_ssa(source))

    assert any(isinstance(item, IRListPush) for item in _instructions(optimized_ir))
    assert any(isinstance(item, SSAListPush) for item in _instructions(optimized_ssa))
    assert sum(isinstance(item, IRListLength) for item in _instructions(optimized_ir)) == 2
    assert sum(isinstance(item, SSAListLength) for item in _instructions(optimized_ssa)) == 2
    assert sum(isinstance(item, IRListGet) for item in _instructions(optimized_ir)) == 2
    assert sum(isinstance(item, SSAListGet) for item in _instructions(optimized_ssa)) == 2
    assert IRInterpreter(optimized_ir).call("main") == 27


def test_list_push_llvm_contains_checked_growth_and_reloads_data() -> None:
    llvm = print_llvm(_ssa("int main(){ List<int> xs={}; xs.push(7); return xs[0]; }"))

    assert "define private void @aether_list_reserve" in llvm
    assert "@llvm.uadd.with.overflow.i64" in llvm
    assert llvm.count("@llvm.umul.with.overflow.i64") >= 3
    assert "select i1 %required_is_larger" in llvm
    assert "%grown_capacity = phi i64 [ 1, %from_zero ], [ %doubled, %doubled_ok ]" in llvm
    assert "@llvm.umul.with.overflow.i64(i64 %capacity, i64 2)" in llvm
    assert "call void @free(ptr %old_data)" in llvm
    call_index = llvm.index("call i64 @aether_list_prepare_push")
    reload_index = llvm.index("load ptr, ptr %list.push.data_field", call_index)
    store_index = llvm.index("store i32 7", reload_index)
    length_index = llvm.index("store i64 %list.push.new_length", store_index)
    assert call_index < reload_index < store_index < length_index
    assert "Aether panic: List capacity overflow" in llvm
    assert "Aether panic: memory allocation failed" in llvm
    assert "%failed = icmp eq ptr %mem, null" in llvm
    assert "br i1 %failed, label %panic, label %ok" in llvm


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int main(){ List<int> xs={}; xs.insert(0,7); return xs.length*10+xs[0]; }", 17),
        ("int main(){ List<int> xs={20,30}; xs.insert(0,10); return xs[0]+xs[1]+xs[2]; }", 60),
        ("int main(){ List<int> xs={10,30}; insert(xs,1,20); return xs.length*10+xs[1]; }", 50),
        ("int main(){ List<int> xs={10,20}; xs.insert(xs.length,30); return xs[2]; }", 30),
        ("int main(){ List<int> xs={}; xs.insert(0,2); xs.insert(0,1); xs.insert(2,4); xs.insert(2,3); int sum=0; for int x in xs {sum=sum*10+x;} return sum; }", 1234),
        ("int main(){ List<int> xs={1,2}; xs.push(3); xs.pop(); xs.insert(1,9); return xs[0]*100+xs[1]*10+xs[2]; }", 192),
        ("int main(){ List<int> xs={3,1,2}; xs.sort(); xs.reverse(); xs.insert(1,9); return xs[0]*10+xs[1]; }", 39),
        ("int main(){ List<int> xs={1,2}; xs.clear(); xs.insert(0,8); return xs.length*10+xs[0]; }", 18),
        ("int main(){ List<int> xs={1,3}; if(xs.contains(2)){return 99;} int result=xs.length*100+xs.indexOf(3)*10; xs.insert(1,2); result=result+xs.length*100+xs.indexOf(3)*10; if(xs.contains(2)){result=result+1;} return result; }", 531),
        ("int main(){ List<double> xs={1.5,3.5}; xs.insert(1,2.5); return int(xs[1]*10.0)+xs.length; }", 28),
        ("int main(){ List<boolean> xs={false}; xs.insert(0,true); if(xs[0]){if(xs[1]){return 0;} return xs.length;} return 0; }", 2),
        ('int main(){ List<string> xs={"a","c"}; xs.insert(1,"b"); return xs.length; }', 3),
        ("int main(){ List<List<int>> xs={}; List<int> inner={1}; xs.insert(0,inner); List<int> got=xs[0]; got.push(2); return inner.length; }", 2),
    ],
)
def test_list_insert_runtime_semantics(source: str, expected: int) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == expected
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == expected % 256


@pytest.mark.parametrize(
    "source",
    [
        "int main(){ List<int> a={1,3}; List<int> b=a; b.insert(1,2); return a.length*10+a[1]; }",
        "int add(List<int> xs){xs.insert(1,2); return 0;} int main(){List<int> a={1,3}; int ignored=add(a); return a.length*10+a[1];}",
        "List<int> identity(List<int> xs){return xs;} int main(){List<int> a={1,3}; List<int> b=identity(a); b.insert(1,2); return a.length*10+a[1];}",
    ],
)
def test_list_insert_is_observed_through_aliases(source: str) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == 32
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == 32


def test_list_insert_typing_arity_const_and_void_result() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        _typed("int main(){ const List<int> xs={1}; xs.insert(0,2); return 0; }")
    with pytest.raises(AetherTypeError, match="index must be int"):
        _typed('int main(){ List<int> xs={1}; xs.insert("0",2); return 0; }')
    with pytest.raises(AetherTypeError, match="not assignable to 'int'"):
        _typed('int main(){ List<int> xs={1}; xs.insert(0,"bad"); return 0; }')
    with pytest.raises(AetherTypeError, match="expects exactly three arguments"):
        _typed("int main(){ List<int> xs={1}; xs.insert(0); return 0; }")
    with pytest.raises(AetherTypeError, match="void"):
        _typed("int main(){ List<int> xs={1}; int result=xs.insert(0,2); return result; }")


def test_list_insert_lowers_prints_interprets_and_verifies_ir_and_ssa() -> None:
    source = "int main(){ List<int> xs={1,3}; xs.insert(1,2); return xs[1]; }"
    ir = IRVerifier(_lower(source)).verify()
    ssa = SSAVerifier(_ssa(source)).verify()

    assert any(isinstance(item, IRListInsert) for item in _instructions(ir))
    assert any(isinstance(item, SSAListInsert) for item in _instructions(ssa))
    assert "list_insert" in print_ir(ir)
    assert "list_insert" in print_ssa(ssa)
    assert IRInterpreter(ir).call("main") == 2


def test_optimizers_preserve_insert_and_reads_around_it() -> None:
    source = "int main(){ List<int> xs={1,3}; int before=xs.length; int old=xs[1]; xs.insert(1,2); int after=xs.length; int now=xs[1]; return before*10+after+old+now; }"
    optimized_ir = OptimizerPipeline().run(_lower(source))
    optimized_ssa = SSAOptimizerPipeline().run(_ssa(source))

    assert any(isinstance(item, IRListInsert) for item in _instructions(optimized_ir))
    assert any(isinstance(item, SSAListInsert) for item in _instructions(optimized_ssa))
    assert sum(isinstance(item, IRListLength) for item in _instructions(optimized_ir)) == 2
    assert sum(isinstance(item, SSAListLength) for item in _instructions(optimized_ssa)) == 2
    assert sum(isinstance(item, IRListGet) for item in _instructions(optimized_ir)) == 2
    assert sum(isinstance(item, SSAListGet) for item in _instructions(optimized_ssa)) == 2
    assert IRInterpreter(optimized_ir).call("main") == 28


@pytest.mark.parametrize("index", [-1, 3])
def test_list_insert_invalid_index_panics_before_mutation(index: int) -> None:
    source = f"int main(){{ List<int> xs={{1,2}}; xs.insert({index},9); return xs.length; }}"
    with pytest.raises(IRExecutionError, match=r"Aether panic: insert\(\) index is out of bounds"):
        IRInterpreter(_lower(source)).call("main")

    if shutil.which("clang") is not None:
        stdout = StringIO()
        assert LLVMRunner().run(_typed(source), stdout=stdout) == 1
        assert stdout.getvalue() == "Aether panic: insert() index is out of bounds\n"


def test_list_insert_llvm_uses_reserve_memmove_and_updates_length_last() -> None:
    llvm = print_llvm(_ssa("int main(){ List<int> xs={1,3}; xs.insert(1,2); return xs[1]; }"))

    assert "define private void @aether_list_reserve" in llvm
    assert "define private i64 @aether_list_prepare_insert" in llvm
    assert "@llvm.memmove.p0.p0.i64" in llvm
    assert "%nonnegative = icmp sge i64 %index, 0" in llvm
    assert "%within_length = icmp ule i64 %index, %length" in llvm
    call_index = llvm.index("call i64 @aether_list_prepare_insert")
    reload_index = llvm.index("load ptr, ptr %list.insert.data_field", call_index)
    move_index = llvm.index("call void @llvm.memmove", reload_index)
    value_index = llvm.index("store i32 2", move_index)
    length_index = llvm.index("store i64 %list.insert.new_length", value_index)
    assert call_index < reload_index < move_index < value_index < length_index


def test_list_insert_emit_llvm_and_clang(tmp_path) -> None:
    source = "int main(){ List<int> xs={10,30}; xs.insert(1,20); return xs[0]+xs[1]+xs[2]; }"
    program = tmp_path / "list_insert.ae"
    program.write_text(source + "\n", encoding="utf-8")
    stdout = StringIO()
    stderr = StringIO()

    assert main(["--emit-llvm", str(program)], stdout=stdout, stderr=stderr) == EXIT_SUCCESS
    assert "@aether_list_prepare_insert" in stdout.getvalue()
    assert "@llvm.memmove.p0.p0.i64" in stdout.getvalue()
    assert stderr.getvalue() == ""
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(_typed(source)) == 60


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int main(){ List<int> xs={7}; int r=xs.removeAt(0); return r+xs.length; }", 7),
        ("int main(){ List<int> xs={10,20,30}; int r=xs.removeAt(0); return r+xs[0]+xs[1]+xs.length; }", 62),
        ("int main(){ List<int> xs={10,20,30,40}; int r=xs.removeAt(2); return r+xs[2]+xs.length; }", 73),
        ("int main(){ List<int> xs={10,20,30}; int r=remove_at(xs,2); return r+xs.length; }", 32),
        ("int main(){ List<double> xs={1.5,2.5}; double r=xs.removeAt(0); return int(r*10.0)+xs.length; }", 16),
        ("int main(){ List<boolean> xs={false,true}; boolean r=xs.removeAt(1); if(r){return xs.length;} return 0; }", 1),
        ('int main(){ List<string> xs={"a","b"}; string r=xs.removeAt(0); return xs.length; }', 1),
        ("int main(){ List<List<int>> xs={}; List<int> inner={1}; xs.push(inner); List<int> r=xs.removeAt(0); r.push(2); return inner.length; }", 2),
        ("int main(){ List<int> xs={1,3}; xs.insert(1,2); xs.removeAt(1); xs.push(4); xs.pop(); return xs.length*10+xs[1]; }", 23),
        ("int main(){ List<int> xs={3,1,2}; xs.sort(); xs.reverse(); xs.removeAt(1); return xs[0]*10+xs[1]; }", 31),
        ("int main(){ List<int> xs={1,2,3}; xs.removeAt(0); xs.removeAt(0); xs.removeAt(0); return xs.length; }", 0),
    ],
)
def test_list_remove_at_runtime_semantics(source: str, expected: int) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == expected
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == expected % 256


@pytest.mark.parametrize(
    "source",
    [
        "int main(){ List<int> a={1,2,3}; List<int> b=a; int r=b.removeAt(1); return a.length*10+a[1]; }",
        "int drop(List<int> xs){return xs.removeAt(1);} int main(){List<int> a={1,2,3}; int r=drop(a); return a.length*10+a[1];}",
        "List<int> identity(List<int> xs){return xs;} int main(){List<int> a={1,2,3}; List<int> b=identity(a); int r=b.removeAt(1); return a.length*10+a[1];}",
    ],
)
def test_list_remove_at_is_observed_through_aliases(source: str) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == 23
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == 23


def test_list_remove_at_typing_arity_and_const() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        _typed("int main(){ const List<int> xs={1}; int r=xs.removeAt(0); return r; }")
    with pytest.raises(AetherTypeError, match="index must be int"):
        _typed('int main(){ List<int> xs={1}; int r=xs.removeAt("0"); return r; }')
    with pytest.raises(AetherTypeError, match="expects exactly two arguments"):
        _typed("int main(){ List<int> xs={1}; int r=xs.removeAt(); return r; }")


def test_list_remove_at_lowers_prints_interprets_and_verifies_ir_and_ssa() -> None:
    source = "int main(){ List<int> xs={1,2,3}; int r=xs.removeAt(1); return r+xs.length; }"
    ir = IRVerifier(_lower(source)).verify()
    ssa = SSAVerifier(_ssa(source)).verify()

    assert any(isinstance(item, IRListRemoveAt) for item in _instructions(ir))
    assert any(isinstance(item, SSAListRemoveAt) for item in _instructions(ssa))
    assert "list_remove_at" in print_ir(ir)
    assert "list_remove_at" in print_ssa(ssa)
    assert IRInterpreter(ir).call("main") == 4


def test_optimizers_preserve_remove_at_when_result_is_unused() -> None:
    source = "int main(){ List<int> xs={1,2,3}; xs.removeAt(1); return xs.length*10+xs[1]; }"
    optimized_ir = OptimizerPipeline().run(_lower(source))
    optimized_ssa = SSAOptimizerPipeline().run(_ssa(source))

    assert any(isinstance(item, IRListRemoveAt) for item in _instructions(optimized_ir))
    assert any(isinstance(item, SSAListRemoveAt) for item in _instructions(optimized_ssa))
    assert IRInterpreter(optimized_ir).call("main") == 23


@pytest.mark.parametrize("index", [-1, 0, 2, 3])
def test_list_remove_at_invalid_index_panics(index: int) -> None:
    values = "" if index == 0 else "1,2"
    source = f"int main(){{ List<int> xs={{{values}}}; xs.removeAt({index}); return xs.length; }}"
    with pytest.raises(IRExecutionError, match=r"Aether panic: removeAt\(\) index is out of bounds"):
        IRInterpreter(_lower(source)).call("main")

    if shutil.which("clang") is not None:
        stdout = StringIO()
        assert LLVMRunner().run(_typed(source), stdout=stdout) == 1
        assert stdout.getvalue() == "Aether panic: removeAt() index is out of bounds\n"


def test_list_remove_at_llvm_validates_moves_and_updates_length_last() -> None:
    llvm = print_llvm(_ssa("int main(){ List<int> xs={1,2,3}; return xs.removeAt(1); }"))

    assert "define private i64 @aether_list_prepare_remove_at" in llvm
    assert "%within_length = icmp ult i64 %index, %length" in llvm
    assert "@llvm.umul.with.overflow.i64" in llvm
    assert "@llvm.memmove.p0.p0.i64" in llvm
    assert "@aether_list_reserve" not in llvm
    call_index = llvm.index("call i64 @aether_list_prepare_remove_at")
    result_index = llvm.index("load i32, ptr %list.remove_at.removed", call_index)
    move_index = llvm.index("call void @llvm.memmove", result_index)
    length_index = llvm.index("store i64 %list.remove_at.new_length", move_index)
    assert call_index < result_index < move_index < length_index


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int main(){ List<int> xs={7}; int x=xs.pop(); if(xs.is_empty){return x;} return 0; }", 7),
        ("int main(){ List<int> xs={10,20,30}; int x=xs.pop(); return x+xs.length; }", 32),
        ("int main(){ List<int> xs={1,2,3}; return xs.pop()*100+xs.pop()*10+xs.pop(); }", 321),
        ("int main(){ List<int> xs={}; xs.push(8); int x=xs.pop(); return x+xs.length; }", 8),
        ("int main(){ List<int> xs={3,1,2}; xs.sort(); xs.reverse(); int x=xs.pop(); return x*10+xs.length; }", 12),
        ("int main(){ List<int> xs={1,2,3}; int ignored=xs.pop(); int sum=0; for int x in xs {sum=sum+x;} return sum; }", 3),
        ("int main(){ List<double> xs={1.5,2.5}; double x=xs.pop(); return int(x*10.0)+xs.length; }", 26),
        ("int main(){ List<boolean> xs={false,true}; boolean x=xs.pop(); if(x){return xs.length+5;} return 0; }", 6),
        ('int main(){ List<string> xs={"a","last"}; string x=xs.pop(); return xs.length; }', 1),
        ("int main(){ List<List<int>> refs={}; List<int> inner={1}; refs.push(inner); List<int> popped=refs.pop(); popped.push(2); return inner.length; }", 2),
    ],
)
def test_list_pop_runtime_semantics(source: str, expected: int) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == expected
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == expected % 256


@pytest.mark.parametrize(
    "source",
    [
        "int main(){ List<int> a={1,2,3}; List<int> b=a; int x=b.pop(); return x*10+a.length; }",
        "int take(List<int> xs){return xs.pop();} int main(){List<int> a={1,2,3}; int x=take(a); return x*10+a.length;}",
        "List<int> identity(List<int> xs){return xs;} int main(){List<int> a={1,2,3}; List<int> b=identity(a); int x=b.pop(); return x*10+a.length;}",
    ],
)
def test_list_pop_is_observed_through_aliases(source: str) -> None:
    typed = _typed(source)
    assert IRInterpreter(_lower(source)).call("main") == 32
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == 32


def test_list_pop_typing_arity_and_const_receiver() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        _typed("int main(){ const List<int> xs={1}; return xs.pop(); }")
    with pytest.raises(AetherTypeError, match="expects exactly one argument"):
        _typed("int main(){ List<int> xs={1}; return xs.pop(2); }")
    assert _typed("int main(){ List<int> xs={1}; return xs.pop(); }")


def test_list_pop_lowers_prints_interprets_and_verifies_ir_and_ssa() -> None:
    source = "int main(){ List<int> xs={1,2,3}; int x=xs.pop(); return x+xs.length; }"
    ir = IRVerifier(_lower(source)).verify()
    ssa = SSAVerifier(_ssa(source)).verify()

    assert any(isinstance(item, IRListPop) for item in _instructions(ir))
    assert any(isinstance(item, SSAListPop) for item in _instructions(ssa))
    assert "list_pop" in print_ir(ir)
    assert "list_pop" in print_ssa(ssa)
    assert IRInterpreter(ir).call("main") == 5


def test_list_pop_empty_panics_in_ast_ir_and_llvm() -> None:
    source = "int main(){ List<int> xs={}; return xs.pop(); }"
    with pytest.raises(IRExecutionError, match=r"pop\(\) cannot be used on an empty List"):
        IRInterpreter(_lower(source)).call("main")

    if shutil.which("clang") is not None:
        stdout = StringIO()
        assert LLVMRunner().run(_typed(source), stdout=stdout) == 1
        assert stdout.getvalue() == "Aether panic: pop() cannot be used on an empty List\n"


def test_list_pop_after_clear_panics() -> None:
    source = "int main(){ List<int> xs={1}; xs.clear(); return xs.pop(); }"
    with pytest.raises(IRExecutionError, match="empty List"):
        IRInterpreter(_lower(source)).call("main")


def test_optimizers_keep_unused_list_pop_and_following_length_read() -> None:
    source = "int main(){ List<int> xs={1,2,3}; xs.pop(); return xs.length; }"
    optimized_ir = OptimizerPipeline().run(_lower(source))
    optimized_ssa = SSAOptimizerPipeline().run(_ssa(source))

    assert any(isinstance(item, IRListPop) for item in _instructions(optimized_ir))
    assert any(isinstance(item, SSAListPop) for item in _instructions(optimized_ssa))
    assert any(isinstance(item, IRListLength) for item in _instructions(optimized_ir))
    assert any(isinstance(item, SSAListLength) for item in _instructions(optimized_ssa))
    assert IRInterpreter(optimized_ir).call("main") == 2


def test_list_pop_llvm_reads_before_length_mutation_and_preserves_storage() -> None:
    llvm = print_llvm(_ssa("int main(){ List<int> xs={1,2,3}; return xs.pop(); }"))

    assert "define private i64 @aether_list_prepare_pop" in llvm
    assert "Aether panic: pop() cannot be used on an empty List" in llvm
    assert "br i1 %empty, label %panic, label %ready" in llvm
    assert llvm.index("%new_length = sub i64 %length, 1") > llvm.index("%empty = icmp eq i64 %length, 0")
    pop_start = llvm.index("call i64 @aether_list_prepare_pop")
    value_load = llvm.index("load i32, ptr %list.pop.element", pop_start)
    length_store = llvm.index("store i64 %list.pop.new_length", value_load)
    pop_body = llvm[pop_start:length_store]
    assert value_load < length_store
    assert "i32 0, i32 1" not in pop_body
    assert "store ptr" not in pop_body
    assert "@aether_list_reserve" not in llvm
    assert "call void @aether_list_release_i32" in llvm
    assert "call void @free(ptr %data)" in llvm
    assert "call void @free(ptr %object)" in llvm


def test_list_pop_emit_llvm_and_clang(tmp_path) -> None:
    source = "int main(){ List<int> xs={10,20,30}; int x=xs.pop(); return x+xs.length; }"
    program = tmp_path / "list_pop.ae"
    program.write_text(source + "\n", encoding="utf-8")
    stdout = StringIO()
    stderr = StringIO()

    assert main(["--emit-llvm", str(program)], stdout=stdout, stderr=stderr) == EXIT_SUCCESS
    assert "@aether_list_prepare_pop" in stdout.getvalue()
    assert stderr.getvalue() == ""
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(_typed(source)) == 32
