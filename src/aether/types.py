from __future__ import annotations

from dataclasses import dataclass
from math import trunc
from typing import Any

from .errors import AetherRuntimeError, AetherTypeError
from .integer_arithmetic import checked_int_binary
from .range_safety import RANGE_STEP_ZERO_MESSAGE
from .string_value import StringValue, as_string_value


TYPE_NAMES = {
    "int", "float", "double", "complex", "string", "boolean",
    "ParseStatus", "IntParseResult", "DoubleParseResult", "FileStatus", "FileReadResult",
}
REAL_NUMERIC_TYPES = {"int", "float", "double"}
NUMERIC_TYPES = REAL_NUMERIC_TYPES | {"complex"}
VOID_VALUE = None
WIDENING: dict[str, set[str]] = {
    "int": {"float", "double", "complex"},
    "float": {"double", "complex"},
    "double": {"complex"},
    "complex": set(),
    "string": set(),
    "boolean": set(),
}


@dataclass(frozen=True, eq=False)
class ArrayType:
    element_type: AetherType

    def __post_init__(self) -> None:
        # Nominal names are resolved by the typechecker after parsing.  Keep
        # primitive validation here, but do not reject a syntactically valid
        # enum/struct name before its declaration table exists.
        if isinstance(self.element_type, str) and self.element_type != "void":
            return
        if not is_known_type(self.element_type):
            raise AetherTypeError(f"Unknown array element type '{type_to_string(self.element_type)}'.")

    def __str__(self) -> str:
        return f"Array<{type_to_string(self.element_type)}>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ArrayType):
            return self.element_type == other.element_type
        if isinstance(other, str):
            return str(self) == other
        return False

    def __hash__(self) -> int:
        return hash(str(self))


@dataclass(frozen=True, eq=False)
class ListType:
    element_type: AetherType

    def __post_init__(self) -> None:
        if isinstance(self.element_type, str) and self.element_type != "void":
            return
        if not is_known_type(self.element_type):
            raise AetherTypeError(f"Unknown list element type '{type_to_string(self.element_type)}'.")

    def __str__(self) -> str:
        return f"List<{type_to_string(self.element_type)}>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ListType):
            return self.element_type == other.element_type
        if isinstance(other, str):
            return str(self) == other
        return False

    def __hash__(self) -> int:
        return hash(("List", self.element_type))


@dataclass(frozen=True, eq=False)
class MatrixType:
    element_type: str
    rows: int | None = None
    cols: int | None = None
    vector: bool = False

    def __post_init__(self) -> None:
        if self.element_type not in TYPE_NAMES:
            raise AetherTypeError(f"Unknown matrix element type '{self.element_type}'.")
        if self.rows is not None and self.rows < 0:
            raise AetherTypeError("Matrix row count cannot be negative.")
        if self.cols is not None and self.cols < 0:
            raise AetherTypeError("Matrix column count cannot be negative.")
        if self.vector and self.rows is not None and self.cols is not None and self.rows > 1 and self.cols > 1:
            raise AetherTypeError("Vector<T> only accepts matrix values with shape 1xN or Nx1.")

    def with_shape(self, rows: int, cols: int) -> "MatrixType":
        return MatrixType(self.element_type, rows, cols, self.vector)

    def as_matrix(self) -> "MatrixType":
        return MatrixType(self.element_type, self.rows, self.cols)

    def __str__(self) -> str:
        name = "Vector" if self.vector else "Matrix"
        return f"{name}<{self.element_type}>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, MatrixType):
            return (
                self.element_type == other.element_type
                and self.rows == other.rows
                and self.cols == other.cols
                and self.vector == other.vector
            )
        if isinstance(other, str):
            return str(self) == other
        return False

    def __hash__(self) -> int:
        return hash((self.element_type, self.rows, self.cols, self.vector))


@dataclass(frozen=True, eq=False)
class VectorType:
    element_type: str
    length: int | None = None
    orientation: str | None = None

    def __post_init__(self) -> None:
        if self.element_type not in TYPE_NAMES:
            raise AetherTypeError(f"Unknown vector element type '{self.element_type}'.")
        if self.length is not None and self.length < 0:
            raise AetherTypeError("Vector length cannot be negative.")
        if self.orientation not in {None, "row", "column"}:
            raise AetherTypeError("Vector orientation must be 'row' or 'column'.")

    def __str__(self) -> str:
        return f"Vector<{self.element_type}>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, VectorType):
            orientations_compatible = (
                self.orientation == other.orientation
                or self.orientation is None
                or other.orientation is None
            )
            return self.element_type == other.element_type and self.length == other.length and orientations_compatible
        if isinstance(other, str):
            return str(self) == other
        return False

    def __hash__(self) -> int:
        return hash((self.element_type, self.length))


