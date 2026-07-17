from __future__ import annotations

import pytest

from aether.errors import AetherRuntimeError, AetherTypeError
from aether.runner import run_aether
from aether.types import ListType


def test_list_push_method_appends_value() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2};
xs.push(3);
println(xs);
"""
    )

    assert result.env["xs"].type_name == ListType("int")
    assert result.output == "{1, 2, 3}\n"


def test_list_pop_method_removes_and_returns_last_value() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2, 3};
int value = xs.pop();
println(value);
println(xs);
"""
    )

    assert result.output == "3\n{1, 2}\n"


def test_list_pop_ast_interpreter_supports_scalar_and_reference_elements() -> None:
    result = run_aether(
        """
List<double> doubles = {1.5, 2.5};
List<boolean> booleans = {false, true};
List<string> strings = {"first", "last"};
List<int> inner = {1};
List<List<int>> refs = {inner};
println(doubles.pop());
println(booleans.pop());
println(strings.pop());
List<int> popped = refs.pop();
popped.push(2);
println(inner);
println(refs.is_empty);
"""
    )

    assert result.output == "2.5\ntrue\nlast\n{1, 2}\ntrue\n"


def test_list_pop_method_rejects_arguments() -> None:
    with pytest.raises(AetherTypeError, match="expects exactly one argument"):
        run_aether("List<int> xs = {1}; xs.pop(2);")


def test_list_insert_method_inserts_at_index() -> None:
    result = run_aether(
        """
List<int> xs = {20, 40};
xs.insert(0, 10);
xs.insert(2, 30);
xs.insert(xs.size(), 50);
println(xs);
"""
    )

    assert result.output == "{10, 20, 30, 40, 50}\n"


def test_list_remove_at_method_removes_and_returns_indexed_value() -> None:
    result = run_aether(
        """
List<int> xs = {10, 20, 30};
int value = xs.removeAt(1);
println(value);
println(xs);
"""
    )

    assert result.output == "20\n{10, 30}\n"


def test_list_contains_method_returns_boolean() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2, 3};
boolean present = xs.contains(2);
println(present);
println(xs.contains(9));
"""
    )

    assert result.output == "true\nfalse\n"


def test_list_index_of_returns_first_index_or_minus_one() -> None:
    result = run_aether(
        """
List<int> xs = {10, 20, 20, 30};
println(xs.indexOf(10));
println(xs.indexOf(20));
println(xs.indexOf(30));
println(xs.indexOf(99));
List<int> empty = {};
println(empty.indexOf(1));
"""
    )

    assert result.output == "0\n1\n3\n-1\n-1\n"


def test_list_index_of_ast_interpreter_uses_eq_for_scalars_and_nested_lists() -> None:
    result = run_aether(
        """
List<double> doubles = {1.5, 2.5};
List<boolean> booleans = {true, false};
List<string> strings = {"a", "bb"};
List<List<int>> refs = {{1}};
List<int> same = refs[0];
List<int> other = {1};
println(doubles.indexOf(2.5));
println(booleans.indexOf(false));
println(strings.indexOf("bb"));
println(refs.indexOf(same));
println(refs.indexOf(other));
"""
    )

    assert result.output == "1\n1\n1\n0\n0\n"


def test_list_clear_method_empties_list() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2, 3};
xs.clear();
println(xs);
println(xs.size());
"""
    )

    assert result.output == "{}\n0\n"


def test_list_size_method_returns_int() -> None:
    result = run_aether(
        """
List<string> xs = {"a", "b", "c"};
int count = xs.size();
println(count);
"""
    )

    assert result.output == "3\n"


def test_list_push_method_rejects_wrong_value_type() -> None:
    with pytest.raises(AetherTypeError, match="push\\(\\.\\.\\.\\) value of type 'string' is not assignable to 'int'"):
        run_aether('List<int> xs = {1}; xs.push("bad");')


def test_list_insert_method_rejects_non_int_index() -> None:
    with pytest.raises(AetherTypeError, match="insert\\(\\) index must be int"):
        run_aether('List<int> xs = {1}; xs.insert("0", 2);')


def test_list_contains_method_rejects_wrong_value_type() -> None:
    with pytest.raises(
        AetherTypeError,
        match="contains\\(\\.\\.\\.\\) value of type 'string' is not assignable to 'int'",
    ):
        run_aether('List<int> xs = {1}; xs.contains("bad");')


def test_list_index_of_method_rejects_wrong_value_type() -> None:
    with pytest.raises(
        AetherTypeError,
        match="index_of\\(\\.\\.\\.\\) value of type 'string' is not assignable to 'int'",
    ):
        run_aether('List<int> xs = {1}; xs.indexOf("bad");')


def test_list_pop_method_rejects_empty_list_at_runtime() -> None:
    with pytest.raises(AetherRuntimeError, match="pop\\(\\) cannot be used on an empty List"):
        run_aether("List<int> xs = {}; xs.pop();")


def test_list_remove_at_method_rejects_out_of_range_index_at_runtime() -> None:
    with pytest.raises(AetherRuntimeError, match=r"Aether panic: removeAt\(\) index is out of bounds"):
        run_aether("List<int> xs = {1, 2}; xs.removeAt(3);")


@pytest.mark.parametrize(
    "call",
    [
        "xs.push(4)",
        "xs.pop()",
        "xs.insert(1, 4)",
        "xs.removeAt(0)",
        "xs.clear()",
    ],
)
def test_list_mutating_methods_reject_const_receiver(call: str) -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        run_aether(f"const List<int> xs = {{1, 2, 3}}; {call};")


def test_list_read_only_methods_accept_const_receiver() -> None:
    result = run_aether(
        """
const List<int> xs = {1, 2, 3};
println(xs.contains(2));
println(xs.size());
"""
    )

    assert result.output == "true\n3\n"
