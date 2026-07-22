//! Independent type, structural, SSA, dominance, lifecycle, and return passes for owned Aether IR.
//!
//! Type verification checks declaration and instruction-local type contracts.
//! Structural verification checks declarations, block termination, and local
//! branch/jump targets. SSA verification checks function-local immutable value
//! definitions, references, and same-block ordering. Dominance verification
//! checks cross-block availability. Lifecycle verification offers both focused
//! block-local checks and deterministic CFG state propagation followed by
//! reachable-exit ownership completion. Return verification proves that every
//! entry-rooted path in a non-void function returns a value. No pass performs
//! phi, cleanup insertion, lifecycle expansion, or optimization verification.

mod cfg;
mod dominance_error;
mod dominance_verifier;
mod error;
mod lifecycle_error;
mod lifecycle_verifier;
mod return_error;
mod return_verifier;
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
    BlockLifecycleError, FunctionLifecycleError, FunctionLifecycleVerificationError,
    LifecycleInstructionLocation, LifecycleOperation, LifecycleRuleError, LifecycleStorageRole,
    LocalSlotState, ModuleLifecycleError, ModuleLifecycleVerificationError,
    OwnershipCompletionReason, PossibleSlotStates,
};
pub use lifecycle_verifier::{
    verify_function_lifecycle, verify_function_local_lifecycle, verify_module_lifecycle,
    verify_module_local_lifecycle,
};
pub use return_error::{
    FunctionReturnVerificationError, ModuleReturnVerificationError, ReturnPathRuleError,
};
pub use return_verifier::{verify_function_returns, verify_module_returns};
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
