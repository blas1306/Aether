//! Function-local SSA definition, ordering, and reference verification.

use std::collections::HashMap;

use aether_ir::{
    IRBasicBlock, IRFunction, IRInstruction, IRModule, IRType, IRValue, LifecycleSource,
};

use crate::ssa_error::{
    BlockSSAError, FunctionSSAError, ModuleSSAError, SSADefinitionError, SSADefinitionLocation,
    SSAInstructionLocation, SSAUseLocation,
};
use crate::verifier::{instruction_kind, instruction_result};

#[derive(Clone, Debug)]
pub(crate) struct Definition {
    pub(crate) r#type: IRType,
    pub(crate) location: SSADefinitionLocation,
}

/// One immutable value operand and its retained instruction field.
#[derive(Clone, Copy, Debug)]
pub(crate) struct SSAOperand<'instruction> {
    pub(crate) value: &'instruction IRValue,
    pub(crate) field_name: &'static str,
}

/// Verifies SSA definitions and references in every function of a module.
///
/// This pass is independent of type and structural verification. It does not
/// construct a CFG and deliberately accepts cross-block uses for the later
/// dominance pass.
pub fn verify_module_ssa(module: &IRModule) -> Result<(), ModuleSSAError> {
    for (function_index, function) in module.functions.iter().enumerate() {
        verify_function_ssa(function).map_err(|source| ModuleSSAError {
            function_index,
            function_name: function.name.clone(),
            source: Box::new(source),
        })?;
    }
    Ok(())
}

/// Verifies one function's SSA definition namespace and value references.
///
/// Parameters are definitions before every instruction. Instruction results
/// are definitions immediately after their instruction. Cross-block ordering
/// and availability are intentionally deferred to dominance verification.
pub fn verify_function_ssa(function: &IRFunction) -> Result<(), FunctionSSAError> {
    let definitions = collect_definitions(function)?;
    for (block_index, block) in function.blocks.iter().enumerate() {
        verify_block(function, block_index, block, &definitions).map_err(|source| {
            FunctionSSAError::Block {
                function_name: function.name.clone(),
                block_index,
                block_name: block.name.clone(),
                source: Box::new(source),
            }
        })?;
    }
    Ok(())
}

pub(crate) fn collect_definitions(
    function: &IRFunction,
) -> Result<HashMap<String, Definition>, FunctionSSAError> {
    let mut definitions: HashMap<String, Definition> = HashMap::new();
    for (parameter_index, parameter) in function.parameters.iter().enumerate() {
        let location = SSADefinitionLocation::Parameter { parameter_index };
        if let Some(previous) = definitions.get(&parameter.name) {
            let source = SSADefinitionError::DuplicateDefinition {
                ssa_identifier: parameter.name.clone(),
                defining_location: previous.location.clone(),
                duplicate_definition_location: location,
            };
            return Err(FunctionSSAError::Definition {
                function_name: function.name.clone(),
                ssa_identifier: parameter.name.clone(),
                source,
            });
        }
        definitions.insert(
            parameter.name.clone(),
            Definition {
                r#type: parameter.r#type.clone(),
                location,
            },
        );
    }

    for (block_index, block) in function.blocks.iter().enumerate() {
        for (instruction_index, instruction) in block.instructions.iter().enumerate() {
            let Some(result) = instruction_result(instruction) else {
                continue;
            };
            let instruction_location =
                instruction_location(block_index, block, instruction_index, instruction);
            let location = SSADefinitionLocation::Instruction(instruction_location.clone());
            if let Some(previous) = definitions.get(&result.name) {
                let source = SSADefinitionError::DuplicateDefinition {
                    ssa_identifier: result.name.clone(),
                    defining_location: previous.location.clone(),
                    duplicate_definition_location: location,
                };
                return Err(FunctionSSAError::Block {
                    function_name: function.name.clone(),
                    block_index,
                    block_name: block.name.clone(),
                    source: Box::new(BlockSSAError {
                        function_name: function.name.clone(),
                        block_name: block.name.clone(),
                        instruction_index,
                        instruction_kind: instruction_kind(instruction),
                        ssa_identifier: result.name.clone(),
                        source,
                    }),
                });
            }
            definitions.insert(
                result.name.clone(),
                Definition {
                    r#type: result.r#type.clone(),
                    location,
                },
            );
        }
    }
    Ok(definitions)
}

