from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .errors import AetherTypeError
from .string_value import aether_string_equal
from .types import (
    AetherType,
    AetherValue,
    ArrayType,
    ClassInstance,
    ClassType,
    EnumType,
    EnumValue,
    FunctionType,
    InterfaceType,
    ListType,
    MatrixType,
    NullType,
    NullableType,
    NullableValue,
    RangeType,
    StructInstance,
    TransposeVectorType,
    TupleType,
    VectorType,
    type_to_string,
)


AliasResolver = Callable[[AetherType], AetherType]
StructResolver = Callable[[str], tuple[str, tuple[AetherType, ...]] | None]


@dataclass(frozen=True)
class EqCapability:
    """Canonical internal witness that ``type_name`` has Aether equality."""

    type_name: AetherType

    def __str__(self) -> str:
        return f"Eq({type_to_string(self.type_name)})"


def eq_capability(
    type_name: AetherType,
    *,
    resolve_alias: AliasResolver | None = None,
    resolve_struct: StructResolver | None = None,
    _visiting: frozenset[str] = frozenset(),
) -> EqCapability | None:
    """Return the single semantic equality witness for an Aether type.

    Struct declarations are supplied by the semantic owner (normally the
    typechecker).  No unknown nominal type is treated as comparable.
    """

    resolved = resolve_alias(type_name) if resolve_alias is not None else type_name
    if isinstance(resolved, (ClassType, InterfaceType, FunctionType, RangeType)):
        return None
    if isinstance(resolved, NullType):
        return EqCapability(resolved)
    if isinstance(resolved, EnumType):
        return EqCapability(resolved)
    if isinstance(resolved, str):
        if resolved in {"int", "float", "double", "complex", "string", "boolean"}:
            return EqCapability(resolved)
        if resolved == "void" or resolve_struct is None:
            return None
        struct = resolve_struct(resolved)
        if struct is None:
            return None
        kind, fields = struct
        if kind != "struct":
            return None
        if resolved in _visiting:
            # Direct recursive value structs cannot be constructed today, but
            # accepting the back-edge makes the capability query total.
            return EqCapability(resolved)
        visiting = _visiting | {resolved}
        if all(
            eq_capability(
                field,
                resolve_alias=resolve_alias,
                resolve_struct=resolve_struct,
                _visiting=visiting,
            )
            is not None
            for field in fields
        ):
            return EqCapability(resolved)
        return None
    if isinstance(resolved, NullableType):
        inner = eq_capability(
            resolved.base_type,
            resolve_alias=resolve_alias,
            resolve_struct=resolve_struct,
            _visiting=_visiting,
        )
        return EqCapability(resolved) if inner is not None else None
    if isinstance(resolved, (ArrayType, ListType)):
        inner = eq_capability(
            resolved.element_type,
            resolve_alias=resolve_alias,
            resolve_struct=resolve_struct,
            _visiting=_visiting,
        )
        return EqCapability(resolved) if inner is not None else None
    if isinstance(resolved, (MatrixType, VectorType, TransposeVectorType)):
        inner = eq_capability(
            resolved.element_type,
            resolve_alias=resolve_alias,
            resolve_struct=resolve_struct,
            _visiting=_visiting,
        )
        return EqCapability(resolved) if inner is not None else None
    if isinstance(resolved, TupleType):
        if all(
            eq_capability(
                element,
                resolve_alias=resolve_alias,
                resolve_struct=resolve_struct,
                _visiting=_visiting,
            )
            is not None
            for element in resolved.element_types
        ):
            return EqCapability(resolved)
    return None


def types_support_equality(
    left_type: AetherType,
    right_type: AetherType,
    *,
    resolve_alias: AliasResolver | None = None,
    resolve_struct: StructResolver | None = None,
) -> bool:
    left = resolve_alias(left_type) if resolve_alias is not None else left_type
    right = resolve_alias(right_type) if resolve_alias is not None else right_type
    if isinstance(left, NullType):
        return isinstance(right, NullType) or (
            isinstance(right, NullableType)
            and eq_capability(right.base_type, resolve_alias=resolve_alias, resolve_struct=resolve_struct) is not None
        )
    if isinstance(right, NullType):
        return isinstance(left, NullableType) and (
            eq_capability(left.base_type, resolve_alias=resolve_alias, resolve_struct=resolve_struct) is not None
        )
    if isinstance(left, NullableType):
        left = left.base_type
    if isinstance(right, NullableType):
        right = right.base_type
    if left == right:
        return eq_capability(left, resolve_alias=resolve_alias, resolve_struct=resolve_struct) is not None
    # Preserve the existing numeric promotion rule.  IEEE equality remains
    # exact after the normal numeric conversion.
    return isinstance(left, str) and isinstance(right, str) and left in {
        "int", "float", "double", "complex"
    } and right in {"int", "float", "double", "complex"}


def require_eq(
    type_name: AetherType,
    *,
    resolve_alias: AliasResolver | None = None,
    resolve_struct: StructResolver | None = None,
) -> EqCapability:
    capability = eq_capability(
        type_name,
        resolve_alias=resolve_alias,
        resolve_struct=resolve_struct,
    )
    if capability is None:
        raise AetherTypeError(f"Type {type_to_string(type_name)} does not define equality.")
    return capability


