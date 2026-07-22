//! Focused function/block structure and basic-CFG verifier coverage.

use std::error::Error as _;

use aether_ir::{
    BoolType, IRBasicBlock, IRConstant, IRFunction, IRInstruction, IRModule, IRParameter,
    IRStorage, IRStructDefinition, IRValue, IntType, StringType, VoidType,
};
use aether_verifier::{
    ActualBlockTermination, BlockStructureVerificationError, BranchTarget, ControlFlowRuleError,
    FunctionStructureVerificationError, InstructionKind, ModuleStructureVerificationError,
    TerminatorExpectation, verify_function_structure, verify_module_structure, verify_module_types,
};

fn value(name: &str, type_: aether_ir::IRType) -> IRValue {
    IRValue::new(name, type_)
}

fn ret() -> IRInstruction {
    IRInstruction::IRReturn {
        value: None,
        transferred_storage: None,
    }
}

fn jump(target: &str) -> IRInstruction {
    IRInstruction::IRJump {
        target: target.to_owned(),
    }
}

fn branch(
    condition_type: aether_ir::IRType,
    true_target: &str,
    false_target: &str,
) -> IRInstruction {
    IRInstruction::IRBranch {
        condition: value("condition", condition_type),
        true_target: true_target.to_owned(),
        false_target: false_target.to_owned(),
    }
}

fn constant(name: &str) -> IRInstruction {
    IRInstruction::IRConst {
        result: value(name, IntType.into()),
        value: IRConstant::Int(1),
    }
}

fn block(name: &str, instructions: Vec<IRInstruction>) -> IRBasicBlock {
    IRBasicBlock {
        name: name.to_owned(),
        instructions,
    }
}

fn function(name: &str, blocks: Vec<IRBasicBlock>) -> IRFunction {
    IRFunction {
        name: name.to_owned(),
        parameters: Vec::new(),
        return_type: VoidType.into(),
        blocks,
    }
}

fn module(functions: Vec<IRFunction>) -> IRModule {
    IRModule {
        functions,
        structs: Vec::new(),
    }
}

fn block_rule(error: &ModuleStructureVerificationError) -> &ControlFlowRuleError {
    let ModuleStructureVerificationError::Function { source, .. } = error else {
        panic!("expected function context")
    };
    let FunctionStructureVerificationError::Block { source, .. } = source.as_ref() else {
        panic!("expected block context")
    };
    &source.source
}

#[test]
fn accepts_one_block_function_ending_in_return_through_both_public_layers() {
    let module = module(vec![function("main", vec![block("entry", vec![ret()])])]);

    assert_eq!(verify_module_structure(&module), Ok(()));
    assert_eq!(
        verify_function_structure(&module, &module.functions[0]),
        Ok(())
    );
}

#[test]
fn accepts_linear_jumps_boolean_branches_loops_and_multiple_return_blocks() {
    let linear = function(
        "linear",
        vec![
            block("entry", vec![jump("next")]),
            block("next", vec![ret()]),
        ],
    );
    let alternatives = function(
        "alternatives",
        vec![
            block("entry", vec![branch(BoolType.into(), "then", "else")]),
            block("then", vec![ret()]),
            block("else", vec![ret()]),
        ],
    );
    let loop_function = function(
        "loop",
        vec![
            block("entry", vec![jump("condition")]),
            block("condition", vec![branch(BoolType.into(), "body", "exit")]),
            block("body", vec![jump("condition")]),
            block("exit", vec![ret()]),
        ],
    );

    assert_eq!(
        verify_module_structure(&module(vec![linear, alternatives, loop_function])),
        Ok(())
    );
}

#[test]
fn accepts_self_loop() {
    let module = module(vec![function(
        "spin",
        vec![block("entry", vec![jump("entry")])],
    )]);

    assert_eq!(verify_module_structure(&module), Ok(()));
}

#[test]
fn rejects_empty_block_as_missing_terminator() {
    let module = module(vec![function("main", vec![block("entry", Vec::new())])]);
    let error = verify_module_structure(&module).unwrap_err();

    assert_eq!(
        block_rule(&error),
        &ControlFlowRuleError::MissingTerminator {
            expected: TerminatorExpectation::OneFinalControlFlowTerminator,
            actual: ActualBlockTermination::EmptyBlock,
        }
    );
}

