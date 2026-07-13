from __future__ import annotations

import pytest

from aether.errors import AetherRuntimeError, AetherSyntaxError, AetherTypeError
from aether import ast
from aether.pipeline import parse_source
from aether.runner import run_aether
from aether.types import ArrayType, ListType, MatrixType, VectorType


def test_list_literal_declaration_and_zero_based_indexing() -> None:
    result = run_aether("List<int> xs = {1, 2, 3}; println(xs[0]);")

    assert result.env["xs"].type_name == ListType("int")
    assert result.output == "1\n"


def test_braced_literal_defaults_to_list_without_expected_type() -> None:
    result = run_aether("xs = {1, 2, 3}; println(xs);")

    assert result.env["xs"].type_name == ListType("int")
    assert result.output == "{1, 2, 3}\n"


def test_var_declaration_syntax_is_not_supported() -> None:
    with pytest.raises(AetherSyntaxError):
        run_aether("var xs = {1, 2, 3};")


def test_braced_literal_uses_list_and_array_expected_types() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2, 3};
Array<int> ys = {4, 5, 6};
println(xs);
println(ys);
"""
    )

    assert result.env["xs"].type_name == ListType("int")
    assert result.env["ys"].type_name == ArrayType("int")
    assert result.output == "{1, 2, 3}\n{4, 5, 6}\n"


def test_braced_literal_uses_function_parameter_context_for_list_and_array() -> None:
    result = run_aether(
        """
void f(List<int> xs) {
    println(xs);
}

void g(Array<int> xs) {
    println(xs);
}

f({1, 2, 3});
g({4, 5, 6});
"""
    )

    assert result.output == "{1, 2, 3}\n{4, 5, 6}\n"


def test_braced_literal_uses_return_context_for_list_and_array() -> None:
    result = run_aether(
        """
List<int> makeList() {
    return {1, 2, 3};
}

Array<int> makeArray() {
    return {4, 5, 6};
}

println(makeList());
println(makeArray());
"""
    )

    assert result.output == "{1, 2, 3}\n{4, 5, 6}\n"


def test_empty_braced_literal_uses_expected_type_in_parameters_returns_and_fields() -> None:
    result = run_aether(
        """
struct Lists {
    List<int> xs;
    Array<int> ys;
}

List<int> emptyList() {
    return {};
}

Array<int> emptyArray() {
    return {};
}

void showList(List<int> xs) {
    println(length(xs));
}

void showArray(Array<int> xs) {
    println(length(xs));
}

Lists lists = Lists({}, {});
showList({});
showArray({});
println(length(emptyList()));
println(length(emptyArray()));
println(lists.xs);
println(lists.ys);
"""
    )

    assert result.output == "0\n0\n0\n0\n{}\n{}\n"


def test_braced_literal_uses_field_assignment_context_for_list_and_array() -> None:
    result = run_aether(
        """
struct Lists {
    List<int> xs;
    Array<int> ys;
}

Lists lists = Lists({1}, {2});
lists.xs = {3, 4};
lists.ys = {5, 6};
println(lists.xs);
println(lists.ys);
lists.xs = {};
lists.ys = {};
println(lists.xs);
println(lists.ys);
"""
    )

    assert result.output == "{3, 4}\n{5, 6}\n{}\n{}\n"


def test_push_pop_work_on_inferred_braced_literal_list() -> None:
    result = run_aether(
        """
xs = {1, 2};
push(xs, 3);
println(pop(xs));
println(xs);
"""
    )

    assert result.env["xs"].type_name == ListType("int")
    assert result.output == "3\n{1, 2}\n"


def test_list_string_literal_and_formatting() -> None:
    result = run_aether('List<string> names = {"Ana", "Luis"}; println(names);')

    assert result.env["names"].type_name == ListType("string")
    assert result.output == '{"Ana", "Luis"}\n'


def test_list_assignment_aliases_mutable_reference() -> None:
    result = run_aether(
        """
List<int> a = {1, 2, 3};
List<int> b = a;
b[0] = 9;
println(a);
println(b);
"""
    )

    assert result.output == "{9, 2, 3}\n{9, 2, 3}\n"


def test_list_parameter_aliases_mutable_reference() -> None:
    result = run_aether(
        """
void setFirst(List<int> xs) {
    xs[0] = 9;
}

