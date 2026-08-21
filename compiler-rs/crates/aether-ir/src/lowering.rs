//! Deterministic Initial IR schema-v1 to SSA schema-v2 lowering.
//!
//! This module implements lowering policy v1 at the frozen wire boundary.  It
//! deliberately does not consult SSA constructor defaults: the eight collection
//! access instructions synthesize `bounds_checked = true` here.

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::error::Error;
use std::fmt;

use serde_json::Value;

use crate::OwnedSsaModule;
use crate::wire::{
    IRFunctionDTO, IRInstructionDTO, IRModuleDTO, NullableDTO, SSA_SCHEMA_VERSION_V2,
    SSABasicBlockV2DTO, SSAFunctionV2DTO, SSAInstructionV2DTO, SSAModuleV2DTO,
};

/// A deterministic, stage-qualified lowering failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SsaLoweringError {
    function: Option<String>,
    message: String,
}

impl SsaLoweringError {
    fn module(message: impl Into<String>) -> Self {
        Self {
            function: None,
            message: message.into(),
        }
    }

    fn function(function: &str, message: impl Into<String>) -> Self {
        Self {
            function: Some(function.into()),
            message: message.into(),
        }
    }
}

impl fmt::Display for SsaLoweringError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match &self.function {
            Some(function) => write!(
                formatter,
                "SSA lowering failed in function '{function}': {}",
                self.message
            ),
            None => write!(formatter, "SSA lowering failed: {}", self.message),
        }
    }
}
impl Error for SsaLoweringError {}

/// Lower verified, lifecycle-normalized Initial IR under policy v1.
///
/// Lifecycle pseudo-instructions are outside this entry point's domain until
/// their separately qualified Rust normalization pass has run.  Failing closed
/// here prevents partially lowered SSA from escaping.
pub fn lower_normalized_ir_to_ssa_v1(
    module: &IRModuleDTO,
) -> Result<OwnedSsaModule, SsaLoweringError> {
    let dto = lower_to_dto(module)?;
    OwnedSsaModule::from_schema_v2(&dto)
        .map_err(|error| SsaLoweringError::module(format!("owned SSA construction: {error}")))
}

fn lower_to_dto(module: &IRModuleDTO) -> Result<SSAModuleV2DTO, SsaLoweringError> {
    let functions = module
        .functions
        .iter()
        .map(lower_function)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(SSAModuleV2DTO {
        schema_version: SSA_SCHEMA_VERSION_V2,
        representation: "aether_ssa".into(),
        functions,
        structs: module.structs.clone(),
    })
}

#[derive(Clone)]
struct PhiState {
    slot: String,
    result: Value,
    incoming: Vec<Value>,
}

struct FunctionLowerer<'a> {
    function: &'a IRFunctionDTO,
    block_index: BTreeMap<String, usize>,
    successors: BTreeMap<String, Vec<String>>,
    predecessors: BTreeMap<String, Vec<String>>,
    reachable: BTreeSet<String>,
    idom: BTreeMap<String, Option<String>>,
    children: BTreeMap<String, Vec<String>>,
    phis: BTreeMap<String, Vec<PhiState>>,
    stacks: BTreeMap<String, Vec<Value>>,
    bindings: BTreeMap<String, Value>,
    definitions: BTreeSet<String>,
    output: BTreeMap<String, Vec<SSAInstructionV2DTO>>,
}

fn lower_function(function: &IRFunctionDTO) -> Result<SSAFunctionV2DTO, SsaLoweringError> {
    if function.blocks.is_empty() {
        return Err(SsaLoweringError::function(
            &function.name,
            "function has no entry block",
        ));
    }
    for block in &function.blocks {
        for instruction in &block.instructions {
            if matches!(
                instruction,
                IRInstructionDTO::InitDefault { .. }
                    | IRInstructionDTO::CopyInit { .. }
                    | IRInstructionDTO::MoveInit { .. }
                    | IRInstructionDTO::Assign { .. }
                    | IRInstructionDTO::Destroy { .. }
                    | IRInstructionDTO::Relocate { .. }
            ) {
                return Err(SsaLoweringError::function(
                    &function.name,
                    "lifecycle normalization must run before SSA construction",
                ));
            }
        }
    }

    let mut lowerer = FunctionLowerer::new(function)?;
    lowerer.place_phis()?;
    lowerer.initialize()?;
    let entry = function.blocks[0].name.clone();
    lowerer.rename_block(&entry)?;
    lowerer.finish()
}

