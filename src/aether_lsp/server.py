from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from bisect import bisect_right
from dataclasses import asdict
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import unquote, urlparse

from aether import analyze_source
from aether.stdlib.registry import builtin_aliases_for_import, builtin_names, is_builtin_namespace
from autocomplete_engine import (
    AutocompleteRequest,
    build_autocomplete_suggestions,
    detect_autocomplete_match,
)
from command_catalog import CommandSuggestion
from document_symbols import (
    SourceRange,
    extract_document_symbol_occurrences,
    extract_document_symbols,
    identifier_at_offset,
    symbol_before_offset,
)


JsonObject = dict[str, Any]
DIAGNOSTIC_DEBOUNCE_SECONDS = 0.35
FALLBACK_BUILTIN_NAMES = {
    "abs",
    "angle",
    "cols",
    "complex",
    "conj",
    "cos",
    "exp",
    "imag",
    "length",
    "ln",
    "log",
    "Math.LinearAlgebra.eig",
    "Math.LinearAlgebra.SVD",
    "Math.LinearAlgebra.solve",
    "Math.mod",
    "plot",
    "print",
    "println",
    "real",
    "rows",
    "sin",
    "sqrt",
    "tan",
}


class AetherLanguageServer:
    def __init__(self, reader: BinaryIO | None = None, writer: BinaryIO | None = None) -> None:
        self.reader = reader or sys.stdin.buffer
        self.writer = writer or sys.stdout.buffer
        self.documents: dict[str, str] = {}
        self.document_versions: dict[str, int] = {}
        self.pending_diagnostics: dict[str, threading.Timer] = {}
        self.write_lock = threading.RLock()
        self.shutdown_requested = False

    def serve(self) -> int:
        while True:
            message = self._read_message()
            if message is None:
                return 0
            response = self._handle_message(message)
            if response is not None:
                self._write_message(response)
            if message.get("method") == "exit":
                return 0 if self.shutdown_requested else 1

    def _handle_message(self, message: JsonObject) -> JsonObject | None:
        method = message.get("method")
        if method == "initialize":
            return self._response(message, self._initialize_result())
        if method == "shutdown":
            self.shutdown_requested = True
            return self._response(message, None)
        if method == "exit":
            return None
        if method == "textDocument/didOpen":
            self._did_open(message.get("params") or {})
            return None
        if method == "textDocument/didChange":
            self._did_change(message.get("params") or {})
            return None
        if method == "textDocument/didSave":
            self._did_save(message.get("params") or {})
            return None
        if method == "textDocument/didClose":
            self._did_close(message.get("params") or {})
            return None
        if method == "textDocument/completion":
            return self._response(message, self._completion_result(message.get("params") or {}))
        if method == "textDocument/documentSymbol":
            return self._response(message, self._document_symbol_result(message.get("params") or {}))
        if method == "textDocument/hover":
            return self._response(message, self._hover_result(message.get("params") or {}))
        if "id" in message:
            return self._error_response(message, code=-32601, message=f"Method not found: {method}")
        return None

    def _initialize_result(self) -> JsonObject:
        return {
            "capabilities": {
                "textDocumentSync": {
                    "openClose": True,
                    "change": 1,
                    "save": {"includeText": True},
                },
                "completionProvider": {
                    "triggerCharacters": _completion_trigger_characters(),
                    "resolveProvider": False,
                },
                "documentSymbolProvider": True,
                "hoverProvider": True,
            }
        }

    def _did_open(self, params: JsonObject) -> None:
        document = params.get("textDocument") or {}
        uri = document.get("uri")
        text = document.get("text", "")
        if isinstance(uri, str) and isinstance(text, str):
            self.documents[uri] = text
            version = _document_version(document)
            if version is not None:
                self.document_versions[uri] = version
            self._publish_diagnostics(uri, text, version)

    def _did_change(self, params: JsonObject) -> None:
        document = params.get("textDocument") or {}
        uri = document.get("uri")
        changes = params.get("contentChanges") or []
        if not isinstance(uri, str) or not changes:
            return
        text = changes[-1].get("text", "") if isinstance(changes[-1], dict) else ""
        if isinstance(text, str):
            version = _document_version(document, default=self.document_versions.get(uri))
            self.documents[uri] = text
            if version is not None:
                self.document_versions[uri] = version
            self._schedule_diagnostics(uri, text, version)

    def _did_save(self, params: JsonObject) -> None:
        document = params.get("textDocument") or {}
        uri = document.get("uri")
        if not isinstance(uri, str):
            return
        text = params.get("text")
        if isinstance(text, str):
            self.documents[uri] = text
        version = _document_version(document, default=self.document_versions.get(uri))
        if version is not None:
            self.document_versions[uri] = version
        self._cancel_pending_diagnostics(uri)
        self._publish_diagnostics(uri, self.documents.get(uri, ""), version)

    def _did_close(self, params: JsonObject) -> None:
        document = params.get("textDocument") or {}
        uri = document.get("uri")
        if not isinstance(uri, str):
            return
        version = self.document_versions.pop(uri, None)
        self.documents.pop(uri, None)
        self._cancel_pending_diagnostics(uri)
        self._write_message(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": _diagnostic_params(uri, [], version),
            }
        )

    def _schedule_diagnostics(self, uri: str, source: str, version: int | None = None) -> None:
        self._cancel_pending_diagnostics(uri)
        timer = threading.Timer(
            DIAGNOSTIC_DEBOUNCE_SECONDS,
            self._publish_diagnostics_if_current,
            args=(uri, source, version),
        )
        timer.daemon = True
        self.pending_diagnostics[uri] = timer
        timer.start()

    def _cancel_pending_diagnostics(self, uri: str) -> None:
        timer = self.pending_diagnostics.pop(uri, None)
        if timer is not None:
            timer.cancel()

    def _flush_pending_diagnostics(self, uri: str) -> None:
        if uri not in self.pending_diagnostics:
            return
        self._cancel_pending_diagnostics(uri)
        source = self.documents.get(uri)
        if source is not None:
            self._publish_diagnostics(uri, source, self.document_versions.get(uri))

    def _publish_diagnostics_if_current(self, uri: str, source: str, version: int | None = None) -> None:
        if self.documents.get(uri) != source:
            return
        if version is not None and self.document_versions.get(uri) != version:
            return
        self.pending_diagnostics.pop(uri, None)
        self._publish_diagnostics(uri, source, version)

    def _publish_diagnostics(self, uri: str, source: str, version: int | None = None) -> None:
        try:
            diagnostics = [
                _lsp_diagnostic(item, source)
                for item in analyze_source(source, source_root=_source_root_for_uri(uri))
            ]
        except Exception as exc:
            diagnostics = [_internal_error_diagnostic(exc, source)]
        self._write_message(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": _diagnostic_params(uri, diagnostics, version),
            }
        )

    def _completion_result(self, params: JsonObject) -> JsonObject:
        document = params.get("textDocument") or {}
        position = params.get("position") or {}
        uri = document.get("uri", "")
        source = self.documents.get(uri, "")

        line = int(position.get("line", 0))
        character = int(position.get("character", 0))
        line_text = _line_text_at(source, line)
        cursor_col = min(max(0, character), len(line_text))
        match = detect_autocomplete_match(line_text, cursor_col)
        if match is None:
            return {"isIncomplete": False, "items": []}

        source_offset = _position_to_offset(source, _line_start_offsets(source), line, cursor_col)
        try:
            suggestions = build_autocomplete_suggestions(
                AutocompleteRequest(
                    line_text=line_text,
                    cursor_col=cursor_col,
                    document_kind="script",
                    document_text=source[:source_offset],
                )
            )
            replace_range = _lsp_completion_range(line, match.token_start_col, match.token_end_col)
            items = [
                _lsp_completion_item(suggestion, index, replace_range)
                for index, suggestion in enumerate(suggestions)
            ]
        except Exception:
            items = []
        return {"isIncomplete": False, "items": items}

    def _document_symbol_result(self, params: JsonObject) -> list[JsonObject]:
        document = params.get("textDocument") or {}
        uri = document.get("uri", "")
        source = self.documents.get(uri, "")
        try:
            return [_lsp_document_symbol(symbol) for symbol in extract_document_symbol_occurrences(source)]
        except Exception:
            return []

    def _hover_result(self, params: JsonObject) -> JsonObject | None:
        document = params.get("textDocument") or {}
        position = params.get("position") or {}
        uri = document.get("uri", "")
        source = self.documents.get(uri, "")
        if not source:
            return None

        line = int(position.get("line", 0))
        character = int(position.get("character", 0))
        line_starts = _line_start_offsets(source)
        offset = _position_to_offset(source, line_starts, line, character)
        token = _hover_token_at_offset(source, offset)
        if token is None:
            return None
        name, token_start, token_end = token

        symbol = symbol_before_offset(source, name, offset)
        if symbol is not None and symbol.origin != "import":
            return _lsp_hover(
                _symbol_hover_markdown(symbol),
                _lsp_range_from_offsets(source, line_starts, token_start, token_end),
            )

        builtin_name = _resolve_builtin_hover_name(source, name)
        if builtin_name is not None:
            return _lsp_hover(
                _builtin_hover_markdown(name, builtin_name),
                _lsp_range_from_offsets(source, line_starts, token_start, token_end),
            )

        if symbol is not None:
            return _lsp_hover(
                _symbol_hover_markdown(symbol),
                _lsp_range_from_offsets(source, line_starts, token_start, token_end),
            )

        if _safe_is_builtin_namespace(name):
            return _lsp_hover(
                f"```aether\n{name}\n```\n\nAether namespace.",
                _lsp_range_from_offsets(source, line_starts, token_start, token_end),
            )

        return None

    def _read_message(self) -> JsonObject | None:
        headers: dict[str, str] = {}
        while True:
            line = self.reader.readline()
            if not line:
                return None
            decoded = line.decode("ascii").strip()
            if not decoded:
                break
            name, _, value = decoded.partition(":")
            headers[name.lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        if length <= 0:
            return None
        payload = self.reader.read(length)
        return json.loads(payload.decode("utf-8"))

    def _write_message(self, message: JsonObject) -> None:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        with self.write_lock:
            self.writer.write(header + payload)
            self.writer.flush()

    def _response(self, request: JsonObject, result: Any) -> JsonObject:
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}

    def _error_response(self, request: JsonObject, *, code: int, message: str) -> JsonObject:
        return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": code, "message": message}}


