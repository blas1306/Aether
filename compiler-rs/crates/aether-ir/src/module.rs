//! Top-level Aether IR module.

use crate::{IRFunction, IRStructDefinition};

/// An owned Aether IR compilation unit.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct IRModule {
    /// Functions in retained module order.
    pub functions: Vec<IRFunction>,
    /// Nominal struct definitions in retained module order.
    pub structs: Vec<IRStructDefinition>,
}

#[cfg(test)]
mod tests {
    use crate::{IRBasicBlock, IRConstant, IRInstruction, IRType, IRValue, IntType};

    use super::*;

    #[test]
    fn owns_and_compares_complete_modules() {
        let int_type: IRType = IntType.into();
        let result = IRValue::new("0", int_type.clone());
        let mut block = IRBasicBlock::new("entry");
        block.instructions.push(IRInstruction::IRConst {
            result: result.clone(),
            value: IRConstant::Int(42),
        });
        block.instructions.push(IRInstruction::IRReturn {
            value: Some(result),
            transferred_storage: None,
        });

        let mut function = IRFunction::new("main", Vec::new(), int_type);
        function.blocks.push(block);
        let module = IRModule {
            functions: vec![function],
            structs: Vec::new(),
        };

        assert_eq!(module, module.clone());
    }
}
