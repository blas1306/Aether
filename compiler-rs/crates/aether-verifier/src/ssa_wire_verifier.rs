//! Exception-aware verification for the value-based SSA wire representation.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet, VecDeque};
use std::error::Error;
use std::fmt;

use aether_ir::OwnedSsaModule;
use aether_ir::wire::{
    IRInstructionDTO, IRTypeDTO, IRValueDTO, SSABasicBlockDTO, SSABoundsCheckedInstructionV2DTO,
    SSAControlInstructionDTO, SSAFunctionDTO, SSAInstructionDTO, SSAModuleDTO,
};

/// A fail-closed value-based SSA wire verification failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SSAWireVerificationError {
    /// Function containing the invalid SSA.
    pub function_name: String,
    /// Block containing the invalid SSA, when applicable.
    pub block_name: Option<String>,
    /// Stable explanation of the violated invariant.
    pub detail: String,
}

impl fmt::Display for SSAWireVerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        if let Some(block_name) = &self.block_name {
            write!(
                formatter,
                "SSA verification failed in function '{}' block '{}': {}",
                self.function_name, block_name, self.detail
            )
        } else {
            write!(
                formatter,
                "SSA verification failed in function '{}': {}",
                self.function_name, self.detail
            )
        }
    }
}

impl Error for SSAWireVerificationError {}

