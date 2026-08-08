from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMBuilder, LLVMRunner
from aether.collection_value import (
    CollectionObject,
    collection_debug_counters,
    reset_collection_debug_counters,
)
from aether.ir import (
    ArrayType,
    IRArrayCopy,
    IRArrayNew,
    IRBasicBlock,
    IRConst,
    IRFunction,
    IRInterpreter,
    IRListCopy,
    IRModule,
    IRReturn,
    IRValue,
    IRVerificationError,
    IRVerifier,
    IntType,
    ListType,
    print_ir,
)
from aether.ir.lowering import IRLowerer
from aether.ir.optimizer import build_optimizer_pipeline
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import (
    GeneralSSABuilder,
    SSAArrayCopy,
    SSABasicBlock,
    SSAConst,
    SSAFunction,
    SSAListCopy,
    SSAModule,
    SSAReturn,
    SSAValue,
    SSAVerificationError,
    SSAVerifier,
    print_ssa,
)
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


def _native_output(source: str) -> str:
    if shutil.which("clang") is None:
        pytest.skip("clang is required")
    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=stdout, stderr=stderr) == 0
    assert stderr.getvalue() == ""
    return stdout.getvalue()


@pytest.mark.parametrize("kind", ["Array", "List"])
@pytest.mark.parametrize("values", [(), (1,), (1, 2, 3)])
def test_runtime_copy_has_distinct_object_buffer_and_normalized_capacity(
    kind: str, values: tuple[int, ...]
) -> None:
    source = CollectionObject(kind, "int", values, capacity=12)
    copied = source.logical_copy()

    assert copied is not source
    assert copied.buffer is not source.buffer
    assert list(copied) == list(source)
    assert copied.strong_count == 1
    assert copied.capacity == len(values)
    if values:
        copied[0] = 99
        assert source[0] == values[0]

    copied.release()
    source.release()


def test_runtime_copy_rolls_back_live_prefix_and_preserves_source(monkeypatch) -> None:
    import aether.collection_value as runtime

    source = CollectionObject("List", "int", (1, 2, 3), capacity=9)
    original_copy_init = runtime.copy_init_value
    calls = 0

    def fail_second(value):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic copy failure")
        return original_copy_init(value)

    reset_collection_debug_counters()
    monkeypatch.setattr(runtime, "copy_init_value", fail_second)
    with pytest.raises(RuntimeError, match="synthetic copy failure"):
        source.logical_copy()

    counters = collection_debug_counters()
    assert list(source) == [1, 2, 3]
    assert source.alive and source.capacity == 9
    assert counters.objects_allocated == counters.objects_freed == 1
    assert counters.buffers_allocated == counters.buffers_freed == 1
    assert counters.elements_destroyed == 1
    source.release()
    reset_collection_debug_counters()


def test_ast_copy_is_outer_shallow_for_nested_collections_and_class_refs() -> None:
    source = """
class Box { public int value; }
List<List<int>> outer = {{1}, {2}};
List<List<int>> copied = outer.copy();
copied[0][0] = 7;
copied[0] = {9};
List<Box> boxes = {Box(1)};
List<Box> boxCopy = boxes.copy();
Box sharedBox = boxCopy[0];
sharedBox.value = 8;
println(outer[0][0] == 7 && copied[0][0] == 9);
println(boxes[0].value == 8);
"""
    assert run_aether(source).output == "true\ntrue\n"


def test_array_and_list_copy_are_explicit_typed_ir_and_ssa_allocations() -> None:
    source = """
int main() {
    Array<int> a = {1, 2};
    Array<int> b = a.copy();
    List<int> xs = {3, 4};
    List<int> ys = xs.copy();
    return b[0] + ys[0];
}
"""
    ir = _ir(source)
    ssa = lower_to_verified_ssa(_typed(source))
    array_copy = next(item for item in _instructions(ir) if isinstance(item, IRArrayCopy))

    assert array_copy.source_location is not None
    assert array_copy.result.type == array_copy.array.type
    assert any(isinstance(item, IRListCopy) for item in _instructions(ir))
    assert any(isinstance(item, SSAArrayCopy) for item in _instructions(ssa))
    assert any(isinstance(item, SSAListCopy) for item in _instructions(ssa))
    assert "array_copy" in print_ir(ir) and "array_copy" in print_ssa(ssa)
    assert IRInterpreter(ir).call("main") == 4


