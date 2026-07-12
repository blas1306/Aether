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


def _element_size(type_: object) -> int:
    if isinstance(type_, IntType):
        return 4
    if isinstance(type_, DoubleType):
        return 8
    if isinstance(type_, StringType):
        return 8
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
            "  %needs_sort = icmp ugt i64 %length, 1",
            "  br i1 %needs_sort, label %allocate, label %exit",
            "allocate:",
            f"  %bytes = mul i64 %length, {element_size}",
            "  %buffer = call ptr @aether_alloc(i64 %bytes)",
            "  br label %outer",
            "outer:",
            "  %width = phi i64 [ 1, %allocate ], [ %width_next, %pass_done ]",
            "  %more_passes = icmp ult i64 %width, %length",
            "  br i1 %more_passes, label %pass_start, label %finish",
            "pass_start:",
            "  br label %inner",
            "inner:",
            "  %left = phi i64 [ 0, %pass_start ], [ %right, %copy_done ]",
            "  %has_run = icmp ult i64 %left, %length",
            "  br i1 %has_run, label %bounds, label %pass_done",
            "bounds:",
            "  %mid_raw = add i64 %left, %width",
            "  %mid_over = icmp ugt i64 %mid_raw, %length",
            "  %mid = select i1 %mid_over, i64 %length, i64 %mid_raw",
            "  %double_width = shl i64 %width, 1",
            "  %right_raw = add i64 %left, %double_width",
            "  %right_over = icmp ugt i64 %right_raw, %length",
            "  %right = select i1 %right_over, i64 %length, i64 %right_raw",
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
            f"  %run_bytes = mul i64 %run_length, {element_size}",
            f"  %copy_source = getelementptr {llvm_element_type}, ptr %buffer, i64 %left",
            f"  %copy_dest = getelementptr {llvm_element_type}, ptr %data, i64 %left",
            "  call void @llvm.memcpy.p0.p0.i64(ptr %copy_dest, ptr %copy_source, i64 %run_bytes, i1 false)",
            "  br label %copy_done",
            "copy_done:",
            "  br label %inner",
            "pass_done:",
            "  %width_next = shl i64 %width, 1",
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
                "  %sort_strcmp = call i32 @strcmp(ptr %left_value_cmp, ptr %right_value_cmp)",
                "  %take_left_cmp = icmp sle i32 %sort_strcmp, 0",
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
