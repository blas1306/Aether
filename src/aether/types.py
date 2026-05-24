from __future__ import annotations

from dataclasses import dataclass
from math import trunc
from typing import Any

from .errors import AetherTypeError


TYPE_NAMES = {"int", "float", "double", "string", "boolean"}
NUMERIC_TYPES = {"int", "float", "double"}
WIDENING: dict[str, set[str]] = {
    "int": {"float", "double"},
    "float": {"double"},
    "double": set(),
    "string": set(),
    "boolean": set(),
}


@dataclass(frozen=True, eq=False)
class ArrayType:
    element_type: AetherType

    def __post_init__(self) -> None:
        if not is_known_type(self.element_type):
            raise AetherTypeError(f"Unknown array element type '{type_to_string(self.element_type)}'.")

    def __str__(self) -> str:
        return f"{type_to_string(self.element_type)}[]"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ArrayType):
            return self.element_type == other.element_type
        if isinstance(other, str):
            return str(self) == other
        return False

    def __hash__(self) -> int:
        return hash(str(self))


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

    def __post_init__(self) -> None:
        if self.element_type not in TYPE_NAMES:
            raise AetherTypeError(f"Unknown vector element type '{self.element_type}'.")
        if self.length is not None and self.length < 0:
            raise AetherTypeError("Vector length cannot be negative.")

    def __str__(self) -> str:
        return f"Vector<{self.element_type}>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, VectorType):
            return self.element_type == other.element_type and self.length == other.length
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


AetherType = str | ArrayType | MatrixType | VectorType | TransposeVectorType | RangeType


@dataclass(frozen=True)
class AetherValue:
    type_name: AetherType
    value: Any


@dataclass(frozen=True)
class AetherRange:
    start: int
    step: int
    end: int

    def __iter__(self):
        if self.step == 0:
            raise AetherTypeError("Range step cannot be zero.")
        current = self.start
        if self.step > 0:
            while current <= self.end:
                yield AetherValue("int", current)
                current += self.step
            return
        while current >= self.end:
            yield AetherValue("int", current)
            current += self.step


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
    if isinstance(value, str):
        return "string"
    raise AetherTypeError(f"Cannot infer Aether type for value {value!r}.")


def type_to_string(type_name: AetherType) -> str:
    return str(type_name)


def is_known_type(type_name: AetherType) -> bool:
    if isinstance(type_name, ArrayType):
        return is_known_type(type_name.element_type)
    if isinstance(type_name, MatrixType):
        return type_name.element_type in TYPE_NAMES
    if isinstance(type_name, (VectorType, TransposeVectorType)):
        return type_name.element_type in TYPE_NAMES
    if isinstance(type_name, RangeType):
        return type_name.element_type == "int"
    return type_name in TYPE_NAMES


def is_array_type(type_name: AetherType) -> bool:
    return isinstance(type_name, ArrayType)


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
    return isinstance(type_name, (ArrayType, MatrixType, VectorType, TransposeVectorType))


def array_element_type(type_name: AetherType) -> AetherType:
    if not isinstance(type_name, ArrayType):
        raise AetherTypeError(f"Expected array type, got '{type_to_string(type_name)}'.")
    return type_name.element_type


def matrix_row_type(type_name: AetherType) -> ArrayType:
    if not isinstance(type_name, MatrixType):
        raise AetherTypeError(f"Expected matrix type, got '{type_to_string(type_name)}'.")
    return ArrayType(type_name.element_type)


def can_implicitly_convert(from_type: AetherType, to_type: AetherType) -> bool:
    if isinstance(from_type, RangeType) or isinstance(to_type, RangeType):
        return from_type == to_type
    if isinstance(from_type, TransposeVectorType) or isinstance(to_type, TransposeVectorType):
        return from_type == to_type
    if isinstance(from_type, VectorType) or isinstance(to_type, VectorType):
        if isinstance(from_type, VectorType) and isinstance(to_type, VectorType):
            if not can_implicitly_convert(from_type.element_type, to_type.element_type):
                return False
            if to_type.length is not None and from_type.length is not None and to_type.length != from_type.length:
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
    if not is_known_type(target_type):
        raise AetherTypeError(f"Unknown type '{type_to_string(target_type)}'.")
    if value.type_name == target_type:
        return value
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


def coerce_vector_value(value: AetherValue, target_type: VectorType) -> AetherValue:
    if isinstance(value.type_name, VectorType):
        source_type = value.type_name
        if not can_implicitly_convert(source_type, target_type):
            raise AetherTypeError(
                f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'. "
                f"Use {type_to_string(target_type)}(...) for explicit conversion."
            )
        return AetherValue(
            VectorType(target_type.element_type, len(value.value)),
            [coerce_implicit(element, target_type.element_type) for element in value.value],
        )
    if isinstance(value.type_name, MatrixType):
        if not can_implicitly_convert(value.type_name, target_type):
            raise AetherTypeError(
                f"Cannot implicitly convert '{type_to_string(value.type_name)}' to '{type_to_string(target_type)}'. "
                f"Use {type_to_string(target_type)}(...) for explicit conversion."
            )
        return AetherValue(
            VectorType(target_type.element_type, len(_matrix_vector_elements(value))),
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
    if target_type in {"int", "float", "double"} and value.type_name not in NUMERIC_TYPES:
        raise AetherTypeError(f"Cannot explicitly convert '{value.type_name}' to '{target_type}'.")
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
    if isinstance(target_type, (ArrayType, MatrixType, VectorType, TransposeVectorType)):
        raise AetherTypeError(f"Cannot coerce scalar value to '{target_type}'.")
    if target_type == "int":
        return trunc(value)  # type: ignore[arg-type]
    if target_type in {"float", "double"}:
        return float(value)  # type: ignore[arg-type]
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
