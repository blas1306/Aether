//! Lowering for canonically resolved Core functions.

use std::collections::BTreeSet;
use std::fmt::Write;

use aether_frontend::{CoreCall, CoreSymbol, FloatType, TypeArena, TypeId};
use aether_middle::{BlockId, SsaOperand};

pub(super) fn declarations(
    output: &mut String,
    calls: &BTreeSet<(CoreSymbol, TypeId)>,
    types: &TypeArena,
) {
    let mut libm = false;
    let mut emitted = BTreeSet::new();
    for &(symbol, ty) in calls {
        let Some(float) = types.float_info(ty) else {
            continue;
        };
        let llvm_ty = if float == FloatType::Float32 {
            "float"
        } else {
            "double"
        };
        let mut declarations = vec![symbol];
        if symbol == CoreSymbol::Clamp {
            declarations.push(CoreSymbol::Min);
        }
        for function in declarations {
            let name = libm_name(function, float);
            if !emitted.insert(name) {
                continue;
            }
            let parameters = if matches!(
                function,
                CoreSymbol::Min | CoreSymbol::Max | CoreSymbol::Clamp
            ) {
                format!("{llvm_ty}, {llvm_ty}")
            } else {
                llvm_ty.into()
            };
            writeln!(output, "declare {llvm_ty} @{name}({parameters}) nounwind").unwrap();
        }
        libm = true;
    }
    if calls
        .iter()
        .any(|(symbol, ty)| *symbol == CoreSymbol::Abs && types.integer_info(*ty).is_some())
    {
        writeln!(
            output,
            "define internal void @aether_core_trap_if(i1 %condition) {{"
        )
        .unwrap();
        writeln!(output, "entry:").unwrap();
        writeln!(output, "  br i1 %condition, label %trap, label %done").unwrap();
        writeln!(output, "trap:").unwrap();
        writeln!(output, "  call void @llvm.trap()").unwrap();
        writeln!(output, "  unreachable").unwrap();
        writeln!(output, "done:").unwrap();
        writeln!(output, "  ret void").unwrap();
        writeln!(output, "}}\n").unwrap();
    }
    if libm {
        writeln!(output, "; Core libm dependency\n").unwrap();
    }
}

fn libm_name(symbol: CoreSymbol, float: FloatType) -> &'static str {
    match (symbol, float) {
        (CoreSymbol::Abs, FloatType::Float32) => "fabsf",
        (CoreSymbol::Abs, FloatType::Float64) => "fabs",
        (CoreSymbol::Min, FloatType::Float32) => "fminf",
        (CoreSymbol::Min, FloatType::Float64) => "fmin",
        (CoreSymbol::Max | CoreSymbol::Clamp, FloatType::Float32) => "fmaxf",
        (CoreSymbol::Max | CoreSymbol::Clamp, FloatType::Float64) => "fmax",
        (CoreSymbol::Sqrt, FloatType::Float32) => "sqrtf",
        (CoreSymbol::Sqrt, FloatType::Float64) => "sqrt",
        (CoreSymbol::Exp, FloatType::Float32) => "expf",
        (CoreSymbol::Exp, FloatType::Float64) => "exp",
        (CoreSymbol::Ln, FloatType::Float32) => "logf",
        (CoreSymbol::Ln, FloatType::Float64) => "log",
        (CoreSymbol::Sin, FloatType::Float32) => "sinf",
        (CoreSymbol::Sin, FloatType::Float64) => "sin",
        (CoreSymbol::Cos, FloatType::Float32) => "cosf",
        (CoreSymbol::Cos, FloatType::Float64) => "cos",
        (CoreSymbol::Tan, FloatType::Float32) => "tanf",
        (CoreSymbol::Tan, FloatType::Float64) => "tan",
        _ => unreachable!("verified Core floating symbol"),
    }
}

