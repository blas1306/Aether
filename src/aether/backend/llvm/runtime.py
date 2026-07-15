from __future__ import annotations

from aether.ir.types import DoubleType, IntType, StringType

from .types import LLVMBackendError, llvm_type


def sequence_sort_helper_name(type_: object) -> str:
    if isinstance(type_, IntType):
        return "aether_sort_i32"
    if isinstance(type_, DoubleType):
        return "aether_sort_f64"
    if isinstance(type_, StringType):
        return "aether_sort_string"
    raise LLVMBackendError(f"LLVM sequence_sort does not support element type {type_}")


def _element_size(type_: object) -> str:
    if isinstance(type_, IntType):
        return "4"
    if isinstance(type_, DoubleType):
        return "8"
    if isinstance(type_, StringType):
        return "ptrtoint (ptr getelementptr (ptr, ptr null, i64 1) to i64)"
    raise LLVMBackendError(f"LLVM sequence_sort does not support element type {type_}")

def sequence_sort_helper(element_type: object) -> str:
    helper = sequence_sort_helper_name(element_type)
    llvm_element_type = llvm_type(element_type)
    element_size = _element_size(element_type)
    compare = _sequence_sort_compare(element_type)
    return "\n".join(
        [
            f"define private void @{helper}(ptr %data, i64 %length) {{",
            "entry:",
            f"  %bytes = call i64 @aether_checked_allocation_bytes(i64 %length, i64 {element_size})",
            "  %needs_sort = icmp ugt i64 %length, 1",
            "  br i1 %needs_sort, label %allocate, label %exit",
            "allocate:",
            "  %buffer = call ptr @aether_alloc(i64 %bytes)",
            "  br label %outer",
            "outer:",
            "  %width = phi i64 [ 1, %allocate ], [ %width_next, %width_ready ]",
            "  %more_passes = icmp ult i64 %width, %length",
            "  br i1 %more_passes, label %pass_start, label %finish",
            "pass_start:",
            "  br label %inner",
            "inner:",
            "  %left = phi i64 [ 0, %pass_start ], [ %right, %copy_done ]",
            "  %has_run = icmp ult i64 %left, %length",
            "  br i1 %has_run, label %bounds, label %pass_done",
            "bounds:",
            "  %left_remaining = sub i64 %length, %left",
            "  %mid_clamped = icmp ult i64 %left_remaining, %width",
            "  %mid_delta = select i1 %mid_clamped, i64 %left_remaining, i64 %width",
            "  %mid = add i64 %left, %mid_delta",
            "  %mid_remaining = sub i64 %length, %mid",
            "  %right_clamped = icmp ult i64 %mid_remaining, %width",
            "  %right_delta = select i1 %right_clamped, i64 %mid_remaining, i64 %width",
            "  %right = add i64 %mid, %right_delta",
            "  br label %merge",
            "merge:",
            "  %i = phi i64 [ %left, %bounds ], [ %i_next, %write ]",
            "  %j = phi i64 [ %mid, %bounds ], [ %j_next, %write ]",
            "  %k = phi i64 [ %left, %bounds ], [ %k_next, %write ]",
            "  %merge_more = icmp ult i64 %k, %right",
            "  br i1 %merge_more, label %choose, label %merge_done",
            "choose:",
            "  %i_more = icmp ult i64 %i, %mid",
            "  br i1 %i_more, label %left_available, label %take_right",
            "left_available:",
            "  %j_more = icmp ult i64 %j, %right",
            "  br i1 %j_more, label %compare, label %take_left",
            "compare:",
            f"  %left_ptr_cmp = getelementptr {llvm_element_type}, ptr %data, i64 %i",
            f"  %left_value_cmp = load {llvm_element_type}, ptr %left_ptr_cmp",
            f"  %right_ptr_cmp = getelementptr {llvm_element_type}, ptr %data, i64 %j",
            f"  %right_value_cmp = load {llvm_element_type}, ptr %right_ptr_cmp",
            compare,
            "  br i1 %take_left_cmp, label %take_left, label %take_right",
            "take_left:",
            f"  %left_ptr = getelementptr {llvm_element_type}, ptr %data, i64 %i",
            f"  %left_value = load {llvm_element_type}, ptr %left_ptr",
            f"  %left_dest = getelementptr {llvm_element_type}, ptr %buffer, i64 %k",
            f"  store {llvm_element_type} %left_value, ptr %left_dest",
            "  %i_after_left = add i64 %i, 1",
            "  br label %write",
            "take_right:",
            f"  %right_ptr = getelementptr {llvm_element_type}, ptr %data, i64 %j",
            f"  %right_value = load {llvm_element_type}, ptr %right_ptr",
            f"  %right_dest = getelementptr {llvm_element_type}, ptr %buffer, i64 %k",
            f"  store {llvm_element_type} %right_value, ptr %right_dest",
            "  %j_after_right = add i64 %j, 1",
            "  br label %write",
            "write:",
            "  %i_next = phi i64 [ %i_after_left, %take_left ], [ %i, %take_right ]",
            "  %j_next = phi i64 [ %j, %take_left ], [ %j_after_right, %take_right ]",
            "  %k_next = add i64 %k, 1",
            "  br label %merge",
            "merge_done:",
            "  %run_length = sub i64 %right, %left",
            f"  %run_bytes = call i64 @aether_checked_mul_i64(i64 %run_length, i64 {element_size})",
            f"  %copy_source = getelementptr {llvm_element_type}, ptr %buffer, i64 %left",
            f"  %copy_dest = getelementptr {llvm_element_type}, ptr %data, i64 %left",
            "  call void @llvm.memcpy.p0.p0.i64(ptr %copy_dest, ptr %copy_source, i64 %run_bytes, i1 false)",
            "  br label %copy_done",
            "copy_done:",
            "  br label %inner",
            "pass_done:",
            "  %remaining_width = sub i64 %length, %width",
            "  %can_double = icmp uge i64 %remaining_width, %width",
            "  br i1 %can_double, label %double_width, label %clamp_width",
            "double_width:",
            "  %doubled_width = add i64 %width, %width",
            "  br label %width_ready",
            "clamp_width:",
            "  br label %width_ready",
            "width_ready:",
            "  %width_next = phi i64 [ %doubled_width, %double_width ], [ %length, %clamp_width ]",
            "  br label %outer",
            "finish:",
            "  call void @free(ptr %buffer)",
            "  br label %exit",
            "exit:",
            "  ret void",
            "}",
        ]
    )


