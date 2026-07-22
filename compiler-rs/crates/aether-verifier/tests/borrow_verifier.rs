//! Python-compatible initial-IR borrowed-element verification coverage.

use std::error::Error as _;

use aether_ir::{
    ArrayType, IRBasicBlock, IRFunction, IRInstruction, IRModule, IRParameter, IRStorage,
    IRStructDefinition, IRType, IRValue, IntType, ListType, StringType, StructType, VoidType,
};
use aether_verifier::{
    BlockTypeVerificationError, BorrowRule, BorrowRuleError, FunctionTypeVerificationError,
    InstructionKind, InstructionTypeVerificationError, ModuleTypeVerificationError,
    SSAInstructionLocation, TypeRuleError, verify_function_dominance, verify_module_types,
};

fn array(element: IRType) -> IRType {
    ArrayType {
        element: Box::new(element),
    }
    .into()
}

fn list(element: IRType) -> IRType {
    ListType {
        element: Box::new(element),
    }
    .into()
}

fn value(name: &str, r#type: &IRType) -> IRValue {
    IRValue::new(name, r#type.clone())
}

fn parameter(name: &str, r#type: &IRType) -> IRParameter {
    IRParameter::new(name, r#type.clone())
}

fn borrowed_list_get(
    result: IRValue,
    list_value: IRValue,
    index: IRValue,
    borrow_scope: Option<&str>,
) -> IRInstruction {
    IRInstruction::IRListGet {
        result,
        list_value,
        index,
        borrowed: true,
        borrow_scope: borrow_scope.map(str::to_owned),
        source_location: None,
    }
}

fn borrowed_array_get(
    result: IRValue,
    array_value: IRValue,
    index: IRValue,
    borrow_scope: Option<&str>,
) -> IRInstruction {
    IRInstruction::IRArrayGet {
        result,
        array: array_value,
        index,
        borrowed: true,
        borrow_scope: borrow_scope.map(str::to_owned),
        source_location: None,
    }
}

fn ret(value: Option<IRValue>) -> IRInstruction {
    IRInstruction::IRReturn {
        value: value.map(Into::into),
        transferred_storage: None,
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

fn borrow_rule(error: &ModuleTypeVerificationError) -> &BorrowRuleError {
    let ModuleTypeVerificationError::Function { source, .. } = error else {
        panic!("expected function error")
    };
    let FunctionTypeVerificationError::Block { source, .. } = source else {
        panic!("expected block error")
    };
    let TypeRuleError::BorrowViolation { source } = &source.source.source else {
        panic!("expected borrow rule error")
    };
    source
}

#[test]
fn accepts_local_scalar_and_managed_borrows() {
    for element_type in [IntType.into(), StringType.into(), list(IntType.into())] {
        let collection_type = list(element_type.clone());
        let collection = value("collection", &collection_type);
        let index = value("index", &IntType.into());
        let borrowed = value("borrowed", &element_type);
        let function = function(
            "local",
            vec![
                parameter("collection", &collection_type),
                parameter("index", &IntType.into()),
            ],
            VoidType.into(),
            vec![block(
                "entry",
                vec![
                    borrowed_list_get(borrowed.clone(), collection, index, Some("entry")),
                    IRInstruction::IRPrint {
                        value: borrowed,
                        newline: true,
                        aggregate_shape: None,
                    },
                    ret(None),
                ],
            )],
        );
        assert_eq!(verify_module_types(&module(vec![function])), Ok(()));
    }
}

#[test]
fn accepts_cross_block_borrow_use_when_ordinary_dominance_holds() {
    let collection_type = array(IntType.into());
    let collection = value("collection", &collection_type);
    let index = value("index", &IntType.into());
    let borrowed = value("borrowed", &IntType.into());
    let function = function(
        "cross_block",
        vec![
            parameter("collection", &collection_type),
            parameter("index", &IntType.into()),
        ],
        VoidType.into(),
        vec![
            block(
                "entry",
                vec![
                    borrowed_array_get(borrowed.clone(), collection, index, Some("entry")),
                    IRInstruction::IRJump {
                        target: "use".to_owned(),
                    },
                ],
            ),
            block(
                "use",
                vec![
                    IRInstruction::IRPrint {
                        value: borrowed,
                        newline: true,
                        aggregate_shape: None,
                    },
                    ret(None),
                ],
            ),
        ],
    );

    assert_eq!(verify_module_types(&module(vec![function.clone()])), Ok(()));
    assert_eq!(verify_function_dominance(&function), Ok(()));
}

#[test]
fn accepts_nested_borrow_from_borrowed_collection_in_the_same_scope() {
    let inner_type = list(IntType.into());
    let outer_type = list(inner_type.clone());
    let outer_borrow = value("outer_borrow", &inner_type);
    let inner_borrow = value("inner_borrow", &IntType.into());
    let function = function(
        "nested",
        vec![
            parameter("outer", &outer_type),
            parameter("index", &IntType.into()),
        ],
        VoidType.into(),
        vec![block(
            "entry",
            vec![
                borrowed_list_get(
                    outer_borrow.clone(),
                    value("outer", &outer_type),
                    value("index", &IntType.into()),
                    Some("entry"),
                ),
                borrowed_list_get(
                    inner_borrow.clone(),
                    outer_borrow,
                    value("index", &IntType.into()),
                    Some("entry"),
                ),
                IRInstruction::IRPrint {
                    value: inner_borrow,
                    newline: true,
                    aggregate_shape: None,
                },
                ret(None),
            ],
        )],
    );

    assert_eq!(verify_module_types(&module(vec![function])), Ok(()));
}

#[test]
fn accepts_same_block_retain_before_managed_store() {
    let string_type: IRType = StringType.into();
    let collection_type = list(string_type.clone());
    let borrowed = value("borrowed", &string_type);
    let function = function(
        "acquired",
        vec![
            parameter("collection", &collection_type),
            parameter("index", &IntType.into()),
        ],
        VoidType.into(),
        vec![block(
            "entry",
            vec![
                borrowed_list_get(
                    borrowed.clone(),
                    value("collection", &collection_type),
                    value("index", &IntType.into()),
                    Some("entry"),
                ),
                IRInstruction::IRCall {
                    function: "__aether_retain".to_owned(),
                    arguments: vec![borrowed.clone()],
                    result: None,
                    builtin: Some("__aether_retain".to_owned()),
                    source_location: None,
                },
                IRInstruction::IRStore {
                    slot: value("saved", &string_type),
                    value: borrowed,
                },
                ret(None),
            ],
        )],
    );

    assert_eq!(verify_module_types(&module(vec![function])), Ok(()));
}

#[test]
fn rejects_missing_empty_mismatched_and_owned_get_scopes() {
    let collection_type = list(IntType.into());
    for (scope, expected_rule) in [
        (None, BorrowRule::Irv037),
        (Some(""), BorrowRule::Irv037),
        (Some("other"), BorrowRule::Irv038),
    ] {
        let function = function(
            "scope",
            vec![
                parameter("collection", &collection_type),
                parameter("index", &IntType.into()),
            ],
            VoidType.into(),
            vec![block(
                "entry",
                vec![
                    borrowed_list_get(
                        value("borrowed", &IntType.into()),
                        value("collection", &collection_type),
                        value("index", &IntType.into()),
                        scope,
                    ),
                    ret(None),
                ],
            )],
        );
        let error = verify_module_types(&module(vec![function])).unwrap_err();
        assert!(matches!(
            borrow_rule(&error),
            BorrowRuleError::MissingBorrowScope { rule, .. }
                | BorrowRuleError::BorrowScopeMismatch { rule, .. }
                if *rule == expected_rule
        ));
    }

    let function = function(
        "owned_scope",
        vec![
            parameter("collection", &collection_type),
            parameter("index", &IntType.into()),
        ],
        VoidType.into(),
        vec![block(
            "entry",
            vec![
                IRInstruction::IRListGet {
                    result: value("owned", &IntType.into()),
                    list_value: value("collection", &collection_type),
                    index: value("index", &IntType.into()),
                    borrowed: false,
                    borrow_scope: Some(String::new()),
                    source_location: None,
                },
                ret(None),
            ],
        )],
    );
    assert!(matches!(
        borrow_rule(&verify_module_types(&module(vec![function])).unwrap_err()),
        BorrowRuleError::OwnedGetDeclaresBorrowScope {
            rule: BorrowRule::Irv039,
            declared_scope,
            ..
        } if declared_scope.is_empty()
    ));
}

#[test]
fn rejects_unacquired_managed_store_but_allows_trivial_store() {
    let cases: [(IRType, bool); 2] = [(StringType.into(), true), (IntType.into(), false)];
    for (element_type, rejected) in cases {
        let collection_type = list(element_type.clone());
        let borrowed = value("borrowed", &element_type);
        let function = function(
            "store",
            vec![
                parameter("collection", &collection_type),
                parameter("index", &IntType.into()),
            ],
            VoidType.into(),
            vec![block(
                "entry",
                vec![
                    borrowed_list_get(
                        borrowed.clone(),
                        value("collection", &collection_type),
                        value("index", &IntType.into()),
                        Some("entry"),
                    ),
                    IRInstruction::IRStore {
                        slot: value("saved", &element_type),
                        value: borrowed,
                    },
                    ret(None),
                ],
            )],
        );
        let result = verify_module_types(&module(vec![function]));
        if rejected {
            assert!(matches!(
                borrow_rule(&result.unwrap_err()),
                BorrowRuleError::BorrowedOwningStoreWithoutAcquisition {
                    rule: BorrowRule::Irv040,
                    ..
                }
            ));
        } else {
            assert_eq!(result, Ok(()));
        }
    }
}

#[test]
fn store_acquisition_is_same_block_only() {
    let string_type: IRType = StringType.into();
    let collection_type = list(string_type.clone());
    let borrowed = value("borrowed", &string_type);
    let function = function(
        "cross_block_acquisition",
        vec![
            parameter("collection", &collection_type),
            parameter("index", &IntType.into()),
        ],
        VoidType.into(),
        vec![
            block(
                "entry",
                vec![
                    borrowed_list_get(
                        borrowed.clone(),
                        value("collection", &collection_type),
                        value("index", &IntType.into()),
                        Some("entry"),
                    ),
                    IRInstruction::IRCall {
                        function: "__aether_retain".to_owned(),
                        arguments: vec![borrowed.clone()],
                        result: None,
                        builtin: Some("__aether_retain".to_owned()),
                        source_location: None,
                    },
                    IRInstruction::IRJump {
                        target: "store".to_owned(),
                    },
                ],
            ),
            block(
                "store",
                vec![
                    IRInstruction::IRStore {
                        slot: value("saved", &string_type),
                        value: borrowed,
                    },
                    ret(None),
                ],
            ),
        ],
    );

    assert!(matches!(
        borrow_rule(&verify_module_types(&module(vec![function])).unwrap_err()),
        BorrowRuleError::BorrowedOwningStoreWithoutAcquisition {
            rule: BorrowRule::Irv040,
            ..
        }
    ));
}

#[test]
fn rejects_direct_return_even_after_retain() {
    let string_type: IRType = StringType.into();
    let collection_type = list(string_type.clone());
    let borrowed = value("borrowed", &string_type);
    let function = function(
        "escape",
        vec![
            parameter("collection", &collection_type),
            parameter("index", &IntType.into()),
        ],
        string_type,
        vec![block(
            "entry",
            vec![
                borrowed_list_get(
                    borrowed.clone(),
                    value("collection", &collection_type),
                    value("index", &IntType.into()),
                    Some("entry"),
                ),
                IRInstruction::IRCall {
                    function: "__aether_retain".to_owned(),
                    arguments: vec![borrowed.clone()],
                    result: None,
                    builtin: Some("__aether_retain".to_owned()),
                    source_location: None,
                },
                ret(Some(borrowed)),
            ],
        )],
    );

    assert!(matches!(
        borrow_rule(&verify_module_types(&module(vec![function])).unwrap_err()),
        BorrowRuleError::BorrowedValueReturned {
            rule: BorrowRule::Irv041,
            ..
        }
    ));
}

#[test]
fn rejects_each_python_mutation_receiver_family() {
    let element_type = list(IntType.into());
    let collection_type = list(element_type.clone());
    let borrowed = value("borrowed", &element_type);
    let index = value("index", &IntType.into());
    let item = value("item", &IntType.into());
    let mutations = vec![
        IRInstruction::IRListSet {
            list_value: borrowed.clone(),
            index: index.clone(),
            value: item.clone(),
        },
        IRInstruction::IRListPush {
            list_value: borrowed.clone(),
            value: item.clone(),
        },
        IRInstruction::IRListInsert {
            list_value: borrowed.clone(),
            index: index.clone(),
            value: item.clone(),
        },
        IRInstruction::IRListRemoveAt {
            result: item.clone(),
            list_value: borrowed.clone(),
            index: index.clone(),
        },
        IRInstruction::IRListPop {
            result: item.clone(),
            list_value: borrowed.clone(),
        },
        IRInstruction::IRListClear {
            list_value: borrowed.clone(),
        },
        IRInstruction::IRListReverse {
            list_value: borrowed.clone(),
        },
        IRInstruction::IRSequenceSort {
            sequence: borrowed.clone(),
        },
    ];

    for mutation in mutations {
        let expected_kind = match &mutation {
            IRInstruction::IRListSet { .. } => InstructionKind::IRListSet,
            IRInstruction::IRListPush { .. } => InstructionKind::IRListPush,
            IRInstruction::IRListInsert { .. } => InstructionKind::IRListInsert,
            IRInstruction::IRListRemoveAt { .. } => InstructionKind::IRListRemoveAt,
            IRInstruction::IRListPop { .. } => InstructionKind::IRListPop,
            IRInstruction::IRListClear { .. } => InstructionKind::IRListClear,
            IRInstruction::IRListReverse { .. } => InstructionKind::IRListReverse,
            IRInstruction::IRSequenceSort { .. } => InstructionKind::IRSequenceSort,
            _ => unreachable!(),
        };
        let function = function(
            "mutation",
            vec![
                parameter("collection", &collection_type),
                parameter("index", &IntType.into()),
                parameter("item", &IntType.into()),
            ],
            VoidType.into(),
            vec![block(
                "entry",
                vec![
                    borrowed_list_get(
                        borrowed.clone(),
                        value("collection", &collection_type),
                        index.clone(),
                        Some("entry"),
                    ),
                    mutation,
                    ret(None),
                ],
            )],
        );
        assert!(matches!(
            borrow_rule(&verify_module_types(&module(vec![function])).unwrap_err()),
            BorrowRuleError::MutationThroughBorrow {
                rule: BorrowRule::Irv042,
                consumer_kind,
                ..
            } if *consumer_kind == expected_kind
        ));
    }
}

#[test]
fn rejects_array_and_struct_mutation_receivers() {
    let int_type: IRType = IntType.into();
    let index = value("index", &int_type);
    let item = value("item", &int_type);
    let array_type = array(int_type.clone());
    let array_outer_type = list(array_type.clone());
    let borrowed_array = value("borrowed_array", &array_type);
    let array_function = function(
        "array_mutation",
        vec![
            parameter("outer", &array_outer_type),
            parameter("index", &int_type),
            parameter("item", &int_type),
        ],
        VoidType.into(),
        vec![block(
            "entry",
            vec![
                borrowed_list_get(
                    borrowed_array.clone(),
                    value("outer", &array_outer_type),
                    index.clone(),
                    Some("entry"),
                ),
                IRInstruction::IRArraySet {
                    array: borrowed_array,
                    index: index.clone(),
                    value: item.clone(),
                },
                ret(None),
            ],
        )],
    );
    assert!(matches!(
        borrow_rule(&verify_module_types(&module(vec![array_function])).unwrap_err()),
        BorrowRuleError::MutationThroughBorrow {
            consumer_kind: InstructionKind::IRArraySet,
            ..
        }
    ));

    let struct_type: IRType = StructType {
        name: "Item".to_owned(),
    }
    .into();
    let struct_outer_type = list(struct_type.clone());
    let borrowed_struct = value("borrowed_struct", &struct_type);
    let struct_function = function(
        "struct_mutation",
        vec![
            parameter("outer", &struct_outer_type),
            parameter("index", &int_type),
            parameter("item", &int_type),
        ],
        VoidType.into(),
        vec![block(
            "entry",
            vec![
                borrowed_list_get(
                    borrowed_struct.clone(),
                    value("outer", &struct_outer_type),
                    index,
                    Some("entry"),
                ),
                IRInstruction::IRStructSet {
                    result: value("updated", &struct_type),
                    r#struct: borrowed_struct,
                    field_index: 0,
                    field_name: "number".to_owned(),
                    value: item,
                },
                ret(None),
            ],
        )],
    );
    let module = IRModule {
        functions: vec![struct_function],
        structs: vec![IRStructDefinition {
            name: "Item".to_owned(),
            fields: vec![("number".to_owned(), int_type)],
        }],
    };
    assert!(matches!(
        borrow_rule(&verify_module_types(&module).unwrap_err()),
        BorrowRuleError::MutationThroughBorrow {
            consumer_kind: InstructionKind::IRStructSet,
            ..
        }
    ));
}

#[test]
fn preserves_python_boundaries_for_aggregate_call_copy_and_multiple_uses() {
    let element_type = list(IntType.into());
    let collection_type = list(element_type.clone());
    let borrowed = value("borrowed", &element_type);
    let aggregate_type = list(element_type.clone());
    let observer_function = function(
        "observe",
        vec![parameter("argument", &element_type)],
        VoidType.into(),
        vec![block("entry", vec![ret(None)])],
    );
    let boundary_function = function(
        "boundaries",
        vec![
            parameter("collection", &collection_type),
            parameter("index", &IntType.into()),
        ],
        VoidType.into(),
        vec![block(
            "entry",
            vec![
                borrowed_list_get(
                    borrowed.clone(),
                    value("collection", &collection_type),
                    value("index", &IntType.into()),
                    Some("entry"),
                ),
                IRInstruction::IRListNew {
                    result: value("aggregate", &aggregate_type),
                    elements: vec![borrowed.clone()],
                },
                IRInstruction::IRCall {
                    function: "observe".to_owned(),
                    arguments: vec![borrowed.clone()],
                    result: None,
                    builtin: None,
                    source_location: None,
                },
                IRInstruction::IRCopyInit {
                    destination: IRStorage::new("copy", element_type),
                    source: borrowed.clone().into(),
                    source_location: None,
                },
                IRInstruction::IRPrint {
                    value: borrowed,
                    newline: true,
                    aggregate_shape: None,
                },
                ret(None),
            ],
        )],
    );

    assert_eq!(
        verify_module_types(&module(vec![observer_function, boundary_function])),
        Ok(())
    );
}

#[test]
fn invalid_collection_source_and_unknown_call_remain_non_borrow_type_rules() {
    let invalid_source = function(
        "invalid_source",
        vec![
            parameter("source", &IntType.into()),
            parameter("index", &IntType.into()),
        ],
        VoidType.into(),
        vec![block(
            "entry",
            vec![
                borrowed_array_get(
                    value("borrowed", &IntType.into()),
                    value("source", &IntType.into()),
                    value("index", &IntType.into()),
                    Some("entry"),
                ),
                ret(None),
            ],
        )],
    );
    let source_error = verify_module_types(&module(vec![invalid_source])).unwrap_err();
    assert!(matches!(
        &source_error,
        ModuleTypeVerificationError::Function {
            source: FunctionTypeVerificationError::Block { source, .. },
            ..
        } if matches!(&source.source.source, TypeRuleError::TypeConstraint { .. })
    ));

    let collection_type = list(IntType.into());
    let borrowed = value("borrowed", &IntType.into());
    let invalid_call = function(
        "invalid_call",
        vec![
            parameter("collection", &collection_type),
            parameter("index", &IntType.into()),
        ],
        VoidType.into(),
        vec![block(
            "entry",
            vec![
                borrowed_list_get(
                    borrowed.clone(),
                    value("collection", &collection_type),
                    value("index", &IntType.into()),
                    Some("entry"),
                ),
                IRInstruction::IRCall {
                    function: "missing".to_owned(),
                    arguments: vec![borrowed],
                    result: None,
                    builtin: None,
                    source_location: None,
                },
                ret(None),
            ],
        )],
    );
    let call_error = verify_module_types(&module(vec![invalid_call])).unwrap_err();
    assert!(matches!(
        &call_error,
        ModuleTypeVerificationError::Function {
            source: FunctionTypeVerificationError::Block { source, .. },
            ..
        } if matches!(&source.source.source, TypeRuleError::UnknownFunction { .. })
    ));
}

#[test]
fn diagnostic_is_deterministic_and_fully_downcastable() {
    let string_type: IRType = StringType.into();
    let collection_type = list(string_type.clone());
    let borrowed = value("borrowed", &string_type);
    let function = function(
        "deterministic",
        vec![
            parameter("collection", &collection_type),
            parameter("index", &IntType.into()),
        ],
        string_type,
        vec![block(
            "entry",
            vec![
                borrowed_list_get(
                    borrowed.clone(),
                    value("collection", &collection_type),
                    value("index", &IntType.into()),
                    Some("entry"),
                ),
                ret(Some(borrowed)),
            ],
        )],
    );
    let module = module(vec![function]);
    let first = verify_module_types(&module).unwrap_err();
    let second = verify_module_types(&module).unwrap_err();

    assert_eq!(first, second);
    assert_eq!(
        first.to_string(),
        "function 0 ('deterministic') failed type verification: block 0 ('entry') of function 'deterministic' failed type verification: type verification failed in function 'deterministic' block 'entry' instruction 1 (IRReturn): IRReturn failed type verification: IRV-041 borrowed iteration value '%borrowed' from scope 'entry' at block 0 ('entry') instruction 0 (IRListGet) cannot escape through return at block 0 ('entry') instruction 1 (IRReturn) without copying"
    );

    let function = (&first as &dyn std::error::Error)
        .source()
        .and_then(|source| source.downcast_ref::<FunctionTypeVerificationError>())
        .expect("module error should expose its function source");
    let block = function
        .source()
        .and_then(|source| source.downcast_ref::<BlockTypeVerificationError>())
        .expect("function error should expose its block source");
    let instruction = block
        .source()
        .and_then(|source| source.downcast_ref::<InstructionTypeVerificationError>())
        .expect("block error should expose its instruction source");
    let type_rule = instruction
        .source()
        .and_then(|source| source.downcast_ref::<TypeRuleError>())
        .expect("instruction error should expose its type-rule source");
    assert!(matches!(
        type_rule
            .source()
            .and_then(|source| source.downcast_ref::<BorrowRuleError>()),
        Some(BorrowRuleError::BorrowedValueReturned {
            rule: BorrowRule::Irv041,
            borrowed_value,
            borrow_scope,
            definition: SSAInstructionLocation {
                block_index: 0,
                instruction_index: 0,
                instruction_kind: InstructionKind::IRListGet,
                ..
            },
            consumer: SSAInstructionLocation {
                block_index: 0,
                instruction_index: 1,
                instruction_kind: InstructionKind::IRReturn,
                ..
            },
        }) if borrowed_value == "borrowed" && borrow_scope == "entry"
    ));
}
