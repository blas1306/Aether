from __future__ import annotations

import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _message(payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _read_message(stream) -> dict:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        assert line
        decoded = line.decode("ascii").strip()
        if not decoded:
            break
        name, _, value = decoded.partition(":")
        headers[name.lower()] = value.strip()
    body = stream.read(int(headers["content-length"]))
    return json.loads(body.decode("utf-8"))


def _completion_items_for(source: str, *, line: int, character: int) -> list[dict]:
    from aether_lsp.server import AetherLanguageServer

    uri = "file:///tmp/completion.ae"
    language_server = AetherLanguageServer(reader=BytesIO(), writer=BytesIO())
    language_server.documents[uri] = source

    result = language_server._completion_result(
        {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}}
    )
    return result["items"]


def _formatting_edits_for(source: str) -> list[dict]:
    from aether_lsp.server import AetherLanguageServer

    uri = "file:///tmp/formatting.ae"
    language_server = AetherLanguageServer(reader=BytesIO(), writer=BytesIO())
    language_server.documents[uri] = source
    return language_server._formatting_result({"textDocument": {"uri": uri}})


def _document_symbols_for(source: str) -> list[dict]:
    from aether_lsp.server import AetherLanguageServer

    uri = "file:///tmp/symbols.ae"
    language_server = AetherLanguageServer(reader=BytesIO(), writer=BytesIO())
    language_server.documents[uri] = source

    return language_server._document_symbol_result({"textDocument": {"uri": uri}})


def _hover_for(source: str, *, line: int, character: int) -> dict | None:
    from aether_lsp.server import AetherLanguageServer

    uri = "file:///tmp/hover.ae"
    language_server = AetherLanguageServer(reader=BytesIO(), writer=BytesIO())
    language_server.documents[uri] = source

    return language_server._hover_result(
        {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}}
    )


def _definition_for(source: str, *, line: int, character: int) -> dict | None:
    from aether_lsp.server import AetherLanguageServer

    uri = "file:///tmp/definition.ae"
    language_server = AetherLanguageServer(reader=BytesIO(), writer=BytesIO())
    language_server.documents[uri] = source
    return language_server._definition_result(
        {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}}
    )


def _references_for(source: str, *, line: int, character: int) -> list[dict]:
    from aether_lsp.server import AetherLanguageServer

    uri = "file:///tmp/references.ae"
    language_server = AetherLanguageServer(reader=BytesIO(), writer=BytesIO())
    language_server.documents[uri] = source
    return language_server._references_result(
        {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": True},
        }
    )


def _inlay_hints_for(source: str) -> list[dict]:
    from aether_lsp.server import AetherLanguageServer

    uri = "file:///tmp/inlay.ae"
    language_server = AetherLanguageServer(reader=BytesIO(), writer=BytesIO())
    language_server.documents[uri] = source
    return language_server._inlay_hint_result({"textDocument": {"uri": uri}})


def _item_by_label(items: list[dict], label: str) -> dict:
    for item in items:
        if item["label"] == label:
            return item
    raise AssertionError(f"Missing completion item {label!r} in {[item['label'] for item in items]}")


def test_lsp_formats_control_flow_headers_idempotently() -> None:
    source = "if ready {\n} else if( false ){\n}\n"
    edits = _formatting_edits_for(source)
    assert len(edits) == 1
    assert edits[0]["newText"] == "if (ready) {\n} else if (false) {\n}\n"
    assert _formatting_edits_for(edits[0]["newText"]) == []


def test_lsp_formats_abbreviated_function_syntax_idempotently() -> None:
    source = "f(double x)=x * exp(x) - 1.0;\n"
    edits = _formatting_edits_for(source)

    assert edits[0]["newText"] == "f(double x) = x * exp(x) - 1.0;\n"
    assert _formatting_edits_for(edits[0]["newText"]) == []


def test_lsp_formats_multiple_exception_handlers_idempotently() -> None:
    source = "try{throw  value;}catch(FileError file){throw file;}catch(Error error){throw ;}\n"
    edits = _formatting_edits_for(source)

    assert edits[0]["newText"] == (
        "try {throw value;} catch (FileError file) {throw file;} "
        "catch (Error error) {throw;}\n"
    )
    assert _formatting_edits_for(edits[0]["newText"]) == []


