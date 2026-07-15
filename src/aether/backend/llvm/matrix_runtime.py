from __future__ import annotations

from dataclasses import dataclass

from aether.vector_matrix_safety import MATRIX_INDEX_OUT_OF_BOUNDS

from .array_runtime import LLVMArrayRuntime
from .runtime_common import (
    LLVMRuntimeCommon,
    aggregate_equal_helper,
    aggregate_helper_suffix,
    aggregate_print_helper,
)


@dataclass(frozen=True)
class LLVMMatrixRuntime:
    """Emit indexing, equality, and print helpers for Matrix values."""

    uses_indexing: bool
    equality_types: frozenset[object]
    print_types: frozenset[object]

    def append(self, sections: list[str], common: LLVMRuntimeCommon) -> None:
        self._append_equality(sections, common)
        self._append_print(sections)
        if not self.uses_indexing:
            return
        size = len(MATRIX_INDEX_OUT_OF_BOUNDS) + 1
        sections.append(
            f'@.aether.matrix.index.bounds = private unnamed_addr constant '
            f'[{size} x i8] c"{MATRIX_INDEX_OUT_OF_BOUNDS}\\00"'
        )
        sections.append(
            LLVMRuntimeCommon.panic_helper(
                "aether_matrix_index_bounds_panic",
                ".aether.matrix.index.bounds",
                size,
            )
        )
        sections.append(
            "\n".join(
                [
                    "define private i64 @aether_matrix_check_index(ptr %matrix, i64 %row, i64 %column, i64 %columns) {",
                    "entry:",
                    LLVMArrayRuntime.length_pointer_line("%len_field", "%matrix", indent="  "),
                    "  %length = load i64, ptr %len_field",
                    "  %rows = udiv i64 %length, %columns",
                    "  %row_at_least_one = icmp sge i64 %row, 1",
                    "  %row_within_bounds = icmp ule i64 %row, %rows",
                    "  %row_valid = and i1 %row_at_least_one, %row_within_bounds",
                    "  %column_at_least_one = icmp sge i64 %column, 1",
                    "  %column_within_bounds = icmp ule i64 %column, %columns",
                    "  %column_valid = and i1 %column_at_least_one, %column_within_bounds",
                    "  %valid = and i1 %row_valid, %column_valid",
                    "  br i1 %valid, label %ready, label %bounds_panic",
                    "bounds_panic:",
                    "  call void @aether_matrix_index_bounds_panic()",
                    "  unreachable",
                    "ready:",
                    "  %row_offset = sub i64 %row, 1",
                    "  %column_offset = sub i64 %column, 1",
                    "  %row_start = mul i64 %row_offset, %columns",
                    "  %offset = add i64 %row_start, %column_offset",
                    "  ret i64 %offset",
                    "}",
                ]
            )
        )

    def _append_equality(self, sections: list[str], common: LLVMRuntimeCommon) -> None:
        for element_type in sorted(self.equality_types, key=aggregate_helper_suffix):
            sections.append(aggregate_equal_helper("matrix", element_type))

    def _append_print(self, sections: list[str]) -> None:
        if not self.print_types:
            return
        sections.extend(
            [
                '@.aether.matrix.open = private unnamed_addr constant [2 x i8] c"[\\00"',
                '@.aether.matrix.close = private unnamed_addr constant [2 x i8] c"]\\00"',
                '@.aether.matrix.space = private unnamed_addr constant [2 x i8] c" \\00"',
                '@.aether.matrix.row_sep = private unnamed_addr constant [3 x i8] c"; \\00"',
                '@.aether.matrix.quote = private unnamed_addr constant [2 x i8] c"\\22\\00"',
            ]
        )
        for element_type in sorted(self.print_types, key=aggregate_helper_suffix):
            sections.append(aggregate_print_helper("matrix", element_type, matrix=True))
