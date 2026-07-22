//! Local and CFG-propagated lifecycle verification for owning storage.

use std::collections::{HashMap, VecDeque};

use aether_ir::{
    IRBasicBlock, IRFunction, IRInstruction, IRModule, IRStorage, IRStructDefinition, IRType,
    IRValue, LifecycleSource,
};

use crate::cfg::{ENTRY_BLOCK_NAME, FunctionCfg};
use crate::lifecycle_error::{
    BlockLifecycleError, FunctionLifecycleError, FunctionLifecycleVerificationError,
    LifecycleInstructionLocation, LifecycleOperation, LifecycleRuleError, LifecycleStorageRole,
    LocalSlotState, ModuleLifecycleError, ModuleLifecycleVerificationError,
    OwnershipCompletionReason, PossibleSlotStates,
};
use crate::structure_verifier::verify_function_structure_prerequisite;
use crate::verifier::instruction_kind;

#[derive(Clone, Copy)]
struct StorageRef<'value> {
    name: &'value str,
    r#type: &'value IRType,
}

impl<'value> From<&'value IRValue> for StorageRef<'value> {
    fn from(value: &'value IRValue) -> Self {
        Self {
            name: &value.name,
            r#type: &value.r#type,
        }
    }
}

impl<'value> From<&'value IRStorage> for StorageRef<'value> {
    fn from(storage: &'value IRStorage) -> Self {
        Self {
            name: &storage.name,
            r#type: &storage.r#type,
        }
    }
}

#[derive(Clone, Copy)]
struct StorageOperand<'value> {
    storage: StorageRef<'value>,
    role: LifecycleStorageRole,
}

