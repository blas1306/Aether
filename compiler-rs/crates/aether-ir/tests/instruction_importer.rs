//! Focused coverage for schema-v1 lifecycle, operator, cast, and call-family import.

use std::error::Error as _;

use aether_ir::wire::{IRFloatDTO, IRInstructionDTO};
use aether_ir::{
    ArrayType, BoolType, DoubleType, EnumType, FunctionType, IRConstant, IREnumConstant,
    IRImportError, IRInstruction, IRSourceLocation, IRStorage, IRType, IRValue, IntType, ListType,
    MethodResultType, NullableType, StringType, StructType, VectorType, VoidType,
    import_instruction,
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
#[allow(clippy::too_many_lines)]
fn imports_call_family_exactly_through_owned_and_borrowed_paths() {
    let nested_type = nested_string_list_type();
    let vector_type = IRType::from(VectorType {
        element: Box::new(DoubleType.into()),
        orientation: Some(" row::raw ".to_owned()),
    });
    let signature = IRType::from(FunctionType {
        parameter_types: vec![IntType.into(), nested_type.clone()],
        return_type: Box::new(vector_type.clone()),
    });
    let present_location = location(-31, i64::MAX, Some(" src/calls\0raw.ae "));

    let cases = vec![
        (
            json!({
                "kind": "call",
                "function": " unresolved::zero ",
                "arguments": [],
                "result": null,
                "builtin": null,
                "source_location": null
            }),
            IRInstruction::IRCall {
                function: " unresolved::zero ".to_owned(),
                arguments: vec![],
                result: None,
                builtin: None,
                source_location: None,
            },
        ),
        (
            json!({
                "kind": "call",
                "function": "module::one",
                "arguments": [{
                    "tag": "parameter",
                    "name": "only::argument",
                    "type": {
                        "tag": "list",
                        "element": {"tag": "nullable", "inner": {"tag": "string"}}
                    }
                }],
                "result": {"tag": "value", "name": "call::result", "type": {"tag": "bool"}},
                "builtin": " builtin::identifier\0raw ",
                "source_location": location_json(
                    -31,
                    i64::MAX,
                    Some(" src/calls\0raw.ae ")
                )
            }),
            IRInstruction::IRCall {
                function: "module::one".to_owned(),
                arguments: vec![IRValue::new("only::argument", nested_type.clone())],
                result: Some(IRValue::new("call::result", BoolType.into())),
                builtin: Some(" builtin::identifier\0raw ".to_owned()),
                source_location: Some(present_location),
            },
        ),
        (
            json!({
                "kind": "call",
                "function": "ordered::many",
                "arguments": [
                    {"tag": "value", "name": "first", "type": {"tag": "string"}},
                    {"tag": "storage", "name": "second", "type": {"tag": "int"}},
                    {
                        "tag": "parameter",
                        "name": "third",
                        "type": {
                            "tag": "vector",
                            "element": {"tag": "double"},
                            "orientation": " row::raw "
                        }
                    }
                ],
                "result": null,
                "builtin": "",
                "source_location": {
                    "tag": "source_location",
                    "line": 0,
                    "column": -9,
                    "path": null
                }
            }),
            IRInstruction::IRCall {
                function: "ordered::many".to_owned(),
                arguments: vec![
                    string_value("first"),
                    int_value("second"),
                    IRValue::new("third", vector_type.clone()),
                ],
                result: None,
                builtin: Some(String::new()),
                source_location: Some(location(0, -9, None)),
            },
        ),
        (
            json!({
                "kind": "function_ref",
                "result": {
                    "tag": "value",
                    "name": "typed::function_ref",
                    "type": {
                        "tag": "function",
                        "parameter_types": [
                            {"tag": "int"},
                            {
                                "tag": "list",
                                "element": {"tag": "nullable", "inner": {"tag": "string"}}
                            }
                        ],
                        "return_type": {
                            "tag": "vector",
                            "element": {"tag": "double"},
                            "orientation": " row::raw "
                        }
                    }
                },
                "function": " unresolved::function_ref\0raw "
            }),
            IRInstruction::IRFunctionRef {
                result: IRValue::new("typed::function_ref", signature.clone()),
                function: " unresolved::function_ref\0raw ".to_owned(),
            },
        ),
        (
            json!({
                "kind": "call_indirect",
                "callee": {
                    "tag": "value",
                    "name": "indirect::target",
                    "type": {
                        "tag": "function",
                        "parameter_types": [
                            {"tag": "int"},
                            {
                                "tag": "list",
                                "element": {"tag": "nullable", "inner": {"tag": "string"}}
                            }
                        ],
                        "return_type": {
                            "tag": "vector",
                            "element": {"tag": "double"},
                            "orientation": " row::raw "
                        }
                    }
                },
                "arguments": [
                    {"tag": "value", "name": "first::indirect", "type": {"tag": "bool"}},
                    {"tag": "value", "name": "second::indirect", "type": {"tag": "string"}}
                ],
                "result": {"tag": "storage", "name": "indirect::result", "type": {"tag": "string"}}
            }),
            IRInstruction::IRCallIndirect {
                callee: IRValue::new("indirect::target", signature),
                arguments: vec![
                    IRValue::new("first::indirect", BoolType.into()),
                    string_value("second::indirect"),
                ],
                result: Some(string_value("indirect::result")),
            },
        ),
        (
            json!({
                "kind": "call_indirect",
                "callee": {"tag": "parameter", "name": "empty::target", "type": {"tag": "int"}},
                "arguments": [],
                "result": null
            }),
            IRInstruction::IRCallIndirect {
                callee: int_value("empty::target"),
                arguments: vec![],
                result: None,
            },
        ),
        (
            json!({
                "kind": "print",
                "value": {
                    "tag": "value",
                    "name": "print::nested",
                    "type": {
                        "tag": "list",
                        "element": {"tag": "nullable", "inner": {"tag": "string"}}
                    }
                },
                "newline": true,
                "aggregate_shape": [i64::MIN, 0, i64::MAX]
            }),
            IRInstruction::IRPrint {
                value: IRValue::new("print::nested", nested_type),
                newline: true,
                aggregate_shape: Some(vec![i64::MIN, 0, i64::MAX]),
            },
        ),
        (
            json!({
                "kind": "print",
                "value": {"tag": "parameter", "name": "print::scalar", "type": {"tag": "int"}},
                "newline": false,
                "aggregate_shape": null
            }),
            IRInstruction::IRPrint {
                value: int_value("print::scalar"),
                newline: false,
                aggregate_shape: None,
            },
        ),
    ];

    assert_eq!(cases.len(), 8);
    for (json, expected) in cases {
        let wire: IRInstructionDTO =
            serde_json::from_value(json).expect("call-family instruction JSON must deserialize");
        let original = wire.clone();

        assert_eq!(import_instruction(&wire), Ok(expected.clone()));
        assert_eq!(import_instruction(&wire), Ok(expected.clone()));
        assert_eq!(IRInstruction::try_from(&wire), Ok(expected.clone()));
        assert_eq!(IRInstruction::try_from(wire.clone()), Ok(expected));
        assert_eq!(wire, original, "borrowed import must not mutate its DTO");
    }
}

#[test]
fn imports_unresolved_calls_and_signature_mismatches_for_the_verifier() {
    let direct: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "call",
        "function": "definitely::unresolved",
        "arguments": [{"tag": "value", "name": "wrong::argument", "type": {"tag": "string"}}],
        "result": {"tag": "value", "name": "wrong::result", "type": {"tag": "bool"}},
        "builtin": "not-a-legal-builtin",
        "source_location": null
    }))
    .expect("unresolved and mismatched direct call is structurally valid");
    let indirect: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "call_indirect",
        "callee": {
            "tag": "value",
            "name": "not-even-a-function",
            "type": {
                "tag": "function",
                "parameter_types": [{"tag": "int"}],
                "return_type": {"tag": "double"}
            }
        },
        "arguments": [],
        "result": {"tag": "value", "name": "mismatched::result", "type": {"tag": "string"}}
    }))
    .expect("signature-mismatched indirect call is structurally valid");

    assert!(matches!(
        import_instruction(&direct),
        Ok(IRInstruction::IRCall { .. })
    ));
    assert!(matches!(
        import_instruction(&indirect),
        Ok(IRInstruction::IRCallIndirect { .. })
    ));
}