#[test]
fn rejects_non_terminator_as_final_instruction() {
    let module = module(vec![function(
        "main",
        vec![block("entry", vec![constant("one")])],
    )]);
    let error = verify_module_structure(&module).unwrap_err();

    assert_eq!(
        block_rule(&error),
        &ControlFlowRuleError::MissingTerminator {
            expected: TerminatorExpectation::OneFinalControlFlowTerminator,
            actual: ActualBlockTermination::NonTerminator {
                final_instruction_kind: InstructionKind::IRConst,
            },
        }
    );
}

#[test]
fn rejects_two_terminators_with_both_instruction_contexts() {
    let module = module(vec![function(
        "main",
        vec![block("entry", vec![ret(), jump("entry")])],
    )]);
    let error = verify_module_structure(&module).unwrap_err();

    assert_eq!(
        block_rule(&error),
        &ControlFlowRuleError::MultipleTerminators {
            first_index: 0,
            first_kind: InstructionKind::IRReturn,
            second_index: 1,
            second_kind: InstructionKind::IRJump,
        }
    );
}

#[test]
fn rejects_instructions_after_each_terminator_kind() {
    for terminator in [
        ret(),
        jump("entry"),
        branch(BoolType.into(), "entry", "entry"),
    ] {
        let expected_kind = match &terminator {
            IRInstruction::IRReturn { .. } => InstructionKind::IRReturn,
            IRInstruction::IRJump { .. } => InstructionKind::IRJump,
            IRInstruction::IRBranch { .. } => InstructionKind::IRBranch,
            _ => unreachable!(),
        };
        let module = module(vec![function(
            "main",
            vec![block("entry", vec![terminator, constant("after")])],
        )]);
        let error = verify_module_structure(&module).unwrap_err();
        assert_eq!(
            block_rule(&error),
            &ControlFlowRuleError::InstructionAfterTerminator {
                terminator_index: 0,
                terminator_kind: expected_kind,
                offending_instruction_index: 1,
                offending_instruction_kind: InstructionKind::IRConst,
            }
        );
    }
}

#[test]
fn rejects_missing_jump_target_and_preserves_exact_name() {
    let module = module(vec![function(
        "main",
        vec![block("entry", vec![jump("Missing.Target")])],
    )]);
    let error = verify_module_structure(&module).unwrap_err();

    assert_eq!(
        block_rule(&error),
        &ControlFlowRuleError::UnknownJumpTarget {
            target: "Missing.Target".to_owned(),
        }
    );
}

#[test]
fn rejects_target_that_exists_only_in_another_function() {
    let module = module(vec![
        function("source", vec![block("entry", vec![jump("foreign")])]),
        function(
            "destination",
            vec![block("entry", vec![ret()]), block("foreign", vec![ret()])],
        ),
    ]);

    assert_eq!(
        block_rule(&verify_module_structure(&module).unwrap_err()),
        &ControlFlowRuleError::UnknownJumpTarget {
            target: "foreign".to_owned(),
        }
    );
}

#[test]
fn rejects_true_then_false_branch_targets_in_field_order() {
    let true_missing = module(vec![function(
        "main",
        vec![
            block(
                "entry",
                vec![branch(BoolType.into(), "missing.true", "else")],
            ),
            block("else", vec![ret()]),
        ],
    )]);
    let false_missing = module(vec![function(
        "main",
        vec![
            block(
                "entry",
                vec![branch(BoolType.into(), "then", "missing.false")],
            ),
            block("then", vec![ret()]),
        ],
    )]);

    assert_eq!(
        block_rule(&verify_module_structure(&true_missing).unwrap_err()),
        &ControlFlowRuleError::UnknownBranchTarget {
            edge: BranchTarget::True,
            target: "missing.true".to_owned(),
        }
    );
    assert_eq!(
        block_rule(&verify_module_structure(&false_missing).unwrap_err()),
        &ControlFlowRuleError::UnknownBranchTarget {
            edge: BranchTarget::False,
            target: "missing.false".to_owned(),
        }
    );
}

#[test]
fn target_matching_is_exact_and_case_sensitive() {
    let module = module(vec![function(
        "main",
        vec![
            block("entry", vec![jump("Target")]),
            block("target", vec![ret()]),
        ],
    )]);

    assert!(matches!(
        block_rule(&verify_module_structure(&module).unwrap_err()),
        ControlFlowRuleError::UnknownJumpTarget { target } if target == "Target"
    ));
}

