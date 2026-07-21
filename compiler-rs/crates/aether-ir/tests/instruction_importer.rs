//! Focused coverage for schema-v1 lifecycle, operator, and cast instruction import.

use std::error::Error as _;

use aether_ir::wire::{IRFloatDTO, IRInstructionDTO};
use aether_ir::{
    ArrayType, BoolType, DoubleType, EnumType, IRConstant, IREnumConstant, IRImportError,
    IRInstruction, IRSourceLocation, IRStorage, IRType, IRValue, IntType, ListType, NullableType,
    StringType, VectorType, import_instruction,
};
use serde_json::{Value, json};

// This is the operator inventory exercised by the frozen Python DTO contract.
const BINARY_OPERATORS: &[&str] = &[
    "add", "sub", "mul", "div", "rem", "mod", "pow", "eq", "ne", "lt", "le", "gt", "ge", "and",
    "or",
];
const UNARY_OPERATORS: &[&str] = &["neg", "not"];
const COMPARE_OPERATORS: &[&str] = &["eq", "ne", "lt", "le", "gt", "ge"];

fn int_value(name: &str) -> IRValue {
    IRValue::new(name, IntType.into())
}

fn string_value(name: &str) -> IRValue {
    IRValue::new(name, StringType.into())
}

fn nested_string_list_type() -> IRType {
    ListType {
        element: Box::new(
            NullableType {
                inner: Box::new(StringType.into()),
            }
            .into(),
        ),
    }
    .into()
}

fn int_storage(name: &str) -> IRStorage {
    IRStorage::new(name, IntType.into())
}

fn location(line: i64, column: i64, path: Option<&str>) -> IRSourceLocation {
    IRSourceLocation {
        line,
        column,
        path: path.map(str::to_owned),
    }
}

fn location_json(line: i64, column: i64, path: Option<&str>) -> Value {
    json!({
        "tag": "source_location",
        "line": line,
        "column": column,
        "path": path,
    })
}

