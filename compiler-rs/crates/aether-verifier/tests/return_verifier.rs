//! Focused IRV-024 non-void all-path return coverage.

use std::error::Error as _;

use aether_ir::{
    BoolType, IRBasicBlock, IRFunction, IRInstruction, IRModule, IRValue, IntType, StringType,
    VoidType,
};
use aether_verifier::{
    FunctionReturnVerificationError, FunctionStructureVerificationError,
    ModuleReturnVerificationError, ReturnPathRuleError, verify_function_returns,
    verify_module_returns,
};

fn value(name: &str, type_: aether_ir::IRType) -> IRValue {
    IRValue::new(name, type_)
}

fn valued_return() -> IRInstruction {
    IRInstruction::IRReturn {
        value: Some(value("result", IntType.into()).into()),
        transferred_storage: None,
    }
}

fn valueless_return() -> IRInstruction {
    IRInstruction::IRReturn {
        value: None,
        transferred_storage: None,
    }
}

fn jump(target: &str) -> IRInstruction {
    IRInstruction::IRJump {
        target: target.to_owned(),
    }
}

fn branch(true_target: &str, false_target: &str) -> IRInstruction {
    IRInstruction::IRBranch {
        condition: value("condition", BoolType.into()),
        true_target: true_target.to_owned(),
        false_target: false_target.to_owned(),
    }
}

fn block(name: &str, terminator: IRInstruction) -> IRBasicBlock {
    IRBasicBlock {
        name: name.to_owned(),
        instructions: vec![terminator],
    }
}

fn function(name: &str, return_type: aether_ir::IRType, blocks: Vec<IRBasicBlock>) -> IRFunction {
    IRFunction {
        name: name.to_owned(),
        parameters: Vec::new(),
        return_type,
        blocks,
    }
}

fn module(functions: Vec<IRFunction>) -> IRModule {
    IRModule {
        functions,
        structs: Vec::new(),
    }
}

fn return_rule(error: &ModuleReturnVerificationError) -> &ReturnPathRuleError {
    let FunctionReturnVerificationError::NonVoidPathWithoutReturn { source, .. } =
        error.source.as_ref()
    else {
        panic!("expected non-void path failure")
    };
    source
}

#[test]
fn accepts_single_and_multiple_valued_return_paths_through_both_public_layers() {
    let single = function(
        "single",
        IntType.into(),
        vec![block("entry", valued_return())],
    );
    assert_eq!(verify_function_returns(&single), Ok(()));

    let alternatives = function(
        "alternatives",
        IntType.into(),
        vec![
            block("entry", branch("then", "else")),
            block("then", valued_return()),
            block("else", valued_return()),
        ],
    );
    assert_eq!(
        verify_module_returns(&module(vec![single, alternatives])),
        Ok(())
    );
}

#[test]
fn rejects_reachable_valueless_return_with_stable_location() {
    let module = module(vec![function(
        "missing",
        IntType.into(),
        vec![
            block("entry", branch("good", "bad")),
            block("good", valued_return()),
            block("bad", valueless_return()),
        ],
    )]);
    let error = verify_module_returns(&module).unwrap_err();

    assert_eq!(
        return_rule(&error),
        &ReturnPathRuleError::ValuelessReturn {
            block_index: 2,
            block_name: "bad".to_owned(),
            instruction_index: 0,
        }
    );
    let FunctionReturnVerificationError::NonVoidPathWithoutReturn {
        function_name,
        return_type,
        entry_block,
        ..
    } = error.source.as_ref()
    else {
        panic!("expected non-void path failure")
    };
    assert_eq!(function_name, "missing");
    assert_eq!(return_type, &aether_ir::IRType::from(IntType));
    assert_eq!(entry_block, "entry");
}

#[test]
fn ordinary_entry_cycle_is_a_non_exiting_path() {
    let module = module(vec![function(
        "choose",
        IntType.into(),
        vec![
            block("entry", branch("then", "else")),
            block("then", valued_return()),
            block("else", jump("entry")),
        ],
    )]);

    assert_eq!(verify_module_returns(&module), Ok(()));
}

#[test]
fn pure_cycle_result_is_independent_of_header_name() {
    for header in ["cond", "for.cond", "loop", "arbitrary_name", "xyz"] {
        let function = function(
            header,
            IntType.into(),
            vec![block("entry", jump(header)), block(header, jump(header))],
        );
        assert_eq!(
            verify_function_returns(&function),
            Ok(()),
            "header {header}"
        );
    }
}

#[test]
fn optional_return_cycle_result_is_independent_of_header_name() {
    for header in ["cond", "for.cond", "loop", "arbitrary_name", "xyz"] {
        let function = function(
            header,
            IntType.into(),
            vec![
                block("entry", jump(header)),
                block(header, branch("return_block", header)),
                block("return_block", valued_return()),
            ],
        );
        assert_eq!(
            verify_function_returns(&function),
            Ok(()),
            "header {header}"
        );
    }
}

