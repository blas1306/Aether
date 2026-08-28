"""Experimental CORE-1.0 in-process adapter; never selected implicitly."""

from __future__ import annotations

import importlib
import json
from types import ModuleType
from typing import Mapping


class InProcessRustSSALoweringClient:
    """Adapt the PyO3 core session to the existing qualification client shape.

    Construction is explicit and import failure is fatal. There is deliberately
    no production discovery, companion fallback, or authority-policy hook here.
    """

    def __init__(self, extension: ModuleType | None = None) -> None:
        self._extension = (
            extension
            if extension is not None
            else importlib.import_module("_aether_core")
        )
        if self._extension.QUALIFICATION_ONLY is not True:
            raise RuntimeError("in-process compiler core is not qualification-only")
        self._core = self._extension.CompilerCore()
        self._requests = 0
        self.last_error_detail: dict[str, object] | None = None

    @property
    def process_start_count(self) -> int:
        return 0

    @property
    def request_count(self) -> int:
        return self._requests

    def lower(self, payload: bytes) -> Mapping[str, object]:
        """Run the current qualified SSA operation on a Rust-owned session."""
        self.last_error_detail = None
        self._requests += 1
        try:
            session = self._core.accept_initial_ir_schema_v1(payload)
            session.lower_ssa()
            raw_ssa = session.export_ssa_schema_v2()
            ssa = json.loads(raw_ssa)
        except self._extension.AetherCoreError as error:
            self.last_error_detail = {
                "kind": getattr(error, "kind", "internal"),
                "category": getattr(error, "category", "unknown"),
                "phase": getattr(error, "phase", "unknown"),
                "code": getattr(error, "code", "CORE-BIND-UNKNOWN"),
                "function": getattr(error, "function", None),
                "block": getattr(error, "block", None),
                "source_location": getattr(error, "source_location", None),
            }
            return {"ok": False, "error": str(error)}
        if not isinstance(ssa, dict):
            raise RuntimeError("in-process core returned a non-object schema-v2 value")
        return {"ok": True, "ssa": ssa}


__all__ = ["InProcessRustSSALoweringClient"]
