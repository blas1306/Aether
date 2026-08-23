//! Behavioral coverage for lowering policy v1.

use aether_ir::wire::IRModuleDTO;
use aether_ir::{characterize_lower_normalized_ir_to_ssa_v1, lower_normalized_ir_to_ssa_v1};
use serde_json::{Value, json};

fn typed(tag: &str, name: &str, ty: Value) -> Value {
    json!({"tag": tag, "name": name, "type": ty})
}

#[test]
fn all_eight_initial_ir_accesses_explicitly_synthesize_checked_bounds() {
    let int = json!({"tag":"int"});
    let array_ty = json!({"tag":"array", "element":int});
    let list_ty = json!({"tag":"list", "element":int});
    let vector_ty = json!({"tag":"vector", "element":int, "orientation":"row"});
    let matrix_ty = json!({"tag":"matrix", "element":int});
    let parameter = |name: &str, ty: Value| typed("parameter", name, ty);
    let operand = |name: &str, ty: Value| typed("parameter", name, ty);
    let result = |name: &str| typed("value", name, int.clone());

    let module: IRModuleDTO = serde_json::from_value(json!({
        "schema_version": 1,
        "structs": [],
        "functions": [{
            "name":"accesses",
            "parameters":[
                parameter("a", array_ty.clone()), parameter("l", list_ty.clone()),
                parameter("v", vector_ty.clone()), parameter("m", matrix_ty.clone()),
                parameter("i", int.clone()), parameter("x", int.clone())
            ],
            "return_type":{"tag":"void"}, "blocks":[{"name":"entry", "instructions":[
                {"kind":"array_get", "result":result("ag"), "array":operand("a",array_ty.clone()), "index":operand("i",int.clone()), "borrowed":false, "borrow_scope":null, "source_location":null},
                {"kind":"array_set", "array":operand("a",array_ty.clone()), "index":operand("i",int.clone()), "value":operand("x",int.clone())},
                {"kind":"list_get", "result":result("lg"), "list_value":operand("l",list_ty.clone()), "index":operand("i",int.clone()), "borrowed":false, "borrow_scope":null, "source_location":null},
                {"kind":"list_set", "list_value":operand("l",list_ty.clone()), "index":operand("i",int.clone()), "value":operand("x",int.clone())},
                {"kind":"vector_get", "result":result("vg"), "vector":operand("v",vector_ty.clone()), "index":operand("i",int.clone())},
                {"kind":"vector_set", "vector":operand("v",vector_ty), "index":operand("i",int.clone()), "value":operand("x",int.clone())},
                {"kind":"matrix_get", "result":result("mg"), "matrix":operand("m",matrix_ty.clone()), "row":operand("i",int.clone()), "column":operand("i",int.clone()), "shape":[4]},
                {"kind":"matrix_set", "matrix":operand("m",matrix_ty), "row":operand("i",int.clone()), "column":operand("i",int.clone()), "value":operand("x",int), "shape":[4]},
                {"kind":"return", "value":null, "transferred_storage":null}
            ]}], "may_throw":false
        }]
    })).expect("valid Initial IR DTO");

    let lowered = lower_normalized_ir_to_ssa_v1(&module)
        .expect("lowering succeeds")
        .to_schema_v2();
    let value = serde_json::to_value(lowered).expect("serialize SSA");
    let instructions = value["functions"][0]["blocks"][0]["instructions"]
        .as_array()
        .unwrap();
    let accesses = instructions
        .iter()
        .filter(|instruction| instruction.get("bounds_checked").is_some())
        .collect::<Vec<_>>();
    assert_eq!(accesses.len(), 8);
    assert!(
        accesses
            .iter()
            .all(|instruction| instruction["bounds_checked"] == true)
    );
}

