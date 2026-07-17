from __future__ import annotations

from pathlib import Path

import pytest

from aether.errors import AetherRuntimeError, AetherTypeError
from aether.runner import run_aether


def test_list_example_runs_with_expected_output() -> None:
    example = Path(__file__).parents[2] / "examples" / "lists" / "list_api.ae"
    result = run_aether(example.read_text(encoding="utf-8"))

    assert result.output == (
        "numbers: {10, 15, 20, 30}\n"
        "contains 20: true\n"
        "contains 99: false\n"
        "removed: 20\n"
        "last: 30\n"
        "numbers after removals: {10, 15}\n"
        "size: 2\n"
        "size after clear: 0\n"
        "numbers reused: {99}\n"
        'names: {"Ana", "Bruno", "Luis", "Marta"}\n'
        "contains Marta: true\n"
        "removed name: Ana\n"
        "last name: Marta\n"
        'remaining names: {"Bruno", "Luis"}\n'
        "color count: 3\n"
        "contains green: true\n"
    )


def test_list_chained_mutations_preserve_values_and_size() -> None:
    result = run_aether(
        """
List<int> xs = {10, 20};
xs.push(30);
xs.insert(1, 15);
int removed = xs.removeAt(2);
xs.push(40);
int last = xs.pop();
println(removed);
println(last);
println(xs.size());
println(xs);
"""
    )

    assert result.output == "20\n40\n3\n{10, 15, 30}\n"


def test_list_contains_tracks_present_and_absent_values_after_mutations() -> None:
    result = run_aether(
        """
List<string> names = {"Ana", "Luis"};
println(names.contains("Ana"));
println(names.contains("Marta"));
names.push("Marta");
names.removeAt(0);
println(names.contains("Ana"));
println(names.contains("Marta"));
"""
    )

    assert result.output == "true\nfalse\nfalse\ntrue\n"


def test_list_clear_resets_size_and_list_can_be_reused() -> None:
    result = run_aether(
        """
List<int> xs = {1, 2, 3};
xs.clear();
println(xs.size());
xs.push(9);
println(xs.size());
println(xs);
"""
    )

    assert result.output == "0\n1\n{9}\n"


def test_list_pop_returns_last_element_and_reduces_size() -> None:
    result = run_aether(
        """
List<int> xs = {4, 5, 6};
int value = xs.pop();
println(value);
println(xs.size());
println(xs);
"""
    )

    assert result.output == "6\n2\n{4, 5}\n"


def test_list_remove_at_returns_element_and_compacts_list() -> None:
    result = run_aether(
        """
List<string> names = {"zero", "one", "two", "three"};
string removed = names.removeAt(1);
println(removed);
println(names.size());
println(names);
println(names[1]);
"""
    )

    assert result.output == 'one\n3\n{"zero", "two", "three"}\ntwo\n'


def test_const_list_allows_size_and_contains() -> None:
    result = run_aether(
        """
const List<int> xs = {2, 4, 6};
println(xs.size());
println(xs.contains(4));
println(xs.contains(5));
"""
    )

    assert result.output == "3\ntrue\nfalse\n"


@pytest.mark.parametrize(
    "call",
    [
        "xs.push(4)",
        "xs.pop()",
        "xs.insert(0, 4)",
        "xs.removeAt(0)",
        "xs.clear()",
    ],
)
def test_const_list_rejects_each_mutating_method(call: str) -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'xs'"):
        run_aether(f"const List<int> xs = {{1, 2, 3}}; {call};")


def test_list_pop_on_empty_list_has_clear_runtime_error() -> None:
    with pytest.raises(AetherRuntimeError, match="pop\\(\\) cannot be used on an empty List"):
        run_aether("List<int> xs = {}; xs.pop();")


@pytest.mark.parametrize("index", ["-1", "xs.size()"])
def test_list_remove_at_rejects_boundary_indices(index: str) -> None:
    with pytest.raises(AetherRuntimeError, match=r"Aether panic: removeAt\(\) index is out of bounds"):
        run_aether(f"List<int> xs = {{1, 2, 3}}; xs.removeAt({index});")


@pytest.mark.parametrize("index", ["-1", "xs.size() + 1"])
def test_list_insert_rejects_out_of_range_indices(index: str) -> None:
    with pytest.raises(AetherRuntimeError, match=r"Aether panic: insert\(\) index is out of bounds"):
        run_aether(f"List<int> xs = {{1, 2, 3}}; xs.insert({index}, 9);")