def _lsp_document_symbol(symbol) -> JsonObject:
    item: JsonObject = {
        "name": symbol.name,
        "kind": _document_symbol_kind(symbol.kind),
        "range": _source_range_to_lsp(symbol.range),
        "selectionRange": _source_range_to_lsp(symbol.selection_range),
    }
    if symbol.detail:
        item["detail"] = symbol.detail
    return item


def _document_symbol_kind(kind: str) -> int:
    return {
        "module": 2,
        "type": 5,
        "function": 12,
        "variable": 13,
    }.get(kind, 13)


def _source_range_to_lsp(source_range: SourceRange) -> JsonObject:
    return {
        "start": {"line": source_range.start_line, "character": source_range.start_character},
        "end": {"line": source_range.end_line, "character": source_range.end_character},
    }


def _lsp_hover(markdown: str, hover_range: JsonObject) -> JsonObject:
    return {
        "contents": {"kind": "markdown", "value": markdown},
        "range": hover_range,
    }


def _symbol_hover_markdown(symbol) -> str:
    signature = symbol.detail or symbol.signature
    description = {
        "function": "User function defined in this document.",
        "module": "Aether import.",
        "type": "Type alias defined in this document.",
        "variable": "Variable defined in this document.",
    }.get(symbol.kind, "Aether symbol.")
    if symbol.origin == "for_loop_variable":
        description = "Loop variable defined in this document."
    if symbol.origin == "struct":
        description = "Struct type defined in this document."
    if symbol.origin == "interface":
        description = "Interface type defined in this document."
    if symbol.origin == "enum":
        description = "Enum type defined in this document."
    return f"```aether\n{signature}\n```\n\n{description}"