impl<'a> FunctionLowerer<'a> {
    fn new(function: &'a IRFunctionDTO) -> Result<Self, SsaLoweringError> {
        let mut block_index = BTreeMap::new();
        for (index, block) in function.blocks.iter().enumerate() {
            if block_index.insert(block.name.clone(), index).is_some() {
                return Err(SsaLoweringError::function(
                    &function.name,
                    format!("duplicate block '{}'", block.name),
                ));
            }
        }
        let mut successors = BTreeMap::new();
        for block in &function.blocks {
            let next = block
                .instructions
                .last()
                .map(successors_of)
                .unwrap_or_default();
            for target in &next {
                if !block_index.contains_key(target) {
                    return Err(SsaLoweringError::function(
                        &function.name,
                        format!("block '{}' targets unknown block '{target}'", block.name),
                    ));
                }
            }
            successors.insert(block.name.clone(), next);
        }
        let entry = function.blocks[0].name.clone();
        let mut reachable = BTreeSet::new();
        let mut queue = VecDeque::from([entry.clone()]);
        while let Some(block) = queue.pop_front() {
            if reachable.insert(block.clone()) {
                queue.extend(successors[&block].iter().cloned());
            }
        }
        let mut predecessors: BTreeMap<String, Vec<String>> =
            reachable.iter().map(|b| (b.clone(), Vec::new())).collect();
        for block in function
            .blocks
            .iter()
            .filter(|b| reachable.contains(&b.name))
        {
            for target in &successors[&block.name] {
                if reachable.contains(target) {
                    predecessors
                        .get_mut(target)
                        .expect("reachable target")
                        .push(block.name.clone());
                }
            }
        }
        let dominators = compute_dominators(function, &predecessors, &reachable);
        let mut idom = BTreeMap::new();
        for block in function
            .blocks
            .iter()
            .filter(|b| reachable.contains(&b.name))
        {
            if block.name == entry {
                idom.insert(block.name.clone(), None);
                continue;
            }
            let strict = dominators[&block.name].iter().filter(|d| *d != &block.name);
            let chosen = strict
                .max_by_key(|d| (dominators[*d].len(), block_index[*d]))
                .cloned();
            idom.insert(block.name.clone(), chosen);
        }
        let mut children: BTreeMap<String, Vec<String>> =
            reachable.iter().map(|b| (b.clone(), Vec::new())).collect();
        for block in function
            .blocks
            .iter()
            .filter(|b| reachable.contains(&b.name))
        {
            if let Some(parent) = &idom[&block.name] {
                children
                    .get_mut(parent)
                    .expect("idom")
                    .push(block.name.clone());
            }
        }
        Ok(Self {
            function,
            block_index,
            successors,
            predecessors,
            reachable,
            idom,
            children,
            phis: BTreeMap::new(),
            stacks: BTreeMap::new(),
            bindings: BTreeMap::new(),
            definitions: BTreeSet::new(),
            output: BTreeMap::new(),
        })
    }

    fn fail(&self, message: impl Into<String>) -> SsaLoweringError {
        SsaLoweringError::function(&self.function.name, message)
    }

