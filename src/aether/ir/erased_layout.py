from __future__ import annotations

from collections.abc import Mapping

from .model import IRStructDefinition
from .types import (
    ArrayType,
    BoolType,
    ClassRefType,
    DoubleType,
    EnumType,
    FloatType,
    FunctionType,
    IntType,
    InterfaceType,
    IRType,
    ListType,
    MatrixType,
    NullableType,
    StringType,
    StructType,
    VectorType,
)


class ErasedLayoutError(ValueError):
    pass


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def erased_size_alignment(
    type_: IRType,
    structs: Mapping[str, IRStructDefinition],
    active: tuple[str, ...] = (),
) -> tuple[int, int]:
    """Return the verifier's deterministic LP64 size/alignment contract."""

    if isinstance(type_, BoolType):
        return 1, 1
    if isinstance(type_, (IntType, FloatType, EnumType)):
        return 4, 4
    if isinstance(type_, DoubleType):
        return 8, 8
    if isinstance(
        type_,
        (
            StringType,
            ClassRefType,
            ArrayType,
            ListType,
            VectorType,
            MatrixType,
            FunctionType,
        ),
    ):
        return 8, 8
    if isinstance(type_, InterfaceType):
        return 16, 8
    if isinstance(type_, NullableType):
        inner_size, inner_alignment = erased_size_alignment(
            type_.inner, structs, active
        )
        payload_offset = align_up(1, inner_alignment)
        return (
            align_up(payload_offset + inner_size, inner_alignment),
            inner_alignment,
        )
    if isinstance(type_, StructType):
        if type_.name in active:
            cycle = " -> ".join((*active, type_.name))
            raise ErasedLayoutError(
                f"recursive by-value erased layout has infinite size ({cycle})"
            )
        definition = structs.get(type_.name)
        if definition is None:
            raise ErasedLayoutError(
                f"nominal struct '{type_.name}' has no complete definition"
            )
        offset = 0
        alignment = 1
        for _field_name, field_type in definition.fields:
            field_size, field_alignment = erased_size_alignment(
                field_type, structs, (*active, type_.name)
            )
            offset = align_up(offset, field_alignment)
            offset += field_size
            alignment = max(alignment, field_alignment)
        return align_up(offset, alignment), alignment
    raise ErasedLayoutError(f"type '{type_}' has no supported erased layout")
