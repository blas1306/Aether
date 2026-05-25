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


def _item_by_label(items: list[dict], label: str) -> dict:
    for item in items:
        if item["label"] == label:
            return item
    raise AssertionError(f"Missing completion item {label!r} in {[item['label'] for item in items]}")


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
    assert "Aether analyzer internal error" in diagnostic["message"]


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
    assert fn["textEdit"]["newText"] == "f(x) = ${1:expression};"
    assert if_snippet["kind"] == 15
    assert if_snippet["insertTextFormat"] == 2
    assert if_snippet["textEdit"]["newText"].startswith("if ${1:condition} {")


def test_lsp_completion_includes_only_document_symbols_before_cursor() -> None:
    source = "localValue = 1;\nlo\nlocalLater = 2;\n"
    items = _completion_items_for(source, line=1, character=2)
    labels = {item["label"] for item in items}

    local_value = _item_by_label(items, "localValue")

    assert "localValue" in labels
    assert "localLater" not in labels
    assert local_value["kind"] == 6
    assert local_value["detail"] == "localValue"


def test_lsp_completion_supports_stdlib_member_context() -> None:
    items = _completion_items_for("Math.", line=0, character=len("Math."))
    labels = [item["label"] for item in items]

    assert labels[:2] == ["LinearAlgebra", "mod"]
    assert _item_by_label(items, "LinearAlgebra")["kind"] == 9


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


def test_lsp_hover_returns_builtin_and_imported_alias_details() -> None:
    source = "import Math.LinearAlgebra\nprintln(1);\nsolve(A, b);\n"

    println_hover = _hover_for(source, line=1, character=1)
    solve_hover = _hover_for(source, line=2, character=1)

    assert println_hover is not None
    assert "println(...)" in println_hover["contents"]["value"]
    assert solve_hover is not None
    assert "solve(...) -> Math.LinearAlgebra.solve(...)" in solve_hover["contents"]["value"]


def test_lsp_hover_returns_none_for_empty_position() -> None:
    assert _hover_for("value = 1;\n", line=0, character=len("value = ")) is None


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
