//! Focused type-consistency verifier coverage.

use std::error::Error as _;

use aether_ir::{
    ArrayType, BoolType, ClassRefType, DoubleType, FloatType, FunctionType, IRBasicBlock,
    IRConstant, IRFunction, IRInstruction, IRModule, IRParameter, IRStorage, IRStructDefinition,
    IRType, IRValue, IRWitnessMethodSlot, IRWitnessTable, IntType, InterfaceType, ListType,
    MatrixType, NullableType, StringType, StructType, VectorType, VoidType,
};
use aether_verifier::{
    BlockTypeVerificationError, FunctionTypeVerificationError, InstructionKind,
    InstructionTypeVerificationError, ModuleTypeVerificationError, TypeRuleError,
    verify_block_types, verify_function_types, verify_module_types,
};

fn value(name: &str, type_: IRType) -> IRValue {
    IRValue::new(name, type_)
}

fn vector(element: IRType, orientation: &str) -> IRType {
    VectorType {
        element: Box::new(element),
        orientation: Some(orientation.to_owned()),
    }
    .into()
}

fn matrix(element: IRType) -> IRType {
    MatrixType {
        element: Box::new(element),
    }
    .into()
}

fn collection(element: IRType, array: bool) -> IRType {
    if array {
        ArrayType {
            element: Box::new(element),
        }
        .into()
    } else {
        ListType {
            element: Box::new(element),
        }
        .into()
    }
}

fn function_with_instruction(
    function_name: &str,
    return_type: IRType,
    instruction: IRInstruction,
) -> IRFunction {
    let mut block = IRBasicBlock::new("entry");
    block.instructions.push(instruction);
    let mut function = IRFunction::new(function_name, Vec::new(), return_type);
    function.blocks.push(block);
    function
}

fn module_with_instruction(instruction: IRInstruction) -> IRModule {
    IRModule {
        functions: vec![function_with_instruction(
            "main",
            VoidType.into(),
            instruction,
        )],
        structs: Vec::new(),
    }
}

fn instruction_rule(error: &ModuleTypeVerificationError) -> &TypeRuleError {
    let ModuleTypeVerificationError::Function { source, .. } = error else {
        panic!("expected a function error")
    };
    let FunctionTypeVerificationError::Block { source, .. } = source else {
        panic!("expected a block error")
    };
    &source.source.source
}

#[test]
fn accepts_valid_primitive_arithmetic_through_every_public_layer() {
    let instruction = IRInstruction::IRBinaryOp {
        result: value("sum", IntType.into()),
        operator: "add".to_owned(),
        left: value("left", IntType.into()),
        right: value("right", IntType.into()),
        source_location: None,
    };
    let module = module_with_instruction(instruction);
    let function = &module.functions[0];
    let block = &function.blocks[0];

    assert_eq!(verify_module_types(&module), Ok(()));
    assert_eq!(verify_function_types(&module, function), Ok(()));
    assert_eq!(verify_block_types(&module, function, block), Ok(()));
}

#[test]
fn null_constant_requires_and_accepts_nullable_result_type() {
    let nullable: IRType = NullableType {
        inner: Box::new(IntType.into()),
    }
    .into();
    let valid = module_with_instruction(IRInstruction::IRConst {
        result: value("absent", nullable),
        value: IRConstant::Null,
    });
    assert_eq!(verify_module_types(&valid), Ok(()));

    let invalid = module_with_instruction(IRInstruction::IRConst {
        result: value("absent", IntType.into()),
        value: IRConstant::Null,
    });
    assert_eq!(
        instruction_rule(&verify_module_types(&invalid).unwrap_err()),
        &TypeRuleError::TypeConstraint {
            field: "result".to_owned(),
            expected: aether_verifier::TypeExpectation::Nullable,
            actual: IntType.into(),
        }
    );
}

#[test]
fn rejects_invalid_arithmetic_operand_types() {
    let module = module_with_instruction(IRInstruction::IRBinaryOp {
        result: value("sum", IntType.into()),
        operator: "add".to_owned(),
        left: value("left", IntType.into()),
        right: value("right", StringType.into()),
        source_location: None,
    });

    let error = verify_module_types(&module).unwrap_err();
    assert_eq!(
        instruction_rule(&error),
        &TypeRuleError::TypeConstraint {
            field: "right".to_owned(),
            expected: aether_verifier::TypeExpectation::Numeric,
            actual: StringType.into(),
        }
    );
}

