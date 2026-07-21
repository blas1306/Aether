//! Typed errors emitted by the cross-block SSA dominance verifier.

use std::error::Error;
use std::fmt;

use crate::{
    FunctionSSAError, FunctionStructureVerificationError, InstructionKind, SSADefinitionLocation,
    SSAInstructionLocation,
};

/// Stable location of one ordinary SSA operand use.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DominanceUseLocation {
    /// Instruction containing the use.
    pub instruction: SSAInstructionLocation,
    /// Zero-based SSA operand index in deterministic field order.
    pub operand_index: usize,
    /// Exact retained instruction field containing the operand.
    pub operand_field: String,
}

impl fmt::Display for DominanceUseLocation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "{} operand {} (field '{}')",
            self.instruction, self.operand_index, self.operand_field
        )
    }
}

/// Leaf causes for cross-block dominance failures.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DominanceRuleError {
    /// An instruction result is not available on every entry-to-use path.
    DefinitionDoesNotDominateUse {
        /// Exact SSA identifier without a textual `%` prefix.
        ssa_identifier: String,
        /// Instruction that defines the value.
        defining_location: SSADefinitionLocation,
        /// Instruction and operand position containing the use.
        use_location: DominanceUseLocation,
        /// Exact function entry-block convention used by the analysis.
        entry_block: String,
    },
}

impl fmt::Display for DominanceRuleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DefinitionDoesNotDominateUse {
                ssa_identifier,
                defining_location,
                use_location,
                entry_block,
            } => write!(
                formatter,
                "SSA value '%{ssa_identifier}' defined at {defining_location} does not dominate its use at {use_location} from entry block '{entry_block}'"
            ),
        }
    }
}

impl Error for DominanceRuleError {}

/// A block-scoped dominance failure with stable instruction context.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockDominanceError {
    /// Containing function name.
    pub function_name: String,
    /// Zero-based containing block index.
    pub block_index: usize,
    /// Exact containing block name.
    pub block_name: String,
    /// Zero-based relevant instruction index.
    pub instruction_index: usize,
    /// Exact relevant instruction variant.
    pub instruction_kind: InstructionKind,
    /// Exact offending SSA identifier without a textual `%` prefix.
    pub ssa_identifier: String,
    /// Typed dominance cause.
    pub source: DominanceRuleError,
}

impl fmt::Display for BlockDominanceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "dominance verification failed in function '{}' block {} ('{}') instruction {} ({}): {}",
            self.function_name,
            self.block_index,
            self.block_name,
            self.instruction_index,
            self.instruction_kind,
            self.source
        )
    }
}

impl Error for BlockDominanceError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(&self.source)
    }
}

/// A function prerequisite failure or nested dominance-rule failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FunctionDominanceError {
    /// Function-local structural validation could not establish an unambiguous CFG.
    StructurePrerequisite {
        /// Exact function name.
        function_name: String,
        /// Typed Step 3B prerequisite failure.
        source: Box<FunctionStructureVerificationError>,
    },
    /// SSA validation could not establish a unique, fully resolved definition namespace.
    SSAPrerequisite {
        /// Exact function name.
        function_name: String,
        /// Typed Step 3C.1 prerequisite failure.
        source: Box<FunctionSSAError>,
    },
    /// A nested block failed cross-block dominance verification.
    Block {
        /// Exact function name.
        function_name: String,
        /// Zero-based block index.
        block_index: usize,
        /// Exact block name.
        block_name: String,
        /// Typed block-level source.
        source: Box<BlockDominanceError>,
    },
}

impl fmt::Display for FunctionDominanceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::StructurePrerequisite {
                function_name,
                source,
            } => write!(
                formatter,
                "function '{function_name}' cannot be dominance-verified because structural verification failed: {source}"
            ),
            Self::SSAPrerequisite {
                function_name,
                source,
            } => write!(
                formatter,
                "function '{function_name}' cannot be dominance-verified because SSA verification failed: {source}"
            ),
            Self::Block {
                function_name,
                block_index,
                block_name,
                source,
            } => write!(
                formatter,
                "block {block_index} ('{block_name}') of function '{function_name}' failed dominance verification: {source}"
            ),
        }
    }
}

impl Error for FunctionDominanceError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::StructurePrerequisite { source, .. } => Some(source.as_ref()),
            Self::SSAPrerequisite { source, .. } => Some(source.as_ref()),
            Self::Block { source, .. } => Some(source.as_ref()),
        }
    }
}

/// A module wrapper retaining the first failing function in source order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ModuleDominanceError {
    /// Zero-based function index.
    pub function_index: usize,
    /// Exact function name.
    pub function_name: String,
    /// Typed function-level source.
    pub source: Box<FunctionDominanceError>,
}

impl fmt::Display for ModuleDominanceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "function {} ('{}') failed dominance verification: {}",
            self.function_index, self.function_name, self.source
        )
    }
}

impl Error for ModuleDominanceError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(self.source.as_ref())
    }
}
