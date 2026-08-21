//! Qualification tests for the owned SSA/schema-v2 codec boundary.

use aether_ir::OwnedSsaModule;
use aether_ir::wire::{SSAModuleV2DTO, SSAWireModuleDTO};
use serde_json::{Value, json};

fn value(name: &str, tag: &str) -> Value {
    json!({"tag":"value", "name":name, "type":{"tag":tag}})
}

fn module(instructions: Vec<Value>, extra_blocks: Vec<Value>) -> Value {
    let mut blocks = vec![json!({"name":"entry", "instructions":instructions})];
    blocks.extend(extra_blocks);
    json!({"schema_version":2, "representation":"aether_ssa", "structs":[],
        "functions":[{"name":"f", "parameters":[], "return_type":{"tag":"void"},
        "entry_block":"entry", "blocks":blocks}]})
}

#[test]
fn minimal_owned_round_trip_is_exact_and_deterministic() {
    let dto: SSAModuleV2DTO = serde_json::from_value(module(vec![], vec![])).unwrap();
    let owned = OwnedSsaModule::from_schema_v2(&dto).unwrap();
    assert_eq!(owned.to_schema_v2(), dto);
    let first = serde_json::to_vec(&owned.to_schema_v2()).unwrap();
    for _ in 0..10 {
        assert_eq!(serde_json::to_vec(&owned.to_schema_v2()).unwrap(), first);
    }
}

#[test]
fn phi_keeps_predecessor_value_associations_and_order() {
    let phi = json!({"kind":"phi", "result":value("r", "int"), "incoming":[
        {"block":"left", "value":value("a", "int")},
        {"block":"right", "value":value("b", "int")} ]});
    let dto: SSAModuleV2DTO = serde_json::from_value(module(
        vec![],
        vec![
            json!({"name":"left", "instructions":[]}),
            json!({"name":"right", "instructions":[]}),
            json!({"name":"merge", "instructions":[phi]}),
        ],
    ))
    .unwrap();
    let owned = OwnedSsaModule::from_schema_v2(&dto).unwrap();
    assert_eq!(owned.to_schema_v2(), dto);
}

#[test]
fn all_bounds_bits_survive_both_values_for_all_eight_kinds() {
    let r = value("r", "int");
    let x = value("x", "int");
    let i = value("i", "int");
    let bases = vec![
        json!({"kind":"array_get","result":r,"array":x,"index":i,"borrowed":false,"borrow_scope":null,"source_location":null}),
        json!({"kind":"array_set","array":x,"index":i,"value":r}),
        json!({"kind":"list_get","result":r,"list_value":x,"index":i,"borrowed":false,"borrow_scope":null,"source_location":null}),
        json!({"kind":"list_set","list_value":x,"index":i,"value":r}),
        json!({"kind":"vector_get","result":r,"vector":x,"index":i}),
        json!({"kind":"vector_set","vector":x,"index":i,"value":r}),
        json!({"kind":"matrix_get","result":r,"matrix":x,"row":i,"column":i,"shape":[4]}),
        json!({"kind":"matrix_set","matrix":x,"row":i,"column":i,"value":r,"shape":[4]}),
    ];
    for checked in [false, true] {
        for base in &bases {
            let mut instruction = base.clone();
            instruction
                .as_object_mut()
                .unwrap()
                .insert("bounds_checked".into(), json!(checked));
            let dto: SSAModuleV2DTO =
                serde_json::from_value(module(vec![instruction], vec![])).unwrap();
            assert_eq!(
                OwnedSsaModule::from_schema_v2(&dto).unwrap().to_schema_v2(),
                dto
            );
        }
    }
}

#[test]
fn rejects_unknown_version_and_dangling_owned_targets_without_panicking() {
    let unknown =
        json!({"schema_version":9,"representation":"aether_ssa","functions":[],"structs":[]});
    assert!(serde_json::from_value::<SSAWireModuleDTO>(unknown).is_err());

    let dto: SSAModuleV2DTO = serde_json::from_value(module(
        vec![json!({"kind":"throw",
        "event":value("e", "exception_event"), "target":"missing", "exceptional_arguments":[]})],
        vec![],
    ))
    .unwrap();
    assert_eq!(
        OwnedSsaModule::from_schema_v2(&dto)
            .unwrap_err()
            .to_string(),
        "functions[0].blocks[0].instructions[0]: control target missing does not name a function block"
    );
}
