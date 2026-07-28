//! Layered traversal, instruction-local type rules, and borrowed-element rules.

use std::collections::{HashMap, HashSet};

use aether_ir::{
    ArrayType, BoolType, ComplexType, DoubleType, FloatType, FunctionType, IRBasicBlock,
    IRConstant, IRFunction, IRInstruction, IRModule, IRStructDefinition, IRType, IRValue, IntType,
    LifecycleSource, ListType, MatrixType, StringType, StructType, VectorType, VoidType,
};

use crate::error::{
    BlockTypeVerificationError, CollectionKind, CollectionLifecycleCapability,
    FunctionTypeVerificationError, InstructionKind, InstructionTypeVerificationError,
    ModuleTypeVerificationError, TypeExpectation, TypeRuleError,
};
use crate::lifecycle_verifier::LifecycleTypeRegistry;
use crate::ssa_error::SSAInstructionLocation;
use crate::ssa_verifier::instruction_location;
use crate::{BorrowRule, BorrowRuleError};

#[derive(Clone)]
struct BorrowDefinition {
    scope: String,
    location: SSAInstructionLocation,
}

/// Verifies declarations, instruction-local types, and borrowed elements in a module.
pub fn verify_module_types(module: &IRModule) -> Result<(), ModuleTypeVerificationError> {
    let verifier = TypeVerifier::new(module);
    verifier.verify_struct_definitions()?;
    for (function_index, function) in module.functions.iter().enumerate() {
        verifier.verify_function(function).map_err(|source| {
            ModuleTypeVerificationError::Function {
                function_index,
                function_name: function.name.clone(),
                source,
            }
        })?;
    }
    Ok(())
}

/// Verifies one function using module declarations for calls, nominal types, and borrows.
pub fn verify_function_types(
    module: &IRModule,
    function: &IRFunction,
) -> Result<(), FunctionTypeVerificationError> {
    TypeVerifier::new(module).verify_function(function)
}

/// Verifies one block using its containing function and module declarations.
pub fn verify_block_types(
    module: &IRModule,
    function: &IRFunction,
    block: &IRBasicBlock,
) -> Result<(), BlockTypeVerificationError> {
    TypeVerifier::new(module).verify_block(function, block)
}

struct TypeVerifier<'module> {
    module: &'module IRModule,
    lifecycle: LifecycleTypeRegistry<'module>,
}

#[allow(clippy::unused_self)]
impl<'module> TypeVerifier<'module> {
    fn new(module: &'module IRModule) -> Self {
        Self {
            module,
            lifecycle: LifecycleTypeRegistry::new(&module.structs),
        }
    }

    fn verify_struct_definitions(&self) -> Result<(), ModuleTypeVerificationError> {
        for (struct_index, definition) in self.module.structs.iter().enumerate() {
            for (field_index, (field_name, field_type)) in definition.fields.iter().enumerate() {
                let result = if matches!(field_type, IRType::Void(_)) {
                    Err(TypeRuleError::TypeConstraint {
                        field: field_name.clone(),
                        expected: TypeExpectation::NonVoid,
                        actual: field_type.clone(),
                    })
                } else {
                    self.require_valid_type(field_name, field_type)
                };
                result.map_err(|source| ModuleTypeVerificationError::StructField {
                    struct_index,
                    struct_name: definition.name.clone(),
                    field_index,
                    field_name: field_name.clone(),
                    source,
                })?;
            }
        }

        let mut visited = HashSet::new();
        let mut active = Vec::new();
        for definition in &self.module.structs {
            self.visit_struct_layout(&definition.name, &mut visited, &mut active)
                .map_err(|source| ModuleTypeVerificationError::StructLayout { source })?;
        }
        Ok(())
    }

    fn visit_struct_layout(
        &self,
        name: &str,
        visited: &mut HashSet<String>,
        active: &mut Vec<String>,
    ) -> Result<(), TypeRuleError> {
        if visited.contains(name) {
            return Ok(());
        }
        if let Some(start) = active.iter().position(|candidate| candidate == name) {
            let mut cycle = active[start..].to_vec();
            cycle.push(name.to_owned());
            return Err(TypeRuleError::RecursiveStructLayout { cycle });
        }
        active.push(name.to_owned());
        if let Some(definition) = self.struct_definition(name) {
            for (_, field_type) in &definition.fields {
                if let IRType::Struct(struct_type) = field_type {
                    self.visit_struct_layout(&struct_type.name, visited, active)?;
                }
            }
        }
        active.pop();
        visited.insert(name.to_owned());
        Ok(())
    }

