//! Focused coverage for schema-v1 collection instruction import.

use aether_ir::wire::{IRInstructionDTO, IRTypeDTO, IRValueDTO, NullableDTO};
use aether_ir::{
    ArrayType, BoolType, IRImportError, IRInstruction, IRSourceLocation, IRType, IRValue, IntType,
    ListType, StringType, StructType, import_instruction,
};
use serde_json::{Value, json};

fn int_value(name: &str) -> IRValue {
    IRValue::new(name, IntType.into())
}

fn bool_value(name: &str) -> IRValue {
    IRValue::new(name, BoolType.into())
}

fn string_value(name: &str) -> IRValue {
    IRValue::new(name, StringType.into())
}

fn struct_value(name: &str) -> IRValue {
    IRValue::new(
        name,
        StructType {
            name: " Missing::Element ".to_owned(),
        }
        .into(),
    )
}

fn int_array_type() -> IRType {
    ArrayType {
        element: Box::new(IntType.into()),
    }
    .into()
}

fn nested_list_type() -> IRType {
    ListType {
        element: Box::new(
            ArrayType {
                element: Box::new(
                    StructType {
                        name: " Missing::Element ".to_owned(),
                    }
                    .into(),
                ),
            }
            .into(),
        ),
    }
    .into()
}

fn int_array_value(name: &str) -> IRValue {
    IRValue::new(name, int_array_type())
}