#[test]
#[allow(clippy::too_many_lines)]
fn imports_all_lifecycle_variants_exactly_through_owned_and_borrowed_paths() {
    let ordered_enum_type = IRType::from(EnumType {
        name: " Status::Raw ".to_owned(),
        variants: vec!["third".to_owned(), "first".to_owned(), "third".to_owned()],
        display_name: None,
    });
    let nested_list_type = IRType::from(ListType {
        element: Box::new(
            NullableType {
                inner: Box::new(StringType.into()),
            }
            .into(),
        ),
    });
    let nested_array_type = IRType::from(ArrayType {
        element: Box::new(
            NullableType {
                inner: Box::new(BoolType.into()),
            }
            .into(),
        ),
    });
    let present_location = location(-7, i64::MAX, Some(" src/odd\0name.ae "));

    let cases = vec![
        (
            json!({
                "kind": "const",
                "result": {
                    "tag": "value",
                    "name": " result::enum ",
                    "type": {
                        "tag": "enum",
                        "name": " Status::Raw ",
                        "variants": ["third", "first", "third"],
                        "display_name": null
                    }
                },
                "value": {
                    "tag": "enum",
                    "value": {
                        "tag": "enum_constant",
                        "enum_name": " Status::Raw ",
                        "member_name": "third",
                        "member_id": 2,
                        "discriminant": -91
                    }
                }
            }),
            IRInstruction::IRConst {
                result: IRValue::new(" result::enum ", ordered_enum_type),
                value: IRConstant::Enum(IREnumConstant {
                    enum_name: " Status::Raw ".to_owned(),
                    member_name: "third".to_owned(),
                    member_id: 2,
                    discriminant: -91,
                }),
            },
        ),
        (
            json!({
                "kind": "load",
                "result": {"tag": "value", "name": "loaded", "type": {"tag": "bool"}},
                "slot": {
                    "tag": "storage",
                    "name": "unresolved::load_slot",
                    "type": {
                        "tag": "list",
                        "element": {"tag": "nullable", "inner": {"tag": "string"}}
                    }
                }
            }),
            IRInstruction::IRLoad {
                result: IRValue::new("loaded", BoolType.into()),
                slot: IRValue::new("unresolved::load_slot", nested_list_type),
            },
        ),
        (
            json!({
                "kind": "store",
                "slot": {"tag": "storage", "name": "missing::slot", "type": {"tag": "int"}},
                "value": {"tag": "parameter", "name": "text_parameter", "type": {"tag": "string"}}
            }),
            IRInstruction::IRStore {
                slot: int_value("missing::slot"),
                value: string_value("text_parameter"),
            },
        ),
        (
            json!({
                "kind": "init_default",
                "destination": {
                    "tag": "storage",
                    "name": "never_declared::destination",
                    "type": {
                        "tag": "array",
                        "element": {"tag": "nullable", "inner": {"tag": "bool"}}
                    }
                },
                "source_location": null
            }),
            IRInstruction::IRInitDefault {
                destination: IRStorage::new("never_declared::destination", nested_array_type),
                source_location: None,
            },
        ),
        (
            json!({
                "kind": "copy_init",
                "destination": {"tag": "storage", "name": "copy::destination", "type": {"tag": "int"}},
                "source": {"tag": "parameter", "name": "copy::source", "type": {"tag": "string"}},
                "source_location": location_json(-7, i64::MAX, Some(" src/odd\0name.ae "))
            }),
            IRInstruction::IRCopyInit {
                destination: int_storage("copy::destination"),
                source: string_value("copy::source"),
                source_location: Some(present_location.clone()),
            },
        ),
        (
            json!({
                "kind": "move_init",
                "destination": {"tag": "storage", "name": "move::destination", "type": {"tag": "string"}},
                "source": {"tag": "storage", "name": "move::source", "type": {"tag": "int"}},
                "source_location": null
            }),
            IRInstruction::IRMoveInit {
                destination: IRStorage::new("move::destination", StringType.into()),
                source: int_storage("move::source"),
                source_location: None,
            },
        ),
        (
            json!({
                "kind": "assign",
                "destination": {"tag": "storage", "name": "assign::destination", "type": {"tag": "bool"}},
                "source": {"tag": "value", "name": "assign::source", "type": {"tag": "int"}},
                "source_location": location_json(0, -1, None)
            }),
            IRInstruction::IRAssign {
                destination: IRStorage::new("assign::destination", BoolType.into()),
                source: int_value("assign::source"),
                source_location: Some(location(0, -1, None)),
            },
        ),
        (
            json!({
                "kind": "destroy",
                "value": {"tag": "storage", "name": "destroy::unresolved", "type": {"tag": "string"}},
                "source_location": null
            }),
            IRInstruction::IRDestroy {
                value: IRStorage::new("destroy::unresolved", StringType.into()),
                source_location: None,
            },
        ),
        (
            json!({
                "kind": "relocate",
                "destination": {"tag": "storage", "name": "relocate::destination", "type": {"tag": "int"}},
                "source": {"tag": "storage", "name": "relocate::source", "type": {"tag": "string"}},
                "count": i64::MIN,
                "source_location": location_json(-7, i64::MAX, Some(" src/odd\0name.ae "))
            }),
            IRInstruction::IRRelocate {
                destination: int_storage("relocate::destination"),
                source: IRStorage::new("relocate::source", StringType.into()),
                count: i64::MIN,
                source_location: Some(present_location),
            },
        ),
    ];

    assert_eq!(cases.len(), 9);
    for (json, expected) in cases {
        let wire: IRInstructionDTO =
            serde_json::from_value(json).expect("lifecycle instruction JSON must deserialize");
        let original = wire.clone();

        assert_eq!(import_instruction(&wire), Ok(expected.clone()));
        assert_eq!(import_instruction(&wire), Ok(expected.clone()));
        assert_eq!(IRInstruction::try_from(&wire), Ok(expected.clone()));
        assert_eq!(IRInstruction::try_from(wire.clone()), Ok(expected));
        assert_eq!(wire, original, "borrowed import must not mutate its DTO");
    }
}

#[test]
fn gives_instruction_and_field_context_for_nested_representation_errors() {
    let wire: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "copy_init",
        "destination": {
            "tag": "storage",
            "name": "destination",
            "type": {
                "tag": "method_result",
                "receiver": {"tag": "list", "element": {"tag": "int"}},
                "value": {"tag": "bool"}
            }
        },
        "source": {"tag": "value", "name": "source", "type": {"tag": "int"}},
        "source_location": null
    }))
    .expect("the wire model permits the unrepresentable nested type");

    let error =
        import_instruction(&wire).expect_err("the owned type cannot represent the receiver");
    assert_eq!(
        error,
        IRImportError::InstructionField {
            instruction: "copy_init",
            field: "destination",
            source: Box::new(IRImportError::StorageType {
                source: Box::new(IRImportError::MethodResultReceiverNotStruct { actual: "list" }),
            }),
        }
    );
    assert_eq!(
        error.to_string(),
        "instruction DTO kind 'copy_init' field 'destination' could not be imported: storage DTO field 'type' could not be imported: method-result receiver must be a struct type, found wire type 'list'"
    );
    assert!(error.source().is_some());
}

