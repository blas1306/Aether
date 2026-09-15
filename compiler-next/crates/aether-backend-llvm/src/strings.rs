//! Private GENERAL-V1 string runtime ABI and lowering.

use std::collections::BTreeSet;
use std::fmt::Write;

use aether_frontend::{FloatType, InterpolationFragment, StringOp, TypeArena, TypeData};
use aether_middle::{SsaIr, SsaOp, SsaOperand};

fn literal_name(bytes: &[u8]) -> String {
    if bytes.is_empty() {
        return "aether_string_empty".into();
    }
    let mut name = String::from("aether_string_literal_");
    for byte in bytes {
        write!(name, "{byte:02x}").unwrap();
    }
    name
}

fn llvm_bytes(bytes: &[u8]) -> String {
    let mut result = String::new();
    for byte in bytes.iter().copied().chain(std::iter::once(0)) {
        write!(result, "\\{byte:02X}").unwrap();
    }
    result
}

pub(super) fn emit_literals(output: &mut String, program: &SsaIr) {
    let mut literals = BTreeSet::from([Vec::new()]);
    for instruction in program
        .functions
        .iter()
        .flat_map(|f| &f.blocks)
        .flat_map(|b| &b.instructions)
    {
        if let SsaOp::String(op) = &instruction.op {
            match op.as_ref() {
                StringOp::Literal { bytes } => {
                    literals.insert(bytes.clone());
                }
                StringOp::Interpolate { fragments, .. } => {
                    for fragment in fragments {
                        if let InterpolationFragment::Text { bytes, .. } = fragment {
                            literals.insert(bytes.clone());
                        }
                    }
                }
                _ => {}
            }
        }
    }
    for bytes in literals {
        let count = bytes.len() + 1;
        writeln!(
            output,
            "@{} = private constant {{ i64, i64, i64, [{count} x i8] }} {{ i64 {}, i64 0, i64 1, [{count} x i8] c\"{}\" }}, align 8",
            literal_name(&bytes),
            bytes.len(),
            llvm_bytes(&bytes)
        )
        .unwrap();
    }
    output.push('\n');
}

