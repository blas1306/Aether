//! Closed algebraic schedules. Both MIR and SSA verify the complete executable
//! tree before LLVM translates it. No capability or symbolic value lives here.
use crate::{BinaryOp, MathAxis, MathInput, MathStep, MathStride, Operand, TrapKind};
use aether_frontend::{FloatType, FloatValue, Orientation, TypeArena, TypeId};

/// Closed computational forms, distinct from frontend semantic product metadata.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum ProductKind {
    ReductionKernel,
    OuterProductKernel,
    MatrixColumnKernel,
    RowMatrixKernel,
    MatrixMatrixKernel,
}

/// Scalar reduction or fully initialized owner, with scoped ordered accumulators.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum ProductStep {
    ShapeGuardPair {
        left_axis: MathAxis,
        right_axis: MathAxis,
        trap: TrapKind,
    },
    SelectSourceExtent {
        axis: MathAxis,
        input: MathInput,
        source_axis: MathAxis,
    },
    EmptyMatrixResultBypass {
        rows: MathAxis,
        columns: MathAxis,
    },
    EmptyResultBypass {
        axis: MathAxis,
    },
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
pub struct AlgebraicProductKernel {
    pub kind: ProductKind,
    pub element_type: TypeId,
    pub product_op: BinaryOp,
    pub accumulate_op: Option<BinaryOp>,
    pub zero: Option<Operand>,
    pub program: Vec<ProductStep>,
}

impl AlgebraicProductKernel {
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

    /// Map of reductions. Result and contraction axes are independent; only the
    /// result axis controls allocation and the overall empty bypass.
    #[must_use]
    pub fn new_matrix_vector(
        element_type: TypeId,
        product_op: BinaryOp,
        accumulate_op: BinaryOp,
        zero: Operand,
        matrix: MathInput,
    ) -> Self {
        use MathAxis::{Columns, Dimension, Rows};
        use MathInput::{Left, Right};
        let left = matrix == Left;
        let result = if left { Rows } else { Columns };
        let contraction = if left { Columns } else { Rows };
        let trap = matches!(product_op, BinaryOp::MultiplyIntegerChecked)
            .then_some(TrapKind::IntegerOverflow);
        let load = |input| {
            ProductStep::Math(MathStep::StridedLoad {
                input,
                offset: if input == matrix {
                    vec![
                        (Rows, MathStride::RowStride),
                        (Columns, MathStride::ColumnStride),
                    ]
                } else {
                    vec![(contraction, MathStride::Stride)]
                },
            })
        };
        let program = vec![
            ProductStep::ShapeGuardPair {
                left_axis: if left { Columns } else { Dimension },
                right_axis: if left { Dimension } else { Rows },
                trap: TrapKind::ShapeMismatch,
            },
            ProductStep::SelectSourceExtent {
                axis: result,
                input: matrix,
                source_axis: result,
            },
            ProductStep::SelectSourceExtent {
                axis: contraction,
                input: matrix,
                source_axis: contraction,
            },
            ProductStep::EmptyResultBypass { axis: result },
            ProductStep::Math(MathStep::Allocate {
                extents: vec![result],
                size_trap: TrapKind::AllocationSizeOverflow,
                failure_trap: TrapKind::AllocationFailure,
            }),
            ProductStep::For {
                axis: result,
                start: 0,
                step: 1,
                body: vec![
                    ProductStep::AccumulatorInit {
                        value: zero.clone(),
                    },
                    ProductStep::For {
                        axis: contraction,
                        start: 0,
                        step: 1,
                        body: vec![
                            load(Left),
                            load(Right),
                            ProductStep::Math(MathStep::ScalarBinary {
                                op: product_op,
                                element_type,
                                trap,
                            }),
                            ProductStep::Accumulate {
                                op: accumulate_op,
                                element_type,
                                trap,
                            },
                        ],
                    },
                    ProductStep::Math(MathStep::InitializeNext),
                ],
            },
            ProductStep::Math(MathStep::YieldOwner),
        ];
        Self {
            kind: if left {
                ProductKind::MatrixColumnKernel
            } else {
                ProductKind::RowMatrixKernel
            },
            element_type,
            product_op,
            accumulate_op: Some(accumulate_op),
            zero: Some(zero),
            program,
        }
    }

