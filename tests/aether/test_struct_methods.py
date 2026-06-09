from __future__ import annotations

from pathlib import Path

import pytest

from aether.errors import AetherSyntaxError, AetherTypeError
from aether.language_service import completion_items
from aether.runner import run_aether
from document_symbols import extract_document_symbol_occurrences


def test_struct_method_without_parameters_can_read_implicit_fields() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;

    double norm() {
        return sqrt(x*x + y*y);
    }
}

Point p = Point(3, 4);
println(p.norm());
"""
    )

    assert result.output == "5.0\n"


def test_struct_method_with_parameter_returns_another_struct() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;

    Point scale(double k) {
        return Point(x*k, y*k);
    }
}

Point p = Point(3, 4);
Point q = p.scale(2);
println(q.x);
println(q.y);
"""
    )

    assert result.output == "6.0\n8.0\n"


def test_struct_method_parameter_shadows_field() -> None:
    result = run_aether(
        """
struct S {
    int x;

    int f(int x) {
        return x;
    }
}

S s = S(1);
println(s.f(9));
"""
    )

    assert result.output == "9\n"


def test_struct_method_can_call_another_method_directly() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;

    double squaredNorm() {
        return x*x + y*y;
    }

    double norm() {
        return sqrt(squaredNorm());
    }
}

Point p = Point(3, 4);
println(p.norm());
"""
    )

    assert result.output == "5.0\n"


def test_explicit_this_field_access_is_supported() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;

    double sum() {
        return this.x + this.y;
    }
}

Point p = Point(3, 4);
println(p.sum());
"""
    )

    assert result.output == "7.0\n"


def test_unknown_struct_method_fails() -> None:
    with pytest.raises(AetherTypeError, match="Struct 'Point' has no method 'unknown'"):
        run_aether(
            """
struct Point {
    double x;
}

Point p = Point(1);
p.unknown();
"""
        )


def test_struct_method_arity_mismatch_fails() -> None:
    with pytest.raises(AetherTypeError, match="Method 'norm' expects 0 arguments but got 1"):
        run_aether(
            """
struct Point {
    double x;

    double norm() {
        return x;
    }
}

Point p = Point(1);
p.norm(1);
"""
        )


def test_struct_method_return_type_mismatch_fails() -> None:
    with pytest.raises(AetherTypeError, match="Point.bad.*returned string"):
        run_aether(
            """
struct Point {
    double x;

    double bad() {
        return "no";
    }
}
"""
        )


def test_struct_method_missing_return_fails() -> None:
    with pytest.raises(AetherTypeError, match="Method 'Point.bad' may not return"):
        run_aether(
            """
struct Point {
    double x;

    double bad() {
        int y = 1;
    }
}
"""
        )


def test_field_and_method_name_collision_fails() -> None:
    with pytest.raises(AetherSyntaxError, match="already has a field named 'x'"):
        run_aether(
            """
struct S {
    int x;

    int x() {
        return 1;
    }
}
"""
        )


def test_duplicate_struct_methods_fail() -> None:
    with pytest.raises(AetherSyntaxError, match="Duplicate method 'f'"):
        run_aether(
            """
struct S {
    int f() {
        return 1;
    }

    int f() {
        return 2;
    }
}
"""
        )


def test_struct_mutating_method_assigns_implicit_field() -> None:
    result = run_aether(
        """
struct Counter {
    int value;

    void increment() {
        value = value + 1;
    }
}

Counter c = Counter(0);
c.increment();
println(c.value);
"""
    )

    assert result.output == "1\n"


def test_struct_mutating_method_assigns_this_field() -> None:
    result = run_aether(
        """
struct Counter {
    int value;

    void add(int n) {
        this.value = this.value + n;
    }
}

Counter c = Counter(1);
c.add(4);
println(c.value);
"""
    )

    assert result.output == "5\n"


def test_struct_mutating_method_field_assignment_checks_type() -> None:
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'string' to 'int'"):
        run_aether(
            """
struct Counter {
    int value;

    void bad() {
        value = "hola";
    }
}
"""
        )


def test_struct_method_parameter_shadows_field_assignment() -> None:
    result = run_aether(
        """
struct Counter {
    int value;

    void f(int value) {
        value = value + 1;
    }
}

Counter c = Counter(3);
c.f(10);
println(c.value);
"""
    )

    assert result.output == "3\n"


def test_struct_method_this_field_overrides_shadowing() -> None:
    result = run_aether(
        """
struct Counter {
    int value;

    void f(int value) {
        this.value = this.value + value;
    }
}

Counter c = Counter(3);
c.f(10);
println(c.value);
"""
    )

    assert result.output == "13\n"


def test_struct_mutating_method_rejects_const_receiver() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'c'"):
        run_aether(
            """
struct Counter {
    int value;

    void increment() {
        value = value + 1;
    }
}

const Counter c = Counter(0);
c.increment();
"""
        )


