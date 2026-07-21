//! Focused coverage for schema-v1 linear-algebra instruction import.

use aether_ir::wire::{IRInstructionDTO, IRTypeDTO, IRValueDTO, NullableDTO};
use aether_ir::{
    BoolType, DoubleType, IRImportError, IRInstruction, IRType, IRValue, IntType, ListType,
    MatrixType, StringType, StructType, VectorType, import_instruction,
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

fn vector_type(orientation: Option<&str>) -> IRType {
    VectorType {
        element: Box::new(DoubleType.into()),
        orientation: orientation.map(str::to_owned),
    }
    .into()
}

fn matrix_type() -> IRType {
    MatrixType {
        element: Box::new(DoubleType.into()),
    }
    .into()
}

fn vector_value(name: &str, orientation: Option<&str>) -> IRValue {
    IRValue::new(name, vector_type(orientation))
}

fn matrix_value(name: &str) -> IRValue {
    IRValue::new(name, matrix_type())
}

fn nested_vector_type() -> IRType {
    VectorType {
        element: Box::new(
            ListType {
                element: Box::new(
                    StructType {
                        name: " Missing::Element ".to_owned(),
                    }
                    .into(),
                ),
            }
            .into(),
        ),
        orientation: Some(" diagonal\0raw ".to_owned()),
    }
    .into()
}

fn nested_matrix_type() -> IRType {
    MatrixType {
        element: Box::new(
            VectorType {
                element: Box::new(DoubleType.into()),
                orientation: None,
            }
            .into(),
        ),
    }
    .into()
}

fn nested_vector_value(name: &str) -> IRValue {
    IRValue::new(name, nested_vector_type())
}

fn nested_matrix_value(name: &str) -> IRValue {
    IRValue::new(name, nested_matrix_type())
}

fn typed_json_value(name: &str, type_: &Value) -> Value {
    json!({"tag": "value", "name": name, "type": type_})
}

fn int_json_value(name: &str) -> Value {
    typed_json_value(name, &json!({"tag": "int"}))
}

fn bool_json_value(name: &str) -> Value {
    typed_json_value(name, &json!({"tag": "bool"}))
}

fn string_json_value(name: &str) -> Value {
    typed_json_value(name, &json!({"tag": "string"}))
}

fn vector_json_type(orientation: Option<&str>) -> Value {
    json!({
        "tag": "vector",
        "element": {"tag": "double"},
        "orientation": orientation,
    })
}

fn matrix_json_type() -> Value {
    json!({"tag": "matrix", "element": {"tag": "double"}})
}

fn vector_json_value(name: &str, orientation: Option<&str>) -> Value {
    typed_json_value(name, &vector_json_type(orientation))
}

fn matrix_json_value(name: &str) -> Value {
    typed_json_value(name, &matrix_json_type())
}

#[test]
#[allow(clippy::too_many_lines)]
fn imports_all_twenty_linear_algebra_variants_exactly_through_both_paths() {
    let nested_vector_json = json!({
        "tag": "vector",
        "element": {
            "tag": "list",
            "element": {"tag": "struct", "name": " Missing::Element "}
        },
        "orientation": " diagonal\0raw ",
    });
    let nested_matrix_json = json!({
        "tag": "matrix",
        "element": {
            "tag": "vector",
            "element": {"tag": "double"},
            "orientation": null,
        },
    });
    let cases = vec![
        (
            json!({
                "kind": "vector_new",
                "result": typed_json_value("vector_new::result", &nested_vector_json),
                "elements": [
                    string_json_value("third"),
                    typed_json_value("first", &nested_matrix_json),
                    bool_json_value("second"),
                    string_json_value("third"),
                ],
                "orientation": " arbitrary\0orientation ",
            }),
            IRInstruction::IRVectorNew {
                result: nested_vector_value("vector_new::result"),
                elements: vec![
                    string_value("third"),
                    nested_matrix_value("first"),
                    bool_value("second"),
                    string_value("third"),
                ],
                orientation: Some(" arbitrary\0orientation ".to_owned()),
            },
        ),
        (
            json!({
                "kind": "matrix_new",
                "result": typed_json_value("matrix_new::result", &nested_matrix_json),
                "elements": [
                    int_json_value("m00"),
                    typed_json_value("nested", &nested_vector_json),
                    int_json_value("m00"),
                ],
                "shape": [-7, 0],
            }),
            IRInstruction::IRMatrixNew {
                result: nested_matrix_value("matrix_new::result"),
                elements: vec![
                    int_value("m00"),
                    nested_vector_value("nested"),
                    int_value("m00"),
                ],
                rows: -7,
                cols: 0,
            },
        ),
        (
            json!({
                "kind": "vector_add",
                "result": vector_json_value("vector_add::result", Some("row")),
                "left": vector_json_value("vector_add::left", Some("column")),
                "right": vector_json_value("vector_add::right", None),
                "shape": [3],
                "orientation": "row",
            }),
            IRInstruction::IRVectorAdd {
                result: vector_value("vector_add::result", Some("row")),
                left: vector_value("vector_add::left", Some("column")),
                right: vector_value("vector_add::right", None),
                length: 3,
                orientation: Some("row".to_owned()),
            },
        ),
        (
            json!({
                "kind": "vector_sub",
                "result": vector_json_value("vector_sub::result", None),
                "left": vector_json_value("vector_sub::left", Some("row")),
                "right": vector_json_value("vector_sub::right", Some("column")),
                "shape": [-1],
                "orientation": null,
            }),
            IRInstruction::IRVectorSub {
                result: vector_value("vector_sub::result", None),
                left: vector_value("vector_sub::left", Some("row")),
                right: vector_value("vector_sub::right", Some("column")),
                length: -1,
                orientation: None,
            },
        ),
        (
            json!({
                "kind": "vector_scale",
                "result": vector_json_value("vector_scale::result", Some("sideways")),
                "vector": vector_json_value("vector_scale::vector", None),
                "scalar": string_json_value("vector_scale::wrong_scalar"),
                "shape": [0],
                "orientation": "sideways",
            }),
            IRInstruction::IRVectorScale {
                result: vector_value("vector_scale::result", Some("sideways")),
                vector: vector_value("vector_scale::vector", None),
                scalar: string_value("vector_scale::wrong_scalar"),
                length: 0,
                orientation: Some("sideways".to_owned()),
            },
        ),
        (
            json!({
                "kind": "vector_dot",
                "result": int_json_value("vector_dot::wrong_result"),
                "left": vector_json_value("vector_dot::left", Some("column")),
                "right": vector_json_value("vector_dot::right", Some("row")),
                "shape": [i64::MAX],
            }),
            IRInstruction::IRVectorDot {
                result: int_value("vector_dot::wrong_result"),
                left: vector_value("vector_dot::left", Some("column")),
                right: vector_value("vector_dot::right", Some("row")),
                length: i64::MAX,
            },
        ),
        (
            json!({
                "kind": "outer_product",
                "result": matrix_json_value("outer_product::result"),
                "column": vector_json_value("outer_product::column", Some("row")),
                "row": vector_json_value("outer_product::row", Some("column")),
                "shape": [2, 5],
            }),
            IRInstruction::IROuterProduct {
                result: matrix_value("outer_product::result"),
                column: vector_value("outer_product::column", Some("row")),
                row: vector_value("outer_product::row", Some("column")),
                rows: 2,
                cols: 5,
            },
        ),
        (
            json!({
                "kind": "matrix_add",
                "result": matrix_json_value("matrix_add::result"),
                "left": matrix_json_value("matrix_add::left"),
                "right": matrix_json_value("matrix_add::right"),
                "shape": [2, 3],
            }),
            IRInstruction::IRMatrixAdd {
                result: matrix_value("matrix_add::result"),
                left: matrix_value("matrix_add::left"),
                right: matrix_value("matrix_add::right"),
                rows: 2,
                cols: 3,
            },
        ),
        (
            json!({
                "kind": "matrix_sub",
                "result": matrix_json_value("matrix_sub::result"),
                "left": matrix_json_value("matrix_sub::left"),
                "right": matrix_json_value("matrix_sub::right"),
                "shape": [i64::MIN, i64::MAX],
            }),
            IRInstruction::IRMatrixSub {
                result: matrix_value("matrix_sub::result"),
                left: matrix_value("matrix_sub::left"),
                right: matrix_value("matrix_sub::right"),
                rows: i64::MIN,
                cols: i64::MAX,
            },
        ),
        (
            json!({
                "kind": "matrix_scale",
                "result": matrix_json_value("matrix_scale::result"),
                "matrix": matrix_json_value("matrix_scale::matrix"),
                "scalar": bool_json_value("matrix_scale::wrong_scalar"),
                "shape": [-3, -4],
            }),
            IRInstruction::IRMatrixScale {
                result: matrix_value("matrix_scale::result"),
                matrix: matrix_value("matrix_scale::matrix"),
                scalar: bool_value("matrix_scale::wrong_scalar"),
                rows: -3,
                cols: -4,
            },
        ),
        (
            json!({
                "kind": "matrix_mat_mul",
                "result": matrix_json_value("matmul::result"),
                "left": matrix_json_value("matmul::left"),
                "right": matrix_json_value("matmul::right"),
                "shape": [2, -9, 7],
            }),
            IRInstruction::IRMatrixMatMul {
                result: matrix_value("matmul::result"),
                left: matrix_value("matmul::left"),
                right: matrix_value("matmul::right"),
                rows: 2,
                inner: -9,
                cols: 7,
            },
        ),
        (
            json!({
                "kind": "matrix_vector_mul",
                "result": vector_json_value("matrix_vector::result", Some("column")),
                "matrix": matrix_json_value("matrix_vector::matrix"),
                "vector": vector_json_value("matrix_vector::vector", Some("row")),
                "shape": [4, 0],
            }),
            IRInstruction::IRMatrixVectorMul {
                result: vector_value("matrix_vector::result", Some("column")),
                matrix: matrix_value("matrix_vector::matrix"),
                vector: vector_value("matrix_vector::vector", Some("row")),
                rows: 4,
                inner: 0,
            },
        ),
        (
            json!({
                "kind": "vector_matrix_mul",
                "result": vector_json_value("vector_matrix::result", Some("row")),
                "vector": vector_json_value("vector_matrix::vector", Some("column")),
                "matrix": matrix_json_value("vector_matrix::matrix"),
                "shape": [-5, 8],
            }),
            IRInstruction::IRVectorMatrixMul {
                result: vector_value("vector_matrix::result", Some("row")),
                vector: vector_value("vector_matrix::vector", Some("column")),
                matrix: matrix_value("vector_matrix::matrix"),
                rows: -5,
                cols: 8,
            },
        ),
        (
            json!({
                "kind": "vector_get",
                "result": string_json_value("vector_get::wrong_result"),
                "vector": vector_json_value("vector_get::vector", None),
                "index": bool_json_value("vector_get::wrong_index"),
            }),
            IRInstruction::IRVectorGet {
                result: string_value("vector_get::wrong_result"),
                vector: vector_value("vector_get::vector", None),
                index: bool_value("vector_get::wrong_index"),
            },
        ),
        (
            json!({
                "kind": "matrix_get",
                "result": int_json_value("matrix_get::result"),
                "matrix": matrix_json_value("matrix_get::matrix"),
                "row": int_json_value("matrix_get::row"),
                "column": int_json_value("matrix_get::column"),
                "shape": [-11],
            }),
            IRInstruction::IRMatrixGet {
                result: int_value("matrix_get::result"),
                matrix: matrix_value("matrix_get::matrix"),
                row: int_value("matrix_get::row"),
                column: int_value("matrix_get::column"),
                cols: -11,
            },
        ),
        (
            json!({
                "kind": "vector_length",
                "result": bool_json_value("vector_length::wrong_result"),
                "vector": vector_json_value("vector_length::vector", None),
            }),
            IRInstruction::IRVectorLength {
                result: bool_value("vector_length::wrong_result"),
                vector: vector_value("vector_length::vector", None),
            },
        ),
        (
            json!({
                "kind": "matrix_rows",
                "result": int_json_value("matrix_rows::result"),
                "matrix": matrix_json_value("matrix_rows::matrix"),
                "shape": [0],
            }),
            IRInstruction::IRMatrixRows {
                result: int_value("matrix_rows::result"),
                matrix: matrix_value("matrix_rows::matrix"),
                rows: 0,
            },
        ),
        (
            json!({
                "kind": "matrix_columns",
                "result": int_json_value("matrix_columns::result"),
                "matrix": matrix_json_value("matrix_columns::matrix"),
                "shape": [-13],
            }),
            IRInstruction::IRMatrixColumns {
                result: int_value("matrix_columns::result"),
                matrix: matrix_value("matrix_columns::matrix"),
                columns: -13,
            },
        ),
        (
            json!({
                "kind": "vector_set",
                "vector": vector_json_value("vector_set::vector", Some("column")),
                "index": string_json_value("vector_set::wrong_index"),
                "value": bool_json_value("vector_set::wrong_value"),
            }),
            IRInstruction::IRVectorSet {
                vector: vector_value("vector_set::vector", Some("column")),
                index: string_value("vector_set::wrong_index"),
                value: bool_value("vector_set::wrong_value"),
            },
        ),
        (
            json!({
                "kind": "matrix_set",
                "matrix": matrix_json_value("matrix_set::matrix"),
                "row": bool_json_value("matrix_set::wrong_row"),
                "column": string_json_value("matrix_set::wrong_column"),
                "value": typed_json_value("matrix_set::nested_value", &nested_vector_json),
                "shape": [i64::MIN],
            }),
            IRInstruction::IRMatrixSet {
                matrix: matrix_value("matrix_set::matrix"),
                row: bool_value("matrix_set::wrong_row"),
                column: string_value("matrix_set::wrong_column"),
                value: nested_vector_value("matrix_set::nested_value"),
                cols: i64::MIN,
            },
        ),
    ];

    assert_eq!(
        cases.len(),
        20,
        "the linear-algebra slice must add 20 kinds"
    );
    for (json, expected) in cases {
        let encoded = serde_json::to_string(&json)
            .expect("linear-algebra instruction JSON must encode deterministically");
        assert_eq!(
            serde_json::to_string(&json).expect("repeat encoding must succeed"),
            encoded
        );
        let wire: IRInstructionDTO = serde_json::from_str(&encoded)
            .expect("linear-algebra instruction JSON must deserialize");
        let original = wire.clone();

        assert_eq!(import_instruction(&wire), Ok(expected.clone()));
        assert_eq!(import_instruction(&wire), Ok(expected.clone()));
        assert_eq!(IRInstruction::try_from(&wire), Ok(expected.clone()));
        assert_eq!(IRInstruction::try_from(wire.clone()), Ok(expected));
        assert_eq!(wire, original, "borrowed import must not mutate its DTO");
    }
}

#[test]
fn gives_linear_algebra_instruction_and_field_context_for_nested_errors() {
    let wire: IRInstructionDTO = serde_json::from_value(json!({
        "kind": "matrix_add",
        "result": matrix_json_value("result"),
        "left": matrix_json_value("left"),
        "right": {
            "tag": "parameter",
            "name": "bad::right",
            "type": {
                "tag": "method_result",
                "receiver": {"tag": "list", "element": {"tag": "int"}},
                "value": {"tag": "bool"}
            }
        },
        "shape": [2, 2]
    }))
    .expect("the wire model permits the unrepresentable nested type");

    assert_eq!(
        import_instruction(&wire),
        Err(IRImportError::InstructionField {
            instruction: "matrix_add",
            field: "right",
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
fn exactly_three_control_flow_variants_remain_explicitly_unsupported() {
    let unsupported = [
        (
            IRInstructionDTO::Branch {
                condition: plain_wire_value("condition"),
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

    assert_eq!(unsupported.len(), 3, "68 total - 65 supported = 3 kinds");
    for (wire, kind) in unsupported {
        assert_eq!(
            import_instruction(&wire),
            Err(IRImportError::UnsupportedInstruction { kind })
        );
    }
}
