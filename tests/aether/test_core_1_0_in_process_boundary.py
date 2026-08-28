from __future__ import annotations

import json
from types import SimpleNamespace

from aether.ssa.in_process import InProcessRustSSALoweringClient


class CoreFailure(Exception):
    pass


class FakeSession:
    def lower_ssa(self) -> None:
        return None

    def export_ssa_schema_v2(self) -> bytes:
        return b'{"schema_version":2,"representation":"aether_ssa","functions":[],"structs":[]}'


class FakeCore:
    def accept_initial_ir_schema_v1(self, payload: bytes) -> FakeSession:
        assert json.loads(payload)["schema_version"] == 1
        return FakeSession()


def extension() -> SimpleNamespace:
    return SimpleNamespace(
        QUALIFICATION_ONLY=True,
        CompilerCore=FakeCore,
        AetherCoreError=CoreFailure,
    )


def test_adapter_is_explicit_and_never_starts_a_process() -> None:
    client = InProcessRustSSALoweringClient(extension())
    result = client.lower(b'{"schema_version":1}')
    assert result["ok"] is True
    assert result["ssa"]["schema_version"] == 2
    assert client.process_start_count == 0
    assert client.request_count == 1


def test_adapter_preserves_structured_binding_error() -> None:
    error = CoreFailure("bad input")
    error.kind = "binding"
    error.category = "input_schema"
    error.phase = "initial_ir_import"
    error.code = "CORE-BIND-INPUT-001"
    error.function = None
    error.block = None
    error.source_location = ("broken.ae", 2, 4)

    class RejectingCore:
        def accept_initial_ir_schema_v1(self, _payload: bytes) -> None:
            raise error

    module = extension()
    module.CompilerCore = RejectingCore
    client = InProcessRustSSALoweringClient(module)
    assert client.lower(b"not-json") == {"ok": False, "error": "bad input"}
    assert client.last_error_detail == {
        "kind": "binding",
        "category": "input_schema",
        "phase": "initial_ir_import",
        "code": "CORE-BIND-INPUT-001",
        "function": None,
        "block": None,
        "source_location": ("broken.ae", 2, 4),
    }
