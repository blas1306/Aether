//! Owned SSA compatibility for the authoritative value-based verifier.

use aether_ir::OwnedSsaModule;
use aether_ir::wire::SSAWireModuleDTO;
use aether_verifier::verify_owned_ssa;
use serde_json::{Value, json};

fn value(name: &str, tag: &str) -> Value {
    json!({"tag":"value", "name":name, "type":{"tag":tag}})
}

fn owned(instructions: Vec<Value>, blocks: Vec<Value>) -> OwnedSsaModule {
    let mut all_blocks = vec![json!({"name":"entry", "instructions":instructions})];
    all_blocks.extend(blocks);
    let wire: SSAWireModuleDTO = serde_json::from_value(json!({
        "schema_version":2, "representation":"aether_ssa", "structs":[],
        "functions":[{"name":"f", "parameters":[], "return_type":{"tag":"void"},
            "entry_block":"entry", "blocks":all_blocks}]
    }))
    .unwrap();
    let SSAWireModuleDTO::V2(dto) = wire else {
        unreachable!()
    };
    OwnedSsaModule::from_schema_v2(&dto).unwrap()
}

#[test]
fn accepts_both_bounds_states_for_all_eight_instruction_shapes() {
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
            let module = owned(
                vec![
                    instruction,
                    json!({"kind":"return","value":null,"transferred_storage":null}),
                ],
                vec![],
            );
            assert_eq!(verify_owned_ssa(&module), Ok(()));
            assert_eq!(
                module.to_schema_v2().functions[0].blocks[0]
                    .instructions
                    .len(),
                2
            );
        }
    }
}

#[test]
fn rejects_malformed_phi_with_the_historical_diagnostic() {
    let module = owned(
        vec![json!({"kind":"jump","target":"merge"})],
        vec![json!({"name":"merge","instructions":[
            {"kind":"phi","result":value("r", "int"),"incoming":[]},
            {"kind":"return","value":null,"transferred_storage":null}
        ]})],
    );
    let error = verify_owned_ssa(&module).unwrap_err();
    assert_eq!(error.function_name, "f");
    assert_eq!(error.block_name.as_deref(), Some("merge"));
    assert_eq!(
        error.detail,
        "phi must have exactly one incoming value per predecessor"
    );
}