def _builtin_hover_markdown(name: str, builtin_name: str) -> str:
    if name == builtin_name:
        signature = f"{name}(...)"
        description = "Aether builtin."
    else:
        signature = f"{name}(...) -> {builtin_name}(...)"
        description = "Aether builtin imported into the current document."
    return f"```aether\n{signature}\n```\n\n{description}"


def _resolve_builtin_hover_name(source: str, name: str) -> str | None:
    names = _safe_builtin_names()
    if name in names:
        return name
    from_pattern = re.compile(
        r"^\s*from\s+(?P<module>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s+import\s+"
        r"(?P<symbol>[A-Za-z_]\w*)(?:\s+as\s+(?P<alias>[A-Za-z_]\w*))?\b",
        re.MULTILINE,
    )
    for match in from_pattern.finditer(source):
        local_name = match.group("alias") or match.group("symbol")
        canonical_name = f"{match.group('module')}.{match.group('symbol')}"
        if local_name == name and canonical_name in names:
            return canonical_name
    import_pattern = re.compile(
        r"^\s*import\s+(?P<module>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)"
        r"(?:\s+as\s+(?P<alias>[A-Za-z_]\w*))?\b",
        re.MULTILINE,
    )
    for match in import_pattern.finditer(source):
        binding = match.group("alias") or match.group("module")
        if name.startswith(binding + "."):
            canonical_name = match.group("module") + name[len(binding) :]
            if canonical_name in names:
                return canonical_name
    for symbol in extract_document_symbols(source):
        if symbol.origin != "import" or not _safe_is_builtin_namespace(symbol.name):
            continue
        builtin_name = _safe_builtin_aliases_for_import(symbol.name).get(name)
        if builtin_name is not None:
            return builtin_name
    return None


