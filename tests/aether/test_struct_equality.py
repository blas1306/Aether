from __future__ import annotations

import pytest

from aether.errors import AetherTypeError
from aether.runner import run_aether


def test_struct_equality_and_inequality_compare_fields() -> None:
    result = run_aether(
        """
struct Point {
    int x;
    int y;
}

println(Point(1, 2) == Point(1, 2));
println(Point(1, 2) == Point(1, 3));
println(Point(1, 2) != Point(1, 3));
println(Point(1, 2) != Point(1, 2));
"""
    )

    assert result.output == "true\nfalse\ntrue\nfalse\n"


def test_struct_equality_supports_string_boolean_and_enum_fields() -> None:
    result = run_aether(
        """
enum Status { Ready, Waiting }

struct State {
    string name;
    boolean enabled;
    Status status;
}

println(State("worker", true, Status.Ready) == State("worker", true, Status.Ready));
println(State("worker", true, Status.Ready) == State("worker", false, Status.Ready));
println(State("worker", true, Status.Ready) != State("worker", true, Status.Waiting));
"""
    )

    assert result.output == "true\nfalse\ntrue\n"


def test_nested_struct_equality_is_recursive() -> None:
    result = run_aether(
        """
struct Point {
    int x;
    int y;
}

struct Segment {
    Point a;
    Point b;
}

println(Segment(Point(0, 0), Point(1, 1)) == Segment(Point(0, 0), Point(1, 1)));
println(Segment(Point(0, 0), Point(1, 1)) != Segment(Point(0, 0), Point(2, 1)));
"""
    )

    assert result.output == "true\ntrue\n"


def test_struct_equality_supports_list_fields() -> None:
    result = run_aether(
        """
struct Samples {
    List<int> values;
}

println(Samples({1, 2, 3}) == Samples({1, 2, 3}));
println(Samples({1, 2, 3}) == Samples({1, 2, 4}));
"""
    )

    assert result.output == "true\nfalse\n"


def test_struct_equality_supports_nullable_comparable_fields() -> None:
    result = run_aether(
        """
struct MaybeCount {
    int? value;
}

println(MaybeCount(null) == MaybeCount(null));
println(MaybeCount(3) == MaybeCount(3));
println(MaybeCount(null) != MaybeCount(3));
"""
    )

    assert result.output == "true\ntrue\ntrue\n"


def test_struct_with_explicit_constructor_uses_structural_equality() -> None:
    result = run_aether(
        """
struct Point {
    int x;
    int y;

    constructor(int value) {
        x = value;
        y = value + 1;
    }
}

println(Point(3) == Point(3));
println(Point(3) != Point(4));
"""
    )

    assert result.output == "true\ntrue\n"


def test_copied_struct_keeps_value_equality() -> None:
    result = run_aether(
        """
struct Point {
    int x;
    int y;
}

Point original = Point(1, 2);
Point copy = original;
println(original == copy);
copy.x = 9;
println(original == copy);
"""
    )

    assert result.output == "true\nfalse\n"


def test_distinct_nominal_structs_are_not_comparable() -> None:
    with pytest.raises(AetherTypeError, match="Cannot compare 'Point' and 'Size'"):
        run_aether(
            """
struct Point { int x; int y; }
struct Size { int x; int y; }

println(Point(1, 2) == Size(1, 2));
"""
        )


def test_struct_and_non_struct_are_not_comparable() -> None:
    with pytest.raises(AetherTypeError, match="Cannot compare 'Point' and 'int'"):
        run_aether(
            """
struct Point { int x; int y; }
println(Point(1, 2) == 1);
"""
        )


def test_struct_with_class_field_is_not_comparable() -> None:
    with pytest.raises(AetherTypeError, match="Type Wrapper does not define equality"):
        run_aether(
            """
class Box {
    int value;
}

struct Wrapper {
    Box box;
}

println(Wrapper(Box(1)) == Wrapper(Box(1)));
"""
        )


def test_struct_with_interface_field_is_not_comparable() -> None:
    with pytest.raises(AetherTypeError, match="Type Wrapper does not define equality"):
        run_aether(
            """
interface ValueView {
    int getValue();
}

class Box implements ValueView {
    int value;
    public int getValue() { return value; }
}

struct Wrapper {
    ValueView value;
}

println(Wrapper(Box(1)) == Wrapper(Box(1)));
"""
        )


def test_class_equality_remains_unsupported() -> None:
    with pytest.raises(AetherTypeError, match="Type Counter does not define equality"):
        run_aether(
            """
class Counter {
    int value;
}

println(Counter(1) == Counter(1));
"""
        )
