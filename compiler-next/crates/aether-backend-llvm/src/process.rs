//! Private PROCESS-ARGS-V1 POSIX boundary for the ordinary `std.Process.args` call.

use std::fmt::Write;

use aether_frontend::{
    EnumInfo, FunctionInstanceInfo, ModuleInfo, OriginKey, PackageKey, StructInfo, TypeArena,
    TypeData,
};
use aether_middle::SsaFunction;

use crate::{bootstrap_symbol, mangle_type};

pub(super) fn is_args(
    signature: &FunctionInstanceInfo,
    modules: &[ModuleInfo],
    types: &TypeArena,
) -> bool {
    let package = &modules[signature.module.0 as usize].key.package;
    matches!(
        package,
        PackageKey::Named { origin: OriginKey::Toolchain, path }
            if path.0.as_slice() == ["std", "Process"]
                && signature.name == "args"
                && signature.parameters.is_empty()
                && matches!(types.get(signature.return_type), Some(TypeData::Array { element }) if *element == aether_frontend::TypeId::STRING)
    )
}

#[allow(clippy::too_many_arguments)]
pub(super) fn emit_function(
    output: &mut String,
    _function: &SsaFunction,
    signature: &FunctionInstanceInfo,
    modules: &[ModuleInfo],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
) {
    let symbol = bootstrap_symbol(signature, modules, structs, enums, types);
    let exception = types
        .classes()
        .iter()
        .find(|class| {
            class.name == "InvalidArgumentEncodingException"
                && matches!(
                    &modules[class.module.0 as usize].key.package,
                    PackageKey::Named { origin: OriginKey::Toolchain, path }
                        if path.0.as_slice() == ["std", "Process"]
                )
        })
        .expect("PROCESS-ARGS-V1 exception is present")
        .id;
    writeln!(
        output,
        "define {{ ptr, i64 }} @{symbol}() {{\nentry:\n  %raw = call {{ i1, {{ ptr, i64 }} }} @aether_process_args()\n  %invalid = extractvalue {{ i1, {{ ptr, i64 }} }} %raw, 0\n  br i1 %invalid, label %encoding, label %return\nreturn:\n  %value = extractvalue {{ i1, {{ ptr, i64 }} }} %raw, 1\n  ret {{ ptr, i64 }} %value\nencoding:\n  %exception = call ptr @aether_object_alloc_{}()\n  call void @aether_throw(ptr %exception)\n  unreachable\n}}\n",
        exception.0
    )
    .unwrap();
}

