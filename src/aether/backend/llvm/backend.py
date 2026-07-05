from __future__ import annotations

from aether.ssa.model import SSAModule

from .printer import LLVMPrinter


class LLVMBackend:
    """Small facade for emitting textual LLVM IR from SSA modules."""

    def __init__(self, printer: LLVMPrinter | None = None) -> None:
        self._printer = printer or LLVMPrinter()

    def emit(self, module: SSAModule) -> str:
        return self._printer.print_module(module)
