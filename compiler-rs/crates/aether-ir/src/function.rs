//! Function container for the Aether IR.

use crate::{IRBasicBlock, IRParameter, IRType};

/// A named function with ordered parameters and basic blocks.
#[derive(Clone, Debug, PartialEq)]
pub struct IRFunction {
    /// Function name.
    pub name: String,
    /// Parameters in declaration order.
    pub parameters: Vec<IRParameter>,
    /// Declared return type.
    pub return_type: IRType,
    /// Basic blocks in retained module order.
    pub blocks: Vec<IRBasicBlock>,
}

impl IRFunction {
    /// Creates a function without any basic blocks.
    pub fn new(name: impl Into<String>, parameters: Vec<IRParameter>, return_type: IRType) -> Self {
        Self {
            name: name.into(),
            parameters,
            return_type,
            blocks: Vec::new(),
        }
    }
}