def test_lsp_server_keeps_running_when_analyzer_raises(monkeypatch) -> None:
    from aether_lsp import server as lsp_server

    def broken_analyzer(source: str) -> list:
        raise RuntimeError(f"boom while reading {source!r}")

    output = BytesIO()
    monkeypatch.setattr(lsp_server, "analyze_source", broken_analyzer)
    language_server = lsp_server.AetherLanguageServer(reader=BytesIO(), writer=output)

    language_server._publish_diagnostics("file:///tmp/broken.ae", "partial")

    output.seek(0)
    diagnostics = _read_message(output)
    assert diagnostics["method"] == "textDocument/publishDiagnostics"
    diagnostic = diagnostics["params"]["diagnostics"][0]
    assert diagnostic["severity"] == 2
    assert "Aether analyzer internal compiler error [ICE-UNEXPECTED-001]" in diagnostic["message"]
    assert "boom while reading" not in diagnostic["message"]
    assert diagnostic["code"] == "ICE-UNEXPECTED-001"


def test_lsp_diagnostics_include_document_versions() -> None:
    from aether_lsp.server import AetherLanguageServer

    uri = "file:///tmp/versioned.ae"
    output = BytesIO()
    language_server = AetherLanguageServer(reader=BytesIO(), writer=output)

    language_server._did_open(
        {"textDocument": {"uri": uri, "version": 7, "text": "println(missing);"}}
    )
    language_server._did_change(
        {
            "textDocument": {"uri": uri, "version": 8},
            "contentChanges": [{"text": "println(stillMissing);"}],
        }
    )
    language_server._flush_pending_diagnostics(uri)
    language_server._did_close({"textDocument": {"uri": uri}})

    output.seek(0)
    opened = _read_message(output)
    changed = _read_message(output)
    closed = _read_message(output)

    assert opened["params"]["version"] == 7
    assert changed["params"]["version"] == 8
    assert closed["params"]["version"] == 8
    assert closed["params"]["diagnostics"] == []
    assert uri not in language_server.documents
    assert uri not in language_server.document_versions


def test_lsp_diagnostics_resolve_imports_relative_to_document(tmp_path: Path) -> None:
    from aether_lsp.server import AetherLanguageServer

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
    uri = (tmp_path / "main.ae").as_uri()
    output = BytesIO()
    language_server = AetherLanguageServer(reader=BytesIO(), writer=output)

    language_server._did_open(
        {
            "textDocument": {
                "uri": uri,
                "version": 1,
                "text": "from Geometry import P;\nP p = P(1.0, 2.0);\n",
            }
        }
    )

    output.seek(0)
    opened = _read_message(output)
    assert opened["params"]["diagnostics"] == []


def test_lsp_diagnostics_publish_multiple_errors_with_line_ranges() -> None:
    from aether_lsp.server import AetherLanguageServer

    uri = "file:///tmp/multiple.ae"
    output = BytesIO()
    language_server = AetherLanguageServer(reader=BytesIO(), writer=output)

    language_server._did_open(
        {
            "textDocument": {
                "uri": uri,
                "version": 1,
                "text": 'int a = "bad";\nboolean b = 1;\n',
            }
        }
    )

    output.seek(0)
    opened = _read_message(output)
    diagnostics = opened["params"]["diagnostics"]

    assert len(diagnostics) == 2
    assert [diagnostic["range"]["start"]["line"] for diagnostic in diagnostics] == [0, 1]
    assert all(diagnostic["range"]["end"]["character"] > diagnostic["range"]["start"]["character"] for diagnostic in diagnostics)


def test_lsp_diagnostic_clamps_eof_range_inside_document() -> None:
    from aether import Diagnostic
    from aether_lsp.server import _lsp_diagnostic

    source = "value = 1"
    diagnostic = Diagnostic(
        message="Expected expression at end of file.",
        severity="error",
        line=1,
        column=len(source) + 1,
        end_line=1,
        end_column=len(source) + 2,
    )

    payload = _lsp_diagnostic(diagnostic, source)

    assert payload["range"]["start"] == {"line": 0, "character": len(source) - 2}
    assert payload["range"]["end"] == {"line": 0, "character": len(source) - 1}