#[test]
fn gives_constant_field_context_for_programmatic_nested_failures() {
    let wire = IRInstructionDTO::Const {
        result: aether_ir::wire::IRValueDTO::Value {
            name: "result".to_owned(),
            r#type: aether_ir::wire::IRTypeDTO::Float {},
        },
        value: aether_ir::wire::IRConstantDTO::Float {
            value: IRFloatDTO(f64::NAN),
        },
    };

    assert_eq!(
        import_instruction(&wire),
        Err(IRImportError::InstructionField {
            instruction: "const",
            field: "value",
            source: Box::new(IRImportError::NonFiniteConstantFloat { field: "value" }),
        })
    );
}

#[test]
#[allow(clippy::too_many_lines)]
fn imports_operator_and_cast_variants_exactly_through_owned_and_borrowed_paths() {
    let nested_type = nested_string_list_type();
    let vector_type = IRType::from(VectorType {
        element: Box::new(DoubleType.into()),
        orientation: Some(" column::raw ".to_owned()),
    });
    let present_location = location(-23, i64::MAX, Some(" src/operators\0raw.ae "));
    let cases = vec![
        (
            json!({
                "kind": "binary_op",
                "result": {"tag": "value", "name": "binary::result", "type": {"tag": "int"}},
                "operator": "sub",
                "left": {
                    "tag": "parameter",
                    "name": "left::nested",
                    "type": {
                        "tag": "list",
                        "element": {"tag": "nullable", "inner": {"tag": "string"}}
                    }
                },
                "right": {"tag": "storage", "name": "right::bool", "type": {"tag": "bool"}},
                "source_location": location_json(
                    -23,
                    i64::MAX,
                    Some(" src/operators\0raw.ae ")
                )
            }),
            IRInstruction::IRBinaryOp {
                result: int_value("binary::result"),
                operator: "sub".to_owned(),
                left: IRValue::new("left::nested", nested_type.clone()),
                right: IRValue::new("right::bool", BoolType.into()),
                source_location: Some(present_location),
            },
        ),
        (
            json!({
                "kind": "unary_op",
                "result": {
                    "tag": "value",
                    "name": "unary::nested_result",
                    "type": {
                        "tag": "list",
                        "element": {"tag": "nullable", "inner": {"tag": "string"}}
                    }
                },
                "operator": "not",
                "operand": {
                    "tag": "value",
                    "name": "unary::vector_operand",
                    "type": {
                        "tag": "vector",
                        "element": {"tag": "double"},
                        "orientation": " column::raw "
                    }
                }
            }),
            IRInstruction::IRUnaryOp {
                result: IRValue::new("unary::nested_result", nested_type.clone()),
                operator: "not".to_owned(),
                operand: IRValue::new("unary::vector_operand", vector_type.clone()),
            },
        ),
        (
            json!({
                "kind": "compare_op",
                "result": {"tag": "value", "name": "compare::result", "type": {"tag": "bool"}},
                "operator": "ge",
                "left": {
                    "tag": "value",
                    "name": "compare::left",
                    "type": {
                        "tag": "vector",
                        "element": {"tag": "double"},
                        "orientation": " column::raw "
                    }
                },
                "right": {"tag": "value", "name": "compare::right", "type": {"tag": "int"}},
                "aggregate_shape": [i64::MIN, 0, i64::MAX]
            }),
            IRInstruction::IRCompareOp {
                result: IRValue::new("compare::result", BoolType.into()),
                operator: "ge".to_owned(),
                left: IRValue::new("compare::left", vector_type),
                right: int_value("compare::right"),
                aggregate_shape: Some(vec![i64::MIN, 0, i64::MAX]),
            },
        ),
        (
            json!({
                "kind": "cast",
                "result": {
                    "tag": "value",
                    "name": "cast::nested_target",
                    "type": {
                        "tag": "list",
                        "element": {"tag": "nullable", "inner": {"tag": "string"}}
                    }
                },
                "value": {"tag": "parameter", "name": "cast::int_source", "type": {"tag": "int"}}
            }),
            IRInstruction::IRCast {
                result: IRValue::new("cast::nested_target", nested_type),
                value: int_value("cast::int_source"),
            },
        ),
    ];

    assert_eq!(cases.len(), 4);
    for (json, expected) in cases {
        let wire: IRInstructionDTO =
            serde_json::from_value(json).expect("operator/cast instruction JSON must deserialize");
        let original = wire.clone();

        assert_eq!(import_instruction(&wire), Ok(expected.clone()));
        assert_eq!(import_instruction(&wire), Ok(expected.clone()));
        assert_eq!(IRInstruction::try_from(&wire), Ok(expected.clone()));
        assert_eq!(IRInstruction::try_from(wire.clone()), Ok(expected));
        assert_eq!(wire, original, "borrowed import must not mutate its DTO");
    }
}

