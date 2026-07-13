from __future__ import annotations

from dataclasses import dataclass

from .runtime_common import LLVMRuntimeCommon


@dataclass(frozen=True)
class LLVMArrayRuntime:
    """Emit helpers owned by the ``%AetherArray`` layout."""

    uses_type: bool
    uses_allocation: bool
    uses_indexing: bool
    uses_slicing: bool
    uses_length_conversion: bool

    STRUCT_TYPE = "%AetherArray"

    @classmethod
    def field_pointer_line(
        cls, result: str, array: str, field_index: int, *, indent: str = ""
    ) -> str:
        return (
            f"{indent}{result} = getelementptr {cls.STRUCT_TYPE}, "
            f"ptr {array}, i32 0, i32 {field_index}"
        )

    @classmethod
    def length_pointer_line(cls, result: str, array: str, *, indent: str = "") -> str:
        return cls.field_pointer_line(result, array, 0, indent=indent)

    @classmethod
    def data_pointer_line(cls, result: str, array: str, *, indent: str = "") -> str:
        return cls.field_pointer_line(result, array, 1, indent=indent)

    @staticmethod
    def index64_line(result: str, index: str) -> str:
        return f"{result} = sext i32 {index} to i64"

    def append_type(self, sections: list[str]) -> None:
        if self.uses_type:
            sections.append(f"{self.STRUCT_TYPE} = type {{ i64, ptr }}")

    def append_allocation(self, sections: list[str]) -> None:
        if not self.uses_allocation:
            return
        sections.append(
            "\n".join(
                [
                    "define private ptr @aether_array_new(i64 %element_size, i64 %length) {",
                    "entry:",
                    "  %data_size = call i64 @aether_checked_allocation_bytes(i64 %length, i64 %element_size)",
                    "  %array = call ptr @aether_alloc(i64 16)",
                    self.length_pointer_line("%len_field", "%array", indent="  "),
                    "  store i64 %length, ptr %len_field",
                    "  %data = call ptr @aether_alloc(i64 %data_size)",
                    self.data_pointer_line("%data_field", "%array", indent="  "),
                    "  store ptr %data, ptr %data_field",
                    "  ret ptr %array",
                    "}",
                ]
            )
        )

    def append_length_conversion(self, sections: list[str]) -> None:
        if not self.uses_length_conversion:
            return
        sections.append('@.aether.array.length.int = private unnamed_addr constant [47 x i8] c"Aether panic: Array length does not fit in int\\00"')
        sections.append(
            "\n".join(
                [
                    "define private i32 @aether_array_length_to_int(i64 %length) {",
                    "entry:",
                    "  %nonnegative = icmp sge i64 %length, 0",
                    "  %fits = icmp sle i64 %length, 2147483647",
                    "  %valid = and i1 %nonnegative, %fits",
                    "  br i1 %valid, label %convert, label %panic",
                    "panic:",
                    "  %message = getelementptr [47 x i8], ptr @.aether.array.length.int, i64 0, i64 0",
                    "  call i32 @puts(ptr %message)",
                    "  call void @exit(i32 1)",
                    "  unreachable",
                    "convert:",
                    "  %result = trunc i64 %length to i32",
                    "  ret i32 %result",
                    "}",
                ]
            )
        )

    def append_slicing(self, sections: list[str]) -> None:
        if not self.uses_slicing:
            return
        sections.append('@.aether.array.slice.bounds = private unnamed_addr constant [40 x i8] c"Aether panic: Array slice out of bounds\\00"')
        sections.append(
            LLVMRuntimeCommon.panic_helper(
                "aether_array_slice_bounds_panic", ".aether.array.slice.bounds", 40
            )
        )
        sections.append(
            "\n".join(
                [
                    "define private ptr @aether_array_slice(ptr %source, i32 %start32, i32 %end32, i64 %element_size) {",
                    "entry:",
                    "  %start = sext i32 %start32 to i64",
                    "  %end = sext i32 %end32 to i64",
                    self.length_pointer_line("%source_len_field", "%source", indent="  "),
                    "  %source_length = load i64, ptr %source_len_field",
                    "  %start_nonnegative = icmp sge i64 %start, 0",
                    "  %ordered = icmp sle i64 %start, %end",
                    "  %end_within_length = icmp sle i64 %end, %source_length",
                    "  %start_valid = and i1 %start_nonnegative, %ordered",
                    "  %valid = and i1 %start_valid, %end_within_length",
                    "  br i1 %valid, label %allocate, label %bounds_panic",
                    "bounds_panic:",
                    "  call void @aether_array_slice_bounds_panic()",
                    "  unreachable",
                    "allocate:",
                    "  %slice_length = sub i64 %end, %start",
                    "  %copy_bytes = call i64 @aether_checked_allocation_bytes(i64 %slice_length, i64 %element_size)",
                    "  %slice = call ptr @aether_array_new(i64 %element_size, i64 %slice_length)",
                    "  %has_bytes = icmp ne i64 %copy_bytes, 0",
                    "  br i1 %has_bytes, label %copy_elements, label %done",
                    "copy_elements:",
                    "  %start_bytes = call i64 @aether_checked_allocation_bytes(i64 %start, i64 %element_size)",
                    self.data_pointer_line("%source_data_field", "%source", indent="  "),
                    "  %source_data = load ptr, ptr %source_data_field",
                    "  %copy_start = getelementptr i8, ptr %source_data, i64 %start_bytes",
                    self.data_pointer_line("%slice_data_field", "%slice", indent="  "),
                    "  %slice_data = load ptr, ptr %slice_data_field",
                    "  call void @llvm.memcpy.p0.p0.i64(ptr %slice_data, ptr %copy_start, i64 %copy_bytes, i1 false)",
                    "  br label %done",
                    "done:",
                    "  ret ptr %slice",
                    "}",
                ]
            )
        )

    def append_indexing(self, sections: list[str]) -> None:
        if not self.uses_indexing:
            return
        sections.append('@.aether.array.index.bounds = private unnamed_addr constant [40 x i8] c"Aether panic: Array index out of bounds\\00"')
        sections.append(
            LLVMRuntimeCommon.panic_helper(
                "aether_array_index_bounds_panic", ".aether.array.index.bounds", 40
            )
        )
        sections.append(
            "\n".join(
                [
                    "define private void @aether_array_check_index(ptr %array, i64 %index) {",
                    "entry:",
                    self.length_pointer_line("%len_field", "%array", indent="  "),
                    "  %length = load i64, ptr %len_field",
                    "  %nonnegative = icmp sge i64 %index, 0",
                    "  %within_length = icmp ult i64 %index, %length",
                    "  %valid = and i1 %nonnegative, %within_length",
                    "  br i1 %valid, label %ready, label %bounds_panic",
                    "bounds_panic:",
                    "  call void @aether_array_index_bounds_panic()",
                    "  unreachable",
                    "ready:",
                    "  ret void",
                    "}",
                ]
            )
        )