def test_lsp_diagnostic_clamps_eof_range_after_trailing_newline() -> None:
    from aether import Diagnostic
    from aether_lsp.server import _lsp_diagnostic

    source = "boolean ok = true;\n"
    diagnostic = Diagnostic(
        message="Expected '}' after block.",
        severity="error",
        line=2,
        column=1,
        end_line=2,
        end_column=2,
    )

    payload = _lsp_diagnostic(diagnostic, source)

    assert payload["range"]["start"] == {"line": 0, "character": len("boolean ok = true") - 1}
    assert payload["range"]["end"] == {"line": 0, "character": len("boolean ok = true;") - 1}


def test_lsp_completion_replaces_identifier_prefix_with_builtin_snippet() -> None:
    items = _completion_items_for("pri", line=0, character=3)

    println = _item_by_label(items, "println")

    assert println["kind"] == 3
    assert println["detail"] == "println(...)"
    assert println["documentation"]["value"] == "Aether builtin."
    assert println["filterText"] == "println"
    assert println["textEdit"] == {
        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
        "newText": "println($0)",
    }
    assert println["insertTextFormat"] == 2


def test_lsp_completion_returns_snippet_placeholders_for_language_snippets() -> None:
    fn_items = _completion_items_for("fn", line=0, character=2)
    if_items = _completion_items_for("if", line=0, character=2)

    fn = _item_by_label(fn_items, "fn")
    if_snippet = _item_by_label(if_items, "if")

    assert fn["kind"] == 15
    assert fn["insertTextFormat"] == 2
    assert fn["textEdit"]["newText"] == "f(double x) = ${1:expression};"
    assert if_snippet["kind"] == 15
    assert if_snippet["insertTextFormat"] == 2
    assert if_snippet["textEdit"]["newText"].startswith("if (${1:condition}) {")


def test_lsp_completion_uses_current_exception_surface_only() -> None:
    try_items = _completion_items_for("try", line=0, character=3)
    rethrow_items = _completion_items_for("rethrow", line=0, character=7)
    type_items = _completion_items_for("E", line=0, character=1)

    try_snippet = next(item for item in try_items if item["kind"] == 15 and item["label"] == "try")
    assert "catch (Error error)" in try_snippet["textEdit"]["newText"]
    assert _item_by_label(rethrow_items, "rethrow")["textEdit"]["newText"] == "throw;"
    assert "Error" in {item["label"] for item in type_items}
    assert "Exception" not in {item["label"] for item in type_items}


def test_lsp_completion_includes_only_document_symbols_before_cursor() -> None:
    source = "localValue = 1;\nlo\nlocalLater = 2;\n"
    items = _completion_items_for(source, line=1, character=2)
    labels = {item["label"] for item in items}

    local_value = _item_by_label(items, "localValue")

    assert "localValue" in labels
    assert "localLater" not in labels
    assert local_value["kind"] == 6
    assert local_value["detail"] == "localValue"


def test_lsp_completion_includes_module_function_declared_after_cursor() -> None:
    source = "int main() { return la; }\nint later() { return 1; }\n"
    items = _completion_items_for(source, line=0, character=len("int main() { return la"))

    later = _item_by_label(items, "later")

    assert later["kind"] == 3
    assert later["detail"] == "later()"


def test_lsp_completion_supports_stdlib_member_context() -> None:
    items = _completion_items_for("Math.", line=0, character=len("Math."))
    labels = [item["label"] for item in items]

    assert labels[:2] == ["LinearAlgebra", "mod"]
    assert _item_by_label(items, "LinearAlgebra")["kind"] == 9


def test_lsp_completion_supports_native_member_context() -> None:
    source = "List<int> xs = {1, 2};\nxs."
    items = _completion_items_for(source, line=1, character=len("xs."))

    length = _item_by_label(items, "length")
    copy = _item_by_label(items, "copy")

    assert length["kind"] == 10
    assert length["textEdit"]["newText"] == "length"
    assert copy["kind"] == 2
    assert copy["textEdit"]["newText"] == "copy($0)"
    assert copy["insertTextFormat"] == 2


