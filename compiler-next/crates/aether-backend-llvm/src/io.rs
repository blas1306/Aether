//! Private IO-V1 POSIX boundary and lowering for ordinary std functions.

use std::fmt::Write;

use aether_frontend::{
    ClassId, EnumInfo, FunctionInstanceInfo, ModuleInfo, OriginKey, PackageKey, StructInfo,
    TypeArena,
};
use aether_middle::SsaFunction;

use crate::{bootstrap_symbol, llvm_type};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum IoFunction {
    ReadLine,
    Eprint { newline: bool },
    ReadText,
    WriteText,
    WriteTextAtomic,
}

pub(super) fn function_kind(
    signature: &FunctionInstanceInfo,
    modules: &[ModuleInfo],
) -> Option<IoFunction> {
    let package = &modules[signature.module.0 as usize].key.package;
    let PackageKey::Named { origin, path } = package else {
        return None;
    };
    if *origin != OriginKey::Toolchain {
        return None;
    }
    match (path.0.as_slice(), signature.name.as_str()) {
        ([a, b], "readLine") if a == "std" && b == "IO" => Some(IoFunction::ReadLine),
        ([a, b], "eprint") if a == "std" && b == "IO" => {
            Some(IoFunction::Eprint { newline: false })
        }
        ([a, b], "eprintln") if a == "std" && b == "IO" => {
            Some(IoFunction::Eprint { newline: true })
        }
        ([a, b], "readText") if a == "std" && b == "File" => Some(IoFunction::ReadText),
        ([a, b], "writeText") if a == "std" && b == "File" => Some(IoFunction::WriteText),
        ([a, b], "writeTextAtomic") if a == "std" && b == "File" => {
            Some(IoFunction::WriteTextAtomic)
        }
        _ => None,
    }
}

pub(super) fn find_class_id(
    types: &TypeArena,
    modules: &[ModuleInfo],
    package: &str,
    name: &str,
) -> Option<ClassId> {
    types
        .classes()
        .iter()
        .find(|class| {
            class.name == name
                && matches!(
                    &modules[class.module.0 as usize].key.package,
                    PackageKey::Named { origin: OriginKey::Toolchain, path }
                        if path.0.join(".") == package
                )
        })
        .map(|class| class.id)
}

pub(super) fn class_id(
    types: &TypeArena,
    modules: &[ModuleInfo],
    package: &str,
    name: &str,
) -> ClassId {
    find_class_id(types, modules, package, name)
        .unwrap_or_else(|| panic!("missing IO-V1 class {package}.{name}"))
}

#[allow(clippy::too_many_arguments)]
pub(super) fn emit_function(
    output: &mut String,
    kind: IoFunction,
    function: &SsaFunction,
    signature: &FunctionInstanceInfo,
    modules: &[ModuleInfo],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
) {
    let symbol = bootstrap_symbol(signature, modules, structs, enums, types);
    let io = class_id(types, modules, "std.IO", "IOException");
    let encoding = find_class_id(types, modules, "std.IO", "InvalidTextEncodingException");
    let not_found = find_class_id(types, modules, "std.File", "FileNotFoundException");
    let denied = find_class_id(types, modules, "std.File", "PermissionDeniedException");
    let throw = |output: &mut String, label: &str, class: ClassId| {
        writeln!(output, "{label}:").unwrap();
        writeln!(
            output,
            "  %exception_{label} = call ptr @aether_object_alloc_{}()",
            class.0
        )
        .unwrap();
        writeln!(output, "  call void @aether_throw(ptr %exception_{label})").unwrap();
        writeln!(output, "  unreachable").unwrap();
    };
    match kind {
        IoFunction::Eprint { newline } => {
            let value = function.parameters[0].value.0;
            writeln!(output, "define i1 @{symbol}(ptr %v{value}) {{\nentry:").unwrap();
            writeln!(output, "  %string = load ptr, ptr %v{value}").unwrap();
            writeln!(
                output,
                "  %status = call i32 @aether_io_write_string(i32 2, ptr %string, i1 {newline})"
            )
            .unwrap();
            output.push_str("  %ok = icmp eq i32 %status, 0\n  br i1 %ok, label %return, label %io_error\nreturn:\n  ret i1 false\n");
            throw(output, "io_error", io);
            output.push_str("}\n\n");
        }
        IoFunction::WriteText | IoFunction::WriteTextAtomic => {
            let path = function.parameters[0].value.0;
            let value = function.parameters[1].value.0;
            writeln!(
                output,
                "define i1 @{symbol}(ptr %v{path}, ptr %v{value}) {{\nentry:"
            )
            .unwrap();
            let helper = if kind == IoFunction::WriteTextAtomic {
                "aether_io_write_text_atomic"
            } else {
                "aether_io_write_text"
            };
            writeln!(output, "  %path = load ptr, ptr %v{path}\n  %value = load ptr, ptr %v{value}\n  %status = call i32 @{helper}(ptr %path, ptr %value)\n  switch i32 %status, label %io_error [ i32 0, label %return i32 3, label %not_found i32 4, label %denied ]\nreturn:\n  ret i1 false").unwrap();
            throw(output, "not_found", not_found.expect("File exception"));
            throw(output, "denied", denied.expect("File exception"));
            throw(output, "io_error", io);
            output.push_str("}\n\n");
        }
        IoFunction::ReadText => {
            let path = function.parameters[0].value.0;
            writeln!(output, "define ptr @{symbol}(ptr %v{path}) {{\nentry:\n  %path = load ptr, ptr %v{path}\n  %raw = call {{ i32, ptr }} @aether_io_read_text(ptr %path)\n  %status = extractvalue {{ i32, ptr }} %raw, 0\n  %value = extractvalue {{ i32, ptr }} %raw, 1\n  switch i32 %status, label %io_error [ i32 0, label %return i32 2, label %encoding i32 3, label %not_found i32 4, label %denied ]\nreturn:\n  ret ptr %value").unwrap();
            throw(output, "encoding", encoding.expect("encoding exception"));
            throw(output, "not_found", not_found.expect("File exception"));
            throw(output, "denied", denied.expect("File exception"));
            throw(output, "io_error", io);
            output.push_str("}\n\n");
        }
        IoFunction::ReadLine => {
            let result_ty = llvm_type(types, signature.return_type);
            writeln!(output, "define {result_ty} @{symbol}() {{\nentry:\n  %raw = call {{ i32, ptr }} @aether_io_read_line()\n  %status = extractvalue {{ i32, ptr }} %raw, 0\n  %value = extractvalue {{ i32, ptr }} %raw, 1\n  %ok = icmp eq i32 %status, 0\n  br i1 %ok, label %result, label %error\nresult:\n  %eof = icmp eq ptr %value, null\n  br i1 %eof, label %end, label %line\nend:\n  %end_value = insertvalue {result_ty} zeroinitializer, i32 1, 0\n  ret {result_ty} %end_value\nline:\n  %line_tag = insertvalue {result_ty} zeroinitializer, i32 0, 0\n  %line_value = insertvalue {result_ty} %line_tag, ptr %value, 1, 0\n  ret {result_ty} %line_value\nerror:\n  %invalid = icmp eq i32 %status, 2\n  br i1 %invalid, label %encoding, label %io_error").unwrap();
            throw(output, "encoding", encoding.expect("encoding exception"));
            throw(output, "io_error", io);
            output.push_str("}\n\n");
        }
    }
}

