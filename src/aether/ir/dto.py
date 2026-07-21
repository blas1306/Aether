from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import NoReturn, TypeAlias

from .model import (
    IRAssign,
    IRArrayCopy,
    IRArrayGet,
    IRArrayLength,
    IRArrayNew,
    IRArraySet,
    IRArraySlice,
    IRBinaryOp,
    IRCall,
    IRCallIndirect,
    IRCast,
    IRCompareOp,
    IRConst,
    IRCopyInit,
    IRDestroy,
    IREnumConstant,
    IRFunctionRef,
    IRInitDefault,
    IRInstruction,
    IRLoad,
    IRListClear,
    IRListContains,
    IRListCopy,
    IRListGet,
    IRListIndexOf,
    IRListInsert,
    IRListIsEmpty,
    IRListLength,
    IRListNew,
    IRListPop,
    IRListPush,
    IRListRemoveAt,
    IRListReverse,
    IRListSet,
    IRListSlice,
    IRMatrixAdd,
    IRMatrixColumns,
    IRMatrixGet,
    IRMatrixMatMul,
    IRMatrixNew,
    IRMatrixRows,
    IRMatrixScale,
    IRMatrixSet,
    IRMatrixSub,
    IRMatrixVectorMul,
    IRMethodResultNew,
    IRMethodResultReceiver,
    IRMethodResultValue,
    IRMoveInit,
    IROuterProduct,
    IRParameter,
    IRPrint,
    IRRelocate,
    IRSequenceSort,
    IRSourceLocation,
    IRStorage,
    IRStore,
    IRStructGet,
    IRStructNew,
    IRStructSet,
    IRUnaryOp,
    IRValue,
    IRVectorAdd,
    IRVectorDot,
    IRVectorGet,
    IRVectorLength,
    IRVectorMatrixMul,
    IRVectorNew,
    IRVectorScale,
    IRVectorSet,
    IRVectorSub,
)
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

IRConstant: TypeAlias = bool | int | float | complex | str | IREnumConstant
"""Python values represented by Rust's ``IRConstant`` enum."""

IRConstantDTO: TypeAlias = dict[str, object]
IREnumConstantDTO: TypeAlias = dict[str, object]
IRValueDTO: TypeAlias = dict[str, object]
IRStorageDTO: TypeAlias = dict[str, object]
IRParameterDTO: TypeAlias = dict[str, object]
IRSourceLocationDTO: TypeAlias = dict[str, object]
IRInstructionDTO: TypeAlias = dict[str, object]
"""Primitive ``kind``-tagged representation of a supported instruction."""


class IRDTOError(ValueError):
    """Raised when primitive data does not conform to the IR DTO schema."""


class IRDTOSchemaVersionError(IRDTOError):
    """Raised when an IR DTO conversion requests an unsupported schema."""


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

IR_INSTRUCTION_TAGS: Mapping[type[IRInstruction], str] = MappingProxyType(
    {
        IRConst: "const",
        IRLoad: "load",
        IRStore: "store",
        IRInitDefault: "init_default",
        IRCopyInit: "copy_init",
        IRMoveInit: "move_init",
        IRAssign: "assign",
        IRDestroy: "destroy",
        IRRelocate: "relocate",
        IRBinaryOp: "binary_op",
        IRUnaryOp: "unary_op",
        IRCompareOp: "compare_op",
        IRCast: "cast",
        IRCall: "call",
        IRFunctionRef: "function_ref",
        IRCallIndirect: "call_indirect",
        IRPrint: "print",
        IRStructNew: "struct_new",
        IRStructGet: "struct_get",
        IRStructSet: "struct_set",
        IRMethodResultNew: "method_result_new",
        IRMethodResultReceiver: "method_result_receiver",
        IRMethodResultValue: "method_result_value",
        IRArrayNew: "array_new",
        IRListNew: "list_new",
        IRArrayCopy: "array_copy",
        IRListCopy: "list_copy",
        IRListContains: "list_contains",
        IRListIndexOf: "list_index_of",
        IRListClear: "list_clear",
        IRListPush: "list_push",
        IRListInsert: "list_insert",
        IRListRemoveAt: "list_remove_at",
        IRListPop: "list_pop",
        IRListReverse: "list_reverse",
        IRSequenceSort: "sequence_sort",
        IRArrayGet: "array_get",
        IRArraySlice: "array_slice",
        IRListSlice: "list_slice",
        IRListGet: "list_get",
        IRArraySet: "array_set",
        IRListSet: "list_set",
        IRArrayLength: "array_length",
        IRListLength: "list_length",
        IRListIsEmpty: "list_is_empty",
        IRVectorNew: "vector_new",
        IRMatrixNew: "matrix_new",
        IRVectorAdd: "vector_add",
        IRVectorSub: "vector_sub",
        IRVectorScale: "vector_scale",
        IRVectorDot: "vector_dot",
        IROuterProduct: "outer_product",
        IRMatrixAdd: "matrix_add",
        IRMatrixSub: "matrix_sub",
        IRMatrixScale: "matrix_scale",
        IRMatrixMatMul: "matrix_mat_mul",
        IRMatrixVectorMul: "matrix_vector_mul",
        IRVectorMatrixMul: "vector_matrix_mul",
        IRVectorGet: "vector_get",
        IRMatrixGet: "matrix_get",
        IRVectorLength: "vector_length",
        IRMatrixRows: "matrix_rows",
        IRMatrixColumns: "matrix_columns",
        IRVectorSet: "vector_set",
        IRMatrixSet: "matrix_set",
    }
)
"""Exact supported instruction class to stable schema tag mapping."""