#[test]
fn gives_call_instruction_and_field_context_for_nested_errors() {
    let wire: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "call",
        "function": "callee",
        "arguments": [{
            "tag": "parameter",
            "name": "bad::argument",
            "type": {
                "tag": "method_result",
                "receiver": {"tag": "array", "element": {"tag": "int"}},
                "value": {"tag": "bool"}
            }
        }],
        "result": null,
        "builtin": null,
        "source_location": null
    }))
    .expect("the wire model permits the unrepresentable nested argument type");

    assert_eq!(
        import_instruction(&wire),
        Err(IRImportError::InstructionField {
            instruction: "call",
            field: "arguments",
            source: Box::new(IRImportError::ValueType {
                kind: "parameter",
                source: Box::new(IRImportError::MethodResultReceiverNotStruct { actual: "array" }),
            }),
        })
    );
}

#[test]
#[allow(clippy::too_many_lines)]
fn imports_struct_family_exactly_through_owned_and_borrowed_paths() {
    let outer_type = IRType::from(StructType {
        name: " Missing::Outer\0raw ".to_owned(),
    });
    let inner_type = IRType::from(StructType {
        name: " Nested::Inner ".to_owned(),
    });
    let nested_payload_type = nested_string_list_type();
    let method_result_type = IRType::from(MethodResultType {
        receiver: StructType {
            name: " Missing::Outer\0raw ".to_owned(),
        },
        value: Box::new(nested_payload_type.clone()),
    });
    let void_method_result_type = IRType::from(MethodResultType {
        receiver: StructType {
            name: " Missing::Outer\0raw ".to_owned(),
        },
        value: Box::new(VoidType.into()),
    });

    let cases = vec![
        (
            json!({
                "kind": "struct_new",
                "result": {
                    "tag": "value",
                    "name": " constructed::outer ",
                    "type": {"tag": "struct", "name": " Missing::Outer\0raw "}
                },
                "fields": [
                    {
                        "tag": "storage",
                        "name": "third::nested",
                        "type": {"tag": "struct", "name": " Nested::Inner "}
                    },
                    {
                        "tag": "parameter",
                        "name": "first::payload",
                        "type": {
                            "tag": "list",
                            "element": {"tag": "nullable", "inner": {"tag": "string"}}
                        }
                    },
                    {"tag": "value", "name": "second::flag", "type": {"tag": "bool"}}
                ]
            }),
            IRInstruction::IRStructNew {
                result: IRValue::new(" constructed::outer ", outer_type.clone()),
                fields: vec![
                    IRValue::new("third::nested", inner_type),
                    IRValue::new("first::payload", nested_payload_type.clone()),
                    IRValue::new("second::flag", BoolType.into()),
                ],
            },
        ),
        (
            json!({
                "kind": "struct_get",
                "result": {"tag": "value", "name": "get::result", "type": {"tag": "string"}},
                "struct": {
                    "tag": "parameter",
                    "name": "get::receiver",
                    "type": {"tag": "struct", "name": " Missing::Outer\0raw "}
                },
                "field_index": i64::MIN,
                "field_name": " unknown::field\0raw "
            }),
            IRInstruction::IRStructGet {
                result: string_value("get::result"),
                r#struct: IRValue::new("get::receiver", outer_type.clone()),
                field_index: i64::MIN,
                field_name: " unknown::field\0raw ".to_owned(),
            },
        ),
        (
            json!({
                "kind": "struct_set",
                "result": {"tag": "storage", "name": "set::result", "type": {"tag": "bool"}},
                "struct": {"tag": "value", "name": "set::not_a_struct", "type": {"tag": "int"}},
                "field_index": i64::MAX,
                "field_name": "missing::replacement",
                "value": {
                    "tag": "parameter",
                    "name": "set::wrong_type",
                    "type": {
                        "tag": "vector",
                        "element": {"tag": "double"},
                        "orientation": " diagonal::raw "
                    }
                }
            }),
            IRInstruction::IRStructSet {
                result: IRValue::new("set::result", BoolType.into()),
                r#struct: int_value("set::not_a_struct"),
                field_index: i64::MAX,
                field_name: "missing::replacement".to_owned(),
                value: IRValue::new(
                    "set::wrong_type",
                    VectorType {
                        element: Box::new(DoubleType.into()),
                        orientation: Some(" diagonal::raw ".to_owned()),
                    }
                    .into(),
                ),
            },
        ),
        (
            json!({
                "kind": "method_result_new",
                "result": {
                    "tag": "value",
                    "name": "method::pair",
                    "type": {
                        "tag": "method_result",
                        "receiver": {"tag": "struct", "name": " Missing::Outer\0raw "},
                        "value": {
                            "tag": "list",
                            "element": {"tag": "nullable", "inner": {"tag": "string"}}
                        }
                    }
                },
                "receiver": {
                    "tag": "storage",
                    "name": "method::receiver",
                    "type": {"tag": "struct", "name": " Missing::Outer\0raw "}
                },
                "value": {
                    "tag": "parameter",
                    "name": "method::payload",
                    "type": {
                        "tag": "list",
                        "element": {"tag": "nullable", "inner": {"tag": "string"}}
                    }
                }
            }),
            IRInstruction::IRMethodResultNew {
                result: IRValue::new("method::pair", method_result_type.clone()),
                receiver: IRValue::new("method::receiver", outer_type.clone()),
                value: Some(IRValue::new("method::payload", nested_payload_type.clone())),
            },
        ),
        (
            json!({
                "kind": "method_result_new",
                "result": {
                    "tag": "value",
                    "name": "method::void_pair",
                    "type": {
                        "tag": "method_result",
                        "receiver": {"tag": "struct", "name": " Missing::Outer\0raw "},
                        "value": {"tag": "void"}
                    }
                },
                "receiver": {
                    "tag": "value",
                    "name": "method::void_receiver",
                    "type": {"tag": "struct", "name": " Missing::Outer\0raw "}
                },
                "value": null
            }),
            IRInstruction::IRMethodResultNew {
                result: IRValue::new("method::void_pair", void_method_result_type),
                receiver: IRValue::new("method::void_receiver", outer_type.clone()),
                value: None,
            },
        ),
        (
            json!({
                "kind": "method_result_receiver",
                "result": {
                    "tag": "value",
                    "name": "extracted::receiver",
                    "type": {"tag": "struct", "name": " Missing::Outer\0raw "}
                },
                "method_result": {
                    "tag": "parameter",
                    "name": "extract::pair",
                    "type": {
                        "tag": "method_result",
                        "receiver": {"tag": "struct", "name": " Missing::Outer\0raw "},
                        "value": {
                            "tag": "list",
                            "element": {"tag": "nullable", "inner": {"tag": "string"}}
                        }
                    }
                }
            }),
            IRInstruction::IRMethodResultReceiver {
                result: IRValue::new("extracted::receiver", outer_type.clone()),
                method_result: IRValue::new("extract::pair", method_result_type.clone()),
            },
        ),
        (
            json!({
                "kind": "method_result_value",
                "result": {
                    "tag": "storage",
                    "name": "extracted::payload",
                    "type": {
                        "tag": "list",
                        "element": {"tag": "nullable", "inner": {"tag": "string"}}
                    }
                },
                "method_result": {
                    "tag": "value",
                    "name": "extract::pair",
                    "type": {
                        "tag": "method_result",
                        "receiver": {"tag": "struct", "name": " Missing::Outer\0raw "},
                        "value": {
                            "tag": "list",
                            "element": {"tag": "nullable", "inner": {"tag": "string"}}
                        }
                    }
                }
            }),
            IRInstruction::IRMethodResultValue {
                result: IRValue::new("extracted::payload", nested_payload_type),
                method_result: IRValue::new("extract::pair", method_result_type),
            },
        ),
    ];

    assert_eq!(cases.len(), 7);
    for (json, expected) in cases {
        let encoded =
            serde_json::to_string(&json).expect("struct JSON must encode deterministically");
        let wire: IRInstructionDTO =
            serde_json::from_str(&encoded).expect("struct-family JSON must deserialize");
        let original = wire.clone();

        assert_eq!(import_instruction(&wire), Ok(expected.clone()));
        assert_eq!(import_instruction(&wire), Ok(expected.clone()));
        assert_eq!(IRInstruction::try_from(&wire), Ok(expected.clone()));
        assert_eq!(IRInstruction::try_from(wire.clone()), Ok(expected));
        assert_eq!(wire, original, "borrowed import must not mutate its DTO");
    }
}

