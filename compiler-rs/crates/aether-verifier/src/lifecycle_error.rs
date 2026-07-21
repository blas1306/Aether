//! Typed errors emitted by the block-local storage lifecycle verifier.

#![allow(missing_docs)]

use std::error::Error;
use std::fmt;

use aether_ir::IRType;

use crate::InstructionKind;

/// A storage state known from the current block's ordered instruction stream.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LocalSlotState {
    /// No predecessor-state merge has established the block-entry state.
    Unknown,
    /// The slot is known not to contain a live value.
    Uninitialized,
    /// The slot is known to contain a live value.
    Initialized,
    /// A local move or relocation consumed the slot.
    Moved,
    /// A local destroy ended the slot's lifetime.
    Destroyed,
}

impl fmt::Display for LocalSlotState {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Unknown => "unknown",
            Self::Uninitialized => "uninitialized",
            Self::Initialized => "initialized",
            Self::Moved => "moved",
            Self::Destroyed => "destroyed",
        })
    }
}

/// Canonical operation names used by lifecycle diagnostics.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LifecycleOperation {
    Load,
    Store,
    InitDefault,
    CopyInit,
    MoveInit,
    Assign,
    Destroy,
    Relocate,
    ReturnTransfer,
}

impl fmt::Display for LifecycleOperation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Load => "load",
            Self::Store => "store",
            Self::InitDefault => "init_default",
            Self::CopyInit => "copy_init",
            Self::MoveInit => "move_init",
            Self::Assign => "assign",
            Self::Destroy => "destroy",
            Self::Relocate => "relocate",
            Self::ReturnTransfer => "return transfer",
        })
    }
}

/// The deterministic instruction field role occupied by a storage operand.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LifecycleStorageRole {
    Slot,
    Destination,
    Source,
    Value,
    TransferredStorage,
}

impl fmt::Display for LifecycleStorageRole {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Slot => "slot",
            Self::Destination => "destination",
            Self::Source => "source",
            Self::Value => "value",
            Self::TransferredStorage => "transferred_storage",
        })
    }
}

/// Stable source-order location of a storage operation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LifecycleInstructionLocation {
    pub block_index: usize,
    pub block_name: String,
    pub instruction_index: usize,
    pub instruction_kind: InstructionKind,
}

impl fmt::Display for LifecycleInstructionLocation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "block {} ('{}') instruction {} ({})",
            self.block_index, self.block_name, self.instruction_index, self.instruction_kind
        )
    }
}

/// Leaf causes for certain block-local lifecycle failures.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LifecycleRuleError {
    StorageTypeMismatch {
        storage_identifier: String,
        expected: IRType,
        actual: IRType,
        first_seen: LifecycleInstructionLocation,
        conflicting_use: LifecycleInstructionLocation,
        role: LifecycleStorageRole,
    },
    OperationTypeMismatch {
        operation: LifecycleOperation,
        source_type: IRType,
        destination_type: IRType,
        location: LifecycleInstructionLocation,
    },
    ReturnTransferTypeMismatch {
        storage_identifier: String,
        storage_type: IRType,
        returned_type: Option<IRType>,
        location: LifecycleInstructionLocation,
    },
    InvalidLifecycleType {
        operation: LifecycleOperation,
        role: LifecycleStorageRole,
        storage_identifier: String,
        storage_type: IRType,
        reason: String,
        location: LifecycleInstructionLocation,
    },
    InvalidRelocateCount {
        count: i64,
        location: LifecycleInstructionLocation,
    },
    ForbiddenSourceDestinationAlias {
        operation: LifecycleOperation,
        storage_identifier: String,
        storage_type: IRType,
        location: LifecycleInstructionLocation,
    },
    DoubleInitialization {
        operation: LifecycleOperation,
        storage_identifier: String,
        storage_type: IRType,
        previous_state: LocalSlotState,
        attempted_state: LocalSlotState,
        previous_transition: LifecycleInstructionLocation,
        current_transition: LifecycleInstructionLocation,
    },
    UseBeforeInitialization {
        operation: LifecycleOperation,
        role: LifecycleStorageRole,
        storage_identifier: String,
        storage_type: IRType,
        previous_state: LocalSlotState,
        attempted_state: LocalSlotState,
        current_use: LifecycleInstructionLocation,
    },
    UseAfterLocalInvalidation {
        operation: LifecycleOperation,
        role: LifecycleStorageRole,
        storage_identifier: String,
        storage_type: IRType,
        previous_state: LocalSlotState,
        attempted_state: LocalSlotState,
        previous_transition: LifecycleInstructionLocation,
        current_use: LifecycleInstructionLocation,
    },
    AssignmentToUninitialized {
        storage_identifier: String,
        storage_type: IRType,
        previous_state: LocalSlotState,
        attempted_state: LocalSlotState,
        current_transition: LifecycleInstructionLocation,
    },
    DestroyOfUninitialized {
        storage_identifier: String,
        storage_type: IRType,
        previous_state: LocalSlotState,
        attempted_state: LocalSlotState,
        current_transition: LifecycleInstructionLocation,
    },
    DoubleDestroy {
        storage_identifier: String,
        storage_type: IRType,
        previous_state: LocalSlotState,
        attempted_state: LocalSlotState,
        previous_transition: LifecycleInstructionLocation,
        current_transition: LifecycleInstructionLocation,
    },
}

