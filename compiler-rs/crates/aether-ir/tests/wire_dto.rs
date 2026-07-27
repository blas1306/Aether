//! Compatibility tests for the schema-v1 Rust wire DTO model.

use std::collections::BTreeSet;

use aether_ir::wire::{
    IRConstantDTO, IRFloatDTO, IRInstructionDTO, IRModuleDTO, IRParameterDTO, IRSourceLocationDTO,
    IRStorageDTO, IRTypeDTO, IRValueDTO,
};
use aether_ir::{IRInstruction, import_instruction};
use serde_json::{Map, Value, json};

const GOLDEN: &str =
    include_str!("../../../../tests/aether/rust_migration/fixtures/ir_module_v1_golden.json");

fn value() -> Value {
    json!({"tag": "value", "name": "value", "type": {"tag": "int"}})
}

fn storage() -> Value {
    json!({"tag": "storage", "name": "storage", "type": {"tag": "int"}})
}

fn parameter() -> Value {
    json!({"tag": "parameter", "name": "parameter", "type": {"tag": "bool"}})
}

fn location() -> Value {
    json!({"tag": "source_location", "line": 3, "column": 5, "path": "sample.ae"})
}

fn instruction(kind: &str, fields: &[(&str, Value)]) -> Value {
    let mut object = Map::from_iter([("kind".to_owned(), Value::String(kind.to_owned()))]);
    object.extend(
        fields
            .iter()
            .map(|(name, value)| ((*name).to_owned(), value.clone())),
    );
    Value::Object(object)
}

