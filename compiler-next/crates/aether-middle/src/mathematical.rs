//! Shared vocabulary for closed mathematical recipes, not a programmable IR.
//!
//! Descriptor axes (Dimension/Rows/Columns) select source extents. Loop axes
//! bind logical coordinates; their role comes from the exact product recipe.
//! In rank-1 products Rows/Columns bind output/contraction in the appropriate
//! order. Rank-2 products require a distinct Contraction binding. Never infer
//! output emptiness from a reduction extent; `AlgebraicProductKernel` exposes
//! `reduction_axis` separately and verification compares every selector.
use crate::{BinaryOp, TrapKind};
use aether_frontend::TypeId;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum MathAxis {
    /// Vector descriptor dimension; also the scalar reduction's loop binding.
    Dimension,
    /// Independent reduction binding when both Rows and Columns bind outputs.
    Contraction,
    /// Logical row extent/coordinate, with role fixed by the kernel recipe.
    Rows,
    /// Logical column extent/coordinate, with role fixed by the kernel recipe.
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
