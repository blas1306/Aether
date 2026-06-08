from __future__ import annotations

import pytest

from aether.errors import AetherRuntimeError, AetherSyntaxError, AetherTypeError
from aether.runner import run_aether
from aether.types import ArrayType, ListType, MatrixType, VectorType


def test_list_literal_declaration_and_zero_based_indexing() -> None:
    result = run_aether("List<int> xs = {1, 2, 3}; println(xs[0]);")

    assert result.env["xs"].type_name == ListType("int")
    assert result.output == "1\n"


def test_list_string_literal_and_formatting() -> None:
    result = run_aether('List<string> names = {"Ana", "Luis"}; println(names);')

    assert result.env["names"].type_name == ListType("string")
    assert result.output == '{"Ana", "Luis"}\n'


def test_array_literal_declaration_read_write_and_length() -> None:
    result = run_aether(
        """
Array<int> a = {1, 2, 3};
println(a);
println(a[0]);
a[0] = 9;
println(a);
println(length(a));
"""
    )

    assert result.env["a"].type_name == ArrayType("int")
    assert result.output == "Array{1, 2, 3}\n1\nArray{9, 2, 3}\n3\n"


def test_copy_array_creates_new_container() -> None:
    result = run_aether(
        """
Array<int> a = {9, 2, 3};
Array<int> b = copy(a);
b[0] = 100;
println(a);
println(b);
"""
    )

    assert result.env["b"].type_name == ArrayType("int")
    assert result.output == "Array{9, 2, 3}\nArray{100, 2, 3}\n"


def test_const_array_blocks_index_assignment() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'a'"):
        run_aether("const Array<int> a = {1, 2, 3}; a[0] = 9;")


def test_array_index_bounds_match_list_bounds() -> None:
    with pytest.raises(AetherRuntimeError, match="Array index 3 out of bounds for length 3"):
        run_aether("Array<int> a = {1, 2, 3}; println(a[3]);")

    with pytest.raises(AetherRuntimeError, match="Array index 3 out of bounds for length 3"):
        run_aether("Array<int> a = {1, 2, 3}; a[3] = 9;")


def test_array_literal_rejects_wrong_element_type() -> None:
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'List<double>' to 'Array<int>'"):
        run_aether("Array<int> a = {1, 2.5};")


def test_array_index_assignment_rejects_wrong_element_type() -> None:
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'double' to 'int'"):
        run_aether("Array<int> a = {1, 2, 3}; a[0] = 2.5;")


def test_list_and_array_do_not_cross_assign() -> None:
    with pytest.raises(AetherTypeError, match="Array<int>.*List<int>"):
        run_aether("Array<int> a = {1, 2, 3}; List<int> xs = a;")

    with pytest.raises(AetherTypeError, match="List<int>.*Array<int>"):
        run_aether("List<int> xs = {1, 2, 3}; Array<int> a = xs;")


@pytest.mark.parametrize("call", ["push(a, 4)", "pop(a)", "insert(a, 0, 9)", "remove_at(a, 0)", "clear(a)", "reverse(a)", "sort(a)"])
def test_array_rejects_list_mutation_builtins(call: str) -> None:
    with pytest.raises(AetherTypeError, match="expects a List argument, got 'Array<int>'"):
        run_aether(f"Array<int> a = {{1, 2, 3}}; {call};")


def test_array_double_accepts_int_literals() -> None:
    result = run_aether("Array<double> a = {1, 2.5}; println(a);")

    assert result.env["a"].type_name == ArrayType("double")
    assert result.output == "Array{1.0, 2.5}\n"


def test_array_string_literal_works() -> None:
    result = run_aether('Array<string> s = {"a", "b"}; println(s[1]); println(s);')

    assert result.env["s"].type_name == ArrayType("string")
    assert result.output == "b\nArray{\"a\", \"b\"}\n"


def test_nested_array_literal_works() -> None:
    result = run_aether(
        """
Array<Array<int>> xss = {{1, 2}, {3, 4}};
println(xss);
println(xss[1][0]);
xss[0][1] = 9;
println(xss);
"""
    )

    assert result.env["xss"].type_name == ArrayType(ArrayType("int"))
    assert result.output == "Array{Array{1, 2}, Array{3, 4}}\n3\nArray{Array{1, 9}, Array{3, 4}}\n"


def test_array_brace_literal_uses_function_and_return_type_context() -> None:
    result = run_aether(
        """
Array<int> make() {
    return {1, 2, 3};
}

void show(Array<int> xs) {
    println(xs);
}

show({4, 5});
println(make());
"""
    )

    assert result.output == "Array{4, 5}\nArray{1, 2, 3}\n"