#[derive(Clone, Debug)]
struct Edge {
    source: String,
    target: String,
    kind: EdgeKind,
    arguments: Vec<IRValueDTO>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum EdgeKind {
    Normal,
    Exceptional,
}

/// Verify the strict SSA DTO, including explicit exceptional CFG and ownership.
///
/// Ordinary instruction schema validation is performed while deserializing the
/// DTO. This pass adds the SSA-specific cross-block rules that cannot be
/// expressed by serde: typed edge arguments, handler shape, invoke/call
/// consistency, and one terminal disposition for every opaque event owner.
pub fn verify_ssa_module_dto(module: &SSAModuleDTO) -> Result<(), SSAWireVerificationError> {
    let mut functions = HashMap::new();
    for function in &module.functions {
        if functions.insert(function.name.as_str(), function).is_some() {
            return Err(failure(
                &function.name,
                None,
                format!("duplicate function '{}'", function.name),
            ));
        }
    }
    for function in &module.functions {
        verify_function(function, &functions)?;
    }
    Ok(())
}

/// Verify the schema-independent owned SSA model with the authoritative SSA rules.
///
/// The adapter is deliberately in the verifier crate (which already depends on
/// `aether-ir`).  It retains the schema-v2 collection check bit in the canonical
/// view while presenting the instruction's unchanged semantic operands to the
/// historical rule engine.  No JSON serialization or schema-v1 decoding occurs.
pub fn verify_owned_ssa(module: &OwnedSsaModule) -> Result<(), SSAWireVerificationError> {
    let wire = module.to_schema_v2();
    let mut bounds_checked = Vec::new();
    let canonical = SSAModuleDTO {
        schema_version: 1,
        representation: wire.representation,
        functions: wire
            .functions
            .into_iter()
            .map(|function| SSAFunctionDTO {
                name: function.name,
                parameters: function.parameters,
                return_type: function.return_type,
                blocks: function
                    .blocks
                    .into_iter()
                    .map(|block| SSABasicBlockDTO {
                        name: block.name,
                        instructions: block
                            .instructions
                            .into_iter()
                            .map(|instruction| match instruction {
                                aether_ir::wire::SSAInstructionV2DTO::Unchanged(value) => value,
                                aether_ir::wire::SSAInstructionV2DTO::BoundsChecked(value) => {
                                    let (instruction, checked) = bounds_instruction_view(value);
                                    bounds_checked.push(checked);
                                    SSAInstructionDTO::Ordinary(instruction)
                                }
                            })
                            .collect(),
                    })
                    .collect(),
                entry_block: function.entry_block,
                may_throw: function.may_throw,
            })
            .collect(),
        structs: wire.structs,
    };

    // Keep this field observable in the canonical adapter.  Existing verifier
    // semantics intentionally impose no true/false constraint on it.
    let _preserved_bounds_checked = bounds_checked;
    verify_ssa_module_dto(&canonical)
}

#[allow(clippy::too_many_lines)]
fn bounds_instruction_view(value: SSABoundsCheckedInstructionV2DTO) -> (IRInstructionDTO, bool) {
    use SSABoundsCheckedInstructionV2DTO as B;
    match value {
        B::ArrayGet {
            result,
            array,
            index,
            borrowed,
            borrow_scope,
            source_location,
            bounds_checked,
        } => (
            IRInstructionDTO::ArrayGet {
                result,
                array,
                index,
                borrowed,
                borrow_scope,
                source_location,
            },
            bounds_checked,
        ),
        B::ArraySet {
            array,
            index,
            value,
            bounds_checked,
        } => (
            IRInstructionDTO::ArraySet {
                array,
                index,
                value,
            },
            bounds_checked,
        ),
        B::ListGet {
            result,
            list_value,
            index,
            borrowed,
            borrow_scope,
            source_location,
            bounds_checked,
        } => (
            IRInstructionDTO::ListGet {
                result,
                list_value,
                index,
                borrowed,
                borrow_scope,
                source_location,
            },
            bounds_checked,
        ),
        B::ListSet {
            list_value,
            index,
            value,
            bounds_checked,
        } => (
            IRInstructionDTO::ListSet {
                list_value,
                index,
                value,
            },
            bounds_checked,
        ),
        B::VectorGet {
            result,
            vector,
            index,
            bounds_checked,
        } => (
            IRInstructionDTO::VectorGet {
                result,
                vector,
                index,
            },
            bounds_checked,
        ),
        B::VectorSet {
            vector,
            index,
            value,
            bounds_checked,
        } => (
            IRInstructionDTO::VectorSet {
                vector,
                index,
                value,
            },
            bounds_checked,
        ),
        B::MatrixGet {
            result,
            matrix,
            row,
            column,
            shape,
            bounds_checked,
        } => (
            IRInstructionDTO::MatrixGet {
                result,
                matrix,
                row,
                column,
                shape,
            },
            bounds_checked,
        ),
        B::MatrixSet {
            matrix,
            row,
            column,
            value,
            shape,
            bounds_checked,
        } => (
            IRInstructionDTO::MatrixSet {
                matrix,
                row,
                column,
                value,
                shape,
            },
            bounds_checked,
        ),
    }
}

fn verify_function(
    function: &SSAFunctionDTO,
    functions: &HashMap<&str, &SSAFunctionDTO>,
) -> Result<(), SSAWireVerificationError> {
    let mut blocks = HashMap::new();
    for block in &function.blocks {
        if blocks.insert(block.name.as_str(), block).is_some() {
            return Err(failure(
                &function.name,
                Some(&block.name),
                format!("duplicate block '{}'", block.name),
            ));
        }
        if block.instructions.is_empty() {
            return Err(failure(
                &function.name,
                Some(&block.name),
                "block has no terminator",
            ));
        }
        for instruction in &block.instructions[..block.instructions.len() - 1] {
            if is_terminator(instruction) {
                return Err(failure(
                    &function.name,
                    Some(&block.name),
                    "terminator must be the final instruction",
                ));
            }
        }
        if !is_terminator(block.instructions.last().expect("non-empty block")) {
            return Err(failure(
                &function.name,
                Some(&block.name),
                "block does not end in a terminator",
            ));
        }
    }
    if !blocks.contains_key(function.entry_block.as_str()) {
        return Err(failure(
            &function.name,
            None,
            format!("missing entry block '{}'", function.entry_block),
        ));
    }

    let mut handlers = HashMap::new();
    let mut handler_ids = HashSet::new();
    let mut caught_events = HashSet::new();
    let mut borrowed_from = HashMap::new();
    let mut has_exception_ir = false;
    for block in &function.blocks {
        let entries = block
            .instructions
            .iter()
            .filter_map(catch_entry)
            .collect::<Vec<_>>();
        if !entries.is_empty() {
            has_exception_ir = true;
            let first_non_phi = block.instructions.iter().find(|instruction| {
                !matches!(
                    instruction,
                    SSAInstructionDTO::Control(SSAControlInstructionDTO::Phi { .. })
                )
            });
            if entries.len() != 1 || first_non_phi.and_then(catch_entry).is_none() {
                return Err(failure(
                    &function.name,
                    Some(&block.name),
                    "catch_entry must be the first non-phi and only handler entry",
                ));
            }
            let (event, handler_id, catch_types) = entries[0];
            require_event(&function.name, &block.name, event)?;
            if handler_id.is_empty() || !handler_ids.insert(handler_id.as_str()) {
                return Err(failure(
                    &function.name,
                    Some(&block.name),
                    format!("duplicate or empty handler id '{handler_id}'"),
                ));
            }
            if catch_types.iter().collect::<HashSet<_>>().len() != catch_types.len() {
                return Err(failure(
                    &function.name,
                    Some(&block.name),
                    format!("handler '{handler_id}' has duplicate catch metadata"),
                ));
            }
            if let Some(position) = catch_types.iter().position(|name| name == "Error") {
                if position + 1 != catch_types.len() {
                    return Err(failure(
                        &function.name,
                        Some(&block.name),
                        format!("handler '{handler_id}' has catches after Error"),
                    ));
                }
            }
            handlers.insert(block.name.as_str(), event);
            if handler_id != "root" {
                caught_events.insert(value_name(event).to_owned());
            }
        }

        for instruction in &block.instructions {
            if is_exception_instruction(instruction) {
                has_exception_ir = true;
            }
            verify_exception_types(function, block, instruction)?;
            verify_no_ordinary_event_use(function, block, instruction)?;
            if let SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionPayload {
                result,
                event,
                ..
            }) = instruction
            {
                borrowed_from.insert(value_name(result).to_owned(), value_name(event).to_owned());
            }
            if let SSAInstructionDTO::Control(SSAControlInstructionDTO::Rethrow { event, .. }) =
                instruction
            {
                if !caught_events.contains(value_name(event)) {
                    return Err(failure(
                        &function.name,
                        Some(&block.name),
                        "rethrow requires an event introduced by a catch handler",
                    ));
                }
            }
            verify_call_invoke_distinction(function, block, instruction, functions)?;
        }
    }
    if has_exception_ir && !function.may_throw {
        return Err(failure(
            &function.name,
            None,
            "function contains exception SSA but may_throw is false",
        ));
    }