def aether_values_equal(
    left: AetherValue,
    right: AetherValue,
    *,
    _visited_pairs: set[tuple[int, int]] | None = None,
) -> bool:
    """Compare runtime values using Aether's typed equality, never Python identity.

    ``_visited_pairs`` is defensive for future recursive collection APIs.  The
    current finite nominal type grammar cannot construct a collection cycle.
    """

    if _runtime_type_has_no_eq(left.type_name) or _runtime_type_has_no_eq(right.type_name):
        raise AetherTypeError(
            f"Type {type_to_string(left.type_name)} does not define equality."
        )
    if isinstance(left.value, ClassInstance) or isinstance(right.value, ClassInstance):
        raise AetherTypeError("Class values do not define equality.")
    if isinstance(left.type_name, (ClassType, InterfaceType, FunctionType)) or isinstance(
        right.type_name, (ClassType, InterfaceType, FunctionType)
    ):
        raise AetherTypeError(
            f"Type {type_to_string(left.type_name)} does not define equality."
        )
    if isinstance(left.type_name, NullableType):
        nullable = left.value
        if not isinstance(nullable, NullableValue):
            raise AetherTypeError("Invalid internal nullable value.")
        if not nullable.has_value:
            return (
                isinstance(right.value, NullableValue)
                and not right.value.has_value
            ) or isinstance(right.type_name, NullType)
        left = AetherValue(left.type_name.base_type, nullable.value)
    if isinstance(right.type_name, NullableType):
        nullable = right.value
        if not isinstance(nullable, NullableValue):
            raise AetherTypeError("Invalid internal nullable value.")
        if not nullable.has_value:
            return isinstance(left.type_name, NullType)
        right = AetherValue(right.type_name.base_type, nullable.value)
    if isinstance(left.value, StructInstance) or isinstance(right.value, StructInstance):
        if not isinstance(left.value, StructInstance) or not isinstance(right.value, StructInstance):
            return False
        if left.value.type_name != right.value.type_name:
            return False
        return all(
            aether_values_equal(
                left.value.fields[name],
                right.value.fields[name],
                _visited_pairs=_visited_pairs,
            )
            for name in left.value.field_order
        )
    if isinstance(left.value, EnumValue) or isinstance(right.value, EnumValue):
        if not isinstance(left.value, EnumValue) or not isinstance(right.value, EnumValue):
            return False
        if left.type_name != right.type_name:
            return False
        if left.value.enum_id is not None or right.value.enum_id is not None:
            return (
                left.value.enum_id is not None
                and left.value.enum_id == right.value.enum_id
                and left.value.discriminant == right.value.discriminant
            )
        return (
            left.value.enum_name == right.value.enum_name
            and left.value.discriminant == right.value.discriminant
        )
    if left.type_name == "string" and right.type_name == "string":
        return aether_string_equal(left.value, right.value)
    if isinstance(left.type_name, (ArrayType, ListType)) and isinstance(
        right.type_name, (ArrayType, ListType)
    ):
        if type(left.type_name) is not type(right.type_name):
            return False
        return _sequences_equal(left.value, right.value, _visited_pairs)
    if isinstance(left.type_name, VectorType) and isinstance(right.type_name, VectorType):
        return _sequences_equal(left.value, right.value, _visited_pairs)
    if isinstance(left.type_name, TransposeVectorType) and isinstance(right.type_name, TransposeVectorType):
        return aether_values_equal(left.value, right.value, _visited_pairs=_visited_pairs)
    if isinstance(left.type_name, MatrixType) and isinstance(right.type_name, MatrixType):
        return _sequences_equal(left.value, right.value, _visited_pairs)
    if isinstance(left.type_name, TupleType) and isinstance(right.type_name, TupleType):
        return _sequences_equal(left.value, right.value, _visited_pairs)
    # Python float equality is IEEE-754: NaN differs from itself and signed
    # zeroes compare equal.  No tolerance or approximate comparison is used.
    return left.value == right.value


def _sequences_equal(
    left: Iterable[AetherValue],
    right: Iterable[AetherValue],
    visited_pairs: set[tuple[int, int]] | None,
) -> bool:
    if left is right:
        return True
    pairs = visited_pairs if visited_pairs is not None else set()
    pair = (id(left), id(right))
    if pair in pairs:
        return True
    pairs.add(pair)
    try:
        left_values = left if hasattr(left, "__len__") else tuple(left)
        right_values = right if hasattr(right, "__len__") else tuple(right)
        if len(left_values) != len(right_values):  # type: ignore[arg-type]
            return False
        return all(
            aether_values_equal(a, b, _visited_pairs=pairs)
            for a, b in zip(left_values, right_values)
        )
    finally:
        pairs.discard(pair)


def _runtime_type_has_no_eq(type_name: AetherType) -> bool:
    if isinstance(type_name, (ClassType, InterfaceType, FunctionType, RangeType)):
        return True
    if isinstance(type_name, NullableType):
        return _runtime_type_has_no_eq(type_name.base_type)
    if isinstance(type_name, (ArrayType, ListType)):
        return _runtime_type_has_no_eq(type_name.element_type)
    if isinstance(type_name, (MatrixType, VectorType, TransposeVectorType)):
        return _runtime_type_has_no_eq(type_name.element_type)
    if isinstance(type_name, TupleType):
        return any(_runtime_type_has_no_eq(item) for item in type_name.element_types)
    return type_name == "void"