fn verify_block(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    definitions: &HashMap<String, Definition>,
) -> Result<(), BlockSSAError> {
    for (instruction_index, instruction) in block.instructions.iter().enumerate() {
        let instruction_location =
            instruction_location(block_index, block, instruction_index, instruction);
        for (operand_index, operand) in ssa_operands(instruction).into_iter().enumerate() {
            let operand = operand.value;
            let use_location = SSAUseLocation {
                instruction: instruction_location.clone(),
                operand_index,
            };
            let Some(definition) = definitions.get(&operand.name) else {
                return Err(block_error(
                    function,
                    block,
                    instruction_index,
                    instruction,
                    operand,
                    SSADefinitionError::UndefinedReference {
                        ssa_identifier: operand.name.clone(),
                        use_location,
                    },
                ));
            };

            if operand.r#type != definition.r#type {
                return Err(block_error(
                    function,
                    block,
                    instruction_index,
                    instruction,
                    operand,
                    SSADefinitionError::ReferenceTypeMismatch {
                        ssa_identifier: operand.name.clone(),
                        expected: definition.r#type.clone(),
                        actual: operand.r#type.clone(),
                        defining_location: definition.location.clone(),
                        use_location,
                    },
                ));
            }

            if let SSADefinitionLocation::Instruction(defining_location) = &definition.location {
                if defining_location.block_index == block_index
                    && defining_location.instruction_index >= instruction_index
                {
                    return Err(block_error(
                        function,
                        block,
                        instruction_index,
                        instruction,
                        operand,
                        SSADefinitionError::UseBeforeDefinition {
                            ssa_identifier: operand.name.clone(),
                            defining_location: definition.location.clone(),
                            use_location,
                        },
                    ));
                }
            }
        }
    }
    Ok(())
}

pub(crate) fn instruction_location(
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
) -> SSAInstructionLocation {
    SSAInstructionLocation {
        block_index,
        block_name: block.name.clone(),
        instruction_index,
        instruction_kind: instruction_kind(instruction),
    }
}

fn block_error(
    function: &IRFunction,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    operand: &IRValue,
    source: SSADefinitionError,
) -> BlockSSAError {
    BlockSSAError {
        function_name: function.name.clone(),
        block_name: block.name.clone(),
        instruction_index,
        instruction_kind: instruction_kind(instruction),
        ssa_identifier: operand.name.clone(),
        source,
    }
}

