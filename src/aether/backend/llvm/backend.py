from __future__ import annotations

from aether.ssa.model import SSAModule
from aether.ssa.verifier import SSAVerificationError, SSAVerifier

from .printer import LLVMPrinter
from .types import LLVMBackendError


class LLVMBackend:
    """Small facade for emitting textual LLVM IR from SSA modules."""

    def __init__(self, printer: LLVMPrinter | None = None) -> None:
        self._printer = printer or LLVMPrinter()

    def emit(self, module: SSAModule, *, native_entry: bool = False) -> str:
        try:
            SSAVerifier(module).verify()
        except SSAVerificationError as exc:
            raise LLVMBackendError(
                f"LLVM backend rejected malformed or unverified SSA: {exc}"
            ) from exc
        return self._printer.print_module(module, native_entry=native_entry)
