//! Type-consistency verification for owned Aether IR.
//!
//! This crate's first verifier pass checks declaration types and the local
//! type contract of each instruction. It deliberately does not construct or
//! validate a control-flow graph and does not perform dominance, ownership,
//! lifecycle, or optimization verification.

mod error;
mod verifier;

pub use error::{
    BlockTypeVerificationError, FunctionTypeVerificationError, InstructionKind,
    InstructionTypeVerificationError, ModuleTypeVerificationError, TypeExpectation, TypeRuleError,
};
pub use verifier::{verify_block_types, verify_function_types, verify_module_types};
