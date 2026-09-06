//! Flow MIR and SSA middle-end.

mod mir;
mod ssa;

pub use mir::{
    BasicBlock, BinaryOp, BlockId, ElementInitialization, FlowMir, MirDropFlag, MirFunction,
    MirInstruction, MirLocal, MirParameter, Operand, Place, PlaceBase, PlaceProjection, Relocate,
    RelocationRange, Rvalue, Terminator, TrapKind, UnaryOp, VerifiedMir, lower_hir, verify_mir,
};
pub use ssa::{
    Phi, SsaBlock, SsaFunction, SsaInstruction, SsaIr, SsaMemoryLocal, SsaOp, SsaOperand,
    SsaParameter, SsaPlace, SsaPlaceBase, SsaPlaceProjection, SsaTerminator, ValueId, VerifiedSsa,
    build_ssa, verify_ssa,
};