def test_lsp_completion_exposes_string_byte_length_property() -> None:
    source = 'string text = "é";\ntext.'
    items = _completion_items_for(source, line=1, character=len("text."))

    byte_length = _item_by_label(items, "byteLength")
    trim = _item_by_label(items, "trim")
    split = _item_by_label(items, "split")
    assert byte_length["kind"] == 10
    assert byte_length["textEdit"]["newText"] == "byteLength"
    assert trim["kind"] == 2
    assert trim["textEdit"]["newText"] == "trim($0)"
    assert trim["insertTextFormat"] == 2
    assert split["kind"] == 2
    assert split["detail"] == "string.split(string separator) -> Array<string>"
    assert split["textEdit"]["newText"] == "split($0)"


def test_lsp_catch_binder_completion_hover_symbols_and_navigation() -> None:
    source = (
        "try { work(); }\n"
        "catch (FileError file) { throw file; }\n"
        "catch (Error error) { print(error); println(error.message()); throw; }\n"
        "println(error);\n"
    )
    error_use_character = len("catch (Error error) { print(err")
    hover = _hover_for(source, line=2, character=len("catch (Error err"))
    definition = _definition_for(source, line=2, character=error_use_character)
    references = _references_for(source, line=2, character=error_use_character)
    symbols = _document_symbols_for(source)
    completion_source = source.splitlines()[0] + "\n" + source.splitlines()[1] + "\ncatch (Error error) { error."
    completions = _completion_items_for(
        completion_source,
        line=2,
        character=len("catch (Error error) { error."),
    )

    assert hover is not None
    assert "Error error" in hover["contents"]["value"]
    assert definition == {
        "uri": "file:///tmp/definition.ae",
        "range": {
            "start": {"line": 2, "character": len("catch (Error ")},
            "end": {"line": 2, "character": len("catch (Error error")},
        },
    }
    assert [item["range"]["start"] for item in references] == [
        {"line": 2, "character": len("catch (Error ")},
        {"line": 2, "character": len("catch (Error error) { print(")},
        {"line": 2, "character": len("catch (Error error) { print(error); println(")},
    ]
    assert [(item["name"], item.get("detail")) for item in symbols if item["name"] in {"file", "error"}] == [
        ("file", "FileError file"),
        ("error", "Error error"),
    ]
    assert _item_by_label(completions, "message")["detail"] == "Error.message()"
    assert _hover_for(source, line=3, character=len("println(err")) is None


def test_lsp_hover_documents_error_message_contract() -> None:
    source = "try { work(); } catch (Error error) { println(error.message()); }"
    hover = _hover_for(source, line=0, character=len("try { work(); } catch (Error error) { println(error.mess"))

    assert hover is not None
    assert "Error.message() -> string" in hover["contents"]["value"]
    assert "Nonthrowing" in hover["contents"]["value"]


def test_lsp_catch_symbols_ignore_comments_and_strings() -> None:
    source = (
        '// catch (Error commentBinder) { }\n'
        'string sample = "catch (Error stringBinder) { }";\n'
        "try { work(); } catch (Error realBinder) { throw; }\n"
        "try { work(); } catch (rootBinder) { throw; }\n"
    )

    assert [
        (item["name"], item["detail"])
        for item in _document_symbols_for(source)
        if item["name"].endswith("Binder")
    ] == [("realBinder", "Error realBinder"), ("rootBinder", "Error rootBinder")]


def test_lsp_hover_exposes_string_split_signature() -> None:
    source = 'string text = "a,b";\nArray<string> parts = text.split(",");'
    hover = _hover_for(source, line=1, character=len("Array<string> parts = text.spl"))
    assert hover is not None
    assert "string.split(string separator) -> Array<string>" in hover["contents"]["value"]


def test_lsp_completion_stays_quiet_inside_strings_and_comments() -> None:
    assert _completion_items_for('"pri', line=0, character=len('"pri')) == []
    assert _completion_items_for("// pri", line=0, character=len("// pri")) == []


