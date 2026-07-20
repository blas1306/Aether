from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TypeAlias

from .types import (
    ArrayType,
    BoolType,
    ClassRefType,
    ComplexType,
    DoubleType,
    EnumType,
    FloatType,
    FunctionType,
    InterfaceType,
    IntType,
    IRType,
    ListType,
    MatrixType,
    MethodResultType,
    NullableType,
    StringType,
    StructType,
    VectorType,
    VoidType,
)


IR_SCHEMA_VERSION = 1
"""Version of the Python-to-Rust IR interchange schema."""

IRTypeDTO: TypeAlias = dict[str, object]
"""Primitive, tagged representation of an :class:`IRType`."""


IR_TYPE_TAGS: Mapping[type[IRType], str] = MappingProxyType(
    {
        IntType: "int",
        FloatType: "float",
        DoubleType: "double",
        BoolType: "bool",
        StringType: "string",
        VoidType: "void",
        FunctionType: "function",
        ComplexType: "complex",
        NullableType: "nullable",
        ListType: "list",
        ArrayType: "array",
        VectorType: "vector",
        MatrixType: "matrix",
        StructType: "struct",
        MethodResultType: "method_result",
        ClassRefType: "class_ref",
        InterfaceType: "interface",
        EnumType: "enum",
    }
)
"""Exact Python IR type class to schema tag mapping."""


def ir_type_to_dto(type_: IRType) -> IRTypeDTO:
    """Convert one Python IR type to its tagged primitive DTO.

    The conversion deliberately uses exact classes.  A newly introduced IR
    type must receive an explicit schema representation instead of silently
    inheriting the representation of an existing type.
    """

    try:
        tag = IR_TYPE_TAGS[type(type_)]
    except KeyError:
        raise TypeError(f"Unsupported IR type for schema v{IR_SCHEMA_VERSION}: {type(type_).__name__}") from None

    dto: IRTypeDTO = {"tag": tag}
    if isinstance(type_, FunctionType):
        dto["parameter_types"] = [ir_type_to_dto(item) for item in type_.parameter_types]
        dto["return_type"] = ir_type_to_dto(type_.return_type)
    elif isinstance(type_, NullableType):
        dto["inner"] = ir_type_to_dto(type_.inner)
    elif isinstance(type_, (ListType, ArrayType, VectorType, MatrixType)):
        dto["element"] = ir_type_to_dto(type_.element)
        if isinstance(type_, VectorType):
            dto["orientation"] = type_.orientation
    elif isinstance(type_, (StructType, ClassRefType, InterfaceType)):
        dto["name"] = type_.name
    elif isinstance(type_, MethodResultType):
        dto["receiver"] = ir_type_to_dto(type_.receiver)
        dto["value"] = ir_type_to_dto(type_.value)
    elif isinstance(type_, EnumType):
        dto["name"] = type_.name
        dto["variants"] = list(type_.variants)
        dto["display_name"] = type_.display_name
    return dto


__all__ = ["IR_SCHEMA_VERSION", "IR_TYPE_TAGS", "IRTypeDTO", "ir_type_to_dto"]
