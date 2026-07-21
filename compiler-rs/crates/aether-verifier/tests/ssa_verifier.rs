//! Focused SSA definition-before-use and reference-validity coverage.

use std::error::Error as _;

use aether_ir::{
    BoolType, FunctionType, IRBasicBlock, IRConstant, IRFunction, IRInstruction, IRModule,
    IRParameter, IRStorage, IRType, IRValue, IntType, StringType, VoidType,
};
use aether_verifier::{
    BlockSSAError, FunctionSSAError, InstructionKind, ModuleSSAError, SSADefinitionError,
    SSADefinitionLocation, SSAInstructionLocation, SSAUseLocation, verify_function_ssa,
    verify_module_ssa,
};

fn value(name: &str, type_: IRType) -> IRValue {
    IRValue::new(name, type_)
}

fn int(name: &str) -> IRValue {
    value(name, IntType.into())
}

fn constant(name: &str, literal: i32) -> IRInstruction {
    IRInstruction::IRConst {
        result: int(name),
        value: IRConstant::Int(literal),
    }
}

fn ret(value: Option<IRValue>) -> IRInstruction {
    IRInstruction::IRReturn {
        value,
        transferred_storage: None,
    }
}

fn jump(target: &str) -> IRInstruction {
    IRInstruction::IRJump {
        target: target.to_owned(),
    }
}

fn block(name: &str, instructions: Vec<IRInstruction>) -> IRBasicBlock {
    IRBasicBlock {
        name: name.to_owned(),
        instructions,
    }
}

fn function(
    name: &str,
    parameters: Vec<IRParameter>,
    return_type: IRType,
    blocks: Vec<IRBasicBlock>,
) -> IRFunction {
    IRFunction {
        name: name.to_owned(),
        parameters,
        return_type,
        blocks,
    }
}

fn module(functions: Vec<IRFunction>) -> IRModule {
    IRModule {
        functions,
        structs: Vec::new(),
    }
}

fn block_rule(error: &ModuleSSAError) -> &SSADefinitionError {
    let FunctionSSAError::Block { source, .. } = error.source.as_ref() else {
        panic!("expected block SSA error")
    };
    &source.source
}

fn instruction_location(
    block_index: usize,
    block_name: &str,
    instruction_index: usize,
    instruction_kind: InstructionKind,
) -> SSAInstructionLocation {
    SSAInstructionLocation {
        block_index,
        block_name: block_name.to_owned(),
        instruction_index,
        instruction_kind,
    }
}

#[test]
fn accepts_parameter_use_through_module_and_function_apis() {
    let parameter = IRParameter::new("input", IntType.into());
    let function = function(
        "identity",
        vec![parameter],
        IntType.into(),
        vec![block("entry", vec![ret(Some(int("input")))])],
    );
    let module = module(vec![function]);

    assert_eq!(verify_module_ssa(&module), Ok(()));
    assert_eq!(verify_function_ssa(&module.functions[0]), Ok(()));
}

#[test]
fn accepts_local_definition_then_use_and_multiple_sequential_definitions() {
    let function = function(
        "sequential",
        Vec::new(),
        IntType.into(),
        vec![block(
            "entry",
            vec![
                constant("one", 1),
                constant("two", 2),
                IRInstruction::IRBinaryOp {
                    result: int("sum"),
                    operator: "add".to_owned(),
                    left: int("one"),
                    right: int("two"),
                    source_location: None,
                },
                ret(Some(int("sum"))),
            ],
        )],
    );

    assert_eq!(verify_function_ssa(&function), Ok(()));
}

#[test]
fn constant_payloads_are_literals_and_storage_operands_are_not_ssa_uses() {
    let slot = IRStorage::new("slot", IntType.into());
    let function = function(
        "load_literal",
        Vec::new(),
        IntType.into(),
        vec![block(
            "entry",
            vec![
                constant("literal", 7),
                IRInstruction::IRStore {
                    slot: (&slot).into(),
                    value: int("literal"),
                },
                IRInstruction::IRLoad {
                    result: int("loaded"),
                    slot: (&slot).into(),
                },
                ret(Some(int("loaded"))),
            ],
        )],
    );

    assert_eq!(verify_function_ssa(&function), Ok(()));
}