#[test]
fn rejects_invalid_arithmetic_result_types() {
    let module = module_with_instruction(IRInstruction::IRBinaryOp {
        result: value("quotient", IntType.into()),
        operator: "div".to_owned(),
        left: value("left", IntType.into()),
        right: value("right", IntType.into()),
        source_location: None,
    });

    let error = verify_module_types(&module).unwrap_err();
    assert_eq!(
        instruction_rule(&error),
        &TypeRuleError::TypeMismatch {
            field: "result".to_owned(),
            expected: DoubleType.into(),
            actual: IntType.into(),
        }
    );
}

#[test]
fn rejects_invalid_direct_call_argument_counts_and_types() {
    let callee = IRFunction::new(
        "take_int",
        vec![IRParameter::new("number", IntType.into())],
        VoidType.into(),
    );
    let bad_count = function_with_instruction(
        "bad_count",
        VoidType.into(),
        IRInstruction::IRCall {
            function: "take_int".to_owned(),
            arguments: Vec::new(),
            result: None,
            builtin: None,
            source_location: None,
        },
    );
    let bad_type = function_with_instruction(
        "bad_type",
        VoidType.into(),
        IRInstruction::IRCall {
            function: "take_int".to_owned(),
            arguments: vec![value("text", StringType.into())],
            result: None,
            builtin: None,
            source_location: None,
        },
    );

    let count_module = IRModule {
        functions: vec![callee.clone(), bad_count],
        structs: Vec::new(),
    };
    let type_module = IRModule {
        functions: vec![callee, bad_type],
        structs: Vec::new(),
    };
    assert!(matches!(
        instruction_rule(&verify_module_types(&count_module).unwrap_err()),
        TypeRuleError::CountMismatch {
            field,
            expected: 1,
            actual: 0,
        } if field == "arguments"
    ));
    assert!(matches!(
        instruction_rule(&verify_module_types(&type_module).unwrap_err()),
        TypeRuleError::TypeMismatch {
            field,
            expected: IRType::Int(_),
            actual: IRType::String(_),
        } if field == "arguments[0]"
    ));
}

#[test]
fn rejects_invalid_indirect_call_signature_compatibility() {
    let signature: IRType = FunctionType {
        parameter_types: vec![IntType.into()],
        return_type: Box::new(StringType.into()),
    }
    .into();
    let module = module_with_instruction(IRInstruction::IRCallIndirect {
        callee: value("callable", signature),
        arguments: vec![value("wrong", BoolType.into())],
        result: Some(value("text", StringType.into())),
    });

    assert!(matches!(
        instruction_rule(&verify_module_types(&module).unwrap_err()),
        TypeRuleError::TypeMismatch {
            field,
            expected: IRType::Int(_),
            actual: IRType::Bool(_),
        } if field == "arguments[0]"
    ));
}

#[test]
fn rejects_invalid_return_type_without_requiring_cfg_structure() {
    let function = function_with_instruction(
        "answer",
        IntType.into(),
        IRInstruction::IRReturn {
            value: Some(value("answer", StringType.into()).into()),
            transferred_storage: None,
        },
    );
    let module = IRModule {
        functions: vec![function],
        structs: Vec::new(),
    };

    assert!(matches!(
        instruction_rule(&verify_module_types(&module).unwrap_err()),
        TypeRuleError::TypeMismatch {
            field,
            expected: IRType::Int(_),
            actual: IRType::String(_),
        } if field == "value"
    ));
}

#[test]
fn accepts_valid_boolean_branch_condition() {
    let module = module_with_instruction(IRInstruction::IRBranch {
        condition: value("condition", BoolType.into()),
        true_target: "then".to_owned(),
        false_target: "else".to_owned(),
    });

    assert_eq!(verify_module_types(&module), Ok(()));
}

#[test]
fn rejects_integer_branch_condition_with_typed_context() {
    let module = module_with_instruction(IRInstruction::IRBranch {
        condition: value("condition", IntType.into()),
        true_target: "then".to_owned(),
        false_target: "else".to_owned(),
    });

    let error = verify_module_types(&module).unwrap_err();
    let ModuleTypeVerificationError::Function { source, .. } = &error else {
        panic!("expected function context")
    };
    let FunctionTypeVerificationError::Block { source, .. } = source else {
        panic!("expected block context")
    };
    assert_eq!(source.instruction_index, 0);
    assert_eq!(source.instruction_kind, InstructionKind::IRBranch);
    assert_eq!(
        instruction_rule(&error),
        &TypeRuleError::TypeMismatch {
            field: "condition".to_owned(),
            expected: BoolType.into(),
            actual: IntType.into(),
        }
    );
}