    fn initialize(&mut self) -> Result<(), SsaLoweringError> {
        for parameter in &self.function.parameters {
            let value = serde_json::to_value(parameter).map_err(|e| self.fail(e.to_string()))?;
            let name = value_name(&value)
                .ok_or_else(|| self.fail("malformed parameter"))?
                .to_owned();
            if !self.definitions.insert(name.clone()) {
                return Err(self.fail(format!("duplicate parameter '{name}'")));
            }
            self.bindings.insert(name, value);
        }
        // Phi names are allocated after parameters but before ordinary results.
        for block in &self.function.blocks {
            if let Some(phis) = self.phis.get_mut(&block.name) {
                for phi in phis {
                    let preferred = first_load_name(block, &phi.slot)
                        .unwrap_or_else(|| format!("{}.{}.phi", block.name, phi.slot));
                    let mut name = preferred.clone();
                    let mut suffix = 1;
                    while self.definitions.contains(&name) {
                        name = format!("{preferred}.{suffix}");
                        suffix += 1;
                    }
                    set_value_name(&mut phi.result, &name);
                    self.definitions.insert(name);
                }
            }
        }
        Ok(())
    }

    fn place_phis(&mut self) -> Result<(), SsaLoweringError> {
        let mut definitions: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        let mut slot_values: BTreeMap<String, Value> = BTreeMap::new();
        let mut uses = BTreeMap::new();
        let mut defs = BTreeMap::new();
        for block in self
            .function
            .blocks
            .iter()
            .filter(|b| self.reachable.contains(&b.name))
        {
            let mut block_uses = BTreeSet::new();
            let mut block_defs = BTreeSet::new();
            for instruction in &block.instructions {
                match serde_json::to_value(instruction).map_err(|e| self.fail(e.to_string()))? {
                    Value::Object(object)
                        if object.get("kind").and_then(Value::as_str) == Some("load") =>
                    {
                        let slot = object.get("slot").expect("load slot");
                        let name = value_name(slot).expect("slot name").to_owned();
                        if !block_defs.contains(&name) {
                            block_uses.insert(name.clone());
                        }
                        slot_values
                            .entry(name)
                            .or_insert_with(|| as_ssa_value(slot.clone()));
                    }
                    Value::Object(object)
                        if object.get("kind").and_then(Value::as_str) == Some("store") =>
                    {
                        let slot = object.get("slot").expect("store slot");
                        let name = value_name(slot).expect("slot name").to_owned();
                        block_defs.insert(name.clone());
                        definitions
                            .entry(name.clone())
                            .or_default()
                            .insert(block.name.clone());
                        slot_values
                            .entry(name)
                            .or_insert_with(|| as_ssa_value(slot.clone()));
                    }
                    _ => {}
                }
            }
            uses.insert(block.name.clone(), block_uses);
            defs.insert(block.name.clone(), block_defs);
        }
        let live_in = dataflow_live_in(
            self.function,
            &self.successors,
            &self.reachable,
            &uses,
            &defs,
        );
        let initialized_in =
            dataflow_initialized_in(self.function, &self.predecessors, &self.reachable, &defs);
        let frontier = dominance_frontiers(
            self.function,
            &self.predecessors,
            &self.idom,
            &self.reachable,
        );
        for (slot, initial) in definitions {
            let mut placed = BTreeSet::new();
            let mut seen = initial.clone();
            let mut work: VecDeque<String> = initial.into_iter().collect();
            while let Some(block) = work.pop_front() {
                for target in &frontier[&block] {
                    if placed.contains(target)
                        || (!live_in[target].contains(&slot)
                            && !initialized_in[target].contains(&slot))
                    {
                        continue;
                    }
                    placed.insert(target.clone());
                    if seen.insert(target.clone()) {
                        work.push_back(target.clone());
                    }
                }
            }
            for block in placed {
                self.phis.entry(block).or_default().push(PhiState {
                    slot: slot.clone(),
                    result: slot_values[&slot].clone(),
                    incoming: Vec::new(),
                });
            }
        }
        for phis in self.phis.values_mut() {
            phis.sort_by(|a, b| a.slot.cmp(&b.slot));
        }
        Ok(())
    }

