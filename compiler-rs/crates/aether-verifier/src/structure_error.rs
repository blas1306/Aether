//! Typed errors emitted by the structural and basic-CFG verifier.

use std::error::Error;
use std::fmt;

use crate::InstructionKind;

/// Which branch edge contains an unresolved target.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BranchTarget {
    /// The edge selected by a true condition.
    True,
    /// The edge selected by a false condition.
    False,
}

impl fmt::Display for BranchTarget {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::True => formatter.write_str("true_target"),
            Self::False => formatter.write_str("false_target"),
        }
    }
}

/// The required terminating shape for every basic block.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TerminatorExpectation {
    /// Exactly one control-flow transfer in final position.
    OneFinalControlFlowTerminator,
}

impl fmt::Display for TerminatorExpectation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("exactly one final control-flow terminator")
    }
}

/// The observed ending of a block that has no terminator.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ActualBlockTermination {
    /// The block contains no instructions.
    EmptyBlock,
    /// The final instruction is not a control-flow terminator.
    NonTerminator {
        /// Exact final instruction variant.
        final_instruction_kind: InstructionKind,
    },
}

impl fmt::Display for ActualBlockTermination {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyBlock => formatter.write_str("an empty block"),
            Self::NonTerminator {
                final_instruction_kind,
            } => write!(formatter, "final non-terminator {final_instruction_kind}"),
        }
    }
}

/// Leaf causes for block termination and target-resolution failures.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ControlFlowRuleError {
    /// A block contains no recognized terminator.
    MissingTerminator {
        /// Required block ending.
        expected: TerminatorExpectation,
        /// Observed block ending.
        actual: ActualBlockTermination,
    },
    /// A non-terminator occurs after the sole terminator.
    InstructionAfterTerminator {
        /// Index of the earlier terminator.
        terminator_index: usize,
        /// Exact earlier terminator variant.
        terminator_kind: InstructionKind,
        /// Index of the first instruction after the terminator.
        offending_instruction_index: usize,
        /// Exact offending instruction variant.
        offending_instruction_kind: InstructionKind,
    },
    /// A block contains more than one terminator.
    MultipleTerminators {
        /// Index of the first terminator.
        first_index: usize,
        /// Exact first terminator variant.
        first_kind: InstructionKind,
        /// Index of the second terminator in source order.
        second_index: usize,
        /// Exact second terminator variant.
        second_kind: InstructionKind,
    },
    /// A jump target does not name a block in the same function.
    UnknownJumpTarget {
        /// Exact unresolved target name.
        target: String,
    },
    /// A branch target does not name a block in the same function.
    UnknownBranchTarget {
        /// Whether the true or false target failed.
        edge: BranchTarget,
        /// Exact unresolved target name.
        target: String,
    },
    /// An invoke aliases its mutually exclusive successor blocks.
    InvalidInvokeSuccessors {
        /// Retained normal target.
        normal_target: String,
        /// Retained exceptional target.
        exceptional_target: String,
    },
}

impl fmt::Display for ControlFlowRuleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingTerminator { expected, actual } => {
                write!(
                    formatter,
                    "missing terminator: expected {expected}, got {actual}"
                )
            }
            Self::InstructionAfterTerminator {
                terminator_index,
                terminator_kind,
                offending_instruction_index,
                offending_instruction_kind,
            } => write!(
                formatter,
                "instruction {offending_instruction_index} ({offending_instruction_kind}) follows terminator {terminator_index} ({terminator_kind})"
            ),
            Self::MultipleTerminators {
                first_index,
                first_kind,
                second_index,
                second_kind,
            } => write!(
                formatter,
                "multiple terminators: instruction {first_index} ({first_kind}) and instruction {second_index} ({second_kind})"
            ),
            Self::UnknownJumpTarget { target } => {
                write!(formatter, "unknown jump target '{target}'")
            }
            Self::UnknownBranchTarget { edge, target } => {
                write!(formatter, "unknown branch {edge} '{target}'")
            }
            Self::InvalidInvokeSuccessors {
                normal_target,
                exceptional_target,
            } => write!(
                formatter,
                "invoke normal target '{normal_target}' aliases exceptional target '{exceptional_target}'"
            ),
        }
    }
}

impl Error for ControlFlowRuleError {}

/// A block failure with stable function, block, and optional instruction context.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockStructureVerificationError {
    /// Containing function name.
    pub function_name: String,
    /// Containing block name.
    pub block_name: String,
    /// Relevant zero-based instruction index, when one exists.
    pub instruction_index: Option<usize>,
    /// Exact relevant instruction variant, when one exists.
    pub instruction_kind: Option<InstructionKind>,
    /// Typed structural or target-resolution cause.
    pub source: ControlFlowRuleError,
}

impl fmt::Display for BlockStructureVerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "structure verification failed in function '{}' block '{}'",
            self.function_name, self.block_name
        )?;
        if let (Some(index), Some(kind)) = (self.instruction_index, self.instruction_kind) {
            write!(formatter, " instruction {index} ({kind})")?;
        }
        write!(formatter, ": {}", self.source)
    }
}

impl Error for BlockStructureVerificationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(&self.source)
    }
}