#[allow(clippy::too_many_lines)]
pub(super) fn runtime(output: &mut String, formatting: bool) {
    output.push_str(
        "@aether_string_alloc_count = internal global i64 0\n\
         @aether_string_free_count = internal global i64 0\n\
         @aether_string_retain_count = internal global i64 0\n\
         @aether_string_release_count = internal global i64 0\n\
         @aether_string_concat_count = internal global i64 0\n\
         @aether_string_equal_count = internal global i64 0\n\
         @aether_string_literal_arc_noop_count = internal global i64 0\n\
         @aether_string_newline = private constant [1 x i8] c\"\\0A\"\n\
         declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1 immarg)\n\
         declare i32 @memcmp(ptr, ptr, i64)\n\
         define internal i64 @aether_string_length(ptr %value) nounwind {\n\
         entry:\n\
           %null = icmp eq ptr %value, null\n\
           br i1 %null, label %trap, label %ok\n\
         ok:\n\
           %length_ptr = getelementptr i8, ptr %value, i64 0\n\
           %length = load i64, ptr %length_ptr\n\
           ret i64 %length\n\
         trap:\n\
           call void @llvm.trap()\n\
           unreachable\n\
         }\n\
         define internal ptr @aether_string_data(ptr %value) nounwind {\n\
         entry:\n\
           %data = getelementptr i8, ptr %value, i64 24\n\
           ret ptr %data\n\
         }\n\
         define internal void @aether_string_retain(ptr %value) nounwind {\n\
         entry:\n\
           %null = icmp eq ptr %value, null\n\
           br i1 %null, label %trap, label %flags_block\n\
         flags_block:\n\
           %flags_ptr = getelementptr i8, ptr %value, i64 16\n\
           %flags = load i64, ptr %flags_ptr\n\
           %invalid_flags = icmp ugt i64 %flags, 1\n\
           br i1 %invalid_flags, label %trap, label %immortal_test\n\
         immortal_test:\n\
           %immortal = icmp eq i64 %flags, 1\n\
           br i1 %immortal, label %literal, label %heap\n\
         literal:\n\
           %ln = load i64, ptr @aether_string_literal_arc_noop_count\n\
           %ln_next = add i64 %ln, 1\n\
           store i64 %ln_next, ptr @aether_string_literal_arc_noop_count\n\
           ret void\n\
         heap:\n\
           %count_ptr = getelementptr i8, ptr %value, i64 8\n\
           %count = load i64, ptr %count_ptr\n\
           %zero = icmp eq i64 %count, 0\n\
           %max = icmp eq i64 %count, -1\n\
           %bad = or i1 %zero, %max\n\
           br i1 %bad, label %trap, label %retain\n\
         retain:\n\
           %next = add i64 %count, 1\n\
           store i64 %next, ptr %count_ptr\n\
           %events = load i64, ptr @aether_string_retain_count\n\
           %events_next = add i64 %events, 1\n\
           store i64 %events_next, ptr @aether_string_retain_count\n\
           ret void\n\
         trap:\n\
           call void @llvm.trap()\n\
           unreachable\n\
         }\n\
         define internal void @aether_string_release(ptr %value) nounwind {\n\
         entry:\n\
           %null = icmp eq ptr %value, null\n\
           br i1 %null, label %trap, label %flags_block\n\
         flags_block:\n\
           %flags_ptr = getelementptr i8, ptr %value, i64 16\n\
           %flags = load i64, ptr %flags_ptr\n\
           %invalid_flags = icmp ugt i64 %flags, 1\n\
           br i1 %invalid_flags, label %trap, label %immortal_test\n\
         immortal_test:\n\
           %immortal = icmp eq i64 %flags, 1\n\
           br i1 %immortal, label %literal, label %heap\n\
         literal:\n\
           %ln = load i64, ptr @aether_string_literal_arc_noop_count\n\
           %ln_next = add i64 %ln, 1\n\
           store i64 %ln_next, ptr @aether_string_literal_arc_noop_count\n\
           ret void\n\
         heap:\n\
           %count_ptr = getelementptr i8, ptr %value, i64 8\n\
           %count = load i64, ptr %count_ptr\n\
           %zero = icmp eq i64 %count, 0\n\
           br i1 %zero, label %trap, label %release\n\
         release:\n\
           %events = load i64, ptr @aether_string_release_count\n\
           %events_next = add i64 %events, 1\n\
           store i64 %events_next, ptr @aether_string_release_count\n\
           %last = icmp eq i64 %count, 1\n\
           br i1 %last, label %final, label %decrement\n\
         decrement:\n\
           %next = sub i64 %count, 1\n\
           store i64 %next, ptr %count_ptr\n\
           ret void\n\
         final:\n\
           store i64 0, ptr %count_ptr\n\
           %frees = load i64, ptr @aether_string_free_count\n\
           %frees_next = add i64 %frees, 1\n\
           store i64 %frees_next, ptr @aether_string_free_count\n\
           %length = call i64 @aether_string_length(ptr %value)\n\
           %total = add i64 %length, 25\n\
           call void @aether_free(ptr %value, i64 %total, i64 8)\n\
           ret void\n\
         trap:\n\
           call void @llvm.trap()\n\
           unreachable\n\
         }\n\
         define internal ptr @aether_string_concat(ptr %left, ptr %right) {\n\
         entry:\n\
           %events = load i64, ptr @aether_string_concat_count\n\
           %events_next = add i64 %events, 1\n\
           store i64 %events_next, ptr @aether_string_concat_count\n\
           %ll = call i64 @aether_string_length(ptr %left)\n\
           %rl = call i64 @aether_string_length(ptr %right)\n\
           %left_empty = icmp eq i64 %ll, 0\n\
           br i1 %left_empty, label %alias_right, label %right_test\n\
         alias_right:\n\
           call void @aether_string_retain(ptr %right)\n\
           ret ptr %right\n\
         right_test:\n\
           %right_empty = icmp eq i64 %rl, 0\n\
           br i1 %right_empty, label %alias_left, label %allocate\n\
         alias_left:\n\
           call void @aether_string_retain(ptr %left)\n\
           ret ptr %left\n\
         allocate:\n\
           %sum_pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %ll, i64 %rl)\n\
           %sum = extractvalue { i64, i1 } %sum_pair, 0\n\
           %sum_overflow = extractvalue { i64, i1 } %sum_pair, 1\n\
           %total_pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %sum, i64 25)\n\
           %total = extractvalue { i64, i1 } %total_pair, 0\n\
           %total_overflow = extractvalue { i64, i1 } %total_pair, 1\n\
           %overflow = or i1 %sum_overflow, %total_overflow\n\
           br i1 %overflow, label %size_trap, label %alloc\n\
         size_trap:\n\
           ; structured Aether trap: AllocationSizeOverflow\n\
           call void @llvm.trap()\n\
           unreachable\n\
         alloc:\n\
           %object = call ptr @aether_alloc(i64 %total, i64 8)\n\
           store i64 %sum, ptr %object\n\
           %count_ptr = getelementptr i8, ptr %object, i64 8\n\
           store i64 1, ptr %count_ptr\n\
           %flags_ptr = getelementptr i8, ptr %object, i64 16\n\
           store i64 0, ptr %flags_ptr\n\
           %data = getelementptr i8, ptr %object, i64 24\n\
           %ld = call ptr @aether_string_data(ptr %left)\n\
           call void @llvm.memcpy.p0.p0.i64(ptr %data, ptr %ld, i64 %ll, i1 false)\n\
           %right_dst = getelementptr i8, ptr %data, i64 %ll\n\
           %rd = call ptr @aether_string_data(ptr %right)\n\
           call void @llvm.memcpy.p0.p0.i64(ptr %right_dst, ptr %rd, i64 %rl, i1 false)\n\
           %terminator = getelementptr i8, ptr %data, i64 %sum\n\
           store i8 0, ptr %terminator\n\
           %allocs = load i64, ptr @aether_string_alloc_count\n\
           %allocs_next = add i64 %allocs, 1\n\
           store i64 %allocs_next, ptr @aether_string_alloc_count\n\
           ret ptr %object\n\
         }\n\
         define internal i1 @aether_string_equal(ptr %left, ptr %right) nounwind {\n\
         entry:\n\
           %events = load i64, ptr @aether_string_equal_count\n\
           %events_next = add i64 %events, 1\n\
           store i64 %events_next, ptr @aether_string_equal_count\n\
           %same = icmp eq ptr %left, %right\n\
           br i1 %same, label %yes, label %lengths\n\
         lengths:\n\
           %ll = call i64 @aether_string_length(ptr %left)\n\
           %rl = call i64 @aether_string_length(ptr %right)\n\
           %same_length = icmp eq i64 %ll, %rl\n\
           br i1 %same_length, label %compare, label %no\n\
         compare:\n\
           %empty = icmp eq i64 %ll, 0\n\
           br i1 %empty, label %yes, label %bytes\n\
         bytes:\n\
           %ld = call ptr @aether_string_data(ptr %left)\n\
           %rd = call ptr @aether_string_data(ptr %right)\n\
           %cmp = call i32 @memcmp(ptr %ld, ptr %rd, i64 %ll)\n\
           %equal = icmp eq i32 %cmp, 0\n\
           ret i1 %equal\n\
         yes:\n\
           ret i1 true\n\
         no:\n\
           ret i1 false\n\
         }\n\
         define internal void @aether_string_write(ptr %value, i1 %newline) {\n\
         entry:\n\
           %length = call i64 @aether_string_length(ptr %value)\n\
           %data = call ptr @aether_string_data(ptr %value)\n\
           br label %loop\n\
         loop:\n\
           %offset = phi i64 [ 0, %entry ], [ %next, %wrote ]\n\
           %done = icmp eq i64 %offset, %length\n\
           br i1 %done, label %suffix, label %write_content\n\
         write_content:\n\
           %remaining = sub i64 %length, %offset\n\
           %cursor = getelementptr i8, ptr %data, i64 %offset\n\
           %written = call i64 @write(i32 1, ptr %cursor, i64 %remaining)\n\
           %bad = icmp sle i64 %written, 0\n\
           br i1 %bad, label %trap, label %wrote\n\
         wrote:\n\
           %next = add i64 %offset, %written\n\
           br label %loop\n\
         suffix:\n\
           br i1 %newline, label %write_newline, label %return\n\
         write_newline:\n\
           %nl = call i64 @write(i32 1, ptr @aether_string_newline, i64 1)\n\
           %nl_bad = icmp ne i64 %nl, 1\n\
           br i1 %nl_bad, label %trap, label %return\n\
         return:\n\
           ret void\n\
         trap:\n\
           call void @llvm.trap()\n\
           unreachable\n\
         }\n\n",
    );
    if formatting {
        output.push_str(FORMAT_RUNTIME);
    }
}

