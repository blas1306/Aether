//! Typed errors emitted for Python-compatible borrowed collection elements.

use std::error::Error;
use std::fmt;

use aether_ir::IRType;

use crate::{InstructionKind, SSAInstructionLocation};

/// Stable identifier of one initial-IR borrow invariant.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BorrowRule {
    /// IRV-037: borrowed collection gets require a non-empty scope.
    Irv037,
    /// IRV-038: a borrow must be defined in its declared scope block.
    Irv038,
    /// IRV-039: an owned collection get cannot carry borrow scope metadata.
    Irv039,
    /// IRV-040: a managed borrow needs same-block acquisition before a store.
    Irv040,
    /// IRV-041: a borrowed collection element cannot be returned directly.
    Irv041,
    /// IRV-042: a borrowed collection element cannot be a mutation receiver.
    Irv042,
}

impl fmt::Display for BorrowRule {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Irv037 => "IRV-037",
            Self::Irv038 => "IRV-038",
            Self::Irv039 => "IRV-039",
            Self::Irv040 => "IRV-040",
            Self::Irv041 => "IRV-041",
            Self::Irv042 => "IRV-042",
        })
    }
}

/// Leaf cause for a borrowed-element verification failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum BorrowRuleError {
    /// A borrowed array/list get omits its required iteration scope.
    MissingBorrowScope {
        /// Stable invariant identifier.
        rule: BorrowRule,
        /// Exact borrowed result identifier.
        borrowed_value: String,
        /// Borrow-producing instruction.
        instruction: SSAInstructionLocation,
        /// Actual block that defines the borrow.
        defining_scope: String,
    },
    /// A borrowed result is defined outside its declared scope block.
    BorrowScopeMismatch {
        /// Stable invariant identifier.
        rule: BorrowRule,
        /// Exact borrowed result identifier.
        borrowed_value: String,
        /// Borrow-producing instruction.
        instruction: SSAInstructionLocation,
        /// Scope retained by the instruction.
        declared_scope: String,
        /// Actual block that defines the borrow.
        defining_scope: String,
    },
    /// An owned array/list get incorrectly carries borrow scope metadata.
    OwnedGetDeclaresBorrowScope {
        /// Stable invariant identifier.
        rule: BorrowRule,
        /// Exact owned result identifier.
        value: String,
        /// Owned get instruction.
        instruction: SSAInstructionLocation,
        /// Unexpected retained scope.
        declared_scope: String,
    },
    /// A managed borrowed value reaches an owning store without acquisition.
    BorrowedOwningStoreWithoutAcquisition {
        /// Stable invariant identifier.
        rule: BorrowRule,
        /// Exact borrowed result identifier.
        borrowed_value: String,
        /// Static type whose lifecycle requires destruction.
        borrowed_type: IRType,
        /// Declared borrow scope.
        borrow_scope: String,
        /// Borrow-producing instruction.
        definition: SSAInstructionLocation,
        /// Store that consumes the value as owned.
        consumer: SSAInstructionLocation,
    },
    /// A borrowed value is returned directly.
    BorrowedValueReturned {
        /// Stable invariant identifier.
        rule: BorrowRule,
        /// Exact borrowed result identifier.
        borrowed_value: String,
        /// Declared borrow scope.
        borrow_scope: String,
        /// Borrow-producing instruction.
        definition: SSAInstructionLocation,
        /// Return instruction causing the escape.
        consumer: SSAInstructionLocation,
    },
    /// A mutation instruction uses a borrowed value as its receiver.
    MutationThroughBorrow {
        /// Stable invariant identifier.
        rule: BorrowRule,
        /// Exact borrowed result identifier.
        borrowed_value: String,
        /// Declared borrow scope.
        borrow_scope: String,
        /// Borrow-producing instruction.
        definition: SSAInstructionLocation,
        /// Mutation instruction using the borrow as receiver.
        consumer: SSAInstructionLocation,
        /// Exact prohibited mutation variant.
        consumer_kind: InstructionKind,
    },
}

impl fmt::Display for BorrowRuleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingBorrowScope {
                rule,
                borrowed_value,
                instruction,
                defining_scope,
            } => write!(
                formatter,
                "{rule} borrow_element '%{borrowed_value}' at {instruction} requires a non-empty iteration scope (definition block '{defining_scope}')"
            ),
            Self::BorrowScopeMismatch {
                rule,
                borrowed_value,
                instruction,
                declared_scope,
                defining_scope,
            } => write!(
                formatter,
                "{rule} borrow_element '%{borrowed_value}' at {instruction} declares scope '{declared_scope}' but is defined in block '{defining_scope}'"
            ),
            Self::OwnedGetDeclaresBorrowScope {
                rule,
                value,
                instruction,
                declared_scope,
            } => write!(
                formatter,
                "{rule} owned collection get '%{value}' at {instruction} cannot declare borrow scope '{declared_scope}'"
            ),
            Self::BorrowedOwningStoreWithoutAcquisition {
                rule,
                borrowed_value,
                borrowed_type,
                borrow_scope,
                definition,
                consumer,
            } => write!(
                formatter,
                "{rule} borrowed iteration value '%{borrowed_value}' of type {borrowed_type} from scope '{borrow_scope}' at {definition} cannot be stored as owned at {consumer} without an earlier same-block __aether_retain"
            ),
            Self::BorrowedValueReturned {
                rule,
                borrowed_value,
                borrow_scope,
                definition,
                consumer,
            } => write!(
                formatter,
                "{rule} borrowed iteration value '%{borrowed_value}' from scope '{borrow_scope}' at {definition} cannot escape through return at {consumer} without copying"
            ),
            Self::MutationThroughBorrow {
                rule,
                borrowed_value,
                borrow_scope,
                definition,
                consumer,
                consumer_kind,
            } => write!(
                formatter,
                "{rule} cannot mutate through borrowed iteration value '%{borrowed_value}' from scope '{borrow_scope}' at {definition}: {consumer_kind} at {consumer} uses it as receiver"
            ),
        }
    }
}

impl Error for BorrowRuleError {}
