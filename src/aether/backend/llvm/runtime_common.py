from __future__ import annotations

from dataclasses import dataclass
import re

from aether.ir.types import BoolType, DoubleType, EnumType, IntType, StringType, StructType

from .runtime import sequence_sort_helper, sequence_sort_helper_name


def aggregate_helper_suffix(element_type: object) -> str:
    if isinstance(element_type, IntType):
        return "i32"
    if isinstance(element_type, DoubleType):
        return "f64"
    if isinstance(element_type, BoolType):
        return "i1"
    if isinstance(element_type, StringType):
        return "string"
    if isinstance(element_type, EnumType):
        encoded = re.sub(r"[^A-Za-z0-9_]", "_", element_type.name)
        return f"enum_{len(element_type.name)}_{encoded}"
    if isinstance(element_type, StructType):
        encoded = re.sub(r"[^A-Za-z0-9_]", "_", element_type.name)
        return f"struct_{len(element_type.name)}_{encoded}"
    raise TypeError(f"unsupported aggregate runtime element type {element_type}")


def aggregate_equal_helper(prefix: str, element_type: object) -> str:
    suffix = aggregate_helper_suffix(element_type)
    llvm_element_type = {
        "i32": "i32",
        "f64": "double",
        "i1": "i1",
        "string": "ptr",
    }[suffix]
    if suffix == "f64":
        comparison = "  %same = fcmp oeq double %left_value, %right_value"
    elif suffix == "string":
        comparison = "\n".join(
            [
                "  %strcmp = call i32 @strcmp(ptr %left_value, ptr %right_value)",
                "  %same = icmp eq i32 %strcmp, 0",
            ]
        )
    else:
        comparison = f"  %same = icmp eq {llvm_element_type} %left_value, %right_value"
    return "\n".join(
        [
            f"define private i1 @aether_{prefix}_equal_{suffix}(ptr %left, ptr %right, i64 %length) {{",
            "entry:",
            "  %left_data_field = getelementptr %AetherArray, ptr %left, i32 0, i32 1",
            "  %left_data = load ptr, ptr %left_data_field",
            "  %right_data_field = getelementptr %AetherArray, ptr %right, i32 0, i32 1",
            "  %right_data = load ptr, ptr %right_data_field",
            "  br label %loop",
            "loop:",
            "  %index = phi i64 [ 0, %entry ], [ %next, %continue ]",
            "  %more = icmp ult i64 %index, %length",
            "  br i1 %more, label %body, label %equal",
            "body:",
            f"  %left_ptr = getelementptr {llvm_element_type}, ptr %left_data, i64 %index",
            f"  %left_value = load {llvm_element_type}, ptr %left_ptr",
            f"  %right_ptr = getelementptr {llvm_element_type}, ptr %right_data, i64 %index",
            f"  %right_value = load {llvm_element_type}, ptr %right_ptr",
            comparison,
            "  br i1 %same, label %continue, label %different",
            "continue:",
            "  %next = add i64 %index, 1",
            "  br label %loop",
            "different:",
            "  ret i1 false",
            "equal:",
            "  ret i1 true",
            "}",
        ]
    )


def aggregate_print_helper(prefix: str, element_type: object, *, matrix: bool) -> str:
    suffix = aggregate_helper_suffix(element_type)
    llvm_element_type = {
        "i32": "i32",
        "f64": "double",
        "i1": "i1",
        "string": "ptr",
    }[suffix]
    parameters = (
        "ptr %value, i64 %rows, i64 %columns, i1 %newline"
        if matrix
        else "ptr %value, i64 %length, i1 %column, i1 %newline"
    )
    length_setup = "  %length = mul i64 %rows, %columns" if matrix else ""
    if matrix:
        separator = "\n".join(
            [
                "  %column_index = urem i64 %index, %columns",
                "  %row_start = icmp eq i64 %column_index, 0",
                f"  %separator = select i1 %row_start, ptr @.aether.{prefix}.row_sep, ptr @.aether.{prefix}.space",
            ]
        )
    else:
        separator = (
            f"  %separator = select i1 %column, ptr @.aether.{prefix}.row_sep, "
            f"ptr @.aether.{prefix}.space"
        )
    if suffix == "i32":
        print_element = "  %element_result = call i32 (ptr, ...) @printf(ptr @.aether.io.int, i32 %element)"
    elif suffix == "f64":
        print_element = "  %element_result = call i32 (ptr, ...) @printf(ptr @.aether.io.double, double %element)"
    elif suffix == "i1":
        print_element = "\n".join(
            [
                "  %boolean = select i1 %element, ptr @.aether.io.true, ptr @.aether.io.false",
                "  %element_result = call i32 (ptr, ...) @printf(ptr @.aether.io.string, ptr %boolean)",
            ]
        )
    else:
        print_element = "\n".join(
            [
                f"  %quote_open = call i32 (ptr, ...) @printf(ptr @.aether.io.string, ptr @.aether.{prefix}.quote)",
                "  %element_result = call i32 (ptr, ...) @printf(ptr @.aether.io.string, ptr %element)",
                f"  %quote_close = call i32 (ptr, ...) @printf(ptr @.aether.io.string, ptr @.aether.{prefix}.quote)",
            ]
        )
    return "\n".join(
        [
            f"define private void @aether_{prefix}_print_{suffix}({parameters}) {{",
            "entry:",
            length_setup,
            "  %data_field = getelementptr %AetherArray, ptr %value, i32 0, i32 1",
            "  %data = load ptr, ptr %data_field",
            f"  %open_result = call i32 (ptr, ...) @printf(ptr @.aether.io.string, ptr @.aether.{prefix}.open)",
            "  br label %loop",
            "loop:",
            "  %index = phi i64 [ 0, %entry ], [ %next, %continue ]",
            "  %more = icmp ult i64 %index, %length",
            "  br i1 %more, label %separator_check, label %finish",
            "separator_check:",
            "  %first = icmp eq i64 %index, 0",
            "  br i1 %first, label %body, label %separator_block",
            "separator_block:",
            separator,
            "  %separator_result = call i32 (ptr, ...) @printf(ptr @.aether.io.string, ptr %separator)",
            "  br label %body",
            "body:",
            f"  %element_ptr = getelementptr {llvm_element_type}, ptr %data, i64 %index",
            f"  %element = load {llvm_element_type}, ptr %element_ptr",
            print_element,
            "  br label %continue",
            "continue:",
            "  %next = add i64 %index, 1",
            "  br label %loop",
            "finish:",
            "  %close_format = select i1 %newline, ptr @.aether.io.stringln, ptr @.aether.io.string",
            f"  %close_result = call i32 (ptr, ...) @printf(ptr %close_format, ptr @.aether.{prefix}.close)",
            "  ret void",
            "}",
        ]
    )


