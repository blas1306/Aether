//! LLVM backend for verified Vertical-2 program SSA.

use std::fmt::Write;

use aether_frontend::{FunctionSignature, ModuleInfo, Type};
use aether_middle::{
    BinaryOp, BlockId, SsaFunction, SsaOp, SsaOperand, SsaTerminator, TrapKind, UnaryOp,
    VerifiedSsa,
};

/// Minimal explicit target contract for the admitted bootstrap platform.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TargetDescriptor {
    /// LLVM target triple.
    pub triple: &'static str,
}

impl TargetDescriptor {
    /// The target admitted by NEXT-VERTICAL-2.
    #[must_use]
    pub const fn linux_x86_64() -> Self {
        Self {
            triple: "x86_64-unknown-linux-gnu",
        }
    }
}

/// Backend boundary: only verified SSA can cross it.
pub trait Backend {
    /// Produces a complete backend module.
    fn emit(&self, ssa: &VerifiedSsa, target: &TargetDescriptor) -> String;
}

/// Bootstrap textual LLVM backend.
#[derive(Clone, Copy, Debug, Default)]
pub struct LlvmTextBackend;

impl Backend for LlvmTextBackend {
    fn emit(&self, ssa: &VerifiedSsa, target: &TargetDescriptor) -> String {
        emit_llvm(ssa, target)
    }
}

/// Lowers verified program SSA to deterministic textual LLVM IR.
#[must_use]
pub fn emit_llvm(ssa: &VerifiedSsa, target: &TargetDescriptor) -> String {
    let program = ssa.as_ssa();
    let mut output = String::new();
    writeln!(output, "; Aether NEXT-VERTICAL-2").unwrap();
    writeln!(
        output,
        "; Internal bootstrap ABI and symbol mangling; not a public Aether ABI"
    )
    .unwrap();
    writeln!(output, "target triple = \"{}\"\n", target.triple).unwrap();
    writeln!(
        output,
        "declare {{ i64, i1 }} @llvm.sadd.with.overflow.i64(i64, i64)"
    )
    .unwrap();
    writeln!(
        output,
        "declare {{ i64, i1 }} @llvm.ssub.with.overflow.i64(i64, i64)"
    )
    .unwrap();
    writeln!(
        output,
        "declare {{ i64, i1 }} @llvm.smul.with.overflow.i64(i64, i64)"
    )
    .unwrap();
    writeln!(output, "declare void @llvm.trap() cold noreturn nounwind\n").unwrap();

    for function in &program.functions {
        let signature = &program.signatures[function.id.0 as usize];
        emit_function(
            &mut output,
            function,
            signature,
            &program.signatures,
            &program.modules,
        );
    }

    let entry = &program.signatures[program.entry.0 as usize];
    writeln!(output, "define i32 @main() {{").unwrap();
    writeln!(output, "entry:").unwrap();
    writeln!(
        output,
        "  %aether_result = call i64 @{}()",
        bootstrap_symbol(entry, &program.modules)
    )
    .unwrap();
    writeln!(
        output,
        "  %process_status = trunc i64 %aether_result to i32"
    )
    .unwrap();
    writeln!(output, "  ret i32 %process_status").unwrap();
    writeln!(output, "}}").unwrap();
    output
}