    fn verify_function(&self, function: &IRFunction) -> Result<(), FunctionTypeVerificationError> {
        for (parameter_index, parameter) in function.parameters.iter().enumerate() {
            self.require_valid_type(&parameter.name, &parameter.r#type)
                .map_err(|source| FunctionTypeVerificationError::Parameter {
                    function_name: function.name.clone(),
                    parameter_index,
                    parameter_name: parameter.name.clone(),
                    source,
                })?;
        }
        self.require_valid_type("return_type", &function.return_type)
            .map_err(|source| FunctionTypeVerificationError::ReturnType {
                function_name: function.name.clone(),
                source,
            })?;

        self.verify_borrowed_elements(function)?;

        for (block_index, block) in function.blocks.iter().enumerate() {
            self.verify_block(function, block).map_err(|source| {
                FunctionTypeVerificationError::Block {
                    function_name: function.name.clone(),
                    block_index,
                    block_name: block.name.clone(),
                    source,
                }
            })?;
        }
        Ok(())
    }

    #[allow(clippy::too_many_lines)]
    fn verify_borrowed_elements(
        &self,
        function: &IRFunction,
    ) -> Result<(), FunctionTypeVerificationError> {
        let mut borrowed = HashMap::new();
        for (block_index, block) in function.blocks.iter().enumerate() {
            for (instruction_index, instruction) in block.instructions.iter().enumerate() {
                let (result, is_borrowed, borrow_scope) = match instruction {
                    IRInstruction::IRArrayGet {
                        result,
                        borrowed,
                        borrow_scope,
                        ..
                    }
                    | IRInstruction::IRListGet {
                        result,
                        borrowed,
                        borrow_scope,
                        ..
                    } => (result, *borrowed, borrow_scope.as_deref()),
                    _ => continue,
                };
                let location =
                    instruction_location(block_index, block, instruction_index, instruction);
                if is_borrowed {
                    let Some(scope) = borrow_scope.filter(|scope| !scope.is_empty()) else {
                        return Err(borrow_function_error(
                            function,
                            block_index,
                            block,
                            instruction_index,
                            instruction,
                            BorrowRuleError::MissingBorrowScope {
                                rule: BorrowRule::Irv037,
                                borrowed_value: result.name.clone(),
                                instruction: location,
                                defining_scope: block.name.clone(),
                            },
                        ));
                    };
                    if scope != block.name {
                        return Err(borrow_function_error(
                            function,
                            block_index,
                            block,
                            instruction_index,
                            instruction,
                            BorrowRuleError::BorrowScopeMismatch {
                                rule: BorrowRule::Irv038,
                                borrowed_value: result.name.clone(),
                                instruction: location,
                                declared_scope: scope.to_owned(),
                                defining_scope: block.name.clone(),
                            },
                        ));
                    }
                    borrowed.insert(
                        result.name.clone(),
                        BorrowDefinition {
                            scope: scope.to_owned(),
                            location,
                        },
                    );
                } else if let Some(scope) = borrow_scope {
                    return Err(borrow_function_error(
                        function,
                        block_index,
                        block,
                        instruction_index,
                        instruction,
                        BorrowRuleError::OwnedGetDeclaresBorrowScope {
                            rule: BorrowRule::Irv039,
                            value: result.name.clone(),
                            instruction: location,
                            declared_scope: scope.to_owned(),
                        },
                    ));
                }
            }
        }

        if borrowed.is_empty() {
            return Ok(());
        }

        for (block_index, block) in function.blocks.iter().enumerate() {
            let mut acquired = HashSet::new();
            for (instruction_index, instruction) in block.instructions.iter().enumerate() {
                if let IRInstruction::IRCall {
                    arguments,
                    builtin: Some(builtin),
                    ..
                } = instruction
                {
                    if builtin == "__aether_retain" {
                        acquired.extend(
                            arguments
                                .iter()
                                .filter(|argument| borrowed.contains_key(&argument.name))
                                .map(|argument| argument.name.clone()),
                        );
                    }
                }

                if let IRInstruction::IRStore { value, .. } = instruction {
                    if let Some(definition) = borrowed.get(&value.name) {
                        if self.lifecycle.needs_destroy(&value.r#type)
                            && !acquired.contains(&value.name)
                        {
                            let consumer = instruction_location(
                                block_index,
                                block,
                                instruction_index,
                                instruction,
                            );
                            return Err(borrow_function_error(
                                function,
                                block_index,
                                block,
                                instruction_index,
                                instruction,
                                BorrowRuleError::BorrowedOwningStoreWithoutAcquisition {
                                    rule: BorrowRule::Irv040,
                                    borrowed_value: value.name.clone(),
                                    borrowed_type: value.r#type.clone(),
                                    borrow_scope: definition.scope.clone(),
                                    definition: definition.location.clone(),
                                    consumer,
                                },
                            ));
                        }
                    }
                }

                if let IRInstruction::IRReturn {
                    value: Some(LifecycleSource::Value(value)),
                    ..
                } = instruction
                {
                    if let Some(definition) = borrowed.get(&value.name) {
                        let consumer = instruction_location(
                            block_index,
                            block,
                            instruction_index,
                            instruction,
                        );
                        return Err(borrow_function_error(
                            function,
                            block_index,
                            block,
                            instruction_index,
                            instruction,
                            BorrowRuleError::BorrowedValueReturned {
                                rule: BorrowRule::Irv041,
                                borrowed_value: value.name.clone(),
                                borrow_scope: definition.scope.clone(),
                                definition: definition.location.clone(),
                                consumer,
                            },
                        ));
                    }
                }

                if let Some(receiver) = borrowed_mutation_receiver(instruction) {
                    if let Some(definition) = borrowed.get(&receiver.name) {
                        let consumer = instruction_location(
                            block_index,
                            block,
                            instruction_index,
                            instruction,
                        );
                        return Err(borrow_function_error(
                            function,
                            block_index,
                            block,
                            instruction_index,
                            instruction,
                            BorrowRuleError::MutationThroughBorrow {
                                rule: BorrowRule::Irv042,
                                borrowed_value: receiver.name.clone(),
                                borrow_scope: definition.scope.clone(),
                                definition: definition.location.clone(),
                                consumer,
                                consumer_kind: instruction_kind(instruction),
                            },
                        ));
                    }
                }
            }
        }

        Ok(())
    }

    fn verify_block(
        &self,
        function: &IRFunction,
        block: &IRBasicBlock,
    ) -> Result<(), BlockTypeVerificationError> {
        for (instruction_index, instruction) in block.instructions.iter().enumerate() {
            let instruction_kind = instruction_kind(instruction);
            self.verify_instruction(function, instruction)
                .map_err(|source| BlockTypeVerificationError {
                    function_name: function.name.clone(),
                    block_name: block.name.clone(),
                    instruction_index,
                    instruction_kind,
                    source: InstructionTypeVerificationError {
                        instruction_kind,
                        source,
                    },
                })?;
        }
        Ok(())
    }

    #[allow(clippy::too_many_lines)]
    fn verify_instruction(
        &self,
        function: &IRFunction,
        instruction: &IRInstruction,
    ) -> Result<(), TypeRuleError> {
        self.verify_operand_types(instruction)?;
        if let Some(result) = instruction_result(instruction) {
            self.require_valid_type("result", &result.r#type)?;
        }

        match instruction {
            IRInstruction::IRConst { result, value } => self.verify_const(result, value),
            IRInstruction::IRLoad { result, slot } => {
                self.require_exact("result", &slot.r#type, &result.r#type)
            }
            IRInstruction::IRStore { slot, value } => {
                self.require_exact("value", &slot.r#type, &value.r#type)
            }
            // Lifecycle validity, including lifecycle operand compatibility, is
            // intentionally owned by the later lifecycle verifier pass.
            IRInstruction::IRInitDefault { .. }
            | IRInstruction::IRCopyInit { .. }
            | IRInstruction::IRMoveInit { .. }
            | IRInstruction::IRAssign { .. }
            | IRInstruction::IRDestroy { .. }
            | IRInstruction::IRRelocate { .. }
            // CFG and terminator validation are deferred.
            | IRInstruction::IRJump { .. } => Ok(()),
            IRInstruction::IRBinaryOp {
                result,
                operator,
                left,
                right,
                ..
            } => self.verify_binary(result, operator, left, right),
            IRInstruction::IRUnaryOp {
                result,
                operator,
                operand,
            } => self.verify_unary(result, operator, operand),
            IRInstruction::IRCompareOp {
                result,
                operator,
                left,
                right,
                aggregate_shape,
            } => self.verify_compare(result, operator, left, right, aggregate_shape.as_deref()),
            IRInstruction::IRCast { result, value } => self.verify_cast(result, value),
            IRInstruction::IRCall {
                function: callee,
                arguments,
                result,
                builtin,
                ..
            } => self.verify_call(callee, arguments, result.as_ref(), builtin.as_deref()),
            IRInstruction::IRFunctionRef { result, function } => {
                self.verify_function_ref(result, function)
            }
            IRInstruction::IRCallIndirect {
                callee,
                arguments,
                result,
            } => self.verify_indirect_call(callee, arguments, result.as_ref()),
            IRInstruction::IRPrint {
                value,
                aggregate_shape,
                ..
            } => {
                if !is_printable(&value.r#type) {
                    return Err(constraint(
                        "value",
                        TypeExpectation::Printable,
                        &value.r#type,
                    ));
                }
                match &value.r#type {
                    IRType::Vector(_) => self.require_aggregate_shape(
                        "aggregate_shape",
                        aggregate_shape.as_deref(),
                        1,
                        false,
                    ),
                    IRType::Matrix(_) => self.require_aggregate_shape(
                        "aggregate_shape",
                        aggregate_shape.as_deref(),
                        2,
                        false,
                    ),
                    _ => self.require_no_aggregate_shape(
                        "aggregate_shape",
                        aggregate_shape.as_deref(),
                    ),
                }
            }
            IRInstruction::IRStructNew { result, fields } => self.verify_struct_new(result, fields),
            IRInstruction::IRClassNew { result } => {
                if matches!(result.r#type, IRType::ClassRef(_)) {
                    Ok(())
                } else {
                    Err(constraint(
                        "result",
                        TypeExpectation::ClassReference,
                        &result.r#type,
                    ))
                }
            }
            IRInstruction::IRClassGet {
                result,
                object,
                field_index,
                field_name,
            } => self.verify_class_get(result, object, *field_index, field_name),
            IRInstruction::IRClassSet {
                object,
                field_index,
                field_name,
                value,
                ..
            } => self.verify_class_set(object, *field_index, field_name, value),
            IRInstruction::IRStructGet {
                result,
                r#struct,
                field_index,
                ..
            } => self.verify_struct_get(result, r#struct, *field_index),
            IRInstruction::IRStructSet {
                result,
                r#struct,
                field_index,
                value,
                ..
            } => self.verify_struct_set(result, r#struct, *field_index, value),
            IRInstruction::IRMethodResultNew {
                result,
                receiver,
                value,
            } => self.verify_method_result_new(result, receiver, value.as_ref()),
            IRInstruction::IRMethodResultReceiver {
                result,
                method_result,
            } => self.verify_method_result_receiver(result, method_result),
            IRInstruction::IRMethodResultValue {
                result,
                method_result,
            } => self.verify_method_result_value(result, method_result),
            IRInstruction::IRArrayNew { result, elements } => {
                self.verify_collection_new(result, elements, true)
            }
            IRInstruction::IRListNew { result, elements } => {
                self.verify_collection_new(result, elements, false)
            }
            IRInstruction::IRArrayCopy { result, array, .. } => {
                let array_type = self.expect_array("array", &array.r#type)?;
                self.require_exact("result", &array.r#type, &result.r#type)?;
                self.require_collection_lifecycle(
                    InstructionKind::IRArrayCopy,
                    CollectionKind::Array,
                    &array_type.element,
                )
            }
            IRInstruction::IRListCopy {
                result, list_value, ..
            } => {
                let list_type = self.expect_list("list_value", &list_value.r#type)?;
                self.require_exact("result", &list_value.r#type, &result.r#type)?;
                self.require_collection_lifecycle(
                    InstructionKind::IRListCopy,
                    CollectionKind::List,
                    &list_type.element,
                )
            }
            IRInstruction::IRListContains {
                result,
                list_value,
                value,
            } => self.verify_list_search(result, list_value, value, true),
            IRInstruction::IRListIndexOf {
                result,
                list_value,
                value,
            } => self.verify_list_search(result, list_value, value, false),
            IRInstruction::IRListClear { list_value }
            | IRInstruction::IRListReverse { list_value } => self
                .expect_list("list_value", &list_value.r#type)
                .map(|_| ()),
            IRInstruction::IRListPush { list_value, value } => {
                let list = self.expect_list("list_value", &list_value.r#type)?;
                self.require_exact("value", &list.element, &value.r#type)
            }
            IRInstruction::IRListInsert {
                list_value,
                index,
                value,
            } => {
                let list = self.expect_list("list_value", &list_value.r#type)?;
                self.expect_int("index", &index.r#type)?;
                self.require_exact("value", &list.element, &value.r#type)
            }
            IRInstruction::IRListRemoveAt {
                result,
                list_value,
                index,
            } => {
                let list = self.expect_list("list_value", &list_value.r#type)?;
                self.expect_int("index", &index.r#type)?;
                self.require_exact("result", &list.element, &result.r#type)
            }
            IRInstruction::IRListPop { result, list_value } => {
                let list = self.expect_list("list_value", &list_value.r#type)?;
                self.require_exact("result", &list.element, &result.r#type)
            }
            IRInstruction::IRSequenceSort { sequence } => {
                let element = match &sequence.r#type {
                    IRType::Array(array) => &array.element,
                    IRType::List(list) => &list.element,
                    actual => {
                        return Err(constraint("sequence", TypeExpectation::Sequence, actual));
                    }
                };
                if matches!(
                    element.as_ref(),
                    IRType::Int(_) | IRType::Double(_) | IRType::String(_)
                ) {
                    Ok(())
                } else {
                    Err(constraint(
                        "sequence.element",
                        TypeExpectation::OneOf(vec![
                            IntType.into(),
                            DoubleType.into(),
                            StringType.into(),
                        ]),
                        element,
                    ))
                }
            }
            IRInstruction::IRVectorNew {
                result,
                elements,
                orientation,
            } => self.verify_vector_new(result, elements, orientation.as_deref()),
            IRInstruction::IRMatrixNew {
                result,
                elements,
                rows,
                cols,
            } => self.verify_matrix_new(result, elements, *rows, *cols),
            IRInstruction::IRVectorAdd {
                result,
                left,
                right,
                length,
                orientation,
            }
            | IRInstruction::IRVectorSub {
                result,
                left,
                right,
                length,
                orientation,
            } => self.verify_vector_binary(
                result,
                left,
                right,
                *length,
                orientation.as_deref(),
            ),
            IRInstruction::IRVectorScale {
                result,
                vector,
                scalar,
                length,
                orientation,
            } => self.verify_vector_scale(
                result,
                vector,
                scalar,
                *length,
                orientation.as_deref(),
            ),
            IRInstruction::IRVectorDot {
                result,
                left,
                right,
                length,
            } => self.verify_vector_dot(result, left, right, *length),
            IRInstruction::IROuterProduct {
                result,
                column,
                row,
                rows,
                cols,
            } => self.verify_outer_product(result, column, row, *rows, *cols),
            IRInstruction::IRMatrixAdd {
                result,
                left,
                right,
                rows,
                cols,
            }
            | IRInstruction::IRMatrixSub {
                result,
                left,
                right,
                rows,
                cols,
            } => self.verify_matrix_binary(result, left, right, *rows, *cols),
            IRInstruction::IRMatrixScale {
                result,
                matrix,
                scalar,
                rows,
                cols,
            } => self.verify_matrix_scale(result, matrix, scalar, *rows, *cols),
            IRInstruction::IRMatrixMatMul {
                result,
                left,
                right,
                rows,
                inner,
                cols,
            } => self.verify_matrix_matmul(result, left, right, *rows, *inner, *cols),
            IRInstruction::IRMatrixVectorMul {
                result,
                matrix,
                vector,
                rows,
                inner,
            } => self.verify_matrix_vector_mul(result, matrix, vector, *rows, *inner),
            IRInstruction::IRVectorMatrixMul {
                result,
                vector,
                matrix,
                rows,
                cols,
            } => self.verify_vector_matrix_mul(result, vector, matrix, *rows, *cols),
            IRInstruction::IRArrayGet {
                result,
                array,
                index,
                ..
            } => self.verify_indexed_get(result, array, index, true),
            IRInstruction::IRArraySlice {
                result,
                array,
                start,
                end,
                ..
            } => self.verify_slice(result, array, start, end, true),
            IRInstruction::IRListSlice {
                result,
                list_value,
                start,
                end,
                ..
            } => {
                self.verify_slice(result, list_value, start, end, false)?;
                let list_type = self.expect_list("list_value", &list_value.r#type)?;
                self.require_collection_lifecycle(
                    InstructionKind::IRListSlice,
                    CollectionKind::List,
                    &list_type.element,
                )
            }
            IRInstruction::IRListGet {
                result,
                list_value,
                index,
                ..
            } => self.verify_indexed_get(result, list_value, index, false),
            IRInstruction::IRVectorGet {
                result,
                vector,
                index,
            } => self.verify_vector_get(result, vector, index),
            IRInstruction::IRMatrixGet {
                result,
                matrix,
                row,
                column,
                cols,
            } => self.verify_matrix_get(result, matrix, row, column, *cols),
            IRInstruction::IRVectorLength { result, vector } => {
                self.expect_vector("vector", &vector.r#type)?;
                self.expect_int("result", &result.r#type)
            }
            IRInstruction::IRMatrixRows {
                result,
                matrix,
                rows,
            } => {
                self.expect_matrix("matrix", &matrix.r#type)?;
                self.require_positive_matrix_dimensions(&["rows"], &[*rows])?;
                self.expect_int("result", &result.r#type)
            }
            IRInstruction::IRMatrixColumns {
                result,
                matrix,
                columns,
            } => {
                self.expect_matrix("matrix", &matrix.r#type)?;
                self.require_positive_matrix_dimensions(&["columns"], &[*columns])?;
                self.expect_int("result", &result.r#type)
            }
            IRInstruction::IRArraySet {
                array,
                index,
                value,
            } => self.verify_indexed_set(array, index, value, true),
            IRInstruction::IRListSet {
                list_value,
                index,
                value,
            } => self.verify_indexed_set(list_value, index, value, false),
            IRInstruction::IRVectorSet {
                vector,
                index,
                value,
            } => self.verify_vector_set(vector, index, value),
            IRInstruction::IRMatrixSet {
                matrix,
                row,
                column,
                value,
                cols,
            } => self.verify_matrix_set(matrix, row, column, value, *cols),
            IRInstruction::IRArrayLength { result, array } => {
                self.expect_array("array", &array.r#type)?;
                self.expect_int("result", &result.r#type)
            }
            IRInstruction::IRListLength { result, list_value } => {
                self.expect_list("list_value", &list_value.r#type)?;
                self.expect_int("result", &result.r#type)
            }
            IRInstruction::IRListIsEmpty { result, list_value } => {
                self.expect_list("list_value", &list_value.r#type)?;
                self.expect_bool("result", &result.r#type)
            }
            IRInstruction::IRBranch { condition, .. } => {
                self.expect_bool("condition", &condition.r#type)
            }
            IRInstruction::IRReturn { value, .. } => match value {
                Some(LifecycleSource::Value(value)) => {
                    self.require_exact("value", &function.return_type, &value.r#type)
                }
                Some(LifecycleSource::Storage(storage)) => {
                    Err(TypeRuleError::StorageReturnOperand {
                        storage: storage.name.clone(),
                    })
                }
                None if matches!(function.return_type, IRType::Void(_)) => Ok(()),
                None => self.require_exact("value", &function.return_type, &VoidType.into()),
            },
        }
    }

    #[allow(clippy::too_many_lines)]
    fn verify_operand_types(&self, instruction: &IRInstruction) -> Result<(), TypeRuleError> {
        let values: Vec<(&str, &IRValue)> = match instruction {
            IRInstruction::IRConst { .. }
            | IRInstruction::IRInitDefault { .. }
            | IRInstruction::IRCopyInit { .. }
            | IRInstruction::IRMoveInit { .. }
            | IRInstruction::IRAssign { .. }
            | IRInstruction::IRDestroy { .. }
            | IRInstruction::IRRelocate { .. }
            | IRInstruction::IRFunctionRef { .. }
            | IRInstruction::IRClassNew { .. }
            | IRInstruction::IRJump { .. } => Vec::new(),
            IRInstruction::IRBranch { condition, .. } => vec![("condition", condition)],
            IRInstruction::IRLoad { slot, .. } => vec![("slot", slot)],
            IRInstruction::IRStore { slot, value } => {
                vec![("slot", slot), ("value", value)]
            }
            IRInstruction::IRBinaryOp { left, right, .. }
            | IRInstruction::IRCompareOp { left, right, .. }
            | IRInstruction::IRVectorAdd { left, right, .. }
            | IRInstruction::IRVectorSub { left, right, .. }
            | IRInstruction::IRVectorDot { left, right, .. }
            | IRInstruction::IRMatrixAdd { left, right, .. }
            | IRInstruction::IRMatrixSub { left, right, .. }
            | IRInstruction::IRMatrixMatMul { left, right, .. } => {
                vec![("left", left), ("right", right)]
            }
            IRInstruction::IRUnaryOp { operand, .. } => vec![("operand", operand)],
            IRInstruction::IRCast { value, .. } | IRInstruction::IRPrint { value, .. } => {
                vec![("value", value)]
            }
            IRInstruction::IRCall { arguments, .. } => arguments
                .iter()
                .map(|argument| ("arguments", argument))
                .collect(),
            IRInstruction::IRCallIndirect {
                callee, arguments, ..
            } => std::iter::once(("callee", callee))
                .chain(arguments.iter().map(|argument| ("arguments", argument)))
                .collect(),
            IRInstruction::IRStructNew { fields, .. } => {
                fields.iter().map(|field| ("fields", field)).collect()
            }
            IRInstruction::IRStructGet { r#struct, .. } => vec![("struct", r#struct)],
            IRInstruction::IRClassGet { object, .. } => vec![("object", object)],
            IRInstruction::IRClassSet { object, value, .. } => {
                vec![("object", object), ("value", value)]
            }
            IRInstruction::IRStructSet {
                r#struct, value, ..
            } => vec![("struct", r#struct), ("value", value)],
            IRInstruction::IRMethodResultNew {
                receiver, value, ..
            } => std::iter::once(("receiver", receiver))
                .chain(value.iter().map(|value| ("value", value)))
                .collect(),
            IRInstruction::IRMethodResultReceiver { method_result, .. }
            | IRInstruction::IRMethodResultValue { method_result, .. } => {
                vec![("method_result", method_result)]
            }
            IRInstruction::IRArrayNew { elements, .. }
            | IRInstruction::IRListNew { elements, .. }
            | IRInstruction::IRVectorNew { elements, .. }
            | IRInstruction::IRMatrixNew { elements, .. } => elements
                .iter()
                .map(|element| ("elements", element))
                .collect(),
            IRInstruction::IRArrayCopy { array, .. }
            | IRInstruction::IRArrayLength { array, .. } => vec![("array", array)],
            IRInstruction::IRListCopy { list_value, .. }
            | IRInstruction::IRListClear { list_value }
            | IRInstruction::IRListPop { list_value, .. }
            | IRInstruction::IRListReverse { list_value }
            | IRInstruction::IRListLength { list_value, .. }
            | IRInstruction::IRListIsEmpty { list_value, .. } => {
                vec![("list_value", list_value)]
            }
            IRInstruction::IRListPush { list_value, value } => {
                vec![("list_value", list_value), ("value", value)]
            }
            IRInstruction::IRListContains {
                list_value, value, ..
            }
            | IRInstruction::IRListIndexOf {
                list_value, value, ..
            } => vec![("list_value", list_value), ("value", value)],
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
                ("list_value", list_value),
                ("index", index),
                ("value", value),
            ],
            IRInstruction::IRListRemoveAt {
                list_value, index, ..
            }
            | IRInstruction::IRListGet {
                list_value, index, ..
            } => vec![("list_value", list_value), ("index", index)],
            IRInstruction::IRSequenceSort { sequence } => vec![("sequence", sequence)],
            IRInstruction::IRVectorScale { vector, scalar, .. } => {
                vec![("vector", vector), ("scalar", scalar)]
            }
            IRInstruction::IROuterProduct { column, row, .. } => {
                vec![("column", column), ("row", row)]
            }
            IRInstruction::IRMatrixScale { matrix, scalar, .. } => {
                vec![("matrix", matrix), ("scalar", scalar)]
            }
            IRInstruction::IRMatrixVectorMul { matrix, vector, .. } => {
                vec![("matrix", matrix), ("vector", vector)]
            }
            IRInstruction::IRVectorMatrixMul { vector, matrix, .. } => {
                vec![("vector", vector), ("matrix", matrix)]
            }
            IRInstruction::IRArrayGet { array, index, .. } => {
                vec![("array", array), ("index", index)]
            }
            IRInstruction::IRArraySet {
                array,
                index,
                value,
            } => vec![("array", array), ("index", index), ("value", value)],
            IRInstruction::IRArraySlice {
                array, start, end, ..
            } => vec![("array", array), ("start", start), ("end", end)],
            IRInstruction::IRListSlice {
                list_value,
                start,
                end,
                ..
            } => vec![("list_value", list_value), ("start", start), ("end", end)],
            IRInstruction::IRVectorGet { vector, index, .. } => {
                vec![("vector", vector), ("index", index)]
            }
            IRInstruction::IRMatrixGet {
                matrix,
                row,
                column,
                ..
            } => vec![("matrix", matrix), ("row", row), ("column", column)],
            IRInstruction::IRVectorLength { vector, .. } => vec![("vector", vector)],
            IRInstruction::IRMatrixRows { matrix, .. }
            | IRInstruction::IRMatrixColumns { matrix, .. } => vec![("matrix", matrix)],
            IRInstruction::IRVectorSet {
                vector,
                index,
                value,
            } => vec![("vector", vector), ("index", index), ("value", value)],
            IRInstruction::IRMatrixSet {
                matrix,
                row,
                column,
                value,
                ..
            } => vec![
                ("matrix", matrix),
                ("row", row),
                ("column", column),
                ("value", value),
            ],
            IRInstruction::IRReturn { value, .. } => match value {
                Some(LifecycleSource::Value(value)) => vec![("value", value)],
                Some(LifecycleSource::Storage(storage)) => {
                    self.require_valid_type("value", &storage.r#type)?;
                    Vec::new()
                }
                None => Vec::new(),
            },
        };
        for (field, value) in values {
            self.require_valid_type(field, &value.r#type)?;
        }
        Ok(())
    }

    fn verify_const(&self, result: &IRValue, value: &IRConstant) -> Result<(), TypeRuleError> {
        match value {
            IRConstant::Null => {
                if matches!(result.r#type, IRType::Nullable(_)) {
                    Ok(())
                } else {
                    Err(constraint(
                        "result",
                        TypeExpectation::Nullable,
                        &result.r#type,
                    ))
                }
            }
            IRConstant::Bool(_) => self.expect_bool("result", &result.r#type),
            IRConstant::Int(_) => self.expect_int("result", &result.r#type),
            IRConstant::Float(_) => {
                if matches!(result.r#type, IRType::Float(_) | IRType::Double(_)) {
                    Ok(())
                } else {
                    Err(constraint(
                        "result",
                        TypeExpectation::OneOf(vec![FloatType.into(), DoubleType.into()]),
                        &result.r#type,
                    ))
                }
            }
            IRConstant::Complex { .. } => {
                self.require_exact("result", &IRType::from(ComplexType), &result.r#type)
            }
            IRConstant::String(_) => {
                self.require_exact("result", &IRType::from(StringType), &result.r#type)
            }
            IRConstant::Enum(value) => {
                let IRType::Enum(result_type) = &result.r#type else {
                    return Err(constraint("result", TypeExpectation::Enum, &result.r#type));
                };
                if value.enum_name != result_type.name {
                    return Err(TypeRuleError::InvalidEnumConstant {
                        field: "value.enum_name".to_owned(),
                        expected: result_type.name.clone(),
                        actual: value.enum_name.clone(),
                    });
                }
                let Ok(member_index) = usize::try_from(value.member_id) else {
                    return Err(TypeRuleError::InvalidEnumConstant {
                        field: "value.member_id".to_owned(),
                        expected: format!("0..{}", result_type.variants.len()),
                        actual: value.member_id.to_string(),
                    });
                };
                let Some(member_name) = result_type.variants.get(member_index) else {
                    return Err(TypeRuleError::InvalidEnumConstant {
                        field: "value.member_id".to_owned(),
                        expected: format!("0..{}", result_type.variants.len()),
                        actual: value.member_id.to_string(),
                    });
                };
                if &value.member_name != member_name {
                    return Err(TypeRuleError::InvalidEnumConstant {
                        field: "value.member_name".to_owned(),
                        expected: member_name.clone(),
                        actual: value.member_name.clone(),
                    });
                }
                if value.discriminant != value.member_id {
                    return Err(TypeRuleError::InvalidEnumConstant {
                        field: "value.discriminant".to_owned(),
                        expected: value.member_id.to_string(),
                        actual: value.discriminant.to_string(),
                    });
                }
                Ok(())
            }
        }
    }

    fn verify_binary(
        &self,
        result: &IRValue,
        operator: &str,
        left: &IRValue,
        right: &IRValue,
    ) -> Result<(), TypeRuleError> {
        let expected = if operator == "add"
            && matches!(left.r#type, IRType::String(_))
            && matches!(right.r#type, IRType::String(_))
        {
            StringType.into()
        } else if matches!(
            operator,
            "add" | "sub" | "mul" | "div" | "rem" | "mod" | "pow"
        ) {
            if !is_numeric(&left.r#type) {
                return Err(constraint("left", TypeExpectation::Numeric, &left.r#type));
            }
            if !is_numeric(&right.r#type) {
                return Err(constraint("right", TypeExpectation::Numeric, &right.r#type));
            }
            if matches!(operator, "rem" | "mod") {
                if !is_real(&left.r#type) {
                    return Err(constraint("left", TypeExpectation::Real, &left.r#type));
                }
                if !is_real(&right.r#type) {
                    return Err(constraint("right", TypeExpectation::Real, &right.r#type));
                }
            }
            self.require_exact("right", &left.r#type, &right.r#type)?;
            if operator == "div" && matches!(left.r#type, IRType::Int(_)) {
                DoubleType.into()
            } else {
                left.r#type.clone()
            }
        } else if matches!(operator, "eq" | "ne") {
            self.require_exact("right", &left.r#type, &right.r#type)?;
            BoolType.into()
        } else if matches!(operator, "lt" | "le" | "gt" | "ge") {
            if !is_real(&left.r#type) {
                return Err(constraint("left", TypeExpectation::Real, &left.r#type));
            }
            if !is_real(&right.r#type) {
                return Err(constraint("right", TypeExpectation::Real, &right.r#type));
            }
            BoolType.into()
        } else if matches!(operator, "and" | "or") {
            self.expect_bool("left", &left.r#type)?;
            self.expect_bool("right", &right.r#type)?;
            BoolType.into()
        } else {
            return Err(TypeRuleError::UnsupportedOperator {
                field: "operator".to_owned(),
                operator: operator.to_owned(),
            });
        };
        self.require_exact("result", &expected, &result.r#type)
    }

    fn verify_unary(
        &self,
        result: &IRValue,
        operator: &str,
        operand: &IRValue,
    ) -> Result<(), TypeRuleError> {
        if operator == "neg" {
            if !matches!(operand.r#type, IRType::Float(_) | IRType::Double(_)) {
                return Err(constraint(
                    "operand",
                    TypeExpectation::OneOf(vec![FloatType.into(), DoubleType.into()]),
                    &operand.r#type,
                ));
            }
            return self.require_exact("result", &operand.r#type, &result.r#type);
        }
        // Python reports every unsupported unary spelling through its `not`
        // validation path; preserve that acceptance boundary.
        if operator != "not" {
            return Err(TypeRuleError::UnsupportedOperator {
                field: "operator".to_owned(),
                operator: operator.to_owned(),
            });
        }
        self.expect_bool("operand", &operand.r#type)?;
        self.expect_bool("result", &result.r#type)
    }

    fn verify_compare(
        &self,
        result: &IRValue,
        operator: &str,
        left: &IRValue,
        right: &IRValue,
        aggregate_shape: Option<&[i64]>,
    ) -> Result<(), TypeRuleError> {
        if matches!(left.r#type, IRType::Vector(_) | IRType::Matrix(_)) {
            if !matches!(operator, "eq" | "ne") {
                return Err(TypeRuleError::UnsupportedOperator {
                    field: "operator".to_owned(),
                    operator: operator.to_owned(),
                });
            }
            self.require_exact("right", &left.r#type, &right.r#type)?;
            let expected_rank = if matches!(left.r#type, IRType::Vector(_)) {
                1
            } else {
                2
            };
            self.require_aggregate_shape("aggregate_shape", aggregate_shape, expected_rank, true)?;
            let element = match &left.r#type {
                IRType::Vector(vector) => &vector.element,
                IRType::Matrix(matrix) => &matrix.element,
                _ => unreachable!(),
            };
            if !matches!(
                element.as_ref(),
                IRType::Int(_) | IRType::Double(_) | IRType::Bool(_) | IRType::String(_)
            ) {
                return Err(constraint(
                    "left.element",
                    TypeExpectation::OneOf(vec![
                        IntType.into(),
                        DoubleType.into(),
                        BoolType.into(),
                        StringType.into(),
                    ]),
                    element,
                ));
            }
        } else {
            self.require_no_aggregate_shape("aggregate_shape", aggregate_shape)?;
            if matches!(operator, "lt" | "le" | "gt" | "ge") {
                if !matches!(left.r#type, IRType::Int(_) | IRType::Double(_)) {
                    return Err(constraint(
                        "left",
                        TypeExpectation::OneOf(vec![IntType.into(), DoubleType.into()]),
                        &left.r#type,
                    ));
                }
                self.require_exact("right", &left.r#type, &right.r#type)?;
            } else if matches!(operator, "eq" | "ne") {
                self.require_exact("right", &left.r#type, &right.r#type)?;
                if !self.is_equality_capable(&left.r#type, &mut HashSet::new()) {
                    return Err(constraint(
                        "left",
                        TypeExpectation::EqualityCapable,
                        &left.r#type,
                    ));
                }
            } else {
                return Err(TypeRuleError::UnsupportedOperator {
                    field: "operator".to_owned(),
                    operator: operator.to_owned(),
                });
            }
        }
        self.expect_bool("result", &result.r#type)
    }

    fn verify_cast(&self, result: &IRValue, value: &IRValue) -> Result<(), TypeRuleError> {
        let source = &value.r#type;
        let target = &result.r#type;
        let nullable_legal = if let IRType::Nullable(target_nullable) = target {
            let source_inner = match source {
                IRType::Nullable(source_nullable) => source_nullable.inner.as_ref(),
                _ => source,
            };
            source_inner == target_nullable.inner.as_ref()
                || matches!(source_inner, IRType::Int(_))
                    && matches!(
                        target_nullable.inner.as_ref(),
                        IRType::Float(_) | IRType::Double(_)
                    )
        } else {
            false
        };
        let legal = nullable_legal
            || source == target && is_real(source)
            || matches!(source, IRType::Int(_))
                && matches!(target, IRType::Float(_) | IRType::Double(_))
            || matches!(source, IRType::Float(_) | IRType::Double(_))
                && is_real(target)
                && source != target;
        if legal {
            Ok(())
        } else {
            Err(TypeRuleError::TypeConstraint {
                field: "value -> result".to_owned(),
                expected: TypeExpectation::OneOf(vec![
                    IntType.into(),
                    FloatType.into(),
                    DoubleType.into(),
                ]),
                actual: source.clone(),
            })
        }
    }

    fn verify_function_ref(&self, result: &IRValue, function: &str) -> Result<(), TypeRuleError> {
        let callee = self
            .function(function)
            .ok_or_else(|| TypeRuleError::UnknownFunction {
                function: function.to_owned(),
            })?;
        let expected = FunctionType {
            parameter_types: callee
                .parameters
                .iter()
                .map(|parameter| parameter.r#type.clone())
                .collect(),
            return_type: Box::new(callee.return_type.clone()),
        }
        .into();
        self.require_exact("result", &expected, &result.r#type)
    }

    fn verify_indirect_call(
        &self,
        callee: &IRValue,
        arguments: &[IRValue],
        result: Option<&IRValue>,
    ) -> Result<(), TypeRuleError> {
        let IRType::Function(signature) = &callee.r#type else {
            return Err(constraint(
                "callee",
                TypeExpectation::Function,
                &callee.r#type,
            ));
        };
        self.require_count(
            "arguments",
            signature.parameter_types.len(),
            arguments.len(),
        )?;
        for (index, (argument, expected)) in
            arguments.iter().zip(&signature.parameter_types).enumerate()
        {
            self.require_exact(&format!("arguments[{index}]"), expected, &argument.r#type)?;
        }
        self.verify_call_result(result, &signature.return_type)
    }

    fn verify_call(
        &self,
        function: &str,
        arguments: &[IRValue],
        result: Option<&IRValue>,
        builtin: Option<&str>,
    ) -> Result<(), TypeRuleError> {
        let Some(builtin) = builtin else {
            let callee = self
                .function(function)
                .ok_or_else(|| TypeRuleError::UnknownFunction {
                    function: function.to_owned(),
                })?;
            self.require_count("arguments", callee.parameters.len(), arguments.len())?;
            for (index, (argument, parameter)) in
                arguments.iter().zip(&callee.parameters).enumerate()
            {
                self.require_exact(
                    &format!("arguments[{index}]"),
                    &parameter.r#type,
                    &argument.r#type,
                )?;
            }
            return self.verify_call_result(result, &callee.return_type);
        };

        self.require_builtin_identity(function, builtin)?;

        if matches!(builtin, "__aether_retain" | "__aether_release") {
            return self.verify_retain_release_builtin(arguments, result, builtin);
        }

        match builtin {
            "System.args" => {
                self.verify_signature(arguments, result, &[], &array_of(StringType.into()))
            }
            "__aether_range_step_nonzero" => {
                self.verify_signature(arguments, result, &[IntType.into()], &VoidType.into())
            }
            "__aether_string_byte_length" => {
                self.verify_signature(arguments, result, &[StringType.into()], &IntType.into())
            }
            "__aether_string_trim" => {
                self.verify_signature(arguments, result, &[StringType.into()], &StringType.into())
            }
            "__aether_string_split" => self.verify_signature(
                arguments,
                result,
                &[StringType.into(), StringType.into()],
                &array_of(StringType.into()),
            ),
            "parseInt" => {
                self.verify_parse_builtin(arguments, result, "IntParseResult", &IntType.into())
            }
            "parseDouble" => self.verify_parse_builtin(
                arguments,
                result,
                "DoubleParseResult",
                &DoubleType.into(),
            ),
            "io.readText" => self.verify_read_text(arguments, result),
            "io.writeText" | "io.writeTextAtomic" | "io.appendText" => {
                self.verify_write_text(arguments, result)
            }
            "text.byteAt" => self.verify_signature(
                arguments,
                result,
                &[StringType.into(), IntType.into()],
                &IntType.into(),
            ),
            "text.byteSlice" => self.verify_signature(
                arguments,
                result,
                &[StringType.into(), IntType.into(), IntType.into()],
                &StringType.into(),
            ),
            "text.formatInt" => {
                self.verify_signature(arguments, result, &[IntType.into()], &StringType.into())
            }
            "text.formatDouble" => {
                self.verify_signature(arguments, result, &[DoubleType.into()], &StringType.into())
            }
            "text.concatFragments" => self.verify_signature(
                arguments,
                result,
                &[list_of(StringType.into())],
                &StringType.into(),
            ),
            name => {
                let expected_result = scalar_math_result_type(name, arguments)?;
                self.verify_call_result(result, &expected_result)
            }
        }
    }

    fn require_builtin_identity(&self, function: &str, builtin: &str) -> Result<(), TypeRuleError> {
        if function == builtin {
            Ok(())
        } else {
            Err(TypeRuleError::InvalidBuiltinIdentity {
                builtin: builtin.to_owned(),
                expected: builtin.to_owned(),
                actual: function.to_owned(),
            })
        }
    }

    fn verify_retain_release_builtin(
        &self,
        arguments: &[IRValue],
        result: Option<&IRValue>,
        builtin: &str,
    ) -> Result<(), TypeRuleError> {
        if arguments.len() != 1 || result.is_some() {
            return Err(TypeRuleError::InvalidRetainReleaseSignature {
                builtin: builtin.to_owned(),
                expected_arguments: 1,
                actual_arguments: arguments.len(),
                actual_result: result.map(|value| value.r#type.clone()),
            });
        }

        let argument_type = &arguments[0].r#type;
        if matches!(
            argument_type,
            IRType::String(_)
                | IRType::Struct(_)
                | IRType::MethodResult(_)
                | IRType::Array(_)
                | IRType::List(_)
                | IRType::Nullable(_)
                | IRType::ClassRef(_)
        ) {
            Ok(())
        } else {
            Err(TypeRuleError::InvalidRetainReleaseType {
                builtin: builtin.to_owned(),
                actual: argument_type.clone(),
            })
        }
    }

    fn verify_signature(
        &self,
        arguments: &[IRValue],
        result: Option<&IRValue>,
        expected_arguments: &[IRType],
        expected_result: &IRType,
    ) -> Result<(), TypeRuleError> {
        self.require_count("arguments", expected_arguments.len(), arguments.len())?;
        for (index, (argument, expected)) in arguments.iter().zip(expected_arguments).enumerate() {
            self.require_exact(&format!("arguments[{index}]"), expected, &argument.r#type)?;
        }
        self.verify_call_result(result, expected_result)
    }

    fn verify_call_result(
        &self,
        result: Option<&IRValue>,
        expected: &IRType,
    ) -> Result<(), TypeRuleError> {
        if matches!(expected, IRType::Void(_)) {
            return match result {
                Some(result) => Err(TypeRuleError::UnexpectedResult {
                    field: "result".to_owned(),
                    actual: result.r#type.clone(),
                }),
                None => Ok(()),
            };
        }
        let result = result.ok_or_else(|| TypeRuleError::MissingResult {
            field: "result".to_owned(),
            expected: expected.clone(),
        })?;
        self.require_exact("result", expected, &result.r#type)
    }

    fn verify_parse_builtin(
        &self,
        arguments: &[IRValue],
        result: Option<&IRValue>,
        struct_name: &str,
        value_type: &IRType,
    ) -> Result<(), TypeRuleError> {
        self.verify_signature(
            arguments,
            result,
            &[StringType.into()],
            &StructType {
                name: struct_name.to_owned(),
            }
            .into(),
        )?;
        let definition =
            self.struct_definition(struct_name)
                .ok_or_else(|| TypeRuleError::UnknownStruct {
                    field: "result".to_owned(),
                    struct_name: struct_name.to_owned(),
                })?;
        self.require_count("result.fields", 2, definition.fields.len())?;
        self.require_exact("result.fields[0]", value_type, &definition.fields[0].1)?;
        if definition.fields[0].0 != "value" {
            return Err(TypeRuleError::MetadataMismatch {
                field: "result.fields[0].name".to_owned(),
                expected: "value".to_owned(),
                actual: definition.fields[0].0.clone(),
            });
        }
        if definition.fields[1].0 != "status" {
            return Err(TypeRuleError::MetadataMismatch {
                field: "result.fields[1].name".to_owned(),
                expected: "status".to_owned(),
                actual: definition.fields[1].0.clone(),
            });
        }
        if !matches!(definition.fields[1].1, IRType::Enum(_)) {
            return Err(constraint(
                "result.fields[1]",
                TypeExpectation::Enum,
                &definition.fields[1].1,
            ));
        }
        Ok(())
    }

    fn verify_read_text(
        &self,
        arguments: &[IRValue],
        result: Option<&IRValue>,
    ) -> Result<(), TypeRuleError> {
        self.verify_signature(
            arguments,
            result,
            &[StringType.into()],
            &StructType {
                name: "FileReadResult".to_owned(),
            }
            .into(),
        )?;
        let definition = self.struct_definition("FileReadResult").ok_or_else(|| {
            TypeRuleError::UnknownStruct {
                field: "result".to_owned(),
                struct_name: "FileReadResult".to_owned(),
            }
        })?;
        self.require_count("result.fields", 2, definition.fields.len())?;
        self.require_exact(
            "result.fields[0]",
            &StringType.into(),
            &definition.fields[0].1,
        )?;
        if definition.fields[0].0 != "content" || definition.fields[1].0 != "status" {
            return Err(TypeRuleError::MetadataMismatch {
                field: "result.fields".to_owned(),
                expected: "content, status".to_owned(),
                actual: definition
                    .fields
                    .iter()
                    .map(|(name, _)| name.as_str())
                    .collect::<Vec<_>>()
                    .join(", "),
            });
        }
        match &definition.fields[1].1 {
            IRType::Enum(enum_type) if enum_type.name == "FileStatus" => Ok(()),
            actual => Err(TypeRuleError::TypeConstraint {
                field: "result.fields[1]".to_owned(),
                expected: TypeExpectation::Enum,
                actual: actual.clone(),
            }),
        }
    }

    fn verify_write_text(
        &self,
        arguments: &[IRValue],
        result: Option<&IRValue>,
    ) -> Result<(), TypeRuleError> {
        self.require_count("arguments", 2, arguments.len())?;
        for (index, argument) in arguments.iter().enumerate() {
            self.require_exact(
                &format!("arguments[{index}]"),
                &StringType.into(),
                &argument.r#type,
            )?;
        }
        let result = result.ok_or_else(|| TypeRuleError::MissingResult {
            field: "result".to_owned(),
            expected: IRType::Enum(aether_ir::EnumType {
                name: "FileStatus".to_owned(),
                variants: Vec::new(),
                display_name: None,
            }),
        })?;
        match &result.r#type {
            IRType::Enum(enum_type) if enum_type.name == "FileStatus" => Ok(()),
            actual => Err(constraint("result", TypeExpectation::Enum, actual)),
        }
    }

    fn verify_struct_new(&self, result: &IRValue, fields: &[IRValue]) -> Result<(), TypeRuleError> {
        let definition = self.struct_for_type("result", &result.r#type)?;
        self.require_count("fields", definition.fields.len(), fields.len())?;
        for (index, (value, (_, expected))) in fields.iter().zip(&definition.fields).enumerate() {
            self.require_exact(&format!("fields[{index}]"), expected, &value.r#type)?;
        }
        Ok(())
    }

    fn verify_struct_get(
        &self,
        result: &IRValue,
        struct_value: &IRValue,
        field_index: i64,
    ) -> Result<(), TypeRuleError> {
        let definition = self.struct_for_type("struct", &struct_value.r#type)?;
        let field = struct_field(definition, field_index)?;
        self.require_exact("result", &field.1, &result.r#type)
    }

    fn verify_class_get(
        &self,
        result: &IRValue,
        object: &IRValue,
        field_index: i64,
        field_name: &str,
    ) -> Result<(), TypeRuleError> {
        let IRType::ClassRef(class_type) = &object.r#type else {
            return Err(constraint(
                "object",
                TypeExpectation::ClassReference,
                &object.r#type,
            ));
        };
        let definition = self.struct_definition(&class_type.name).ok_or_else(|| {
            TypeRuleError::UnknownStruct {
                field: "object".to_owned(),
                struct_name: class_type.name.clone(),
            }
        })?;
        let field = struct_field(definition, field_index)?;
        self.require_class_field_name(field_name, field)?;
        self.require_exact("result", &field.1, &result.r#type)
    }

    fn verify_class_set(
        &self,
        object: &IRValue,
        field_index: i64,
        field_name: &str,
        value: &IRValue,
    ) -> Result<(), TypeRuleError> {
        let IRType::ClassRef(class_type) = &object.r#type else {
            return Err(constraint(
                "object",
                TypeExpectation::ClassReference,
                &object.r#type,
            ));
        };
        let definition = self.struct_definition(&class_type.name).ok_or_else(|| {
            TypeRuleError::UnknownStruct {
                field: "object".to_owned(),
                struct_name: class_type.name.clone(),
            }
        })?;
        let field = struct_field(definition, field_index)?;
        self.require_class_field_name(field_name, field)?;
        self.require_exact("value", &field.1, &value.r#type)
    }

    fn require_class_field_name(
        &self,
        field_name: &str,
        field: &(String, IRType),
    ) -> Result<(), TypeRuleError> {
        if field_name == field.0 {
            return Ok(());
        }
        Err(TypeRuleError::MetadataMismatch {
            field: "field_name".to_owned(),
            expected: field.0.clone(),
            actual: field_name.to_owned(),
        })
    }

    fn verify_struct_set(
        &self,
        result: &IRValue,
        struct_value: &IRValue,
        field_index: i64,
        value: &IRValue,
    ) -> Result<(), TypeRuleError> {
        let definition = self.struct_for_type("struct", &struct_value.r#type)?;
        let field = struct_field(definition, field_index)?;
        self.require_exact("value", &field.1, &value.r#type)?;
        self.require_exact("result", &struct_value.r#type, &result.r#type)
    }

    fn verify_method_result_new(
        &self,
        result: &IRValue,
        receiver: &IRValue,
        value: Option<&IRValue>,
    ) -> Result<(), TypeRuleError> {
        let IRType::MethodResult(method_result) = &result.r#type else {
            return Err(constraint(
                "result",
                TypeExpectation::MethodResult,
                &result.r#type,
            ));
        };
        self.require_exact(
            "receiver",
            &IRType::Struct(method_result.receiver.clone()),
            &receiver.r#type,
        )?;
        if matches!(method_result.value.as_ref(), IRType::Void(_)) {
            return match value {
                Some(value) => Err(TypeRuleError::UnexpectedResult {
                    field: "value".to_owned(),
                    actual: value.r#type.clone(),
                }),
                None => Ok(()),
            };
        }
        let value = value.ok_or_else(|| TypeRuleError::MissingResult {
            field: "value".to_owned(),
            expected: method_result.value.as_ref().clone(),
        })?;
        self.require_exact("value", &method_result.value, &value.r#type)
    }

    fn verify_method_result_receiver(
        &self,
        result: &IRValue,
        method_result: &IRValue,
    ) -> Result<(), TypeRuleError> {
        let IRType::MethodResult(type_) = &method_result.r#type else {
            return Err(constraint(
                "method_result",
                TypeExpectation::MethodResult,
                &method_result.r#type,
            ));
        };
        self.require_exact(
            "result",
            &IRType::Struct(type_.receiver.clone()),
            &result.r#type,
        )
    }

    fn verify_method_result_value(
        &self,
        result: &IRValue,
        method_result: &IRValue,
    ) -> Result<(), TypeRuleError> {
        let IRType::MethodResult(type_) = &method_result.r#type else {
            return Err(constraint(
                "method_result",
                TypeExpectation::MethodResult,
                &method_result.r#type,
            ));
        };
        self.require_exact("result", &type_.value, &result.r#type)
    }

    fn verify_collection_new(
        &self,
        result: &IRValue,
        elements: &[IRValue],
        array: bool,
    ) -> Result<(), TypeRuleError> {
        let element_type = if array {
            &self.expect_array("result", &result.r#type)?.element
        } else {
            &self.expect_list("result", &result.r#type)?.element
        };
        for (index, element) in elements.iter().enumerate() {
            self.require_exact(&format!("elements[{index}]"), element_type, &element.r#type)?;
        }
        Ok(())
    }

    fn verify_list_search(
        &self,
        result: &IRValue,
        list_value: &IRValue,
        value: &IRValue,
        contains: bool,
    ) -> Result<(), TypeRuleError> {
        let list = self.expect_list("list_value", &list_value.r#type)?;
        self.require_exact("value", &list.element, &value.r#type)?;
        if !self.is_equality_capable(&value.r#type, &mut HashSet::new()) {
            return Err(constraint(
                "value",
                TypeExpectation::EqualityCapable,
                &value.r#type,
            ));
        }
        if contains {
            self.expect_bool("result", &result.r#type)
        } else {
            self.expect_int("result", &result.r#type)
        }
    }

    fn verify_vector_new(
        &self,
        result: &IRValue,
        elements: &[IRValue],
        orientation: Option<&str>,
    ) -> Result<(), TypeRuleError> {
        let vector = self.expect_vector("result", &result.r#type)?;
        require_orientation("result.orientation", vector.orientation.as_deref())?;
        require_orientation("orientation", orientation)?;
        if orientation != vector.orientation.as_deref() {
            return Err(metadata(
                "orientation",
                orientation_text(vector.orientation.as_deref()),
                orientation_text(orientation),
            ));
        }
        for (index, element) in elements.iter().enumerate() {
            self.require_exact(
                &format!("elements[{index}]"),
                &vector.element,
                &element.r#type,
            )?;
        }
        Ok(())
    }

    fn verify_matrix_new(
        &self,
        result: &IRValue,
        elements: &[IRValue],
        rows: i64,
        columns: i64,
    ) -> Result<(), TypeRuleError> {
        let matrix = self.expect_matrix("result", &result.r#type)?;
        self.require_positive_matrix_dimensions(&["rows", "cols"], &[rows, columns])?;
        let expected = i128::from(rows) * i128::from(columns);
        if i128::try_from(elements.len()).ok() != Some(expected) {
            return Err(TypeRuleError::InvalidMatrixCardinality {
                rows,
                columns,
                expected,
                actual: elements.len(),
            });
        }
        for (index, element) in elements.iter().enumerate() {
            self.require_exact(
                &format!("elements[{index}]"),
                &matrix.element,
                &element.r#type,
            )?;
        }
        Ok(())
    }

    fn verify_vector_binary(
        &self,
        result: &IRValue,
        left: &IRValue,
        right: &IRValue,
        length: i64,
        orientation: Option<&str>,
    ) -> Result<(), TypeRuleError> {
        let result_type = self.expect_vector("result", &result.r#type)?;
        let left_type = self.expect_vector("left", &left.r#type)?;
        let right_type = self.expect_vector("right", &right.r#type)?;
        self.require_positive_vector_length("length", length)?;
        if left_type.orientation != right_type.orientation {
            return Err(metadata(
                "right.orientation",
                orientation_text(left_type.orientation.as_deref()),
                orientation_text(right_type.orientation.as_deref()),
            ));
        }
        if orientation != result_type.orientation.as_deref() {
            return Err(metadata(
                "orientation",
                orientation_text(result_type.orientation.as_deref()),
                orientation_text(orientation),
            ));
        }
        self.require_exact("result", &left.r#type, &result.r#type)?;
        self.require_exact("right", &left.r#type, &right.r#type)
    }

    fn verify_vector_scale(
        &self,
        result: &IRValue,
        vector: &IRValue,
        scalar: &IRValue,
        length: i64,
        orientation: Option<&str>,
    ) -> Result<(), TypeRuleError> {
        let result_type = self.expect_vector("result", &result.r#type)?;
        let vector_type = self.expect_vector("vector", &vector.r#type)?;
        self.require_positive_vector_length("length", length)?;
        if orientation != result_type.orientation.as_deref() {
            return Err(metadata(
                "orientation",
                orientation_text(result_type.orientation.as_deref()),
                orientation_text(orientation),
            ));
        }
        self.require_exact("result", &vector.r#type, &result.r#type)?;
        self.require_exact("scalar", &vector_type.element, &scalar.r#type)
    }

    fn verify_vector_dot(
        &self,
        result: &IRValue,
        left: &IRValue,
        right: &IRValue,
        length: i64,
    ) -> Result<(), TypeRuleError> {
        let left_type = self.expect_vector("left", &left.r#type)?;
        let right_type = self.expect_vector("right", &right.r#type)?;
        require_exact_orientation("left.orientation", left_type.orientation.as_deref(), "row")?;
        require_exact_orientation(
            "right.orientation",
            right_type.orientation.as_deref(),
            "column",
        )?;
        self.require_positive_vector_length("length", length)?;
        let expected = numeric_result_type(&left_type.element, &right_type.element)?;
        self.require_exact("result", &expected, &result.r#type)
    }

    fn verify_outer_product(
        &self,
        result: &IRValue,
        column: &IRValue,
        row: &IRValue,
        rows: i64,
        columns: i64,
    ) -> Result<(), TypeRuleError> {
        let result_type = self.expect_matrix("result", &result.r#type)?;
        let column_type = self.expect_vector("column", &column.r#type)?;
        let row_type = self.expect_vector("row", &row.r#type)?;
        require_exact_orientation(
            "column.orientation",
            column_type.orientation.as_deref(),
            "column",
        )?;
        require_exact_orientation("row.orientation", row_type.orientation.as_deref(), "row")?;
        self.require_positive_matrix_dimensions(&["rows", "cols"], &[rows, columns])?;
        let expected = numeric_result_type(&column_type.element, &row_type.element)?;
        self.require_exact("result.element", &expected, &result_type.element)
    }

    fn verify_matrix_binary(
        &self,
        result: &IRValue,
        left: &IRValue,
        right: &IRValue,
        rows: i64,
        columns: i64,
    ) -> Result<(), TypeRuleError> {
        self.expect_matrix("result", &result.r#type)?;
        self.expect_matrix("left", &left.r#type)?;
        self.expect_matrix("right", &right.r#type)?;
        self.require_positive_matrix_dimensions(&["rows", "cols"], &[rows, columns])?;
        self.require_exact("result", &left.r#type, &result.r#type)?;
        self.require_exact("right", &left.r#type, &right.r#type)
    }

    fn verify_matrix_scale(
        &self,
        result: &IRValue,
        matrix: &IRValue,
        scalar: &IRValue,
        rows: i64,
        columns: i64,
    ) -> Result<(), TypeRuleError> {
        self.expect_matrix("result", &result.r#type)?;
        let matrix_type = self.expect_matrix("matrix", &matrix.r#type)?;
        self.require_positive_matrix_dimensions(&["rows", "cols"], &[rows, columns])?;
        self.require_exact("result", &matrix.r#type, &result.r#type)?;
        self.require_exact("scalar", &matrix_type.element, &scalar.r#type)
    }

    fn verify_matrix_matmul(
        &self,
        result: &IRValue,
        left: &IRValue,
        right: &IRValue,
        rows: i64,
        inner: i64,
        columns: i64,
    ) -> Result<(), TypeRuleError> {
        let result_type = self.expect_matrix("result", &result.r#type)?;
        let left_type = self.expect_matrix("left", &left.r#type)?;
        let right_type = self.expect_matrix("right", &right.r#type)?;
        self.require_positive_matrix_dimensions(
            &["rows", "inner", "cols"],
            &[rows, inner, columns],
        )?;
        let expected = numeric_result_type(&left_type.element, &right_type.element)?;
        self.require_exact("result.element", &expected, &result_type.element)
    }

    fn verify_matrix_vector_mul(
        &self,
        result: &IRValue,
        matrix: &IRValue,
        vector: &IRValue,
        rows: i64,
        inner: i64,
    ) -> Result<(), TypeRuleError> {
        let result_type = self.expect_vector("result", &result.r#type)?;
        let matrix_type = self.expect_matrix("matrix", &matrix.r#type)?;
        let vector_type = self.expect_vector("vector", &vector.r#type)?;
        require_exact_orientation(
            "result.orientation",
            result_type.orientation.as_deref(),
            "column",
        )?;
        require_exact_orientation(
            "vector.orientation",
            vector_type.orientation.as_deref(),
            "column",
        )?;
        self.require_positive_matrix_dimensions(&["rows", "inner"], &[rows, inner])?;
        let expected = numeric_result_type(&matrix_type.element, &vector_type.element)?;
        self.require_exact("result.element", &expected, &result_type.element)
    }

    fn verify_vector_matrix_mul(
        &self,
        result: &IRValue,
        vector: &IRValue,
        matrix: &IRValue,
        rows: i64,
        columns: i64,
    ) -> Result<(), TypeRuleError> {
        let result_type = self.expect_vector("result", &result.r#type)?;
        let vector_type = self.expect_vector("vector", &vector.r#type)?;
        let matrix_type = self.expect_matrix("matrix", &matrix.r#type)?;
        require_exact_orientation(
            "result.orientation",
            result_type.orientation.as_deref(),
            "row",
        )?;
        require_exact_orientation(
            "vector.orientation",
            vector_type.orientation.as_deref(),
            "row",
        )?;
        self.require_positive_matrix_dimensions(&["rows", "cols"], &[rows, columns])?;
        let expected = numeric_result_type(&vector_type.element, &matrix_type.element)?;
        self.require_exact("result.element", &expected, &result_type.element)
    }

    fn verify_indexed_get(
        &self,
        result: &IRValue,
        collection: &IRValue,
        index: &IRValue,
        array: bool,
    ) -> Result<(), TypeRuleError> {
        let element = if array {
            &self.expect_array("array", &collection.r#type)?.element
        } else {
            &self.expect_list("list_value", &collection.r#type)?.element
        };
        self.expect_int("index", &index.r#type)?;
        self.require_exact("result", element, &result.r#type)
    }

    fn verify_slice(
        &self,
        result: &IRValue,
        collection: &IRValue,
        start: &IRValue,
        end: &IRValue,
        array: bool,
    ) -> Result<(), TypeRuleError> {
        if array {
            self.expect_array("array", &collection.r#type)?;
        } else {
            self.expect_list("list_value", &collection.r#type)?;
        }
        self.expect_int("start", &start.r#type)?;
        self.expect_int("end", &end.r#type)?;
        self.require_exact("result", &collection.r#type, &result.r#type)
    }

    fn require_collection_lifecycle(
        &self,
        instruction: InstructionKind,
        collection_kind: CollectionKind,
        element_type: &IRType,
    ) -> Result<(), TypeRuleError> {
        match self.lifecycle.collection_unsupported_reason(element_type) {
            Some(reason) => Err(TypeRuleError::MissingCollectionLifecycleCapability {
                instruction,
                collection_kind,
                element_type: element_type.clone(),
                capability: CollectionLifecycleCapability::Lifecycle,
                reason,
            }),
            None => Ok(()),
        }
    }

    fn verify_indexed_set(
        &self,
        collection: &IRValue,
        index: &IRValue,
        value: &IRValue,
        array: bool,
    ) -> Result<(), TypeRuleError> {
        let element = if array {
            &self.expect_array("array", &collection.r#type)?.element
        } else {
            &self.expect_list("list_value", &collection.r#type)?.element
        };
        self.expect_int("index", &index.r#type)?;
        self.require_exact("value", element, &value.r#type)
    }

    fn verify_vector_get(
        &self,
        result: &IRValue,
        vector: &IRValue,
        index: &IRValue,
    ) -> Result<(), TypeRuleError> {
        let vector = self.expect_vector("vector", &vector.r#type)?;
        self.expect_int("index", &index.r#type)?;
        self.require_exact("result", &vector.element, &result.r#type)
    }

    fn verify_matrix_get(
        &self,
        result: &IRValue,
        matrix: &IRValue,
        row: &IRValue,
        column: &IRValue,
        columns: i64,
    ) -> Result<(), TypeRuleError> {
        let matrix = self.expect_matrix("matrix", &matrix.r#type)?;
        self.expect_int("row", &row.r#type)?;
        self.expect_int("column", &column.r#type)?;
        self.require_positive_matrix_dimensions(&["cols"], &[columns])?;
        self.require_exact("result", &matrix.element, &result.r#type)
    }

    fn verify_vector_set(
        &self,
        vector: &IRValue,
        index: &IRValue,
        value: &IRValue,
    ) -> Result<(), TypeRuleError> {
        let vector = self.expect_vector("vector", &vector.r#type)?;
        self.expect_int("index", &index.r#type)?;
        self.require_exact("value", &vector.element, &value.r#type)
    }

    fn verify_matrix_set(
        &self,
        matrix: &IRValue,
        row: &IRValue,
        column: &IRValue,
        value: &IRValue,
        columns: i64,
    ) -> Result<(), TypeRuleError> {
        let matrix = self.expect_matrix("matrix", &matrix.r#type)?;
        self.expect_int("row", &row.r#type)?;
        self.expect_int("column", &column.r#type)?;
        self.require_positive_matrix_dimensions(&["cols"], &[columns])?;
        self.require_exact("value", &matrix.element, &value.r#type)
    }

    fn struct_for_type<'a>(
        &'a self,
        field: &str,
        type_: &IRType,
    ) -> Result<&'a IRStructDefinition, TypeRuleError> {
        let IRType::Struct(struct_type) = type_ else {
            return Err(constraint(field, TypeExpectation::Struct, type_));
        };
        self.struct_definition(&struct_type.name)
            .ok_or_else(|| TypeRuleError::UnknownStruct {
                field: field.to_owned(),
                struct_name: struct_type.name.clone(),
            })
    }

    fn struct_definition(&self, name: &str) -> Option<&IRStructDefinition> {
        // Python's module dictionary retains the last duplicate definition.
        // Duplicate-name rejection belongs to the later definition pass.
        self.module
            .structs
            .iter()
            .rev()
            .find(|definition| definition.name == name)
    }

    fn function(&self, name: &str) -> Option<&IRFunction> {
        // Match Python dictionary construction while leaving duplicate-name
        // validation to its explicitly deferred pass.
        self.module
            .functions
            .iter()
            .rev()
            .find(|function| function.name == name)
    }

    fn require_valid_type(&self, field: &str, type_: &IRType) -> Result<(), TypeRuleError> {
        if self.is_valid_type(type_) {
            Ok(())
        } else {
            Err(constraint(field, TypeExpectation::Valid, type_))
        }
    }

    fn is_valid_type(&self, type_: &IRType) -> bool {
        match type_ {
            IRType::Enum(enum_type) => {
                !enum_type.name.is_empty()
                    && !enum_type.variants.is_empty()
                    && enum_type.variants.iter().collect::<HashSet<_>>().len()
                        == enum_type.variants.len()
            }
            IRType::Struct(struct_type) => self.struct_definition(&struct_type.name).is_some(),
            IRType::Nullable(nullable) => {
                !matches!(
                    nullable.inner.as_ref(),
                    IRType::Nullable(_) | IRType::Void(_)
                ) && self.is_valid_type(&nullable.inner)
            }
            IRType::List(list) => self.is_valid_type(&list.element),
            IRType::Array(array) => self.is_valid_type(&array.element),
            IRType::Vector(vector) => self.is_valid_type(&vector.element),
            IRType::Matrix(matrix) => self.is_valid_type(&matrix.element),
            IRType::MethodResult(result) => {
                self.is_valid_type(&IRType::Struct(result.receiver.clone()))
                    && self.is_valid_type(&result.value)
            }
            // The Python verifier deliberately does not recursively validate
            // FunctionType signatures and accepts nominal class/interface
            // spellings as-is.
            IRType::Int(_)
            | IRType::Float(_)
            | IRType::Double(_)
            | IRType::Bool(_)
            | IRType::String(_)
            | IRType::Void(_)
            | IRType::Function(_)
            | IRType::Complex(_)
            | IRType::ClassRef(_)
            | IRType::Interface(_) => true,
        }
    }

    fn is_equality_capable(&self, type_: &IRType, visiting: &mut HashSet<String>) -> bool {
        match type_ {
            IRType::Int(_)
            | IRType::Float(_)
            | IRType::Double(_)
            | IRType::Bool(_)
            | IRType::String(_)
            | IRType::Enum(_)
            | IRType::ClassRef(_) => true,
            IRType::Array(array) => self.is_equality_capable(&array.element, visiting),
            IRType::List(list) => self.is_equality_capable(&list.element, visiting),
            IRType::Vector(vector) => self.is_equality_capable(&vector.element, visiting),
            IRType::Matrix(matrix) => self.is_equality_capable(&matrix.element, visiting),
            IRType::Nullable(nullable) => self.is_equality_capable(&nullable.inner, visiting),
            IRType::Struct(struct_type) => {
                let Some(definition) = self.struct_definition(&struct_type.name) else {
                    return false;
                };
                if !visiting.insert(struct_type.name.clone()) {
                    return true;
                }
                let result = definition
                    .fields
                    .iter()
                    .all(|(_, field_type)| self.is_equality_capable(field_type, visiting));
                visiting.remove(&struct_type.name);
                result
            }
            _ => false,
        }
    }

    fn expect_array<'a>(
        &self,
        field: &str,
        actual: &'a IRType,
    ) -> Result<&'a ArrayType, TypeRuleError> {
        match actual {
            IRType::Array(type_) => Ok(type_),
            _ => Err(constraint(field, TypeExpectation::Array, actual)),
        }
    }

    fn expect_list<'a>(
        &self,
        field: &str,
        actual: &'a IRType,
    ) -> Result<&'a ListType, TypeRuleError> {
        match actual {
            IRType::List(type_) => Ok(type_),
            _ => Err(constraint(field, TypeExpectation::List, actual)),
        }
    }

    fn expect_vector<'a>(
        &self,
        field: &str,
        actual: &'a IRType,
    ) -> Result<&'a VectorType, TypeRuleError> {
        match actual {
            IRType::Vector(type_) => Ok(type_),
            _ => Err(constraint(field, TypeExpectation::Vector, actual)),
        }
    }

    fn expect_matrix<'a>(
        &self,
        field: &str,
        actual: &'a IRType,
    ) -> Result<&'a MatrixType, TypeRuleError> {
        match actual {
            IRType::Matrix(type_) => Ok(type_),
            _ => Err(constraint(field, TypeExpectation::Matrix, actual)),
        }
    }

    fn expect_int(&self, field: &str, actual: &IRType) -> Result<(), TypeRuleError> {
        self.require_exact(field, &IntType.into(), actual)
    }

    fn expect_bool(&self, field: &str, actual: &IRType) -> Result<(), TypeRuleError> {
        self.require_exact(field, &BoolType.into(), actual)
    }

    fn require_aggregate_shape(
        &self,
        field: &str,
        actual: Option<&[i64]>,
        expected_rank: usize,
        requires_positive_dimensions: bool,
    ) -> Result<(), TypeRuleError> {
        let valid = actual.is_some_and(|shape| {
            shape.len() == expected_rank
                && (!requires_positive_dimensions || shape.iter().all(|dimension| *dimension > 0))
        });
        if valid {
            Ok(())
        } else {
            Err(TypeRuleError::InvalidAggregateShape {
                field: field.to_owned(),
                expected_rank,
                requires_positive_dimensions,
                actual: actual.map(<[i64]>::to_vec),
            })
        }
    }

    fn require_no_aggregate_shape(
        &self,
        field: &str,
        actual: Option<&[i64]>,
    ) -> Result<(), TypeRuleError> {
        if actual.is_none() {
            Ok(())
        } else {
            Err(TypeRuleError::InvalidAggregateShape {
                field: field.to_owned(),
                expected_rank: 0,
                requires_positive_dimensions: false,
                actual: actual.map(<[i64]>::to_vec),
            })
        }
    }

    fn require_positive_vector_length(
        &self,
        field: &str,
        actual: i64,
    ) -> Result<(), TypeRuleError> {
        if actual > 0 {
            Ok(())
        } else {
            Err(TypeRuleError::InvalidVectorLength {
                field: field.to_owned(),
                actual,
            })
        }
    }

    fn require_positive_matrix_dimensions(
        &self,
        fields: &[&str],
        actual: &[i64],
    ) -> Result<(), TypeRuleError> {
        debug_assert_eq!(fields.len(), actual.len());
        if actual.iter().all(|dimension| *dimension > 0) {
            Ok(())
        } else {
            Err(TypeRuleError::InvalidMatrixDimensions {
                fields: fields.iter().map(|field| (*field).to_owned()).collect(),
                actual: actual.to_vec(),
            })
        }
    }

    fn require_exact(
        &self,
        field: &str,
        expected: &IRType,
        actual: &IRType,
    ) -> Result<(), TypeRuleError> {
        if actual == expected {
            Ok(())
        } else {
            Err(TypeRuleError::TypeMismatch {
                field: field.to_owned(),
                expected: expected.clone(),
                actual: actual.clone(),
            })
        }
    }

    fn require_count(
        &self,
        field: &str,
        expected: usize,
        actual: usize,
    ) -> Result<(), TypeRuleError> {
        if actual == expected {
            Ok(())
        } else {
            Err(TypeRuleError::CountMismatch {
                field: field.to_owned(),
                expected,
                actual,
            })
        }
    }
}

fn borrow_function_error(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    source: BorrowRuleError,
) -> FunctionTypeVerificationError {
    let instruction_kind = instruction_kind(instruction);
    FunctionTypeVerificationError::Block {
        function_name: function.name.clone(),
        block_index,
        block_name: block.name.clone(),
        source: BlockTypeVerificationError {
            function_name: function.name.clone(),
            block_name: block.name.clone(),
            instruction_index,
            instruction_kind,
            source: InstructionTypeVerificationError {
                instruction_kind,
                source: TypeRuleError::BorrowViolation { source },
            },
        },
    }
}

fn borrowed_mutation_receiver(instruction: &IRInstruction) -> Option<&IRValue> {
    match instruction {
        IRInstruction::IRArraySet { array, .. } => Some(array),
        IRInstruction::IRListSet { list_value, .. }
        | IRInstruction::IRListPush { list_value, .. }
        | IRInstruction::IRListInsert { list_value, .. }
        | IRInstruction::IRListRemoveAt { list_value, .. }
        | IRInstruction::IRListPop { list_value, .. }
        | IRInstruction::IRListClear { list_value }
        | IRInstruction::IRListReverse { list_value } => Some(list_value),
        IRInstruction::IRSequenceSort { sequence } => Some(sequence),
        IRInstruction::IRStructSet { r#struct, .. } => Some(r#struct),
        _ => None,
    }
}

fn scalar_math_result_type(name: &str, arguments: &[IRValue]) -> Result<IRType, TypeRuleError> {
    let types = arguments
        .iter()
        .map(|argument| &argument.r#type)
        .collect::<Vec<_>>();
    match name {
        "sin" | "cos" | "tan" | "exp" | "ln" | "log" | "sqrt" => {
            require_builtin_arity(name, 1, types.len())?;
            if !is_real(types[0]) {
                return Err(constraint("arguments[0]", TypeExpectation::Real, types[0]));
            }
            Ok(DoubleType.into())
        }
        "abs" => {
            require_builtin_arity(name, 1, types.len())?;
            if !is_numeric(types[0]) {
                return Err(constraint(
                    "arguments[0]",
                    TypeExpectation::Numeric,
                    types[0],
                ));
            }
            if matches!(types[0], IRType::Complex(_)) {
                Ok(DoubleType.into())
            } else {
                Ok(types[0].clone())
            }
        }
        "Math.floor" | "Math.ceil" => {
            require_builtin_arity(name, 1, types.len())?;
            if !is_real(types[0]) {
                return Err(constraint("arguments[0]", TypeExpectation::Real, types[0]));
            }
            Ok(IntType.into())
        }
        "Math.factorial" => {
            require_builtin_arity(name, 1, types.len())?;
            if !matches!(types[0], IRType::Int(_)) {
                return Err(TypeRuleError::TypeMismatch {
                    field: "arguments[0]".to_owned(),
                    expected: IntType.into(),
                    actual: types[0].clone(),
                });
            }
            Ok(IntType.into())
        }
        "Math.mod" => {
            require_builtin_arity(name, 2, types.len())?;
            for (index, type_) in types.iter().enumerate() {
                if !is_real(type_) {
                    return Err(constraint(
                        &format!("arguments[{index}]"),
                        TypeExpectation::Real,
                        type_,
                    ));
                }
            }
            if types.iter().any(|type_| matches!(type_, IRType::Double(_))) {
                Ok(DoubleType.into())
            } else if types.iter().any(|type_| matches!(type_, IRType::Float(_))) {
                Ok(FloatType.into())
            } else {
                Ok(IntType.into())
            }
        }
        _ => Err(TypeRuleError::UnsupportedOperator {
            field: "builtin".to_owned(),
            operator: name.to_owned(),
        }),
    }
}

fn require_builtin_arity(name: &str, expected: usize, actual: usize) -> Result<(), TypeRuleError> {
    if expected == actual {
        Ok(())
    } else {
        Err(TypeRuleError::CountMismatch {
            field: format!("{name}.arguments"),
            expected,
            actual,
        })
    }
}

fn numeric_result_type(left: &IRType, right: &IRType) -> Result<IRType, TypeRuleError> {
    if !is_numeric(left) {
        return Err(constraint("left.element", TypeExpectation::Numeric, left));
    }
    if !is_numeric(right) {
        return Err(constraint("right.element", TypeExpectation::Numeric, right));
    }
    if matches!(left, IRType::Complex(_)) || matches!(right, IRType::Complex(_)) {
        Ok(ComplexType.into())
    } else if matches!(left, IRType::Double(_)) || matches!(right, IRType::Double(_)) {
        Ok(DoubleType.into())
    } else if matches!(left, IRType::Float(_)) || matches!(right, IRType::Float(_)) {
        Ok(FloatType.into())
    } else {
        Ok(IntType.into())
    }
}

fn struct_field(
    definition: &IRStructDefinition,
    field_index: i64,
) -> Result<&(String, IRType), TypeRuleError> {
    let index = usize::try_from(field_index).ok();
    index
        .and_then(|index| definition.fields.get(index))
        .ok_or(TypeRuleError::InvalidFieldIndex {
            field: "field_index".to_owned(),
            actual: field_index,
            field_count: definition.fields.len(),
        })
}

fn require_orientation(field: &str, orientation: Option<&str>) -> Result<(), TypeRuleError> {
    if matches!(orientation, Some("row" | "column")) {
        Ok(())
    } else {
        Err(metadata(
            field,
            "row or column".to_owned(),
            orientation_text(orientation),
        ))
    }
}

fn require_exact_orientation(
    field: &str,
    orientation: Option<&str>,
    expected: &str,
) -> Result<(), TypeRuleError> {
    if orientation == Some(expected) {
        Ok(())
    } else {
        Err(metadata(
            field,
            expected.to_owned(),
            orientation_text(orientation),
        ))
    }
}

fn orientation_text(orientation: Option<&str>) -> String {
    orientation.unwrap_or("none").to_owned()
}

fn metadata(field: &str, expected: String, actual: String) -> TypeRuleError {
    TypeRuleError::MetadataMismatch {
        field: field.to_owned(),
        expected,
        actual,
    }
}

fn constraint(field: &str, expected: TypeExpectation, actual: &IRType) -> TypeRuleError {
    TypeRuleError::TypeConstraint {
        field: field.to_owned(),
        expected,
        actual: actual.clone(),
    }
}

fn is_numeric(type_: &IRType) -> bool {
    matches!(
        type_,
        IRType::Int(_) | IRType::Float(_) | IRType::Double(_) | IRType::Complex(_)
    )
}

fn is_real(type_: &IRType) -> bool {
    matches!(type_, IRType::Int(_) | IRType::Float(_) | IRType::Double(_))
}

fn is_printable(type_: &IRType) -> bool {
    match type_ {
        IRType::Nullable(nullable) => is_printable(&nullable.inner),
        IRType::Array(array) => is_printable(&array.element),
        IRType::List(list) => is_printable(&list.element),
        IRType::Int(_)
        | IRType::Bool(_)
        | IRType::String(_)
        | IRType::Double(_)
        | IRType::Enum(_)
        | IRType::Vector(_)
        | IRType::Matrix(_)
        | IRType::Struct(_) => true,
        _ => false,
    }
}

fn array_of(element: IRType) -> IRType {
    ArrayType {
        element: Box::new(element),
    }
    .into()
}

fn list_of(element: IRType) -> IRType {
    ListType {
        element: Box::new(element),
    }
    .into()
}

#[allow(clippy::too_many_lines)]
pub(crate) fn instruction_result(instruction: &IRInstruction) -> Option<&IRValue> {
    match instruction {
        IRInstruction::IRConst { result, .. }
        | IRInstruction::IRLoad { result, .. }
        | IRInstruction::IRBinaryOp { result, .. }
        | IRInstruction::IRUnaryOp { result, .. }
        | IRInstruction::IRCompareOp { result, .. }
        | IRInstruction::IRCast { result, .. }
        | IRInstruction::IRFunctionRef { result, .. }
        | IRInstruction::IRStructNew { result, .. }
        | IRInstruction::IRClassNew { result, .. }
        | IRInstruction::IRClassGet { result, .. }
        | IRInstruction::IRStructGet { result, .. }
        | IRInstruction::IRStructSet { result, .. }
        | IRInstruction::IRMethodResultNew { result, .. }
        | IRInstruction::IRMethodResultReceiver { result, .. }
        | IRInstruction::IRMethodResultValue { result, .. }
        | IRInstruction::IRArrayNew { result, .. }
        | IRInstruction::IRListNew { result, .. }
        | IRInstruction::IRArrayCopy { result, .. }
        | IRInstruction::IRListCopy { result, .. }
        | IRInstruction::IRListContains { result, .. }
        | IRInstruction::IRListIndexOf { result, .. }
        | IRInstruction::IRListRemoveAt { result, .. }
        | IRInstruction::IRListPop { result, .. }
        | IRInstruction::IRVectorNew { result, .. }
        | IRInstruction::IRMatrixNew { result, .. }
        | IRInstruction::IRVectorAdd { result, .. }
        | IRInstruction::IRVectorSub { result, .. }
        | IRInstruction::IRVectorScale { result, .. }
        | IRInstruction::IRVectorDot { result, .. }
        | IRInstruction::IROuterProduct { result, .. }
        | IRInstruction::IRMatrixAdd { result, .. }
        | IRInstruction::IRMatrixSub { result, .. }
        | IRInstruction::IRMatrixScale { result, .. }
        | IRInstruction::IRMatrixMatMul { result, .. }
        | IRInstruction::IRMatrixVectorMul { result, .. }
        | IRInstruction::IRVectorMatrixMul { result, .. }
        | IRInstruction::IRArrayGet { result, .. }
        | IRInstruction::IRArraySlice { result, .. }
        | IRInstruction::IRListSlice { result, .. }
        | IRInstruction::IRListGet { result, .. }
        | IRInstruction::IRVectorGet { result, .. }
        | IRInstruction::IRMatrixGet { result, .. }
        | IRInstruction::IRVectorLength { result, .. }
        | IRInstruction::IRMatrixRows { result, .. }
        | IRInstruction::IRMatrixColumns { result, .. }
        | IRInstruction::IRArrayLength { result, .. }
        | IRInstruction::IRListLength { result, .. }
        | IRInstruction::IRListIsEmpty { result, .. } => Some(result),
        IRInstruction::IRCall { result, .. } | IRInstruction::IRCallIndirect { result, .. } => {
            result.as_ref()
        }
        _ => None,
    }
}

#[allow(clippy::too_many_lines)]
pub(crate) fn instruction_kind(instruction: &IRInstruction) -> InstructionKind {
    match instruction {
        IRInstruction::IRConst { .. } => InstructionKind::IRConst,
        IRInstruction::IRLoad { .. } => InstructionKind::IRLoad,
        IRInstruction::IRStore { .. } => InstructionKind::IRStore,
        IRInstruction::IRInitDefault { .. } => InstructionKind::IRInitDefault,
        IRInstruction::IRCopyInit { .. } => InstructionKind::IRCopyInit,
        IRInstruction::IRMoveInit { .. } => InstructionKind::IRMoveInit,
        IRInstruction::IRAssign { .. } => InstructionKind::IRAssign,
        IRInstruction::IRDestroy { .. } => InstructionKind::IRDestroy,
        IRInstruction::IRRelocate { .. } => InstructionKind::IRRelocate,
        IRInstruction::IRBinaryOp { .. } => InstructionKind::IRBinaryOp,
        IRInstruction::IRUnaryOp { .. } => InstructionKind::IRUnaryOp,
        IRInstruction::IRCompareOp { .. } => InstructionKind::IRCompareOp,
        IRInstruction::IRCast { .. } => InstructionKind::IRCast,
        IRInstruction::IRCall { .. } => InstructionKind::IRCall,
        IRInstruction::IRFunctionRef { .. } => InstructionKind::IRFunctionRef,
        IRInstruction::IRCallIndirect { .. } => InstructionKind::IRCallIndirect,
        IRInstruction::IRPrint { .. } => InstructionKind::IRPrint,
        IRInstruction::IRStructNew { .. } => InstructionKind::IRStructNew,
        IRInstruction::IRClassNew { .. } => InstructionKind::IRClassNew,
        IRInstruction::IRClassGet { .. } => InstructionKind::IRClassGet,
        IRInstruction::IRClassSet { .. } => InstructionKind::IRClassSet,
        IRInstruction::IRStructGet { .. } => InstructionKind::IRStructGet,
        IRInstruction::IRStructSet { .. } => InstructionKind::IRStructSet,
        IRInstruction::IRMethodResultNew { .. } => InstructionKind::IRMethodResultNew,
        IRInstruction::IRMethodResultReceiver { .. } => InstructionKind::IRMethodResultReceiver,
        IRInstruction::IRMethodResultValue { .. } => InstructionKind::IRMethodResultValue,
        IRInstruction::IRArrayNew { .. } => InstructionKind::IRArrayNew,
        IRInstruction::IRListNew { .. } => InstructionKind::IRListNew,
        IRInstruction::IRArrayCopy { .. } => InstructionKind::IRArrayCopy,
        IRInstruction::IRListCopy { .. } => InstructionKind::IRListCopy,
        IRInstruction::IRListContains { .. } => InstructionKind::IRListContains,
        IRInstruction::IRListIndexOf { .. } => InstructionKind::IRListIndexOf,
        IRInstruction::IRListClear { .. } => InstructionKind::IRListClear,
        IRInstruction::IRListPush { .. } => InstructionKind::IRListPush,
        IRInstruction::IRListInsert { .. } => InstructionKind::IRListInsert,
        IRInstruction::IRListRemoveAt { .. } => InstructionKind::IRListRemoveAt,
        IRInstruction::IRListPop { .. } => InstructionKind::IRListPop,
        IRInstruction::IRListReverse { .. } => InstructionKind::IRListReverse,
        IRInstruction::IRSequenceSort { .. } => InstructionKind::IRSequenceSort,
        IRInstruction::IRVectorNew { .. } => InstructionKind::IRVectorNew,
        IRInstruction::IRMatrixNew { .. } => InstructionKind::IRMatrixNew,
        IRInstruction::IRVectorAdd { .. } => InstructionKind::IRVectorAdd,
        IRInstruction::IRVectorSub { .. } => InstructionKind::IRVectorSub,
        IRInstruction::IRVectorScale { .. } => InstructionKind::IRVectorScale,
        IRInstruction::IRVectorDot { .. } => InstructionKind::IRVectorDot,
        IRInstruction::IROuterProduct { .. } => InstructionKind::IROuterProduct,
        IRInstruction::IRMatrixAdd { .. } => InstructionKind::IRMatrixAdd,
        IRInstruction::IRMatrixSub { .. } => InstructionKind::IRMatrixSub,
        IRInstruction::IRMatrixScale { .. } => InstructionKind::IRMatrixScale,
        IRInstruction::IRMatrixMatMul { .. } => InstructionKind::IRMatrixMatMul,
        IRInstruction::IRMatrixVectorMul { .. } => InstructionKind::IRMatrixVectorMul,
        IRInstruction::IRVectorMatrixMul { .. } => InstructionKind::IRVectorMatrixMul,
        IRInstruction::IRArrayGet { .. } => InstructionKind::IRArrayGet,
        IRInstruction::IRArraySlice { .. } => InstructionKind::IRArraySlice,
        IRInstruction::IRListSlice { .. } => InstructionKind::IRListSlice,
        IRInstruction::IRListGet { .. } => InstructionKind::IRListGet,
        IRInstruction::IRVectorGet { .. } => InstructionKind::IRVectorGet,
        IRInstruction::IRMatrixGet { .. } => InstructionKind::IRMatrixGet,
        IRInstruction::IRVectorLength { .. } => InstructionKind::IRVectorLength,
        IRInstruction::IRMatrixRows { .. } => InstructionKind::IRMatrixRows,
        IRInstruction::IRMatrixColumns { .. } => InstructionKind::IRMatrixColumns,
        IRInstruction::IRArraySet { .. } => InstructionKind::IRArraySet,
        IRInstruction::IRListSet { .. } => InstructionKind::IRListSet,
        IRInstruction::IRVectorSet { .. } => InstructionKind::IRVectorSet,
        IRInstruction::IRMatrixSet { .. } => InstructionKind::IRMatrixSet,
        IRInstruction::IRArrayLength { .. } => InstructionKind::IRArrayLength,
        IRInstruction::IRListLength { .. } => InstructionKind::IRListLength,
        IRInstruction::IRListIsEmpty { .. } => InstructionKind::IRListIsEmpty,
        IRInstruction::IRBranch { .. } => InstructionKind::IRBranch,
        IRInstruction::IRJump { .. } => InstructionKind::IRJump,
        IRInstruction::IRReturn { .. } => InstructionKind::IRReturn,
    }
}
