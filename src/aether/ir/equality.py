from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aether.string_value import StringValue, aether_string_equal

from .types import (
    ArrayType,
    BoolType,
    DoubleType,
    EnumType,
    FloatType,
    IRType,
    IntType,
    ListType,
    MatrixType,
    StringType,
    StructType,
    VectorType,
)


@dataclass(frozen=True)
class IREqCapability:
    type: IRType

    def __str__(self) -> str:
        return f"Eq({self.type})"


def ir_eq_capability(
    type_: IRType,
    structs: Mapping[str, object],
    visiting: frozenset[str] = frozenset(),
) -> IREqCapability | None:
    if isinstance(type_, (IntType, FloatType, DoubleType, BoolType, StringType, EnumType)):
        return IREqCapability(type_)
    if isinstance(type_, (ArrayType, ListType, VectorType, MatrixType)):
        return (
            IREqCapability(type_)
            if ir_eq_capability(type_.element, structs, visiting) is not None
            else None
        )
    if isinstance(type_, StructType):
        definition = structs.get(type_.name)
        fields = getattr(definition, "fields", None)
        if fields is None:
            return None
        if type_.name in visiting:
            return IREqCapability(type_)
        nested = visiting | {type_.name}
        return (
            IREqCapability(type_)
            if all(ir_eq_capability(field_type, structs, nested) is not None for _, field_type in fields)
            else None
        )
    return None


def ir_values_equal(
    type_: IRType,
    left: Any,
    right: Any,
    structs: Mapping[str, object],
    visited_pairs: set[tuple[int, int, IRType]] | None = None,
) -> bool:
    if isinstance(type_, StringType):
        if isinstance(left, StringValue) or isinstance(right, StringValue):
            return aether_string_equal(left, right)
        return left == right
    if isinstance(type_, StructType):
        definition = structs.get(type_.name)
        fields = getattr(definition, "fields", None)
        if fields is None or len(left) != len(fields) or len(right) != len(fields):
            return False
        return all(
            ir_values_equal(field_type, a, b, structs, visited_pairs)
            for a, b, (_, field_type) in zip(left, right, fields)
        )
    if isinstance(type_, (ArrayType, ListType, VectorType, MatrixType)):
        if left is right:
            return True
        pairs = visited_pairs if visited_pairs is not None else set()
        pair = (id(left), id(right), type_)
        if pair in pairs:
            return True
        pairs.add(pair)
        try:
            if len(left) != len(right):
                return False
            return all(
                ir_values_equal(type_.element, a, b, structs, pairs)
                for a, b in zip(left, right)
            )
        finally:
            pairs.discard(pair)
    return left == right