#[test]
fn rejects_aggregate_branch_condition() {
    let aggregate_type = collection(BoolType.into(), true);
    let module = module_with_instruction(IRInstruction::IRBranch {
        condition: value("condition", aggregate_type.clone()),
        true_target: "then".to_owned(),
        false_target: "else".to_owned(),
    });

    let error = verify_module_types(&module).unwrap_err();
    assert_eq!(
        instruction_rule(&error),
        &TypeRuleError::TypeMismatch {
            field: "condition".to_owned(),
            expected: BoolType.into(),
            actual: aggregate_type,
        }
    );
}

#[test]
fn accepts_nonexistent_branch_targets_with_boolean_condition() {
    let module = module_with_instruction(IRInstruction::IRBranch {
        condition: value("condition", BoolType.into()),
        true_target: "definitely_missing".to_owned(),
        false_target: "also_missing".to_owned(),
    });

    assert_eq!(verify_module_types(&module), Ok(()));
}

#[test]
fn rejects_invalid_struct_construction_field_type() {
    let point_type = IRType::Struct(StructType {
        name: "Point".to_owned(),
    });
    let mut module = module_with_instruction(IRInstruction::IRStructNew {
        result: value("point", point_type),
        fields: vec![value("x", StringType.into())],
    });
    module.structs.push(IRStructDefinition {
        name: "Point".to_owned(),
        fields: vec![("x".to_owned(), IntType.into())],
    });

    assert!(matches!(
        instruction_rule(&verify_module_types(&module).unwrap_err()),
        TypeRuleError::TypeMismatch {
            field,
            expected: IRType::Int(_),
            actual: IRType::String(_),
        } if field == "fields[0]"
    ));
}

#[test]
fn class_new_requires_a_class_reference_result() {
    let class_type: IRType = ClassRefType {
        name: "pkg.Widget".to_owned(),
    }
    .into();
    let valid = module_with_instruction(IRInstruction::IRClassNew {
        result: value("object", class_type),
    });
    assert_eq!(verify_module_types(&valid), Ok(()));

    let invalid = module_with_instruction(IRInstruction::IRClassNew {
        result: value("object", IntType.into()),
    });
    assert_eq!(
        instruction_rule(&verify_module_types(&invalid).unwrap_err()),
        &TypeRuleError::TypeConstraint {
            field: "result".to_owned(),
            expected: aether_verifier::TypeExpectation::ClassReference,
            actual: IntType.into(),
        }
    );
}

#[test]
fn interface_construct_requires_class_carrier_and_ordered_witness_metadata() {
    let carrier_type: IRType = ClassRefType {
        name: "Box".to_owned(),
    }
    .into();
    let interface_type: IRType = InterfaceType {
        name: "Readable".to_owned(),
    }
    .into();
    let witness = IRWitnessTable {
        symbol: "__ae_witness_i8_5265616461626c65__c3_426f78__524730a6e96e3203".to_owned(),
        interface_id: "Readable".to_owned(),
        concrete_type_id: "Box".to_owned(),
        carrier_kind: "class".to_owned(),
        method_slots: vec![IRWitnessMethodSlot {
            index: 0,
            method_id: "Readable.read".to_owned(),
            parameter_types: Vec::new(),
            return_type: IntType.into(),
            thunk_symbol: "__ae_interface_thunk_s0__test".to_owned(),
            receiver_ownership: "borrowed".to_owned(),
        }],
        abi_version: 1,
        box_layout: None,
    };
    let mut valid = module_with_instruction(IRInstruction::IRInterfaceConstruct {
        result: value("interface", interface_type.clone()),
        carrier: value("box", carrier_type.clone()),
        witness: witness.clone(),
    });
    valid.functions.push(IRFunction::new(
        "Box.read",
        vec![IRParameter::new("this", carrier_type.clone())],
        IntType.into(),
    ));
    assert_eq!(verify_module_types(&valid), Ok(()));

    let mut invalid_witness = witness;
    invalid_witness.method_slots[0].index = 1;
    let mut invalid = module_with_instruction(IRInstruction::IRInterfaceConstruct {
        result: value("interface", interface_type),
        carrier: value("box", carrier_type.clone()),
        witness: invalid_witness,
    });
    invalid.functions.push(IRFunction::new(
        "Box.read",
        vec![IRParameter::new("this", carrier_type)],
        IntType.into(),
    ));
    assert!(matches!(
        instruction_rule(&verify_module_types(&invalid).unwrap_err()),
        TypeRuleError::TypeConstraint { field, .. } if field == "witness"
    ));
}

