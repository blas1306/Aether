from __future__ import annotations

from io import StringIO
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMBuilder, LLVMRunner
from aether.collection_value import CollectionObject
from aether.errors import AetherRuntimeError, AetherTypeError
from aether.interpreter import Environment
from aether.ir import (
    IRArrayGet,
    IRBasicBlock,
    IRFunction,
    IRInterpreter,
    IRModule,
    IRParameter,
    IRPrinter,
    IRReturn,
    IRValue,
)
from aether.ir.types import ArrayType as IRArrayType, IntType
from aether.ir.optimizer import build_optimizer_pipeline
from aether.ir.verifier import IRVerificationError, IRVerifier
from aether.native_members import native_method
from aether.pipeline import IRBackend, prepare_typed_program
from aether.runner import run_aether
from aether.stdlib import MutationKind, builtin_mutation
from aether.string_value import StringValue
from aether.typechecker import TypeChecker
from aether.types import AetherValue, ListType
from aether.ssa import GeneralSSABuilder
from aether.ssa.optimizer import SSAOptimizerPipeline


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _outputs(source: str) -> tuple[str, str, str | None]:
    typed = _typed(source)
    ast_output = run_aether(source).output
    interpreter = IRInterpreter(IRBackend().lower_verified(typed))
    assert interpreter.call("main") == 0
    native_output: str | None = None
    if shutil.which("clang") is not None:
        stdout = StringIO()
        stderr = StringIO()
        assert LLVMRunner().run(typed, stdout=stdout, stderr=stderr) == 0
        assert stderr.getvalue() == ""
        native_output = stdout.getvalue()
    return ast_output, interpreter.output, native_output


@pytest.mark.parametrize(
    "body",
    [
        "xs[0] = 9;",
        "xs.sort();",
        "xs.clear();",
        "xs.push(9);",
        "xs.pop();",
        "xs.insert(0, 9);",
        "xs.removeAt(0);",
    ],
)
def test_const_list_rejects_all_typed_mutations(body: str) -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        _typed(f"int main() {{ const List<int> xs = {{1, 2}}; {body} return 0; }}")


def test_const_array_rejects_set_and_sort_but_observes_mutable_alias() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'view'"):
        _typed("int main() { const Array<int> view = {2, 1}; view.sort(); return 0; }")
    source = """
int main() {
    Array<int> values = {1, 2};
    const Array<int> view = values;
    values[0] = 7;
    println(view[0]);
    return 0;
}
"""
    assert _outputs(source) == ("7\n", "7\n", "7\n" if shutil.which("clang") else None)


def test_const_depth_blocks_struct_and_nested_collection_but_not_contained_class() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        _typed(
            "struct Item { int value; } "
            "int main() { const List<Item> xs = {Item(1)}; xs[0].value = 2; return 0; }"
        )
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        _typed(
            "int main() { const List<List<int>> xs = {{1}}; xs[0].push(2); return 0; }"
        )
    _typed(
        "class Account { int amount; public constructor(int x) { amount = x; } "
        "public void deposit(int x) { amount = amount + x; } } "
        "int main() { List<Account> xs = {Account(1)}; const List<Account> view = xs; "
        "view[0].deposit(2); return 0; }"
    )


def test_for_in_rejects_direct_and_simple_alias_mutation() -> None:
    for mutation in ("xs[0] = 2;", "other[0] = 2;", "other.push(2);"):
        source = (
            "int main() { List<int> xs = {1}; List<int> other = xs; "
            f"for (int value in xs) {{ {mutation} }} return 0; }}"
        )
        with pytest.raises(AetherTypeError, match="while iterating over it"):
            _typed(source)


def test_for_in_read_only_depth_and_class_reference_barrier() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate borrowed iteration element 'item'"):
        _typed(
            "struct Item { int value; } int main() { List<Item> xs = {Item(1)}; "
            "for (Item item in xs) { item.value = 2; } return 0; }"
        )
    with pytest.raises(AetherTypeError, match="Cannot mutate borrowed iteration element 'inner'"):
        _typed(
            "int main() { List<List<int>> xs = {{1}}; "
            "for (List<int> inner in xs) { inner.push(2); } return 0; }"
        )
    _typed(
        "class Account { int amount; public constructor(int x) { amount = x; } "
        "public void deposit(int x) { amount = amount + x; } } "
        "int main() { List<Account> xs = {Account(1)}; "
        "for (Account item in xs) { item.deposit(2); } return 0; }"
    )


def test_borrow_to_owned_local_and_return_survive_iteration_and_container_clear() -> None:
    source = """
List<int> first(List<List<int>> values) {
    for (List<int> item in values) { return item; }
    return {};
}
int main() {
    List<List<int>> values = {{1, 2}};
    List<int> saved = first(values);
    values.clear();
    println(saved);
    return 0;
}
"""
    expected = "{1, 2}\n"
    assert _outputs(source) == (expected, expected, expected if shutil.which("clang") else None)


