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
        let mut names = BTreeSet::new();
        for parameter in &function.parameters {
            collect_json_names(&serde_json::to_value(parameter).unwrap(), &mut names);
        }
        for block in &function.blocks {
            for instruction in &block.instructions {
                collect_json_names(&serde_json::to_value(instruction).unwrap(), &mut names);
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
                expand(
                    instruction,
                    &definitions,
                    &mut owned,
                    &mut temporary,
                    &mut replacement,
                )
                .map_err(|e| LifecycleNormalizationError::lifecycle(Some(&function.name), e))?;
            }
            block.instructions = replacement;
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
    temporary: &mut F,
    out: &mut Vec<I>,
) -> Result<(), String>
where
    F: FnMut(&T) -> V,
{
    match instruction {
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
    let result = temporary(t);
    let instruction = match t {
        T::Struct { name } => {
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
            I::StructNew {
                result: result.clone(),
                fields,
            }
        }
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
