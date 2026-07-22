//! Focused IRV-026 canonical-import and return-operand regression coverage.

use aether_ir::{IRInstruction, LifecycleSource, import_module_json};
use aether_verifier::{
    FunctionTypeVerificationError, ModuleTypeVerificationError, TypeRuleError,
    verify_module_dominance, verify_module_lifecycle, verify_module_returns, verify_module_ssa,
    verify_module_structure, verify_module_types,
};

fn module_json(parameters: &str, instructions: &str) -> String {
    format!(
        r#"{{
  "schema_version": 1,
  "structs": [],
  "functions": [{{
    "name": "return_operand",
    "parameters": [{parameters}],
    "return_type": {{"tag": "int"}},
    "blocks": [{{
      "name": "entry",
      "instructions": [{instructions}]
    }}]
  }}]
}}"#
    )
}

fn value(tag: &str, name: &str) -> String {
    format!(r#"{{"tag":"{tag}","name":"{name}","type":{{"tag":"int"}}}}"#)
}

fn return_instruction(tag: &str, name: &str) -> String {
    format!(
        r#"{{"kind":"return","value":{},"transferred_storage":null}}"#,
        value(tag, name)
    )
}

fn storage_return_module(storage_name: &str, parameters: &str) -> String {
    let storage = value("storage", storage_name);
    module_json(
        parameters,
        &format!(
            r#"{{"kind":"init_default","destination":{storage},"source_location":null}},{}"#,
            return_instruction("storage", storage_name)
        ),
    )
}

fn instruction_rule(error: &ModuleTypeVerificationError) -> &TypeRuleError {
    let ModuleTypeVerificationError::Function { source, .. } = error else {
        panic!("expected function context")
    };
    let FunctionTypeVerificationError::Block { source, .. } = source else {
        panic!("expected block context")
    };
    &source.source.source
}

fn assert_all_verifiers_accept(json: &str) {
    let module = import_module_json(json).expect("canonical return module must import");
    assert_eq!(verify_module_structure(&module), Ok(()));
    assert_eq!(verify_module_types(&module), Ok(()));
    assert_eq!(verify_module_ssa(&module), Ok(()));
    assert_eq!(verify_module_dominance(&module), Ok(()));
    assert_eq!(verify_module_lifecycle(&module), Ok(()));
    assert_eq!(verify_module_returns(&module), Ok(()));
}

#[test]
fn canonical_ssa_constant_and_expression_returns_remain_valid() {
    let parameter = value("parameter", "value");
    assert_all_verifiers_accept(&module_json(
        &parameter,
        &return_instruction("parameter", "value"),
    ));

    let result = value("value", "result");
    assert_all_verifiers_accept(&module_json(
        "",
        &format!(
            r#"{{"kind":"const","result":{result},"value":{{"tag":"int","value":1}}}},{}"#,
            return_instruction("value", "result")
        ),
    ));

    let left = value("parameter", "left");
    let right = value("parameter", "right");
    let sum = value("value", "sum");
    assert_all_verifiers_accept(&module_json(
        &format!("{left},{right}"),
        &format!(
            r#"{{"kind":"binary_op","result":{sum},"operator":"add","left":{left},"right":{right},"source_location":null}},{}"#,
            return_instruction("value", "sum")
        ),
    ));
}

#[test]
fn canonical_storage_return_is_rejected_as_irv026() {
    for json in [
        storage_return_module("slot", ""),
        storage_return_module("x", &value("parameter", "x")),
    ] {
        let module = import_module_json(&json).expect("canonical storage return must import");
        let return_operand = &module.functions[0].blocks[0].instructions[1];
        assert!(matches!(
            return_operand,
            IRInstruction::IRReturn {
                value: Some(LifecycleSource::Storage(storage)),
                ..
            } if storage.name == if module.functions[0].parameters.is_empty() { "slot" } else { "x" }
        ));

        let error = verify_module_types(&module).unwrap_err();
        assert_eq!(
            instruction_rule(&error),
            &TypeRuleError::StorageReturnOperand {
                storage: if module.functions[0].parameters.is_empty() {
                    "slot".to_owned()
                } else {
                    "x".to_owned()
                },
            }
        );
        assert!(error.to_string().contains("IRV-026"));
    }
}
