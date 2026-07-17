from __future__ import annotations

import pytest

from aether.errors import AetherSyntaxError, AetherTypeError
from aether.runner import run_aether


def test_struct_explicit_constructor_initializes_fields() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;

    constructor(double initialX, double initialY) {
        x = initialX;
        y = initialY;
    }
}

Point p = Point(1.0, 2.0);
println(p.x);
println(p.y);
"""
    )

    assert result.output == "1.0\n2.0\n"


def test_struct_explicit_constructor_can_use_this() -> None:
    result = run_aether(
        """
struct Point {
    int x;
    int y;

    constructor(int x, int y) {
        this.x = x;
        this.y = y;
    }
}

Point p = Point(3, 4);
println(p.x + p.y);
"""
    )

    assert result.output == "7\n"


def test_struct_explicit_constructor_can_read_initialized_fields() -> None:
    result = run_aether(
        """
struct Pair {
    int first;
    int second;

    constructor(int value) {
        first = value;
        second = first + 1;
    }
}

Pair pair = Pair(10);
println(pair.second);
"""
    )

    assert result.output == "11\n"


def test_struct_explicit_constructor_can_call_internal_method() -> None:
    result = run_aether(
        """
struct Counter {
    int value;

    constructor(int initial) {
        value = initial;
        increment();
    }

    void increment() {
        value = value + 1;
    }
}

Counter counter = Counter(9);
println(counter.value);
"""
    )

    assert result.output == "10\n"


def test_struct_explicit_constructor_supports_simple_logic() -> None:
    result = run_aether(
        """
struct Counter {
    int value;

    constructor(int initial) {
        if (initial < 0) {
            value = 0;
        } else {
            value = initial;
        }
    }
}

println(Counter(-2).value);
println(Counter(7).value);
"""
    )

    assert result.output == "0\n7\n"


def test_struct_without_explicit_constructor_keeps_positional_constructor() -> None:
    result = run_aether(
        """
struct Pair {
    int left;
    string right;
}

Pair pair = Pair(2, "two");
println(pair.left);
println(pair.right);
"""
    )

    assert result.output == "2\ntwo\n"


def test_struct_explicit_constructor_preserves_value_semantics() -> None:
    result = run_aether(
        """
struct Counter {
    int value;

    constructor(int initial) {
        value = initial;
    }

    void increment() {
        value = value + 1;
    }
}

Counter a = Counter(0);
Counter b = a;
b.increment();
println(a.value);
println(b.value);
"""
    )

    assert result.output == "0\n1\n"


def test_struct_cannot_declare_two_explicit_constructors() -> None:
    with pytest.raises(AetherSyntaxError, match="cannot declare more than one constructor"):
        run_aether(
            """
struct Counter {
    constructor() {}
    constructor(int initial) {}
}
"""
        )


def test_struct_constructor_cannot_be_private_or_static() -> None:
    with pytest.raises(AetherSyntaxError, match="Constructors cannot be private"):
        run_aether("struct Counter { private constructor() {} }")

    with pytest.raises(AetherSyntaxError, match="Constructors cannot be static"):
        run_aether("struct Counter { static constructor() {} }")


def test_constructor_cannot_be_declared_outside_aggregate() -> None:
    with pytest.raises(AetherSyntaxError, match="inside a class or struct"):
        run_aether("constructor(int initial) {}")


def test_struct_constructor_cannot_return_a_value() -> None:
    with pytest.raises(AetherTypeError, match="cannot return a value"):
        run_aether(
            """
struct Counter {
    constructor() {
        return 1;
    }
}
"""
        )


def test_struct_constructor_cannot_declare_return_type() -> None:
    with pytest.raises(AetherSyntaxError, match="cannot declare a return type"):
        run_aether("struct Counter { void constructor() {} }")


def test_struct_constructor_parameters_must_be_typed() -> None:
    with pytest.raises(AetherSyntaxError, match="Expected constructor parameter name"):
        run_aether("struct Counter { constructor(initial) {} }")


def test_struct_explicit_constructor_validates_arity_and_types() -> None:
    with pytest.raises(AetherTypeError, match="constructor expects 1 arguments but got 0"):
        run_aether("struct Counter { constructor(int initial) {} }\nCounter c = Counter();")

    with pytest.raises(AetherTypeError, match="constructor parameter 'initial'.*string.*int"):
        run_aether(
            'struct Counter { constructor(int initial) {} }\nCounter c = Counter("bad");'
        )


def test_struct_explicit_constructor_typechecks_field_assignments() -> None:
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'string' to 'int'"):
        run_aether(
            """
struct Counter {
    int value;

    constructor() {
        value = "bad";
    }
}
"""
        )


def test_struct_explicit_constructor_replaces_automatic_signature() -> None:
    with pytest.raises(AetherTypeError, match="constructor expects 1 arguments but got 2"):
        run_aether(
            """
struct Pair {
    int left;
    int right;

    constructor(int value) {
        left = value;
        right = value;
    }
}

Pair pair = Pair(1, 2);
"""
        )