#[test]
fn lowering_places_and_renames_a_merge_phi_deterministically() {
    let module: IRModuleDTO = serde_json::from_value(json!({
        "schema_version":1, "structs":[], "functions":[{
            "name":"merge", "parameters":[{"tag":"parameter","name":"c","type":{"tag":"bool"}}],
            "return_type":{"tag":"int"}, "may_throw":false,
            "blocks":[
                {"name":"entry","instructions":[{"kind":"branch","condition":{"tag":"parameter","name":"c","type":{"tag":"bool"}},"true_target":"left","false_target":"right"}]},
                {"name":"left","instructions":[{"kind":"const","result":{"tag":"value","name":"one","type":{"tag":"int"}},"value":{"tag":"int","value":1}},{"kind":"store","slot":{"tag":"value","name":"s","type":{"tag":"int"}},"value":{"tag":"value","name":"one","type":{"tag":"int"}}},{"kind":"jump","target":"join"}]},
                {"name":"right","instructions":[{"kind":"const","result":{"tag":"value","name":"two","type":{"tag":"int"}},"value":{"tag":"int","value":2}},{"kind":"store","slot":{"tag":"value","name":"s","type":{"tag":"int"}},"value":{"tag":"value","name":"two","type":{"tag":"int"}}},{"kind":"jump","target":"join"}]},
                {"name":"join","instructions":[{"kind":"load","result":{"tag":"value","name":"answer","type":{"tag":"int"}},"slot":{"tag":"value","name":"s","type":{"tag":"int"}}},{"kind":"return","value":{"tag":"value","name":"answer","type":{"tag":"int"}},"transferred_storage":null}]}
            ]
        }]
    })).unwrap();
    let first = lower_normalized_ir_to_ssa_v1(&module)
        .unwrap()
        .to_schema_v2();
    let second = lower_normalized_ir_to_ssa_v1(&module)
        .unwrap()
        .to_schema_v2();
    assert_eq!(first, second);
    let value = serde_json::to_value(first).unwrap();
    let join = &value["functions"][0]["blocks"][3]["instructions"];
    assert_eq!(join[0]["kind"], "phi");
    assert_eq!(join[0]["result"]["name"], "answer");
    assert_eq!(join[0]["incoming"].as_array().unwrap().len(), 2);
    assert_eq!(join[1]["value"]["name"], "answer");
}

#[test]
fn diagnostic_characterization_preserves_exact_lowering_result() {
    let module: IRModuleDTO = serde_json::from_value(json!({
        "schema_version":1, "structs":[], "functions":[{
            "name":"diagnostic", "parameters":[], "return_type":{"tag":"void"},
            "may_throw":false, "blocks":[
                {"name":"entry","instructions":[{"kind":"jump","target":"exit"}]},
                {"name":"exit","instructions":[{"kind":"return","value":null,"transferred_storage":null}]}
            ]
        }]
    }))
    .unwrap();
    let ordinary = lower_normalized_ir_to_ssa_v1(&module).expect("ordinary lowering");
    let (characterized, timings) =
        characterize_lower_normalized_ir_to_ssa_v1(&module).expect("characterized lowering");

    assert_eq!(characterized, ordinary);
    assert!(timings.measured_ns() > 0);
    assert!(timings.cfg_construction_ns > 0);
    assert!(timings.reachability_and_rpo_ns > 0);
    assert!(timings.chk_idom_ns > 0);
    assert!(timings.renaming_ns > 0);
}

#[test]
fn lifecycle_input_fails_closed_instead_of_partially_lowering() {
    let module: IRModuleDTO = serde_json::from_value(json!({
        "schema_version":1, "structs":[], "functions":[{"name":"f","parameters":[],"return_type":{"tag":"void"},"blocks":[{"name":"entry","instructions":[{"kind":"destroy","value":{"tag":"storage","name":"s","type":{"tag":"string"}},"source_location":null},{"kind":"return","value":null,"transferred_storage":null}]}],"may_throw":false}]
    })).unwrap();
    let error = lower_normalized_ir_to_ssa_v1(&module)
        .unwrap_err()
        .to_string();
    assert!(error.contains("lifecycle normalization must run"));
}