#[test]
fn class_fields_use_the_nominal_definition_and_canonical_field_type() {
    let class_type: IRType = ClassRefType {
        name: "pkg.Widget".to_owned(),
    }
    .into();
    let mut valid = module_with_instruction(IRInstruction::IRClassGet {
        result: value("field", IntType.into()),
        object: value("object", class_type.clone()),
        field_index: 0,
        field_name: "value".to_owned(),
    });
    valid.structs.push(IRStructDefinition {
        name: "pkg.Widget".to_owned(),
        fields: vec![("value".to_owned(), IntType.into())],
    });
    assert_eq!(verify_module_types(&valid), Ok(()));

    let mut wrong_name = module_with_instruction(IRInstruction::IRClassGet {
        result: value("field", IntType.into()),
        object: value("object", class_type.clone()),
        field_index: 0,
        field_name: "other".to_owned(),
    });
    wrong_name.structs = valid.structs.clone();
    assert!(matches!(
        instruction_rule(&verify_module_types(&wrong_name).unwrap_err()),
        TypeRuleError::MetadataMismatch {
            field,
            expected,
            actual,
        } if field == "field_name" && expected == "value" && actual == "other"
    ));

    let mut invalid = module_with_instruction(IRInstruction::IRClassSet {
        object: value("object", class_type),
        field_index: 0,
        field_name: "value".to_owned(),
        value: value("wrong", StringType.into()),
        initialize: true,
    });
    invalid.structs = valid.structs;
    assert!(matches!(
        instruction_rule(&verify_module_types(&invalid).unwrap_err()),
        TypeRuleError::TypeMismatch {
            field,
            expected: IRType::Int(_),
            actual: IRType::String(_),
        } if field == "value"
    ));
}

#[test]
fn class_references_have_identity_equality() {
    let class_type: IRType = ClassRefType {
        name: "pkg.Widget".to_owned(),
    }
    .into();
    let module = module_with_instruction(IRInstruction::IRCompareOp {
        result: value("same", BoolType.into()),
        operator: "eq".to_owned(),
        left: value("left", class_type.clone()),
        right: value("right", class_type),
        aggregate_shape: None,
    });

    assert_eq!(verify_module_types(&module), Ok(()));
}

#[test]
fn rejects_invalid_array_and_list_literal_element_types() {
    for array in [true, false] {
        let result = value("items", collection(IntType.into(), array));
        let elements = vec![value("bad", BoolType.into())];
        let instruction = if array {
            IRInstruction::IRArrayNew { result, elements }
        } else {
            IRInstruction::IRListNew { result, elements }
        };
        let error = verify_module_types(&module_with_instruction(instruction)).unwrap_err();
        assert!(matches!(
            instruction_rule(&error),
            TypeRuleError::TypeMismatch {
                field,
                expected: IRType::Int(_),
                actual: IRType::Bool(_),
            } if field == "elements[0]"
        ));
    }
}

#[test]
fn rejects_invalid_matrix_and_vector_element_compatibility() {
    let matrix_module = module_with_instruction(IRInstruction::IRMatrixMatMul {
        result: value("product", matrix(BoolType.into())),
        left: value("left", matrix(IntType.into())),
        right: value("right", matrix(DoubleType.into())),
        rows: 2,
        inner: 2,
        cols: 2,
    });
    let vector_module = module_with_instruction(IRInstruction::IRVectorScale {
        result: value("scaled", vector(IntType.into(), "row")),
        vector: value("vector", vector(IntType.into(), "row")),
        scalar: value("scalar", FloatType.into()),
        length: 3,
        orientation: Some("row".to_owned()),
    });

    assert!(matches!(
        instruction_rule(&verify_module_types(&matrix_module).unwrap_err()),
        TypeRuleError::TypeMismatch {
            field,
            expected: IRType::Double(_),
            actual: IRType::Bool(_),
        } if field == "result.element"
    ));
    assert!(matches!(
        instruction_rule(&verify_module_types(&vector_module).unwrap_err()),
        TypeRuleError::TypeMismatch {
            field,
            expected: IRType::Int(_),
            actual: IRType::Float(_),
        } if field == "scalar"
    ));
}

