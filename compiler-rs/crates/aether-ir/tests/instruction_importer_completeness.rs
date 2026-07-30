//! Cross-family completeness audits for schema-v1 instruction import.

use std::error::Error as _;

use aether_ir::wire::{IRConstantDTO, IRFloatDTO, IRInstructionDTO, IRValueDTO};
use aether_ir::{
    BoolType, IRImportError, IRInstruction, IRSourceLocation, IRStorage, IRValue, IntType,
    StringType, import_instruction,
};
use serde_json::{Value, json};

fn value(tag: &str, name: &str, type_: Value) -> Value {
    let mut value = json!({"tag": tag, "name": name, "type": null});
    value["type"] = type_;
    value
}

fn int_value(name: &str) -> IRValue {
    IRValue::new(name, IntType.into())
}

fn string_value(name: &str) -> IRValue {
    IRValue::new(name, StringType.into())
}

fn import_json(json: Value) -> Result<IRInstruction, IRImportError> {
    let wire =
        serde_json::from_value(json).expect("audit case must be structurally valid wire JSON");
    import_instruction(&wire)
}

#[test]
#[allow(clippy::too_many_lines)]
fn preserves_representative_fields_exactly_across_instruction_families() {
    let cases = [
        (
            json!({
                "kind": "call",
                "function": " unresolved::callee\0raw ",
                "arguments": [
                    value("parameter", " second ", json!({"tag": "string"})),
                    value("storage", "first\0raw", json!({"tag": "int"})),
                    value("value", " second ", json!({"tag": "bool"}))
                ],
                "result": value("value", " nullable::result ", json!({"tag": "string"})),
                "builtin": " BUILTIN::Raw ",
                "source_location": {
                    "tag": "source_location",
                    "line": i64::MIN,
                    "column": i64::MAX,
                    "path": null
                }
            }),
            IRInstruction::IRCall {
                function: " unresolved::callee\0raw ".to_owned(),
                arguments: vec![
                    string_value(" second "),
                    int_value("first\0raw"),
                    IRValue::new(" second ", BoolType.into()),
                ],
                result: Some(string_value(" nullable::result ")),
                builtin: Some(" BUILTIN::Raw ".to_owned()),
                source_location: Some(IRSourceLocation {
                    line: i64::MIN,
                    column: i64::MAX,
                    path: None,
                }),
                may_throw: false,
            },
        ),
        (
            json!({
                "kind": "print",
                "value": value("value", "aggregate", json!({"tag": "string"})),
                "newline": false,
                "aggregate_shape": [i64::MAX, 0, i64::MIN]
            }),
            IRInstruction::IRPrint {
                value: string_value("aggregate"),
                newline: false,
                aggregate_shape: Some(vec![i64::MAX, 0, i64::MIN]),
            },
        ),
        (
            json!({
                "kind": "array_get",
                "result": value("value", "result", json!({"tag": "int"})),
                "array": value("parameter", "array", json!({
                    "tag": "array",
                    "element": {"tag": "int"}
                })),
                "index": value("value", "index", json!({"tag": "int"})),
                "borrowed": true,
                "borrow_scope": null,
                "source_location": null
            }),
            IRInstruction::IRArrayGet {
                result: int_value("result"),
                array: IRValue::new(
                    "array",
                    aether_ir::ArrayType {
                        element: Box::new(IntType.into()),
                    }
                    .into(),
                ),
                index: int_value("index"),
                borrowed: true,
                borrow_scope: None,
                source_location: None,
            },
        ),
        (
            json!({
                "kind": "matrix_mat_mul",
                "result": value("value", "result", json!({"tag": "int"})),
                "left": value("value", "left", json!({"tag": "int"})),
                "right": value("value", "right", json!({"tag": "int"})),
                "shape": [i64::MIN, 7, i64::MAX]
            }),
            IRInstruction::IRMatrixMatMul {
                result: int_value("result"),
                left: int_value("left"),
                right: int_value("right"),
                rows: i64::MIN,
                inner: 7,
                cols: i64::MAX,
            },
        ),
        (
            json!({
                "kind": "return",
                "value": null,
                "transferred_storage": value(
                    "storage",
                    " transfer::owned\0raw ",
                    json!({"tag": "string"})
                )
            }),
            IRInstruction::IRReturn {
                value: None,
                transferred_storage: Some(IRStorage::new(
                    " transfer::owned\0raw ",
                    StringType.into(),
                )),
            },
        ),
        (
            json!({"kind": "return", "value": null, "transferred_storage": null}),
            IRInstruction::IRReturn {
                value: None,
                transferred_storage: None,
            },
        ),
    ];

    for (json, expected) in cases {
        assert_eq!(import_json(json), Ok(expected));
    }
}

fn invalid_method_result_type(receiver: Value) -> Value {
    let mut type_ = json!({
        "tag": "method_result",
        "receiver": null,
        "value": {"tag": "int"}
    });
    type_["receiver"] = receiver;
    type_
}