#[test]
fn preserves_struct_constructor_field_order() {
    let wire: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "struct_new",
        "result": {
            "tag": "value",
            "name": "ordered",
            "type": {"tag": "struct", "name": "UnknownOrdered"}
        },
        "fields": [
            {"tag": "value", "name": "third", "type": {"tag": "string"}},
            {"tag": "value", "name": "first", "type": {"tag": "bool"}},
            {"tag": "value", "name": "second", "type": {"tag": "int"}},
            {"tag": "value", "name": "third", "type": {"tag": "string"}}
        ]
    }))
    .expect("ordered constructor fields must deserialize");

    let IRInstruction::IRStructNew { result, fields } =
        import_instruction(&wire).expect("unknown structs and duplicate fields are representable")
    else {
        panic!("expected a struct_new instruction");
    };

    assert_eq!(
        result.r#type,
        StructType {
            name: "UnknownOrdered".to_owned()
        }
        .into()
    );
    assert_eq!(
        fields
            .iter()
            .map(|field| field.name.as_str())
            .collect::<Vec<_>>(),
        ["third", "first", "second", "third"]
    );
}

#[test]
fn leaves_unknown_struct_fields_and_type_mismatches_to_the_verifier() {
    let get: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "struct_get",
        "result": {"tag": "value", "name": "result", "type": {"tag": "bool"}},
        "struct": {
            "tag": "value",
            "name": "receiver",
            "type": {"tag": "struct", "name": "DefinitelyMissing"}
        },
        "field_index": -91,
        "field_name": "definitely_missing"
    }))
    .expect("invalid-but-representable struct_get must deserialize");
    let set: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "struct_set",
        "result": {"tag": "value", "name": "result", "type": {"tag": "string"}},
        "struct": {"tag": "value", "name": "receiver", "type": {"tag": "bool"}},
        "field_index": -1,
        "field_name": "unknown_field",
        "value": {"tag": "value", "name": "replacement", "type": {"tag": "int"}}
    }))
    .expect("invalid-but-representable struct_set must deserialize");

    assert!(matches!(
        import_instruction(&get),
        Ok(IRInstruction::IRStructGet {
            field_index: -91,
            ref field_name,
            ..
        }) if field_name == "definitely_missing"
    ));
    assert!(matches!(
        import_instruction(&set),
        Ok(IRInstruction::IRStructSet {
            field_index: -1,
            ref field_name,
            ..
        }) if field_name == "unknown_field"
    ));
}

