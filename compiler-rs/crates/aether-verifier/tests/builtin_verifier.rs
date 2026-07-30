//! Canonical builtin identity and retain/release contract coverage.

use std::error::Error as _;

use aether_ir::{
    ArrayType, BoolType, DoubleType, EnumType, IRBasicBlock, IRFunction, IRInstruction, IRModule,
    IRParameter, IRStructDefinition, IRType, IRValue, IntType, ListType, MatrixType,
    MethodResultType, NullableType, StringType, StructType, VectorType, VoidType,
};
use aether_verifier::{
    FunctionTypeVerificationError, InstructionKind, InstructionTypeVerificationError,
    ModuleTypeVerificationError, TypeRuleError, verify_module_types,
};

fn value(name: &str, type_: IRType) -> IRValue {
    IRValue::new(name, type_)
}

fn call(
    function: &str,
    builtin: &str,
    arguments: Vec<IRValue>,
    result: Option<IRValue>,
) -> IRInstruction {
    IRInstruction::IRCall {
        function: function.to_owned(),
        arguments,
        result,
        builtin: Some(builtin.to_owned()),
        source_location: None,
        may_throw: false,
    }
}

fn module_with_call(instruction: IRInstruction) -> IRModule {
    let mut block = IRBasicBlock::new("entry");
    block.instructions.push(instruction);
    let mut function = IRFunction::new("main", Vec::new(), VoidType.into());
    function.blocks.push(block);
    IRModule {
        functions: vec![function],
        structs: Vec::new(),
    }
}

fn instruction_rule(error: &ModuleTypeVerificationError) -> &TypeRuleError {
    let ModuleTypeVerificationError::Function { source, .. } = error else {
        panic!("expected a function error")
    };
    let FunctionTypeVerificationError::Block { source, .. } = source else {
        panic!("expected a block error")
    };
    &source.source.source
}

fn managed_struct() -> IRStructDefinition {
    IRStructDefinition {
        name: "Managed".to_owned(),
        fields: vec![("number".to_owned(), IntType.into())],
    }
}

#[test]
fn accepts_a_canonical_builtin_call() {
    let module = module_with_call(call(
        "sin",
        "sin",
        vec![value("number", DoubleType.into())],
        Some(value("result", DoubleType.into())),
    ));

    assert_eq!(verify_module_types(&module), Ok(()));
}

#[test]
fn rejects_every_builtin_family_when_the_function_spelling_is_not_canonical() {
    let builtins = [
        "System.args",
        "__aether_range_step_nonzero",
        "__aether_string_byte_length",
        "__aether_string_trim",
        "__aether_string_split",
        "parseInt",
        "parseDouble",
        "io.readText",
        "io.writeText",
        "io.writeTextAtomic",
        "io.appendText",
        "text.byteAt",
        "text.byteSlice",
        "text.formatInt",
        "text.formatDouble",
        "text.concatFragments",
        "__aether_retain",
        "__aether_release",
        "sin",
    ];

    for builtin in builtins {
        let module = module_with_call(call("alias", builtin, Vec::new(), None));
        assert_eq!(
            instruction_rule(&verify_module_types(&module).unwrap_err()),
            &TypeRuleError::InvalidBuiltinIdentity {
                builtin: builtin.to_owned(),
                expected: builtin.to_owned(),
                actual: "alias".to_owned(),
            }
        );
    }
}

#[test]
fn rejects_wrong_builtin_with_an_identical_signature() {
    let module = module_with_call(call(
        "cos",
        "sin",
        vec![value("number", DoubleType.into())],
        Some(value("result", DoubleType.into())),
    ));

    assert!(matches!(
        instruction_rule(&verify_module_types(&module).unwrap_err()),
        TypeRuleError::InvalidBuiltinIdentity {
            builtin,
            expected,
            actual,
        } if builtin == "sin" && expected == "sin" && actual == "cos"
    ));
}

#[test]
fn rejects_a_user_function_alias_with_an_identical_signature() {
    let user_function = IRFunction::new(
        "user_sin",
        vec![IRParameter::new("number", DoubleType.into())],
        DoubleType.into(),
    );
    let mut module = module_with_call(call(
        "user_sin",
        "sin",
        vec![value("number", DoubleType.into())],
        Some(value("result", DoubleType.into())),
    ));
    module.functions.insert(0, user_function);

    assert!(matches!(
        instruction_rule(&verify_module_types(&module).unwrap_err()),
        TypeRuleError::InvalidBuiltinIdentity { actual, .. } if actual == "user_sin"
    ));
}

#[test]
fn canonical_spelling_is_the_identity_even_if_a_same_named_function_is_declared() {
    let same_named_function = IRFunction::new(
        "sin",
        vec![IRParameter::new("number", DoubleType.into())],
        DoubleType.into(),
    );
    let mut module = module_with_call(call(
        "sin",
        "sin",
        vec![value("number", DoubleType.into())],
        Some(value("result", DoubleType.into())),
    ));
    module.functions.insert(0, same_named_function);

    assert_eq!(verify_module_types(&module), Ok(()));
}