#[test]
fn imports_every_contract_binary_operator_without_rewriting_it() {
    for operator in BINARY_OPERATORS {
        let wire: IRInstructionDTO = serde_json::from_value(json!({
            "kind": "binary_op",
            "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
            "operator": operator,
            "left": {"tag": "value", "name": "left", "type": {"tag": "int"}},
            "right": {"tag": "value", "name": "right", "type": {"tag": "int"}},
            "source_location": null
        }))
        .expect("known binary operator JSON must deserialize");

        assert_eq!(
            import_instruction(&wire),
            Ok(IRInstruction::IRBinaryOp {
                result: int_value("result"),
                operator: (*operator).to_owned(),
                left: int_value("left"),
                right: int_value("right"),
                source_location: None,
            })
        );
    }
}

#[test]
fn imports_every_contract_unary_operator_without_rewriting_it() {
    for operator in UNARY_OPERATORS {
        let wire: IRInstructionDTO = serde_json::from_value(json!({
            "kind": "unary_op",
            "result": {"tag": "value", "name": "result", "type": {"tag": "bool"}},
            "operator": operator,
            "operand": {"tag": "value", "name": "operand", "type": {"tag": "string"}}
        }))
        .expect("known unary operator JSON must deserialize");

        assert_eq!(
            import_instruction(&wire),
            Ok(IRInstruction::IRUnaryOp {
                result: IRValue::new("result", BoolType.into()),
                operator: (*operator).to_owned(),
                operand: string_value("operand"),
            })
        );
    }
}

#[test]
fn imports_every_contract_compare_operator_without_rewriting_it() {
    for operator in COMPARE_OPERATORS {
        let wire: IRInstructionDTO = serde_json::from_value(json!({
            "kind": "compare_op",
            "result": {"tag": "value", "name": "result", "type": {"tag": "bool"}},
            "operator": operator,
            "left": {"tag": "value", "name": "left", "type": {"tag": "string"}},
            "right": {"tag": "value", "name": "right", "type": {"tag": "int"}},
            "aggregate_shape": null
        }))
        .expect("known compare operator JSON must deserialize");

        assert_eq!(
            import_instruction(&wire),
            Ok(IRInstruction::IRCompareOp {
                result: IRValue::new("result", BoolType.into()),
                operator: (*operator).to_owned(),
                left: string_value("left"),
                right: int_value("right"),
                aggregate_shape: None,
            })
        );
    }
}

#[test]
fn preserves_binary_operand_order_and_present_or_absent_locations() {
    let cases = [
        ("left::first", "right::second", None),
        (
            "left::still_first",
            "right::still_second",
            Some(location(8, 13, None)),
        ),
    ];

    for (left_name, right_name, source_location) in cases {
        let wire: IRInstructionDTO = serde_json::from_value(json!({
            "kind": "binary_op",
            "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
            "operator": "div",
            "left": {"tag": "value", "name": left_name, "type": {"tag": "int"}},
            "right": {"tag": "value", "name": right_name, "type": {"tag": "int"}},
            "source_location": source_location.as_ref().map(|location| location_json(
                location.line,
                location.column,
                location.path.as_deref()
            ))
        }))
        .expect("binary operator JSON must deserialize");

        assert_eq!(
            import_instruction(&wire),
            Ok(IRInstruction::IRBinaryOp {
                result: int_value("result"),
                operator: "div".to_owned(),
                left: int_value(left_name),
                right: int_value(right_name),
                source_location,
            })
        );
    }
}