fn nested_list_value(name: &str) -> IRValue {
    IRValue::new(name, nested_list_type())
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
fn imports_all_twenty_two_collection_variants_exactly_through_both_paths() {
    let present_location = location(i64::MIN, i64::MAX, Some(" src/collections\0raw.ae "));
    let nested_type_json = json!({
        "tag": "list",
        "element": {
            "tag": "array",
            "element": {"tag": "struct", "name": " Missing::Element "}
        }
    });
    let cases = vec![
        (
            json!({
                "kind": "array_new",
                "result": {
                    "tag": "value",
                    "name": "array::ordered",
                    "type": {"tag": "array", "element": {"tag": "int"}}
                },
                "elements": [
                    {"tag": "value", "name": "third", "type": {"tag": "string"}},
                    {
                        "tag": "parameter",
                        "name": "first",
                        "type": {"tag": "struct", "name": " Missing::Element "}
                    },
                    {"tag": "storage", "name": "second", "type": nested_type_json.clone()},
                    {"tag": "value", "name": "third", "type": {"tag": "string"}}
                ]
            }),
            IRInstruction::IRArrayNew {
                result: int_array_value("array::ordered"),
                elements: vec![
                    string_value("third"),
                    struct_value("first"),
                    nested_list_value("second"),
                    string_value("third"),
                ],
            },
        ),
        (
            json!({
                "kind": "list_new",
                "result": {"tag": "value", "name": "list::one", "type": nested_type_json.clone()},
                "elements": [{"tag": "parameter", "name": "only", "type": {"tag": "bool"}}]
            }),
            IRInstruction::IRListNew {
                result: nested_list_value("list::one"),
                elements: vec![bool_value("only")],
            },
        ),
        (
            json!({
                "kind": "array_copy",
                "result": {"tag": "value", "name": "array::copy", "type": {"tag": "array", "element": {"tag": "int"}}},
                "array": {"tag": "parameter", "name": "unresolved::array", "type": {"tag": "array", "element": {"tag": "int"}}},
                "source_location": location_json(i64::MIN, i64::MAX, Some(" src/collections\0raw.ae "))
            }),
            IRInstruction::IRArrayCopy {
                result: int_array_value("array::copy"),
                array: int_array_value("unresolved::array"),
                source_location: Some(present_location.clone()),
            },
        ),
        (
            json!({
                "kind": "list_copy",
                "result": {"tag": "value", "name": "list::copy", "type": nested_type_json.clone()},
                "list_value": {"tag": "storage", "name": "unresolved::list", "type": nested_type_json.clone()},
                "source_location": null
            }),
            IRInstruction::IRListCopy {
                result: nested_list_value("list::copy"),
                list_value: nested_list_value("unresolved::list"),
                source_location: None,
            },
        ),
        (
            json!({
                "kind": "list_contains",
                "result": {"tag": "value", "name": "contains::result", "type": {"tag": "bool"}},
                "list_value": {"tag": "value", "name": "contains::list", "type": nested_type_json.clone()},
                "value": {"tag": "value", "name": "contains::needle", "type": {"tag": "struct", "name": " Missing::Element "}}
            }),
            IRInstruction::IRListContains {
                result: bool_value("contains::result"),
                list_value: nested_list_value("contains::list"),
                value: struct_value("contains::needle"),
            },
        ),
        (
            json!({
                "kind": "list_index_of",
                "result": {"tag": "value", "name": "index_of::result", "type": {"tag": "int"}},
                "list_value": {"tag": "parameter", "name": "index_of::list", "type": nested_type_json.clone()},
                "value": {"tag": "value", "name": "index_of::needle", "type": {"tag": "string"}}
            }),
            IRInstruction::IRListIndexOf {
                result: int_value("index_of::result"),
                list_value: nested_list_value("index_of::list"),
                value: string_value("index_of::needle"),
            },
        ),
        (
            json!({"kind": "list_clear", "list_value": {"tag": "value", "name": "clear::list", "type": nested_type_json.clone()}}),
            IRInstruction::IRListClear {
                list_value: nested_list_value("clear::list"),
            },
        ),
        (
            json!({
                "kind": "list_push",
                "list_value": {"tag": "storage", "name": "push::list", "type": nested_type_json.clone()},
                "value": {"tag": "parameter", "name": "push::value", "type": {"tag": "bool"}}
            }),
            IRInstruction::IRListPush {
                list_value: nested_list_value("push::list"),
                value: bool_value("push::value"),
            },
        ),
        (
            json!({
                "kind": "list_insert",
                "list_value": {"tag": "value", "name": "insert::list", "type": nested_type_json.clone()},
                "index": {"tag": "value", "name": "insert::negative_index", "type": {"tag": "int"}},
                "value": {"tag": "value", "name": "insert::value", "type": {"tag": "struct", "name": " Missing::Element "}}
            }),
            IRInstruction::IRListInsert {
                list_value: nested_list_value("insert::list"),
                index: int_value("insert::negative_index"),
                value: struct_value("insert::value"),
            },
        ),
        (
            json!({
                "kind": "list_remove_at",
                "result": {"tag": "value", "name": "remove::result", "type": {"tag": "string"}},
                "list_value": {"tag": "value", "name": "remove::list", "type": nested_type_json.clone()},
                "index": {"tag": "parameter", "name": "remove::past_end", "type": {"tag": "int"}}
            }),
            IRInstruction::IRListRemoveAt {
                result: string_value("remove::result"),
                list_value: nested_list_value("remove::list"),
                index: int_value("remove::past_end"),
            },
        ),
        (
            json!({
                "kind": "list_pop",
                "result": {"tag": "value", "name": "pop::result", "type": {"tag": "string"}},
                "list_value": {"tag": "value", "name": "pop::possibly_empty", "type": nested_type_json.clone()}
            }),
            IRInstruction::IRListPop {
                result: string_value("pop::result"),
                list_value: nested_list_value("pop::possibly_empty"),
            },
        ),
        (
            json!({"kind": "list_reverse", "list_value": {"tag": "parameter", "name": "reverse::list", "type": nested_type_json.clone()}}),
            IRInstruction::IRListReverse {
                list_value: nested_list_value("reverse::list"),
            },
        ),
        (
            json!({"kind": "sequence_sort", "sequence": {"tag": "value", "name": "sort::sequence", "type": {"tag": "array", "element": {"tag": "int"}}}}),
            IRInstruction::IRSequenceSort {
                sequence: int_array_value("sort::sequence"),
            },
        ),
        (
            json!({
                "kind": "array_get",
                "result": {"tag": "value", "name": "array_get::result", "type": {"tag": "string"}},
                "array": {"tag": "value", "name": "array_get::array", "type": {"tag": "array", "element": {"tag": "int"}}},
                "index": {"tag": "parameter", "name": "array_get::index", "type": {"tag": "int"}},
                "borrowed": true,
                "borrow_scope": " unresolved::scope\0raw ",
                "source_location": null
            }),
            IRInstruction::IRArrayGet {
                result: string_value("array_get::result"),
                array: int_array_value("array_get::array"),
                index: int_value("array_get::index"),
                borrowed: true,
                borrow_scope: Some(" unresolved::scope\0raw ".to_owned()),
                source_location: None,
            },
        ),
        (
            json!({
                "kind": "array_slice",
                "result": {"tag": "value", "name": "array_slice::result", "type": {"tag": "array", "element": {"tag": "int"}}},
                "array": {"tag": "value", "name": "array_slice::array", "type": {"tag": "array", "element": {"tag": "int"}}},
                "start": {"tag": "value", "name": "array_slice::after_end", "type": {"tag": "int"}},
                "end": {"tag": "value", "name": "array_slice::before_start", "type": {"tag": "int"}},
                "source_location": location_json(i64::MIN, i64::MAX, Some(" src/collections\0raw.ae "))
            }),
            IRInstruction::IRArraySlice {
                result: int_array_value("array_slice::result"),
                array: int_array_value("array_slice::array"),
                start: int_value("array_slice::after_end"),
                end: int_value("array_slice::before_start"),
                source_location: Some(present_location.clone()),
            },
        ),
        (
            json!({
                "kind": "list_slice",
                "result": {"tag": "value", "name": "list_slice::result", "type": nested_type_json.clone()},
                "list_value": {"tag": "value", "name": "list_slice::list", "type": nested_type_json.clone()},
                "start": {"tag": "value", "name": "list_slice::start", "type": {"tag": "int"}},
                "end": {"tag": "value", "name": "list_slice::end", "type": {"tag": "int"}},
                "source_location": null
            }),
            IRInstruction::IRListSlice {
                result: nested_list_value("list_slice::result"),
                list_value: nested_list_value("list_slice::list"),
                start: int_value("list_slice::start"),
                end: int_value("list_slice::end"),
                source_location: None,
            },
        ),
        (
            json!({
                "kind": "list_get",
                "result": {"tag": "value", "name": "list_get::result", "type": {"tag": "struct", "name": " Missing::Element "}},
                "list_value": {"tag": "parameter", "name": "list_get::list", "type": nested_type_json.clone()},
                "index": {"tag": "value", "name": "list_get::index", "type": {"tag": "int"}},
                "borrowed": false,
                "borrow_scope": null,
                "source_location": location_json(0, -91, None)
            }),
            IRInstruction::IRListGet {
                result: struct_value("list_get::result"),
                list_value: nested_list_value("list_get::list"),
                index: int_value("list_get::index"),
                borrowed: false,
                borrow_scope: None,
                source_location: Some(location(0, -91, None)),
            },
        ),
        (
            json!({
                "kind": "array_set",
                "array": {"tag": "value", "name": "array_set::immutable", "type": {"tag": "array", "element": {"tag": "int"}}},
                "index": {"tag": "value", "name": "array_set::index", "type": {"tag": "bool"}},
                "value": {"tag": "value", "name": "array_set::value", "type": {"tag": "string"}}
            }),
            IRInstruction::IRArraySet {
                array: int_array_value("array_set::immutable"),
                index: bool_value("array_set::index"),
                value: string_value("array_set::value"),
            },
        ),
        (
            json!({
                "kind": "list_set",
                "list_value": {"tag": "value", "name": "list_set::immutable", "type": nested_type_json.clone()},
                "index": {"tag": "value", "name": "list_set::index", "type": {"tag": "string"}},
                "value": {"tag": "value", "name": "list_set::value", "type": {"tag": "bool"}}
            }),
            IRInstruction::IRListSet {
                list_value: nested_list_value("list_set::immutable"),
                index: string_value("list_set::index"),
                value: bool_value("list_set::value"),
            },
        ),
        (
            json!({
                "kind": "array_length",
                "result": {"tag": "value", "name": "array_length::wrong_result_type", "type": {"tag": "string"}},
                "array": {"tag": "value", "name": "array_length::array", "type": {"tag": "array", "element": {"tag": "int"}}}
            }),
            IRInstruction::IRArrayLength {
                result: string_value("array_length::wrong_result_type"),
                array: int_array_value("array_length::array"),
            },
        ),
        (
            json!({
                "kind": "list_length",
                "result": {"tag": "value", "name": "list_length::result", "type": {"tag": "int"}},
                "list_value": {"tag": "value", "name": "list_length::list", "type": nested_type_json.clone()}
            }),
            IRInstruction::IRListLength {
                result: int_value("list_length::result"),
                list_value: nested_list_value("list_length::list"),
            },
        ),
        (
            json!({
                "kind": "list_is_empty",
                "result": {"tag": "value", "name": "is_empty::result", "type": {"tag": "bool"}},
                "list_value": {"tag": "value", "name": "is_empty::list", "type": nested_type_json}
            }),
            IRInstruction::IRListIsEmpty {
                result: bool_value("is_empty::result"),
                list_value: nested_list_value("is_empty::list"),
            },
        ),
    ];

    assert_eq!(
        cases.len(),
        22,
        "the collection slice must add exactly 22 kinds"
    );
    for (json, expected) in cases {
        let encoded = serde_json::to_string(&json)
            .expect("collection instruction JSON must encode deterministically");
        let wire: IRInstructionDTO =
            serde_json::from_str(&encoded).expect("collection instruction JSON must deserialize");
        let original = wire.clone();

        assert_eq!(import_instruction(&wire), Ok(expected.clone()));
        assert_eq!(import_instruction(&wire), Ok(expected.clone()));
        assert_eq!(IRInstruction::try_from(&wire), Ok(expected.clone()));
        assert_eq!(IRInstruction::try_from(wire.clone()), Ok(expected));
        assert_eq!(wire, original, "borrowed import must not mutate its DTO");
    }
}

#[test]
fn preserves_empty_singleton_and_multiple_element_constructors() {
    let cases = [
        ("array_new", Vec::<&str>::new()),
        ("list_new", vec!["only"]),
        ("array_new", vec!["first", "second", "first"]),
    ];

    for (kind, names) in cases {
        let elements = names
            .iter()
            .map(|name| json!({"tag": "value", "name": name, "type": {"tag": "int"}}))
            .collect::<Vec<_>>();
        let wire: IRInstructionDTO = serde_json::from_value(json!({
            "kind": kind,
            "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
            "elements": elements
        }))
        .expect("constructor JSON must deserialize");
        let imported = import_instruction(&wire).expect("constructor is representable");
        let imported_names = match imported {
            IRInstruction::IRArrayNew { elements, .. }
            | IRInstruction::IRListNew { elements, .. } => elements
                .into_iter()
                .map(|element| element.name)
                .collect::<Vec<_>>(),
            _ => panic!("expected a collection constructor"),
        };

        assert_eq!(imported_names, names);
    }
}

#[test]
fn leaves_invalid_but_representable_collection_semantics_to_the_verifier() {
    let cases = [
        json!({
            "kind": "array_get",
            "result": {"tag": "value", "name": "result", "type": {"tag": "struct", "name": "Unknown"}},
            "array": {"tag": "value", "name": "not_an_array", "type": {"tag": "string"}},
            "index": {"tag": "value", "name": "negative_or_past_end", "type": {"tag": "bool"}},
            "borrowed": true,
            "borrow_scope": "unresolved::scope",
            "source_location": null
        }),
        json!({
            "kind": "list_insert",
            "list_value": {"tag": "value", "name": "immutable_or_missing", "type": {"tag": "bool"}},
            "index": {"tag": "value", "name": "invalid_index", "type": {"tag": "string"}},
            "value": {"tag": "value", "name": "wrong_element_type", "type": {"tag": "struct", "name": "Unknown"}}
        }),
        json!({
            "kind": "list_slice",
            "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
            "list_value": {"tag": "value", "name": "not_a_list", "type": {"tag": "string"}},
            "start": {"tag": "value", "name": "after_end", "type": {"tag": "bool"}},
            "end": {"tag": "value", "name": "before_start", "type": {"tag": "struct", "name": "Unknown"}},
            "source_location": null
        }),
        json!({
            "kind": "sequence_sort",
            "sequence": {"tag": "value", "name": "not_sortable_or_mutable", "type": {"tag": "bool"}}
        }),
        json!({
            "kind": "list_pop",
            "result": {"tag": "value", "name": "wrong_result", "type": {"tag": "string"}},
            "list_value": {"tag": "value", "name": "possibly_empty", "type": {"tag": "list", "element": {"tag": "int"}}}
        }),
    ];

    for json in cases {
        let wire: IRInstructionDTO = serde_json::from_value(json)
            .expect("invalid collection semantics remain structurally valid DTOs");
        assert!(import_instruction(&wire).is_ok());
    }
}

#[test]
fn gives_collection_instruction_and_field_context_for_nested_errors() {
    let wire: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "array_slice",
        "result": {"tag": "value", "name": "result", "type": {"tag": "int"}},
        "array": {"tag": "value", "name": "array", "type": {"tag": "array", "element": {"tag": "int"}}},
        "start": {"tag": "value", "name": "start", "type": {"tag": "int"}},
        "end": {
            "tag": "parameter",
            "name": "bad::end",
            "type": {
                "tag": "method_result",
                "receiver": {"tag": "list", "element": {"tag": "int"}},
                "value": {"tag": "bool"}
            }
        },
        "source_location": null
    }))
    .expect("the wire model permits the unrepresentable nested type");

    assert_eq!(
        import_instruction(&wire),
        Err(IRImportError::InstructionField {
            instruction: "array_slice",
            field: "end",
            source: Box::new(IRImportError::ValueType {
                kind: "parameter",
                source: Box::new(IRImportError::MethodResultReceiverNotStruct { actual: "list" }),
            }),
        })
    );
}