#[test]
fn rejects_empty_function_missing_entry_and_duplicate_blocks() {
    let empty = module(vec![function("empty", Vec::new())]);
    let ModuleStructureVerificationError::Function { source, .. } =
        verify_module_structure(&empty).unwrap_err()
    else {
        panic!("expected function context")
    };
    assert!(matches!(
        source.as_ref(),
        FunctionStructureVerificationError::EmptyFunction { .. }
    ));

    let missing_entry = module(vec![function(
        "missing_entry",
        vec![block("body", vec![ret()])],
    )]);
    let ModuleStructureVerificationError::Function { source, .. } =
        verify_module_structure(&missing_entry).unwrap_err()
    else {
        panic!("expected function context")
    };
    assert!(matches!(
        source.as_ref(),
        FunctionStructureVerificationError::MissingEntryBlock {
            required_entry_block,
            ..
        } if required_entry_block == "entry"
    ));

    let duplicates = module(vec![function(
        "duplicates",
        vec![block("entry", vec![ret()]), block("entry", vec![ret()])],
    )]);
    let ModuleStructureVerificationError::Function { source, .. } =
        verify_module_structure(&duplicates).unwrap_err()
    else {
        panic!("expected function context")
    };
    assert!(matches!(
        source.as_ref(),
        FunctionStructureVerificationError::DuplicateBlockName {
            block_index: 1,
            earlier_block_index: 0,
            ..
        }
    ));
}

#[test]
fn entry_is_named_entry_but_need_not_be_first() {
    let module = module(vec![function(
        "main",
        vec![block("body", vec![ret()]), block("entry", vec![ret()])],
    )]);

    assert_eq!(verify_module_structure(&module), Ok(()));
}

#[test]
fn unreachable_trailing_block_and_unreachable_cycle_remain_accepted() {
    let module = module(vec![function(
        "main",
        vec![
            block("entry", vec![ret()]),
            block("dead.one", vec![jump("dead.two")]),
            block("dead.two", vec![jump("dead.one")]),
        ],
    )]);

    assert_eq!(verify_module_structure(&module), Ok(()));
}

#[test]
fn accepts_all_blocks_reachable_through_branch_alternatives() {
    let module = module(vec![function(
        "main",
        vec![
            block("entry", vec![branch(BoolType.into(), "left", "right")]),
            block("left", vec![jump("exit")]),
            block("right", vec![jump("exit")]),
            block("exit", vec![ret()]),
        ],
    )]);

    assert_eq!(verify_module_structure(&module), Ok(()));
}

#[test]
fn enforces_module_and_declaration_name_uniqueness_in_python_order() {
    let duplicate_structs = IRModule {
        functions: Vec::new(),
        structs: vec![
            IRStructDefinition {
                name: "Point".to_owned(),
                fields: Vec::new(),
            },
            IRStructDefinition {
                name: "Point".to_owned(),
                fields: Vec::new(),
            },
        ],
    };
    assert!(matches!(
        verify_module_structure(&duplicate_structs),
        Err(ModuleStructureVerificationError::DuplicateStructName {
            struct_index: 1,
            earlier_struct_index: 0,
            ..
        })
    ));

    let duplicate_fields = IRModule {
        functions: Vec::new(),
        structs: vec![IRStructDefinition {
            name: "Point".to_owned(),
            fields: vec![
                ("x".to_owned(), IntType.into()),
                ("x".to_owned(), StringType.into()),
            ],
        }],
    };
    assert!(matches!(
        verify_module_structure(&duplicate_fields),
        Err(ModuleStructureVerificationError::DuplicateStructFieldName {
            field_index: 1,
            earlier_field_index: 0,
            ..
        })
    ));

    let duplicate_functions = module(vec![
        function("same", vec![block("entry", vec![ret()])]),
        function("same", vec![block("entry", vec![ret()])]),
    ]);
    assert!(matches!(
        verify_module_structure(&duplicate_functions),
        Err(ModuleStructureVerificationError::DuplicateFunctionName {
            function_index: 1,
            earlier_function_index: 0,
            ..
        })
    ));

    let mut duplicate_parameters = function("parameters", vec![block("entry", vec![ret()])]);
    duplicate_parameters.parameters = vec![
        IRParameter::new("value", IntType.into()),
        IRParameter::new("value", StringType.into()),
    ];
    let duplicate_parameters = module(vec![duplicate_parameters]);
    let ModuleStructureVerificationError::Function { source, .. } =
        verify_module_structure(&duplicate_parameters).unwrap_err()
    else {
        panic!("expected function context")
    };
    assert!(matches!(
        source.as_ref(),
        FunctionStructureVerificationError::DuplicateParameterName {
            parameter_index: 1,
            earlier_parameter_index: 0,
            ..
        }
    ));
}