#[allow(clippy::too_many_lines)]
fn instruction_cases() -> Vec<Value> {
    vec![
        instruction(
            "const",
            &[
                ("result", value()),
                ("value", json!({"tag": "int", "value": 7})),
            ],
        ),
        instruction("load", &[("result", value()), ("slot", storage())]),
        instruction("store", &[("slot", storage()), ("value", value())]),
        instruction(
            "init_default",
            &[("destination", storage()), ("source_location", location())],
        ),
        instruction(
            "copy_init",
            &[
                ("destination", storage()),
                ("source", value()),
                ("source_location", Value::Null),
            ],
        ),
        instruction(
            "move_init",
            &[
                ("destination", storage()),
                ("source", storage()),
                ("source_location", Value::Null),
            ],
        ),
        instruction(
            "assign",
            &[
                ("destination", storage()),
                ("source", value()),
                ("source_location", Value::Null),
            ],
        ),
        instruction(
            "destroy",
            &[("value", storage()), ("source_location", Value::Null)],
        ),
        instruction(
            "relocate",
            &[
                ("destination", storage()),
                ("source", storage()),
                ("count", json!(2)),
                ("source_location", location()),
            ],
        ),
        instruction(
            "binary_op",
            &[
                ("result", value()),
                ("operator", json!("+")),
                ("left", value()),
                ("right", value()),
                ("source_location", location()),
            ],
        ),
        instruction(
            "unary_op",
            &[
                ("result", value()),
                ("operator", json!("neg")),
                ("operand", value()),
            ],
        ),
        instruction(
            "compare_op",
            &[
                ("result", value()),
                ("operator", json!("eq")),
                ("left", value()),
                ("right", value()),
                ("aggregate_shape", json!([2, 3])),
            ],
        ),
        instruction("cast", &[("result", value()), ("value", value())]),
        instruction(
            "call",
            &[
                ("function", json!("callee")),
                ("arguments", json!([value()])),
                ("result", value()),
                ("builtin", Value::Null),
                ("source_location", location()),
            ],
        ),
        instruction(
            "function_ref",
            &[("result", value()), ("function", json!("callee"))],
        ),
        instruction(
            "call_indirect",
            &[
                ("callee", value()),
                ("arguments", json!([value()])),
                ("result", Value::Null),
            ],
        ),
        instruction(
            "print",
            &[
                ("value", value()),
                ("newline", json!(true)),
                ("aggregate_shape", Value::Null),
            ],
        ),
        instruction(
            "struct_new",
            &[("result", value()), ("fields", json!([value()]))],
        ),
        instruction("class_new", &[("result", value())]),
        instruction(
            "struct_get",
            &[
                ("result", value()),
                ("struct", value()),
                ("field_index", json!(0)),
                ("field_name", json!("field")),
            ],
        ),
        instruction(
            "struct_set",
            &[
                ("result", value()),
                ("struct", value()),
                ("field_index", json!(0)),
                ("field_name", json!("field")),
                ("value", value()),
            ],
        ),
        instruction(
            "method_result_new",
            &[
                ("result", value()),
                ("receiver", value()),
                ("value", Value::Null),
            ],
        ),
        instruction(
            "method_result_receiver",
            &[("result", value()), ("method_result", value())],
        ),
        instruction(
            "method_result_value",
            &[("result", value()), ("method_result", value())],
        ),
        instruction(
            "array_new",
            &[("result", value()), ("elements", json!([value()]))],
        ),
        instruction(
            "list_new",
            &[("result", value()), ("elements", json!([value()]))],
        ),
        instruction(
            "array_copy",
            &[
                ("result", value()),
                ("array", value()),
                ("source_location", location()),
            ],
        ),
        instruction(
            "list_copy",
            &[
                ("result", value()),
                ("list_value", value()),
                ("source_location", location()),
            ],
        ),
        instruction(
            "list_contains",
            &[
                ("result", value()),
                ("list_value", value()),
                ("value", value()),
            ],
        ),
        instruction(
            "list_index_of",
            &[
                ("result", value()),
                ("list_value", value()),
                ("value", value()),
            ],
        ),
        instruction("list_clear", &[("list_value", value())]),
        instruction("list_push", &[("list_value", value()), ("value", value())]),
        instruction(
            "list_insert",
            &[
                ("list_value", value()),
                ("index", value()),
                ("value", value()),
            ],
        ),
        instruction(
            "list_remove_at",
            &[
                ("result", value()),
                ("list_value", value()),
                ("index", value()),
            ],
        ),
        instruction("list_pop", &[("result", value()), ("list_value", value())]),
        instruction("list_reverse", &[("list_value", value())]),
        instruction("sequence_sort", &[("sequence", value())]),
        instruction(
            "array_get",
            &[
                ("result", value()),
                ("array", value()),
                ("index", value()),
                ("borrowed", json!(true)),
                ("borrow_scope", json!("scope")),
                ("source_location", location()),
            ],
        ),
        instruction(
            "array_slice",
            &[
                ("result", value()),
                ("array", value()),
                ("start", value()),
                ("end", value()),
                ("source_location", Value::Null),
            ],
        ),
        instruction(
            "list_slice",
            &[
                ("result", value()),
                ("list_value", value()),
                ("start", value()),
                ("end", value()),
                ("source_location", Value::Null),
            ],
        ),
        instruction(
            "list_get",
            &[
                ("result", value()),
                ("list_value", value()),
                ("index", value()),
                ("borrowed", json!(false)),
                ("borrow_scope", Value::Null),
                ("source_location", Value::Null),
            ],
        ),
        instruction(
            "array_set",
            &[("array", value()), ("index", value()), ("value", value())],
        ),
        instruction(
            "list_set",
            &[
                ("list_value", value()),
                ("index", value()),
                ("value", value()),
            ],
        ),
        instruction("array_length", &[("result", value()), ("array", value())]),
        instruction(
            "list_length",
            &[("result", value()), ("list_value", value())],
        ),
        instruction(
            "list_is_empty",
            &[("result", value()), ("list_value", value())],
        ),
        instruction(
            "vector_new",
            &[
                ("result", value()),
                ("elements", json!([value()])),
                ("orientation", json!("row")),
            ],
        ),
        instruction(
            "matrix_new",
            &[
                ("result", value()),
                ("elements", json!([value()])),
                ("shape", json!([2, 3])),
            ],
        ),
        instruction(
            "vector_add",
            &[
                ("result", value()),
                ("left", value()),
                ("right", value()),
                ("shape", json!([3])),
                ("orientation", json!("row")),
            ],
        ),
        instruction(
            "vector_sub",
            &[
                ("result", value()),
                ("left", value()),
                ("right", value()),
                ("shape", json!([3])),
                ("orientation", Value::Null),
            ],
        ),
        instruction(
            "vector_scale",
            &[
                ("result", value()),
                ("vector", value()),
                ("scalar", value()),
                ("shape", json!([3])),
                ("orientation", json!("column")),
            ],
        ),
        instruction(
            "vector_dot",
            &[
                ("result", value()),
                ("left", value()),
                ("right", value()),
                ("shape", json!([3])),
            ],
        ),
        instruction(
            "outer_product",
            &[
                ("result", value()),
                ("column", value()),
                ("row", value()),
                ("shape", json!([2, 3])),
            ],
        ),
        instruction(
            "matrix_add",
            &[
                ("result", value()),
                ("left", value()),
                ("right", value()),
                ("shape", json!([2, 3])),
            ],
        ),
        instruction(
            "matrix_sub",
            &[
                ("result", value()),
                ("left", value()),
                ("right", value()),
                ("shape", json!([2, 3])),
            ],
        ),
        instruction(
            "matrix_scale",
            &[
                ("result", value()),
                ("matrix", value()),
                ("scalar", value()),
                ("shape", json!([2, 3])),
            ],
        ),
        instruction(
            "matrix_mat_mul",
            &[
                ("result", value()),
                ("left", value()),
                ("right", value()),
                ("shape", json!([2, 4, 3])),
            ],
        ),
        instruction(
            "matrix_vector_mul",
            &[
                ("result", value()),
                ("matrix", value()),
                ("vector", value()),
                ("shape", json!([2, 3])),
            ],
        ),
        instruction(
            "vector_matrix_mul",
            &[
                ("result", value()),
                ("vector", value()),
                ("matrix", value()),
                ("shape", json!([2, 3])),
            ],
        ),
        instruction(
            "vector_get",
            &[("result", value()), ("vector", value()), ("index", value())],
        ),
        instruction(
            "matrix_get",
            &[
                ("result", value()),
                ("matrix", value()),
                ("row", value()),
                ("column", value()),
                ("shape", json!([3])),
            ],
        ),
        instruction("vector_length", &[("result", value()), ("vector", value())]),
        instruction(
            "matrix_rows",
            &[
                ("result", value()),
                ("matrix", value()),
                ("shape", json!([2])),
            ],
        ),
        instruction(
            "matrix_columns",
            &[
                ("result", value()),
                ("matrix", value()),
                ("shape", json!([3])),
            ],
        ),
        instruction(
            "vector_set",
            &[("vector", value()), ("index", value()), ("value", value())],
        ),
        instruction(
            "matrix_set",
            &[
                ("matrix", value()),
                ("row", value()),
                ("column", value()),
                ("value", value()),
                ("shape", json!([3])),
            ],
        ),
        instruction(
            "branch",
            &[
                ("condition", parameter()),
                ("true_target", json!("then")),
                ("false_target", json!("else")),
            ],
        ),
        instruction("jump", &[("target", json!("exit"))]),
        instruction(
            "return",
            &[("value", value()), ("transferred_storage", storage())],
        ),
    ]
}

