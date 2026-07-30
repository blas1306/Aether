//! Value-based SSA exceptional-edge and ownership verification.

use aether_ir::wire::SSAModuleDTO;
use aether_verifier::verify_ssa_module_dto;
use serde_json::{Value, json};

fn event(name: &str) -> Value {
    json!({"tag": "value", "name": name, "type": {"tag": "exception_event"}})
}

fn string_value(name: &str) -> Value {
    json!({"tag": "parameter", "name": name, "type": {"tag": "string"}})
}

fn module_with_cleanup(include_old_event_destroy: bool) -> SSAModuleDTO {
    let mut cleanup = vec![json!({
        "kind": "catch_entry",
        "event": event("new_caught"),
        "handler_id": "cleanup",
        "catch_types": []
    })];
    if include_old_event_destroy {
        cleanup.push(json!({
            "kind": "exception_destroy",
            "event": event("old_caught")
        }));
    }
    cleanup.push(json!({
        "kind": "propagate",
        "event": event("new_caught"),
        "target": null,
        "exceptional_arguments": []
    }));

    serde_json::from_value(json!({
        "schema_version": 1,
        "representation": "aether_ssa",
        "functions": [{
            "name": "main",
            "parameters": [{
                "tag": "parameter",
                "name": "payload",
                "type": {"tag": "string"}
            }],
            "return_type": {"tag": "void"},
            "entry_block": "entry",
            "may_throw": true,
            "blocks": [
                {
                    "name": "entry",
                    "instructions": [
                        {
                            "kind": "exception_pack",
                            "result": event("old"),
                            "payload": string_value("payload"),
                            "dynamic_type": "FileError",
                            "source_location": null
                        },
                        {
                            "kind": "throw",
                            "event": event("old"),
                            "target": "handler",
                            "exceptional_arguments": [event("old")]
                        }
                    ]
                },
                {
                    "name": "handler",
                    "instructions": [
                        {
                            "kind": "catch_entry",
                            "event": event("old_caught"),
                            "handler_id": "handler",
                            "catch_types": ["FileError"]
                        },
                        {
                            "kind": "invoke",
                            "function": "unknown_throwing_function",
                            "arguments": [],
                            "result": null,
                            "exception": event("new"),
                            "normal_target": "normal",
                            "exceptional_target": "cleanup",
                            "builtin": null,
                            "source_location": null,
                            "normal_arguments": [],
                            "exceptional_arguments": [event("new")]
                        }
                    ]
                },
                {
                    "name": "normal",
                    "instructions": [
                        {
                            "kind": "exception_destroy",
                            "event": event("old_caught")
                        },
                        {
                            "kind": "return",
                            "value": null,
                            "transferred_storage": null
                        }
                    ]
                },
                {
                    "name": "cleanup",
                    "instructions": cleanup
                }
            ]
        }],
        "structs": []
    }))
    .unwrap()
}

#[test]
fn accepts_invoke_cleanup_that_consumes_the_old_caught_event() {
    assert_eq!(verify_ssa_module_dto(&module_with_cleanup(true)), Ok(()));
}

#[test]
fn rejects_new_propagation_that_leaks_the_old_caught_event() {
    let error = verify_ssa_module_dto(&module_with_cleanup(false))
        .expect_err("the previous caught event remains owned");
    assert!(error.detail.contains("leaks another owned event"));
}

#[test]
fn rejects_invoke_with_missing_exceptional_successor_argument() {
    let mut module = module_with_cleanup(true);
    let instruction = &mut module.functions[0].blocks[1].instructions[1];
    let aether_ir::wire::SSAInstructionDTO::Control(
        aether_ir::wire::SSAControlInstructionDTO::Invoke {
            exceptional_arguments,
            ..
        },
    ) = instruction
    else {
        unreachable!()
    };
    exceptional_arguments.clear();

    let error =
        verify_ssa_module_dto(&module).expect_err("invoke must move its edge-defined event");
    assert!(error.detail.contains("exceptional edge"));
}