#[test]
fn imports_representative_casts_without_checking_legality() {
    let cases = [
        (
            json!({"tag": "int"}),
            json!({"tag": "double"}),
            IntType.into(),
            DoubleType.into(),
        ),
        (
            json!({"tag": "string"}),
            json!({
                "tag": "list",
                "element": {"tag": "nullable", "inner": {"tag": "string"}}
            }),
            StringType.into(),
            nested_string_list_type(),
        ),
    ];

    for (source_json, target_json, source_type, target_type) in cases {
        let wire: IRInstructionDTO = serde_json::from_value(json!({
            "kind": "cast",
            "result": {"tag": "value", "name": "target", "type": target_json},
            "value": {"tag": "value", "name": "source", "type": source_json}
        }))
        .expect("cast JSON must deserialize");

        assert_eq!(
            import_instruction(&wire),
            Ok(IRInstruction::IRCast {
                result: IRValue::new("target", target_type),
                value: IRValue::new("source", source_type),
            })
        );
    }
}

#[test]
fn preserves_unknown_operator_spellings_for_the_verifier() {
    let cases = [
        (
            json!({
                "kind": "binary_op",
                "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
                "operator": " future::binary + raw ",
                "left": {"tag": "value", "name": "left", "type": {"tag": "int"}},
                "right": {"tag": "value", "name": "right", "type": {"tag": "int"}},
                "source_location": null
            }),
            " future::binary + raw ",
        ),
        (
            json!({
                "kind": "unary_op",
                "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
                "operator": "future_unary\0raw",
                "operand": {"tag": "value", "name": "operand", "type": {"tag": "int"}}
            }),
            "future_unary\0raw",
        ),
        (
            json!({
                "kind": "compare_op",
                "result": {"tag": "value", "name": "result", "type": {"tag": "bool"}},
                "operator": "FutureCompare",
                "left": {"tag": "value", "name": "left", "type": {"tag": "int"}},
                "right": {"tag": "value", "name": "right", "type": {"tag": "int"}},
                "aggregate_shape": null
            }),
            "FutureCompare",
        ),
    ];

    for (json, expected_operator) in cases {
        let wire: IRInstructionDTO =
            serde_json::from_value(json).expect("unknown operator spelling must deserialize");
        let imported = import_instruction(&wire).expect("unknown spelling is representable");
        let operator = match imported {
            IRInstruction::IRBinaryOp { operator, .. }
            | IRInstruction::IRUnaryOp { operator, .. }
            | IRInstruction::IRCompareOp { operator, .. } => Some(operator),
            _ => None,
        };

        assert_eq!(operator.as_deref(), Some(expected_operator));
    }
}

#[test]
fn imports_structurally_valid_operator_type_mismatches() {
    let wire: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "binary_op",
        "result": {"tag": "value", "name": "result", "type": {"tag": "string"}},
        "operator": "pow",
        "left": {"tag": "value", "name": "left", "type": {"tag": "bool"}},
        "right": {
            "tag": "value",
            "name": "right",
            "type": {"tag": "array", "element": {"tag": "double"}}
        },
        "source_location": null
    }))
    .expect("type-mismatched operator is structurally valid");

    assert!(matches!(
        import_instruction(&wire),
        Ok(IRInstruction::IRBinaryOp { .. })
    ));
}

#[test]
fn gives_operator_instruction_and_field_context_for_nested_errors() {
    let wire: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "compare_op",
        "result": {"tag": "value", "name": "result", "type": {"tag": "bool"}},
        "operator": "eq",
        "left": {"tag": "value", "name": "left", "type": {"tag": "int"}},
        "right": {
            "tag": "parameter",
            "name": "right",
            "type": {
                "tag": "method_result",
                "receiver": {"tag": "array", "element": {"tag": "int"}},
                "value": {"tag": "bool"}
            }
        },
        "aggregate_shape": null
    }))
    .expect("the wire model permits the unrepresentable nested type");

    assert_eq!(
        import_instruction(&wire),
        Err(IRImportError::InstructionField {
            instruction: "compare_op",
            field: "right",
            source: Box::new(IRImportError::ValueType {
                kind: "parameter",
                source: Box::new(IRImportError::MethodResultReceiverNotStruct { actual: "array" }),
            }),
        })
    );
}

#[test]
fn explicitly_rejects_a_later_instruction_family() {
    let wire: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "call",
        "function": "later::callee",
        "arguments": [],
        "result": null,
        "builtin": null,
        "source_location": null
    }))
    .expect("unsupported instruction JSON must still deserialize");

    let error = import_instruction(&wire).expect_err("calls are a later importer slice");
    assert_eq!(
        error,
        IRImportError::UnsupportedInstruction { kind: "call" }
    );
    assert_eq!(
        error.to_string(),
        "instruction DTO kind 'call' is not supported by the incremental importer"
    );
}