def test_lsp_document_symbols_include_functions_variables_and_imports() -> None:
    source = (
        "import Math.LinearAlgebra\n"
        "double square(double x) {\n"
        "    return x*x;\n"
        "}\n"
        "value = square(2);\n"
    )

    symbols = _document_symbols_for(source)
    by_name = {item["name"]: item for item in symbols}

    assert by_name["Math.LinearAlgebra"]["kind"] == 2
    assert by_name["Math.LinearAlgebra"]["detail"] == "import Math.LinearAlgebra"
    assert by_name["square"]["kind"] == 12
    assert by_name["square"]["detail"] == "double square(double x)"
    assert by_name["square"]["selectionRange"] == {
        "start": {"line": 1, "character": len("double ")},
        "end": {"line": 1, "character": len("double square")},
    }
    assert by_name["value"]["kind"] == 13


def test_lsp_document_symbol_and_hover_support_inferred_abbreviated_function() -> None:
    source = "f(double x) = x * exp(x) - 1.0;\nvalue = f(1.0);\n"

    symbols = _document_symbols_for(source)
    by_name = {item["name"]: item for item in symbols}
    hover = _hover_for(source, line=1, character=len("value = f"))

    assert by_name["f"]["kind"] == 12
    assert by_name["f"]["detail"] == "f(double x) -> inferred"
    assert hover is not None
    assert "f(double x) -> inferred" in hover["contents"]["value"]


def test_lsp_document_symbols_use_visible_import_aliases() -> None:
    symbols = _document_symbols_for(
        "import Math.LinearAlgebra as LA;\n"
        "from Math.LinearAlgebra import solve as linearSolve;\n"
    )
    by_name = {item["name"]: item for item in symbols}

    assert by_name["LA"]["detail"] == "import Math.LinearAlgebra as LA"
    assert by_name["linearSolve"]["detail"] == (
        "from Math.LinearAlgebra import solve as linearSolve"
    )


def test_lsp_hover_returns_document_symbol_details() -> None:
    source = "double square(double x) { return x*x; }\nvalue = square(2);\n"

    function_hover = _hover_for(source, line=1, character=len("value = s"))
    variable_hover = _hover_for(source, line=1, character=1)

    assert function_hover is not None
    assert "double square(double x)" in function_hover["contents"]["value"]
    assert function_hover["range"] == {
        "start": {"line": 1, "character": len("value = ")},
        "end": {"line": 1, "character": len("value = square")},
    }
    assert variable_hover is not None
    assert "Variable defined in this document" in variable_hover["contents"]["value"]


def test_lsp_hover_and_definition_resolve_function_declared_later() -> None:
    source = "int main() { return later(); }\nint later() { return 1; }\n"

    hover = _hover_for(source, line=0, character=len("int main() { return lat"))
    definition = _definition_for(source, line=0, character=len("int main() { return lat"))

    assert hover is not None
    assert "int later()" in hover["contents"]["value"]
    assert definition == {
        "uri": "file:///tmp/definition.ae",
        "range": {
            "start": {"line": 1, "character": len("int ")},
            "end": {"line": 1, "character": len("int later")},
        },
    }
    references = _references_for(source, line=0, character=len("int main() { return lat"))
    assert [item["range"]["start"] for item in references] == [
        {"line": 0, "character": len("int main() { return ")},
        {"line": 1, "character": len("int ")},
    ]


def test_lsp_hover_returns_builtin_and_imported_alias_details() -> None:
    source = "from Math.LinearAlgebra import solve\nprintln(1);\nsolve(A, b);\n"

    println_hover = _hover_for(source, line=1, character=1)
    solve_hover = _hover_for(source, line=2, character=1)

    assert println_hover is not None
    assert "println(...)" in println_hover["contents"]["value"]
    assert solve_hover is not None
    assert "solve(...) -> Math.LinearAlgebra.solve(...)" in solve_hover["contents"]["value"]


def test_lsp_hover_returns_none_for_empty_position() -> None:
    assert _hover_for("value = 1;\n", line=0, character=len("value = ")) is None


def test_lsp_inlay_hints_show_parameter_names_for_safe_function_calls() -> None:
    source = (
        "int sum(int a, int b, int c) { return a + b + c; }\n"
        "int main() {\n"
        "    int value = sum(1, 2, 3);\n"
        "    return value;\n"
        "}\n"
    )

    hints = _inlay_hints_for(source)
    labels = [hint["label"] for hint in hints]

    assert labels == ["a:", "b:", "c:"]
    assert all(hint["position"]["line"] == 2 for hint in hints)
    assert [hint["position"]["character"] for hint in hints] == [
        len("    int value = sum("),
        len("    int value = sum(1, "),
        len("    int value = sum(1, 2, "),
    ]


