//! Differential-contract tests for normalized Initial IR to owned SSA refinement.

use aether_ir::wire::{IRModuleDTO, SSAInstructionDTO, SSAInstructionV2DTO};
use aether_ir::{OwnedSsaModule, lower_normalized_ir_to_ssa_v1};
use aether_verifier::{
    CompilerCore, CompilerPhase, SsaRefinementErrorCategory, SsaRefinementPhase, verify_owned_ssa,
    verify_owned_ssa_refinement,
};
use serde_json::json;

fn value(name: &str, tag: &str) -> serde_json::Value {
    json!({"tag":"value", "name":name, "type":{"tag":tag}})
}

fn parameter(name: &str, tag: &str) -> serde_json::Value {
    json!({"tag":"parameter", "name":name, "type":{"tag":tag}})
}

fn diamond() -> IRModuleDTO {
    serde_json::from_value(json!({
        "schema_version": 1,
        "structs": [],
        "functions": [{
            "name": "choose",
            "parameters": [parameter("cond", "bool")],
            "return_type": {"tag":"int"},
            "may_throw": false,
            "blocks": [
                {"name":"entry", "instructions":[
                    {"kind":"const", "result":value("one", "int"), "value":{"tag":"int", "value":1}},
                    {"kind":"store", "slot":value("x", "int"), "value":value("one", "int")},
                    {"kind":"branch", "condition":parameter("cond", "bool"), "true_target":"then", "false_target":"else"}
                ]},
                {"name":"then", "instructions":[
                    {"kind":"const", "result":value("two", "int"), "value":{"tag":"int", "value":2}},
                    {"kind":"store", "slot":value("x", "int"), "value":value("two", "int")},
                    {"kind":"jump", "target":"merge"}
                ]},
                {"name":"else", "instructions":[
                    {"kind":"jump", "target":"merge"}
                ]},
                {"name":"merge", "instructions":[
                    {"kind":"load", "result":value("loaded", "int"), "slot":value("x", "int")},
                    {"kind":"return", "value":value("loaded", "int"), "transferred_storage":null}
                ]},
                {"name":"dead", "instructions":[
                    {"kind":"return", "value":value("one", "int"), "transferred_storage":null}
                ]}
            ]
        }]
    }))
    .expect("valid normalized diamond")
}

fn lowered() -> OwnedSsaModule {
    lower_normalized_ir_to_ssa_v1(&diamond()).expect("diamond lowers")
}

fn mutate_schema(
    module: &OwnedSsaModule,
    mutation: impl FnOnce(&mut aether_ir::wire::SSAModuleV2DTO),
) -> OwnedSsaModule {
    let mut dto = module.to_schema_v2();
    mutation(&mut dto);
    OwnedSsaModule::from_schema_v2(&dto).expect("mutation remains valid schema-v2")
}

#[test]
fn accepts_owned_lowering_with_phi_promotion_and_unreachable_elimination() {
    let initial = diamond();
    let ssa = lower_normalized_ir_to_ssa_v1(&initial).unwrap();

    verify_owned_ssa(&ssa).unwrap();
    verify_owned_ssa_refinement(&initial, &ssa).unwrap();
    assert_eq!(
        ssa.functions[0]
            .blocks
            .iter()
            .map(|block| block.id.as_str())
            .collect::<Vec<_>>(),
        vec!["entry", "then", "else", "merge"]
    );
}

#[test]
fn rejects_semantically_changed_constant_which_remains_well_formed_ssa() {
    let initial = diamond();
    let corrupted = mutate_schema(&lowered(), |dto| {
        let SSAInstructionV2DTO::Unchanged(SSAInstructionDTO::Ordinary(
            aether_ir::wire::IRInstructionDTO::Const { value, .. },
        )) = &mut dto.functions[0].blocks[0].instructions[0]
        else {
            panic!("expected entry const")
        };
        *value = serde_json::from_value(json!({"tag":"int", "value":42})).unwrap();
    });

    verify_owned_ssa(&corrupted).unwrap();
    let error = verify_owned_ssa_refinement(&initial, &corrupted).unwrap_err();
    assert_eq!(error.category, SsaRefinementErrorCategory::Instruction);
    assert_eq!(error.phase, SsaRefinementPhase::SemanticPreservation);
    assert_eq!(error.function.as_deref(), Some("choose"));
    assert_eq!(error.block.as_deref(), Some("entry"));
    assert_eq!(error.instruction_index, Some(0));
}

#[test]
fn rejects_well_formed_phi_with_wrong_reaching_value() {
    let initial = diamond();
    let corrupted = mutate_schema(&lowered(), |dto| {
        let SSAInstructionV2DTO::Unchanged(SSAInstructionDTO::Control(
            aether_ir::wire::SSAControlInstructionDTO::Phi { incoming, .. },
        )) = &mut dto.functions[0].blocks[3].instructions[0]
        else {
            panic!("expected merge phi")
        };
        let then = incoming
            .iter_mut()
            .find(|item| item.block == "then")
            .expect("then incoming");
        then.value = serde_json::from_value(value("one", "int")).unwrap();
    });

    verify_owned_ssa(&corrupted).unwrap();
    let error = verify_owned_ssa_refinement(&initial, &corrupted).unwrap_err();
    assert_eq!(error.category, SsaRefinementErrorCategory::Phi);
    assert_eq!(error.phase, SsaRefinementPhase::PhiVerification);
    assert_eq!(error.block.as_deref(), Some("merge"));
}

