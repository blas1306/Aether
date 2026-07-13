from __future__ import annotations


VECTOR_INDEX_BASE = 1
MATRIX_INDEX_BASE = 1

VECTOR_INDEX_OUT_OF_BOUNDS = "Aether panic: Vector index out of bounds"
MATRIX_INDEX_OUT_OF_BOUNDS = "Aether panic: Matrix index out of bounds"


def checked_vector_offset(index: int, length: int) -> int:
    """Translate a public 1-based vector index to a checked flat offset."""
    offset = index - VECTOR_INDEX_BASE
    if offset < 0 or offset >= length:
        raise IndexError(VECTOR_INDEX_OUT_OF_BOUNDS)
    return offset


def checked_matrix_offset(
    row: int,
    column: int,
    element_count: int,
    columns: int,
) -> int:
    """Validate both public coordinates before computing the flat offset."""
    if columns <= 0 or element_count < 0 or element_count % columns != 0:
        raise ValueError("invalid internal Matrix shape")
    rows = element_count // columns
    row_offset = row - MATRIX_INDEX_BASE
    column_offset = column - MATRIX_INDEX_BASE
    if (
        row_offset < 0
        or row_offset >= rows
        or column_offset < 0
        or column_offset >= columns
    ):
        raise IndexError(MATRIX_INDEX_OUT_OF_BOUNDS)
    return row_offset * columns + column_offset
