//! Collection copy/slice lifecycle-capability verifier coverage.

use std::error::Error as _;

use aether_ir::{
    ArrayType, ClassRefType, FunctionType, IRBasicBlock, IRFunction, IRInstruction, IRModule,
    IRStructDefinition, IRType, IRValue, IntType, InterfaceType, ListType, MatrixType,
    NullableType, StringType, StructType, VoidType,
};
use aether_verifier::{
    BlockTypeVerificationError, CollectionKind, CollectionLifecycleCapability,
    FunctionTypeVerificationError, InstructionKind, InstructionTypeVerificationError,
    ModuleTypeVerificationError, TypeRuleError, verify_module_types,
};

fn array(element: IRType) -> IRType {
    ArrayType {
        element: Box::new(element),
    }
    .into()
}

fn list(element: IRType) -> IRType {
    ListType {
        element: Box::new(element),
    }
    .into()
}

fn nullable(inner: IRType) -> IRType {
    NullableType {
        inner: Box::new(inner),
    }
    .into()
}

fn collection_module(
    instruction_kind: InstructionKind,
    element_type: IRType,
    structs: Vec<IRStructDefinition>,
) -> IRModule {
    let collection_type = match instruction_kind {
        InstructionKind::IRArrayCopy | InstructionKind::IRArraySlice => array(element_type),
        InstructionKind::IRListCopy | InstructionKind::IRListSlice => list(element_type),
        _ => panic!("unsupported collection lifecycle test instruction"),
    };
    let collection = IRValue::new("collection", collection_type.clone());
    let result = IRValue::new("result", collection_type);
    let start = IRValue::new("start", IntType.into());
    let end = IRValue::new("end", IntType.into());
    let instruction = match instruction_kind {
        InstructionKind::IRArrayCopy => IRInstruction::IRArrayCopy {
            result,
            array: collection,
            source_location: None,
        },
        InstructionKind::IRListCopy => IRInstruction::IRListCopy {
            result,
            list_value: collection,
            source_location: None,
        },
        InstructionKind::IRArraySlice => IRInstruction::IRArraySlice {
            result,
            array: collection,
            start,
            end,
            source_location: None,
        },
        InstructionKind::IRListSlice => IRInstruction::IRListSlice {
            result,
            list_value: collection,
            start,
            end,
            source_location: None,
        },
        _ => unreachable!(),
    };
    let mut block = IRBasicBlock::new("entry");
    block.instructions.push(instruction);
    let mut function = IRFunction::new("main", Vec::new(), VoidType.into());
    function.blocks.push(block);
    IRModule {
        functions: vec![function],
        structs,
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
        name: "Holder".to_owned(),
        fields: vec![(
            "member".to_owned(),
            ClassRefType {
                name: "Box".to_owned(),
            }
            .into(),
        )],
    }
}

#[test]
fn accepts_python_supported_scalar_managed_struct_function_and_nested_elements() {
    let function_type = FunctionType {
        parameter_types: vec![IntType.into()],
        return_type: Box::new(IntType.into()),
    }
    .into();
    let types = [
        IntType.into(),
        StringType.into(),
        StructType {
            name: "Holder".to_owned(),
        }
        .into(),
        function_type,
        list(
            ClassRefType {
                name: "Box".to_owned(),
            }
            .into(),
        ),
        InterfaceType {
            name: "Readable".to_owned(),
        }
        .into(),
    ];

    for instruction in [
        InstructionKind::IRArrayCopy,
        InstructionKind::IRListCopy,
        InstructionKind::IRListSlice,
    ] {
        for element_type in &types {
            let module =
                collection_module(instruction, element_type.clone(), vec![managed_struct()]);
            assert_eq!(verify_module_types(&module), Ok(()));
        }
    }
}

#[test]
fn array_slice_does_not_require_element_lifecycle_support() {
    for element_type in [
        ClassRefType {
            name: "Box".to_owned(),
        }
        .into(),
        nullable(StringType.into()),
        MatrixType {
            element: Box::new(IntType.into()),
        }
        .into(),
    ] {
        let module = collection_module(InstructionKind::IRArraySlice, element_type, Vec::new());
        assert_eq!(verify_module_types(&module), Ok(()));
    }
}

#[test]
fn rejects_missing_direct_element_lifecycle_capabilities() {
    let cases: [(InstructionKind, CollectionKind, IRType, &str); 1] = [(
        InstructionKind::IRListCopy,
        CollectionKind::List,
        MatrixType {
            element: Box::new(IntType.into()),
        }
        .into(),
        "matrix default requires compile-time dimensions",
    )];

    for (instruction, collection_kind, element_type, reason) in cases {
        let module = collection_module(instruction, element_type.clone(), Vec::new());
        assert_eq!(
            instruction_rule(&verify_module_types(&module).unwrap_err()),
            &TypeRuleError::MissingCollectionLifecycleCapability {
                instruction,
                collection_kind,
                element_type,
                capability: CollectionLifecycleCapability::Lifecycle,
                reason: reason.to_owned(),
            }
        );
    }
}

#[test]
fn collection_lifecycle_diagnostic_is_deterministic_and_downcastable() {
    let element_type: IRType = MatrixType {
        element: Box::new(IntType.into()),
    }
    .into();
    let module = collection_module(
        InstructionKind::IRListSlice,
        element_type.clone(),
        Vec::new(),
    );
    let first = verify_module_types(&module).unwrap_err();
    let second = verify_module_types(&module).unwrap_err();

    assert_eq!(first, second);
    assert_eq!(
        first.to_string(),
        "function 0 ('main') failed type verification: block 0 ('entry') of function 'main' failed type verification: type verification failed in function 'main' block 'entry' instruction 0 (IRListSlice): IRListSlice failed type verification: IRListSlice requires lifecycle support for list element type 'matrix<int>': matrix default requires compile-time dimensions"
    );

    let function = (&first as &dyn std::error::Error)
        .source()
        .and_then(|source| source.downcast_ref::<FunctionTypeVerificationError>())
        .expect("module error should expose its function source");
    let block = function
        .source()
        .and_then(|source| source.downcast_ref::<BlockTypeVerificationError>())
        .expect("function error should expose its block source");
    let instruction = block
        .source()
        .and_then(|source| source.downcast_ref::<InstructionTypeVerificationError>())
        .expect("block error should expose its instruction source");
    assert!(matches!(
        instruction
            .source()
            .and_then(|source| source.downcast_ref::<TypeRuleError>()),
        Some(TypeRuleError::MissingCollectionLifecycleCapability {
            instruction: InstructionKind::IRListSlice,
            collection_kind: CollectionKind::List,
            element_type: actual,
            capability: CollectionLifecycleCapability::Lifecycle,
            reason,
        }) if actual == &element_type
            && reason == "matrix default requires compile-time dimensions"
    ));
}