#[test]
fn accepts_consistent_alpha_renaming_of_preserved_definition() {
    let initial = diamond();
    let renamed = mutate_schema(&lowered(), |dto| {
        let SSAInstructionV2DTO::Unchanged(SSAInstructionDTO::Ordinary(
            aether_ir::wire::IRInstructionDTO::Const { result, .. },
        )) = &mut dto.functions[0].blocks[0].instructions[0]
        else {
            panic!("expected entry const")
        };
        let aether_ir::wire::IRValueDTO::Value { name, .. } = result else {
            panic!("expected SSA value")
        };
        *name = "alpha.one".into();

        let SSAInstructionV2DTO::Unchanged(SSAInstructionDTO::Control(
            aether_ir::wire::SSAControlInstructionDTO::Phi { incoming, .. },
        )) = &mut dto.functions[0].blocks[3].instructions[0]
        else {
            panic!("expected merge phi")
        };
        let item = incoming
            .iter_mut()
            .find(|item| item.block == "else")
            .expect("else incoming");
        let aether_ir::wire::IRValueDTO::Value { name, .. } = &mut item.value else {
            panic!("expected SSA value")
        };
        *name = "alpha.one".into();
    });

    verify_owned_ssa(&renamed).unwrap();
    verify_owned_ssa_refinement(&initial, &renamed).unwrap();
}

#[test]
fn rejects_disabled_bounds_check_even_when_owned_ssa_verifier_accepts_it() {
    let initial: IRModuleDTO = serde_json::from_value(json!({
        "schema_version":1, "structs":[], "functions":[{
            "name":"get", "parameters":[
                {"tag":"parameter", "name":"items", "type":{"tag":"array", "element":{"tag":"int"}}},
                parameter("index", "int")
            ], "return_type":{"tag":"int"}, "blocks":[{
                "name":"entry", "instructions":[
                    {"kind":"array_get", "result":value("item", "int"),
                     "array":{"tag":"parameter", "name":"items", "type":{"tag":"array", "element":{"tag":"int"}}},
                     "index":parameter("index", "int"), "borrowed":false,
                     "borrow_scope":null, "source_location":{"tag":"source_location", "line":7, "column":11, "path":"bounds.ae"}},
                    {"kind":"return", "value":value("item", "int"), "transferred_storage":null}
                ]
            }], "may_throw":false
        }]
    }))
    .unwrap();
    let valid = lower_normalized_ir_to_ssa_v1(&initial).unwrap();
    let corrupted = mutate_schema(&valid, |dto| {
        let SSAInstructionV2DTO::BoundsChecked(
            aether_ir::wire::SSABoundsCheckedInstructionV2DTO::ArrayGet { bounds_checked, .. },
        ) = &mut dto.functions[0].blocks[0].instructions[0]
        else {
            panic!("expected checked array_get")
        };
        *bounds_checked = false;
    });
    verify_owned_ssa(&corrupted).unwrap();
    let error = verify_owned_ssa_refinement(&initial, &corrupted).unwrap_err();
    assert_eq!(error.category, SsaRefinementErrorCategory::Instruction);
    assert_eq!(error.source_location.as_ref().unwrap().line, 7);
}

#[test]
fn rejects_function_identity_and_reachable_cfg_corruption() {
    let initial = diamond();
    let renamed = mutate_schema(&lowered(), |dto| {
        dto.functions[0].name = "other".into();
    });
    let error = verify_owned_ssa_refinement(&initial, &renamed).unwrap_err();
    assert_eq!(error.category, SsaRefinementErrorCategory::Metadata);
    assert_eq!(error.phase, SsaRefinementPhase::FunctionMetadata);

    let reordered = mutate_schema(&lowered(), |dto| {
        dto.functions[0].blocks.swap(1, 2);
    });
    let error = verify_owned_ssa_refinement(&initial, &reordered).unwrap_err();
    assert_eq!(error.category, SsaRefinementErrorCategory::ControlFlow);
}

#[test]
fn compiler_session_runs_refinement_before_export() {
    let mut session = CompilerCore.accept_initial_ir(diamond());
    session.lower_ssa().unwrap();
    let exported = session.export_ssa_schema_v2().unwrap();
    assert_eq!(exported.schema_version, 2);

    let error = CompilerCore
        .lower_verified_ssa(
            serde_json::from_value(json!({
                "schema_version":1,
                "structs":[],
                "functions":[{
                    "name":"bad", "parameters":[], "return_type":{"tag":"void"},
                    "blocks":[], "may_throw":false
                }]
            }))
            .unwrap(),
        )
        .unwrap_err();
    assert!(matches!(
        error.phase,
        CompilerPhase::LifecycleNormalization | CompilerPhase::SsaLowering
    ));
}

#[test]
fn deep_cfg_verification_is_iterative() {
    let blocks = (0..5_000)
        .map(|index| {
            if index == 4_999 {
                json!({"name":format!("b{index}"), "instructions":[
                    {"kind":"return", "value":null, "transferred_storage":null}
                ]})
            } else {
                json!({"name":format!("b{index}"), "instructions":[
                    {"kind":"jump", "target":format!("b{}", index + 1)}
                ]})
            }
        })
        .collect::<Vec<_>>();
    let initial: IRModuleDTO = serde_json::from_value(json!({
        "schema_version":1, "structs":[], "functions":[{
            "name":"deep", "parameters":[], "return_type":{"tag":"void"},
            "blocks":blocks, "may_throw":false
        }]
    }))
    .unwrap();
    let ssa = lower_normalized_ir_to_ssa_v1(&initial).unwrap();
    verify_owned_ssa_refinement(&initial, &ssa).unwrap();
}
