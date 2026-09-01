//! LLVM backend for verified Vertical-3 program SSA.

use std::fmt::Write;

use aether_frontend::{
    CoercionKind, FloatType, FloatValue, FunctionSignature, IntegerType, ModuleInfo,
    TargetProperties, Type,
};
use aether_middle::{
    BinaryOp, BlockId, SsaFunction, SsaOp, SsaOperand, SsaTerminator, TrapKind, UnaryOp,
    VerifiedSsa,
};

/// Minimal explicit target contract for the admitted bootstrap platform.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TargetDescriptor {
    /// LLVM target triple.
    pub triple: &'static str,
    /// Semantic/layout properties shared with type analysis.
    pub properties: TargetProperties,
}

impl TargetDescriptor {
    /// The target admitted by NEXT-VERTICAL-3.
    #[must_use]
    pub const fn linux_x86_64() -> Self {
        Self {
            triple: "x86_64-unknown-linux-gnu",
            properties: TargetProperties::LINUX_X86_64,
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
    writeln!(output, "; Aether NEXT-VERTICAL-3").unwrap();
    writeln!(
        output,
        "; Internal bootstrap ABI and symbol mangling; not a public Aether ABI"
    )
    .unwrap();
    writeln!(output, "target triple = \"{}\"\n", target.triple).unwrap();
    for bits in [8, 16, 32, 64] {
        for family in ['s', 'u'] {
            for op in ["add", "sub", "mul"] {
                writeln!(output,"declare {{ i{bits}, i1 }} @llvm.{family}{op}.with.overflow.i{bits}(i{bits}, i{bits})").unwrap();
            }
        }
    }
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
                SsaOp::Use(operand) => writeln!(
                    output,
                    "  %v{} = select i1 true, {} {}, {} {}",
                    instruction.result.0,
                    llvm_type(instruction.ty),
                    llvm_operand(operand),
                    llvm_type(instruction.ty),
                    llvm_operand(operand)
                )
                .unwrap(),
                SsaOp::Coerce {
                    kind,
                    operand,
                    from,
                } => {
                    let opcode = match kind {
                        CoercionKind::SignExtend => "sext",
                        CoercionKind::ZeroExtend => "zext",
                        CoercionKind::FloatExtend => "fpext",
                    };
                    writeln!(
                        output,
                        "  %v{} = {opcode} {} {} to {}",
                        instruction.result.0,
                        llvm_type(*from),
                        llvm_operand(operand),
                        llvm_type(instruction.ty)
                    )
                    .unwrap();
                }
                SsaOp::Unary {
                    op: UnaryOp::NegateIntegerChecked,
                    operand,
                    trap: Some(TrapKind::IntegerOverflow),
                } => {
                    overflow_trap = true;
                    emit_checked(
                        output,
                        block.id,
                        instruction.result.0,
                        &format!("llvm.ssub.with.overflow.{}", llvm_type(instruction.ty)),
                        llvm_type(instruction.ty),
                        "0",
                        &llvm_operand(operand),
                    );
                }
                SsaOp::Unary {
                    op: UnaryOp::NegateFloat,
                    operand,
                    trap: None,
                } => {
                    writeln!(
                        output,
                        "  %v{} = fneg {} {}",
                        instruction.result.0,
                        llvm_type(instruction.ty),
                        llvm_operand(operand)
                    )
                    .unwrap();
                }
                SsaOp::Unary { .. } => unreachable!("verified unary trap contract"),
                SsaOp::Binary {
                    op,
                    left,
                    right,
                    trap,
                } => match op {
                    BinaryOp::AddIntegerChecked
                    | BinaryOp::SubtractIntegerChecked
                    | BinaryOp::MultiplyIntegerChecked => {
                        overflow_trap = true;
                        let operand_ty = operand_type(function, left);
                        let integer = operand_ty.as_integer().expect("verified integer op");
                        let prefix = if integer.is_signed() { 's' } else { 'u' };
                        let opname = match op {
                            BinaryOp::AddIntegerChecked => "add",
                            BinaryOp::SubtractIntegerChecked => "sub",
                            BinaryOp::MultiplyIntegerChecked => "mul",
                            _ => unreachable!(),
                        };
                        let llvm_ty = llvm_type(operand_ty);
                        let intrinsic = format!("llvm.{prefix}{opname}.with.overflow.{llvm_ty}");
                        debug_assert_eq!(*trap, Some(TrapKind::IntegerOverflow));
                        emit_checked(
                            output,
                            block.id,
                            instruction.result.0,
                            &intrinsic,
                            llvm_ty,
                            &llvm_operand(left),
                            &llvm_operand(right),
                        );
                    }
                    BinaryOp::AddFloat | BinaryOp::SubtractFloat | BinaryOp::MultiplyFloat => {
                        let opcode = match op {
                            BinaryOp::AddFloat => "fadd",
                            BinaryOp::SubtractFloat => "fsub",
                            BinaryOp::MultiplyFloat => "fmul",
                            _ => unreachable!(),
                        };
                        writeln!(
                            output,
                            "  %v{} = {opcode} {} {}, {}",
                            instruction.result.0,
                            llvm_type(operand_type(function, left)),
                            llvm_operand(left),
                            llvm_operand(right)
                        )
                        .unwrap();
                    }
                    BinaryOp::Less
                    | BinaryOp::LessEqual
                    | BinaryOp::Greater
                    | BinaryOp::GreaterEqual
                    | BinaryOp::Equal
                    | BinaryOp::NotEqual => {
                        let operand_ty = operand_type(function, left);
                        if let Type::Float(_) = operand_ty {
                            let predicate = match op {
                                BinaryOp::Less => "olt",
                                BinaryOp::LessEqual => "ole",
                                BinaryOp::Greater => "ogt",
                                BinaryOp::GreaterEqual => "oge",
                                BinaryOp::Equal => "oeq",
                                BinaryOp::NotEqual => "une",
                                _ => unreachable!(),
                            };
                            writeln!(
                                output,
                                "  %v{} = fcmp {predicate} {} {}, {}",
                                instruction.result.0,
                                llvm_type(operand_ty),
                                llvm_operand(left),
                                llvm_operand(right)
                            )
                            .unwrap();
                        } else {
                            let signed =
                                operand_ty.as_integer().is_some_and(IntegerType::is_signed);
                            let predicate = match op {
                                BinaryOp::Less => {
                                    if signed {
                                        "slt"
                                    } else {
                                        "ult"
                                    }
                                }
                                BinaryOp::LessEqual => {
                                    if signed {
                                        "sle"
                                    } else {
                                        "ule"
                                    }
                                }
                                BinaryOp::Greater => {
                                    if signed {
                                        "sgt"
                                    } else {
                                        "ugt"
                                    }
                                }
                                BinaryOp::GreaterEqual => {
                                    if signed {
                                        "sge"
                                    } else {
                                        "uge"
                                    }
                                }
                                BinaryOp::Equal => "eq",
                                BinaryOp::NotEqual => "ne",
                                _ => unreachable!(),
                            };
                            writeln!(
                                output,
                                "  %v{} = icmp {predicate} {} {}, {}",
                                instruction.result.0,
                                llvm_type(operand_ty),
                                llvm_operand(left),
                                llvm_operand(right)
                            )
                            .unwrap();
                        }
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
    ty: &str,
    left: &str,
    right: &str,
) {
    writeln!(
        output,
        "  %checked{result} = call {{ {ty}, i1 }} @{intrinsic}({ty} {left}, {ty} {right})"
    )
    .unwrap();
    writeln!(
        output,
        "  %v{result} = extractvalue {{ {ty}, i1 }} %checked{result}, 0"
    )
    .unwrap();
    writeln!(
        output,
        "  %overflow{result} = extractvalue {{ {ty}, i1 }} %checked{result}, 1"
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
        SsaOp::Unary {
            op: UnaryOp::NegateIntegerChecked,
            ..
        } | SsaOp::Binary {
            op: BinaryOp::AddIntegerChecked
                | BinaryOp::SubtractIntegerChecked
                | BinaryOp::MultiplyIntegerChecked,
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
        Type::Bool => "i1",
        Type::Integer(IntegerType::Int8 | IntegerType::Uint8) => "i8",
        Type::Integer(IntegerType::Int16 | IntegerType::Uint16) => "i16",
        Type::Integer(IntegerType::Int32 | IntegerType::Uint32) => "i32",
        Type::Integer(
            IntegerType::Int64 | IntegerType::Uint64 | IntegerType::Isize | IntegerType::Usize,
        ) => "i64",
        Type::Float(FloatType::Float32) => "float",
        Type::Float(FloatType::Float64) => "double",
    }
}

fn llvm_operand(operand: &SsaOperand) -> String {
    match operand {
        SsaOperand::Value(value) => format!("%v{}", value.0),
        SsaOperand::Int { value, .. } => value.to_string(),
        SsaOperand::Float { value, .. } => float_operand(*value),
        SsaOperand::Bool(value) => value.to_string(),
    }
}

fn operand_type(function: &SsaFunction, operand: &SsaOperand) -> Type {
    match operand {
        SsaOperand::Int { ty, .. } | SsaOperand::Float { ty, .. } => *ty,
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

fn float_operand(value: FloatValue) -> String {
    let mut s = match value {
        FloatValue::Float32(bits) => f32::from_bits(bits).to_string(),
        FloatValue::Float64(bits) => f64::from_bits(bits).to_string(),
    };
    if !s.contains(['.', 'e', 'E']) {
        s.push_str(".0");
    }
    s
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