#[test]
fn retain_and_release_accept_python_managed_type_allowlist() {
    let struct_type: IRType = StructType {
        name: "Managed".to_owned(),
    }
    .into();
    let managed_types = [
        StringType.into(),
        struct_type.clone(),
        MethodResultType {
            receiver: StructType {
                name: "Managed".to_owned(),
            },
            value: Box::new(IntType.into()),
        }
        .into(),
        ArrayType {
            element: Box::new(IntType.into()),
        }
        .into(),
        ListType {
            element: Box::new(BoolType.into()),
        }
        .into(),
        NullableType {
            inner: Box::new(StringType.into()),
        }
        .into(),
    ];

    for builtin in ["__aether_retain", "__aether_release"] {
        for type_ in &managed_types {
            let mut module = module_with_call(call(
                builtin,
                builtin,
                vec![value("managed", type_.clone())],
                None,
            ));
            module.structs.push(managed_struct());
            assert_eq!(verify_module_types(&module), Ok(()));
        }
    }
}

#[test]
fn retain_rejects_primitive_and_enum_arguments() {
    let enum_type: IRType = EnumType {
        name: "State".to_owned(),
        variants: vec!["ready".to_owned()],
        display_name: None,
    }
    .into();

    for type_ in [IntType.into(), enum_type] {
        let module = module_with_call(call(
            "__aether_retain",
            "__aether_retain",
            vec![value("unsupported", type_.clone())],
            None,
        ));
        assert_eq!(
            instruction_rule(&verify_module_types(&module).unwrap_err()),
            &TypeRuleError::InvalidRetainReleaseType {
                builtin: "__aether_retain".to_owned(),
                actual: type_,
            }
        );
    }
}

#[test]
fn release_rejects_primitive_aggregate_and_other_unsupported_types() {
    let unsupported: [IRType; 3] = [
        BoolType.into(),
        VectorType {
            element: Box::new(IntType.into()),
            orientation: Some("row".to_owned()),
        }
        .into(),
        MatrixType {
            element: Box::new(DoubleType.into()),
        }
        .into(),
    ];

    for type_ in unsupported {
        let module = module_with_call(call(
            "__aether_release",
            "__aether_release",
            vec![value("unsupported", type_.clone())],
            None,
        ));
        assert_eq!(
            instruction_rule(&verify_module_types(&module).unwrap_err()),
            &TypeRuleError::InvalidRetainReleaseType {
                builtin: "__aether_release".to_owned(),
                actual: type_,
            }
        );
    }
}

#[test]
fn retain_rejects_invalid_argument_count() {
    let module = module_with_call(call("__aether_retain", "__aether_retain", Vec::new(), None));

    assert_eq!(
        instruction_rule(&verify_module_types(&module).unwrap_err()),
        &TypeRuleError::InvalidRetainReleaseSignature {
            builtin: "__aether_retain".to_owned(),
            expected_arguments: 1,
            actual_arguments: 0,
            actual_result: None,
        }
    );
}

#[test]
fn retain_rejects_an_unexpected_result() {
    let module = module_with_call(call(
        "__aether_retain",
        "__aether_retain",
        vec![value("managed", StringType.into())],
        Some(value("unexpected", StringType.into())),
    ));

    assert!(matches!(
        instruction_rule(&verify_module_types(&module).unwrap_err()),
        TypeRuleError::InvalidRetainReleaseSignature {
            builtin,
            expected_arguments: 1,
            actual_arguments: 1,
            actual_result: Some(IRType::String(_)),
        } if builtin == "__aether_retain"
    ));
}

#[test]
fn release_rejects_an_invalid_signature() {
    let module = module_with_call(call(
        "__aether_release",
        "__aether_release",
        vec![
            value("first", StringType.into()),
            value("second", StringType.into()),
        ],
        Some(value("unexpected", BoolType.into())),
    ));

    assert!(matches!(
        instruction_rule(&verify_module_types(&module).unwrap_err()),
        TypeRuleError::InvalidRetainReleaseSignature {
            builtin,
            expected_arguments: 1,
            actual_arguments: 2,
            actual_result: Some(IRType::Bool(_)),
        } if builtin == "__aether_release"
    ));
}

#[test]
fn builtin_diagnostics_are_deterministic_and_downcastable() {
    let module = module_with_call(call(
        "renamed_retain",
        "__aether_retain",
        vec![value("managed", StringType.into())],
        None,
    ));
    let first = verify_module_types(&module).unwrap_err();

    for _ in 0..32 {
        let next = verify_module_types(&module).unwrap_err();
        assert_eq!(next, first);
        assert_eq!(next.to_string(), first.to_string());
    }

    let function_error = first
        .source()
        .and_then(|source| source.downcast_ref::<FunctionTypeVerificationError>())
        .expect("module error must source the function error");
    let block_error = function_error
        .source()
        .expect("function error must source the block error");
    let instruction_error = block_error
        .source()
        .and_then(|source| source.downcast_ref::<InstructionTypeVerificationError>())
        .expect("block error must source the instruction error");
    assert_eq!(instruction_error.instruction_kind, InstructionKind::IRCall);
    assert!(instruction_error.source().is_some_and(|source| {
        matches!(
            source.downcast_ref::<TypeRuleError>(),
            Some(TypeRuleError::InvalidBuiltinIdentity {
                builtin,
                expected,
                actual,
            }) if builtin == "__aether_retain"
                && expected == "__aether_retain"
                && actual == "renamed_retain"
        )
    }));
}