@dataclass(frozen=True, eq=False)
class TransposeVectorType:
    element_type: str
    length: int | None = None

    def __post_init__(self) -> None:
        if self.element_type not in TYPE_NAMES:
            raise AetherTypeError(f"Unknown vector element type '{self.element_type}'.")
        if self.length is not None and self.length < 0:
            raise AetherTypeError("TransposeVector length cannot be negative.")

    def __str__(self) -> str:
        return f"TransposeVector<{self.element_type}>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TransposeVectorType):
            return self.element_type == other.element_type and self.length == other.length
        if isinstance(other, str):
            return str(self) == other
        return False

    def __hash__(self) -> int:
        return hash((self.element_type, self.length))


@dataclass(frozen=True, eq=False)
class RangeType:
    element_type: str = "int"

    def __post_init__(self) -> None:
        if self.element_type != "int":
            raise AetherTypeError("Ranges only support int elements in Aether v0.")

    def __str__(self) -> str:
        return f"Range<{self.element_type}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RangeType) and self.element_type == other.element_type

    def __hash__(self) -> int:
        return hash(("Range", self.element_type))


@dataclass(frozen=True, eq=False)
class TupleType:
    element_types: tuple["AetherType", ...]

    def __post_init__(self) -> None:
        if len(self.element_types) < 2:
            raise AetherTypeError("Tuple types require at least two elements.")
        for element_type in self.element_types:
            if not is_known_type(element_type):
                raise AetherTypeError(f"Unknown tuple element type '{type_to_string(element_type)}'.")

    def __str__(self) -> str:
        return "(" + ", ".join(type_to_string(element_type) for element_type in self.element_types) + ")"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TupleType) and self.element_types == other.element_types

    def __hash__(self) -> int:
        return hash(("Tuple", self.element_types))


@dataclass(frozen=True, eq=False)
class NullType:
    def __str__(self) -> str:
        return "null"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, NullType)

    def __hash__(self) -> int:
        return hash("NullType")


@dataclass(frozen=True, eq=False)
class NullableType:
    base_type: "AetherType"

    def __post_init__(self) -> None:
        if isinstance(self.base_type, (NullableType, NullType)):
            raise AetherTypeError("Nullable types require a non-null base type.")
        if isinstance(self.base_type, str):
            if self.base_type == "void":
                raise AetherTypeError("'void' cannot be nullable.")
            return
        if not is_known_type(self.base_type):
            raise AetherTypeError(f"Unknown nullable base type '{type_to_string(self.base_type)}'.")

    def __str__(self) -> str:
        return f"{type_to_string(self.base_type)}?"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, NullableType) and self.base_type == other.base_type

    def __hash__(self) -> int:
        return hash(("Nullable", self.base_type))


@dataclass(frozen=True)
class NullableValue:
    """Canonical in-memory representation of an Aether ``T?`` value."""

    has_value: bool
    value: Any = None

    def __post_init__(self) -> None:
        if not self.has_value and self.value is not None:
            raise AetherTypeError("An absent nullable value cannot contain a live payload.")


@dataclass(frozen=True)
class EnumIdentity:
    """Stable nominal identity for a source enum declaration.

    ``owner`` is the semantic module/package id, never an absolute path.
    ``declaration`` is the declaration name within that module.
    """

    owner: str
    declaration: str

    def __str__(self) -> str:
        return f"{self.owner}.{self.declaration}"