def test_array_brace_literal_uses_struct_field_context() -> None:
    result = run_aether(
        """
struct Box {
    Array<int> items;
}

Box box = Box({1, 2});
println(box.items);
"""
    )

    assert result.output == "Array{1, 2}\n"


def test_array_slicing_is_not_supported_yet() -> None:
    with pytest.raises(AetherTypeError, match="Cannot slice value of type 'Array<int>'"):
        run_aether("Array<int> a = {1, 2, 3}; a[0:1];")


def test_list_literal_rejects_incompatible_elements() -> None:
    with pytest.raises(AetherTypeError, match="List literals must contain homogeneous compatible element types"):
        run_aether('List<int> xs = {1, "a"};')


def test_vector_and_list_literals_do_not_cross_assign() -> None:
    with pytest.raises(AetherTypeError, match="List<int>.*Vector<int>"):
        run_aether("Vector<int> v = {1, 2, 3};")

    with pytest.raises(AetherTypeError, match="Vector<int>.*List<int>"):
        run_aether("List<int> xs = [1, 2, 3];")


def test_row_vector_literals_use_commas_or_spaces() -> None:
    comma = run_aether("Vector<int> v = [1, 2, 3]; println(v); println(v[1]);")
    spaces = run_aether("Vector<int> v = [1 2 3]; println(v); println(v[1]);")

    assert comma.env["v"].type_name == VectorType("int", 3, "row")
    assert spaces.env["v"].type_name == VectorType("int", 3, "row")
    assert comma.output == "[1 2 3]\n1\n"
    assert spaces.output == "[1 2 3]\n1\n"


def test_column_vector_literal_uses_semicolons() -> None:
    result = run_aether("Vector<int> v = [1; 2; 3]; println(v); println(v[1]);")

    assert result.env["v"].type_name == VectorType("int", 3, "column")
    assert result.output == "[1; 2; 3]\n1\n"


def test_matrix_literal_and_one_based_indexing() -> None:
    result = run_aether("Matrix<int> A = [1 2; 3 4]; println(A[1, 1]);")

    assert result.env["A"].type_name == MatrixType("int", 2, 2)
    assert result.output == "1\n"


def test_list_and_vector_index_bases_are_distinct() -> None:
    result = run_aether(
        """
List<int> xs = {10, 20};
Vector<int> v = [10 20];
println(xs[0]);
println(v[1]);
"""
    )

    assert result.output == "10\n10\n"


def test_list_slice_start_end_is_inclusive_and_zero_based() -> None:
    result = run_aether(
        """
List<int> xs = {10, 20, 30, 40, 50};
List<int> a = xs[1:3];
println(a);
"""
    )

    assert result.env["a"].type_name == ListType("int")
    assert result.output == "{20, 30, 40}\n"


def test_list_slice_start_step_end_is_inclusive() -> None:
    result = run_aether(
        """
List<int> xs = {10, 20, 30, 40, 50};
List<int> b = xs[0:2:4];
println(b);
"""
    )

    assert result.output == "{10, 30, 50}\n"


def test_list_slice_negative_step_walks_backwards() -> None:
    result = run_aether(
        """
List<int> xs = {10, 20, 30, 40, 50};
List<int> c = xs[4:-1:2];
println(c);
"""
    )

    assert result.output == "{50, 40, 30}\n"


def test_list_slice_can_copy_whole_container() -> None:
    result = run_aether(
        """
List<int> xs = {10, 20, 30, 40, 50};
List<int> d = xs[0:length(xs)-1];
println(d);
"""
    )

    assert result.output == "{10, 20, 30, 40, 50}\n"


def test_list_slice_result_is_new_container() -> None:
    result = run_aether(
        """
List<int> xs = {10, 20, 30};
List<int> ys = xs[0:2];
ys[0] = 99;
println(xs);
println(ys);
"""
    )

    assert result.output == "{10, 20, 30}\n{99, 20, 30}\n"


def test_list_slice_step_zero_is_runtime_error() -> None:
    with pytest.raises(AetherRuntimeError, match="slice step cannot be 0"):
        run_aether("List<int> xs = {10, 20, 30, 40}; xs[0:0:3];")


def test_list_slice_negative_index_is_runtime_error() -> None:
    with pytest.raises(AetherRuntimeError, match="negative list slice index"):
        run_aether("List<int> xs = {10, 20, 30}; xs[-1:2];")


def test_list_slice_out_of_range_index_is_runtime_error() -> None:
    with pytest.raises(AetherRuntimeError, match="List slice index 3 out of bounds for length 3"):
        run_aether("List<int> xs = {10, 20, 30}; xs[0:3];")


