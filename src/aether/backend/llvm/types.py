from __future__ import annotations

from aether.ir.types import BoolType, DoubleType, IntType, IRType, VoidType


class LLVMBackendError(Exception):
    """Raised when SSA cannot be emitted by the minimal LLVM backend."""


def llvm_type(type_: IRType) -> str:
    if isinstance(type_, IntType):
        return "i32"
    if isinstance(type_, DoubleType):
        return "double"
    if isinstance(type_, VoidType):
        return "void"
    if isinstance(type_, BoolType):
        return "i1"
    raise LLVMBackendError(f"LLVM backend does not support type {type_}")
