from __future__ import annotations

from pathlib import Path

import pytest

from aether.errors import AetherSyntaxError, AetherTypeError
from aether.runner import run_aether


def test_basic_struct_fields_are_readable() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;
}

Point p = Point(1.0, 2.0);
println(p.x);
println(p.y);
"""
    )

    assert result.output == "1.0\n2.0\n"


def test_struct_constructor_supports_local_inference() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;
}

p = Point(1.0, 2.0);
println(p.x);
"""
    )

    assert result.output == "1.0\n"


def test_struct_constructor_with_too_few_arguments_fails() -> None:
    with pytest.raises(AetherTypeError, match="constructor expects 2 arguments but got 1"):
        run_aether(
            """
struct Point {
    double x;
    double y;
}

Point p = Point(1.0);
"""
        )


def test_struct_constructor_with_too_many_arguments_fails() -> None:
    with pytest.raises(AetherTypeError, match="constructor expects 2 arguments but got 3"):
        run_aether(
            """
struct Point {
    double x;
    double y;
}

Point p = Point(1.0, 2.0, 3.0);
"""
        )


def test_struct_constructor_with_incompatible_field_type_fails() -> None:
    with pytest.raises(AetherTypeError, match="field 'x'.*string.*double"):
        run_aether(
            """
struct Point {
    double x;
    double y;
}

Point p = Point("a", 2.0);
"""
        )


def test_missing_struct_field_fails() -> None:
    with pytest.raises(AetherTypeError, match="Struct 'Point' has no field 'z'"):
        run_aether(
            """
struct Point {
    double x;
    double y;
}

p = Point(1.0, 2.0);
println(p.z);
"""
        )


def test_field_access_on_non_struct_fails() -> None:
    with pytest.raises(AetherTypeError, match="Cannot access field 'y' on non-struct value of type 'int'"):
        run_aether(
            """
int x = 3;
println(x.y);
"""
        )


def test_duplicate_struct_field_fails() -> None:
    with pytest.raises(AetherSyntaxError, match="Duplicate field 'x'"):
        run_aether(
            """
struct Point {
    double x;
    double x;
}
"""
        )


def test_duplicate_struct_fails() -> None:
    with pytest.raises(AetherTypeError, match="Struct 'Point' is already defined"):
        run_aether(
            """
struct Point {
    double x;
}

struct Point {
    double y;
}
"""
        )


def test_struct_alias_collision_fails() -> None:
    with pytest.raises(AetherTypeError, match="Type alias 'Point' is already defined|conflicts with an existing type"):
        run_aether(
            """
struct Point {
    double x;
}

alias Point = double;
"""
        )


def test_struct_function_collision_fails() -> None:
    with pytest.raises(AetherTypeError, match="already defined as a struct"):
        run_aether(
            """
struct Point {
    double x;
}

double Point(double x) {
    return x;
}
"""
        )


def test_struct_top_level_variable_collision_fails() -> None:
    with pytest.raises(AetherTypeError, match="already defined as a struct"):
        run_aether(
            """
struct Point {
    double x;
}

Point = 1;
"""
        )


def test_public_struct_imported_from_package_works(tmp_path: Path) -> None:
    (tmp_path / "Geometry.ae").write_text(
        """
package Geometry;

public struct Point {
    double x;
    double y;
}
""",
        encoding="utf-8",
    )

    result = run_aether(
        """
import Geometry;

Point p = Point(1.0, 2.0);
println(p.x);
""",
        source_root=tmp_path,
    )

    assert result.output == "1.0\n"


def test_private_struct_is_not_imported_from_package(tmp_path: Path) -> None:
    (tmp_path / "Geometry.ae").write_text(
        """
package Geometry;

private struct Hidden {
    int value;
}
""",
        encoding="utf-8",
    )

    with pytest.raises(AetherTypeError, match="private"):
        run_aether("import Geometry;\nHidden h = Hidden(3);", source_root=tmp_path)


def test_default_private_struct_is_not_imported_from_package(tmp_path: Path) -> None:
    (tmp_path / "Geometry.ae").write_text(
        """
package Geometry;

struct Hidden {
    int value;
}
""",
        encoding="utf-8",
    )

    with pytest.raises(AetherTypeError, match="private"):
        run_aether("import Geometry;\nHidden h = Hidden(3);", source_root=tmp_path)


def test_alias_of_struct_works_for_type_and_constructor() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;
}

alias P = Point;
P p = P(1.0, 2.0);
println(p.x);
"""
    )

    assert result.output == "1.0\n"


def test_struct_field_can_use_type_alias() -> None:
    result = run_aether(
        """
alias Real = double;

struct Point {
    Real x;
    Real y;
}

Point p = Point(1.0, 2.0);
println(p.x);
"""
    )

    assert result.output == "1.0\n"


def test_function_can_receive_struct() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;
}

double sumPoint(Point p) {
    return p.x + p.y;
}

println(sumPoint(Point(1.0, 2.0)));
"""
    )

    assert result.output == "3.0\n"


