//! LLVM backend for verified Vertical-6 program SSA.

use std::fmt::Write;

use aether_frontend::{
    CastKind, CoercionKind, EnumInfo, FieldId, FloatType, FloatValue, FunctionSignature,
    IntegerType, ModuleInfo, StructInfo, TargetProperties, Type,
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
    /// The target admitted through NEXT-VERTICAL-6.
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
    writeln!(output, "; Aether NEXT-VERTICAL-6").unwrap();
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

    for info in &program.structs {
        let fields = info
            .fields
            .iter()
            .map(|field| llvm_type(field.ty))
            .collect::<Vec<_>>()
            .join(", ");
        writeln!(
            output,
            "{} = type {{ {fields} }}",
            llvm_type(Type::Struct(info.id))
        )
        .unwrap();
    }
    for info in &program.enums {
        let mut fields = vec!["i32".to_string()];
        fields.extend(info.variants.iter().map(|variant| {
            let payloads = variant
                .payloads
                .iter()
                .map(|payload| llvm_type(payload.ty))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{{ {payloads} }}")
        }));
        writeln!(
            output,
            "{} = type {{ {} }}",
            llvm_type(Type::Enum(info.id)),
            fields.join(", ")
        )
        .unwrap();
    }
    if !program.structs.is_empty() || !program.enums.is_empty() {
        writeln!(output).unwrap();
    }

    for function in &program.functions {
        let signature = &program.signatures[function.id.0 as usize];
        emit_function(
            &mut output,
            function,
            signature,
            &program.signatures,
            &program.modules,
            &program.structs,
            &program.enums,
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
    structs: &[StructInfo],
    enums: &[EnumInfo],
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
    let mut conversion_trap = false;
    let mut division_overflow_trap = false;
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
                SsaOp::Aggregate { struct_id, fields } => {
                    let aggregate_ty = Type::Struct(*struct_id);
                    if fields.is_empty() {
                        writeln!(
                            output,
                            "  %v{} = select i1 true, {} zeroinitializer, {} zeroinitializer",
                            instruction.result.0,
                            llvm_type(aggregate_ty),
                            llvm_type(aggregate_ty)
                        )
                        .unwrap();
                    } else {
                        for (position, (field_id, operand)) in fields.iter().enumerate() {
                            let field = field_info(structs, *field_id);
                            let previous = if position == 0 {
                                "poison".to_string()
                            } else {
                                format!("%agg{}_{}", instruction.result.0, position - 1)
                            };
                            let result_name = if position + 1 == fields.len() {
                                format!("%v{}", instruction.result.0)
                            } else {
                                format!("%agg{}_{}", instruction.result.0, position)
                            };
                            writeln!(
                                output,
                                "  {result_name} = insertvalue {} {previous}, {} {}, {}",
                                llvm_type(aggregate_ty),
                                llvm_type(field.ty),
                                llvm_operand(operand),
                                field.index
                            )
                            .unwrap();
                        }
                    }
                }
                SsaOp::EnumConstruct {
                    enum_id,
                    variant_id,
                    payloads,
                } => {
                    let info = &enums[enum_id.0 as usize];
                    let variant = &info.variants[variant_id.index as usize];
                    let aggregate_ty = Type::Enum(*enum_id);
                    let tag_result = if payloads.is_empty() {
                        format!("%v{}", instruction.result.0)
                    } else {
                        format!("%enum{}_tag", instruction.result.0)
                    };
                    writeln!(
                        output,
                        "  {tag_result} = insertvalue {} zeroinitializer, i32 {}, 0",
                        llvm_type(aggregate_ty),
                        variant.discriminant
                    )
                    .unwrap();
                    for (position, (operand, payload)) in
                        payloads.iter().zip(&variant.payloads).enumerate()
                    {
                        let previous = if position == 0 {
                            tag_result.clone()
                        } else {
                            format!("%enum{}_payload{}", instruction.result.0, position - 1)
                        };
                        let result_name = if position + 1 == payloads.len() {
                            format!("%v{}", instruction.result.0)
                        } else {
                            format!("%enum{}_payload{}", instruction.result.0, position)
                        };
                        writeln!(
                            output,
                            "  {result_name} = insertvalue {} {previous}, {} {}, {}, {}",
                            llvm_type(aggregate_ty),
                            llvm_type(payload.ty),
                            llvm_operand(operand),
                            variant.index + 1,
                            payload.index
                        )
                        .unwrap();
                    }
                }
                SsaOp::EnumDiscriminant { value, enum_id } => {
                    writeln!(
                        output,
                        "  %v{} = extractvalue {} {}, 0",
                        instruction.result.0,
                        llvm_type(Type::Enum(*enum_id)),
                        llvm_operand(value)
                    )
                    .unwrap();
                }
                SsaOp::EnumPayload {
                    value,
                    enum_id,
                    variant_id,
                    index,
                } => {
                    let info = &enums[enum_id.0 as usize];
                    let variant = &info.variants[variant_id.index as usize];
                    writeln!(
                        output,
                        "  %v{} = extractvalue {} {}, {}, {}",
                        instruction.result.0,
                        llvm_type(Type::Enum(*enum_id)),
                        llvm_operand(value),
                        variant.index + 1,
                        index
                    )
                    .unwrap();
                }
                SsaOp::ExtractField {
                    aggregate,
                    projections,
                } => {
                    let aggregate_ty = operand_type(function, aggregate);
                    let indices = llvm_projection_indices(aggregate_ty, projections, structs);
                    writeln!(
                        output,
                        "  %v{} = extractvalue {} {}, {indices}",
                        instruction.result.0,
                        llvm_type(aggregate_ty),
                        llvm_operand(aggregate)
                    )
                    .unwrap();
                }
                SsaOp::InsertField {
                    aggregate,
                    projections,
                    value,
                } => {
                    let aggregate_ty = operand_type(function, aggregate);
                    let value_ty = operand_type(function, value);
                    let indices = llvm_projection_indices(aggregate_ty, projections, structs);
                    writeln!(
                        output,
                        "  %v{} = insertvalue {} {}, {} {}, {indices}",
                        instruction.result.0,
                        llvm_type(aggregate_ty),
                        llvm_operand(aggregate),
                        llvm_type(value_ty),
                        llvm_operand(value)
                    )
                    .unwrap();
                }
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
                SsaOp::Cast {
                    kind,
                    operand,
                    from,
                    trap,
                } => {
                    if *trap == Some(TrapKind::ConversionOutOfRange) {
                        conversion_trap = true;
                    }
                    emit_cast(
                        output,
                        block.id,
                        instruction.result.0,
                        *kind,
                        operand,
                        *from,
                        instruction.ty,
                        *trap,
                    );
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
                        &llvm_type(instruction.ty),
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
                    secondary_trap,
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
                            &llvm_ty,
                            &llvm_operand(left),
                            &llvm_operand(right),
                        );
                    }
                    BinaryOp::DivideIntegerSignedChecked
                    | BinaryOp::DivideIntegerUnsignedChecked
                    | BinaryOp::RemainderIntegerSignedChecked
                    | BinaryOp::RemainderIntegerUnsignedChecked => {
                        division_trap = true;
                        if matches!(op, BinaryOp::DivideIntegerSignedChecked) {
                            division_overflow_trap = true;
                        }
                        emit_integer_division(
                            output,
                            block.id,
                            instruction.result.0,
                            *op,
                            operand_type(function, left),
                            &llvm_operand(left),
                            &llvm_operand(right),
                        );
                        debug_assert_eq!(*trap, Some(TrapKind::DivisionByZero));
                        debug_assert_eq!(
                            *secondary_trap,
                            matches!(op, BinaryOp::DivideIntegerSignedChecked)
                                .then_some(TrapKind::DivisionOverflow)
                        );
                    }
                    BinaryOp::AddFloat
                    | BinaryOp::SubtractFloat
                    | BinaryOp::MultiplyFloat
                    | BinaryOp::DivideFloat => {
                        let opcode = match op {
                            BinaryOp::AddFloat => "fadd",
                            BinaryOp::SubtractFloat => "fsub",
                            BinaryOp::MultiplyFloat => "fmul",
                            BinaryOp::DivideFloat => "fdiv",
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
            SsaTerminator::Switch {
                discriminant,
                cases,
                otherwise,
                ..
            } => {
                let default = otherwise.map_or_else(
                    || format!("switch_unreachable_bb{}", block.id.0),
                    block_label,
                );
                writeln!(
                    output,
                    "  switch i32 {}, label %{default} [",
                    llvm_operand(discriminant)
                )
                .unwrap();
                for (value, target) in cases {
                    writeln!(output, "    i32 {value}, label %{}", block_label(*target)).unwrap();
                }
                writeln!(output, "  ]").unwrap();
                if otherwise.is_none() {
                    writeln!(output, "{default}:\n  unreachable").unwrap();
                }
            }
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
            SsaTerminator::Trap(TrapKind::ConversionOutOfRange) => {
                conversion_trap = true;
                writeln!(output, "  br label %trap_conversion_out_of_range").unwrap();
            }
            SsaTerminator::Trap(TrapKind::DivisionOverflow) => {
                division_overflow_trap = true;
                writeln!(output, "  br label %trap_division_overflow").unwrap();
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
    if conversion_trap {
        writeln!(
            output,
            "trap_conversion_out_of_range:\n  call void @llvm.trap()\n  unreachable"
        )
        .unwrap();
    }
    if division_overflow_trap {
        writeln!(
            output,
            "trap_division_overflow:\n  call void @llvm.trap()\n  unreachable"
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

#[allow(clippy::too_many_arguments)]
fn emit_cast(
    output: &mut String,
    block: BlockId,
    result: u32,
    kind: CastKind,
    operand: &SsaOperand,
    from: Type,
    to: Type,
    trap: Option<TrapKind>,
) {
    let value = llvm_operand(operand);
    match kind {
        CastKind::Identity | CastKind::IntegerReencode => {
            emit_identity(output, result, to, &value);
        }
        CastKind::IntegerExtendSigned => {
            writeln!(
                output,
                "  %v{result} = sext {} {value} to {}",
                llvm_type(from),
                llvm_type(to)
            )
            .unwrap();
        }
        CastKind::IntegerExtendUnsigned => {
            writeln!(
                output,
                "  %v{result} = zext {} {value} to {}",
                llvm_type(from),
                llvm_type(to)
            )
            .unwrap();
        }
        CastKind::IntegerNarrowChecked | CastKind::IntegerSignednessChecked => {
            if trap == Some(TrapKind::ConversionOutOfRange) {
                emit_integer_cast_check(output, block, result, &value, from, to);
            }
            emit_integer_cast_value(output, result, &value, from, to);
        }
        CastKind::SignedIntegerToFloat | CastKind::UnsignedIntegerToFloat => {
            let opcode = if kind == CastKind::SignedIntegerToFloat {
                "sitofp"
            } else {
                "uitofp"
            };
            writeln!(
                output,
                "  %v{result} = {opcode} {} {value} to {}",
                llvm_type(from),
                llvm_type(to)
            )
            .unwrap();
        }
        CastKind::FloatToSignedIntegerChecked | CastKind::FloatToUnsignedIntegerChecked => {
            emit_float_to_integer_check(output, block, result, &value, from, to);
            let opcode = if kind == CastKind::FloatToSignedIntegerChecked {
                "fptosi"
            } else {
                "fptoui"
            };
            writeln!(
                output,
                "  %v{result} = {opcode} {} {value} to {}",
                llvm_type(from),
                llvm_type(to)
            )
            .unwrap();
        }
        CastKind::FloatExtend => {
            writeln!(
                output,
                "  %v{result} = fpext {} {value} to {}",
                llvm_type(from),
                llvm_type(to)
            )
            .unwrap();
        }
        CastKind::FloatTruncate => {
            writeln!(
                output,
                "  %v{result} = fptrunc {} {value} to {}",
                llvm_type(from),
                llvm_type(to)
            )
            .unwrap();
        }
    }
}

fn emit_identity(output: &mut String, result: u32, ty: Type, value: &str) {
    writeln!(
        output,
        "  %v{result} = select i1 true, {} {value}, {} {value}",
        llvm_type(ty),
        llvm_type(ty)
    )
    .unwrap();
}

fn emit_integer_cast_check(
    output: &mut String,
    block: BlockId,
    result: u32,
    value: &str,
    from: Type,
    to: Type,
) {
    let source = from.as_integer().expect("verified integer cast source");
    let target = to.as_integer().expect("verified integer cast target");
    let properties = TargetProperties::LINUX_X86_64;
    let (source_min, source_max) = source.range(properties);
    let (target_min, target_max) = target.range(properties);
    let predicate_prefix = if source.is_signed() { 's' } else { 'u' };
    let mut conditions = Vec::new();
    if target_min > source_min {
        writeln!(
            output,
            "  %cast_lower{result} = icmp {predicate_prefix}ge {} {value}, {target_min}",
            llvm_type(from)
        )
        .unwrap();
        conditions.push(format!("%cast_lower{result}"));
    }
    if target_max < source_max {
        writeln!(
            output,
            "  %cast_upper{result} = icmp {predicate_prefix}le {} {value}, {target_max}",
            llvm_type(from)
        )
        .unwrap();
        conditions.push(format!("%cast_upper{result}"));
    }
    let condition = match conditions.as_slice() {
        [condition] => condition.clone(),
        [lower, upper] => {
            writeln!(output, "  %cast_ok{result} = and i1 {lower}, {upper}").unwrap();
            format!("%cast_ok{result}")
        }
        _ => unreachable!("fallible integer cast has at least one range boundary"),
    };
    writeln!(
        output,
        "  br i1 {condition}, label %{}, label %trap_conversion_out_of_range",
        continuation_label(block, result)
    )
    .unwrap();
    writeln!(output, "{}:", continuation_label(block, result)).unwrap();
}

fn emit_integer_cast_value(output: &mut String, result: u32, value: &str, from: Type, to: Type) {
    let properties = TargetProperties::LINUX_X86_64;
    let source = from.as_integer().unwrap();
    let target = to.as_integer().unwrap();
    match source.bits(properties).cmp(&target.bits(properties)) {
        std::cmp::Ordering::Less => {
            let opcode = if source.is_signed() && target.is_signed() {
                "sext"
            } else {
                "zext"
            };
            writeln!(
                output,
                "  %v{result} = {opcode} {} {value} to {}",
                llvm_type(from),
                llvm_type(to)
            )
            .unwrap();
        }
        std::cmp::Ordering::Greater => writeln!(
            output,
            "  %v{result} = trunc {} {value} to {}",
            llvm_type(from),
            llvm_type(to)
        )
        .unwrap(),
        std::cmp::Ordering::Equal => emit_identity(output, result, to, value),
    }
}

fn emit_float_to_integer_check(
    output: &mut String,
    block: BlockId,
    result: u32,
    value: &str,
    from: Type,
    to: Type,
) {
    let source = from.as_float().unwrap();
    let target = to.as_integer().unwrap();
    let (min, max) = target.range(TargetProperties::LINUX_X86_64);
    let (lower_predicate, lower) = if target.is_signed() {
        let minimum = float_boundary(source, min);
        let below = float_boundary(source, min - 1);
        if below == minimum {
            ("oge", minimum)
        } else {
            ("ogt", below)
        }
    } else {
        ("ogt", float_boundary(source, -1))
    };
    let upper = float_boundary(source, max + 1);
    writeln!(
        output,
        "  %cast_lower{result} = fcmp {lower_predicate} {} {value}, {}",
        llvm_type(from),
        float_operand(lower)
    )
    .unwrap();
    writeln!(
        output,
        "  %cast_upper{result} = fcmp olt {} {value}, {}",
        llvm_type(from),
        float_operand(upper)
    )
    .unwrap();
    writeln!(
        output,
        "  %cast_ok{result} = and i1 %cast_lower{result}, %cast_upper{result}"
    )
    .unwrap();
    writeln!(
        output,
        "  br i1 %cast_ok{result}, label %{}, label %trap_conversion_out_of_range",
        continuation_label(block, result)
    )
    .unwrap();
    writeln!(output, "{}:", continuation_label(block, result)).unwrap();
}

#[allow(clippy::cast_precision_loss)]
fn float_boundary(source: FloatType, value: i128) -> FloatValue {
    match source {
        FloatType::Float32 => FloatValue::Float32((value as f32).to_bits()),
        FloatType::Float64 => FloatValue::Float64((value as f64).to_bits()),
    }
}

fn emit_integer_division(
    output: &mut String,
    block: BlockId,
    result: u32,
    op: BinaryOp,
    ty: Type,
    left: &str,
    right: &str,
) {
    let llvm_ty = llvm_type(ty);
    writeln!(output, "  %div_zero{result} = icmp eq {llvm_ty} {right}, 0").unwrap();
    let nonzero = if matches!(
        op,
        BinaryOp::DivideIntegerUnsignedChecked | BinaryOp::RemainderIntegerUnsignedChecked
    ) {
        continuation_label(block, result)
    } else {
        format!("bb{}_nonzero_v{result}", block.0)
    };
    writeln!(
        output,
        "  br i1 %div_zero{result}, label %trap_division_by_zero, label %{nonzero}"
    )
    .unwrap();
    writeln!(output, "{nonzero}:").unwrap();
    match op {
        BinaryOp::DivideIntegerUnsignedChecked | BinaryOp::RemainderIntegerUnsignedChecked => {
            let opcode = if matches!(op, BinaryOp::DivideIntegerUnsignedChecked) {
                "udiv"
            } else {
                "urem"
            };
            writeln!(output, "  %v{result} = {opcode} {llvm_ty} {left}, {right}").unwrap();
        }
        BinaryOp::DivideIntegerSignedChecked => {
            let integer = ty.as_integer().unwrap();
            let min = integer.range(TargetProperties::LINUX_X86_64).0;
            writeln!(
                output,
                "  %div_min{result} = icmp eq {llvm_ty} {left}, {min}"
            )
            .unwrap();
            writeln!(
                output,
                "  %div_neg_one{result} = icmp eq {llvm_ty} {right}, -1"
            )
            .unwrap();
            writeln!(
                output,
                "  %div_overflow{result} = and i1 %div_min{result}, %div_neg_one{result}"
            )
            .unwrap();
            writeln!(
                output,
                "  br i1 %div_overflow{result}, label %trap_division_overflow, label %{}",
                continuation_label(block, result)
            )
            .unwrap();
            writeln!(output, "{}:", continuation_label(block, result)).unwrap();
            writeln!(output, "  %v{result} = sdiv {llvm_ty} {left}, {right}").unwrap();
        }
        BinaryOp::RemainderIntegerSignedChecked => {
            let integer = ty.as_integer().unwrap();
            let min = integer.range(TargetProperties::LINUX_X86_64).0;
            let special = format!("bb{}_remainder_min_v{result}", block.0);
            let normal = format!("bb{}_remainder_normal_v{result}", block.0);
            writeln!(
                output,
                "  %rem_min{result} = icmp eq {llvm_ty} {left}, {min}"
            )
            .unwrap();
            writeln!(
                output,
                "  %rem_neg_one{result} = icmp eq {llvm_ty} {right}, -1"
            )
            .unwrap();
            writeln!(
                output,
                "  %rem_special{result} = and i1 %rem_min{result}, %rem_neg_one{result}"
            )
            .unwrap();
            writeln!(
                output,
                "  br i1 %rem_special{result}, label %{special}, label %{normal}"
            )
            .unwrap();
            writeln!(
                output,
                "{special}:\n  br label %{}",
                continuation_label(block, result)
            )
            .unwrap();
            writeln!(output, "{normal}:").unwrap();
            writeln!(
                output,
                "  %rem_value{result} = srem {llvm_ty} {left}, {right}"
            )
            .unwrap();
            writeln!(output, "  br label %{}", continuation_label(block, result)).unwrap();
            writeln!(output, "{}:", continuation_label(block, result)).unwrap();
            writeln!(
                output,
                "  %v{result} = phi {llvm_ty} [ 0, %{special} ], [ %rem_value{result}, %{normal} ]"
            )
            .unwrap();
        }
        _ => unreachable!("verified integer division opcode"),
    }
}

fn is_checked(op: &SsaOp) -> bool {
    matches!(
        op,
        SsaOp::Unary {
            op: UnaryOp::NegateIntegerChecked,
            ..
        } | SsaOp::Cast {
            trap: Some(TrapKind::ConversionOutOfRange),
            ..
        } | SsaOp::Binary {
            op: BinaryOp::AddIntegerChecked
                | BinaryOp::SubtractIntegerChecked
                | BinaryOp::MultiplyIntegerChecked
                | BinaryOp::DivideIntegerSignedChecked
                | BinaryOp::DivideIntegerUnsignedChecked
                | BinaryOp::RemainderIntegerSignedChecked
                | BinaryOp::RemainderIntegerUnsignedChecked,
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

fn llvm_type(ty: Type) -> String {
    match ty {
        Type::Bool => "i1".into(),
        Type::Integer(IntegerType::Int8 | IntegerType::Uint8) => "i8".into(),
        Type::Integer(IntegerType::Int16 | IntegerType::Uint16) => "i16".into(),
        Type::Integer(IntegerType::Int32 | IntegerType::Uint32) => "i32".into(),
        Type::Integer(
            IntegerType::Int64 | IntegerType::Uint64 | IntegerType::Isize | IntegerType::Usize,
        ) => "i64".into(),
        Type::Float(FloatType::Float32) => "float".into(),
        Type::Float(FloatType::Float64) => "double".into(),
        Type::Struct(id) => format!("%aether.struct.{}", id.0),
        Type::Enum(id) => format!("%aether.enum.{}", id.0),
    }
}

fn field_info(structs: &[StructInfo], id: FieldId) -> &aether_frontend::FieldInfo {
    structs
        .iter()
        .find_map(|info| info.fields.iter().find(|field| field.id == id))
        .expect("verified field identity")
}

fn llvm_projection_indices(
    mut ty: Type,
    projections: &[FieldId],
    structs: &[StructInfo],
) -> String {
    projections
        .iter()
        .map(|field_id| {
            let owner = ty.as_struct().expect("verified projection owner");
            let field = structs[owner.0 as usize]
                .fields
                .iter()
                .find(|field| field.id == *field_id)
                .expect("verified projection field");
            ty = field.ty;
            field.index.to_string()
        })
        .collect::<Vec<_>>()
        .join(", ")
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
    let bits = match value {
        // LLVM spells non-double hexadecimal constants with the exact double
        // encoding of the represented value.
        FloatValue::Float32(bits) => f64::from(f32::from_bits(bits)).to_bits(),
        FloatValue::Float64(bits) => bits,
    };
    format!("0x{bits:016X}")
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

    #[test]
    fn emits_explicit_scalar_conversion_instructions_and_checks() {
        let output = llvm(
            "int main(){int64 x=127;int8 y=int8(x);uint16 u=uint16(y);float64 f=double(u);float32 g=float32(f);return int32(g);}",
        );
        assert!(output.contains("trunc i64"));
        assert!(output.contains("zext i8"));
        assert!(output.contains("uitofp i16"));
        assert!(output.contains("fptrunc double"));
        assert!(output.contains("fptosi float"));
        assert!(output.contains("trap_conversion_out_of_range"));
    }

    #[test]
    fn emits_checked_integer_and_ieee_float_division() {
        let output = llvm(
            "int64 q(int64 a,int64 b){return a/b;}int64 r(int64 a,int64 b){return a%b;}float64 f(float64 a,float64 b){return a/b;}int main(){return q(5,2)+r(5,2)+int(f(4.0,2.0));}",
        );
        assert!(output.contains("icmp eq i64"));
        assert!(output.contains("trap_division_by_zero"));
        assert!(output.contains("trap_division_overflow"));
        assert!(output.contains(" = sdiv i64 "));
        assert!(output.contains(" = srem i64 "));
        assert!(output.contains(" = fdiv double "));
    }

    #[test]
    fn emits_typed_enum_envelope_payload_ops_and_switch() {
        let output = llvm(
            "enum E{A,B(int,bool),}int main(){E e=E.B(42,true);match(e){E.A=>{return 0;}E.B(x,yes)=>{if(yes){return x;}return 0;}}}",
        );
        assert!(output.contains("%aether.enum.0 = type { i32, {  }, { i64, i1 } }"));
        assert!(output.contains("insertvalue %aether.enum.0"));
        assert!(output.contains("extractvalue %aether.enum.0"));
        assert!(output.contains("switch i32"));
    }
}
