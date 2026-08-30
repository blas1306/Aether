//! Transport-independent compiler-core boundary.
//!
//! The subprocess companion and language bindings are adapters over this
//! module. Wire decoding, framing, Python objects, and Python exceptions do not
//! belong here. A [`CompilationSession`] owns typed Rust representations so
//! future compiler stages can be added without a serialization boundary
//! between every stage.

use std::error::Error;
use std::fmt;

use aether_ir::wire::{IRModuleDTO, SSAModuleV2DTO};
use aether_ir::{OwnedSsaModule, lower_normalized_ir_to_ssa_v1, normalize_lifecycle_v1};
use serde::Serialize;

use crate::ssa_wire_verifier::SSAWireVerificationError;
use crate::{SsaRefinementVerificationError, verify_owned_ssa, verify_owned_ssa_refinement};

/// Version of the transport-independent CompilerCore API exposed to adapters.
pub const COMPILER_CORE_API_VERSION: u32 = 1;

/// Persistent companion framing and response protocol version.
pub const COMPILER_CORE_PROTOCOL_VERSION: u32 = 1;

/// Initial IR schemas accepted by the current core adapters.
pub const COMPILER_CORE_INPUT_SCHEMA_VERSIONS: &[u32] = &[1];

/// SSA schemas materialized by the current core adapters.
pub const COMPILER_CORE_OUTPUT_SCHEMA_VERSIONS: &[u32] = &[2];

/// Stable top-level classification crossing binding and protocol adapters.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CompilerErrorKind {
    /// The accepted program cannot be lowered or verified.
    Compiler,
    /// A core invariant failed unexpectedly.
    Internal,
}

/// Stable compiler phase associated with a core failure.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CompilerPhase {
    /// Initial IR lifecycle normalization.
    LifecycleNormalization,
    /// Construction of owned SSA.
    SsaLowering,
    /// Verification of the owned SSA result.
    SsaVerification,
    /// Invalid use of the stateful core API.
    CoreState,
}

/// Machine-readable error emitted by the transport-independent core.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CompilerError {
    /// Broad failure class.
    pub kind: CompilerErrorKind,
    /// Stable diagnostic category.
    pub category: &'static str,
    /// Compiler phase which failed.
    pub phase: CompilerPhase,
    /// Stable machine-readable identifier.
    pub code: &'static str,
    /// Deterministic human-readable detail.
    pub message: String,
    /// Function containing the failure, when known.
    pub function: Option<String>,
    /// Block containing the failure, when known.
    pub block: Option<String>,
    /// Source location when the underlying stage can identify one.
    pub source_location: Option<SourceLocation>,
}

/// Transport-neutral source position for binding diagnostics.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct SourceLocation {
    /// Optional source path.
    pub path: Option<String>,
    /// One-based line number.
    pub line: u64,
    /// One-based column number.
    pub column: u64,
}

impl CompilerError {
    fn lowering(message: String) -> Self {
        let phase = if message.starts_with("lifecycle normalization") {
            CompilerPhase::LifecycleNormalization
        } else {
            CompilerPhase::SsaLowering
        };
        Self {
            kind: CompilerErrorKind::Compiler,
            category: "ssa_construction",
            phase,
            code: "CORE-SSA-001",
            message,
            function: None,
            block: None,
            source_location: None,
        }
    }

    fn verification(error: SSAWireVerificationError) -> Self {
        Self {
            kind: CompilerErrorKind::Internal,
            category: "owned_ssa_verification",
            phase: CompilerPhase::SsaVerification,
            code: "CORE-SSA-VERIFY-001",
            message: error.to_string(),
            function: Some(error.function_name),
            block: error.block_name,
            source_location: None,
        }
    }

    fn refinement_verification(error: SsaRefinementVerificationError) -> Self {
        Self {
            kind: CompilerErrorKind::Internal,
            category: "ssa_refinement_verification",
            phase: CompilerPhase::SsaVerification,
            code: error.code,
            message: error.to_string(),
            function: error.function,
            block: error.block,
            source_location: error.source_location.map(|location| SourceLocation {
                path: location.path,
                line: u64::try_from(location.line).unwrap_or_default(),
                column: u64::try_from(location.column).unwrap_or_default(),
            }),
        }
    }

    fn missing_ssa() -> Self {
        Self {
            kind: CompilerErrorKind::Internal,
            category: "core_state",
            phase: CompilerPhase::CoreState,
            code: "CORE-STATE-001",
            message: "SSA has not been lowered for this compilation session".into(),
            function: None,
            block: None,
            source_location: None,
        }
    }
}

