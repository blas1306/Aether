from __future__ import annotations

from .types import AetherRange, AetherValue, ArrayType, MatrixType, RangeType


def format_value(value: AetherValue) -> str:
    if isinstance(value.type_name, MatrixType):
        return format_matrix(value)
    if isinstance(value.type_name, ArrayType):
        return format_array(value)
    if isinstance(value.type_name, RangeType):
        return format_range(value)
    return format_scalar(value)


def format_matrix(value: AetherValue) -> str:
    if value.type_name.vector:
        return "[" + ", ".join(format_matrix_element(element) for element in _vector_elements(value)) + "]"
    rows = _matrix_rows(value)
    if len(rows) == 1 and len(rows[0]) == 1:
        return format_matrix_element(rows[0][0])
    if len(rows) == 1:
        return "[" + " ".join(format_matrix_element(element) for element in rows[0]) + "]"
    rendered_rows = [" ".join(format_matrix_element(element) for element in row) for row in rows]
    return "[" + "; ".join(rendered_rows) + "]"


def format_array(value: AetherValue) -> str:
    return "[" + ", ".join(format_array_element(element) for element in value.value) + "]"


def format_range(value: AetherValue) -> str:
    range_value = value.value
    if not isinstance(range_value, AetherRange):
        return str(range_value)
    if range_value.step == 1:
        return f"{range_value.start}:{range_value.end}"
    return f"{range_value.start}:{range_value.step}:{range_value.end}"


def format_scalar(value: AetherValue) -> str:
    if value.type_name == "boolean":
        return "true" if value.value else "false"
    return str(value.value)


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
