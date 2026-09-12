//! Private GENERAL-V1 string runtime ABI and lowering.

use std::collections::BTreeSet;
use std::fmt::Write;

use aether_frontend::StringOp;
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
        if let SsaOp::String(op) = &instruction.op
            && let StringOp::Literal { bytes } = op.as_ref()
        {
            literals.insert(bytes.clone());
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
pub(super) fn runtime(output: &mut String) {
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
}

pub(super) fn emit_op(
    output: &mut String,
    op: &StringOp<SsaOperand>,
    result: u32,
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
    }
}
