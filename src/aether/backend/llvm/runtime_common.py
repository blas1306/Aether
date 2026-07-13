from __future__ import annotations

from dataclasses import dataclass

from aether.ir.types import StringType

from .runtime import sequence_sort_helper, sequence_sort_helper_name


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