def test_slice_on_non_list_indexing_context_fails() -> None:
    with pytest.raises(AetherTypeError, match="Cannot index non-indexable value"):
        run_aether("int x = 1; x[0:0];")


def test_unsupported_list_slice_forms_fail() -> None:
    for source in (
        "List<int> xs = {10, 20, 30}; xs[:3];",
        "List<int> xs = {10, 20, 30}; xs[1:];",
        "List<int> xs = {10, 20, 30}; xs[:];",
    ):
        with pytest.raises((AetherSyntaxError, AetherTypeError)):
            run_aether(source)


def test_list_requires_commas() -> None:
    with pytest.raises(AetherSyntaxError, match="Expected ',' between list elements"):
        run_aether("x = {1 2 3};")


def test_list_length_and_is_empty_builtins() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2, 3};
List<int> empty = {};
println(length(xs));
println(is_empty(xs));
println(is_empty(empty));
"""
    )

    assert result.output == "3\nfalse\ntrue\n"


def test_push_appends_and_preserves_list_type() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2};
push(xs, 3);
println(xs);
"""
    )

    assert result.env["xs"].type_name == ListType("int")
    assert result.output == "{1, 2, 3}\n"


def test_pop_returns_last_element_and_mutates_list() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2, 3};
int x = pop(xs);
println(x);
println(xs);
"""
    )

    assert result.output == "3\n{1, 2}\n"


def test_pop_empty_list_is_runtime_error() -> None:
    with pytest.raises(AetherRuntimeError, match="pop\\(\\) cannot be used on an empty List"):
        run_aether("List<int> xs = {}; pop(xs);")


def test_insert_at_start_middle_and_end() -> None:
    result = run_aether(
        """
List<int> xs = {20, 40};
insert(xs, 0, 10);
insert(xs, 2, 30);
insert(xs, length(xs), 50);
println(xs);
"""
    )

    assert result.output == "{10, 20, 30, 40, 50}\n"


def test_insert_out_of_bounds_is_runtime_error() -> None:
    with pytest.raises(AetherRuntimeError, match="insert\\(\\) index must be between 0 and length\\(xs\\)"):
        run_aether("List<int> xs = {1, 2}; insert(xs, 3, 99);")


def test_remove_at_start_middle_and_end() -> None:
    result = run_aether(
        """
List<int> xs = {10, 20, 30, 40, 50};
println(remove_at(xs, 0));
println(remove_at(xs, 1));
println(remove_at(xs, length(xs) - 1));
println(xs);
"""
    )

    assert result.output == "10\n30\n50\n{20, 40}\n"


def test_remove_at_out_of_bounds_is_runtime_error() -> None:
    with pytest.raises(AetherRuntimeError, match="remove_at\\(\\) index 5 out of bounds for List of length 3"):
        run_aether("List<int> xs = {1, 2, 3}; remove_at(xs, 5);")


def test_contains_returns_true_and_false() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2, 3};
println(contains(xs, 2));
println(contains(xs, 9));
"""
    )

    assert result.output == "true\nfalse\n"


def test_clear_empties_list() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2, 3};
clear(xs);
println(length(xs));
println(xs);
"""
    )

    assert result.output == "0\n{}\n"


def test_copy_preserves_list_type_and_contents() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2};
List<int> ys = copy(xs);
println(xs);
println(ys);
"""
    )

    assert result.env["ys"].type_name == ListType("int")
    assert result.output == "{1, 2}\n{1, 2}\n"


def test_copy_is_shallow_container_copy() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2};
List<int> ys = copy(xs);
ys[0] = 9;
println(xs);
println(ys);
"""
    )

    assert result.output == "{1, 2}\n{9, 2}\n"


def test_copy_accepts_const_list() -> None:
    result = run_aether(
        """
const List<int> xs = {1, 2};
List<int> ys = copy(xs);
ys[0] = 9;
println(xs);
println(ys);
"""
    )

    assert result.output == "{1, 2}\n{9, 2}\n"


def test_reverse_mutates_list_in_place() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2, 3};
reverse(xs);
println(xs);
"""
    )

    assert result.output == "{3, 2, 1}\n"


@pytest.mark.parametrize(
    ("type_name", "values", "expected"),
    [
        ("int", "{3, 1, 2}", "{1, 2, 3}"),
        ("double", "{3.0, 1.5, 2.25}", "{1.5, 2.25, 3.0}"),
        ("string", '{"b", "a", "c"}', '{"a", "b", "c"}'),
    ],
)
def test_sort_mutates_supported_list_types(type_name: str, values: str, expected: str) -> None:
    result = run_aether(
        f"""
List<{type_name}> xs = {values};
sort(xs);
println(xs);
"""
    )

    assert result.output == f"{expected}\n"


