//! Policy-v1 lifecycle normalization and composed verified-IR lowering.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt;

use crate::wire::{
    IRBasicBlockDTO, IRConstantDTO as C, IRFloatDTO, IRInstructionDTO as I, IRModuleDTO,
    IRStorageDTO, IRStructDefinitionDTO, IRTypeDTO as T, IRValueDTO as V, NullableDTO,
};
use crate::{OwnedSsaModule, SsaLoweringError, lower_normalized_ir_to_ssa_v1};

/// A deterministic, phase-qualified lifecycle normalization failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LifecycleNormalizationError {
    phase: &'static str,
    function: Option<String>,
    message: String,
}

impl LifecycleNormalizationError {
    fn lifecycle(function: Option<&str>, message: impl Into<String>) -> Self {
        Self {
            phase: "lifecycle normalization",
            function: function.map(str::to_owned),
            message: message.into(),
        }
    }
    fn lowering(error: SsaLoweringError) -> Self {
        Self {
            phase: "SSA construction",
            function: None,
            message: error.to_string(),
        }
    }
}
impl fmt::Display for LifecycleNormalizationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if let Some(name) = &self.function {
            write!(
                f,
                "{} failed in function '{}': {}",
                self.phase, name, self.message
            )
        } else {
            write!(f, "{} failed: {}", self.phase, self.message)
        }
    }
}
impl Error for LifecycleNormalizationError {}

/// Normalize a verified Initial-IR DTO without modifying it.
pub fn normalize_lifecycle_v1(
    module: &IRModuleDTO,
    policy_version: i64,
) -> Result<IRModuleDTO, LifecycleNormalizationError> {
    if policy_version != 1 {
        return Err(LifecycleNormalizationError::lifecycle(
            None,
            format!(
                "Unsupported lifecycle normalization policy version {policy_version}; expected 1"
            ),
        ));
    }
    let has_helper = module
        .functions
        .iter()
        .flat_map(|f| &f.blocks)
        .flat_map(|b| &b.instructions)
        .any(is_helper);
    let has_pseudo = module
        .functions
        .iter()
        .flat_map(|f| &f.blocks)
        .flat_map(|b| &b.instructions)
        .any(is_pseudo);
    if has_helper && has_pseudo {
        return Err(LifecycleNormalizationError::lifecycle(
            None,
            "input containing a lifecycle pseudo-instruction and an internal ownership helper is neither legal unnormalized nor normalized IR",
        ));
    }
    if has_helper {
        return Ok(module.clone());
    }
    let definitions: BTreeMap<_, _> = module
        .structs
        .iter()
        .map(|s| (s.name.as_str(), s))
        .collect();
    let mut output = module.clone();
    for function in &mut output.functions {
        let mut owned = BTreeSet::new();
        let mut used = BTreeSet::new();
        let mut remaining = BTreeMap::<String, usize>::new();
        let mut names = BTreeSet::new();
        for parameter in &function.parameters {
            collect_json_names(&serde_json::to_value(parameter).unwrap(), &mut names);
        }
        for block in &function.blocks {
            for instruction in &block.instructions {
                collect_json_names(&serde_json::to_value(instruction).unwrap(), &mut names);
                for operand in instruction_operands(instruction) {
                    used.insert(operand.clone());
                    *remaining.entry(operand).or_default() += 1;
                }
                if let Some(result) = owned_result(instruction, &definitions)? {
                    owned.insert(value_name(result).to_owned());
                }
            }
        }
        let mut next = names
            .iter()
            .filter_map(|n| n.parse::<u64>().ok())
            .max()
            .map_or(0, |n| n + 1);
        let mut temporary = |ty: &T| {
            loop {
                let name = next.to_string();
                next += 1;
                if names.insert(name.clone()) {
                    break V::Value {
                        name,
                        r#type: ty.clone(),
                    };
                }
            }
        };
        for block in &mut function.blocks {
            let old = std::mem::take(&mut block.instructions);
            let mut replacement = Vec::new();
            for instruction in old {
                let operands = instruction_operands(&instruction);
                expand(
                    instruction,
                    &definitions,
                    &mut owned,
                    &used,
                    &remaining,
                    &mut temporary,
                    &mut replacement,
                )
                .map_err(|e| LifecycleNormalizationError::lifecycle(Some(&function.name), e))?;
                for operand in operands {
                    if let Some(count) = remaining.get_mut(&operand) {
                        *count = count.saturating_sub(1);
                    }
                }
            }
            block.instructions = fold_trivial_return_transfer(replacement);
        }
        repair_constructor_invocations(function, &definitions, &mut temporary)
            .map_err(|e| LifecycleNormalizationError::lifecycle(Some(&function.name), e))?;
    }
    if output
        .functions
        .iter()
        .flat_map(|f| &f.blocks)
        .flat_map(|b| &b.instructions)
        .any(is_pseudo)
    {
        return Err(LifecycleNormalizationError::lifecycle(
            None,
            "post-normalization lifecycle pseudo-instruction remains",
        ));
    }
    Ok(output)
}