// IRInstruction has no common operand iterator. Keep this exhaustive match in
// the verifier so new variants must explicitly classify immutable SSA values
// separately from IRStorage operands and literal/metadata fields.
#[allow(clippy::too_many_lines)]
pub(crate) fn ssa_operands(instruction: &IRInstruction) -> Vec<SSAOperand<'_>> {
    fn operand<'instruction>(
        field_name: &'static str,
        value: &'instruction IRValue,
    ) -> SSAOperand<'instruction> {
        SSAOperand { value, field_name }
    }

    match instruction {
        IRInstruction::IRConst { .. }
        | IRInstruction::IRLoad { .. }
        | IRInstruction::IRInitDefault { .. }
        | IRInstruction::IRMoveInit { .. }
        | IRInstruction::IRDestroy { .. }
        | IRInstruction::IRRelocate { .. }
        | IRInstruction::IRFunctionRef { .. }
        | IRInstruction::IRClassNew { .. }
        | IRInstruction::IRJump { .. }
        | IRInstruction::IRCopyInit {
            source: LifecycleSource::Storage(_),
            ..
        }
        | IRInstruction::IRAssign {
            source: LifecycleSource::Storage(_),
            ..
        } => Vec::new(),
        IRInstruction::IRStore { value, .. }
        | IRInstruction::IRCast { value, .. }
        | IRInstruction::IRPrint { value, .. } => vec![operand("value", value)],
        IRInstruction::IRCopyInit {
            source: LifecycleSource::Value(source),
            ..
        }
        | IRInstruction::IRAssign {
            source: LifecycleSource::Value(source),
            ..
        } => vec![operand("source", source)],
        IRInstruction::IRBinaryOp { left, right, .. }
        | IRInstruction::IRCompareOp { left, right, .. }
        | IRInstruction::IRVectorAdd { left, right, .. }
        | IRInstruction::IRVectorSub { left, right, .. }
        | IRInstruction::IRVectorDot { left, right, .. }
        | IRInstruction::IRMatrixAdd { left, right, .. }
        | IRInstruction::IRMatrixSub { left, right, .. }
        | IRInstruction::IRMatrixMatMul { left, right, .. } => {
            vec![operand("left", left), operand("right", right)]
        }
        IRInstruction::IRUnaryOp { operand: value, .. } => vec![operand("operand", value)],
        IRInstruction::IRCall { arguments, .. } => arguments
            .iter()
            .map(|value| operand("arguments", value))
            .collect(),
        IRInstruction::IRCallIndirect {
            callee, arguments, ..
        } => std::iter::once(operand("callee", callee))
            .chain(arguments.iter().map(|value| operand("arguments", value)))
            .collect(),
        IRInstruction::IRStructNew { fields, .. } => fields
            .iter()
            .map(|value| operand("fields", value))
            .collect(),
        IRInstruction::IRStructGet { r#struct, .. } => vec![operand("struct", r#struct)],
        IRInstruction::IRClassGet { object, .. } => vec![operand("object", object)],
        IRInstruction::IRClassSet { object, value, .. } => {
            vec![operand("object", object), operand("value", value)]
        }
        IRInstruction::IRStructSet {
            r#struct, value, ..
        } => vec![operand("struct", r#struct), operand("value", value)],
        IRInstruction::IRMethodResultNew {
            receiver, value, ..
        } => std::iter::once(operand("receiver", receiver))
            .chain(value.iter().map(|value| operand("value", value)))
            .collect(),
        IRInstruction::IRMethodResultReceiver { method_result, .. }
        | IRInstruction::IRMethodResultValue { method_result, .. } => {
            vec![operand("method_result", method_result)]
        }
        IRInstruction::IRArrayNew { elements, .. }
        | IRInstruction::IRListNew { elements, .. }
        | IRInstruction::IRVectorNew { elements, .. }
        | IRInstruction::IRMatrixNew { elements, .. } => elements
            .iter()
            .map(|value| operand("elements", value))
            .collect(),
        IRInstruction::IRArrayCopy { array, .. } | IRInstruction::IRArrayLength { array, .. } => {
            vec![operand("array", array)]
        }
        IRInstruction::IRListCopy { list_value, .. }
        | IRInstruction::IRListClear { list_value }
        | IRInstruction::IRListPop { list_value, .. }
        | IRInstruction::IRListReverse { list_value }
        | IRInstruction::IRListLength { list_value, .. }
        | IRInstruction::IRListIsEmpty { list_value, .. } => {
            vec![operand("list_value", list_value)]
        }
        IRInstruction::IRListPush { list_value, value }
        | IRInstruction::IRListContains {
            list_value, value, ..
        }
        | IRInstruction::IRListIndexOf {
            list_value, value, ..
        } => vec![operand("list_value", list_value), operand("value", value)],
        IRInstruction::IRListInsert {
            list_value,
            index,
            value,
        }
        | IRInstruction::IRListSet {
            list_value,
            index,
            value,
        } => vec![
            operand("list_value", list_value),
            operand("index", index),
            operand("value", value),
        ],
        IRInstruction::IRListRemoveAt {
            list_value, index, ..
        }
        | IRInstruction::IRListGet {
            list_value, index, ..
        } => vec![operand("list_value", list_value), operand("index", index)],
        IRInstruction::IRSequenceSort { sequence } => vec![operand("sequence", sequence)],
        IRInstruction::IRVectorScale { vector, scalar, .. } => {
            vec![operand("vector", vector), operand("scalar", scalar)]
        }
        IRInstruction::IROuterProduct { column, row, .. } => {
            vec![operand("column", column), operand("row", row)]
        }
        IRInstruction::IRMatrixScale { matrix, scalar, .. } => {
            vec![operand("matrix", matrix), operand("scalar", scalar)]
        }
        IRInstruction::IRMatrixVectorMul { matrix, vector, .. } => {
            vec![operand("matrix", matrix), operand("vector", vector)]
        }
        IRInstruction::IRVectorMatrixMul { vector, matrix, .. } => {
            vec![operand("vector", vector), operand("matrix", matrix)]
        }
        IRInstruction::IRArrayGet { array, index, .. } => {
            vec![operand("array", array), operand("index", index)]
        }
        IRInstruction::IRArraySet {
            array,
            index,
            value,
            ..
        } => vec![
            operand("array", array),
            operand("index", index),
            operand("value", value),
        ],
        IRInstruction::IRArraySlice {
            array, start, end, ..
        } => vec![
            operand("array", array),
            operand("start", start),
            operand("end", end),
        ],
        IRInstruction::IRListSlice {
            list_value,
            start,
            end,
            ..
        } => vec![
            operand("list_value", list_value),
            operand("start", start),
            operand("end", end),
        ],
        IRInstruction::IRVectorGet { vector, index, .. } => {
            vec![operand("vector", vector), operand("index", index)]
        }
        IRInstruction::IRMatrixGet {
            matrix,
            row,
            column,
            ..
        } => vec![
            operand("matrix", matrix),
            operand("row", row),
            operand("column", column),
        ],
        IRInstruction::IRVectorLength { vector, .. } => vec![operand("vector", vector)],
        IRInstruction::IRMatrixRows { matrix, .. }
        | IRInstruction::IRMatrixColumns { matrix, .. } => vec![operand("matrix", matrix)],
        IRInstruction::IRVectorSet {
            vector,
            index,
            value,
            ..
        } => vec![
            operand("vector", vector),
            operand("index", index),
            operand("value", value),
        ],
        IRInstruction::IRMatrixSet {
            matrix,
            row,
            column,
            value,
            ..
        } => vec![
            operand("matrix", matrix),
            operand("row", row),
            operand("column", column),
            operand("value", value),
        ],
        IRInstruction::IRBranch { condition, .. } => vec![operand("condition", condition)],
        IRInstruction::IRReturn { value, .. } => match value {
            Some(LifecycleSource::Value(value)) => vec![operand("value", value)],
            Some(LifecycleSource::Storage(_)) | None => Vec::new(),
        },
    }
}
