//! Flow MIR and SSA middle-end.

mod mir;
mod ssa;

pub use mir::{
    BasicBlock, BinaryOp, BlockId, FlowMir, MirFunction, MirInstruction, MirLocal, MirParameter,
    Operand, Rvalue, Terminator, TrapKind, UnaryOp, VerifiedMir, lower_hir, verify_mir,
};
pub use ssa::{
    Phi, SsaBlock, SsaFunction, SsaInstruction, SsaIr, SsaOp, SsaOperand, SsaParameter,
    SsaTerminator, ValueId, VerifiedSsa, build_ssa, verify_ssa,
};
