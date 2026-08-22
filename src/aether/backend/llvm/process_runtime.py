from __future__ import annotations

from dataclasses import dataclass

from .runtime_common import LLVMRuntimeCommon


@dataclass(frozen=True)
class LLVMProcessRuntime:
    """Private POSIX process context and owned System.args() snapshots."""

    enabled: bool
    snapshots: bool = False

    def append(self, sections: list[str]) -> None:
        if not self.enabled:
            return

        LLVMRuntimeCommon.declare(sections, "declare i64 @strlen(ptr)")
        LLVMRuntimeCommon.declare(sections, "declare i32 @fprintf(ptr, ptr, ...)")
        diagnostic = (
            "Aether startup error: process argument %lld is not valid UTF-8.\n"
        )
        size = len(diagnostic.encode("utf-8")) + 1
        escaped = diagnostic.replace("\n", "\\0A") + "\\00"
        helpers = [
                "@.aether.process.argc = private global i64 0",
                "@.aether.process.argv = private global ptr null",
                (
                    f"@.aether.process.invalid_utf8 = private unnamed_addr constant "
                    f"[{size} x i8] c\"{escaped}\""
                ),
                self._initialize(size),
                self._destroy(),
        ]
        if self.snapshots:
            helpers.append(self._snapshot())
        sections.extend(helpers)

    @staticmethod
    def _initialize(diagnostic_size: int) -> str:
        return "\n".join(
            [
                "define private i1 @aether_process_context_init(i32 %argc32, ptr %argv) {",
                "entry:",
                "  %argc = sext i32 %argc32 to i64",
                "  %has_program = icmp sgt i64 %argc, 0",
                "  %program_count = select i1 %has_program, i64 1, i64 0",
                "  %count = sub i64 %argc, %program_count",
                "  %args = getelementptr ptr, ptr %argv, i64 %program_count",
                "  br label %validate",
                "validate:",
                "  %index = phi i64 [ 0, %entry ], [ %next, %valid_argument ]",
                "  %done = icmp eq i64 %index, %count",
                "  br i1 %done, label %publish, label %argument",
                "argument:",
                "  %slot = getelementptr ptr, ptr %args, i64 %index",
                "  %bytes = load ptr, ptr %slot",
                "  %length = call i64 @strlen(ptr %bytes)",
                "  %valid = call i1 @aether_string_is_valid_utf8(ptr %bytes, i64 %length)",
                "  br i1 %valid, label %valid_argument, label %invalid",
                "valid_argument:",
                "  %next = add i64 %index, 1",
                "  br label %validate",
                "invalid:",
                "  %stream = call ptr @aether_stderr_stream()",
                (
                    f"  %format = getelementptr [{diagnostic_size} x i8], "
                    "ptr @.aether.process.invalid_utf8, i64 0, i64 0"
                ),
                "  %written = call i32 (ptr, ptr, ...) @fprintf(ptr %stream, ptr %format, i64 %index)",
                "  ret i1 false",
                "publish:",
                "  store i64 %count, ptr @.aether.process.argc",
                "  store ptr %args, ptr @.aether.process.argv",
                "  ret i1 true",
                "}",
            ]
        )

    @staticmethod
    def _destroy() -> str:
        return "\n".join(
            [
                "define private void @aether_process_context_destroy() {",
                "entry:",
                "  store i64 0, ptr @.aether.process.argc",
                "  store ptr null, ptr @.aether.process.argv",
                "  ret void",
                "}",
            ]
        )

    @staticmethod
    def _snapshot() -> str:
        return "\n".join(
            [
                "define private ptr @aether_process_args_snapshot() {",
                "entry:",
                "  %count = load i64, ptr @.aether.process.argc",
                "  %snapshot = call ptr @aether_array_new(i64 ptrtoint (ptr getelementptr (ptr, ptr null, i64 1) to i64), i64 %count)",
                "  %data_field = getelementptr %AetherArray, ptr %snapshot, i32 0, i32 1",
                "  %data = load ptr, ptr %data_field",
                "  %argv = load ptr, ptr @.aether.process.argv",
                "  br label %copy",
                "copy:",
                "  %index = phi i64 [ 0, %entry ], [ %next, %body ]",
                "  %done = icmp eq i64 %index, %count",
                "  br i1 %done, label %finish, label %body",
                "body:",
                "  %source_slot = getelementptr ptr, ptr %argv, i64 %index",
                "  %bytes = load ptr, ptr %source_slot",
                "  %length = call i64 @strlen(ptr %bytes)",
                "  %string = call ptr @aether_string_from_utf8(ptr %bytes, i64 %length)",
                "  %destination = getelementptr ptr, ptr %data, i64 %index",
                "  store ptr %string, ptr %destination",
                "  %next = add i64 %index, 1",
                "  br label %copy",
                "finish:",
                "  ret ptr %snapshot",
                "}",
            ]
        )

    @staticmethod
    def entry_wrapper(program_entry: str = "__aether_program_main") -> str:
        return "\n".join(
            [
                "define i32 @main(i32 %argc, ptr %argv) {",
                "entry:",
                "  %ready = call i1 @aether_process_context_init(i32 %argc, ptr %argv)",
                "  br i1 %ready, label %run, label %invalid_arguments",
                "run:",
                f"  %result = call i32 @{program_entry}()",
                "  call void @aether_process_context_destroy()",
                "  ret i32 %result",
                "invalid_arguments:",
                "  ret i32 2",
                "}",
            ]
        )
