from __future__ import annotations

import math

from .types import AetherExceptionValue, AetherRange, AetherValue, ArrayType, ClassInstance, EnumValue, ListType, MatrixType, NullableType, NullableValue, RangeType, StructInstance, TransposeVectorType, TupleType, VectorType


def format_value(value: AetherValue) -> str:
    if isinstance(value.type_name, NullableType):
        nullable = value.value
        if not isinstance(nullable, NullableValue) or not nullable.has_value:
            return "null"
        return format_value(AetherValue(value.type_name.base_type, nullable.value))
    if isinstance(value.type_name, VectorType):
        return format_vector(value)
    if isinstance(value.type_name, TransposeVectorType):
        return format_transpose_vector(value)
    if isinstance(value.type_name, MatrixType):
        return format_matrix(value)
    if isinstance(value.type_name, ListType):
        return format_list(value)
    if isinstance(value.type_name, ArrayType):
        return format_array(value)
    if isinstance(value.type_name, RangeType):
        return format_range(value)
    if isinstance(value.type_name, TupleType):
        return format_tuple(value)
    if isinstance(value.value, AetherExceptionValue):
        return format_exception(value.value)
    if isinstance(value.value, (StructInstance, ClassInstance)):
        return format_struct(value.value)
    if isinstance(value.value, EnumValue):
        return format_enum(value.value)
    return format_scalar(value)


def format_vector(value: AetherValue) -> str:
    if value.type_name.orientation == "column":
        return "[" + "; ".join(format_matrix_element(element) for element in value.value) + "]"
    return "[" + " ".join(format_matrix_element(element) for element in value.value) + "]"


def format_transpose_vector(value: AetherValue) -> str:
    return "[" + " ".join(format_matrix_element(element) for element in value.value.value) + "]"


def format_matrix(value: AetherValue) -> str:
    if value.type_name.vector:
        rows = _matrix_rows(value)
        if len(rows) > 1 and all(len(row) == 1 for row in rows):
            return "[" + "; ".join(format_matrix_element(row[0]) for row in rows) + "]"
        return "[" + " ".join(format_matrix_element(element) for element in _vector_elements(value)) + "]"
    rows = _matrix_rows(value)
    if len(rows) == 1 and len(rows[0]) == 1:
        return format_matrix_element(rows[0][0])
    if len(rows) == 1:
        return "[" + " ".join(format_matrix_element(element) for element in rows[0]) + "]"
    rendered_rows = [" ".join(format_matrix_element(element) for element in row) for row in rows]
    return "[" + "; ".join(rendered_rows) + "]"


def format_array(value: AetherValue) -> str:
    return "{" + ", ".join(format_array_element(element) for element in value.value) + "}"


def format_list(value: AetherValue) -> str:
    return "{" + ", ".join(format_array_element(element) for element in value.value) + "}"


def format_tuple(value: AetherValue) -> str:
    return "(" + ", ".join(format_array_element(element) for element in value.value) + ")"


def format_range(value: AetherValue) -> str:
    range_value = value.value
    if not isinstance(range_value, AetherRange):
        return str(range_value)
    if range_value.step == 1:
        return f"{range_value.start}:{range_value.end}"
    return f"{range_value.start}:{range_value.step}:{range_value.end}"


def format_struct(value: StructInstance | ClassInstance) -> str:
    fields = ", ".join(
        f"{name}={format_value(value.fields[name])}"
        for name in value.field_order
    )
    return f"{value.type_name}({fields})"


def format_exception(value: AetherExceptionValue) -> str:
    return f'{value.kind}("{_escape_string(value.message)}")'


def format_enum(value: EnumValue) -> str:
    return f"{value.enum_name}.{value.variant_name}"


def format_scalar(value: AetherValue) -> str:
    if value.value is None:
        return "null"
    if value.type_name == "boolean":
        return "true" if value.value else "false"
    if value.type_name == "double":
        return format_public_double(float(value.value))
    if value.type_name == "complex":
        return _format_complex(value.value)
    return str(value.value)


def format_public_double(value: float) -> str:
    """Format binary64 for public output, separately from the ALPT1 codec."""

    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "-Infinity" if value < 0.0 else "Infinity"
    rendered = format(value, ".15g")
    if not any(marker in rendered for marker in (".", "e", "E")):
        rendered += ".0"
    return rendered


def format_matrix_element(value: AetherValue) -> str:
    if value.type_name == "string":
        return '"' + _escape_string(value.value) + '"'
    return format_value(value)


def format_array_element(value: AetherValue) -> str:
    if value.type_name == "string":
        return '"' + _escape_string(value.value) + '"'
    return format_value(value)


def _matrix_rows(value: AetherValue) -> list[list[AetherValue]]:
    return [list(row.value) for row in value.value]


def _vector_elements(value: AetherValue) -> list[AetherValue]:
    rows = _matrix_rows(value)
    if not rows:
        return []
    if len(rows) == 1:
        return rows[0]
    if len(rows[0]) == 1:
        return [row[0] for row in rows]
    return [element for row in rows for element in row]


def _escape_string(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def _format_complex(value: object) -> str:
    complex_value = complex(value)
    real = _clean_zero(complex_value.real)
    imag = _clean_zero(complex_value.imag)
    if imag == 0:
        return _format_complex_component(real)
    imag_abs = abs(imag)
    imag_text = "im" if imag_abs == 1 else f"{_format_complex_component(imag_abs)}im"
    if real == 0:
        return imag_text if imag > 0 else f"-{imag_text}"
    sign = "+" if imag > 0 else "-"
    return f"{_format_complex_component(real)} {sign} {imag_text}"


def _clean_zero(value: float) -> float:
    return 0.0 if abs(value) < 1e-12 else value


def _format_complex_component(value: float) -> str:
    value = float(value)
    if value.is_integer():
        return f"{value:.1f}"
    return f"{value:.12g}"
