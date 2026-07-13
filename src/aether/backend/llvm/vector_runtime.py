from __future__ import annotations

from dataclasses import dataclass

from aether.vector_matrix_safety import VECTOR_INDEX_OUT_OF_BOUNDS

from .array_runtime import LLVMArrayRuntime
from .runtime_common import (
    LLVMRuntimeCommon,
    aggregate_equal_helper,
    aggregate_helper_suffix,
    aggregate_print_helper,
)


@dataclass(frozen=True)
class LLVMVectorRuntime:
    """Emit indexing, equality, and print helpers for Vector values."""

    uses_indexing: bool
    equality_types: frozenset[object]
    print_types: frozenset[object]

    def append(self, sections: list[str], common: LLVMRuntimeCommon) -> None:
        self._append_equality(sections, common)
        self._append_print(sections)
        if not self.uses_indexing:
            return
        size = len(VECTOR_INDEX_OUT_OF_BOUNDS) + 1
        sections.append(
            f'@.aether.vector.index.bounds = private unnamed_addr constant '
            f'[{size} x i8] c"{VECTOR_INDEX_OUT_OF_BOUNDS}\\00"'
        )
        sections.append(
            LLVMRuntimeCommon.panic_helper(
                "aether_vector_index_bounds_panic",
                ".aether.vector.index.bounds",
                size,
            )
        )
        sections.append(
            "\n".join(
                [
                    "define private i64 @aether_vector_check_index(ptr %vector, i64 %index) {",
                    "entry:",
                    LLVMArrayRuntime.length_pointer_line("%len_field", "%vector", indent="  "),
                    "  %length = load i64, ptr %len_field",
                    "  %at_least_one = icmp sge i64 %index, 1",
                    "  %within_length = icmp ule i64 %index, %length",
                    "  %valid = and i1 %at_least_one, %within_length",
                    "  br i1 %valid, label %ready, label %bounds_panic",
                    "bounds_panic:",
                    "  call void @aether_vector_index_bounds_panic()",
                    "  unreachable",
                    "ready:",
                    "  %offset = sub i64 %index, 1",
                    "  ret i64 %offset",
                    "}",
                ]
            )
        )

    def _append_equality(self, sections: list[str], common: LLVMRuntimeCommon) -> None:
        for element_type in sorted(self.equality_types, key=aggregate_helper_suffix):
            if aggregate_helper_suffix(element_type) == "string":
                common.declare(sections, "declare i32 @strcmp(ptr, ptr)")
            sections.append(aggregate_equal_helper("vector", element_type))

    def _append_print(self, sections: list[str]) -> None:
        if not self.print_types:
            return
        sections.extend(
            [
                '@.aether.vector.open = private unnamed_addr constant [2 x i8] c"[\\00"',
                '@.aether.vector.close = private unnamed_addr constant [2 x i8] c"]\\00"',
                '@.aether.vector.space = private unnamed_addr constant [2 x i8] c" \\00"',
                '@.aether.vector.row_sep = private unnamed_addr constant [3 x i8] c"; \\00"',
                '@.aether.vector.quote = private unnamed_addr constant [2 x i8] c"\\22\\00"',
            ]
        )
        for element_type in sorted(self.print_types, key=aggregate_helper_suffix):
            sections.append(aggregate_print_helper("vector", element_type, matrix=False))
