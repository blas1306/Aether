//! Focused coverage for schema-v1 foundational entity import.

use std::error::Error as _;

use aether_ir::wire::{
    IRConstantDTO, IREnumConstantDTO, IRFloatDTO, IRParameterDTO, IRSourceLocationDTO,
    IRStorageDTO, IRTypeDTO, IRValueDTO, NullableDTO,
};
use aether_ir::{
    ArrayType, BoolType, EnumType, FunctionType, IRConstant, IREnumConstant, IRImportError,
    IRParameter, IRSourceLocation, IRStorage, IRType, IRValue, IntType, ListType, MethodResultType,
    NullableType, StringType, StructType, VectorType, import_constant, import_enum_constant,
    import_optional_source_location, import_parameter, import_source_location, import_storage,
    import_value,
};
use serde_json::json;

fn boxed(type_: IRTypeDTO) -> Box<IRTypeDTO> {
    Box::new(type_)
}

#[test]
fn imports_every_constant_variant_through_owned_and_borrowed_paths() {
    let cases = vec![
        (
            json!({"tag": "bool", "value": true}),
            IRConstant::Bool(true),
        ),
        (
            json!({"tag": "int", "value": -2_147_483_648_i64}),
            IRConstant::Int(i32::MIN),
        ),
        (
            json!({"tag": "float", "value": 1.25}),
            IRConstant::Float(1.25),
        ),
        (
            json!({"tag": "complex", "real": -2.5, "imaginary": 3.75}),
            IRConstant::Complex {
                real: -2.5,
                imaginary: 3.75,
            },
        ),
        (
            json!({"tag": "string", "value": "  Aether\n\u{0}λ  "}),
            IRConstant::String("  Aether\n\0λ  ".to_owned()),
        ),
        (
            json!({
                "tag": "enum",
                "value": {
                    "tag": "enum_constant",
                    "enum_name": " Color::Δ ",
                    "member_name": " red\u{0} ",
                    "member_id": 2_147_483_647_i64,
                    "discriminant": -2_147_483_648_i64
                }
            }),
            IRConstant::Enum(IREnumConstant {
                enum_name: " Color::Δ ".to_owned(),
                member_name: " red\0 ".to_owned(),
                member_id: i32::MAX,
                discriminant: i32::MIN,
            }),
        ),
    ];

    assert_eq!(cases.len(), 6);
    for (json, expected) in cases {
        let wire: IRConstantDTO =
            serde_json::from_value(json).expect("constant JSON must deserialize");

        assert_eq!(import_constant(&wire), Ok(expected.clone()));
        assert_eq!(IRConstant::try_from(&wire), Ok(expected.clone()));
        assert_eq!(IRConstant::try_from(wire), Ok(expected));
    }
}

#[test]
fn imports_enum_constant_metadata_directly_without_narrowing() {
    let wire: IREnumConstantDTO = serde_json::from_value(json!({
        "tag": "enum_constant",
        "enum_name": "E",
        "member_name": "MAX",
        "member_id": 2_147_483_647_i64,
        "discriminant": -2_147_483_648_i64
    }))
    .expect("enum constant JSON must deserialize");
    let expected = IREnumConstant {
        enum_name: "E".to_owned(),
        member_name: "MAX".to_owned(),
        member_id: i32::MAX,
        discriminant: i32::MIN,
    };

    assert_eq!(import_enum_constant(&wire), Ok(expected.clone()));
    assert_eq!(IREnumConstant::try_from(&wire), Ok(expected.clone()));
    assert_eq!(IREnumConstant::try_from(wire), Ok(expected));
}

