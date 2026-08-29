"""In-process adapter for the productive native CompilerCore distribution."""

from __future__ import annotations

import json
import threading
from types import ModuleType
from typing import Mapping


class InProcessRustSSALoweringClient:
    """Adapt the PyO3 core session to the existing Rust-client shape.

    A client owns and reuses one thread-safe ``CompilerCore``. Every request
    still gets its own Rust-owned ``CompilationSession``. Productive discovery
    goes exclusively through the stable ``aether_compiler_core`` wrapper; an
    explicit module remains supported for the qualified boundary tests.
    """

    def __init__(self, extension: ModuleType | None = None) -> None:
        if extension is None:
            try:
                from aether_compiler_core import binding
            except ImportError as exc:
                raise RuntimeError(
                    "compatible aether-compiler-core is required for the "
                    "in-process Rust core transport"
                ) from exc
            extension = binding()
        self._extension = extension
        qualification_only = getattr(self._extension, "QUALIFICATION_ONLY", None)
        if qualification_only is False:
            expected = {
                "__version__": "1.0.0rc4",
                "COMPILER_CORE_API_VERSION": 1,
                "PROTOCOL_VERSION": 1,
                "INPUT_SCHEMA_VERSIONS": (1,),
                "OUTPUT_SCHEMA_VERSIONS": (2,),
            }
            mismatches = {
                name: getattr(self._extension, name, None)
                for name, value in expected.items()
                if (
                    tuple(getattr(self._extension, name, ())) != value
                    if isinstance(value, tuple)
                    else getattr(self._extension, name, None) != value
                )
            }
            if mismatches:
                raise RuntimeError(
                    f"productive in-process compiler core is incompatible: {mismatches!r}"
                )
        elif qualification_only is not True:
            raise RuntimeError("in-process compiler core has no recognized provenance")
        self._core = self._extension.CompilerCore()
        self._requests = 0
        self._request_lock = threading.Lock()
        self._thread_state = threading.local()

    @property
    def last_error_detail(self) -> dict[str, object] | None:
        """Structured detail for the calling thread's most recent request."""
        return getattr(self._thread_state, "last_error_detail", None)

    @property
    def process_start_count(self) -> int:
        return 0

    @property
    def request_count(self) -> int:
        with self._request_lock:
            return self._requests

    def lower(self, payload: bytes) -> Mapping[str, object]:
        """Run the current qualified SSA operation on a Rust-owned session."""
        self._thread_state.last_error_detail = None
        with self._request_lock:
            self._requests += 1
        try:
            session = self._core.accept_initial_ir_schema_v1(payload)
            session.lower_ssa()
            raw_ssa = session.export_ssa_schema_v2()
            ssa = json.loads(raw_ssa)
        except self._extension.AetherCoreError as error:
            self._thread_state.last_error_detail = {
                "kind": getattr(error, "kind", "internal"),
                "category": getattr(error, "category", "unknown"),
                "phase": getattr(error, "phase", "unknown"),
                "code": getattr(error, "code", "CORE-BIND-UNKNOWN"),
                "function": getattr(error, "function", None),
                "block": getattr(error, "block", None),
                "source_location": getattr(error, "source_location", None),
            }
            return {
                "ok": False,
                "error": str(error),
                "diagnostic": dict(self.last_error_detail or {}),
            }
        if not isinstance(ssa, dict):
            raise RuntimeError("in-process core returned a non-object schema-v2 value")
        return {"ok": True, "ssa": ssa}

    def close(self) -> None:
        """Match the productive client lifecycle; PyO3 owns no subprocess."""
        return None


__all__ = ["InProcessRustSSALoweringClient"]