def _safe_builtin_names() -> set[str]:
    try:
        return set(builtin_names())
    except Exception:
        return set(FALLBACK_BUILTIN_NAMES)


def _safe_is_builtin_namespace(name: str) -> bool:
    try:
        return is_builtin_namespace(name)
    except Exception:
        prefix = f"{name}."
        return any(item.startswith(prefix) for item in FALLBACK_BUILTIN_NAMES)


def _safe_builtin_aliases_for_import(module_name: str) -> dict[str, str]:
    try:
        return builtin_aliases_for_import(module_name)
    except Exception:
        prefix = f"{module_name}."
        return {
            builtin_name[len(prefix) :]: builtin_name
            for builtin_name in FALLBACK_BUILTIN_NAMES
            if builtin_name.startswith(prefix) and "." not in builtin_name[len(prefix) :]
        }


def _hover_token_at_offset(source: str, offset: int) -> tuple[str, int, int] | None:
    if not source:
        return None
    offset = min(max(0, offset), len(source) - 1)
    if not _is_hover_identifier_char(source[offset]) and offset > 0:
        offset -= 1
    if not _is_hover_identifier_char(source[offset]):
        return None

    start = offset
    while start > 0 and _is_hover_identifier_char(source[start - 1]):
        start -= 1
    end = offset + 1
    while end < len(source) and _is_hover_identifier_char(source[end]):
        end += 1

    while start < end and source[start] == ".":
        start += 1
    while end > start and source[end - 1] == ".":
        end -= 1
    if start >= end:
        return None
    name = source[start:end]
    if identifier_at_offset(source, offset) != name:
        return None
    return name, start, end


def _is_hover_identifier_char(char: str) -> bool:
    return char.isalnum() or char in "_.!"


def _lsp_range_from_offsets(source: str, line_starts: list[int], start_offset: int, end_offset: int) -> JsonObject:
    source_len = len(source)
    start = _offset_to_position(line_starts, min(max(0, start_offset), source_len))
    end = _offset_to_position(line_starts, min(max(start_offset, end_offset), source_len))
    return {
        "start": {"line": start[0], "character": start[1]},
        "end": {"line": end[0], "character": end[1]},
    }


def _document_version(document: JsonObject, default: int | None = None) -> int | None:
    version = document.get("version", default)
    return version if isinstance(version, int) else default