#[allow(clippy::too_many_lines)]
pub(super) fn runtime(
    output: &mut String,
    need_read_line: bool,
    need_files: bool,
    need_atomic_write: bool,
    stdout_exception: Option<ClassId>,
) {
    output.push_str(
        "declare i64 @read(i32, ptr, i64)\n\
         declare i32 @open(ptr, i32, ...)\n\
         declare i32 @close(i32)\n\
         declare ptr @realloc(ptr, i64)\n\
         define internal i32 @aether_io_errno() nounwind {\nentry:\n  %p = call ptr @__errno_location()\n  %e = load i32, ptr %p\n  ret i32 %e\n}\n\
         define internal ptr @aether_io_grow(ptr %old, i64 %capacity) {\nentry:\n  %zero = icmp eq i64 %capacity, 0\n  br i1 %zero, label %alloc, label %double\ndouble:\n  %too_big = icmp ugt i64 %capacity, 9223372036854775807\n  br i1 %too_big, label %trap, label %twice\ntwice:\n  %doubled = shl i64 %capacity, 1\n  br label %alloc\nalloc:\n  %size = phi i64 [ 64, %entry ], [ %doubled, %twice ]\n  %buffer = call ptr @realloc(ptr %old, i64 %size)\n  %failed = icmp eq ptr %buffer, null\n  br i1 %failed, label %trap, label %return\nreturn:\n  ret ptr %buffer\ntrap:\n  ; structured Aether trap: AllocationSizeOverflowOrOOM\n  call void @llvm.trap()\n  unreachable\n}\n\
         define internal i1 @aether_io_utf8(ptr %data, i64 %length) nounwind {\nentry:\n  br label %loop\nloop:\n  %i = phi i64 [ 0, %entry ], [ %next, %advance ], [ %multi_next, %loop_multi ]\n  %done = icmp eq i64 %i, %length\n  br i1 %done, label %valid, label %lead\nlead:\n  %p = getelementptr i8, ptr %data, i64 %i\n  %b8 = load i8, ptr %p\n  %b = zext i8 %b8 to i32\n  %ascii = icmp ult i32 %b, 128\n  br i1 %ascii, label %one, label %multi\none:\n  br label %advance\nmulti:\n  %two_lo = icmp uge i32 %b, 194\n  %two_hi = icmp ule i32 %b, 223\n  %two = and i1 %two_lo, %two_hi\n  br i1 %two, label %need1, label %three_test\nthree_test:\n  %three_lo = icmp uge i32 %b, 224\n  %three_hi = icmp ule i32 %b, 239\n  %three = and i1 %three_lo, %three_hi\n  br i1 %three, label %need2, label %four_test\nfour_test:\n  %four_lo = icmp uge i32 %b, 240\n  %four_hi = icmp ule i32 %b, 244\n  %four = and i1 %four_lo, %four_hi\n  br i1 %four, label %need3, label %invalid\nneed1:\n  %i1 = add i64 %i, 1\n  %has1 = icmp ult i64 %i1, %length\n  br i1 %has1, label %check1_two, label %invalid\ncheck1_two:\n  %p1t = getelementptr i8, ptr %data, i64 %i1\n  %c1t8 = load i8, ptr %p1t\n  %c1t = zext i8 %c1t8 to i32\n  %c1tlo = icmp uge i32 %c1t, 128\n  %c1thi = icmp ule i32 %c1t, 191\n  %c1tok = and i1 %c1tlo, %c1thi\n  br i1 %c1tok, label %advance2, label %invalid\nneed2:\n  %i2bound = add i64 %i, 2\n  %has2 = icmp ult i64 %i2bound, %length\n  br i1 %has2, label %check3bytes, label %invalid\ncheck3bytes:\n  %i31 = add i64 %i, 1\n  %p31 = getelementptr i8, ptr %data, i64 %i31\n  %c318 = load i8, ptr %p31\n  %c31 = zext i8 %c318 to i32\n  %p32 = getelementptr i8, ptr %data, i64 %i2bound\n  %c328 = load i8, ptr %p32\n  %c32 = zext i8 %c328 to i32\n  %c32lo = icmp uge i32 %c32, 128\n  %c32hi = icmp ule i32 %c32, 191\n  %c32ok = and i1 %c32lo, %c32hi\n  %e0 = icmp eq i32 %b, 224\n  %ed = icmp eq i32 %b, 237\n  %normal3lo = icmp uge i32 %c31, 128\n  %normal3hi = icmp ule i32 %c31, 191\n  %normal3 = and i1 %normal3lo, %normal3hi\n  %e0ok = icmp uge i32 %c31, 160\n  %edok = icmp ule i32 %c31, 159\n  %not_e0 = xor i1 %e0, true\n  %not_ed = xor i1 %ed, true\n  %special0 = or i1 %not_e0, %e0ok\n  %speciald = or i1 %not_ed, %edok\n  %c31a = and i1 %normal3, %special0\n  %c31ok = and i1 %c31a, %speciald\n  %threeok = and i1 %c31ok, %c32ok\n  br i1 %threeok, label %advance3, label %invalid\nneed3:\n  %i3bound = add i64 %i, 3\n  %has3 = icmp ult i64 %i3bound, %length\n  br i1 %has3, label %check4bytes, label %invalid\ncheck4bytes:\n  %i41 = add i64 %i, 1\n  %i42 = add i64 %i, 2\n  %p41 = getelementptr i8, ptr %data, i64 %i41\n  %c418 = load i8, ptr %p41\n  %c41 = zext i8 %c418 to i32\n  %p42 = getelementptr i8, ptr %data, i64 %i42\n  %c428 = load i8, ptr %p42\n  %c42 = zext i8 %c428 to i32\n  %p43 = getelementptr i8, ptr %data, i64 %i3bound\n  %c438 = load i8, ptr %p43\n  %c43 = zext i8 %c438 to i32\n  %c42lo = icmp uge i32 %c42, 128\n  %c42hi = icmp ule i32 %c42, 191\n  %c42ok = and i1 %c42lo, %c42hi\n  %c43lo = icmp uge i32 %c43, 128\n  %c43hi = icmp ule i32 %c43, 191\n  %c43ok = and i1 %c43lo, %c43hi\n  %f0 = icmp eq i32 %b, 240\n  %f4 = icmp eq i32 %b, 244\n  %normal4lo = icmp uge i32 %c41, 128\n  %normal4hi = icmp ule i32 %c41, 191\n  %normal4 = and i1 %normal4lo, %normal4hi\n  %f0ok = icmp uge i32 %c41, 144\n  %f4ok = icmp ule i32 %c41, 143\n  %not_f0 = xor i1 %f0, true\n  %not_f4 = xor i1 %f4, true\n  %specialf0 = or i1 %not_f0, %f0ok\n  %specialf4 = or i1 %not_f4, %f4ok\n  %c41a = and i1 %normal4, %specialf0\n  %c41ok = and i1 %c41a, %specialf4\n  %four12 = and i1 %c41ok, %c42ok\n  %fourok = and i1 %four12, %c43ok\n  br i1 %fourok, label %advance4, label %invalid\nadvance2:\n  %next2 = add i64 %i, 2\n  br label %advance_join\nadvance3:\n  %next3 = add i64 %i, 3\n  br label %advance_join\nadvance4:\n  %next4 = add i64 %i, 4\n  br label %advance_join\nadvance_join:\n  %multi_next = phi i64 [ %next2, %advance2 ], [ %next3, %advance3 ], [ %next4, %advance4 ]\n  br label %loop_multi\nloop_multi:\n  br label %loop\nadvance:\n  %next = add i64 %i, 1\n  br label %loop\nvalid:\n  ret i1 true\ninvalid:\n  ret i1 false\n}\n",
    );
    // The validator's multi-byte backedge needs its own phi incoming. Keep it
    // textual and deterministic instead of exposing a public compiler op.
    output.push('\n');
    emit_common_runtime(output);
    if let Some(class) = stdout_exception {
        writeln!(output, "define internal i1 @aether_io_stdout(ptr %value, i1 %newline) {{\nentry:\n  %status = call i32 @aether_io_write_string(i32 1, ptr %value, i1 %newline)\n  %ok = icmp eq i32 %status, 0\n  br i1 %ok, label %return, label %error\nreturn:\n  ret i1 false\nerror:\n  %exception = call ptr @aether_object_alloc_{}()\n  call void @aether_throw(ptr %exception)\n  unreachable\n}}\n", class.0).unwrap();
    }
    if need_read_line {
        emit_read_line(output);
    }
    if need_files {
        emit_file_runtime(output);
    }
    if need_atomic_write {
        emit_atomic_write_runtime(output);
    }
}

