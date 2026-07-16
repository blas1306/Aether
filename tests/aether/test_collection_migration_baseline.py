from __future__ import annotations

from io import StringIO
import shutil

import pytest

from aether.backend.llvm import LLVMBuilder, LLVMRunner
from aether.capabilities import BackendCapabilityError, Capability
from aether.errors import AetherTypeError
from aether.ir import IRInterpreter
from aether.pipeline import IRBackend, prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _ir_output(source: str) -> str:
    interpreter = IRInterpreter(IRBackend().lower_verified(_typed(source)))
    assert interpreter.call("main") == 0
    return interpreter.output


def _assert_current_output_on_all_backends(source: str, expected: str) -> None:
    assert run_aether(source).output == expected
    assert _ir_output(source) == expected
    if shutil.which("clang") is None:
        return
    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue() == expected
    assert stderr.getvalue() == ""


def test_migration_baseline_assignment_parameters_returns_and_struct_fields_alias() -> None:
    source = """
struct Box { List<int> values; }

List<int> identity(List<int> values) { return values; }
List<int> field(Box box) { return box.values; }
void append(List<int> values) { values.push(3); }
void rebind(List<int> values) { values = {9}; values.push(10); }

int main() {
    List<int> a = {1, 2};
    List<int> assigned = a;
    assigned[0] = 7;
    append(a);
    rebind(a);
    List<int> returned = identity(a);
    returned[1] = 8;
    Box box = Box(a);
    Box copied_box = box;
    List<int> copied_field = copied_box.values;
    copied_field.push(4);
    List<int> returned_field = field(box);
    returned_field[0] = 6;
    println(a);
    return 0;
}
"""

    _assert_current_output_on_all_backends(source, "{6, 8, 3, 4}\n")


def test_migration_baseline_array_assignment_copies_the_handle_and_aliases() -> None:
    source = """
int main() {
    Array<int> original = {1, 2, 3};
    Array<int> assigned = original;
    assigned[1] = 9;
    println(original);
    return 0;
}
"""

    _assert_current_output_on_all_backends(source, "{1, 9, 3}\n")


def test_migration_baseline_explicit_list_copy_is_outer_only() -> None:
    source = """
int main() {
    List<List<int>> original = {{1}, {2}};
    List<List<int>> copied = original.copy();
    copied[0][0] = 9;
    copied[1] = {8};
    println(original[0][0]);
    println(original[1][0]);
    println(copied[0][0]);
    println(copied[1][0]);
    return 0;
}
"""

    _assert_current_output_on_all_backends(
        source,
        "9\n2\n9\n8\n",
    )


def test_migration_baseline_const_is_binding_constness_not_transitive_immutability() -> None:
    source = """
int main() {
    List<int> mutable = {1};
    const List<int> view = mutable;
    mutable.push(2);
    println(view);
    return 0;
}
"""

    _assert_current_output_on_all_backends(source, "{1, 2}\n")
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'view'"):
        _typed("int main() { const List<int> view = {1}; view.push(2); return 0; }")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "int main() { List<int> xs = {1}; for int x in xs { xs.push(2); } return 0; }",
            "Cannot structurally mutate collection 'xs'",
        ),
        (
            "int main() { List<List<int>> xs = {{1}}; for List<int> x in xs { x.push(2); } return 0; }",
            "Cannot mutate borrowed loop variable 'x'",
        ),
    ],
)
def test_migration_baseline_for_in_rejects_unambiguous_borrow_mutation(
    source: str,
    message: str,
) -> None:
    with pytest.raises(AetherTypeError, match=message):
        _typed(source)


def test_migration_baseline_for_in_explicit_alias_uses_normal_reference_semantics() -> None:
    source = """
int main() {
    List<List<int>> values = {{1}, {2}};
    for List<int> borrowed in values {
        List<int> saved = borrowed;
        saved.push(9);
    }
    println(values[0][0]);
    println(values[0][1]);
    println(values[1][0]);
    println(values[1][1]);
    return 0;
}
"""

    _assert_current_output_on_all_backends(source, "1\n9\n2\n9\n")


def test_migration_baseline_array_slice_is_half_open_and_independent() -> None:
    source = """
int main() {
    Array<int> values = {10, 20, 30};
    Array<int> empty = values[0:0];
    Array<int> whole = values[0:3];
    Array<int> middle = values[1:3];
    middle[0] = 99;
    println(empty);
    println(whole);
    println(middle);
    println(values);
    return 0;
}
"""

    _assert_current_output_on_all_backends(
        source,
        "{}\n{10, 20, 30}\n{99, 30}\n{10, 20, 30}\n",
    )


def test_migration_baseline_list_slice_is_half_open_and_backend_complete() -> None:
    source = """
int main() {
    List<int> values = {10, 20, 30, 40};
    println(values[0:0]);
    println(values[1:3]);
    println(values[4:4]);
    return 0;
}
"""

    _assert_current_output_on_all_backends(source, "{}\n{20, 30}\n{}\n")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "int main() { List<int> a = {1}; List<int> b = {1}; println(a == b); return 0; }",
            "true\n",
        ),
        (
            "int main() { Array<int> a = {1}; Array<int> b = {1}; println(a != b); return 0; }",
            "false\n",
        ),
        (
            "struct Item { int value; } int main() { List<Item> xs = {Item(1)}; println(xs.contains(Item(1))); return 0; }",
            "true\n",
        ),
    ],
)
def test_migration_baseline_eq_operations_are_supported_end_to_end(
    source: str,
    expected: str,
) -> None:
    _assert_current_output_on_all_backends(source, expected)


def test_migration_baseline_collection_equality_is_structural_in_ast() -> None:
    source = """
struct Pair { int left; string right; }
int main() {
    List<Pair> a = {Pair(1, "x")};
    List<Pair> b = {Pair(1, "x")};
    List<List<int>> nested_a = {{1}, {2}};
    List<List<int>> nested_b = {{1}, {2}};
    println(a == b);
    println(nested_a == nested_b);
    nested_b[1][0] = 3;
    println(nested_a != nested_b);
    return 0;
}
"""

    assert run_aether(source).output == "true\ntrue\ntrue\n"


def test_migration_baseline_search_uses_structural_eq_for_nested_collections() -> None:
    source = """
int main() {
    List<int> nested = {1};
    List<List<int>> values = {nested};
    List<int> equal_but_distinct = {1};
    println(values.contains(nested));
    println(values.contains(equal_but_distinct));
    println(values.indexOf(nested));
    println(values.indexOf(equal_but_distinct));
    return 0;
}
"""

    _assert_current_output_on_all_backends(source, "true\ntrue\n0\n0\n")


def test_migration_baseline_string_elements_survive_copy_set_and_clear() -> None:
    source = """
int main() {
    List<string> values = {"one", "two"};
    List<string> copied = values.copy();
    values[0] = "changed";
    values.clear();
    println(copied[0]);
    println(copied[1]);
    println(values.length);
    return 0;
}
"""

    _assert_current_output_on_all_backends(source, "one\ntwo\n0\n")