def test_struct_mutating_method_rejects_temporary_receiver() -> None:
    with pytest.raises(AetherTypeError, match="Cannot call mutating method on temporary value"):
        run_aether(
            """
struct Counter {
    int value;

    void increment() {
        value = value + 1;
    }
}

Counter(0).increment();
"""
        )


def test_struct_mutating_method_preserves_value_semantics() -> None:
    result = run_aether(
        """
struct Counter {
    int value;

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


def test_struct_non_mutating_method_accepts_const_receiver() -> None:
    result = run_aether(
        """
struct Counter {
    int value;

    int get() {
        return value;
    }
}

const Counter c = Counter(7);
println(c.get());
"""
    )

    assert result.output == "7\n"


def test_struct_mutating_method_can_call_another_mutating_method() -> None:
    result = run_aether(
        """
struct Counter {
    int value;

    void increment() {
        value = value + 1;
    }

    void addTwo() {
        increment();
        this.increment();
    }
}

Counter c = Counter(0);
c.addTwo();
println(c.value);
"""
    )

    assert result.output == "2\n"


def test_struct_method_calling_mutating_method_is_mutating() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'c'"):
        run_aether(
            """
struct Counter {
    int value;

    void increment() {
        value = value + 1;
    }

    void wrapper() {
        increment();
    }
}

const Counter c = Counter(0);
c.wrapper();
"""
        )


def test_interface_mutating_method_updates_contained_value() -> None:
    result = run_aether(
        """
interface Inc {
    void increment();
    int get();
}

struct Counter implements Inc {
    int value;

    void increment() {
        value = value + 1;
    }

    int get() {
        return value;
    }
}

Inc c = Counter(0);
c.increment();
println(c.get());
"""
    )

    assert result.output == "1\n"


def test_interface_mutating_method_rejects_const_receiver() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'c'"):
        run_aether(
            """
interface Inc {
    void increment();
}

struct Counter implements Inc {
    int value;

    void increment() {
        value = value + 1;
    }
}

const Inc c = Counter(0);
c.increment();
"""
        )


def test_completion_after_struct_value_dot_includes_fields_and_methods() -> None:
    source = """
struct Point {
    double x;
    double y;

    double norm() {
        return sqrt(x*x + y*y);
    }
}

Point p = Point(3, 4);
p.
"""

    items = completion_items(source, 12, len("p.") + 1)
    labels = {item.label: item.kind for item in items}

    assert labels["x"] == "property"
    assert labels["y"] == "property"
    assert labels["norm"] == "method"


def test_document_symbols_include_struct_methods() -> None:
    source = """
struct Point {
    double x;

    double norm() {
        return x;
    }
}
"""

    symbols = extract_document_symbol_occurrences(source)
    labels = {(symbol.name, symbol.kind) for symbol in symbols}

    assert ("Point", "type") in labels
    assert ("norm", "function") in labels


def test_public_struct_with_methods_imports_from_package(tmp_path: Path) -> None:
    (tmp_path / "Geometry.ae").write_text(
        """
package Geometry;

private double hyp(double x, double y) {
    return sqrt(x*x + y*y);
}

public struct Point {
    double x;
    double y;

    double norm() {
        return hyp(x, y);
    }
}
""",
        encoding="utf-8",
    )

    result = run_aether(
        """
import Geometry;

Point p = Point(3, 4);
println(p.norm());
""",
        source_root=tmp_path,
    )

    assert result.output == "5.0\n"


def test_private_struct_with_methods_is_not_imported(tmp_path: Path) -> None:
    (tmp_path / "Geometry.ae").write_text(
        """
package Geometry;

private struct Hidden {
    int x;

    int value() {
        return x;
    }
}
""",
        encoding="utf-8",
    )

    with pytest.raises(AetherTypeError, match="private"):
        run_aether("import Geometry;\nHidden h = Hidden(1);\nprintln(h.value());", source_root=tmp_path)


def test_struct_methods_accept_and_return_enum_list_array_vector_and_matrix_types() -> None:
    result = run_aether(
        """
enum Axis {
    X,
    Y
}

struct Bundle {
    List<int> xs;
    Array<int> ys;
    Vector<double> v;
    Matrix<double> m;

    Axis choose(Axis axis) {
        return axis;
    }

    List<int> listValue() {
        return xs;
    }

    Array<int> arrayValue() {
        return ys;
    }

    Vector<double> vectorValue() {
        return v;
    }

    Matrix<double> matrixValue() {
        return m;
    }
}

Bundle b = Bundle({1, 2}, {3, 4}, [3, 4], [1 2; 3 4]);
println(b.choose(Axis.Y));
println(b.listValue());
println(b.arrayValue());
println(b.vectorValue());
println(b.matrixValue());
"""
    )

    assert result.output == "Axis.Y\n{1, 2}\nArray{3, 4}\n[3.0 4.0]\n[1.0 2.0; 3.0 4.0]\n"
