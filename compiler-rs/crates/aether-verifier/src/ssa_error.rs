//! Typed errors emitted by the SSA definition/use verifier.

use std::error::Error;
use std::fmt;

use aether_ir::IRType;

use crate::InstructionKind;

/// Stable source location of an instruction in retained function order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SSAInstructionLocation {
    /// Zero-based block index.
    pub block_index: usize,
    /// Exact block name.
    pub block_name: String,
    /// Zero-based instruction index within the block.
    pub instruction_index: usize,
    /// Exact instruction variant.
    pub instruction_kind: InstructionKind,
}

impl fmt::Display for SSAInstructionLocation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "block {} ('{}') instruction {} ({})",
            self.block_index, self.block_name, self.instruction_index, self.instruction_kind
        )
    }
}

/// Location of a function-local SSA definition.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SSADefinitionLocation {
    /// A function parameter, available before the first instruction.
    Parameter {
        /// Zero-based parameter index.
        parameter_index: usize,
    },
    /// An instruction result, available immediately after the instruction.
    Instruction(SSAInstructionLocation),
}

impl fmt::Display for SSADefinitionLocation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Parameter { parameter_index } => {
                write!(formatter, "parameter {parameter_index}")
            }
            Self::Instruction(location) => location.fmt(formatter),
        }
    }
}

/// Location of one SSA operand use.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SSAUseLocation {
    /// Instruction containing the use.
    pub instruction: SSAInstructionLocation,
    /// Zero-based SSA-operand index in deterministic field order.
    pub operand_index: usize,
}

impl fmt::Display for SSAUseLocation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "{} operand {}",
            self.instruction, self.operand_index
        )
    }
}

/// Leaf causes for function-local SSA definition and reference failures.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SSADefinitionError {
    /// A parameter or instruction result repeats an earlier definition.
    DuplicateDefinition {
        /// Exact SSA identifier without a textual `%` prefix.
        ssa_identifier: String,
        /// Earlier definition in function source order.
        defining_location: SSADefinitionLocation,
        /// Later conflicting definition.
        duplicate_definition_location: SSADefinitionLocation,
    },
    /// An operand names no parameter or instruction result in the function.
    UndefinedReference {
        /// Exact unresolved SSA identifier without a textual `%` prefix.
        ssa_identifier: String,
        /// Instruction and operand position containing the use.
        use_location: SSAUseLocation,
    },
    /// A same-block operand occurs before or within its defining instruction.
    UseBeforeDefinition {
        /// Exact SSA identifier without a textual `%` prefix.
        ssa_identifier: String,
        /// Later instruction that defines the value.
        defining_location: SSADefinitionLocation,
        /// Earlier instruction and operand position containing the use.
        use_location: SSAUseLocation,
    },
    /// A use has the right name but does not retain its definition's type.
    ReferenceTypeMismatch {
        /// Exact SSA identifier without a textual `%` prefix.
        ssa_identifier: String,
        /// Type attached to the definition.
        expected: IRType,
        /// Type attached to the use.
        actual: IRType,
        /// Parameter or instruction that defines the value.
        defining_location: SSADefinitionLocation,
        /// Instruction and operand position containing the mismatched use.
        use_location: SSAUseLocation,
    },
}

impl fmt::Display for SSADefinitionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateDefinition {
                ssa_identifier,
                defining_location,
                duplicate_definition_location,
            } => write!(
                formatter,
                "SSA value '%{ssa_identifier}' is defined twice: first at {defining_location}, then at {duplicate_definition_location}"
            ),
            Self::UndefinedReference {
                ssa_identifier,
                use_location,
            } => write!(
                formatter,
                "undefined SSA value '%{ssa_identifier}' used at {use_location}"
            ),
            Self::UseBeforeDefinition {
                ssa_identifier,
                defining_location,
                use_location,
            } => write!(
                formatter,
                "SSA value '%{ssa_identifier}' is used at {use_location} before its definition at {defining_location}"
            ),
            Self::ReferenceTypeMismatch {
                ssa_identifier,
                expected,
                actual,
                defining_location,
                use_location,
            } => write!(
                formatter,
                "SSA value '%{ssa_identifier}' used at {use_location} has type {actual}, but its definition at {defining_location} has type {expected}"
            ),
        }
    }
}

impl Error for SSADefinitionError {}

/// A block-scoped SSA failure with stable instruction context.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockSSAError {
    /// Containing function name.
    pub function_name: String,
    /// Containing block name.
    pub block_name: String,
    /// Zero-based relevant instruction index.
    pub instruction_index: usize,
    /// Exact relevant instruction variant.
    pub instruction_kind: InstructionKind,
    /// Exact offending SSA identifier without a textual `%` prefix.
    pub ssa_identifier: String,
    /// Typed SSA definition/reference cause.
    pub source: SSADefinitionError,
}

impl fmt::Display for BlockSSAError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "SSA verification failed in function '{}' block '{}' instruction {} ({}): {}",
            self.function_name,
            self.block_name,
            self.instruction_index,
            self.instruction_kind,
            self.source
        )
    }
}

impl Error for BlockSSAError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(&self.source)
    }
}

/// A function-level SSA failure or nested block failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FunctionSSAError {
    /// A parameter conflicts with an earlier function-local definition.
    Definition {
        /// Exact function name.
        function_name: String,
        /// Exact offending SSA identifier without a textual `%` prefix.
        ssa_identifier: String,
        /// Typed duplicate-definition cause.
        source: SSADefinitionError,
    },
    /// A nested block failed SSA verification.
    Block {
        /// Exact function name.
        function_name: String,
        /// Zero-based block index.
        block_index: usize,
        /// Exact block name.
        block_name: String,
        /// Typed block-level source.
        source: Box<BlockSSAError>,
    },
}

impl fmt::Display for FunctionSSAError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Definition {
                function_name,
                source,
                ..
            } => write!(
                formatter,
                "function '{function_name}' failed SSA definition verification: {source}"
            ),
            Self::Block {
                function_name,
                block_index,
                block_name,
                source,
            } => write!(
                formatter,
                "block {block_index} ('{block_name}') of function '{function_name}' failed SSA verification: {source}"
            ),
        }
    }
}

impl Error for FunctionSSAError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Definition { source, .. } => Some(source),
            Self::Block { source, .. } => Some(source.as_ref()),
        }
    }
}

/// A module wrapper retaining the first failing function in source order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ModuleSSAError {
    /// Zero-based function index.
    pub function_index: usize,
    /// Exact function name.
    pub function_name: String,
    /// Typed function-level source.
    pub source: Box<FunctionSSAError>,
}

impl fmt::Display for ModuleSSAError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "function {} ('{}') failed SSA verification: {}",
            self.function_index, self.function_name, self.source
        )
    }
}

impl Error for ModuleSSAError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(self.source.as_ref())
    }
}
