//! Translation of the verified algebraic instruction tree, preserving strict
//! multiplication followed by addition and a single loop-carried accumulator.
use super::{continuation_label, float_operand, llvm_type, mangle_type};
use aether_frontend::TypeArena;
use aether_middle::{
    BinaryOp, BlockId, MathInput, MathStep, Operand, ProductStep, VectorProductKernel,
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
        for (slot, field) in ["ptr", "Dimension", "Stride"].iter().enumerate() {
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
                    if let Some(zero) = &self.kernel.zero {
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
                ProductStep::Math(math) => match math {
                    MathStep::ShapeGuard { axis, .. } => {
                        let next = format!("{p}_shape_ok");
                        writeln!(self.output, "  %{p}_equal = icmp eq i64 %{p}_Left_{axis:?}, %{p}_Right_{axis:?}\n  br i1 %{p}_equal, label %{next}, label %trap_shape_mismatch\n{next}:").unwrap();
                        *current = next;
                    }
                    MathStep::Allocate { .. } => {
                        let suffix = mangle_type(self.types, self.kernel.element_type);
                        let cont = continuation_label(self.block, self.id);
                        writeln!(self.output, "  %{p}_allocated = call {{ ptr, i64, i64 }} @aether_matrix_new_{suffix}(i64 %{p}_extent_Rows, i64 %{p}_extent_Columns)\n  %{p}_data = extractvalue {{ ptr, i64, i64 }} %{p}_allocated, 0\n  %{p}_empty_rows = icmp eq i64 %{p}_extent_Rows, 0\n  %{p}_empty_columns = icmp eq i64 %{p}_extent_Columns, 0\n  %{p}_empty = or i1 %{p}_empty_rows, %{p}_empty_columns\n  br i1 %{p}_empty, label %{p}_empty_result, label %{p}_nonempty\n{p}_empty_result:\n  br label %{cont}\n{p}_nonempty:").unwrap();
                        *current = format!("{p}_nonempty");
                    }
                    MathStep::StridedLoad { input, offset } => {
                        let (axis, stride) = offset[0];
                        writeln!(self.output, "  %{p}_{input:?}_offset = mul i64 %{p}_{axis:?}_index, %{p}_{input:?}_{stride:?}\n  %{p}_{input:?}_slot = getelementptr {et}, ptr %{p}_{input:?}_ptr, i64 %{p}_{input:?}_offset\n  %{p}_{input:?}_value = load {et}, ptr %{p}_{input:?}_slot").unwrap();
                    }
                    MathStep::ScalarBinary { op, .. } => self.scalar(
                        *op,
                        "product",
                        &format!("%{p}_Left_value"),
                        &format!("%{p}_Right_value"),
                        current,
                    ),
                    MathStep::InitializeNext => {
                        writeln!(self.output, "  %{p}_row_base = mul i64 %{p}_Rows_index, %{p}_extent_Columns\n  %{p}_initialized_prefix = add i64 %{p}_row_base, %{p}_Columns_index\n  %{p}_result_slot = getelementptr {et}, ptr %{p}_data, i64 %{p}_initialized_prefix\n  store {et} %{p}_product, ptr %{p}_result_slot ; InitializeNext").unwrap();
                    }
                    MathStep::YieldOwner => {
                        let cont = continuation_label(self.block, self.id);
                        writeln!(self.output, "  br label %{cont}\n{cont}:\n  %v{} = phi {{ ptr, i64, i64 }} [ %{p}_allocated, %{p}_empty_result ], [ %{p}_allocated, %{current} ]\n  ; AlgebraicEnd {}", self.id, self.id).unwrap();
                        *current = cont;
                    }
                    _ => unreachable!("verified closed algebraic schedule"),
                },
            }
        }
    }
}
