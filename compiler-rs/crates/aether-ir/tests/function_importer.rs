//! Focused coverage for schema-v1 function import.

use std::error::Error as _;

use aether_ir::wire::{
    IRBasicBlockDTO, IRConstantDTO, IRFloatDTO, IRFunctionDTO, IRInstructionDTO, IRTypeDTO,
    IRValueDTO,
};
use aether_ir::{
    BoolType, FunctionType, IRBasicBlock, IRConstant, IRFunction, IRImportError, IRInstruction,
    IRParameter, IRType, IRValue, IntType, ListType, NullableType, StringType, import_function,
};
use serde_json::{Value, json};

fn parameter_json(name: &str, type_: &Value) -> Value {
    json!({"tag": "parameter", "name": name, "type": type_})
}

fn value_json(name: &str, type_: &Value) -> Value {
    json!({"tag": "value", "name": name, "type": type_})
}

fn const_json(name: &str, value: i32) -> Value {
    json!({
        "kind": "const",
        "result": value_json(name, &json!({"tag": "int"})),
        "value": {"tag": "int", "value": value}
    })
}

fn return_json(value: Option<&Value>) -> Value {
    json!({"kind": "return", "value": value, "transferred_storage": null})
}

fn block_json(name: &str, instructions: &[Value]) -> Value {
    json!({"name": name, "instructions": instructions})
}

fn function_json(name: &str, parameters: &[Value], return_type: &Value, blocks: &[Value]) -> Value {
    json!({
        "name": name,
        "parameters": parameters,
        "return_type": return_type,
        "blocks": blocks
    })
}

fn wire_function(
    name: &str,
    parameters: &[Value],
    return_type: &Value,
    blocks: &[Value],
) -> IRFunctionDTO {
    serde_json::from_value(function_json(name, parameters, return_type, blocks))
        .expect("function fixture must be valid wire JSON")
}

fn invalid_method_result_type() -> Value {
    json!({
        "tag": "method_result",
        "receiver": {"tag": "list", "element": {"tag": "int"}},
        "value": {"tag": "int"}
    })
}

fn empty_return() -> IRInstruction {
    IRInstruction::IRReturn {
        value: None,
        transferred_storage: None,
    }
}

#[test]
fn imports_raw_name_with_no_parameters_and_no_blocks() {
    let wire = wire_function(" raw\0function ", &[], &json!({"tag": "void"}), &[]);

    assert_eq!(
        import_function(&wire),
        Ok(IRFunction {
            name: " raw\0function ".to_owned(),
            parameters: vec![],
            return_type: IRType::Void(aether_ir::VoidType),
            blocks: vec![],
        })
    );
}

#[test]
fn imports_one_parameter_through_owned_and_borrowed_paths_without_mutating_dto() {
    let wire = wire_function(
        "one",
        &[parameter_json("argument", &json!({"tag": "int"}))],
        &json!({"tag": "bool"}),
        &[block_json("entry", &[])],
    );
    let original = wire.clone();
    let expected = IRFunction {
        name: "one".to_owned(),
        parameters: vec![IRParameter::new("argument", IntType.into())],
        return_type: BoolType.into(),
        blocks: vec![IRBasicBlock::new("entry")],
    };

    assert_eq!(import_function(&wire), Ok(expected.clone()));
    assert_eq!(IRFunction::try_from(&wire), Ok(expected.clone()));
    assert_eq!(IRFunction::try_from(wire.clone()), Ok(expected));
    assert_eq!(wire, original, "borrowed import must not mutate its DTO");
}

