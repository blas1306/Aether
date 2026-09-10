//! Flow MIR and SSA middle-end.

mod algebraic;
pub use algebraic::{AlgebraicProductKernel, ProductKind, ProductStep};
mod elementwise;
mod mir;
pub use elementwise::ElementwiseKernel;
mod mathematical;
pub use mathematical::{MathAxis, MathInput, MathStep, MathStride};
mod ssa;

pub use mir::{
    BasicBlock, BinaryOp, BlockId, ElementInitialization, FlowMir, MirDropFlag, MirFunction,
    MirInstruction, MirLocal, MirParameter, Operand, Place, PlaceBase, PlaceProjection, PushInit,
    Relocate, RelocationRange, Rvalue, SlotPlace, TakeState, Terminator, TrapKind, UnaryOp,
    VerifiedMir, lower_hir, verify_mir,
};
pub use ssa::{
    Phi, SsaBlock, SsaFunction, SsaInstruction, SsaIr, SsaMemoryLocal, SsaOp, SsaOperand,
    SsaParameter, SsaPlace, SsaPlaceBase, SsaPlaceProjection, SsaTerminator, ValueId, VerifiedSsa,
    build_ssa, verify_ssa,
};
