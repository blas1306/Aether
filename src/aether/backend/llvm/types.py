from __future__ import annotations

from aether.ir.types import ArrayType, BoolType, DoubleType, IntType, IRType, StringType, VectorType, VoidType


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
    if isinstance(type_, StringType):
        return "ptr"
    if isinstance(type_, ArrayType):
        return "ptr"
    if isinstance(type_, VectorType):
        return "ptr"
    raise LLVMBackendError(f"LLVM backend does not support type {type_}")
