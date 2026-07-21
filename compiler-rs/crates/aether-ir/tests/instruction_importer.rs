//! Focused coverage for schema-v1 lifecycle instruction import.

use std::error::Error as _;

use aether_ir::wire::{IRFloatDTO, IRInstructionDTO};
use aether_ir::{
    ArrayType, BoolType, EnumType, IRConstant, IREnumConstant, IRImportError, IRInstruction,
    IRSourceLocation, IRStorage, IRType, IRValue, IntType, ListType, NullableType, StringType,
    import_instruction,
};
use serde_json::{Value, json};

fn int_value(name: &str) -> IRValue {
    IRValue::new(name, IntType.into())
}

fn string_value(name: &str) -> IRValue {
    IRValue::new(name, StringType.into())
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
fn explicitly_rejects_a_not_yet_supported_instruction_kind() {
    let wire: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "binary_op",
        "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
        "operator": "+",
        "left": {"tag": "value", "name": "left", "type": {"tag": "int"}},
        "right": {"tag": "value", "name": "right", "type": {"tag": "int"}},
        "source_location": null
    }))
    .expect("unsupported instruction JSON must still deserialize");

    let error = import_instruction(&wire).expect_err("binary operators are a later importer slice");
    assert_eq!(
        error,
        IRImportError::UnsupportedInstruction { kind: "binary_op" }
    );
    assert_eq!(
        error.to_string(),
        "instruction DTO kind 'binary_op' is not supported by the incremental importer"
    );
}
