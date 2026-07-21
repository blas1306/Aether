//! Typed errors emitted by the IR type verifier.

use std::error::Error;
use std::fmt;

use aether_ir::IRType;

/// The expected family of types for an instruction operand or result.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TypeExpectation {
    /// One exact IR type.
    Exact(IRType),
    /// Any valid IR type.
    Valid,
    /// Any valid type except void.
    NonVoid,
    /// A numeric scalar: int, float, double, or complex.
    Numeric,
    /// A real numeric scalar: int, float, or double.
    Real,
    /// A printable type accepted by the Python verifier.
    Printable,
    /// A type supporting the Python verifier's equality contract.
    EqualityCapable,
    /// A dynamically sized array.
    Array,
    /// A dynamically sized list.
    List,
    /// An array or list.
    Sequence,
    /// A vector.
    Vector,
    /// A matrix.
    Matrix,
    /// A nominal struct.
    Struct,
    /// A method-result pair.
    MethodResult,
    /// A function signature.
    Function,
    /// An enum type.
    Enum,
    /// One of several exact IR types.
    OneOf(Vec<IRType>),
}

impl fmt::Display for TypeExpectation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Exact(type_) => write!(formatter, "{type_}"),
            Self::Valid => formatter.write_str("a valid IR type"),
            Self::NonVoid => formatter.write_str("a valid non-void IR type"),
            Self::Numeric => formatter.write_str("a numeric type"),
            Self::Real => formatter.write_str("a real numeric type"),
            Self::Printable => formatter.write_str("a printable type"),
            Self::EqualityCapable => formatter.write_str("an equality-capable type"),
            Self::Array => formatter.write_str("an array type"),
            Self::List => formatter.write_str("a list type"),
            Self::Sequence => formatter.write_str("an array or list type"),
            Self::Vector => formatter.write_str("a vector type"),
            Self::Matrix => formatter.write_str("a matrix type"),
            Self::Struct => formatter.write_str("a declared struct type"),
            Self::MethodResult => formatter.write_str("a method-result type"),
            Self::Function => formatter.write_str("a function type"),
            Self::Enum => formatter.write_str("an enum type"),
            Self::OneOf(types) => {
                for (index, type_) in types.iter().enumerate() {
                    if index > 0 {
                        formatter.write_str(" or ")?;
                    }
                    write!(formatter, "{type_}")?;
                }
                Ok(())
            }
        }
    }
}

/// The leaf cause of a type-verification failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TypeRuleError {
    /// An operand, result, parameter, or field has the wrong exact type.
    TypeMismatch {
        /// The offending instruction operand or declaration field.
        field: String,
        /// The required type.
        expected: IRType,
        /// The encountered type.
        actual: IRType,
    },
    /// A type does not belong to the required family.
    TypeConstraint {
        /// The offending instruction operand or declaration field.
        field: String,
        /// The required family.
        expected: TypeExpectation,
        /// The encountered type.
        actual: IRType,
    },
    /// A call or construction has the wrong number of values.
    CountMismatch {
        /// The offending argument or element collection.
        field: String,
        /// The required count.
        expected: usize,
        /// The encountered count.
        actual: usize,
    },
    /// An instruction that must produce a result has none.
    MissingResult {
        /// The result field.
        field: String,
        /// The required result type.
        expected: IRType,
    },
    /// An instruction that must not produce a result has one.
    UnexpectedResult {
        /// The result field.
        field: String,
        /// The encountered result type.
        actual: IRType,
    },
    /// A direct call or function reference names no function in the module.
    UnknownFunction {
        /// The unresolved function name.
        function: String,
    },
    /// A nominal struct type names no declaration in the module.
    UnknownStruct {
        /// The offending operand or field.
        field: String,
        /// The unresolved struct name.
        struct_name: String,
    },
    /// A struct field index is outside the declared layout.
    InvalidFieldIndex {
        /// The index field name.
        field: String,
        /// The encountered signed index.
        actual: i64,
        /// Number of fields in the struct.
        field_count: usize,
    },
    /// An operator spelling is not supported by the Python verifier.
    UnsupportedOperator {
        /// Operator-bearing instruction field.
        field: String,
        /// Unsupported spelling.
        operator: String,
    },
    /// String metadata is incompatible with an instruction's type contract.
    MetadataMismatch {
        /// The offending metadata field.
        field: String,
        /// Required metadata spelling.
        expected: String,
        /// Encountered metadata spelling.
        actual: String,
    },
    /// An enum constant does not match its result enum declaration.
    InvalidEnumConstant {
        /// The offending enum-constant component.
        field: String,
        /// Required value rendered without losing its kind.
        expected: String,
        /// Encountered value rendered without losing its kind.
        actual: String,
    },
    /// A by-value nominal struct cycle would have infinite size.
    RecursiveStructLayout {
        /// Ordered cycle, including the repeated closing name.
        cycle: Vec<String>,
    },
}