@dataclass(frozen=True, eq=False)
class EnumType:
    name: str
    identity: EnumIdentity | None = None

    def __str__(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        if isinstance(other, EnumType):
            if self.identity is not None or other.identity is not None:
                return self.identity is not None and self.identity == other.identity
            return self.name == other.name
        if isinstance(other, str):
            return self.name == other
        return False

    def __hash__(self) -> int:
        return hash(("Enum", self.identity if self.identity is not None else self.name))


@dataclass(frozen=True, eq=False)
class InterfaceType:
    name: str

    def __str__(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        if isinstance(other, InterfaceType):
            return self.name == other.name
        if isinstance(other, str):
            return self.name == other
        return False

    def __hash__(self) -> int:
        return hash(("Interface", self.name))


@dataclass(frozen=True, eq=False)
class ClassType:
    name: str

    def __str__(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ClassType):
            return self.name == other.name
        if isinstance(other, str):
            return self.name == other
        return False

    def __hash__(self) -> int:
        return hash(("Class", self.name))


@dataclass(frozen=True, eq=False)
class FunctionType:
    """Structural type of a capture-free top-level function reference."""

    parameter_types: tuple["AetherType", ...]
    return_type: "AetherType"

    def __post_init__(self) -> None:
        for parameter_type in self.parameter_types:
            if parameter_type == "void" or not (
                isinstance(parameter_type, str) or is_known_type(parameter_type)
            ):
                raise AetherTypeError(
                    f"Unknown callable parameter type '{type_to_string(parameter_type)}'."
                )
        if self.return_type != "void" and not (
            isinstance(self.return_type, str) or is_known_type(self.return_type)
        ):
            raise AetherTypeError(
                f"Unknown callable return type '{type_to_string(self.return_type)}'."
            )

    def __str__(self) -> str:
        parameters = ", ".join(type_to_string(item) for item in self.parameter_types)
        return f"{type_to_string(self.return_type)}({parameters})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, FunctionType)
            and self.parameter_types == other.parameter_types
            and self.return_type == other.return_type
        )

    def __hash__(self) -> int:
        return hash(("Function", self.parameter_types, self.return_type))


AetherType = (
    str
    | ArrayType
    | ListType
    | MatrixType
    | VectorType
    | TransposeVectorType
    | RangeType
    | TupleType
    | NullType
    | NullableType
    | EnumType
    | InterfaceType
    | ClassType
    | FunctionType
)
NULL_TYPE = NullType()


@dataclass(frozen=True)
class AetherValue:
    type_name: AetherType
    value: Any

    def __post_init__(self) -> None:
        if isinstance(self.type_name, NullableType):
            nullable = (
                self.value
                if isinstance(self.value, NullableValue)
                else NullableValue(self.value is not None, self.value)
            )
            object.__setattr__(self, "value", nullable)
        base_type = (
            self.type_name.base_type
            if isinstance(self.type_name, NullableType)
            and isinstance(self.value, NullableValue)
            and self.value.has_value
            else self.type_name
        )
        payload = (
            self.value.value
            if isinstance(self.type_name, NullableType)
            and isinstance(self.value, NullableValue)
            and self.value.has_value
            else self.value
        )
        if base_type == "string" and isinstance(payload, (str, StringValue)):
            # General values come from runtime operations (builtins,
            # interpolation, arguments). Source and IR literal construction
            # opts into immortal storage explicitly.
            converted = as_string_value(payload, literal=False)
            object.__setattr__(
                self,
                "value",
                NullableValue(True, converted)
                if isinstance(self.type_name, NullableType)
                else converted,
            )
            payload = converted
        if isinstance(base_type, (ArrayType, ListType)) and isinstance(payload, list):
            from .collection_value import CollectionObject

            if not isinstance(payload, CollectionObject):
                converted = CollectionObject(
                    "Array" if isinstance(base_type, ArrayType) else "List",
                    base_type.element_type,
                    payload,
                )
                object.__setattr__(
                    self,
                    "value",
                    NullableValue(True, converted)
                    if isinstance(self.type_name, NullableType)
                    else converted,
                )


@dataclass
class StructInstance:
    type_name: str
    fields: dict[str, AetherValue]
    field_order: tuple[str, ...]


@dataclass
class ClassInstance:
    type_name: str
    fields: dict[str, AetherValue]
    field_order: tuple[str, ...]


@dataclass(frozen=True, eq=False)
class EnumValue:
    enum_name: str
    variant_name: str
    enum_id: EnumIdentity | None = None
    member_id: int = 0
    discriminant: int = 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EnumValue):
            return False
        if self.enum_id is not None or other.enum_id is not None:
            return (
                self.enum_id is not None
                and self.enum_id == other.enum_id
                and self.member_id == other.member_id
                and self.discriminant == other.discriminant
            )
        return self.enum_name == other.enum_name and self.variant_name == other.variant_name

    def __hash__(self) -> int:
        if self.enum_id is not None:
            return hash((self.enum_id, self.member_id, self.discriminant))
        return hash((self.enum_name, self.variant_name))


@dataclass(frozen=True)
class AetherRange:
    start: int
    step: int
    end: int

    def __iter__(self):
        if self.step == 0:
            raise AetherTypeError(RANGE_STEP_ZERO_MESSAGE)
        current = self.start
        if self.step > 0:
            while current <= self.end:
                yield AetherValue("int", current)
                if current == self.end:
                    return
                try:
                    current = int(checked_int_binary("add", current, self.step))
                except OverflowError as exc:
                    raise AetherRuntimeError(str(exc)) from exc
            return
        while current >= self.end:
            yield AetherValue("int", current)
            if current == self.end:
                return
            try:
                current = int(checked_int_binary("add", current, self.step))
            except OverflowError as exc:
                raise AetherRuntimeError(str(exc)) from exc


def default_text(value: AetherValue) -> str:
    from .formatting import format_value

    return format_value(value)


def infer_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "double"
    if isinstance(value, complex):
        return "complex"
    if isinstance(value, (str, StringValue)):
        return "string"
    raise AetherTypeError(f"Cannot infer Aether type for value {value!r}.")


