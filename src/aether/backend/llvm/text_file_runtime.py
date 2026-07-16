from __future__ import annotations

from dataclasses import dataclass

from .runtime_common import LLVMRuntimeCommon


@dataclass(frozen=True)
class LLVMTextFileRuntime:
    """Private Linux/POSIX length-aware UTF-8 whole-file runtime."""

    enabled: bool

    def append(self, sections: list[str]) -> None:
        if not self.enabled:
            return
        declare = LLVMRuntimeCommon.declare
        declare(sections, "declare i32 @open(ptr, i32, ...)")
        declare(sections, "declare i64 @read(i32, ptr, i64)")
        declare(sections, "declare i64 @write(i32, ptr, i64)")
        declare(sections, "declare i32 @close(i32)")
        declare(sections, "declare ptr @__errno_location()")
        declare(sections, "declare noalias ptr @malloc(i64)")
        declare(sections, "declare ptr @realloc(ptr, i64)")
        declare(sections, "declare void @free(ptr)")
        declare(sections, "declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1 immarg)")
        declare(sections, "declare { i64, i1 } @llvm.uadd.with.overflow.i64(i64, i64)")
        sections.extend(
            [
                self._result_helper(),
                self._errno_status(),
                self._path_copy(),
                self._read_text(),
                self._write_text(),
            ]
        )

    @staticmethod
    def _result_helper() -> str:
        return "\n".join(
            [
                "define private %struct.FileReadResult @aether_file_read_result(ptr %content, i32 %status) {",
                "entry:",
                "  %with_content = insertvalue %struct.FileReadResult undef, ptr %content, 0",
                "  %result = insertvalue %struct.FileReadResult %with_content, i32 %status, 1",
                "  ret %struct.FileReadResult %result",
                "}",
            ]
        )

    @staticmethod
    def _errno_status() -> str:
        # Linux errno values are private runtime details and never enter the
        # language contract. The builder rejects this helper on other native
        # platforms until their runtime mapping is implemented explicitly.
        return "\n".join(
            [
                "define private i32 @aether_file_errno_status() {",
                "entry:",
                "  %errno_ptr = call ptr @__errno_location()",
                "  %error = load i32, ptr %errno_ptr",
                "  switch i32 %error, label %io [",
                "    i32 2, label %not_found",
                "    i32 1, label %permission",
                "    i32 13, label %permission",
                "    i32 22, label %invalid",
                "    i32 36, label %invalid",
                "  ]",
                "not_found:",
                "  ret i32 1",
                "permission:",
                "  ret i32 2",
                "invalid:",
                "  ret i32 3",
                "io:",
                "  ret i32 5",
                "}",
            ]
        )

    @staticmethod
    def _path_copy() -> str:
        return "\n".join(
            [
                "define private { ptr, i32 } @aether_text_path_c(ptr %path) {",
                "entry:",
                "  call void @aether_string_validate(ptr %path)",
                "  %length = call i64 @aether_string_byte_length(ptr %path)",
                "  %empty = icmp eq i64 %length, 0",
                "  br i1 %empty, label %invalid, label %scan_prepare",
                "scan_prepare:",
                "  %data = call ptr @aether_string_data(ptr %path)",
                "  br label %scan",
                "scan:",
                "  %index = phi i64 [ 0, %scan_prepare ], [ %next, %non_nul ]",
                "  %done = icmp eq i64 %index, %length",
                "  br i1 %done, label %size, label %byte",
                "byte:",
                "  %byte_ptr = getelementptr i8, ptr %data, i64 %index",
                "  %value = load i8, ptr %byte_ptr",
                "  %nul = icmp eq i8 %value, 0",
                "  br i1 %nul, label %invalid, label %non_nul",
                "non_nul:",
                "  %next = add i64 %index, 1",
                "  br label %scan",
                "size:",
                "  %size_pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %length, i64 1)",
                "  %size_value = extractvalue { i64, i1 } %size_pair, 0",
                "  %overflow = extractvalue { i64, i1 } %size_pair, 1",
                "  br i1 %overflow, label %io_error, label %allocate",
                "allocate:",
                "  %copy = call noalias ptr @malloc(i64 %size_value)",
                "  %failed = icmp eq ptr %copy, null",
                "  br i1 %failed, label %io_error, label %initialize",
                "initialize:",
                "  call void @llvm.memcpy.p0.p0.i64(ptr %copy, ptr %data, i64 %length, i1 false)",
                "  %terminator = getelementptr i8, ptr %copy, i64 %length",
                "  store i8 0, ptr %terminator",
                "  %ok_ptr = insertvalue { ptr, i32 } undef, ptr %copy, 0",
                "  %ok = insertvalue { ptr, i32 } %ok_ptr, i32 0, 1",
                "  ret { ptr, i32 } %ok",
                "invalid:",
                "  %invalid_ptr = insertvalue { ptr, i32 } undef, ptr null, 0",
                "  %invalid_result = insertvalue { ptr, i32 } %invalid_ptr, i32 3, 1",
                "  ret { ptr, i32 } %invalid_result",
                "io_error:",
                "  %io_ptr = insertvalue { ptr, i32 } undef, ptr null, 0",
                "  %io_result = insertvalue { ptr, i32 } %io_ptr, i32 5, 1",
                "  ret { ptr, i32 } %io_result",
                "}",
            ]
        )

    @staticmethod
    def _read_text() -> str:
        return "\n".join(
            [
                "define private %struct.FileReadResult @aether_read_text(ptr %path) {",
                "entry:",
                "  %path_result = call { ptr, i32 } @aether_text_path_c(ptr %path)",
                "  %c_path = extractvalue { ptr, i32 } %path_result, 0",
                "  %path_status = extractvalue { ptr, i32 } %path_result, 1",
                "  %path_ok = icmp eq i32 %path_status, 0",
                "  br i1 %path_ok, label %open_file, label %path_failure",
                "path_failure:",
                "  %path_failed_result = call %struct.FileReadResult @aether_file_read_result(ptr @.aether.string.empty, i32 %path_status)",
                "  ret %struct.FileReadResult %path_failed_result",
                "open_file:",
                "  %fd = call i32 (ptr, i32, ...) @open(ptr %c_path, i32 0)",
                "  %open_failed = icmp slt i32 %fd, 0",
                "  br i1 %open_failed, label %open_error, label %opened",
                "open_error:",
                "  %open_status = call i32 @aether_file_errno_status()",
                "  call void @free(ptr %c_path)",
                "  %open_result = call %struct.FileReadResult @aether_file_read_result(ptr @.aether.string.empty, i32 %open_status)",
                "  ret %struct.FileReadResult %open_result",
                "opened:",
                "  call void @free(ptr %c_path)",
                "  %initial = call noalias ptr @malloc(i64 65536)",
                "  %allocation_failed = icmp eq ptr %initial, null",
                "  br i1 %allocation_failed, label %initial_oom, label %loop",
                "initial_oom:",
                "  %close_oom = call i32 @close(i32 %fd)",
                "  %oom_result = call %struct.FileReadResult @aether_file_read_result(ptr @.aether.string.empty, i32 5)",
                "  ret %struct.FileReadResult %oom_result",
                "loop:",
                "  %buffer = phi ptr [ %initial, %opened ], [ %grown, %grow_ok ], [ %buffer, %read_more ]",
                "  %capacity = phi i64 [ 65536, %opened ], [ %new_capacity, %grow_ok ], [ %capacity, %read_more ]",
                "  %length = phi i64 [ 0, %opened ], [ %length, %grow_ok ], [ %new_length, %read_more ]",
                "  %full = icmp eq i64 %length, %capacity",
                "  br i1 %full, label %grow_check, label %read_chunk",
                "grow_check:",
                "  %can_grow = icmp ule i64 %capacity, 4611686018427387903",
                "  br i1 %can_grow, label %grow, label %read_io_error",
                "grow:",
                "  %new_capacity = shl i64 %capacity, 1",
                "  %grown = call ptr @realloc(ptr %buffer, i64 %new_capacity)",
                "  %grow_failed = icmp eq ptr %grown, null",
                "  br i1 %grow_failed, label %read_io_error, label %grow_ok",
                "grow_ok:",
                "  br label %loop",
                "read_chunk:",
                "  %destination = getelementptr i8, ptr %buffer, i64 %length",
                "  %available = sub i64 %capacity, %length",
                "  %count = call i64 @read(i32 %fd, ptr %destination, i64 %available)",
                "  %read_failed = icmp slt i64 %count, 0",
                "  br i1 %read_failed, label %read_errno, label %read_count",
                "read_errno:",
                "  %read_errno_ptr = call ptr @__errno_location()",
                "  %read_errno_value = load i32, ptr %read_errno_ptr",
                "  %read_interrupted = icmp eq i32 %read_errno_value, 4",
                "  br i1 %read_interrupted, label %read_chunk, label %read_error_status",
                "read_error_status:",
                "  %read_status = call i32 @aether_file_errno_status()",
                "  br label %read_failure",
                "read_count:",
                "  %eof = icmp eq i64 %count, 0",
                "  br i1 %eof, label %finish, label %read_more",
                "read_more:",
                "  %new_length = add i64 %length, %count",
                "  br label %loop",
                "finish:",
                "  %close_status = call i32 @close(i32 %fd)",
                "  %close_failed = icmp ne i32 %close_status, 0",
                "  br i1 %close_failed, label %closed_error, label %validate_utf8",
                "closed_error:",
                "  call void @free(ptr %buffer)",
                "  %close_result = call %struct.FileReadResult @aether_file_read_result(ptr @.aether.string.empty, i32 5)",
                "  ret %struct.FileReadResult %close_result",
                "validate_utf8:",
                "  %valid = call i1 @aether_string_is_valid_utf8(ptr %buffer, i64 %length)",
                "  br i1 %valid, label %make_string, label %invalid_utf8",
                "invalid_utf8:",
                "  call void @free(ptr %buffer)",
                "  %invalid_result = call %struct.FileReadResult @aether_file_read_result(ptr @.aether.string.empty, i32 4)",
                "  ret %struct.FileReadResult %invalid_result",
                "make_string:",
                "  %content = call ptr @aether_string_from_utf8(ptr %buffer, i64 %length)",
                "  call void @free(ptr %buffer)",
                "  %success = call %struct.FileReadResult @aether_file_read_result(ptr %content, i32 0)",
                "  ret %struct.FileReadResult %success",
                "read_io_error:",
                "  br label %read_failure",
                "read_failure:",
                "  %failure_status = phi i32 [ %read_status, %read_error_status ], [ 5, %read_io_error ]",
                "  %close_read_error = call i32 @close(i32 %fd)",
                "  call void @free(ptr %buffer)",
                "  %read_failed_result = call %struct.FileReadResult @aether_file_read_result(ptr @.aether.string.empty, i32 %failure_status)",
                "  ret %struct.FileReadResult %read_failed_result",
                "}",
            ]
        )

    @staticmethod
    def _write_text() -> str:
        return "\n".join(
            [
                "define private i32 @aether_write_text(ptr %path, ptr %content, i1 %append) {",
                "entry:",
                "  call void @aether_string_validate(ptr %content)",
                "  %path_result = call { ptr, i32 } @aether_text_path_c(ptr %path)",
                "  %c_path = extractvalue { ptr, i32 } %path_result, 0",
                "  %path_status = extractvalue { ptr, i32 } %path_result, 1",
                "  %path_ok = icmp eq i32 %path_status, 0",
                "  br i1 %path_ok, label %open_file, label %path_failure",
                "path_failure:",
                "  ret i32 %path_status",
                "open_file:",
                "  %flags = select i1 %append, i32 1089, i32 577",
                "  %fd = call i32 (ptr, i32, ...) @open(ptr %c_path, i32 %flags, i32 438)",
                "  %open_failed = icmp slt i32 %fd, 0",
                "  br i1 %open_failed, label %open_error, label %opened",
                "open_error:",
                "  %open_status = call i32 @aether_file_errno_status()",
                "  call void @free(ptr %c_path)",
                "  ret i32 %open_status",
                "opened:",
                "  call void @free(ptr %c_path)",
                "  %length = call i64 @aether_string_byte_length(ptr %content)",
                "  %data = call ptr @aether_string_data(ptr %content)",
                "  br label %write_loop",
                "write_loop:",
                "  %offset = phi i64 [ 0, %opened ], [ %next_offset, %wrote ]",
                "  %done = icmp eq i64 %offset, %length",
                "  br i1 %done, label %finish, label %write_chunk",
                "write_chunk:",
                "  %source = getelementptr i8, ptr %data, i64 %offset",
                "  %remaining = sub i64 %length, %offset",
                "  %count = call i64 @write(i32 %fd, ptr %source, i64 %remaining)",
                "  %write_failed = icmp slt i64 %count, 0",
                "  br i1 %write_failed, label %write_error, label %write_zero_check",
                "write_zero_check:",
                "  %short_write = icmp eq i64 %count, 0",
                "  br i1 %short_write, label %short_write_error, label %wrote",
                "wrote:",
                "  %next_offset = add i64 %offset, %count",
                "  br label %write_loop",
                "write_error:",
                "  %write_errno_ptr = call ptr @__errno_location()",
                "  %write_errno_value = load i32, ptr %write_errno_ptr",
                "  %write_interrupted = icmp eq i32 %write_errno_value, 4",
                "  br i1 %write_interrupted, label %write_chunk, label %write_error_status",
                "write_error_status:",
                "  %write_status = call i32 @aether_file_errno_status()",
                "  %close_error = call i32 @close(i32 %fd)",
                "  ret i32 %write_status",
                "short_write_error:",
                "  %close_short_write = call i32 @close(i32 %fd)",
                "  ret i32 5",
                "finish:",
                "  %close_status = call i32 @close(i32 %fd)",
                "  %close_failed = icmp ne i32 %close_status, 0",
                "  %result = select i1 %close_failed, i32 5, i32 0",
                "  ret i32 %result",
                "}",
            ]
        )
