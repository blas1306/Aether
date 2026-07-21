//! End-to-end coverage for strict JSON -> wire DTO -> owned Rust IR ingestion.

use std::error::Error as _;
use std::fs;
use std::path::Path;

use aether_ir::wire::{IR_SCHEMA_VERSION, IRModuleDTO};
use aether_ir::{
    ArrayType, BoolType, EnumType, IRConstant, IRImportError, IRInstruction,
    IRModuleJsonImportError, IRType, IntType, ListType, NullableType, StringType, StructType,
    import_module_json,
};
use serde_json::json;

const GOLDEN: &str =
    include_str!("../../../../tests/aether/rust_migration/fixtures/ir_module_v1_golden.json");

fn error_chain_len(error: &(dyn std::error::Error + 'static)) -> usize {
    let mut length = 1;
    let mut current = error;
    while let Some(source) = current.source() {
        length += 1;
        current = source;
    }
    length
}

#[test]
fn canonical_python_golden_reaches_owned_ir_with_exact_hierarchy_data() {
    let wire: IRModuleDTO = serde_json::from_str(GOLDEN).expect("golden wire DTO must deserialize");
    assert_eq!(wire.schema_version, IR_SCHEMA_VERSION);

    let module = import_module_json(GOLDEN).expect("golden JSON must import end to end");
    assert_eq!(module.structs.len(), 1);
    assert_eq!(module.structs[0].name, "Envelope");
    assert_eq!(
        module.structs[0]
            .fields
            .iter()
            .map(|(name, _)| name.as_str())
            .collect::<Vec<_>>(),
        ["payload", "labels"]
    );
    assert_eq!(
        module.structs[0].fields[0].1,
        ArrayType {
            element: Box::new(
                StructType {
                    name: "Point".to_owned(),
                }
                .into()
            ),
        }
        .into()
    );
    assert_eq!(
        module.structs[0].fields[1].1,
        ListType {
            element: Box::new(StringType.into()),
        }
        .into()
    );

    assert_eq!(module.functions.len(), 1);
    let function = &module.functions[0];
    assert_eq!(function.name, "choose");
    assert_eq!(function.parameters.len(), 1);
    assert_eq!(function.parameters[0].name, "condition");
    assert_eq!(function.parameters[0].r#type, BoolType.into());
    assert_eq!(function.return_type, IntType.into());
    assert_eq!(
        function
            .blocks
            .iter()
            .map(|block| block.name.as_str())
            .collect::<Vec<_>>(),
        ["entry", "selected"]
    );

    match &function.blocks[0].instructions[0] {
        IRInstruction::IRInitDefault {
            destination,
            source_location: Some(location),
        } => {
            assert_eq!(destination.name, "answer");
            assert_eq!(destination.r#type, IntType.into());
            assert_eq!((location.line, location.column), (4, 3));
            assert_eq!(location.path.as_deref(), Some("fixtures/golden.ae"));
        }
        other => panic!("expected init_default with a source location, found {other:?}"),
    }
    assert_eq!(
        function.blocks[0].instructions[1],
        IRInstruction::IRBranch {
            condition: function.parameters[0].clone().into(),
            true_target: "selected".to_owned(),
            false_target: "selected".to_owned(),
        }
    );
    assert_eq!(
        function.blocks[1].instructions[0],
        IRInstruction::IRConst {
            result: aether_ir::IRValue::new("answer", IntType.into()),
            value: IRConstant::Int(7),
        }
    );
    match &function.blocks[1].instructions[1] {
        IRInstruction::IRReturn {
            value: Some(value),
            transferred_storage: Some(storage),
        } => {
            assert_eq!(
                (value.name.as_str(), storage.name.as_str()),
                ("answer", "answer")
            );
            assert_eq!(value.r#type, storage.r#type);
        }
        other => panic!("expected return with transferred storage, found {other:?}"),
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn complete_boundary_preserves_nested_nullable_enum_shape_and_borrow_metadata() {
    let document = json!({
        "schema_version": 1,
        "structs": [{
            "name": "Señal",
            "fields": [{
                "name": "status_history",
                "type": {
                    "tag": "nullable",
                    "inner": {
                        "tag": "list",
                        "element": {
                            "tag": "enum",
                            "name": "Status",
                            "variants": ["ready", "done"],
                            "display_name": null
                        }
                    }
                }
            }]
        }],
        "functions": [{
            "name": "structural_only",
            "parameters": [{"tag": "parameter", "name": "seed", "type": {"tag": "int"}}],
            "return_type": {"tag": "void"},
            "blocks": [{
                "name": "entry",
                "instructions": [
                    {
                        "kind": "const",
                        "result": {"tag": "value", "name": "status", "type": {
                            "tag": "enum", "name": "Status", "variants": ["ready", "done"],
                            "display_name": "Estado"
                        }},
                        "value": {"tag": "enum", "value": {
                            "tag": "enum_constant", "enum_name": "Status", "member_name": "ready",
                            "member_id": 0, "discriminant": 7
                        }}
                    },
                    {
                        "kind": "compare_op",
                        "result": {"tag": "value", "name": "mask", "type": {"tag": "bool"}},
                        "operator": "eq",
                        "left": {"tag": "value", "name": "left", "type": {"tag": "int"}},
                        "right": {"tag": "value", "name": "right", "type": {"tag": "int"}},
                        "aggregate_shape": [2, 3]
                    },
                    {
                        "kind": "array_get",
                        "result": {"tag": "value", "name": "item", "type": {"tag": "int"}},
                        "array": {"tag": "value", "name": "items", "type": {
                            "tag": "array", "element": {"tag": "int"}
                        }},
                        "index": {"tag": "value", "name": "index", "type": {"tag": "int"}},
                        "borrowed": true,
                        "borrow_scope": "loop.body",
                        "source_location": {"tag": "source_location", "line": 9, "column": 11, "path": null}
                    },
                    {
                        "kind": "call",
                        "function": "missing",
                        "arguments": [],
                        "result": null,
                        "builtin": null,
                        "source_location": null
                    },
                    {"kind": "return", "value": null, "transferred_storage": null}
                ]
            }]
        }]
    });
    let json = serde_json::to_string(&document).expect("integration document must serialize");

    let first = import_module_json(&json).expect("structurally valid document must import");
    let second = import_module_json(&json).expect("repeated import must succeed");
    assert_eq!(first, second, "owned imports must be deterministic");
    assert_eq!(first.structs[0].name, "Señal");

    assert_eq!(
        first.structs[0].fields[0].1,
        NullableType {
            inner: Box::new(
                ListType {
                    element: Box::new(
                        EnumType {
                            name: "Status".to_owned(),
                            variants: vec!["ready".to_owned(), "done".to_owned()],
                            display_name: None,
                        }
                        .into(),
                    ),
                }
                .into(),
            ),
        }
        .into()
    );
    let instructions = &first.functions[0].blocks[0].instructions;
    match &instructions[0] {
        IRInstruction::IRConst {
            value: IRConstant::Enum(value),
            result,
        } => {
            assert_eq!(value.member_name, "ready");
            assert_eq!(value.discriminant, 7);
            assert!(matches!(result.r#type, IRType::Enum(_)));
        }
        other => panic!("expected enum constant, found {other:?}"),
    }
    match &instructions[1] {
        IRInstruction::IRCompareOp {
            aggregate_shape, ..
        } => assert_eq!(aggregate_shape.as_deref(), Some([2, 3].as_slice())),
        other => panic!("expected aggregate comparison, found {other:?}"),
    }
    match &instructions[2] {
        IRInstruction::IRArrayGet {
            borrowed,
            borrow_scope,
            source_location: Some(location),
            ..
        } => {
            assert!(*borrowed);
            assert_eq!(borrow_scope.as_deref(), Some("loop.body"));
            assert_eq!(
                (location.line, location.column, location.path.as_deref()),
                (9, 11, None)
            );
        }
        other => panic!("expected borrowed array_get, found {other:?}"),
    }
    assert!(matches!(
        instructions[3],
        IRInstruction::IRCall {
            result: None,
            builtin: None,
            source_location: None,
            ..
        }
    ));
    assert!(matches!(
        instructions[4],
        IRInstruction::IRReturn {
            value: None,
            transferred_storage: None
        }
    ));
}

#[test]
fn migration_json_corpus_contains_and_imports_only_the_canonical_module_fixture() {
    let fixture_directory =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/aether/rust_migration/fixtures");
    let mut json_fixtures = fs::read_dir(fixture_directory)
        .expect("migration fixture directory must exist")
        .map(|entry| entry.expect("fixture entry must be readable").path())
        .filter(|path| {
            path.extension()
                .is_some_and(|extension| extension == "json")
        })
        .collect::<Vec<_>>();
    json_fixtures.sort();
    assert_eq!(
        json_fixtures
            .iter()
            .filter_map(|path| path.file_name().and_then(|name| name.to_str()))
            .collect::<Vec<_>>(),
        ["ir_module_v1_golden.json"]
    );

    for fixture in json_fixtures {
        let json = fs::read_to_string(&fixture).expect("module fixture must be UTF-8 text");
        import_module_json(&json).unwrap_or_else(|error| {
            panic!("{} must import end to end: {error}", fixture.display())
        });
    }
}

#[test]
fn failures_are_reported_at_the_json_wire_schema_version_and_import_layers() {
    assert!(matches!(
        import_module_json("{"),
        Err(IRModuleJsonImportError::Json { .. })
    ));
    for document in [
        r#"{"schema_version":1,"functions":[],"structs":[],"extra":true}"#,
        r#"{"schema_version":1,"functions":[]}"#,
        r#"{"schema_version":1,"functions":[{"name":"f","parameters":[],"return_type":{"tag":"void"},"blocks":[{"name":"entry","instructions":[{"kind":"future"}]}]}],"structs":[]}"#,
    ] {
        assert!(matches!(
            import_module_json(document),
            Err(IRModuleJsonImportError::Wire { .. })
        ));
    }
    assert!(matches!(
        import_module_json(r#"{"schema_version":2,"functions":[],"structs":[]}"#),
        Err(IRModuleJsonImportError::SchemaVersion {
            source: IRImportError::UnsupportedSchemaVersion {
                received: 2,
                supported: IR_SCHEMA_VERSION,
            }
        })
    ));
}

#[test]
fn duplicate_keys_are_json_errors_at_root_and_every_nested_object_depth() {
    for document in [
        r#"{"schema_version":1,"schema_version":1,"functions":[],"structs":[]}"#,
        r#"{"schema_version":1,"functions":[],"structs":[{"name":"A","fields":[{"name":"x","name":"y","type":{"tag":"int"}}]}]}"#,
        r#"{"schema_version":1,"functions":[],"structs":[],"extra":{"x":1,"x":2}}"#,
    ] {
        let error = import_module_json(document).expect_err("duplicate key must fail");
        assert!(matches!(error, IRModuleJsonImportError::Json { .. }));
        assert!(
            error
                .to_string()
                .contains("duplicate IR module JSON object key")
        );
        assert!(error.source().is_some());
    }
}

#[test]
fn nonstandard_and_nonfinite_number_spellings_fail_at_the_json_layer() {
    for number in ["NaN", "Infinity", "-Infinity", "1e400"] {
        let document =
            format!(r#"{{"schema_version":1,"functions":[],"structs":[],"number":{number}}}"#);
        assert!(matches!(
            import_module_json(&document),
            Err(IRModuleJsonImportError::Json { .. })
        ));
    }
}

#[test]
fn deeply_nested_structural_failure_retains_the_complete_typed_source_chain() {
    let document = r#"{
        "schema_version": 1,
        "structs": [],
        "functions": [{
            "name": "broken",
            "parameters": [],
            "return_type": {"tag": "void"},
            "blocks": [{
                "name": "entry",
                "instructions": [{
                    "kind": "const",
                    "result": {"tag": "value", "name": "bad", "type": {
                        "tag": "method_result",
                        "receiver": {"tag": "list", "element": {"tag": "int"}},
                        "value": {"tag": "int"}
                    }},
                    "value": {"tag": "int", "value": 0}
                }]
            }]
        }]
    }"#;

    let error = import_module_json(document).expect_err("unrepresentable owned type must fail");
    assert!(matches!(
        error,
        IRModuleJsonImportError::Import {
            source: IRImportError::ModuleFunction { index: 0, .. }
        }
    ));
    assert_eq!(error_chain_len(&error), 7);
    assert!(error.to_string().contains("function 'broken'"));
    assert!(error.to_string().contains("instruction at index 0"));
    assert!(error.to_string().contains("method-result receiver"));
}

#[test]
fn semantically_invalid_but_structurally_representable_module_still_imports() {
    let function =
        r#"{"blocks":[],"name":"duplicate","parameters":[],"return_type":{"tag":"void"}}"#;
    let document =
        format!(r#"{{"functions":[{function},{function}],"schema_version":1,"structs":[]}}"#);

    let module = import_module_json(&document).expect("semantic verification is out of scope");
    assert_eq!(
        module
            .functions
            .iter()
            .map(|function| function.name.as_str())
            .collect::<Vec<_>>(),
        ["duplicate", "duplicate"]
    );
    assert!(
        module
            .functions
            .iter()
            .all(|function| function.blocks.is_empty())
    );
}
