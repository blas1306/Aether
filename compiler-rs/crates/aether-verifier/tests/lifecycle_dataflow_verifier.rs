//! Function-wide lifecycle data-flow, join, loop, and reachability coverage.

use std::error::Error as _;

use aether_ir::{
    BoolType, IRBasicBlock, IRFunction, IRInstruction, IRModule, IRStorage, IRType, IRValue,
    IntType, StringType, VoidType,
};
use aether_verifier::{
    BlockLifecycleError, FunctionLifecycleVerificationError, LifecycleOperation,
    LifecycleRuleError, LifecycleStorageRole, LocalSlotState, verify_function_lifecycle,
    verify_module_lifecycle,
};

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

fn destroy(target: &IRStorage) -> IRInstruction {
    IRInstruction::IRDestroy {
        value: target.clone(),
        source_location: None,
    }
}

fn store(target: &IRStorage) -> IRInstruction {
    IRInstruction::IRStore {
        slot: target.clone().into(),
        value: IRValue::new("input", target.r#type.clone()),
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

fn move_init(destination: &IRStorage, source: &IRStorage) -> IRInstruction {
    IRInstruction::IRMoveInit {
        destination: destination.clone(),
        source: source.clone(),
        source_location: None,
    }
}

fn jump(target: &str) -> IRInstruction {
    IRInstruction::IRJump {
        target: target.to_owned(),
    }
}

fn branch(true_target: &str, false_target: &str) -> IRInstruction {
    IRInstruction::IRBranch {
        condition: IRValue::new("condition", BoolType.into()),
        true_target: true_target.to_owned(),
        false_target: false_target.to_owned(),
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

fn module(blocks: Vec<IRBasicBlock>) -> IRModule {
    IRModule {
        functions: vec![IRFunction {
            name: "main".to_owned(),
            parameters: Vec::new(),
            return_type: VoidType.into(),
            blocks,
        }],
        structs: Vec::new(),
    }
}

fn rule(error: &FunctionLifecycleVerificationError) -> &LifecycleRuleError {
    let FunctionLifecycleVerificationError::Block { source, .. } = error else {
        panic!("expected lifecycle block error")
    };
    &source.source
}

fn block_error(error: &FunctionLifecycleVerificationError) -> &BlockLifecycleError {
    let FunctionLifecycleVerificationError::Block { source, .. } = error else {
        panic!("expected lifecycle block error")
    };
    source
}

#[test]
fn accepts_initialization_on_all_predecessors_and_entry_not_first() {
    let slot = int_storage("slot");
    let module = module(vec![
        block("left", vec![init(&slot), jump("merge")]),
        block("merge", vec![load("read", &slot), ret()]),
        block("entry", vec![branch("left", "right")]),
        block("right", vec![init(&slot), jump("merge")]),
    ]);

    assert_eq!(verify_module_lifecycle(&module), Ok(()));
}

#[test]
fn rejects_read_when_only_one_predecessor_initializes() {
    let slot = int_storage("slot");
    let module = module(vec![
        block("entry", vec![branch("left", "right")]),
        block("left", vec![init(&slot), jump("merge")]),
        block("right", vec![jump("merge")]),
        block("merge", vec![load("read", &slot), ret()]),
    ]);

    let error = verify_function_lifecycle(&module, &module.functions[0]).unwrap_err();
    let LifecycleRuleError::InvalidMergedState {
        operation,
        role,
        possible_states,
        required_state,
        ..
    } = rule(&error)
    else {
        panic!("expected merged-state diagnostic")
    };
    assert_eq!(*operation, LifecycleOperation::Load);
    assert_eq!(*role, LifecycleStorageRole::Slot);
    assert!(possible_states.may_be_initialized);
    assert!(possible_states.may_be_uninitialized);
    assert_eq!(*required_state, LocalSlotState::Initialized);
}

#[test]
fn raw_store_repairs_divergent_incoming_state() {
    let slot = int_storage("slot");
    let module = module(vec![
        block("entry", vec![branch("left", "right")]),
        block("left", vec![init(&slot), jump("merge")]),
        block("right", vec![jump("merge")]),
        block("merge", vec![store(&slot), load("read", &slot), ret()]),
    ]);

    assert_eq!(verify_module_lifecycle(&module), Ok(()));
}

#[test]
fn raw_store_repairs_every_divergent_state_for_trivial_and_managed_slots() {
    for r#type in [IRType::from(IntType), IRType::from(StringType)] {
        for incoming in [
            LocalSlotState::Uninitialized,
            LocalSlotState::Moved,
            LocalSlotState::Destroyed,
        ] {
            let slot = storage("slot", r#type.clone());
            let consumed = storage("consumed", r#type.clone());
            let mut entry = Vec::new();
            let mut left = Vec::new();
            let mut right = Vec::new();
            if incoming == LocalSlotState::Uninitialized {
                left.push(init(&slot));
            } else {
                entry.push(init(&slot));
                if incoming == LocalSlotState::Moved {
                    right.push(move_init(&consumed, &slot));
                    right.push(destroy(&consumed));
                } else {
                    right.push(destroy(&slot));
                }
            }
            entry.push(branch("left", "right"));
            left.push(jump("merge"));
            right.push(jump("merge"));
            let module = module(vec![
                block("entry", entry),
                block("left", left),
                block("right", right),
                block("merge", vec![store(&slot), load("read", &slot), ret()]),
            ]);

            assert_eq!(verify_module_lifecycle(&module), Ok(()));
        }
    }
}

#[test]
fn read_before_repair_and_unrepaired_successor_remain_invalid() {
    for r#type in [IRType::from(IntType), IRType::from(StringType)] {
        let slot = storage("slot", r#type.clone());
        let read_before_store = module(vec![
            block("entry", vec![init(&slot), branch("left", "right")]),
            block("left", vec![jump("merge")]),
            block("right", vec![destroy(&slot), jump("merge")]),
            block(
                "merge",
                vec![
                    load("early", &slot),
                    store(&slot),
                    load("late", &slot),
                    ret(),
                ],
            ),
        ]);
        let error = verify_function_lifecycle(&read_before_store, &read_before_store.functions[0])
            .unwrap_err();
        assert!(matches!(
            rule(&error),
            LifecycleRuleError::InvalidMergedState {
                operation: LifecycleOperation::Load,
                ..
            }
        ));

        let one_successor = module(vec![
            block("entry", vec![init(&slot), branch("left", "right")]),
            block("left", vec![jump("merge")]),
            block("right", vec![destroy(&slot), jump("merge")]),
            block("merge", vec![branch("repaired", "unrepaired")]),
            block("repaired", vec![store(&slot), load("safe", &slot), ret()]),
            block("unrepaired", vec![load("unsafe", &slot), ret()]),
        ]);
        let error =
            verify_function_lifecycle(&one_successor, &one_successor.functions[0]).unwrap_err();
        assert_eq!(block_error(&error).block_name, "unrepaired");

        let unused_other_successor = module(vec![
            block("entry", vec![init(&slot), branch("left", "right")]),
            block("left", vec![jump("merge")]),
            block("right", vec![destroy(&slot), jump("merge")]),
            block("merge", vec![branch("repaired", "unused")]),
            block("repaired", vec![store(&slot), load("safe", &slot), ret()]),
            block("unused", vec![ret()]),
        ]);
        assert_eq!(verify_module_lifecycle(&unused_other_successor), Ok(()));
    }
}

#[test]
fn rejects_moved_or_destroyed_storage_source_on_one_path() {
    for moved in [true, false] {
        let source = storage("source", StringType.into());
        let consumed = storage("consumed", StringType.into());
        let destination = storage("destination", StringType.into());
        let invalidation = if moved {
            move_init(&consumed, &source)
        } else {
            destroy(&source)
        };
        let module = module(vec![
            block("entry", vec![init(&source), branch("left", "right")]),
            block("left", vec![invalidation, jump("merge")]),
            block("right", vec![jump("merge")]),
            block(
                "merge",
                vec![copy_from_storage(&destination, &source), ret()],
            ),
        ]);

        let error = verify_function_lifecycle(&module, &module.functions[0]).unwrap_err();
        assert!(matches!(
            rule(&error),
            LifecycleRuleError::InvalidMergedState {
                operation: LifecycleOperation::CopyInit,
                role: LifecycleStorageRole::Source,
                ..
            }
        ));
    }
}

#[test]
fn loop_carried_live_state_converges() {
    let slot = int_storage("slot");
    let module = module(vec![
        block("entry", vec![init(&slot), jump("header")]),
        block(
            "header",
            vec![load("header_read", &slot), branch("body", "exit")],
        ),
        block("body", vec![load("body_read", &slot), jump("header")]),
        block("exit", vec![load("exit_read", &slot), ret()]),
    ]);

    assert_eq!(verify_module_lifecycle(&module), Ok(()));
}

#[test]
fn initialization_only_in_loop_body_does_not_cover_zero_iterations() {
    let slot = int_storage("slot");
    let module = module(vec![
        block("entry", vec![jump("header")]),
        block("header", vec![branch("body", "exit")]),
        block("body", vec![store(&slot), jump("header")]),
        block("exit", vec![load("read", &slot), ret()]),
    ]);

    let error = verify_function_lifecycle(&module, &module.functions[0]).unwrap_err();
    assert!(matches!(
        rule(&error),
        LifecycleRuleError::InvalidMergedState {
            operation: LifecycleOperation::Load,
            ..
        }
    ));
}

#[test]
fn move_in_loop_body_is_invalid_on_a_later_iteration() {
    let source = int_storage("source");
    let consumed = int_storage("consumed");
    let module = module(vec![
        block("entry", vec![init(&source), jump("header")]),
        block("header", vec![branch("body", "exit")]),
        block(
            "body",
            vec![
                move_init(&consumed, &source),
                destroy(&consumed),
                jump("header"),
            ],
        ),
        block("exit", vec![ret()]),
    ]);

    let error = verify_function_lifecycle(&module, &module.functions[0]).unwrap_err();
    assert_eq!(block_error(&error).block_name, "body");
    assert!(matches!(
        rule(&error),
        LifecycleRuleError::InvalidMergedState {
            operation: LifecycleOperation::MoveInit,
            role: LifecycleStorageRole::Source,
            ..
        }
    ));
}

#[test]
fn self_loop_with_total_store_converges_and_duplicate_edges_are_stable() {
    let slot = int_storage("slot");
    let module = module(vec![block(
        "entry",
        vec![store(&slot), load("read", &slot), branch("entry", "entry")],
    )]);

    assert_eq!(verify_module_lifecycle(&module), Ok(()));
    assert_eq!(verify_module_lifecycle(&module), Ok(()));
}

#[test]
fn unreachable_blocks_match_python_all_slots_live_policy() {
    for r#type in [IRType::from(IntType), IRType::from(StringType)] {
        let slot = storage("slot", r#type.clone());
        let isolated_load = module(vec![
            block("entry", vec![ret()]),
            block("dead", vec![load("dead_read", &slot), ret()]),
        ]);
        assert_eq!(verify_module_lifecycle(&isolated_load), Ok(()));

        let isolated_destroy = module(vec![
            block("entry", vec![ret()]),
            block("dead", vec![destroy(&slot), ret()]),
        ]);
        assert_eq!(verify_module_lifecycle(&isolated_destroy), Ok(()));

        let initialization = module(vec![
            block("entry", vec![ret()]),
            block("dead_init", vec![init(&slot), jump("dead_read")]),
            block("dead_read", vec![load("read", &slot), ret()]),
        ]);
        let error =
            verify_function_lifecycle(&initialization, &initialization.functions[0]).unwrap_err();
        assert_eq!(block_error(&error).block_name, "dead_init");
        assert!(matches!(
            rule(&error),
            LifecycleRuleError::DoubleInitialization { .. }
        ));
    }
}

#[test]
fn unreachable_edges_do_not_propagate_move_or_destroy_state() {
    for r#type in [IRType::from(IntType), IRType::from(StringType)] {
        let source = storage("source", r#type.clone());
        let destination = storage("destination", r#type.clone());
        let target = storage("target", r#type.clone());

        let after_destroy = module(vec![
            block("entry", vec![ret()]),
            block("dead_destroy", vec![destroy(&source), jump("dead_use")]),
            block(
                "dead_use",
                vec![assign_from_storage(&target, &source), ret()],
            ),
        ]);
        assert_eq!(verify_module_lifecycle(&after_destroy), Ok(()));

        let local_destroy = module(vec![
            block("entry", vec![ret()]),
            block(
                "dead",
                vec![
                    destroy(&source),
                    assign_from_storage(&target, &source),
                    ret(),
                ],
            ),
        ]);
        assert!(matches!(
            rule(
                &verify_function_lifecycle(&local_destroy, &local_destroy.functions[0])
                    .unwrap_err()
            ),
            LifecycleRuleError::UseAfterLocalInvalidation {
                previous_state: LocalSlotState::Destroyed,
                ..
            }
        ));

        let local_move = module(vec![
            block("entry", vec![ret()]),
            block(
                "dead",
                vec![
                    destroy(&destination),
                    move_init(&destination, &source),
                    assign_from_storage(&target, &source),
                    ret(),
                ],
            ),
        ]);
        assert!(matches!(
            rule(&verify_function_lifecycle(&local_move, &local_move.functions[0]).unwrap_err()),
            LifecycleRuleError::UseAfterLocalInvalidation {
                previous_state: LocalSlotState::Moved,
                ..
            }
        ));
    }
}

#[test]
fn unreachable_cycles_and_disconnected_components_are_stable() {
    for r#type in [IRType::from(IntType), IRType::from(StringType)] {
        let first = storage("first", r#type.clone());
        let second = storage("second", r#type.clone());
        let module = module(vec![
            block("entry", vec![ret()]),
            block(
                "dead_linear",
                vec![load("linear", &first), jump("dead_cycle")],
            ),
            block(
                "dead_cycle",
                vec![load("cycle", &first), jump("dead_cycle")],
            ),
            block(
                "dead_self",
                vec![load("self_read", &second), jump("dead_self")],
            ),
            block("dead_isolated", vec![destroy(&second), ret()]),
        ]);

        assert_eq!(verify_module_lifecycle(&module), Ok(()));
        assert_eq!(verify_module_lifecycle(&module), Ok(()));
    }
}

#[test]
fn source_order_selects_the_first_invalid_block_not_worklist_order() {
    let first = int_storage("first");
    let later = int_storage("later");
    let module = module(vec![
        block("entry", vec![branch("later_bad", "first_bad")]),
        block("first_bad", vec![load("first_read", &first), ret()]),
        block("later_bad", vec![load("later_read", &later), ret()]),
    ]);

    let error = verify_function_lifecycle(&module, &module.functions[0]).unwrap_err();
    assert_eq!(block_error(&error).block_name, "first_bad");
}

#[test]
fn malformed_cfg_is_a_typed_prerequisite_error() {
    let module = module(vec![block("entry", vec![jump("missing")])]);
    let error = verify_function_lifecycle(&module, &module.functions[0]).unwrap_err();

    assert!(matches!(
        error,
        FunctionLifecycleVerificationError::StructurePrerequisite { .. }
    ));
}

#[test]
fn complete_error_chain_is_stable_and_downcastable() {
    let slot = int_storage("slot");
    let module = module(vec![block("entry", vec![load("read", &slot), ret()])]);

    let first = verify_module_lifecycle(&module).unwrap_err();
    let repeated = verify_module_lifecycle(&module).unwrap_err();
    assert_eq!(first, repeated);
    let function = first
        .source()
        .and_then(|source| source.downcast_ref::<FunctionLifecycleVerificationError>())
        .expect("module source must retain the function error");
    let block = function
        .source()
        .and_then(|source| source.downcast_ref::<BlockLifecycleError>())
        .expect("function source must retain the block error");
    assert!(
        block
            .source()
            .is_some_and(|source| { source.downcast_ref::<LifecycleRuleError>().is_some() })
    );
}
