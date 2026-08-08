from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMRunner
from aether.collection_value import (
    CollectionObject,
    collection_debug_counters,
    reset_collection_debug_counters,
)
from aether.errors import AetherRuntimeError, AetherTypeError
from aether.ir import (
    IRArraySlice,
    IRExecutionError,
    IRInterpreter,
    IRListSlice,
    IRVerifier,
    print_ir,
)
from aether.ir.optimizer import build_optimizer_pipeline
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import GeneralSSABuilder, SSAArraySlice, SSAListSlice, print_ssa
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


ARRAY_PANIC = "Aether panic: Array slice index out of bounds"
LIST_PANIC = "Aether panic: List slice index out of bounds"


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


@pytest.mark.parametrize("kind", ["Array", "List"])
@pytest.mark.parametrize(
    ("bounds", "expected"),
    [("0:0", "{}"), ("0:4", "{10, 20, 30, 40}"), ("4:4", "{}"), ("1:3", "{20, 30}"), ("2:3", "{30}")],
)
def test_half_open_slice_edge_cases(kind: str, bounds: str, expected: str) -> None:
    source = f"{kind}<int> xs = {{10, 20, 30, 40}}; println(xs[{bounds}]);"
    assert run_aether(source).output == f"{expected}\n"


@pytest.mark.parametrize("kind", ["Array", "List"])
@pytest.mark.parametrize("bounds", ["-1:2", "0:-1", "3:2", "5:5", "0:5"])
def test_invalid_slice_bounds_are_not_clamped(kind: str, bounds: str) -> None:
    with pytest.raises(AetherRuntimeError, match=rf"{kind} slice"):
        run_aether(f"{kind}<int> xs = {{1, 2, 3, 4}}; println(xs[{bounds}]);")


@pytest.mark.parametrize("kind", ["Array", "List"])
def test_slice_order_has_a_distinct_diagnostic(kind: str) -> None:
    with pytest.raises(AetherRuntimeError, match="start is greater than end"):
        run_aether(f"{kind}<int> xs = {{1, 2, 3}}; println(xs[2:1]);")


@pytest.mark.parametrize("kind", ["Array", "List"])
def test_slice_has_independent_outer_storage(kind: str) -> None:
    source = f"""
{kind}<int> source = {{1, 2, 3}};
{kind}<int> sliced = source[0:2];
sliced[0] = 9;
println(source);
println(sliced);
"""
    assert run_aether(source).output == "{1, 2, 3}\n{9, 2}\n"


def test_runtime_slice_has_distinct_object_buffer_and_normalized_capacity() -> None:
    source = CollectionObject("List", "int", (1, 2, 3, 4), capacity=12)
    sliced = source.logical_slice(1, 3)

    assert sliced is not source
    assert sliced.buffer is not source.buffer
    assert list(sliced) == [2, 3]
    assert sliced.capacity == sliced.size == 2
    assert sliced.strong_count == 1
    empty = source.logical_slice(source.size, source.size)
    assert empty.size == empty.capacity == 0
    sliced[0] = 9
    assert source[1] == 2

    sliced.release()
    empty.release()
    source.release()


@pytest.mark.parametrize("kind", ["Array", "List"])
def test_empty_source_slice_is_valid(kind: str) -> None:
    assert run_aether(f"{kind}<int> xs = {{}}; println(xs[0:0]);").output == "{}\n"


@pytest.mark.parametrize("kind", ["Array", "List"])
def test_slice_bounds_can_come_from_runtime_variables(kind: str) -> None:
    source = f"{kind}<int> xs = {{1, 2, 3}}; int start = 1; int end = xs.length; println(xs[start:end]);"
    assert run_aether(source).output == "{2, 3}\n"