impl fmt::Display for TypeRuleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TypeMismatch {
                field,
                expected,
                actual,
            } => write!(
                formatter,
                "type mismatch for '{field}': expected {expected}, got {actual}"
            ),
            Self::TypeConstraint {
                field,
                expected,
                actual,
            } => write!(
                formatter,
                "invalid type for '{field}': expected {expected}, got {actual}"
            ),
            Self::CountMismatch {
                field,
                expected,
                actual,
            } => write!(
                formatter,
                "count mismatch for '{field}': expected {expected}, got {actual}"
            ),
            Self::MissingResult { field, expected } => {
                write!(formatter, "missing '{field}' of type {expected}")
            }
            Self::UnexpectedResult { field, actual } => {
                write!(formatter, "unexpected '{field}' of type {actual}")
            }
            Self::UnknownFunction { function } => {
                write!(formatter, "unknown function '{function}'")
            }
            Self::UnknownStruct { field, struct_name } => {
                write!(formatter, "'{field}' names unknown struct '{struct_name}'")
            }
            Self::InvalidFieldIndex {
                field,
                actual,
                field_count,
            } => write!(
                formatter,
                "invalid '{field}' {actual} for struct with {field_count} fields"
            ),
            Self::UnsupportedOperator { field, operator } => {
                write!(formatter, "unsupported '{field}' value '{operator}'")
            }
            Self::MetadataMismatch {
                field,
                expected,
                actual,
            } => write!(
                formatter,
                "metadata mismatch for '{field}': expected {expected}, got {actual}"
            ),
            Self::InvalidEnumConstant {
                field,
                expected,
                actual,
            } => write!(
                formatter,
                "invalid enum constant '{field}': expected {expected}, got {actual}"
            ),
            Self::RecursiveStructLayout { cycle } => write!(
                formatter,
                "recursive by-value struct layout has infinite size: {}",
                cycle.join(" -> ")
            ),
        }
    }
}

impl Error for TypeRuleError {}

/// The exact owned-IR instruction variant being verified.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum InstructionKind {
    IRConst,
    IRLoad,
    IRStore,
    IRInitDefault,
    IRCopyInit,
    IRMoveInit,
    IRAssign,
    IRDestroy,
    IRRelocate,
    IRBinaryOp,
    IRUnaryOp,
    IRCompareOp,
    IRCast,
    IRCall,
    IRFunctionRef,
    IRCallIndirect,
    IRPrint,
    IRStructNew,
    IRStructGet,
    IRStructSet,
    IRMethodResultNew,
    IRMethodResultReceiver,
    IRMethodResultValue,
    IRArrayNew,
    IRListNew,
    IRArrayCopy,
    IRListCopy,
    IRListContains,
    IRListIndexOf,
    IRListClear,
    IRListPush,
    IRListInsert,
    IRListRemoveAt,
    IRListPop,
    IRListReverse,
    IRSequenceSort,
    IRVectorNew,
    IRMatrixNew,
    IRVectorAdd,
    IRVectorSub,
    IRVectorScale,
    IRVectorDot,
    IROuterProduct,
    IRMatrixAdd,
    IRMatrixSub,
    IRMatrixScale,
    IRMatrixMatMul,
    IRMatrixVectorMul,
    IRVectorMatrixMul,
    IRArrayGet,
    IRArraySlice,
    IRListSlice,
    IRListGet,
    IRVectorGet,
    IRMatrixGet,
    IRVectorLength,
    IRMatrixRows,
    IRMatrixColumns,
    IRArraySet,
    IRListSet,
    IRVectorSet,
    IRMatrixSet,
    IRArrayLength,
    IRListLength,
    IRListIsEmpty,
    IRBranch,
    IRJump,
    IRReturn,
}