const FORMAT_RUNTIME: &str = r#"
; FORMAT C++ to_chars dependency (qualified shortest-decimal engine)
declare { ptr, i32 } @_ZSt8to_charsPcS_fSt12chars_format(ptr, ptr, float, i32) nounwind
declare { ptr, i32 } @_ZSt8to_charsPcS_dSt12chars_format(ptr, ptr, double, i32) nounwind

define internal ptr @aether_string_allocate(i64 %length) {
entry:
  %empty = icmp eq i64 %length, 0
  br i1 %empty, label %empty_result, label %size
empty_result:
  ret ptr @aether_string_empty
size:
  %pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %length, i64 25)
  %total = extractvalue { i64, i1 } %pair, 0
  %overflow = extractvalue { i64, i1 } %pair, 1
  br i1 %overflow, label %trap, label %allocate
allocate:
  %object = call ptr @aether_alloc(i64 %total, i64 8)
  store i64 %length, ptr %object
  %count = getelementptr i8, ptr %object, i64 8
  store i64 1, ptr %count
  %flags = getelementptr i8, ptr %object, i64 16
  store i64 0, ptr %flags
  %data = getelementptr i8, ptr %object, i64 24
  %terminator = getelementptr i8, ptr %data, i64 %length
  store i8 0, ptr %terminator
  %allocs = load i64, ptr @aether_string_alloc_count
  %next = add i64 %allocs, 1
  store i64 %next, ptr @aether_string_alloc_count
  ret ptr %object
trap:
  call void @llvm.trap()
  unreachable
}

define internal ptr @aether_string_from_buffer(ptr %source, i64 %length) {
entry:
  %object = call ptr @aether_string_allocate(i64 %length)
  %empty = icmp eq i64 %length, 0
  br i1 %empty, label %done, label %copy
copy:
  %data = call ptr @aether_string_data(ptr %object)
  call void @llvm.memcpy.p0.p0.i64(ptr %data, ptr %source, i64 %length, i1 false)
  br label %done
done:
  ret ptr %object
}

define internal i64 @aether_format_u64_length(i64 %value) nounwind {
entry:
  br label %loop
loop:
  %v = phi i64 [ %value, %entry ], [ %q, %loop ]
  %n = phi i64 [ 1, %entry ], [ %nn, %loop ]
  %q = udiv i64 %v, 10
  %more = icmp ne i64 %q, 0
  %nn = add i64 %n, 1
  br i1 %more, label %loop, label %done
done:
  ret i64 %n
}

define internal void @aether_format_u64_write(ptr %destination, i64 %value, i64 %length) nounwind {
entry:
  br label %loop
loop:
  %v = phi i64 [ %value, %entry ], [ %q, %loop ]
  %remaining = phi i64 [ %length, %entry ], [ %previous, %loop ]
  %previous = sub i64 %remaining, 1
  %digit = urem i64 %v, 10
  %ascii64 = add i64 %digit, 48
  %ascii = trunc i64 %ascii64 to i8
  %slot = getelementptr i8, ptr %destination, i64 %previous
  store i8 %ascii, ptr %slot
  %q = udiv i64 %v, 10
  %more = icmp ne i64 %previous, 0
  br i1 %more, label %loop, label %done
done:
  ret void
}

