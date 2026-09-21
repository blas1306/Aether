//! Private runtime boundary for the canonical `std::Text` module.

use std::fmt::Write;

use aether_frontend::TextOp;
use aether_middle::SsaOperand;

#[allow(clippy::too_many_lines)]
pub(super) fn runtime(output: &mut String, parse_int: bool, parse_double: bool) {
    output.push_str(r"
declare ptr @memmem(ptr, i64, ptr, i64) nounwind readonly

; std::private::TextCore.textByteAt -- never source-importable.
define internal i8 @aether_text_byte_at(ptr %value, i64 %offset) nounwind {
entry:
  %length = call i64 @aether_string_length(ptr %value)
  %valid = icmp ult i64 %offset, %length
  br i1 %valid, label %read, label %trap
read:
  %data = call ptr @aether_string_data(ptr %value)
  %address = getelementptr i8, ptr %data, i64 %offset
  %byte = load i8, ptr %address
  ret i8 %byte
trap:
  ; structured Aether trap: TextByteOffsetOutOfBounds
  call void @llvm.trap()
  unreachable
}

; std::private::TextCore.copyUtf8ByteRange -- validates before publication.
define internal ptr @aether_text_copy_range(ptr %value, i64 %start, i64 %end) {
entry:
  %length = call i64 @aether_string_length(ptr %value)
  %ordered = icmp ule i64 %start, %end
  %bounded = icmp ule i64 %end, %length
  %range_ok = and i1 %ordered, %bounded
  br i1 %range_ok, label %start_boundary, label %trap
start_boundary:
  %start_edge = icmp eq i64 %start, %length
  br i1 %start_edge, label %end_boundary, label %start_read
start_read:
  %sb = call i8 @aether_text_byte_at(ptr %value, i64 %start)
  %sb_mask = and i8 %sb, -64
  %sb_cont = icmp eq i8 %sb_mask, -128
  br i1 %sb_cont, label %trap, label %end_boundary
end_boundary:
  %end_edge = icmp eq i64 %end, %length
  br i1 %end_edge, label %identity, label %end_read
end_read:
  %eb = call i8 @aether_text_byte_at(ptr %value, i64 %end)
  %eb_mask = and i8 %eb, -64
  %eb_cont = icmp eq i8 %eb_mask, -128
  br i1 %eb_cont, label %trap, label %identity
identity:
  %empty = icmp eq i64 %start, %end
  br i1 %empty, label %empty_result, label %full_test
empty_result:
  %empty_ptr = getelementptr i8, ptr @aether_string_empty, i64 0
  call void @aether_string_retain(ptr %empty_ptr)
  ret ptr %empty_ptr
full_test:
  %at_zero = icmp eq i64 %start, 0
  %at_end = icmp eq i64 %end, %length
  %full = and i1 %at_zero, %at_end
  br i1 %full, label %alias, label %allocate
alias:
  call void @aether_string_retain(ptr %value)
  ret ptr %value
allocate:
  %range_length = sub i64 %end, %start
  %total_pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %range_length, i64 25)
  %total = extractvalue { i64, i1 } %total_pair, 0
  %overflow = extractvalue { i64, i1 } %total_pair, 1
  br i1 %overflow, label %size_trap, label %alloc
alloc:
  %object = call ptr @aether_alloc(i64 %total, i64 8)
  store i64 %range_length, ptr %object
  %count_ptr = getelementptr i8, ptr %object, i64 8
  store i64 1, ptr %count_ptr
  %flags_ptr = getelementptr i8, ptr %object, i64 16
  store i64 0, ptr %flags_ptr
  %source_data = call ptr @aether_string_data(ptr %value)
  %source = getelementptr i8, ptr %source_data, i64 %start
  %destination = getelementptr i8, ptr %object, i64 24
  call void @llvm.memcpy.p0.p0.i64(ptr %destination, ptr %source, i64 %range_length, i1 false)
  %terminator = getelementptr i8, ptr %destination, i64 %range_length
  store i8 0, ptr %terminator
  %allocs = load i64, ptr @aether_string_alloc_count
  %allocs_next = add i64 %allocs, 1
  store i64 %allocs_next, ptr @aether_string_alloc_count
  ret ptr %object
size_trap:
  call void @llvm.trap()
  unreachable
trap:
  call void @llvm.trap()
  unreachable
}

define internal i1 @aether_text_is_byte_boundary(ptr %value, i64 %offset) nounwind {
entry:
  %length = call i64 @aether_string_length(ptr %value)
  %bounded = icmp ule i64 %offset, %length
  br i1 %bounded, label %edge_test, label %trap
edge_test:
  %at_zero = icmp eq i64 %offset, 0
  %at_end = icmp eq i64 %offset, %length
  %at_edge = or i1 %at_zero, %at_end
  br i1 %at_edge, label %boundary, label %read
read:
  %byte = call i8 @aether_text_byte_at(ptr %value, i64 %offset)
  %mask = and i8 %byte, -64
  %continuation = icmp eq i8 %mask, -128
  %result = xor i1 %continuation, true
  ret i1 %result
boundary:
  ret i1 true
trap:
  ; structured Aether trap: TextByteOffsetOutOfBounds
  call void @llvm.trap()
  unreachable
}

; Internal bridge result: tag plus the owned Slice payload when tag is zero.
define internal { i32, ptr } @aether_text_byte_slice(ptr %value, i64 %start, i64 %end) {
entry:
  %length = call i64 @aether_string_length(ptr %value)
  %ordered = icmp ule i64 %start, %end
  br i1 %ordered, label %bounds, label %invalid_range
bounds:
  %start_bounded = icmp ule i64 %start, %length
  %end_bounded = icmp ule i64 %end, %length
  %bounded = and i1 %start_bounded, %end_bounded
  br i1 %bounded, label %start_boundary, label %out_of_bounds
start_boundary:
  %start_edge = icmp eq i64 %start, %length
  br i1 %start_edge, label %end_boundary, label %start_read
start_read:
  %start_byte = call i8 @aether_text_byte_at(ptr %value, i64 %start)
  %start_mask = and i8 %start_byte, -64
  %start_continuation = icmp eq i8 %start_mask, -128
  br i1 %start_continuation, label %invalid_boundary, label %end_boundary
end_boundary:
  %end_edge = icmp eq i64 %end, %length
  br i1 %end_edge, label %slice, label %end_read
end_read:
  %end_byte = call i8 @aether_text_byte_at(ptr %value, i64 %end)
  %end_mask = and i8 %end_byte, -64
  %end_continuation = icmp eq i8 %end_mask, -128
  br i1 %end_continuation, label %invalid_boundary, label %slice
slice:
  %owned = call ptr @aether_text_copy_range(ptr %value, i64 %start, i64 %end)
  %slice_tag = insertvalue { i32, ptr } zeroinitializer, i32 0, 0
  %slice_result = insertvalue { i32, ptr } %slice_tag, ptr %owned, 1
  ret { i32, ptr } %slice_result
invalid_range:
  %range_result = insertvalue { i32, ptr } zeroinitializer, i32 1, 0
  ret { i32, ptr } %range_result
out_of_bounds:
  %bounds_result = insertvalue { i32, ptr } zeroinitializer, i32 2, 0
  ret { i32, ptr } %bounds_result
invalid_boundary:
  %boundary_result = insertvalue { i32, ptr } zeroinitializer, i32 3, 0
  ret { i32, ptr } %boundary_result
}

define internal i64 @aether_text_code_point_count(ptr %value) nounwind {
entry:
  %length = call i64 @aether_string_length(ptr %value)
  br label %loop
loop:
  %offset = phi i64 [ 0, %entry ], [ %next, %body ]
  %count = phi i64 [ 0, %entry ], [ %count_next, %body ]
  %done = icmp eq i64 %offset, %length
  br i1 %done, label %return, label %body
body:
  %byte = call i8 @aether_text_byte_at(ptr %value, i64 %offset)
  %mask = and i8 %byte, -64
  %continuation = icmp eq i8 %mask, -128
  %increment = select i1 %continuation, i64 0, i64 1
  %count_next = add i64 %count, %increment
  %next = add i64 %offset, 1
  br label %loop
return:
  ret i64 %count
}

define internal i64 @aether_text_scalar_to_byte(ptr %value, i64 %wanted) nounwind {
entry:
  %length = call i64 @aether_string_length(ptr %value)
  br label %loop
loop:
  %offset = phi i64 [ 0, %entry ], [ %next, %body ]
  %scalar = phi i64 [ 0, %entry ], [ %scalar_next, %body ]
  %found = icmp eq i64 %scalar, %wanted
  br i1 %found, label %return, label %bounds
bounds:
  %done = icmp eq i64 %offset, %length
  br i1 %done, label %trap, label %body
body:
  %byte = call i8 @aether_text_byte_at(ptr %value, i64 %offset)
  %ascii = icmp ult i8 %byte, -128
  %two = icmp ult i8 %byte, -32
  %three = icmp ult i8 %byte, -16
  %wide = select i1 %three, i64 3, i64 4
  %non_ascii = select i1 %two, i64 2, i64 %wide
  %width = select i1 %ascii, i64 1, i64 %non_ascii
  %scalar_next = add i64 %scalar, 1
  %next = add i64 %offset, %width
  br label %loop
return:
  ret i64 %offset
trap:
  ; structured Aether trap: TextPositionOutOfBounds
  call void @llvm.trap()
  unreachable
}

define internal i64 @aether_text_byte_to_scalar(ptr %value, i64 %wanted) nounwind {
entry:
  br label %loop
loop:
  %offset = phi i64 [ 0, %entry ], [ %next, %body ]
  %scalar = phi i64 [ 0, %entry ], [ %scalar_next, %body ]
  %done = icmp eq i64 %offset, %wanted
  br i1 %done, label %return, label %body
body:
  %byte = call i8 @aether_text_byte_at(ptr %value, i64 %offset)
  %mask = and i8 %byte, -64
  %continuation = icmp eq i8 %mask, -128
  %increment = select i1 %continuation, i64 0, i64 1
  %scalar_next = add i64 %scalar, %increment
  %next = add i64 %offset, 1
  br label %loop
return:
  ret i64 %scalar
}

define internal { i1, i64 } @aether_text_find(ptr %value, ptr %needle, i64 %start_scalar) nounwind {
entry:
  %start = call i64 @aether_text_scalar_to_byte(ptr %value, i64 %start_scalar)
  %length = call i64 @aether_string_length(ptr %value)
  %needle_length = call i64 @aether_string_length(ptr %needle)
  %empty = icmp eq i64 %needle_length, 0
  br i1 %empty, label %empty_result, label %search
empty_result:
  %e0 = insertvalue { i1, i64 } poison, i1 true, 0
  %e1 = insertvalue { i1, i64 } %e0, i64 %start_scalar, 1
  ret { i1, i64 } %e1
search:
  %remaining = sub i64 %length, %start
  %data = call ptr @aether_string_data(ptr %value)
  %cursor = getelementptr i8, ptr %data, i64 %start
  %needle_data = call ptr @aether_string_data(ptr %needle)
  %match = call ptr @memmem(ptr %cursor, i64 %remaining, ptr %needle_data, i64 %needle_length)
  %missing = icmp eq ptr %match, null
  br i1 %missing, label %not_found, label %found
not_found:
  ret { i1, i64 } zeroinitializer
found:
  %match_int = ptrtoint ptr %match to i64
  %data_int = ptrtoint ptr %data to i64
  %byte_offset = sub i64 %match_int, %data_int
  %scalar = call i64 @aether_text_byte_to_scalar(ptr %value, i64 %byte_offset)
  %f0 = insertvalue { i1, i64 } poison, i1 true, 0
  %f1 = insertvalue { i1, i64 } %f0, i64 %scalar, 1
  ret { i1, i64 } %f1
}

define internal i1 @aether_text_starts_with(ptr %value, ptr %needle) nounwind {
entry:
  %vl = call i64 @aether_string_length(ptr %value)
  %nl = call i64 @aether_string_length(ptr %needle)
  %fits = icmp ule i64 %nl, %vl
  br i1 %fits, label %compare, label %no
compare:
  %vd = call ptr @aether_string_data(ptr %value)
  %nd = call ptr @aether_string_data(ptr %needle)
  %cmp = call i32 @memcmp(ptr %vd, ptr %nd, i64 %nl)
  %equal = icmp eq i32 %cmp, 0
  ret i1 %equal
no:
  ret i1 false
}

define internal i1 @aether_text_ends_with(ptr %value, ptr %needle) nounwind {
entry:
  %vl = call i64 @aether_string_length(ptr %value)
  %nl = call i64 @aether_string_length(ptr %needle)
  %fits = icmp ule i64 %nl, %vl
  br i1 %fits, label %compare, label %no
compare:
  %start = sub i64 %vl, %nl
  %vd = call ptr @aether_string_data(ptr %value)
  %suffix = getelementptr i8, ptr %vd, i64 %start
  %nd = call ptr @aether_string_data(ptr %needle)
  %cmp = call i32 @memcmp(ptr %suffix, ptr %nd, i64 %nl)
  %equal = icmp eq i32 %cmp, 0
  ret i1 %equal
no:
  ret i1 false
}

define internal ptr @aether_text_substring(ptr %value, i64 %start_scalar, i64 %end_scalar) {
entry:
  %ordered = icmp ule i64 %start_scalar, %end_scalar
  br i1 %ordered, label %resolve, label %invalid_range
resolve:
  %start = call i64 @aether_text_scalar_to_byte(ptr %value, i64 %start_scalar)
  %end = call i64 @aether_text_scalar_to_byte(ptr %value, i64 %end_scalar)
  %result = call ptr @aether_text_copy_range(ptr %value, i64 %start, i64 %end)
  ret ptr %result
invalid_range:
  ; structured Aether trap: InvalidTextRange
  call void @llvm.trap()
  unreachable
}

define internal i1 @aether_text_is_trim_byte(i8 %byte) nounwind {
entry:
  %space = icmp eq i8 %byte, 32
  %tab = icmp eq i8 %byte, 9
  %lf = icmp eq i8 %byte, 10
  %cr = icmp eq i8 %byte, 13
  %ff = icmp eq i8 %byte, 12
  %vt = icmp eq i8 %byte, 11
  %a = or i1 %space, %tab
  %b = or i1 %lf, %cr
  %c = or i1 %ff, %vt
  %d = or i1 %a, %b
  %result = or i1 %d, %c
  ret i1 %result
}

define internal ptr @aether_text_trim(ptr %value) {
entry:
  %length = call i64 @aether_string_length(ptr %value)
  br label %left_loop
left_loop:
  %left = phi i64 [ 0, %entry ], [ %left_next, %left_body ]
  %left_done = icmp eq i64 %left, %length
  br i1 %left_done, label %copy_empty, label %left_body
left_body:
  %lb = call i8 @aether_text_byte_at(ptr %value, i64 %left)
  %lw = call i1 @aether_text_is_trim_byte(i8 %lb)
  %left_next = add i64 %left, 1
  br i1 %lw, label %left_loop, label %right_loop
right_loop:
  %right = phi i64 [ %length, %left_body ], [ %right_next, %right_body ]
  %right_done = icmp eq i64 %right, %left
  br i1 %right_done, label %copy, label %right_body
right_body:
  %right_next = sub i64 %right, 1
  %rb = call i8 @aether_text_byte_at(ptr %value, i64 %right_next)
  %rw = call i1 @aether_text_is_trim_byte(i8 %rb)
  br i1 %rw, label %right_loop, label %copy
copy_empty:
  %empty = call ptr @aether_text_copy_range(ptr %value, i64 0, i64 0)
  ret ptr %empty
copy:
  %result = call ptr @aether_text_copy_range(ptr %value, i64 %left, i64 %right)
  ret ptr %result
}

define internal { ptr, i64, i64 } @aether_text_split(ptr %value, ptr %separator) {
entry:
  %length = call i64 @aether_string_length(ptr %value)
  %separator_length = call i64 @aether_string_length(ptr %separator)
  %empty_separator = icmp eq i64 %separator_length, 0
  br i1 %empty_separator, label %separator_trap, label %count_header
count_header:
  %count_cursor = phi i64 [ 0, %entry ], [ %count_next_cursor, %count_match ]
  %matches = phi i64 [ 0, %entry ], [ %matches_next, %count_match ]
  %count_remaining = sub i64 %length, %count_cursor
  %value_data = call ptr @aether_string_data(ptr %value)
  %value_data_int = ptrtoint ptr %value_data to i64
  %count_ptr = getelementptr i8, ptr %value_data, i64 %count_cursor
  %separator_data = call ptr @aether_string_data(ptr %separator)
  %count_found = call ptr @memmem(ptr %count_ptr, i64 %count_remaining, ptr %separator_data, i64 %separator_length)
  %count_missing = icmp eq ptr %count_found, null
  br i1 %count_missing, label %allocate_count, label %count_match
count_match:
  %count_found_int = ptrtoint ptr %count_found to i64
  %count_offset = sub i64 %count_found_int, %value_data_int
  %count_next_cursor = add i64 %count_offset, %separator_length
  %matches_next_pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %matches, i64 1)
  %matches_next = extractvalue { i64, i1 } %matches_next_pair, 0
  %matches_overflow = extractvalue { i64, i1 } %matches_next_pair, 1
  br i1 %matches_overflow, label %size_trap, label %count_header
allocate_count:
  %items_pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %matches, i64 1)
  %items = extractvalue { i64, i1 } %items_pair, 0
  %items_overflow = extractvalue { i64, i1 } %items_pair, 1
  br i1 %items_overflow, label %size_trap, label %allocate_size