#[test]
fn preserves_finite_float_bits_and_rejects_non_finite_programmatic_dtos() {
    let cases = [
        (r#"{"tag":"float","value":-0.0}"#, -0.0),
        (r#"{"tag":"float","value":5e-324}"#, f64::from_bits(1)),
        (
            r#"{"tag":"float","value":2.2250738585072014e-308}"#,
            f64::MIN_POSITIVE,
        ),
        (
            r#"{"tag":"float","value":1.7976931348623157e308}"#,
            f64::MAX,
        ),
    ];

    for (json, expected) in cases {
        let wire: IRConstantDTO =
            serde_json::from_str(json).expect("finite float JSON must deserialize");
        let IRConstant::Float(actual) = import_constant(&wire).expect("finite float must import")
        else {
            panic!("expected a float constant");
        };
        assert_eq!(actual.to_bits(), expected.to_bits());
    }

    let complex = IRConstantDTO::Complex {
        real: IRFloatDTO(-0.0),
        imaginary: IRFloatDTO(f64::from_bits(1)),
    };
    let IRConstant::Complex { real, imaginary } =
        import_constant(&complex).expect("finite complex value must import")
    else {
        panic!("expected a complex constant");
    };
    assert_eq!(real.to_bits(), (-0.0_f64).to_bits());
    assert_eq!(imaginary.to_bits(), f64::from_bits(1).to_bits());

    for value in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        assert_eq!(
            IRConstant::try_from(IRConstantDTO::Float {
                value: IRFloatDTO(value),
            }),
            Err(IRImportError::NonFiniteConstantFloat { field: "value" })
        );
    }
    assert_eq!(
        import_constant(&IRConstantDTO::Complex {
            real: IRFloatDTO(f64::INFINITY),
            imaginary: IRFloatDTO(0.0),
        }),
        Err(IRImportError::NonFiniteConstantFloat { field: "real" })
    );
    assert_eq!(
        import_constant(&IRConstantDTO::Complex {
            real: IRFloatDTO(0.0),
            imaginary: IRFloatDTO(f64::NAN),
        }),
        Err(IRImportError::NonFiniteConstantFloat { field: "imaginary" })
    );
}

#[test]
fn wire_integer_widths_match_owned_widths_and_out_of_range_json_is_rejected() {
    for value in [i32::MIN, i32::MAX] {
        let wire: IRConstantDTO = serde_json::from_value(json!({
            "tag": "int",
            "value": value
        }))
        .expect("i32 boundary must deserialize");
        assert_eq!(import_constant(&wire), Ok(IRConstant::Int(value)));
    }

    let location: IRSourceLocationDTO = serde_json::from_value(json!({
        "tag": "source_location",
        "line": i64::MIN,
        "column": i64::MAX,
        "path": null
    }))
    .expect("i64 boundaries must deserialize");
    assert_eq!(
        import_source_location(&location),
        Ok(IRSourceLocation {
            line: i64::MIN,
            column: i64::MAX,
            path: None,
        })
    );

    assert!(
        serde_json::from_value::<IRConstantDTO>(json!({
            "tag": "int",
            "value": 2_147_483_648_i64
        }))
        .is_err()
    );
    assert!(
        serde_json::from_value::<IREnumConstantDTO>(json!({
            "tag": "enum_constant",
            "enum_name": "E",
            "member_name": "M",
            "member_id": -2_147_483_649_i64,
            "discriminant": 0
        }))
        .is_err()
    );
    assert!(
        serde_json::from_value::<IRSourceLocationDTO>(json!({
            "tag": "source_location",
            "line": 9_223_372_036_854_775_808_u64,
            "column": 0,
            "path": null
        }))
        .is_err()
    );
}

#[test]
fn imports_all_value_tags_with_recursive_types_and_unresolved_names() {
    let cases = [
        json!({
            "tag": "value",
            "name": " %result\tΔ\u{0} ",
            "type": {"tag": "struct", "name": " Missing::Type "}
        }),
        json!({
            "tag": "storage",
            "name": "slot::unresolved",
            "type": {
                "tag": "list",
                "element": {
                    "tag": "nullable",
                    "inner": {
                        "tag": "enum",
                        "name": "UnknownEnum",
                        "variants": [" z ", "z", ""],
                        "display_name": null
                    }
                }
            }
        }),
        json!({
            "tag": "parameter",
            "name": "not_declared_anywhere",
            "type": {
                "tag": "function",
                "parameter_types": [
                    {"tag": "array", "element": {"tag": "bool"}},
                    {"tag": "vector", "element": {"tag": "int"}, "orientation": " diagonal "}
                ],
                "return_type": {"tag": "string"}
            }
        }),
    ];
    let expected_types = [
        IRType::from(StructType {
            name: " Missing::Type ".to_owned(),
        }),
        IRType::from(ListType {
            element: Box::new(
                NullableType {
                    inner: Box::new(
                        EnumType {
                            name: "UnknownEnum".to_owned(),
                            variants: vec![" z ".to_owned(), "z".to_owned(), String::new()],
                            display_name: None,
                        }
                        .into(),
                    ),
                }
                .into(),
            ),
        }),
        IRType::from(FunctionType {
            parameter_types: vec![
                ArrayType {
                    element: Box::new(BoolType.into()),
                }
                .into(),
                VectorType {
                    element: Box::new(IntType.into()),
                    orientation: Some(" diagonal ".to_owned()),
                }
                .into(),
            ],
            return_type: Box::new(StringType.into()),
        }),
    ];
    let expected_names = [
        " %result\tΔ\0 ",
        "slot::unresolved",
        "not_declared_anywhere",
    ];

    for ((json, expected_type), expected_name) in
        cases.into_iter().zip(expected_types).zip(expected_names)
    {
        let wire: IRValueDTO = serde_json::from_value(json).expect("value JSON must deserialize");
        let expected = IRValue::new(expected_name, expected_type);

        assert_eq!(import_value(&wire), Ok(expected.clone()));
        assert_eq!(IRValue::try_from(&wire), Ok(expected.clone()));
        assert_eq!(IRValue::try_from(wire), Ok(expected));
    }
}

#[test]
fn imports_storage_and_parameters_with_primitive_and_nested_types() {
    let storage: IRStorageDTO = serde_json::from_value(json!({
        "type": {
            "tag": "method_result",
            "receiver": {"tag": "struct", "name": " UnresolvedReceiver "},
            "value": {"tag": "list", "element": {"tag": "int"}}
        },
        "name": " storage\u{0}identity ",
        "tag": "storage"
    }))
    .expect("storage JSON must deserialize regardless of field order");
    let expected_storage = IRStorage::new(
        " storage\0identity ",
        MethodResultType {
            receiver: StructType {
                name: " UnresolvedReceiver ".to_owned(),
            },
            value: Box::new(
                ListType {
                    element: Box::new(IntType.into()),
                }
                .into(),
            ),
        }
        .into(),
    );
    assert_eq!(import_storage(&storage), Ok(expected_storage.clone()));
    assert_eq!(IRStorage::try_from(&storage), Ok(expected_storage.clone()));
    assert_eq!(IRStorage::try_from(storage), Ok(expected_storage));

    let primitive: IRParameterDTO =
        serde_json::from_str(r#"{"type":{"tag":"bool"},"tag":"parameter","name":" flag "}"#)
            .expect("primitive parameter JSON must deserialize");
    let nested: IRParameterDTO = serde_json::from_value(json!({
        "tag": "parameter",
        "name": "items",
        "type": {
            "tag": "array",
            "element": {"tag": "nullable", "inner": {"tag": "string"}}
        }
    }))
    .expect("nested parameter JSON must deserialize");
    let expected_primitive = IRParameter::new(" flag ", BoolType.into());
    let expected_nested = IRParameter::new(
        "items",
        ArrayType {
            element: Box::new(
                NullableType {
                    inner: Box::new(StringType.into()),
                }
                .into(),
            ),
        }
        .into(),
    );

    assert_eq!(import_parameter(&primitive), Ok(expected_primitive.clone()));
    assert_eq!(IRParameter::try_from(primitive), Ok(expected_primitive));
    assert_eq!(import_parameter(&nested), Ok(expected_nested.clone()));
    assert_eq!(IRParameter::try_from(&nested), Ok(expected_nested.clone()));
    assert_eq!(IRParameter::try_from(nested), Ok(expected_nested));
}

#[test]
fn preserves_present_absent_and_explicitly_null_source_location_fields() {
    let present: IRSourceLocationDTO = serde_json::from_value(json!({
        "tag": "source_location",
        "line": 17,
        "column": 29,
        "path": " ./src/Δ file.ae\u{0} "
    }))
    .expect("present source location must deserialize");
    let null_path: IRSourceLocationDTO = serde_json::from_value(json!({
        "tag": "source_location",
        "line": -1,
        "column": 0,
        "path": null
    }))
    .expect("explicitly null path must deserialize");
    let expected_present = IRSourceLocation {
        line: 17,
        column: 29,
        path: Some(" ./src/Δ file.ae\0 ".to_owned()),
    };
    let expected_null_path = IRSourceLocation {
        line: -1,
        column: 0,
        path: None,
    };

    assert_eq!(
        import_source_location(&present),
        Ok(expected_present.clone())
    );
    assert_eq!(
        IRSourceLocation::try_from(&present),
        Ok(expected_present.clone())
    );
    assert_eq!(
        IRSourceLocation::try_from(present.clone()),
        Ok(expected_present.clone())
    );
    assert_eq!(
        import_source_location(&null_path),
        Ok(expected_null_path.clone())
    );
    assert_eq!(
        import_optional_source_location(&NullableDTO(Some(present))),
        Ok(Some(expected_present))
    );
    assert_eq!(
        import_optional_source_location(&NullableDTO(Some(null_path))),
        Ok(Some(expected_null_path))
    );
    assert_eq!(
        import_optional_source_location(&NullableDTO(None)),
        Ok(None)
    );
}

#[test]
fn repeated_import_is_deterministic() {
    let constant: IRConstantDTO = serde_json::from_value(json!({
        "tag": "enum",
        "value": {
            "tag": "enum_constant",
            "enum_name": "E",
            "member_name": "M",
            "member_id": 7,
            "discriminant": -9
        }
    }))
    .expect("constant must deserialize");
    let value = IRValueDTO::Storage {
        name: "unresolved".to_owned(),
        r#type: IRTypeDTO::Array {
            element: boxed(IRTypeDTO::Struct {
                name: "Missing".to_owned(),
            }),
        },
    };

    assert_eq!(import_constant(&constant), import_constant(&constant));
    assert_eq!(import_value(&value), import_value(&value));
    assert_eq!(IRValue::try_from(value.clone()), IRValue::try_from(&value));
}

#[test]
fn nested_type_failures_retain_foundational_entity_context() {
    let invalid_type = json!({
        "tag": "method_result",
        "receiver": {"tag": "int"},
        "value": {"tag": "bool"}
    });
    let value: IRValueDTO = serde_json::from_value(json!({
        "tag": "storage",
        "name": "slot",
        "type": invalid_type.clone()
    }))
    .expect("the incompatible type is structurally valid wire JSON");
    let storage: IRStorageDTO = serde_json::from_value(json!({
        "tag": "storage",
        "name": "slot",
        "type": invalid_type.clone()
    }))
    .expect("the incompatible type is structurally valid wire JSON");
    let parameter: IRParameterDTO = serde_json::from_value(json!({
        "tag": "parameter",
        "name": "argument",
        "type": invalid_type
    }))
    .expect("the incompatible type is structurally valid wire JSON");
    let nested = IRImportError::MethodResultReceiverNotStruct { actual: "int" };

    let value_error = import_value(&value).expect_err("value type must fail structurally");
    assert_eq!(
        value_error,
        IRImportError::ValueType {
            kind: "storage",
            source: Box::new(nested.clone()),
        }
    );
    assert_eq!(
        value_error.to_string(),
        "value DTO variant 'storage' field 'type' could not be imported: method-result receiver must be a struct type, found wire type 'int'"
    );
    assert_eq!(
        value_error.source().map(ToString::to_string),
        Some(nested.to_string())
    );
    assert_eq!(
        import_storage(&storage),
        Err(IRImportError::StorageType {
            source: Box::new(nested.clone()),
        })
    );
    assert_eq!(
        import_parameter(&parameter),
        Err(IRImportError::ParameterType {
            source: Box::new(nested),
        })
    );
}
