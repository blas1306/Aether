//! Closed algebraic schedules. Both MIR and SSA verify the complete executable
//! tree before LLVM translates it. No capability or symbolic value lives here.
use crate::{BinaryOp, MathAxis, MathInput, MathStep, MathStride, Operand, TrapKind};
use aether_frontend::{FloatType, FloatValue, Orientation, TypeArena, TypeId};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum ProductKind {
    ReductionKernel,
    OuterProductKernel,
}

/// Single accumulator or fully initialized owner; never both.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum ProductStep {
    SelectExtent {
        axis: MathAxis,
        input: MathInput,
    },
    Math(MathStep),
    AccumulatorInit {
        value: Operand,
    },
    For {
        axis: MathAxis,
        start: u64,
        step: u64,
        body: Vec<ProductStep>,
    },
    Accumulate {
        op: BinaryOp,
        element_type: TypeId,
        trap: Option<TrapKind>,
    },
    YieldScalar,
}

#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub struct VectorProductKernel {
    pub kind: ProductKind,
    pub element_type: TypeId,
    pub product_op: BinaryOp,
    pub accumulate_op: Option<BinaryOp>,
    pub zero: Option<Operand>,
    pub program: Vec<ProductStep>,
}

impl VectorProductKernel {
    /// Build a closed schedule from concretized HIR metadata.
    #[must_use]
    pub fn new(
        element_type: TypeId,
        product_op: BinaryOp,
        reduction: Option<(BinaryOp, Operand)>,
    ) -> Self {
        use MathAxis::{Columns, Dimension, Rows};
        use MathInput::{Left, Right};
        let inner = reduction.is_some();
        let trap = matches!(product_op, BinaryOp::MultiplyIntegerChecked)
            .then_some(TrapKind::IntegerOverflow);
        let mut body = vec![
            ProductStep::Math(MathStep::StridedLoad {
                input: Left,
                offset: vec![(if inner { Dimension } else { Rows }, MathStride::Stride)],
            }),
            ProductStep::Math(MathStep::StridedLoad {
                input: Right,
                offset: vec![(if inner { Dimension } else { Columns }, MathStride::Stride)],
            }),
            ProductStep::Math(MathStep::ScalarBinary {
                op: product_op,
                element_type,
                trap,
            }),
        ];
        if let Some((op, _)) = &reduction {
            body.push(ProductStep::Accumulate {
                op: *op,
                element_type,
                trap,
            });
        } else {
            body.push(ProductStep::Math(MathStep::InitializeNext));
        }
        let axes = if inner {
            vec![Dimension]
        } else {
            vec![Rows, Columns]
        };
        for axis in axes.iter().rev() {
            body = vec![ProductStep::For {
                axis: *axis,
                start: 0,
                step: 1,
                body,
            }];
        }
        let mut program = if let Some((_, zero)) = &reduction {
            vec![
                ProductStep::Math(MathStep::ShapeGuard {
                    axis: Dimension,
                    trap: TrapKind::ShapeMismatch,
                }),
                ProductStep::SelectExtent {
                    axis: Dimension,
                    input: Left,
                },
                ProductStep::AccumulatorInit {
                    value: zero.clone(),
                },
            ]
        } else {
            vec![
                ProductStep::SelectExtent {
                    axis: Rows,
                    input: Left,
                },
                ProductStep::SelectExtent {
                    axis: Columns,
                    input: Right,
                },
                ProductStep::Math(MathStep::Allocate {
                    extents: axes,
                    size_trap: TrapKind::AllocationSizeOverflow,
                    failure_trap: TrapKind::AllocationFailure,
                }),
            ]
        };
        program.extend(body);
        program.push(if inner {
            ProductStep::YieldScalar
        } else {
            ProductStep::Math(MathStep::YieldOwner)
        });
        Self {
            kind: if inner {
                ProductKind::ReductionKernel
            } else {
                ProductKind::OuterProductKernel
            },
            element_type,
            product_op,
            accumulate_op: reduction.as_ref().map(|r| r.0),
            zero: reduction.map(|r| r.1),
            program,
        }
    }

    /// Check concrete types, orientation, independent strides, extents, guard
    /// dominance, exactly one accumulator and ordered complete initialization.
    pub fn verify(
        &self,
        types: &TypeArena,
        left: TypeId,
        right: TypeId,
        result: TypeId,
    ) -> Result<(), String> {
        let inner = self.kind == ProductKind::ReductionKernel;
        let e = self.element_type;
        let (lo, ro) = if inner {
            (Orientation::Row, Orientation::Column)
        } else {
            (Orientation::Column, Orientation::Row)
        };
        let input = |t, o| {
            types
                .vector_view_info(t)
                .is_some_and(|(et, orient, _)| et == e && orient == o)
        };
        let integer = types.integer_info(e).is_some();
        let mul = if integer {
            BinaryOp::MultiplyIntegerChecked
        } else {
            BinaryOp::MultiplyFloat
        };
        let add = if integer {
            BinaryOp::AddIntegerChecked
        } else {
            BinaryOp::AddFloat
        };
        let zero = if integer {
            Operand::Int { value: 0, ty: e }
        } else {
            Operand::Float {
                value: if types.float_info(e) == Some(FloatType::Float32) {
                    FloatValue::Float32(0)
                } else {
                    FloatValue::Float64(0)
                },
                ty: e,
            }
        };
        if !types.supports_builtin_multiply(e)
            || types.needs_drop(e)
            || !input(left, lo)
            || !input(right, ro)
            || (if inner {
                result != e
            } else {
                types.matrix_element(result) != Some(e)
            })
            || *self != Self::new(e, mul, inner.then_some((add, zero)))
        {
            return Err("algebraic kernel orientation/result/guard/stride/operations/accumulator/initialization schedule invalid".into());
        }
        Ok(())
    }
}