allocate_size:
  %bytes_pair = call { i64, i1 } @llvm.umul.with.overflow.i64(i64 %items, i64 8)
  %bytes = extractvalue { i64, i1 } %bytes_pair, 0
  %bytes_overflow = extractvalue { i64, i1 } %bytes_pair, 1
  br i1 %bytes_overflow, label %size_trap, label %allocate
allocate:
  %storage = call ptr @aether_alloc(i64 %bytes, i64 8)
  br label %fill_header
fill_header:
  %cursor = phi i64 [ 0, %allocate ], [ %next_cursor, %fill_match ]
  %index = phi i64 [ 0, %allocate ], [ %next_index, %fill_match ]
  %remaining = sub i64 %length, %cursor
  %cursor_ptr = getelementptr i8, ptr %value_data, i64 %cursor
  %found = call ptr @memmem(ptr %cursor_ptr, i64 %remaining, ptr %separator_data, i64 %separator_length)
  %missing = icmp eq ptr %found, null
  br i1 %missing, label %tail, label %fill_match
fill_match:
  %found_int = ptrtoint ptr %found to i64
  %match_offset = sub i64 %found_int, %value_data_int
  %piece = call ptr @aether_text_copy_range(ptr %value, i64 %cursor, i64 %match_offset)
  %slot = getelementptr ptr, ptr %storage, i64 %index
  store ptr %piece, ptr %slot
  %next_cursor = add i64 %match_offset, %separator_length
  %next_index = add i64 %index, 1
  br label %fill_header
