//! Independent type and structural verification passes for owned Aether IR.
//!
//! Type verification checks declaration and instruction-local type contracts.
//! Structural verification checks declarations, block termination, and local
//! branch/jump targets. Neither pass performs dominance, ownership, lifecycle,
//! or optimization verification.

mod error;
mod structure_error;
mod structure_verifier;
mod verifier;

pub use error::{
    BlockTypeVerificationError, FunctionTypeVerificationError, InstructionKind,
    InstructionTypeVerificationError, ModuleTypeVerificationError, TypeExpectation, TypeRuleError,
};
pub use structure_error::{
    ActualBlockTermination, BlockStructureVerificationError, BranchTarget, ControlFlowRuleError,
    FunctionStructureVerificationError, ModuleStructureVerificationError, TerminatorExpectation,
};
pub use structure_verifier::{verify_function_structure, verify_module_structure};
pub use verifier::{verify_block_types, verify_function_types, verify_module_types};
