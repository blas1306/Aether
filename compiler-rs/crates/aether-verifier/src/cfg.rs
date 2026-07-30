//! Narrow shared function-local CFG structure for verifier passes.

use std::collections::HashMap;

use aether_ir::{IRFunction, IRInstruction};

pub(crate) const ENTRY_BLOCK_NAME: &str = "entry";

/// Stable duplicate information produced while indexing retained blocks.
pub(crate) struct DuplicateBlockName {
    pub(crate) block_index: usize,
    pub(crate) earlier_block_index: usize,
}

/// Exact block-name lookup retaining the validated entry index.
pub(crate) struct FunctionBlockIndex<'function> {
    by_name: HashMap<&'function str, usize>,
}

impl<'function> FunctionBlockIndex<'function> {
    pub(crate) fn build(function: &'function IRFunction) -> Result<Self, DuplicateBlockName> {
        let mut by_name = HashMap::new();
        for (block_index, block) in function.blocks.iter().enumerate() {
            if let Some(&earlier_block_index) = by_name.get(block.name.as_str()) {
                return Err(DuplicateBlockName {
                    block_index,
                    earlier_block_index,
                });
            }
            by_name.insert(block.name.as_str(), block_index);
        }
        Ok(Self { by_name })
    }

    pub(crate) fn contains(&self, block_name: &str) -> bool {
        self.by_name.contains_key(block_name)
    }

    pub(crate) fn entry_index(&self) -> Option<usize> {
        self.index_of(ENTRY_BLOCK_NAME)
    }

    fn index_of(&self, block_name: &str) -> Option<usize> {
        self.by_name.get(block_name).copied()
    }
}

/// Successor names in retained terminator-field order.
pub(crate) enum TerminatorSuccessors<'instruction> {
    None,
    Jump(&'instruction str),
    Branch {
        true_target: &'instruction str,
        false_target: &'instruction str,
    },
}

pub(crate) fn terminator_successors(instruction: &IRInstruction) -> TerminatorSuccessors<'_> {
    match instruction {
        IRInstruction::IRJump { target } => TerminatorSuccessors::Jump(target),
        IRInstruction::IRBranch {
            true_target,
            false_target,
            ..
        } => TerminatorSuccessors::Branch {
            true_target,
            false_target,
        },
        IRInstruction::IRInvoke {
            normal_target,
            exceptional_target,
            ..
        }
        | IRInstruction::IRInvokeIndirect {
            normal_target,
            exceptional_target,
            ..
        }
        | IRInstruction::IRInvokeInterface {
            normal_target,
            exceptional_target,
            ..
        } => TerminatorSuccessors::Branch {
            true_target: normal_target,
            false_target: exceptional_target,
        },
        IRInstruction::IRThrow {
            target: Some(target),
            ..
        }
        | IRInstruction::IRRethrow {
            target: Some(target),
            ..
        }
        | IRInstruction::IRPropagate {
            target: Some(target),
            ..
        } => TerminatorSuccessors::Jump(target),
        _ => TerminatorSuccessors::None,
    }
}

/// Indexed successors and predecessors for a structurally verified function.
pub(crate) struct FunctionCfg {
    entry_index: usize,
    successors: Vec<Vec<usize>>,
    predecessors: Vec<Vec<usize>>,
}

impl FunctionCfg {
    /// Resolves a CFG after the structure verifier has established final
    /// terminators, unique block names, an entry, and valid targets.
    pub(crate) fn from_validated(
        function: &IRFunction,
        blocks: &FunctionBlockIndex<'_>,
    ) -> Option<Self> {
        let entry_index = blocks.entry_index()?;
        let mut successors = vec![Vec::new(); function.blocks.len()];

        for (source_index, block) in function.blocks.iter().enumerate() {
            let terminator = block.instructions.last()?;
            match terminator_successors(terminator) {
                TerminatorSuccessors::None => {}
                TerminatorSuccessors::Jump(target) => {
                    successors[source_index].push(blocks.index_of(target)?);
                }
                TerminatorSuccessors::Branch {
                    true_target,
                    false_target,
                } => {
                    successors[source_index].push(blocks.index_of(true_target)?);
                    successors[source_index].push(blocks.index_of(false_target)?);
                }
            }
        }

        let mut predecessors = vec![Vec::new(); function.blocks.len()];
        for (source_index, targets) in successors.iter().enumerate() {
            for &target_index in targets {
                if !predecessors[target_index].contains(&source_index) {
                    predecessors[target_index].push(source_index);
                }
            }
        }

        Some(Self {
            entry_index,
            successors,
            predecessors,
        })
    }

    pub(crate) fn block_count(&self) -> usize {
        self.successors.len()
    }

    pub(crate) fn entry_index(&self) -> usize {
        self.entry_index
    }

    pub(crate) fn successors(&self, block_index: usize) -> &[usize] {
        self.successors.get(block_index).map_or(&[], Vec::as_slice)
    }

    pub(crate) fn predecessors(&self, block_index: usize) -> &[usize] {
        self.predecessors
            .get(block_index)
            .map_or(&[], Vec::as_slice)
    }
}