#[test]
fn non_boolean_branch_is_type_invalid_but_structurally_valid() {
    let module = module(vec![function(
        "main",
        vec![
            block("entry", vec![branch(IntType.into(), "then", "else")]),
            block("then", vec![ret()]),
            block("else", vec![ret()]),
        ],
    )]);

    assert_eq!(verify_module_structure(&module), Ok(()));
    assert!(verify_module_types(&module).is_err());
}

#[test]
fn type_correct_but_structurally_invalid_function_fails_only_structure() {
    let module = module(vec![function(
        "main",
        vec![block("entry", vec![constant("one")])],
    )]);

    assert_eq!(verify_module_types(&module), Ok(()));
    assert!(verify_module_structure(&module).is_err());
}

#[test]
fn definition_before_use_and_dominance_remain_deferred() {
    let merge_value = value("from_then", IntType.into());
    let mut function = IRFunction::new("main", Vec::new(), IntType.into());
    function.blocks = vec![
        block("entry", vec![branch(BoolType.into(), "then", "else")]),
        block(
            "then",
            vec![
                IRInstruction::IRConst {
                    result: merge_value.clone(),
                    value: IRConstant::Int(1),
                },
                jump("merge"),
            ],
        ),
        block("else", vec![jump("merge")]),
        block(
            "merge",
            vec![IRInstruction::IRReturn {
                value: Some(merge_value.into()),
                transferred_storage: None,
            }],
        ),
    ];
    let module = module(vec![function]);

    assert_eq!(verify_module_structure(&module), Ok(()));
}

#[test]
fn ownership_and_lifecycle_violations_remain_deferred() {
    let storage = IRStorage::new("slot", StringType.into());
    let module = module(vec![function(
        "main",
        vec![block(
            "entry",
            vec![
                IRInstruction::IRDestroy {
                    value: storage.clone(),
                    source_location: None,
                },
                IRInstruction::IRDestroy {
                    value: storage,
                    source_location: None,
                },
                ret(),
            ],
        )],
    )]);

    assert_eq!(verify_module_structure(&module), Ok(()));
}

#[test]
fn errors_retain_full_context_and_complete_source_chain() {
    let module = module(vec![function(
        "context",
        vec![block("entry", vec![jump("raw.target")])],
    )]);
    let error = verify_module_structure(&module).unwrap_err();
    let ModuleStructureVerificationError::Function {
        function_index,
        function_name,
        source,
    } = &error
    else {
        panic!("expected function context")
    };
    let FunctionStructureVerificationError::Block {
        block_index,
        block_name,
        source: block_source,
        ..
    } = source.as_ref()
    else {
        panic!("expected block context")
    };

    assert_eq!((*function_index, function_name.as_str()), (0, "context"));
    assert_eq!((*block_index, block_name.as_str()), (0, "entry"));
    assert_eq!(block_source.function_name, "context");
    assert_eq!(block_source.block_name, "entry");
    assert_eq!(block_source.instruction_index, Some(0));
    assert_eq!(block_source.instruction_kind, Some(InstructionKind::IRJump));
    assert!(error.source().is_some());
    assert!(error.source().and_then(|nested| nested.source()).is_some());
    assert!(
        error
            .source()
            .and_then(|nested| nested.source())
            .and_then(|nested| nested.source())
            .is_some()
    );
    assert!(matches!(
        block_source.source,
        ControlFlowRuleError::UnknownJumpTarget { ref target } if target == "raw.target"
    ));
}

#[test]
fn first_error_selection_is_stable_in_source_order() {
    let module = module(vec![function(
        "stable",
        vec![
            block("entry", vec![branch(BoolType.into(), "z", "a")]),
            block("later", vec![constant("unterminated")]),
        ],
    )]);
    let expected = verify_module_structure(&module).unwrap_err();

    for _ in 0..32 {
        assert_eq!(verify_module_structure(&module), Err(expected.clone()));
    }
    assert_eq!(
        block_rule(&expected),
        &ControlFlowRuleError::UnknownBranchTarget {
            edge: BranchTarget::True,
            target: "z".to_owned(),
        }
    );
}

#[test]
fn block_error_type_is_downcastable_from_function_source() {
    let module = module(vec![function("main", vec![block("entry", Vec::new())])]);
    let error = verify_module_structure(&module).unwrap_err();
    let function_source = error.source().expect("function source");
    let block_source = function_source.source().expect("block source");

    assert!(
        block_source
            .downcast_ref::<BlockStructureVerificationError>()
            .is_some()
    );
}
