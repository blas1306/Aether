//! Canonical combined verifier API and diagnostic normalization coverage.

use aether_ir::{
    ArrayType, BoolType, EnumType, IRBasicBlock, IRConstant, IRFunction, IRInstruction, IRModule,
    IRParameter, IRStorage, IRType, IRValue, IntType, VoidType,
};
use aether_verifier::{
    BorrowRule, BorrowRuleError, InstructionKind, TypeRuleError, VerificationError,
    VerificationErrorCategory, VerificationPhase, verify_module,
};

fn ret() -> IRInstruction {
    IRInstruction::IRReturn {
        value: None,
        transferred_storage: None,
    }
}

fn function(return_type: IRType, instructions: Vec<IRInstruction>) -> IRFunction {
    IRFunction {
        name: "main".to_owned(),
        parameters: Vec::new(),
        return_type,
        blocks: vec![IRBasicBlock {
            name: "entry".to_owned(),
            instructions,
        }],
        may_throw: false,
    }
}

fn module(function: IRFunction) -> IRModule {
    IRModule {
        functions: vec![function],
        structs: Vec::new(),
    }
}

fn structurally_invalid_module() -> IRModule {
    module(function(VoidType.into(), Vec::new()))
}

#[test]
fn successful_verification_returns_ok() {
    let module = module(function(VoidType.into(), vec![ret()]));

    assert_eq!(verify_module(&module), Ok(()));
}

#[test]
fn first_failing_pass_follows_the_canonical_order() {
    let invalid_type: IRType = EnumType {
        name: String::new(),
        variants: Vec::new(),
        display_name: None,
    }
    .into();
    let structure_before_types = module(function(invalid_type, Vec::new()));
    assert_eq!(
        verify_module(&structure_before_types).unwrap_err().phase(),
        VerificationPhase::Structure
    );

    let bad_type = IRInstruction::IRConst {
        result: IRValue::new("duplicate", BoolType.into()),
        value: IRConstant::Int(1),
    };
    let duplicate_ssa_definition = IRInstruction::IRConst {
        result: IRValue::new("duplicate", IntType.into()),
        value: IRConstant::Int(2),
    };
    let module = module(function(
        VoidType.into(),
        vec![bad_type, duplicate_ssa_definition, ret()],
    ));

    let failure = verify_module(&module).unwrap_err();

    assert_eq!(failure.phase(), VerificationPhase::Types);
    assert_eq!(failure.invariant_id(), Some("IRV-069"));
    assert_eq!(failure.category(), VerificationErrorCategory::Constants);
    assert!(matches!(
        failure.underlying_error(),
        VerificationError::Types(_)
    ));
}

#[test]
fn repeated_invalid_verification_is_identical() {
    let module = structurally_invalid_module();
    let first = verify_module(&module).unwrap_err();

    for _ in 0..8 {
        assert_eq!(verify_module(&module).unwrap_err(), first);
    }
}

#[test]
fn invariant_metadata_propagates_from_typed_borrow_errors() {
    let array_type: IRType = ArrayType {
        element: Box::new(IntType.into()),
    }
    .into();
    let mut function = function(
        VoidType.into(),
        vec![
            IRInstruction::IRArrayGet {
                result: IRValue::new("borrowed", IntType.into()),
                array: IRValue::new("array", array_type.clone()),
                index: IRValue::new("index", IntType.into()),
                borrowed: true,
                borrow_scope: None,
                source_location: None,
            },
            ret(),
        ],
    );
    function.parameters = vec![
        IRParameter::new("array", array_type),
        IRParameter::new("index", IntType.into()),
    ];

    let failure = verify_module(&module(function)).unwrap_err();

    assert_eq!(failure.phase(), VerificationPhase::Types);
    assert_eq!(failure.invariant_id(), Some("IRV-037"));
    assert_eq!(failure.category(), VerificationErrorCategory::Borrowing);
    let VerificationError::Types(error) = failure.underlying_error() else {
        panic!("expected the original type verifier error")
    };
    let aether_verifier::ModuleTypeVerificationError::Function { source, .. } = error.as_ref()
    else {
        panic!("expected function context")
    };
    let aether_verifier::FunctionTypeVerificationError::Block { source, .. } = source else {
        panic!("expected block context")
    };
    let TypeRuleError::BorrowViolation { source } = &source.source.source else {
        panic!("expected borrow leaf error")
    };
    assert!(matches!(
        source,
        BorrowRuleError::MissingBorrowScope {
            rule: BorrowRule::Irv037,
            ..
        }
    ));
}

#[test]
fn phase_and_instruction_context_propagate_from_lifecycle() {
    let module = module(function(
        VoidType.into(),
        vec![
            IRInstruction::IRDestroy {
                value: IRStorage::new("slot", IntType.into()),
                source_location: None,
            },
            ret(),
        ],
    ));

    let failure = verify_module(&module).unwrap_err();

    assert_eq!(failure.phase(), VerificationPhase::Lifecycle);
    assert_eq!(failure.invariant_id(), Some("IRV-050"));
    assert_eq!(failure.category(), VerificationErrorCategory::Lifecycle);
    assert_eq!(failure.context().function_index, Some(0));
    assert_eq!(failure.context().function_name.as_deref(), Some("main"));
    assert_eq!(failure.context().block_index, Some(0));
    assert_eq!(failure.context().block_name.as_deref(), Some("entry"));
    assert_eq!(failure.context().instruction_index, Some(0));
    assert_eq!(
        failure.context().instruction_kind,
        Some(InstructionKind::IRDestroy)
    );
}

#[test]
fn normalized_message_is_stable_and_human_readable() {
    let module = structurally_invalid_module();
    let first = verify_module(&module).unwrap_err();
    let second = verify_module(&module).unwrap_err();
    let expected = "function 0 ('main') failed structure verification: block 0 ('entry') \
                    of function 'main' failed structure verification: structure verification \
                    failed in function 'main' block 'entry': missing terminator: expected exactly \
                    one final control-flow terminator, got an empty block";

    assert_eq!(first.message(), expected);
    assert_eq!(second.message(), expected);
    assert_eq!(first.to_string(), expected);
    assert_eq!(first.invariant_id(), Some("IRV-018"));
    assert_eq!(first.phase(), VerificationPhase::Structure);
}