    let mut incoming_kinds: HashMap<&str, Vec<EdgeKind>> = function
        .blocks
        .iter()
        .map(|block| (block.name.as_str(), Vec::new()))
        .collect();
    let mut all_edges = Vec::new();
    for block in &function.blocks {
        let edges = successor_edges(block);
        for edge in &edges {
            if !blocks.contains_key(edge.target.as_str()) {
                return Err(failure(
                    &function.name,
                    Some(&block.name),
                    format!("edge targets unknown block '{}'", edge.target),
                ));
            }
            incoming_kinds
                .get_mut(edge.target.as_str())
                .expect("known target")
                .push(edge.kind);
            match edge.kind {
                EdgeKind::Exceptional => {
                    if !handlers.contains_key(edge.target.as_str()) {
                        return Err(failure(
                            &function.name,
                            Some(&block.name),
                            "exceptional edge must target a catch_entry block",
                        ));
                    }
                    if edge.arguments.len() != 1 || !is_event(&edge.arguments[0]) {
                        return Err(failure(
                            &function.name,
                            Some(&block.name),
                            "exceptional edge must move exactly one exception_event",
                        ));
                    }
                }
                EdgeKind::Normal => {
                    if handlers.contains_key(edge.target.as_str()) {
                        return Err(failure(
                            &function.name,
                            Some(&block.name),
                            "normal edge cannot target a catch_entry block",
                        ));
                    }
                }
            }
        }
        verify_edge_arguments(function, block)?;
        all_edges.extend(edges);
    }
    for handler_name in handlers.keys() {
        let kinds = &incoming_kinds[handler_name];
        if kinds.is_empty() || kinds.iter().any(|kind| *kind != EdgeKind::Exceptional) {
            return Err(failure(
                &function.name,
                Some(handler_name),
                "handler must have only exceptional predecessors",
            ));
        }
    }

    verify_phi_completeness(function, &all_edges)?;
    verify_event_ownership(function, &blocks, &handlers, &borrowed_from)
}

fn verify_phi_completeness(
    function: &SSAFunctionDTO,
    edges: &[Edge],
) -> Result<(), SSAWireVerificationError> {
    let mut predecessors: HashMap<&str, BTreeSet<&str>> = HashMap::new();
    for block in &function.blocks {
        predecessors.insert(block.name.as_str(), BTreeSet::new());
    }
    for edge in edges {
        predecessors
            .get_mut(edge.target.as_str())
            .expect("known target")
            .insert(edge.source.as_str());
    }
    for block in &function.blocks {
        let expected = &predecessors[block.name.as_str()];
        let mut past_phi = false;
        for instruction in &block.instructions {
            match instruction {
                SSAInstructionDTO::Control(SSAControlInstructionDTO::Phi { incoming, .. })
                    if !past_phi =>
                {
                    let actual = incoming
                        .iter()
                        .map(|edge| edge.block.as_str())
                        .collect::<BTreeSet<_>>();
                    if actual != *expected || actual.len() != incoming.len() {
                        return Err(failure(
                            &function.name,
                            Some(&block.name),
                            "phi must have exactly one incoming value per predecessor",
                        ));
                    }
                }
                SSAInstructionDTO::Control(SSAControlInstructionDTO::Phi { .. }) => {
                    return Err(failure(
                        &function.name,
                        Some(&block.name),
                        "phi instructions must be contiguous at block start",
                    ));
                }
                _ => past_phi = true,
            }
        }
    }
    Ok(())
}