define internal i64 @aether_format_i64(ptr %destination, i64 %value) nounwind {
entry:
  %negative = icmp slt i64 %value, 0
  %magnitude = sub i64 0, %value
  %unsigned = select i1 %negative, i64 %magnitude, i64 %value
  %digits = call i64 @aether_format_u64_length(i64 %unsigned)
  %sign = zext i1 %negative to i64
  %length = add i64 %digits, %sign
  br i1 %negative, label %minus, label %write
minus:
  store i8 45, ptr %destination
  br label %write
write:
  %digits_destination = getelementptr i8, ptr %destination, i64 %sign
  call void @aether_format_u64_write(ptr %digits_destination, i64 %unsigned, i64 %digits)
  ret i64 %length
}

define internal i64 @aether_format_u64(ptr %destination, i64 %value) nounwind {
entry:
  %length = call i64 @aether_format_u64_length(i64 %value)
  call void @aether_format_u64_write(ptr %destination, i64 %value, i64 %length)
  ret i64 %length
}

define internal i64 @aether_format_bool(ptr %destination, i1 %value) nounwind {
entry:
  br i1 %value, label %yes, label %no
yes:
  call void @llvm.memcpy.p0.p0.i64(ptr %destination, ptr @aether_format_true, i64 4, i1 false)
  ret i64 4
no:
  call void @llvm.memcpy.p0.p0.i64(ptr %destination, ptr @aether_format_false, i64 5, i1 false)
  ret i64 5
}

define internal i64 @aether_format_char(ptr %destination, i32 %value) nounwind {
entry:
  %too_large = icmp ugt i32 %value, 1114111
  %surrogate_low = icmp uge i32 %value, 55296
  %surrogate_high = icmp ule i32 %value, 57343
  %surrogate = and i1 %surrogate_low, %surrogate_high
  %invalid = or i1 %too_large, %surrogate
  br i1 %invalid, label %trap, label %width
width:
  %one = icmp ule i32 %value, 127
  br i1 %one, label %write1, label %width2
write1:
  %c1 = trunc i32 %value to i8
  store i8 %c1, ptr %destination
  ret i64 1
width2:
  %two = icmp ule i32 %value, 2047
  br i1 %two, label %write2, label %width3
write2:
  %h2 = lshr i32 %value, 6
  %b20 = or i32 %h2, 192
  %b21m = and i32 %value, 63
  %b21 = or i32 %b21m, 128
  %b20x = trunc i32 %b20 to i8
  %b21x = trunc i32 %b21 to i8
  store i8 %b20x, ptr %destination
  %p21 = getelementptr i8, ptr %destination, i64 1
  store i8 %b21x, ptr %p21
  ret i64 2
width3:
  %three = icmp ule i32 %value, 65535
  br i1 %three, label %write3, label %write4
write3:
  %h30 = lshr i32 %value, 12
  %b30 = or i32 %h30, 224
  %h31 = lshr i32 %value, 6
  %m31 = and i32 %h31, 63
  %b31 = or i32 %m31, 128
  %m32 = and i32 %value, 63
  %b32 = or i32 %m32, 128
  %b30x = trunc i32 %b30 to i8
  %b31x = trunc i32 %b31 to i8
  %b32x = trunc i32 %b32 to i8
  store i8 %b30x, ptr %destination
  %p31 = getelementptr i8, ptr %destination, i64 1
  store i8 %b31x, ptr %p31
  %p32 = getelementptr i8, ptr %destination, i64 2
  store i8 %b32x, ptr %p32
  ret i64 3
write4:
  %h40 = lshr i32 %value, 18
  %b40 = or i32 %h40, 240
  %h41 = lshr i32 %value, 12
  %m41 = and i32 %h41, 63
  %b41 = or i32 %m41, 128
  %h42 = lshr i32 %value, 6
  %m42 = and i32 %h42, 63
  %b42 = or i32 %m42, 128
  %m43 = and i32 %value, 63
  %b43 = or i32 %m43, 128
  %b40x = trunc i32 %b40 to i8
  %b41x = trunc i32 %b41 to i8
  %b42x = trunc i32 %b42 to i8
  %b43x = trunc i32 %b43 to i8
  store i8 %b40x, ptr %destination
  %p41 = getelementptr i8, ptr %destination, i64 1
  store i8 %b41x, ptr %p41
  %p42 = getelementptr i8, ptr %destination, i64 2
  store i8 %b42x, ptr %p42
  %p43 = getelementptr i8, ptr %destination, i64 3
  store i8 %b43x, ptr %p43
  ret i64 4
trap:
  call void @llvm.trap()
  unreachable
}
@aether_format_true = private constant [4 x i8] c"true"
@aether_format_false = private constant [5 x i8] c"false"
@aether_format_nan = private constant [3 x i8] c"NaN"
@aether_format_inf = private constant [3 x i8] c"Inf"
@aether_format_ninf = private constant [4 x i8] c"-Inf"
@aether_format_zero = private constant [1 x i8] c"0"
@aether_format_nzero = private constant [2 x i8] c"-0"