#[test]
fn preserves_multiple_parameter_order_and_recursive_types() {
    let nested_parameter = json!({
        "tag": "list",
        "element": {"tag": "nullable", "inner": {"tag": "string"}}
    });
    let nested_return = json!({
        "tag": "function",
        "parameter_types": [
            {"tag": "int"},
            {"tag": "list", "element": {"tag": "bool"}}
        ],
        "return_type": {
            "tag": "nullable",
            "inner": {"tag": "list", "element": {"tag": "string"}}
        }
    });
    let wire = wire_function(
        "ordered",
        &[
            parameter_json("first", &json!({"tag": "int"})),
            parameter_json("nested", &nested_parameter),
            parameter_json("last", &json!({"tag": "bool"})),
        ],
        &nested_return,
        &[],
    );

    let imported = import_function(&wire).expect("recursive function types must import");
    assert_eq!(
        imported.parameters,
        vec![
            IRParameter::new("first", IntType.into()),
            IRParameter::new(
                "nested",
                ListType {
                    element: Box::new(
                        NullableType {
                            inner: Box::new(StringType.into()),
                        }
                        .into(),
                    ),
                }
                .into(),
            ),
            IRParameter::new("last", BoolType.into()),
        ]
    );
    assert_eq!(
        imported.return_type,
        FunctionType {
            parameter_types: vec![
                IntType.into(),
                ListType {
                    element: Box::new(BoolType.into()),
                }
                .into(),
            ],
            return_type: Box::new(
                NullableType {
                    inner: Box::new(
                        ListType {
                            element: Box::new(StringType.into()),
                        }
                        .into(),
                    ),
                }
                .into(),
            ),
        }
        .into()
    );
}

#[test]
fn accepts_duplicate_parameter_names_without_reordering_or_deduplication() {
    let wire = wire_function(
        "duplicates",
        &[
            parameter_json("same", &json!({"tag": "int"})),
            parameter_json("same", &json!({"tag": "string"})),
        ],
        &json!({"tag": "void"}),
        &[],
    );

    let imported = import_function(&wire).expect("parameter uniqueness is a verifier concern");
    assert_eq!(
        imported.parameters,
        vec![
            IRParameter::new("same", IntType.into()),
            IRParameter::new("same", StringType.into()),
        ]
    );
}

#[test]
fn preserves_block_order_duplicate_names_and_invalid_but_representable_contents() {
    let wire = wire_function(
        "blocks",
        &[],
        &json!({"tag": "void"}),
        &[
            block_json("duplicate", &[]),
            block_json(
                "middle",
                &[return_json(None), const_json("after_return", 9)],
            ),
            block_json("duplicate", &[return_json(None), return_json(None)]),
        ],
    );

    let imported = import_function(&wire)
        .expect("block uniqueness and terminator placement are verifier concerns");
    assert_eq!(
        imported
            .blocks
            .iter()
            .map(|block| block.name.as_str())
            .collect::<Vec<_>>(),
        vec!["duplicate", "middle", "duplicate"]
    );
    assert_eq!(imported.blocks[0].instructions, vec![]);
    assert_eq!(
        imported.blocks[1].instructions,
        vec![
            empty_return(),
            IRInstruction::IRConst {
                result: IRValue::new("after_return", IntType.into()),
                value: IRConstant::Int(9),
            },
        ]
    );
    assert_eq!(
        imported.blocks[2].instructions,
        vec![empty_return(), empty_return()]
    );
}

#[test]
fn accepts_return_instruction_that_mismatches_declared_return_type() {
    let wire = wire_function(
        "mismatch",
        &[],
        &json!({"tag": "bool"}),
        &[block_json(
            "entry",
            &[return_json(Some(&value_json(
                "integer_result",
                &json!({"tag": "int"}),
            )))],
        )],
    );

    let imported =
        import_function(&wire).expect("return compatibility is a verifier responsibility");
    assert_eq!(imported.return_type, BoolType.into());
    assert_eq!(
        imported.blocks[0].instructions,
        vec![IRInstruction::IRReturn {
            value: Some(IRValue::new("integer_result", IntType.into())),
            transferred_storage: None,
        }]
    );
}

#[test]
fn json_wire_owned_conversion_is_deterministic() {
    let json = function_json(
        " deterministic ",
        &[
            parameter_json("second", &json!({"tag": "string"})),
            parameter_json("first", &json!({"tag": "int"})),
        ],
        &json!({"tag": "int"}),
        &[
            block_json("second", &[return_json(None)]),
            block_json("first", &[]),
        ],
    );
    let encoded = serde_json::to_string(&json).expect("fixture JSON must serialize");
    let first_wire: IRFunctionDTO =
        serde_json::from_str(&encoded).expect("fixture JSON must deserialize");
    let wire_round_trip: IRFunctionDTO =
        serde_json::from_str(&serde_json::to_string(&first_wire).expect("wire DTO must serialize"))
            .expect("serialized wire DTO must deserialize");

    assert_eq!(wire_round_trip, first_wire);
    let expected = import_function(&first_wire).expect("first import must succeed");
    assert_eq!(import_function(&first_wire), Ok(expected.clone()));
    assert_eq!(import_function(&wire_round_trip), Ok(expected));
}

