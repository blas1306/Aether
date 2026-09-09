//! Closed structured MIR/SSA region for trivial mathematical initialization.
//!
//! These are semantic instructions, not backend hints. `For` binds a zero-based
//! counter in [0, extent), stepping by one. `InitializeNext` writes and advances
//! an initially zero prefix. `YieldOwner` requires the prefix to equal the
//! validated extent product. No instruction can mutate or consume an input.
use crate::{BinaryOp, TrapKind};
use aether_frontend::{TypeArena, TypeData, TypeId};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum MathAxis {
    Dimension,
    Contraction,
    Rows,
    Columns,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum MathStride {
    Stride,
    RowStride,
    ColumnStride,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum MathInput {
    Left,
    Right,
}

/// Explicit structured control flow and initialization instructions.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum MathStep {
    ShapeGuard {
        axis: MathAxis,
        trap: TrapKind,
    },
    Allocate {
        extents: Vec<MathAxis>,
        size_trap: TrapKind,
        failure_trap: TrapKind,
    },
    For {
        axis: MathAxis,
        start: u64,
        step: u64,
        body: Vec<MathStep>,
    },
    StridedLoad {
        input: MathInput,
        offset: Vec<(MathAxis, MathStride)>,
    },
    InvariantScalar {
        input: MathInput,
    },
    ScalarBinary {
        op: BinaryOp,
        element_type: TypeId,
        trap: Option<TrapKind>,
    },
    InitializeNext,
    YieldOwner,
}

/// A region whose only escaping value is a completely initialized fresh owner.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ElementwiseKernel {
    /// Logical rank; Vector orientation stays in the operand/result `TypeIds`.
    pub matrix: bool,
    /// Source side of the scalar, or None for pairwise addition/subtraction.
    pub scalar_side: Option<MathInput>,
    /// Scalar checked/IEEE operator, independently checked against element type.
    pub op: BinaryOp,
    /// Concrete built-in scalar type, never a symbolic storage capability.
    pub element_type: TypeId,
    /// Ordered guards, allocation, structured loops, and complete owner yield.
    pub program: Vec<MathStep>,
}

impl ElementwiseKernel {
    /// Construct the explicit canonical initialization loop.
    #[must_use]
    pub fn new(matrix: bool, op: BinaryOp, element_type: TypeId) -> Self {
        Self::build(matrix, op, element_type, None)
    }

    /// Construct scaling with exactly one descriptor and a loop-invariant scalar.
    #[must_use]
    pub fn new_scalar(matrix: bool, op: BinaryOp, element_type: TypeId, side: MathInput) -> Self {
        Self::build(matrix, op, element_type, Some(side))
    }

    fn build(
        matrix: bool,
        op: BinaryOp,
        element_type: TypeId,
        scalar_side: Option<MathInput>,
    ) -> Self {
        use MathAxis::{Columns, Dimension, Rows};
        let axes = if matrix {
            vec![Rows, Columns]
        } else {
            vec![Dimension]
        };
        let offset = if matrix {
            vec![
                (Rows, MathStride::RowStride),
                (Columns, MathStride::ColumnStride),
            ]
        } else {
            vec![(Dimension, MathStride::Stride)]
        };
        let trap = matches!(
            op,
            BinaryOp::AddIntegerChecked
                | BinaryOp::SubtractIntegerChecked
                | BinaryOp::MultiplyIntegerChecked
        )
        .then_some(TrapKind::IntegerOverflow);
        let mut body = vec![
            MathStep::StridedLoad {
                input: MathInput::Left,
                offset: offset.clone(),
            },
            MathStep::StridedLoad {
                input: MathInput::Right,
                offset,
            },
            MathStep::ScalarBinary {
                op,
                element_type,
                trap,
            },
            MathStep::InitializeNext,
        ];
        if let Some(input) = scalar_side {
            body[usize::from(input == MathInput::Right)] = MathStep::InvariantScalar { input };
        }
        for axis in axes.iter().rev() {
            body = vec![MathStep::For {
                axis: *axis,
                start: 0,
                step: 1,
                body,
            }];
        }
        let mut program: Vec<_> = axes
            .iter()
            .map(|axis| MathStep::ShapeGuard {
                axis: *axis,
                trap: TrapKind::ShapeMismatch,
            })
            .collect();
        if scalar_side.is_some() {
            program.clear();
        }
        program.push(MathStep::Allocate {
            extents: axes,
            size_trap: TrapKind::AllocationSizeOverflow,
            failure_trap: TrapKind::AllocationFailure,
        });
        program.extend(body);
        program.push(MathStep::YieldOwner);
        Self {
            matrix,
            scalar_side,
            op,
            element_type,
            program,
        }
    }

    /// Validate region control, addressing and the complete-prefix induction.
    ///
    /// The closed language admits one canonical schedule: each successful guard
    /// dominates allocation; allocation dominates all loops; nested unit loops
    /// enumerate every logical slot exactly once in row-major order. Their body
    /// loads each descriptor at those coordinates and initializes one next slot.
    /// Equality checks the *entire* executable tree, including ordering, bounds,
    /// stride selectors and trap semantics. No unchecked extension is accepted.
    pub fn verify(
        &self,
        types: &TypeArena,
        left: TypeId,
        right: TypeId,
        result: TypeId,
    ) -> Result<(), String> {
        let element = self.element_type;
        let valid_types = if let Some(side) = self.scalar_side {
            let (scalar, source) = if side == MathInput::Left {
                (left, right)
            } else {
                (right, left)
            };
            scalar == element
                && if self.matrix {
                    types
                        .matrix_view_info(source)
                        .is_some_and(|(t, _)| t == element)
                        && types.matrix_element(result) == Some(element)
                } else {
                    types.vector_view_info(source).is_some_and(|(t, o, _)| {
                        t == element
                            && types.get(result)
                                == Some(&TypeData::Vector {
                                    element,
                                    orientation: o,
                                })
                    })
                }
        } else if self.matrix {
            types
                .matrix_view_info(left)
                .is_some_and(|(t, _)| t == element)
                && types
                    .matrix_view_info(right)
                    .is_some_and(|(t, _)| t == element)
                && types.matrix_element(result) == Some(element)
        } else {
            types.vector_view_info(left).is_some_and(|(t, o, _)| {
                t == element
                    && types
                        .vector_view_info(right)
                        .is_some_and(|(rt, ro, _)| rt == t && ro == o)
                    && types.get(result)
                        == Some(&TypeData::Vector {
                            element,
                            orientation: o,
                        })
            })
        };
        let scalar = crate::mir::binary_contract(types, self.op, element)?;
        let valid_op = if self.scalar_side.is_some() {
            types.supports_builtin_multiply(element)
                && matches!(
                    self.op,
                    BinaryOp::MultiplyIntegerChecked | BinaryOp::MultiplyFloat
                )
        } else {
            types.supports_builtin_add_sub(element)
                && matches!(
                    self.op,
                    BinaryOp::AddIntegerChecked
                        | BinaryOp::SubtractIntegerChecked
                        | BinaryOp::AddFloat
                        | BinaryOp::SubtractFloat
                )
        };
        if !valid_types
            || !valid_op
            || scalar.0 != element
            || scalar.1 != element
            || *self != Self::build(self.matrix, self.op, element, self.scalar_side)
        {
            return Err("elementwise read-only types/shape guards/allocation/stride loop/complete initialization contract invalid".into());
        }
        Ok(())
    }
}
