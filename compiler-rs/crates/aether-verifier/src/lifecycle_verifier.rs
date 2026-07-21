//! Source-ordered, block-local lifecycle verification for owning storage.

use std::collections::HashMap;

use aether_ir::{
    IRBasicBlock, IRFunction, IRInstruction, IRModule, IRStorage, IRStructDefinition, IRType,
    IRValue, LifecycleSource,
};

use crate::lifecycle_error::{
    BlockLifecycleError, FunctionLifecycleError, LifecycleInstructionLocation, LifecycleOperation,
    LifecycleRuleError, LifecycleStorageRole, LocalSlotState, ModuleLifecycleError,
};
use crate::verifier::instruction_kind;

const ENTRY_BLOCK_NAME: &str = "entry";

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
}

struct StorageIndex {
    declarations: HashMap<String, StorageDeclaration>,
    order: Vec<String>,
}

#[derive(Clone)]
struct StateFact {
    state: LocalSlotState,
    transition: Option<LifecycleInstructionLocation>,
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

fn collect_storage_index(function: &IRFunction) -> StorageIndex {
    let mut declarations = HashMap::new();
    let mut order = Vec::new();
    for (block_index, block) in function.blocks.iter().enumerate() {
        for (instruction_index, instruction) in block.instructions.iter().enumerate() {
            let location = instruction_location(block_index, block, instruction_index, instruction);
            for operand in storage_operands(instruction) {
                if declarations.contains_key(operand.storage.name) {
                    continue;
                }
                order.push(operand.storage.name.to_owned());
                declarations.insert(
                    operand.storage.name.to_owned(),
                    StorageDeclaration {
                        r#type: operand.storage.r#type.clone(),
                        first_seen: location.clone(),
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
    let mut states = HashMap::new();
    for name in &storage_index.order {
        states.insert(
            name.clone(),
            StateFact {
                state: entry_state,
                transition: None,
            },
        );
    }

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
        )?;
    }
    Ok(())
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
) -> Result<(), BlockLifecycleError> {
    match effect {
        LifecycleEffect::None => Ok(()),
        LifecycleEffect::Load(storage) => require_live(
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
        ),
        LifecycleEffect::Store(storage) => {
            set_state(states, storage, LocalSlotState::Initialized, location);
            Ok(())
        }
        LifecycleEffect::InitDefault(destination) => {
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
            set_state(states, destination, LocalSlotState::Initialized, location);
            Ok(())
        }
        LifecycleEffect::CopyInit {
            destination,
            source,
        } => {
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
        ),
        LifecycleEffect::Assign {
            destination,
            source,
        } => {
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
            set_state(states, destination, LocalSlotState::Initialized, location);
            Ok(())
        }
        LifecycleEffect::Destroy(storage) => {
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
        ),
        LifecycleEffect::ReturnTransfer(storage) => {
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
) -> Result<(), BlockLifecycleError> {
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
    if let Some(count) = relocate_count {
        if count <= 0 {
            return Err(rule_error(
                function,
                block_index,
                block,
                instruction_index,
                instruction,
                LifecycleStorageRole::Source,
                source,
                LifecycleRuleError::InvalidRelocateCount {
                    count,
                    location: location.clone(),
                },
            ));
        }
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
    if fact.state == LocalSlotState::Initialized {
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
                previous_state: fact.state,
                attempted_state: LocalSlotState::Initialized,
                previous_transition: fact.transition.clone().unwrap_or_else(|| location.clone()),
                current_transition: location.clone(),
            },
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
    match fact.state {
        LocalSlotState::Unknown | LocalSlotState::Initialized => Ok(()),
        LocalSlotState::Uninitialized => Err(rule_error(
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
                previous_state: fact.state,
                attempted_state: LocalSlotState::Initialized,
                current_use: location.clone(),
            },
        )),
        LocalSlotState::Moved | LocalSlotState::Destroyed => Err(rule_error(
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
                previous_state: fact.state,
                attempted_state: LocalSlotState::Initialized,
                previous_transition: fact.transition.clone().unwrap_or_else(|| location.clone()),
                current_use: location.clone(),
            },
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
    match fact.state {
        LocalSlotState::Unknown | LocalSlotState::Initialized => Ok(()),
        LocalSlotState::Uninitialized => Err(rule_error(
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
                previous_state: fact.state,
                attempted_state: LocalSlotState::Initialized,
                current_transition: location.clone(),
            },
        )),
        LocalSlotState::Moved | LocalSlotState::Destroyed => require_live(
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
    match fact.state {
        LocalSlotState::Unknown | LocalSlotState::Initialized => Ok(()),
        LocalSlotState::Uninitialized => Err(rule_error(
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
                previous_state: fact.state,
                attempted_state: LocalSlotState::Destroyed,
                current_transition: location.clone(),
            },
        )),
        LocalSlotState::Destroyed => Err(rule_error(
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
                previous_state: fact.state,
                attempted_state: LocalSlotState::Destroyed,
                previous_transition: fact.transition.clone().unwrap_or_else(|| location.clone()),
                current_transition: location.clone(),
            },
        )),
        LocalSlotState::Moved => require_live(
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
            state,
            transition: Some(location.clone()),
        },
    );
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
    reason: String,
}

struct LifecycleTypeRegistry<'module> {
    structs: &'module [IRStructDefinition],
}

impl<'module> LifecycleTypeRegistry<'module> {
    fn new(structs: &'module [IRStructDefinition]) -> Self {
        Self { structs }
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
            | IRType::Enum(_)
            | IRType::String(_)
            | IRType::Array(_)
            | IRType::List(_) => LifecycleTraits::valid(true, true),
            IRType::Vector(vector) => LifecycleTraits {
                trivially_relocatable: true,
                supports_default: matches!(vector.orientation.as_deref(), Some("row" | "column")),
                reason: "vector default requires a concrete row or column orientation".to_owned(),
            },
            IRType::Matrix(_) => LifecycleTraits {
                trivially_relocatable: true,
                supports_default: false,
                reason: "matrix default requires compile-time dimensions".to_owned(),
            },
            IRType::Function(_) => LifecycleTraits {
                trivially_relocatable: true,
                supports_default: false,
                reason: "function values have no default".to_owned(),
            },
            IRType::ClassRef(_) | IRType::Interface(_) | IRType::Nullable(_) => {
                LifecycleTraits::invalid("lifecycle layout is not defined")
            }
            IRType::Void(_) => LifecycleTraits::invalid("void has no storage"),
            IRType::MethodResult(result) => {
                let receiver = IRType::Struct(result.receiver.clone());
                self.aggregate_traits([&receiver, result.value.as_ref()], active)
            }
            IRType::Struct(struct_type) => {
                if active.contains(&struct_type.name) {
                    return LifecycleTraits::invalid("recursive layout");
                }
                let Some(definition) = self
                    .structs
                    .iter()
                    .find(|definition| definition.name == struct_type.name)
                else {
                    return LifecycleTraits::invalid("nominal struct has no definition");
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
        let mut reason = String::new();
        for field in fields {
            let traits = self.compute(field, active);
            relocatable &= traits.trivially_relocatable;
            supports_default &= traits.supports_default;
            if reason.is_empty() && (!traits.trivially_relocatable || !traits.supports_default) {
                reason = traits.reason;
            }
        }
        LifecycleTraits {
            trivially_relocatable: relocatable,
            supports_default,
            reason,
        }
    }
}

impl LifecycleTraits {
    fn valid(trivially_relocatable: bool, supports_default: bool) -> Self {
        Self {
            trivially_relocatable,
            supports_default,
            reason: String::new(),
        }
    }

    fn invalid(reason: &str) -> Self {
        Self {
            trivially_relocatable: false,
            supports_default: false,
            reason: reason.to_owned(),
        }
    }
}