def test_runtime_slice_rolls_back_a_partially_copied_prefix(monkeypatch) -> None:
    import aether.collection_value as runtime

    source = CollectionObject("List", "int", (1, 2, 3), capacity=8)
    original_copy_init = runtime.copy_init_value
    calls = 0

    def fail_second(value):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic slice copy failure")
        return original_copy_init(value)

    reset_collection_debug_counters()
    monkeypatch.setattr(runtime, "copy_init_value", fail_second)
    with pytest.raises(RuntimeError, match="synthetic slice copy failure"):
        source.logical_slice(0, 3)

    counters = collection_debug_counters()
    assert list(source) == [1, 2, 3]
    assert counters.objects_allocated == counters.objects_freed == 1
    assert counters.buffers_allocated == counters.buffers_freed == 1
    assert counters.elements_destroyed == 1
    source.release()
    reset_collection_debug_counters()


def test_nested_list_slice_shares_inner_handles_but_not_outer_slots() -> None:
    source = """
List<List<int>> outer = {{1}, {2}, {3}};
List<List<int>> sliced = outer[1:3];
List<int> shared = sliced[0];
shared.push(9);
sliced[1] = {7};
println(outer);
println(sliced);
"""
    assert run_aether(source).output == "{{1}, {2, 9}, {3}}\n{{2, 9}, {7}}\n"


def test_ast_slice_supports_strings_structs_classes_and_callables() -> None:
    source = r'''
struct Item { string name; int value; }
class Box { public int value; }
int twice(int value) { return value * 2; }

List<Item> items = {Item("a", 1), Item("b", 2)};
List<Item> itemSlice = items[0:1];
itemSlice[0] = Item("changed", 9);
List<Box> boxes = {Box(3), Box(4)};
List<Box> boxSlice = boxes[0:1];
Box shared = boxSlice[0];
shared.value = 8;
List<Function<(int), int>> functions = {twice};
List<Function<(int), int>> functionSlice = functions[0:1];
Function<(int), int> selected = functionSlice[0];
println(items[0].name);
println(boxes[0].value);
println(selected(5));
'''
    assert run_aether(source).output == "a\n8\n10\n"


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_slice_supports_enums_and_callables() -> None:
    source = """
enum State { Ready, Done }
int twice(int value) { return value * 2; }
int main() {
    Array<State> states = {State.Ready, State.Done};
    Array<State> stateSlice = states[1:2];
    List<Function<(int), int>> functions = {twice};
    List<Function<(int), int>> functionSlice = functions[0:1];
    Function<(int), int> selected = functionSlice[0];
    return selected(5) - 10;
}
"""
    assert LLVMRunner().run(_typed(source)) == 0


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_slice_supports_imported_struct_elements(tmp_path: Path) -> None:
    (tmp_path / "Model.ae").write_text(
        "package Model; public struct Item { string name; int value; }",
        encoding="utf-8",
    )
    source = """
from Model import Item;
int main() {
    List<Item> items = {Item("a", 1), Item("b", 2)};
    List<Item> sliced = items[0:1];
    sliced[0] = Item("changed", 9);
    println(items[0].name);
    return 0;
}
"""
    typed = prepare_typed_program(source, TypeChecker(source_root=tmp_path))
    assert run_aether(source, source_root=tmp_path).output == "a\n"
    stdout = StringIO()
    assert LLVMRunner().run(typed, stdout=stdout) == 0
    assert stdout.getvalue() == "a\n"


def test_array_and_list_slices_are_explicit_effectful_ir_and_ssa_operations() -> None:
    source = """
int main() {
    Array<int> a = {1, 2};
    List<int> xs = {3, 4};
    Array<int> b = a[0:1];
    List<int> ys = xs[0:1];
    return b[0] + ys[0];
}
"""
    ir = _ir(source)
    ssa = lower_to_verified_ssa(_typed(source))
    array_slice = next(item for item in _instructions(ir) if isinstance(item, IRArraySlice))
    list_slice = next(item for item in _instructions(ir) if isinstance(item, IRListSlice))

    assert array_slice.source_location is not None
    assert list_slice.source_location is not None
    assert (list_slice.allocates, list_slice.reads_memory, list_slice.may_trap) == (True, True, True)
    assert any(isinstance(item, SSAArraySlice) for item in _instructions(ssa))
    assert any(isinstance(item, SSAListSlice) for item in _instructions(ssa))
    assert "array_slice" in print_ir(ir) and "list_slice" in print_ir(ir)
    assert "array_slice" in print_ssa(ssa) and "list_slice" in print_ssa(ssa)