#[allow(clippy::too_many_lines)]
pub(super) fn runtime(output: &mut String, types: &TypeArena) {
    let string_suffix = mangle_type(types, aether_frontend::TypeId::STRING);
    writeln!(
        output,
        r"@aether_process_snapshot_entries = internal global ptr null
@aether_process_snapshot_count = internal global i64 0
declare i64 @strlen(ptr) nounwind

define internal void @aether_process_snapshot_init(i32 %argc, ptr %argv) {{
entry:
  %negative = icmp slt i32 %argc, 0
  br i1 %negative, label %trap, label %count
count:
  %argc64 = zext i32 %argc to i64
  %positive = icmp ugt i64 %argc64, 0
  %argv_null = icmp eq ptr %argv, null
  %bad_vector = and i1 %positive, %argv_null
  br i1 %bad_vector, label %trap, label %derive
derive:
  %has_user = icmp ugt i64 %argc64, 1
  %user_count = select i1 %has_user, i64 %argc64, i64 1
  %count_value = sub i64 %user_count, 1
  %size_pair = call {{ i64, i1 }} @llvm.umul.with.overflow.i64(i64 %count_value, i64 16)
  %size = extractvalue {{ i64, i1 }} %size_pair, 0
  %overflow = extractvalue {{ i64, i1 }} %size_pair, 1
  br i1 %overflow, label %trap, label %empty_test
empty_test:
  %empty = icmp eq i64 %count_value, 0
  br i1 %empty, label %publish_empty, label %allocate
allocate:
  %entries = call ptr @malloc(i64 %size)
  %allocation_failed = icmp eq ptr %entries, null
  br i1 %allocation_failed, label %trap, label %loop
loop:
  %index = phi i64 [ 0, %allocate ], [ %next, %copied ]
  %done = icmp eq i64 %index, %count_value
  br i1 %done, label %publish, label %load
load:
  %host_index = add i64 %index, 1
  %host_slot = getelementptr ptr, ptr %argv, i64 %host_index
  %host = load ptr, ptr %host_slot
  %host_null = icmp eq ptr %host, null
  br i1 %host_null, label %trap, label %measure
measure:
  %length = call i64 @strlen(ptr %host)
  %is_empty = icmp eq i64 %length, 0
  %copy_size = select i1 %is_empty, i64 1, i64 %length
  %copy = call ptr @malloc(i64 %copy_size)
  %copy_failed = icmp eq ptr %copy, null
  br i1 %copy_failed, label %trap, label %copy_bytes
copy_bytes:
  call void @llvm.memcpy.p0.p0.i64(ptr %copy, ptr %host, i64 %length, i1 false)
  %snapshot_item = getelementptr {{ ptr, i64 }}, ptr %entries, i64 %index
  %entry_data = getelementptr {{ ptr, i64 }}, ptr %snapshot_item, i32 0, i32 0
  store ptr %copy, ptr %entry_data
  %entry_length = getelementptr {{ ptr, i64 }}, ptr %snapshot_item, i32 0, i32 1
  store i64 %length, ptr %entry_length
  br label %copied
copied:
  %next = add i64 %index, 1
  br label %loop
publish:
  store ptr %entries, ptr @aether_process_snapshot_entries
  store i64 %count_value, ptr @aether_process_snapshot_count
  ret void
publish_empty:
  store ptr null, ptr @aether_process_snapshot_entries
  store i64 0, ptr @aether_process_snapshot_count
  ret void
trap:
  call void @llvm.trap()
  unreachable
}}

define internal void @aether_process_snapshot_dispose() nounwind {{
entry:
  %entries = load ptr, ptr @aether_process_snapshot_entries
  %count = load i64, ptr @aether_process_snapshot_count
  br label %loop
loop:
  %index = phi i64 [ 0, %entry ], [ %next, %body ]
  %done = icmp eq i64 %index, %count
  br i1 %done, label %finish, label %body
body:
  %entry_ptr = getelementptr {{ ptr, i64 }}, ptr %entries, i64 %index
  %data_ptr = getelementptr {{ ptr, i64 }}, ptr %entry_ptr, i32 0, i32 0
  %data = load ptr, ptr %data_ptr
  call void @free(ptr %data)
  %next = add i64 %index, 1
  br label %loop
finish:
  call void @free(ptr %entries)
  store ptr null, ptr @aether_process_snapshot_entries
  store i64 0, ptr @aether_process_snapshot_count
  ret void
}}

define internal {{ i1, {{ ptr, i64 }} }} @aether_process_args() {{
entry:
  %count = load i64, ptr @aether_process_snapshot_count
  %snapshot = load ptr, ptr @aether_process_snapshot_entries
  %array = call {{ ptr, i64 }} @aether_fixed_new_{string_suffix}(i64 %count)
  %array_data = extractvalue {{ ptr, i64 }} %array, 0
  br label %loop
loop:
  %index = phi i64 [ 0, %entry ], [ %next, %store ]
  %done = icmp eq i64 %index, %count
  br i1 %done, label %success, label %load
load:
  %snapshot_entry = getelementptr {{ ptr, i64 }}, ptr %snapshot, i64 %index
  %snapshot_data_ptr = getelementptr {{ ptr, i64 }}, ptr %snapshot_entry, i32 0, i32 0
  %snapshot_length_ptr = getelementptr {{ ptr, i64 }}, ptr %snapshot_entry, i32 0, i32 1
  %data = load ptr, ptr %snapshot_data_ptr
  %length = load i64, ptr %snapshot_length_ptr
  %utf8 = call i1 @aether_utf8_validate(ptr %data, i64 %length)
  br i1 %utf8, label %convert, label %cleanup
convert:
  %string = call ptr @aether_string_from_buffer(ptr %data, i64 %length)
  br label %store
store:
  %slot = getelementptr ptr, ptr %array_data, i64 %index
  store ptr %string, ptr %slot
  %next = add i64 %index, 1
  br label %loop
success:
  %success0 = insertvalue {{ i1, {{ ptr, i64 }} }} poison, i1 false, 0
  %success_value = insertvalue {{ i1, {{ ptr, i64 }} }} %success0, {{ ptr, i64 }} %array, 1
  ret {{ i1, {{ ptr, i64 }} }} %success_value
cleanup:
  br label %cleanup_loop
cleanup_loop:
  %remaining = phi i64 [ %index, %cleanup ], [ %previous, %cleanup_body ]
  %cleanup_done = icmp eq i64 %remaining, 0
  br i1 %cleanup_done, label %free_array, label %cleanup_body
cleanup_body:
  %previous = sub i64 %remaining, 1
  %initialized_slot = getelementptr ptr, ptr %array_data, i64 %previous
  %initialized = load ptr, ptr %initialized_slot
  call void @aether_string_release(ptr %initialized)
  br label %cleanup_loop
free_array:
  %array_size = mul i64 %count, 8
  call void @aether_free(ptr %array_data, i64 %array_size, i64 8)
  %failure = insertvalue {{ i1, {{ ptr, i64 }} }} zeroinitializer, i1 true, 0
  ret {{ i1, {{ ptr, i64 }} }} %failure
}}
"
    )
    .unwrap();
}
