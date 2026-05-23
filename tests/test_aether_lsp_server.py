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
        assert "completionProvider" in initialized["result"]["capabilities"]

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

        process.stdin.write(_message({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None}))
        process.stdin.write(_message({"jsonrpc": "2.0", "method": "exit"}))
        process.stdin.flush()
        shutdown = _read_message(process.stdout)
        assert shutdown["id"] == 3
    finally:
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()

    assert process.returncode == 0