fn verify_edge_arguments(
    function: &SSAFunctionDTO,
    block: &SSABasicBlockDTO,
) -> Result<(), SSAWireVerificationError> {
    let instruction = block.instructions.last().expect("non-empty block");
    match instruction {
        SSAInstructionDTO::Control(
            SSAControlInstructionDTO::Invoke {
                result,
                exception,
                normal_arguments,
                exceptional_arguments,
                ..
            }
            | SSAControlInstructionDTO::InvokeIndirect {
                result,
                exception,
                normal_arguments,
                exceptional_arguments,
                ..
            }
            | SSAControlInstructionDTO::InvokeInterface {
                result,
                exception,
                normal_arguments,
                exceptional_arguments,
                ..
            },
        ) => {
            let expected_normal = result.0.iter().cloned().collect::<Vec<_>>();
            if normal_arguments != &expected_normal {
                return Err(failure(
                    &function.name,
                    Some(&block.name),
                    "invoke normal arguments must contain exactly its result",
                ));
            }
            if exceptional_arguments.as_slice() != [exception.clone()] {
                return Err(failure(
                    &function.name,
                    Some(&block.name),
                    "invoke exceptional arguments must contain exactly its event",
                ));
            }
        }
        SSAInstructionDTO::Control(
            SSAControlInstructionDTO::Throw {
                event,
                target,
                exceptional_arguments,
            }
            | SSAControlInstructionDTO::Rethrow {
                event,
                target,
                exceptional_arguments,
            }
            | SSAControlInstructionDTO::Propagate {
                event,
                target,
                exceptional_arguments,
            },
        ) => {
            if target.0.is_none() {
                if !exceptional_arguments.is_empty() {
                    return Err(failure(
                        &function.name,
                        Some(&block.name),
                        "root exceptional transfer cannot have successor arguments",
                    ));
                }
            } else if exceptional_arguments.as_slice() != [event.clone()] {
                return Err(failure(
                    &function.name,
                    Some(&block.name),
                    "exceptional transfer must move exactly its owned event",
                ));
            }
        }
        _ => {}
    }
    Ok(())
}

fn verify_event_ownership(
    function: &SSAFunctionDTO,
    blocks: &HashMap<&str, &SSABasicBlockDTO>,
    handlers: &HashMap<&str, &IRValueDTO>,
    borrowed_from: &HashMap<String, String>,
) -> Result<(), SSAWireVerificationError> {
    let event_phis = function
        .blocks
        .iter()
        .map(|block| {
            let phis = block
                .instructions
                .iter()
                .filter_map(|instruction| match instruction {
                    SSAInstructionDTO::Control(SSAControlInstructionDTO::Phi {
                        result,
                        incoming,
                    }) if is_event(result) => Some((result, incoming)),
                    _ => None,
                })
                .collect::<Vec<_>>();
            (block.name.as_str(), phis)
        })
        .collect::<HashMap<_, _>>();

    let mut incoming: HashMap<String, BTreeMap<String, BTreeSet<String>>> = function
        .blocks
        .iter()
        .map(|block| (block.name.clone(), BTreeMap::new()))
        .collect();
    incoming
        .get_mut(&function.entry_block)
        .expect("verified entry")
        .insert("<entry>".to_owned(), BTreeSet::new());
    let mut worklist = VecDeque::from([function.entry_block.clone()]);
    let mut queued = HashSet::from([function.entry_block.clone()]);
    let mut processed = HashMap::<String, BTreeSet<String>>::new();

    while let Some(block_name) = worklist.pop_front() {
        queued.remove(&block_name);
        let predecessor_states = incoming.get(&block_name).cloned().unwrap_or_default();
        if predecessor_states.is_empty() {
            continue;
        }
        let mut normalized = Vec::new();
        for (predecessor, mut live) in predecessor_states {
            if predecessor != "<entry>" {
                for (result, phi_incoming) in &event_phis[block_name.as_str()] {
                    let Some(edge) = phi_incoming.iter().find(|edge| edge.block == predecessor)
                    else {
                        return Err(failure(
                            &function.name,
                            Some(&block_name),
                            "event phi is missing its predecessor",
                        ));
                    };
                    let incoming_name = value_name(&edge.value);
                    if !live.remove(incoming_name) {
                        return Err(failure(
                            &function.name,
                            Some(&block_name),
                            format!("event phi moves non-live owner '%{incoming_name}'"),
                        ));
                    }
                    live.insert(value_name(result).to_owned());
                }
            }
            if let Some(event) = handlers.get(block_name.as_str()) {
                live.insert(value_name(event).to_owned());
            }
            normalized.push(live);
        }
        let first = normalized.first().cloned().unwrap_or_default();
        if normalized.iter().skip(1).any(|state| state != &first) {
            return Err(failure(
                &function.name,
                Some(&block_name),
                "incompatible exception-event ownership merge",
            ));
        }
        if processed.get(&block_name) == Some(&first) {
            continue;
        }
        processed.insert(block_name.clone(), first.clone());
        let block = blocks[block_name.as_str()];
        let outgoing = transfer_exception_events(function, block, first, borrowed_from)?;
        for (target, state) in outgoing {
            let target_inputs = incoming.get_mut(&target).expect("verified target");
            if target_inputs.get(&block_name) == Some(&state) {
                continue;
            }
            target_inputs.insert(block_name.clone(), state);
            if queued.insert(target.clone()) {
                worklist.push_back(target);
            }
        }
    }

    for block in &function.blocks {
        if processed.contains_key(&block.name) {
            continue;
        }
        let created = block
            .instructions
            .iter()
            .filter_map(|instruction| match instruction {
                SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionPack { result, .. }) => {
                    Some(value_name(result))
                }
                _ => None,
            })
            .collect::<HashSet<_>>();
        let consumed = block
            .instructions
            .iter()
            .filter_map(terminal_event)
            .map(value_name)
            .collect::<HashSet<_>>();
        if let Some(event) = created.difference(&consumed).next() {
            return Err(failure(
                &function.name,
                Some(&block.name),
                format!("owned exception event '%{event}' has no terminal disposition"),
            ));
        }
    }
    Ok(())
}