def test_ir_marks_for_in_element_borrow_without_owning_loop_storage() -> None:
    source = (
        "int main() { List<List<int>> xs = {{1}}; "
        "for (List<int> item in xs) { println(item.length); } return 0; }"
    )
    printed = IRPrinter().print_module(IRBackend().lower_verified(_typed(source)))
    assert "borrow_element list" in printed
    assert "%item:" not in printed
    assert "destroy %item" not in printed


def test_native_for_in_borrow_adds_no_element_retain_until_copy_init() -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")
    borrowed = LLVMBuilder().emit_llvm(
        _typed(
            "int main() { List<List<int>> xs = {{1}, {2}}; "
            "for (List<int> item in xs) { println(item.length); } return 0; }"
        )
    )
    copied = LLVMBuilder().emit_llvm(
        _typed(
            "int main() { List<List<int>> xs = {{1}, {2}}; "
            "for (List<int> item in xs) { List<int> saved = item; println(saved.length); } return 0; }"
        )
    )
    borrowed_retains = sum("call void @" in line and "retain" in line for line in borrowed.splitlines())
    copied_retains = sum("call void @" in line and "retain" in line for line in copied.splitlines())
    assert copied_retains == borrowed_retains + 1


def test_ast_borrow_metadata_is_non_owning_and_invalidated() -> None:
    collection = CollectionObject("List", "int", [AetherValue("int", 1)])
    value = AetherValue(ListType("int"), collection)
    env = Environment()
    env.define("item", value, is_const=True, owned=False, borrowed_iteration=True)
    assert collection.strong_count == 1
    env.cleanup()
    assert collection.strong_count == 1
    with pytest.raises(AetherRuntimeError, match="no longer valid"):
        env.get("item")
    collection.release()


def test_ast_string_borrow_acquires_owner_only_for_normal_local_copy() -> None:
    text = StringValue.dynamic("owned")
    collection = CollectionObject("List", "string", [AetherValue("string", text)])
    text.claim_owner()
    text.release()  # leave the collection as the sole owner
    assert text.strong_count == 1

    borrowed_env = Environment()
    borrowed_env.define(
        "item",
        AetherValue("string", text),
        is_const=True,
        owned=False,
        borrowed_iteration=True,
    )
    assert text.strong_count == 1
    owning_env = Environment(parent=borrowed_env)
    owning_env.define("saved", borrowed_env.get("item"))
    assert text.strong_count == 2
    owning_env.cleanup()
    assert text.strong_count == 1
    borrowed_env.cleanup()
    collection.release()
    assert text.strong_count == 0


def test_mutation_classification_is_semantic_metadata() -> None:
    assert builtin_mutation("push") is MutationKind.STRUCTURAL
    assert builtin_mutation("sort") is MutationKind.ELEMENT
    assert builtin_mutation("contains") is MutationKind.NONE
    method = native_method(ListType("int"), "removeAt")
    assert method is not None and method.mutation is MutationKind.STRUCTURAL


def test_ir_verifier_rejects_direct_borrow_escape() -> None:
    array_type = IRArrayType(IntType())
    array = IRParameter("array", array_type)
    index = IRParameter("index", IntType())
    borrowed = IRValue("borrowed", IntType())
    module = IRModule(
        [
            IRFunction(
                "bad",
                [array, index],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRArrayGet(
                                borrowed,
                                array,
                                index,
                                borrowed=True,
                                borrow_scope="entry",
                            ),
                            IRReturn(borrowed),
                        ],
                    )
                ],
            )
        ]
    )
    with pytest.raises(IRVerificationError, match="cannot escape"):
        IRVerifier(module).verify()


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
def test_borrowed_for_in_survives_optimization_profiles_and_clang(
    profile: str, tmp_path,
) -> None:
    source = """
int main() {
    List<List<int>> values = {{1}, {2}};
    int total = 0;
    for (List<int> item in values) { total = total + item[0]; }
    println(total);
    return 0;
}
"""
    backend = IRBackend()
    ir = backend.lower_verified(_typed(source))
    optimized_ir = backend.optimize_verified(
        ir, optimizer=build_optimizer_pipeline(profile)
    )
    ssa = GeneralSSABuilder().build(optimized_ir)
    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(ssa)
    llvm = LLVMBackend().emit(optimized_ssa)
    llvm_path = tmp_path / f"borrowed-for-{profile}.ll"
    executable = tmp_path / f"borrowed-for-{profile}"
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
    assert completed.stdout == "3\n"
    assert completed.stderr == ""
