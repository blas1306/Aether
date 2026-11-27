//! Reachability-driven helpers for the three closed exponentiation modes.

use std::collections::BTreeSet;
use std::fmt::Write;

use aether_frontend::{FloatType, PowerMode, PowerSpec, TypeArena};

use super::llvm_type;

pub(super) fn helper_name(spec: PowerSpec) -> String {
    format!(
        "aether_power_{:?}_{}_{}",
        spec.mode, spec.base_type.0, spec.exponent_type.0
    )
    .to_ascii_lowercase()
}

pub(super) fn declarations(output: &mut String, specs: &BTreeSet<PowerSpec>, types: &TypeArena) {
    let mut powf = false;
    let mut pow = false;
    for spec in specs {
        match spec.mode {
            PowerMode::IntegerChecked => emit_integer_helper(output, *spec, types),
            PowerMode::FloatInteger => emit_float_integer_helper(output, *spec, types),
            PowerMode::FloatLibm => match types.float_info(spec.base_type).unwrap() {
                FloatType::Float32 => powf = true,
                FloatType::Float64 => pow = true,
            },
        }
    }
    if powf {
        writeln!(output, "declare float @powf(float, float) nounwind").unwrap();
    }
    if pow {
        writeln!(output, "declare double @pow(double, double) nounwind").unwrap();
    }
    if powf || pow {
        writeln!(output, "; Core libm dependency").unwrap();
    }
}

fn emit_checked_mul(
    output: &mut String,
    label: &str,
    prefix: char,
    ty: &str,
    left: &str,
    right: &str,
) {
    writeln!(
        output,
        "  %{label}_pair = call {{ {ty}, i1 }} @llvm.{prefix}mul.with.overflow.{ty}({ty} {left}, {ty} {right})\n  %{label} = extractvalue {{ {ty}, i1 }} %{label}_pair, 0\n  %{label}_overflow = extractvalue {{ {ty}, i1 }} %{label}_pair, 1\n  br i1 %{label}_overflow, label %trap_overflow, label %{label}_ok\n{label}_ok:"
    )
    .unwrap();
}

fn emit_integer_helper(output: &mut String, spec: PowerSpec, types: &TypeArena) {
    let name = helper_name(spec);
    let base_ty = llvm_type(types, spec.base_type);
    let exponent_ty = llvm_type(types, spec.exponent_type);
    let base_info = types.integer_info(spec.base_type).unwrap();
    let exponent_info = types.integer_info(spec.exponent_type).unwrap();
    let prefix = if base_info.is_signed() { 's' } else { 'u' };
    writeln!(
        output,
        "define internal {base_ty} @{name}({base_ty} %base, {exponent_ty} %exponent) {{\nentry:"
    )
    .unwrap();
    if exponent_info.is_signed() {
        writeln!(output, "  %negative = icmp slt {exponent_ty} %exponent, 0\n  br i1 %negative, label %trap_negative, label %domain_ok\ntrap_negative:\n  ; structured Aether trap: NegativeIntegerExponent\n  call void @llvm.trap()\n  unreachable\ndomain_ok:").unwrap();
    }
    writeln!(output, "  %is_zero_exp = icmp eq {exponent_ty} %exponent, 0\n  br i1 %is_zero_exp, label %return_one, label %base_checks\nbase_checks:\n  %is_zero_base = icmp eq {base_ty} %base, 0\n  br i1 %is_zero_base, label %return_zero, label %base_one_check\nbase_one_check:\n  %is_one_base = icmp eq {base_ty} %base, 1\n  br i1 %is_one_base, label %return_one, label %base_special_done").unwrap();
    if base_info.is_signed() {
        writeln!(output, "base_special_done:\n  %is_minus_one = icmp eq {base_ty} %base, -1\n  br i1 %is_minus_one, label %minus_one, label %loop\nminus_one:\n  %parity = and {exponent_ty} %exponent, 1\n  %is_odd_special = icmp ne {exponent_ty} %parity, 0\n  %minus_one_result = select i1 %is_odd_special, {base_ty} -1, {base_ty} 1\n  ret {base_ty} %minus_one_result").unwrap();
    } else {
        writeln!(output, "base_special_done:\n  br label %loop").unwrap();
    }
    writeln!(output, "loop:\n  %acc = phi {base_ty} [ 1, %base_special_done ], [ %next_acc, %squared_ok ]\n  %factor = phi {base_ty} [ %base, %base_special_done ], [ %squared, %squared_ok ]\n  %n = phi {exponent_ty} [ %exponent, %base_special_done ], [ %next_n, %squared_ok ]\n  %low = and {exponent_ty} %n, 1\n  %odd = icmp ne {exponent_ty} %low, 0\n  br i1 %odd, label %multiply_acc, label %skip_acc\nmultiply_acc:").unwrap();
    emit_checked_mul(output, "multiplied", prefix, &base_ty, "%acc", "%factor");
    writeln!(output, "  br label %after_acc\nskip_acc:\n  br label %after_acc\nafter_acc:\n  %next_acc = phi {base_ty} [ %multiplied, %multiplied_ok ], [ %acc, %skip_acc ]\n  %next_n = lshr {exponent_ty} %n, 1\n  %finished = icmp eq {exponent_ty} %next_n, 0\n  br i1 %finished, label %done, label %square\nsquare:").unwrap();
    emit_checked_mul(output, "squared", prefix, &base_ty, "%factor", "%factor");
    writeln!(output, "  br label %loop\ndone:\n  ret {base_ty} %next_acc\nreturn_zero:\n  ret {base_ty} 0\nreturn_one:\n  ret {base_ty} 1\ntrap_overflow:\n  ; structured Aether trap: IntegerOverflow\n  call void @llvm.trap()\n  unreachable\n}}\n").unwrap();
}

