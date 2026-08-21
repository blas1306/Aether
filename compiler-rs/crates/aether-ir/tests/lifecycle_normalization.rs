//! Lifecycle normalization policy-v1 regression tests.

use aether_ir::{
    normalize_lifecycle_v1,
    wire::{
        IRBasicBlockDTO, IRFunctionDTO, IRInstructionDTO as I, IRModuleDTO, IRStorageDTO,
        IRTypeDTO as T, IRValueDTO as V, NullableDTO,
    },
};
use serde_json::json;

fn storage(name: &str, ty: T) -> IRStorageDTO {
    IRStorageDTO::Storage {
        name: name.into(),
        r#type: ty,
    }
}
fn module(instructions: Vec<I>) -> IRModuleDTO {
    IRModuleDTO {
        schema_version: 1,
        structs: vec![],
        functions: vec![IRFunctionDTO {
            name: "f".into(),
            parameters: vec![],
            return_type: T::Void {},
            may_throw: false,
            blocks: vec![IRBasicBlockDTO {
                name: "entry".into(),
                instructions,
            }],
        }],
    }
}

#[test]
fn expands_all_six_pseudos_deterministically_without_mutating_input() {
    let int = T::Int {};
    let string = T::String {};
    let a = storage("a", int.clone());
    let b = storage("b", int.clone());
    let s = storage("s", string.clone());
    let input = module(vec![
        I::InitDefault {
            destination: a.clone(),
            source_location: NullableDTO(None),
        },
        I::CopyInit {
            destination: b.clone(),
            source: V::Storage {
                name: "a".into(),
                r#type: int.clone(),
            },
            source_location: NullableDTO(None),
        },
        I::Assign {
            destination: s.clone(),
            source: V::Value {
                name: "incoming".into(),
                r#type: string,
            },
            source_location: NullableDTO(None),
        },
        I::MoveInit {
            destination: a.clone(),
            source: b.clone(),
            source_location: NullableDTO(None),
        },
        I::Destroy {
            value: s,
            source_location: NullableDTO(None),
        },
        I::Relocate {
            destination: b,
            source: a,
            count: 1,
            source_location: NullableDTO(None),
        },
        I::Return {
            value: NullableDTO(None),
            transferred_storage: NullableDTO(None),
        },
    ]);
    let snapshot = input.clone();
    let first = normalize_lifecycle_v1(&input, 1).unwrap();
    let second = normalize_lifecycle_v1(&input, 1).unwrap();
    assert_eq!(input, snapshot);
    assert_eq!(first, second);
    assert!(
        first.functions[0].blocks[0]
            .instructions
            .iter()
            .all(|i| !matches!(
                i,
                I::InitDefault { .. }
                    | I::CopyInit { .. }
                    | I::MoveInit { .. }
                    | I::Assign { .. }
                    | I::Destroy { .. }
                    | I::Relocate { .. }
            ))
    );
}

#[test]
fn rejects_wrong_policy_and_mixed_domains() {
    let input = module(vec![]);
    assert!(
        normalize_lifecycle_v1(&input, 2)
            .unwrap_err()
            .to_string()
            .contains("expected 1")
    );
    let mixed = module(vec![
        I::InitDefault {
            destination: storage("s", T::String {}),
            source_location: NullableDTO(None),
        },
        I::Call {
            function: "__aether_retain".into(),
            arguments: vec![],
            result: NullableDTO(None),
            builtin: NullableDTO(Some("__aether_retain".into())),
            source_location: NullableDTO(None),
            may_throw: false,
        },
    ]);
    assert!(
        normalize_lifecycle_v1(&mixed, 1)
            .unwrap_err()
            .to_string()
            .contains("neither legal")
    );
}

#[test]
fn repairs_owning_constructor_invoke_edges_exactly_and_deterministically() {
    let input: IRModuleDTO = serde_json::from_value(json!({
        "schema_version": 1,
        "structs": [{"name":"Owner","fields":[
            {"name":"first","type":{"tag":"string"}},
            {"name":"nested","type":{"tag":"struct","name":"Nested"}}
        ]},{"name":"Nested","fields":[
            {"name":"second","type":{"tag":"string"}}
        ]}],
        "functions": [{
            "name":"f", "parameters":[], "return_type":{"tag":"void"}, "may_throw":true,
            "blocks":[
                {"name":"entry","instructions":[{
                    "kind":"invoke", "function":"Owner.__ctor",
                    "arguments":[{"tag":"value","name":"receiver","type":{"tag":"struct","name":"Owner"}}],
                    "result":null,
                    "exception":{"tag":"value","name":"exception","type":{"tag":"exception_event"}},
                    "normal_target":"normal", "exceptional_target":"handler",
                    "exceptional_target_event":{"tag":"value","name":"caught","type":{"tag":"exception_event"}},
                    "builtin":null,
                    "source_location":{"tag":"source_location","line":7,"column":11,"path":"owner.ae"}
                }]},
                {"name":"normal","instructions":[
                    {"kind":"const","result":{"tag":"value","name":"kept","type":{"tag":"int"}},"value":{"tag":"int","value":1}},
                    {"kind":"return","value":null,"transferred_storage":null}
                ]},
                {"name":"handler","instructions":[
                    {"kind":"catch_entry","event":{"tag":"value","name":"caught","type":{"tag":"exception_event"}},"handler_id":"user","catch_types":[]},
                    {"kind":"propagate","event":{"tag":"value","name":"caught","type":{"tag":"exception_event"}},"target":null,"target_event":null}
                ]},
                {"name":"constructor.receiver.cleanup0","instructions":[
                    {"kind":"return","value":null,"transferred_storage":null}
                ]}
            ]
        }]
    })).unwrap();

    let first = normalize_lifecycle_v1(&input, 1).unwrap();
    assert_eq!(first, normalize_lifecycle_v1(&input, 1).unwrap());
    assert_eq!(first.functions[0].blocks.len(), 5);
    let I::Invoke {
        exceptional_target,
        exceptional_target_event,
        source_location,
        ..
    } = &first.functions[0].blocks[0].instructions[0]
    else {
        panic!()
    };
    assert_eq!(exceptional_target, "constructor.receiver.cleanup1");
    assert!(matches!(
        source_location.0.as_ref().unwrap(),
        aether_ir::wire::IRSourceLocationDTO::SourceLocation {
            line: 7,
            column: 11,
            ..
        }
    ));
    assert_eq!(super_name(exceptional_target_event), "0");

    let normal = &first.functions[0].blocks[1].instructions;
    assert!(
        matches!(&normal[0], I::Call { builtin: NullableDTO(Some(name)), arguments, .. }
        if name == "__aether_release" && super_name(&arguments[0]) == "receiver")
    );
    assert!(matches!(&normal[1], I::Const { .. }));

    let cleanup = &first.functions[0].blocks[4];
    assert_eq!(cleanup.name, "constructor.receiver.cleanup1");
    assert!(
        matches!(&cleanup.instructions[0], I::CatchEntry { handler_id, .. }
        if handler_id == "constructor_receiver_cleanup1")
    );
    assert!(
        matches!(&cleanup.instructions[1], I::Call { builtin: NullableDTO(Some(name)), .. }
        if name == "__aether_release")
    );
    assert!(
        matches!(&cleanup.instructions[2], I::Propagate { target: NullableDTO(Some(target)), target_event: NullableDTO(Some(event)), .. }
        if target == "handler" && super_name(event) == "caught")
    );
}

fn super_name(value: &V) -> &str {
    match value {
        V::Value { name, .. } | V::Storage { name, .. } | V::Parameter { name, .. } => name,
    }
}