tail:
  %last = call ptr @aether_text_copy_range(ptr %value, i64 %cursor, i64 %length)
  %last_slot = getelementptr ptr, ptr %storage, i64 %index
  store ptr %last, ptr %last_slot
  %r0 = insertvalue { ptr, i64, i64 } poison, ptr %storage, 0
  %r1 = insertvalue { ptr, i64, i64 } %r0, i64 %items, 1
  %r2 = insertvalue { ptr, i64, i64 } %r1, i64 %items, 2
  ret { ptr, i64, i64 } %r2
separator_trap:
  ; structured Aether trap: EmptyTextSeparator
  call void @llvm.trap()
  unreachable
size_trap:
  call void @llvm.trap()
  unreachable
}

define internal { ptr, i64, i64 } @aether_text_lines(ptr %value) {
entry:
  %length = call i64 @aether_string_length(ptr %value)
  %empty = icmp eq i64 %length, 0
  br i1 %empty, label %empty_result, label %count_header
empty_result:
  ret { ptr, i64, i64 } zeroinitializer
count_header:
  %count_offset = phi i64 [ 0, %entry ], [ %count_next_offset, %count_body ]
  %lf_count = phi i64 [ 0, %entry ], [ %count_next, %count_body ]
  %count_done = icmp eq i64 %count_offset, %length
  br i1 %count_done, label %count_finish, label %count_body
count_body:
  %count_byte = call i8 @aether_text_byte_at(ptr %value, i64 %count_offset)
  %is_lf = icmp eq i8 %count_byte, 10
  %count_increment = zext i1 %is_lf to i64
  %count_next = add i64 %lf_count, %count_increment
  %count_next_offset = add i64 %count_offset, 1
  br label %count_header
count_finish:
  %last_offset = sub i64 %length, 1
  %last_byte = call i8 @aether_text_byte_at(ptr %value, i64 %last_offset)
  %terminal_lf = icmp eq i8 %last_byte, 10
  %tail_count = select i1 %terminal_lf, i64 0, i64 1
  %items_pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %lf_count, i64 %tail_count)
  %items = extractvalue { i64, i1 } %items_pair, 0
  %items_overflow = extractvalue { i64, i1 } %items_pair, 1
  br i1 %items_overflow, label %size_trap, label %allocate_size
