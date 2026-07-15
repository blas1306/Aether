from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil

import pytest

from aether.backend.llvm import LLVMBuilder, LLVMRunner
from aether.backend.llvm.layout import LLVMTypeLayouts
from aether.capabilities import BackendCapabilityError
from aether.ir import (
    ArrayType,
    BoolType,
    DoubleType,
    IRModule,
    IRStructDefinition,
    IRVerificationError,
    IRVerifier,
    IntType,
    StringType,
    StructType,
)
from aether.pipeline import prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker


ROOT = Path(__file__).resolve().parents[2]


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _native_output(source: str) -> str:
    if shutil.which("clang") is None:
        pytest.skip("clang is required")
    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=stdout, stderr=stderr) == 0
    assert stderr.getvalue() == ""
    return stdout.getvalue()


def test_layout_uses_llvm_target_for_padding_nested_structs_and_references() -> None:
    definitions = [
        IRStructDefinition("Inner", (("flag", BoolType()), ("amount", DoubleType()))),
        IRStructDefinition(
            "Outer",
            (("id", IntType()), ("inner", StructType("Inner")), ("name", StringType())),
        ),
    ]
    layouts = LLVMTypeLayouts(definitions)

    inner = layouts.collection_element("Array", StructType("Inner"))
    outer = layouts.collection_element("List", StructType("Outer"))

    assert inner.size_operand == "ptrtoint (ptr getelementptr (%struct.Inner, ptr null, i64 1) to i64)"
    assert outer.size_operand == "ptrtoint (ptr getelementptr (%struct.Outer, ptr null, i64 1) to i64)"
    assert inner.trivially_copyable and not inner.contains_references
    assert not outer.trivially_copyable and outer.contains_references
    assert inner.trivially_relocatable and outer.trivially_relocatable
    assert not inner.needs_destroy and outer.needs_destroy
    assert not inner.needs_retain and outer.needs_retain


def test_current_string_and_nested_collection_layouts_report_lifecycle_facts() -> None:
    definitions = [
        IRStructDefinition("Label", (("text", StringType()),)),
        IRStructDefinition("Record", (("label", StructType("Label")), ("values", ArrayType(IntType())))),
    ]
    layouts = LLVMTypeLayouts(definitions)

    string = layouts.layout(StringType())
    nested = layouts.collection_element("List", StructType("Record"))

    assert string.sized and not string.trivially_copyable and string.trivially_relocatable
    assert string.contains_references and string.needs_retain and string.needs_destroy
    assert nested.sized and not nested.trivially_copyable and nested.trivially_relocatable
    assert nested.contains_references and nested.needs_retain and nested.needs_destroy


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_array_of_struct_native_get_set_slice_return_print_and_value_copy() -> None:
    source = r'''
enum State { Ready, Done }
struct Label { string text; boolean visible; }
struct Record { boolean padded; double amount; State state; Label label; int count; }
alias RecordAlias = Record;

Array<Record> identity(Array<Record> values) { return values; }

int main() {
    Array<Record> values = {
        Record(true, 1.5, State.Ready, Label("one", true), 1),
        Record(false, 2.5, State.Done, Label("two", false), 2)
    };
    Record copy = values[0];
    copy.count = 99;
    println(values[0].count == 1);
    values[1] = copy;
    println(values[1].count == 99);
    println(values[1].label.text);
    println(values[0].state == State.Ready);
    Array<Record> sliced = values[0:2];
    sliced[0] = Record(true, 7.5, State.Done, Label("slice", true), 7);
    println(values[0].count == 1);
    println(sliced[0].count == 7);
    println(identity(values).length == 2);
    Array<RecordAlias> aliased = {Record(true, 3.5, State.Done, Label("alias", true), 3)};
    println(aliased[0].count == 3);
    Array<Label> printable = {Label("a", true), Label("b", false)};
    println(printable);
    return 0;
}
'''
    expected = "true\ntrue\none\ntrue\ntrue\ntrue\ntrue\ntrue\n{Label(text=a, visible=true), Label(text=b, visible=false)}\n"
    assert run_aether(source).output == expected
    assert _native_output(source) == expected

    llvm = LLVMBuilder().emit_llvm(_typed(source))
    assert "%struct.Record = type { i1, double, i32, %struct.Label, i32 }" in llvm
    assert "@aether_array_new(i64 ptrtoint (ptr getelementptr (%struct.Record" in llvm
    assert "getelementptr %struct.Record, ptr" in llvm


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_list_of_struct_native_reallocation_mutations_copy_clear_and_for_in() -> None:
    source = r'''
enum Kind { Even, Odd }
struct Entry { int value; Kind kind; string label; }

List<Entry> passThrough(List<Entry> values) { return values; }

int main() {
    List<Entry> values = {};
    int i = 0;
    while i < 20 {
        values.push(Entry(i, Kind.Even, "item"));
        i = i + 1;
    }
    values.insert(10, Entry(100, Kind.Odd, "inserted"));
    println(values.length == 21);
    println(values[10].value == 100 && values[11].value == 10);

    Entry fetched = values[0];
    fetched.value = 77;
    println(values[0].value == 0);
    values[0] = fetched;
    println(values[0].value == 77);

    List<Entry> cloned = values.copy();
    cloned[0] = Entry(88, Kind.Odd, "clone");
    println(values[0].value == 77 && cloned[0].value == 88);

    Entry removed = values.removeAt(10);
    Entry popped = values.pop();
    println(removed.value == 100 && popped.value == 19 && values.length == 19);
    values.reverse();
    println(values[0].value == 18);

    int total = 0;
    for Entry entry in passThrough(values) { total = total + entry.value; }
    println(total == 248);
    List<Entry> printable = {Entry(1, Kind.Even, "a"), Entry(2, Kind.Odd, "b")};
    println(printable);
    values.clear();
    println(values.length == 0 && values.is_empty);
    return 0;
}
'''
    expected = (
        "true\ntrue\ntrue\ntrue\ntrue\ntrue\ntrue\ntrue\n"
        "{Entry(value=1, kind=Kind.Even, label=a), Entry(value=2, kind=Kind.Odd, label=b)}\n"
        "true\n"
    )
    assert run_aether(source).output == expected
    assert _native_output(source) == expected

    llvm = LLVMBuilder().emit_llvm(_typed(source))
    struct_size = "ptrtoint (ptr getelementptr (%struct.Entry, ptr null, i64 1) to i64)"
    assert f"@aether_list_prepare_push(ptr" in llvm
    assert struct_size in llvm
    assert "@llvm.memcpy.p0.p0.i64" in llvm
    assert "@llvm.memmove.p0.p0.i64" in llvm