#[allow(clippy::too_many_arguments, clippy::too_many_lines)]
pub(super) fn emit_op(
    output: &mut String,
    call: &CoreCall<SsaOperand>,
    result: u32,
    types: &TypeArena,
    llvm_ty: &str,
    operand: impl Fn(&SsaOperand) -> String,
    unwind: Option<BlockId>,
    block: BlockId,
    io_exception_available: bool,
) {
    let args = call.arguments.iter().map(&operand).collect::<Vec<_>>();
    let ty = call.function.parameter_type;
    match call.function.symbol {
        CoreSymbol::Print | CoreSymbol::Println => {
            let newline = call.function.symbol == CoreSymbol::Println;
            if io_exception_available && let Some(unwind) = unwind {
                writeln!(output, "  %v{result} = invoke i1 @aether_io_stdout(ptr {}, i1 {newline}) to label %core_cont_{}_{} unwind label %bb{}", args[0], block.0, result, unwind.0).unwrap();
                writeln!(output, "core_cont_{}_{}:", block.0, result).unwrap();
            } else if io_exception_available {
                writeln!(
                    output,
                    "  %v{result} = call i1 @aether_io_stdout(ptr {}, i1 {newline})",
                    args[0]
                )
                .unwrap();
            } else {
                writeln!(
                    output,
                    "  call void @aether_string_write(ptr {}, i1 {newline})",
                    args[0]
                )
                .unwrap();
                writeln!(output, "  %v{result} = select i1 true, i1 true, i1 true").unwrap();
            }
        }
        CoreSymbol::ByteLength => {
            writeln!(
                output,
                "  %v{result} = call i64 @aether_string_length(ptr {})",
                args[0]
            )
            .unwrap();
        }
        CoreSymbol::Abs if types.float_info(ty).is_some() => {
            let name = libm_name(call.function.symbol, types.float_info(ty).unwrap());
            writeln!(
                output,
                "  %v{result} = call {llvm_ty} @{name}({llvm_ty} {})",
                args[0]
            )
            .unwrap();
        }
        CoreSymbol::Abs => {
            writeln!(
                output,
                "  %core_neg{result} = icmp slt {llvm_ty} {}, 0",
                args[0]
            )
            .unwrap();
            writeln!(output, "  %core_abs{result} = call {{ {llvm_ty}, i1 }} @llvm.ssub.with.overflow.{llvm_ty}({llvm_ty} 0, {llvm_ty} {})", args[0]).unwrap();
            writeln!(
                output,
                "  %core_abs_value{result} = extractvalue {{ {llvm_ty}, i1 }} %core_abs{result}, 0"
            )
            .unwrap();
            writeln!(output, "  %core_abs_overflow{result} = extractvalue {{ {llvm_ty}, i1 }} %core_abs{result}, 1").unwrap();
            writeln!(
                output,
                "  %core_abs_trap{result} = and i1 %core_neg{result}, %core_abs_overflow{result}"
            )
            .unwrap();
            writeln!(
                output,
                "  call void @aether_core_trap_if(i1 %core_abs_trap{result})"
            )
            .unwrap();
            writeln!(output, "  %v{result} = select i1 %core_neg{result}, {llvm_ty} %core_abs_value{result}, {llvm_ty} {}", args[0]).unwrap();
        }
        CoreSymbol::Min | CoreSymbol::Max | CoreSymbol::Clamp if types.float_info(ty).is_some() => {
            let float = types.float_info(ty).unwrap();
            let first_symbol = if call.function.symbol == CoreSymbol::Min {
                CoreSymbol::Min
            } else {
                CoreSymbol::Max
            };
            let first = libm_name(first_symbol, float);
            writeln!(
                output,
                "  %core_first{result} = call {llvm_ty} @{first}({llvm_ty} {}, {llvm_ty} {})",
                args[0], args[1]
            )
            .unwrap();
            if call.function.symbol == CoreSymbol::Clamp {
                let second = libm_name(CoreSymbol::Min, float);
                writeln!(output, "  %v{result} = call {llvm_ty} @{second}({llvm_ty} %core_first{result}, {llvm_ty} {})", args[2]).unwrap();
            } else {
                writeln!(output, "  %v{result} = select i1 true, {llvm_ty} %core_first{result}, {llvm_ty} %core_first{result}").unwrap();
            }
        }
        CoreSymbol::Min | CoreSymbol::Max | CoreSymbol::Clamp => {
            let signed = types.integer_info(ty).unwrap().is_signed();
            let predicate = if signed { "slt" } else { "ult" };
            writeln!(
                output,
                "  %core_cmp{result} = icmp {predicate} {llvm_ty} {}, {}",
                args[0], args[1]
            )
            .unwrap();
            let (when_true, when_false) = if call.function.symbol == CoreSymbol::Min {
                (&args[0], &args[1])
            } else {
                (&args[1], &args[0])
            };
            writeln!(output, "  %core_first{result} = select i1 %core_cmp{result}, {llvm_ty} {when_true}, {llvm_ty} {when_false}").unwrap();
            if call.function.symbol == CoreSymbol::Clamp {
                writeln!(
                    output,
                    "  %core_cmp_hi{result} = icmp {predicate} {llvm_ty} {}, %core_first{result}",
                    args[2]
                )
                .unwrap();
                writeln!(output, "  %v{result} = select i1 %core_cmp_hi{result}, {llvm_ty} {}, {llvm_ty} %core_first{result}", args[2]).unwrap();
            } else {
                writeln!(output, "  %v{result} = select i1 true, {llvm_ty} %core_first{result}, {llvm_ty} %core_first{result}").unwrap();
            }
        }
        symbol => {
            let name = libm_name(symbol, types.float_info(ty).unwrap());
            writeln!(
                output,
                "  %v{result} = call {llvm_ty} @{name}({llvm_ty} {})",
                args[0]
            )
            .unwrap();
        }
    }
}
