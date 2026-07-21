//! Conversion from schema-v1 wire DTOs into the owned Rust IR.

use std::error::Error;
use std::fmt;

use crate::wire::{
    IRBasicBlockDTO, IRConstantDTO, IREnumConstantDTO, IRInstructionDTO, IRParameterDTO,
    IRSourceLocationDTO, IRStorageDTO, IRTypeDTO, IRValueDTO, NullableDTO,
};
use crate::{
    ArrayType, BoolType, ClassRefType, ComplexType, DoubleType, EnumType, FloatType, FunctionType,
    IRBasicBlock, IRConstant, IREnumConstant, IRInstruction, IRParameter, IRSourceLocation,
    IRStorage, IRType, IRValue, IntType, InterfaceType, ListType, MatrixType, MethodResultType,
    NullableType, StringType, StructType, VectorType, VoidType,
};

/// A structural failure while importing a wire DTO into the owned Rust IR.
///
/// Semantic validity is intentionally outside this error type and remains the
/// responsibility of the IR verifier.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum IRImportError {
    /// An instruction nested in a basic block could not be imported.
    BasicBlockInstruction {
        /// Exact, unnormalized block name from the wire DTO.
        block: String,
        /// Zero-based position in the block's instruction vector.
        index: usize,
        /// Contextual instruction-import failure.
        source: Box<Self>,
    },
    /// A nested instruction field could not be represented by the owned IR.
    InstructionField {
        /// Stable schema-v1 instruction kind.
        instruction: &'static str,
        /// Exact field containing the incompatible nested DTO.
        field: &'static str,
        /// Focused nested conversion failure.
        source: Box<Self>,
    },
    /// A method-result receiver used a wire type that the owned IR cannot store.
    MethodResultReceiverNotStruct {
        /// Stable wire tag of the incompatible receiver type.
        actual: &'static str,
    },
    /// A named value's `type` field could not be represented by the owned IR.
    ValueType {
        /// Stable tag of the wire value variant being imported.
        kind: &'static str,
        /// Structural type-import failure.
        source: Box<Self>,
    },
    /// A storage entity's `type` field could not be represented by the owned IR.
    StorageType {
        /// Structural type-import failure.
        source: Box<Self>,
    },
    /// A parameter entity's `type` field could not be represented by the owned IR.
    ParameterType {
        /// Structural type-import failure.
        source: Box<Self>,
    },
    /// A constant floating-point field was not finite.
    NonFiniteConstantFloat {
        /// Stable field name within the constant DTO variant.
        field: &'static str,
    },
}

impl fmt::Display for IRImportError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::BasicBlockInstruction {
                block,
                index,
                source,
            } => write!(
                formatter,
                "basic-block DTO '{block}' instruction at index {index} could not be imported: {source}"
            ),
            Self::InstructionField {
                instruction,
                field,
                source,
            } => write!(
                formatter,
                "instruction DTO kind '{instruction}' field '{field}' could not be imported: {source}"
            ),
            Self::MethodResultReceiverNotStruct { actual } => write!(
                formatter,
                "method-result receiver must be a struct type, found wire type '{actual}'"
            ),
            Self::ValueType { kind, source } => write!(
                formatter,
                "value DTO variant '{kind}' field 'type' could not be imported: {source}"
            ),
            Self::StorageType { source } => write!(
                formatter,
                "storage DTO field 'type' could not be imported: {source}"
            ),
            Self::ParameterType { source } => write!(
                formatter,
                "parameter DTO field 'type' could not be imported: {source}"
            ),
            Self::NonFiniteConstantFloat { field } => write!(
                formatter,
                "constant DTO field '{field}' must contain a finite floating-point value"
            ),
        }
    }
}

impl Error for IRImportError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::BasicBlockInstruction { source, .. }
            | Self::InstructionField { source, .. }
            | Self::ValueType { source, .. }
            | Self::StorageType { source }
            | Self::ParameterType { source } => Some(source.as_ref()),
            Self::MethodResultReceiverNotStruct { .. } | Self::NonFiniteConstantFloat { .. } => {
                None
            }
        }
    }
}

/// Reconstruct an owned Rust IR type from a borrowed wire DTO.
pub fn import_type(type_: &IRTypeDTO) -> Result<IRType, IRImportError> {
    type_.try_into()
}

/// Reconstruct an owned Rust IR enum constant from a borrowed wire DTO.
pub fn import_enum_constant(constant: &IREnumConstantDTO) -> Result<IREnumConstant, IRImportError> {
    constant.try_into()
}

/// Reconstruct an owned Rust IR constant from a borrowed wire DTO.
pub fn import_constant(constant: &IRConstantDTO) -> Result<IRConstant, IRImportError> {
    constant.try_into()
}

/// Reconstruct an owned Rust IR value from a borrowed wire DTO.
pub fn import_value(value: &IRValueDTO) -> Result<IRValue, IRImportError> {
    value.try_into()
}

/// Reconstruct an owned Rust IR storage location from a borrowed wire DTO.
pub fn import_storage(storage: &IRStorageDTO) -> Result<IRStorage, IRImportError> {
    storage.try_into()
}

/// Reconstruct an owned Rust IR parameter from a borrowed wire DTO.
pub fn import_parameter(parameter: &IRParameterDTO) -> Result<IRParameter, IRImportError> {
    parameter.try_into()
}

/// Reconstruct an owned Rust source location from a borrowed wire DTO.
pub fn import_source_location(
    source_location: &IRSourceLocationDTO,
) -> Result<IRSourceLocation, IRImportError> {
    source_location.try_into()
}

