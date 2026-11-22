//! Private runtime boundary for the canonical `std::Format` module.

use std::fmt::Write;

use aether_frontend::{
    EnumInfo, FloatType, FunctionInstanceInfo, ModuleInfo, OriginKey, PackageKey, StructInfo,
    TypeArena, TypeId,
};
use aether_middle::SsaFunction;

use crate::bootstrap_symbol;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum FormatFunction {
    Fixed(FloatType),
    Scientific(FloatType),
}

pub(super) fn function_kind(
    signature: &FunctionInstanceInfo,
    modules: &[ModuleInfo],
    types: &TypeArena,
) -> Option<FormatFunction> {
    let package = &modules[signature.module.0 as usize].key.package;
    if !matches!(
        package,
        PackageKey::Named { origin: OriginKey::Toolchain, path }
            if path.0.as_slice() == ["std", "Format"]
    ) || signature.parameters.len() != 2
        || signature.parameters[1].ty != TypeId::USIZE
        || signature.return_type != TypeId::STRING
    {
        return None;
    }
    let float = types.float_info(signature.parameters[0].ty)?;
    match signature.name.as_str() {
        "fixed" => Some(FormatFunction::Fixed(float)),
        "scientific" => Some(FormatFunction::Scientific(float)),
        _ => None,
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) fn emit_function(
    output: &mut String,
    kind: FormatFunction,
    function: &SsaFunction,
    signature: &FunctionInstanceInfo,
    modules: &[ModuleInfo],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
) {
    let symbol = bootstrap_symbol(signature, modules, structs, enums, types);
    let value = function.parameters[0].value.0;
    let digits = function.parameters[1].value.0;
    let (float, scientific) = match kind {
        FormatFunction::Fixed(float) => (float, false),
        FormatFunction::Scientific(float) => (float, true),
    };
    let argument = match float {
        FloatType::Float32 => {
            writeln!(
                output,
                "define ptr @{symbol}(float %v{value}, i64 %v{digits}) {{\nentry:\n  %wide = fpext float %v{value} to double"
            )
            .unwrap();
            "%wide".to_owned()
        }
        FloatType::Float64 => {
            writeln!(
                output,
                "define ptr @{symbol}(double %v{value}, i64 %v{digits}) {{\nentry:"
            )
            .unwrap();
            format!("%v{value}")
        }
    };
    writeln!(
        output,
        "  %result = call ptr @aether_format_explicit_f64(double {argument}, i64 %v{digits}, i1 {scientific})\n  ret ptr %result\n}}\n"
    )
    .unwrap();
}

#[allow(clippy::too_many_lines)]
pub(super) fn runtime(output: &mut String) {
    output.push_str(
        r"
; FORMAT-V2 fixed/scientific boundary. std::to_chars performs decimal rounding
; from the exact binary value; Aether owns sizing, spelling policy and strings.
declare { ptr, i32 } @_ZSt8to_charsPcS_dSt12chars_formati(ptr, ptr, double, i32, i32) nounwind

define internal ptr @aether_format_explicit_f64(double %value, i64 %digits, i1 %scientific) {
entry:
  %bits = bitcast double %value to i64
  %absbits = and i64 %bits, 9223372036854775807
  %nan = icmp ugt i64 %absbits, 9218868437227405312
  br i1 %nan, label %nan_case, label %inf_test
nan_case:
  %nan_value = call ptr @aether_string_from_buffer(ptr @aether_format_nan, i64 3)
  ret ptr %nan_value
inf_test:
  %inf = icmp eq i64 %absbits, 9218868437227405312
  %negative = icmp slt i64 %bits, 0
  br i1 %inf, label %inf_case, label %precision
inf_case:
  br i1 %negative, label %ninf, label %pinf
ninf:
  %ninf_value = call ptr @aether_string_from_buffer(ptr @aether_format_ninf, i64 4)
  ret ptr %ninf_value
pinf:
  %inf_value = call ptr @aether_string_from_buffer(ptr @aether_format_inf, i64 3)
  ret ptr %inf_value
precision:
  ; The qualified libstdc++ ABI accepts an `int` precision. Values outside it
  ; are rejected before truncation or allocation.
  %precision_too_large = icmp ugt i64 %digits, 2147483647
  br i1 %precision_too_large, label %size_trap, label %capacity
capacity:
  %has_fraction = icmp ne i64 %digits, 0
  %dot = zext i1 %has_fraction to i64
  %base = select i1 %scientific, i64 7, i64 310
  %capacity_pair0 = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %base, i64 %digits)
  %capacity0 = extractvalue { i64, i1 } %capacity_pair0, 0
  %overflow0 = extractvalue { i64, i1 } %capacity_pair0, 1
  %capacity_pair1 = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %capacity0, i64 %dot)
  %capacity1 = extractvalue { i64, i1 } %capacity_pair1, 0
  %overflow1 = extractvalue { i64, i1 } %capacity_pair1, 1
  %overflow = or i1 %overflow0, %overflow1
  br i1 %overflow, label %size_trap, label %allocate
allocate:
  %temporary = call ptr @aether_alloc(i64 %capacity1, i64 1)
  %end = getelementptr i8, ptr %temporary, i64 %capacity1
  %precision32 = trunc i64 %digits to i32
  %style = select i1 %scientific, i32 1, i32 2
  %raw = call { ptr, i32 } @_ZSt8to_charsPcS_dSt12chars_formati(ptr %temporary, ptr %end, double %value, i32 %style, i32 %precision32)
  %finish = extractvalue { ptr, i32 } %raw, 0
  %error = extractvalue { ptr, i32 } %raw, 1
  %failed = icmp ne i32 %error, 0
  br i1 %failed, label %conversion_trap, label %length
length:
  %finish_int = ptrtoint ptr %finish to i64
  %start_int = ptrtoint ptr %temporary to i64
  %raw_length = sub i64 %finish_int, %start_int
  br i1 %scientific, label %find_exponent, label %fixed_publish
fixed_publish:
  %fixed_value = call ptr @aether_string_from_buffer(ptr %temporary, i64 %raw_length)
  call void @aether_free(ptr %temporary, i64 %capacity1, i64 1)
  ret ptr %fixed_value
find_exponent:
  br label %exponent_loop
exponent_loop:
  %index = phi i64 [ 0, %find_exponent ], [ %next_index, %exponent_next ]
  %character_ptr = getelementptr i8, ptr %temporary, i64 %index
  %character = load i8, ptr %character_ptr
  %is_exponent = icmp eq i8 %character, 101
  br i1 %is_exponent, label %trim_prepare, label %exponent_next
exponent_next:
  %next_index = add i64 %index, 1
  br label %exponent_loop
trim_prepare:
  %exponent_start = add i64 %index, 2
  br label %trim_loop
trim_loop:
  %source_index = phi i64 [ %exponent_start, %trim_prepare ], [ %trim_next, %trim_zero ]
  %trim_next = add i64 %source_index, 1
  %has_later_digit = icmp ult i64 %trim_next, %raw_length
  %source_ptr = getelementptr i8, ptr %temporary, i64 %source_index
  %source_character = load i8, ptr %source_ptr
  %is_zero = icmp eq i8 %source_character, 48
  %can_trim = and i1 %has_later_digit, %is_zero
  br i1 %can_trim, label %trim_zero, label %scientific_publish
trim_zero:
  br label %trim_loop
scientific_publish:
  %trimmed = sub i64 %source_index, %exponent_start
  %final_length = sub i64 %raw_length, %trimmed
  %scientific_value = call ptr @aether_string_allocate(i64 %final_length)
  %destination = call ptr @aether_string_data(ptr %scientific_value)
  call void @llvm.memcpy.p0.p0.i64(ptr %destination, ptr %temporary, i64 %exponent_start, i1 false)
  %suffix_length = sub i64 %raw_length, %source_index
  %suffix_source = getelementptr i8, ptr %temporary, i64 %source_index
  %suffix_destination = getelementptr i8, ptr %destination, i64 %exponent_start
  call void @llvm.memcpy.p0.p0.i64(ptr %suffix_destination, ptr %suffix_source, i64 %suffix_length, i1 false)
  call void @aether_free(ptr %temporary, i64 %capacity1, i64 1)
  ret ptr %scientific_value
conversion_trap:
  call void @aether_free(ptr %temporary, i64 %capacity1, i64 1)
  call void @llvm.trap()
  unreachable
size_trap:
  ; structured Aether trap: AllocationSizeOverflow
  call void @llvm.trap()
  unreachable
}
",
    );
}
