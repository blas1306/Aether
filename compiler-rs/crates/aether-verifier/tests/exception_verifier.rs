//! Exception-bearing Initial IR verifier contracts.

use aether_ir::{
    BoolType, ExceptionEventType, IRBasicBlock, IRFunction, IRInstruction, IRModule, IRParameter,
    IRStructDefinition, IRValue, StructType, VoidType,
};
use aether_verifier::verify_module;

fn event(name: &str) -> IRValue {
    IRValue::new(name, ExceptionEventType.into())
}

fn error_type() -> StructType {
    StructType {
        name: "FileError".to_owned(),
    }
}

fn throwing_function() -> IRFunction {
    let payload = IRParameter::new("payload", error_type().into());
    let packed = event("packed");
    IRFunction {
        name: "fail".to_owned(),
        parameters: vec![payload.clone()],
        return_type: VoidType.into(),
        blocks: vec![IRBasicBlock {
            name: "entry".to_owned(),
            instructions: vec![
                IRInstruction::IRPackException {
                    result: packed.clone(),
                    payload: payload.into(),
                    dynamic_type: Some("FileError".to_owned()),
                    source_location: None,
                },
                IRInstruction::IRThrow {
                    event: packed,
                    target: None,
                    target_event: None,
                },
            ],
        }],
        may_throw: true,
    }
}

fn invoking_function(normal_target: &str, exceptional_target: &str) -> IRFunction {
    let payload = IRParameter::new("payload", error_type().into());
    let invoke_event = event("invoke_event");
    let handler_event = event("handler_event");
    IRFunction {
        name: "main".to_owned(),
        parameters: vec![payload.clone()],
        return_type: VoidType.into(),
        blocks: vec![
            IRBasicBlock {
                name: "entry".to_owned(),
                instructions: vec![IRInstruction::IRInvoke {
                    function: "fail".to_owned(),
                    arguments: vec![payload.into()],
                    result: None,
                    exception: invoke_event,
                    normal_target: normal_target.to_owned(),
                    exceptional_target: exceptional_target.to_owned(),
                    exceptional_target_event: handler_event.clone(),
                    builtin: None,
                    source_location: None,
                }],
            },
            IRBasicBlock {
                name: "normal".to_owned(),
                instructions: vec![IRInstruction::IRReturn {
                    value: None,
                    transferred_storage: None,
                }],
            },
            IRBasicBlock {
                name: "handler".to_owned(),
                instructions: vec![
                    IRInstruction::IRCatchEntry {
                        event: handler_event.clone(),
                        handler_id: "handler0".to_owned(),
                        catch_types: vec!["FileError".to_owned()],
                    },
                    IRInstruction::IRExceptionDestroy {
                        event: handler_event,
                    },
                    IRInstruction::IRReturn {
                        value: None,
                        transferred_storage: None,
                    },
                ],
            },
        ],
        may_throw: true,
    }
}

fn module(main: IRFunction) -> IRModule {
    IRModule {
        functions: vec![throwing_function(), main],
        structs: vec![IRStructDefinition {
            name: "FileError".to_owned(),
            fields: vec![],
        }],
    }
}

#[test]
fn accepts_explicit_invoke_handler_and_owned_event_flow() {
    assert_eq!(
        verify_module(&module(invoking_function("normal", "handler"))),
        Ok(())
    );
}

#[test]
fn rejects_aliased_normal_and_exceptional_successors() {
    let error = verify_module(&module(invoking_function("handler", "handler")))
        .expect_err("invoke successors must remain mutually exclusive");
    assert_eq!(error.invariant_id(), Some("IRV-136"));
}

#[test]
fn rejects_non_event_invoke_results() {
    let mut main = invoking_function("normal", "handler");
    let IRInstruction::IRInvoke { exception, .. } = &mut main.blocks[0].instructions[0] else {
        unreachable!()
    };
    *exception = IRValue::new("not_event", BoolType.into());

    let error = verify_module(&module(main)).expect_err("invoke event must be opaque");
    assert_eq!(error.invariant_id(), Some("IRV-052"));
}

#[test]
fn rejects_ordinary_call_to_may_throw_function() {
    let payload = IRParameter::new("payload", error_type().into());
    let main = IRFunction {
        name: "main".to_owned(),
        parameters: vec![payload.clone()],
        return_type: VoidType.into(),
        blocks: vec![IRBasicBlock {
            name: "entry".to_owned(),
            instructions: vec![
                IRInstruction::IRCall {
                    function: "fail".to_owned(),
                    arguments: vec![payload.into()],
                    result: None,
                    builtin: None,
                    source_location: None,
                    may_throw: false,
                },
                IRInstruction::IRReturn {
                    value: None,
                    transferred_storage: None,
                },
            ],
        }],
        may_throw: false,
    };

    assert!(verify_module(&module(main)).is_err());
}
