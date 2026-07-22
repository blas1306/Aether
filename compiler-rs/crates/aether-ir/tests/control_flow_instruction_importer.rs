//! Focused coverage for schema-v1 control-flow instruction import.

use aether_ir::wire::IRInstructionDTO;
use aether_ir::{
    BoolType, IRImportError, IRInstruction, IRStorage, IRType, IRValue, IntType, LifecycleSource,
    ListType, NullableType, StringType, StructType, import_instruction,
};
use serde_json::{Value, json};

fn nested_type() -> IRType {
    ListType {
        element: Box::new(
            NullableType {
                inner: Box::new(
                    StructType {
                        name: " Missing::Payload ".to_owned(),
                    }
                    .into(),
                ),
            }
            .into(),
        ),
    }
    .into()
}

fn assert_import_paths(json: &Value, expected: IRInstruction) {
    let encoded = serde_json::to_string(json).expect("control-flow JSON must serialize");
    let wire: IRInstructionDTO =
        serde_json::from_str(&encoded).expect("control-flow JSON must deserialize");
    let original = wire.clone();

    assert_eq!(import_instruction(&wire), Ok(expected.clone()));
    assert_eq!(import_instruction(&wire), Ok(expected.clone()));
    assert_eq!(IRInstruction::try_from(&wire), Ok(expected.clone()));
    assert_eq!(IRInstruction::try_from(wire.clone()), Ok(expected));
    assert_eq!(wire, original, "borrowed import must not mutate its DTO");
}

#[test]
fn imports_branches_with_exact_targets_without_semantic_validation() {
    assert_import_paths(
        &json!({
            "kind": "branch",
            "condition": {
                "tag": "parameter",
                "name": "unresolved::non_boolean_condition",
                "type": {"tag": "int"}
            },
            "true_target": "",
            "false_target": " missing::false\0target "
        }),
        IRInstruction::IRBranch {
            condition: IRValue::new("unresolved::non_boolean_condition", IntType.into()),
            true_target: String::new(),
            false_target: " missing::false\0target ".to_owned(),
        },
    );

    assert_import_paths(
        &json!({
            "kind": "branch",
            "condition": {
                "tag": "value",
                "name": "nested-condition",
                "type": {
                    "tag": "list",
                    "element": {
                        "tag": "nullable",
                        "inner": {"tag": "struct", "name": " Missing::Payload "}
                    }
                }
            },
            "true_target": "same::unresolved",
            "false_target": "same::unresolved"
        }),
        IRInstruction::IRBranch {
            condition: IRValue::new("nested-condition", nested_type()),
            true_target: "same::unresolved".to_owned(),
            false_target: "same::unresolved".to_owned(),
        },
    );
}

#[test]
fn imports_jumps_with_empty_and_unusual_unresolved_targets() {
    for target in ["", " unresolved::exit\0label "] {
        assert_import_paths(
            &json!({"kind": "jump", "target": target}),
            IRInstruction::IRJump {
                target: target.to_owned(),
            },
        );
    }
}

#[test]
fn imports_returns_with_primitive_and_nested_values_and_storage() {
    assert_import_paths(
        &json!({
            "kind": "return",
            "value": {
                "tag": "value",
                "name": "incompatible::return",
                "type": {"tag": "string"}
            },
            "transferred_storage": {
                "tag": "storage",
                "name": "unresolved::transfer",
                "type": {"tag": "bool"}
            }
        }),
        IRInstruction::IRReturn {
            value: Some(IRValue::new("incompatible::return", StringType.into()).into()),
            transferred_storage: Some(IRStorage::new("unresolved::transfer", BoolType.into())),
        },
    );

    assert_import_paths(
        &json!({
            "kind": "return",
            "value": {
                "tag": "storage",
                "name": "nested-return",
                "type": {
                    "tag": "list",
                    "element": {
                        "tag": "nullable",
                        "inner": {"tag": "struct", "name": " Missing::Payload "}
                    }
                }
            },
            "transferred_storage": null
        }),
        IRInstruction::IRReturn {
            value: Some(LifecycleSource::Storage(IRStorage::new(
                "nested-return",
                nested_type(),
            ))),
            transferred_storage: None,
        },
    );
}

#[test]
fn imports_returns_without_a_value_or_function_context() {
    assert_import_paths(
        &json!({"kind": "return", "value": null, "transferred_storage": null}),
        IRInstruction::IRReturn {
            value: None,
            transferred_storage: None,
        },
    );
}

#[test]
fn reports_nested_control_flow_fields_with_typed_context() {
    let cases = [
        (
            json!({
                "kind": "branch",
                "condition": {
                    "tag": "value",
                    "name": "bad::condition",
                    "type": {
                        "tag": "method_result",
                        "receiver": {"tag": "list", "element": {"tag": "int"}},
                        "value": {"tag": "bool"}
                    }
                },
                "true_target": "then",
                "false_target": "else"
            }),
            IRImportError::InstructionField {
                instruction: "branch",
                field: "condition",
                source: Box::new(IRImportError::ValueType {
                    kind: "value",
                    source: Box::new(IRImportError::MethodResultReceiverNotStruct {
                        actual: "list",
                    }),
                }),
            },
        ),
        (
            json!({
                "kind": "return",
                "value": {
                    "tag": "parameter",
                    "name": "bad::return",
                    "type": {
                        "tag": "method_result",
                        "receiver": {"tag": "array", "element": {"tag": "int"}},
                        "value": {"tag": "string"}
                    }
                },
                "transferred_storage": null
            }),
            IRImportError::InstructionField {
                instruction: "return",
                field: "value",
                source: Box::new(IRImportError::ValueType {
                    kind: "parameter",
                    source: Box::new(IRImportError::MethodResultReceiverNotStruct {
                        actual: "array",
                    }),
                }),
            },
        ),
        (
            json!({
                "kind": "return",
                "value": null,
                "transferred_storage": {
                    "tag": "storage",
                    "name": "bad::transfer",
                    "type": {
                        "tag": "method_result",
                        "receiver": {"tag": "nullable", "inner": {"tag": "int"}},
                        "value": {"tag": "string"}
                    }
                }
            }),
            IRImportError::InstructionField {
                instruction: "return",
                field: "transferred_storage",
                source: Box::new(IRImportError::StorageType {
                    source: Box::new(IRImportError::MethodResultReceiverNotStruct {
                        actual: "nullable",
                    }),
                }),
            },
        ),
    ];

    for (json, expected) in cases {
        let wire: IRInstructionDTO = serde_json::from_value(json)
            .expect("the wire model permits the unrepresentable nested type");
        assert_eq!(import_instruction(&wire), Err(expected));
    }
}