def type_to_string(type_name: AetherType) -> str:
    return str(type_name)


def is_known_type(type_name: AetherType) -> bool:
    if isinstance(type_name, FunctionType):
        return all(
            item != "void" and (isinstance(item, str) or is_known_type(item))
            for item in type_name.parameter_types
        ) and (
            type_name.return_type == "void"
            or isinstance(type_name.return_type, str)
            or is_known_type(type_name.return_type)
        )
    if isinstance(type_name, NullableType):
        return is_known_type(type_name.base_type)
    if isinstance(type_name, NullType):
        return True
    if isinstance(type_name, ArrayType):
        return is_known_type(type_name.element_type)
    if isinstance(type_name, ListType):
        return is_known_type(type_name.element_type)
    if isinstance(type_name, TupleType):
        return all(is_known_type(element_type) for element_type in type_name.element_types)
    if isinstance(type_name, MatrixType):
        return type_name.element_type in TYPE_NAMES
    if isinstance(type_name, (VectorType, TransposeVectorType)):
        return type_name.element_type in TYPE_NAMES
    if isinstance(type_name, RangeType):
        return type_name.element_type == "int"
    if isinstance(type_name, (EnumType, InterfaceType, ClassType)):
        return True
    return type_name in TYPE_NAMES


def is_array_type(type_name: AetherType) -> bool:
    return isinstance(type_name, ArrayType)


def is_list_type(type_name: AetherType) -> bool:
    return isinstance(type_name, ListType)


def is_matrix_type(type_name: AetherType) -> bool:
    return isinstance(type_name, MatrixType)


def is_vector_type(type_name: AetherType) -> bool:
    return isinstance(type_name, VectorType)


def is_transpose_vector_type(type_name: AetherType) -> bool:
    return isinstance(type_name, TransposeVectorType)


def is_vector_like_type(type_name: AetherType) -> bool:
    return isinstance(type_name, (VectorType, TransposeVectorType)) or (
        isinstance(type_name, MatrixType) and type_name.vector
    )


def is_range_type(type_name: AetherType) -> bool:
    return isinstance(type_name, RangeType)


def is_indexable_type(type_name: AetherType) -> bool:
    return isinstance(type_name, (ArrayType, ListType, MatrixType, VectorType, TransposeVectorType))


def is_mutable_reference_type(type_name: AetherType) -> bool:
    return isinstance(type_name, (ArrayType, ListType, MatrixType, VectorType, TransposeVectorType))


def shape_dimensions(value: AetherValue) -> list[int]:
    type_name = value.type_name
    if isinstance(type_name, NullableType):
        nullable = value.value
        if not isinstance(nullable, NullableValue) or not nullable.has_value:
            raise AetherTypeError(f"size(...) is not defined for null '{type_to_string(type_name)}'.")
        return shape_dimensions(AetherValue(type_name.base_type, nullable.value))
    if isinstance(type_name, VectorType):
        return [len(value.value)]
    if isinstance(type_name, TransposeVectorType):
        return [1, len(value.value.value)]
    if isinstance(type_name, MatrixType):
        rows = len(value.value)
        cols = len(value.value[0].value) if value.value else 0
        return [rows, cols]
    if isinstance(type_name, ArrayType):
        return [len(value.value)]
    if isinstance(type_name, ListType):
        return [len(value.value)]
    if isinstance(type_name, str) and type_name in TYPE_NAMES:
        return []
    raise AetherTypeError(f"size(...) is not defined for '{type_to_string(type_name)}'.")


def shape_dimension_count(type_name: AetherType) -> int:
    if isinstance(type_name, NullableType):
        return shape_dimension_count(type_name.base_type)
    if isinstance(type_name, VectorType):
        return 1
    if isinstance(type_name, (MatrixType, TransposeVectorType)):
        return 2
    if isinstance(type_name, ArrayType):
        return 1
    if isinstance(type_name, ListType):
        return 1
    if isinstance(type_name, str) and type_name in TYPE_NAMES:
        return 0
    raise AetherTypeError(f"size(...) is not defined for '{type_to_string(type_name)}'.")


def shape_vector_value(value: AetherValue) -> AetherValue:
    dimensions = shape_dimensions(value)
    return AetherValue(
        VectorType("int", len(dimensions)),
        [AetherValue("int", dimension) for dimension in dimensions],
    )


def array_element_type(type_name: AetherType) -> AetherType:
    if not isinstance(type_name, ArrayType):
        raise AetherTypeError(f"Expected array type, got '{type_to_string(type_name)}'.")
    return type_name.element_type


def list_element_type(type_name: AetherType) -> AetherType:
    if not isinstance(type_name, ListType):
        raise AetherTypeError(f"Expected list type, got '{type_to_string(type_name)}'.")
    return type_name.element_type