#[test]
fn lifecycle_value_sources_are_ssa_uses_and_storage_sources_are_not() {
    let value_source = function(
        "value_sources",
        vec![IRParameter::new("input", IntType.into())],
        VoidType.into(),
        vec![block(
            "entry",
            vec![
                IRInstruction::IRCopyInit {
                    destination: IRStorage::new("copy", IntType.into()),
                    source: int("input").into(),
                    source_location: None,
                },
                IRInstruction::IRAssign {
                    destination: IRStorage::new("assign", IntType.into()),
                    source: int("input").into(),
                    source_location: None,
                },
                ret(None),
            ],
        )],
    );
    assert_eq!(verify_function_ssa(&value_source), Ok(()));

    for instruction in [
        IRInstruction::IRCopyInit {
            destination: IRStorage::new("copy", IntType.into()),
            source: IRStorage::new("not_an_ssa_definition", IntType.into()).into(),
            source_location: None,
        },
        IRInstruction::IRAssign {
            destination: IRStorage::new("assign", IntType.into()),
            source: IRStorage::new("not_an_ssa_definition", IntType.into()).into(),
            source_location: None,
        },
    ] {
        let storage_source = function(
            "storage_source",
            Vec::new(),
            VoidType.into(),
            vec![block("entry", vec![instruction, ret(None)])],
        );
        assert_eq!(verify_function_ssa(&storage_source), Ok(()));
    }
}

#[test]
fn lifecycle_source_kind_is_not_inferred_from_colliding_identifier_spelling() {
    let storage_source = IRStorage::new("same", IntType.into());
    let function = function(
        "separate_namespaces",
        vec![IRParameter::new("same", IntType.into())],
        VoidType.into(),
        vec![block(
            "entry",
            vec![
                IRInstruction::IRCopyInit {
                    destination: IRStorage::new("from_storage", IntType.into()),
                    source: storage_source.into(),
                    source_location: None,
                },
                IRInstruction::IRCopyInit {
                    destination: IRStorage::new("from_value", IntType.into()),
                    source: int("same").into(),
                    source_location: None,
                },
                ret(None),
            ],
        )],
    );

    assert_eq!(verify_function_ssa(&function), Ok(()));
}

#[test]
fn rejects_undefined_lifecycle_value_sources_for_copy_init_and_assign() {
    for instruction in [
        IRInstruction::IRCopyInit {
            destination: IRStorage::new("copy", IntType.into()),
            source: int("missing").into(),
            source_location: None,
        },
        IRInstruction::IRAssign {
            destination: IRStorage::new("assign", IntType.into()),
            source: int("missing").into(),
            source_location: None,
        },
    ] {
        let function = function(
            "undefined_lifecycle_value",
            Vec::new(),
            VoidType.into(),
            vec![block("entry", vec![instruction, ret(None)])],
        );
        assert!(matches!(
            verify_function_ssa(&function),
            Err(FunctionSSAError::Block { source, .. })
                if source.ssa_identifier == "missing"
                    && matches!(source.source, SSADefinitionError::UndefinedReference { .. })
        ));
    }
}

#[test]
fn function_reference_results_are_definitions_available_to_indirect_calls() {
    let signature: IRType = FunctionType {
        parameter_types: Vec::new(),
        return_type: Box::new(VoidType.into()),
    }
    .into();
    let function = function(
        "callable",
        Vec::new(),
        VoidType.into(),
        vec![block(
            "entry",
            vec![
                IRInstruction::IRFunctionRef {
                    result: value("target_ref", signature.clone()),
                    function: "target".to_owned(),
                },
                IRInstruction::IRCallIndirect {
                    callee: value("target_ref", signature),
                    arguments: Vec::new(),
                    result: None,
                },
                ret(None),
            ],
        )],
    );

    assert_eq!(verify_function_ssa(&function), Ok(()));
}

#[test]
fn accepts_cross_block_non_dominating_and_phi_like_merge_uses() {
    let condition = IRParameter::new("condition", BoolType.into());
    let function = function(
        "deferred_dominance",
        vec![condition],
        IntType.into(),
        vec![
            block(
                "entry",
                vec![IRInstruction::IRBranch {
                    condition: value("condition", BoolType.into()),
                    true_target: "left".to_owned(),
                    false_target: "right".to_owned(),
                }],
            ),
            block("left", vec![constant("left_only", 1), jump("merge")]),
            block("right", vec![jump("merge")]),
            block("merge", vec![ret(Some(int("left_only")))]),
        ],
    );

    // The missing merge/phi semantics and sibling-definition dominance
    // violation are both intentionally deferred to later passes.
    assert_eq!(verify_function_ssa(&function), Ok(()));
}

#[test]
fn ownership_and_lifecycle_state_are_ignored() {
    let function = function(
        "lifecycle_deferred",
        Vec::new(),
        VoidType.into(),
        vec![block(
            "entry",
            vec![
                IRInstruction::IRDestroy {
                    value: IRStorage::new("never_initialized", StringType.into()),
                    source_location: None,
                },
                ret(None),
            ],
        )],
    );

    assert_eq!(verify_function_ssa(&function), Ok(()));
}