fn emit_common_runtime(output: &mut String) {
    output.push_str(
        "define internal ptr @aether_io_publish(ptr %buffer, i64 %length) {\nentry:\n  %total_pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %length, i64 25)\n  %total = extractvalue { i64, i1 } %total_pair, 0\n  %overflow = extractvalue { i64, i1 } %total_pair, 1\n  br i1 %overflow, label %trap, label %alloc\nalloc:\n  %object = call ptr @aether_alloc(i64 %total, i64 8)\n  store i64 %length, ptr %object\n  %count = getelementptr i8, ptr %object, i64 8\n  store i64 1, ptr %count\n  %flags = getelementptr i8, ptr %object, i64 16\n  store i64 0, ptr %flags\n  %data = getelementptr i8, ptr %object, i64 24\n  call void @llvm.memcpy.p0.p0.i64(ptr %data, ptr %buffer, i64 %length, i1 false)\n  %nul = getelementptr i8, ptr %data, i64 %length\n  store i8 0, ptr %nul\n  call void @free(ptr %buffer)\n  %events = load i64, ptr @aether_string_alloc_count\n  %events_next = add i64 %events, 1\n  store i64 %events_next, ptr @aether_string_alloc_count\n  ret ptr %object\ntrap:\n  call void @free(ptr %buffer)\n  call void @llvm.trap()\n  unreachable\n}\n\
         define internal i32 @aether_io_write_all(i32 %fd, ptr %data, i64 %length) {\nentry:\n  br label %loop\nloop:\n  %offset = phi i64 [ 0, %entry ], [ %next, %progress ], [ %offset, %errno ]\n  %done = icmp eq i64 %offset, %length\n  br i1 %done, label %ok, label %attempt\nattempt:\n  %remaining = sub i64 %length, %offset\n  %cursor = getelementptr i8, ptr %data, i64 %offset\n  %written = call i64 @write(i32 %fd, ptr %cursor, i64 %remaining)\n  %positive = icmp sgt i64 %written, 0\n  br i1 %positive, label %progress, label %failed\nprogress:\n  %next = add i64 %offset, %written\n  br label %loop\nfailed:\n  %zero = icmp eq i64 %written, 0\n  br i1 %zero, label %error, label %errno\nerrno:\n  %e = call i32 @aether_io_errno()\n  %eintr = icmp eq i32 %e, 4\n  br i1 %eintr, label %loop, label %error\nok:\n  ret i32 0\nerror:\n  ret i32 1\n}\n\
         define internal i32 @aether_io_write_string(i32 %fd, ptr %value, i1 %newline) {\nentry:\n  %length = call i64 @aether_string_length(ptr %value)\n  %data = call ptr @aether_string_data(ptr %value)\n  %status = call i32 @aether_io_write_all(i32 %fd, ptr %data, i64 %length)\n  %ok = icmp eq i32 %status, 0\n  br i1 %ok, label %suffix, label %error\nsuffix:\n  br i1 %newline, label %nl, label %return\nnl:\n  %nlstatus = call i32 @aether_io_write_all(i32 %fd, ptr @aether_string_newline, i64 1)\n  ret i32 %nlstatus\nreturn:\n  ret i32 0\nerror:\n  ret i32 1\n}\n",
    );
}