macro_rules! instruction_variant_mapping {
    ($($wire:ident => $owned:ident),+ $(,)?) => {
        const INSTRUCTION_VARIANT_MAPPING_COUNT: usize = [$(stringify!($wire)),+].len();

        fn has_corresponding_owned_variant(
            wire: &IRInstructionDTO,
            owned: &IRInstruction,
        ) -> bool {
            match wire {
                $(
                    IRInstructionDTO::$wire { .. } => {
                        matches!(owned, IRInstruction::$owned { .. })
                    }
                ),+
            }
        }
    };
}

// This is the importer identity map, not a second tag inventory. The outer
// match is intentionally exhaustive so a new wire variant cannot compile
// without an explicit owned-variant decision here and in the importer.
instruction_variant_mapping! {
    Const => IRConst,
    Load => IRLoad,
    Store => IRStore,
    InitDefault => IRInitDefault,
    CopyInit => IRCopyInit,
    MoveInit => IRMoveInit,
    Assign => IRAssign,
    Destroy => IRDestroy,
    Relocate => IRRelocate,
    BinaryOp => IRBinaryOp,
    UnaryOp => IRUnaryOp,
    CompareOp => IRCompareOp,
    Cast => IRCast,
    Call => IRCall,
    FunctionRef => IRFunctionRef,
    CallIndirect => IRCallIndirect,
    Print => IRPrint,
    StructNew => IRStructNew,
    ClassNew => IRClassNew,
    StructGet => IRStructGet,
    StructSet => IRStructSet,
    MethodResultNew => IRMethodResultNew,
    MethodResultReceiver => IRMethodResultReceiver,
    MethodResultValue => IRMethodResultValue,
    ArrayNew => IRArrayNew,
    ListNew => IRListNew,
    ArrayCopy => IRArrayCopy,
    ListCopy => IRListCopy,
    ListContains => IRListContains,
    ListIndexOf => IRListIndexOf,
    ListClear => IRListClear,
    ListPush => IRListPush,
    ListInsert => IRListInsert,
    ListRemoveAt => IRListRemoveAt,
    ListPop => IRListPop,
    ListReverse => IRListReverse,
    SequenceSort => IRSequenceSort,
    ArrayGet => IRArrayGet,
    ArraySlice => IRArraySlice,
    ListSlice => IRListSlice,
    ListGet => IRListGet,
    ArraySet => IRArraySet,
    ListSet => IRListSet,
    ArrayLength => IRArrayLength,
    ListLength => IRListLength,
    ListIsEmpty => IRListIsEmpty,
    VectorNew => IRVectorNew,
    MatrixNew => IRMatrixNew,
    VectorAdd => IRVectorAdd,
    VectorSub => IRVectorSub,
    VectorScale => IRVectorScale,
    VectorDot => IRVectorDot,
    OuterProduct => IROuterProduct,
    MatrixAdd => IRMatrixAdd,
    MatrixSub => IRMatrixSub,
    MatrixScale => IRMatrixScale,
    MatrixMatMul => IRMatrixMatMul,
    MatrixVectorMul => IRMatrixVectorMul,
    VectorMatrixMul => IRVectorMatrixMul,
    VectorGet => IRVectorGet,
    MatrixGet => IRMatrixGet,
    VectorLength => IRVectorLength,
    MatrixRows => IRMatrixRows,
    MatrixColumns => IRMatrixColumns,
    VectorSet => IRVectorSet,
    MatrixSet => IRMatrixSet,
    Branch => IRBranch,
    Jump => IRJump,
    Return => IRReturn,
}