/// Reconstruct an optional owned Rust source location from a nullable wire field.
pub fn import_optional_source_location(
    source_location: &NullableDTO<IRSourceLocationDTO>,
) -> Result<Option<IRSourceLocation>, IRImportError> {
    source_location
        .0
        .as_ref()
        .map(IRSourceLocation::try_from)
        .transpose()
}

/// Reconstruct an owned Rust IR instruction from a borrowed wire DTO.
///
/// All sixty-eight frozen schema-v1 instruction kinds are supported. Semantic
/// validity remains the responsibility of the IR verifier.
pub fn import_instruction(instruction: &IRInstructionDTO) -> Result<IRInstruction, IRImportError> {
    instruction.try_into()
}

/// Reconstruct an owned Rust basic block from a borrowed wire DTO.
///
/// Instruction order and duplicates are retained exactly. Control-flow and
/// terminator validity remain the responsibility of the IR verifier.
pub fn import_basic_block(block: &IRBasicBlockDTO) -> Result<IRBasicBlock, IRImportError> {
    block.try_into()
}

impl TryFrom<&IRBasicBlockDTO> for IRBasicBlock {
    type Error = IRImportError;

    fn try_from(block: &IRBasicBlockDTO) -> Result<Self, Self::Error> {
        let instructions = block
            .instructions
            .iter()
            .enumerate()
            .map(|(index, instruction)| {
                import_instruction(instruction).map_err(|source| {
                    IRImportError::BasicBlockInstruction {
                        block: block.name.clone(),
                        index,
                        source: Box::new(source),
                    }
                })
            })
            .collect::<Result<_, _>>()?;

        Ok(Self {
            name: block.name.clone(),
            instructions,
        })
    }
}

impl TryFrom<IRBasicBlockDTO> for IRBasicBlock {
    type Error = IRImportError;

    fn try_from(block: IRBasicBlockDTO) -> Result<Self, Self::Error> {
        Self::try_from(&block)
    }
}

impl TryFrom<&IRInstructionDTO> for IRInstruction {
    type Error = IRImportError;

