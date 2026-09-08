//! Translation of verified structured MIR/SSA math instructions to LLVM CFG.
use super::{continuation_label, llvm_type, mangle_type};
use aether_frontend::TypeArena;
use aether_middle::{BinaryOp, BlockId, ElementwiseKernel, MathAxis, MathInput, MathStep};
use std::fmt::Write;

pub(super) fn emit(
    output: &mut String,
    types: &TypeArena,
    kernel: &ElementwiseKernel,
    inputs: [(&str, &str); 2],
    id: u32,
    block: BlockId,
) {
    let prefix = format!("ew{id}");
    let result_ty = if kernel.matrix {
        "{ ptr, i64, i64 }"
    } else {
        "{ ptr, i64 }"
    };
    writeln!(
        output,
        "  ; ElementwiseBegin {id}\n  br label %{prefix}_entry\n{prefix}_entry:"
    )
    .unwrap();
    for ((ty, value), input) in inputs.into_iter().zip([MathInput::Left, MathInput::Right]) {
        if kernel.scalar_side == Some(input) {
            continue;
        }
        let fields: &[&str] = if kernel.matrix {
            &["ptr", "Rows", "Columns", "RowStride", "ColumnStride"]
        } else {
            &["ptr", "Dimension", "Stride"]
        };
        for (slot, field) in fields.iter().enumerate() {
            writeln!(
                output,
                "  %{prefix}_{input:?}_{field} = extractvalue {ty} {value}, {slot}"
            )
            .unwrap();
        }
    }
    let mut emitter = Emitter {
        output,
        types,
        kernel,
        prefix,
        result_ty,
        id,
        block,
        scalar: kernel
            .scalar_side
            .map(|side| inputs[usize::from(side == MathInput::Right)].1.to_owned()),
    };
    let mut current = format!("ew{id}_entry");
    emitter.steps(&kernel.program, &mut current);
}