fn fold_trivial_return_transfer(mut instructions: Vec<I>) -> Vec<I> {
    if instructions.len() < 3 {
        return instructions;
    }
    let length = instructions.len();
    let (slot, stored) = match &instructions[length - 3] {
        I::Store { slot, value } => (slot.clone(), value.clone()),
        _ => return instructions,
    };
    let loaded = match &instructions[length - 2] {
        I::Load {
            result,
            slot: loaded_slot,
        } if loaded_slot == &slot => result.clone(),
        _ => return instructions,
    };
    let transferable = match &instructions[length - 1] {
        I::Return {
            value: return_value,
            transferred_storage,
        } if return_value.0.as_ref() == Some(&loaded)
            && (transferred_storage.0.is_none()
                || transferred_storage
                    .0
                    .as_ref()
                    .is_some_and(|storage| value(storage) == slot)) =>
        {
            true
        }
        _ => false,
    };
    if !transferable {
        return instructions;
    }
    instructions.truncate(length - 3);
    if let Some(I::Load {
        result,
        slot: source_slot,
    }) = instructions.last().cloned()
    {
        if result == stored {
            instructions.pop();
            instructions.push(I::Load {
                result: loaded.clone(),
                slot: source_slot,
            });
            instructions.push(I::Return {
                value: NullableDTO(Some(loaded)),
                transferred_storage: NullableDTO(None),
            });
            return instructions;
        }
    }
    instructions.push(I::Return {
        value: NullableDTO(Some(stored)),
        transferred_storage: NullableDTO(None),
    });
    instructions
}

/// Apply the separately specified edge-specific disposition of an owning
/// direct-constructor receiver. This intentionally recognizes only the
/// policy's `name.__ctor` direct-invoke form; indirect/interface invokes do not
/// carry normative constructor identity.
fn repair_constructor_invocations<F>(
    function: &mut crate::wire::IRFunctionDTO,
    defs: &BTreeMap<&str, &IRStructDefinitionDTO>,
    temporary: &mut F,
) -> Result<(), String>
where
    F: FnMut(&T) -> V,
{
    let mut used_blocks = function
        .blocks
        .iter()
        .map(|block| block.name.clone())
        .collect::<BTreeSet<_>>();
    let mut cleanup_index = 0_u64;
    let mut cleanups = Vec::new();
    let mut normal_releases: BTreeMap<String, Vec<I>> = BTreeMap::new();

    for block in &mut function.blocks {
        for instruction in &mut block.instructions {
            let I::Invoke {
                function: callee,
                arguments,
                normal_target,
                exceptional_target,
                exceptional_target_event,
                ..
            } = instruction
            else {
                continue;
            };
            if !callee.ends_with(".__ctor") || arguments.is_empty() {
                continue;
            }
            let receiver = arguments[0].clone();
            if !matches!(ty(&receiver), T::Struct { .. } | T::ClassRef { .. }) {
                return Err("constructor invoke receiver must be a struct or class owner".into());
            }
            if !traits(ty(&receiver), defs, &mut BTreeSet::new())?.0 {
                continue;
            }

            if matches!(ty(&receiver), T::Struct { .. }) {
                normal_releases
                    .entry(normal_target.clone())
                    .or_default()
                    .push(call("__aether_release", vec![receiver.clone()], None));
            }

            let (cleanup_name, suffix) = loop {
                let suffix = cleanup_index;
                cleanup_index += 1;
                let candidate = format!("constructor.receiver.cleanup{suffix}");
                if used_blocks.insert(candidate.clone()) {
                    break (candidate, suffix);
                }
            };
            let original_target = exceptional_target.clone();
            let original_event = exceptional_target_event.clone();
            let event = temporary(&T::ExceptionEvent {});
            *exceptional_target = cleanup_name.clone();
            *exceptional_target_event = event.clone();
            cleanups.push(IRBasicBlockDTO {
                name: cleanup_name,
                instructions: vec![
                    I::CatchEntry {
                        event: event.clone(),
                        handler_id: format!("constructor_receiver_cleanup{suffix}"),
                        catch_types: vec![],
                    },
                    call("__aether_release", vec![receiver], None),
                    I::Propagate {
                        event,
                        target: NullableDTO(Some(original_target)),
                        target_event: NullableDTO(Some(original_event)),
                    },
                ],
            });
        }
    }

    for block in &mut function.blocks {
        if let Some(mut releases) = normal_releases.remove(&block.name) {
            releases.append(&mut block.instructions);
            block.instructions = releases;
        }
    }
    function.blocks.extend(cleanups);
    Ok(())
}