def _source_root_for_uri(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file" or not parsed.path:
        return None
    return Path(unquote(parsed.path)).parent


def _diagnostic_params(uri: str, diagnostics: list[JsonObject], version: int | None = None) -> JsonObject:
    params: JsonObject = {"uri": uri, "diagnostics": diagnostics}
    if version is not None:
        params["version"] = version
    return params


def _lsp_diagnostic(diagnostic, source: str = "") -> JsonObject:
    payload = asdict(diagnostic)
    return {
        "range": _safe_lsp_range(
            source,
            payload["line"],
            payload["column"],
            payload["end_line"],
            payload["end_column"],
        ),
        "severity": 1,
        "source": "aether",
        "message": payload["message"],
    }


def _completion_kind(kind: str) -> int:
    return {
        "command": 3,
        "text": 1,
        "function": 3,
        "method": 2,
        "module": 9,
        "property": 10,
        "snippet": 15,
        "variable": 6,
        "keyword": 14,
    }.get(kind, 1)


def _completion_trigger_characters() -> list[str]:
    identifier_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return [".", "(", "_", "\\"] + list(identifier_chars)


def _lsp_completion_range(line: int, start_col: int, end_col: int) -> JsonObject:
    return {
        "start": {"line": max(0, line), "character": max(0, start_col)},
        "end": {"line": max(0, line), "character": max(0, end_col)},
    }


def _lsp_completion_item(suggestion: CommandSuggestion, index: int, replace_range: JsonObject) -> JsonObject:
    label = suggestion.label or suggestion.name
    new_text, is_snippet = _lsp_insert_text(suggestion)
    item: JsonObject = {
        "label": label,
        "kind": _completion_kind(suggestion.kind),
        "detail": suggestion.signature,
        "documentation": {"kind": "markdown", "value": suggestion.description},
        "filterText": suggestion.match_text or label,
        "sortText": f"{index:04d}_{label.casefold()}",
        "textEdit": {
            "range": replace_range,
            "newText": new_text,
        },
    }
    if is_snippet:
        item["insertTextFormat"] = 2
    return item


def _lsp_insert_text(suggestion: CommandSuggestion) -> tuple[str, bool]:
    insert_text = suggestion.insert_text
    cursor_backtrack = suggestion.cursor_backtrack or 0
    selection_length = suggestion.cursor_selection_length or 0
    if cursor_backtrack <= 0 and selection_length <= 0:
        return insert_text, False

    cursor_pos = max(0, min(len(insert_text), len(insert_text) - cursor_backtrack))
    selection_end = max(cursor_pos, min(len(insert_text), cursor_pos + selection_length))

    before = _escape_lsp_snippet(insert_text[:cursor_pos])
    selected = _escape_lsp_snippet(insert_text[cursor_pos:selection_end])
    after = _escape_lsp_snippet(insert_text[selection_end:])
    if selection_length > 0:
        return f"{before}${{1:{selected}}}{after}", True
    return f"{before}$0{after}", True


def _escape_lsp_snippet(text: str) -> str:
    return text.replace("\\", "\\\\").replace("$", "\\$").replace("}", "\\}")


def _internal_error_diagnostic(exc: Exception, source: str = "") -> JsonObject:
    return {
        "range": _safe_lsp_range(source, 1, 1, 1, 2),
        "severity": 2,
        "source": "aether",
        "message": f"Aether analyzer internal error: {type(exc).__name__}: {exc}",
    }


def _safe_lsp_range(
    source: str,
    line: int,
    column: int,
    end_line: int,
    end_column: int,
) -> JsonObject:
    if not source:
        return {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 0},
        }

    line_starts = _line_start_offsets(source)
    source_len = len(source)
    start_offset = _position_to_offset(source, line_starts, line - 1, column - 1)
    end_offset = _position_to_offset(source, line_starts, end_line - 1, end_column - 1)

    if start_offset >= source_len or end_offset >= source_len:
        start_offset, end_offset = _eof_fallback_span(source)
    elif end_offset <= start_offset:
        end_offset = min(start_offset + 1, source_len)
        if end_offset >= source_len:
            start_offset, end_offset = _eof_fallback_span(source)

    start = _offset_to_position(line_starts, start_offset)
    end = _offset_to_position(line_starts, end_offset)
    return {
        "start": {"line": start[0], "character": start[1]},
        "end": {"line": end[0], "character": end[1]},
    }


def _line_start_offsets(source: str) -> list[int]:
    starts = [0]
    for idx, char in enumerate(source):
        if char == "\n":
            starts.append(idx + 1)
    return starts


def _line_text_at(source: str, line: int) -> str:
    line_starts = _line_start_offsets(source)
    line_idx = min(max(0, line), len(line_starts) - 1)
    line_start = line_starts[line_idx]
    line_end = source.find("\n", line_start)
    if line_end < 0:
        line_end = len(source)
    return source[line_start:line_end]


def _position_to_offset(source: str, line_starts: list[int], line: int, character: int) -> int:
    line_idx = min(max(0, line), len(line_starts) - 1)
    line_start = line_starts[line_idx]
    line_end = source.find("\n", line_start)
    if line_end < 0:
        line_end = len(source)
    return min(line_start + max(0, character), line_end)


def _offset_to_position(line_starts: list[int], offset: int) -> tuple[int, int]:
    line_idx = max(0, bisect_right(line_starts, offset) - 1)
    return line_idx, max(0, offset - line_starts[line_idx])


def _eof_fallback_span(source: str) -> tuple[int, int]:
    idx = len(source) - 1
    while idx >= 0 and source[idx] in "\r\n":
        idx -= 1
    if idx <= 0:
        return 0, min(1, len(source))
    return idx - 1, idx


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aether_lsp.server")
    parser.add_argument("--stdio", action="store_true", help="Run over stdio. Present for IntelliJ compatibility.")
    parser.parse_args(argv)
    return AetherLanguageServer().serve()


if __name__ == "__main__":
    raise SystemExit(main())