#[derive(Clone, Copy)]
enum LifecycleEffect<'instruction> {
    None,
    Load(StorageRef<'instruction>),
    Store(StorageRef<'instruction>),
    InitDefault(StorageRef<'instruction>),
    CopyInit {
        destination: StorageRef<'instruction>,
        source: &'instruction LifecycleSource,
    },
    MoveInit {
        destination: StorageRef<'instruction>,
        source: StorageRef<'instruction>,
    },
    Assign {
        destination: StorageRef<'instruction>,
        source: &'instruction LifecycleSource,
    },
    Destroy(StorageRef<'instruction>),
    Relocate {
        destination: StorageRef<'instruction>,
        source: StorageRef<'instruction>,
        count: i64,
    },
    ReturnTransfer(StorageRef<'instruction>),
}

#[derive(Clone)]
struct StorageDeclaration {
    r#type: IRType,
    first_seen: LifecycleInstructionLocation,
    participates_in_lifecycle: bool,
}

struct StorageIndex {
    declarations: HashMap<String, StorageDeclaration>,
    order: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct StateFact {
    states: PossibleSlotStates,
    transition: Option<LifecycleInstructionLocation>,
}

impl StateFact {
    fn singleton(state: LocalSlotState) -> Self {
        Self {
            states: PossibleSlotStates::singleton(state),
            transition: None,
        }
    }

    fn concrete_state(&self) -> Option<LocalSlotState> {
        self.states.concrete_singleton()
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum TransferMode {
    Validate,
    Propagate,
}

impl TransferMode {
    const fn validates(self) -> bool {
        matches!(self, Self::Validate)
    }
}

type SlotStateMap = HashMap<String, StateFact>;

/// Immutable fixed-point result indexed by retained block order.
struct LifecycleDataFlow {
    reachable: Vec<bool>,
    entry_states: Vec<Option<SlotStateMap>>,
    exit_states: Vec<Option<SlotStateMap>>,
}

/// Verifies local lifecycle transitions in every retained function and block.
///
/// The pass deliberately performs no CFG propagation or predecessor merging.
/// It does not invoke the type, structure, SSA, or dominance passes because
/// none is required to establish a source-ordered fact inside one block.
pub fn verify_module_local_lifecycle(module: &IRModule) -> Result<(), ModuleLifecycleError> {
    for (function_index, function) in module.functions.iter().enumerate() {
        verify_function_local_lifecycle(module, function).map_err(|source| {
            ModuleLifecycleError {
                function_index,
                function_name: function.name.clone(),
                source: Box::new(source),
            }
        })?;
    }
    Ok(())
}

/// Verifies local lifecycle transitions for one function using module structs.
pub fn verify_function_local_lifecycle(
    module: &IRModule,
    function: &IRFunction,
) -> Result<(), FunctionLifecycleError> {
    let storage_index = collect_storage_index(function);
    let registry = LifecycleTypeRegistry::new(&module.structs);

    for (block_index, block) in function.blocks.iter().enumerate() {
        verify_block(function, block_index, block, &storage_index, &registry).map_err(
            |source| FunctionLifecycleError {
                function_name: function.name.clone(),
                block_index,
                block_name: block.name.clone(),
                source: Box::new(source),
            },
        )?;
    }
    Ok(())
}

/// Verifies function-wide storage lifecycle state and reachable-exit ownership
/// completion in every retained function.
///
/// Structural verification is the sole prerequisite: this pass needs a safe,
/// unambiguous CFG. SSA value validity and dominance remain independently
/// callable passes because lifecycle state tracks only `IRStorage`.
pub fn verify_module_lifecycle(module: &IRModule) -> Result<(), ModuleLifecycleVerificationError> {
    for (function_index, function) in module.functions.iter().enumerate() {
        verify_function_lifecycle(module, function).map_err(|source| {
            ModuleLifecycleVerificationError {
                function_index,
                function_name: function.name.clone(),
                source: Box::new(source),
            }
        })?;
    }
    Ok(())
}

/// Verifies function-wide lifecycle state and ownership completion after
/// deterministic CFG convergence.
pub fn verify_function_lifecycle(
    module: &IRModule,
    function: &IRFunction,
) -> Result<(), FunctionLifecycleVerificationError> {
    let blocks = verify_function_structure_prerequisite(function).map_err(|source| {
        FunctionLifecycleVerificationError::StructurePrerequisite {
            function_name: function.name.clone(),
            source: Box::new(source),
        }
    })?;
    let Some(cfg) = FunctionCfg::from_validated(function, &blocks) else {
        // Structural verification owns this invariant, so reaching this branch
        // would require the model to mutate through an immutable borrow.
        return Ok(());
    };
    let storage_index = collect_storage_index(function);
    let registry = LifecycleTypeRegistry::new(&module.structs);
    let data_flow = LifecycleDataFlow::compute(function, &cfg, &storage_index, &registry);
    debug_assert_eq!(data_flow.exit_states.len(), function.blocks.len());

    // Emit diagnostics only after convergence and in retained source order.
    for (block_index, block) in function.blocks.iter().enumerate() {
        let entry_states = if data_flow.reachable[block_index] {
            data_flow.entry_states[block_index]
                .clone()
                .unwrap_or_else(|| initial_states(&storage_index, LocalSlotState::Uninitialized))
        } else {
            // IRV-022 deliberately checks each unreachable block in isolation
            // with every collected slot available. No edge in an unreachable
            // component propagates lifecycle facts into another block.
            initial_states(&storage_index, LocalSlotState::Initialized)
        };
        verify_block_from_states(
            function,
            block_index,
            block,
            &storage_index,
            &registry,
            entry_states,
        )
        .map_err(|source| FunctionLifecycleVerificationError::Block {
            function_name: function.name.clone(),
            block_index,
            block_name: block.name.clone(),
            source: Box::new(source),
        })?;
    }
    verify_reachable_exits(function, &storage_index, &registry, &data_flow)?;
    Ok(())
}

impl LifecycleDataFlow {
    fn compute(
        function: &IRFunction,
        cfg: &FunctionCfg,
        storage_index: &StorageIndex,
        registry: &LifecycleTypeRegistry<'_>,
    ) -> Self {
        let block_count = cfg.block_count();
        let mut reachable = vec![false; block_count];
        let mut reachability_worklist = VecDeque::from([cfg.entry_index()]);
        while let Some(block_index) = reachability_worklist.pop_front() {
            if reachable[block_index] {
                continue;
            }
            reachable[block_index] = true;
            for &successor in cfg.successors(block_index) {
                if !reachable[successor] {
                    reachability_worklist.push_back(successor);
                }
            }
        }

        let mut entry_states = vec![None; block_count];
        let mut exit_states = vec![None; block_count];
        let mut queued = vec![false; block_count];
        let mut worklist = VecDeque::new();
        for (block_index, is_reachable) in reachable.iter().copied().enumerate() {
            if is_reachable {
                worklist.push_back(block_index);
                queued[block_index] = true;
            }
        }

        while let Some(block_index) = worklist.pop_front() {
            queued[block_index] = false;
            let mut incoming = if block_index == cfg.entry_index() {
                Some(initial_states(storage_index, LocalSlotState::Uninitialized))
            } else {
                None
            };
            for &predecessor in cfg.predecessors(block_index) {
                if !reachable[predecessor] {
                    continue;
                }
                let Some(predecessor_exit) = &exit_states[predecessor] else {
                    continue;
                };
                match &mut incoming {
                    Some(existing) => join_state_maps(existing, predecessor_exit, storage_index),
                    None => incoming = Some(predecessor_exit.clone()),
                }
            }
            let Some(incoming) = incoming else {
                continue;
            };
            if entry_states[block_index].as_ref() != Some(&incoming) {
                entry_states[block_index] = Some(incoming.clone());
            }
            let output = transfer_block(
                function,
                block_index,
                &function.blocks[block_index],
                incoming,
                registry,
                TransferMode::Propagate,
            );
            if exit_states[block_index].as_ref() == Some(&output) {
                continue;
            }
            exit_states[block_index] = Some(output);
            for &successor in cfg.successors(block_index) {
                if reachable[successor] && !queued[successor] {
                    queued[successor] = true;
                    worklist.push_back(successor);
                }
            }
        }

        Self {
            reachable,
            entry_states,
            exit_states,
        }
    }
}

fn initial_states(storage_index: &StorageIndex, state: LocalSlotState) -> SlotStateMap {
    storage_index
        .order
        .iter()
        .map(|name| (name.clone(), StateFact::singleton(state)))
        .collect()
}

fn join_state_maps(
    destination: &mut SlotStateMap,
    source: &SlotStateMap,
    storage_index: &StorageIndex,
) {
    for name in &storage_index.order {
        let (Some(source_fact), Some(destination_fact)) =
            (source.get(name), destination.get_mut(name))
        else {
            continue;
        };
        let previous_states = destination_fact.states;
        destination_fact.states.join(source_fact.states);
        if destination_fact.states != previous_states
            || destination_fact.transition != source_fact.transition
        {
            destination_fact.transition = None;
        }
    }
}

fn collect_storage_index(function: &IRFunction) -> StorageIndex {
    let mut declarations: HashMap<String, StorageDeclaration> = HashMap::new();
    let mut order = Vec::new();
    for (block_index, block) in function.blocks.iter().enumerate() {
        for (instruction_index, instruction) in block.instructions.iter().enumerate() {
            let location = instruction_location(block_index, block, instruction_index, instruction);
            let participates_in_lifecycle = is_ownership_lifecycle_instruction(instruction);
            for operand in storage_operands(instruction) {
                if let Some(declaration) = declarations.get_mut(operand.storage.name) {
                    declaration.participates_in_lifecycle |= participates_in_lifecycle;
                    continue;
                }
                order.push(operand.storage.name.to_owned());
                declarations.insert(
                    operand.storage.name.to_owned(),
                    StorageDeclaration {
                        r#type: operand.storage.r#type.clone(),
                        first_seen: location.clone(),
                        participates_in_lifecycle,
                    },
                );
            }
        }
    }
    StorageIndex {
        declarations,
        order,
    }
}

fn verify_reachable_exits(
    function: &IRFunction,
    storage_index: &StorageIndex,
    registry: &LifecycleTypeRegistry<'_>,
    data_flow: &LifecycleDataFlow,
) -> Result<(), FunctionLifecycleVerificationError> {
    for (block_index, block) in function.blocks.iter().enumerate() {
        if !data_flow.reachable[block_index] {
            continue;
        }
        let Some(IRInstruction::IRReturn {
            transferred_storage,
            ..
        }) = block.instructions.last()
        else {
            continue;
        };
        let Some(exit_states) = &data_flow.exit_states[block_index] else {
            continue;
        };
        let instruction_index = block.instructions.len() - 1;
        let instruction = &block.instructions[instruction_index];
        let exit = instruction_location(block_index, block, instruction_index, instruction);

        let mut ownership_slots: Vec<&str> = storage_index
            .order
            .iter()
            .filter_map(|name| {
                storage_index.declarations[name]
                    .participates_in_lifecycle
                    .then_some(name.as_str())
            })
            .collect();
        ownership_slots.sort_unstable();
        for name in ownership_slots {
            let declaration = &storage_index.declarations[name];
            if !declaration.participates_in_lifecycle
                || transferred_storage
                    .as_ref()
                    .is_some_and(|storage| storage.name == name)
            {
                continue;
            }
            let fact = &exit_states[name];
            if !fact.states.contains(LocalSlotState::Initialized) {
                continue;
            }

            let storage = StorageRef {
                name,
                r#type: &declaration.r#type,
            };
            let source = LifecycleRuleError::IncompleteOwnershipAtExit {
                storage_identifier: name.to_owned(),
                storage_type: declaration.r#type.clone(),
                exit_block: block.name.clone(),
                terminal_states: fact.states,
                expected_terminal_states: completed_terminal_states(),
                ownership_reason: if registry.traits(&declaration.r#type).needs_destroy {
                    OwnershipCompletionReason::ManagedStorageRequiresCleanup
                } else {
                    OwnershipCompletionReason::TrivialLifecycleStorageRequiresCompletion
                },
                last_transition: fact.transition.clone(),
                exit: exit.clone(),
            };
            return Err(FunctionLifecycleVerificationError::Block {
                function_name: function.name.clone(),
                block_index,
                block_name: block.name.clone(),
                source: Box::new(rule_error(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleStorageRole::ExitOwner,
                    storage,
                    source,
                )),
            });
        }
    }
    Ok(())
}

const fn completed_terminal_states() -> PossibleSlotStates {
    PossibleSlotStates {
        may_be_unknown: false,
        may_be_uninitialized: true,
        may_be_initialized: false,
        may_be_moved: true,
        may_be_destroyed: true,
    }
}

const fn is_ownership_lifecycle_instruction(instruction: &IRInstruction) -> bool {
    matches!(
        instruction,
        IRInstruction::IRInitDefault { .. }
            | IRInstruction::IRCopyInit { .. }
            | IRInstruction::IRMoveInit { .. }
            | IRInstruction::IRAssign { .. }
            | IRInstruction::IRDestroy { .. }
            | IRInstruction::IRRelocate { .. }
    )
}

fn verify_block(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    storage_index: &StorageIndex,
    registry: &LifecycleTypeRegistry<'_>,
) -> Result<(), BlockLifecycleError> {
    let entry_state = if block.name == ENTRY_BLOCK_NAME {
        LocalSlotState::Uninitialized
    } else {
        LocalSlotState::Unknown
    };
    let states = initial_states(storage_index, entry_state);
    verify_block_from_states(
        function,
        block_index,
        block,
        storage_index,
        registry,
        states,
    )
}

fn verify_block_from_states(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    storage_index: &StorageIndex,
    registry: &LifecycleTypeRegistry<'_>,
    mut states: SlotStateMap,
) -> Result<(), BlockLifecycleError> {
    for (instruction_index, instruction) in block.instructions.iter().enumerate() {
        let location = instruction_location(block_index, block, instruction_index, instruction);
        for operand in storage_operands(instruction) {
            let declaration = &storage_index.declarations[operand.storage.name];
            if declaration.r#type != *operand.storage.r#type {
                return Err(block_error(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    operand,
                    LifecycleRuleError::StorageTypeMismatch {
                        storage_identifier: operand.storage.name.to_owned(),
                        expected: declaration.r#type.clone(),
                        actual: operand.storage.r#type.clone(),
                        first_seen: declaration.first_seen.clone(),
                        conflicting_use: location.clone(),
                        role: operand.role,
                    },
                ));
            }
        }

        apply_effect(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            lifecycle_effect(instruction),
            &location,
            &mut states,
            registry,
            TransferMode::Validate,
        )?;
    }
    Ok(())
}

fn transfer_block(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    mut states: SlotStateMap,
    registry: &LifecycleTypeRegistry<'_>,
    mode: TransferMode,
) -> SlotStateMap {
    for (instruction_index, instruction) in block.instructions.iter().enumerate() {
        let location = instruction_location(block_index, block, instruction_index, instruction);
        // Propagation deliberately suppresses diagnostics. Every transfer is a
        // total monotone function; validation replays it after convergence.
        let result = apply_effect(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            lifecycle_effect(instruction),
            &location,
            &mut states,
            registry,
            mode,
        );
        debug_assert!(result.is_ok() || mode.validates());
    }
    states
}

#[allow(clippy::too_many_arguments, clippy::too_many_lines)]
fn apply_effect(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    effect: LifecycleEffect<'_>,
    location: &LifecycleInstructionLocation,
    states: &mut HashMap<String, StateFact>,
    registry: &LifecycleTypeRegistry<'_>,
    mode: TransferMode,
) -> Result<(), BlockLifecycleError> {
    match effect {
        LifecycleEffect::None => Ok(()),
        LifecycleEffect::Load(storage) => {
            if mode.validates() {
                require_live(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleOperation::Load,
                    LifecycleStorageRole::Slot,
                    storage,
                    location,
                    states,
                )?;
            }
            Ok(())
        }
        LifecycleEffect::Store(storage) => {
            set_state(states, storage, LocalSlotState::Initialized, location);
            Ok(())
        }
        LifecycleEffect::InitDefault(destination) => {
            if mode.validates() {
                require_non_void(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleOperation::InitDefault,
                    LifecycleStorageRole::Destination,
                    destination,
                    location,
                )?;
                require_uninitialized_destination(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleOperation::InitDefault,
                    destination,
                    location,
                    states,
                )?;
                let traits = registry.traits(destination.r#type);
                if !traits.supports_default {
                    return Err(rule_error(
                        function,
                        block_index,
                        block,
                        instruction_index,
                        instruction,
                        LifecycleStorageRole::Destination,
                        destination,
                        LifecycleRuleError::InvalidLifecycleType {
                            operation: LifecycleOperation::InitDefault,
                            role: LifecycleStorageRole::Destination,
                            storage_identifier: destination.name.to_owned(),
                            storage_type: destination.r#type.clone(),
                            reason: traits.reason,
                            location: location.clone(),
                        },
                    ));
                }
            }
            set_state(states, destination, LocalSlotState::Initialized, location);
            Ok(())
        }
        LifecycleEffect::CopyInit {
            destination,
            source,
        } => {
            if mode.validates() {
                require_non_void(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleOperation::CopyInit,
                    LifecycleStorageRole::Destination,
                    destination,
                    location,
                )?;
                require_uninitialized_destination(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleOperation::CopyInit,
                    destination,
                    location,
                    states,
                )?;
                if let LifecycleSource::Storage(source) = source {
                    require_live(
                        function,
                        block_index,
                        block,
                        instruction_index,
                        instruction,
                        LifecycleOperation::CopyInit,
                        LifecycleStorageRole::Source,
                        source.into(),
                        location,
                        states,
                    )?;
                }
                require_matching_types(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleOperation::CopyInit,
                    destination,
                    source.r#type(),
                    location,
                )?;
            }
            set_state(states, destination, LocalSlotState::Initialized, location);
            Ok(())
        }
        LifecycleEffect::MoveInit {
            destination,
            source,
        } => apply_move_like(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            LifecycleOperation::MoveInit,
            destination,
            source,
            location,
            states,
            None,
            registry,
            mode,
        ),
        LifecycleEffect::Assign {
            destination,
            source,
        } => {
            if mode.validates() {
                require_non_void(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleOperation::Assign,
                    LifecycleStorageRole::Destination,
                    destination,
                    location,
                )?;
                require_assignment_destination(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    destination,
                    location,
                    states,
                )?;
                if let LifecycleSource::Storage(source) = source {
                    require_live(
                        function,
                        block_index,
                        block,
                        instruction_index,
                        instruction,
                        LifecycleOperation::Assign,
                        LifecycleStorageRole::Source,
                        source.into(),
                        location,
                        states,
                    )?;
                }
                require_matching_types(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleOperation::Assign,
                    destination,
                    source.r#type(),
                    location,
                )?;
            }
            set_state(states, destination, LocalSlotState::Initialized, location);
            Ok(())
        }
        LifecycleEffect::Destroy(storage) => {
            if mode.validates() {
                require_non_void(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleOperation::Destroy,
                    LifecycleStorageRole::Value,
                    storage,
                    location,
                )?;
                require_destroyable_state(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    storage,
                    location,
                    states,
                )?;
            }
            set_state(states, storage, LocalSlotState::Destroyed, location);
            Ok(())
        }
        LifecycleEffect::Relocate {
            destination,
            source,
            count,
        } => apply_move_like(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            LifecycleOperation::Relocate,
            destination,
            source,
            location,
            states,
            Some(count),
            registry,
            mode,
        ),
        LifecycleEffect::ReturnTransfer(storage) => {
            if mode.validates() {
                require_non_void(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleOperation::ReturnTransfer,
                    LifecycleStorageRole::TransferredStorage,
                    storage,
                    location,
                )?;
                require_live(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleOperation::ReturnTransfer,
                    LifecycleStorageRole::TransferredStorage,
                    storage,
                    location,
                    states,
                )?;
                let IRInstruction::IRReturn { value, .. } = instruction else {
                    return Ok(());
                };
                if value
                    .as_ref()
                    .is_none_or(|value| value.r#type != *storage.r#type)
                {
                    return Err(rule_error(
                        function,
                        block_index,
                        block,
                        instruction_index,
                        instruction,
                        LifecycleStorageRole::TransferredStorage,
                        storage,
                        LifecycleRuleError::ReturnTransferTypeMismatch {
                            storage_identifier: storage.name.to_owned(),
                            storage_type: storage.r#type.clone(),
                            returned_type: value.as_ref().map(|value| value.r#type.clone()),
                            location: location.clone(),
                        },
                    ));
                }
            }
            Ok(())
        }
    }
}

#[allow(clippy::too_many_arguments, clippy::too_many_lines)]
fn apply_move_like(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    operation: LifecycleOperation,
    destination: StorageRef<'_>,
    source: StorageRef<'_>,
    location: &LifecycleInstructionLocation,
    states: &mut HashMap<String, StateFact>,
    relocate_count: Option<i64>,
    registry: &LifecycleTypeRegistry<'_>,
    mode: TransferMode,
) -> Result<(), BlockLifecycleError> {
    if mode.validates() {
        require_non_void(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            operation,
            LifecycleStorageRole::Destination,
            destination,
            location,
        )?;
        require_non_void(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            operation,
            LifecycleStorageRole::Source,
            source,
            location,
        )?;
        if relocate_count.is_some_and(|count| count <= 0) {
            return Err(rule_error(
                function,
                block_index,
                block,
                instruction_index,
                instruction,
                LifecycleStorageRole::Source,
                source,
                LifecycleRuleError::InvalidRelocateCount {
                    count: relocate_count.unwrap_or_default(),
                    location: location.clone(),
                },
            ));
        }
        if destination.name == source.name {
            return Err(rule_error(
                function,
                block_index,
                block,
                instruction_index,
                instruction,
                LifecycleStorageRole::Source,
                source,
                LifecycleRuleError::ForbiddenSourceDestinationAlias {
                    operation,
                    storage_identifier: source.name.to_owned(),
                    storage_type: source.r#type.clone(),
                    location: location.clone(),
                },
            ));
        }
        require_uninitialized_destination(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            operation,
            destination,
            location,
            states,
        )?;
        require_live(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            operation,
            LifecycleStorageRole::Source,
            source,
            location,
            states,
        )?;
        require_matching_types(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            operation,
            destination,
            source.r#type,
            location,
        )?;
        if operation == LifecycleOperation::Relocate {
            let traits = registry.traits(source.r#type);
            if !traits.trivially_relocatable {
                return Err(rule_error(
                    function,
                    block_index,
                    block,
                    instruction_index,
                    instruction,
                    LifecycleStorageRole::Source,
                    source,
                    LifecycleRuleError::InvalidLifecycleType {
                        operation,
                        role: LifecycleStorageRole::Source,
                        storage_identifier: source.name.to_owned(),
                        storage_type: source.r#type.clone(),
                        reason: traits.reason,
                        location: location.clone(),
                    },
                ));
            }
        }
    }
    set_state(states, destination, LocalSlotState::Initialized, location);
    set_state(states, source, LocalSlotState::Moved, location);
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn require_non_void(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    operation: LifecycleOperation,
    role: LifecycleStorageRole,
    storage: StorageRef<'_>,
    location: &LifecycleInstructionLocation,
) -> Result<(), BlockLifecycleError> {
    if matches!(storage.r#type, IRType::Void(_)) {
        return Err(rule_error(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            role,
            storage,
            LifecycleRuleError::InvalidLifecycleType {
                operation,
                role,
                storage_identifier: storage.name.to_owned(),
                storage_type: storage.r#type.clone(),
                reason: "void has no storage".to_owned(),
                location: location.clone(),
            },
        ));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn require_matching_types(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    operation: LifecycleOperation,
    destination: StorageRef<'_>,
    source_type: &IRType,
    location: &LifecycleInstructionLocation,
) -> Result<(), BlockLifecycleError> {
    if destination.r#type != source_type {
        return Err(rule_error(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            LifecycleStorageRole::Destination,
            destination,
            LifecycleRuleError::OperationTypeMismatch {
                operation,
                source_type: source_type.clone(),
                destination_type: destination.r#type.clone(),
                location: location.clone(),
            },
        ));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn require_uninitialized_destination(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    operation: LifecycleOperation,
    storage: StorageRef<'_>,
    location: &LifecycleInstructionLocation,
    states: &HashMap<String, StateFact>,
) -> Result<(), BlockLifecycleError> {
    let fact = &states[storage.name];
    if fact.states.is_singleton(LocalSlotState::Initialized) {
        return Err(rule_error(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            LifecycleStorageRole::Destination,
            storage,
            LifecycleRuleError::DoubleInitialization {
                operation,
                storage_identifier: storage.name.to_owned(),
                storage_type: storage.r#type.clone(),
                previous_state: LocalSlotState::Initialized,
                attempted_state: LocalSlotState::Initialized,
                previous_transition: fact.transition.clone().unwrap_or_else(|| location.clone()),
                current_transition: location.clone(),
            },
        ));
    }
    if fact.states.contains(LocalSlotState::Initialized) {
        return Err(merged_state_error(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            operation,
            LifecycleStorageRole::Destination,
            storage,
            fact.states,
            LocalSlotState::Uninitialized,
            location,
        ));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn require_live(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    operation: LifecycleOperation,
    role: LifecycleStorageRole,
    storage: StorageRef<'_>,
    location: &LifecycleInstructionLocation,
    states: &HashMap<String, StateFact>,
) -> Result<(), BlockLifecycleError> {
    let fact = &states[storage.name];
    match fact.concrete_state() {
        Some(LocalSlotState::Unknown | LocalSlotState::Initialized) => Ok(()),
        Some(LocalSlotState::Uninitialized) => Err(rule_error(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            role,
            storage,
            LifecycleRuleError::UseBeforeInitialization {
                operation,
                role,
                storage_identifier: storage.name.to_owned(),
                storage_type: storage.r#type.clone(),
                previous_state: LocalSlotState::Uninitialized,
                attempted_state: LocalSlotState::Initialized,
                current_use: location.clone(),
            },
        )),
        Some(previous_state @ (LocalSlotState::Moved | LocalSlotState::Destroyed)) => {
            Err(rule_error(
                function,
                block_index,
                block,
                instruction_index,
                instruction,
                role,
                storage,
                LifecycleRuleError::UseAfterLocalInvalidation {
                    operation,
                    role,
                    storage_identifier: storage.name.to_owned(),
                    storage_type: storage.r#type.clone(),
                    previous_state,
                    attempted_state: LocalSlotState::Initialized,
                    previous_transition: fact
                        .transition
                        .clone()
                        .unwrap_or_else(|| location.clone()),
                    current_use: location.clone(),
                },
            ))
        }
        None => Err(merged_state_error(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            operation,
            role,
            storage,
            fact.states,
            LocalSlotState::Initialized,
            location,
        )),
    }
}

#[allow(clippy::too_many_arguments)]
fn require_assignment_destination(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    storage: StorageRef<'_>,
    location: &LifecycleInstructionLocation,
    states: &HashMap<String, StateFact>,
) -> Result<(), BlockLifecycleError> {
    let fact = &states[storage.name];
    match fact.concrete_state() {
        Some(LocalSlotState::Unknown | LocalSlotState::Initialized) => Ok(()),
        Some(LocalSlotState::Uninitialized) => Err(rule_error(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            LifecycleStorageRole::Destination,
            storage,
            LifecycleRuleError::AssignmentToUninitialized {
                storage_identifier: storage.name.to_owned(),
                storage_type: storage.r#type.clone(),
                previous_state: LocalSlotState::Uninitialized,
                attempted_state: LocalSlotState::Initialized,
                current_transition: location.clone(),
            },
        )),
        Some(LocalSlotState::Moved | LocalSlotState::Destroyed) => require_live(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            LifecycleOperation::Assign,
            LifecycleStorageRole::Destination,
            storage,
            location,
            states,
        ),
        None => Err(merged_state_error(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            LifecycleOperation::Assign,
            LifecycleStorageRole::Destination,
            storage,
            fact.states,
            LocalSlotState::Initialized,
            location,
        )),
    }
}

#[allow(clippy::too_many_arguments)]
fn require_destroyable_state(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    storage: StorageRef<'_>,
    location: &LifecycleInstructionLocation,
    states: &HashMap<String, StateFact>,
) -> Result<(), BlockLifecycleError> {
    let fact = &states[storage.name];
    match fact.concrete_state() {
        Some(LocalSlotState::Unknown | LocalSlotState::Initialized) => Ok(()),
        Some(LocalSlotState::Uninitialized) => Err(rule_error(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            LifecycleStorageRole::Value,
            storage,
            LifecycleRuleError::DestroyOfUninitialized {
                storage_identifier: storage.name.to_owned(),
                storage_type: storage.r#type.clone(),
                previous_state: LocalSlotState::Uninitialized,
                attempted_state: LocalSlotState::Destroyed,
                current_transition: location.clone(),
            },
        )),
        Some(LocalSlotState::Destroyed) => Err(rule_error(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            LifecycleStorageRole::Value,
            storage,
            LifecycleRuleError::DoubleDestroy {
                storage_identifier: storage.name.to_owned(),
                storage_type: storage.r#type.clone(),
                previous_state: LocalSlotState::Destroyed,
                attempted_state: LocalSlotState::Destroyed,
                previous_transition: fact.transition.clone().unwrap_or_else(|| location.clone()),
                current_transition: location.clone(),
            },
        )),
        Some(LocalSlotState::Moved) => require_live(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            LifecycleOperation::Destroy,
            LifecycleStorageRole::Value,
            storage,
            location,
            states,
        ),
        None => Err(merged_state_error(
            function,
            block_index,
            block,
            instruction_index,
            instruction,
            LifecycleOperation::Destroy,
            LifecycleStorageRole::Value,
            storage,
            fact.states,
            LocalSlotState::Initialized,
            location,
        )),
    }
}

fn set_state(
    states: &mut HashMap<String, StateFact>,
    storage: StorageRef<'_>,
    state: LocalSlotState,
    location: &LifecycleInstructionLocation,
) {
    states.insert(
        storage.name.to_owned(),
        StateFact {
            states: PossibleSlotStates::singleton(state),
            transition: Some(location.clone()),
        },
    );
}

#[allow(clippy::too_many_arguments)]
fn merged_state_error(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    operation: LifecycleOperation,
    role: LifecycleStorageRole,
    storage: StorageRef<'_>,
    possible_states: PossibleSlotStates,
    required_state: LocalSlotState,
    location: &LifecycleInstructionLocation,
) -> BlockLifecycleError {
    rule_error(
        function,
        block_index,
        block,
        instruction_index,
        instruction,
        role,
        storage,
        LifecycleRuleError::InvalidMergedState {
            operation,
            role,
            storage_identifier: storage.name.to_owned(),
            storage_type: storage.r#type.clone(),
            possible_states,
            required_state,
            current_transition: location.clone(),
        },
    )
}

#[allow(clippy::too_many_arguments)]
fn rule_error(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    role: LifecycleStorageRole,
    storage: StorageRef<'_>,
    source: LifecycleRuleError,
) -> BlockLifecycleError {
    block_error(
        function,
        block_index,
        block,
        instruction_index,
        instruction,
        StorageOperand { storage, role },
        source,
    )
}

fn block_error(
    function: &IRFunction,
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
    operand: StorageOperand<'_>,
    source: LifecycleRuleError,
) -> BlockLifecycleError {
    BlockLifecycleError {
        function_name: function.name.clone(),
        block_index,
        block_name: block.name.clone(),
        instruction_index,
        instruction_kind: instruction_kind(instruction),
        storage_role: operand.role,
        storage_identifier: operand.storage.name.to_owned(),
        storage_type: operand.storage.r#type.clone(),
        source,
    }
}

fn instruction_location(
    block_index: usize,
    block: &IRBasicBlock,
    instruction_index: usize,
    instruction: &IRInstruction,
) -> LifecycleInstructionLocation {
    LifecycleInstructionLocation {
        block_index,
        block_name: block.name.clone(),
        instruction_index,
        instruction_kind: instruction_kind(instruction),
    }
}

fn lifecycle_effect(instruction: &IRInstruction) -> LifecycleEffect<'_> {
    match instruction {
        IRInstruction::IRLoad { slot, .. } => LifecycleEffect::Load(slot.into()),
        IRInstruction::IRStore { slot, .. } => LifecycleEffect::Store(slot.into()),
        IRInstruction::IRInitDefault { destination, .. } => {
            LifecycleEffect::InitDefault(destination.into())
        }
        IRInstruction::IRCopyInit {
            destination,
            source,
            ..
        } => LifecycleEffect::CopyInit {
            destination: destination.into(),
            source,
        },
        IRInstruction::IRMoveInit {
            destination,
            source,
            ..
        } => LifecycleEffect::MoveInit {
            destination: destination.into(),
            source: source.into(),
        },
        IRInstruction::IRAssign {
            destination,
            source,
            ..
        } => LifecycleEffect::Assign {
            destination: destination.into(),
            source,
        },
        IRInstruction::IRDestroy { value, .. } => LifecycleEffect::Destroy(value.into()),
        IRInstruction::IRRelocate {
            destination,
            source,
            count,
            ..
        } => LifecycleEffect::Relocate {
            destination: destination.into(),
            source: source.into(),
            count: *count,
        },
        IRInstruction::IRReturn {
            transferred_storage: Some(storage),
            ..
        } => LifecycleEffect::ReturnTransfer(storage.into()),
        _ => LifecycleEffect::None,
    }
}

fn storage_operands(instruction: &IRInstruction) -> Vec<StorageOperand<'_>> {
    fn operand(storage: StorageRef<'_>, role: LifecycleStorageRole) -> StorageOperand<'_> {
        StorageOperand { storage, role }
    }

    match instruction {
        IRInstruction::IRLoad { slot, .. } | IRInstruction::IRStore { slot, .. } => {
            vec![operand(slot.into(), LifecycleStorageRole::Slot)]
        }
        IRInstruction::IRInitDefault { destination, .. } => vec![operand(
            destination.into(),
            LifecycleStorageRole::Destination,
        )],
        IRInstruction::IRCopyInit {
            destination,
            source,
            ..
        }
        | IRInstruction::IRAssign {
            destination,
            source,
            ..
        } => {
            let mut operands = vec![operand(
                destination.into(),
                LifecycleStorageRole::Destination,
            )];
            if let LifecycleSource::Storage(source) = source {
                operands.push(operand(source.into(), LifecycleStorageRole::Source));
            }
            operands
        }
        IRInstruction::IRMoveInit {
            destination,
            source,
            ..
        }
        | IRInstruction::IRRelocate {
            destination,
            source,
            ..
        } => vec![
            operand(destination.into(), LifecycleStorageRole::Destination),
            operand(source.into(), LifecycleStorageRole::Source),
        ],
        IRInstruction::IRDestroy { value, .. } => {
            vec![operand(value.into(), LifecycleStorageRole::Value)]
        }
        IRInstruction::IRReturn {
            transferred_storage: Some(storage),
            ..
        } => vec![operand(
            storage.into(),
            LifecycleStorageRole::TransferredStorage,
        )],
        _ => Vec::new(),
    }
}

#[derive(Clone)]
struct LifecycleTraits {
    trivially_relocatable: bool,
    supports_default: bool,
    needs_destroy: bool,
    reason: String,
    collection_unsupported_reason: Option<String>,
}

pub(crate) struct LifecycleTypeRegistry<'module> {
    structs: &'module [IRStructDefinition],
}

impl<'module> LifecycleTypeRegistry<'module> {
    pub(crate) fn new(structs: &'module [IRStructDefinition]) -> Self {
        Self { structs }
    }

    pub(crate) fn collection_unsupported_reason(&self, r#type: &IRType) -> Option<String> {
        self.traits(r#type).collection_unsupported_reason
    }

    fn traits(&self, r#type: &IRType) -> LifecycleTraits {
        self.compute(r#type, &mut Vec::new())
    }

    fn compute(&self, r#type: &IRType, active: &mut Vec<String>) -> LifecycleTraits {
        match r#type {
            IRType::Int(_)
            | IRType::Float(_)
            | IRType::Double(_)
            | IRType::Bool(_)
            | IRType::Complex(_)
            | IRType::Enum(_) => LifecycleTraits::valid(true, true, false),
            IRType::String(_) | IRType::Array(_) | IRType::List(_) => {
                LifecycleTraits::valid(true, true, true)
            }
            IRType::Vector(vector) => LifecycleTraits {
                trivially_relocatable: true,
                supports_default: matches!(vector.orientation.as_deref(), Some("row" | "column")),
                needs_destroy: false,
                reason: "vector default requires a concrete row or column orientation".to_owned(),
                collection_unsupported_reason: (!matches!(
                    vector.orientation.as_deref(),
                    Some("row" | "column")
                ))
                .then(|| "vector default requires a concrete orientation".to_owned()),
            },
            IRType::Matrix(_) => LifecycleTraits {
                trivially_relocatable: true,
                supports_default: false,
                needs_destroy: false,
                reason: "matrix default requires compile-time dimensions".to_owned(),
                collection_unsupported_reason: Some(
                    "matrix default requires compile-time dimensions".to_owned(),
                ),
            },
            IRType::Function(_) => LifecycleTraits {
                trivially_relocatable: true,
                supports_default: false,
                needs_destroy: false,
                reason: "function values have no default".to_owned(),
                collection_unsupported_reason: None,
            },
            IRType::ClassRef(_) | IRType::Interface(_) | IRType::Nullable(_) => {
                LifecycleTraits::invalid(
                    "lifecycle layout is not defined",
                    format!("lifecycle layout for '{type}' is not defined"),
                )
            }
            IRType::Void(_) => {
                LifecycleTraits::invalid("void has no storage", "void has no storage")
            }
            IRType::MethodResult(result) => {
                let receiver = IRType::Struct(result.receiver.clone());
                self.aggregate_traits([&receiver, result.value.as_ref()], active)
            }
            IRType::Struct(struct_type) => {
                if active.contains(&struct_type.name) {
                    return LifecycleTraits::invalid("recursive layout", "recursive layout");
                }
                let Some(definition) = self
                    .structs
                    .iter()
                    .find(|definition| definition.name == struct_type.name)
                else {
                    return LifecycleTraits::invalid(
                        "nominal struct has no definition",
                        format!("nominal struct '{}' has no definition", struct_type.name),
                    );
                };
                active.push(struct_type.name.clone());
                let result = self.aggregate_traits(
                    definition.fields.iter().map(|(_, field_type)| field_type),
                    active,
                );
                active.pop();
                result
            }
        }
    }

    fn aggregate_traits<'type_ref>(
        &self,
        fields: impl IntoIterator<Item = &'type_ref IRType>,
        active: &mut Vec<String>,
    ) -> LifecycleTraits {
        let mut relocatable = true;
        let mut supports_default = true;
        let mut needs_destroy = false;
        let mut reason = String::new();
        for field in fields {
            let traits = self.compute(field, active);
            relocatable &= traits.trivially_relocatable;
            supports_default &= traits.supports_default;
            needs_destroy |= traits.needs_destroy;
            if reason.is_empty() && (!traits.trivially_relocatable || !traits.supports_default) {
                reason = traits.reason;
            }
        }
        LifecycleTraits {
            trivially_relocatable: relocatable,
            supports_default,
            needs_destroy,
            reason,
            // Python's aggregate trait composition does not propagate child
            // reasons, so a defined struct or method-result advertises a
            // collection lifecycle even when a nested field does not.
            collection_unsupported_reason: None,
        }
    }
}

impl LifecycleTraits {
    fn valid(trivially_relocatable: bool, supports_default: bool, needs_destroy: bool) -> Self {
        Self {
            trivially_relocatable,
            supports_default,
            needs_destroy,
            reason: String::new(),
            collection_unsupported_reason: None,
        }
    }

    fn invalid(reason: &str, collection_reason: impl Into<String>) -> Self {
        Self {
            trivially_relocatable: false,
            supports_default: false,
            needs_destroy: false,
            reason: reason.to_owned(),
            collection_unsupported_reason: Some(collection_reason.into()),
        }
    }
}