@dataclass(frozen=True)
class LLVMRuntimeCommon:
    """Shared allocation, declarations, and sequence-sort runtime support."""

    uses_allocation: bool
    uses_checked_allocation_size: bool
    uses_panic: bool
    uses_free_and_memcpy: bool
    uses_memmove: bool
    sequence_sort_types: frozenset[object]

    @staticmethod
    def declare(sections: list[str], declaration: str) -> None:
        if declaration not in sections:
            sections.append(declaration)

    @staticmethod
    def panic_helper(function_name: str, global_name: str, size: int) -> str:
        """Build the shared puts/exit/unreachable panic mechanism."""
        return "\n".join(
            [
                f"define private void @{function_name}() noreturn {{",
                "entry:",
                f"  %message = getelementptr [{size} x i8], ptr @{global_name}, i64 0, i64 0",
                "  call i32 @puts(ptr %message)",
                "  call void @exit(i32 1)",
                "  unreachable",
                "}",
            ]
        )

    def append_core(self, sections: list[str]) -> None:
        if self.uses_panic:
            self.declare(sections, "declare i32 @puts(ptr)")
            self.declare(sections, "declare void @exit(i32) noreturn")
        if self.uses_allocation:
            self.declare(sections, "declare noalias ptr @malloc(i64)")
            sections.append('@.aether.oom = private unnamed_addr constant [39 x i8] c"Aether panic: memory allocation failed\\00"')
            sections.append(self.panic_helper("aether_allocation_failure_panic", ".aether.oom", 39))
            sections.append("\n".join([
                "define private ptr @aether_alloc(i64 %size) {", "entry:",
                "  %zero = icmp eq i64 %size, 0", "  br i1 %zero, label %empty, label %allocate",
                "empty:", "  ret ptr null", "allocate:",
                "  %mem = call noalias ptr @malloc(i64 %size)",
                "  %failed = icmp eq ptr %mem, null", "  br i1 %failed, label %panic, label %ok",
                "panic:", "  call void @aether_allocation_failure_panic()", "  unreachable",
                "ok:", "  ret ptr %mem", "}",
            ]))
        if self.uses_checked_allocation_size:
            sections.append('@.aether.allocation.overflow = private unnamed_addr constant [39 x i8] c"Aether panic: allocation size overflow\\00"')
            sections.append(self.panic_helper("aether_allocation_overflow_panic", ".aether.allocation.overflow", 39))
            sections.append("\n".join([
                "define private i64 @aether_checked_allocation_bytes(i64 %length, i64 %element_size) {", "entry:",
                "  %negative_length = icmp slt i64 %length, 0", "  %negative_size = icmp slt i64 %element_size, 0",
                "  %invalid = or i1 %negative_length, %negative_size", "  br i1 %invalid, label %panic, label %multiply",
                "panic:", "  call void @aether_allocation_overflow_panic()", "  unreachable", "multiply:",
                "  %bytes = call i64 @aether_checked_mul_i64(i64 %length, i64 %element_size)", "  ret i64 %bytes", "}",
            ]))
            sections.append("\n".join([
                "define private i64 @aether_checked_mul_i64(i64 %left, i64 %right) {", "entry:",
                "  %pair = call { i64, i1 } @llvm.umul.with.overflow.i64(i64 %left, i64 %right)",
                "  %result = extractvalue { i64, i1 } %pair, 0", "  %overflow = extractvalue { i64, i1 } %pair, 1",
                "  br i1 %overflow, label %panic, label %ok", "panic:",
                "  call void @aether_allocation_overflow_panic()", "  unreachable", "ok:", "  ret i64 %result", "}",
            ]))
        if self.uses_free_and_memcpy:
            self.declare(sections, "declare void @free(ptr)")
            self.declare(sections, "declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1 immarg)")
        if self.uses_memmove:
            self.declare(sections, "declare void @llvm.memmove.p0.p0.i64(ptr, ptr, i64, i1 immarg)")

    def append_sort(self, sections: list[str]) -> None:
        if any(isinstance(type_, StringType) for type_ in self.sequence_sort_types):
            self.declare(sections, "declare i32 @strcmp(ptr, ptr)")
        for element_type in sorted(self.sequence_sort_types, key=sequence_sort_helper_name):
            sections.append(sequence_sort_helper(element_type))
