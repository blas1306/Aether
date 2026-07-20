//! Basic-block container for Aether IR instructions.

use crate::IRInstruction;

/// A named basic block containing instructions in execution order.
#[derive(Clone, Debug, PartialEq)]
pub struct IRBasicBlock {
    /// Block name used by branch and jump targets.
    pub name: String,
    /// Instructions in program order.
    pub instructions: Vec<IRInstruction>,
}

impl IRBasicBlock {
    /// Creates an empty named basic block.
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            instructions: Vec::new(),
        }
    }
}