fn transfer_exception_events(
    function: &SSAFunctionDTO,
    block: &SSABasicBlockDTO,
    mut live: BTreeSet<String>,
    borrowed_from: &HashMap<String, String>,
) -> Result<Vec<(String, BTreeSet<String>)>, SSAWireVerificationError> {
    for instruction in &block.instructions {
        for value in instruction_values(instruction) {
            if let Some(owner) = borrowed_from.get(value_name(&value)) {
                if !live.contains(owner) {
                    return Err(failure(
                        &function.name,
                        Some(&block.name),
                        format!(
                            "borrowed catch value '%{}' is used after its event was consumed",
                            value_name(&value)
                        ),
                    ));
                }
            }
        }
        match instruction {
            SSAInstructionDTO::Control(SSAControlInstructionDTO::Phi { .. })
            | SSAInstructionDTO::Ordinary(IRInstructionDTO::CatchEntry { .. }) => {}
            SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionPack { result, .. }) => {
                let name = value_name(result);
                if !live.insert(name.to_owned()) {
                    return Err(failure(
                        &function.name,
                        Some(&block.name),
                        format!("exception event '%{name}' is defined while already live"),
                    ));
                }
            }
            SSAInstructionDTO::Ordinary(
                IRInstructionDTO::ExceptionMatch { event, .. }
                | IRInstructionDTO::ExceptionPayload { event, .. },
            ) => {
                require_live(function, block, event, &live, "borrowed after consumption")?;
            }
            SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionDestroy { event }) => {
                consume(function, block, event, &mut live)?;
            }
            SSAInstructionDTO::Control(
                SSAControlInstructionDTO::Throw { event, target, .. }
                | SSAControlInstructionDTO::Rethrow { event, target, .. }
                | SSAControlInstructionDTO::Propagate { event, target, .. },
            ) => {
                consume(function, block, event, &mut live)?;
                if let Some(target) = &target.0 {
                    return Ok(vec![(target.clone(), live)]);
                }
                if !live.is_empty() {
                    return Err(failure(
                        &function.name,
                        Some(&block.name),
                        "exceptional unwind leaks another owned event",
                    ));
                }
                return Ok(Vec::new());
            }
            SSAInstructionDTO::Control(
                SSAControlInstructionDTO::Invoke {
                    normal_target,
                    exceptional_target,
                    ..
                }
                | SSAControlInstructionDTO::InvokeIndirect {
                    normal_target,
                    exceptional_target,
                    ..
                }
                | SSAControlInstructionDTO::InvokeInterface {
                    normal_target,
                    exceptional_target,
                    ..
                },
            ) => {
                return Ok(vec![
                    (normal_target.clone(), live.clone()),
                    (exceptional_target.clone(), live),
                ]);
            }
            SSAInstructionDTO::Ordinary(IRInstructionDTO::Jump { target }) => {
                return Ok(vec![(target.clone(), live)]);
            }
            SSAInstructionDTO::Ordinary(IRInstructionDTO::Branch {
                true_target,
                false_target,
                ..
            }) => {
                return Ok(vec![
                    (true_target.clone(), live.clone()),
                    (false_target.clone(), live),
                ]);
            }
            SSAInstructionDTO::Ordinary(IRInstructionDTO::Return { .. }) => {
                if !live.is_empty() {
                    return Err(failure(
                        &function.name,
                        Some(&block.name),
                        "return leaks an owned exception event",
                    ));
                }
                return Ok(Vec::new());
            }
            _ => {}
        }
    }
    unreachable!("block structure was verified")
}