struct Emitter<'a> {
    output: &'a mut String,
    types: &'a TypeArena,
    kernel: &'a ElementwiseKernel,
    prefix: String,
    result_ty: &'static str,
    id: u32,
    block: BlockId,
    scalar: Option<String>,
}
impl Emitter<'_> {
    #[allow(clippy::too_many_lines)]
    fn steps(&mut self, steps: &[MathStep], current: &mut String) {
        let p = self.prefix.clone();
        let source = if self.kernel.scalar_side == Some(MathInput::Left) {
            "Right"
        } else {
            "Left"
        };
        let et = llvm_type(self.types, self.kernel.element_type);
        for step in steps {
            match step {
                MathStep::ShapeGuard { axis, .. } => {
                    let next = format!("{p}_shape_{axis:?}");
                    writeln!(self.output, "  %{p}_equal_{axis:?} = icmp eq i64 %{p}_Left_{axis:?}, %{p}_Right_{axis:?}\n  br i1 %{p}_equal_{axis:?}, label %{next}, label %trap_shape_mismatch\n{next}:").unwrap();
                    *current = next;
                }
                MathStep::Allocate { extents, .. } => {
                    let axis = extents[0];
                    writeln!(self.output, "  %{p}_empty = icmp eq i64 %{p}_{source}_{axis:?}, 0\n  br i1 %{p}_empty, label %{p}_empty_result, label %{p}_allocate\n{p}_empty_result:\n  br label %{}\n{p}_allocate:", continuation_label(self.block,self.id)).unwrap();
                    let suffix = mangle_type(self.types, self.kernel.element_type);
                    let args = extents
                        .iter()
                        .map(|a| format!("i64 %{p}_{source}_{a:?}"))
                        .collect::<Vec<_>>()
                        .join(", ");
                    let helper = if self.kernel.matrix {
                        "matrix"
                    } else {
                        "fixed"
                    };
                    writeln!(self.output, "  %{p}_allocated = call {} @aether_{helper}_new_{suffix}({args})\n  %{p}_data = extractvalue {} %{p}_allocated, 0", self.result_ty,self.result_ty).unwrap();
                    *current = format!("{p}_allocate");
                }
                MathStep::For {
                    axis,
                    start,
                    step,
                    body,
                } => {
                    let a = format!("{p}_{axis:?}");
                    writeln!(self.output, "  br label %{a}_header\n{a}_header:\n  %{a}_index = phi i64 [ {start}, %{current} ], [ %{a}_next, %{a}_latch ]\n  %{a}_more = icmp ult i64 %{a}_index, %{p}_{source}_{axis:?}\n  br i1 %{a}_more, label %{a}_body, label %{a}_done\n{a}_body:").unwrap();
                    *current = format!("{a}_body");
                    self.steps(body, current);
                    writeln!(self.output, "  br label %{a}_latch\n{a}_latch:\n  %{a}_next = add i64 %{a}_index, {step}\n  br label %{a}_header\n{a}_done:").unwrap();
                    *current = format!("{a}_done");
                }
                MathStep::StridedLoad { input, offset } => {
                    let mut terms = Vec::new();
                    for (axis, stride) in offset {
                        let term = format!("%{p}_{input:?}_{axis:?}_offset");
                        writeln!(
                            self.output,
                            "  {term} = mul i64 %{p}_{axis:?}_index, %{p}_{input:?}_{stride:?}"
                        )
                        .unwrap();
                        terms.push(term);
                    }
                    let offset = if terms.len() == 1 {
                        terms[0].clone()
                    } else {
                        writeln!(
                            self.output,
                            "  %{p}_{input:?}_offset = add i64 {}, {}",
                            terms[0], terms[1]
                        )
                        .unwrap();
                        format!("%{p}_{input:?}_offset")
                    };
                    writeln!(self.output, "  %{p}_{input:?}_slot = getelementptr {et}, ptr %{p}_{input:?}_ptr, i64 {offset}\n  %{p}_{input:?}_value = load {et}, ptr %{p}_{input:?}_slot").unwrap();
                }
                MathStep::InvariantScalar { .. } => {} // Captured before the region; no per-element load.
                MathStep::ScalarBinary { op, .. } => {
                    let left = if self.kernel.scalar_side == Some(MathInput::Left) {
                        self.scalar.clone().unwrap()
                    } else {
                        format!("%{p}_Left_value")
                    };
                    let right = if self.kernel.scalar_side == Some(MathInput::Right) {
                        self.scalar.clone().unwrap()
                    } else {
                        format!("%{p}_Right_value")
                    };
                    if let Some(integer) = self.types.integer_info(self.kernel.element_type) {
                        let sign = if integer.is_signed() { 's' } else { 'u' };
                        let name = match op {
                            BinaryOp::AddIntegerChecked => "add",
                            BinaryOp::SubtractIntegerChecked => "sub",
                            BinaryOp::MultiplyIntegerChecked => "mul",
                            _ => unreachable!("verified integer math"),
                        };
                        writeln!(self.output, "  %{p}_checked = call {{ {et}, i1 }} @llvm.{sign}{name}.with.overflow.{et}({et} {left}, {et} {right})\n  %{p}_overflow = extractvalue {{ {et}, i1 }} %{p}_checked, 1\n  br i1 %{p}_overflow, label %trap_integer_overflow, label %{p}_scalar_ok\n{p}_scalar_ok:\n  %{p}_value = extractvalue {{ {et}, i1 }} %{p}_checked, 0").unwrap();
                        *current = format!("{p}_scalar_ok");
                    } else {
                        let name = match op {
                            BinaryOp::AddFloat => "fadd",
                            BinaryOp::SubtractFloat => "fsub",
                            BinaryOp::MultiplyFloat => "fmul",
                            _ => unreachable!("verified float math"),
                        };
                        writeln!(self.output, "  %{p}_value = {name} {et} {left}, {right}")
                            .unwrap();
                    }
                }
                MathStep::InitializeNext => {
                    let index = if self.kernel.matrix {
                        writeln!(self.output, "  %{p}_row_base = mul i64 %{p}_Rows_index, %{p}_{source}_Columns\n  %{p}_initialized_prefix = add i64 %{p}_row_base, %{p}_Columns_index").unwrap();
                        format!("%{p}_initialized_prefix")
                    } else {
                        format!("%{p}_{:?}_index", MathAxis::Dimension)
                    };
                    writeln!(self.output, "  %{p}_result_slot = getelementptr {et}, ptr %{p}_data, i64 {index}\n  store {et} %{p}_value, ptr %{p}_result_slot ; InitializeNext").unwrap();
                }
                MathStep::YieldOwner => {
                    let cont = continuation_label(self.block, self.id);
                    writeln!(self.output, "  br label %{cont}\n{cont}:\n  %v{} = phi {} [ zeroinitializer, %{p}_empty_result ], [ %{p}_allocated, %{current} ]\n  ; ElementwiseEnd {}",self.id,self.result_ty,self.id).unwrap();
                    *current = cont;
                }
            }
        }
    }
}