#[test]
fn golden_python_fixture_round_trips_deterministically() {
    let dto: IRModuleDTO = serde_json::from_str(GOLDEN).expect("golden DTO must deserialize");

    assert_eq!(dto.schema_version, 1);
    let first = serde_json::to_string(&dto).expect("golden DTO must serialize");
    let decoded: IRModuleDTO = serde_json::from_str(&first).expect("Rust JSON must deserialize");
    let second = serde_json::to_string(&decoded).expect("round-tripped DTO must serialize");

    assert_eq!(dto, decoded);
    assert_eq!(first, second);
    assert_eq!(
        serde_json::from_str::<Value>(GOLDEN).expect("fixture is valid JSON"),
        serde_json::from_str::<Value>(&first).expect("serialized DTO is valid JSON")
    );
}

#[test]
fn every_instruction_tag_deserializes_imports_and_round_trips() {
    let cases = instruction_cases();
    let tags = cases
        .iter()
        .map(|case| case["kind"].as_str().expect("kind is a string"))
        .collect::<BTreeSet<_>>();

    assert_eq!(cases.len(), 68);
    assert_eq!(tags.len(), 68);
    assert_eq!(INSTRUCTION_VARIANT_MAPPING_COUNT, 68);
    for case in cases {
        let tag = case["kind"].as_str().expect("kind is a string");
        let dto: IRInstructionDTO = serde_json::from_value(case.clone())
            .unwrap_or_else(|error| panic!("{tag} must deserialize: {error}"));
        let imported =
            import_instruction(&dto).unwrap_or_else(|error| panic!("{tag} must import: {error}"));
        assert!(
            has_corresponding_owned_variant(&dto, &imported),
            "{tag} imported into the wrong owned instruction variant: {imported:?}"
        );
        assert_eq!(IRInstruction::try_from(&dto), Ok(imported.clone()));
        assert_eq!(IRInstruction::try_from(dto.clone()), Ok(imported));
        assert_eq!(
            serde_json::to_value(dto).expect("instruction must serialize"),
            case,
            "{tag} changed wire shape"
        );
    }
}

