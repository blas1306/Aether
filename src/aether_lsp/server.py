from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any, BinaryIO

from aether import analyze_source, completion_items


JsonObject = dict[str, Any]


class AetherLanguageServer:
    def __init__(self, reader: BinaryIO | None = None, writer: BinaryIO | None = None) -> None:
        self.reader = reader or sys.stdin.buffer
        self.writer = writer or sys.stdout.buffer
        self.documents: dict[str, str] = {}
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
        if method == "textDocument/completion":
            return self._response(message, self._completion_result(message.get("params") or {}))
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
                "completionProvider": {"triggerCharacters": [".", "(", "_"]},
            }
        }

    def _did_open(self, params: JsonObject) -> None:
        document = params.get("textDocument") or {}
        uri = document.get("uri")
        text = document.get("text", "")
        if isinstance(uri, str) and isinstance(text, str):
            self.documents[uri] = text
            self._publish_diagnostics(uri, text)

    def _did_change(self, params: JsonObject) -> None:
        document = params.get("textDocument") or {}
        uri = document.get("uri")
        changes = params.get("contentChanges") or []
        if not isinstance(uri, str) or not changes:
            return
        text = changes[-1].get("text", "") if isinstance(changes[-1], dict) else ""
        if isinstance(text, str):
            self.documents[uri] = text
            self._publish_diagnostics(uri, text)

    def _did_save(self, params: JsonObject) -> None:
        document = params.get("textDocument") or {}
        uri = document.get("uri")
        if not isinstance(uri, str):
            return
        text = params.get("text")
        if isinstance(text, str):
            self.documents[uri] = text
        self._publish_diagnostics(uri, self.documents.get(uri, ""))

    def _publish_diagnostics(self, uri: str, source: str) -> None:
        try:
            diagnostics = [_lsp_diagnostic(item) for item in analyze_source(source)]
        except Exception as exc:
            diagnostics = [_internal_error_diagnostic(exc)]
        self._write_message(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": {"uri": uri, "diagnostics": diagnostics},
            }
        )

    def _completion_result(self, params: JsonObject) -> JsonObject:
        document = params.get("textDocument") or {}
        position = params.get("position") or {}
        uri = document.get("uri", "")
        source = self.documents.get(uri, "")
        line = int(position.get("line", 0)) + 1
        column = int(position.get("character", 0)) + 1
        try:
            items = [
                {
                    "label": item.label,
                    "kind": _completion_kind(item.kind),
                    "detail": item.detail,
                }
                for item in completion_items(source, line, column)
            ]
        except Exception:
            items = []
        return {"isIncomplete": False, "items": items}

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
        self.writer.write(header + payload)
        self.writer.flush()

    def _response(self, request: JsonObject, result: Any) -> JsonObject:
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}

    def _error_response(self, request: JsonObject, *, code: int, message: str) -> JsonObject:
        return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": code, "message": message}}


def _lsp_diagnostic(diagnostic) -> JsonObject:
    payload = asdict(diagnostic)
    return {
        "range": {
            "start": {"line": max(0, payload["line"] - 1), "character": max(0, payload["column"] - 1)},
            "end": {
                "line": max(0, payload["end_line"] - 1),
                "character": max(0, payload["end_column"] - 1),
            },
        },
        "severity": 1,
        "source": "aether",
        "message": payload["message"],
    }


def _completion_kind(kind: str) -> int:
    return {
        "text": 1,
        "function": 3,
        "variable": 6,
        "keyword": 14,
    }.get(kind, 1)


def _internal_error_diagnostic(exc: Exception) -> JsonObject:
    return {
        "range": {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 1},
        },
        "severity": 2,
        "source": "aether",
        "message": f"Aether analyzer internal error: {type(exc).__name__}: {exc}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aether_lsp.server")
    parser.add_argument("--stdio", action="store_true", help="Run over stdio. Present for IntelliJ compatibility.")
    parser.parse_args(argv)
    return AetherLanguageServer().serve()


if __name__ == "__main__":
    raise SystemExit(main())
