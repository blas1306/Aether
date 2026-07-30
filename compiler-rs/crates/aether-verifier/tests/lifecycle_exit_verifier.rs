//! Reachable function-exit ownership-completeness coverage.

use std::error::Error as _;

use aether_ir::{
    ArrayType, BoolType, IRBasicBlock, IRConstant, IRFunction, IRInstruction, IRModule, IRStorage,
    IRStructDefinition, IRType, IRValue, IntType, ListType, StringType, StructType, VoidType,
};
use aether_verifier::{
    BlockLifecycleError, FunctionLifecycleVerificationError, LifecycleRuleError, LocalSlotState,
    ModuleLifecycleVerificationError, OwnershipCompletionReason, verify_function_lifecycle,
    verify_module_lifecycle,
};

fn storage(name: &str, r#type: IRType) -> IRStorage {
    IRStorage::new(name, r#type)
}

fn init(target: &IRStorage) -> IRInstruction {
    IRInstruction::IRInitDefault {
        destination: target.clone(),
        source_location: None,
    }
}

fn destroy(target: &IRStorage) -> IRInstruction {
    IRInstruction::IRDestroy {
        value: target.clone(),
        source_location: None,
    }
}

fn move_init(destination: &IRStorage, source: &IRStorage) -> IRInstruction {
    IRInstruction::IRMoveInit {
        destination: destination.clone(),
        source: source.clone(),
        source_location: None,
    }
}

fn load(result: &str, source: &IRStorage) -> (IRValue, IRInstruction) {
    let result = IRValue::new(result, source.r#type.clone());
    let instruction = IRInstruction::IRLoad {
        result: result.clone(),
        slot: source.into(),
    };
    (result, instruction)
}

fn string_constant(name: &str) -> (IRValue, IRInstruction) {
    let result = IRValue::new(name, StringType.into());
    let instruction = IRInstruction::IRConst {
        result: result.clone(),
        value: IRConstant::String("unrelated value".to_owned()),
    };
    (result, instruction)
}

fn branch(true_target: &str, false_target: &str) -> IRInstruction {
    IRInstruction::IRBranch {
        condition: IRValue::new("condition", BoolType.into()),
        true_target: true_target.to_owned(),
        false_target: false_target.to_owned(),
    }
}

fn jump(target: &str) -> IRInstruction {
    IRInstruction::IRJump {
        target: target.to_owned(),
    }
}

fn ret() -> IRInstruction {
    IRInstruction::IRReturn {
        value: None,
        transferred_storage: None,
    }
}

fn transferred_ret(value: IRValue, storage: &IRStorage) -> IRInstruction {
    IRInstruction::IRReturn {
        value: Some(value.into()),
        transferred_storage: Some(storage.clone()),
    }
}

fn block(name: &str, instructions: Vec<IRInstruction>) -> IRBasicBlock {
    IRBasicBlock {
        name: name.to_owned(),
        instructions,
    }
}

fn module(blocks: Vec<IRBasicBlock>, structs: Vec<IRStructDefinition>) -> IRModule {
    IRModule {
        functions: vec![IRFunction {
            name: "owner".to_owned(),
            parameters: Vec::new(),
            return_type: VoidType.into(),
            blocks,
            may_throw: false,
        }],
        structs,
    }
}

fn rule(error: &FunctionLifecycleVerificationError) -> &LifecycleRuleError {
    let FunctionLifecycleVerificationError::Block { source, .. } = error else {
        panic!("expected block lifecycle error")
    };
    &source.source
}

fn block_error(error: &FunctionLifecycleVerificationError) -> &BlockLifecycleError {
    let FunctionLifecycleVerificationError::Block { source, .. } = error else {
        panic!("expected block lifecycle error")
    };
    source
}

#[test]
fn accepts_destroyed_managed_and_trivial_locals_before_void_return() {
    for r#type in [IRType::from(StringType), IRType::from(IntType)] {
        let slot = storage("local", r#type);
        let module = module(
            vec![block("entry", vec![init(&slot), destroy(&slot), ret()])],
            Vec::new(),
        );
        assert_eq!(verify_module_lifecycle(&module), Ok(()));
    }
}

#[test]
fn accepts_moved_string_ownership_returned_from_the_exact_destination() {
    let source = storage("source", StringType.into());
    let result = storage("$return", StringType.into());
    let (returned, load_result) = load("returned", &result);
    let mut module = module(
        vec![block(
            "entry",
            vec![
                init(&source),
                move_init(&result, &source),
                load_result,
                transferred_ret(returned, &result),
            ],
        )],
        Vec::new(),
    );
    module.functions[0].return_type = StringType.into();

    assert_eq!(verify_module_lifecycle(&module), Ok(()));
}

#[test]
fn accepts_live_transfer_with_same_typed_value_without_storage_provenance() {
    let transferred = storage("transferred", StringType.into());
    let (unrelated, define_unrelated) = string_constant("unrelated_same_typed_value");
    let mut module = module(
        vec![block(
            "entry",
            vec![
                define_unrelated,
                init(&transferred),
                transferred_ret(unrelated, &transferred),
            ],
        )],
        Vec::new(),
    );
    module.functions[0].return_type = StringType.into();

    assert_eq!(verify_module_lifecycle(&module), Ok(()));
}

#[test]
fn transferring_one_of_two_live_same_typed_owners_still_rejects_the_other() {
    let transferred = storage("transferred", StringType.into());
    let leaked = storage("leaked", StringType.into());
    let (unrelated, define_unrelated) = string_constant("unrelated_same_typed_value");
    let mut module = module(
        vec![block(
            "entry",
            vec![
                define_unrelated,
                init(&transferred),
                init(&leaked),
                transferred_ret(unrelated, &transferred),
            ],
        )],
        Vec::new(),
    );
    module.functions[0].return_type = StringType.into();

    let error = verify_function_lifecycle(&module, &module.functions[0]).unwrap_err();
    assert_eq!(block_error(&error).storage_identifier, "leaked");
    assert!(matches!(
        rule(&error),
        LifecycleRuleError::IncompleteOwnershipAtExit { .. }
    ));
}

#[test]
fn accepts_nested_managed_aggregate_moved_into_return_storage() {
    let definition = IRStructDefinition {
        name: "Envelope".to_owned(),
        fields: vec![(
            "messages".to_owned(),
            ListType {
                element: Box::new(StringType.into()),
            }
            .into(),
        )],
    };
    let aggregate_type: IRType = StructType {
        name: "Envelope".to_owned(),
    }
    .into();
    let source = storage("source", aggregate_type.clone());
    let result = storage("$return", aggregate_type.clone());
    let (returned, load_result) = load("returned", &result);
    let mut module = module(
        vec![block(
            "entry",
            vec![
                init(&source),
                move_init(&result, &source),
                load_result,
                transferred_ret(returned, &result),
            ],
        )],
        vec![definition],
    );
    module.functions[0].return_type = aggregate_type;

    assert_eq!(verify_module_lifecycle(&module), Ok(()));
}

#[test]
fn accepts_multiple_early_exits_with_destroy_or_conditional_transfer() {
    let slot = storage("value", StringType.into());
    let (returned, load_value) = load("returned", &slot);
    let mut module = module(
        vec![
            block("entry", vec![init(&slot), branch("transfer", "cleanup")]),
            block(
                "transfer",
                vec![load_value, transferred_ret(returned, &slot)],
            ),
            block("cleanup", vec![destroy(&slot), ret()]),
        ],
        Vec::new(),
    );
    // This intentionally exercises only lifecycle verification: return typing
    // is an independently callable pass.
    module.functions[0].return_type = StringType.into();

    assert_eq!(verify_module_lifecycle(&module), Ok(()));
}

#[test]
fn accepts_nested_managed_struct_array_and_list_cleanup() {
    let inner = IRStructDefinition {
        name: "Inner".to_owned(),
        fields: vec![("text".to_owned(), StringType.into())],
    };
    let outer = IRStructDefinition {
        name: "Outer".to_owned(),
        fields: vec![
            (
                "inner".to_owned(),
                StructType {
                    name: "Inner".to_owned(),
                }
                .into(),
            ),
            (
                "items".to_owned(),
                ListType {
                    element: Box::new(StringType.into()),
                }
                .into(),
            ),
        ],
    };
    let slots = [
        storage(
            "aggregate",
            StructType {
                name: "Outer".to_owned(),
            }
            .into(),
        ),
        storage(
            "array",
            ArrayType {
                element: Box::new(StringType.into()),
            }
            .into(),
        ),
        storage(
            "list",
            ListType {
                element: Box::new(StringType.into()),
            }
            .into(),
        ),
    ];
    let mut instructions = Vec::new();
    for slot in &slots {
        instructions.push(init(slot));
    }
    for slot in slots.iter().rev() {
        instructions.push(destroy(slot));
    }
    instructions.push(ret());
    let module = module(vec![block("entry", instructions)], vec![inner, outer]);

    assert_eq!(verify_module_lifecycle(&module), Ok(()));
}

#[test]
fn rejects_leaked_string_array_list_struct_and_trivial_lifecycle_storage() {
    let managed_struct = IRStructDefinition {
        name: "Managed".to_owned(),
        fields: vec![("text".to_owned(), StringType.into())],
    };
    let cases = [
        (IRType::from(StringType), true),
        (
            IRType::from(ArrayType {
                element: Box::new(StringType.into()),
            }),
            true,
        ),
        (
            IRType::from(ListType {
                element: Box::new(IntType.into()),
            }),
            true,
        ),
        (
            IRType::from(StructType {
                name: "Managed".to_owned(),
            }),
            true,
        ),
        (IRType::from(IntType), false),
    ];

    for (r#type, managed) in cases {
        let slot = storage("leaked", r#type);
        let module = module(
            vec![block("entry", vec![init(&slot), ret()])],
            vec![managed_struct.clone()],
        );
        let error = verify_function_lifecycle(&module, &module.functions[0]).unwrap_err();
        let LifecycleRuleError::IncompleteOwnershipAtExit {
            storage_identifier,
            storage_type,
            exit_block,
            terminal_states,
            expected_terminal_states,
            ownership_reason,
            last_transition,
            ..
        } = rule(&error)
        else {
            panic!("expected ownership-completion error")
        };
        assert_eq!(storage_identifier, "leaked");
        assert_eq!(storage_type, &slot.r#type);
        assert_eq!(exit_block, "entry");
        assert!(terminal_states.may_be_initialized);
        assert!(!expected_terminal_states.may_be_initialized);
        assert!(last_transition.is_some());
        assert_eq!(
            *ownership_reason,
            if managed {
                OwnershipCompletionReason::ManagedStorageRequiresCleanup
            } else {
                OwnershipCompletionReason::TrivialLifecycleStorageRequiresCompletion
            }
        );
    }
}

#[test]
fn rejects_partially_destroyed_aggregate_at_join() {
    let definition = IRStructDefinition {
        name: "Managed".to_owned(),
        fields: vec![("text".to_owned(), StringType.into())],
    };
    let slot = storage(
        "aggregate",
        StructType {
            name: "Managed".to_owned(),
        }
        .into(),
    );
    let module = module(
        vec![
            block("entry", vec![init(&slot), branch("destroyed", "live")]),
            block("destroyed", vec![destroy(&slot), jump("exit")]),
            block("live", vec![jump("exit")]),
            block("exit", vec![ret()]),
        ],
        vec![definition],
    );

    let error = verify_function_lifecycle(&module, &module.functions[0]).unwrap_err();
    let LifecycleRuleError::IncompleteOwnershipAtExit {
        terminal_states, ..
    } = rule(&error)
    else {
        panic!("expected ownership-completion error")
    };
    assert!(terminal_states.may_be_initialized);
    assert!(terminal_states.may_be_destroyed);
    assert_eq!(block_error(&error).block_name, "exit");
}

#[test]
fn rejects_moved_source_named_as_return_transfer_and_type_invalid_transfer() {
    let source = storage("source", StringType.into());
    let destination = storage("destination", StringType.into());
    let (returned, define_returned) = string_constant("returned");
    let moved_source = module(
        vec![block(
            "entry",
            vec![
                define_returned,
                init(&source),
                move_init(&destination, &source),
                transferred_ret(returned, &source),
            ],
        )],
        Vec::new(),
    );
    let error = verify_function_lifecycle(&moved_source, &moved_source.functions[0]).unwrap_err();
    assert!(matches!(
        rule(&error),
        LifecycleRuleError::UseAfterLocalInvalidation {
            previous_state: LocalSlotState::Moved,
            ..
        }
    ));

    let destroyed = storage("destroyed", StringType.into());
    let (returned, define_returned) = string_constant("destroyed_returned");
    let destroyed_source = module(
        vec![block(
            "entry",
            vec![
                define_returned,
                init(&destroyed),
                destroy(&destroyed),
                transferred_ret(returned, &destroyed),
            ],
        )],
        Vec::new(),
    );
    let error =
        verify_function_lifecycle(&destroyed_source, &destroyed_source.functions[0]).unwrap_err();
    assert!(matches!(
        rule(&error),
        LifecycleRuleError::UseAfterLocalInvalidation {
            previous_state: LocalSlotState::Destroyed,
            ..
        }
    ));

    let live = storage("live", StringType.into());
    let wrong = IRValue::new("wrong", IntType.into());
    let invalid_type = module(
        vec![block(
            "entry",
            vec![
                IRInstruction::IRConst {
                    result: wrong.clone(),
                    value: IRConstant::Int(1),
                },
                init(&live),
                transferred_ret(wrong, &live),
            ],
        )],
        Vec::new(),
    );
    let error = verify_function_lifecycle(&invalid_type, &invalid_type.functions[0]).unwrap_err();
    assert!(matches!(
        rule(&error),
        LifecycleRuleError::ReturnTransferTypeMismatch { .. }
    ));
}

#[test]
fn rejects_first_leaking_reachable_exit_even_when_another_exit_is_valid() {
    let slot = storage("local", StringType.into());
    let module = module(
        vec![
            block("entry", vec![init(&slot), branch("valid", "leak")]),
            block("valid", vec![destroy(&slot), ret()]),
            block("leak", vec![ret()]),
        ],
        Vec::new(),
    );

    let error = verify_function_lifecycle(&module, &module.functions[0]).unwrap_err();
    assert_eq!(block_error(&error).block_name, "leak");
}

#[test]
fn ignores_ownership_completion_for_unreachable_exits_but_keeps_local_checks() {
    let slot = storage("local", StringType.into());
    let module = module(
        vec![
            block("entry", vec![init(&slot), destroy(&slot), ret()]),
            // With Python's unreachable seed this exit is locally live, but it
            // is not an executable function exit and therefore is ignored.
            block("dead_leak", vec![ret()]),
            block("dead_valid", vec![destroy(&slot), ret()]),
        ],
        Vec::new(),
    );

    assert_eq!(verify_module_lifecycle(&module), Ok(()));
}

#[test]
fn ownership_error_chain_is_deterministic_and_downcastable() {
    let transferred = storage("transferred", StringType.into());
    let later_name = storage("zeta", StringType.into());
    let first_name = storage("alpha", StringType.into());
    let (unrelated, define_unrelated) = string_constant("unrelated_same_typed_value");
    let mut module = module(
        vec![block(
            "entry",
            vec![
                define_unrelated,
                init(&transferred),
                init(&later_name),
                init(&first_name),
                transferred_ret(unrelated, &transferred),
            ],
        )],
        Vec::new(),
    );
    module.functions[0].return_type = StringType.into();
    let first = verify_module_lifecycle(&module).unwrap_err();
    let repeated = verify_module_lifecycle(&module).unwrap_err();
    assert_eq!(first, repeated);
    assert!(first.to_string().contains("terminal lifecycle state"));

    let function = first
        .source()
        .and_then(|source| source.downcast_ref::<FunctionLifecycleVerificationError>())
        .expect("module error must retain function source");
    let block = function
        .source()
        .and_then(|source| source.downcast_ref::<BlockLifecycleError>())
        .expect("function error must retain block source");
    assert_eq!(block.storage_identifier, "alpha");
    assert!(
        block
            .source()
            .is_some_and(|source| source.downcast_ref::<LifecycleRuleError>().is_some())
    );
    let _: &ModuleLifecycleVerificationError = &first;
}
