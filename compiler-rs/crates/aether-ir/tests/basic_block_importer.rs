//! Focused coverage for schema-v1 basic-block import.

use std::error::Error as _;

use aether_ir::wire::{IRBasicBlockDTO, IRConstantDTO, IRFloatDTO, IRInstructionDTO, IRValueDTO};
use aether_ir::{
    IRBasicBlock, IRConstant, IRImportError, IRInstruction, IRValue, IntType, import_basic_block,
};
use serde_json::{Value, json};

fn int_value_json(name: &str) -> Value {
    json!({"tag": "value", "name": name, "type": {"tag": "int"}})
}

fn const_json(name: &str, value: i32) -> Value {
    json!({
        "kind": "const",
        "result": int_value_json(name),
        "value": {"tag": "int", "value": value}
    })
}

fn return_json() -> Value {
    json!({"kind": "return", "value": null, "transferred_storage": null})
}

fn block_json(name: &str, instructions: &[Value]) -> Value {
    json!({"name": name, "instructions": instructions})
}

fn wire_block(name: &str, instructions: &[Value]) -> IRBasicBlockDTO {
    serde_json::from_value(block_json(name, instructions))
        .expect("basic-block fixture must be valid wire JSON")
}

fn int_const(name: &str, value: i32) -> IRInstruction {
    IRInstruction::IRConst {
        result: IRValue::new(name, IntType.into()),
        value: IRConstant::Int(value),
    }
}

fn empty_return() -> IRInstruction {
    IRInstruction::IRReturn {
        value: None,
        transferred_storage: None,
    }
}

#[test]
fn imports_empty_block_with_exact_name() {
    let wire = wire_block(" entry\0raw ", &[]);

    assert_eq!(
        import_basic_block(&wire),
        Ok(IRBasicBlock {
            name: " entry\0raw ".to_owned(),
            instructions: vec![],
        })
    );
}

#[test]
fn imports_single_instruction_through_owned_and_borrowed_paths_without_mutating_dto() {
    let wire = wire_block("single", &[const_json("one", 1)]);
    let original = wire.clone();
    let expected = IRBasicBlock {
        name: "single".to_owned(),
        instructions: vec![int_const("one", 1)],
    };

    assert_eq!(import_basic_block(&wire), Ok(expected.clone()));
    assert_eq!(IRBasicBlock::try_from(&wire), Ok(expected.clone()));
    assert_eq!(IRBasicBlock::try_from(wire.clone()), Ok(expected));
    assert_eq!(wire, original, "borrowed import must not mutate its DTO");
}

#[test]
fn preserves_multiple_instruction_order_and_duplicate_instructions() {
    let duplicate = const_json("duplicate", 7);
    let wire = wire_block(
        "ordered",
        &[
            const_json("first", 1),
            duplicate.clone(),
            const_json("last", 3),
            duplicate,
        ],
    );

    assert_eq!(
        import_basic_block(&wire),
        Ok(IRBasicBlock {
            name: "ordered".to_owned(),
            instructions: vec![
                int_const("first", 1),
                int_const("duplicate", 7),
                int_const("last", 3),
                int_const("duplicate", 7),
            ],
        })
    );
}

#[test]
fn accepts_missing_and_multiple_terminators_without_verification() {
    let missing = wire_block("missing-terminator", &[const_json("value", 4)]);
    let multiple = wire_block("multiple-terminators", &[return_json(), return_json()]);

    assert_eq!(
        import_basic_block(&missing)
            .expect("missing terminators remain verifier concerns")
            .instructions,
        vec![int_const("value", 4)]
    );
    assert_eq!(
        import_basic_block(&multiple)
            .expect("multiple terminators remain verifier concerns")
            .instructions,
        vec![empty_return(), empty_return()]
    );
}

#[test]
fn accepts_invalid_but_representable_instruction_ordering() {
    let wire = wire_block(
        "after-return",
        &[return_json(), const_json("unreachable", 9)],
    );

    assert_eq!(
        import_basic_block(&wire)
            .expect("terminator placement remains a verifier concern")
            .instructions,
        vec![empty_return(), int_const("unreachable", 9)]
    );
}

#[test]
fn imports_duplicate_block_names_independently() {
    let first = wire_block("duplicate-name", &[const_json("first", 1)]);
    let second = wire_block("duplicate-name", &[return_json()]);

    assert_eq!(
        import_basic_block(&first)
            .expect("block-name uniqueness is not checked during individual import")
            .name,
        "duplicate-name"
    );
    assert_eq!(
        import_basic_block(&second)
            .expect("block-name uniqueness is not checked during individual import")
            .name,
        "duplicate-name"
    );
}

#[test]
fn json_wire_owned_conversion_is_deterministic_and_wire_round_trip_preserves_contents() {
    let json = block_json(
        " deterministic ",
        &[
            const_json("second", 2),
            const_json("first", 1),
            return_json(),
        ],
    );
    let encoded = serde_json::to_string(&json).expect("fixture JSON must serialize");
    let first_wire: IRBasicBlockDTO =
        serde_json::from_str(&encoded).expect("fixture JSON must deserialize");
    let wire_round_trip: IRBasicBlockDTO =
        serde_json::from_str(&serde_json::to_string(&first_wire).expect("wire DTO must serialize"))
            .expect("serialized wire DTO must deserialize");

    assert_eq!(wire_round_trip, first_wire);
    let expected = import_basic_block(&first_wire).expect("first import must succeed");
    assert_eq!(import_basic_block(&first_wire), Ok(expected.clone()));
    assert_eq!(import_basic_block(&wire_round_trip), Ok(expected));
}

#[test]
fn nested_failure_retains_block_index_and_instruction_field_error_chain() {
    let result: IRValueDTO = serde_json::from_value(int_value_json("bad-float"))
        .expect("result fixture must deserialize");
    let wire = IRBasicBlockDTO {
        name: " failing\0block ".to_owned(),
        instructions: vec![
            serde_json::from_value(return_json()).expect("return fixture must deserialize"),
            IRInstructionDTO::Const {
                result,
                value: IRConstantDTO::Float {
                    value: IRFloatDTO(f64::NAN),
                },
            },
        ],
    };
    let expected_instruction_error = IRImportError::InstructionField {
        instruction: "const",
        field: "value",
        source: Box::new(IRImportError::NonFiniteConstantFloat { field: "value" }),
    };
    let expected = IRImportError::BasicBlockInstruction {
        block: " failing\0block ".to_owned(),
        index: 1,
        source: Box::new(expected_instruction_error.clone()),
    };

    let error = import_basic_block(&wire).expect_err("nested instruction import must fail");
    assert_eq!(error, expected);
    assert_eq!(
        error
            .source()
            .and_then(|source| source.downcast_ref::<IRImportError>()),
        Some(&expected_instruction_error)
    );
    assert_eq!(
        error
            .source()
            .and_then(std::error::Error::source)
            .and_then(|source| source.downcast_ref::<IRImportError>()),
        Some(&IRImportError::NonFiniteConstantFloat { field: "value" })
    );
}
