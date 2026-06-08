from __future__ import annotations

from dataclasses import dataclass

from .types import AetherType, ArrayType, ListType, MatrixType, TransposeVectorType, VectorType


@dataclass(frozen=True)
class NativeMember:
    name: str
    builtin_name: str
    kind: str


@dataclass(frozen=True)
class NativeMemberSet:
    properties: dict[str, NativeMember]
    methods: dict[str, NativeMember]


LIST_NATIVE_MEMBERS = NativeMemberSet(
    properties={
        "length": NativeMember("length", "length", "property"),
    },
    methods={
        "copy": NativeMember("copy", "copy", "method"),
        "reverse": NativeMember("reverse", "reverse", "method"),
        "sort": NativeMember("sort", "sort", "method"),
    },
)

ARRAY_NATIVE_MEMBERS = NativeMemberSet(
    properties={
        "length": NativeMember("length", "length", "property"),
    },
    methods={
        "copy": NativeMember("copy", "copy", "method"),
    },
)

VECTOR_NATIVE_MEMBERS = NativeMemberSet(
    properties={
        "length": NativeMember("length", "length", "property"),
    },
    methods={
        "norm": NativeMember("norm", "Math.LinearAlgebra.norm", "method"),
    },
)

MATRIX_NATIVE_MEMBERS = NativeMemberSet(
    properties={
        "rows": NativeMember("rows", "rows", "property"),
        "columns": NativeMember("columns", "columns", "property"),
    },
    methods={
        "transpose": NativeMember("transpose", "Math.LinearAlgebra.transpose", "method"),
    },
)


def native_member_set(type_name: AetherType) -> NativeMemberSet | None:
    if isinstance(type_name, ListType):
        return LIST_NATIVE_MEMBERS
    if isinstance(type_name, ArrayType):
        return ARRAY_NATIVE_MEMBERS
    if isinstance(type_name, (VectorType, TransposeVectorType)):
        return VECTOR_NATIVE_MEMBERS
    if isinstance(type_name, MatrixType):
        return VECTOR_NATIVE_MEMBERS if type_name.vector else MATRIX_NATIVE_MEMBERS
    return None


def native_property(type_name: AetherType, name: str) -> NativeMember | None:
    members = native_member_set(type_name)
    if members is None:
        return None
    return members.properties.get(name)


def native_method(type_name: AetherType, name: str) -> NativeMember | None:
    members = native_member_set(type_name)
    if members is None:
        return None
    return members.methods.get(name)


def is_native_property_name(type_name: AetherType, name: str) -> bool:
    return native_property(type_name, name) is not None


def is_native_method_name(type_name: AetherType, name: str) -> bool:
    return native_method(type_name, name) is not None
