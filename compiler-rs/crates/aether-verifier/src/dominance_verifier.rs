//! Function-local, entry-rooted cross-block SSA dominance verification.

use std::collections::VecDeque;

use aether_ir::{IRFunction, IRModule};

use crate::FunctionStructureVerificationError;
use crate::cfg::{ENTRY_BLOCK_NAME, FunctionCfg};
use crate::dominance_error::{
    BlockDominanceError, DominanceRuleError, DominanceUseLocation, FunctionDominanceError,
    ModuleDominanceError,
};
use crate::ssa_error::SSADefinitionLocation;
use crate::ssa_verifier::{
    collect_definitions, instruction_location, ssa_operands, verify_function_ssa,
};
use crate::structure_verifier::verify_function_structure_prerequisite;
use crate::verifier::instruction_kind;

/// Verifies cross-block SSA dominance in every function, in retained order.
///
/// Each function independently invokes the narrowly required Step 3B and Step
/// 3C.1 validations first. Their typed errors are preserved as prerequisite
/// sources; the type verifier and a combined all-phases pipeline are not run.
pub fn verify_module_dominance(module: &IRModule) -> Result<(), ModuleDominanceError> {
    for (function_index, function) in module.functions.iter().enumerate() {
        verify_function_dominance(function).map_err(|source| ModuleDominanceError {
            function_index,
            function_name: function.name.clone(),
            source: Box::new(source),
        })?;
    }
    Ok(())
}

/// Runs only the dominance pass after module structure and SSA have succeeded.
pub(crate) fn verify_module_dominance_after_prerequisites(
    module: &IRModule,
) -> Result<(), ModuleDominanceError> {
    for (function_index, function) in module.functions.iter().enumerate() {
        let Ok(blocks) = crate::cfg::FunctionBlockIndex::build(function) else {
            unreachable!("module structure was verified before dominance")
        };
        verify_function_dominance_after_prerequisites(function, &blocks).map_err(|source| {
            ModuleDominanceError {
                function_index,
                function_name: function.name.clone(),
                source: Box::new(source),
            }
        })?;
    }
    Ok(())
}

/// Verifies that every cross-block instruction definition dominates its use.
///
/// Parameters are entry definitions and are therefore available in every
/// block, including unreachable blocks. Same-block ordering remains owned by
/// Step 3C.1. Matching the authoritative Python Initial IR verifier, retained
/// unreachable blocks are checked locally with every collected value
/// available; cross-block dominance is therefore only an executable-path rule.
pub fn verify_function_dominance(function: &IRFunction) -> Result<(), FunctionDominanceError> {
    let blocks = verify_function_structure_prerequisite(function).map_err(|source| {
        FunctionDominanceError::StructurePrerequisite {
            function_name: function.name.clone(),
            source: Box::new(source),
        }
    })?;
    verify_function_ssa(function).map_err(|source| FunctionDominanceError::SSAPrerequisite {
        function_name: function.name.clone(),
        source: Box::new(source),
    })?;

    verify_function_dominance_after_prerequisites(function, &blocks)
}

