from __future__ import annotations

from pathlib import Path

import pytest

from aether.errors import AetherSyntaxError, AetherTypeError
from aether.language_service import completion_items
from aether.runner import run_aether
from document_symbols import extract_document_symbol_occurrences


def test_interface_simple_struct_implements_and_dispatches() -> None:
    result = run_aether(
        """
interface Shape {
    double area();
}

struct Circle implements Shape {
    double r;

    double area() {
        return r * r;
    }
}

Shape s = Circle(2);
println(s.area());
"""
    )

    assert result.output == "4.0\n"


def test_missing_required_interface_method_fails() -> None:
    with pytest.raises(AetherTypeError, match="missing method 'area'.*interface 'Shape'"):
        run_aether(
            """
interface Shape {
    double area();
}

struct Circle implements Shape {
    double r;
}
"""
        )


def test_interface_return_type_mismatch_fails() -> None:
    with pytest.raises(AetherTypeError, match="return type expected 'double' but got 'int'"):
        run_aether(
            """
interface Shape {
    double area();
}

struct Circle implements Shape {
    int area() {
        return 1;
    }
}
"""
        )


def test_interface_parameter_type_mismatch_fails() -> None:
    with pytest.raises(AetherTypeError, match="parameter 1 expected 'double' but got 'int'"):
        run_aether(
            """
interface Scalable {
    double scale(double k);
}

struct Circle implements Scalable {
    double scale(int k) {
        return 1.0;
    }
}
"""
        )


def test_struct_can_implement_two_interfaces() -> None:
    result = run_aether(
        """
interface Shape {
    double area();
}

interface Printable {
    string toString();
}

struct Circle implements Shape, Printable {
    double r;

    double area() {
        return r * r;
    }

    string toString() {
        return "Circle";
    }
}

Shape s = Circle(3);
Printable p = Circle(3);
println(s.area());
println(p.toString());
"""
    )

    assert result.output == "9.0\nCircle\n"


def test_interface_variable_accepts_implementing_struct() -> None:
    result = run_aether(
        """
interface Shape { double area(); }
struct Circle implements Shape {
    double r;
    double area() { return r * r; }
}

Shape s = Circle(2);
println(s.area());
"""
    )

    assert result.output == "4.0\n"


def test_interface_argument_accepts_implementing_struct() -> None:
    result = run_aether(
        """
interface Shape { double area(); }
struct Circle implements Shape {
    double r;
    double area() { return r * r; }
}

void printArea(Shape s) {
    println(s.area());
}

printArea(Circle(5));
"""
    )

    assert result.output == "25.0\n"


def test_interface_return_accepts_implementing_struct() -> None:
    result = run_aether(
        """
interface Shape { double area(); }
struct Circle implements Shape {
    double r;
    double area() { return r * r; }
}

Shape makeShape() {
    return Circle(6);
}

println(makeShape().area());
"""
    )

    assert result.output == "36.0\n"


def test_interface_method_dispatch_uses_actual_struct_method() -> None:
    result = run_aether(
        """
interface Shape { double area(); }
struct Circle implements Shape {
    double r;
    double area() { return r + 10.0; }
}

Shape s = Circle(7);
println(s.area());
"""
    )

    assert result.output == "17.0\n"


def test_field_access_on_interface_variable_fails() -> None:
    with pytest.raises(AetherTypeError, match="Cannot access field 'r' on interface type 'Shape'"):
        run_aether(
            """
interface Shape { double area(); }
struct Circle implements Shape {
    double r;
    double area() { return r; }
}

Shape s = Circle(2);
println(s.r);
"""
        )


def test_missing_method_on_interface_variable_fails() -> None:
    with pytest.raises(AetherTypeError, match="Interface 'Shape' has no method 'foo'"):
        run_aether(
            """
interface Shape { double area(); }
struct Circle implements Shape {
    double r;
    double area() { return r; }
}

Shape s = Circle(2);
s.foo();
"""
        )


def test_interface_cannot_declare_fields() -> None:
    with pytest.raises(AetherSyntaxError, match="Interfaces cannot declare fields"):
        run_aether(
            """
interface Shape {
    double area;
}
"""
        )


def test_interface_methods_cannot_have_bodies() -> None:
    with pytest.raises(AetherSyntaxError, match="Interface methods cannot have bodies"):
        run_aether(
            """
interface Shape {
    double area() {
        return 1.0;
    }
}
"""
        )


def test_public_interface_imports_and_private_interface_is_hidden(tmp_path: Path) -> None:
    (tmp_path / "Geometry.ae").write_text(
        """
package Geometry;

public interface Shape {
    double area();
}

private interface Hidden {
    double secret();
}

public struct Circle implements Shape {
    double r;
    double area() { return r * r; }
}
""",
        encoding="utf-8",
    )

    result = run_aether(
        "import Geometry;\nShape s = Circle(4);\nprintln(s.area());",
        source_root=tmp_path,
    )
    assert result.output == "16.0\n"

    with pytest.raises(AetherTypeError, match="private"):
        run_aether("import Geometry;\nHidden h = Circle(1);", source_root=tmp_path)


def test_public_struct_cannot_implement_private_interface_in_package(tmp_path: Path) -> None:
    (tmp_path / "M.ae").write_text(
        """
package M;

private interface Hidden {
    double secret();
}

public struct Exposed implements Hidden {
    double secret() { return 1.0; }
}
""",
        encoding="utf-8",
    )

    with pytest.raises(AetherTypeError, match="cannot implement private interface 'Hidden'"):
        run_aether("import M;", source_root=tmp_path)


def test_interface_top_level_collision_fails() -> None:
    with pytest.raises(AetherTypeError, match="already defined as an interface|already defined as a struct"):
        run_aether(
            """
interface Shape { double area(); }
struct Shape {}
"""
        )


def test_struct_cannot_implement_non_interface_type() -> None:
    with pytest.raises(AetherTypeError, match="cannot implement non-interface type 'Point'"):
        run_aether(
            """
struct Point {}
struct Circle implements Point {}
"""
        )


def test_interface_cannot_be_instantiated() -> None:
    with pytest.raises(AetherTypeError, match="Cannot instantiate interface 'Shape'"):
        run_aether(
            """
interface Shape { double area(); }
Shape s = Shape();
"""
        )


def test_generic_interfaces_are_not_supported_yet() -> None:
    with pytest.raises(AetherSyntaxError, match="Generic interfaces are not supported yet"):
        run_aether("interface Shape<T> { double area(); }")


def test_language_service_understands_interfaces() -> None:
    source = """
interface Shape {
    double area();
}

struct Circle implements Shape {
    double r;
    double area() { return r * r; }
}

Shape s = Circle(2);
s.
"""

    symbols = extract_document_symbol_occurrences(source)
    assert {symbol.name for symbol in symbols} >= {"Shape", "area", "Circle"}

    items = completion_items(source, 12, len("s.") + 1)
    labels = {item.label: item.kind for item in items}
    assert labels["area"] == "method"