def matrix_row_type(type_name: AetherType) -> ArrayType:
    if not isinstance(type_name, MatrixType):
        raise AetherTypeError(f"Expected matrix type, got '{type_to_string(type_name)}'.")
    return ArrayType(type_name.element_type)


def can_implicitly_convert(from_type: AetherType, to_type: AetherType) -> bool:
    if isinstance(from_type, FunctionType) or isinstance(to_type, FunctionType):
        return from_type == to_type
    if isinstance(to_type, NullableType):
        if isinstance(from_type, NullType):
            return True
        if isinstance(from_type, NullableType):
            return can_implicitly_convert(from_type.base_type, to_type.base_type)
        return can_implicitly_convert(from_type, to_type.base_type)
    if isinstance(from_type, (NullType, NullableType)):
        return from_type == to_type
    if isinstance(from_type, TupleType) or isinstance(to_type, TupleType):
        if not isinstance(from_type, TupleType) or not isinstance(to_type, TupleType):
            return False
        if len(from_type.element_types) != len(to_type.element_types):
            return False
        return all(
            can_implicitly_convert(source_type, target_type)
            for source_type, target_type in zip(from_type.element_types, to_type.element_types)
        )
    if isinstance(from_type, RangeType) or isinstance(to_type, RangeType):
        return from_type == to_type
    if isinstance(from_type, EnumType) or isinstance(to_type, EnumType):
        return from_type == to_type
    if isinstance(from_type, ClassType) or isinstance(to_type, ClassType):
        return from_type == to_type
    if isinstance(from_type, InterfaceType) or isinstance(to_type, InterfaceType):
        return from_type == to_type
    if isinstance(from_type, ListType) or isinstance(to_type, ListType):
        if not isinstance(from_type, ListType) or not isinstance(to_type, ListType):
            return False
        return can_implicitly_convert(from_type.element_type, to_type.element_type)
    if isinstance(from_type, TransposeVectorType) or isinstance(to_type, TransposeVectorType):
        return from_type == to_type
    if isinstance(from_type, VectorType) or isinstance(to_type, VectorType):
        if isinstance(from_type, VectorType) and isinstance(to_type, VectorType):
            if not can_implicitly_convert(from_type.element_type, to_type.element_type):
                return False
            if to_type.length is not None and from_type.length is not None and to_type.length != from_type.length:
                return False
            if (
                to_type.orientation is not None
                and from_type.orientation is not None
                and to_type.orientation != from_type.orientation
            ):
                return False
            return True
        if isinstance(to_type, VectorType) and isinstance(from_type, MatrixType):
            if not can_implicitly_convert(from_type.element_type, to_type.element_type):
                return False
            if from_type.rows is not None and from_type.cols is not None and from_type.rows > 1 and from_type.cols > 1:
                return False
            source_length = _matrix_vector_length(from_type)
            if to_type.length is not None and source_length is not None and to_type.length != source_length:
                return False
            return True
        return False
    if isinstance(from_type, MatrixType) or isinstance(to_type, MatrixType):
        if not isinstance(from_type, MatrixType) or not isinstance(to_type, MatrixType):
            return False
        if not can_implicitly_convert(from_type.element_type, to_type.element_type):
            return False
        if to_type.vector and from_type.rows is not None and from_type.cols is not None:
            if from_type.rows > 1 and from_type.cols > 1:
                return False
        if to_type.rows is not None and from_type.rows is not None and to_type.rows != from_type.rows:
            return False
        if to_type.cols is not None and from_type.cols is not None and to_type.cols != from_type.cols:
            return False
        return True
    if isinstance(from_type, ArrayType) or isinstance(to_type, ArrayType):
        return from_type == to_type
    return from_type == to_type or to_type in WIDENING.get(from_type, set())