def test_ir_and_ssa_verifiers_reject_invalid_array_copy_receiver_and_result() -> None:
    integer = IntType()
    array_type = ArrayType(integer)
    element = IRValue("element", integer)
    array = IRValue("array", array_type)
    invalid_result = IRValue("copy", ListType(integer))
    ir = IRModule([
        IRFunction(
            "main",
            [],
            integer,
            [IRBasicBlock("entry", [
                IRConst(element, 1),
                IRArrayNew(array, (element,)),
                IRArrayCopy(invalid_result, array),
                IRReturn(element),
            ])],
        )
    ])
    with pytest.raises(IRVerificationError, match="Array copy result type mismatch"):
        IRVerifier(ir).verify()

    ssa_element = SSAValue("element", integer)
    invalid_ssa_result = SSAValue("copy", array_type)
    ssa = SSAModule([
        SSAFunction(
            "main",
            [],
            integer,
            [SSABasicBlock("entry", [
                SSAConst(ssa_element, 1),
                SSAArrayCopy(invalid_ssa_result, ssa_element),
                SSAReturn(ssa_element),
            ])],
        )
    ])
    with pytest.raises(SSAVerificationError, match="Array copy expects array value"):
        SSAVerifier(ssa).verify()


@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
def test_collection_copy_survives_ir_optimization_profiles(profile: str) -> None:
    source = "int main(){ Array<int> a={1,2}; Array<int> b=a.copy(); b[0]=9; return a[0]*10+b[0]; }"
    optimized = IRVerifier(build_optimizer_pipeline(profile).run(_ir(source))).verify()
    assert any(isinstance(item, IRArrayCopy) for item in _instructions(optimized))
    assert IRInterpreter(optimized).call("main") == 19


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_copy_handles_strings_structs_nested_collections_and_callables() -> None:
    source = r'''
struct Person { string name; int age; }
int plusOne(int value) { return value + 1; }
int twice(int value) { return value * 2; }

int main() {
    Array<Person> people = {Person("Ana", 10)};
    Array<Person> changed = people.copy();
    changed[0] = Person("Bea", 20);
    println(people[0].age == 10 && changed[0].age == 20);

    Array<List<string>> nested = {{"x"}};
    Array<List<string>> nestedCopy = nested.copy();
    List<string> sharedInner = nestedCopy[0];
    sharedInner.push("shared");
    println(nested[0].length == 2);
    nestedCopy[0] = {"replacement"};
    println(nested[0].length == 2 && nestedCopy[0].length == 1);

    List<Function<(int), int>> operations = {plusOne, twice};
    List<Function<(int), int>> operationCopy = operations.copy();
    Function<(int), int> selected = operationCopy[1];
    println(selected(4) == 8);
    return 0;
}
'''
    expected = "true\ntrue\ntrue\ntrue\n"
    assert run_aether(source).output == expected
    assert _native_output(source) == expected

    llvm = LLVMBuilder().emit_llvm(_typed(source))
    assert "define private ptr @aether_array_copy_" in llvm
    assert "define private ptr @aether_list_copy_" in llvm
    assert "copy.body:" in llvm
    assert "call void @aether_string_retain" in llvm


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("collection", ["Array", "List"])
def test_native_direct_string_and_enum_copy(collection: str) -> None:
    source = f'''
enum State {{ Ready, Done }}
int main() {{
    {collection}<string> names = {{"alpha"}};
    {collection}<string> nameCopy = names.copy();
    nameCopy[0] = "beta";
    {collection}<State> states = {{State.Ready}};
    {collection}<State> stateCopy = states.copy();
    stateCopy[0] = State.Done;
    return names.length + nameCopy.length + states.length + stateCopy.length - 4;
}}
'''
    assert LLVMRunner().run(_typed(source)) == 0
    llvm = LLVMBuilder().emit_llvm(_typed(source))
    assert f"@aether_{collection.lower()}_copy_string" in llvm
    assert f"@aether_{collection.lower()}_copy_enum_" in llvm


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("collection", ["Array", "List"])
def test_native_copy_return_and_borrowed_temporary_cleanup(collection: str) -> None:
    source = f'''
{collection}<int> duplicate({collection}<int> values) {{ return values.copy(); }}
int consume({collection}<int> values) {{ return values[0]; }}
int main() {{
    {collection}<int> original = {{1, 2}};
    {collection}<int> copied = duplicate(original);
    int temporaryValue = consume(original.copy());
    copied[0] = 9;
    return original[0] * 100 + copied[0] * 10 + temporaryValue - 191;
}}
'''
    assert LLVMRunner().run(_typed(source)) == 0


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
def test_collection_copy_profiles_compile_with_real_clang(
    profile: str, tmp_path: Path
) -> None:
    source = """
int main() {
    Array<int> original = {1, 2};
    Array<int> copied = original.copy();
    copied[0] = 9;
    return original[0] * 10 + copied[0] - 19;
}
"""
    optimized_ir = IRVerifier(build_optimizer_pipeline(profile).run(_ir(source))).verify()
    ssa = GeneralSSABuilder().build(optimized_ir)
    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(ssa)
    llvm = LLVMBackend().emit(optimized_ssa)
    llvm_path = tmp_path / f"collection-copy-{profile}.ll"
    executable = tmp_path / f"collection-copy-{profile}"
    llvm_path.write_text(llvm, encoding="utf-8")
    compiled = subprocess.run(
        [shutil.which("clang") or "clang", str(llvm_path), "-o", str(executable)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    completed = subprocess.run(
        [str(executable)], check=False, capture_output=True, text=True
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
