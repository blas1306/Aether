//! Typed errors emitted by non-void all-path return verification.

use std::error::Error;
use std::fmt;

use aether_ir::IRType;

use crate::FunctionStructureVerificationError;

/// Leaf reasons why an entry-reachable path does not prove a valued return.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ReturnPathRuleError {
    /// A reachable return terminator carries no value.
    ValuelessReturn {
        /// Zero-based index of the return block.
        block_index: usize,
        /// Exact return-block name.
        block_name: String,
        /// Zero-based index of the final return instruction.
        instruction_index: usize,
    },
}

impl fmt::Display for ReturnPathRuleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ValuelessReturn {
                block_index,
                block_name,
                instruction_index,
            } => write!(
                formatter,
                "entry-reachable block {block_index} ('{block_name}') ends at instruction {instruction_index} with a valueless return"
            ),
        }
    }
}

impl Error for ReturnPathRuleError {}

/// A function prerequisite failure or non-void all-path return failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FunctionReturnVerificationError {
    /// Function-local structural validation could not establish a safe CFG.
    StructurePrerequisite {
        /// Exact function name.
        function_name: String,
        /// Typed Step 3B prerequisite failure.
        source: Box<FunctionStructureVerificationError>,
    },
    /// At least one path from `entry` did not prove a valued return.
    NonVoidPathWithoutReturn {
        /// Exact function name.
        function_name: String,
        /// Declared non-void return type.
        return_type: IRType,
        /// Exact entry-block convention used by the analysis.
        entry_block: String,
        /// First deterministic failure found by true-before-false traversal.
        source: ReturnPathRuleError,
    },
}

impl fmt::Display for FunctionReturnVerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::StructurePrerequisite {
                function_name,
                source,
            } => write!(
                formatter,
                "function '{function_name}' cannot be return-verified because structural verification failed: {source}"
            ),
            Self::NonVoidPathWithoutReturn {
                function_name,
                return_type,
                entry_block,
                source,
            } => write!(
                formatter,
                "non-void function '{function_name}' returning {return_type} may exit without returning a value from entry block '{entry_block}': {source}"
            ),
        }
    }
}

impl Error for FunctionReturnVerificationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::StructurePrerequisite { source, .. } => Some(source.as_ref()),
            Self::NonVoidPathWithoutReturn { source, .. } => Some(source),
        }
    }
}

/// Module wrapper retaining the first failing function in source order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ModuleReturnVerificationError {
    /// Zero-based function index.
    pub function_index: usize,
    /// Exact function name.
    pub function_name: String,
    /// Typed function-level source.
    pub source: Box<FunctionReturnVerificationError>,
}

impl fmt::Display for ModuleReturnVerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "function {} ('{}') failed all-path return verification: {}",
            self.function_index, self.function_name, self.source
        )
    }
}

impl Error for ModuleReturnVerificationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(self.source.as_ref())
    }
}
