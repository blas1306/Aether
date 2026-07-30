//! Focused coverage for schema-v1 module and struct-definition import.

use std::error::Error as _;

use aether_ir::wire::{
    IR_SCHEMA_VERSION, IRFunctionDTO, IRModuleDTO, IRParameterDTO, IRStructDefinitionDTO,
    IRStructFieldDTO, IRTypeDTO,
};
use aether_ir::{
    ArrayType, BoolType, IRConstant, IRImportError, IRInstruction, IRModule, IRStructDefinition,
    IRType, IntType, ListType, NullableType, StringType, StructType, import_module,
    import_struct_definition,
};
use serde_json::{Value, json};

const GOLDEN: &str =
    include_str!("../../../../tests/aether/rust_migration/fixtures/ir_module_v1_golden.json");

fn type_json(tag: &str) -> Value {
    json!({"tag": tag})
}

fn field_json(name: &str, r#type: &Value) -> Value {
    json!({"name": name, "type": r#type})
}

fn struct_json(name: &str, fields: &[Value]) -> Value {
    json!({"name": name, "fields": fields})
}

fn function_json(name: &str, return_type: &Value, instructions: &[Value]) -> Value {
    json!({
        "name": name,
        "parameters": [],
        "return_type": return_type,
        "blocks": [{"name": "entry", "instructions": instructions}]
    })
}

fn module_json(functions: &[Value], structs: &[Value]) -> Value {
    json!({
        "schema_version": IR_SCHEMA_VERSION,
        "functions": functions,
        "structs": structs
    })
}

fn wire_module(functions: &[Value], structs: &[Value]) -> IRModuleDTO {
    serde_json::from_value(module_json(functions, structs))
        .expect("module fixture must be valid wire JSON")
}

fn invalid_method_result_type() -> IRTypeDTO {
    IRTypeDTO::MethodResult {
        receiver: Box::new(IRTypeDTO::List {
            element: Box::new(IRTypeDTO::Int {}),
        }),
        value: Box::new(IRTypeDTO::Int {}),
    }
}

#[test]
fn imports_empty_module_through_all_conversion_paths_without_mutating_dto() {
    let wire = wire_module(&[], &[]);
    let original = wire.clone();
    let expected = IRModule::default();

    assert_eq!(import_module(&wire), Ok(expected.clone()));
    assert_eq!(IRModule::try_from(&wire), Ok(expected.clone()));
    assert_eq!(IRModule::try_from(wire.clone()), Ok(expected));
    assert_eq!(wire, original, "borrowed import must not mutate its DTO");
}

#[test]
fn imports_only_structs_with_empty_primitive_and_recursively_nested_fields_in_order() {
    let nested = json!({
        "tag": "array",
        "element": {
            "tag": "nullable",
            "inner": {"tag": "list", "element": {"tag": "struct", "name": "Unknown"}}
        }
    });
    let wire = wire_module(
        &[],
        &[
            struct_json(" empty\0 ", &[]),
            struct_json(
                "ordered",
                &[
                    field_json("third", &type_json("bool")),
                    field_json("first", &nested),
                    field_json("second", &type_json("int")),
                ],
            ),
        ],
    );

    let imported = import_module(&wire).expect("struct-only module must import");
    assert!(imported.functions.is_empty());
    assert_eq!(
        imported.structs,
        vec![
            IRStructDefinition {
                name: " empty\0 ".to_owned(),
                fields: vec![],
            },
            IRStructDefinition {
                name: "ordered".to_owned(),
                fields: vec![
                    ("third".to_owned(), BoolType.into()),
                    (
                        "first".to_owned(),
                        ArrayType {
                            element: Box::new(
                                NullableType {
                                    inner: Box::new(
                                        ListType {
                                            element: Box::new(
                                                StructType {
                                                    name: "Unknown".to_owned(),
                                                }
                                                .into(),
                                            ),
                                        }
                                        .into(),
                                    ),
                                }
                                .into(),
                            ),
                        }
                        .into(),
                    ),
                    ("second".to_owned(), IntType.into()),
                ],
            },
        ]
    );
}

#[test]
fn struct_definition_public_api_supports_borrowed_and_owned_conversion() {
    let definition: IRStructDefinitionDTO = serde_json::from_value(struct_json(
        "Pair",
        &[
            field_json("left", &type_json("int")),
            field_json("right", &type_json("string")),
        ],
    ))
    .expect("struct fixture must deserialize");
    let expected = IRStructDefinition {
        name: "Pair".to_owned(),
        fields: vec![
            ("left".to_owned(), IntType.into()),
            ("right".to_owned(), StringType.into()),
        ],
    };

    assert_eq!(import_struct_definition(&definition), Ok(expected.clone()));
    assert_eq!(
        IRStructDefinition::try_from(&definition),
        Ok(expected.clone())
    );
    assert_eq!(IRStructDefinition::try_from(definition), Ok(expected));
}

#[test]
fn imports_only_functions_and_preserves_exact_order_and_invalid_contents() {
    let invalid_but_representable = vec![
        json!({"kind": "return", "value": null, "transferred_storage": null}),
        json!({
            "kind": "const",
            "result": {"tag": "value", "name": "after", "type": {"tag": "int"}},
            "value": {"tag": "int", "value": 9}
        }),
    ];
    let wire = wire_module(
        &[
            function_json("second", &type_json("void"), &[]),
            function_json("first", &type_json("void"), &invalid_but_representable),
            function_json("second", &type_json("int"), &[]),
        ],
        &[],
    );

    let imported = import_module(&wire)
        .expect("function uniqueness and instruction placement require verification");
    assert!(imported.structs.is_empty());
    assert_eq!(
        imported
            .functions
            .iter()
            .map(|function| function.name.as_str())
            .collect::<Vec<_>>(),
        vec!["second", "first", "second"]
    );
    assert_eq!(imported.functions[1].blocks[0].instructions.len(), 2);
    assert!(matches!(
        imported.functions[1].blocks[0].instructions[0],
        IRInstruction::IRReturn { .. }
    ));
    assert_eq!(
        imported.functions[1].blocks[0].instructions[1],
        IRInstruction::IRConst {
            result: aether_ir::IRValue::new("after", IntType.into()),
            value: IRConstant::Int(9),
        }
    );
}

#[test]
fn mixed_module_preserves_duplicates_unknown_and_recursive_nominal_types() {
    let wire = wire_module(
        &[
            function_json("same", &type_json("void"), &[]),
            function_json("same", &type_json("void"), &[]),
        ],
        &[
            struct_json(
                "Node",
                &[
                    field_json("same", &json!({"tag": "struct", "name": "Node"})),
                    field_json("same", &json!({"tag": "struct", "name": "Missing"})),
                ],
            ),
            struct_json("Node", &[]),
        ],
    );
    let original = wire.clone();

    let imported = import_module(&wire).expect("semantic module checks are out of scope");
    assert_eq!(IRModule::try_from(&wire), Ok(imported.clone()));
    assert_eq!(IRModule::try_from(wire.clone()), Ok(imported.clone()));
    assert_eq!(wire, original, "borrowed import must not mutate its DTO");
    assert_eq!(
        imported
            .structs
            .iter()
            .map(|definition| definition.name.as_str())
            .collect::<Vec<_>>(),
        vec!["Node", "Node"]
    );
    assert_eq!(
        imported.structs[0]
            .fields
            .iter()
            .map(|(name, _)| name.as_str())
            .collect::<Vec<_>>(),
        vec!["same", "same"]
    );
    assert_eq!(
        imported.structs[0].fields[0].1,
        IRType::Struct(StructType {
            name: "Node".to_owned(),
        })
    );
    assert_eq!(
        imported.structs[0].fields[1].1,
        IRType::Struct(StructType {
            name: "Missing".to_owned(),
        })
    );
}

#[test]
fn json_wire_owned_conversion_is_deterministic() {
    let json = module_json(
        &[function_json("raw function", &type_json("void"), &[])],
        &[struct_json(
            "raw struct",
            &[field_json("raw field", &type_json("int"))],
        )],
    );
    let encoded = serde_json::to_string(&json).expect("fixture JSON must serialize");
    let first: IRModuleDTO = serde_json::from_str(&encoded).expect("fixture JSON must deserialize");
    let round_trip: IRModuleDTO = serde_json::from_str(
        &serde_json::to_string(&first).expect("wire DTO must serialize deterministically"),
    )
    .expect("wire DTO must deserialize again");

    assert_eq!(round_trip, first);
    let expected = import_module(&first).expect("first import must succeed");
    assert_eq!(import_module(&first), Ok(expected.clone()));
    assert_eq!(import_module(&round_trip), Ok(expected));
}

#[test]
fn canonical_golden_imports_representative_root_and_deep_contents() {
    let wire: IRModuleDTO = serde_json::from_str(GOLDEN).expect("golden DTO must deserialize");
    let imported = import_module(&wire).expect("golden module must import");

    assert_eq!(imported.structs.len(), 1);
    assert_eq!(imported.structs[0].name, "Envelope");
    assert_eq!(imported.structs[0].fields[0].0, "payload");
    assert_eq!(
        imported.structs[0].fields[0].1,
        ArrayType {
            element: Box::new(
                StructType {
                    name: "Point".to_owned(),
                }
                .into(),
            ),
        }
        .into()
    );
    assert_eq!(imported.functions.len(), 1);
    assert_eq!(imported.functions[0].name, "choose");
    assert_eq!(imported.functions[0].parameters[0].name, "condition");
    assert_eq!(imported.functions[0].blocks[1].name, "selected");
    assert_eq!(
        imported.functions[0].blocks[1].instructions[0],
        IRInstruction::IRConst {
            result: aether_ir::IRValue::new("answer", IntType.into()),
            value: IRConstant::Int(7),
        }
    );
    match &imported.functions[0].blocks[1].instructions[1] {
        IRInstruction::IRReturn {
            value: Some(aether_ir::LifecycleSource::Storage(value)),
            transferred_storage: Some(storage),
        } => {
            assert_eq!(value.name, "answer");
            assert_eq!(storage.name, "answer");
        }
        other => panic!("expected deeply nested return, found {other:?}"),
    }
}

#[test]
fn rejects_directly_constructed_unsupported_schema_version_with_typed_values() {
    let wire = IRModuleDTO {
        schema_version: 47,
        functions: vec![],
        structs: vec![],
    };

    let error = import_module(&wire).expect_err("unsupported direct DTO must fail");
    assert_eq!(
        error,
        IRImportError::UnsupportedSchemaVersion {
            received: 47,
            supported: IR_SCHEMA_VERSION,
        }
    );
    assert!(error.source().is_none());
}

#[test]
fn struct_field_failure_retains_module_struct_field_and_type_source_chain() {
    let type_error = IRImportError::MethodResultReceiverNotStruct { actual: "list" };
    let field_error = IRImportError::StructDefinitionField {
        r#struct: " broken\0struct ".to_owned(),
        index: 1,
        field: " broken\0field ".to_owned(),
        source: Box::new(type_error.clone()),
    };
    let expected = IRImportError::ModuleStructDefinition {
        index: 1,
        name: " broken\0struct ".to_owned(),
        source: Box::new(field_error.clone()),
    };
    let wire = IRModuleDTO {
        schema_version: IR_SCHEMA_VERSION,
        functions: vec![],
        structs: vec![
            IRStructDefinitionDTO {
                name: "valid".to_owned(),
                fields: vec![],
            },
            IRStructDefinitionDTO {
                name: " broken\0struct ".to_owned(),
                fields: vec![
                    IRStructFieldDTO {
                        name: "valid".to_owned(),
                        r#type: IRTypeDTO::Int {},
                    },
                    IRStructFieldDTO {
                        name: " broken\0field ".to_owned(),
                        r#type: invalid_method_result_type(),
                    },
                ],
            },
        ],
    };

    let error = import_module(&wire).expect_err("invalid nested field type must fail");
    assert_eq!(error, expected);
    assert_eq!(downcast_source(&error), Some(&field_error));
    assert_eq!(downcast_source(&field_error), Some(&type_error));
    assert!(type_error.source().is_none());
}

#[test]
fn function_failure_retains_module_function_and_complete_nested_source_chain() {
    let type_error = IRImportError::MethodResultReceiverNotStruct { actual: "list" };
    let parameter_error = IRImportError::ParameterType {
        source: Box::new(type_error.clone()),
    };
    let function_error = IRImportError::FunctionParameter {
        function: " broken\0function ".to_owned(),
        index: 0,
        source: Box::new(parameter_error.clone()),
    };
    let expected = IRImportError::ModuleFunction {
        index: 1,
        function: " broken\0function ".to_owned(),
        source: Box::new(function_error.clone()),
    };
    let wire = IRModuleDTO {
        schema_version: IR_SCHEMA_VERSION,
        functions: vec![
            serde_json::from_value(function_json("valid", &type_json("void"), &[]))
                .expect("valid function fixture"),
            IRFunctionDTO {
                name: " broken\0function ".to_owned(),
                parameters: vec![IRParameterDTO::Parameter {
                    name: "bad".to_owned(),
                    r#type: invalid_method_result_type(),
                }],
                return_type: IRTypeDTO::Void {},
                blocks: vec![],
                may_throw: false,
            },
        ],
        structs: vec![],
    };

    let error = import_module(&wire).expect_err("invalid nested function must fail");
    assert_eq!(error, expected);
    assert_eq!(downcast_source(&error), Some(&function_error));
    assert_eq!(downcast_source(&function_error), Some(&parameter_error));
    assert_eq!(downcast_source(&parameter_error), Some(&type_error));
    assert!(type_error.source().is_none());
}

fn downcast_source(error: &IRImportError) -> Option<&IRImportError> {
    error
        .source()
        .and_then(|source| source.downcast_ref::<IRImportError>())
}