allocate_size:
  %bytes_pair = call { i64, i1 } @llvm.umul.with.overflow.i64(i64 %items, i64 8)
  %bytes = extractvalue { i64, i1 } %bytes_pair, 0
  %bytes_overflow = extractvalue { i64, i1 } %bytes_pair, 1
  br i1 %bytes_overflow, label %size_trap, label %allocate
allocate:
  %storage = call ptr @aether_alloc(i64 %bytes, i64 8)
  br label %fill_header
fill_header:
  %offset = phi i64 [ 0, %allocate ], [ %next_offset, %fill_next ]
  %start = phi i64 [ 0, %allocate ], [ %next_start_value, %fill_next ]
  %index = phi i64 [ 0, %allocate ], [ %next_index_value, %fill_next ]
  %done = icmp eq i64 %offset, %length
  br i1 %done, label %tail_check, label %fill_body
fill_body:
  %byte = call i8 @aether_text_byte_at(ptr %value, i64 %offset)
  %separator = icmp eq i8 %byte, 10
  br i1 %separator, label %line_end_check, label %advance
line_end_check:
  %has_previous = icmp ult i64 %start, %offset
  br i1 %has_previous, label %previous, label %publish
previous:
  %previous_offset = sub i64 %offset, 1
  %previous_byte = call i8 @aether_text_byte_at(ptr %value, i64 %previous_offset)
  %is_cr = icmp eq i8 %previous_byte, 13
  %stripped_end = select i1 %is_cr, i64 %previous_offset, i64 %offset
  br label %publish
