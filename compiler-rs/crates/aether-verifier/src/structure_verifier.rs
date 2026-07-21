//! Function/block structure and basic control-flow verification.

use std::collections::HashMap;

use aether_ir::{IRBasicBlock, IRFunction, IRInstruction, IRModule};

use crate::cfg::{
    ENTRY_BLOCK_NAME, FunctionBlockIndex, TerminatorSuccessors, terminator_successors,
};
use crate::structure_error::{
    ActualBlockTermination, BlockStructureVerificationError, BranchTarget, ControlFlowRuleError,
    FunctionStructureVerificationError, ModuleStructureVerificationError, TerminatorExpectation,
};
use crate::verifier::instruction_kind;

/// Verifies declaration structure, block structure, and local CFG targets.
pub fn verify_module_structure(module: &IRModule) -> Result<(), ModuleStructureVerificationError> {
    verify_struct_declarations(module)?;
    verify_unique_function_names(module)?;

    for (function_index, function) in module.functions.iter().enumerate() {
        verify_function_structure(module, function).map_err(|source| {
            ModuleStructureVerificationError::Function {
                function_index,
                function_name: function.name.clone(),
                source: Box::new(source),
            }
        })?;
    }
    Ok(())
}

/// Verifies one function's declarations, blocks, terminators, and local targets.
pub fn verify_function_structure(
    _module: &IRModule,
    function: &IRFunction,
) -> Result<(), FunctionStructureVerificationError> {
    verify_function_structure_prerequisite(function).map(|_| ())
}

/// Runs the function-local portion of structural verification for passes that
/// need an unambiguous CFG but no module declarations.
pub(crate) fn verify_function_structure_prerequisite(
    function: &IRFunction,
) -> Result<FunctionBlockIndex<'_>, FunctionStructureVerificationError> {
    verify_unique_parameter_names(function)?;
    if function.blocks.is_empty() {
        return Err(FunctionStructureVerificationError::EmptyFunction {
            function_name: function.name.clone(),
        });
    }

    let blocks = FunctionBlockIndex::build(function).map_err(|duplicate| {
        FunctionStructureVerificationError::DuplicateBlockName {
            function_name: function.name.clone(),
            block_index: duplicate.block_index,
            block_name: function.blocks[duplicate.block_index].name.clone(),
            earlier_block_index: duplicate.earlier_block_index,
        }
    })?;
    if blocks.entry_index().is_none() {
        return Err(FunctionStructureVerificationError::MissingEntryBlock {
            function_name: function.name.clone(),
            required_entry_block: ENTRY_BLOCK_NAME.to_owned(),
        });
    }

    for (block_index, block) in function.blocks.iter().enumerate() {
        verify_block(function, block, &blocks).map_err(|source| {
            FunctionStructureVerificationError::Block {
                function_name: function.name.clone(),
                block_index,
                block_name: block.name.clone(),
                source: Box::new(source),
            }
        })?;
    }
    Ok(blocks)
}

fn verify_struct_declarations(module: &IRModule) -> Result<(), ModuleStructureVerificationError> {
    let mut structs = HashMap::new();
    for (struct_index, definition) in module.structs.iter().enumerate() {
        if let Some(&earlier_struct_index) = structs.get(definition.name.as_str()) {
            return Err(ModuleStructureVerificationError::DuplicateStructName {
                struct_index,
                struct_name: definition.name.clone(),
                earlier_struct_index,
            });
        }
        structs.insert(definition.name.as_str(), struct_index);
    }

    for (struct_index, definition) in module.structs.iter().enumerate() {
        if definition.name.is_empty() {
            return Err(ModuleStructureVerificationError::EmptyStructName { struct_index });
        }
        let mut fields = HashMap::new();
        for (field_index, (field_name, _)) in definition.fields.iter().enumerate() {
            if let Some(&earlier_field_index) = fields.get(field_name.as_str()) {
                return Err(ModuleStructureVerificationError::DuplicateStructFieldName {
                    struct_index,
                    struct_name: definition.name.clone(),
                    field_index,
                    field_name: field_name.clone(),
                    earlier_field_index,
                });
            }
            fields.insert(field_name.as_str(), field_index);
        }
    }
    Ok(())
}

fn verify_unique_function_names(module: &IRModule) -> Result<(), ModuleStructureVerificationError> {
    let mut functions = HashMap::new();
    for (function_index, function) in module.functions.iter().enumerate() {
        if let Some(&earlier_function_index) = functions.get(function.name.as_str()) {
            return Err(ModuleStructureVerificationError::DuplicateFunctionName {
                function_index,
                function_name: function.name.clone(),
                earlier_function_index,
            });
        }
        functions.insert(function.name.as_str(), function_index);
    }
    Ok(())
}