define internal i64 @aether_normalize_float(ptr %destination, ptr %source, i64 %length) nounwind {
entry:
  %digits = alloca [32 x i8], align 1
  %first = load i8, ptr %source
  %negative = icmp eq i8 %first, 45
  %start = select i1 %negative, i64 1, i64 0
  br label %scan
scan:
  %i = phi i64 [ %start, %entry ], [ %inext, %scan_next ]
  %count = phi i64 [ 0, %entry ], [ %count_next, %scan_next ]
  %chp = getelementptr i8, ptr %source, i64 %i
  %ch = load i8, ptr %chp
  %is_e = icmp eq i8 %ch, 101
  br i1 %is_e, label %parse_exp, label %scan_digit
scan_digit:
  %is_dot = icmp eq i8 %ch, 46
  br i1 %is_dot, label %scan_next, label %save_digit
save_digit:
  %dp = getelementptr [32 x i8], ptr %digits, i64 0, i64 %count
  store i8 %ch, ptr %dp
  %saved_count = add i64 %count, 1
  br label %scan_next
scan_next:
  %count_next = phi i64 [ %count, %scan_digit ], [ %saved_count, %save_digit ]
  %inext = add i64 %i, 1
  br label %scan
parse_exp:
  %sign_index = add i64 %i, 1
  %sign_ptr = getelementptr i8, ptr %source, i64 %sign_index
  %sign_char = load i8, ptr %sign_ptr
  %exp_negative = icmp eq i8 %sign_char, 45
  %exp_start = add i64 %i, 2
  br label %exp_loop
exp_loop:
  %ei = phi i64 [ %exp_start, %parse_exp ], [ %ei_next, %exp_body ]
  %exp_value = phi i64 [ 0, %parse_exp ], [ %exp_next, %exp_body ]
  %exp_done = icmp eq i64 %ei, %length
  br i1 %exp_done, label %choose, label %exp_body
exp_body:
  %ecp = getelementptr i8, ptr %source, i64 %ei
  %ec = load i8, ptr %ecp
  %ed = sub i8 %ec, 48
  %ed64 = zext i8 %ed to i64
  %exp_ten = mul i64 %exp_value, 10
  %exp_next = add i64 %exp_ten, %ed64
  %ei_next = add i64 %ei, 1
  br label %exp_loop
choose:
  %signed_negative = sub i64 0, %exp_value
  %exponent = select i1 %exp_negative, i64 %signed_negative, i64 %exp_value
  %fixed_low = icmp sge i64 %exponent, -6
  %fixed_high = icmp slt i64 %exponent, 21
  %fixed = and i1 %fixed_low, %fixed_high
  %sign_len = zext i1 %negative to i64
  br i1 %negative, label %write_minus, label %notation
write_minus:
  store i8 45, ptr %destination
  br label %notation
notation:
  br i1 %fixed, label %fixed_notation, label %scientific
fixed_notation:
  %nonnegative = icmp sge i64 %exponent, 0
  br i1 %nonnegative, label %fixed_integer, label %fixed_fraction
fixed_integer:
  %integer_count = add i64 %exponent, 1
  br label %integer_loop
integer_loop:
  %ii = phi i64 [ 0, %fixed_integer ], [ %ii_next, %integer_store ]
  %integer_done = icmp eq i64 %ii, %integer_count
  br i1 %integer_done, label %integer_suffix, label %integer_store
integer_store:
  %has_digit = icmp ult i64 %ii, %count
  %idp = getelementptr [32 x i8], ptr %digits, i64 0, i64 %ii
  %id = load i8, ptr %idp
  %out_digit = select i1 %has_digit, i8 %id, i8 48
  %io = add i64 %sign_len, %ii
  %iop = getelementptr i8, ptr %destination, i64 %io
  store i8 %out_digit, ptr %iop
  %ii_next = add i64 %ii, 1
  br label %integer_loop
integer_suffix:
  %has_fraction = icmp ugt i64 %count, %integer_count
  br i1 %has_fraction, label %fraction_dot, label %fixed_integer_done
fraction_dot:
  %dot_at = add i64 %sign_len, %integer_count
  %dot_ptr = getelementptr i8, ptr %destination, i64 %dot_at
  store i8 46, ptr %dot_ptr
  br label %fraction_loop
fraction_loop:
  %fi = phi i64 [ %integer_count, %fraction_dot ], [ %fi_next, %fraction_copy ]
  %fi_done = icmp eq i64 %fi, %count
  br i1 %fi_done, label %fixed_fraction_done, label %fraction_copy
fraction_copy:
  %fdp = getelementptr [32 x i8], ptr %digits, i64 0, i64 %fi
  %fd = load i8, ptr %fdp
  %fo_base = add i64 %sign_len, 1
  %fo = add i64 %fo_base, %fi
  %fop = getelementptr i8, ptr %destination, i64 %fo
  store i8 %fd, ptr %fop
  %fi_next = add i64 %fi, 1
  br label %fraction_loop
fixed_integer_done:
  %integer_length = add i64 %sign_len, %integer_count
  ret i64 %integer_length
fixed_fraction_done:
  %fraction_length_base = add i64 %sign_len, %count
  %fraction_length = add i64 %fraction_length_base, 1
  ret i64 %fraction_length
fixed_fraction:
  %zero_at = getelementptr i8, ptr %destination, i64 %sign_len
  store i8 48, ptr %zero_at
  %dot_index = add i64 %sign_len, 1
  %fixed_dot = getelementptr i8, ptr %destination, i64 %dot_index
  store i8 46, ptr %fixed_dot
  %negexp = sub i64 0, %exponent
  %zero_count = sub i64 %negexp, 1
  br label %zero_loop
zero_loop:
  %zi = phi i64 [ 0, %fixed_fraction ], [ %zi_next, %zero_store ]
  %zero_done = icmp eq i64 %zi, %zero_count
  br i1 %zero_done, label %small_digits, label %zero_store
zero_store:
  %zo_base = add i64 %sign_len, 2
  %zo = add i64 %zo_base, %zi
  %zop = getelementptr i8, ptr %destination, i64 %zo
  store i8 48, ptr %zop
  %zi_next = add i64 %zi, 1
  br label %zero_loop
small_digits:
  br label %small_loop
small_loop:
  %si = phi i64 [ 0, %small_digits ], [ %si_next, %small_copy ]
  %small_done = icmp eq i64 %si, %count
  br i1 %small_done, label %small_return, label %small_copy
small_copy:
  %sdp = getelementptr [32 x i8], ptr %digits, i64 0, i64 %si
  %sd = load i8, ptr %sdp
  %so_base0 = add i64 %sign_len, 2
  %so_base = add i64 %so_base0, %zero_count
  %so = add i64 %so_base, %si
  %sop = getelementptr i8, ptr %destination, i64 %so
  store i8 %sd, ptr %sop
  %si_next = add i64 %si, 1
  br label %small_loop
small_return:
  %small_base = add i64 %sign_len, 2
  %small_zeros = add i64 %small_base, %zero_count
  %small_length = add i64 %small_zeros, %count
  ret i64 %small_length
scientific:
  %d0p = getelementptr [32 x i8], ptr %digits, i64 0, i64 0
  %d0 = load i8, ptr %d0p
  %d0out = getelementptr i8, ptr %destination, i64 %sign_len
  store i8 %d0, ptr %d0out
  %many = icmp ugt i64 %count, 1
  %dot_extra = zext i1 %many to i64
  br i1 %many, label %sci_dot, label %sci_e
sci_dot:
  %sdot_i = add i64 %sign_len, 1
  %sdot = getelementptr i8, ptr %destination, i64 %sdot_i
  store i8 46, ptr %sdot
  br label %sci_digits
sci_digits:
  %sci_i = phi i64 [ 1, %sci_dot ], [ %sci_next, %sci_copy ]
  %sci_done = icmp eq i64 %sci_i, %count
  br i1 %sci_done, label %sci_e, label %sci_copy
sci_copy:
  %scidp = getelementptr [32 x i8], ptr %digits, i64 0, i64 %sci_i
  %scid = load i8, ptr %scidp
  %scio_base = add i64 %sign_len, 1
  %scio = add i64 %scio_base, %sci_i
  %sciop = getelementptr i8, ptr %destination, i64 %scio
  store i8 %scid, ptr %sciop
  %sci_next = add i64 %sci_i, 1
  br label %sci_digits
sci_e:
  %mantissa_len0 = add i64 %sign_len, %count
  %mantissa_len = add i64 %mantissa_len0, %dot_extra
  %ep = getelementptr i8, ptr %destination, i64 %mantissa_len
  store i8 101, ptr %ep
  %es_i = add i64 %mantissa_len, 1
  %esp = getelementptr i8, ptr %destination, i64 %es_i
  %esign = select i1 %exp_negative, i8 45, i8 43
  store i8 %esign, ptr %esp
  %hundreds = icmp uge i64 %exp_value, 100
  %tens = icmp uge i64 %exp_value, 10
  %below_hundred_digits = select i1 %tens, i64 2, i64 1
  %exp_digits2 = select i1 %hundreds, i64 3, i64 %below_hundred_digits
  %exp_out = add i64 %mantissa_len, 2
  %exp_destination = getelementptr i8, ptr %destination, i64 %exp_out
  call void @aether_format_u64_write(ptr %exp_destination, i64 %exp_value, i64 %exp_digits2)
  %sci_len = add i64 %exp_out, %exp_digits2
  ret i64 %sci_len
}