def test_imported_function_can_receive_public_struct(tmp_path: Path) -> None:
    (tmp_path / "Geometry.ae").write_text(
        """
package Geometry;

public struct Point {
    double x;
    double y;
}

public double sumPoint(Point p) {
    return p.x + p.y;
}
""",
        encoding="utf-8",
    )

    result = run_aether(
        """
import Geometry;
println(sumPoint(Point(1.0, 2.0)));
""",
        source_root=tmp_path,
    )

    assert result.output == "3.0\n"


def test_public_struct_cannot_expose_private_field_type(tmp_path: Path) -> None:
    (tmp_path / "Geometry.ae").write_text(
        """
package Geometry;

private struct Internal {
    int x;
}

public struct Wrapper {
    Internal value;
}
""",
        encoding="utf-8",
    )

    with pytest.raises(AetherTypeError, match="cannot expose private field type 'Internal'"):
        run_aether("import Geometry;", source_root=tmp_path)


def test_struct_field_assignment_updates_value() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;
}

Point p = Point(1.0, 2.0);
p.x = 3.0;
println(p.x);
"""
    )

    assert result.output == "3.0\n"


def test_struct_prints_with_field_names() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;
}

println(Point(1.0, 2.0));
"""
    )

    assert result.output == "Point(x=1.0, y=2.0)\n"


def test_nested_struct_fields_are_readable() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;
}

struct Segment {
    Point a;
    Point b;
}

Segment s = Segment(Point(0.0, 0.0), Point(1.0, 1.0));
println(s.a.x);
println(s.b.y);
"""
    )

    assert result.output == "0.0\n1.0\n"


def test_function_can_return_struct() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;
}

Point origin() {
    return Point(0.0, 0.0);
}

p = origin();
println(p.x);
"""
    )

    assert result.output == "0.0\n"


def test_function_can_take_and_return_struct() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;
}

Point shift(Point p, double dx, double dy) {
    return Point(p.x + dx, p.y + dy);
}

q = shift(Point(1.0, 2.0), 3.0, 4.0);
println(q.x);
println(q.y);
"""
    )

    assert result.output == "4.0\n6.0\n"


def test_struct_field_assignment_with_incompatible_type_fails() -> None:
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'string' to 'double'"):
        run_aether(
            """
struct Point {
    double x;
    double y;
}

Point p = Point(1.0, 2.0);
p.x = "hola";
"""
        )


def test_struct_field_assignment_to_missing_field_fails() -> None:
    with pytest.raises(AetherTypeError, match="Struct 'Point' has no field 'z'"):
        run_aether(
            """
struct Point {
    double x;
    double y;
}

Point p = Point(1.0, 2.0);
p.z = 3.0;
"""
        )


def test_struct_field_assignment_on_temporary_fails() -> None:
    with pytest.raises(AetherSyntaxError, match="temporaries is not supported"):
        run_aether(
            """
struct Point {
    double x;
    double y;
}

Point(1.0, 2.0).x = 5.0;
"""
        )


def test_nested_field_assignment_from_variable_is_allowed() -> None:
    result = run_aether(
        """
struct Point {
    double x;
    double y;
}

struct Segment {
    Point a;
    Point b;
}

Segment s = Segment(Point(0.0, 0.0), Point(1.0, 1.0));
s.a.x = 5.0;
println(s.a.x);
"""
    )

    assert result.output == "5.0\n"


def test_public_nested_structs_imported_from_package_work(tmp_path: Path) -> None:
    (tmp_path / "Geometry.ae").write_text(
        """
package Geometry;

public struct Point {
    double x;
    double y;
}

public struct Segment {
    Point a;
    Point b;
}
""",
        encoding="utf-8",
    )

    result = run_aether(
        """
import Geometry;

s = Segment(Point(0.0, 0.0), Point(1.0, 1.0));
println(s.b.x);
""",
        source_root=tmp_path,
    )

    assert result.output == "1.0\n"


def test_imported_alias_of_struct_works_as_type_and_constructor(tmp_path: Path) -> None:
    (tmp_path / "Geometry.ae").write_text(
        """
package Geometry;

public struct Point {
    double x;
    double y;
}

public alias P = Point;
""",
        encoding="utf-8",
    )

    result = run_aether(
        """
import Geometry;

P p = P(1.0, 2.0);
println(p.x);
""",
        source_root=tmp_path,
    )

    assert result.output == "1.0\n"


def test_struct_equality_is_not_supported_yet() -> None:
    with pytest.raises(AetherTypeError, match="Struct equality is not supported yet"):
        run_aether(
            """
struct Point {
    double x;
    double y;
}

println(Point(1.0, 2.0) == Point(1.0, 2.0));
"""
        )