@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
@pytest.mark.parametrize("kind, instruction_type", [("Array", IRArraySlice), ("List", IRListSlice)])
def test_slice_survives_ir_optimization_profiles(profile: str, kind: str, instruction_type: type) -> None:
    source = f"int main() {{ {kind}<int> xs = {{1, 2}}; {kind}<int> ignored = xs[1:0]; return 0; }}"
    optimized = IRVerifier(build_optimizer_pipeline(profile).run(_ir(source))).verify()
    assert any(isinstance(item, instruction_type) for item in _instructions(optimized))


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_list_slice_bounds_and_runtime_helper() -> None:
    source = "int main() { List<int> xs = {1, 2, 3}; List<int> ys = xs[-1:2]; return 0; }"
    output = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=output) == 1
    assert output.getvalue() == f"{LIST_PANIC}\n"

    llvm = LLVMBackend().emit(lower_to_verified_ssa(_typed("int main(){ List<int> xs={1,2}; List<int> ys=xs[0:1]; return 0; }")))
    assert "define private ptr @aether_list_slice" in llvm
    assert "call ptr @aether_list_slice" in llvm
    assert "llvm.memcpy" in llvm


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_slices_copy_strings_structs_and_nested_collection_handles() -> None:
    source = r'''
struct Item { string name; int value; }
int main() {
    List<Item> items = {Item("a", 1), Item("b", 2)};
    List<Item> slicedItems = items[0:1];
    slicedItems[0] = Item("changed", 9);
    println(items[0].name);

    Array<string> names = {"x", "y"};
    Array<string> slicedNames = names[0:2];
    names[0] = "z";
    println(slicedNames);

    List<List<int>> outer = {{1}, {2}, {3}};
    List<List<int>> nestedSlice = outer[1:3];
    List<int> shared = nestedSlice[0];
    shared.push(9);
    nestedSlice[1] = {7};
    println(outer[1][1]);
    println(outer[2][0]);
    println(nestedSlice[1][0]);
    return 0;
}
'''
    stdout = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=stdout) == 0
    assert stdout.getvalue() == 'a\n{"x", "y"}\n9\n3\n7\n'


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_slice_return_and_borrowed_temporary_cleanup() -> None:
    source = """
List<int> middle(List<int> values) { return values[1:3]; }
int consume(List<int> values) { return values[0]; }
int main() {
    List<int> original = {1, 2, 3, 4};
    List<int> sliced = middle(original);
    int temporary = consume(original[2:4]);
    sliced[0] = 9;
    return original[1] * 100 + sliced[0] * 10 + temporary - 293;
}
"""
    assert LLVMRunner().run(_typed(source)) == 0


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
def test_list_slice_profiles_compile_with_real_clang(profile: str, tmp_path: Path) -> None:
    source = "int main(){ List<int> xs={1,2,3}; List<int> ys=xs[1:3]; ys[0]=9; return xs[1]*10+ys[0]-29; }"
    optimized_ir = IRVerifier(build_optimizer_pipeline(profile).run(_ir(source))).verify()
    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(GeneralSSABuilder().build(optimized_ir))
    llvm = LLVMBackend().emit(optimized_ssa)
    llvm_path = tmp_path / f"list-slice-{profile}.ll"
    executable = tmp_path / f"list-slice-{profile}"
    llvm_path.write_text(llvm, encoding="utf-8")
    compiled = subprocess.run(
        [shutil.which("clang") or "clang", str(llvm_path), "-o", str(executable)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    completed = subprocess.run([str(executable)], check=False, capture_output=True, text=True)
    assert completed.returncode == 0
    assert completed.stderr == ""