define internal i64 @aether_format_f32(ptr %destination, float %value) nounwind {
entry:
  %bits = bitcast float %value to i32
  %absbits = and i32 %bits, 2147483647
  %nan = icmp ugt i32 %absbits, 2139095040
  br i1 %nan, label %nan_case, label %inf_test
nan_case:
  call void @llvm.memcpy.p0.p0.i64(ptr %destination, ptr @aether_format_nan, i64 3, i1 false)
  ret i64 3
inf_test:
  %inf = icmp eq i32 %absbits, 2139095040
  %negative = icmp slt i32 %bits, 0
  br i1 %inf, label %inf_case, label %zero_test
inf_case:
  br i1 %negative, label %ninf, label %pinf
ninf:
  call void @llvm.memcpy.p0.p0.i64(ptr %destination, ptr @aether_format_ninf, i64 4, i1 false)
  ret i64 4
pinf:
  call void @llvm.memcpy.p0.p0.i64(ptr %destination, ptr @aether_format_inf, i64 3, i1 false)
  ret i64 3
zero_test:
  %zero = icmp eq i32 %absbits, 0
  br i1 %zero, label %zero_case, label %finite
zero_case:
  br i1 %negative, label %nzero, label %pzero
nzero:
  call void @llvm.memcpy.p0.p0.i64(ptr %destination, ptr @aether_format_nzero, i64 2, i1 false)
  ret i64 2
pzero:
  store i8 48, ptr %destination
  ret i64 1
finite:
  %raw = alloca [64 x i8], align 1
  %end = getelementptr [64 x i8], ptr %raw, i64 0, i64 64
  %result = call { ptr, i32 } @_ZSt8to_charsPcS_fSt12chars_format(ptr %raw, ptr %end, float %value, i32 1)
  %finish = extractvalue { ptr, i32 } %result, 0
  %rawlen = ptrtoint ptr %finish to i64
  %rawstart = ptrtoint ptr %raw to i64
  %length = sub i64 %rawlen, %rawstart
  %normalized = call i64 @aether_normalize_float(ptr %destination, ptr %raw, i64 %length)
  ret i64 %normalized
}