publish:
  %line_end = phi i64 [ %offset, %line_end_check ], [ %stripped_end, %previous ]
  %line = call ptr @aether_text_copy_range(ptr %value, i64 %start, i64 %line_end)
  %slot = getelementptr ptr, ptr %storage, i64 %index
  store ptr %line, ptr %slot
  %next_start = add i64 %offset, 1
  %next_index = add i64 %index, 1
  br label %fill_next
advance:
  br label %fill_next
fill_next:
  %next_start_value = phi i64 [ %next_start, %publish ], [ %start, %advance ]
  %next_index_value = phi i64 [ %next_index, %publish ], [ %index, %advance ]
  %next_offset = add i64 %offset, 1
  br label %fill_header
tail_check:
  %has_tail = icmp ult i64 %start, %length
  br i1 %has_tail, label %tail, label %return
tail:
  %last = call ptr @aether_text_copy_range(ptr %value, i64 %start, i64 %length)
  %last_slot = getelementptr ptr, ptr %storage, i64 %index
  store ptr %last, ptr %last_slot
  br label %return
return:
  %r0 = insertvalue { ptr, i64, i64 } poison, ptr %storage, 0
  %r1 = insertvalue { ptr, i64, i64 } %r0, i64 %items, 1
  %r2 = insertvalue { ptr, i64, i64 } %r1, i64 %items, 2
  ret { ptr, i64, i64 } %r2