List<int> a = {1, 2, 3};
setFirst(a);
println(a);
"""
    )

    assert result.output == "{9, 2, 3}\n"


def test_list_return_aliases_mutable_reference() -> None:
    result = run_aether(
        """
List<int> same(List<int> xs) {
    return xs;
}

List<int> a = {1, 2, 3};
List<int> b = same(a);
b[0] = 9;
println(a);
println(b);
"""
    )

    assert result.output == "{9, 2, 3}\n{9, 2, 3}\n"


def test_list_copy_is_shallow_for_nested_reference_elements() -> None:
    result = run_aether(
        """
List<List<int>> xs = {{1}, {2}};
List<List<int>> ys = copy(xs);
ys[0][0] = 9;
println(xs);
println(ys);
ys[0] = {7};
println(xs);
println(ys);
"""
    )

    assert result.output == "{{9}, {2}}\n{{9}, {2}}\n{{9}, {2}}\n{{7}, {2}}\n"


def test_const_list_alias_blocks_that_reference_only() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'c'"):
        run_aether(
            """
List<int> a = {1, 2, 3};
const List<int> c = a;
c[0] = 9;
"""
        )

    result = run_aether(
        """
List<int> a = {1, 2, 3};
const List<int> c = a;
a[0] = 9;
println(c);
"""
    )

    assert result.output == "{9, 2, 3}\n"


def test_struct_value_copy_preserves_list_reference_field() -> None:
    result = run_aether(
        """
struct Box {
    List<int> items;
}

List<int> xs = {1, 2};
Box a = Box(xs);
Box b = a;
b.items[0] = 9;
println(xs);
println(a.items);
println(b.items);
"""
    )

    assert result.output == "{9, 2}\n{9, 2}\n{9, 2}\n"


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
    assert result.output == "{1, 2, 3}\n1\n{9, 2, 3}\n3\n"


def test_other_mutable_aggregates_alias_by_assignment() -> None:
    result = run_aether(
        """
Array<int> a = {1, 2};
Array<int> b = a;
b[0] = 9;
println(a);

Vector<int> v = [1, 2];
Vector<int> w = v;
w[1] = 9;
println(v);