define internal i64 @aether_format_f64(ptr %destination, double %value) nounwind {
entry:
  %bits = bitcast double %value to i64
  %absbits = and i64 %bits, 9223372036854775807
  %nan = icmp ugt i64 %absbits, 9218868437227405312
  br i1 %nan, label %nan_case, label %inf_test
nan_case:
  call void @llvm.memcpy.p0.p0.i64(ptr %destination, ptr @aether_format_nan, i64 3, i1 false)
  ret i64 3
inf_test:
  %inf = icmp eq i64 %absbits, 9218868437227405312
  %negative = icmp slt i64 %bits, 0
  br i1 %inf, label %inf_case, label %zero_test
inf_case:
  br i1 %negative, label %ninf, label %pinf
ninf:
  call void @llvm.memcpy.p0.p0.i64(ptr %destination, ptr @aether_format_ninf, i64 4, i1 false)
  ret i64 4
pinf:
  call void @llvm.memcpy.p0.p0.i64(ptr %destination, ptr @aether_format_inf, i64 3, i1 false)
  ret i64 3
zero_test:
  %zero = icmp eq i64 %absbits, 0
  br i1 %zero, label %zero_case, label %finite
zero_case:
  br i1 %negative, label %nzero, label %pzero
nzero:
  call void @llvm.memcpy.p0.p0.i64(ptr %destination, ptr @aether_format_nzero, i64 2, i1 false)
  ret i64 2
pzero:
  store i8 48, ptr %destination
  ret i64 1
finite:
  %raw = alloca [64 x i8], align 1
  %end = getelementptr [64 x i8], ptr %raw, i64 0, i64 64
  %result = call { ptr, i32 } @_ZSt8to_charsPcS_dSt12chars_format(ptr %raw, ptr %end, double %value, i32 1)
  %finish = extractvalue { ptr, i32 } %result, 0
  %rawlen = ptrtoint ptr %finish to i64
  %rawstart = ptrtoint ptr %raw to i64
  %length = sub i64 %rawlen, %rawstart
  %normalized = call i64 @aether_normalize_float(ptr %destination, ptr %raw, i64 %length)
  ret i64 %normalized
}
"#;

pub(super) fn emit_op(
    output: &mut String,
    op: &StringOp<SsaOperand>,
    result: u32,
    types: &TypeArena,
    operand: impl Fn(&SsaOperand) -> String,
) {
    match op {
        StringOp::Literal { bytes } => {
            writeln!(
                output,
                "  %v{result} = getelementptr i8, ptr @{}, i64 0",
                literal_name(bytes)
            )
            .unwrap();
        }
        StringOp::Alias { source } => {
            let source = operand(source);
            writeln!(output, "  call void @aether_string_retain(ptr {source})").unwrap();
            writeln!(
                output,
                "  %v{result} = select i1 true, ptr {source}, ptr {source}"
            )
            .unwrap();
        }
        StringOp::Concat { left, right } => {
            writeln!(
                output,
                "  %v{result} = call ptr @aether_string_concat(ptr {}, ptr {})",
                operand(left),
                operand(right)
            )
            .unwrap();
        }
        StringOp::Equal {
            left,
            right,
            negate,
        } => {
            let name = if *negate {
                format!("%string_eq{result}")
            } else {
                format!("%v{result}")
            };
            writeln!(
                output,
                "  {name} = call i1 @aether_string_equal(ptr {}, ptr {})",
                operand(left),
                operand(right)
            )
            .unwrap();
            if *negate {
                writeln!(output, "  %v{result} = xor i1 {name}, true").unwrap();
            }
        }
        StringOp::ByteLength { source } => {
            writeln!(
                output,
                "  %v{result} = call i64 @aether_string_length(ptr {})",
                operand(source)
            )
            .unwrap();
        }
        StringOp::Output { source, newline } => {
            writeln!(
                output,
                "  call void @aether_string_write(ptr {}, i1 {})",
                operand(source),
                newline
            )
            .unwrap();
            writeln!(output, "  %v{result} = select i1 true, i1 true, i1 true").unwrap();
        }
        StringOp::Interpolate { fragments, .. } => {
            emit_interpolation(output, fragments, result, types, operand);
        }
    }
}

fn scalar_formatter(
    types: &TypeArena,
    ty: aether_frontend::TypeId,
) -> (&'static str, &'static str) {
    match types.get(ty).expect("verified interpolation scalar") {
        TypeData::Bool => ("aether_format_bool", "i1"),
        TypeData::Char => ("aether_format_char", "i32"),
        TypeData::Integer(integer) if integer.is_signed() => ("aether_format_i64", "i64"),
        TypeData::Integer(_) => ("aether_format_u64", "i64"),
        TypeData::Float(FloatType::Float32) => ("aether_format_f32", "float"),
        TypeData::Float(FloatType::Float64) => ("aether_format_f64", "double"),
        _ => unreachable!("verified interpolation conversion"),
    }
}