impl fmt::Display for LifecycleRuleError {
    #[allow(clippy::too_many_lines)]
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::StorageTypeMismatch {
                storage_identifier,
                expected,
                actual,
                first_seen,
                conflicting_use,
                role,
            } => write!(
                formatter,
                "storage '%{storage_identifier}' has type {actual} as {role} at {conflicting_use}, but was first seen with type {expected} at {first_seen}"
            ),
            Self::OperationTypeMismatch {
                operation,
                source_type,
                destination_type,
                location,
            } => write!(
                formatter,
                "{operation} at {location} requires equal source and destination types, got {source_type} and {destination_type}"
            ),
            Self::ReturnTransferTypeMismatch {
                storage_identifier,
                storage_type,
                returned_type,
                location,
            } => match returned_type {
                Some(returned_type) => write!(
                    formatter,
                    "return transfer storage '%{storage_identifier}: {storage_type}' does not match returned value type {returned_type} at {location}"
                ),
                None => write!(
                    formatter,
                    "return transfer storage '%{storage_identifier}: {storage_type}' has no returned value at {location}"
                ),
            },
            Self::InvalidLifecycleType {
                operation,
                role,
                storage_identifier,
                storage_type,
                reason,
                location,
            } => write!(
                formatter,
                "{operation} {role} '%{storage_identifier}' has invalid lifecycle type {storage_type} at {location}: {reason}"
            ),
            Self::InvalidRelocateCount { count, location } => write!(
                formatter,
                "relocate count must be positive at {location}, got {count}"
            ),
            Self::ForbiddenSourceDestinationAlias {
                operation,
                storage_identifier,
                storage_type,
                location,
            } => write!(
                formatter,
                "{operation} source and destination alias storage '%{storage_identifier}: {storage_type}' at {location}"
            ),
            Self::DoubleInitialization {
                operation,
                storage_identifier,
                previous_state,
                attempted_state,
                previous_transition,
                current_transition,
                ..
            } => write!(
                formatter,
                "{operation} cannot transition storage '%{storage_identifier}' from {previous_state} to {attempted_state} at {current_transition}; it became {previous_state} at {previous_transition}"
            ),
            Self::UseBeforeInitialization {
                operation,
                role,
                storage_identifier,
                previous_state,
                attempted_state,
                current_use,
                ..
            } => write!(
                formatter,
                "{operation} {role} '%{storage_identifier}' is {previous_state} at {current_use} and cannot be used as {attempted_state}"
            ),
            Self::UseAfterLocalInvalidation {
                operation,
                role,
                storage_identifier,
                previous_state,
                attempted_state,
                previous_transition,
                current_use,
                ..
            } => write!(
                formatter,
                "{operation} {role} '%{storage_identifier}' is used at {current_use} after becoming {previous_state} at {previous_transition}; attempted state is {attempted_state}"
            ),
            Self::AssignmentToUninitialized {
                storage_identifier,
                previous_state,
                attempted_state,
                current_transition,
                ..
            } => write!(
                formatter,
                "assign destination '%{storage_identifier}' is {previous_state} at {current_transition}; assignment requires {attempted_state}"
            ),
            Self::DestroyOfUninitialized {
                storage_identifier,
                previous_state,
                attempted_state,
                current_transition,
                ..
            } => write!(
                formatter,
                "destroy target '%{storage_identifier}' is {previous_state} at {current_transition}; destroy requires {attempted_state}"
            ),
            Self::DoubleDestroy {
                storage_identifier,
                previous_state,
                attempted_state,
                previous_transition,
                current_transition,
                ..
            } => write!(
                formatter,
                "storage '%{storage_identifier}' is destroyed again at {current_transition}; it became {previous_state} at {previous_transition} and cannot transition to {attempted_state}"
            ),
        }
    }
}

impl Error for LifecycleRuleError {}

/// Block-scoped lifecycle failure with exact instruction and storage context.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockLifecycleError {
    pub function_name: String,
    pub block_index: usize,
    pub block_name: String,
    pub instruction_index: usize,
    pub instruction_kind: InstructionKind,
    pub storage_role: LifecycleStorageRole,
    pub storage_identifier: String,
    pub storage_type: IRType,
    pub source: LifecycleRuleError,
}

impl fmt::Display for BlockLifecycleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "local lifecycle verification failed in function '{}' block {} ('{}') instruction {} ({}) {} '%{}: {}': {}",
            self.function_name,
            self.block_index,
            self.block_name,
            self.instruction_index,
            self.instruction_kind,
            self.storage_role,
            self.storage_identifier,
            self.storage_type,
            self.source
        )
    }
}

impl Error for BlockLifecycleError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(&self.source)
    }
}

/// A function wrapper retaining the first failing block in source order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FunctionLifecycleError {
    pub function_name: String,
    pub block_index: usize,
    pub block_name: String,
    pub source: Box<BlockLifecycleError>,
}

impl fmt::Display for FunctionLifecycleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "block {} ('{}') of function '{}' failed local lifecycle verification: {}",
            self.block_index, self.block_name, self.function_name, self.source
        )
    }
}

impl Error for FunctionLifecycleError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(self.source.as_ref())
    }
}

/// A module wrapper retaining the first failing function in source order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ModuleLifecycleError {
    pub function_index: usize,
    pub function_name: String,
    pub source: Box<FunctionLifecycleError>,
}

impl fmt::Display for ModuleLifecycleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "function {} ('{}') failed local lifecycle verification: {}",
            self.function_index, self.function_name, self.source
        )
    }
}

impl Error for ModuleLifecycleError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(self.source.as_ref())
    }
}
