from __future__ import annotations

from aether.runner import run_aether


def test_struct_assignment_copies_value() -> None:
    result = run_aether(
        """
struct Point {
    int x;
    int y;
}

Point p = Point(1, 2);
Point q = p;
q = Point(10, 20);

println(p.x);
println(p.y);
println(q.x);
println(q.y);
"""
    )

    assert result.output == "1\n2\n10\n20\n"


def test_struct_argument_is_passed_by_value() -> None:
    result = run_aether(
        """
struct Point {
    int x;
    int y;
}

Point move(Point p) {
    return Point(p.x + 1, p.y + 1);
}

Point p = Point(1, 2);
Point q = move(p);

println(p.x);
println(p.y);
println(q.x);
println(q.y);
"""
    )

    assert result.output == "1\n2\n2\n3\n"


def test_struct_return_produces_independent_values() -> None:
    result = run_aether(
        """
struct Point {
    int x;
    int y;
}

Point create() {
    return Point(1, 2);
}

Point a = create();
Point b = create();
b.x = 10;

println(a.x);
println(a.y);
println(b.x);
println(b.y);
"""
    )

    assert result.output == "1\n2\n10\n2\n"


def test_struct_assignment_copies_nested_struct_fields() -> None:
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

Point p = Point(1, 2);
Segment s1 = Segment(p, p);
Segment s2 = s1;

s2.a.x = 10;
s2.b.y = 20;

println(p.x);
println(p.y);
println(s1.a.x);
println(s1.b.y);
println(s2.a.x);
println(s2.b.y);
"""
    )

    assert result.output == "1\n2\n1\n2\n10\n20\n"