size_trap:
  call void @llvm.trap()
  unreachable
}
");
    if parse_int {
        output.push_str(
            r"
; status: 0 Value, 1 Invalid, 2 Overflow.  Syntax is validated after overflow.
define internal { i32, i64 } @aether_text_parse_int(ptr %value) nounwind {
entry:
  %length = call i64 @aether_string_length(ptr %value)
  %data = call ptr @aether_string_data(ptr %value)
  %empty = icmp eq i64 %length, 0
  br i1 %empty, label %invalid, label %first
first:
  %head = load i8, ptr %data
  %plus = icmp eq i8 %head, 43
  %minus = icmp eq i8 %head, 45
  %signed = or i1 %plus, %minus
  %start = select i1 %signed, i64 1, i64 0
  %sign_only = icmp eq i64 %start, %length
  br i1 %sign_only, label %invalid, label %loop
loop:
  %index = phi i64 [ %start, %first ], [ %next, %digit ]
  %magnitude = phi i64 [ 0, %first ], [ %magnitude_next, %digit ]
  %overflowed = phi i1 [ false, %first ], [ %overflow_next, %digit ]
  %done = icmp eq i64 %index, %length
  br i1 %done, label %finish, label %read
read:
  %address = getelementptr i8, ptr %data, i64 %index
  %byte = load i8, ptr %address
  %decimal = add i8 %byte, -48
  %valid = icmp ult i8 %decimal, 10
  br i1 %valid, label %digit, label %invalid
digit:
  %d = zext i8 %decimal to i64
  %limit = select i1 %minus, i64 -9223372036854775808, i64 9223372036854775807
  %room = sub i64 %limit, %d
  %threshold = udiv i64 %room, 10
  %new_overflow = icmp ugt i64 %magnitude, %threshold
  %overflow_next = or i1 %overflowed, %new_overflow
  %product = mul i64 %magnitude, 10
  %sum = add i64 %product, %d
  %magnitude_next = select i1 %overflow_next, i64 %magnitude, i64 %sum
  %next = add i64 %index, 1
  br label %loop
finish:
  br i1 %overflowed, label %overflow, label %parsed_value
parsed_value:
  %inverted = xor i64 %magnitude, -1
  %negated = add i64 %inverted, 1
  %number = select i1 %minus, i64 %negated, i64 %magnitude
  %v0 = insertvalue { i32, i64 } zeroinitializer, i32 0, 0
  %v1 = insertvalue { i32, i64 } %v0, i64 %number, 1
  ret { i32, i64 } %v1
invalid:
  %bad = insertvalue { i32, i64 } zeroinitializer, i32 1, 0
  ret { i32, i64 } %bad
overflow:
  %wide = insertvalue { i32, i64 } zeroinitializer, i32 2, 0
  ret { i32, i64 } %wide
}
",
        );
    }
    if parse_double {
        output.push_str(include_str!("numeric_parse_runtime.inc"));
        output.push_str(
            r"
define internal { i32, double } @aether_text_parse_double(ptr %value) nounwind {
entry:
  %length = call i64 @aether_string_length(ptr %value)
  %data = call ptr @aether_string_data(ptr %value)
  %raw = call { i32, i64 } @aether_numeric_parse_double(ptr %data, i64 %length)
  %status = extractvalue { i32, i64 } %raw, 0
  %bits = extractvalue { i32, i64 } %raw, 1
  %number = bitcast i64 %bits to double
  %r0 = insertvalue { i32, double } zeroinitializer, i32 %status, 0
  %r1 = insertvalue { i32, double } %r0, double %number, 1
  ret { i32, double } %r1
}
",
        );
    }
}