def test_callable_field_collection_copy_uses_capture_free_handle_layout() -> None:
    source = """
struct Bad { int(int) callback; }
int same(int value) { return value; }
int main() {
    List<Bad> values = {Bad(same)};
    List<Bad> copied = values.copy();
    return copied.length - 1;
}
"""
    typed = _typed(source)
    llvm = LLVMBuilder().emit_llvm(typed)
    assert "define private ptr @aether_list_copy_struct_" in llvm
    if shutil.which("clang") is not None:
        assert LLVMRunner().run(typed) == 0


def test_struct_collection_search_and_sort_fail_before_llvm_emission() -> None:
    for operation, reason in (("values.contains(Item(1))", "structural search"), ("values.sort()", "only supports sequences")):
        source = f"struct Item {{ int value; }} int main() {{ List<Item> values = {{Item(1)}}; {operation}; return 0; }}"
        with pytest.raises(Exception, match=reason):
            LLVMBuilder().emit_llvm(_typed(source))


def test_ir_verifier_rejects_incomplete_and_recursive_collection_layouts() -> None:
    incomplete = IRModule(structs=[IRStructDefinition("Holder", (("items", ArrayType(StructType("Missing"))),))])
    with pytest.raises(IRVerificationError, match="invalid or incomplete"):
        IRVerifier(incomplete).verify()

    recursive = IRModule(structs=[IRStructDefinition("Node", (("next", StructType("Node")),))])
    with pytest.raises(IRVerificationError, match="infinite size"):
        IRVerifier(recursive).verify()


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_particle_array_preliminary_example_matches_ast_and_native() -> None:
    source = (ROOT / "examples" / "aggregate_collections" / "particles.ae").read_text(
        encoding="utf-8"
    )
    expected = "true\ntrue\ntrue\ntrue\ntrue\n"
    assert run_aether(source).output == expected
    assert _native_output(source) == expected


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_homonymous_struct_arrays_from_distinct_modules_keep_nominal_layouts(
    tmp_path: Path,
) -> None:
    (tmp_path / "A.ae").write_text(
        "package A; public struct Item { int value; } "
        "public int first() { Array<Item> xs = {Item(1)}; return xs[0].value; }",
        encoding="utf-8",
    )
    (tmp_path / "B.ae").write_text(
        "package B; public struct Item { int value; } "
        "public int first() { Array<Item> xs = {Item(2)}; return xs[0].value; }",
        encoding="utf-8",
    )
    source = "import A; import B; int main() { println(A.first()); println(B.first()); return 0; }"
    typed = prepare_typed_program(source, TypeChecker(source_root=tmp_path))
    llvm = LLVMBuilder().emit_llvm(typed)

    assert "%struct.__ae_m1_A__struct_4_Item = type { i32 }" in llvm
    assert "%struct.__ae_m1_B__struct_4_Item = type { i32 }" in llvm
    stdout = StringIO()
    assert LLVMRunner().run(typed, stdout=stdout) == 0
    assert stdout.getvalue() == "1\n2\n"