    /// Two output axes and one independent contraction axis. The closed tree
    /// defines rows -> columns -> contraction, with one Zero/store per cell.
    #[must_use]
    pub fn new_matrix_matrix(
        element_type: TypeId,
        product_op: BinaryOp,
        accumulate_op: BinaryOp,
        zero: Operand,
    ) -> Self {
        use MathAxis::{Columns, Contraction, Rows};
        use MathInput::{Left, Right};
        let trap = matches!(product_op, BinaryOp::MultiplyIntegerChecked)
            .then_some(TrapKind::IntegerOverflow);
        let program = vec![
            ProductStep::ShapeGuardPair {
                left_axis: Columns,
                right_axis: Rows,
                trap: TrapKind::ShapeMismatch,
            },
            ProductStep::SelectSourceExtent {
                axis: Rows,
                input: Left,
                source_axis: Rows,
            },
            ProductStep::SelectSourceExtent {
                axis: Columns,
                input: Right,
                source_axis: Columns,
            },
            ProductStep::SelectSourceExtent {
                axis: Contraction,
                input: Left,
                source_axis: Columns,
            },
            ProductStep::EmptyMatrixResultBypass {
                rows: Rows,
                columns: Columns,
            },
            ProductStep::Math(MathStep::Allocate {
                extents: vec![Rows, Columns],
                size_trap: TrapKind::AllocationSizeOverflow,
                failure_trap: TrapKind::AllocationFailure,
            }),
            ProductStep::For {
                axis: Rows,
                start: 0,
                step: 1,
                body: vec![ProductStep::For {
                    axis: Columns,
                    start: 0,
                    step: 1,
                    body: vec![
                        ProductStep::AccumulatorInit {
                            value: zero.clone(),
                        },
                        ProductStep::For {
                            axis: Contraction,
                            start: 0,
                            step: 1,
                            body: vec![
                                ProductStep::Math(MathStep::StridedLoad {
                                    input: Left,
                                    offset: vec![
                                        (Rows, MathStride::RowStride),
                                        (Contraction, MathStride::ColumnStride),
                                    ],
                                }),
                                ProductStep::Math(MathStep::StridedLoad {
                                    input: Right,
                                    offset: vec![
                                        (Contraction, MathStride::RowStride),
                                        (Columns, MathStride::ColumnStride),
                                    ],
                                }),
                                ProductStep::Math(MathStep::ScalarBinary {
                                    op: product_op,
                                    element_type,
                                    trap,
                                }),
                                ProductStep::Accumulate {
                                    op: accumulate_op,
                                    element_type,
                                    trap,
                                },
                            ],
                        },
                        ProductStep::Math(MathStep::InitializeNext),
                    ],
                }],
            },
            ProductStep::Math(MathStep::YieldOwner),
        ];
        Self {
            kind: ProductKind::MatrixMatrixKernel,
            element_type,
            product_op,
            accumulate_op: Some(accumulate_op),
            zero: Some(zero),
            program,
        }
    }

    /// The contraction loop binding the ordered accumulator, if present.
    /// This is never an authority for result emptiness or allocation size:
    /// those use the separate output selectors in the canonical recipe.
    #[must_use]
    pub fn reduction_axis(&self) -> Option<MathAxis> {
        match self.kind {
            ProductKind::ReductionKernel => Some(MathAxis::Dimension),
            ProductKind::MatrixColumnKernel => Some(MathAxis::Columns),
            ProductKind::RowMatrixKernel => Some(MathAxis::Rows),
            ProductKind::MatrixMatrixKernel => Some(MathAxis::Contraction),
            ProductKind::OuterProductKernel => None,
        }
    }

    /// Matrix source for the two map-reduction families.
    #[must_use]
    pub fn matrix_input(&self) -> Option<MathInput> {
        match self.kind {
            ProductKind::MatrixColumnKernel => Some(MathInput::Left),
            ProductKind::RowMatrixKernel => Some(MathInput::Right),
            _ => None,
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
        if self.kind == ProductKind::MatrixMatrixKernel {
            if !types.supports_builtin_multiply(e)
                || types.needs_drop(e)
                || types.matrix_view_info(left).is_none_or(|(t, _)| t != e)
                || types.matrix_view_info(right).is_none_or(|(t, _)| t != e)
                || types.matrix_element(result) != Some(e)
                || *self != Self::new_matrix_matrix(e, mul, add, zero)
            {
                return Err("Matrix algebraic map-reduction sources/result/three extents/guard/allocation/strides/zero/row-column-contraction initialization schedule invalid".into());
            }
            return Ok(());
        }
        if let Some(matrix) = self.matrix_input() {
            let (mt, vt, orientation) = if matrix == MathInput::Left {
                (left, right, Orientation::Column)
            } else {
                (right, left, Orientation::Row)
            };
            if !types.supports_builtin_multiply(e)
                || types.needs_drop(e)
                || types.matrix_view_info(mt).is_none_or(|(t, _)| t != e)
                || !input(vt, orientation)
                || types.vector_element(result) != Some(e)
                || types.vector_like_info(result) != Some((e, orientation))
                || *self != Self::new_matrix_vector(e, mul, add, zero, matrix)
            {
                return Err("algebraic map-reduction source/result orientation, result/contraction extent, guard/allocation/stride/zero/ordered initialization schedule invalid".into());
            }
            return Ok(());
        }
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