Matrix<int> A = [1 2; 3 4];
Matrix<int> B = A;
B[1, 1] = 9;
println(A);
"""
    )

    assert result.output == "{9, 2}\n[9 2]\n[9 2; 3 4]\n"


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
    assert result.output == "{9, 2, 3}\n{100, 2, 3}\n"


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


@pytest.mark.parametrize("call", ["push(a, 4)", "pop(a)", "insert(a, 0, 9)", "remove_at(a, 0)", "clear(a)", "reverse(a)"])
def test_array_rejects_list_mutation_builtins(call: str) -> None:
    with pytest.raises(AetherTypeError, match="expects a List argument, got 'Array<int>'"):
        run_aether(f"Array<int> a = {{1, 2, 3}}; {call};")


def test_array_double_accepts_int_literals() -> None:
    result = run_aether("Array<double> a = {1, 2.5}; println(a);")

    assert result.env["a"].type_name == ArrayType("double")
    assert result.output == "{1.0, 2.5}\n"


def test_array_string_literal_works() -> None:
    result = run_aether('Array<string> s = {"a", "b"}; println(s[1]); println(s);')

    assert result.env["s"].type_name == ArrayType("string")
    assert result.output == "b\n{\"a\", \"b\"}\n"


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
    assert result.output == "{{1, 2}, {3, 4}}\n3\n{{1, 9}, {3, 4}}\n"


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

    assert result.output == "{4, 5}\n{1, 2, 3}\n"


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

    assert result.output == "{1, 2}\n"


def test_array_slicing_returns_an_independent_array() -> None:
    result = run_aether(
        "Array<int> a = {1, 2, 3}; Array<int> b = a[0:2]; b[0] = 9; println(a[0]); println(b[0]);"
    )

    assert result.output.splitlines() == ["1", "9"]


def test_list_literal_rejects_incompatible_elements() -> None:
    with pytest.raises(AetherTypeError, match="List literals must contain homogeneous compatible element types"):
        run_aether('List<int> xs = {1, "a"};')


def test_vector_and_list_literals_do_not_cross_assign() -> None:
    with pytest.raises(AetherTypeError, match="List<int>.*Vector<int>"):
        run_aether("Vector<int> v = {1, 2, 3};")

    with pytest.raises(AetherTypeError, match="Vector<int>.*List<int>"):
        run_aether("List<int> xs = [1, 2, 3];")


def test_parser_accepts_row_vector_type_annotation_and_literal_ast() -> None:
    program = parse_source("Vector<int, Row> v = [1, 2, 3];")
    declaration = program.statements[0]

    assert isinstance(declaration, ast.VarDeclaration)
    assert declaration.type_name == VectorType("int", orientation="row")
    assert isinstance(declaration.initializer, ast.MatrixLiteral)
    assert declaration.initializer.rows == [[ast.Literal(1, "int"), ast.Literal(2, "int"), ast.Literal(3, "int")]]
    assert declaration.initializer.orientation == "row"
    assert declaration.initializer.uses_commas is True


def test_parser_accepts_column_vector_type_annotation_with_comma_literal_ast() -> None:
    program = parse_source("Vector<int, Column> v = [1, 2, 3];")
    declaration = program.statements[0]

    assert isinstance(declaration, ast.VarDeclaration)
    assert declaration.type_name == VectorType("int", orientation="column")
    assert isinstance(declaration.initializer, ast.MatrixLiteral)
    assert declaration.initializer.rows == [[ast.Literal(1, "int"), ast.Literal(2, "int"), ast.Literal(3, "int")]]
    assert declaration.initializer.orientation == "row"
    assert declaration.initializer.uses_commas is True


def test_parser_accepts_column_vector_literal_ast() -> None:
    program = parse_source("c = [1; 2; 3];")
    assignment = program.statements[0]

    assert isinstance(assignment, ast.Assignment)
    assert isinstance(assignment.expression, ast.MatrixLiteral)
    assert assignment.expression.rows == [[ast.Literal(1, "int")], [ast.Literal(2, "int")], [ast.Literal(3, "int")]]
    assert assignment.expression.vector is True
    assert assignment.expression.orientation == "column"
    assert assignment.expression.uses_commas is False


def test_parser_accepts_comma_rows_as_matrix_literal_ast() -> None:
    program = parse_source("A = [1, 2; 3, 4];")
    assignment = program.statements[0]

    assert isinstance(assignment, ast.Assignment)
    assert isinstance(assignment.expression, ast.MatrixLiteral)
    assert assignment.expression.rows == [
        [ast.Literal(1, "int"), ast.Literal(2, "int")],
        [ast.Literal(3, "int"), ast.Literal(4, "int")],
    ]
    assert assignment.expression.vector is False
    assert assignment.expression.orientation is None
    assert assignment.expression.uses_commas is True


def test_row_vector_literal_infers_vector_type_without_expected_type() -> None:
    result = run_aether("v = [1, 2, 3];")

    assert result.env["v"].type_name == VectorType("int", 3, "row")


def test_column_vector_literal_infers_vector_type_without_expected_type() -> None:
    result = run_aether("c = [1; 2; 3];")

    assert result.env["c"].type_name == VectorType("int", 3, "column")


def test_row_vector_literal_uses_row_vector_expected_type() -> None:
    result = run_aether("Vector<int, Row> v = [1, 2, 3];")

    assert result.env["v"].type_name == VectorType("int", 3, "row")


def test_comma_vector_literal_uses_column_vector_expected_type() -> None:
    result = run_aether("Vector<int, Column> v = [1, 2, 3];")

    assert result.env["v"].type_name == VectorType("int", 3, "column")


def test_comma_vector_literal_uses_column_vector_parameter_type() -> None:
    result = run_aether(
        """
int first(Vector<int, Column> values) {
    return values[1];
}
answer = first([1, 2, 3]);
"""
    )

    assert result.env["answer"].value == 1


def test_row_vector_literal_rejects_incompatible_expected_type() -> None:
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'Vector<int>' to 'Array<int>'"):
        run_aether("Array<int> xs = [1, 2, 3];")


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


def test_column_vector_literal_uses_column_vector_expected_type() -> None:
    result = run_aether("Vector<int, Column> v = [1; 2; 3];")

    assert result.env["v"].type_name == VectorType("int", 3, "column")


def test_comma_matrix_literal_infers_matrix_type_without_expected_type() -> None:
    result = run_aether("A = [1, 2; 3, 4];")

    assert result.env["A"].type_name == MatrixType("int", 2, 2)


def test_comma_matrix_literal_uses_matrix_expected_type() -> None:
    result = run_aether("Matrix<int> A = [1, 2; 3, 4];")

    assert result.env["A"].type_name == MatrixType("int", 2, 2)


def test_comma_matrix_literal_rejects_ragged_rows() -> None:
    with pytest.raises(AetherTypeError, match="Matrix literals must be rectangular"):
        run_aether("Matrix<int> A = [1, 2; 3];")


def test_comma_matrix_literal_rejects_heterogeneous_elements() -> None:
    with pytest.raises(AetherTypeError, match="homogeneous compatible"):
        run_aether('Matrix<int> A = [1, "x"; 3, 4];')


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
println(xs.is_empty);
println(empty.is_empty);
"""
    )

    assert result.output == "3\nfalse\ntrue\nfalse\ntrue\n"


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