#[test]
fn loop_carried_phi_has_exact_predecessor_labels_and_is_deterministic() {
    let module: IRModuleDTO = serde_json::from_value(json!({
        "schema_version":1, "structs":[], "functions":[{
            "name":"loop_phi", "parameters":[{"tag":"parameter","name":"again","type":{"tag":"bool"}}],
            "return_type":{"tag":"int"}, "may_throw":false,
            "blocks":[
                {"name":"entry","instructions":[
                    {"kind":"const","result":{"tag":"value","name":"zero","type":{"tag":"int"}},"value":{"tag":"int","value":0}},
                    {"kind":"store","slot":{"tag":"value","name":"s","type":{"tag":"int"}},"value":{"tag":"value","name":"zero","type":{"tag":"int"}}},
                    {"kind":"jump","target":"header"}]},
                {"name":"header","instructions":[
                    {"kind":"load","result":{"tag":"value","name":"current","type":{"tag":"int"}},"slot":{"tag":"value","name":"s","type":{"tag":"int"}}},
                    {"kind":"branch","condition":{"tag":"parameter","name":"again","type":{"tag":"bool"}},"true_target":"body","false_target":"exit"}]},
                {"name":"body","instructions":[
                    {"kind":"const","result":{"tag":"value","name":"next","type":{"tag":"int"}},"value":{"tag":"int","value":1}},
                    {"kind":"store","slot":{"tag":"value","name":"s","type":{"tag":"int"}},"value":{"tag":"value","name":"next","type":{"tag":"int"}}},
                    {"kind":"jump","target":"header"}]},
                {"name":"exit","instructions":[
                    {"kind":"load","result":{"tag":"value","name":"answer","type":{"tag":"int"}},"slot":{"tag":"value","name":"s","type":{"tag":"int"}}},
                    {"kind":"return","value":{"tag":"value","name":"answer","type":{"tag":"int"}},"transferred_storage":null}]}
            ]
        }]
    })).unwrap();
    let first = lower_normalized_ir_to_ssa_v1(&module)
        .unwrap()
        .to_schema_v2();
    let second = lower_normalized_ir_to_ssa_v1(&module)
        .unwrap()
        .to_schema_v2();
    assert_eq!(first, second);
    let value = serde_json::to_value(first).unwrap();
    let header = value["functions"][0]["blocks"]
        .as_array()
        .unwrap()
        .iter()
        .find(|block| block["name"] == "header")
        .unwrap();
    let phi = &header["instructions"][0];
    assert_eq!(phi["kind"], "phi");
    assert_eq!(phi["result"]["name"], "current");
    let incoming = phi["incoming"].as_array().unwrap();
    assert_eq!(incoming.len(), 2);
    assert_eq!(incoming[0]["block"], "entry");
    assert_eq!(incoming[0]["value"]["name"], "zero");
    assert_eq!(incoming[1]["block"], "body");
    assert_eq!(incoming[1]["value"]["name"], "next");
}

#[test]
fn dead_slot_and_unreachable_definition_do_not_place_reachable_phis() {
    let module: IRModuleDTO = serde_json::from_value(json!({
        "schema_version":1, "structs":[], "functions":[{
            "name":"pruned", "parameters":[{"tag":"parameter","name":"c","type":{"tag":"bool"}}],
            "return_type":{"tag":"void"}, "may_throw":false,
            "blocks":[
                {"name":"entry","instructions":[{"kind":"branch","condition":{"tag":"parameter","name":"c","type":{"tag":"bool"}},"true_target":"left","false_target":"right"}]},
                {"name":"dead","instructions":[
                    {"kind":"const","result":{"tag":"value","name":"dead_value","type":{"tag":"int"}},"value":{"tag":"int","value":9}},
                    {"kind":"store","slot":{"tag":"value","name":"s","type":{"tag":"int"}},"value":{"tag":"value","name":"dead_value","type":{"tag":"int"}}},
                    {"kind":"jump","target":"join"}]},
                {"name":"left","instructions":[
                    {"kind":"const","result":{"tag":"value","name":"one","type":{"tag":"int"}},"value":{"tag":"int","value":1}},
                    {"kind":"store","slot":{"tag":"value","name":"unused","type":{"tag":"int"}},"value":{"tag":"value","name":"one","type":{"tag":"int"}}},
                    {"kind":"jump","target":"join"}]},
                {"name":"right","instructions":[
                    {"kind":"const","result":{"tag":"value","name":"two","type":{"tag":"int"}},"value":{"tag":"int","value":2}},
                    {"kind":"jump","target":"join"}]},
                {"name":"join","instructions":[{"kind":"return","value":null,"transferred_storage":null}]}
            ]
        }]
    })).unwrap();
    let value = serde_json::to_value(
        lower_normalized_ir_to_ssa_v1(&module)
            .unwrap()
            .to_schema_v2(),
    )
    .unwrap();
    let blocks = value["functions"][0]["blocks"].as_array().unwrap();
    assert!(blocks.iter().all(|block| block["name"] != "dead"));
    let join = blocks.iter().find(|block| block["name"] == "join").unwrap();
    assert!(
        join["instructions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|instruction| instruction["kind"] != "phi")
    );
}