@pytest.mark.parametrize("call", ["reverse(xs)", "sort(xs)"])
def test_reorder_builtins_reject_const_list_root(call: str) -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        run_aether(f"const List<int> xs = {{1, 2, 3}}; {call};")


@pytest.mark.parametrize(
    "source",
    [
        "List<boolean> xs = {true, false}; sort(xs);",
        "List<List<int>> xs = {{2}, {1}}; sort(xs);",
    ],
)
def test_sort_rejects_unsupported_list_element_types(source: str) -> None:
    with pytest.raises(AetherTypeError, match="sort\\(\\.\\.\\.\\) only supports"):
        run_aether(source)


def test_list_mutation_builtins_reject_wrong_value_type() -> None:
    with pytest.raises(AetherTypeError, match="push\\(\\.\\.\\.\\) value of type 'string' is not assignable to 'int'"):
        run_aether('List<int> xs = {1}; push(xs, "bad");')

    with pytest.raises(AetherTypeError, match="insert\\(\\.\\.\\.\\) value of type 'string' is not assignable to 'int'"):
        run_aether('List<int> xs = {1}; insert(xs, 0, "bad");')


def test_list_mutation_builtins_reject_wrong_index_type() -> None:
    with pytest.raises(AetherTypeError, match="remove_at\\(\\) index must be int"):
        run_aether('List<int> xs = {1}; remove_at(xs, "0");')


def test_list_mutation_builtins_reject_vector_and_matrix() -> None:
    with pytest.raises(AetherTypeError, match="push\\(\\.\\.\\.\\) expects a List argument, got 'Vector<int>'"):
        run_aether("Vector<int> v = [1, 2]; push(v, 3);")

    with pytest.raises(AetherTypeError, match="pop\\(\\.\\.\\.\\) expects a List argument, got 'Matrix<int>'"):
        run_aether("Matrix<int> A = [1 2; 3 4]; pop(A);")


@pytest.mark.parametrize(
    "call",
    [
        "push(xs, 4)",
        "pop(xs)",
        "insert(xs, 1, 4)",
        "remove_at(xs, 0)",
        "clear(xs)",
    ],
)
def test_list_mutation_builtins_reject_const_list_root(call: str) -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        run_aether(f"const List<int> xs = {{1, 2, 3}}; {call};")


def test_list_mutation_builtin_rejects_const_indexed_root() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xss'"):
        run_aether(
            """
const List<List<int>> xss = {{1, 2}, {3, 4}};
push(xss[0], 9);
"""
        )


def test_index_assignment_rejects_const_list_root() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        run_aether(
            """
const List<int> xs = {1, 2, 3};
xs[0] = 9;
"""
        )


def test_matrix_index_assignment_rejects_const_matrix_root() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'A'"):
        run_aether(
            """
const Matrix<int> A = [1 2; 3 4];
A[1, 1] = 9;
"""
        )


def test_index_assignment_rejects_const_vector_root() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'v'"):
        run_aether(
            """
const Vector<int> v = [1, 2];
v[1] = 9;
"""
        )


def test_nested_index_assignment_rejects_const_root() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        run_aether(
            """
const List<List<int>> xs = {{1}, {2}};
xs[0][0] = 9;
"""
        )


def test_index_assignment_allows_mutable_list_root() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2, 3};
xs[0] = 9;
println(xs);
"""
    )

    assert result.output == "{9, 2, 3}\n"


def test_const_list_alias_blocks_const_root_but_not_mutable_alias() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'zs'"):
        run_aether(
            """
List<int> ys = {1, 2, 3};
const List<int> zs = ys;
zs[0] = 9;
"""
        )

    result = run_aether(
        """
List<int> ys = {1, 2, 3};
const List<int> zs = ys;
ys[0] = 9;
push(ys, 4);
println(ys);
println(zs);
"""
    )

    assert result.output == "{9, 2, 3, 4}\n{9, 2, 3, 4}\n"


def test_slice_assignment_error_is_preserved() -> None:
    with pytest.raises(AetherTypeError, match="Slice assignment is not supported yet\\."):
        run_aether("List<int> xs = {1, 2, 3}; xs[0:3] = 9;")


def test_ragged_matrix_literal_is_rejected() -> None:
    with pytest.raises(AetherTypeError, match="rectangular|ragged"):
        run_aether("Matrix<int> A = [1 2; 3];")