fn widened_scalar_operand(
    output: &mut String,
    types: &TypeArena,
    ty: aether_frontend::TypeId,
    value: &str,
    name: &str,
) -> String {
    let Some(integer) = types.integer_info(ty) else {
        return value.into();
    };
    let bits = integer.bits(aether_frontend::TargetProperties::LINUX_X86_64);
    if bits == 64 {
        return value.into();
    }
    let extension = if integer.is_signed() { "sext" } else { "zext" };
    writeln!(output, "  %{name} = {extension} i{bits} {value} to i64").unwrap();
    format!("%{name}")
}

fn emit_interpolation(
    output: &mut String,
    fragments: &[InterpolationFragment<SsaOperand>],
    result: u32,
    types: &TypeArena,
    operand: impl Fn(&SsaOperand) -> String,
) {
    for (index, fragment) in fragments.iter().enumerate() {
        if let InterpolationFragment::Hole { value, ty, .. } = fragment {
            if *ty == aether_frontend::TypeId::STRING {
                writeln!(
                    output,
                    "  %fmt_len{result}_{index} = call i64 @aether_string_length(ptr {})",
                    operand(value)
                )
                .unwrap();
            } else {
                writeln!(
                    output,
                    "  %fmt_buf{result}_{index} = alloca [128 x i8], align 8"
                )
                .unwrap();
                let (formatter, llvm_ty) = scalar_formatter(types, *ty);
                let value = widened_scalar_operand(
                    output,
                    types,
                    *ty,
                    &operand(value),
                    &format!("fmt_wide{result}_{index}"),
                );
                writeln!(output, "  %fmt_len{result}_{index} = call i64 @{formatter}(ptr %fmt_buf{result}_{index}, {llvm_ty} {value})").unwrap();
            }
        }
    }
    writeln!(output, "  %fmt_total{result}_0 = add i64 0, 0").unwrap();
    for (index, fragment) in fragments.iter().enumerate() {
        let length = match fragment {
            InterpolationFragment::Text { bytes, .. } => bytes.len().to_string(),
            InterpolationFragment::Hole { .. } => format!("%fmt_len{result}_{index}"),
        };
        writeln!(output, "  %fmt_sum{result}_{index} = call {{ i64, i1 }} @llvm.uadd.with.overflow.i64(i64 %fmt_total{result}_{index}, i64 {length})").unwrap();
        writeln!(
            output,
            "  %fmt_total{result}_{} = extractvalue {{ i64, i1 }} %fmt_sum{result}_{index}, 0",
            index + 1
        )
        .unwrap();
        writeln!(output, "  %fmt_overflow{result}_{index} = extractvalue {{ i64, i1 }} %fmt_sum{result}_{index}, 1").unwrap();
        writeln!(output, "  br i1 %fmt_overflow{result}_{index}, label %fmt_trap{result}, label %fmt_size_ok{result}_{index}").unwrap();
        writeln!(output, "fmt_size_ok{result}_{index}:").unwrap();
    }
    let total = format!("%fmt_total{result}_{}", fragments.len());
    writeln!(
        output,
        "  %v{result} = call ptr @aether_string_allocate(i64 {total})"
    )
    .unwrap();
    writeln!(
        output,
        "  %fmt_build{result} = call ptr @aether_string_data(ptr %v{result})"
    )
    .unwrap();
    writeln!(output, "  %fmt_offset{result}_0 = add i64 0, 0").unwrap();
    for (index, fragment) in fragments.iter().enumerate() {
        let (source, length) = match fragment {
            InterpolationFragment::Text { bytes, .. } => (
                format!("getelementptr (i8, ptr @{}, i64 24)", literal_name(bytes)),
                bytes.len().to_string(),
            ),
            InterpolationFragment::Hole { value, ty, .. }
                if *ty == aether_frontend::TypeId::STRING =>
            {
                writeln!(
                    output,
                    "  %fmt_src{result}_{index} = call ptr @aether_string_data(ptr {})",
                    operand(value)
                )
                .unwrap();
                (
                    format!("%fmt_src{result}_{index}"),
                    format!("%fmt_len{result}_{index}"),
                )
            }
            InterpolationFragment::Hole { .. } => (
                format!("%fmt_buf{result}_{index}"),
                format!("%fmt_len{result}_{index}"),
            ),
        };
        writeln!(output, "  %fmt_dst{result}_{index} = getelementptr i8, ptr %fmt_build{result}, i64 %fmt_offset{result}_{index}").unwrap();
        writeln!(output, "  call void @llvm.memcpy.p0.p0.i64(ptr %fmt_dst{result}_{index}, ptr {source}, i64 {length}, i1 false)").unwrap();
        writeln!(
            output,
            "  %fmt_offset{result}_{} = add i64 %fmt_offset{result}_{index}, {length}",
            index + 1
        )
        .unwrap();
    }
    writeln!(output, "  br label %fmt_done{result}").unwrap();
    writeln!(output, "fmt_trap{result}:").unwrap();
    writeln!(output, "  call void @llvm.trap()").unwrap();
    writeln!(output, "  unreachable").unwrap();
    writeln!(output, "fmt_done{result}:").unwrap();
}