/// Complete policy-v1 composition. The input DTO is borrowed and remains unchanged.
pub fn lower_verified_ir_to_ssa_v1(
    module: &IRModuleDTO,
    lowering_policy_version: i64,
    lifecycle_policy_version: i64,
) -> Result<OwnedSsaModule, LifecycleNormalizationError> {
    if lowering_policy_version != 1 {
        return Err(LifecycleNormalizationError::lifecycle(
            None,
            format!(
                "Unsupported SSA lowering policy version {lowering_policy_version}; expected 1"
            ),
        ));
    }
    let normalized = normalize_lifecycle_v1(module, lifecycle_policy_version)?;
    lower_normalized_ir_to_ssa_v1(&normalized).map_err(LifecycleNormalizationError::lowering)
}

fn is_pseudo(i: &I) -> bool {
    matches!(
        i,
        I::InitDefault { .. }
            | I::CopyInit { .. }
            | I::MoveInit { .. }
            | I::Assign { .. }
            | I::Destroy { .. }
            | I::Relocate { .. }
    )
}
fn is_helper(i: &I) -> bool {
    matches!(i, I::Call { builtin: NullableDTO(Some(b)), .. }
    if matches!(b.as_str(), "__aether_retain"|"__aether_release"|"__aether_interface_copy_owned"))
}
fn collect_json_names(value: &serde_json::Value, names: &mut BTreeSet<String>) {
    match value {
        serde_json::Value::Array(a) => {
            for v in a {
                collect_json_names(v, names)
            }
        }
        serde_json::Value::Object(o) => {
            if matches!(
                o.get("tag").and_then(|v| v.as_str()),
                Some("value" | "storage" | "parameter")
            ) {
                if let Some(n) = o.get("name").and_then(|v| v.as_str()) {
                    names.insert(n.to_owned());
                }
            }
            for v in o.values() {
                collect_json_names(v, names);
            }
        }
        _ => {}
    }
}
fn instruction_operands(instruction: &I) -> Vec<String> {
    let mut json = serde_json::to_value(instruction).expect("instruction serialization");
    if let serde_json::Value::Object(object) = &mut json {
        object.remove("result");
        object.remove("destination");
        object.remove("source_location");
    }
    let mut operands = Vec::new();
    fn visit(value: &serde_json::Value, operands: &mut Vec<String>) {
        match value {
            serde_json::Value::Array(values) => {
                for value in values {
                    visit(value, operands);
                }
            }
            serde_json::Value::Object(object) => {
                if matches!(
                    object.get("tag").and_then(|value| value.as_str()),
                    Some("value" | "storage" | "parameter")
                ) {
                    if let Some(name) = object.get("name").and_then(|value| value.as_str()) {
                        operands.push(name.to_owned());
                        return;
                    }
                }
                for value in object.values() {
                    visit(value, operands);
                }
            }
            _ => {}
        }
    }
    visit(&json, &mut operands);
    operands
}
fn value(storage: &IRStorageDTO) -> V {
    match storage {
        IRStorageDTO::Storage { name, r#type } => V::Storage {
            name: name.clone(),
            r#type: r#type.clone(),
        },
    }
}
fn ty(v: &V) -> &T {
    match v {
        V::Value { r#type, .. } | V::Storage { r#type, .. } | V::Parameter { r#type, .. } => r#type,
    }
}
fn value_name(v: &V) -> &str {
    match v {
        V::Value { name, .. } | V::Storage { name, .. } | V::Parameter { name, .. } => name,
    }
}
fn owned_result<'a>(
    i: &'a I,
    defs: &BTreeMap<&str, &IRStructDefinitionDTO>,
) -> Result<Option<&'a V>, LifecycleNormalizationError> {
    let result = match i {
        I::Call {
            result: NullableDTO(v),
            ..
        }
        | I::CallIndirect {
            result: NullableDTO(v),
            ..
        }
        | I::InterfaceCall {
            result: NullableDTO(v),
            ..
        } => v.as_ref(),
        I::BinaryOp {
            result, operator, ..
        } if operator == "add" && matches!(ty(result), T::String {}) => Some(result),
        I::ArrayGet {
            result,
            borrowed: false,
            ..
        }
        | I::ListGet {
            result,
            borrowed: false,
            ..
        }
        | I::ListPop { result, .. }
        | I::ListRemoveAt { result, .. }
        | I::ArrayNew { result, .. }
        | I::ListNew { result, .. }
        | I::ArrayCopy { result, .. }
        | I::ListCopy { result, .. }
        | I::ArraySlice { result, .. }
        | I::ListSlice { result, .. }
        | I::StructNew { result, .. }
        | I::StructSet { result, .. }
        | I::MethodResultNew { result, .. }
        | I::ClassNew { result }
        | I::InterfaceConstruct { result, .. }
        | I::ClassGet { result, .. } => Some(result),
        _ => None,
    };
    match result {
        Some(v)
            if traits(ty(v), defs, &mut BTreeSet::new())
                .map_err(|e| LifecycleNormalizationError::lifecycle(None, e))?
                .0 =>
        {
            Ok(Some(v))
        }
        _ => Ok(None),
    }
}
fn store(slot: &IRStorageDTO, value_: V) -> I {
    I::Store {
        slot: value(slot),
        value: value_,
    }
}
fn load(slot: &IRStorageDTO, temporary: V) -> I {
    I::Load {
        result: temporary,
        slot: value(slot),
    }
}
fn call(name: &str, args: Vec<V>, result: Option<V>) -> I {
    I::Call {
        function: name.into(),
        arguments: args,
        result: NullableDTO(result),
        builtin: NullableDTO(Some(name.into())),
        source_location: NullableDTO(None),
        may_throw: false,
    }
}