#[test]
fn gives_struct_instruction_and_field_context_for_nested_errors() {
    let cases = [
        (
            json!({
                "kind": "struct_new",
                "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
                "fields": [{
                    "tag": "storage",
                    "name": "bad::field",
                    "type": {
                        "tag": "method_result",
                        "receiver": {"tag": "array", "element": {"tag": "int"}},
                        "value": {"tag": "string"}
                    }
                }]
            }),
            IRImportError::InstructionField {
                instruction: "struct_new",
                field: "fields",
                source: Box::new(IRImportError::ValueType {
                    kind: "storage",
                    source: Box::new(IRImportError::MethodResultReceiverNotStruct {
                        actual: "array",
                    }),
                }),
            },
        ),
        (
            json!({
                "kind": "method_result_new",
                "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
                "receiver": {
                    "tag": "parameter",
                    "name": "bad::receiver",
                    "type": {
                        "tag": "method_result",
                        "receiver": {"tag": "list", "element": {"tag": "int"}},
                        "value": {"tag": "bool"}
                    }
                },
                "value": null
            }),
            IRImportError::InstructionField {
                instruction: "method_result_new",
                field: "receiver",
                source: Box::new(IRImportError::ValueType {
                    kind: "parameter",
                    source: Box::new(IRImportError::MethodResultReceiverNotStruct {
                        actual: "list",
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