#[test]
#[allow(clippy::too_many_lines)]
fn preserves_typed_nested_errors_across_representative_families() {
    let const_result: IRValueDTO =
        serde_json::from_value(value("value", "result", json!({"tag": "int"})))
            .expect("value must deserialize");
    let scalar = IRInstructionDTO::Const {
        result: const_result,
        value: IRConstantDTO::Float {
            value: IRFloatDTO(f64::NAN),
        },
    };

    let cases = [
        (
            scalar,
            IRImportError::InstructionField {
                instruction: "const",
                field: "value",
                source: Box::new(IRImportError::NonFiniteConstantFloat { field: "value" }),
            },
        ),
        (
            serde_json::from_value(json!({
                "kind": "array_new",
                "result": value("value", "result", json!({"tag": "int"})),
                "elements": [
                    value("value", "first", json!({"tag": "int"})),
                    value(
                        "value",
                        "bad-second",
                        invalid_method_result_type(json!({
                            "tag": "list",
                            "element": {"tag": "int"}
                        }))
                    )
                ]
            }))
            .expect("wire type intentionally permits the unrepresentable nested type"),
            IRImportError::InstructionField {
                instruction: "array_new",
                field: "elements",
                source: Box::new(IRImportError::ValueType {
                    kind: "value",
                    source: Box::new(IRImportError::MethodResultReceiverNotStruct {
                        actual: "list",
                    }),
                }),
            },
        ),
        (
            serde_json::from_value(json!({
                "kind": "function_ref",
                "result": value("value", "nested-signature", json!({
                    "tag": "function",
                    "parameter_types": [invalid_method_result_type(json!({
                        "tag": "array",
                        "element": {"tag": "int"}
                    }))],
                    "return_type": {"tag": "void"}
                })),
                "function": "callee"
            }))
            .expect("wire type intentionally permits the unrepresentable nested signature"),
            IRImportError::InstructionField {
                instruction: "function_ref",
                field: "result",
                source: Box::new(IRImportError::ValueType {
                    kind: "value",
                    source: Box::new(IRImportError::MethodResultReceiverNotStruct {
                        actual: "array",
                    }),
                }),
            },
        ),
        (
            serde_json::from_value(json!({
                "kind": "return",
                "value": null,
                "transferred_storage": value(
                    "storage",
                    "bad-transfer",
                    invalid_method_result_type(json!({
                        "tag": "nullable",
                        "inner": {"tag": "int"}
                    }))
                )
            }))
            .expect("wire type intentionally permits the unrepresentable transferred storage"),
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

    for (wire, expected) in cases {
        let error = import_instruction(&wire).expect_err("nested conversion must fail");
        assert_eq!(error, expected);
        let expected_source = match &expected {
            IRImportError::InstructionField { source, .. } => source.as_ref(),
            _ => unreachable!("audit cases must use contextual instruction errors"),
        };
        assert_eq!(
            error
                .source()
                .and_then(|source| source.downcast_ref::<IRImportError>()),
            Some(expected_source),
            "instruction errors must retain a typed source"
        );
    }
}

#[test]
fn leaves_cross_family_semantic_validation_to_the_verifier() {
    let cases = [
        json!({
            "kind": "call",
            "function": "unresolved::function",
            "arguments": [value("value", "wrong-argument", json!({"tag": "string"}))],
            "result": value("value", "wrong-result", json!({"tag": "bool"})),
            "builtin": null,
            "source_location": null
        }),
        json!({
            "kind": "binary_op",
            "result": value("value", "result", json!({"tag": "bool"})),
            "operator": "not-a-real-operator",
            "left": value("value", "left", json!({"tag": "string"})),
            "right": value("value", "right", json!({"tag": "int"})),
            "source_location": null
        }),
        json!({
            "kind": "array_get",
            "result": value("value", "result", json!({"tag": "string"})),
            "array": value("value", "not-an-array", json!({"tag": "bool"})),
            "index": value("value", "negative-or-past-end", json!({"tag": "bool"})),
            "borrowed": true,
            "borrow_scope": "unresolved::scope",
            "source_location": null
        }),
        json!({
            "kind": "matrix_mat_mul",
            "result": value("value", "result", json!({"tag": "string"})),
            "left": value("value", "left", json!({"tag": "bool"})),
            "right": value("value", "right", json!({"tag": "int"})),
            "shape": [-2, 0, -7]
        }),
        json!({
            "kind": "branch",
            "condition": value("value", "non-boolean", json!({"tag": "int"})),
            "true_target": "missing::then",
            "false_target": "missing::else"
        }),
        json!({
            "kind": "return",
            "value": value("value", "incompatible-return", json!({"tag": "string"})),
            "transferred_storage": null
        }),
    ];

    for json in cases {
        assert!(
            import_json(json).is_ok(),
            "structurally representable semantics belong to the verifier"
        );
    }
}