    #[allow(clippy::too_many_lines)]
    fn try_from(instruction: &IRInstructionDTO) -> Result<Self, Self::Error> {
        let kind = wire_instruction_kind(instruction);

        match instruction {
            IRInstructionDTO::Const { result, value } => Ok(Self::IRConst {
                result: import_instruction_value(kind, "result", result)?,
                value: import_instruction_constant(kind, "value", value)?,
            }),
            IRInstructionDTO::Load { result, slot } => Ok(Self::IRLoad {
                result: import_instruction_value(kind, "result", result)?,
                slot: import_instruction_value(kind, "slot", slot)?,
            }),
            IRInstructionDTO::Store { slot, value } => Ok(Self::IRStore {
                slot: import_instruction_value(kind, "slot", slot)?,
                value: import_instruction_value(kind, "value", value)?,
            }),
            IRInstructionDTO::InitDefault {
                destination,
                source_location,
            } => Ok(Self::IRInitDefault {
                destination: import_instruction_storage(kind, "destination", destination)?,
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::CopyInit {
                destination,
                source,
                source_location,
            } => Ok(Self::IRCopyInit {
                destination: import_instruction_storage(kind, "destination", destination)?,
                source: import_instruction_value(kind, "source", source)?,
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::MoveInit {
                destination,
                source,
                source_location,
            } => Ok(Self::IRMoveInit {
                destination: import_instruction_storage(kind, "destination", destination)?,
                source: import_instruction_storage(kind, "source", source)?,
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::Assign {
                destination,
                source,
                source_location,
            } => Ok(Self::IRAssign {
                destination: import_instruction_storage(kind, "destination", destination)?,
                source: import_instruction_value(kind, "source", source)?,
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::Destroy {
                value,
                source_location,
            } => Ok(Self::IRDestroy {
                value: import_instruction_storage(kind, "value", value)?,
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::Relocate {
                destination,
                source,
                count,
                source_location,
            } => Ok(Self::IRRelocate {
                destination: import_instruction_storage(kind, "destination", destination)?,
                source: import_instruction_storage(kind, "source", source)?,
                count: *count,
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::BinaryOp {
                result,
                operator,
                left,
                right,
                source_location,
            } => Ok(Self::IRBinaryOp {
                result: import_instruction_value(kind, "result", result)?,
                operator: operator.clone(),
                left: import_instruction_value(kind, "left", left)?,
                right: import_instruction_value(kind, "right", right)?,
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::UnaryOp {
                result,
                operator,
                operand,
            } => Ok(Self::IRUnaryOp {
                result: import_instruction_value(kind, "result", result)?,
                operator: operator.clone(),
                operand: import_instruction_value(kind, "operand", operand)?,
            }),
            IRInstructionDTO::CompareOp {
                result,
                operator,
                left,
                right,
                aggregate_shape,
            } => Ok(Self::IRCompareOp {
                result: import_instruction_value(kind, "result", result)?,
                operator: operator.clone(),
                left: import_instruction_value(kind, "left", left)?,
                right: import_instruction_value(kind, "right", right)?,
                aggregate_shape: aggregate_shape.0.clone(),
            }),
            IRInstructionDTO::Cast { result, value } => Ok(Self::IRCast {
                result: import_instruction_value(kind, "result", result)?,
                value: import_instruction_value(kind, "value", value)?,
            }),
            IRInstructionDTO::Call {
                function,
                arguments,
                result,
                builtin,
                source_location,
            } => Ok(Self::IRCall {
                function: function.clone(),
                arguments: import_instruction_values(kind, "arguments", arguments)?,
                result: import_optional_instruction_value(kind, "result", result)?,
                builtin: builtin.0.clone(),
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::FunctionRef { result, function } => Ok(Self::IRFunctionRef {
                result: import_instruction_value(kind, "result", result)?,
                function: function.clone(),
            }),
            IRInstructionDTO::CallIndirect {
                callee,
                arguments,
                result,
            } => Ok(Self::IRCallIndirect {
                callee: import_instruction_value(kind, "callee", callee)?,
                arguments: import_instruction_values(kind, "arguments", arguments)?,
                result: import_optional_instruction_value(kind, "result", result)?,
            }),
            IRInstructionDTO::Print {
                value,
                newline,
                aggregate_shape,
            } => Ok(Self::IRPrint {
                value: import_instruction_value(kind, "value", value)?,
                newline: *newline,
                aggregate_shape: aggregate_shape.0.clone(),
            }),
            IRInstructionDTO::StructNew { result, fields } => Ok(Self::IRStructNew {
                result: import_instruction_value(kind, "result", result)?,
                fields: import_instruction_values(kind, "fields", fields)?,
            }),
            IRInstructionDTO::StructGet {
                result,
                r#struct,
                field_index,
                field_name,
            } => Ok(Self::IRStructGet {
                result: import_instruction_value(kind, "result", result)?,
                r#struct: import_instruction_value(kind, "struct", r#struct)?,
                field_index: *field_index,
                field_name: field_name.clone(),
            }),
            IRInstructionDTO::StructSet {
                result,
                r#struct,
                field_index,
                field_name,
                value,
            } => Ok(Self::IRStructSet {
                result: import_instruction_value(kind, "result", result)?,
                r#struct: import_instruction_value(kind, "struct", r#struct)?,
                field_index: *field_index,
                field_name: field_name.clone(),
                value: import_instruction_value(kind, "value", value)?,
            }),
            IRInstructionDTO::MethodResultNew {
                result,
                receiver,
                value,
            } => Ok(Self::IRMethodResultNew {
                result: import_instruction_value(kind, "result", result)?,
                receiver: import_instruction_value(kind, "receiver", receiver)?,
                value: import_optional_instruction_value(kind, "value", value)?,
            }),
            IRInstructionDTO::MethodResultReceiver {
                result,
                method_result,
            } => Ok(Self::IRMethodResultReceiver {
                result: import_instruction_value(kind, "result", result)?,
                method_result: import_instruction_value(kind, "method_result", method_result)?,
            }),
            IRInstructionDTO::MethodResultValue {
                result,
                method_result,
            } => Ok(Self::IRMethodResultValue {
                result: import_instruction_value(kind, "result", result)?,
                method_result: import_instruction_value(kind, "method_result", method_result)?,
            }),
            IRInstructionDTO::ArrayNew { result, elements } => Ok(Self::IRArrayNew {
                result: import_instruction_value(kind, "result", result)?,
                elements: import_instruction_values(kind, "elements", elements)?,
            }),
            IRInstructionDTO::ListNew { result, elements } => Ok(Self::IRListNew {
                result: import_instruction_value(kind, "result", result)?,
                elements: import_instruction_values(kind, "elements", elements)?,
            }),
            IRInstructionDTO::ArrayCopy {
                result,
                array,
                source_location,
            } => Ok(Self::IRArrayCopy {
                result: import_instruction_value(kind, "result", result)?,
                array: import_instruction_value(kind, "array", array)?,
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::ListCopy {
                result,
                list_value,
                source_location,
            } => Ok(Self::IRListCopy {
                result: import_instruction_value(kind, "result", result)?,
                list_value: import_instruction_value(kind, "list_value", list_value)?,
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::ListContains {
                result,
                list_value,
                value,
            } => Ok(Self::IRListContains {
                result: import_instruction_value(kind, "result", result)?,
                list_value: import_instruction_value(kind, "list_value", list_value)?,
                value: import_instruction_value(kind, "value", value)?,
            }),
            IRInstructionDTO::ListIndexOf {
                result,
                list_value,
                value,
            } => Ok(Self::IRListIndexOf {
                result: import_instruction_value(kind, "result", result)?,
                list_value: import_instruction_value(kind, "list_value", list_value)?,
                value: import_instruction_value(kind, "value", value)?,
            }),
            IRInstructionDTO::ListClear { list_value } => Ok(Self::IRListClear {
                list_value: import_instruction_value(kind, "list_value", list_value)?,
            }),
            IRInstructionDTO::ListPush { list_value, value } => Ok(Self::IRListPush {
                list_value: import_instruction_value(kind, "list_value", list_value)?,
                value: import_instruction_value(kind, "value", value)?,
            }),
            IRInstructionDTO::ListInsert {
                list_value,
                index,
                value,
            } => Ok(Self::IRListInsert {
                list_value: import_instruction_value(kind, "list_value", list_value)?,
                index: import_instruction_value(kind, "index", index)?,
                value: import_instruction_value(kind, "value", value)?,
            }),
            IRInstructionDTO::ListRemoveAt {
                result,
                list_value,
                index,
            } => Ok(Self::IRListRemoveAt {
                result: import_instruction_value(kind, "result", result)?,
                list_value: import_instruction_value(kind, "list_value", list_value)?,
                index: import_instruction_value(kind, "index", index)?,
            }),
            IRInstructionDTO::ListPop { result, list_value } => Ok(Self::IRListPop {
                result: import_instruction_value(kind, "result", result)?,
                list_value: import_instruction_value(kind, "list_value", list_value)?,
            }),
            IRInstructionDTO::ListReverse { list_value } => Ok(Self::IRListReverse {
                list_value: import_instruction_value(kind, "list_value", list_value)?,
            }),
            IRInstructionDTO::SequenceSort { sequence } => Ok(Self::IRSequenceSort {
                sequence: import_instruction_value(kind, "sequence", sequence)?,
            }),
            IRInstructionDTO::ArrayGet {
                result,
                array,
                index,
                borrowed,
                borrow_scope,
                source_location,
            } => Ok(Self::IRArrayGet {
                result: import_instruction_value(kind, "result", result)?,
                array: import_instruction_value(kind, "array", array)?,
                index: import_instruction_value(kind, "index", index)?,
                borrowed: *borrowed,
                borrow_scope: borrow_scope.0.clone(),
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::ArraySlice {
                result,
                array,
                start,
                end,
                source_location,
            } => Ok(Self::IRArraySlice {
                result: import_instruction_value(kind, "result", result)?,
                array: import_instruction_value(kind, "array", array)?,
                start: import_instruction_value(kind, "start", start)?,
                end: import_instruction_value(kind, "end", end)?,
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::ListSlice {
                result,
                list_value,
                start,
                end,
                source_location,
            } => Ok(Self::IRListSlice {
                result: import_instruction_value(kind, "result", result)?,
                list_value: import_instruction_value(kind, "list_value", list_value)?,
                start: import_instruction_value(kind, "start", start)?,
                end: import_instruction_value(kind, "end", end)?,
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::ListGet {
                result,
                list_value,
                index,
                borrowed,
                borrow_scope,
                source_location,
            } => Ok(Self::IRListGet {
                result: import_instruction_value(kind, "result", result)?,
                list_value: import_instruction_value(kind, "list_value", list_value)?,
                index: import_instruction_value(kind, "index", index)?,
                borrowed: *borrowed,
                borrow_scope: borrow_scope.0.clone(),
                source_location: import_instruction_source_location(kind, source_location)?,
            }),
            IRInstructionDTO::ArraySet {
                array,
                index,
                value,
            } => Ok(Self::IRArraySet {
                array: import_instruction_value(kind, "array", array)?,
                index: import_instruction_value(kind, "index", index)?,
                value: import_instruction_value(kind, "value", value)?,
            }),
            IRInstructionDTO::ListSet {
                list_value,
                index,
                value,
            } => Ok(Self::IRListSet {
                list_value: import_instruction_value(kind, "list_value", list_value)?,
                index: import_instruction_value(kind, "index", index)?,
                value: import_instruction_value(kind, "value", value)?,
            }),
            IRInstructionDTO::ArrayLength { result, array } => Ok(Self::IRArrayLength {
                result: import_instruction_value(kind, "result", result)?,
                array: import_instruction_value(kind, "array", array)?,
            }),
            IRInstructionDTO::ListLength { result, list_value } => Ok(Self::IRListLength {
                result: import_instruction_value(kind, "result", result)?,
                list_value: import_instruction_value(kind, "list_value", list_value)?,
            }),
            IRInstructionDTO::ListIsEmpty { result, list_value } => Ok(Self::IRListIsEmpty {
                result: import_instruction_value(kind, "result", result)?,
                list_value: import_instruction_value(kind, "list_value", list_value)?,
            }),
            IRInstructionDTO::VectorNew {
                result,
                elements,
                orientation,
            } => Ok(Self::IRVectorNew {
                result: import_instruction_value(kind, "result", result)?,
                elements: import_instruction_values(kind, "elements", elements)?,
                orientation: orientation.0.clone(),
            }),
            IRInstructionDTO::MatrixNew {
                result,
                elements,
                shape: [rows, cols],
            } => Ok(Self::IRMatrixNew {
                result: import_instruction_value(kind, "result", result)?,
                elements: import_instruction_values(kind, "elements", elements)?,
                rows: *rows,
                cols: *cols,
            }),
            IRInstructionDTO::VectorAdd {
                result,
                left,
                right,
                shape: [length],
                orientation,
            } => Ok(Self::IRVectorAdd {
                result: import_instruction_value(kind, "result", result)?,
                left: import_instruction_value(kind, "left", left)?,
                right: import_instruction_value(kind, "right", right)?,
                length: *length,
                orientation: orientation.0.clone(),
            }),
            IRInstructionDTO::VectorSub {
                result,
                left,
                right,
                shape: [length],
                orientation,
            } => Ok(Self::IRVectorSub {
                result: import_instruction_value(kind, "result", result)?,
                left: import_instruction_value(kind, "left", left)?,
                right: import_instruction_value(kind, "right", right)?,
                length: *length,
                orientation: orientation.0.clone(),
            }),
            IRInstructionDTO::VectorScale {
                result,
                vector,
                scalar,
                shape: [length],
                orientation,
            } => Ok(Self::IRVectorScale {
                result: import_instruction_value(kind, "result", result)?,
                vector: import_instruction_value(kind, "vector", vector)?,
                scalar: import_instruction_value(kind, "scalar", scalar)?,
                length: *length,
                orientation: orientation.0.clone(),
            }),
            IRInstructionDTO::VectorDot {
                result,
                left,
                right,
                shape: [length],
            } => Ok(Self::IRVectorDot {
                result: import_instruction_value(kind, "result", result)?,
                left: import_instruction_value(kind, "left", left)?,
                right: import_instruction_value(kind, "right", right)?,
                length: *length,
            }),
            IRInstructionDTO::OuterProduct {
                result,
                column,
                row,
                shape: [rows, cols],
            } => Ok(Self::IROuterProduct {
                result: import_instruction_value(kind, "result", result)?,
                column: import_instruction_value(kind, "column", column)?,
                row: import_instruction_value(kind, "row", row)?,
                rows: *rows,
                cols: *cols,
            }),
            IRInstructionDTO::MatrixAdd {
                result,
                left,
                right,
                shape: [rows, cols],
            } => Ok(Self::IRMatrixAdd {
                result: import_instruction_value(kind, "result", result)?,
                left: import_instruction_value(kind, "left", left)?,
                right: import_instruction_value(kind, "right", right)?,
                rows: *rows,
                cols: *cols,
            }),
            IRInstructionDTO::MatrixSub {
                result,
                left,
                right,
                shape: [rows, cols],
            } => Ok(Self::IRMatrixSub {
                result: import_instruction_value(kind, "result", result)?,
                left: import_instruction_value(kind, "left", left)?,
                right: import_instruction_value(kind, "right", right)?,
                rows: *rows,
                cols: *cols,
            }),
            IRInstructionDTO::MatrixScale {
                result,
                matrix,
                scalar,
                shape: [rows, cols],
            } => Ok(Self::IRMatrixScale {
                result: import_instruction_value(kind, "result", result)?,
                matrix: import_instruction_value(kind, "matrix", matrix)?,
                scalar: import_instruction_value(kind, "scalar", scalar)?,
                rows: *rows,
                cols: *cols,
            }),
            IRInstructionDTO::MatrixMatMul {
                result,
                left,
                right,
                shape: [rows, inner, cols],
            } => Ok(Self::IRMatrixMatMul {
                result: import_instruction_value(kind, "result", result)?,
                left: import_instruction_value(kind, "left", left)?,
                right: import_instruction_value(kind, "right", right)?,
                rows: *rows,
                inner: *inner,
                cols: *cols,
            }),
            IRInstructionDTO::MatrixVectorMul {
                result,
                matrix,
                vector,
                shape: [rows, inner],
            } => Ok(Self::IRMatrixVectorMul {
                result: import_instruction_value(kind, "result", result)?,
                matrix: import_instruction_value(kind, "matrix", matrix)?,
                vector: import_instruction_value(kind, "vector", vector)?,
                rows: *rows,
                inner: *inner,
            }),
            IRInstructionDTO::VectorMatrixMul {
                result,
                vector,
                matrix,
                shape: [rows, cols],
            } => Ok(Self::IRVectorMatrixMul {
                result: import_instruction_value(kind, "result", result)?,
                vector: import_instruction_value(kind, "vector", vector)?,
                matrix: import_instruction_value(kind, "matrix", matrix)?,
                rows: *rows,
                cols: *cols,
            }),
            IRInstructionDTO::VectorGet {
                result,
                vector,
                index,
            } => Ok(Self::IRVectorGet {
                result: import_instruction_value(kind, "result", result)?,
                vector: import_instruction_value(kind, "vector", vector)?,
                index: import_instruction_value(kind, "index", index)?,
            }),
            IRInstructionDTO::MatrixGet {
                result,
                matrix,
                row,
                column,
                shape: [cols],
            } => Ok(Self::IRMatrixGet {
                result: import_instruction_value(kind, "result", result)?,
                matrix: import_instruction_value(kind, "matrix", matrix)?,
                row: import_instruction_value(kind, "row", row)?,
                column: import_instruction_value(kind, "column", column)?,
                cols: *cols,
            }),
            IRInstructionDTO::VectorLength { result, vector } => Ok(Self::IRVectorLength {
                result: import_instruction_value(kind, "result", result)?,
                vector: import_instruction_value(kind, "vector", vector)?,
            }),
            IRInstructionDTO::MatrixRows {
                result,
                matrix,
                shape: [rows],
            } => Ok(Self::IRMatrixRows {
                result: import_instruction_value(kind, "result", result)?,
                matrix: import_instruction_value(kind, "matrix", matrix)?,
                rows: *rows,
            }),
            IRInstructionDTO::MatrixColumns {
                result,
                matrix,
                shape: [columns],
            } => Ok(Self::IRMatrixColumns {
                result: import_instruction_value(kind, "result", result)?,
                matrix: import_instruction_value(kind, "matrix", matrix)?,
                columns: *columns,
            }),
            IRInstructionDTO::VectorSet {
                vector,
                index,
                value,
            } => Ok(Self::IRVectorSet {
                vector: import_instruction_value(kind, "vector", vector)?,
                index: import_instruction_value(kind, "index", index)?,
                value: import_instruction_value(kind, "value", value)?,
            }),
            IRInstructionDTO::MatrixSet {
                matrix,
                row,
                column,
                value,
                shape: [cols],
            } => Ok(Self::IRMatrixSet {
                matrix: import_instruction_value(kind, "matrix", matrix)?,
                row: import_instruction_value(kind, "row", row)?,
                column: import_instruction_value(kind, "column", column)?,
                value: import_instruction_value(kind, "value", value)?,
                cols: *cols,
            }),
            IRInstructionDTO::Branch {
                condition,
                true_target,
                false_target,
            } => Ok(Self::IRBranch {
                condition: import_instruction_value(kind, "condition", condition)?,
                true_target: true_target.clone(),
                false_target: false_target.clone(),
            }),
            IRInstructionDTO::Jump { target } => Ok(Self::IRJump {
                target: target.clone(),
            }),
            IRInstructionDTO::Return {
                value,
                transferred_storage,
            } => Ok(Self::IRReturn {
                value: import_optional_instruction_value(kind, "value", value)?,
                transferred_storage: import_instruction_field(
                    kind,
                    "transferred_storage",
                    transferred_storage
                        .0
                        .as_ref()
                        .map(import_storage)
                        .transpose(),
                )?,
            }),
        }
    }
}

impl TryFrom<IRInstructionDTO> for IRInstruction {
    type Error = IRImportError;

    fn try_from(instruction: IRInstructionDTO) -> Result<Self, Self::Error> {
        Self::try_from(&instruction)
    }
}

impl TryFrom<IRTypeDTO> for IRType {
    type Error = IRImportError;

    fn try_from(type_: IRTypeDTO) -> Result<Self, Self::Error> {
        match type_ {
            IRTypeDTO::Int {} => Ok(IntType.into()),
            IRTypeDTO::Float {} => Ok(FloatType.into()),
            IRTypeDTO::Double {} => Ok(DoubleType.into()),
            IRTypeDTO::Bool {} => Ok(BoolType.into()),
            IRTypeDTO::String {} => Ok(StringType.into()),
            IRTypeDTO::Void {} => Ok(VoidType.into()),
            IRTypeDTO::Function {
                parameter_types,
                return_type,
            } => Ok(FunctionType {
                parameter_types: parameter_types
                    .into_iter()
                    .map(Self::try_from)
                    .collect::<Result<_, _>>()?,
                return_type: Box::new(Self::try_from(*return_type)?),
            }
            .into()),
            IRTypeDTO::Complex {} => Ok(ComplexType.into()),
            IRTypeDTO::Nullable { inner } => Ok(NullableType {
                inner: Box::new(Self::try_from(*inner)?),
            }
            .into()),
            IRTypeDTO::List { element } => Ok(ListType {
                element: Box::new(Self::try_from(*element)?),
            }
            .into()),
            IRTypeDTO::Array { element } => Ok(ArrayType {
                element: Box::new(Self::try_from(*element)?),
            }
            .into()),
            IRTypeDTO::Vector {
                element,
                orientation: NullableDTO(orientation),
            } => Ok(VectorType {
                element: Box::new(Self::try_from(*element)?),
                orientation,
            }
            .into()),
            IRTypeDTO::Matrix { element } => Ok(MatrixType {
                element: Box::new(Self::try_from(*element)?),
            }
            .into()),
            IRTypeDTO::Struct { name } => Ok(StructType { name }.into()),
            IRTypeDTO::MethodResult { receiver, value } => {
                let receiver = match *receiver {
                    IRTypeDTO::Struct { name } => StructType { name },
                    actual => {
                        return Err(IRImportError::MethodResultReceiverNotStruct {
                            actual: wire_type_tag(&actual),
                        });
                    }
                };
                Ok(MethodResultType {
                    receiver,
                    value: Box::new(Self::try_from(*value)?),
                }
                .into())
            }
            IRTypeDTO::ClassRef { name } => Ok(ClassRefType { name }.into()),
            IRTypeDTO::Interface { name } => Ok(InterfaceType { name }.into()),
            IRTypeDTO::Enum {
                name,
                variants,
                display_name: NullableDTO(display_name),
            } => Ok(EnumType {
                name,
                variants,
                display_name,
            }
            .into()),
        }
    }
}

impl TryFrom<&IRTypeDTO> for IRType {
    type Error = IRImportError;

    fn try_from(type_: &IRTypeDTO) -> Result<Self, Self::Error> {
        Self::try_from(type_.clone())
    }
}

impl TryFrom<IREnumConstantDTO> for IREnumConstant {
    type Error = IRImportError;

    fn try_from(constant: IREnumConstantDTO) -> Result<Self, Self::Error> {
        let IREnumConstantDTO::EnumConstant {
            enum_name,
            member_name,
            member_id,
            discriminant,
        } = constant;

        Ok(Self {
            enum_name,
            member_name,
            member_id,
            discriminant,
        })
    }
}

impl TryFrom<&IREnumConstantDTO> for IREnumConstant {
    type Error = IRImportError;

    fn try_from(constant: &IREnumConstantDTO) -> Result<Self, Self::Error> {
        Self::try_from(constant.clone())
    }
}

impl TryFrom<IRConstantDTO> for IRConstant {
    type Error = IRImportError;

    fn try_from(constant: IRConstantDTO) -> Result<Self, Self::Error> {
        match constant {
            IRConstantDTO::Bool { value } => Ok(Self::Bool(value)),
            IRConstantDTO::Int { value } => Ok(Self::Int(value)),
            IRConstantDTO::Float { value } => {
                Ok(Self::Float(import_finite_constant_float(value.0, "value")?))
            }
            IRConstantDTO::Complex { real, imaginary } => Ok(Self::Complex {
                real: import_finite_constant_float(real.0, "real")?,
                imaginary: import_finite_constant_float(imaginary.0, "imaginary")?,
            }),
            IRConstantDTO::String { value } => Ok(Self::String(value)),
            IRConstantDTO::Enum { value } => Ok(Self::Enum(value.try_into()?)),
        }
    }
}

impl TryFrom<&IRConstantDTO> for IRConstant {
    type Error = IRImportError;

    fn try_from(constant: &IRConstantDTO) -> Result<Self, Self::Error> {
        Self::try_from(constant.clone())
    }
}

impl TryFrom<IRValueDTO> for IRValue {
    type Error = IRImportError;

    fn try_from(value: IRValueDTO) -> Result<Self, Self::Error> {
        let (kind, name, type_) = match value {
            IRValueDTO::Value { name, r#type } => ("value", name, r#type),
            IRValueDTO::Storage { name, r#type } => ("storage", name, r#type),
            IRValueDTO::Parameter { name, r#type } => ("parameter", name, r#type),
        };
        let r#type = IRType::try_from(type_).map_err(|source| IRImportError::ValueType {
            kind,
            source: Box::new(source),
        })?;

        Ok(Self { name, r#type })
    }
}

impl TryFrom<&IRValueDTO> for IRValue {
    type Error = IRImportError;

    fn try_from(value: &IRValueDTO) -> Result<Self, Self::Error> {
        Self::try_from(value.clone())
    }
}

impl TryFrom<IRStorageDTO> for IRStorage {
    type Error = IRImportError;

    fn try_from(storage: IRStorageDTO) -> Result<Self, Self::Error> {
        let IRStorageDTO::Storage { name, r#type } = storage;
        let r#type = IRType::try_from(r#type).map_err(|source| IRImportError::StorageType {
            source: Box::new(source),
        })?;

        Ok(Self { name, r#type })
    }
}

impl TryFrom<&IRStorageDTO> for IRStorage {
    type Error = IRImportError;

    fn try_from(storage: &IRStorageDTO) -> Result<Self, Self::Error> {
        Self::try_from(storage.clone())
    }
}

impl TryFrom<IRParameterDTO> for IRParameter {
    type Error = IRImportError;

    fn try_from(parameter: IRParameterDTO) -> Result<Self, Self::Error> {
        let IRParameterDTO::Parameter { name, r#type } = parameter;
        let r#type = IRType::try_from(r#type).map_err(|source| IRImportError::ParameterType {
            source: Box::new(source),
        })?;

        Ok(Self { name, r#type })
    }
}

impl TryFrom<&IRParameterDTO> for IRParameter {
    type Error = IRImportError;

    fn try_from(parameter: &IRParameterDTO) -> Result<Self, Self::Error> {
        Self::try_from(parameter.clone())
    }
}

impl TryFrom<IRSourceLocationDTO> for IRSourceLocation {
    type Error = IRImportError;

    fn try_from(source_location: IRSourceLocationDTO) -> Result<Self, Self::Error> {
        let IRSourceLocationDTO::SourceLocation {
            line,
            column,
            path: NullableDTO(path),
        } = source_location;

        Ok(Self { line, column, path })
    }
}

impl TryFrom<&IRSourceLocationDTO> for IRSourceLocation {
    type Error = IRImportError;

    fn try_from(source_location: &IRSourceLocationDTO) -> Result<Self, Self::Error> {
        Self::try_from(source_location.clone())
    }
}

fn import_finite_constant_float(value: f64, field: &'static str) -> Result<f64, IRImportError> {
    if value.is_finite() {
        Ok(value)
    } else {
        Err(IRImportError::NonFiniteConstantFloat { field })
    }
}

fn import_instruction_field<T>(
    instruction: &'static str,
    field: &'static str,
    result: Result<T, IRImportError>,
) -> Result<T, IRImportError> {
    result.map_err(|source| IRImportError::InstructionField {
        instruction,
        field,
        source: Box::new(source),
    })
}

fn import_instruction_value(
    instruction: &'static str,
    field: &'static str,
    value: &IRValueDTO,
) -> Result<IRValue, IRImportError> {
    import_instruction_field(instruction, field, import_value(value))
}

fn import_instruction_values(
    instruction: &'static str,
    field: &'static str,
    values: &[IRValueDTO],
) -> Result<Vec<IRValue>, IRImportError> {
    values
        .iter()
        .map(|value| import_instruction_value(instruction, field, value))
        .collect()
}

fn import_optional_instruction_value(
    instruction: &'static str,
    field: &'static str,
    value: &NullableDTO<IRValueDTO>,
) -> Result<Option<IRValue>, IRImportError> {
    value
        .0
        .as_ref()
        .map(|value| import_instruction_value(instruction, field, value))
        .transpose()
}

fn import_instruction_constant(
    instruction: &'static str,
    field: &'static str,
    constant: &IRConstantDTO,
) -> Result<IRConstant, IRImportError> {
    import_instruction_field(instruction, field, import_constant(constant))
}

fn import_instruction_storage(
    instruction: &'static str,
    field: &'static str,
    storage: &IRStorageDTO,
) -> Result<IRStorage, IRImportError> {
    import_instruction_field(instruction, field, import_storage(storage))
}

fn import_instruction_source_location(
    instruction: &'static str,
    source_location: &NullableDTO<IRSourceLocationDTO>,
) -> Result<Option<IRSourceLocation>, IRImportError> {
    import_instruction_field(
        instruction,
        "source_location",
        import_optional_source_location(source_location),
    )
}

const fn wire_type_tag(type_: &IRTypeDTO) -> &'static str {
    match type_ {
        IRTypeDTO::Int {} => "int",
        IRTypeDTO::Float {} => "float",
        IRTypeDTO::Double {} => "double",
        IRTypeDTO::Bool {} => "bool",
        IRTypeDTO::String {} => "string",
        IRTypeDTO::Void {} => "void",
        IRTypeDTO::Function { .. } => "function",
        IRTypeDTO::Complex {} => "complex",
        IRTypeDTO::Nullable { .. } => "nullable",
        IRTypeDTO::List { .. } => "list",
        IRTypeDTO::Array { .. } => "array",
        IRTypeDTO::Vector { .. } => "vector",
        IRTypeDTO::Matrix { .. } => "matrix",
        IRTypeDTO::Struct { .. } => "struct",
        IRTypeDTO::MethodResult { .. } => "method_result",
        IRTypeDTO::ClassRef { .. } => "class_ref",
        IRTypeDTO::Interface { .. } => "interface",
        IRTypeDTO::Enum { .. } => "enum",
    }
}

const fn wire_instruction_kind(instruction: &IRInstructionDTO) -> &'static str {
    match instruction {
        IRInstructionDTO::Const { .. } => "const",
        IRInstructionDTO::Load { .. } => "load",
        IRInstructionDTO::Store { .. } => "store",
        IRInstructionDTO::InitDefault { .. } => "init_default",
        IRInstructionDTO::CopyInit { .. } => "copy_init",
        IRInstructionDTO::MoveInit { .. } => "move_init",
        IRInstructionDTO::Assign { .. } => "assign",
        IRInstructionDTO::Destroy { .. } => "destroy",
        IRInstructionDTO::Relocate { .. } => "relocate",
        IRInstructionDTO::BinaryOp { .. } => "binary_op",
        IRInstructionDTO::UnaryOp { .. } => "unary_op",
        IRInstructionDTO::CompareOp { .. } => "compare_op",
        IRInstructionDTO::Cast { .. } => "cast",
        IRInstructionDTO::Call { .. } => "call",
        IRInstructionDTO::FunctionRef { .. } => "function_ref",
        IRInstructionDTO::CallIndirect { .. } => "call_indirect",
        IRInstructionDTO::Print { .. } => "print",
        IRInstructionDTO::StructNew { .. } => "struct_new",
        IRInstructionDTO::StructGet { .. } => "struct_get",
        IRInstructionDTO::StructSet { .. } => "struct_set",
        IRInstructionDTO::MethodResultNew { .. } => "method_result_new",
        IRInstructionDTO::MethodResultReceiver { .. } => "method_result_receiver",
        IRInstructionDTO::MethodResultValue { .. } => "method_result_value",
        IRInstructionDTO::ArrayNew { .. } => "array_new",
        IRInstructionDTO::ListNew { .. } => "list_new",
        IRInstructionDTO::ArrayCopy { .. } => "array_copy",
        IRInstructionDTO::ListCopy { .. } => "list_copy",
        IRInstructionDTO::ListContains { .. } => "list_contains",
        IRInstructionDTO::ListIndexOf { .. } => "list_index_of",
        IRInstructionDTO::ListClear { .. } => "list_clear",
        IRInstructionDTO::ListPush { .. } => "list_push",
        IRInstructionDTO::ListInsert { .. } => "list_insert",
        IRInstructionDTO::ListRemoveAt { .. } => "list_remove_at",
        IRInstructionDTO::ListPop { .. } => "list_pop",
        IRInstructionDTO::ListReverse { .. } => "list_reverse",
        IRInstructionDTO::SequenceSort { .. } => "sequence_sort",
        IRInstructionDTO::ArrayGet { .. } => "array_get",
        IRInstructionDTO::ArraySlice { .. } => "array_slice",
        IRInstructionDTO::ListSlice { .. } => "list_slice",
        IRInstructionDTO::ListGet { .. } => "list_get",
        IRInstructionDTO::ArraySet { .. } => "array_set",
        IRInstructionDTO::ListSet { .. } => "list_set",
        IRInstructionDTO::ArrayLength { .. } => "array_length",
        IRInstructionDTO::ListLength { .. } => "list_length",
        IRInstructionDTO::ListIsEmpty { .. } => "list_is_empty",
        IRInstructionDTO::VectorNew { .. } => "vector_new",
        IRInstructionDTO::MatrixNew { .. } => "matrix_new",
        IRInstructionDTO::VectorAdd { .. } => "vector_add",
        IRInstructionDTO::VectorSub { .. } => "vector_sub",
        IRInstructionDTO::VectorScale { .. } => "vector_scale",
        IRInstructionDTO::VectorDot { .. } => "vector_dot",
        IRInstructionDTO::OuterProduct { .. } => "outer_product",
        IRInstructionDTO::MatrixAdd { .. } => "matrix_add",
        IRInstructionDTO::MatrixSub { .. } => "matrix_sub",
        IRInstructionDTO::MatrixScale { .. } => "matrix_scale",
        IRInstructionDTO::MatrixMatMul { .. } => "matrix_mat_mul",
        IRInstructionDTO::MatrixVectorMul { .. } => "matrix_vector_mul",
        IRInstructionDTO::VectorMatrixMul { .. } => "vector_matrix_mul",
        IRInstructionDTO::VectorGet { .. } => "vector_get",
        IRInstructionDTO::MatrixGet { .. } => "matrix_get",
        IRInstructionDTO::VectorLength { .. } => "vector_length",
        IRInstructionDTO::MatrixRows { .. } => "matrix_rows",
        IRInstructionDTO::MatrixColumns { .. } => "matrix_columns",
        IRInstructionDTO::VectorSet { .. } => "vector_set",
        IRInstructionDTO::MatrixSet { .. } => "matrix_set",
        IRInstructionDTO::Branch { .. } => "branch",
        IRInstructionDTO::Jump { .. } => "jump",
        IRInstructionDTO::Return { .. } => "return",
    }
}