fn expand<F>(
    instruction: I,
    defs: &BTreeMap<&str, &IRStructDefinitionDTO>,
    owned: &mut BTreeSet<String>,
    used: &BTreeSet<String>,
    remaining: &BTreeMap<String, usize>,
    temporary: &mut F,
    out: &mut Vec<I>,
) -> Result<(), String>
where
    F: FnMut(&T) -> V,
{
    match instruction {
        I::ClassGet {
            result,
            object,
            field_index,
            field_name,
        } => {
            let result_owned = traits(ty(&result), defs, &mut BTreeSet::new())?.0;
            out.push(I::ClassGet {
                result: result.clone(),
                object: object.clone(),
                field_index,
                field_name,
            });
            if result_owned {
                out.push(call("__aether_retain", vec![result.clone()], None));
            }
            release_consumed_owner(&object, owned, out);
            release_unused_result(&result, used, owned, out);
        }
        I::StructNew { result, fields } => {
            for field in &fields {
                acquire_aggregate_field(field, defs, owned, out)?;
            }
            out.push(I::StructNew {
                result: result.clone(),
                fields,
            });
            release_unused_result(&result, used, owned, out);
        }
        I::StructSet {
            result,
            r#struct,
            field_index,
            field_name,
            value: field_value,
        } => {
            acquire_aggregate_field(&field_value, defs, owned, out)?;
            let struct_traits = traits(ty(&r#struct), defs, &mut BTreeSet::new())?;
            if !owned.remove(value_name(&r#struct)) && struct_traits.0 {
                out.push(call("__aether_retain", vec![r#struct.clone()], None));
            }
            let field_type = match ty(&r#struct) {
                T::Struct { name } => defs
                    .get(name.as_str())
                    .and_then(|definition| definition.fields.get(field_index as usize))
                    .map(|field| &field.r#type),
                _ => None,
            }
            .ok_or_else(|| "struct_set field has no nominal definition".to_owned())?;
            if traits(field_type, defs, &mut BTreeSet::new())?.0 {
                let old = temporary(field_type);
                out.push(I::StructGet {
                    result: old.clone(),
                    r#struct: r#struct.clone(),
                    field_index,
                    field_name: field_name.clone(),
                });
                out.push(call("__aether_release", vec![old], None));
            }
            out.push(I::StructSet {
                result: result.clone(),
                r#struct,
                field_index,
                field_name,
                value: field_value,
            });
            if struct_traits.0 {
                owned.insert(value_name(&result).to_owned());
            }
            release_unused_result(&result, used, owned, out);
        }
        I::MethodResultNew {
            result,
            receiver,
            value: result_value,
        } => {
            acquire_aggregate_field(&receiver, defs, owned, out)?;
            if let Some(field) = &result_value.0 {
                acquire_aggregate_field(field, defs, owned, out)?;
            }
            out.push(I::MethodResultNew {
                result: result.clone(),
                receiver,
                value: result_value,
            });
            release_unused_result(&result, used, owned, out);
        }
        I::InterfaceConstruct {
            result,
            carrier,
            witness,
        } => {
            if matches!(ty(&carrier), T::Struct { .. }) {
                out.push(I::InterfaceConstruct {
                    result: result.clone(),
                    carrier: carrier.clone(),
                    witness,
                });
                release_consumed_owner(&carrier, owned, out);
            } else {
                if !owned.remove(value_name(&carrier)) {
                    out.push(call("__aether_retain", vec![carrier.clone()], None));
                }
                out.push(I::InterfaceConstruct {
                    result: result.clone(),
                    carrier,
                    witness,
                });
            }
            release_unused_result(&result, used, owned, out);
        }
        I::BinaryOp {
            result,
            operator,
            left,
            right,
            source_location,
        } if operator == "add" && matches!(ty(&result), T::String {}) => {
            out.push(I::BinaryOp {
                result: result.clone(),
                operator,
                left: left.clone(),
                right: right.clone(),
                source_location,
            });
            release_consumed_owner(&left, owned, out);
            release_consumed_owner(&right, owned, out);
            release_unused_result(&result, used, owned, out);
        }
        I::CompareOp {
            result,
            operator,
            left,
            right,
            aggregate_shape,
        } if matches!(operator.as_str(), "eq" | "ne")
            && traits(ty(&left), defs, &mut BTreeSet::new())?.0 =>
        {
            let current = instruction_operands(&I::CompareOp {
                result: result.clone(),
                operator: operator.clone(),
                left: left.clone(),
                right: right.clone(),
                aggregate_shape: aggregate_shape.clone(),
            });
            out.push(I::CompareOp {
                result,
                operator,
                left: left.clone(),
                right: right.clone(),
                aggregate_shape,
            });
            for operand in [&left, &right] {
                let name = value_name(operand);
                let current_uses = current.iter().filter(|item| item.as_str() == name).count();
                if owned.contains(name) && remaining.get(name).copied().unwrap_or(0) <= current_uses
                {
                    release_consumed_owner(operand, owned, out);
                }
            }
        }
        I::ListPush {
            list_value,
            value: pushed,
        } => {
            out.push(I::ListPush {
                list_value,
                value: pushed.clone(),
            });
            release_consumed_owner(&pushed, owned, out);
        }
        I::ArrayNew { result, elements } => {
            out.push(I::ArrayNew {
                result: result.clone(),
                elements: elements.clone(),
            });
            for element in &elements {
                release_consumed_owner(element, owned, out);
            }
            release_unused_result(&result, used, owned, out);
        }
        I::ListNew { result, elements } => {
            out.push(I::ListNew {
                result: result.clone(),
                elements: elements.clone(),
            });
            for element in &elements {
                release_consumed_owner(element, owned, out);
            }
            release_unused_result(&result, used, owned, out);
        }
        I::ClassSet {
            object,
            field_index,
            field_name,
            value: field_value,
            initialize,
        } => {
            out.push(I::ClassSet {
                object,
                field_index,
                field_name,
                value: field_value.clone(),
                initialize,
            });
            release_consumed_owner(&field_value, owned, out);
        }
        I::ArrayGet {
            result,
            array,
            index,
            borrowed,
            borrow_scope,
            source_location,
        } => {
            out.push(I::ArrayGet {
                result: result.clone(),
                array: array.clone(),
                index,
                borrowed,
                borrow_scope,
                source_location,
            });
            release_consumed_owner(&array, owned, out);
            release_unused_result(&result, used, owned, out);
        }
        I::ListGet {
            result,
            list_value,
            index,
            borrowed,
            borrow_scope,
            source_location,
        } => {
            out.push(I::ListGet {
                result: result.clone(),
                list_value: list_value.clone(),
                index,
                borrowed,
                borrow_scope,
                source_location,
            });
            release_consumed_owner(&list_value, owned, out);
            release_unused_result(&result, used, owned, out);
        }
        I::MethodResultReceiver {
            result,
            method_result,
        } => {
            owned.remove(value_name(&method_result));
            if traits(ty(&result), defs, &mut BTreeSet::new())?.0 {
                owned.insert(value_name(&result).to_owned());
            }
            out.push(I::MethodResultReceiver {
                result: result.clone(),
                method_result,
            });
            release_unused_result(&result, used, owned, out);
        }
        I::MethodResultValue {
            result,
            method_result,
        } => {
            if traits(ty(&result), defs, &mut BTreeSet::new())?.0 {
                owned.insert(value_name(&result).to_owned());
            }
            out.push(I::MethodResultValue {
                result: result.clone(),
                method_result,
            });
            release_unused_result(&result, used, owned, out);
        }
        I::Call {
            function,
            arguments,
            result,
            builtin,
            source_location,
            may_throw,
        } => {
            out.push(I::Call {
                function: function.clone(),
                arguments: arguments.clone(),
                result: result.clone(),
                builtin,
                source_location,
                may_throw,
            });
            for (index, argument) in arguments.iter().enumerate() {
                if !(function.ends_with(".__ctor") && index == 0) {
                    release_consumed_owner(argument, owned, out);
                }
            }
            if let Some(result) = &result.0 {
                release_unused_result(result, used, owned, out);
            }
        }
        I::Print {
            value: printed,
            newline,
            aggregate_shape,
        } => {
            out.push(I::Print {
                value: printed.clone(),
                newline,
                aggregate_shape,
            });
            release_consumed_owner(&printed, owned, out);
        }
        I::InitDefault { destination, .. } => {
            let (_, t) = storage_parts(&destination);
            let v = default_value(t, defs, temporary, out, &mut BTreeSet::new())?;
            out.push(store(&destination, v));
        }
        I::CopyInit {
            destination,
            source,
            ..
        } => copy_assign(destination, source, false, defs, owned, temporary, out)?,
        I::Assign {
            destination,
            source,
            ..
        } => copy_assign(destination, source, true, defs, owned, temporary, out)?,
        I::MoveInit {
            destination,
            source,
            ..
        } => {
            let (_, t) = storage_parts(&source);
            let tmp = temporary(t);
            out.push(load(&source, tmp.clone()));
            out.push(store(&destination, tmp));
            if traits(t, defs, &mut BTreeSet::new())?.0 {
                let empty = default_value(t, defs, temporary, out, &mut BTreeSet::new())?;
                out.push(store(&source, empty));
            }
        }
        I::Relocate {
            destination,
            source,
            ..
        } => {
            let (_, t) = storage_parts(&source);
            let tmp = temporary(t);
            out.push(load(&source, tmp.clone()));
            out.push(store(&destination, tmp));
        }
        I::Destroy { value: v, .. } => {
            let (_, t) = storage_parts(&v);
            if traits(t, defs, &mut BTreeSet::new())?.0 {
                let tmp = temporary(t);
                out.push(load(&v, tmp.clone()));
                out.push(call("__aether_release", vec![tmp], None));
            }
        }
        I::Return {
            value: v,
            transferred_storage: NullableDTO(Some(_)),
        } => out.push(I::Return {
            value: v,
            transferred_storage: NullableDTO(None),
        }),
        other => out.push(other),
    }
    Ok(())
}
fn acquire_aggregate_field(
    field: &V,
    defs: &BTreeMap<&str, &IRStructDefinitionDTO>,
    owned: &mut BTreeSet<String>,
    out: &mut Vec<I>,
) -> Result<(), String> {
    if traits(ty(field), defs, &mut BTreeSet::new())?.0 {
        if !owned.remove(value_name(field)) {
            out.push(call("__aether_retain", vec![field.clone()], None));
        }
    }
    Ok(())
}
fn release_consumed_owner(value: &V, owned: &mut BTreeSet<String>, out: &mut Vec<I>) {
    if owned.remove(value_name(value)) {
        out.push(call("__aether_release", vec![value.clone()], None));
    }
}
fn release_unused_result(
    result: &V,
    used: &BTreeSet<String>,
    owned: &mut BTreeSet<String>,
    out: &mut Vec<I>,
) {
    let name = value_name(result);
    if !used.contains(name) && owned.remove(name) {
        out.push(call("__aether_release", vec![result.clone()], None));
    }
}
fn copy_assign<F>(
    destination: IRStorageDTO,
    source: V,
    assign: bool,
    defs: &BTreeMap<&str, &IRStructDefinitionDTO>,
    owned: &mut BTreeSet<String>,
    temporary: &mut F,
    out: &mut Vec<I>,
) -> Result<(), String>
where
    F: FnMut(&T) -> V,
{
    let was_storage = matches!(source, V::Storage { .. });
    let source = if was_storage {
        let tmp = temporary(ty(&source));
        out.push(I::Load {
            result: tmp.clone(),
            slot: source,
        });
        tmp
    } else {
        source
    };
    if !traits(ty(&source), defs, &mut BTreeSet::new())?.0 {
        out.push(store(&destination, source));
        return Ok(());
    }
    let incoming = if !was_storage && owned.remove(value_name(&source)) {
        source
    } else if contains_interface(ty(&source), defs, &mut BTreeSet::new())? {
        let copy = temporary(ty(&source));
        out.push(call(
            "__aether_interface_copy_owned",
            vec![source],
            Some(copy.clone()),
        ));
        copy
    } else {
        out.push(call("__aether_retain", vec![source.clone()], None));
        source
    };
    if assign {
        let (_, dt) = storage_parts(&destination);
        let old = temporary(dt);
        out.push(load(&destination, old.clone()));
        out.push(store(&destination, incoming));
        out.push(call("__aether_release", vec![old], None));
    } else {
        out.push(store(&destination, incoming));
    }
    Ok(())
}
fn storage_parts(s: &IRStorageDTO) -> (&str, &T) {
    match s {
        IRStorageDTO::Storage { name, r#type } => (name, r#type),
    }
}
// Returns (needs_destroy, supports_default).
fn traits(
    t: &T,
    defs: &BTreeMap<&str, &IRStructDefinitionDTO>,
    active: &mut BTreeSet<String>,
) -> Result<(bool, bool), String> {
    Ok(match t {
        T::String {} | T::Array { .. } | T::List { .. } => (true, true),
        T::ClassRef { .. } | T::Interface { .. } => (true, false),
        T::Nullable { inner } => (traits(inner, defs, active)?.0, true),
        T::Struct { name } => aggregate(name, defs, active)?,
        T::MethodResult { receiver, value } => {
            let a = traits(receiver, defs, active)?;
            let b = traits(value, defs, active)?;
            (a.0 || b.0, a.1 && b.1)
        }
        T::Vector { orientation, .. } => (
            false,
            matches!(&orientation.0,Some(v) if v=="row"||v=="column"),
        ),
        T::Matrix { .. } | T::Function { .. } => (false, false),
        T::Void {} | T::ExceptionEvent {} => (false, false),
        _ => (false, true),
    })
}
fn aggregate(
    name: &str,
    defs: &BTreeMap<&str, &IRStructDefinitionDTO>,
    active: &mut BTreeSet<String>,
) -> Result<(bool, bool), String> {
    let d = defs
        .get(name)
        .ok_or_else(|| format!("nominal struct '{name}' has no definition"))?;
    if !active.insert(name.into()) {
        return Err("recursive layout".into());
    }
    let mut destroy = false;
    let mut default = true;
    for f in &d.fields {
        let x = traits(&f.r#type, defs, active)?;
        destroy |= x.0;
        default &= x.1;
    }
    active.remove(name);
    Ok((destroy, default))
}
fn contains_interface(
    t: &T,
    defs: &BTreeMap<&str, &IRStructDefinitionDTO>,
    active: &mut BTreeSet<String>,
) -> Result<bool, String> {
    Ok(match t {
        T::Interface { .. } => true,
        T::Nullable { inner } => contains_interface(inner, defs, active)?,
        T::MethodResult { receiver, value } => {
            contains_interface(receiver, defs, active)? || contains_interface(value, defs, active)?
        }
        T::Struct { name } => {
            if !active.insert(name.clone()) {
                false
            } else {
                let d = defs
                    .get(name.as_str())
                    .ok_or_else(|| format!("nominal struct '{name}' has no definition"))?;
                let x = d.fields.iter().try_fold(false, |a, f| {
                    Ok::<_, String>(a || contains_interface(&f.r#type, defs, active)?)
                })?;
                active.remove(name);
                x
            }
        }
        _ => false,
    })
}
fn default_value<F>(
    t: &T,
    defs: &BTreeMap<&str, &IRStructDefinitionDTO>,
    temporary: &mut F,
    out: &mut Vec<I>,
    active: &mut BTreeSet<String>,
) -> Result<V, String>
where
    F: FnMut(&T) -> V,
{
    if let T::Struct { name } = t {
        if !active.insert(name.clone()) {
            return Err("recursive layout".into());
        }
        let d = defs
            .get(name.as_str())
            .ok_or_else(|| format!("nominal struct '{name}' has no definition"))?;
        let mut fields = Vec::new();
        for f in &d.fields {
            fields.push(default_value(&f.r#type, defs, temporary, out, active)?)
        }
        active.remove(name);
        let result = temporary(t);
        out.push(I::StructNew {
            result: result.clone(),
            fields,
        });
        return Ok(result);
    }
    let result = temporary(t);
    let instruction = match t {
        T::Struct { .. } => unreachable!("struct defaults handled above"),
        T::Array { .. } => I::ArrayNew {
            result: result.clone(),
            elements: vec![],
        },
        T::List { .. } => I::ListNew {
            result: result.clone(),
            elements: vec![],
        },
        T::Nullable { .. } => I::Const {
            result: result.clone(),
            value: C::Null,
        },
        T::Vector { orientation, .. } if orientation.0.is_some() => I::VectorNew {
            result: result.clone(),
            elements: vec![],
            orientation: orientation.clone(),
        },
        T::Enum { name, variants, .. } => {
            let member = variants
                .first()
                .ok_or_else(|| format!("enum '{name}' has no default variant"))?;
            I::Const {
                result: result.clone(),
                value: C::Enum {
                    value: crate::wire::IREnumConstantDTO::EnumConstant {
                        enum_name: name.clone(),
                        member_name: member.clone(),
                        member_id: 0,
                        discriminant: 0,
                    },
                },
            }
        }
        T::Bool {} => I::Const {
            result: result.clone(),
            value: C::Bool { value: false },
        },
        T::Int {} => I::Const {
            result: result.clone(),
            value: C::Int { value: 0 },
        },
        T::String {} => I::Const {
            result: result.clone(),
            value: C::String {
                value: String::new(),
            },
        },
        T::Float {} | T::Double {} => I::Const {
            result: result.clone(),
            value: C::Float {
                value: IRFloatDTO(0.0),
            },
        },
        T::Complex {} => I::Const {
            result: result.clone(),
            value: C::Complex {
                real: IRFloatDTO(0.0),
                imaginary: IRFloatDTO(0.0),
            },
        },
        _ => return Err(format!("type '{t:?}' has no lifecycle default")),
    };
    out.push(instruction);
    Ok(result)
}