fn verify_function_dominance_after_prerequisites(
    function: &IRFunction,
    blocks: &crate::cfg::FunctionBlockIndex<'_>,
) -> Result<(), FunctionDominanceError> {
    let definitions = collect_definitions(function).map_err(|source| {
        FunctionDominanceError::SSAPrerequisite {
            function_name: function.name.clone(),
            source: Box::new(source),
        }
    })?;
    let Some(cfg) = FunctionCfg::from_validated(function, blocks) else {
        // The structural prerequisite above normally owns this diagnostic.
        // Retain the same typed context if an independently called analysis
        // ever observes the invariant changing underneath it.
        return Err(FunctionDominanceError::StructurePrerequisite {
            function_name: function.name.clone(),
            source: Box::new(FunctionStructureVerificationError::MissingEntryBlock {
                function_name: function.name.clone(),
                required_entry_block: ENTRY_BLOCK_NAME.to_owned(),
            }),
        });
    };
    let dominance = DominanceInfo::compute(&cfg);

    for (block_index, block) in function.blocks.iter().enumerate() {
        for (instruction_index, instruction) in block.instructions.iter().enumerate() {
            for (operand_index, operand) in ssa_operands(instruction).into_iter().enumerate() {
                let Some(definition) = definitions.get(&operand.value.name) else {
                    // Step 3C.1 succeeded, so this is unreachable without a
                    // concurrent model mutation (which Rust borrowing forbids).
                    continue;
                };
                let SSADefinitionLocation::Instruction(defining_location) = &definition.location
                else {
                    // Function parameters are defined at entry and Python makes
                    // them available even to retained unreachable blocks.
                    continue;
                };
                if defining_location.block_index == block_index {
                    // Definition-before-use within a block is Step 3C.1's rule.
                    continue;
                }
                if !dominance.is_reachable(block_index)
                    || dominance.dominates(defining_location.block_index, block_index)
                {
                    continue;
                }

                let use_instruction =
                    instruction_location(block_index, block, instruction_index, instruction);
                let use_location = DominanceUseLocation {
                    instruction: use_instruction,
                    operand_index,
                    operand_field: operand.field_name.to_owned(),
                };
                let source = DominanceRuleError::DefinitionDoesNotDominateUse {
                    ssa_identifier: operand.value.name.clone(),
                    defining_location: definition.location.clone(),
                    use_location,
                    entry_block: ENTRY_BLOCK_NAME.to_owned(),
                };
                let block_source = BlockDominanceError {
                    function_name: function.name.clone(),
                    block_index,
                    block_name: block.name.clone(),
                    instruction_index,
                    instruction_kind: instruction_kind(instruction),
                    ssa_identifier: operand.value.name.clone(),
                    source,
                };
                return Err(FunctionDominanceError::Block {
                    function_name: function.name.clone(),
                    block_index,
                    block_name: block.name.clone(),
                    source: Box::new(block_source),
                });
            }
        }
    }

    Ok(())
}

/// Immutable function-local entry reachability and dominator sets.
#[derive(Clone, Debug)]
struct DominanceInfo {
    reachable: Vec<bool>,
    dominators: Vec<Vec<bool>>,
}

impl DominanceInfo {
    fn compute(cfg: &FunctionCfg) -> Self {
        let block_count = cfg.block_count();
        let entry_index = cfg.entry_index();
        let mut reachable = vec![false; block_count];
        let mut worklist = VecDeque::from([entry_index]);
        while let Some(block_index) = worklist.pop_front() {
            if reachable[block_index] {
                continue;
            }
            reachable[block_index] = true;
            for &successor in cfg.successors(block_index) {
                if !reachable[successor] {
                    worklist.push_back(successor);
                }
            }
        }

        let mut dominators = vec![vec![false; block_count]; block_count];
        for block_index in 0..block_count {
            if block_index == entry_index || !reachable[block_index] {
                dominators[block_index][block_index] = true;
            } else {
                dominators[block_index].clone_from(&reachable);
            }
        }

        let mut changed = true;
        while changed {
            changed = false;
            for block_index in 0..block_count {
                if block_index == entry_index || !reachable[block_index] {
                    continue;
                }

                let mut new_dominators = vec![false; block_count];
                let mut reachable_predecessors = cfg
                    .predecessors(block_index)
                    .iter()
                    .copied()
                    .filter(|&predecessor| reachable[predecessor]);
                if let Some(first_predecessor) = reachable_predecessors.next() {
                    new_dominators.clone_from(&dominators[first_predecessor]);
                    for predecessor in reachable_predecessors {
                        for (is_dominator, predecessor_dominator) in
                            new_dominators.iter_mut().zip(&dominators[predecessor])
                        {
                            *is_dominator &= predecessor_dominator;
                        }
                    }
                }
                new_dominators[block_index] = true;
                if new_dominators != dominators[block_index] {
                    dominators[block_index] = new_dominators;
                    changed = true;
                }
            }
        }

        Self {
            reachable,
            dominators,
        }
    }

    fn is_reachable(&self, block_index: usize) -> bool {
        self.reachable
            .get(block_index)
            .copied()
            .is_some_and(|value| value)
    }

    fn dominates(&self, dominator: usize, block_index: usize) -> bool {
        self.dominators
            .get(block_index)
            .and_then(|set| set.get(dominator))
            .copied()
            .is_some_and(|value| value)
    }
}