#[test]
fn rejects_first_undefined_reference_in_instruction_and_operand_order() {
    let function = function(
        "undefined",
        Vec::new(),
        IntType.into(),
        vec![block(
            "entry",
            vec![IRInstruction::IRBinaryOp {
                result: int("result"),
                operator: "add".to_owned(),
                left: int("first_missing"),
                right: int("second_missing"),
                source_location: None,
            }],
        )],
    );
    let error = verify_function_ssa(&function).unwrap_err();

    let FunctionSSAError::Block { source, .. } = error else {
        panic!("expected block error")
    };
    assert_eq!(source.function_name, "undefined");
    assert_eq!(source.block_name, "entry");
    assert_eq!(source.instruction_index, 0);
    assert_eq!(source.instruction_kind, InstructionKind::IRBinaryOp);
    assert_eq!(source.ssa_identifier, "first_missing");
    assert_eq!(
        source.source,
        SSADefinitionError::UndefinedReference {
            ssa_identifier: "first_missing".to_owned(),
            use_location: SSAUseLocation {
                instruction: instruction_location(0, "entry", 0, InstructionKind::IRBinaryOp),
                operand_index: 0,
            },
        }
    );
}

#[test]
fn rejects_duplicate_instruction_result_with_both_definition_locations() {
    let module = module(vec![function(
        "duplicate",
        Vec::new(),
        IntType.into(),
        vec![block(
            "entry",
            vec![
                constant("same", 1),
                constant("same", 2),
                ret(Some(int("same"))),
            ],
        )],
    )]);
    let error = verify_module_ssa(&module).unwrap_err();

    assert_eq!(error.function_index, 0);
    assert_eq!(error.function_name, "duplicate");
    assert_eq!(
        block_rule(&error),
        &SSADefinitionError::DuplicateDefinition {
            ssa_identifier: "same".to_owned(),
            defining_location: SSADefinitionLocation::Instruction(instruction_location(
                0,
                "entry",
                0,
                InstructionKind::IRConst,
            )),
            duplicate_definition_location: SSADefinitionLocation::Instruction(
                instruction_location(0, "entry", 1, InstructionKind::IRConst),
            ),
        }
    );
}

#[test]
fn list_pop_and_remove_at_results_are_instruction_definitions() {
    for result_instruction in [
        IRInstruction::IRListPop {
            result: int("duplicate"),
            list_value: value(
                "items",
                aether_ir::ListType {
                    element: Box::new(IntType.into()),
                }
                .into(),
            ),
        },
        IRInstruction::IRListRemoveAt {
            result: int("duplicate"),
            list_value: value(
                "items",
                aether_ir::ListType {
                    element: Box::new(IntType.into()),
                }
                .into(),
            ),
            index: int("index"),
        },
    ] {
        let module = module(vec![function(
            "list_result",
            Vec::new(),
            VoidType.into(),
            vec![block(
                "entry",
                vec![constant("duplicate", 1), result_instruction],
            )],
        )]);

        assert!(matches!(
            block_rule(&verify_module_ssa(&module).unwrap_err()),
            SSADefinitionError::DuplicateDefinition { ssa_identifier, .. }
                if ssa_identifier == "duplicate"
        ));
    }
}

#[test]
fn rejects_duplicate_parameter_names_and_parameter_result_collisions() {
    let duplicate_parameters = function(
        "parameters",
        vec![
            IRParameter::new("same", IntType.into()),
            IRParameter::new("same", IntType.into()),
        ],
        VoidType.into(),
        vec![block("entry", vec![ret(None)])],
    );
    assert_eq!(
        verify_function_ssa(&duplicate_parameters).unwrap_err(),
        FunctionSSAError::Definition {
            function_name: "parameters".to_owned(),
            ssa_identifier: "same".to_owned(),
            source: SSADefinitionError::DuplicateDefinition {
                ssa_identifier: "same".to_owned(),
                defining_location: SSADefinitionLocation::Parameter { parameter_index: 0 },
                duplicate_definition_location: SSADefinitionLocation::Parameter {
                    parameter_index: 1,
                },
            },
        }
    );

    let collision = function(
        "collision",
        vec![IRParameter::new("same", IntType.into())],
        VoidType.into(),
        vec![block("entry", vec![constant("same", 1), ret(None)])],
    );
    let FunctionSSAError::Block { source, .. } = verify_function_ssa(&collision).unwrap_err()
    else {
        panic!("expected instruction duplicate")
    };
    assert!(matches!(
        source.source,
        SSADefinitionError::DuplicateDefinition {
            defining_location: SSADefinitionLocation::Parameter { parameter_index: 0 },
            duplicate_definition_location: SSADefinitionLocation::Instruction(_),
            ..
        }
    ));
}