def ir_type_to_dto(
    type_: IRType,
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRTypeDTO:
    """Convert one Python IR type to its tagged primitive DTO.

    The conversion deliberately uses exact classes.  A newly introduced IR
    type must receive an explicit schema representation instead of silently
    inheriting the representation of an existing type.
    """

    _require_schema_version(schema_version)
    try:
        tag = IR_TYPE_TAGS[type(type_)]
    except KeyError:
        raise TypeError(f"Unsupported IR type for schema v{IR_SCHEMA_VERSION}: {type(type_).__name__}") from None

    dto: IRTypeDTO = {"tag": tag}
    if isinstance(type_, FunctionType):
        dto["parameter_types"] = [
            ir_type_to_dto(item, schema_version=schema_version) for item in type_.parameter_types
        ]
        dto["return_type"] = ir_type_to_dto(type_.return_type, schema_version=schema_version)
    elif isinstance(type_, NullableType):
        dto["inner"] = ir_type_to_dto(type_.inner, schema_version=schema_version)
    elif isinstance(type_, (ListType, ArrayType, VectorType, MatrixType)):
        dto["element"] = ir_type_to_dto(type_.element, schema_version=schema_version)
        if isinstance(type_, VectorType):
            dto["orientation"] = _expect_optional_string(type_.orientation, "IR vector type orientation")
    elif isinstance(type_, (StructType, ClassRefType, InterfaceType)):
        dto["name"] = _expect_string(type_.name, f"IR {tag} type name")
    elif isinstance(type_, MethodResultType):
        dto["receiver"] = ir_type_to_dto(type_.receiver, schema_version=schema_version)
        dto["value"] = ir_type_to_dto(type_.value, schema_version=schema_version)
    elif isinstance(type_, EnumType):
        dto["name"] = _expect_string(type_.name, "IR enum type name")
        dto["variants"] = [
            _expect_string(item, f"IR enum type variants[{index}]")
            for index, item in enumerate(type_.variants)
        ]
        dto["display_name"] = _expect_optional_string(type_.display_name, "IR enum type display_name")
    return dto


def ir_type_from_dto(
    dto: Mapping[str, object],
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRType:
    """Decode one strictly validated schema-v1 IR type DTO."""

    _require_schema_version(schema_version)
    mapping = _expect_mapping(dto, "IR type")
    tag = _expect_tag(mapping, "IR type")

    scalar_types: Mapping[str, type[IRType]] = {
        "int": IntType,
        "float": FloatType,
        "double": DoubleType,
        "bool": BoolType,
        "string": StringType,
        "void": VoidType,
        "complex": ComplexType,
    }
    if tag in scalar_types:
        _expect_fields(mapping, {"tag"}, f"IR type '{tag}'")
        return scalar_types[tag]()
    if tag == "function":
        _expect_fields(mapping, {"tag", "parameter_types", "return_type"}, "IR type 'function'")
        parameters = _expect_sequence(mapping["parameter_types"], "IR type 'function'.parameter_types")
        return FunctionType(
            tuple(ir_type_from_dto(item, schema_version=schema_version) for item in parameters),
            ir_type_from_dto(mapping["return_type"], schema_version=schema_version),
        )
    if tag == "nullable":
        _expect_fields(mapping, {"tag", "inner"}, "IR type 'nullable'")
        return NullableType(ir_type_from_dto(mapping["inner"], schema_version=schema_version))
    if tag in {"list", "array", "matrix"}:
        _expect_fields(mapping, {"tag", "element"}, f"IR type '{tag}'")
        element = ir_type_from_dto(mapping["element"], schema_version=schema_version)
        collection_types: Mapping[str, type[ListType] | type[ArrayType] | type[MatrixType]] = {
            "list": ListType,
            "array": ArrayType,
            "matrix": MatrixType,
        }
        return collection_types[tag](element)
    if tag == "vector":
        _expect_fields(mapping, {"tag", "element", "orientation"}, "IR type 'vector'")
        orientation = _expect_optional_string(mapping["orientation"], "IR type 'vector'.orientation")
        return VectorType(
            ir_type_from_dto(mapping["element"], schema_version=schema_version),
            orientation,
        )
    if tag in {"struct", "class_ref", "interface"}:
        _expect_fields(mapping, {"tag", "name"}, f"IR type '{tag}'")
        name = _expect_string(mapping["name"], f"IR type '{tag}'.name")
        nominal_types: Mapping[str, type[StructType] | type[ClassRefType] | type[InterfaceType]] = {
            "struct": StructType,
            "class_ref": ClassRefType,
            "interface": InterfaceType,
        }
        return nominal_types[tag](name)
    if tag == "method_result":
        _expect_fields(mapping, {"tag", "receiver", "value"}, "IR type 'method_result'")
        receiver = ir_type_from_dto(mapping["receiver"], schema_version=schema_version)
        if not isinstance(receiver, StructType):
            raise IRDTOError("IR type 'method_result'.receiver must decode to a struct type")
        return MethodResultType(
            receiver,
            ir_type_from_dto(mapping["value"], schema_version=schema_version),
        )
    if tag == "enum":
        _expect_fields(mapping, {"tag", "name", "variants", "display_name"}, "IR type 'enum'")
        variants = _expect_sequence(mapping["variants"], "IR type 'enum'.variants")
        return EnumType(
            _expect_string(mapping["name"], "IR type 'enum'.name"),
            tuple(_expect_string(item, f"IR type 'enum'.variants[{index}]") for index, item in enumerate(variants)),
            _expect_optional_string(mapping["display_name"], "IR type 'enum'.display_name"),
        )
    _unknown_tag("IR type", tag)


def ir_enum_constant_to_dto(
    value: IREnumConstant,
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IREnumConstantDTO:
    """Convert nominal enum metadata to a tagged primitive DTO."""

    _require_schema_version(schema_version)
    if type(value) is not IREnumConstant:
        raise TypeError(f"Unsupported IR enum constant for schema v{IR_SCHEMA_VERSION}: {type(value).__name__}")
    _require_i32(value.member_id, "IR enum constant member_id")
    _require_i32(value.discriminant, "IR enum constant discriminant")
    return {
        "tag": "enum_constant",
        "enum_name": _expect_string(value.enum_name, "IR enum constant enum_name"),
        "member_name": _expect_string(value.member_name, "IR enum constant member_name"),
        "member_id": value.member_id,
        "discriminant": value.discriminant,
    }


def ir_enum_constant_from_dto(
    dto: Mapping[str, object],
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IREnumConstant:
    """Decode nominal enum metadata from a strictly validated DTO."""

    _require_schema_version(schema_version)
    mapping = _expect_mapping(dto, "IR enum constant")
    tag = _expect_tag(mapping, "IR enum constant")
    if tag != "enum_constant":
        _unknown_tag("IR enum constant", tag)
    _expect_fields(
        mapping,
        {"tag", "enum_name", "member_name", "member_id", "discriminant"},
        "IR enum constant",
    )
    return IREnumConstant(
        _expect_string(mapping["enum_name"], "IR enum constant.enum_name"),
        _expect_string(mapping["member_name"], "IR enum constant.member_name"),
        _expect_i32(mapping["member_id"], "IR enum constant.member_id"),
        _expect_i32(mapping["discriminant"], "IR enum constant.discriminant"),
    )


def ir_constant_to_dto(
    value: IRConstant,
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRConstantDTO:
    """Convert a Python IR constant into the Rust-compatible tagged DTO."""

    _require_schema_version(schema_version)
    if type(value) is bool:
        return {"tag": "bool", "value": value}
    if type(value) is int:
        _require_i32(value, "IR constant int value")
        return {"tag": "int", "value": value}
    if type(value) is float:
        return {"tag": "float", "value": value}
    if type(value) is complex:
        return {"tag": "complex", "real": value.real, "imaginary": value.imag}
    if type(value) is str:
        return {"tag": "string", "value": value}
    if type(value) is IREnumConstant:
        return {
            "tag": "enum",
            "value": ir_enum_constant_to_dto(value, schema_version=schema_version),
        }
    raise TypeError(f"Unsupported IR constant for schema v{IR_SCHEMA_VERSION}: {type(value).__name__}")


def ir_constant_from_dto(
    dto: Mapping[str, object],
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRConstant:
    """Decode a Rust-compatible constant DTO to its existing Python value."""

    _require_schema_version(schema_version)
    mapping = _expect_mapping(dto, "IR constant")
    tag = _expect_tag(mapping, "IR constant")
    if tag == "bool":
        _expect_fields(mapping, {"tag", "value"}, "IR constant 'bool'")
        return _expect_bool(mapping["value"], "IR constant 'bool'.value")
    if tag == "int":
        _expect_fields(mapping, {"tag", "value"}, "IR constant 'int'")
        return _expect_i32(mapping["value"], "IR constant 'int'.value")
    if tag == "float":
        _expect_fields(mapping, {"tag", "value"}, "IR constant 'float'")
        return _expect_float(mapping["value"], "IR constant 'float'.value")
    if tag == "complex":
        _expect_fields(mapping, {"tag", "real", "imaginary"}, "IR constant 'complex'")
        return complex(
            _expect_float(mapping["real"], "IR constant 'complex'.real"),
            _expect_float(mapping["imaginary"], "IR constant 'complex'.imaginary"),
        )
    if tag == "string":
        _expect_fields(mapping, {"tag", "value"}, "IR constant 'string'")
        return _expect_string(mapping["value"], "IR constant 'string'.value")
    if tag == "enum":
        _expect_fields(mapping, {"tag", "value"}, "IR constant 'enum'")
        return ir_enum_constant_from_dto(mapping["value"], schema_version=schema_version)
    _unknown_tag("IR constant", tag)


_VALUE_TAGS: Mapping[type[IRValue], str] = MappingProxyType(
    {IRValue: "value", IRStorage: "storage", IRParameter: "parameter"}
)


def ir_value_to_dto(
    value: IRValue,
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRValueDTO:
    """Convert a named value while preserving its exact semantic kind."""

    _require_schema_version(schema_version)
    try:
        tag = _VALUE_TAGS[type(value)]
    except KeyError:
        raise TypeError(f"Unsupported IR value for schema v{IR_SCHEMA_VERSION}: {type(value).__name__}") from None
    return {
        "tag": tag,
        "name": _expect_string(value.name, f"IR value '{tag}' name"),
        "type": ir_type_to_dto(value.type, schema_version=schema_version),
    }


def ir_value_from_dto(
    dto: Mapping[str, object],
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRValue:
    """Decode an IR value, storage location, or parameter by stable tag."""

    _require_schema_version(schema_version)
    return _value_from_dto(dto, expected_tag=None, schema_version=schema_version)


def ir_storage_to_dto(
    storage: IRStorage,
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRStorageDTO:
    """Convert one addressable owning storage location to a DTO."""

    _require_exact_value_kind(storage, IRStorage, "storage")
    return ir_value_to_dto(storage, schema_version=schema_version)


def ir_storage_from_dto(
    dto: Mapping[str, object],
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRStorage:
    """Decode one addressable owning storage location DTO."""

    _require_schema_version(schema_version)
    value = _value_from_dto(dto, expected_tag="storage", schema_version=schema_version)
    assert isinstance(value, IRStorage)
    return value


def ir_parameter_to_dto(
    parameter: IRParameter,
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRParameterDTO:
    """Convert one declared function parameter to a DTO."""

    _require_exact_value_kind(parameter, IRParameter, "parameter")
    return ir_value_to_dto(parameter, schema_version=schema_version)


def ir_parameter_from_dto(
    dto: Mapping[str, object],
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRParameter:
    """Decode one declared function parameter DTO."""

    _require_schema_version(schema_version)
    value = _value_from_dto(dto, expected_tag="parameter", schema_version=schema_version)
    assert isinstance(value, IRParameter)
    return value


def ir_source_location_to_dto(
    location: IRSourceLocation | None,
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRSourceLocationDTO | None:
    """Convert a location, preserving an absent location as explicit null."""

    _require_schema_version(schema_version)
    if location is None:
        return None
    if type(location) is not IRSourceLocation:
        raise TypeError(f"Unsupported IR source location for schema v{IR_SCHEMA_VERSION}: {type(location).__name__}")
    _require_i64(location.line, "IR source location line")
    _require_i64(location.column, "IR source location column")
    return {
        "tag": "source_location",
        "line": location.line,
        "column": location.column,
        "path": _expect_optional_string(location.path, "IR source location path"),
    }


def ir_source_location_from_dto(
    dto: Mapping[str, object] | None,
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRSourceLocation | None:
    """Decode a location, preserving explicit null as absence."""

    _require_schema_version(schema_version)
    if dto is None:
        return None
    mapping = _expect_mapping(dto, "IR source location")
    tag = _expect_tag(mapping, "IR source location")
    if tag != "source_location":
        _unknown_tag("IR source location", tag)
    _expect_fields(mapping, {"tag", "line", "column", "path"}, "IR source location")
    return IRSourceLocation(
        _expect_i64(mapping["line"], "IR source location.line"),
        _expect_i64(mapping["column"], "IR source location.column"),
        _expect_optional_string(mapping["path"], "IR source location.path"),
    )


def ir_instruction_to_dto(
    instruction: IRInstruction,
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRInstructionDTO:
    """Convert one supported instruction to a primitive DTO."""

    _require_schema_version(schema_version)
    try:
        kind = IR_INSTRUCTION_TAGS[type(instruction)]
    except KeyError:
        raise TypeError(
            f"Unsupported IR instruction for schema v{IR_SCHEMA_VERSION}: "
            f"{type(instruction).__name__}"
        ) from None

    if type(instruction) is IRConst:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "value": ir_constant_to_dto(instruction.value, schema_version=schema_version),
        }
    if type(instruction) is IRLoad:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "slot": ir_value_to_dto(instruction.slot, schema_version=schema_version),
        }
    if type(instruction) is IRStore:
        return {
            "kind": kind,
            "slot": ir_value_to_dto(instruction.slot, schema_version=schema_version),
            "value": ir_value_to_dto(instruction.value, schema_version=schema_version),
        }
    if type(instruction) is IRInitDefault:
        return {
            "kind": kind,
            "destination": ir_storage_to_dto(
                instruction.destination,
                schema_version=schema_version,
            ),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRCopyInit:
        return {
            "kind": kind,
            "destination": ir_storage_to_dto(
                instruction.destination,
                schema_version=schema_version,
            ),
            "source": ir_value_to_dto(instruction.source, schema_version=schema_version),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRMoveInit:
        return {
            "kind": kind,
            "destination": ir_storage_to_dto(
                instruction.destination,
                schema_version=schema_version,
            ),
            "source": ir_storage_to_dto(instruction.source, schema_version=schema_version),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRAssign:
        return {
            "kind": kind,
            "destination": ir_storage_to_dto(
                instruction.destination,
                schema_version=schema_version,
            ),
            "source": ir_value_to_dto(instruction.source, schema_version=schema_version),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRDestroy:
        return {
            "kind": kind,
            "value": ir_storage_to_dto(instruction.value, schema_version=schema_version),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRRelocate:
        return {
            "kind": kind,
            "destination": ir_storage_to_dto(
                instruction.destination,
                schema_version=schema_version,
            ),
            "source": ir_storage_to_dto(instruction.source, schema_version=schema_version),
            "count": _expect_i64(instruction.count, "IR instruction 'relocate'.count"),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRBinaryOp:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "operator": _expect_string(
                instruction.operator,
                "IR instruction 'binary_op'.operator",
            ),
            "left": ir_value_to_dto(instruction.left, schema_version=schema_version),
            "right": ir_value_to_dto(instruction.right, schema_version=schema_version),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRUnaryOp:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "operator": _expect_string(
                instruction.operator,
                "IR instruction 'unary_op'.operator",
            ),
            "operand": ir_value_to_dto(instruction.operand, schema_version=schema_version),
        }
    if type(instruction) is IRCompareOp:
        aggregate_shape = instruction.aggregate_shape
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "operator": _expect_string(
                instruction.operator,
                "IR instruction 'compare_op'.operator",
            ),
            "left": ir_value_to_dto(instruction.left, schema_version=schema_version),
            "right": ir_value_to_dto(instruction.right, schema_version=schema_version),
            "aggregate_shape": (
                None
                if aggregate_shape is None
                else [
                    _expect_i64(size, f"IR instruction 'compare_op'.aggregate_shape[{index}]")
                    for index, size in enumerate(aggregate_shape)
                ]
            ),
        }
    if type(instruction) is IRCast:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "value": ir_value_to_dto(instruction.value, schema_version=schema_version),
        }
    if type(instruction) is IRCall:
        return {
            "kind": kind,
            "function": _expect_string(
                instruction.function,
                "IR instruction 'call'.function",
            ),
            "arguments": [
                ir_value_to_dto(argument, schema_version=schema_version)
                for argument in instruction.arguments
            ],
            "result": (
                None
                if instruction.result is None
                else ir_value_to_dto(instruction.result, schema_version=schema_version)
            ),
            "builtin": _expect_optional_string(
                instruction.builtin,
                "IR instruction 'call'.builtin",
            ),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRFunctionRef:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "function": _expect_string(
                instruction.function,
                "IR instruction 'function_ref'.function",
            ),
        }
    if type(instruction) is IRCallIndirect:
        return {
            "kind": kind,
            "callee": ir_value_to_dto(instruction.callee, schema_version=schema_version),
            "arguments": [
                ir_value_to_dto(argument, schema_version=schema_version)
                for argument in instruction.arguments
            ],
            "result": (
                None
                if instruction.result is None
                else ir_value_to_dto(instruction.result, schema_version=schema_version)
            ),
        }
    if type(instruction) is IRPrint:
        aggregate_shape = instruction.aggregate_shape
        return {
            "kind": kind,
            "value": ir_value_to_dto(instruction.value, schema_version=schema_version),
            "newline": _expect_bool(
                instruction.newline,
                "IR instruction 'print'.newline",
            ),
            "aggregate_shape": (
                None
                if aggregate_shape is None
                else [
                    _expect_i64(size, f"IR instruction 'print'.aggregate_shape[{index}]")
                    for index, size in enumerate(aggregate_shape)
                ]
            ),
        }
    if type(instruction) is IRStructNew:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "fields": [
                ir_value_to_dto(field, schema_version=schema_version)
                for field in instruction.fields
            ],
        }
    if type(instruction) is IRStructGet:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "struct": ir_value_to_dto(instruction.struct, schema_version=schema_version),
            "field_index": _expect_i64(
                instruction.field_index,
                "IR instruction 'struct_get'.field_index",
            ),
            "field_name": _expect_string(
                instruction.field_name,
                "IR instruction 'struct_get'.field_name",
            ),
        }
    if type(instruction) is IRStructSet:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "struct": ir_value_to_dto(instruction.struct, schema_version=schema_version),
            "field_index": _expect_i64(
                instruction.field_index,
                "IR instruction 'struct_set'.field_index",
            ),
            "field_name": _expect_string(
                instruction.field_name,
                "IR instruction 'struct_set'.field_name",
            ),
            "value": ir_value_to_dto(instruction.value, schema_version=schema_version),
        }
    if type(instruction) is IRMethodResultNew:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "receiver": ir_value_to_dto(
                instruction.receiver,
                schema_version=schema_version,
            ),
            "value": (
                None
                if instruction.value is None
                else ir_value_to_dto(instruction.value, schema_version=schema_version)
            ),
        }
    if type(instruction) is IRMethodResultReceiver:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "method_result": ir_value_to_dto(
                instruction.method_result,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRMethodResultValue:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "method_result": ir_value_to_dto(
                instruction.method_result,
                schema_version=schema_version,
            ),
        }
    if type(instruction) in {IRArrayNew, IRListNew}:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "elements": [
                ir_value_to_dto(element, schema_version=schema_version)
                for element in instruction.elements
            ],
        }
    if type(instruction) is IRArrayCopy:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "array": ir_value_to_dto(instruction.array, schema_version=schema_version),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRListCopy:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "list_value": ir_value_to_dto(
                instruction.list_value,
                schema_version=schema_version,
            ),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) in {IRListContains, IRListIndexOf}:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "list_value": ir_value_to_dto(
                instruction.list_value,
                schema_version=schema_version,
            ),
            "value": ir_value_to_dto(instruction.value, schema_version=schema_version),
        }
    if type(instruction) is IRListClear:
        return {
            "kind": kind,
            "list_value": ir_value_to_dto(
                instruction.list_value,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRListPush:
        return {
            "kind": kind,
            "list_value": ir_value_to_dto(
                instruction.list_value,
                schema_version=schema_version,
            ),
            "value": ir_value_to_dto(instruction.value, schema_version=schema_version),
        }
    if type(instruction) is IRListInsert:
        return {
            "kind": kind,
            "list_value": ir_value_to_dto(
                instruction.list_value,
                schema_version=schema_version,
            ),
            "index": ir_value_to_dto(instruction.index, schema_version=schema_version),
            "value": ir_value_to_dto(instruction.value, schema_version=schema_version),
        }
    if type(instruction) is IRListRemoveAt:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "list_value": ir_value_to_dto(
                instruction.list_value,
                schema_version=schema_version,
            ),
            "index": ir_value_to_dto(instruction.index, schema_version=schema_version),
        }
    if type(instruction) is IRListPop:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "list_value": ir_value_to_dto(
                instruction.list_value,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRListReverse:
        return {
            "kind": kind,
            "list_value": ir_value_to_dto(
                instruction.list_value,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRSequenceSort:
        return {
            "kind": kind,
            "sequence": ir_value_to_dto(
                instruction.sequence,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRVectorNew:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "elements": [
                ir_value_to_dto(element, schema_version=schema_version)
                for element in instruction.elements
            ],
            "orientation": _expect_optional_string(
                instruction.orientation,
                "IR instruction 'vector_new'.orientation",
            ),
        }
    if type(instruction) is IRMatrixNew:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "elements": [
                ir_value_to_dto(element, schema_version=schema_version)
                for element in instruction.elements
            ],
            "shape": _shape_to_dto(
                (instruction.rows, instruction.cols),
                "IR instruction 'matrix_new'.shape",
            ),
        }
    if type(instruction) in {IRVectorAdd, IRVectorSub}:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "left": ir_value_to_dto(instruction.left, schema_version=schema_version),
            "right": ir_value_to_dto(instruction.right, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.length,),
                f"IR instruction '{kind}'.shape",
            ),
            "orientation": _expect_optional_string(
                instruction.orientation,
                f"IR instruction '{kind}'.orientation",
            ),
        }
    if type(instruction) is IRVectorScale:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "vector": ir_value_to_dto(instruction.vector, schema_version=schema_version),
            "scalar": ir_value_to_dto(instruction.scalar, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.length,),
                "IR instruction 'vector_scale'.shape",
            ),
            "orientation": _expect_optional_string(
                instruction.orientation,
                "IR instruction 'vector_scale'.orientation",
            ),
        }
    if type(instruction) is IRVectorDot:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "left": ir_value_to_dto(instruction.left, schema_version=schema_version),
            "right": ir_value_to_dto(instruction.right, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.length,),
                "IR instruction 'vector_dot'.shape",
            ),
        }
    if type(instruction) is IROuterProduct:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "column": ir_value_to_dto(instruction.column, schema_version=schema_version),
            "row": ir_value_to_dto(instruction.row, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.rows, instruction.cols),
                "IR instruction 'outer_product'.shape",
            ),
        }
    if type(instruction) in {IRMatrixAdd, IRMatrixSub}:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "left": ir_value_to_dto(instruction.left, schema_version=schema_version),
            "right": ir_value_to_dto(instruction.right, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.rows, instruction.cols),
                f"IR instruction '{kind}'.shape",
            ),
        }
    if type(instruction) is IRMatrixScale:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "matrix": ir_value_to_dto(instruction.matrix, schema_version=schema_version),
            "scalar": ir_value_to_dto(instruction.scalar, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.rows, instruction.cols),
                "IR instruction 'matrix_scale'.shape",
            ),
        }
    if type(instruction) is IRMatrixMatMul:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "left": ir_value_to_dto(instruction.left, schema_version=schema_version),
            "right": ir_value_to_dto(instruction.right, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.rows, instruction.inner, instruction.cols),
                "IR instruction 'matrix_mat_mul'.shape",
            ),
        }
    if type(instruction) is IRMatrixVectorMul:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "matrix": ir_value_to_dto(instruction.matrix, schema_version=schema_version),
            "vector": ir_value_to_dto(instruction.vector, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.rows, instruction.inner),
                "IR instruction 'matrix_vector_mul'.shape",
            ),
        }
    if type(instruction) is IRVectorMatrixMul:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "vector": ir_value_to_dto(instruction.vector, schema_version=schema_version),
            "matrix": ir_value_to_dto(instruction.matrix, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.rows, instruction.cols),
                "IR instruction 'vector_matrix_mul'.shape",
            ),
        }
    if type(instruction) is IRVectorGet:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "vector": ir_value_to_dto(instruction.vector, schema_version=schema_version),
            "index": ir_value_to_dto(instruction.index, schema_version=schema_version),
        }
    if type(instruction) is IRMatrixGet:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "matrix": ir_value_to_dto(instruction.matrix, schema_version=schema_version),
            "row": ir_value_to_dto(instruction.row, schema_version=schema_version),
            "column": ir_value_to_dto(instruction.column, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.cols,),
                "IR instruction 'matrix_get'.shape",
            ),
        }
    if type(instruction) is IRVectorLength:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "vector": ir_value_to_dto(instruction.vector, schema_version=schema_version),
        }
    if type(instruction) is IRMatrixRows:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "matrix": ir_value_to_dto(instruction.matrix, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.rows,),
                "IR instruction 'matrix_rows'.shape",
            ),
        }
    if type(instruction) is IRMatrixColumns:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "matrix": ir_value_to_dto(instruction.matrix, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.columns,),
                "IR instruction 'matrix_columns'.shape",
            ),
        }
    if type(instruction) is IRVectorSet:
        return {
            "kind": kind,
            "vector": ir_value_to_dto(instruction.vector, schema_version=schema_version),
            "index": ir_value_to_dto(instruction.index, schema_version=schema_version),
            "value": ir_value_to_dto(instruction.value, schema_version=schema_version),
        }
    if type(instruction) is IRMatrixSet:
        return {
            "kind": kind,
            "matrix": ir_value_to_dto(instruction.matrix, schema_version=schema_version),
            "row": ir_value_to_dto(instruction.row, schema_version=schema_version),
            "column": ir_value_to_dto(instruction.column, schema_version=schema_version),
            "value": ir_value_to_dto(instruction.value, schema_version=schema_version),
            "shape": _shape_to_dto(
                (instruction.cols,),
                "IR instruction 'matrix_set'.shape",
            ),
        }
    if type(instruction) is IRArrayGet:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "array": ir_value_to_dto(instruction.array, schema_version=schema_version),
            "index": ir_value_to_dto(instruction.index, schema_version=schema_version),
            "borrowed": _expect_bool(
                instruction.borrowed,
                "IR instruction 'array_get'.borrowed",
            ),
            "borrow_scope": _expect_optional_string(
                instruction.borrow_scope,
                "IR instruction 'array_get'.borrow_scope",
            ),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) in {IRArraySlice, IRListSlice}:
        collection_field = "array" if type(instruction) is IRArraySlice else "list_value"
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            collection_field: ir_value_to_dto(
                getattr(instruction, collection_field),
                schema_version=schema_version,
            ),
            "start": ir_value_to_dto(instruction.start, schema_version=schema_version),
            "end": ir_value_to_dto(instruction.end, schema_version=schema_version),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRListGet:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "list_value": ir_value_to_dto(
                instruction.list_value,
                schema_version=schema_version,
            ),
            "index": ir_value_to_dto(instruction.index, schema_version=schema_version),
            "borrowed": _expect_bool(
                instruction.borrowed,
                "IR instruction 'list_get'.borrowed",
            ),
            "borrow_scope": _expect_optional_string(
                instruction.borrow_scope,
                "IR instruction 'list_get'.borrow_scope",
            ),
            "source_location": ir_source_location_to_dto(
                instruction.source_location,
                schema_version=schema_version,
            ),
        }
    if type(instruction) is IRArraySet:
        return {
            "kind": kind,
            "array": ir_value_to_dto(instruction.array, schema_version=schema_version),
            "index": ir_value_to_dto(instruction.index, schema_version=schema_version),
            "value": ir_value_to_dto(instruction.value, schema_version=schema_version),
        }
    if type(instruction) is IRListSet:
        return {
            "kind": kind,
            "list_value": ir_value_to_dto(
                instruction.list_value,
                schema_version=schema_version,
            ),
            "index": ir_value_to_dto(instruction.index, schema_version=schema_version),
            "value": ir_value_to_dto(instruction.value, schema_version=schema_version),
        }
    if type(instruction) is IRArrayLength:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "array": ir_value_to_dto(instruction.array, schema_version=schema_version),
        }
    if type(instruction) in {IRListLength, IRListIsEmpty}:
        return {
            "kind": kind,
            "result": ir_value_to_dto(instruction.result, schema_version=schema_version),
            "list_value": ir_value_to_dto(
                instruction.list_value,
                schema_version=schema_version,
            ),
        }
    raise AssertionError(f"Missing encoder for registered IR instruction kind {kind!r}")