#[test]
fn parameter_failure_retains_function_index_and_complete_type_error_chain() {
    let wire = wire_function(
        " parameter\0failure ",
        &[
            parameter_json("valid", &json!({"tag": "int"})),
            parameter_json("invalid", &invalid_method_result_type()),
        ],
        &json!({"tag": "void"}),
        &[],
    );
    let type_error = IRImportError::MethodResultReceiverNotStruct { actual: "list" };
    let parameter_error = IRImportError::ParameterType {
        source: Box::new(type_error.clone()),
    };
    let expected = IRImportError::FunctionParameter {
        function: " parameter\0failure ".to_owned(),
        index: 1,
        source: Box::new(parameter_error.clone()),
    };

    let error = import_function(&wire).expect_err("invalid nested parameter type must fail");
    assert_eq!(error, expected);
    assert_eq!(downcast_source(&error), Some(&parameter_error));
    assert_eq!(downcast_source(&parameter_error), Some(&type_error));
    assert!(type_error.source().is_none());
}

#[test]
fn return_type_failure_retains_function_field_and_type_error_source() {
    let wire = wire_function("return failure", &[], &invalid_method_result_type(), &[]);
    let type_error = IRImportError::MethodResultReceiverNotStruct { actual: "list" };
    let expected = IRImportError::FunctionReturnType {
        function: "return failure".to_owned(),
        field: "return_type",
        source: Box::new(type_error.clone()),
    };

    let error = import_function(&wire).expect_err("invalid return type must fail");
    assert_eq!(error, expected);
    assert_eq!(downcast_source(&error), Some(&type_error));
}

#[test]
fn block_failure_retains_function_index_block_and_complete_instruction_error_chain() {
    let result: IRValueDTO =
        serde_json::from_value(value_json("bad_float", &json!({"tag": "int"})))
            .expect("value fixture must deserialize");
    let wire = IRFunctionDTO {
        name: " block\0failure ".to_owned(),
        parameters: vec![],
        return_type: IRTypeDTO::Void {},
        blocks: vec![
            IRBasicBlockDTO {
                name: "valid".to_owned(),
                instructions: vec![],
            },
            IRBasicBlockDTO {
                name: " failing\0block ".to_owned(),
                instructions: vec![
                    serde_json::from_value(return_json(None))
                        .expect("return fixture must deserialize"),
                    IRInstructionDTO::Const {
                        result,
                        value: IRConstantDTO::Float {
                            value: IRFloatDTO(f64::NAN),
                        },
                    },
                ],
            },
        ],
    };
    let float_error = IRImportError::NonFiniteConstantFloat { field: "value" };
    let field_error = IRImportError::InstructionField {
        instruction: "const",
        field: "value",
        source: Box::new(float_error.clone()),
    };
    let instruction_error = IRImportError::BasicBlockInstruction {
        block: " failing\0block ".to_owned(),
        index: 1,
        source: Box::new(field_error.clone()),
    };
    let expected = IRImportError::FunctionBasicBlock {
        function: " block\0failure ".to_owned(),
        index: 1,
        block: " failing\0block ".to_owned(),
        source: Box::new(instruction_error.clone()),
    };

    let error = import_function(&wire).expect_err("invalid nested instruction must fail");
    assert_eq!(error, expected);
    assert_eq!(downcast_source(&error), Some(&instruction_error));
    assert_eq!(downcast_source(&instruction_error), Some(&field_error));
    assert_eq!(downcast_source(&field_error), Some(&float_error));
    assert!(float_error.source().is_none());
}

fn downcast_source(error: &IRImportError) -> Option<&IRImportError> {
    error
        .source()
        .and_then(|source| source.downcast_ref::<IRImportError>())
}