#[allow(clippy::too_many_lines)]
fn emit_function(
    output: &mut String,
    function: &SsaFunction,
    signature: &FunctionSignature,
    signatures: &[FunctionSignature],
    modules: &[ModuleInfo],
) {
    let parameters = function
        .parameters
        .iter()
        .map(|parameter| format!("{} %v{}", llvm_type(parameter.ty), parameter.value.0))
        .collect::<Vec<_>>()
        .join(", ");
    writeln!(
        output,
        "define {} @{}({parameters}) {{",
        llvm_type(signature.return_type),
        bootstrap_symbol(signature, modules)
    )
    .unwrap();

    let exit_labels: Vec<String> = function
        .blocks
        .iter()
        .map(|block| {
            block
                .instructions
                .iter()
                .rev()
                .find(|instruction| is_checked(&instruction.op))
                .map_or_else(
                    || block_label(block.id),
                    |instruction| continuation_label(block.id, instruction.result.0),
                )
        })
        .collect();
    let mut overflow_trap = false;
    let mut division_trap = false;
    for block in &function.blocks {
        writeln!(output, "{}:", block_label(block.id)).unwrap();
        for phi in &block.phis {
            let incoming = phi
                .incoming
                .iter()
                .map(|(predecessor, value)| {
                    format!(
                        "[ %v{}, %{} ]",
                        value.0, exit_labels[predecessor.0 as usize]
                    )
                })
                .collect::<Vec<_>>()
                .join(", ");
            writeln!(
                output,
                "  %v{} = phi {} {}",
                phi.result.0,
                llvm_type(phi.ty),
                incoming
            )
            .unwrap();
        }
        for instruction in &block.instructions {
            match &instruction.op {
                SsaOp::Use(operand) => match instruction.ty {
                    Type::Int64 => writeln!(
                        output,
                        "  %v{} = add i64 {}, 0",
                        instruction.result.0,
                        llvm_operand(operand)
                    )
                    .unwrap(),
                    Type::Bool => writeln!(
                        output,
                        "  %v{} = or i1 {}, false",
                        instruction.result.0,
                        llvm_operand(operand)
                    )
                    .unwrap(),
                },
                SsaOp::Unary {
                    op: UnaryOp::NegateChecked,
                    operand,
                    trap: TrapKind::IntegerOverflow,
                } => {
                    overflow_trap = true;
                    emit_checked(
                        output,
                        block.id,
                        instruction.result.0,
                        "llvm.ssub.with.overflow.i64",
                        "0",
                        &llvm_operand(operand),
                    );
                }
                SsaOp::Unary {
                    trap: TrapKind::DivisionByZero,
                    ..
                } => unreachable!("verified unary trap contract"),
                SsaOp::Binary {
                    op,
                    left,
                    right,
                    trap,
                } => match op {
                    BinaryOp::AddChecked
                    | BinaryOp::SubtractChecked
                    | BinaryOp::MultiplyChecked => {
                        overflow_trap = true;
                        let intrinsic = match op {
                            BinaryOp::AddChecked => "llvm.sadd.with.overflow.i64",
                            BinaryOp::SubtractChecked => "llvm.ssub.with.overflow.i64",
                            BinaryOp::MultiplyChecked => "llvm.smul.with.overflow.i64",
                            _ => unreachable!(),
                        };
                        debug_assert_eq!(*trap, Some(TrapKind::IntegerOverflow));
                        emit_checked(
                            output,
                            block.id,
                            instruction.result.0,
                            intrinsic,
                            &llvm_operand(left),
                            &llvm_operand(right),
                        );
                    }
                    BinaryOp::Less
                    | BinaryOp::LessEqual
                    | BinaryOp::Greater
                    | BinaryOp::GreaterEqual
                    | BinaryOp::Equal
                    | BinaryOp::NotEqual => {
                        let predicate = match op {
                            BinaryOp::Less => "slt",
                            BinaryOp::LessEqual => "sle",
                            BinaryOp::Greater => "sgt",
                            BinaryOp::GreaterEqual => "sge",
                            BinaryOp::Equal => "eq",
                            BinaryOp::NotEqual => "ne",
                            _ => unreachable!(),
                        };
                        let operand_ty = operand_type(function, left);
                        writeln!(
                            output,
                            "  %v{} = icmp {} {} {}, {}",
                            instruction.result.0,
                            predicate,
                            llvm_type(operand_ty),
                            llvm_operand(left),
                            llvm_operand(right)
                        )
                        .unwrap();
                    }
                },
                SsaOp::Call { callee, args } => {
                    let callee_signature = &signatures[callee.0 as usize];
                    let arguments = args
                        .iter()
                        .zip(&callee_signature.parameters)
                        .map(|(argument, parameter)| {
                            format!("{} {}", llvm_type(parameter.ty), llvm_operand(argument))
                        })
                        .collect::<Vec<_>>()
                        .join(", ");
                    writeln!(
                        output,
                        "  %v{} = call {} @{}({arguments})",
                        instruction.result.0,
                        llvm_type(callee_signature.return_type),
                        bootstrap_symbol(callee_signature, modules)
                    )
                    .unwrap();
                }
            }
        }
        match &block.terminator {
            SsaTerminator::Goto(target) => {
                writeln!(output, "  br label %{}", block_label(*target)).unwrap();
            }
            SsaTerminator::Branch {
                condition,
                then_block,
                else_block,
            } => writeln!(
                output,
                "  br i1 {}, label %{}, label %{}",
                llvm_operand(condition),
                block_label(*then_block),
                block_label(*else_block)
            )
            .unwrap(),
            SsaTerminator::Return(value) => writeln!(
                output,
                "  ret {} {}",
                llvm_type(signature.return_type),
                llvm_operand(value)
            )
            .unwrap(),
            SsaTerminator::Trap(TrapKind::IntegerOverflow) => {
                overflow_trap = true;
                writeln!(output, "  br label %trap_integer_overflow").unwrap();
            }
            SsaTerminator::Trap(TrapKind::DivisionByZero) => {
                division_trap = true;
                writeln!(output, "  br label %trap_division_by_zero").unwrap();
            }
        }
    }
    if overflow_trap {
        writeln!(
            output,
            "trap_integer_overflow:\n  call void @llvm.trap()\n  unreachable"
        )
        .unwrap();
    }
    if division_trap {
        writeln!(
            output,
            "trap_division_by_zero:\n  call void @llvm.trap()\n  unreachable"
        )
        .unwrap();
    }
    writeln!(output, "}}\n").unwrap();
}