def ir_instruction_from_dto(
    dto: Mapping[str, object],
    *,
    schema_version: int = IR_SCHEMA_VERSION,
) -> IRInstruction:
    """Decode one strictly validated supported instruction DTO.

    This boundary validates only the versioned interchange shape.  Semantic
    facts such as whether function names exist or call signatures agree stay
    verbatim here and remain the responsibility of the Python IR verifier,
    which assigns the corresponding ``IRV-*`` diagnostics.
    """

    _require_schema_version(schema_version)
    mapping = _expect_mapping(dto, "IR instruction")
    kind = _expect_kind(mapping, "IR instruction")

    if kind == "const":
        _expect_fields(mapping, {"kind", "result", "value"}, "IR instruction 'const'")
        return IRConst(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_constant_from_dto(mapping["value"], schema_version=schema_version),
        )
    if kind == "load":
        _expect_fields(mapping, {"kind", "result", "slot"}, "IR instruction 'load'")
        return IRLoad(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["slot"], schema_version=schema_version),
        )
    if kind == "store":
        _expect_fields(mapping, {"kind", "slot", "value"}, "IR instruction 'store'")
        return IRStore(
            ir_value_from_dto(mapping["slot"], schema_version=schema_version),
            ir_value_from_dto(mapping["value"], schema_version=schema_version),
        )
    if kind == "init_default":
        _expect_fields(
            mapping,
            {"kind", "destination", "source_location"},
            "IR instruction 'init_default'",
        )
        return IRInitDefault(
            ir_storage_from_dto(mapping["destination"], schema_version=schema_version),
            ir_source_location_from_dto(mapping["source_location"], schema_version=schema_version),
        )
    if kind == "copy_init":
        _expect_fields(
            mapping,
            {"kind", "destination", "source", "source_location"},
            "IR instruction 'copy_init'",
        )
        return IRCopyInit(
            ir_storage_from_dto(mapping["destination"], schema_version=schema_version),
            ir_value_from_dto(mapping["source"], schema_version=schema_version),
            ir_source_location_from_dto(mapping["source_location"], schema_version=schema_version),
        )
    if kind == "move_init":
        _expect_fields(
            mapping,
            {"kind", "destination", "source", "source_location"},
            "IR instruction 'move_init'",
        )
        return IRMoveInit(
            ir_storage_from_dto(mapping["destination"], schema_version=schema_version),
            ir_storage_from_dto(mapping["source"], schema_version=schema_version),
            ir_source_location_from_dto(mapping["source_location"], schema_version=schema_version),
        )
    if kind == "assign":
        _expect_fields(
            mapping,
            {"kind", "destination", "source", "source_location"},
            "IR instruction 'assign'",
        )
        return IRAssign(
            ir_storage_from_dto(mapping["destination"], schema_version=schema_version),
            ir_value_from_dto(mapping["source"], schema_version=schema_version),
            ir_source_location_from_dto(mapping["source_location"], schema_version=schema_version),
        )
    if kind == "destroy":
        _expect_fields(
            mapping,
            {"kind", "value", "source_location"},
            "IR instruction 'destroy'",
        )
        return IRDestroy(
            ir_storage_from_dto(mapping["value"], schema_version=schema_version),
            ir_source_location_from_dto(mapping["source_location"], schema_version=schema_version),
        )
    if kind == "relocate":
        _expect_fields(
            mapping,
            {"kind", "destination", "source", "count", "source_location"},
            "IR instruction 'relocate'",
        )
        return IRRelocate(
            ir_storage_from_dto(mapping["destination"], schema_version=schema_version),
            ir_storage_from_dto(mapping["source"], schema_version=schema_version),
            _expect_i64(mapping["count"], "IR instruction 'relocate'.count"),
            ir_source_location_from_dto(mapping["source_location"], schema_version=schema_version),
        )
    if kind == "binary_op":
        _expect_fields(
            mapping,
            {"kind", "result", "operator", "left", "right", "source_location"},
            "IR instruction 'binary_op'",
        )
        return IRBinaryOp(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            _expect_string(mapping["operator"], "IR instruction 'binary_op'.operator"),
            ir_value_from_dto(mapping["left"], schema_version=schema_version),
            ir_value_from_dto(mapping["right"], schema_version=schema_version),
            ir_source_location_from_dto(mapping["source_location"], schema_version=schema_version),
        )
    if kind == "unary_op":
        _expect_fields(
            mapping,
            {"kind", "result", "operator", "operand"},
            "IR instruction 'unary_op'",
        )
        return IRUnaryOp(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            _expect_string(mapping["operator"], "IR instruction 'unary_op'.operator"),
            ir_value_from_dto(mapping["operand"], schema_version=schema_version),
        )
    if kind == "compare_op":
        _expect_fields(
            mapping,
            {"kind", "result", "operator", "left", "right", "aggregate_shape"},
            "IR instruction 'compare_op'",
        )
        raw_shape = mapping["aggregate_shape"]
        aggregate_shape = (
            None
            if raw_shape is None
            else tuple(
                _expect_i64(size, f"IR instruction 'compare_op'.aggregate_shape[{index}]")
                for index, size in enumerate(
                    _expect_sequence(raw_shape, "IR instruction 'compare_op'.aggregate_shape")
                )
            )
        )
        return IRCompareOp(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            _expect_string(mapping["operator"], "IR instruction 'compare_op'.operator"),
            ir_value_from_dto(mapping["left"], schema_version=schema_version),
            ir_value_from_dto(mapping["right"], schema_version=schema_version),
            aggregate_shape,
        )
    if kind == "cast":
        _expect_fields(mapping, {"kind", "result", "value"}, "IR instruction 'cast'")
        return IRCast(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["value"], schema_version=schema_version),
        )
    if kind == "call":
        _expect_fields(
            mapping,
            {"kind", "function", "arguments", "result", "builtin", "source_location"},
            "IR instruction 'call'",
        )
        arguments = _expect_sequence(mapping["arguments"], "IR instruction 'call'.arguments")
        raw_result = mapping["result"]
        return IRCall(
            _expect_string(mapping["function"], "IR instruction 'call'.function"),
            tuple(
                ir_value_from_dto(argument, schema_version=schema_version)
                for argument in arguments
            ),
            (
                None
                if raw_result is None
                else ir_value_from_dto(raw_result, schema_version=schema_version)
            ),
            _expect_optional_string(mapping["builtin"], "IR instruction 'call'.builtin"),
            ir_source_location_from_dto(mapping["source_location"], schema_version=schema_version),
        )
    if kind == "function_ref":
        _expect_fields(
            mapping,
            {"kind", "result", "function"},
            "IR instruction 'function_ref'",
        )
        return IRFunctionRef(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            _expect_string(
                mapping["function"],
                "IR instruction 'function_ref'.function",
            ),
        )
    if kind == "call_indirect":
        _expect_fields(
            mapping,
            {"kind", "callee", "arguments", "result"},
            "IR instruction 'call_indirect'",
        )
        arguments = _expect_sequence(
            mapping["arguments"],
            "IR instruction 'call_indirect'.arguments",
        )
        raw_result = mapping["result"]
        return IRCallIndirect(
            ir_value_from_dto(mapping["callee"], schema_version=schema_version),
            tuple(
                ir_value_from_dto(argument, schema_version=schema_version)
                for argument in arguments
            ),
            (
                None
                if raw_result is None
                else ir_value_from_dto(raw_result, schema_version=schema_version)
            ),
        )
    if kind == "print":
        _expect_fields(
            mapping,
            {"kind", "value", "newline", "aggregate_shape"},
            "IR instruction 'print'",
        )
        raw_shape = mapping["aggregate_shape"]
        aggregate_shape = (
            None
            if raw_shape is None
            else tuple(
                _expect_i64(size, f"IR instruction 'print'.aggregate_shape[{index}]")
                for index, size in enumerate(
                    _expect_sequence(raw_shape, "IR instruction 'print'.aggregate_shape")
                )
            )
        )
        return IRPrint(
            ir_value_from_dto(mapping["value"], schema_version=schema_version),
            _expect_bool(mapping["newline"], "IR instruction 'print'.newline"),
            aggregate_shape,
        )
    if kind == "struct_new":
        _expect_fields(
            mapping,
            {"kind", "result", "fields"},
            "IR instruction 'struct_new'",
        )
        fields = _expect_sequence(mapping["fields"], "IR instruction 'struct_new'.fields")
        return IRStructNew(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            tuple(
                ir_value_from_dto(field, schema_version=schema_version)
                for field in fields
            ),
        )
    if kind == "struct_get":
        _expect_fields(
            mapping,
            {"kind", "result", "struct", "field_index", "field_name"},
            "IR instruction 'struct_get'",
        )
        return IRStructGet(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["struct"], schema_version=schema_version),
            _expect_i64(mapping["field_index"], "IR instruction 'struct_get'.field_index"),
            _expect_string(mapping["field_name"], "IR instruction 'struct_get'.field_name"),
        )
    if kind == "struct_set":
        _expect_fields(
            mapping,
            {"kind", "result", "struct", "field_index", "field_name", "value"},
            "IR instruction 'struct_set'",
        )
        return IRStructSet(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["struct"], schema_version=schema_version),
            _expect_i64(mapping["field_index"], "IR instruction 'struct_set'.field_index"),
            _expect_string(mapping["field_name"], "IR instruction 'struct_set'.field_name"),
            ir_value_from_dto(mapping["value"], schema_version=schema_version),
        )
    if kind == "method_result_new":
        _expect_fields(
            mapping,
            {"kind", "result", "receiver", "value"},
            "IR instruction 'method_result_new'",
        )
        raw_value = mapping["value"]
        return IRMethodResultNew(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["receiver"], schema_version=schema_version),
            (
                None
                if raw_value is None
                else ir_value_from_dto(raw_value, schema_version=schema_version)
            ),
        )
    if kind == "method_result_receiver":
        _expect_fields(
            mapping,
            {"kind", "result", "method_result"},
            "IR instruction 'method_result_receiver'",
        )
        return IRMethodResultReceiver(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["method_result"], schema_version=schema_version),
        )
    if kind == "method_result_value":
        _expect_fields(
            mapping,
            {"kind", "result", "method_result"},
            "IR instruction 'method_result_value'",
        )
        return IRMethodResultValue(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["method_result"], schema_version=schema_version),
        )
    if kind in {"array_new", "list_new"}:
        _expect_fields(
            mapping,
            {"kind", "result", "elements"},
            f"IR instruction '{kind}'",
        )
        elements = _expect_sequence(
            mapping["elements"],
            f"IR instruction '{kind}'.elements",
        )
        instruction_type = IRArrayNew if kind == "array_new" else IRListNew
        return instruction_type(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            tuple(
                ir_value_from_dto(element, schema_version=schema_version)
                for element in elements
            ),
        )
    if kind == "array_copy":
        _expect_fields(
            mapping,
            {"kind", "result", "array", "source_location"},
            "IR instruction 'array_copy'",
        )
        return IRArrayCopy(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["array"], schema_version=schema_version),
            ir_source_location_from_dto(
                mapping["source_location"],
                schema_version=schema_version,
            ),
        )
    if kind == "list_copy":
        _expect_fields(
            mapping,
            {"kind", "result", "list_value", "source_location"},
            "IR instruction 'list_copy'",
        )
        return IRListCopy(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["list_value"], schema_version=schema_version),
            ir_source_location_from_dto(
                mapping["source_location"],
                schema_version=schema_version,
            ),
        )
    if kind in {"list_contains", "list_index_of"}:
        _expect_fields(
            mapping,
            {"kind", "result", "list_value", "value"},
            f"IR instruction '{kind}'",
        )
        instruction_type = IRListContains if kind == "list_contains" else IRListIndexOf
        return instruction_type(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["list_value"], schema_version=schema_version),
            ir_value_from_dto(mapping["value"], schema_version=schema_version),
        )
    if kind == "list_clear":
        _expect_fields(mapping, {"kind", "list_value"}, "IR instruction 'list_clear'")
        return IRListClear(
            ir_value_from_dto(mapping["list_value"], schema_version=schema_version)
        )
    if kind == "list_push":
        _expect_fields(
            mapping,
            {"kind", "list_value", "value"},
            "IR instruction 'list_push'",
        )
        return IRListPush(
            ir_value_from_dto(mapping["list_value"], schema_version=schema_version),
            ir_value_from_dto(mapping["value"], schema_version=schema_version),
        )
    if kind == "list_insert":
        _expect_fields(
            mapping,
            {"kind", "list_value", "index", "value"},
            "IR instruction 'list_insert'",
        )
        return IRListInsert(
            ir_value_from_dto(mapping["list_value"], schema_version=schema_version),
            ir_value_from_dto(mapping["index"], schema_version=schema_version),
            ir_value_from_dto(mapping["value"], schema_version=schema_version),
        )
    if kind == "list_remove_at":
        _expect_fields(
            mapping,
            {"kind", "result", "list_value", "index"},
            "IR instruction 'list_remove_at'",
        )
        return IRListRemoveAt(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["list_value"], schema_version=schema_version),
            ir_value_from_dto(mapping["index"], schema_version=schema_version),
        )
    if kind == "list_pop":
        _expect_fields(
            mapping,
            {"kind", "result", "list_value"},
            "IR instruction 'list_pop'",
        )
        return IRListPop(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["list_value"], schema_version=schema_version),
        )
    if kind == "list_reverse":
        _expect_fields(
            mapping,
            {"kind", "list_value"},
            "IR instruction 'list_reverse'",
        )
        return IRListReverse(
            ir_value_from_dto(mapping["list_value"], schema_version=schema_version)
        )
    if kind == "sequence_sort":
        _expect_fields(
            mapping,
            {"kind", "sequence"},
            "IR instruction 'sequence_sort'",
        )
        return IRSequenceSort(
            ir_value_from_dto(mapping["sequence"], schema_version=schema_version)
        )
    if kind == "vector_new":
        _expect_fields(
            mapping,
            {"kind", "result", "elements", "orientation"},
            "IR instruction 'vector_new'",
        )
        elements = _expect_sequence(
            mapping["elements"],
            "IR instruction 'vector_new'.elements",
        )
        return IRVectorNew(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            tuple(
                ir_value_from_dto(element, schema_version=schema_version)
                for element in elements
            ),
            _expect_optional_string(
                mapping["orientation"],
                "IR instruction 'vector_new'.orientation",
            ),
        )
    if kind == "matrix_new":
        _expect_fields(
            mapping,
            {"kind", "result", "elements", "shape"},
            "IR instruction 'matrix_new'",
        )
        elements = _expect_sequence(
            mapping["elements"],
            "IR instruction 'matrix_new'.elements",
        )
        rows, cols = _shape_from_dto(
            mapping["shape"],
            2,
            "IR instruction 'matrix_new'.shape",
        )
        return IRMatrixNew(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            tuple(
                ir_value_from_dto(element, schema_version=schema_version)
                for element in elements
            ),
            rows,
            cols,
        )
    if kind in {"vector_add", "vector_sub"}:
        _expect_fields(
            mapping,
            {"kind", "result", "left", "right", "shape", "orientation"},
            f"IR instruction '{kind}'",
        )
        instruction_type = IRVectorAdd if kind == "vector_add" else IRVectorSub
        (length,) = _shape_from_dto(
            mapping["shape"],
            1,
            f"IR instruction '{kind}'.shape",
        )
        return instruction_type(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["left"], schema_version=schema_version),
            ir_value_from_dto(mapping["right"], schema_version=schema_version),
            length,
            _expect_optional_string(
                mapping["orientation"],
                f"IR instruction '{kind}'.orientation",
            ),
        )
    if kind == "vector_scale":
        _expect_fields(
            mapping,
            {"kind", "result", "vector", "scalar", "shape", "orientation"},
            "IR instruction 'vector_scale'",
        )
        (length,) = _shape_from_dto(
            mapping["shape"],
            1,
            "IR instruction 'vector_scale'.shape",
        )
        return IRVectorScale(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["vector"], schema_version=schema_version),
            ir_value_from_dto(mapping["scalar"], schema_version=schema_version),
            length,
            _expect_optional_string(
                mapping["orientation"],
                "IR instruction 'vector_scale'.orientation",
            ),
        )
    if kind == "vector_dot":
        _expect_fields(
            mapping,
            {"kind", "result", "left", "right", "shape"},
            "IR instruction 'vector_dot'",
        )
        (length,) = _shape_from_dto(
            mapping["shape"],
            1,
            "IR instruction 'vector_dot'.shape",
        )
        return IRVectorDot(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["left"], schema_version=schema_version),
            ir_value_from_dto(mapping["right"], schema_version=schema_version),
            length,
        )
    if kind == "outer_product":
        _expect_fields(
            mapping,
            {"kind", "result", "column", "row", "shape"},
            "IR instruction 'outer_product'",
        )
        rows, cols = _shape_from_dto(
            mapping["shape"],
            2,
            "IR instruction 'outer_product'.shape",
        )
        return IROuterProduct(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["column"], schema_version=schema_version),
            ir_value_from_dto(mapping["row"], schema_version=schema_version),
            rows,
            cols,
        )
    if kind in {"matrix_add", "matrix_sub"}:
        _expect_fields(
            mapping,
            {"kind", "result", "left", "right", "shape"},
            f"IR instruction '{kind}'",
        )
        instruction_type = IRMatrixAdd if kind == "matrix_add" else IRMatrixSub
        rows, cols = _shape_from_dto(
            mapping["shape"],
            2,
            f"IR instruction '{kind}'.shape",
        )
        return instruction_type(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["left"], schema_version=schema_version),
            ir_value_from_dto(mapping["right"], schema_version=schema_version),
            rows,
            cols,
        )
    if kind == "matrix_scale":
        _expect_fields(
            mapping,
            {"kind", "result", "matrix", "scalar", "shape"},
            "IR instruction 'matrix_scale'",
        )
        rows, cols = _shape_from_dto(
            mapping["shape"],
            2,
            "IR instruction 'matrix_scale'.shape",
        )
        return IRMatrixScale(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["matrix"], schema_version=schema_version),
            ir_value_from_dto(mapping["scalar"], schema_version=schema_version),
            rows,
            cols,
        )
    if kind == "matrix_mat_mul":
        _expect_fields(
            mapping,
            {"kind", "result", "left", "right", "shape"},
            "IR instruction 'matrix_mat_mul'",
        )
        rows, inner, cols = _shape_from_dto(
            mapping["shape"],
            3,
            "IR instruction 'matrix_mat_mul'.shape",
        )
        return IRMatrixMatMul(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["left"], schema_version=schema_version),
            ir_value_from_dto(mapping["right"], schema_version=schema_version),
            rows,
            inner,
            cols,
        )
    if kind == "matrix_vector_mul":
        _expect_fields(
            mapping,
            {"kind", "result", "matrix", "vector", "shape"},
            "IR instruction 'matrix_vector_mul'",
        )
        rows, inner = _shape_from_dto(
            mapping["shape"],
            2,
            "IR instruction 'matrix_vector_mul'.shape",
        )
        return IRMatrixVectorMul(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["matrix"], schema_version=schema_version),
            ir_value_from_dto(mapping["vector"], schema_version=schema_version),
            rows,
            inner,
        )
    if kind == "vector_matrix_mul":
        _expect_fields(
            mapping,
            {"kind", "result", "vector", "matrix", "shape"},
            "IR instruction 'vector_matrix_mul'",
        )
        rows, cols = _shape_from_dto(
            mapping["shape"],
            2,
            "IR instruction 'vector_matrix_mul'.shape",
        )
        return IRVectorMatrixMul(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["vector"], schema_version=schema_version),
            ir_value_from_dto(mapping["matrix"], schema_version=schema_version),
            rows,
            cols,
        )
    if kind == "vector_get":
        _expect_fields(
            mapping,
            {"kind", "result", "vector", "index"},
            "IR instruction 'vector_get'",
        )
        return IRVectorGet(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["vector"], schema_version=schema_version),
            ir_value_from_dto(mapping["index"], schema_version=schema_version),
        )
    if kind == "matrix_get":
        _expect_fields(
            mapping,
            {"kind", "result", "matrix", "row", "column", "shape"},
            "IR instruction 'matrix_get'",
        )
        (cols,) = _shape_from_dto(
            mapping["shape"],
            1,
            "IR instruction 'matrix_get'.shape",
        )
        return IRMatrixGet(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["matrix"], schema_version=schema_version),
            ir_value_from_dto(mapping["row"], schema_version=schema_version),
            ir_value_from_dto(mapping["column"], schema_version=schema_version),
            cols,
        )
    if kind == "vector_length":
        _expect_fields(
            mapping,
            {"kind", "result", "vector"},
            "IR instruction 'vector_length'",
        )
        return IRVectorLength(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["vector"], schema_version=schema_version),
        )
    if kind == "matrix_rows":
        _expect_fields(
            mapping,
            {"kind", "result", "matrix", "shape"},
            "IR instruction 'matrix_rows'",
        )
        (rows,) = _shape_from_dto(
            mapping["shape"],
            1,
            "IR instruction 'matrix_rows'.shape",
        )
        return IRMatrixRows(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["matrix"], schema_version=schema_version),
            rows,
        )
    if kind == "matrix_columns":
        _expect_fields(
            mapping,
            {"kind", "result", "matrix", "shape"},
            "IR instruction 'matrix_columns'",
        )
        (columns,) = _shape_from_dto(
            mapping["shape"],
            1,
            "IR instruction 'matrix_columns'.shape",
        )
        return IRMatrixColumns(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["matrix"], schema_version=schema_version),
            columns,
        )
    if kind == "vector_set":
        _expect_fields(
            mapping,
            {"kind", "vector", "index", "value"},
            "IR instruction 'vector_set'",
        )
        return IRVectorSet(
            ir_value_from_dto(mapping["vector"], schema_version=schema_version),
            ir_value_from_dto(mapping["index"], schema_version=schema_version),
            ir_value_from_dto(mapping["value"], schema_version=schema_version),
        )
    if kind == "matrix_set":
        _expect_fields(
            mapping,
            {"kind", "matrix", "row", "column", "value", "shape"},
            "IR instruction 'matrix_set'",
        )
        (cols,) = _shape_from_dto(
            mapping["shape"],
            1,
            "IR instruction 'matrix_set'.shape",
        )
        return IRMatrixSet(
            ir_value_from_dto(mapping["matrix"], schema_version=schema_version),
            ir_value_from_dto(mapping["row"], schema_version=schema_version),
            ir_value_from_dto(mapping["column"], schema_version=schema_version),
            ir_value_from_dto(mapping["value"], schema_version=schema_version),
            cols,
        )
    if kind == "array_get":
        _expect_fields(
            mapping,
            {
                "kind",
                "result",
                "array",
                "index",
                "borrowed",
                "borrow_scope",
                "source_location",
            },
            "IR instruction 'array_get'",
        )
        return IRArrayGet(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["array"], schema_version=schema_version),
            ir_value_from_dto(mapping["index"], schema_version=schema_version),
            _expect_bool(mapping["borrowed"], "IR instruction 'array_get'.borrowed"),
            _expect_optional_string(
                mapping["borrow_scope"],
                "IR instruction 'array_get'.borrow_scope",
            ),
            ir_source_location_from_dto(
                mapping["source_location"],
                schema_version=schema_version,
            ),
        )
    if kind == "array_slice":
        _expect_fields(
            mapping,
            {"kind", "result", "array", "start", "end", "source_location"},
            "IR instruction 'array_slice'",
        )
        return IRArraySlice(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["array"], schema_version=schema_version),
            ir_value_from_dto(mapping["start"], schema_version=schema_version),
            ir_value_from_dto(mapping["end"], schema_version=schema_version),
            ir_source_location_from_dto(
                mapping["source_location"],
                schema_version=schema_version,
            ),
        )
    if kind == "list_slice":
        _expect_fields(
            mapping,
            {"kind", "result", "list_value", "start", "end", "source_location"},
            "IR instruction 'list_slice'",
        )
        return IRListSlice(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["list_value"], schema_version=schema_version),
            ir_value_from_dto(mapping["start"], schema_version=schema_version),
            ir_value_from_dto(mapping["end"], schema_version=schema_version),
            ir_source_location_from_dto(
                mapping["source_location"],
                schema_version=schema_version,
            ),
        )
    if kind == "list_get":
        _expect_fields(
            mapping,
            {
                "kind",
                "result",
                "list_value",
                "index",
                "borrowed",
                "borrow_scope",
                "source_location",
            },
            "IR instruction 'list_get'",
        )
        return IRListGet(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["list_value"], schema_version=schema_version),
            ir_value_from_dto(mapping["index"], schema_version=schema_version),
            _expect_bool(mapping["borrowed"], "IR instruction 'list_get'.borrowed"),
            _expect_optional_string(
                mapping["borrow_scope"],
                "IR instruction 'list_get'.borrow_scope",
            ),
            ir_source_location_from_dto(
                mapping["source_location"],
                schema_version=schema_version,
            ),
        )
    if kind == "array_set":
        _expect_fields(
            mapping,
            {"kind", "array", "index", "value"},
            "IR instruction 'array_set'",
        )
        return IRArraySet(
            ir_value_from_dto(mapping["array"], schema_version=schema_version),
            ir_value_from_dto(mapping["index"], schema_version=schema_version),
            ir_value_from_dto(mapping["value"], schema_version=schema_version),
        )
    if kind == "list_set":
        _expect_fields(
            mapping,
            {"kind", "list_value", "index", "value"},
            "IR instruction 'list_set'",
        )
        return IRListSet(
            ir_value_from_dto(mapping["list_value"], schema_version=schema_version),
            ir_value_from_dto(mapping["index"], schema_version=schema_version),
            ir_value_from_dto(mapping["value"], schema_version=schema_version),
        )
    if kind == "array_length":
        _expect_fields(
            mapping,
            {"kind", "result", "array"},
            "IR instruction 'array_length'",
        )
        return IRArrayLength(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["array"], schema_version=schema_version),
        )
    if kind in {"list_length", "list_is_empty"}:
        _expect_fields(
            mapping,
            {"kind", "result", "list_value"},
            f"IR instruction '{kind}'",
        )
        instruction_type = IRListLength if kind == "list_length" else IRListIsEmpty
        return instruction_type(
            ir_value_from_dto(mapping["result"], schema_version=schema_version),
            ir_value_from_dto(mapping["list_value"], schema_version=schema_version),
        )
    _unknown_tag("IR instruction", kind)