fn verify_unique_parameter_names(
    function: &IRFunction,
) -> Result<(), FunctionStructureVerificationError> {
    let mut parameters = HashMap::new();
    for (parameter_index, parameter) in function.parameters.iter().enumerate() {
        if let Some(&earlier_parameter_index) = parameters.get(parameter.name.as_str()) {
            return Err(FunctionStructureVerificationError::DuplicateParameterName {
                function_name: function.name.clone(),
                parameter_index,
                parameter_name: parameter.name.clone(),
                earlier_parameter_index,
            });
        }
        parameters.insert(parameter.name.as_str(), parameter_index);
    }
    Ok(())
}

fn verify_block(
    function: &IRFunction,
    block: &IRBasicBlock,
    blocks: &FunctionBlockIndex<'_>,
) -> Result<(), BlockStructureVerificationError> {
    let terminators: Vec<(usize, &IRInstruction)> = block
        .instructions
        .iter()
        .enumerate()
        .filter(|(_, instruction)| is_terminator(instruction))
        .collect();

    let Some(&(terminator_index, terminator)) = terminators.first() else {
        let actual =
            block
                .instructions
                .last()
                .map_or(ActualBlockTermination::EmptyBlock, |instruction| {
                    ActualBlockTermination::NonTerminator {
                        final_instruction_kind: instruction_kind(instruction),
                    }
                });
        return Err(block_error(
            function,
            block,
            None,
            ControlFlowRuleError::MissingTerminator {
                expected: TerminatorExpectation::OneFinalControlFlowTerminator,
                actual,
            },
        ));
    };

    if let Some(&(second_index, second)) = terminators.get(1) {
        return Err(block_error(
            function,
            block,
            Some((second_index, second)),
            ControlFlowRuleError::MultipleTerminators {
                first_index: terminator_index,
                first_kind: instruction_kind(terminator),
                second_index,
                second_kind: instruction_kind(second),
            },
        ));
    }

    if terminator_index + 1 != block.instructions.len() {
        let offending_instruction_index = terminator_index + 1;
        let offending_instruction = &block.instructions[offending_instruction_index];
        return Err(block_error(
            function,
            block,
            Some((offending_instruction_index, offending_instruction)),
            ControlFlowRuleError::InstructionAfterTerminator {
                terminator_index,
                terminator_kind: instruction_kind(terminator),
                offending_instruction_index,
                offending_instruction_kind: instruction_kind(offending_instruction),
            },
        ));
    }

    verify_targets(function, block, blocks, terminator_index, terminator)
}

fn verify_targets(
    function: &IRFunction,
    block: &IRBasicBlock,
    blocks: &FunctionBlockIndex<'_>,
    instruction_index: usize,
    terminator: &IRInstruction,
) -> Result<(), BlockStructureVerificationError> {
    match terminator_successors(terminator) {
        TerminatorSuccessors::Jump(target) if !blocks.contains(target) => Err(block_error(
            function,
            block,
            Some((instruction_index, terminator)),
            ControlFlowRuleError::UnknownJumpTarget {
                target: target.to_owned(),
            },
        )),
        TerminatorSuccessors::Branch {
            true_target,
            false_target: _,
        } if !blocks.contains(true_target) => Err(block_error(
            function,
            block,
            Some((instruction_index, terminator)),
            ControlFlowRuleError::UnknownBranchTarget {
                edge: BranchTarget::True,
                target: true_target.to_owned(),
            },
        )),
        TerminatorSuccessors::Branch {
            true_target: _,
            false_target,
        } if !blocks.contains(false_target) => Err(block_error(
            function,
            block,
            Some((instruction_index, terminator)),
            ControlFlowRuleError::UnknownBranchTarget {
                edge: BranchTarget::False,
                target: false_target.to_owned(),
            },
        )),
        _ => Ok(()),
    }
}

fn block_error(
    function: &IRFunction,
    block: &IRBasicBlock,
    instruction: Option<(usize, &IRInstruction)>,
    source: ControlFlowRuleError,
) -> BlockStructureVerificationError {
    BlockStructureVerificationError {
        function_name: function.name.clone(),
        block_name: block.name.clone(),
        instruction_index: instruction.map(|(index, _)| index),
        instruction_kind: instruction.map(|(_, instruction)| instruction_kind(instruction)),
        source,
    }
}

fn is_terminator(instruction: &IRInstruction) -> bool {
    matches!(
        instruction,
        IRInstruction::IRBranch { .. }
            | IRInstruction::IRJump { .. }
            | IRInstruction::IRReturn { .. }
    )
}