fn emit_checked(
    output: &mut String,
    block: BlockId,
    result: u32,
    intrinsic: &str,
    left: &str,
    right: &str,
) {
    writeln!(
        output,
        "  %checked{result} = call {{ i64, i1 }} @{intrinsic}(i64 {left}, i64 {right})"
    )
    .unwrap();
    writeln!(
        output,
        "  %v{result} = extractvalue {{ i64, i1 }} %checked{result}, 0"
    )
    .unwrap();
    writeln!(
        output,
        "  %overflow{result} = extractvalue {{ i64, i1 }} %checked{result}, 1"
    )
    .unwrap();
    writeln!(
        output,
        "  br i1 %overflow{result}, label %trap_integer_overflow, label %{}",
        continuation_label(block, result)
    )
    .unwrap();
    writeln!(output, "{}:", continuation_label(block, result)).unwrap();
}

fn is_checked(op: &SsaOp) -> bool {
    matches!(
        op,
        SsaOp::Unary { .. }
            | SsaOp::Binary {
                op: BinaryOp::AddChecked | BinaryOp::SubtractChecked | BinaryOp::MultiplyChecked,
                ..
            }
    )
}

fn bootstrap_symbol(signature: &FunctionSignature, modules: &[ModuleInfo]) -> String {
    let module = &modules[signature.module.0 as usize];
    bootstrap_symbol_for(&module.name, &signature.name)
}

fn block_label(block: BlockId) -> String {
    format!("bb{}", block.0)
}

fn continuation_label(block: BlockId, result: u32) -> String {
    format!("bb{}_after_v{}", block.0, result)
}

fn llvm_type(ty: Type) -> &'static str {
    match ty {
        Type::Int64 => "i64",
        Type::Bool => "i1",
    }
}

fn llvm_operand(operand: &SsaOperand) -> String {
    match operand {
        SsaOperand::Value(value) => format!("%v{}", value.0),
        SsaOperand::Int(value) => value.to_string(),
        SsaOperand::Bool(value) => value.to_string(),
    }
}

fn operand_type(function: &SsaFunction, operand: &SsaOperand) -> Type {
    match operand {
        SsaOperand::Int(_) => Type::Int64,
        SsaOperand::Bool(_) => Type::Bool,
        SsaOperand::Value(value) => function
            .parameters
            .iter()
            .find(|parameter| parameter.value == *value)
            .map(|parameter| parameter.ty)
            .or_else(|| {
                function.blocks.iter().find_map(|block| {
                    block
                        .phis
                        .iter()
                        .find(|phi| phi.result == *value)
                        .map(|phi| phi.ty)
                        .or_else(|| {
                            block
                                .instructions
                                .iter()
                                .find(|instruction| instruction.result == *value)
                                .map(|instruction| instruction.ty)
                        })
                })
            })
            .expect("verified SSA value has definition"),
    }
}

/// Exposes deterministic bootstrap mangling for qualification without making it public ABI.
#[must_use]
pub fn bootstrap_symbol_for(module: &str, function: &str) -> String {
    format!(
        "__aether_v2_m{}_{}_f{}_{}",
        module.len(),
        escape_symbol_part(module),
        function.len(),
        escape_symbol_part(function)
    )
}

fn escape_symbol_part(name: &str) -> String {
    let mut escaped = String::new();
    for byte in name.bytes() {
        if byte.is_ascii_alphanumeric() {
            escaped.push(char::from(byte));
        } else {
            write!(escaped, "_{byte:02x}").unwrap();
        }
    }
    escaped
}

#[cfg(test)]
mod tests {
    use super::*;
    use aether_frontend::{SourceFile, analyze, parse_source};
    use aether_middle::{build_ssa, lower_hir, verify_mir, verify_ssa};

    fn llvm(text: &str) -> String {
        let hir = analyze(parse_source(&SourceFile::new("test.ae", text)).unwrap()).unwrap();
        let mir = verify_mir(lower_hir(hir)).unwrap();
        let ssa = verify_ssa(build_ssa(&mir)).unwrap();
        emit_llvm(&ssa, &TargetDescriptor::linux_x86_64())
    }

    #[test]
    fn emits_checked_arithmetic_and_phi() {
        let output = llvm("int main(){int i=0;while(i<3){i=i+1;}return i;}");
        assert!(output.contains("llvm.sadd.with.overflow.i64"));
        assert!(output.contains(" = phi i64 "));
        assert!(output.contains("trap_integer_overflow"));
        assert!(!output.contains(" add nsw "));
    }

    #[test]
    fn emits_functions_bool_signatures_calls_and_wrapper() {
        let output = llvm(
            "bool positive(int x){return x>0;}int main(){if(positive(5)){return 1;}return 0;}",
        );
        assert!(output.contains("define i1 @__aether_v2_m4_main_f8_positive(i64 %v0)"));
        assert!(output.contains("call i1 @__aether_v2_m4_main_f8_positive(i64 5)"));
        assert!(output.contains("define i32 @main()"));
    }

    #[test]
    fn bootstrap_symbols_are_identity_based_and_deterministic() {
        assert_eq!(
            bootstrap_symbol_for("math", "add"),
            "__aether_v2_m4_math_f3_add"
        );
        assert_ne!(
            bootstrap_symbol_for("a_b", "c"),
            bootstrap_symbol_for("a", "b_c")
        );
    }
}