def test_lsp_inlay_hints_for_multiline_and_nested_calls() -> None:
    source = (
        "int inner(int a, int b) { return a + b; }\n"
        "int outer(int x, int y) { return x + y; }\n"
        "int main() {\n"
        "    int value = outer(\n"
        "        inner(1, 2),\n"
        "        3\n"
        "    );\n"
        "    return value;\n"
        "}\n"
    )

    hints = _inlay_hints_for(source)
    labels = [hint["label"] for hint in hints]

    assert labels == ["a:", "b:", "x:", "y:"]
    assert hints[0]["position"]["line"] == 3
    assert hints[1]["position"]["line"] == 3
    assert hints[2]["position"]["line"] == 4
    assert hints[3]["position"]["line"] == 5


def test_lsp_inlay_hints_ignore_functions_without_parameters() -> None:
    source = (
        "int hello() { return 1; }\n"
        "int main() {\n"
        "    return hello();\n"
        "}\n"
    )

    assert _inlay_hints_for(source) == []


def test_lsp_inlay_hints_ignore_unknown_or_unresolvable_calls() -> None:
    source = (
        "int add(int a, int b) { return a + b; }\n"
        "int main() {\n"
        "    return missing(1, 2);\n"
        "}\n"
    )

    assert _inlay_hints_for(source) == []


def test_lsp_inlay_hints_ignore_wrong_arity_and_keep_same_file_multiple_calls() -> None:
    source = (
        "int add(int a, int b) { return a + b; }\n"
        "int mul(int x, int y) { return x * y; }\n"
        "int main() {\n"
        "    int value = add(1);\n"
        "    int other = mul(2, 3) + add(4, 5);\n"
        "    return value + other;\n"
        "}\n"
    )

    hints = _inlay_hints_for(source)
    labels = [hint["label"] for hint in hints]

    assert labels == ["x:", "y:", "a:", "b:"]
    assert [hint["position"]["line"] for hint in hints] == [3, 3, 4, 4]


def test_lsp_inlay_hints_multiple_calls_in_same_file() -> None:
    source = (
        "int f(int a, int b) { return a + b; }\n"
        "int g(int x, int y, int z) { return x + y + z; }\n"
        "int main() {\n"
        "    int v1 = f(1, 2);\n"
        "    int v2 = g(3, 4, 5);\n"
        "    return v1 + v2;\n"
        "}\n"
    )

    hints = _inlay_hints_for(source)
    labels = [hint["label"] for hint in hints]

    assert labels == ["a:", "b:", "x:", "y:", "z:"]


def test_lsp_inlay_hints_support_struct_and_class_methods_and_constructors() -> None:
    source = (
        "struct Vector {\n"
        "    double x;\n"
        "    double y;\n"
        "    void translate(double dx, double dy) { this.x = this.x + dx; this.y = this.y + dy; }\n"
        "}\n"
        "class Camera {\n"
        "    int zoom;\n"
        "    void focus(int step, int strength) { this.zoom = step + strength; }\n"
        "}\n"
        "struct Point {\n"
        "    double x;\n"
        "    double y;\n"
        "    constructor(double x0, double y0) { this.x = x0; this.y = y0; }\n"
        "}\n"
        "struct Origin {\n"
        "    double x;\n"
        "    double y;\n"
        "}\n"
        "int main() {\n"
        "    Vector v = Vector(0.0, 0.0);\n"
        "    v.translate(2.0, 3.0);\n"
        "    Camera c = Camera();\n"
        "    c.focus(4, 5);\n"
        "    Point p = Point(10.0, 20.0);\n"
        "    Origin origin = Origin(9.0, 8.0);\n"
        "    return 0;\n"
        "}\n"
    )

    hints = _inlay_hints_for(source)
    labels = [hint["label"] for hint in hints]

    assert labels == ["x:", "y:", "dx:", "dy:", "step:", "strength:", "x0:", "y0:", "x:", "y:"]
    assert any(hint["label"] == "dx:" for hint in hints)
    assert any(hint["label"] == "x0:" for hint in hints)


