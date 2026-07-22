//! Focused block-local storage lifecycle verifier coverage.

use std::error::Error as _;

use aether_ir::{
    BoolType, ClassRefType, IRBasicBlock, IRConstant, IRFunction, IRInstruction, IRModule,
    IRParameter, IRStorage, IRStructDefinition, IRType, IRValue, IntType, MatrixType, StringType,
    StructType, VoidType,
};
use aether_verifier::{
    BlockLifecycleError, FunctionLifecycleError, InstructionKind, LifecycleOperation,
    LifecycleRuleError, LifecycleStorageRole, LocalSlotState, verify_function_local_lifecycle,
    verify_module_local_lifecycle,
};

fn int_value(name: &str) -> IRValue {
    IRValue::new(name, IntType.into())
}

fn storage(name: &str, r#type: IRType) -> IRStorage {
    IRStorage::new(name, r#type)
}

fn int_storage(name: &str) -> IRStorage {
    storage(name, IntType.into())
}

fn init(target: &IRStorage) -> IRInstruction {
    IRInstruction::IRInitDefault {
        destination: target.clone(),
        source_location: None,
    }
}

fn load(result: &str, target: &IRStorage) -> IRInstruction {
    IRInstruction::IRLoad {
        result: IRValue::new(result, target.r#type.clone()),
        slot: target.into(),
    }
}

fn assign(target: &IRStorage, source: IRValue) -> IRInstruction {
    IRInstruction::IRAssign {
        destination: target.clone(),
        source: source.into(),
        source_location: None,
    }
}

fn copy_from_storage(destination: &IRStorage, source: &IRStorage) -> IRInstruction {
    IRInstruction::IRCopyInit {
        destination: destination.clone(),
        source: source.clone().into(),
        source_location: None,
    }
}

fn assign_from_storage(destination: &IRStorage, source: &IRStorage) -> IRInstruction {
    IRInstruction::IRAssign {
        destination: destination.clone(),
        source: source.clone().into(),
        source_location: None,
    }
}

fn destroy(target: &IRStorage) -> IRInstruction {
    IRInstruction::IRDestroy {
        value: target.clone(),
        source_location: None,
    }
}

fn ret() -> IRInstruction {
    IRInstruction::IRReturn {
        value: None,
        transferred_storage: None,
    }
}

fn block(name: &str, instructions: Vec<IRInstruction>) -> IRBasicBlock {
    IRBasicBlock {
        name: name.to_owned(),
        instructions,
    }
}

fn function(name: &str, parameters: Vec<IRParameter>, blocks: Vec<IRBasicBlock>) -> IRFunction {
    IRFunction {
        name: name.to_owned(),
        parameters,
        return_type: VoidType.into(),
        blocks,
    }
}

fn module(function: IRFunction) -> IRModule {
    IRModule {
        functions: vec![function],
        structs: Vec::new(),
    }
}

fn function_error(module: &IRModule) -> FunctionLifecycleError {
    verify_function_local_lifecycle(module, &module.functions[0]).unwrap_err()
}

fn block_error(error: &FunctionLifecycleError) -> &BlockLifecycleError {
    &error.source
}

#[test]
fn accepts_valid_local_sequences_for_trivial_managed_and_independent_storage() {
    let first = int_storage("first");
    let second = storage("second", StringType.into());
    let function = function(
        "valid",
        vec![IRParameter::new("input", IntType.into())],
        vec![block(
            "entry",
            vec![
                IRInstruction::IRCopyInit {
                    destination: first.clone(),
                    source: int_value("input").into(),
                    source_location: None,
                },
                load("read", &first),
                assign(&first, int_value("input")),
                init(&second),
                destroy(&second),
                destroy(&first),
                ret(),
            ],
        )],
    );
    let module = module(function);

    assert_eq!(verify_module_local_lifecycle(&module), Ok(()));
    assert_eq!(
        verify_function_local_lifecycle(&module, &module.functions[0]),
        Ok(())
    );
}

#[test]
fn accepts_copy_init_and_assign_from_live_storage_including_managed_types() {
    let source = storage("source", StringType.into());
    let copy = storage("copy", StringType.into());
    let function = function(
        "storage_sources",
        Vec::new(),
        vec![block(
            "entry",
            vec![
                init(&source),
                copy_from_storage(&copy, &source),
                assign_from_storage(&copy, &source),
                destroy(&copy),
                destroy(&source),
                ret(),
            ],
        )],
    );

    assert_eq!(verify_module_local_lifecycle(&module(function)), Ok(()));
}

#[test]
fn rejects_uninitialized_storage_sources_for_copy_init_and_assign() {
    let source = int_storage("source");
    let copy_destination = int_storage("copy_destination");
    let copy = module(function(
        "copy_uninitialized_source",
        Vec::new(),
        vec![block(
            "entry",
            vec![copy_from_storage(&copy_destination, &source), ret()],
        )],
    ));
    assert!(matches!(
        block_error(&function_error(&copy)).source,
        LifecycleRuleError::UseBeforeInitialization {
            operation: LifecycleOperation::CopyInit,
            role: LifecycleStorageRole::Source,
            ..
        }
    ));

    let assign_destination = int_storage("assign_destination");
    let assignment = module(function(
        "assign_uninitialized_source",
        Vec::new(),
        vec![block(
            "entry",
            vec![
                init(&assign_destination),
                assign_from_storage(&assign_destination, &source),
                ret(),
            ],
        )],
    ));
    assert!(matches!(
        block_error(&function_error(&assignment)).source,
        LifecycleRuleError::UseBeforeInitialization {
            operation: LifecycleOperation::Assign,
            role: LifecycleStorageRole::Source,
            ..
        }
    ));
}

#[test]
fn rejects_moved_and_destroyed_storage_sources_for_copy_init_and_assign() {
    for previous_state in [LocalSlotState::Moved, LocalSlotState::Destroyed] {
        for assign_operation in [false, true] {
            let source = int_storage("source");
            let consumed = int_storage("consumed");
            let destination = int_storage("destination");
            let invalidation = match previous_state {
                LocalSlotState::Moved => IRInstruction::IRMoveInit {
                    destination: consumed,
                    source: source.clone(),
                    source_location: None,
                },
                LocalSlotState::Destroyed => destroy(&source),
                _ => unreachable!(),
            };
            let operation = if assign_operation {
                assign_from_storage(&destination, &source)
            } else {
                copy_from_storage(&destination, &source)
            };
            let mut instructions = vec![init(&source), invalidation];
            if assign_operation {
                instructions.push(init(&destination));
            }
            instructions.extend([operation, ret()]);
            let module = module(function(
                "invalid_storage_source",
                Vec::new(),
                vec![block("entry", instructions)],
            ));

            assert!(matches!(
                block_error(&function_error(&module)).source,
                LifecycleRuleError::UseAfterLocalInvalidation {
                    role: LifecycleStorageRole::Source,
                    previous_state: actual,
                    ..
                } if actual == previous_state
            ));
        }
    }
}

#[test]
fn parameters_are_values_and_raw_store_initializes_or_overwrites_a_slot() {
    let slot = int_storage("input");
    let function = function(
        "parameter_namespace",
        vec![IRParameter::new("input", IntType.into())],
        vec![block(
            "entry",
            vec![
                IRInstruction::IRStore {
                    slot: (&slot).into(),
                    value: int_value("input"),
                },
                IRInstruction::IRStore {
                    slot: (&slot).into(),
                    value: int_value("input"),
                },
                load("loaded", &slot),
                destroy(&slot),
                ret(),
            ],
        )],
    );

    assert_eq!(verify_module_local_lifecycle(&module(function)), Ok(()));
}

#[test]
fn non_entry_unknown_accepts_incoming_state_but_local_transition_becomes_certain() {
    let slot = int_storage("slot");
    let accepted = module(function(
        "unknown_entry",
        Vec::new(),
        vec![block(
            "merge",
            vec![
                load("incoming", &slot),
                assign(&slot, int_value("value")),
                destroy(&slot),
            ],
        )],
    ));
    assert_eq!(verify_module_local_lifecycle(&accepted), Ok(()));

    let rejected = module(function(
        "local_fact",
        Vec::new(),
        vec![block("merge", vec![destroy(&slot), load("after", &slot)])],
    ));
    assert!(matches!(
        block_error(&function_error(&rejected)).source,
        LifecycleRuleError::UseAfterLocalInvalidation {
            previous_state: LocalSlotState::Destroyed,
            ..
        }
    ));
}

#[test]
fn rejects_entry_read_before_initialization() {
    let slot = int_storage("slot");
    let module = module(function(
        "read_before_init",
        Vec::new(),
        vec![block("entry", vec![load("loaded", &slot), ret()])],
    ));
    let error = function_error(&module);

    assert!(matches!(
        block_error(&error).source,
        LifecycleRuleError::UseBeforeInitialization {
            operation: LifecycleOperation::Load,
            role: LifecycleStorageRole::Slot,
            previous_state: LocalSlotState::Uninitialized,
            ..
        }
    ));
}

#[test]
fn rejects_read_after_destroy_with_both_exact_locations() {
    let slot = int_storage("slot");
    let module = module(function(
        "read_after_destroy",
        Vec::new(),
        vec![block(
            "entry",
            vec![init(&slot), destroy(&slot), load("loaded", &slot), ret()],
        )],
    ));

    let error = function_error(&module);
    let LifecycleRuleError::UseAfterLocalInvalidation {
        previous_transition,
        current_use,
        previous_state,
        ..
    } = &block_error(&error).source
    else {
        panic!("expected local invalidation error")
    };
    assert_eq!(*previous_state, LocalSlotState::Destroyed);
    assert_eq!(previous_transition.instruction_index, 1);
    assert_eq!(current_use.instruction_index, 2);
    assert_eq!(current_use.instruction_kind, InstructionKind::IRLoad);
}

#[test]
fn move_and_relocate_consume_their_sources_locally() {
    for relocate in [false, true] {
        let source = int_storage("source");
        let destination = int_storage("destination");
        let transfer = if relocate {
            IRInstruction::IRRelocate {
                destination: destination.clone(),
                source: source.clone(),
                count: 1,
                source_location: None,
            }
        } else {
            IRInstruction::IRMoveInit {
                destination: destination.clone(),
                source: source.clone(),
                source_location: None,
            }
        };
        let module = module(function(
            "consume",
            Vec::new(),
            vec![block(
                "entry",
                vec![init(&source), transfer, load("invalid", &source), ret()],
            )],
        ));
        assert!(matches!(
            block_error(&function_error(&module)).source,
            LifecycleRuleError::UseAfterLocalInvalidation {
                previous_state: LocalSlotState::Moved,
                ..
            }
        ));
    }
}

#[test]
fn rejects_double_initialization_assignment_and_destroy_before_initialization() {
    let slot = int_storage("slot");
    let double_init = module(function(
        "double_init",
        Vec::new(),
        vec![block("entry", vec![init(&slot), init(&slot), ret()])],
    ));
    assert!(matches!(
        block_error(&function_error(&double_init)).source,
        LifecycleRuleError::DoubleInitialization { .. }
    ));

    let assignment = module(function(
        "assignment",
        Vec::new(),
        vec![block(
            "entry",
            vec![assign(&slot, int_value("value")), ret()],
        )],
    ));
    assert!(matches!(
        block_error(&function_error(&assignment)).source,
        LifecycleRuleError::AssignmentToUninitialized { .. }
    ));

    let destroy = module(function(
        "destroy",
        Vec::new(),
        vec![block("entry", vec![destroy(&slot), ret()])],
    ));
    assert!(matches!(
        block_error(&function_error(&destroy)).source,
        LifecycleRuleError::DestroyOfUninitialized { .. }
    ));
}

#[test]
fn rejects_double_destroy_and_destroy_after_move_as_distinct_rules() {
    let slot = int_storage("slot");
    let double = module(function(
        "double_destroy",
        Vec::new(),
        vec![block(
            "entry",
            vec![init(&slot), destroy(&slot), destroy(&slot), ret()],
        )],
    ));
    assert!(matches!(
        block_error(&function_error(&double)).source,
        LifecycleRuleError::DoubleDestroy { .. }
    ));

    let destination = int_storage("destination");
    let after_move = module(function(
        "destroy_after_move",
        Vec::new(),
        vec![block(
            "entry",
            vec![
                init(&slot),
                IRInstruction::IRMoveInit {
                    destination,
                    source: slot.clone(),
                    source_location: None,
                },
                destroy(&slot),
                ret(),
            ],
        )],
    ));
    assert!(matches!(
        block_error(&function_error(&after_move)).source,
        LifecycleRuleError::UseAfterLocalInvalidation {
            previous_state: LocalSlotState::Moved,
            ..
        }
    ));
}

#[test]
fn rejects_move_and_relocate_self_alias_and_invalid_relocate_count() {
    let slot = int_storage("slot");
    for instruction in [
        IRInstruction::IRMoveInit {
            destination: slot.clone(),
            source: slot.clone(),
            source_location: None,
        },
        IRInstruction::IRRelocate {
            destination: slot.clone(),
            source: slot.clone(),
            count: 1,
            source_location: None,
        },
    ] {
        let module = module(function(
            "alias",
            Vec::new(),
            vec![block("entry", vec![instruction, ret()])],
        ));
        assert!(matches!(
            block_error(&function_error(&module)).source,
            LifecycleRuleError::ForbiddenSourceDestinationAlias { .. }
        ));
    }

    let destination = int_storage("destination");
    let invalid_count = module(function(
        "count",
        Vec::new(),
        vec![block(
            "entry",
            vec![IRInstruction::IRRelocate {
                destination,
                source: slot,
                count: 0,
                source_location: None,
            }],
        )],
    ));
    assert!(matches!(
        block_error(&function_error(&invalid_count)).source,
        LifecycleRuleError::InvalidRelocateCount { count: 0, .. }
    ));
}

#[test]
fn checks_lifecycle_operation_types_and_python_type_traits() {
    let source = int_storage("source");
    let destination = storage("destination", StringType.into());
    let mismatch = module(function(
        "mismatch",
        Vec::new(),
        vec![block(
            "entry",
            vec![
                init(&source),
                IRInstruction::IRMoveInit {
                    destination,
                    source,
                    source_location: None,
                },
            ],
        )],
    ));
    assert!(matches!(
        block_error(&function_error(&mismatch)).source,
        LifecycleRuleError::OperationTypeMismatch { .. }
    ));

    let class_type: IRType = ClassRefType {
        name: "Object".to_owned(),
    }
    .into();
    let source = storage("source", class_type.clone());
    let destination = storage("destination", class_type);
    let non_relocatable = module(function(
        "non_relocatable",
        Vec::new(),
        vec![block(
            "merge",
            vec![IRInstruction::IRRelocate {
                destination,
                source,
                count: 1,
                source_location: None,
            }],
        )],
    ));
    assert!(matches!(
        block_error(&function_error(&non_relocatable)).source,
        LifecycleRuleError::InvalidLifecycleType {
            operation: LifecycleOperation::Relocate,
            ..
        }
    ));

    let matrix = storage(
        "matrix",
        MatrixType {
            element: Box::new(IntType.into()),
        }
        .into(),
    );
    let no_default = module(function(
        "no_default",
        Vec::new(),
        vec![block("entry", vec![init(&matrix)])],
    ));
    assert!(matches!(
        block_error(&function_error(&no_default)).source,
        LifecycleRuleError::InvalidLifecycleType {
            operation: LifecycleOperation::InitDefault,
            ..
        }
    ));
}

#[test]
fn recursively_classifies_struct_default_and_relocation_traits() {
    let record_type: IRType = StructType {
        name: "Record".to_owned(),
    }
    .into();
    let record = storage("record", record_type.clone());
    let function = function(
        "record",
        Vec::new(),
        vec![block("entry", vec![init(&record), destroy(&record), ret()])],
    );
    let module = IRModule {
        functions: vec![function],
        structs: vec![IRStructDefinition {
            name: "Record".to_owned(),
            fields: vec![
                ("count".to_owned(), IntType.into()),
                ("text".to_owned(), StringType.into()),
            ],
        }],
    };
    assert_eq!(verify_module_local_lifecycle(&module), Ok(()));
}

#[test]
fn validates_return_transfer_state_and_value_type_without_exit_cleanup_analysis() {
    let return_storage = int_storage("return");
    let valid = module(function(
        "valid_transfer",
        Vec::new(),
        vec![block(
            "entry",
            vec![
                init(&return_storage),
                IRInstruction::IRReturn {
                    value: Some(int_value("result").into()),
                    transferred_storage: Some(return_storage.clone()),
                },
            ],
        )],
    ));
    assert_eq!(verify_module_local_lifecycle(&valid), Ok(()));

    let wrong_type = module(function(
        "wrong_transfer_type",
        Vec::new(),
        vec![block(
            "entry",
            vec![
                init(&return_storage),
                IRInstruction::IRReturn {
                    value: Some(IRValue::new("result", StringType.into()).into()),
                    transferred_storage: Some(return_storage),
                },
            ],
        )],
    ));
    assert!(matches!(
        block_error(&function_error(&wrong_type)).source,
        LifecycleRuleError::ReturnTransferTypeMismatch { .. }
    ));
}

#[test]
fn reinitialization_and_raw_store_after_local_invalidation_are_valid() {
    let slot = int_storage("slot");
    let function = function(
        "new_lifetimes",
        Vec::new(),
        vec![block(
            "entry",
            vec![
                init(&slot),
                destroy(&slot),
                init(&slot),
                destroy(&slot),
                IRInstruction::IRStore {
                    slot: (&slot).into(),
                    value: int_value("raw"),
                },
                load("loaded", &slot),
                destroy(&slot),
                ret(),
            ],
        )],
    );

    assert_eq!(verify_module_local_lifecycle(&module(function)), Ok(()));
}

#[test]
fn detects_storage_type_conflicts_without_conflating_the_ssa_namespace() {
    let int_slot = int_storage("same");
    let string_slot = storage("same", StringType.into());
    let conflict = module(function(
        "conflict",
        Vec::new(),
        vec![block(
            "entry",
            vec![init(&int_slot), destroy(&string_slot), ret()],
        )],
    ));
    assert!(matches!(
        block_error(&function_error(&conflict)).source,
        LifecycleRuleError::StorageTypeMismatch { .. }
    ));

    let separate = module(function(
        "separate",
        vec![IRParameter::new("same", IntType.into())],
        vec![block(
            "entry",
            vec![
                IRInstruction::IRCopyInit {
                    destination: int_slot.clone(),
                    source: int_value("same").into(),
                    source_location: None,
                },
                destroy(&int_slot),
                ret(),
            ],
        )],
    ));
    assert_eq!(verify_module_local_lifecycle(&separate), Ok(()));

    let colliding_storage_source = module(function(
        "colliding_storage_source",
        vec![IRParameter::new("same", IntType.into())],
        vec![block(
            "entry",
            vec![
                init(&int_slot),
                destroy(&int_slot),
                copy_from_storage(&int_storage("destination"), &int_slot),
                ret(),
            ],
        )],
    ));
    assert!(matches!(
        block_error(&function_error(&colliding_storage_source)).source,
        LifecycleRuleError::UseAfterLocalInvalidation {
            operation: LifecycleOperation::CopyInit,
            role: LifecycleStorageRole::Source,
            previous_state: LocalSlotState::Destroyed,
            ..
        }
    ));

    let self_assignment = module(function(
        "storage_self_assignment",
        Vec::new(),
        vec![block(
            "entry",
            vec![
                init(&int_slot),
                assign_from_storage(&int_slot, &int_slot),
                ret(),
            ],
        )],
    ));
    assert_eq!(verify_module_local_lifecycle(&self_assignment), Ok(()));
}

#[test]
fn defers_all_cross_block_merge_loop_and_cleanup_decisions() {
    let condition = IRValue::new("condition", BoolType.into());
    let slot = int_storage("slot");
    let cases = vec![
        block(
            "entry",
            vec![IRInstruction::IRBranch {
                condition,
                true_target: "left".to_owned(),
                false_target: "right".to_owned(),
            }],
        ),
        block("left", vec![init(&slot), ret()]),
        block("right", vec![destroy(&slot), ret()]),
        block("merge", vec![load("merged", &slot), ret()]),
        block("loop", vec![load("carried", &slot), ret()]),
    ];
    let module = module(function(
        "deferred",
        vec![IRParameter::new("condition", BoolType.into())],
        cases,
    ));

    assert_eq!(verify_module_local_lifecycle(&module), Ok(()));
}

#[test]
fn diagnostics_are_deterministic_and_keep_complete_downcastable_sources() {
    let first = int_storage("first");
    let second = int_storage("second");
    let module = module(function(
        "ordered",
        Vec::new(),
        vec![block(
            "entry",
            vec![destroy(&first), destroy(&second), ret()],
        )],
    ));

    let first_error = verify_module_local_lifecycle(&module).unwrap_err();
    let repeated = verify_module_local_lifecycle(&module).unwrap_err();
    assert_eq!(first_error, repeated);
    assert_eq!(first_error.source.source.storage_identifier, "first");
    let function_source = first_error
        .source()
        .and_then(|source| source.downcast_ref::<FunctionLifecycleError>())
        .expect("module source must retain the function error");
    let block_source = function_source
        .source()
        .and_then(|source| source.downcast_ref::<BlockLifecycleError>())
        .expect("function source must retain the block error");
    assert!(
        block_source
            .source()
            .is_some_and(|source| { source.downcast_ref::<LifecycleRuleError>().is_some() })
    );
}

#[test]
fn unrelated_malformed_ir_does_not_panic_or_trigger_other_passes() {
    let function = function(
        "standalone",
        Vec::new(),
        vec![block(
            "not_entry",
            vec![
                IRInstruction::IRConst {
                    result: int_value("duplicate"),
                    value: IRConstant::Int(1),
                },
                IRInstruction::IRConst {
                    result: int_value("duplicate"),
                    value: IRConstant::Int(2),
                },
            ],
        )],
    );
    assert_eq!(verify_module_local_lifecycle(&module(function)), Ok(()));
}