def test_list_native_length_property() -> None:
    result = run_aether("List<int> xs = {1, 2, 3}; println(xs.length);")

    assert result.output == "3\n"


def test_list_native_copy_method_creates_new_container() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2};
List<int> ys = xs.copy();
ys[0] = 9;
println(xs);
println(ys);
"""
    )

    assert result.env["ys"].type_name == ListType("int")
    assert result.output == "{1, 2}\n{9, 2}\n"


def test_list_native_reverse_and_sort_mutate_in_place() -> None:
    result = run_aether(
        """
List<int> xs = {3, 1, 2};
xs.reverse();
println(xs);
xs.sort();
println(xs);
"""
    )

    assert result.output == "{2, 1, 3}\n{1, 2, 3}\n"


def test_list_native_mutating_methods_reject_const_root() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        run_aether("const List<int> xs = {1, 2}; xs.reverse();")


def test_list_native_readonly_members_accept_const_root() -> None:
    result = run_aether(
        """
const List<int> xs = {1, 2};
List<int> ys = xs.copy();
ys[0] = 9;
println(xs.length);
println(xs);
println(ys);
"""
    )

    assert result.output == "2\n{1, 2}\n{9, 2}\n"


def test_array_native_length_and_copy() -> None:
    result = run_aether(
        """
Array<int> a = {1, 2, 3};
Array<int> b = a.copy();
b[0] = 9;
println(a.length);
println(a);
println(b);
"""
    )

    assert result.env["b"].type_name == ArrayType("int")
    assert result.output == "3\n{1, 2, 3}\n{9, 2, 3}\n"


def test_matrix_native_dimensions_and_transpose() -> None:
    result = run_aether(
        """
Matrix<double> A = [1 2; 3 4];
Matrix<double> B = A.transpose();
println(A.rows);
println(A.columns);
println(B);
"""
    )

    assert result.env["B"].type_name == MatrixType("double", 2, 2)
    assert result.output == "2\n2\n[1.0 3.0; 2.0 4.0]\n"


def test_vector_native_length_and_norm() -> None:
    result = run_aether("Vector<double, Row> v = [3 4]; println(v.length); println(v.norm());")

    assert result.output == "2\n5.0\n"


def test_native_property_called_as_method_fails_clearly() -> None:
    with pytest.raises(AetherTypeError, match="length is a property, not a method"):
        run_aether("List<int> xs = {1, 2}; xs.length();")


def test_native_method_used_as_value_fails_clearly() -> None:
    with pytest.raises(AetherTypeError, match="copy is a method and must be called"):
        run_aether("List<int> xs = {1, 2}; println(xs.copy);")


def test_native_unknown_property_and_method_fail() -> None:
    with pytest.raises(AetherTypeError, match="has no native property 'unknown'"):
        run_aether("List<int> xs = {1, 2}; println(xs.unknown);")

    with pytest.raises(AetherTypeError, match="has no native method 'unknown'"):
        run_aether("List<int> xs = {1, 2}; xs.unknown();")


def test_native_methods_do_not_accept_explicit_receiver_argument() -> None:
    with pytest.raises(AetherTypeError, match="copy\\(\\.\\.\\.\\) expects exactly one argument"):
        run_aether("List<int> xs = {1, 2}; xs.copy(xs);")


def test_function_style_builtins_still_work_with_native_members() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
List<int> xs = {3, 1, 2};
println(length(xs));
List<int> ys = copy(xs);
reverse(ys);
sort(xs);
Matrix<double> A = [1 2; 3 4];
println(ys);
println(xs);
println(rows(A));
println(columns(A));
println(transpose(A));
"""
    )

    assert result.output == "3\n{2, 1, 3}\n{1, 2, 3}\n2\n2\n[1.0 3.0; 2.0 4.0]\n"


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