    fn rename_block(&mut self, block_name: &str) -> Result<(), SsaLoweringError> {
        let mut pushed = Vec::new();
        let mut bound = Vec::new();
        if let Some(phis) = self.phis.get(block_name) {
            for phi in phis.clone() {
                self.stacks
                    .entry(phi.slot.clone())
                    .or_default()
                    .push(phi.result.clone());
                pushed.push(phi.slot);
            }
        }
        let block = &self.function.blocks[self.block_index[block_name]];
        let mut emitted = Vec::new();
        for instruction in &block.instructions {
            let mut value =
                serde_json::to_value(instruction).map_err(|e| self.fail(e.to_string()))?;
            let kind = value
                .get("kind")
                .and_then(Value::as_str)
                .expect("instruction kind")
                .to_owned();
            if kind == "store" {
                let object = value.as_object_mut().expect("instruction object");
                let slot = value_name(&object["slot"]).expect("slot name").to_owned();
                let source = self.resolve(&object["value"])?;
                self.stacks.entry(slot.clone()).or_default().push(source);
                pushed.push(slot);
                continue;
            }
            if kind == "load" {
                let object = value.as_object().expect("instruction object");
                let slot = value_name(&object["slot"]).expect("slot name");
                let result = value_name(&object["result"])
                    .expect("result name")
                    .to_owned();
                let current = self
                    .stacks
                    .get(slot)
                    .and_then(|s| s.last())
                    .cloned()
                    .ok_or_else(|| self.fail(format!("load from uninitialized slot '%{slot}'")))?;
                if self.bindings.insert(result.clone(), current).is_some()
                    && !self.definitions.contains(&result)
                {
                    return Err(self.fail(format!("duplicate value binding '%{result}'")));
                }
                bound.push(result);
                continue;
            }
            self.convert_instruction(&mut value, &kind, &mut bound)?;
            emitted.push(
                serde_json::from_value(value)
                    .map_err(|e| self.fail(format!("schema-v2 construction: {e}")))?,
            );
        }
        self.output.insert(block_name.to_owned(), emitted);
        let successors = self.successors[block_name].clone();
        for successor in successors {
            if let Some(phis) = self.phis.get_mut(&successor) {
                for phi in phis {
                    let current = self.stacks.get(&phi.slot).and_then(|s| s.last()).cloned()
                        .ok_or_else(|| SsaLoweringError::function(&self.function.name, format!("phi for slot '%{}' in '{successor}' has no incoming from '{block_name}'", phi.slot)))?;
                    phi.incoming
                        .push(serde_json::json!({"block": block_name, "value": current}));
                }
            }
        }
        for child in self.children[block_name].clone() {
            self.rename_block(&child)?;
        }
        for name in bound.into_iter().rev() {
            self.bindings.remove(&name);
        }
        for slot in pushed.into_iter().rev() {
            self.stacks.get_mut(&slot).expect("slot stack").pop();
        }
        Ok(())
    }