impl fmt::Display for InstructionKind {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

/// An instruction-local failure, retaining the typed rule cause.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InstructionTypeVerificationError {
    /// The exact instruction variant.
    pub instruction_kind: InstructionKind,
    /// Typed leaf cause.
    pub source: TypeRuleError,
}

impl fmt::Display for InstructionTypeVerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "{} failed type verification: {}",
            self.instruction_kind, self.source
        )
    }
}

impl Error for InstructionTypeVerificationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(&self.source)
    }
}

/// A block failure with stable instruction context.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockTypeVerificationError {
    /// Containing function name.
    pub function_name: String,
    /// Containing block name.
    pub block_name: String,
    /// Zero-based instruction index.
    pub instruction_index: usize,
    /// Exact instruction variant.
    pub instruction_kind: InstructionKind,
    /// Typed instruction-level source.
    pub source: InstructionTypeVerificationError,
}

impl fmt::Display for BlockTypeVerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "type verification failed in function '{}' block '{}' instruction {} ({}): {}",
            self.function_name,
            self.block_name,
            self.instruction_index,
            self.instruction_kind,
            self.source
        )
    }
}

impl Error for BlockTypeVerificationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(&self.source)
    }
}

/// A function declaration or nested block type failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FunctionTypeVerificationError {
    /// A parameter type is invalid.
    Parameter {
        /// Function name.
        function_name: String,
        /// Zero-based parameter index.
        parameter_index: usize,
        /// Exact parameter name.
        parameter_name: String,
        /// Typed leaf cause.
        source: TypeRuleError,
    },
    /// The declared function return type is invalid.
    ReturnType {
        /// Function name.
        function_name: String,
        /// Typed leaf cause.
        source: TypeRuleError,
    },
    /// A nested block failed.
    Block {
        /// Function name.
        function_name: String,
        /// Zero-based block index.
        block_index: usize,
        /// Exact block name.
        block_name: String,
        /// Typed block-level source.
        source: BlockTypeVerificationError,
    },
}

impl fmt::Display for FunctionTypeVerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Parameter {
                function_name,
                parameter_index,
                parameter_name,
                source,
            } => write!(
                formatter,
                "parameter {parameter_index} ('{parameter_name}') of function '{function_name}' failed type verification: {source}"
            ),
            Self::ReturnType {
                function_name,
                source,
            } => write!(
                formatter,
                "return type of function '{function_name}' failed type verification: {source}"
            ),
            Self::Block {
                function_name,
                block_index,
                block_name,
                source,
            } => write!(
                formatter,
                "block {block_index} ('{block_name}') of function '{function_name}' failed type verification: {source}"
            ),
        }
    }
}

impl Error for FunctionTypeVerificationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Parameter { source, .. } | Self::ReturnType { source, .. } => Some(source),
            Self::Block { source, .. } => Some(source),
        }
    }
}

/// A module-level declaration or nested function type failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ModuleTypeVerificationError {
    /// A struct field type is invalid.
    StructField {
        /// Zero-based struct index.
        struct_index: usize,
        /// Exact struct name.
        struct_name: String,
        /// Zero-based field index.
        field_index: usize,
        /// Exact field name.
        field_name: String,
        /// Typed leaf cause.
        source: TypeRuleError,
    },
    /// The direct by-value struct graph is recursive.
    StructLayout {
        /// Typed leaf cause containing the complete cycle.
        source: TypeRuleError,
    },
    /// A nested function failed.
    Function {
        /// Zero-based function index.
        function_index: usize,
        /// Exact function name.
        function_name: String,
        /// Typed function-level source.
        source: FunctionTypeVerificationError,
    },
}

impl fmt::Display for ModuleTypeVerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::StructField {
                struct_index,
                struct_name,
                field_index,
                field_name,
                source,
            } => write!(
                formatter,
                "field {field_index} ('{field_name}') of struct {struct_index} ('{struct_name}') failed type verification: {source}"
            ),
            Self::StructLayout { source } => {
                write!(
                    formatter,
                    "struct layout failed type verification: {source}"
                )
            }
            Self::Function {
                function_index,
                function_name,
                source,
            } => write!(
                formatter,
                "function {function_index} ('{function_name}') failed type verification: {source}"
            ),
        }
    }
}

impl Error for ModuleTypeVerificationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::StructField { source, .. } | Self::StructLayout { source } => Some(source),
            Self::Function { source, .. } => Some(source),
        }
    }
}