def coerce_implicit(value: AetherValue, target_type: AetherType) -> AetherValue:
    if value.type_name == target_type:
        return copy_value(value) if contains_struct_value(value) else value
    if isinstance(target_type, NullableType):
        if isinstance(value.type_name, NullType):
            return AetherValue(target_type, NullableValue(False))
        if isinstance(value.type_name, NullableType):
            nullable = value.value
            if not isinstance(nullable, NullableValue):
                raise AetherTypeError("Invalid internal nullable value.")
            if not nullable.has_value:
                return AetherValue(target_type, NullableValue(False))
            value = AetherValue(value.type_name.base_type, nullable.value)
        coerced = coerce_implicit(value, target_type.base_type)
        return AetherValue(target_type, NullableValue(True, coerced.value))
    if not is_known_type(target_type):
        raise AetherTypeError(f"Unknown type '{type_to_string(target_type)}'.")
    if isinstance(value.type_name, NullType):
        raise AetherTypeError(
            f"Cannot implicitly convert 'null' to '{type_to_string(target_type)}'. "
            f"Use {type_to_string(target_type)}? for nullable values."
        )
    if isinstance(value.type_name, NullableType):
        raise AetherTypeError(
            f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'."
        )
    if isinstance(target_type, TupleType):
        return coerce_tuple_value(value, target_type)
    if isinstance(target_type, InterfaceType):
        if isinstance(value.value, ClassInstance):
            return AetherValue(target_type, value.value)
        if isinstance(value.value, StructInstance) or value.type_name == target_type:
            return AetherValue(target_type, copy_value(value).value)
        raise AetherTypeError(
            f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'."
        )
    if isinstance(target_type, ArrayType):
        return coerce_array_literal_value(value, target_type)
    if isinstance(target_type, ListType):
        return coerce_list_value(value, target_type)
    if isinstance(target_type, VectorType):
        return coerce_vector_value(value, target_type)
    if isinstance(target_type, TransposeVectorType):
        return coerce_transpose_vector_value(value, target_type)
    if isinstance(target_type, MatrixType):
        return coerce_matrix_value(value, target_type)
    if not can_implicitly_convert(value.type_name, target_type):
        raise AetherTypeError(
            f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'. "
            f"Use {type_to_string(target_type)}(...) for explicit conversion."
        )
    return AetherValue(target_type, _coerce_python_value(value.value, target_type))


def coerce_return_value(value: AetherValue, target_type: AetherType) -> AetherValue:
    if target_type == "void":
        if value.type_name != "void":
            raise AetherTypeError(
                f"Cannot implicitly convert '{type_to_string(value.type_name)}' to 'void'."
            )
        return AetherValue("void", VOID_VALUE)
    if isinstance(target_type, TupleType):
        if not isinstance(value.type_name, TupleType):
            raise AetherTypeError(
                f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'."
            )
        if len(value.type_name.element_types) != len(target_type.element_types):
            raise AetherTypeError("Tuple return type arity mismatch.")
        return AetherValue(
            target_type,
            tuple(
                coerce_return_value(element, element_type)
                for element, element_type in zip(value.value, target_type.element_types)
            ),
        )
    if target_type == "float" and value.type_name == "double":
        return AetherValue("float", float(value.value))
    return coerce_implicit(value, target_type)


def contains_struct_value(value: AetherValue) -> bool:
    if isinstance(value.value, ClassInstance):
        return False
    if isinstance(value.value, StructInstance):
        return True
    if isinstance(value.value, AetherValue):
        return contains_struct_value(value.value)
    if isinstance(value.value, (list, tuple)):
        return any(isinstance(element, AetherValue) and contains_struct_value(element) for element in value.value)
    if isinstance(value.type_name, NullableType):
        nullable = value.value
        return (
            isinstance(nullable, NullableValue)
            and nullable.has_value
            and contains_struct_value(AetherValue(value.type_name.base_type, nullable.value))
        )
    return False


def copy_value(value: AetherValue) -> AetherValue:
    if isinstance(value.value, ClassInstance):
        return value
    if is_mutable_reference_type(value.type_name):
        if isinstance(value.type_name, (ArrayType, ListType)):
            from .collection_value import copy_init_value

            return copy_init_value(value)
        return value
    if value.type_name == "string" and isinstance(value.value, StringValue):
        value.value.retain()
        return value
    if isinstance(value.value, StructInstance):
        return AetherValue(
            value.type_name,
            StructInstance(
                value.value.type_name,
                {name: copy_value(field_value) for name, field_value in value.value.fields.items()},
                value.value.field_order,
            ),
        )
    if isinstance(value.type_name, NullableType):
        nullable = value.value
        if not isinstance(nullable, NullableValue):
            raise AetherTypeError("Invalid internal nullable value.")
        if not nullable.has_value:
            return value
        copied = copy_value(AetherValue(value.type_name.base_type, nullable.value))
        return AetherValue(value.type_name, NullableValue(True, copied.value))
    if isinstance(value.type_name, TupleType):
        return AetherValue(value.type_name, tuple(copy_value(element) for element in value.value))
    return value


def coerce_tuple_value(value: AetherValue, target_type: TupleType) -> AetherValue:
    if not isinstance(value.type_name, TupleType):
        raise AetherTypeError(
            f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'."
        )
    if len(value.type_name.element_types) != len(target_type.element_types):
        raise AetherTypeError("Tuple return type arity mismatch.")
    return AetherValue(
        target_type,
        tuple(
            coerce_implicit(element, element_type)
            for element, element_type in zip(value.value, target_type.element_types)
        ),
    )