def _value_from_dto(
    dto: Mapping[str, object],
    *,
    expected_tag: str | None,
    schema_version: int,
) -> IRValue:
    mapping = _expect_mapping(dto, "IR value")
    tag = _expect_tag(mapping, "IR value")
    value_types: Mapping[str, type[IRValue]] = {
        "value": IRValue,
        "storage": IRStorage,
        "parameter": IRParameter,
    }
    if tag not in value_types:
        _unknown_tag("IR value", tag)
    if expected_tag is not None and tag != expected_tag:
        raise IRDTOError(f"IR {expected_tag} DTO requires tag '{expected_tag}', got '{tag}'")
    _expect_fields(mapping, {"tag", "name", "type"}, f"IR value '{tag}'")
    return value_types[tag](
        _expect_string(mapping["name"], f"IR value '{tag}'.name"),
        ir_type_from_dto(mapping["type"], schema_version=schema_version),
    )


def _require_exact_value_kind(value: object, expected: type[IRValue], entity: str) -> None:
    if type(value) is not expected:
        raise TypeError(f"Unsupported IR {entity} for schema v{IR_SCHEMA_VERSION}: {type(value).__name__}")


def _require_schema_version(schema_version: object) -> None:
    if type(schema_version) is not int or schema_version != IR_SCHEMA_VERSION:
        raise IRDTOSchemaVersionError(
            f"Unsupported IR DTO schema version {schema_version!r}; expected {IR_SCHEMA_VERSION}"
        )


