from __future__ import annotations

import hashlib
import re

from aether.ir.types import ArrayType, BoolType, DoubleType, EnumType, FloatType, FunctionType, IntType, IRType, ListType, MatrixType, MethodResultType, NullableType, StringType, StructType, VectorType, VoidType


class LLVMBackendError(Exception):
    """Raised when SSA cannot be emitted by the minimal LLVM backend."""


def nullable_type_name(type_: NullableType) -> str:
    """Return the deterministic LLVM name for the canonical nullable aggregate."""

    descriptor = str(type_.inner)
    readable = re.sub(r"[^A-Za-z0-9._-]+", "_", descriptor).strip("_") or "value"
    digest = hashlib.sha256(descriptor.encode("utf-8")).hexdigest()[:12]
    return f"%nullable.{readable[:40]}.{digest}"


def llvm_type(type_: IRType) -> str:
    if isinstance(type_, IntType):
        return "i32"
    if isinstance(type_, EnumType):
        return "i32"
    if isinstance(type_, DoubleType):
        return "double"
    if isinstance(type_, FloatType):
        return "float"
    if isinstance(type_, VoidType):
        return "void"
    if isinstance(type_, BoolType):
        return "i1"
    if isinstance(type_, StringType):
        return "ptr"
    if isinstance(type_, FunctionType):
        return "ptr"
    if isinstance(type_, ArrayType):
        return "ptr"
    if isinstance(type_, ListType):
        return "ptr"
    if isinstance(type_, VectorType):
        return "ptr"
    if isinstance(type_, MatrixType):
        return "ptr"
    if isinstance(type_, StructType):
        return f"%struct.{type_.name}"
    if isinstance(type_, NullableType):
        return nullable_type_name(type_)
    if isinstance(type_, MethodResultType):
        receiver = llvm_type(type_.receiver)
        if isinstance(type_.value, VoidType):
            return f"{{ {receiver} }}"
        return f"{{ {receiver}, {llvm_type(type_.value)} }}"
    raise LLVMBackendError(f"LLVM backend does not support type {type_}")
