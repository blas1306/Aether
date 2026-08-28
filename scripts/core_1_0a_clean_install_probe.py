#!/usr/bin/env python3
"""Stdlib-only probe run inside a clean CORE-1.0A wheel environment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import struct
import subprocess


def _read_exact(stream, count: int) -> bytes:
    value = stream.read(count)
    if len(value) != count:
        raise RuntimeError("truncated companion frame")
    return value


def _read_frame(stream) -> dict[str, object]:
    size = int.from_bytes(_read_exact(stream, 4), "big")
    if size > 64 * 1024 * 1024:
        raise RuntimeError("oversized companion response")
    value = json.loads(_read_exact(stream, size))
    if not isinstance(value, dict):
        raise RuntimeError("companion returned a non-object")
    return value


def _write_frame(stream, payload: bytes) -> None:
    stream.write(struct.pack(">I", len(payload)) + payload)
    stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companion", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import _aether_core

    payload = args.fixture.read_bytes()
    core = _aether_core.CompilerCore()
    session = core.accept_initial_ir_schema_v1(payload)
    session.lower_ssa()
    first = json.loads(session.export_ssa_schema_v2())
    session.lower_ssa()
    second = json.loads(session.export_ssa_schema_v2())
    try:
        core.accept_initial_ir_schema_v1(b"{")
    except _aether_core.AetherBindingError as error:
        structured_failure = {
            key: getattr(error, key, None)
            for key in ("kind", "category", "phase", "code", "function", "block", "source_location")
        }
    else:
        raise RuntimeError("malformed binding input was accepted")

    process = subprocess.Popen(
        [str(args.companion), "--persistent"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        identity = _read_frame(process.stdout)
        _write_frame(process.stdin, payload)
        companion_first = _read_frame(process.stdout)
        _write_frame(process.stdin, payload)
        companion_second = _read_frame(process.stdout)
        _write_frame(process.stdin, b"{")
        companion_failure = _read_frame(process.stdout)
    finally:
        process.terminate()
        process.wait(timeout=5)

    status = (
        _aether_core.QUALIFICATION_ONLY is True
        and first == second
        and first == companion_first.get("ssa") == companion_second.get("ssa")
        and structured_failure["kind"] == "binding"
        and set(companion_failure) == {"ok", "error"}
        and companion_failure["ok"] is False
        and identity.get("protocol_version") == 1
    )
    report = {
        "status": "PASS" if status else "FAIL",
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "extension_module": str(Path(_aether_core.__file__).resolve()),
        "qualification_only": _aether_core.QUALIFICATION_ONLY,
        "ordinary_lowering": "PASS" if first == companion_first.get("ssa") else "FAIL",
        "structured_failure": structured_failure,
        "repeated_session_use": "PASS" if first == second else "FAIL",
        "companion_protocol_v1": identity,
        "companion_repeated_use": "PASS" if companion_first == companion_second else "FAIL",
        "companion_default_failure_shape": sorted(companion_failure),
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if status else 1


if __name__ == "__main__":
    raise SystemExit(main())