def _expect_mapping(value: object, entity: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise IRDTOError(f"{entity} DTO must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise IRDTOError(f"{entity} DTO field names must be strings")
    return value


def _expect_fields(mapping: Mapping[str, object], fields: set[str], entity: str) -> None:
    actual = set(mapping)
    missing = sorted(fields - actual)
    unexpected = sorted(actual - fields)
    details: list[str] = []
    if missing:
        details.append(f"missing fields: {', '.join(missing)}")
    if unexpected:
        details.append(f"unexpected fields: {', '.join(unexpected)}")
    if details:
        raise IRDTOError(f"Malformed {entity} DTO ({'; '.join(details)})")


def _expect_tag(mapping: Mapping[str, object], entity: str) -> str:
    if "tag" not in mapping:
        raise IRDTOError(f"Malformed {entity} DTO (missing fields: tag)")
    return _expect_string(mapping["tag"], f"{entity}.tag")


def _expect_kind(mapping: Mapping[str, object], entity: str) -> str:
    if "kind" not in mapping:
        raise IRDTOError(f"Malformed {entity} DTO (missing fields: kind)")
    return _expect_string(mapping["kind"], f"{entity}.kind")


def _unknown_tag(entity: str, tag: str) -> NoReturn:
    raise IRDTOError(f"Unknown {entity} DTO tag: {tag!r}")


def _expect_sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise IRDTOError(f"{field} must be a sequence")
    return value


def _shape_to_dto(dimensions: Sequence[object], field: str) -> list[int]:
    """Encode retained dimension metadata in canonical row-major order."""

    return [
        _expect_i64(dimension, f"{field}[{index}]")
        for index, dimension in enumerate(dimensions)
    ]


def _shape_from_dto(value: object, rank: int, field: str) -> tuple[int, ...]:
    """Decode one fixed-rank shape without enforcing semantic dimension rules."""

    dimensions = _expect_sequence(value, field)
    if len(dimensions) != rank:
        raise IRDTOError(f"{field} must contain exactly {rank} dimensions")
    return tuple(
        _expect_i64(dimension, f"{field}[{index}]")
        for index, dimension in enumerate(dimensions)
    )


def _expect_string(value: object, field: str) -> str:
    if type(value) is not str:
        raise IRDTOError(f"{field} must be a string")
    return value


def _expect_optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _expect_string(value, field)


def _expect_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise IRDTOError(f"{field} must be a boolean")
    return value


def _expect_float(value: object, field: str) -> float:
    if type(value) is not float:
        raise IRDTOError(f"{field} must be a floating-point value")
    return value


def _expect_i32(value: object, field: str) -> int:
    if type(value) is not int or not -(2**31) <= value < 2**31:
        raise IRDTOError(f"{field} must be a signed 32-bit integer")
    return value


def _expect_i64(value: object, field: str) -> int:
    if type(value) is not int or not -(2**63) <= value < 2**63:
        raise IRDTOError(f"{field} must be a signed 64-bit integer")
    return value


def _require_i32(value: object, field: str) -> None:
    _expect_i32(value, field)


def _require_i64(value: object, field: str) -> None:
    _expect_i64(value, field)


__all__ = [
    "IR_SCHEMA_VERSION",
    "IR_INSTRUCTION_TAGS",
    "IR_TYPE_TAGS",
    "IRConstant",
    "IRConstantDTO",
    "IRDTOError",
    "IRDTOSchemaVersionError",
    "IREnumConstantDTO",
    "IRInstructionDTO",
    "IRParameterDTO",
    "IRSourceLocationDTO",
    "IRStorageDTO",
    "IRTypeDTO",
    "IRValueDTO",
    "ir_constant_from_dto",
    "ir_constant_to_dto",
    "ir_enum_constant_from_dto",
    "ir_enum_constant_to_dto",
    "ir_instruction_from_dto",
    "ir_instruction_to_dto",
    "ir_parameter_from_dto",
    "ir_parameter_to_dto",
    "ir_source_location_from_dto",
    "ir_source_location_to_dto",
    "ir_storage_from_dto",
    "ir_storage_to_dto",
    "ir_type_from_dto",
    "ir_type_to_dto",
    "ir_value_from_dto",
    "ir_value_to_dto",
]