fn verify_call_invoke_distinction(
    function: &SSAFunctionDTO,
    block: &SSABasicBlockDTO,
    instruction: &SSAInstructionDTO,
    functions: &HashMap<&str, &SSAFunctionDTO>,
) -> Result<(), SSAWireVerificationError> {
    match instruction {
        SSAInstructionDTO::Ordinary(IRInstructionDTO::Call {
            function: callee, ..
        }) => {
            if functions
                .get(callee.as_str())
                .is_some_and(|target| target.may_throw)
            {
                return Err(failure(
                    &function.name,
                    Some(&block.name),
                    format!("call to may_throw function '{callee}' must use invoke"),
                ));
            }
        }
        SSAInstructionDTO::Control(SSAControlInstructionDTO::Invoke {
            function: callee, ..
        }) => {
            if functions
                .get(callee.as_str())
                .is_some_and(|target| !target.may_throw)
            {
                return Err(failure(
                    &function.name,
                    Some(&block.name),
                    format!("invoke target '{callee}' is not may_throw"),
                ));
            }
        }
        SSAInstructionDTO::Ordinary(IRInstructionDTO::InterfaceCall { slot, .. }) => {
            if slot.may_throw {
                return Err(failure(
                    &function.name,
                    Some(&block.name),
                    format!(
                        "interface call to may_throw slot '{}' must use invoke",
                        slot.method_id
                    ),
                ));
            }
        }
        SSAInstructionDTO::Control(SSAControlInstructionDTO::InvokeInterface { slot, .. }) => {
            if !slot.may_throw {
                return Err(failure(
                    &function.name,
                    Some(&block.name),
                    format!(
                        "interface invoke target '{}' is not may_throw",
                        slot.method_id
                    ),
                ));
            }
        }
        _ => {}
    }
    Ok(())
}

fn verify_exception_types(
    function: &SSAFunctionDTO,
    block: &SSABasicBlockDTO,
    instruction: &SSAInstructionDTO,
) -> Result<(), SSAWireVerificationError> {
    match instruction {
        SSAInstructionDTO::Control(
            SSAControlInstructionDTO::Invoke { exception, .. }
            | SSAControlInstructionDTO::InvokeIndirect { exception, .. }
            | SSAControlInstructionDTO::InvokeInterface { exception, .. },
        )
        | SSAInstructionDTO::Control(
            SSAControlInstructionDTO::Throw {
                event: exception, ..
            }
            | SSAControlInstructionDTO::Rethrow {
                event: exception, ..
            }
            | SSAControlInstructionDTO::Propagate {
                event: exception, ..
            },
        )
        | SSAInstructionDTO::Ordinary(IRInstructionDTO::CatchEntry {
            event: exception, ..
        })
        | SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionMatch {
            event: exception, ..
        })
        | SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionPayload {
            event: exception,
            ..
        })
        | SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionDestroy { event: exception })
        | SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionPack {
            result: exception, ..
        }) => require_event(&function.name, &block.name, exception),
        _ => Ok(()),
    }
}

fn verify_no_ordinary_event_use(
    function: &SSAFunctionDTO,
    block: &SSABasicBlockDTO,
    instruction: &SSAInstructionDTO,
) -> Result<(), SSAWireVerificationError> {
    let illegal_invoke_operand = match instruction {
        SSAInstructionDTO::Control(SSAControlInstructionDTO::Invoke {
            arguments, result, ..
        }) => arguments.iter().any(is_event) || result.0.as_ref().is_some_and(is_event),
        SSAInstructionDTO::Control(SSAControlInstructionDTO::InvokeIndirect {
            callee,
            arguments,
            result,
            ..
        }) => {
            is_event(callee)
                || arguments.iter().any(is_event)
                || result.0.as_ref().is_some_and(is_event)
        }
        SSAInstructionDTO::Control(SSAControlInstructionDTO::InvokeInterface {
            receiver,
            arguments,
            result,
            ..
        }) => {
            is_event(receiver)
                || arguments.iter().any(is_event)
                || result.0.as_ref().is_some_and(is_event)
        }
        _ => false,
    };
    if illegal_invoke_operand {
        return Err(failure(
            &function.name,
            Some(&block.name),
            "exception_event cannot be an ordinary invoke operand or result",
        ));
    }
    let allowed = matches!(
        instruction,
        SSAInstructionDTO::Control(SSAControlInstructionDTO::Phi { .. })
            | SSAInstructionDTO::Control(SSAControlInstructionDTO::Invoke { .. })
            | SSAInstructionDTO::Control(SSAControlInstructionDTO::InvokeIndirect { .. })
            | SSAInstructionDTO::Control(SSAControlInstructionDTO::InvokeInterface { .. })
            | SSAInstructionDTO::Control(SSAControlInstructionDTO::Throw { .. })
            | SSAInstructionDTO::Control(SSAControlInstructionDTO::Rethrow { .. })
            | SSAInstructionDTO::Control(SSAControlInstructionDTO::Propagate { .. })
            | SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionPack { .. })
            | SSAInstructionDTO::Ordinary(IRInstructionDTO::CatchEntry { .. })
            | SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionMatch { .. })
            | SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionPayload { .. })
            | SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionDestroy { .. })
    );
    if !allowed && instruction_values(instruction).iter().any(is_event) {
        return Err(failure(
            &function.name,
            Some(&block.name),
            "exception_event cannot be used by an ordinary instruction",
        ));
    }
    Ok(())
}