fn emit_float_integer_helper(output: &mut String, spec: PowerSpec, types: &TypeArena) {
    let name = helper_name(spec);
    let base_ty = llvm_type(types, spec.base_type);
    let exponent_ty = llvm_type(types, spec.exponent_type);
    let signed = types.integer_info(spec.exponent_type).unwrap().is_signed();
    writeln!(
        output,
        "define internal {base_ty} @{name}({base_ty} %base, {exponent_ty} %exponent) {{\nentry:"
    )
    .unwrap();
    if signed {
        writeln!(output, "  %negative = icmp slt {exponent_ty} %exponent, 0\n  br i1 %negative, label %reciprocal, label %positive\nreciprocal:\n  %reciprocal_base = fdiv {base_ty} 1.000000e+00, %base\n  %magnitude = sub {exponent_ty} 0, %exponent\n  br label %loop\npositive:\n  br label %loop\nloop:\n  %factor = phi {base_ty} [ %reciprocal_base, %reciprocal ], [ %base, %positive ], [ %squared, %square ]\n  %n = phi {exponent_ty} [ %magnitude, %reciprocal ], [ %exponent, %positive ], [ %next_n, %square ]\n  %acc = phi {base_ty} [ 1.000000e+00, %reciprocal ], [ 1.000000e+00, %positive ], [ %next_acc, %square ]").unwrap();
    } else {
        writeln!(output, "  br label %loop\nloop:\n  %factor = phi {base_ty} [ %base, %entry ], [ %squared, %square ]\n  %n = phi {exponent_ty} [ %exponent, %entry ], [ %next_n, %square ]\n  %acc = phi {base_ty} [ 1.000000e+00, %entry ], [ %next_acc, %square ]").unwrap();
    }
    writeln!(output, "  %more = icmp ne {exponent_ty} %n, 0\n  br i1 %more, label %body, label %done\nbody:\n  %low = and {exponent_ty} %n, 1\n  %odd = icmp ne {exponent_ty} %low, 0\n  br i1 %odd, label %multiply, label %skip\nmultiply:\n  %product = fmul {base_ty} %acc, %factor\n  br label %after_acc\nskip:\n  br label %after_acc\nafter_acc:\n  %next_acc = phi {base_ty} [ %product, %multiply ], [ %acc, %skip ]\n  %next_n = lshr {exponent_ty} %n, 1\n  %finished = icmp eq {exponent_ty} %next_n, 0\n  br i1 %finished, label %done_after, label %square\nsquare:\n  %squared = fmul {base_ty} %factor, %factor\n  br label %loop\ndone_after:\n  ret {base_ty} %next_acc\ndone:\n  ret {base_ty} %acc\n}}\n").unwrap();
}
