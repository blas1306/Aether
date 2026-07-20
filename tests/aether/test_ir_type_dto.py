from __future__ import annotations

import aether.ir as public_ir
import pytest

from aether.ir.dto import IR_SCHEMA_VERSION, IR_TYPE_TAGS, ir_type_to_dto
from aether.ir.types import (
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


def test_schema_version_starts_at_one() -> None:
    assert IR_SCHEMA_VERSION == 1


def test_every_public_ir_type_has_an_explicit_schema_mapping() -> None:
    public_type_classes = {
        value
        for name in public_ir.__all__
        if isinstance((value := getattr(public_ir, name)), type)
        and issubclass(value, IRType)
        and value is not IRType
    }

    assert set(IR_TYPE_TAGS) == public_type_classes


@pytest.mark.parametrize(
    ("type_", "expected"),
    [
        (IntType(), {"tag": "int"}),
        (FloatType(), {"tag": "float"}),
        (DoubleType(), {"tag": "double"}),
        (BoolType(), {"tag": "bool"}),
        (StringType(), {"tag": "string"}),
        (VoidType(), {"tag": "void"}),
        (ComplexType(), {"tag": "complex"}),
        (
            FunctionType((IntType(), BoolType()), StringType()),
            {
                "tag": "function",
                "parameter_types": [{"tag": "int"}, {"tag": "bool"}],
                "return_type": {"tag": "string"},
            },
        ),
        (NullableType(IntType()), {"tag": "nullable", "inner": {"tag": "int"}}),
        (ListType(StringType()), {"tag": "list", "element": {"tag": "string"}}),
        (ArrayType(BoolType()), {"tag": "array", "element": {"tag": "bool"}}),
        (
            VectorType(DoubleType(), orientation="row"),
            {"tag": "vector", "element": {"tag": "double"}, "orientation": "row"},
        ),
        (MatrixType(FloatType()), {"tag": "matrix", "element": {"tag": "float"}}),
        (StructType("Point"), {"tag": "struct", "name": "Point"}),
        (
            MethodResultType(StructType("Counter"), IntType()),
            {
                "tag": "method_result",
                "receiver": {"tag": "struct", "name": "Counter"},
                "value": {"tag": "int"},
            },
        ),
        (ClassRefType("File"), {"tag": "class_ref", "name": "File"}),
        (InterfaceType("Display"), {"tag": "interface", "name": "Display"}),
        (
            EnumType("Color", ("RED", "GREEN"), "ColorType"),
            {
                "tag": "enum",
                "name": "Color",
                "variants": ["RED", "GREEN"],
                "display_name": "ColorType",
            },
        ),
    ],
)
def test_ir_type_mapping(type_: IRType, expected: dict[str, object]) -> None:
    assert ir_type_to_dto(type_) == expected


def test_vector_without_orientation_preserves_absence() -> None:
    assert ir_type_to_dto(VectorType(IntType())) == {
        "tag": "vector",
        "element": {"tag": "int"},
        "orientation": None,
    }


def test_unknown_ir_type_is_rejected() -> None:
    class FutureType(IntType):
        pass

    with pytest.raises(TypeError, match=r"Unsupported IR type for schema v1: FutureType"):
        ir_type_to_dto(FutureType())