fn instruction_values(instruction: &SSAInstructionDTO) -> Vec<IRValueDTO> {
    fn walk<'value>(value: &'value serde_json::Value, found: &mut Vec<&'value serde_json::Value>) {
        match value {
            serde_json::Value::Array(items) => {
                for item in items {
                    walk(item, found);
                }
            }
            serde_json::Value::Object(mapping) => {
                if matches!(
                    mapping.get("tag"),
                    Some(serde_json::Value::String(tag))
                        if tag == "value" || tag == "parameter"
                ) {
                    found.push(value);
                    return;
                }
                for item in mapping.values() {
                    walk(item, found);
                }
            }
            _ => {}
        }
    }

    let encoded = serde_json::to_value(instruction)
        .expect("wire DTO serialization is infallible after construction");
    let mut encoded_values = Vec::new();
    walk(&encoded, &mut encoded_values);
    encoded_values
        .into_iter()
        .filter_map(|value| serde_json::from_value::<IRValueDTO>(value.clone()).ok())
        .collect()
}

fn successor_edges(block: &SSABasicBlockDTO) -> Vec<Edge> {
    let source = block.name.clone();
    match block.instructions.last().expect("non-empty block") {
        SSAInstructionDTO::Ordinary(IRInstructionDTO::Jump { target }) => vec![Edge {
            source,
            target: target.clone(),
            kind: EdgeKind::Normal,
            arguments: Vec::new(),
        }],
        SSAInstructionDTO::Ordinary(IRInstructionDTO::Branch {
            true_target,
            false_target,
            ..
        }) => vec![
            Edge {
                source: source.clone(),
                target: true_target.clone(),
                kind: EdgeKind::Normal,
                arguments: Vec::new(),
            },
            Edge {
                source,
                target: false_target.clone(),
                kind: EdgeKind::Normal,
                arguments: Vec::new(),
            },
        ],
        SSAInstructionDTO::Control(
            SSAControlInstructionDTO::Invoke {
                normal_target,
                exceptional_target,
                normal_arguments,
                exceptional_arguments,
                ..
            }
            | SSAControlInstructionDTO::InvokeIndirect {
                normal_target,
                exceptional_target,
                normal_arguments,
                exceptional_arguments,
                ..
            }
            | SSAControlInstructionDTO::InvokeInterface {
                normal_target,
                exceptional_target,
                normal_arguments,
                exceptional_arguments,
                ..
            },
        ) => vec![
            Edge {
                source: source.clone(),
                target: normal_target.clone(),
                kind: EdgeKind::Normal,
                arguments: normal_arguments.clone(),
            },
            Edge {
                source,
                target: exceptional_target.clone(),
                kind: EdgeKind::Exceptional,
                arguments: exceptional_arguments.clone(),
            },
        ],
        SSAInstructionDTO::Control(
            SSAControlInstructionDTO::Throw {
                target,
                exceptional_arguments,
                ..
            }
            | SSAControlInstructionDTO::Rethrow {
                target,
                exceptional_arguments,
                ..
            }
            | SSAControlInstructionDTO::Propagate {
                target,
                exceptional_arguments,
                ..
            },
        ) => target
            .0
            .iter()
            .map(|target| Edge {
                source: source.clone(),
                target: target.clone(),
                kind: EdgeKind::Exceptional,
                arguments: exceptional_arguments.clone(),
            })
            .collect(),
        _ => Vec::new(),
    }
}