/// A function declaration or nested block structural failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FunctionStructureVerificationError {
    /// Two parameters use the same exact name.
    DuplicateParameterName {
        /// Function name.
        function_name: String,
        /// Index of the duplicate parameter.
        parameter_index: usize,
        /// Exact duplicated name.
        parameter_name: String,
        /// Index of the earlier conflicting parameter.
        earlier_parameter_index: usize,
    },
    /// A function has no blocks.
    EmptyFunction {
        /// Function name.
        function_name: String,
    },
    /// No block uses the required entry-block name.
    MissingEntryBlock {
        /// Function name.
        function_name: String,
        /// Exact required entry-block name.
        required_entry_block: String,
    },
    /// Two blocks use the same exact name.
    DuplicateBlockName {
        /// Function name.
        function_name: String,
        /// Index of the duplicate block.
        block_index: usize,
        /// Exact duplicated name.
        block_name: String,
        /// Index of the earlier conflicting block.
        earlier_block_index: usize,
    },
    /// A nested block failed verification.
    Block {
        /// Function name.
        function_name: String,
        /// Zero-based block index.
        block_index: usize,
        /// Exact block name.
        block_name: String,
        /// Typed block-level source.
        source: Box<BlockStructureVerificationError>,
    },
}

impl fmt::Display for FunctionStructureVerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateParameterName {
                function_name,
                parameter_index,
                parameter_name,
                earlier_parameter_index,
            } => write!(
                formatter,
                "parameter {parameter_index} ('{parameter_name}') of function '{function_name}' duplicates parameter {earlier_parameter_index}"
            ),
            Self::EmptyFunction { function_name } => {
                write!(formatter, "function '{function_name}' has no blocks")
            }
            Self::MissingEntryBlock {
                function_name,
                required_entry_block,
            } => write!(
                formatter,
                "function '{function_name}' has no entry block '{required_entry_block}'"
            ),
            Self::DuplicateBlockName {
                function_name,
                block_index,
                block_name,
                earlier_block_index,
            } => write!(
                formatter,
                "block {block_index} ('{block_name}') of function '{function_name}' duplicates block {earlier_block_index}"
            ),
            Self::Block {
                function_name,
                block_index,
                block_name,
                source,
            } => write!(
                formatter,
                "block {block_index} ('{block_name}') of function '{function_name}' failed structure verification: {source}"
            ),
        }
    }
}

impl Error for FunctionStructureVerificationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Block { source, .. } => Some(source.as_ref()),
            Self::DuplicateParameterName { .. }
            | Self::EmptyFunction { .. }
            | Self::MissingEntryBlock { .. }
            | Self::DuplicateBlockName { .. } => None,
        }
    }
}

/// A module declaration or nested function structural failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ModuleStructureVerificationError {
    /// Two nominal structs use the same exact name.
    DuplicateStructName {
        /// Index of the duplicate struct.
        struct_index: usize,
        /// Exact duplicated name.
        struct_name: String,
        /// Index of the earlier conflicting struct.
        earlier_struct_index: usize,
    },
    /// A nominal struct has an empty name.
    EmptyStructName {
        /// Zero-based struct index.
        struct_index: usize,
    },
    /// Two fields in one nominal struct use the same exact name.
    DuplicateStructFieldName {
        /// Zero-based struct index.
        struct_index: usize,
        /// Exact struct name.
        struct_name: String,
        /// Index of the duplicate field.
        field_index: usize,
        /// Exact duplicated field name.
        field_name: String,
        /// Index of the earlier conflicting field.
        earlier_field_index: usize,
    },
    /// Two functions use the same exact name.
    DuplicateFunctionName {
        /// Index of the duplicate function.
        function_index: usize,
        /// Exact duplicated name.
        function_name: String,
        /// Index of the earlier conflicting function.
        earlier_function_index: usize,
    },
    /// A nested function failed verification.
    Function {
        /// Zero-based function index.
        function_index: usize,
        /// Exact function name.
        function_name: String,
        /// Typed function-level source.
        source: Box<FunctionStructureVerificationError>,
    },
}

impl fmt::Display for ModuleStructureVerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateStructName {
                struct_index,
                struct_name,
                earlier_struct_index,
            } => write!(
                formatter,
                "struct {struct_index} ('{struct_name}') duplicates struct {earlier_struct_index}"
            ),
            Self::EmptyStructName { struct_index } => {
                write!(formatter, "struct {struct_index} has an empty name")
            }
            Self::DuplicateStructFieldName {
                struct_index,
                struct_name,
                field_index,
                field_name,
                earlier_field_index,
            } => write!(
                formatter,
                "field {field_index} ('{field_name}') of struct {struct_index} ('{struct_name}') duplicates field {earlier_field_index}"
            ),
            Self::DuplicateFunctionName {
                function_index,
                function_name,
                earlier_function_index,
            } => write!(
                formatter,
                "function {function_index} ('{function_name}') duplicates function {earlier_function_index}"
            ),
            Self::Function {
                function_index,
                function_name,
                source,
            } => write!(
                formatter,
                "function {function_index} ('{function_name}') failed structure verification: {source}"
            ),
        }
    }
}

impl Error for ModuleStructureVerificationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Function { source, .. } => Some(source.as_ref()),
            Self::DuplicateStructName { .. }
            | Self::EmptyStructName { .. }
            | Self::DuplicateStructFieldName { .. }
            | Self::DuplicateFunctionName { .. } => None,
        }
    }
}
