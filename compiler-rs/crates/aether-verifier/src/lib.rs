//! Independent type, structural, and SSA definition/use passes for owned Aether IR.
//!
//! Type verification checks declaration and instruction-local type contracts.
//! Structural verification checks declarations, block termination, and local
//! branch/jump targets. SSA verification checks function-local immutable value
//! definitions, references, and same-block ordering. No pass performs dominance,
//! phi, ownership, lifecycle, or optimization verification.

mod error;
mod ssa_error;
mod ssa_verifier;
mod structure_error;
mod structure_verifier;
mod verifier;

pub use error::{
    BlockTypeVerificationError, FunctionTypeVerificationError, InstructionKind,
    InstructionTypeVerificationError, ModuleTypeVerificationError, TypeExpectation, TypeRuleError,
};
pub use ssa_error::{
    BlockSSAError, FunctionSSAError, ModuleSSAError, SSADefinitionError, SSADefinitionLocation,
    SSAInstructionLocation, SSAUseLocation,
};
pub use ssa_verifier::{verify_function_ssa, verify_module_ssa};
pub use structure_error::{
    ActualBlockTermination, BlockStructureVerificationError, BranchTarget, ControlFlowRuleError,
    FunctionStructureVerificationError, ModuleStructureVerificationError, TerminatorExpectation,
};
pub use structure_verifier::{verify_function_structure, verify_module_structure};
pub use verifier::{verify_block_types, verify_function_types, verify_module_types};
