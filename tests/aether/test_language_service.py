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


def test_analyze_source_accepts_parser_phase_multiple_catches_and_rethrow() -> None:
    diagnostics = analyze_source(
        'try { throw "legacy placeholder"; } '
        "catch (FileError file_error) { } "
        "catch (Error error) { throw; }"
    )

    assert diagnostics == []


def test_analyze_source_reports_malformed_catch_header_without_internal_error() -> None:
    diagnostics = analyze_source("try { } catch (Error) { }\nthrow;")

    assert diagnostics
    assert "Expected catch binder name" in diagnostics[0].message
    assert all("internal compiler error" not in diagnostic.message for diagnostic in diagnostics)


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

    diagnostics = analyze_source("from Geometry import P;\nP p = P(1.0, 2.0);", source_root=tmp_path)

    assert diagnostics == []


def test_run_source_returns_output() -> None:
    result = run_source('println("hola");')

    assert result.success
    assert result.output == "hola\n"
    assert result.error is None
    assert result.exit_code == 0


def test_run_source_propagates_explicit_main_exit_code() -> None:
    result = run_source("int main() { return 7; }")

    assert result.success
    assert result.exit_code == 7


def test_diagnostics_reject_mixed_script_and_explicit_main() -> None:
    diagnostics = analyze_source('println("top");\nint main() {}\n')

    assert len(diagnostics) == 1
    assert "Cannot combine top-level executable statements" in diagnostics[0].message
    assert diagnostics[0].line == 1


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

    result = run_source("from Geometry import P;\nP p = P(1.0, 2.0);\nprintln(p.x);", source_root=tmp_path)

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


def test_completion_items_respect_explicit_import_bindings() -> None:
    module_labels = {
        item.label
        for item in completion_items("import Math.LinearAlgebra as LA;\n", 2, 1)
    }
    symbol_labels = {
        item.label
        for item in completion_items(
            "from Math.LinearAlgebra import solve as linearSolve;\n",
            2,
            1,
        )
    }

    assert "LA" in module_labels
    assert "solve" not in module_labels
    assert "linearSolve" in symbol_labels
    assert "solve" not in symbol_labels


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


def test_completion_items_include_native_members_after_dot() -> None:
    source = "List<int> xs = {1, 2};\nArray<int> a = {1, 2};\nMatrix<double> A = [1 2; 3 4];\nVector<double> v = [3 4];\nstring text = \" value \";\n"

    list_labels = {item.label: item.kind for item in completion_items(source + "xs.", 6, len("xs.") + 1)}
    array_labels = {item.label: item.kind for item in completion_items(source + "a.", 6, len("a.") + 1)}
    matrix_labels = {item.label: item.kind for item in completion_items(source + "A.", 6, len("A.") + 1)}
    vector_labels = {item.label: item.kind for item in completion_items(source + "v.", 6, len("v.") + 1)}
    string_labels = {item.label: item.kind for item in completion_items(source + "text.", 6, len("text.") + 1)}

    list_members = {
        "length": "property",
        "push": "method",
        "pop": "method",
        "insert": "method",
        "removeAt": "method",
        "contains": "method",
        "clear": "method",
        "size": "method",
        "copy": "method",
        "reverse": "method",
        "sort": "method",
    }
    for label, kind in list_members.items():
        assert list_labels[label] == kind
    for label, kind in {"length": "property", "copy": "method"}.items():
        assert array_labels[label] == kind
    for label, kind in {"rows": "property", "columns": "property", "transpose": "method"}.items():
        assert matrix_labels[label] == kind
    for label, kind in {"length": "property", "norm": "method"}.items():
        assert vector_labels[label] == kind
    assert string_labels == {
        "byteLength": "property",
        "trim": "method",
        "split": "method",
    }