fn emit_read_line(output: &mut String) {
    output.push_str(
        "define internal { i32, ptr } @aether_io_read_line() {\nentry:\n  %byte = alloca i8\n  br label %loop\nloop:\n  %buffer = phi ptr [ null, %entry ], [ %buffer_next, %continue ], [ %buffer, %read_error ]\n  %length = phi i64 [ 0, %entry ], [ %length_next, %continue ], [ %length, %read_error ]\n  %capacity = phi i64 [ 0, %entry ], [ %capacity_next, %continue ], [ %capacity, %read_error ]\n  %n = call i64 @read(i32 0, ptr %byte, i64 1)\n  %one = icmp eq i64 %n, 1\n  br i1 %one, label %got, label %not_one\nnot_one:\n  %eof = icmp eq i64 %n, 0\n  br i1 %eof, label %finish, label %read_error\nread_error:\n  %errno = call i32 @aether_io_errno()\n  %eintr = icmp eq i32 %errno, 4\n  br i1 %eintr, label %loop, label %error\ngot:\n  %b = load i8, ptr %byte\n  %lf = icmp eq i8 %b, 10\n  br i1 %lf, label %trim, label %append\nappend:\n  %full = icmp eq i64 %length, %capacity\n  br i1 %full, label %grow, label %store\ngrow:\n  %grown = call ptr @aether_io_grow(ptr %buffer, i64 %capacity)\n  %was_zero = icmp eq i64 %capacity, 0\n  %doubled = shl i64 %capacity, 1\n  %chosen_capacity = select i1 %was_zero, i64 64, i64 %doubled\n  br label %store\nstore:\n  %buffer_next = phi ptr [ %grown, %grow ], [ %buffer, %append ]\n  %capacity_next = phi i64 [ %chosen_capacity, %grow ], [ %capacity, %append ]\n  %slot = getelementptr i8, ptr %buffer_next, i64 %length\n  store i8 %b, ptr %slot\n  %length_next = add i64 %length, 1\n  br label %continue\ncontinue:\n  br label %loop\ntrim:\n  %nonempty = icmp ne i64 %length, 0\n  br i1 %nonempty, label %last, label %finish\nlast:\n  %last_index = sub i64 %length, 1\n  %last_ptr = getelementptr i8, ptr %buffer, i64 %last_index\n  %last_byte = load i8, ptr %last_ptr\n  %cr = icmp eq i8 %last_byte, 13\n  %trimmed = select i1 %cr, i64 %last_index, i64 %length\n  br label %finish\nfinish:\n  %final_length = phi i64 [ %length, %not_one ], [ 0, %trim ], [ %trimmed, %last ]\n  %final_buffer = phi ptr [ %buffer, %not_one ], [ %buffer, %trim ], [ %buffer, %last ]\n  %final_eof = phi i1 [ %eof, %not_one ], [ false, %trim ], [ false, %last ]\n  %final_empty = icmp eq i64 %final_length, 0\n  %immediate_eof = and i1 %final_eof, %final_empty\n  br i1 %immediate_eof, label %end, label %validate\nvalidate:\n  %valid = call i1 @aether_io_utf8(ptr %final_buffer, i64 %final_length)\n  br i1 %valid, label %publish, label %encoding\npublish:\n  %value = call ptr @aether_io_publish(ptr %final_buffer, i64 %final_length)\n  %ok0 = insertvalue { i32, ptr } zeroinitializer, i32 0, 0\n  %ok = insertvalue { i32, ptr } %ok0, ptr %value, 1\n  ret { i32, ptr } %ok\nend:\n  call void @free(ptr %final_buffer)\n  ret { i32, ptr } zeroinitializer\nencoding:\n  call void @free(ptr %final_buffer)\n  %bad = insertvalue { i32, ptr } zeroinitializer, i32 2, 0\n  ret { i32, ptr } %bad\nerror:\n  call void @free(ptr %buffer)\n  %io = insertvalue { i32, ptr } zeroinitializer, i32 1, 0\n  ret { i32, ptr } %io\n}\n",
    );
}