#[test]
fn rejects_casts_outside_the_python_allowlist() {
    let module = module_with_instruction(IRInstruction::IRCast {
        result: value("number", IntType.into()),
        value: value("flag", BoolType.into()),
    });

    assert!(matches!(
        instruction_rule(&verify_module_types(&module).unwrap_err()),
        TypeRuleError::TypeConstraint {
            field,
            actual: IRType::Bool(_),
            ..
        } if field == "value -> result"
    ));
}

#[test]
fn rejects_invalid_parameter_types_with_function_context() {
    let function = IRFunction::new(
        "consume",
        vec![IRParameter::new(
            "missing",
            StructType {
                name: "Missing".to_owned(),
            }
            .into(),
        )],
        VoidType.into(),
    );
    let module = IRModule {
        functions: vec![function],
        structs: Vec::new(),
    };

    let error = verify_module_types(&module).unwrap_err();
    assert!(matches!(
        error,
        ModuleTypeVerificationError::Function {
            source: FunctionTypeVerificationError::Parameter {
                function_name,
                parameter_index: 0,
                parameter_name,
                source: TypeRuleError::TypeConstraint {
                    field,
                    actual: IRType::Struct(_),
                    ..
                },
            },
            ..
        } if function_name == "consume" && parameter_name == "missing" && field == "missing"
    ));
}

#[test]
fn intentionally_defers_cfg_names_and_lifecycle_contracts() {
    let mut block = IRBasicBlock::new("not_entry");
    block.instructions.push(IRInstruction::IRCopyInit {
        destination: IRStorage::new("slot", IntType.into()),
        source: value("text", StringType.into()).into(),
        source_location: None,
    });
    block.instructions.push(IRInstruction::IRBranch {
        condition: value("condition", BoolType.into()),
        true_target: "missing".to_owned(),
        false_target: "also_missing".to_owned(),
    });
    block.instructions.push(IRInstruction::IRJump {
        target: "after_terminator".to_owned(),
    });
    let mut first = IRFunction::new("duplicate", Vec::new(), VoidType.into());
    first.blocks.push(block);
    let second = IRFunction::new("duplicate", Vec::new(), VoidType.into());
    let module = IRModule {
        functions: vec![first, second],
        structs: Vec::new(),
    };

    assert_eq!(verify_module_types(&module), Ok(()));
}

#[test]
fn nested_errors_retain_context_and_complete_source_chain() {
    let module = module_with_instruction(IRInstruction::IRArrayNew {
        result: value("items", collection(IntType.into(), true)),
        elements: vec![value("bad", StringType.into())],
    });

    let error = verify_module_types(&module).unwrap_err();
    let ModuleTypeVerificationError::Function {
        function_index,
        function_name,
        ..
    } = &error
    else {
        panic!("expected function context")
    };
    assert_eq!((*function_index, function_name.as_str()), (0, "main"));

    let function_error = error
        .source()
        .and_then(|source| source.downcast_ref::<FunctionTypeVerificationError>())
        .expect("module error must source the function error");
    let FunctionTypeVerificationError::Block {
        block_index,
        block_name,
        ..
    } = function_error
    else {
        panic!("expected block context")
    };
    assert_eq!((*block_index, block_name.as_str()), (0, "entry"));

    let block_error = function_error
        .source()
        .and_then(|source| source.downcast_ref::<BlockTypeVerificationError>())
        .expect("function error must source the block error");
    assert_eq!(block_error.function_name, "main");
    assert_eq!(block_error.block_name, "entry");
    assert_eq!(block_error.instruction_index, 0);
    assert_eq!(block_error.instruction_kind, InstructionKind::IRArrayNew);

    let instruction_error = block_error
        .source()
        .and_then(|source| source.downcast_ref::<InstructionTypeVerificationError>())
        .expect("block error must source the instruction error");
    assert_eq!(
        instruction_error.instruction_kind,
        InstructionKind::IRArrayNew
    );
    assert!(instruction_error.source().is_some_and(|source| {
        matches!(
            source.downcast_ref::<TypeRuleError>(),
            Some(TypeRuleError::TypeMismatch { field, .. }) if field == "elements[0]"
        )
    }));
}

#[test]
fn repeated_verification_is_deterministic() {
    let module = module_with_instruction(IRInstruction::IRBinaryOp {
        result: value("sum", BoolType.into()),
        operator: "add".to_owned(),
        left: value("left", IntType.into()),
        right: value("right", IntType.into()),
        source_location: None,
    });

    let first = verify_module_types(&module).unwrap_err();
    for _ in 0..32 {
        let next = verify_module_types(&module).unwrap_err();
        assert_eq!(next, first);
        assert_eq!(next.to_string(), first.to_string());
    }
}
