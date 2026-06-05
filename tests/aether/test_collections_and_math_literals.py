from __future__ import annotations

import pytest

from aether.errors import AetherRuntimeError, AetherSyntaxError, AetherTypeError
from aether.runner import run_aether
from aether.types import ListType, MatrixType, VectorType


def test_list_literal_declaration_and_zero_based_indexing() -> None:
    result = run_aether("List<int> xs = {1, 2, 3}; println(xs[0]);")

    assert result.env["xs"].type_name == ListType("int")
    assert result.output == "1\n"


def test_list_string_literal_and_formatting() -> None:
    result = run_aether('List<string> names = {"Ana", "Luis"}; println(names);')

    assert result.env["names"].type_name == ListType("string")
    assert result.output == '{"Ana", "Luis"}\n'


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


def test_list_mutation_builtins_reject_const_list() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant List 'xs' with push"):
        run_aether("const List<int> xs = {1, 2}; push(xs, 3);")


def test_ragged_matrix_literal_is_rejected() -> None:
    with pytest.raises(AetherTypeError, match="rectangular|ragged"):
        run_aether("Matrix<int> A = [1 2; 3];")