#[allow(clippy::too_many_lines)]
pub(super) fn emit_op(
    output: &mut String,
    op: &TextOp<SsaOperand>,
    result: u32,
    result_ty: &str,
    scalar_ty: &str,
    operand: impl Fn(&SsaOperand) -> String,
) {
    let borrowed = |value: &SsaOperand, suffix: &str, output: &mut String| {
        let name = format!("%text_ref_{result}_{suffix}");
        writeln!(output, "  {name} = load ptr, ptr {}", operand(value)).unwrap();
        name
    };
    let scalar = |value: &SsaOperand, suffix: &str, output: &mut String| {
        let name = format!("%text_scalar_{result}_{suffix}");
        writeln!(
            output,
            "  {name} = extractvalue {scalar_ty} {}, 0",
            operand(value)
        )
        .unwrap();
        name
    };
    match op {
        TextOp::CodePointCount { value } => {
            let value = borrowed(value, "value", output);
            writeln!(
                output,
                "  %v{result} = call i64 @aether_text_code_point_count(ptr {value})"
            )
            .unwrap();
        }
        TextOp::Contains { value, needle } => {
            let value = borrowed(value, "value", output);
            let needle = borrowed(needle, "needle", output);
            writeln!(output, "  %text_find_{result} = call {{ i1, i64 }} @aether_text_find(ptr {value}, ptr {needle}, i64 0)").unwrap();
            writeln!(
                output,
                "  %v{result} = extractvalue {{ i1, i64 }} %text_find_{result}, 0"
            )
            .unwrap();
        }
        TextOp::StartsWith { value, prefix } => {
            let value = borrowed(value, "value", output);
            let prefix = borrowed(prefix, "prefix", output);
            writeln!(
                output,
                "  %v{result} = call i1 @aether_text_starts_with(ptr {value}, ptr {prefix})"
            )
            .unwrap();
        }
        TextOp::EndsWith { value, suffix } => {
            let value = borrowed(value, "value", output);
            let suffix = borrowed(suffix, "suffix", output);
            writeln!(
                output,
                "  %v{result} = call i1 @aether_text_ends_with(ptr {value}, ptr {suffix})"
            )
            .unwrap();
        }
        TextOp::Find {
            value,
            needle,
            start,
        } => {
            let value = borrowed(value, "value", output);
            let needle = borrowed(needle, "needle", output);
            let start = start
                .as_ref()
                .map_or_else(|| "0".into(), |v| scalar(v, "start", output));
            writeln!(output, "  %text_find_{result} = call {{ i1, i64 }} @aether_text_find(ptr {value}, ptr {needle}, i64 {start})").unwrap();
            writeln!(
                output,
                "  %text_found_{result} = extractvalue {{ i1, i64 }} %text_find_{result}, 0"
            )
            .unwrap();
            writeln!(
                output,
                "  %text_offset_{result} = extractvalue {{ i1, i64 }} %text_find_{result}, 1"
            )
            .unwrap();
            writeln!(
                output,
                "  %text_tag_{result} = select i1 %text_found_{result}, i32 0, i32 1"
            )
            .unwrap();
            writeln!(output, "  %text_enum_{result} = insertvalue {result_ty} zeroinitializer, i32 %text_tag_{result}, 0").unwrap();
            writeln!(output, "  %v{result} = insertvalue {result_ty} %text_enum_{result}, i64 %text_offset_{result}, 1, 0, 0").unwrap();
        }
        TextOp::Substring { value, start, end } => {
            let value = borrowed(value, "value", output);
            let start = scalar(start, "start", output);
            let end = scalar(end, "end", output);
            writeln!(
                output,
                "  %v{result} = call ptr @aether_text_substring(ptr {value}, i64 {start}, i64 {end})"
            )
            .unwrap();
        }
        TextOp::Trim { value } => {
            let value = borrowed(value, "value", output);
            writeln!(
                output,
                "  %v{result} = call ptr @aether_text_trim(ptr {value})"
            )
            .unwrap();
        }
        TextOp::Split { value, separator } => {
            let value = borrowed(value, "value", output);
            let separator = borrowed(separator, "separator", output);
            writeln!(output, "  %v{result} = call {{ ptr, i64, i64 }} @aether_text_split(ptr {value}, ptr {separator})").unwrap();
        }
        TextOp::Lines { value } => {
            let value = borrowed(value, "value", output);
            writeln!(
                output,
                "  %v{result} = call {{ ptr, i64, i64 }} @aether_text_lines(ptr {value})"
            )
            .unwrap();
        }
        TextOp::ByteAt { value, offset } => {
            let value = borrowed(value, "value", output);
            writeln!(
                output,
                "  %v{result} = call i8 @aether_text_byte_at(ptr {value}, i64 {})",
                operand(offset)
            )
            .unwrap();
        }
        TextOp::IsByteBoundary { value, offset } => {
            let value = borrowed(value, "value", output);
            writeln!(
                output,
                "  %v{result} = call i1 @aether_text_is_byte_boundary(ptr {value}, i64 {})",
                operand(offset)
            )
            .unwrap();
        }
        TextOp::ByteSlice {
            value,
            start,
            end_exclusive,
        } => {
            let value = borrowed(value, "value", output);
            writeln!(output, "  %text_byte_slice_{result} = call {{ i32, ptr }} @aether_text_byte_slice(ptr {value}, i64 {}, i64 {})", operand(start), operand(end_exclusive)).unwrap();
            writeln!(output, "  %text_byte_slice_tag_{result} = extractvalue {{ i32, ptr }} %text_byte_slice_{result}, 0").unwrap();
            writeln!(output, "  %text_byte_slice_payload_{result} = extractvalue {{ i32, ptr }} %text_byte_slice_{result}, 1").unwrap();
            writeln!(output, "  %text_byte_slice_enum_{result} = insertvalue {result_ty} zeroinitializer, i32 %text_byte_slice_tag_{result}, 0").unwrap();
            writeln!(output, "  %v{result} = insertvalue {result_ty} %text_byte_slice_enum_{result}, ptr %text_byte_slice_payload_{result}, 1, 0").unwrap();
        }
        TextOp::ParseInt { value } => {
            let value = borrowed(value, "value", output);
            writeln!(output, "  %text_parse_int_{result} = call {{ i32, i64 }} @aether_text_parse_int(ptr {value})").unwrap();
            writeln!(output, "  %text_parse_int_tag_{result} = extractvalue {{ i32, i64 }} %text_parse_int_{result}, 0").unwrap();
            writeln!(output, "  %text_parse_int_payload_{result} = extractvalue {{ i32, i64 }} %text_parse_int_{result}, 1").unwrap();
            writeln!(output, "  %text_parse_int_enum_{result} = insertvalue {result_ty} zeroinitializer, i32 %text_parse_int_tag_{result}, 0").unwrap();
            writeln!(output, "  %v{result} = insertvalue {result_ty} %text_parse_int_enum_{result}, i64 %text_parse_int_payload_{result}, 1, 0").unwrap();
        }
        TextOp::ParseDouble { value } => {
            let value = borrowed(value, "value", output);
            writeln!(output, "  %text_parse_double_{result} = call {{ i32, double }} @aether_text_parse_double(ptr {value})").unwrap();
            writeln!(output, "  %text_parse_double_tag_{result} = extractvalue {{ i32, double }} %text_parse_double_{result}, 0").unwrap();
            writeln!(output, "  %text_parse_double_payload_{result} = extractvalue {{ i32, double }} %text_parse_double_{result}, 1").unwrap();
            writeln!(output, "  %text_parse_double_enum_{result} = insertvalue {result_ty} zeroinitializer, i32 %text_parse_double_tag_{result}, 0").unwrap();
            writeln!(output, "  %v{result} = insertvalue {result_ty} %text_parse_double_enum_{result}, double %text_parse_double_payload_{result}, 1, 0").unwrap();
        }
    }
}