fn is_terminator(instruction: &SSAInstructionDTO) -> bool {
    matches!(
        instruction,
        SSAInstructionDTO::Control(
            SSAControlInstructionDTO::Invoke { .. }
                | SSAControlInstructionDTO::InvokeIndirect { .. }
                | SSAControlInstructionDTO::InvokeInterface { .. }
                | SSAControlInstructionDTO::Throw { .. }
                | SSAControlInstructionDTO::Rethrow { .. }
                | SSAControlInstructionDTO::Propagate { .. }
        ) | SSAInstructionDTO::Ordinary(
            IRInstructionDTO::Branch { .. }
                | IRInstructionDTO::Jump { .. }
                | IRInstructionDTO::Return { .. }
        )
    )
}

fn is_exception_instruction(instruction: &SSAInstructionDTO) -> bool {
    matches!(
        instruction,
        SSAInstructionDTO::Control(
            SSAControlInstructionDTO::Invoke { .. }
                | SSAControlInstructionDTO::InvokeIndirect { .. }
                | SSAControlInstructionDTO::InvokeInterface { .. }
                | SSAControlInstructionDTO::Throw { .. }
                | SSAControlInstructionDTO::Rethrow { .. }
                | SSAControlInstructionDTO::Propagate { .. }
        ) | SSAInstructionDTO::Ordinary(
            IRInstructionDTO::ExceptionPack { .. }
                | IRInstructionDTO::CatchEntry { .. }
                | IRInstructionDTO::ExceptionMatch { .. }
                | IRInstructionDTO::ExceptionPayload { .. }
                | IRInstructionDTO::ExceptionDestroy { .. }
        )
    )
}

fn catch_entry(instruction: &SSAInstructionDTO) -> Option<(&IRValueDTO, &String, &Vec<String>)> {
    match instruction {
        SSAInstructionDTO::Ordinary(IRInstructionDTO::CatchEntry {
            event,
            handler_id,
            catch_types,
        }) => Some((event, handler_id, catch_types)),
        _ => None,
    }
}

fn terminal_event(instruction: &SSAInstructionDTO) -> Option<&IRValueDTO> {
    match instruction {
        SSAInstructionDTO::Ordinary(IRInstructionDTO::ExceptionDestroy { event })
        | SSAInstructionDTO::Control(SSAControlInstructionDTO::Throw { event, .. })
        | SSAInstructionDTO::Control(SSAControlInstructionDTO::Rethrow { event, .. })
        | SSAInstructionDTO::Control(SSAControlInstructionDTO::Propagate { event, .. }) => {
            Some(event)
        }
        _ => None,
    }
}

fn require_event(
    function_name: &str,
    block_name: &str,
    value: &IRValueDTO,
) -> Result<(), SSAWireVerificationError> {
    if is_event(value) {
        Ok(())
    } else {
        Err(failure(
            function_name,
            Some(block_name),
            format!("'%{}' must have exception_event type", value_name(value)),
        ))
    }
}

fn require_live(
    function: &SSAFunctionDTO,
    block: &SSABasicBlockDTO,
    event: &IRValueDTO,
    live: &BTreeSet<String>,
    action: &str,
) -> Result<(), SSAWireVerificationError> {
    if live.contains(value_name(event)) {
        Ok(())
    } else {
        Err(failure(
            &function.name,
            Some(&block.name),
            format!("exception event '%{}' is {action}", value_name(event)),
        ))
    }
}

fn consume(
    function: &SSAFunctionDTO,
    block: &SSABasicBlockDTO,
    event: &IRValueDTO,
    live: &mut BTreeSet<String>,
) -> Result<(), SSAWireVerificationError> {
    if live.remove(value_name(event)) {
        Ok(())
    } else {
        Err(failure(
            &function.name,
            Some(&block.name),
            format!(
                "exception event '%{}' is consumed more than once or after propagation",
                value_name(event)
            ),
        ))
    }
}

fn is_event(value: &IRValueDTO) -> bool {
    matches!(value_type(value), IRTypeDTO::ExceptionEvent {})
}

fn value_name(value: &IRValueDTO) -> &str {
    match value {
        IRValueDTO::Value { name, .. }
        | IRValueDTO::Storage { name, .. }
        | IRValueDTO::Parameter { name, .. } => name,
    }
}

fn value_type(value: &IRValueDTO) -> &IRTypeDTO {
    match value {
        IRValueDTO::Value { r#type, .. }
        | IRValueDTO::Storage { r#type, .. }
        | IRValueDTO::Parameter { r#type, .. } => r#type,
    }
}

fn failure(
    function_name: &str,
    block_name: Option<&str>,
    detail: impl Into<String>,
) -> SSAWireVerificationError {
    SSAWireVerificationError {
        function_name: function_name.to_owned(),
        block_name: block_name.map(str::to_owned),
        detail: detail.into(),
    }
}