#[test]
fn rejects_same_block_use_before_definition_and_self_reference() {
    let before = function(
        "before",
        Vec::new(),
        IntType.into(),
        vec![block(
            "entry",
            vec![ret(Some(int("later"))), constant("later", 1)],
        )],
    );
    let error = verify_function_ssa(&before).unwrap_err();
    let FunctionSSAError::Block { source, .. } = error else {
        panic!("expected use-before-definition error")
    };
    assert_eq!(
        source.source,
        SSADefinitionError::UseBeforeDefinition {
            ssa_identifier: "later".to_owned(),
            defining_location: SSADefinitionLocation::Instruction(instruction_location(
                0,
                "entry",
                1,
                InstructionKind::IRConst,
            )),
            use_location: SSAUseLocation {
                instruction: instruction_location(0, "entry", 0, InstructionKind::IRReturn),
                operand_index: 0,
            },
        }
    );

    let self_reference = function(
        "self_reference",
        Vec::new(),
        IntType.into(),
        vec![block(
            "entry",
            vec![IRInstruction::IRUnaryOp {
                result: int("same_instruction"),
                operator: "neg".to_owned(),
                operand: int("same_instruction"),
            }],
        )],
    );
    assert!(matches!(
        verify_function_ssa(&self_reference).unwrap_err(),
        FunctionSSAError::Block { source, .. }
            if matches!(source.source, SSADefinitionError::UseBeforeDefinition { .. })
    ));
}

#[test]
fn rejects_missing_function_reference_result_and_resultless_non_definition() {
    let signature: IRType = FunctionType {
        parameter_types: Vec::new(),
        return_type: Box::new(VoidType.into()),
    }
    .into();
    let missing_reference = function(
        "missing_reference",
        Vec::new(),
        VoidType.into(),
        vec![block(
            "entry",
            vec![IRInstruction::IRCallIndirect {
                callee: value("missing_ref", signature),
                arguments: Vec::new(),
                result: None,
            }],
        )],
    );
    assert!(matches!(
        verify_function_ssa(&missing_reference).unwrap_err(),
        FunctionSSAError::Block { source, .. }
            if source.ssa_identifier == "missing_ref"
                && matches!(source.source, SSADefinitionError::UndefinedReference { .. })
    ));

    let resultless = function(
        "resultless",
        vec![IRParameter::new("input", IntType.into())],
        IntType.into(),
        vec![block(
            "entry",
            vec![
                IRInstruction::IRPrint {
                    value: int("input"),
                    newline: true,
                    aggregate_shape: None,
                },
                ret(Some(int("printed"))),
            ],
        )],
    );
    assert!(matches!(
        verify_function_ssa(&resultless).unwrap_err(),
        FunctionSSAError::Block { source, .. }
            if source.ssa_identifier == "printed"
    ));
}

#[test]
fn rejects_reference_type_mismatch_as_invalid_name_resolution() {
    let function = function(
        "reference_type",
        Vec::new(),
        StringType.into(),
        vec![block(
            "entry",
            vec![
                constant("value", 1),
                ret(Some(value("value", StringType.into()))),
            ],
        )],
    );

    assert!(matches!(
        verify_function_ssa(&function).unwrap_err(),
        FunctionSSAError::Block { source, .. }
            if matches!(
                source.source,
                SSADefinitionError::ReferenceTypeMismatch {
                    expected: IRType::Int(_),
                    actual: IRType::String(_),
                    ..
                }
            )
    ));
}

#[test]
fn diagnostics_are_deterministic_across_repeated_verification() {
    let module = module(vec![function(
        "repeatable",
        Vec::new(),
        IntType.into(),
        vec![
            block("entry", vec![constant("duplicate", 1)]),
            block("later", vec![constant("duplicate", 2)]),
        ],
    )]);
    let expected = verify_module_ssa(&module).unwrap_err();

    for _ in 0..32 {
        assert_eq!(verify_module_ssa(&module).unwrap_err(), expected);
    }
}

#[test]
fn error_source_chain_is_complete_and_downcastable() {
    let module = module(vec![function(
        "chain",
        Vec::new(),
        IntType.into(),
        vec![block("entry", vec![ret(Some(int("missing")))])],
    )]);
    let module_error = verify_module_ssa(&module).unwrap_err();

    let function_error = module_error
        .source()
        .and_then(|source| source.downcast_ref::<FunctionSSAError>())
        .expect("module source should be FunctionSSAError");
    let block_error = function_error
        .source()
        .and_then(|source| source.downcast_ref::<BlockSSAError>())
        .expect("function source should be BlockSSAError");
    let leaf = block_error
        .source()
        .and_then(|source| source.downcast_ref::<SSADefinitionError>())
        .expect("block source should be SSADefinitionError");

    assert!(matches!(
        leaf,
        SSADefinitionError::UndefinedReference { ssa_identifier, .. }
            if ssa_identifier == "missing"
    ));
    assert!(leaf.source().is_none());
}
