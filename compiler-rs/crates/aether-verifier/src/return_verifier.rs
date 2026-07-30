//! Entry-rooted non-void all-path return verification.

use aether_ir::{IRFunction, IRInstruction, IRModule, IRType};

use crate::cfg::{ENTRY_BLOCK_NAME, FunctionCfg};
use crate::return_error::{
    FunctionReturnVerificationError, ModuleReturnVerificationError, ReturnPathRuleError,
};
use crate::structure_verifier::verify_function_structure_prerequisite;

/// Verifies IRV-024 in every retained function, in source order.
pub fn verify_module_returns(module: &IRModule) -> Result<(), ModuleReturnVerificationError> {
    for (function_index, function) in module.functions.iter().enumerate() {
        verify_function_returns(function).map_err(|source| ModuleReturnVerificationError {
            function_index,
            function_name: function.name.clone(),
            source: Box::new(source),
        })?;
    }
    Ok(())
}

/// Runs only all-path return analysis after module structure has succeeded.
pub(crate) fn verify_module_returns_after_structure(
    module: &IRModule,
) -> Result<(), ModuleReturnVerificationError> {
    for (function_index, function) in module.functions.iter().enumerate() {
        let Ok(blocks) = crate::cfg::FunctionBlockIndex::build(function) else {
            unreachable!("module structure was verified before return analysis")
        };
        verify_function_returns_after_structure(function, &blocks).map_err(|source| {
            ModuleReturnVerificationError {
                function_index,
                function_name: function.name.clone(),
                source: Box::new(source),
            }
        })?;
    }
    Ok(())
}

/// Verifies that every path from `entry` in a non-void function proves a valued return.
///
/// Step 3B structural verification is the sole prerequisite. Return operand
/// types, SSA validity, lifecycle transfer, cleanup, and unreachable blocks
/// remain owned by their independent verifier families.
pub fn verify_function_returns(
    function: &IRFunction,
) -> Result<(), FunctionReturnVerificationError> {
    let blocks = verify_function_structure_prerequisite(function).map_err(|source| {
        FunctionReturnVerificationError::StructurePrerequisite {
            function_name: function.name.clone(),
            source: Box::new(source),
        }
    })?;
    verify_function_returns_after_structure(function, &blocks)
}

fn verify_function_returns_after_structure(
    function: &IRFunction,
    blocks: &crate::cfg::FunctionBlockIndex<'_>,
) -> Result<(), FunctionReturnVerificationError> {
    if matches!(function.return_type, IRType::Void(_)) {
        return Ok(());
    }

    let Some(cfg) = FunctionCfg::from_validated(function, blocks) else {
        // The structural prerequisite owns every condition that can make CFG
        // construction fail, and immutable borrowing prevents later mutation.
        return Ok(());
    };
    find_valueless_return(function, &cfg).map_err(|source| {
        FunctionReturnVerificationError::NonVoidPathWithoutReturn {
            function_name: function.name.clone(),
            return_type: function.return_type.clone(),
            entry_block: ENTRY_BLOCK_NAME.to_owned(),
            source,
        }
    })
}

fn find_valueless_return(
    function: &IRFunction,
    cfg: &FunctionCfg,
) -> Result<(), ReturnPathRuleError> {
    let mut visited = vec![false; cfg.block_count()];
    let mut worklist = vec![cfg.entry_index()];
    visited[cfg.entry_index()] = true;

    while let Some(block_index) = worklist.pop() {
        let block = &function.blocks[block_index];
        match block
            .instructions
            .last()
            .expect("structural prerequisite guarantees a final terminator")
        {
            IRInstruction::IRReturn { value, .. } => {
                if value.is_none() {
                    return Err(ReturnPathRuleError::ValuelessReturn {
                        block_index,
                        block_name: block.name.clone(),
                        instruction_index: block.instructions.len() - 1,
                    });
                }
            }
            IRInstruction::IRJump { .. } => {
                let successor = cfg.successors(block_index)[0];
                enqueue_unvisited(successor, &mut visited, &mut worklist);
            }
            IRInstruction::IRBranch { .. } => {
                let successors = cfg.successors(block_index);
                // This is a LIFO worklist. Enqueue false before true so the
                // retained true-target field remains the first visited edge.
                enqueue_unvisited(successors[1], &mut visited, &mut worklist);
                enqueue_unvisited(successors[0], &mut visited, &mut worklist);
            }
            IRInstruction::IRInvoke { .. }
            | IRInstruction::IRInvokeIndirect { .. }
            | IRInstruction::IRInvokeInterface { .. } => {
                let successors = cfg.successors(block_index);
                enqueue_unvisited(successors[1], &mut visited, &mut worklist);
                enqueue_unvisited(successors[0], &mut visited, &mut worklist);
            }
            IRInstruction::IRThrow { target, .. }
            | IRInstruction::IRRethrow { target, .. }
            | IRInstruction::IRPropagate { target, .. } => {
                if target.is_some() {
                    let successor = cfg.successors(block_index)[0];
                    enqueue_unvisited(successor, &mut visited, &mut worklist);
                }
            }
            _ => unreachable!("structural prerequisite guarantees a control-flow terminator"),
        }
    }

    Ok(())
}

fn enqueue_unvisited(block_index: usize, visited: &mut [bool], worklist: &mut Vec<usize>) {
    if !visited[block_index] {
        visited[block_index] = true;
        worklist.push(block_index);
    }
}