def _runtime_value_matches_type(value: AetherValue, target_type: AetherType) -> bool:
    if isinstance(target_type, ArrayType):
        return isinstance(value.type_name, ArrayType) and all(
            _runtime_value_matches_type(element, target_type.element_type)
            for element in value.value
        )
    if isinstance(target_type, ListType):
        return isinstance(value.type_name, ListType) and all(
            _runtime_value_matches_type(element, target_type.element_type)
            for element in value.value
        )
    if isinstance(target_type, VectorType):
        return isinstance(value.type_name, VectorType) and all(
            _runtime_value_matches_type(element, target_type.element_type)
            for element in value.value
        )
    if isinstance(target_type, TransposeVectorType):
        return isinstance(value.type_name, TransposeVectorType) and _runtime_value_matches_type(
            value.value,
            VectorType(target_type.element_type, target_type.length),
        )
    if isinstance(target_type, MatrixType):
        row_type = ArrayType(target_type.element_type)
        return isinstance(value.type_name, MatrixType) and all(
            _runtime_value_matches_type(row, row_type)
            for row in value.value
        )
    return value.type_name == target_type


def coerce_list_value(value: AetherValue, target_type: ListType) -> AetherValue:
    if not isinstance(value.type_name, ListType):
        raise AetherTypeError(
            f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'."
        )
    if value.type_name == target_type and _runtime_value_matches_type(value, target_type):
        return value
    if not can_implicitly_convert(value.type_name, target_type):
        raise AetherTypeError(
            f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'. "
            f"Use {type_to_string(target_type)}(...) for explicit conversion."
        )
    return AetherValue(
        target_type,
        [coerce_implicit(element, target_type.element_type) for element in value.value],
    )


def coerce_vector_value(value: AetherValue, target_type: VectorType) -> AetherValue:
    if isinstance(value.type_name, VectorType):
        source_type = value.type_name
        if not can_implicitly_convert(source_type, target_type):
            raise AetherTypeError(
                f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'. "
                f"Use {type_to_string(target_type)}(...) for explicit conversion."
            )
        if source_type.element_type == target_type.element_type and _runtime_value_matches_type(value, source_type):
            return value
        return AetherValue(
            VectorType(target_type.element_type, len(value.value), value.type_name.orientation),
            [coerce_implicit(element, target_type.element_type) for element in value.value],
        )
    if isinstance(value.type_name, MatrixType):
        if not can_implicitly_convert(value.type_name, target_type):
            raise AetherTypeError(
                f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'. "
                f"Use {type_to_string(target_type)}(...) for explicit conversion."
            )
        return AetherValue(
            VectorType(target_type.element_type, len(_matrix_vector_elements(value)), target_type.orientation),
            [coerce_implicit(element, target_type.element_type) for element in _matrix_vector_elements(value)],
        )
    raise AetherTypeError(
        f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'."
    )


def coerce_transpose_vector_value(value: AetherValue, target_type: TransposeVectorType) -> AetherValue:
    if not isinstance(value.type_name, TransposeVectorType):
        raise AetherTypeError(
            f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'."
        )
    vector = coerce_vector_value(value.value, VectorType(target_type.element_type, target_type.length))
    return AetherValue(TransposeVectorType(target_type.element_type, len(vector.value)), vector)


def coerce_matrix_value(value: AetherValue, target_type: MatrixType) -> AetherValue:
    if not isinstance(value.type_name, MatrixType):
        raise AetherTypeError(
            f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'."
        )
    source_type = value.type_name
    rows = source_type.rows if source_type.rows is not None else len(value.value)
    cols = source_type.cols
    if cols is None:
        cols = len(value.value[0].value) if value.value else 0
    source_type = MatrixType(source_type.element_type, rows, cols, source_type.vector)
    check_type = _normalized_vector_type(source_type) if target_type.vector else source_type
    if not can_implicitly_convert(check_type, target_type):
        raise AetherTypeError(
            f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'. "
            f"Use {type_to_string(target_type)}(...) for explicit conversion."
        )
    if source_type.element_type == target_type.element_type and _runtime_value_matches_type(value, source_type):
        return value
    row_type = ArrayType(target_type.element_type)
    if target_type.vector:
        vector_elements = _matrix_vector_elements(value)
        coerced_vector_rows = [
            coerce_array_literal_value(AetherValue(ArrayType(source_type.element_type), [element]), row_type)
            for element in vector_elements
        ]
        concrete_type = MatrixType(target_type.element_type, len(coerced_vector_rows), 1, vector=True)
        return AetherValue(concrete_type, coerced_vector_rows)
    coerced_rows: list[AetherValue] = []
    for row in value.value:
        coerced_rows.append(coerce_array_literal_value(row, row_type))
    concrete_type = MatrixType(target_type.element_type, rows, cols, target_type.vector)
    return AetherValue(concrete_type, coerced_rows)