fn plain_wire_value(name: &str) -> IRValueDTO {
    IRValueDTO::Value {
        name: name.to_owned(),
        r#type: IRTypeDTO::Int {},
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn every_later_family_remains_explicitly_unsupported() {
    let v = || plain_wire_value("value");
    let unsupported = vec![
        (
            IRInstructionDTO::VectorNew {
                result: v(),
                elements: vec![],
                orientation: NullableDTO(None),
            },
            "vector_new",
        ),
        (
            IRInstructionDTO::MatrixNew {
                result: v(),
                elements: vec![],
                shape: [0, -1],
            },
            "matrix_new",
        ),
        (
            IRInstructionDTO::VectorAdd {
                result: v(),
                left: v(),
                right: v(),
                shape: [-1],
                orientation: NullableDTO(None),
            },
            "vector_add",
        ),
        (
            IRInstructionDTO::VectorSub {
                result: v(),
                left: v(),
                right: v(),
                shape: [-1],
                orientation: NullableDTO(None),
            },
            "vector_sub",
        ),
        (
            IRInstructionDTO::VectorScale {
                result: v(),
                vector: v(),
                scalar: v(),
                shape: [-1],
                orientation: NullableDTO(None),
            },
            "vector_scale",
        ),
        (
            IRInstructionDTO::VectorDot {
                result: v(),
                left: v(),
                right: v(),
                shape: [-1],
            },
            "vector_dot",
        ),
        (
            IRInstructionDTO::OuterProduct {
                result: v(),
                column: v(),
                row: v(),
                shape: [-1, 0],
            },
            "outer_product",
        ),
        (
            IRInstructionDTO::MatrixAdd {
                result: v(),
                left: v(),
                right: v(),
                shape: [-1, 0],
            },
            "matrix_add",
        ),
        (
            IRInstructionDTO::MatrixSub {
                result: v(),
                left: v(),
                right: v(),
                shape: [-1, 0],
            },
            "matrix_sub",
        ),
        (
            IRInstructionDTO::MatrixScale {
                result: v(),
                matrix: v(),
                scalar: v(),
                shape: [-1, 0],
            },
            "matrix_scale",
        ),
        (
            IRInstructionDTO::MatrixMatMul {
                result: v(),
                left: v(),
                right: v(),
                shape: [-1, 0, 1],
            },
            "matrix_mat_mul",
        ),
        (
            IRInstructionDTO::MatrixVectorMul {
                result: v(),
                matrix: v(),
                vector: v(),
                shape: [-1, 0],
            },
            "matrix_vector_mul",
        ),
        (
            IRInstructionDTO::VectorMatrixMul {
                result: v(),
                vector: v(),
                matrix: v(),
                shape: [-1, 0],
            },
            "vector_matrix_mul",
        ),
        (
            IRInstructionDTO::VectorGet {
                result: v(),
                vector: v(),
                index: v(),
            },
            "vector_get",
        ),
        (
            IRInstructionDTO::MatrixGet {
                result: v(),
                matrix: v(),
                row: v(),
                column: v(),
                shape: [-1],
            },
            "matrix_get",
        ),
        (
            IRInstructionDTO::VectorLength {
                result: v(),
                vector: v(),
            },
            "vector_length",
        ),
        (
            IRInstructionDTO::MatrixRows {
                result: v(),
                matrix: v(),
                shape: [-1],
            },
            "matrix_rows",
        ),
        (
            IRInstructionDTO::MatrixColumns {
                result: v(),
                matrix: v(),
                shape: [-1],
            },
            "matrix_columns",
        ),
        (
            IRInstructionDTO::VectorSet {
                vector: v(),
                index: v(),
                value: v(),
            },
            "vector_set",
        ),
        (
            IRInstructionDTO::MatrixSet {
                matrix: v(),
                row: v(),
                column: v(),
                value: v(),
                shape: [-1],
            },
            "matrix_set",
        ),
        (
            IRInstructionDTO::Branch {
                condition: v(),
                true_target: "missing::true".to_owned(),
                false_target: "missing::false".to_owned(),
            },
            "branch",
        ),
        (
            IRInstructionDTO::Jump {
                target: "missing::target".to_owned(),
            },
            "jump",
        ),
        (
            IRInstructionDTO::Return {
                value: NullableDTO(None),
                transferred_storage: NullableDTO(None),
            },
            "return",
        ),
    ];

    assert_eq!(
        unsupported.len(),
        23,
        "68 total - 45 supported = 23 later kinds"
    );
    for (wire, kind) in unsupported {
        assert_eq!(
            import_instruction(&wire),
            Err(IRImportError::UnsupportedInstruction { kind })
        );
    }
}