#[test]
fn lowering_shaped_while_is_invariant_under_bijective_block_renaming() {
    let lowering_names = function(
        "lowering_names",
        IntType.into(),
        vec![
            block("entry", jump("cond0")),
            block("cond0", branch("body0", "exit0")),
            block("body0", jump("cond0")),
            block("exit0", valued_return()),
        ],
    );
    let arbitrary_names = function(
        "arbitrary_names",
        IntType.into(),
        vec![
            block("entry", jump("arbitrary_name")),
            block("arbitrary_name", branch("xyz", "done")),
            block("xyz", jump("arbitrary_name")),
            block("done", valued_return()),
        ],
    );

    assert_eq!(verify_function_returns(&lowering_names), Ok(()));
    assert_eq!(verify_function_returns(&arbitrary_names), Ok(()));
}

#[test]
fn lowering_shaped_for_is_invariant_under_bijective_block_renaming() {
    let lowering_names = function(
        "lowering_names",
        IntType.into(),
        vec![
            block("entry", jump("for.cond0")),
            block("for.cond0", branch("for.body0", "for.exit0")),
            block("for.body0", jump("for.inc0")),
            block("for.inc0", branch("for.exit0", "for.advance0")),
            block("for.advance0", jump("for.cond0")),
            block("for.exit0", valued_return()),
        ],
    );
    let arbitrary_names = function(
        "arbitrary_names",
        IntType.into(),
        vec![
            block("entry", jump("alpha")),
            block("alpha", branch("beta", "omega")),
            block("beta", jump("gamma")),
            block("gamma", branch("omega", "delta")),
            block("delta", jump("alpha")),
            block("omega", valued_return()),
        ],
    );

    assert_eq!(verify_function_returns(&lowering_names), Ok(()));
    assert_eq!(verify_function_returns(&arbitrary_names), Ok(()));
}

#[test]
fn ignores_unreachable_valueless_returns_and_ordinary_cycles() {
    let function = function(
        "reachable_only",
        IntType.into(),
        vec![
            block("dead.return", valueless_return()),
            block("entry", valued_return()),
            block("dead.one", jump("dead.two")),
            block("dead.two", jump("dead.one")),
        ],
    );

    assert_eq!(verify_function_returns(&function), Ok(()));
}

#[test]
fn void_functions_are_exempt_after_structural_validation() {
    let void_function = function(
        "void_spin",
        VoidType.into(),
        vec![block("entry", jump("entry"))],
    );
    assert_eq!(verify_function_returns(&void_function), Ok(()));

    let malformed = function(
        "malformed_void",
        VoidType.into(),
        vec![IRBasicBlock {
            name: "entry".to_owned(),
            instructions: Vec::new(),
        }],
    );
    assert!(matches!(
        verify_function_returns(&malformed),
        Err(FunctionReturnVerificationError::StructurePrerequisite { .. })
    ));
}

#[test]
fn checks_only_value_presence_not_return_operand_type_or_ssa_validity() {
    let function = function(
        "independent",
        IntType.into(),
        vec![block(
            "entry",
            IRInstruction::IRReturn {
                value: Some(value("undefined", StringType.into()).into()),
                transferred_storage: None,
            },
        )],
    );

    assert_eq!(verify_function_returns(&function), Ok(()));
}

#[test]
fn structural_prerequisite_error_chain_remains_typed_and_downcastable() {
    let module = module(vec![function(
        "broken",
        IntType.into(),
        vec![block("entry", jump("missing"))],
    )]);
    let error = verify_module_returns(&module).unwrap_err();

    assert!(matches!(
        error.source.as_ref(),
        FunctionReturnVerificationError::StructurePrerequisite { .. }
    ));
    assert!(error.source().is_some());
    assert!(error.source().and_then(|nested| nested.source()).is_some());
    assert!(
        error
            .source()
            .and_then(|nested| nested.source())
            .and_then(|nested| nested.source())
            .is_some()
    );
    assert!(
        error
            .source()
            .and_then(|nested| nested.source())
            .expect("structural function source")
            .downcast_ref::<FunctionStructureVerificationError>()
            .is_some()
    );
}

#[test]
fn first_failure_is_true_before_false_and_module_source_order_is_stable() {
    let first = function(
        "first",
        IntType.into(),
        vec![
            block("entry", branch("true.bad", "false.bad")),
            block("true.bad", jump("true.bad")),
            block("false.bad", valueless_return()),
        ],
    );
    let second = function(
        "second",
        IntType.into(),
        vec![block("entry", valueless_return())],
    );
    let module = module(vec![first, second]);
    let expected = verify_module_returns(&module).unwrap_err();

    assert_eq!(expected.function_index, 0);
    assert!(matches!(
        return_rule(&expected),
        ReturnPathRuleError::ValuelessReturn { block_name, .. }
            if block_name == "false.bad"
    ));
    for _ in 0..32 {
        assert_eq!(verify_module_returns(&module), Err(expected.clone()));
    }
}