fn emit_file_runtime(output: &mut String) {
    output.push_str(
        "define internal { i32, ptr } @aether_io_path(ptr %path) {\nentry:\n  %length = call i64 @aether_string_length(ptr %path)\n  %data = call ptr @aether_string_data(ptr %path)\n  br label %scan\nscan:\n  %i = phi i64 [ 0, %entry ], [ %next, %continue ]\n  %done = icmp eq i64 %i, %length\n  br i1 %done, label %allocate, label %byte\nbyte:\n  %p = getelementptr i8, ptr %data, i64 %i\n  %b = load i8, ptr %p\n  %nul = icmp eq i8 %b, 0\n  br i1 %nul, label %invalid, label %continue\ncontinue:\n  %next = add i64 %i, 1\n  br label %scan\nallocate:\n  %pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %length, i64 1)\n  %size = extractvalue { i64, i1 } %pair, 0\n  %overflow = extractvalue { i64, i1 } %pair, 1\n  br i1 %overflow, label %trap, label %alloc\nalloc:\n  %copy = call ptr @realloc(ptr null, i64 %size)\n  %failed = icmp eq ptr %copy, null\n  br i1 %failed, label %trap, label %copy_bytes\ncopy_bytes:\n  call void @llvm.memcpy.p0.p0.i64(ptr %copy, ptr %data, i64 %length, i1 false)\n  %end = getelementptr i8, ptr %copy, i64 %length\n  store i8 0, ptr %end\n  %r0 = insertvalue { i32, ptr } zeroinitializer, i32 0, 0\n  %r = insertvalue { i32, ptr } %r0, ptr %copy, 1\n  ret { i32, ptr } %r\ninvalid:\n  %bad = insertvalue { i32, ptr } zeroinitializer, i32 1, 0\n  ret { i32, ptr } %bad\ntrap:\n  call void @llvm.trap()\n  unreachable\n}\n\
         define internal i32 @aether_io_open_status() nounwind {\nentry:\n  %e = call i32 @aether_io_errno()\n  %nf = icmp eq i32 %e, 2\n  br i1 %nf, label %not_found, label %permission_test\npermission_test:\n  %acces = icmp eq i32 %e, 13\n  %perm = icmp eq i32 %e, 1\n  %denied = or i1 %acces, %perm\n  br i1 %denied, label %permission, label %io\nnot_found:\n  ret i32 3\npermission:\n  ret i32 4\nio:\n  ret i32 1\n}\n\
         define internal { i32, ptr } @aether_io_read_text(ptr %path) {\nentry:\n  %path_result = call { i32, ptr } @aether_io_path(ptr %path)\n  %path_status = extractvalue { i32, ptr } %path_result, 0\n  %cpath = extractvalue { i32, ptr } %path_result, 1\n  %path_ok = icmp eq i32 %path_status, 0\n  br i1 %path_ok, label %open_loop, label %path_error\nopen_loop:\n  %fd = call i32 (ptr, i32, ...) @open(ptr %cpath, i32 0)\n  %opened = icmp sge i32 %fd, 0\n  br i1 %opened, label %opened_ok, label %open_failed\nopen_failed:\n  %oe = call i32 @aether_io_errno()\n  %oeintr = icmp eq i32 %oe, 4\n  br i1 %oeintr, label %open_loop, label %open_error\nopen_error:\n  %os = call i32 @aether_io_open_status()\n  call void @free(ptr %cpath)\n  %or = insertvalue { i32, ptr } zeroinitializer, i32 %os, 0\n  ret { i32, ptr } %or\nopened_ok:\n  call void @free(ptr %cpath)\n  %byte = alloca i8\n  br label %read_loop\nread_loop:\n  %buffer = phi ptr [ null, %opened_ok ], [ %buffer_next, %continue ], [ %buffer, %read_failed ]\n  %length = phi i64 [ 0, %opened_ok ], [ %length_next, %continue ], [ %length, %read_failed ]\n  %capacity = phi i64 [ 0, %opened_ok ], [ %capacity_next, %continue ], [ %capacity, %read_failed ]\n  %n = call i64 @read(i32 %fd, ptr %byte, i64 1)\n  %one = icmp eq i64 %n, 1\n  br i1 %one, label %append, label %read_not_one\nappend:\n  %full = icmp eq i64 %length, %capacity\n  br i1 %full, label %grow, label %store\ngrow:\n  %grown = call ptr @aether_io_grow(ptr %buffer, i64 %capacity)\n  %was_zero = icmp eq i64 %capacity, 0\n  %doubled = shl i64 %capacity, 1\n  %chosen_capacity = select i1 %was_zero, i64 64, i64 %doubled\n  br label %store\nstore:\n  %buffer_next = phi ptr [ %grown, %grow ], [ %buffer, %append ]\n  %capacity_next = phi i64 [ %chosen_capacity, %grow ], [ %capacity, %append ]\n  %slot = getelementptr i8, ptr %buffer_next, i64 %length\n  %b = load i8, ptr %byte\n  store i8 %b, ptr %slot\n  %length_next = add i64 %length, 1\n  br label %continue\ncontinue:\n  br label %read_loop\nread_not_one:\n  %eof = icmp eq i64 %n, 0\n  br i1 %eof, label %close_success, label %read_failed\nread_failed:\n  %re = call i32 @aether_io_errno()\n  %reintr = icmp eq i32 %re, 4\n  br i1 %reintr, label %read_loop, label %close_error\nclose_success:\n  %closed = call i32 @close(i32 %fd)\n  %close_ok = icmp eq i32 %closed, 0\n  br i1 %close_ok, label %validate, label %io_error\nvalidate:\n  %valid = call i1 @aether_io_utf8(ptr %buffer, i64 %length)\n  br i1 %valid, label %publish, label %encoding\npublish:\n  %value = call ptr @aether_io_publish(ptr %buffer, i64 %length)\n  %rr0 = insertvalue { i32, ptr } zeroinitializer, i32 0, 0\n  %rr = insertvalue { i32, ptr } %rr0, ptr %value, 1\n  ret { i32, ptr } %rr\nencoding:\n  call void @free(ptr %buffer)\n  %er = insertvalue { i32, ptr } zeroinitializer, i32 2, 0\n  ret { i32, ptr } %er\nclose_error:\n  %ignored_close = call i32 @close(i32 %fd)\n  br label %io_error\nio_error:\n  call void @free(ptr %buffer)\n  %ir = insertvalue { i32, ptr } zeroinitializer, i32 1, 0\n  ret { i32, ptr } %ir\npath_error:\n  %pr = insertvalue { i32, ptr } zeroinitializer, i32 %path_status, 0\n  ret { i32, ptr } %pr\n}\n\
         define internal i32 @aether_io_write_text(ptr %path, ptr %value) {\nentry:\n  %path_result = call { i32, ptr } @aether_io_path(ptr %path)\n  %path_status = extractvalue { i32, ptr } %path_result, 0\n  %cpath = extractvalue { i32, ptr } %path_result, 1\n  %path_ok = icmp eq i32 %path_status, 0\n  br i1 %path_ok, label %open_loop, label %path_error\nopen_loop:\n  %fd = call i32 (ptr, i32, ...) @open(ptr %cpath, i32 577, i32 438)\n  %opened = icmp sge i32 %fd, 0\n  br i1 %opened, label %opened_ok, label %open_failed\nopen_failed:\n  %oe = call i32 @aether_io_errno()\n  %oeintr = icmp eq i32 %oe, 4\n  br i1 %oeintr, label %open_loop, label %open_error\nopen_error:\n  %os = call i32 @aether_io_open_status()\n  call void @free(ptr %cpath)\n  ret i32 %os\nopened_ok:\n  call void @free(ptr %cpath)\n  %length = call i64 @aether_string_length(ptr %value)\n  %data = call ptr @aether_string_data(ptr %value)\n  %status = call i32 @aether_io_write_all(i32 %fd, ptr %data, i64 %length)\n  %closed = call i32 @close(i32 %fd)\n  %write_ok = icmp eq i32 %status, 0\n  %close_ok = icmp eq i32 %closed, 0\n  %ok = and i1 %write_ok, %close_ok\n  %result = select i1 %ok, i32 0, i32 1\n  ret i32 %result\npath_error:\n  ret i32 %path_status\n}\n",
    );
}

