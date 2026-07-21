//! Independent type, structural, SSA, dominance, and local lifecycle passes for owned Aether IR.
//!
//! Type verification checks declaration and instruction-local type contracts.
//! Structural verification checks declarations, block termination, and local
//! branch/jump targets. SSA verification checks function-local immutable value
//! definitions, references, and same-block ordering. Dominance verification
//! checks cross-block availability. Local lifecycle verification tracks certain
//! source-ordered slot transitions without predecessor-state propagation. No
//! pass performs phi, complete ownership/cleanup, or optimization verification.

mod cfg;
mod dominance_error;
mod dominance_verifier;
mod error;
mod lifecycle_error;
mod lifecycle_verifier;
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
pub use lifecycle_error::{
    BlockLifecycleError, FunctionLifecycleError, LifecycleInstructionLocation, LifecycleOperation,
    LifecycleRuleError, LifecycleStorageRole, LocalSlotState, ModuleLifecycleError,
};
pub use lifecycle_verifier::{verify_function_local_lifecycle, verify_module_local_lifecycle};
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
