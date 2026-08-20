from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sys

import pytest

from aether.ir import (
    CanonicalRustVerifierRequest,
    RustVerifierAcceptedOutcome,
    RustVerifierInvalidResponse,
    RustVerifierOutputLimitExceeded,
    RustVerifierRequestTooLarge,
    RustVerifierTimeout,
)
from aether.ir.rust_verifier import PersistentSubprocessRustVerifierClient


IDENTITY = {
    "identity_schema_version": 1,
    "executable": "aether-ir-verifier",
    "version": "0.1.0",
    "protocol_versions": [1],
    "ir_schema_versions": [1],
    "capabilities": ["verify"],
}
REQUEST = CanonicalRustVerifierRequest(b"{}\n", 1, 1)


def _server(response: bytes, *, delay: float = 0.0) -> list[str]:
    identity = json.dumps(IDENTITY, separators=(",", ":")).encode() + b"\n"
    source = (
        "import os,struct,time\n"
        f"identity={identity!r}; response={response!r}; delay={delay!r}\n"
        "def frame(value): os.write(1,struct.pack('>I',len(value))+value)\n"
        "frame(identity)\n"
        "while True:\n"
        " h=os.read(0,4)\n"
        " if not h: break\n"
        " while len(h)<4:\n"
        "  x=os.read(0,4-len(h))\n"
        "  if not x: raise SystemExit(3)\n"
        "  h+=x\n"
        " n=struct.unpack('>I',h)[0]; data=b''\n"
        " while len(data)<n: data+=os.read(0,n-len(data))\n"
        " time.sleep(delay); frame(response)\n"
    )
    return [sys.executable, "-c", source]


def test_concurrent_calls_are_serialized_without_frame_corruption() -> None:
    response = b'{"protocol_version":1,"status":"accepted"}\n'
    client = PersistentSubprocessRustVerifierClient(executable=_server(response))
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(client.verify, [REQUEST] * 24))
    finally:
        client.close()
    assert all(isinstance(item.outcome, RustVerifierAcceptedOutcome) for item in outcomes)
    assert client.process_start_count == 1


def test_malformed_response_fails_closed_and_does_not_restart() -> None:
    client = PersistentSubprocessRustVerifierClient(executable=_server(b"not-json"))
    with pytest.raises(RustVerifierInvalidResponse):
        client.verify(REQUEST)
    with pytest.raises(Exception):
        client.verify(REQUEST)
    assert client.process_start_count == 1


def test_oversized_response_fails_closed() -> None:
    client = PersistentSubprocessRustVerifierClient(
        executable=_server(b"x" * 65), stdout_limit_bytes=64
    )
    with pytest.raises(RustVerifierOutputLimitExceeded):
        client.verify(REQUEST)
    assert client.process_start_count == 1


def test_response_timeout_fails_closed_without_retry() -> None:
    client = PersistentSubprocessRustVerifierClient(
        executable=_server(b"{}", delay=0.2), timeout_seconds=0.05
    )
    with pytest.raises(RustVerifierTimeout):
        client.verify(REQUEST)
    assert client.process_start_count == 1


def test_oversized_request_is_rejected_before_process_start() -> None:
    client = PersistentSubprocessRustVerifierClient(
        executable=_server(b"{}"), request_limit_bytes=1
    )
    with pytest.raises(RustVerifierRequestTooLarge):
        client.verify(REQUEST)
    assert client.process_start_count == 0


def test_unexpected_eof_fails_closed_without_restart() -> None:
    identity = json.dumps(IDENTITY, separators=(",", ":")).encode() + b"\n"
    source = (
        "import os,struct\n"
        f"value={identity!r}\n"
        "os.write(1,struct.pack('>I',len(value))+value)\n"
        "os.read(0,4)\n"
    )
    client = PersistentSubprocessRustVerifierClient(
        executable=[sys.executable, "-c", source]
    )
    with pytest.raises(RustVerifierInvalidResponse, match="closed stdout"):
        client.verify(REQUEST)
    assert client.process_start_count == 1
