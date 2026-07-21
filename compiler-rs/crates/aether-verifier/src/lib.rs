//! Independent type, structural, SSA definition/use, and dominance passes for owned Aether IR.
//!
//! Type verification checks declaration and instruction-local type contracts.
//! Structural verification checks declarations, block termination, and local
//! branch/jump targets. SSA verification checks function-local immutable value
//! definitions, references, and same-block ordering. Dominance verification
//! checks cross-block availability. No pass performs phi, ownership, lifecycle,
//! or optimization verification.

mod cfg;
mod dominance_error;
mod dominance_verifier;
mod error;
mod ssa_error;
mod ssa_verifier;
mod structure_error;
mod structure_verifier;
mod verifier;

pub use dominance_error::{
    BlockDominanceError, DominanceRuleError, DominanceUseLocation, FunctionDominanceError,
    ModuleDominanceError,
};
pub use dominance_verifier::{verify_function_dominance, verify_module_dominance};
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
