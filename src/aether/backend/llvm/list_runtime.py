from __future__ import annotations

from dataclasses import dataclass

from aether.ir.types import (
    ArrayType,
    BoolType,
    DoubleType,
    IntType,
    ListType,
    MatrixType,
    StringType,
    VectorType,
)

from .runtime import sequence_sort_helper, sequence_sort_helper_name
from .types import LLVMBackendError, llvm_type


@dataclass(frozen=True)
class LLVMListRuntime:
    """Generate the LLVM runtime sections required by one emitted module."""

    _uses_array_type: bool
    _uses_array_allocation: bool
    _uses_list_type: bool
    _uses_list_allocation: bool
    _uses_list_copy: bool
    _uses_list_push: bool
    _uses_list_insert: bool
    _uses_list_pop: bool
    _uses_list_remove_at: bool
    _uses_list_reverse: bool
    _uses_list_indexing: bool
    _uses_list_length_conversion: bool
    _sequence_sort_types: frozenset[object]
    _list_contains_types: frozenset[object]
    _list_index_of_types: frozenset[object]

    _ARRAY_STRUCT_TYPE = "%AetherArray"
    _LIST_STRUCT_TYPE = "%AetherList"

    @classmethod
    def _list_field_pointer(
        cls,
        result: str,
        list_value: str,
        field_index: int,
    ) -> str:
        return (
            f"  {result} = getelementptr {cls._LIST_STRUCT_TYPE}, "
            f"ptr {list_value}, i32 0, i32 {field_index}"
        )

    @classmethod
    def _list_length_pointer(cls, result: str, list_value: str) -> str:
        return cls._list_field_pointer(result, list_value, 0)

    @classmethod
    def _list_capacity_pointer(cls, result: str, list_value: str) -> str:
        return cls._list_field_pointer(result, list_value, 1)

    @classmethod
    def _list_data_pointer(cls, result: str, list_value: str) -> str:
        return cls._list_field_pointer(result, list_value, 2)

    @staticmethod
    def _declare(sections: list[str], declaration: str) -> None:
        if declaration not in sections:
            sections.append(declaration)

    def declarations(self) -> list[str]:
        sections: list[str] = []
        uses_list_growth = self._uses_list_push or self._uses_list_insert
        uses_allocation = bool(
            self._uses_array_allocation
            or self._uses_list_allocation
            or uses_list_growth
            or self._sequence_sort_types
        )
        uses_checked_allocation_size = bool(self._uses_list_allocation or self._sequence_sort_types)
        uses_int_conversion = bool(self._uses_list_length_conversion or self._list_index_of_types)
        if self._uses_array_type:
            sections.append(f"{self._ARRAY_STRUCT_TYPE} = type {{ i64, ptr }}")
        if self._uses_list_type:
            sections.append(f"{self._LIST_STRUCT_TYPE} = type {{ i64, i64, ptr }}")
        if uses_allocation or self._uses_list_indexing or self._uses_list_pop or self._uses_list_remove_at or uses_int_conversion:
            self._declare(sections, "declare i32 @puts(ptr)")
            self._declare(sections, "declare void @exit(i32) noreturn")
        if uses_allocation:
            self._declare(sections, "declare noalias ptr @malloc(i64)")
            sections.append('@.aether.oom = private unnamed_addr constant [39 x i8] c"Aether panic: memory allocation failed\\00"')
            sections.append(
                "\n".join(
                    [
                        "define private void @aether_allocation_failure_panic() noreturn {",
                        "entry:",
                        "  %message = getelementptr [39 x i8], ptr @.aether.oom, i64 0, i64 0",
                        "  call i32 @puts(ptr %message)",
                        "  call void @exit(i32 1)",
                        "  unreachable",
                        "}",
                    ]
                )
            )
            sections.append(
                "\n".join(
                    [
                        "define private ptr @aether_alloc(i64 %size) {",
                        "entry:",
                        "  %zero = icmp eq i64 %size, 0",
                        "  br i1 %zero, label %empty, label %allocate",
                        "empty:",
                        "  ret ptr null",
                        "allocate:",
                        "  %mem = call noalias ptr @malloc(i64 %size)",
                        "  %failed = icmp eq ptr %mem, null",
                        "  br i1 %failed, label %panic, label %ok",
                        "panic:",
                        "  call void @aether_allocation_failure_panic()",
                        "  unreachable",
                        "ok:",
                        "  ret ptr %mem",
                        "}",
                    ]
                )
            )
        if uses_checked_allocation_size:
            sections.append('@.aether.allocation.overflow = private unnamed_addr constant [39 x i8] c"Aether panic: allocation size overflow\\00"')
            sections.append(
                "\n".join(
                    [
                        "define private void @aether_allocation_overflow_panic() noreturn {",
                        "entry:",
                        "  %message = getelementptr [39 x i8], ptr @.aether.allocation.overflow, i64 0, i64 0",
                        "  call i32 @puts(ptr %message)",
                        "  call void @exit(i32 1)",
                        "  unreachable",
                        "}",
                    ]
                )
            )
            sections.append(
                "\n".join(
                    [
                        "define private i64 @aether_checked_allocation_bytes(i64 %length, i64 %element_size) {",
                        "entry:",
                        "  %negative_length = icmp slt i64 %length, 0",
                        "  %negative_size = icmp slt i64 %element_size, 0",
                        "  %invalid = or i1 %negative_length, %negative_size",
                        "  br i1 %invalid, label %panic, label %multiply",
                        "panic:",
                        "  call void @aether_allocation_overflow_panic()",
                        "  unreachable",
                        "multiply:",
                        "  %bytes = call i64 @aether_checked_mul_i64(i64 %length, i64 %element_size)",
                        "  ret i64 %bytes",
                        "}",
                    ]
                )
            )
            sections.append(
                "\n".join(
                    [
                        "define private i64 @aether_checked_mul_i64(i64 %left, i64 %right) {",
                        "entry:",
                        "  %pair = call { i64, i1 } @llvm.umul.with.overflow.i64(i64 %left, i64 %right)",
                        "  %result = extractvalue { i64, i1 } %pair, 0",
                        "  %overflow = extractvalue { i64, i1 } %pair, 1",
                        "  br i1 %overflow, label %panic, label %ok",
                        "panic:",
                        "  call void @aether_allocation_overflow_panic()",
                        "  unreachable",
                        "ok:",
                        "  ret i64 %result",
                        "}",
                    ]
                )
            )
        if self._sequence_sort_types or uses_list_growth:
            self._declare(sections, "declare void @free(ptr)")
            self._declare(sections, "declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1 immarg)")
        if self._uses_list_insert or self._uses_list_remove_at:
            self._declare(sections, "declare void @llvm.memmove.p0.p0.i64(ptr, ptr, i64, i1 immarg)")
        if self._uses_array_allocation:
            sections.append(
                "\n".join(
                    [
                        "define private ptr @aether_array_new(i64 %element_size, i64 %length) {",
                        "entry:",
                        "  %array = call ptr @aether_alloc(i64 16)",
                        f"  %len_field = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr %array, i32 0, i32 0",
                        "  store i64 %length, ptr %len_field",
                        "  %data_size = mul i64 %element_size, %length",
                        "  %data = call ptr @aether_alloc(i64 %data_size)",
                        f"  %data_field = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr %array, i32 0, i32 1",
                        "  store ptr %data, ptr %data_field",
                        "  ret ptr %array",
                        "}",
                    ]
                )
            )
        if self._uses_list_allocation:
            sections.append(
                "\n".join(
                    [
                        "define private ptr @aether_list_new(i64 %element_size, i64 %length) {",
                        "entry:",
                        "  %data_size = call i64 @aether_checked_allocation_bytes(i64 %length, i64 %element_size)",
                        "  %list = call ptr @aether_alloc(i64 24)",
                        self._list_length_pointer("%len_field", "%list"),
                        "  store i64 %length, ptr %len_field",
                        self._list_capacity_pointer("%cap_field", "%list"),
                        "  store i64 %length, ptr %cap_field",
                        "  %data = call ptr @aether_alloc(i64 %data_size)",
                        self._list_data_pointer("%data_field", "%list"),
                        "  store ptr %data, ptr %data_field",
                        "  ret ptr %list",
                        "}",
                    ]
                )
            )
        if self._uses_list_copy:
            if not self._sequence_sort_types and not uses_list_growth:
                self._declare(sections, "declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1 immarg)")
            sections.append(
                "\n".join(
                    [
                        "define private ptr @aether_list_copy(ptr %source, i64 %element_size) {",
                        "entry:",
                        self._list_length_pointer("%source_len_field", "%source"),
                        "  %length = load i64, ptr %source_len_field",
                        "  %bytes = call i64 @aether_checked_allocation_bytes(i64 %length, i64 %element_size)",
                        "  %copy = call ptr @aether_list_new(i64 %element_size, i64 %length)",
                        self._list_data_pointer("%source_data_field", "%source"),
                        "  %source_data = load ptr, ptr %source_data_field",
                        self._list_data_pointer("%copy_data_field", "%copy"),
                        "  %copy_data = load ptr, ptr %copy_data_field",
                        "  %has_bytes = icmp ne i64 %bytes, 0",
                        "  br i1 %has_bytes, label %copy_elements, label %done",
                        "copy_elements:",
                        "  call void @llvm.memcpy.p0.p0.i64(ptr %copy_data, ptr %source_data, i64 %bytes, i1 false)",
                        "  br label %done",
                        "done:",
                        "  ret ptr %copy",
                        "}",
                    ]
                )
            )
        if self._uses_list_length_conversion:
            sections.append('@.aether.list.length.int = private unnamed_addr constant [46 x i8] c"Aether panic: List length does not fit in int\\00"')
            sections.append(
                "\n".join(
                    [
                        "define private i32 @aether_list_length_to_int(i64 %length) {",
                        "entry:",
                        "  %nonnegative = icmp sge i64 %length, 0",
                        "  %fits = icmp sle i64 %length, 2147483647",
                        "  %valid = and i1 %nonnegative, %fits",
                        "  br i1 %valid, label %convert, label %panic",
                        "panic:",
                        "  %message = getelementptr [46 x i8], ptr @.aether.list.length.int, i64 0, i64 0",
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
        if self._list_index_of_types:
            sections.append('@.aether.list.index.int = private unnamed_addr constant [45 x i8] c"Aether panic: List index does not fit in int\\00"')
            sections.append(
                "\n".join(
                    [
                        "define private i32 @aether_list_index_to_int(i64 %index) {",
                        "entry:",
                        "  %not_below_sentinel = icmp sge i64 %index, -1",
                        "  %fits = icmp sle i64 %index, 2147483647",
                        "  %valid = and i1 %not_below_sentinel, %fits",
                        "  br i1 %valid, label %convert, label %panic",
                        "panic:",
                        "  %message = getelementptr [45 x i8], ptr @.aether.list.index.int, i64 0, i64 0",
                        "  call i32 @puts(ptr %message)",
                        "  call void @exit(i32 1)",
                        "  unreachable",
                        "convert:",
                        "  %result = trunc i64 %index to i32",
                        "  ret i32 %result",
                        "}",
                    ]
                )
            )
        if self._uses_list_indexing:
            sections.append('@.aether.list.index.bounds = private unnamed_addr constant [39 x i8] c"Aether panic: List index out of bounds\\00"')
            sections.append(
                "\n".join(
                    [
                        "define private void @aether_list_index_bounds_panic() noreturn {",
                        "entry:",
                        "  %message = getelementptr [39 x i8], ptr @.aether.list.index.bounds, i64 0, i64 0",
                        "  call i32 @puts(ptr %message)",
                        "  call void @exit(i32 1)",
                        "  unreachable",
                        "}",
                    ]
                )
            )
            sections.append(
                "\n".join(
                    [
                        "define private void @aether_list_check_index(ptr %list, i64 %index) {",
                        "entry:",
                        self._list_length_pointer("%len_field", "%list"),
                        "  %length = load i64, ptr %len_field",
                        "  %nonnegative = icmp sge i64 %index, 0",
                        "  %within_length = icmp ult i64 %index, %length",
                        "  %valid = and i1 %nonnegative, %within_length",
                        "  br i1 %valid, label %ready, label %bounds_panic",
                        "bounds_panic:",
                        "  call void @aether_list_index_bounds_panic()",
                        "  unreachable",
                        "ready:",
                        "  ret void",
                        "}",
                    ]
                )
            )
        if uses_checked_allocation_size or uses_list_growth or self._uses_list_remove_at:
            self._declare(sections, "declare { i64, i1 } @llvm.umul.with.overflow.i64(i64, i64)")
        if uses_list_growth or self._uses_list_remove_at:
            sections.append('@.aether.list.overflow = private unnamed_addr constant [37 x i8] c"Aether panic: List capacity overflow\\00"')
            sections.append(
                "\n".join(
                    [
                        "define private void @aether_list_overflow_panic() noreturn {",
                        "entry:",
                        "  %message = getelementptr [37 x i8], ptr @.aether.list.overflow, i64 0, i64 0",
                        "  call i32 @puts(ptr %message)",
                        "  call void @exit(i32 1)",
                        "  unreachable",
                        "}",
                    ]
                )
            )
        if uses_list_growth:
            self._declare(sections, "declare { i64, i1 } @llvm.uadd.with.overflow.i64(i64, i64)")
        if self._uses_list_insert:
            sections.append('@.aether.list.insert.bounds = private unnamed_addr constant [46 x i8] c"Aether panic: insert() index is out of bounds\\00"')
            sections.append(
                "\n".join(
                    [
                        "define private void @aether_list_insert_bounds_panic() noreturn {",
                        "entry:",
                        "  %message = getelementptr [46 x i8], ptr @.aether.list.insert.bounds, i64 0, i64 0",
                        "  call i32 @puts(ptr %message)",
                        "  call void @exit(i32 1)",
                        "  unreachable",
                        "}",
                    ]
                )
            )
            sections.append(
                "\n".join(
                    [
                        "define private i64 @aether_list_prepare_insert(ptr %list, i64 %index, i64 %element_size) {",
                        "entry:",
                        self._list_length_pointer("%len_field", "%list"),
                        "  %length = load i64, ptr %len_field",
                        "  %nonnegative = icmp sge i64 %index, 0",
                        "  %within_length = icmp ule i64 %index, %length",
                        "  %valid = and i1 %nonnegative, %within_length",
                        "  br i1 %valid, label %required, label %bounds_panic",
                        "bounds_panic:",
                        "  call void @aether_list_insert_bounds_panic()",
                        "  unreachable",
                        "required:",
                        "  %elements_to_move = sub i64 %length, %index",
                        "  %move_pair = call { i64, i1 } @llvm.umul.with.overflow.i64(i64 %elements_to_move, i64 %element_size)",
                        "  %move_overflow = extractvalue { i64, i1 } %move_pair, 1",
                        "  br i1 %move_overflow, label %overflow_panic, label %length_required",
                        "length_required:",
                        "  %required_pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %length, i64 1)",
                        "  %required_length = extractvalue { i64, i1 } %required_pair, 0",
                        "  %overflow = extractvalue { i64, i1 } %required_pair, 1",
                        "  br i1 %overflow, label %overflow_panic, label %reserve",
                        "overflow_panic:",
                        "  call void @aether_list_overflow_panic()",
                        "  unreachable",
                        "reserve:",
                        "  call void @aether_list_reserve(ptr %list, i64 %required_length, i64 %element_size)",
                        "  ret i64 %length",
                        "}",
                    ]
                )
            )
        if uses_list_growth:
            sections.append(
                "\n".join(
                    [
                        "define private void @aether_list_reserve(ptr %list, i64 %required_capacity, i64 %element_size) {",
                        "entry:",
                        self._list_capacity_pointer("%cap_field", "%list"),
                        "  %capacity = load i64, ptr %cap_field",
                        "  %enough = icmp uge i64 %capacity, %required_capacity",
                        "  br i1 %enough, label %exit, label %grow",
                        "grow:",
                        "  %is_zero = icmp eq i64 %capacity, 0",
                        "  br i1 %is_zero, label %from_zero, label %double",
                        "from_zero:",
                        "  br label %choose",
                        "double:",
                        "  %double_pair = call { i64, i1 } @llvm.umul.with.overflow.i64(i64 %capacity, i64 2)",
                        "  %doubled = extractvalue { i64, i1 } %double_pair, 0",
                        "  %double_overflow = extractvalue { i64, i1 } %double_pair, 1",
                        "  br i1 %double_overflow, label %overflow, label %doubled_ok",
                        "doubled_ok:",
                        "  br label %choose",
                        "choose:",
                        "  %grown_capacity = phi i64 [ 1, %from_zero ], [ %doubled, %doubled_ok ]",
                        "  %required_is_larger = icmp ugt i64 %required_capacity, %grown_capacity",
                        "  %new_capacity = select i1 %required_is_larger, i64 %required_capacity, i64 %grown_capacity",
                        "  %size_pair = call { i64, i1 } @llvm.umul.with.overflow.i64(i64 %new_capacity, i64 %element_size)",
                        "  %new_bytes = extractvalue { i64, i1 } %size_pair, 0",
                        "  %size_overflow = extractvalue { i64, i1 } %size_pair, 1",
                        "  br i1 %size_overflow, label %overflow, label %copy_size",
                        "copy_size:",
                        self._list_length_pointer("%len_field", "%list"),
                        "  %length = load i64, ptr %len_field",
                        "  %copy_pair = call { i64, i1 } @llvm.umul.with.overflow.i64(i64 %length, i64 %element_size)",
                        "  %copy_bytes = extractvalue { i64, i1 } %copy_pair, 0",
                        "  %copy_overflow = extractvalue { i64, i1 } %copy_pair, 1",
                        "  br i1 %copy_overflow, label %overflow, label %allocate",
                        "allocate:",
                        "  %new_data = call ptr @aether_alloc(i64 %new_bytes)",
                        self._list_data_pointer("%data_field", "%list"),
                        "  %old_data = load ptr, ptr %data_field",
                        "  %has_data = icmp ne i64 %copy_bytes, 0",
                        "  br i1 %has_data, label %copy, label %replace",
                        "copy:",
                        "  call void @llvm.memcpy.p0.p0.i64(ptr %new_data, ptr %old_data, i64 %copy_bytes, i1 false)",
                        "  br label %replace",
                        "replace:",
                        "  call void @free(ptr %old_data)",
                        "  store ptr %new_data, ptr %data_field",
                        "  store i64 %new_capacity, ptr %cap_field",
                        "  br label %exit",
                        "overflow:",
                        "  call void @aether_list_overflow_panic()",
                        "  unreachable",
                        "exit:",
                        "  ret void",
                        "}",
                    ]
                )
            )
            sections.append(
                "\n".join(
                    [
                        "define private i64 @aether_list_prepare_push(ptr %list, i64 %element_size) {",
                        "entry:",
                        self._list_length_pointer("%len_field", "%list"),
                        "  %length = load i64, ptr %len_field",
                        "  %required_pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %length, i64 1)",
                        "  %required_length = extractvalue { i64, i1 } %required_pair, 0",
                        "  %overflow = extractvalue { i64, i1 } %required_pair, 1",
                        "  br i1 %overflow, label %panic, label %reserve",
                        "panic:",
                        "  call void @aether_list_overflow_panic()",
                        "  unreachable",
                        "reserve:",
                        "  call void @aether_list_reserve(ptr %list, i64 %required_length, i64 %element_size)",
                        "  ret i64 %length",
                        "}",
                    ]
                )
            )
        if self._uses_list_pop:
            sections.append('@.aether.list.pop.empty = private unnamed_addr constant [52 x i8] c"Aether panic: pop() cannot be used on an empty List\\00"')
            sections.append(
                "\n".join(
                    [
                        "define private void @aether_list_pop_empty_panic() noreturn {",
                        "entry:",
                        "  %message = getelementptr [52 x i8], ptr @.aether.list.pop.empty, i64 0, i64 0",
                        "  call i32 @puts(ptr %message)",
                        "  call void @exit(i32 1)",
                        "  unreachable",
                        "}",
                    ]
                )
            )
            sections.append(
                "\n".join(
                    [
                        "define private i64 @aether_list_prepare_pop(ptr %list) {",
                        "entry:",
                        self._list_length_pointer("%len_field", "%list"),
                        "  %length = load i64, ptr %len_field",
                        "  %empty = icmp eq i64 %length, 0",
                        "  br i1 %empty, label %panic, label %ready",
                        "panic:",
                        "  call void @aether_list_pop_empty_panic()",
                        "  unreachable",
                        "ready:",
                        "  %new_length = sub i64 %length, 1",
                        "  ret i64 %new_length",
                        "}",
                    ]
                )
            )
        if self._uses_list_remove_at:
            sections.append('@.aether.list.remove_at.bounds = private unnamed_addr constant [48 x i8] c"Aether panic: removeAt() index is out of bounds\\00"')
            sections.append(
                "\n".join(
                    [
                        "define private void @aether_list_remove_at_bounds_panic() noreturn {",
                        "entry:",
                        "  %message = getelementptr [48 x i8], ptr @.aether.list.remove_at.bounds, i64 0, i64 0",
                        "  call i32 @puts(ptr %message)",
                        "  call void @exit(i32 1)",
                        "  unreachable",
                        "}",
                    ]
                )
            )
            sections.append(
                "\n".join(
                    [
                        "define private i64 @aether_list_prepare_remove_at(ptr %list, i64 %index, i64 %element_size) {",
                        "entry:",
                        self._list_length_pointer("%len_field", "%list"),
                        "  %length = load i64, ptr %len_field",
                        "  %nonnegative = icmp sge i64 %index, 0",
                        "  %within_length = icmp ult i64 %index, %length",
                        "  %valid = and i1 %nonnegative, %within_length",
                        "  br i1 %valid, label %move_size, label %bounds_panic",
                        "bounds_panic:",
                        "  call void @aether_list_remove_at_bounds_panic()",
                        "  unreachable",
                        "move_size:",
                        "  %new_length = sub i64 %length, 1",
                        "  %elements_to_move = sub i64 %new_length, %index",
                        "  %move_pair = call { i64, i1 } @llvm.umul.with.overflow.i64(i64 %elements_to_move, i64 %element_size)",
                        "  %move_overflow = extractvalue { i64, i1 } %move_pair, 1",
                        "  br i1 %move_overflow, label %overflow_panic, label %ready",
                        "overflow_panic:",
                        "  call void @aether_list_overflow_panic()",
                        "  unreachable",
                        "ready:",
                        "  ret i64 %length",
                        "}",
                    ]
                )
            )
        if self._uses_list_reverse:
            sections.append(
                "\n".join(
                    [
                        "define private void @aether_list_reverse(ptr %list, i64 %element_size) {",
                        "entry:",
                        self._list_length_pointer("%len_field", "%list"),
                        "  %length = load i64, ptr %len_field",
                        self._list_data_pointer("%data_field", "%list"),
                        "  %data = load ptr, ptr %data_field",
                        "  %has_pair = icmp ugt i64 %length, 1",
                        "  br i1 %has_pair, label %start, label %exit",
                        "start:",
                        "  %right_start = sub i64 %length, 1",
                        "  br label %outer",
                        "outer:",
                        "  %left = phi i64 [ 0, %start ], [ %left_next, %outer_continue ]",
                        "  %right = phi i64 [ %right_start, %start ], [ %right_next, %outer_continue ]",
                        "  %swap_more = icmp ult i64 %left, %right",
                        "  br i1 %swap_more, label %inner_entry, label %exit",
                        "inner_entry:",
                        "  %left_offset = mul i64 %left, %element_size",
                        "  %right_offset = mul i64 %right, %element_size",
                        "  br label %inner",
                        "inner:",
                        "  %byte = phi i64 [ 0, %inner_entry ], [ %byte_next, %inner_body ]",
                        "  %byte_more = icmp ult i64 %byte, %element_size",
                        "  br i1 %byte_more, label %inner_body, label %outer_continue",
                        "inner_body:",
                        "  %left_byte_offset = add i64 %left_offset, %byte",
                        "  %right_byte_offset = add i64 %right_offset, %byte",
                        "  %left_ptr = getelementptr i8, ptr %data, i64 %left_byte_offset",
                        "  %right_ptr = getelementptr i8, ptr %data, i64 %right_byte_offset",
                        "  %left_value = load i8, ptr %left_ptr",
                        "  %right_value = load i8, ptr %right_ptr",
                        "  store i8 %right_value, ptr %left_ptr",
                        "  store i8 %left_value, ptr %right_ptr",
                        "  %byte_next = add i64 %byte, 1",
                        "  br label %inner",
                        "outer_continue:",
                        "  %left_next = add i64 %left, 1",
                        "  %right_next = sub i64 %right, 1",
                        "  br label %outer",
                        "exit:",
                        "  ret void",
                        "}",
                    ]
                )
            )
        if any(isinstance(type_, StringType) for type_ in self._sequence_sort_types):
            self._declare(sections, "declare i32 @strcmp(ptr, ptr)")
        for element_type in sorted(self._sequence_sort_types, key=sequence_sort_helper_name):
            sections.append(sequence_sort_helper(element_type))
        search_types = self._list_contains_types | self._list_index_of_types
        if any(isinstance(type_, StringType) for type_ in search_types) and not any(
            isinstance(type_, StringType) for type_ in self._sequence_sort_types
        ):
            self._declare(sections, "declare i32 @strcmp(ptr, ptr)")
        search_helpers: dict[str, object] = {}
        for element_type in search_types:
            search_helpers.setdefault(self.list_search_helper_name(element_type), element_type)
        for helper_name in sorted(search_helpers):
            sections.append(self._list_search_helper(search_helpers[helper_name]))
        index_helpers: dict[str, object] = {}
        for element_type in self._list_index_of_types:
            index_helpers.setdefault(self.list_index_of_helper_name(element_type), element_type)
        for helper_name in sorted(index_helpers):
            sections.append(self._list_index_of_helper(index_helpers[helper_name]))
        contains_helpers: dict[str, object] = {}
        for element_type in self._list_contains_types:
            contains_helpers.setdefault(self.list_contains_helper_name(element_type), element_type)
        for helper_name in sorted(contains_helpers):
            sections.append(self._list_contains_helper(contains_helpers[helper_name]))
        return sections

    def _list_contains_helper(self, element_type: object) -> str:
        helper = self.list_contains_helper_name(element_type)
        search_helper = self.list_search_helper_name(element_type)
        llvm_element_type = llvm_type(element_type)
        return "\n".join(
            [
                f"define private i1 @{helper}(ptr %list, {llvm_element_type} %needle) {{",
                "entry:",
                f"  %index = call i64 @{search_helper}(ptr %list, {llvm_element_type} %needle)",
                "  %found = icmp sge i64 %index, 0",
                "  ret i1 %found",
                "}",
            ]
        )

    def _list_index_of_helper(self, element_type: object) -> str:
        helper = self.list_index_of_helper_name(element_type)
        search_helper = self.list_search_helper_name(element_type)
        llvm_element_type = llvm_type(element_type)
        return "\n".join(
            [
                f"define private i32 @{helper}(ptr %list, {llvm_element_type} %needle) {{",
                "entry:",
                f"  %index = call i64 @{search_helper}(ptr %list, {llvm_element_type} %needle)",
                "  %result = call i32 @aether_list_index_to_int(i64 %index)",
                "  ret i32 %result",
                "}",
            ]
        )

    def _list_search_helper(self, element_type: object) -> str:
        helper = self.list_search_helper_name(element_type)
        llvm_element_type = llvm_type(element_type)
        compare = self._list_element_compare(element_type, llvm_element_type)
        return "\n".join(
            [
                f"define private i64 @{helper}(ptr %list, {llvm_element_type} %needle) {{",
                "entry:",
                self._list_length_pointer("%len_field", "%list"),
                "  %length = load i64, ptr %len_field",
                self._list_data_pointer("%data_field", "%list"),
                "  %data = load ptr, ptr %data_field",
                "  br label %loop",
                "loop:",
                "  %index = phi i64 [ 0, %entry ], [ %next, %continue ]",
                "  %more = icmp ult i64 %index, %length",
                "  br i1 %more, label %body, label %not_found",
                "body:",
                f"  %element_ptr = getelementptr {llvm_element_type}, ptr %data, i64 %index",
                f"  %element = load {llvm_element_type}, ptr %element_ptr",
                compare,
                "  br i1 %equal, label %found, label %continue",
                "continue:",
                "  %next = add i64 %index, 1",
                "  br label %loop",
                "found:",
                "  ret i64 %index",
                "not_found:",
                "  ret i64 -1",
                "}",
            ]
        )

    @staticmethod
    def _list_element_compare(element_type: object, llvm_element_type: str) -> str:
        if isinstance(element_type, DoubleType):
            return "  %equal = fcmp oeq double %element, %needle"
        if isinstance(element_type, StringType):
            return "\n".join([
                "  %strcmp_result = call i32 @strcmp(ptr %element, ptr %needle)",
                "  %equal = icmp eq i32 %strcmp_result, 0",
            ])
        return f"  %equal = icmp eq {llvm_element_type} %element, %needle"

    @staticmethod
    def list_contains_helper_name(type_: object) -> str:
        if isinstance(type_, IntType):
            return "aether_list_contains_int"
        if isinstance(type_, DoubleType):
            return "aether_list_contains_double"
        if isinstance(type_, BoolType):
            return "aether_list_contains_bool"
        if isinstance(type_, StringType):
            return "aether_list_contains_string"
        if isinstance(type_, (ListType, ArrayType, VectorType, MatrixType)):
            return "aether_list_contains_ref"
        raise LLVMBackendError(f"LLVM list_contains does not support element type {type_}")

    @staticmethod
    def list_index_of_helper_name(type_: object) -> str:
        if isinstance(type_, IntType):
            return "aether_list_index_of_int"
        if isinstance(type_, DoubleType):
            return "aether_list_index_of_double"
        if isinstance(type_, BoolType):
            return "aether_list_index_of_bool"
        if isinstance(type_, StringType):
            return "aether_list_index_of_string"
        if isinstance(type_, (ListType, ArrayType, VectorType, MatrixType)):
            return "aether_list_index_of_ref"
        raise LLVMBackendError(f"LLVM list_index_of does not support element type {type_}")

    @staticmethod
    def list_search_helper_name(type_: object) -> str:
        if isinstance(type_, IntType):
            return "aether_list_search_int"
        if isinstance(type_, DoubleType):
            return "aether_list_search_double"
        if isinstance(type_, BoolType):
            return "aether_list_search_bool"
        if isinstance(type_, StringType):
            return "aether_list_search_string"
        if isinstance(type_, (ListType, ArrayType, VectorType, MatrixType)):
            return "aether_list_search_ref"
        raise LLVMBackendError(f"LLVM list search does not support element type {type_}")


def list_contains_helper_name(type_: object) -> str:
    return LLVMListRuntime.list_contains_helper_name(type_)


def list_index_of_helper_name(type_: object) -> str:
    return LLVMListRuntime.list_index_of_helper_name(type_)
