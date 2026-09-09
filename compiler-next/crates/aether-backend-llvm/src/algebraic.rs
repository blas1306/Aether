//! Translation of the verified algebraic instruction tree, preserving strict
//! multiplication followed by addition and a single loop-carried accumulator.
use super::{continuation_label, float_operand, llvm_type, mangle_type};
use aether_frontend::TypeArena;
use aether_middle::{
    BinaryOp, BlockId, MathAxis, MathInput, MathStep, Operand, ProductKind, ProductStep,
    VectorProductKernel,
};
use std::fmt::Write;

pub(super) fn emit(
    output: &mut String,
    types: &TypeArena,
    kernel: &VectorProductKernel,
    inputs: [(&str, &str); 2],
    id: u32,
    block: BlockId,
) {
    let prefix = format!("vp{id}");
    writeln!(
        output,
        "  ; AlgebraicBegin {id} {:?}\n  br label %{prefix}_entry\n{prefix}_entry:",
        kernel.kind
    )
    .unwrap();
    for ((ty, value), input) in inputs.into_iter().zip([MathInput::Left, MathInput::Right]) {
        let fields: &[&str] = if kernel.matrix_input() == Some(input)
            || kernel.kind == ProductKind::MatrixMatrixKernel
        {
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
        id,
        block,
    };
    emitter.steps(&kernel.program, &mut format!("vp{id}_entry"));
}

struct Emitter<'a> {
    output: &'a mut String,
    types: &'a TypeArena,
    kernel: &'a VectorProductKernel,
    prefix: String,
    id: u32,
    block: BlockId,
}
impl Emitter<'_> {
    fn scalar(&mut self, op: BinaryOp, name: &str, left: &str, right: &str, current: &mut String) {
        let p = &self.prefix;
        let et = llvm_type(self.types, self.kernel.element_type);
        let mul = matches!(
            op,
            BinaryOp::MultiplyIntegerChecked | BinaryOp::MultiplyFloat
        );
        if let Some(integer) = self.types.integer_info(self.kernel.element_type) {
            let sign = if integer.is_signed() { 's' } else { 'u' };
            let operation = if mul { "mul" } else { "add" };
            writeln!(self.output, "  %{p}_{name}_checked = call {{ {et}, i1 }} @llvm.{sign}{operation}.with.overflow.{et}({et} {left}, {et} {right})\n  %{p}_{name}_overflow = extractvalue {{ {et}, i1 }} %{p}_{name}_checked, 1\n  br i1 %{p}_{name}_overflow, label %trap_integer_overflow, label %{p}_{name}_ok\n{p}_{name}_ok:\n  %{p}_{name} = extractvalue {{ {et}, i1 }} %{p}_{name}_checked, 0").unwrap();
            *current = format!("{p}_{name}_ok");
        } else {
            let operation = if mul { "fmul" } else { "fadd" };
            writeln!(
                self.output,
                "  %{p}_{name} = {operation} {et} {left}, {right}"
            )
            .unwrap();
        }
    }

    #[allow(clippy::too_many_lines)]
    fn steps(&mut self, steps: &[ProductStep], current: &mut String) {
        let p = self.prefix.clone();
        let et = llvm_type(self.types, self.kernel.element_type);
        for step in steps {
            match step {
                ProductStep::ShapeGuardPair {
                    left_axis,
                    right_axis,
                    ..
                } => {
                    let next = format!("{p}_shape_ok");
                    writeln!(self.output, "  %{p}_equal = icmp eq i64 %{p}_Left_{left_axis:?}, %{p}_Right_{right_axis:?}\n  br i1 %{p}_equal, label %{next}, label %trap_shape_mismatch\n{next}:").unwrap();
                    *current = next;
                }
                ProductStep::SelectSourceExtent {
                    axis,
                    input,
                    source_axis,
                } => {
                    writeln!(
                        self.output,
                        "  %{p}_extent_{axis:?} = add i64 %{p}_{input:?}_{source_axis:?}, 0"
                    )
                    .unwrap();
                }
                ProductStep::EmptyMatrixResultBypass { rows, columns } => {
                    let cont = continuation_label(self.block, self.id);
                    writeln!(self.output, "  %{p}_empty_rows = icmp eq i64 %{p}_extent_{rows:?}, 0\n  %{p}_empty_columns = icmp eq i64 %{p}_extent_{columns:?}, 0\n  %{p}_empty = or i1 %{p}_empty_rows, %{p}_empty_columns\n  br i1 %{p}_empty, label %{p}_empty_result, label %{p}_allocate\n{p}_empty_result:\n  %{p}_empty_shape = insertvalue {{ ptr, i64, i64 }} zeroinitializer, i64 %{p}_extent_{rows:?}, 1\n  %{p}_empty_owner = insertvalue {{ ptr, i64, i64 }} %{p}_empty_shape, i64 %{p}_extent_{columns:?}, 2\n  br label %{cont}\n{p}_allocate:").unwrap();
                    *current = format!("{p}_allocate");
                }
                ProductStep::EmptyResultBypass { axis } => {
                    let cont = continuation_label(self.block, self.id);
                    writeln!(self.output, "  %{p}_empty = icmp eq i64 %{p}_extent_{axis:?}, 0\n  br i1 %{p}_empty, label %{p}_empty_result, label %{p}_allocate\n{p}_empty_result:\n  br label %{cont}\n{p}_allocate:").unwrap();
                    *current = format!("{p}_allocate");
                }
                ProductStep::SelectExtent { axis, input } => {
                    writeln!(
                        self.output,
                        "  %{p}_extent_{axis:?} = add i64 %{p}_{input:?}_Dimension, 0"
                    )
                    .unwrap();
                }
                ProductStep::AccumulatorInit { .. } => {} // Concrete constant is the entry value of the accumulator phi.
                ProductStep::For {
                    axis,
                    start,
                    step,
                    body,
                } => {
                    let a = format!("{p}_{axis:?}");
                    writeln!(self.output, "  br label %{a}_header\n{a}_header:\n  %{a}_index = phi i64 [ {start}, %{current} ], [ %{a}_next, %{a}_latch ]").unwrap();
                    // Accumulator is bound by the reduction loop only, and reset
                    // on each outer iteration, including zero-trip contractions.
                    if let Some(zero) = &self.kernel.zero
                        && self.kernel.reduction_axis() == Some(*axis)
                    {
                        let z = match zero {
                            Operand::Int { value, .. } => value.to_string(),
                            Operand::Float { value, .. } => float_operand(*value),
                            _ => unreachable!("verified concrete zero"),
                        };
                        writeln!(self.output, "  %{p}_accumulator = phi {et} [ {z}, %{current} ], [ %{p}_accumulate, %{a}_latch ]").unwrap();
                    }
                    writeln!(self.output, "  %{a}_more = icmp ult i64 %{a}_index, %{p}_extent_{axis:?}\n  br i1 %{a}_more, label %{a}_body, label %{a}_done\n{a}_body:").unwrap();
                    *current = format!("{a}_body");
                    self.steps(body, current);
                    writeln!(self.output, "  br label %{a}_latch\n{a}_latch:\n  %{a}_next = add i64 %{a}_index, {step}\n  br label %{a}_header\n{a}_done:").unwrap();
                    *current = format!("{a}_done");
                }
                ProductStep::Accumulate { op, .. } => self.scalar(
                    *op,
                    "accumulate",
                    &format!("%{p}_accumulator"),
                    &format!("%{p}_product"),
                    current,
                ),
                ProductStep::YieldScalar => {
                    let cont = continuation_label(self.block, self.id);
                    writeln!(self.output, "  br label %{cont}\n{cont}:\n  %v{} = phi {et} [ %{p}_accumulator, %{current} ]\n  ; AlgebraicEnd {}", self.id, self.id).unwrap();
                    *current = cont;
                }
                ProductStep::Math(math) => {
                    match math {
                        MathStep::ShapeGuard { axis, .. } => {
                            let next = format!("{p}_shape_ok");
                            writeln!(self.output, "  %{p}_equal = icmp eq i64 %{p}_Left_{axis:?}, %{p}_Right_{axis:?}\n  br i1 %{p}_equal, label %{next}, label %trap_shape_mismatch\n{next}:").unwrap();
                            *current = next;
                        }
                        MathStep::Allocate { extents, .. } => {
                            if self.kernel.kind == ProductKind::MatrixMatrixKernel {
                                let suffix = mangle_type(self.types, self.kernel.element_type);
                                writeln!(self.output, "  %{p}_allocated = call {{ ptr, i64, i64 }} @aether_matrix_new_{suffix}(i64 %{p}_extent_Rows, i64 %{p}_extent_Columns)\n  %{p}_data = extractvalue {{ ptr, i64, i64 }} %{p}_allocated, 0").unwrap();
                                continue;
                            }
                            if self.kernel.matrix_input().is_some() {
                                let suffix = mangle_type(self.types, self.kernel.element_type);
                                let axis = extents[0];
                                writeln!(self.output, "  %{p}_allocated = call {{ ptr, i64 }} @aether_fixed_new_{suffix}(i64 %{p}_extent_{axis:?})\n  %{p}_data = extractvalue {{ ptr, i64 }} %{p}_allocated, 0").unwrap();
                                continue;
                            }
                            let suffix = mangle_type(self.types, self.kernel.element_type);
                            let cont = continuation_label(self.block, self.id);
                            writeln!(self.output, "  %{p}_allocated = call {{ ptr, i64, i64 }} @aether_matrix_new_{suffix}(i64 %{p}_extent_Rows, i64 %{p}_extent_Columns)\n  %{p}_data = extractvalue {{ ptr, i64, i64 }} %{p}_allocated, 0\n  %{p}_empty_rows = icmp eq i64 %{p}_extent_Rows, 0\n  %{p}_empty_columns = icmp eq i64 %{p}_extent_Columns, 0\n  %{p}_empty = or i1 %{p}_empty_rows, %{p}_empty_columns\n  br i1 %{p}_empty, label %{p}_empty_result, label %{p}_nonempty\n{p}_empty_result:\n  br label %{cont}\n{p}_nonempty:").unwrap();
                            *current = format!("{p}_nonempty");
                        }
                        MathStep::StridedLoad { input, offset } => {
                            let mut terms = Vec::new();
                            for (axis, stride) in offset {
                                let term = format!("%{p}_{input:?}_{axis:?}_offset");
                                writeln!(self.output, "  {term} = mul i64 %{p}_{axis:?}_index, %{p}_{input:?}_{stride:?}").unwrap();
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
                        MathStep::ScalarBinary { op, .. } => self.scalar(
                            *op,
                            "product",
                            &format!("%{p}_Left_value"),
                            &format!("%{p}_Right_value"),
                            current,
                        ),
                        MathStep::InitializeNext => {
                            if let Some(matrix) = self.kernel.matrix_input() {
                                let axis = if matrix == MathInput::Left {
                                    MathAxis::Rows
                                } else {
                                    MathAxis::Columns
                                };
                                writeln!(self.output, "  %{p}_result_slot = getelementptr {et}, ptr %{p}_data, i64 %{p}_{axis:?}_index\n  store {et} %{p}_accumulator, ptr %{p}_result_slot ; InitializeNext").unwrap();
                                continue;
                            }
                            let value = if self.kernel.kind == ProductKind::MatrixMatrixKernel {
                                "accumulator"
                            } else {
                                "product"
                            };
                            writeln!(self.output, "  %{p}_row_base = mul i64 %{p}_Rows_index, %{p}_extent_Columns\n  %{p}_initialized_prefix = add i64 %{p}_row_base, %{p}_Columns_index\n  %{p}_result_slot = getelementptr {et}, ptr %{p}_data, i64 %{p}_initialized_prefix\n  store {et} %{p}_{value}, ptr %{p}_result_slot ; InitializeNext").unwrap();
                        }
                        MathStep::YieldOwner => {
                            let cont = continuation_label(self.block, self.id);
                            if self.kernel.matrix_input().is_some() {
                                writeln!(self.output, "  br label %{cont}\n{cont}:\n  %v{} = phi {{ ptr, i64 }} [ zeroinitializer, %{p}_empty_result ], [ %{p}_allocated, %{current} ]\n  ; AlgebraicEnd {}", self.id, self.id).unwrap();
                                *current = cont;
                                continue;
                            }
                            let empty = if self.kernel.kind == ProductKind::MatrixMatrixKernel {
                                "empty_owner"
                            } else {
                                "allocated"
                            };
                            writeln!(self.output, "  br label %{cont}\n{cont}:\n  %v{} = phi {{ ptr, i64, i64 }} [ %{p}_{empty}, %{p}_empty_result ], [ %{p}_allocated, %{current} ]\n  ; AlgebraicEnd {}", self.id, self.id).unwrap();
                            *current = cont;
                        }
                        _ => unreachable!("verified closed algebraic schedule"),
                    }
                }
            }
        }
    }
}