impl fmt::Display for CompilerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Protocol v1 historically returned the stage message verbatim. Keep
        // that presentation stable; adapters obtain the code from fields.
        formatter.write_str(&self.message)
    }
}

impl Error for CompilerError {}

/// Stateless factory for Rust-owned compilation sessions.
#[derive(Clone, Copy, Debug, Default)]
pub struct CompilerCore;

impl CompilerCore {
    /// Accept one already decoded schema-v1 Initial IR value.
    pub fn accept_initial_ir(&self, initial_ir: IRModuleDTO) -> CompilationSession {
        CompilationSession {
            initial_ir,
            ssa: None,
        }
    }

    /// Convenience entry point for adapters which need the current one-shot operation.
    pub fn lower_verified_ssa(
        &self,
        initial_ir: IRModuleDTO,
    ) -> Result<OwnedSsaModule, CompilerError> {
        let mut session = self.accept_initial_ir(initial_ir);
        session.lower_ssa()?;
        session.into_ssa()
    }
}

/// Compilation-local, Rust-owned representations retained between core stages.
#[derive(Clone, Debug)]
pub struct CompilationSession {
    initial_ir: IRModuleDTO,
    ssa: Option<OwnedSsaModule>,
}

impl CompilationSession {
    /// Lower and verify SSA once. Repeated calls are intentionally idempotent.
    pub fn lower_ssa(&mut self) -> Result<(), CompilerError> {
        if self.ssa.is_some() {
            return Ok(());
        }
        let normalized = normalize_lifecycle_v1(&self.initial_ir, 1)
            .map_err(|error| CompilerError::lowering(error.to_string()))?;
        let ssa = lower_normalized_ir_to_ssa_v1(&normalized)
            .map_err(|error| CompilerError::lowering(error.to_string()))?;
        verify_owned_ssa(&ssa).map_err(CompilerError::verification)?;
        verify_owned_ssa_refinement(&normalized, &ssa)
            .map_err(CompilerError::refinement_verification)?;
        self.ssa = Some(ssa);
        Ok(())
    }

    /// Borrow the accepted Initial IR without exposing mutation.
    pub fn initial_ir(&self) -> &IRModuleDTO {
        &self.initial_ir
    }

    /// Borrow verified owned SSA, if SSA lowering has completed.
    pub fn ssa(&self) -> Option<&OwnedSsaModule> {
        self.ssa.as_ref()
    }

    /// Materialize schema-v2 only at an adapter/debug boundary.
    pub fn export_ssa_schema_v2(&self) -> Result<SSAModuleV2DTO, CompilerError> {
        self.ssa
            .as_ref()
            .map(OwnedSsaModule::to_schema_v2)
            .ok_or_else(CompilerError::missing_ssa)
    }

    /// Consume the session and return its verified owned SSA.
    pub fn into_ssa(self) -> Result<OwnedSsaModule, CompilerError> {
        self.ssa.ok_or_else(CompilerError::missing_ssa)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use aether_ir::wire::{IRFunctionDTO, IRTypeDTO};

    fn empty_module() -> IRModuleDTO {
        IRModuleDTO {
            schema_version: 1,
            functions: vec![IRFunctionDTO {
                name: "empty".into(),
                parameters: Vec::new(),
                return_type: IRTypeDTO::Void {},
                blocks: Vec::new(),
                may_throw: false,
            }],
            structs: Vec::new(),
        }
    }

    #[test]
    fn state_error_is_structured_before_lowering() {
        let session = CompilerCore.accept_initial_ir(empty_module());
        let error = session.export_ssa_schema_v2().unwrap_err();
        assert_eq!(error.kind, CompilerErrorKind::Internal);
        assert_eq!(error.phase, CompilerPhase::CoreState);
        assert_eq!(error.code, "CORE-STATE-001");
    }

    #[test]
    fn lowering_failure_retains_machine_readable_fields() {
        let error = CompilerCore.lower_verified_ssa(empty_module()).unwrap_err();
        assert_eq!(error.kind, CompilerErrorKind::Compiler);
        assert_eq!(error.code, "CORE-SSA-001");
        assert!(error.message.contains("function has no entry block"));
    }

    #[test]
    fn core_and_owned_session_are_send_and_sync() {
        fn assert_send_sync<T: Send + Sync>() {}

        assert_send_sync::<CompilerCore>();
        assert_send_sync::<CompilationSession>();
    }
}