def test_lsp_inlay_hints_resolve_methods_by_receiver_type_and_ignore_invalid_calls() -> None:
    source = (
        "struct PrintThing {\n"
        "    void run(int value) { }\n"
        "}\n"
        "struct OtherThing {\n"
        "    void run(double scale) { }\n"
        "}\n"
        "struct Payload {\n"
        "    int value;\n"
        "}\n"
        "int main() {\n"
        "    PrintThing a = PrintThing();\n"
        "    OtherThing b = OtherThing();\n"
        "    a.run(1);\n"
        "    b.run(2.0);\n"
        "    Payload p = Payload(1);\n"
        "    unknown.run(1);\n"
        "    return 0;\n"
        "}\n"
    )

    hints = _inlay_hints_for(source)
    labels = [hint["label"] for hint in hints]

    assert labels == ["value:", "scale:", "value:"]
    assert all(label != "value:" for label in labels[:1]) is False


def test_lsp_inlay_hints_for_methods_and_constructors_update_after_edit() -> None:
    from aether_lsp.server import AetherLanguageServer

    uri = "file:///tmp/inlay_refresh.ae"
    server = AetherLanguageServer(reader=BytesIO(), writer=BytesIO())
    server.documents[uri] = (
        "struct Point {\n"
        "    double x;\n"
        "    double y;\n"
        "}\n"
        "int main() {\n"
        "    Point p = Point(1.0, 2.0);\n"
        "    return 0;\n"
        "}\n"
    )
    first = server._inlay_hint_result({"textDocument": {"uri": uri}})
    assert [hint["label"] for hint in first] == ["x:", "y:"]

    server.documents[uri] = (
        "struct Point {\n"
        "    double px;\n"
        "    double py;\n"
        "}\n"
        "int main() {\n"
        "    Point p = Point(1.0, 2.0);\n"
        "    return 0;\n"
        "}\n"
    )
    server.semantic_cache.pop(uri, None)
    refreshed = server._inlay_hint_result({"textDocument": {"uri": uri}})
    assert [hint["label"] for hint in refreshed] == ["px:", "py:"]


def test_lsp_server_initializes_publishes_diagnostics_and_completes() -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", "aether_lsp.server", "--stdio"],
        cwd=ROOT,
        env={"PYTHONPATH": str(SRC)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        process.stdin.write(_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))
        process.stdin.flush()
        initialized = _read_message(process.stdout)
        assert initialized["id"] == 1
        completion_provider = initialized["result"]["capabilities"]["completionProvider"]
        assert "p" in completion_provider["triggerCharacters"]
        assert "\\" in completion_provider["triggerCharacters"]
        assert initialized["result"]["capabilities"]["documentSymbolProvider"] is True
        assert initialized["result"]["capabilities"]["hoverProvider"] is True
        assert initialized["result"]["capabilities"]["documentFormattingProvider"] is True

        uri = "file:///tmp/demo.ae"
        process.stdin.write(
            _message(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {
                            "uri": uri,
                            "languageId": "aether",
                            "version": 1,
                            "text": "println(missing);",
                        }
                    },
                }
            )
        )
        process.stdin.flush()
        diagnostics = _read_message(process.stdout)
        assert diagnostics["method"] == "textDocument/publishDiagnostics"
        assert diagnostics["params"]["version"] == 1
        assert diagnostics["params"]["diagnostics"]

        process.stdin.write(
            _message(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "textDocument/completion",
                    "params": {"textDocument": {"uri": uri}, "position": {"line": 0, "character": 3}},
                }
            )
        )
        process.stdin.flush()
        completion = _read_message(process.stdout)
        labels = {item["label"] for item in completion["result"]["items"]}
        assert "println" in labels

        process.stdin.write(
            _message(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "textDocument/documentSymbol",
                    "params": {"textDocument": {"uri": uri}},
                }
            )
        )
        process.stdin.flush()
        symbols = _read_message(process.stdout)
        assert symbols["id"] == 3
        assert symbols["result"] == []

        process.stdin.write(_message({"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": None}))
        process.stdin.write(_message({"jsonrpc": "2.0", "method": "exit"}))
        process.stdin.flush()
        shutdown = _read_message(process.stdout)
        assert shutdown["id"] == 4
    finally:
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()

    assert process.returncode == 0