/// Emits the Linux/POSIX FILE-ATOMIC-WRITE-V1 adapter.  Its syscall surface is
/// deliberately separate so ordinary file IO does not retain entropy,
/// exclusive-create, rename, or atomic cleanup helpers.
#[allow(clippy::too_many_lines)]
fn emit_atomic_write_runtime(output: &mut String) {
    output.push_str(
        r#"@aether_atomic_dot = private constant [2 x i8] c".\00"
@aether_atomic_root = private constant [2 x i8] c"/\00"
@aether_atomic_prefix = private constant [14 x i8] c".aether-write-"
@aether_atomic_hex = private constant [16 x i8] c"0123456789abcdef"
declare i64 @getrandom(ptr, i64, i32)
declare i32 @openat(i32, ptr, i32, ...)
declare i32 @renameat(i32, ptr, i32, ptr)
declare i32 @unlinkat(i32, ptr, i32)

define internal i32 @aether_atomic_errno_status() nounwind {
entry:
  %e = call i32 @aether_io_errno()
  %nf = icmp eq i32 %e, 2
  br i1 %nf, label %not_found, label %permission_test
permission_test:
  %access = icmp eq i32 %e, 13
  %policy = icmp eq i32 %e, 1
  %denied = or i1 %access, %policy
  br i1 %denied, label %permission, label %io
not_found:
  ret i32 3
permission:
  ret i32 4
io:
  ret i32 1
}

define internal { i32, ptr } @aether_atomic_path(ptr %path) {
entry:
  %length = call i64 @aether_string_length(ptr %path)
  %data = call ptr @aether_string_data(ptr %path)
  %empty = icmp eq i64 %length, 0
  br i1 %empty, label %invalid, label %scan
scan:
  %i = phi i64 [ 0, %entry ], [ %next, %continue ]
  %done = icmp eq i64 %i, %length
  br i1 %done, label %allocate, label %byte
byte:
  %p = getelementptr i8, ptr %data, i64 %i
  %b = load i8, ptr %p
  %nul = icmp eq i8 %b, 0
  br i1 %nul, label %invalid, label %continue
continue:
  %next = add i64 %i, 1
  br label %scan
allocate:
  %last_index = sub i64 %length, 1
  %last_ptr = getelementptr i8, ptr %data, i64 %last_index
  %last = load i8, ptr %last_ptr
  %trailing_slash = icmp eq i8 %last, 47
  br i1 %trailing_slash, label %invalid, label %size
size:
  %pair = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %length, i64 1)
  %bytes = extractvalue { i64, i1 } %pair, 0
  %overflow = extractvalue { i64, i1 } %pair, 1
  br i1 %overflow, label %trap, label %alloc
alloc:
  %copy = call ptr @realloc(ptr null, i64 %bytes)
  %failed = icmp eq ptr %copy, null
  br i1 %failed, label %trap, label %copy_bytes
copy_bytes:
  call void @llvm.memcpy.p0.p0.i64(ptr %copy, ptr %data, i64 %length, i1 false)
  %end = getelementptr i8, ptr %copy, i64 %length
  store i8 0, ptr %end
  %r0 = insertvalue { i32, ptr } zeroinitializer, i32 0, 0
  %r = insertvalue { i32, ptr } %r0, ptr %copy, 1
  ret { i32, ptr } %r
invalid:
  %bad = insertvalue { i32, ptr } zeroinitializer, i32 1, 0
  ret { i32, ptr } %bad
trap:
  call void @llvm.trap()
  unreachable
}

define internal i32 @aether_atomic_write_all(i32 %fd, ptr %data, i64 %length) {
entry:
  br label %loop
loop:
  %offset = phi i64 [ 0, %entry ], [ %next, %progress ], [ %offset, %retry ]
  %done = icmp eq i64 %offset, %length
  br i1 %done, label %ok, label %attempt
attempt:
  %remaining = sub i64 %length, %offset
  %cursor = getelementptr i8, ptr %data, i64 %offset
  %written = call i64 @write(i32 %fd, ptr %cursor, i64 %remaining)
  %positive = icmp sgt i64 %written, 0
  br i1 %positive, label %progress, label %failed
progress:
  %next = add i64 %offset, %written
  br label %loop
failed:
  %zero = icmp eq i64 %written, 0
  br i1 %zero, label %io, label %errno
errno:
  %e = call i32 @aether_io_errno()
  %eintr = icmp eq i32 %e, 4
  br i1 %eintr, label %retry, label %status
retry:
  br label %loop
status:
  %failure = call i32 @aether_atomic_errno_status()
  ret i32 %failure
ok:
  ret i32 0
io:
  ret i32 1
}

define internal i32 @aether_io_write_text_atomic(ptr %path, ptr %value) {
entry:
  %path_result = call { i32, ptr } @aether_atomic_path(ptr %path)
  %path_status = extractvalue { i32, ptr } %path_result, 0
  %cpath = extractvalue { i32, ptr } %path_result, 1
  %path_ok = icmp eq i32 %path_status, 0
  br i1 %path_ok, label %find_slash, label %path_error

find_slash:
  %path_length = call i64 @aether_string_length(ptr %path)
  br label %slash_loop
slash_loop:
  %si = phi i64 [ 0, %find_slash ], [ %si_next, %slash_continue ]
  %last_slash = phi i64 [ -1, %find_slash ], [ %chosen_slash, %slash_continue ]
  %slash_done = icmp eq i64 %si, %path_length
  br i1 %slash_done, label %split, label %slash_byte
slash_byte:
  %sp = getelementptr i8, ptr %cpath, i64 %si
  %sb = load i8, ptr %sp
  %is_slash = icmp eq i8 %sb, 47
  %chosen_slash = select i1 %is_slash, i64 %si, i64 %last_slash
  br label %slash_continue
slash_continue:
  %si_next = add i64 %si, 1
  br label %slash_loop

split:
  %no_slash = icmp eq i64 %last_slash, -1
  br i1 %no_slash, label %relative, label %has_slash
relative:
  br label %open_parent
has_slash:
  %at_root = icmp eq i64 %last_slash, 0
  br i1 %at_root, label %root_parent, label %explicit_parent
root_parent:
  %root_basename = getelementptr i8, ptr %cpath, i64 1
  br label %open_parent
explicit_parent:
  %separator = getelementptr i8, ptr %cpath, i64 %last_slash
  store i8 0, ptr %separator
  %explicit_basename_index = add i64 %last_slash, 1
  %explicit_basename = getelementptr i8, ptr %cpath, i64 %explicit_basename_index
  br label %open_parent

open_parent:
  %parent = phi ptr [ @aether_atomic_dot, %relative ], [ @aether_atomic_root, %root_parent ], [ %cpath, %explicit_parent ]
  %basename = phi ptr [ %cpath, %relative ], [ %root_basename, %root_parent ], [ %explicit_basename, %explicit_parent ]
  br label %parent_attempt
parent_attempt:
  %parent_fd = call i32 (ptr, i32, ...) @open(ptr %parent, i32 589824)
  %parent_opened = icmp sge i32 %parent_fd, 0
  br i1 %parent_opened, label %temp_setup, label %parent_failed
parent_failed:
  %parent_errno = call i32 @aether_io_errno()
  %parent_eintr = icmp eq i32 %parent_errno, 4
  br i1 %parent_eintr, label %parent_attempt, label %parent_error
parent_error:
  %parent_status = call i32 @aether_atomic_errno_status()
  call void @free(ptr %cpath)
  ret i32 %parent_status

temp_setup:
  %random = alloca [16 x i8]
  %temp = alloca [47 x i8]
  call void @llvm.memcpy.p0.p0.i64(ptr %temp, ptr @aether_atomic_prefix, i64 14, i1 false)
  %temp_end = getelementptr i8, ptr %temp, i64 46
  store i8 0, ptr %temp_end
  br label %candidate

candidate:
  %attempt_index = phi i32 [ 0, %temp_setup ], [ %attempt_next, %collision ], [ %attempt_next_equal, %same_target ]
  %exhausted = icmp eq i32 %attempt_index, 16
  br i1 %exhausted, label %collision_exhausted, label %entropy_start
entropy_start:
  br label %entropy_loop
entropy_loop:
  %random_offset = phi i64 [ 0, %entropy_start ], [ %random_next, %entropy_progress ], [ %random_offset, %entropy_retry ]
  %random_done = icmp eq i64 %random_offset, 16
  br i1 %random_done, label %hex_start, label %entropy_attempt
entropy_attempt:
  %random_cursor = getelementptr i8, ptr %random, i64 %random_offset
  %random_remaining = sub i64 16, %random_offset
  %random_count = call i64 @getrandom(ptr %random_cursor, i64 %random_remaining, i32 0)
  %random_positive = icmp sgt i64 %random_count, 0
  br i1 %random_positive, label %entropy_progress, label %entropy_failed
entropy_progress:
  %random_next = add i64 %random_offset, %random_count
  br label %entropy_loop
entropy_failed:
  %random_zero = icmp eq i64 %random_count, 0
  br i1 %random_zero, label %precreate_io_error, label %entropy_errno
entropy_errno:
  %random_errno = call i32 @aether_io_errno()
  %random_eintr = icmp eq i32 %random_errno, 4
  br i1 %random_eintr, label %entropy_retry, label %entropy_error
entropy_retry:
  br label %entropy_loop
entropy_error:
  %entropy_status = call i32 @aether_atomic_errno_status()
  br label %precreate_failure

hex_start:
  br label %hex_loop
hex_loop:
  %hi = phi i64 [ 0, %hex_start ], [ %hi_next, %hex_byte ]
  %hex_done = icmp eq i64 %hi, 16
  br i1 %hex_done, label %compare_start, label %hex_byte
hex_byte:
  %random_byte_ptr = getelementptr i8, ptr %random, i64 %hi
  %random_byte = load i8, ptr %random_byte_ptr
  %random_u = zext i8 %random_byte to i64
  %upper_index = lshr i64 %random_u, 4
  %lower_index = and i64 %random_u, 15
  %upper_ptr = getelementptr i8, ptr @aether_atomic_hex, i64 %upper_index
  %lower_ptr = getelementptr i8, ptr @aether_atomic_hex, i64 %lower_index
  %upper = load i8, ptr %upper_ptr
  %lower = load i8, ptr %lower_ptr
  %double_index = shl i64 %hi, 1
  %upper_temp_index = add i64 %double_index, 14
  %lower_temp_index = add i64 %upper_temp_index, 1
  %upper_temp = getelementptr i8, ptr %temp, i64 %upper_temp_index
  %lower_temp = getelementptr i8, ptr %temp, i64 %lower_temp_index
  store i8 %upper, ptr %upper_temp
  store i8 %lower, ptr %lower_temp
  %hi_next = add i64 %hi, 1
  br label %hex_loop

compare_start:
  br label %compare_loop
compare_loop:
  %ci = phi i64 [ 0, %compare_start ], [ %ci_next, %compare_equal_byte ]
  %candidate_ptr = getelementptr i8, ptr %temp, i64 %ci
  %target_ptr = getelementptr i8, ptr %basename, i64 %ci
  %candidate_byte = load i8, ptr %candidate_ptr
  %target_byte = load i8, ptr %target_ptr
  %same_byte = icmp eq i8 %candidate_byte, %target_byte
  br i1 %same_byte, label %compare_equal_byte, label %create_temp
compare_equal_byte:
  %candidate_end = icmp eq i8 %candidate_byte, 0
  %ci_next = add i64 %ci, 1
  br i1 %candidate_end, label %same_target, label %compare_loop
same_target:
  %attempt_next_equal = add i32 %attempt_index, 1
  br label %candidate

create_temp:
  %temp_fd = call i32 (i32, ptr, i32, ...) @openat(i32 %parent_fd, ptr %temp, i32 655553, i32 438)
  %temp_opened = icmp sge i32 %temp_fd, 0
  br i1 %temp_opened, label %write_temp, label %create_failed
create_failed:
  %create_errno = call i32 @aether_io_errno()
  %exists = icmp eq i32 %create_errno, 17
  br i1 %exists, label %collision, label %create_error
collision:
  %attempt_next = add i32 %attempt_index, 1
  br label %candidate
create_error:
  %create_status = call i32 @aether_atomic_errno_status()
  br label %precreate_failure
collision_exhausted:
  br label %precreate_io_error
precreate_io_error:
  br label %precreate_failure
precreate_failure:
  %precreate_status = phi i32 [ %entropy_status, %entropy_error ], [ %create_status, %create_error ], [ 1, %precreate_io_error ]
  %ignored_parent_close0 = call i32 @close(i32 %parent_fd)
  call void @free(ptr %cpath)
  ret i32 %precreate_status

write_temp:
  %length = call i64 @aether_string_length(ptr %value)
  %data = call ptr @aether_string_data(ptr %value)
  %write_status = call i32 @aether_atomic_write_all(i32 %temp_fd, ptr %data, i64 %length)
  %write_ok = icmp eq i32 %write_status, 0
  br i1 %write_ok, label %close_temp, label %cleanup_open_temp
close_temp:
  %closed = call i32 @close(i32 %temp_fd)
  %close_ok = icmp eq i32 %closed, 0
  br i1 %close_ok, label %publish, label %close_error
close_error:
  %close_status = call i32 @aether_atomic_errno_status()
  br label %cleanup_closed_temp

publish:
  %renamed = call i32 @renameat(i32 %parent_fd, ptr %temp, i32 %parent_fd, ptr %basename)
  %rename_ok = icmp eq i32 %renamed, 0
  br i1 %rename_ok, label %published, label %rename_error
rename_error:
  %rename_status = call i32 @aether_atomic_errno_status()
  br label %cleanup_closed_temp

cleanup_open_temp:
  %ignored_temp_close = call i32 @close(i32 %temp_fd)
  br label %cleanup_temp
cleanup_closed_temp:
  %closed_failure = phi i32 [ %close_status, %close_error ], [ %rename_status, %rename_error ]
  br label %cleanup_temp
cleanup_temp:
  %failure_status = phi i32 [ %write_status, %cleanup_open_temp ], [ %closed_failure, %cleanup_closed_temp ]
  %ignored_unlink = call i32 @unlinkat(i32 %parent_fd, ptr %temp, i32 0)
  %ignored_parent_close1 = call i32 @close(i32 %parent_fd)
  call void @free(ptr %cpath)
  ret i32 %failure_status

published:
  %ignored_parent_close2 = call i32 @close(i32 %parent_fd)
  call void @free(ptr %cpath)
  ret i32 0
path_error:
  ret i32 %path_status
}
"#,
    );
}