    fn convert_instruction(
        &mut self,
        value: &mut Value,
        kind: &str,
        bound: &mut Vec<String>,
    ) -> Result<(), SsaLoweringError> {
        let definition_keys: &[&str] = match kind {
            "catch_entry" => &["event"],
            "invoke" | "invoke_indirect" | "invoke_interface" => &["result", "exception"],
            _ => &["result"],
        };
        let object = value.as_object_mut().expect("instruction object");
        let mut definitions = Vec::new();
        for key in definition_keys {
            if let Some(definition) = object.get_mut(*key) {
                if !definition.is_null() {
                    let name = value_name(definition)
                        .ok_or_else(|| {
                            SsaLoweringError::function(
                                &self.function.name,
                                format!("malformed {kind}.{key}"),
                            )
                        })?
                        .to_owned();
                    *definition = as_ssa_value(definition.clone());
                    definitions.push((name, definition.clone()));
                }
            }
        }
        let mut excluded_keys = definition_keys.to_vec();
        if matches!(kind, "invoke" | "invoke_indirect" | "invoke_interface") {
            excluded_keys.push("exceptional_target_event");
        } else if matches!(kind, "throw" | "rethrow" | "propagate") {
            excluded_keys.push("target_event");
        }
        resolve_tree(value, &self.bindings, &excluded_keys)?;
        let object = value.as_object_mut().expect("instruction object");
        match kind {
            "invoke" | "invoke_indirect" | "invoke_interface" => {
                object.remove("exceptional_target_event");
                let normal = object
                    .get("result")
                    .filter(|v| !v.is_null())
                    .cloned()
                    .into_iter()
                    .collect::<Vec<_>>();
                let exception = object.get("exception").expect("invoke exception").clone();
                object.insert("normal_arguments".into(), Value::Array(normal));
                object.insert(
                    "exceptional_arguments".into(),
                    Value::Array(vec![exception]),
                );
            }
            "throw" | "rethrow" | "propagate" => {
                let arguments = if object.get("target").is_some_and(|v| !v.is_null()) {
                    vec![object["event"].clone()]
                } else {
                    Vec::new()
                };
                object.remove("target_event");
                object.insert("exceptional_arguments".into(), Value::Array(arguments));
            }
            "return" => {
                if object
                    .get("transferred_storage")
                    .is_some_and(|value| !value.is_null())
                {
                    return Err(self.fail(
                        "return ownership transfer was not discharged by lifecycle normalization",
                    ));
                }
            }
            "call" => {
                object.remove("may_throw");
            }
            _ => {}
        }
        // Normative synthesis, intentionally independent of Rust/Python defaults.
        if matches!(
            kind,
            "array_get"
                | "array_set"
                | "list_get"
                | "list_set"
                | "vector_get"
                | "vector_set"
                | "matrix_get"
                | "matrix_set"
        ) {
            object.insert("bounds_checked".into(), Value::Bool(true));
            if matches!(kind, "matrix_get" | "matrix_set") {
                if let Some(cols) = object.remove("cols") {
                    object.insert("shape".into(), Value::Array(vec![cols]));
                }
            }
        }
        for (name, definition) in definitions {
            self.bind(&name, definition, bound)?;
        }
        Ok(())
    }

    fn resolve(&self, value: &Value) -> Result<Value, SsaLoweringError> {
        let name = value_name(value).ok_or_else(|| self.fail("malformed value operand"))?;
        self.bindings
            .get(name)
            .cloned()
            .ok_or_else(|| self.fail(format!("undefined value '%{name}'")))
    }

    fn bind(
        &mut self,
        name: &str,
        value: Value,
        bound: &mut Vec<String>,
    ) -> Result<(), SsaLoweringError> {
        if !self.definitions.insert(name.to_owned()) {
            return Err(self.fail(format!("duplicate SSA definition '%{name}'")));
        }
        self.bindings.insert(name.to_owned(), value);
        bound.push(name.to_owned());
        Ok(())
    }

    fn finish(self) -> Result<SSAFunctionV2DTO, SsaLoweringError> {
        let mut blocks = Vec::new();
        for block in self
            .function
            .blocks
            .iter()
            .filter(|b| self.reachable.contains(&b.name))
        {
            let mut instructions = Vec::new();
            for phi in self.phis.get(&block.name).into_iter().flatten() {
                let value =
                    serde_json::json!({"kind":"phi", "result":phi.result, "incoming":phi.incoming});
                instructions.push(
                    serde_json::from_value(value)
                        .map_err(|e| self.fail(format!("phi construction: {e}")))?,
                );
            }
            instructions.extend(self.output[&block.name].clone());
            blocks.push(SSABasicBlockV2DTO {
                name: block.name.clone(),
                instructions,
            });
        }
        Ok(SSAFunctionV2DTO {
            name: self.function.name.clone(),
            parameters: self.function.parameters.clone(),
            return_type: self.function.return_type.clone(),
            blocks,
            entry_block: self.function.blocks[0].name.clone(),
            may_throw: self.function.may_throw,
        })
    }
}