#[test]
fn every_type_tag_deserializes_and_round_trips() {
    let cases = [
        json!({"tag": "int"}),
        json!({"tag": "float"}),
        json!({"tag": "double"}),
        json!({"tag": "bool"}),
        json!({"tag": "string"}),
        json!({"tag": "void"}),
        json!({"tag": "function", "parameter_types": [{"tag": "int"}], "return_type": {"tag": "void"}}),
        json!({"tag": "complex"}),
        json!({"tag": "nullable", "inner": {"tag": "string"}}),
        json!({"tag": "list", "element": {"tag": "int"}}),
        json!({"tag": "array", "element": {"tag": "int"}}),
        json!({"tag": "vector", "element": {"tag": "float"}, "orientation": null}),
        json!({"tag": "matrix", "element": {"tag": "double"}}),
        json!({"tag": "struct", "name": "Point"}),
        json!({"tag": "method_result", "receiver": {"tag": "struct", "name": "Point"}, "value": {"tag": "int"}}),
        json!({"tag": "class_ref", "name": "Widget"}),
        json!({"tag": "interface", "name": "Drawable"}),
        json!({"tag": "enum", "name": "Color", "variants": ["red", "blue"], "display_name": "Color"}),
    ];

    assert_eq!(cases.len(), 18);
    for case in cases {
        let dto: IRTypeDTO = serde_json::from_value(case.clone()).expect("type must deserialize");
        assert_eq!(
            serde_json::to_value(dto).expect("type must serialize"),
            case
        );
    }
}

#[test]
fn value_constant_and_location_tags_preserve_their_shapes() {
    for case in [value(), storage(), parameter()] {
        let dto: IRValueDTO = serde_json::from_value(case.clone()).expect("value must deserialize");
        assert_eq!(
            serde_json::to_value(dto).expect("value must serialize"),
            case
        );
    }

    let storage_dto: IRStorageDTO =
        serde_json::from_value(storage()).expect("storage must deserialize");
    let parameter_dto: IRParameterDTO =
        serde_json::from_value(parameter()).expect("parameter must deserialize");
    let location_dto: IRSourceLocationDTO =
        serde_json::from_value(location()).expect("location must deserialize");
    assert_eq!(serde_json::to_value(storage_dto).unwrap(), storage());
    assert_eq!(serde_json::to_value(parameter_dto).unwrap(), parameter());
    assert_eq!(serde_json::to_value(location_dto).unwrap(), location());

    let constants = [
        json!({"tag": "null"}),
        json!({"tag": "bool", "value": true}),
        json!({"tag": "int", "value": -7}),
        json!({"tag": "float", "value": 1.25}),
        json!({"tag": "complex", "real": 2.0, "imaginary": -3.0}),
        json!({"tag": "string", "value": "aether"}),
        json!({"tag": "enum", "value": {"tag": "enum_constant", "enum_name": "Color", "member_name": "red", "member_id": 0, "discriminant": 4}}),
    ];
    for case in constants {
        let dto: IRConstantDTO =
            serde_json::from_value(case.clone()).expect("constant must deserialize");
        assert_eq!(serde_json::to_value(dto).unwrap(), case);
    }
}

#[test]
fn malformed_json_and_unknown_instruction_tags_are_rejected() {
    assert!(serde_json::from_str::<IRModuleDTO>("{").is_err());
    assert!(serde_json::from_value::<IRInstructionDTO>(json!({"kind": "future"})).is_err());
    assert!(
        serde_json::from_value::<IRModuleDTO>(
            json!({"schema_version": 2, "functions": [], "structs": []})
        )
        .is_err()
    );
    assert!(serde_json::from_value::<IRConstantDTO>(json!({"tag": "float", "value": 1})).is_err());
    assert!(
        serde_json::to_string(&IRConstantDTO::Float {
            value: IRFloatDTO(f64::NAN),
        })
        .is_err()
    );
}

#[test]
fn missing_fields_including_nullable_fields_are_rejected() {
    assert!(serde_json::from_value::<IRInstructionDTO>(json!({"kind": "jump"})).is_err());
    assert!(
        serde_json::from_value::<IRInstructionDTO>(
            json!({"kind": "return", "transferred_storage": null})
        )
        .is_err()
    );
    assert!(
        serde_json::from_value::<IRInstructionDTO>(json!({"kind": "return", "value": null}))
            .is_err()
    );
}

#[test]
fn unexpected_fields_are_rejected_like_the_python_contract() {
    assert!(
        serde_json::from_value::<IRModuleDTO>(
            json!({"schema_version": 1, "functions": [], "structs": [], "extra": true})
        )
        .is_err()
    );
    assert!(
        serde_json::from_value::<IRInstructionDTO>(
            json!({"kind": "jump", "target": "exit", "extra": true})
        )
        .is_err()
    );
    assert!(serde_json::from_value::<IRTypeDTO>(json!({"tag": "int", "extra": true})).is_err());
}
