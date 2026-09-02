//! Flow MIR and SSA middle-end.

mod mir;
mod ssa;

pub use mir::{
    BasicBlock, BinaryOp, BlockId, FlowMir, MirFunction, MirInstruction, MirLocal, MirParameter,
    Operand, Place, PlaceBase, Rvalue, Terminator, TrapKind, UnaryOp, VerifiedMir, lower_hir,
    verify_mir,
};
pub use ssa::{
    Phi, SsaBlock, SsaFunction, SsaInstruction, SsaIr, SsaMemoryLocal, SsaOp, SsaOperand,
    SsaParameter, SsaPlace, SsaPlaceBase, SsaTerminator, ValueId, VerifiedSsa, build_ssa,
    verify_ssa,
};