fn successors_of(instruction: &IRInstructionDTO) -> Vec<String> {
    match instruction {
        IRInstructionDTO::Jump { target } => vec![target.clone()],
        IRInstructionDTO::Branch {
            true_target,
            false_target,
            ..
        } => vec![true_target.clone(), false_target.clone()],
        IRInstructionDTO::Invoke {
            normal_target,
            exceptional_target,
            ..
        }
        | IRInstructionDTO::InvokeIndirect {
            normal_target,
            exceptional_target,
            ..
        }
        | IRInstructionDTO::InvokeInterface {
            normal_target,
            exceptional_target,
            ..
        } => vec![normal_target.clone(), exceptional_target.clone()],
        IRInstructionDTO::Throw {
            target: NullableDTO(target),
            ..
        }
        | IRInstructionDTO::Rethrow {
            target: NullableDTO(target),
            ..
        }
        | IRInstructionDTO::Propagate {
            target: NullableDTO(target),
            ..
        } => target.iter().cloned().collect(),
        _ => Vec::new(),
    }
}

fn compute_dominators(
    function: &IRFunctionDTO,
    predecessors: &BTreeMap<String, Vec<String>>,
    reachable: &BTreeSet<String>,
) -> BTreeMap<String, BTreeSet<String>> {
    let entry = &function.blocks[0].name;
    let mut result = BTreeMap::new();
    for block in function
        .blocks
        .iter()
        .filter(|b| reachable.contains(&b.name))
    {
        result.insert(
            block.name.clone(),
            if &block.name == entry {
                BTreeSet::from([block.name.clone()])
            } else {
                reachable.clone()
            },
        );
    }
    loop {
        let mut changed = false;
        for block in function
            .blocks
            .iter()
            .filter(|b| reachable.contains(&b.name) && &b.name != entry)
        {
            let mut next = reachable.clone();
            for predecessor in &predecessors[&block.name] {
                next = next.intersection(&result[predecessor]).cloned().collect();
            }
            next.insert(block.name.clone());
            if next != result[&block.name] {
                result.insert(block.name.clone(), next);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    result
}

fn dominance_frontiers(
    function: &IRFunctionDTO,
    predecessors: &BTreeMap<String, Vec<String>>,
    idom: &BTreeMap<String, Option<String>>,
    reachable: &BTreeSet<String>,
) -> BTreeMap<String, BTreeSet<String>> {
    let mut result: BTreeMap<String, BTreeSet<String>> = reachable
        .iter()
        .map(|b| (b.clone(), BTreeSet::new()))
        .collect();
    for block in function
        .blocks
        .iter()
        .filter(|b| reachable.contains(&b.name))
    {
        if predecessors[&block.name].len() < 2 {
            continue;
        }
        for predecessor in &predecessors[&block.name] {
            let mut runner = predecessor.clone();
            while Some(&runner) != idom[&block.name].as_ref() {
                result
                    .get_mut(&runner)
                    .expect("frontier runner")
                    .insert(block.name.clone());
                let Some(parent) = &idom[&runner] else { break };
                runner = parent.clone();
            }
        }
    }
    result
}

fn dataflow_live_in(
    function: &IRFunctionDTO,
    successors: &BTreeMap<String, Vec<String>>,
    reachable: &BTreeSet<String>,
    uses: &BTreeMap<String, BTreeSet<String>>,
    defs: &BTreeMap<String, BTreeSet<String>>,
) -> BTreeMap<String, BTreeSet<String>> {
    let mut input: BTreeMap<String, BTreeSet<String>> = reachable
        .iter()
        .map(|b| (b.clone(), BTreeSet::new()))
        .collect();
    let mut output = input.clone();
    loop {
        let mut changed = false;
        for block in function
            .blocks
            .iter()
            .rev()
            .filter(|b| reachable.contains(&b.name))
        {
            let out = successors[&block.name]
                .iter()
                .filter(|s| reachable.contains(*s))
                .flat_map(|s| input[s].iter().cloned())
                .collect::<BTreeSet<_>>();
            let next = uses[&block.name]
                .union(&out.difference(&defs[&block.name]).cloned().collect())
                .cloned()
                .collect();
            if out != output[&block.name] || next != input[&block.name] {
                output.insert(block.name.clone(), out);
                input.insert(block.name.clone(), next);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    input
}

fn dataflow_initialized_in(
    function: &IRFunctionDTO,
    predecessors: &BTreeMap<String, Vec<String>>,
    reachable: &BTreeSet<String>,
    defs: &BTreeMap<String, BTreeSet<String>>,
) -> BTreeMap<String, BTreeSet<String>> {
    let all = defs
        .values()
        .flat_map(|s| s.iter().cloned())
        .collect::<BTreeSet<_>>();
    let mut input: BTreeMap<String, BTreeSet<String>> = reachable
        .iter()
        .map(|b| (b.clone(), BTreeSet::new()))
        .collect();
    let mut output: BTreeMap<String, BTreeSet<String>> = reachable
        .iter()
        .map(|b| (b.clone(), defs[b].clone()))
        .collect();
    loop {
        let mut changed = false;
        for block in function
            .blocks
            .iter()
            .rev()
            .filter(|b| reachable.contains(&b.name))
        {
            let next_in = if predecessors[&block.name].is_empty() {
                BTreeSet::new()
            } else {
                predecessors[&block.name]
                    .iter()
                    .fold(all.clone(), |acc, p| {
                        acc.intersection(&output[p]).cloned().collect()
                    })
            };
            let next_out = next_in.union(&defs[&block.name]).cloned().collect();
            if next_in != input[&block.name] || next_out != output[&block.name] {
                input.insert(block.name.clone(), next_in);
                output.insert(block.name.clone(), next_out);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    input
}

fn first_load_name(block: &crate::wire::IRBasicBlockDTO, slot: &str) -> Option<String> {
    block
        .instructions
        .iter()
        .find_map(|instruction| match instruction {
            IRInstructionDTO::Load {
                result,
                slot: candidate,
            } if dto_value_name(candidate) == slot => Some(dto_value_name(result).to_owned()),
            _ => None,
        })
}

fn dto_value_name(value: &crate::wire::IRValueDTO) -> &str {
    match value {
        crate::wire::IRValueDTO::Value { name, .. }
        | crate::wire::IRValueDTO::Storage { name, .. }
        | crate::wire::IRValueDTO::Parameter { name, .. } => name,
    }
}

fn value_name(value: &Value) -> Option<&str> {
    value.as_object()?.get("name")?.as_str()
}
fn set_value_name(value: &mut Value, name: &str) {
    value
        .as_object_mut()
        .expect("value object")
        .insert("name".into(), Value::String(name.into()));
}
fn as_ssa_value(mut value: Value) -> Value {
    value
        .as_object_mut()
        .expect("value object")
        .insert("tag".into(), Value::String("value".into()));
    value
}

fn resolve_tree(
    value: &mut Value,
    bindings: &BTreeMap<String, Value>,
    excluded_root_keys: &[&str],
) -> Result<(), SsaLoweringError> {
    fn walk(value: &mut Value, bindings: &BTreeMap<String, Value>) -> Result<(), SsaLoweringError> {
        match value {
            Value::Object(object)
                if matches!(
                    object.get("tag").and_then(Value::as_str),
                    Some("value" | "parameter")
                ) && object.contains_key("type") =>
            {
                let name = object
                    .get("name")
                    .and_then(Value::as_str)
                    .expect("value name");
                *value = bindings.get(name).cloned().ok_or_else(|| {
                    SsaLoweringError::module(format!("undefined value '%{name}'"))
                })?;
            }
            Value::Object(object) => {
                for child in object.values_mut() {
                    walk(child, bindings)?;
                }
            }
            Value::Array(items) => {
                for child in items {
                    walk(child, bindings)?;
                }
            }
            _ => {}
        }
        Ok(())
    }
    let object = value.as_object_mut().expect("instruction object");
    for (key, child) in object {
        if !excluded_root_keys.contains(&key.as_str()) {
            walk(child, bindings)?;
        }
    }
    Ok(())
}