def coerce_array_literal_value(value: AetherValue, target_type: AetherType) -> AetherValue:
    if not isinstance(target_type, ArrayType):
        return coerce_implicit(value, target_type)
    if not isinstance(value.type_name, ArrayType):
        raise AetherTypeError(
            f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'."
        )
    if value.type_name == target_type and _runtime_value_matches_type(value, target_type):
        return value
    coerced_elements: list[AetherValue] = []
    for element in value.value:
        target_element_type = target_type.element_type
        if isinstance(target_element_type, ArrayType):
            coerced_elements.append(coerce_array_literal_value(element, target_element_type))
            continue
        if not isinstance(element.type_name, ArrayType):
            if can_implicitly_convert(element.type_name, target_element_type):
                coerced_elements.append(coerce_implicit(element, target_element_type))
                continue
            if target_element_type == "float" and element.type_name == "double":
                coerced_elements.append(AetherValue("float", float(element.value)))
                continue
        raise AetherTypeError(
            f"Cannot implicitly convert '{type_to_string(element.type_name)}' to '{type_to_string(target_element_type)}'. "
            f"Use {type_to_string(target_element_type)}(...) for explicit conversion."
        )
    return AetherValue(target_type, coerced_elements)


def explicit_cast(target_type: str, value: AetherValue) -> AetherValue:
    if target_type not in TYPE_NAMES:
        raise AetherTypeError(f"Unknown type '{target_type}'.")
    if target_type == "boolean" and value.type_name != "boolean":
        raise AetherTypeError(f"Cannot explicitly convert '{value.type_name}' to 'boolean' yet.")
    if target_type in REAL_NUMERIC_TYPES and (value.type_name not in REAL_NUMERIC_TYPES):
        raise AetherTypeError(f"Cannot explicitly convert '{value.type_name}' to '{target_type}'.")
    if target_type == "complex" and value.type_name not in NUMERIC_TYPES:
        raise AetherTypeError(f"Cannot explicitly convert '{value.type_name}' to 'complex'.")
    if target_type != "string" and value.type_name == "string":
        raise AetherTypeError(f"Cannot explicitly convert 'string' to '{target_type}'.")
    if target_type == "string":
        return AetherValue("string", default_text(value))
    if target_type == "boolean":
        return value
    return AetherValue(target_type, _coerce_python_value(value.value, target_type))


def promote_numeric(left_type: str, right_type: str, operator: str) -> str:
    if left_type not in NUMERIC_TYPES or right_type not in NUMERIC_TYPES:
        raise AetherTypeError(f"Operator '{operator}' requires numeric operands.")
    if "complex" in {left_type, right_type}:
        return "complex"
    if operator == "/":
        if "double" in {left_type, right_type}:
            return "double"
        if "float" in {left_type, right_type}:
            return "float"
        return "double"
    if "double" in {left_type, right_type}:
        return "double"
    if "float" in {left_type, right_type}:
        return "float"
    return "int"


def _coerce_python_value(value: object, target_type: AetherType) -> object:
    if isinstance(target_type, (ArrayType, ListType, MatrixType, VectorType, TransposeVectorType)):
        raise AetherTypeError(f"Cannot coerce scalar value to '{target_type}'.")
    if target_type == "int":
        return trunc(value)  # type: ignore[arg-type]
    if target_type in {"float", "double"}:
        return float(value)  # type: ignore[arg-type]
    if target_type == "complex":
        return complex(value)  # type: ignore[arg-type]
    if target_type == "string":
        return str(value)
    if target_type == "boolean":
        return bool(value)
    raise AetherTypeError(f"Unknown type '{target_type}'.")


def _normalized_vector_type(type_name: MatrixType) -> MatrixType:
    if type_name.rows is None or type_name.cols is None:
        return MatrixType(type_name.element_type, vector=True)
    if type_name.rows <= 0 or type_name.cols <= 0 or (type_name.rows > 1 and type_name.cols > 1):
        return type_name
    length = type_name.cols if type_name.rows == 1 else type_name.rows
    return MatrixType(type_name.element_type, length, 1, vector=True)


def _matrix_vector_length(type_name: MatrixType) -> int | None:
    if type_name.rows is None or type_name.cols is None:
        return None
    if type_name.rows == 1:
        return type_name.cols
    if type_name.cols == 1:
        return type_name.rows
    return None


def _matrix_vector_elements(value: AetherValue) -> list[AetherValue]:
    if not isinstance(value.type_name, MatrixType):
        raise AetherTypeError(f"Expected matrix type, got '{type_to_string(value.type_name)}'.")
    rows = value.value
    if not rows:
        return []
    if len(rows) == 1:
        return list(rows[0].value)
    if len(rows[0].value) == 1:
        return [row.value[0] for row in rows]
    raise AetherTypeError(
        f"Cannot implicitly convert '{type_to_string(value.type_name)}' to 'Vector<{value.type_name.element_type}>'."
    )