def _sequence_sort_compare(element_type: object) -> str:
    if isinstance(element_type, IntType):
        return "  %take_left_cmp = icmp sle i32 %left_value_cmp, %right_value_cmp"
    if isinstance(element_type, StringType):
        return "\n".join(
            [
                "  %sort_compare = call i32 @aether_string_compare_bytes(ptr %left_value_cmp, ptr %right_value_cmp)",
                "  %take_left_cmp = icmp sle i32 %sort_compare, 0",
            ]
        )
    if isinstance(element_type, DoubleType):
        return "\n".join(
            [
                "  %left_nan = fcmp uno double %left_value_cmp, %left_value_cmp",
                "  %right_nan = fcmp uno double %right_value_cmp, %right_value_cmp",
                "  %both_nan = and i1 %left_nan, %right_nan",
                "  %left_not_nan = xor i1 %left_nan, true",
                "  %numeric_le = fcmp ole double %left_value_cmp, %right_value_cmp",
                "  %right_nan_or_le = or i1 %right_nan, %numeric_le",
                "  %ordered_take_left = and i1 %left_not_nan, %right_nan_or_le",
                "  %take_left_cmp = or i1 %both_nan, %ordered_take_left",
            ]
        )
    raise LLVMBackendError(f"LLVM sequence_sort does not support element type {element_type}")
