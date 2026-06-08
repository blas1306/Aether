from __future__ import annotations

from pathlib import Path

from aether import analyze_source, completion_items, run_source


def test_analyze_source_reports_syntax_error_location() -> None:
    diagnostics = analyze_source("println(")

    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic.severity == "error"
    assert diagnostic.line == 1
    assert diagnostic.column >= 1
    assert "AetherSyntaxError" in diagnostic.message


def test_analyze_source_reports_type_error() -> None:
    diagnostics = analyze_source("println(missing);")

    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "error"
    assert "Undefined variable 'missing'" in diagnostics[0].message


def test_analyze_source_reports_implicit_conversion_location() -> None:
    diagnostics = analyze_source('println("ok");\nint n = 28;\nint m = sqrt(n);\n')

    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert "Cannot implicitly convert 'double' to 'int'" in diagnostic.message
    assert diagnostic.line == 3


def test_analyze_source_reports_multiple_syntax_errors() -> None:
    diagnostics = analyze_source("int a = ;\nint b = ;\n")

    assert len(diagnostics) == 2
    assert [diagnostic.line for diagnostic in diagnostics] == [1, 2]
    assert all("AetherSyntaxError" in diagnostic.message for diagnostic in diagnostics)


def test_analyze_source_reports_multiple_type_errors() -> None:
    diagnostics = analyze_source('int a = "bad";\nboolean b = 1;\n')

    assert len(diagnostics) == 2
    assert [diagnostic.line for diagnostic in diagnostics] == [1, 2]
    assert "Cannot implicitly convert 'string' to 'int'" in diagnostics[0].message
    assert "Cannot implicitly convert 'int' to 'boolean'" in diagnostics[1].message


def test_analyze_source_accepts_valid_program() -> None:
    assert analyze_source('x = 1; println(x);') == []


def test_analyze_source_resolves_imports_from_source_root(tmp_path: Path) -> None:
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

    diagnostics = analyze_source("import Geometry;\nP p = P(1.0, 2.0);", source_root=tmp_path)

    assert diagnostics == []


def test_run_source_returns_output() -> None:
    result = run_source('println("hola");')

    assert result.success
    assert result.output == "hola\n"
    assert result.error is None


def test_run_source_can_stream_output_while_retaining_result() -> None:
    chunks: list[str] = []

    result = run_source('println("a"); print("b");', output_writer=chunks.append)

    assert result.success
    assert result.output == "a\nb"
    assert chunks == ["a\n", "b"]


def test_run_source_resolves_imports_from_source_root(tmp_path: Path) -> None:
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

    result = run_source("import Geometry;\nP p = P(1.0, 2.0);\nprintln(p.x);", source_root=tmp_path)

    assert result.success
    assert result.output == "1.0\n"


def test_run_source_returns_error_without_raising() -> None:
    result = run_source("println(missing);")

    assert not result.success
    assert result.output == ""
    assert "Undefined variable 'missing'" in (result.error or "")


def test_completion_items_include_keywords_builtins_and_symbols() -> None:
    items = completion_items("value = 1;\nfunction double square(double x) { return x*x; }\n", 2, 1)
    labels = {item.label for item in items}

    assert {"if", "for", "println", "sqrt", "value", "square"} <= labels


def test_completion_items_include_exception_keywords() -> None:
    items = completion_items("tr", 1, 2)
    labels = {item.label for item in items}

    assert {"try", "catch", "throw"} <= labels


def test_completion_items_include_enum_keyword_and_variants_after_dot() -> None:
    source = "enum SolverStatus { Converged, MaxIterations }\nSolverStatus."
    keyword_labels = {item.label for item in completion_items(source, 1, 1)}
    variant_items = completion_items(source, 2, len("SolverStatus.") + 1)
    variant_labels = {item.label for item in variant_items}

    assert "enum" in keyword_labels
    assert {"Converged", "MaxIterations"} <= variant_labels
