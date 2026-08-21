//! Strict value-based SSA wire DTO coverage.

use aether_ir::wire::{
    SSAControlInstructionDTO, SSAInstructionDTO, SSAModuleDTO, SSAWireModuleDTO,
};
use serde_json::json;

fn value(name: &str, tag: &str) -> serde_json::Value {
    json!({"tag": "value", "name": name, "type": {"tag": tag}})
}

#[test]
fn imports_and_round_trips_exceptional_ssa_edges() {
    let document = json!({
        "schema_version": 1,
        "representation": "aether_ssa",
        "functions": [{
            "name": "main",
            "parameters": [],
            "return_type": {"tag": "void"},
            "entry_block": "entry",
            "may_throw": true,
            "blocks": [
                {
                    "name": "entry",
                    "instructions": [{
                        "kind": "invoke",
                        "function": "fail",
                        "arguments": [],
                        "result": null,
                        "exception": value("event", "exception_event"),
                        "normal_target": "normal",
                        "exceptional_target": "handler",
                        "builtin": null,
                        "source_location": null,
                        "normal_arguments": [],
                        "exceptional_arguments": [
                            value("event", "exception_event")
                        ]
                    }]
                },
                {
                    "name": "normal",
                    "instructions": [{
                        "kind": "return",
                        "value": null,
                        "transferred_storage": null
                    }]
                },
                {
                    "name": "handler",
                    "instructions": [
                        {
                            "kind": "catch_entry",
                            "event": value("caught", "exception_event"),
                            "handler_id": "root",
                            "catch_types": []
                        },
                        {
                            "kind": "propagate",
                            "event": value("caught", "exception_event"),
                            "target": null,
                            "exceptional_arguments": []
                        }
                    ]
                }
            ]
        }],
        "structs": []
    });

    let module: SSAModuleDTO = serde_json::from_value(document).unwrap();
    assert!(matches!(
        module.functions[0].blocks[0].instructions[0],
        SSAInstructionDTO::Control(SSAControlInstructionDTO::Invoke { .. })
    ));
    let encoded = serde_json::to_value(&module).unwrap();
    let decoded: SSAModuleDTO = serde_json::from_value(encoded).unwrap();
    assert_eq!(decoded, module);
}

#[test]
fn rejects_initial_ir_invoke_shape_at_ssa_boundary() {
    let instruction = json!({
        "kind": "invoke",
        "function": "fail",
        "arguments": [],
        "result": null,
        "exception": value("event", "exception_event"),
        "normal_target": "normal",
        "exceptional_target": "handler",
        "exceptional_target_event": value("caught", "exception_event"),
        "builtin": null,
        "source_location": null
    });
    assert!(serde_json::from_value::<SSAInstructionDTO>(instruction).is_err());
}

#[test]
fn rejects_initial_ir_storage_and_call_effect_shapes_at_ssa_boundary() {
    let storage_result = json!({
        "kind": "const",
        "result": {
            "tag": "storage",
            "name": "slot",
            "type": {"tag": "int"}
        },
        "value": {"tag": "int", "value": 1}
    });
    assert!(serde_json::from_value::<SSAInstructionDTO>(storage_result).is_err());

    let initial_ir_call = json!({
        "kind": "call",
        "function": "fail",
        "arguments": [],
        "result": null,
        "builtin": null,
        "source_location": null,
        "may_throw": true
    });
    assert!(serde_json::from_value::<SSAInstructionDTO>(initial_ir_call).is_err());
}

fn v2_document(instruction: serde_json::Value) -> serde_json::Value {
    json!({
        "schema_version": 2, "representation": "aether_ssa", "structs": [],
        "functions": [{"name": "f", "parameters": [], "return_type": {"tag": "void"},
            "entry_block": "entry", "blocks": [{"name": "entry", "instructions": [instruction]}]}]
    })
}

#[test]
fn explicitly_dispatches_v1_and_v2_and_rejects_unknown_versions() {
    let v1 = json!({"schema_version": 1, "representation": "aether_ssa", "functions": [], "structs": []});
    assert!(matches!(
        serde_json::from_value::<SSAWireModuleDTO>(v1).unwrap(),
        SSAWireModuleDTO::V1(_)
    ));
    let v2 = json!({"schema_version": 2, "representation": "aether_ssa", "functions": [], "structs": []});
    assert!(matches!(
        serde_json::from_value::<SSAWireModuleDTO>(v2).unwrap(),
        SSAWireModuleDTO::V2(_)
    ));
    let unknown = json!({"schema_version": 3, "representation": "aether_ssa", "functions": [], "structs": []});
    assert!(serde_json::from_value::<SSAWireModuleDTO>(unknown).is_err());
}

#[test]
fn schema_v2_requires_bounds_checked_on_all_eight_shapes() {
    let r = value("r", "int");
    let x = value("x", "int");
    let i = value("i", "int");
    let instructions = vec![
        json!({"kind":"array_get","result":r,"array":x,"index":i,"borrowed":false,"borrow_scope":null,"source_location":null}),
        json!({"kind":"array_set","array":x,"index":i,"value":r}),
        json!({"kind":"list_get","result":r,"list_value":x,"index":i,"borrowed":false,"borrow_scope":null,"source_location":null}),
        json!({"kind":"list_set","list_value":x,"index":i,"value":r}),
        json!({"kind":"vector_get","result":r,"vector":x,"index":i}),
        json!({"kind":"vector_set","vector":x,"index":i,"value":r}),
        json!({"kind":"matrix_get","result":r,"matrix":x,"row":i,"column":i,"shape":[4]}),
        json!({"kind":"matrix_set","matrix":x,"row":i,"column":i,"value":r,"shape":[4]}),
    ];
    for instruction in instructions {
        assert!(
            serde_json::from_value::<SSAWireModuleDTO>(v2_document(instruction.clone())).is_err()
        );
        for checked in [false, true] {
            let mut complete = instruction.clone();
            complete
                .as_object_mut()
                .unwrap()
                .insert("bounds_checked".into(), json!(checked));
            let module: SSAWireModuleDTO = serde_json::from_value(v2_document(complete)).unwrap();
            let encoded = serde_json::to_value(&module).unwrap();
            let decoded: SSAWireModuleDTO = serde_json::from_value(encoded).unwrap();
            assert_eq!(decoded, module);
        }
    }
}
