//! Focused entry-rooted, cross-block SSA dominance coverage.

use std::error::Error as _;

use aether_ir::{
    BoolType, IRBasicBlock, IRConstant, IRFunction, IRInstruction, IRModule, IRParameter,
    IRStorage, IRType, IRValue, IntType, StringType,
};
use aether_verifier::{
    BlockDominanceError, DominanceRuleError, DominanceUseLocation, FunctionDominanceError,
    FunctionSSAError, FunctionStructureVerificationError, InstructionKind, SSADefinitionError,
    SSADefinitionLocation, SSAInstructionLocation, verify_function_dominance, verify_function_ssa,
    verify_module_dominance,
};

fn int(name: &str) -> IRValue {
    IRValue::new(name, IntType.into())
}

fn bool_value(name: &str) -> IRValue {
    IRValue::new(name, BoolType.into())
}

fn parameter(name: &str, r#type: IRType) -> IRParameter {
    IRParameter::new(name, r#type)
}

fn constant(name: &str, literal: i32) -> IRInstruction {
    IRInstruction::IRConst {
        result: int(name),
        value: IRConstant::Int(literal),
    }
}

fn add(result: &str, left: &str, right: &str) -> IRInstruction {
    IRInstruction::IRBinaryOp {
        result: int(result),
        operator: "add".to_owned(),
        left: int(left),
        right: int(right),
        source_location: None,
    }
}

fn jump(target: &str) -> IRInstruction {
    IRInstruction::IRJump {
        target: target.to_owned(),
    }
}

fn branch(condition: &str, true_target: &str, false_target: &str) -> IRInstruction {
    IRInstruction::IRBranch {
        condition: bool_value(condition),
        true_target: true_target.to_owned(),
        false_target: false_target.to_owned(),
    }
}

fn ret(value: Option<&str>) -> IRInstruction {
    IRInstruction::IRReturn {
        value: value.map(int),
        transferred_storage: None,
    }
}

fn block(name: &str, instructions: Vec<IRInstruction>) -> IRBasicBlock {
    IRBasicBlock {
        name: name.to_owned(),
        instructions,
    }
}

fn function(name: &str, parameters: Vec<IRParameter>, blocks: Vec<IRBasicBlock>) -> IRFunction {
    IRFunction {
        name: name.to_owned(),
        parameters,
        return_type: IntType.into(),
        blocks,
    }
}

fn module(functions: Vec<IRFunction>) -> IRModule {
    IRModule {
        functions,
        structs: Vec::new(),
    }
}

fn dominance_block(error: &FunctionDominanceError) -> &BlockDominanceError {
    let FunctionDominanceError::Block { source, .. } = error else {
        panic!("expected block dominance error")
    };
    source
}

fn invalid_rule(error: &FunctionDominanceError) -> &DominanceRuleError {
    &dominance_block(error).source
}

#[test]
fn accepts_parameters_in_entry_descendants_and_unreachable_blocks() {
    let function = function(
        "parameters",
        vec![
            parameter("input", IntType.into()),
            parameter("condition", BoolType.into()),
        ],
        vec![
            block(
                "entry",
                vec![add("entry_value", "input", "input"), jump("live")],
            ),
            block(
                "live",
                vec![add("live_value", "input", "input"), ret(Some("live_value"))],
            ),
            block(
                "dead",
                vec![add("dead_value", "input", "input"), ret(Some("dead_value"))],
            ),
        ],
    );

    assert_eq!(verify_function_dominance(&function), Ok(()));
}

#[test]
fn accepts_entry_definition_in_diamond_branches_and_merge() {
    let function = function(
        "diamond",
        vec![parameter("condition", BoolType.into())],
        vec![
            block(
                "entry",
                vec![constant("shared", 1), branch("condition", "left", "right")],
            ),
            block(
                "left",
                vec![add("left_value", "shared", "shared"), jump("merge")],
            ),
            block(
                "right",
                vec![add("right_value", "shared", "shared"), jump("merge")],
            ),
            block("merge", vec![ret(Some("shared"))]),
        ],
    );

    assert_eq!(
        verify_module_dominance(&module(vec![function.clone()])),
        Ok(())
    );
    assert_eq!(verify_function_dominance(&function), Ok(()));
}

#[test]
fn accepts_linear_cfg_and_multiple_return_blocks() {
    let function = function(
        "linear_returns",
        vec![parameter("condition", BoolType.into())],
        vec![
            block("entry", vec![constant("shared", 1), jump("middle")]),
            block(
                "middle",
                vec![
                    add("sum", "shared", "shared"),
                    branch("condition", "yes", "no"),
                ],
            ),
            block("yes", vec![ret(Some("sum"))]),
            block("no", vec![ret(Some("shared"))]),
        ],
    );

    assert_eq!(verify_function_dominance(&function), Ok(()));
}

#[test]
fn accepts_loop_header_definition_self_loop_and_multiple_back_edges() {
    let function = function(
        "loops",
        vec![parameter("condition", BoolType.into())],
        vec![
            block("entry", vec![constant("outside", 1), jump("header")]),
            block(
                "header",
                vec![
                    add("header_value", "outside", "outside"),
                    branch("condition", "body", "exit"),
                ],
            ),
            block(
                "body",
                vec![
                    add("body_value", "header_value", "outside"),
                    branch("condition", "latch", "header"),
                ],
            ),
            block(
                "latch",
                vec![
                    add("latch_value", "header_value", "body_value"),
                    jump("header"),
                ],
            ),
            block("exit", vec![ret(Some("header_value"))]),
            block(
                "dead_self",
                vec![
                    constant("local", 2),
                    add("local_sum", "local", "local"),
                    jump("dead_self"),
                ],
            ),
        ],
    );

    assert_eq!(verify_function_dominance(&function), Ok(()));
}

#[test]
fn accepts_entry_not_first_duplicate_branch_edges_and_exact_names() {
    let function = function(
        "ordering",
        vec![parameter("condition", BoolType.into())],
        vec![
            block("Target", vec![ret(Some("shared"))]),
            block(
                "entry",
                vec![
                    constant("shared", 1),
                    branch("condition", "Target", "Target"),
                ],
            ),
            block(
                "target",
                vec![constant("lowercase_local", 2), ret(Some("lowercase_local"))],
            ),
        ],
    );

    assert_eq!(verify_function_dominance(&function), Ok(()));
}

#[test]
fn rejects_branch_definition_used_at_merge_with_exact_locations() {
    let function = function(
        "bad_merge",
        vec![parameter("condition", BoolType.into())],
        vec![
            block("entry", vec![branch("condition", "left", "right")]),
            block("left", vec![constant("left_only", 1), jump("merge")]),
            block("right", vec![jump("merge")]),
            block("merge", vec![ret(Some("left_only"))]),
        ],
    );
    let error = verify_function_dominance(&function).unwrap_err();

    assert_eq!(
        invalid_rule(&error),
        &DominanceRuleError::DefinitionDoesNotDominateUse {
            ssa_identifier: "left_only".to_owned(),
            defining_location: SSADefinitionLocation::Instruction(SSAInstructionLocation {
                block_index: 1,
                block_name: "left".to_owned(),
                instruction_index: 0,
                instruction_kind: InstructionKind::IRConst,
            }),
            use_location: DominanceUseLocation {
                instruction: SSAInstructionLocation {
                    block_index: 3,
                    block_name: "merge".to_owned(),
                    instruction_index: 0,
                    instruction_kind: InstructionKind::IRReturn,
                },
                operand_index: 0,
                operand_field: "value".to_owned(),
            },
            entry_block: "entry".to_owned(),
        }
    );
}

#[test]
fn rejects_sibling_definition_used_in_other_sibling() {
    let function = function(
        "sibling",
        vec![parameter("condition", BoolType.into())],
        vec![
            block("entry", vec![branch("condition", "left", "right")]),
            block(
                "left",
                vec![constant("left_only", 1), ret(Some("left_only"))],
            ),
            block("right", vec![ret(Some("left_only"))]),
        ],
    );

    assert!(matches!(
        invalid_rule(&verify_function_dominance(&function).unwrap_err()),
        DominanceRuleError::DefinitionDoesNotDominateUse { ssa_identifier, use_location, .. }
            if ssa_identifier == "left_only" && use_location.instruction.block_name == "right"
    ));
}

#[test]
fn rejects_descendant_definition_used_in_ancestor() {
    let function = function(
        "descendant",
        vec![parameter("condition", BoolType.into())],
        vec![
            block("body", vec![constant("later", 1), jump("entry")]),
            block(
                "entry",
                vec![
                    add("use_later", "later", "later"),
                    branch("condition", "body", "exit"),
                ],
            ),
            block("exit", vec![ret(Some("use_later"))]),
        ],
    );

    assert!(matches!(
        invalid_rule(&verify_function_dominance(&function).unwrap_err()),
        DominanceRuleError::DefinitionDoesNotDominateUse { defining_location: SSADefinitionLocation::Instruction(location), use_location, .. }
            if location.block_name == "body" && use_location.instruction.block_name == "entry"
    ));
}

#[test]
fn rejects_loop_body_definition_used_in_header() {
    let function = function(
        "bad_loop",
        vec![parameter("condition", BoolType.into())],
        vec![
            block("entry", vec![jump("header")]),
            block(
                "header",
                vec![
                    add("header_use", "body_value", "body_value"),
                    branch("condition", "body", "exit"),
                ],
            ),
            block("body", vec![constant("body_value", 1), jump("header")]),
            block("exit", vec![ret(Some("header_use"))]),
        ],
    );

    assert!(matches!(
        invalid_rule(&verify_function_dominance(&function).unwrap_err()),
        DominanceRuleError::DefinitionDoesNotDominateUse { ssa_identifier, .. }
            if ssa_identifier == "body_value"
    ));
}

#[test]
fn reports_first_failing_use_in_block_instruction_and_operand_order() {
    let function = function(
        "first_error",
        vec![parameter("condition", BoolType.into())],
        vec![
            block("entry", vec![branch("condition", "left", "right")]),
            block(
                "left",
                vec![constant("first", 1), constant("second", 2), jump("merge")],
            ),
            block("right", vec![jump("merge")]),
            block(
                "merge",
                vec![add("bad", "first", "second"), ret(Some("bad"))],
            ),
        ],
    );
    let first = verify_function_dominance(&function).unwrap_err();
    let second = verify_function_dominance(&function).unwrap_err();

    assert_eq!(first, second);
    assert!(matches!(
        invalid_rule(&first),
        DominanceRuleError::DefinitionDoesNotDominateUse { ssa_identifier, use_location, .. }
            if ssa_identifier == "first"
                && use_location.operand_index == 0
                && use_location.operand_field == "left"
    ));
}

#[test]
fn preserves_same_block_boundary_owned_by_ssa_pass() {
    let invalid = function(
        "local_order",
        Vec::new(),
        vec![block(
            "entry",
            vec![
                add("sum", "later", "later"),
                constant("later", 1),
                ret(Some("sum")),
            ],
        )],
    );
    let ssa_error = verify_function_ssa(&invalid).unwrap_err();
    let dominance_error = verify_function_dominance(&invalid).unwrap_err();

    assert!(matches!(
        ssa_error,
        FunctionSSAError::Block { source, .. }
            if matches!(source.source, SSADefinitionError::UseBeforeDefinition { .. })
    ));
    assert!(matches!(
        dominance_error,
        FunctionDominanceError::SSAPrerequisite { .. }
    ));

    let valid = function(
        "local_valid",
        Vec::new(),
        vec![block(
            "entry",
            vec![
                constant("one", 1),
                add("sum", "one", "one"),
                ret(Some("sum")),
            ],
        )],
    );
    assert_eq!(verify_function_dominance(&valid), Ok(()));
}

#[test]
fn rejects_cross_block_uses_inside_unreachable_cycle() {
    let function = function(
        "dead_cycle",
        Vec::new(),
        vec![
            block("entry", vec![constant("live", 1), ret(Some("live"))]),
            block("dead_a", vec![constant("dead_value", 2), jump("dead_b")]),
            block(
                "dead_b",
                vec![add("dead_use", "dead_value", "dead_value"), jump("dead_a")],
            ),
        ],
    );

    assert!(matches!(
        invalid_rule(&verify_function_dominance(&function).unwrap_err()),
        DominanceRuleError::DefinitionDoesNotDominateUse { ssa_identifier, use_location, .. }
            if ssa_identifier == "dead_value" && use_location.instruction.block_name == "dead_b"
    ));
}

#[test]
fn accepts_isolated_unreachable_same_block_definition_and_use() {
    let function = function(
        "isolated_dead",
        Vec::new(),
        vec![
            block("entry", vec![constant("live", 1), ret(Some("live"))]),
            block(
                "dead",
                vec![
                    constant("dead_value", 2),
                    add("dead_use", "dead_value", "dead_value"),
                    ret(Some("dead_use")),
                ],
            ),
        ],
    );

    assert_eq!(verify_function_dominance(&function), Ok(()));
}

#[test]
fn rejects_reachable_use_of_unreachable_definition_and_inverse() {
    let reachable_use = function(
        "dead_definition",
        Vec::new(),
        vec![
            block("entry", vec![ret(Some("dead_value"))]),
            block(
                "dead",
                vec![constant("dead_value", 1), ret(Some("dead_value"))],
            ),
        ],
    );
    assert!(verify_function_dominance(&reachable_use).is_err());

    let unreachable_use = function(
        "dead_use",
        Vec::new(),
        vec![
            block("entry", vec![constant("live", 1), ret(Some("live"))]),
            block("dead", vec![ret(Some("live"))]),
        ],
    );
    assert!(verify_function_dominance(&unreachable_use).is_err());
}

#[test]
fn wraps_structural_and_ssa_prerequisites_without_panicking() {
    let malformed_cfg = function(
        "malformed_cfg",
        Vec::new(),
        vec![block("entry", vec![jump("missing")])],
    );
    let structure_error = verify_function_dominance(&malformed_cfg).unwrap_err();
    assert!(matches!(
        structure_error,
        FunctionDominanceError::StructurePrerequisite {
            source,
            ..
        } if matches!(source.as_ref(), FunctionStructureVerificationError::Block { .. })
    ));

    let unresolved = function(
        "unresolved",
        Vec::new(),
        vec![block("entry", vec![ret(Some("missing"))])],
    );
    let ssa_error = verify_function_dominance(&unresolved).unwrap_err();
    assert!(matches!(
        ssa_error,
        FunctionDominanceError::SSAPrerequisite { .. }
    ));
}

#[test]
fn type_and_lifecycle_rules_remain_outside_this_pass() {
    let type_invalid = IRFunction {
        name: "type_invalid".to_owned(),
        parameters: Vec::new(),
        return_type: IntType.into(),
        blocks: vec![block(
            "entry",
            vec![
                IRInstruction::IRConst {
                    result: int("wrongly_typed"),
                    value: IRConstant::Bool(true),
                },
                ret(Some("wrongly_typed")),
            ],
        )],
    };
    assert_eq!(verify_function_dominance(&type_invalid), Ok(()));

    let lifecycle_invalid = IRFunction {
        name: "lifecycle_invalid".to_owned(),
        parameters: Vec::new(),
        return_type: IntType.into(),
        blocks: vec![block(
            "entry",
            vec![
                IRInstruction::IRDestroy {
                    value: IRStorage::new("never_live", StringType.into()),
                    source_location: None,
                },
                constant("result", 1),
                ret(Some("result")),
            ],
        )],
    };
    assert_eq!(verify_function_dominance(&lifecycle_invalid), Ok(()));
}

#[test]
fn module_order_and_error_source_chain_are_stable_and_downcastable() {
    let valid = function(
        "valid",
        Vec::new(),
        vec![block(
            "entry",
            vec![constant("result", 1), ret(Some("result"))],
        )],
    );
    let invalid = function(
        "invalid",
        vec![parameter("condition", BoolType.into())],
        vec![
            block("entry", vec![branch("condition", "left", "right")]),
            block("left", vec![constant("left_only", 1), jump("merge")]),
            block("right", vec![jump("merge")]),
            block("merge", vec![ret(Some("left_only"))]),
        ],
    );
    let error = verify_module_dominance(&module(vec![valid, invalid])).unwrap_err();

    assert_eq!(error.function_index, 1);
    assert_eq!(error.function_name, "invalid");
    let function_source = error.source().expect("function source");
    assert!(
        function_source
            .downcast_ref::<FunctionDominanceError>()
            .is_some()
    );
    let block_source = function_source.source().expect("block source");
    assert!(block_source.downcast_ref::<BlockDominanceError>().is_some());
    let rule_source = block_source.source().expect("rule source");
    assert!(rule_source.downcast_ref::<DominanceRuleError>().is_some());
}
