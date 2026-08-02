from __future__ import annotations

from aether.ssa.model import SSAModule
from aether.ssa.verifier import SSAVerificationError, SSAVerifier

from .printer import LLVMPrinter
from .native_boundary import NativeBoundaryVerifier
from .types import LLVMBackendError


class LLVMBackend:
    """Small facade for emitting textual LLVM IR from SSA modules."""

    def __init__(self, printer: LLVMPrinter | None = None) -> None:
        self._printer = printer or LLVMPrinter()

    def emit(self, module: SSAModule, *, native_entry: bool = False) -> str:
        # Boundary declarations and private ABI facts must fail with their
        # specific diagnostics even when an internal test hook also constructs
        # SSA that the general verifier would call undefined.  The complete SSA
        # verifier still runs last, immediately before textual LLVM emission.
        NativeBoundaryVerifier(
            module,
            exception_runtime_abi_version=self._printer.exception_runtime_abi_version,
            exception_strategy=self._printer.exception_strategy,
        ).verify()
        try:
            SSAVerifier(module).verify()
        except SSAVerificationError as exc:
            raise LLVMBackendError(
                f"LLVM backend rejected malformed or unverified SSA: {exc}"
            ) from exc
        return self._printer.print_module(module, native_entry=native_entry)
