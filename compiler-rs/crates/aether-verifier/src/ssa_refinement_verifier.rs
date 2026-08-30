//! Independent refinement verification from normalized Initial IR to owned SSA.
//!
//! This pass deliberately does not reuse SSA construction, dominance, phi
//! placement, or renaming state.  It derives reachability and promoted-slot
//! values from the normalized input and checks the received owned SSA against
//! that independently computed relation.
#![allow(
    clippy::result_large_err,
    clippy::too_many_arguments,
    clippy::too_many_lines
)]

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt;

use aether_ir::wire::{
    IRInstructionDTO, IRModuleDTO, NullableDTO, SSABoundsCheckedInstructionV2DTO,
    SSAControlInstructionDTO,
};
use aether_ir::{
    IRBasicBlock, IRFunction, IRInstruction, IRModule, IRSourceLocation, IRType, IRValue,
    LifecycleSource, OwnedSsaFunction, OwnedSsaInstruction, OwnedSsaModule, import_instruction,
    import_module,
};
use serde::Serialize;

/// Stable failure category for the refinement relation.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SsaRefinementErrorCategory {
    /// The normalized input could not be imported as owned IR.
    InputContract,
    /// Module or function declarations changed.
    Metadata,
    /// Reachable control-flow structure changed.
    ControlFlow,
    /// Load/store promotion cannot explain an SSA value.
    SlotPromotion,
    /// Preserved instruction correspondence changed.
    Instruction,
    /// SSA value definitions or provenance changed.
    Provenance,
    /// A phi is not justified by a promoted slot.
    Phi,
}

/// Stable sub-phase within refinement verification.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SsaRefinementPhase {
    /// Top-level declarations and struct definitions.
    ModuleMetadata,
    /// Function identity, signature, and parameters.
    FunctionMetadata,
    /// Reachable blocks, entry, and edges.
    ControlFlow,
    /// Definition identities derived from normalized Initial IR.
    InitialProvenance,
    /// Forward reaching-value analysis for promoted slots.
    SlotAnalysis,
    /// Phi prefix and preserved instruction correspondence.
    InstructionAlignment,
    /// Definition identities derived from received SSA.
    SsaProvenance,
    /// Phi predecessor, value, and slot justification.
    PhiVerification,
    /// Final field and operand-provenance comparison.
    SemanticPreservation,
}

/// Machine-readable rejection from the owned SSA refinement verifier.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct SsaRefinementVerificationError {
    /// Stable semantic class of rejection.
    pub category: SsaRefinementErrorCategory,
    /// Refinement sub-phase which rejected the pair.
    pub phase: SsaRefinementPhase,
    /// Stable diagnostic identifier.
    pub code: &'static str,
    /// Deterministic human-readable detail.
    pub message: String,
    /// Function containing the failure, when known.
    pub function: Option<String>,
    /// Block containing the failure, when known.
    pub block: Option<String>,
    /// Initial IR instruction index, when applicable.
    pub instruction_index: Option<usize>,
    /// Preserved Initial IR source location, when available.
    pub source_location: Option<RefinementSourceLocation>,
}

/// Source location retained by a refinement failure.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct RefinementSourceLocation {
    /// Optional source path.
    pub path: Option<String>,
    /// One-based source line.
    pub line: i64,
    /// One-based source column.
    pub column: i64,
}

impl From<&IRSourceLocation> for RefinementSourceLocation {
    fn from(value: &IRSourceLocation) -> Self {
        Self {
            path: value.path.clone(),
            line: value.line,
            column: value.column,
        }
    }
}

impl fmt::Display for SsaRefinementVerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for SsaRefinementVerificationError {}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
enum DefinitionField {
    Result,
    Exception,
    Event,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
enum Origin {
    Parameter {
        index: usize,
        name: String,
    },
    Instruction {
        block: String,
        index: usize,
        field: DefinitionField,
    },
    Uninitialized {
        slot: String,
    },
}

type Provenance = BTreeSet<Origin>;
type SlotState = BTreeMap<String, Provenance>;

#[derive(Clone)]
struct AlignedInstruction<'a> {
    block: String,
    initial_index: usize,
    initial: &'a IRInstruction,
    ssa: IRInstruction,
}

/// Verify that `ssa` is a justified refinement of lifecycle-normalized Initial IR.
pub fn verify_owned_ssa_refinement(
    normalized: &IRModuleDTO,
    ssa: &OwnedSsaModule,
) -> Result<(), SsaRefinementVerificationError> {
    let initial = import_module(normalized).map_err(|error| SsaRefinementVerificationError {
        category: SsaRefinementErrorCategory::InputContract,
        phase: SsaRefinementPhase::ModuleMetadata,
        code: "SSA-REFINE-INPUT-001",
        message: format!("normalized Initial IR import failed: {error}"),
        function: None,
        block: None,
        instruction_index: None,
        source_location: None,
    })?;
    ModuleVerifier::new(&initial, ssa).verify()
}

struct ModuleVerifier<'a> {
    initial: &'a IRModule,
    ssa: &'a OwnedSsaModule,
}

impl<'a> ModuleVerifier<'a> {
    fn new(initial: &'a IRModule, ssa: &'a OwnedSsaModule) -> Self {
        Self { initial, ssa }
    }

    fn verify(self) -> Result<(), SsaRefinementVerificationError> {
        if self.initial.functions.len() != self.ssa.functions.len() {
            return Err(module_error(
                SsaRefinementErrorCategory::Metadata,
                "SSA-REFINE-MODULE-001",
                format!(
                    "function count changed: Initial IR has {}, SSA has {}",
                    self.initial.functions.len(),
                    self.ssa.functions.len()
                ),
            ));
        }
        if self.initial.structs != self.ssa.structs {
            return Err(module_error(
                SsaRefinementErrorCategory::Metadata,
                "SSA-REFINE-MODULE-002",
                "module struct definitions changed",
            ));
        }
        for (initial, ssa) in self.initial.functions.iter().zip(&self.ssa.functions) {
            FunctionVerifier::new(initial, ssa).verify()?;
        }
        Ok(())
    }
}

fn module_error(
    category: SsaRefinementErrorCategory,
    code: &'static str,
    message: impl Into<String>,
) -> SsaRefinementVerificationError {
    SsaRefinementVerificationError {
        category,
        phase: SsaRefinementPhase::ModuleMetadata,
        code,
        message: message.into(),
        function: None,
        block: None,
        instruction_index: None,
        source_location: None,
    }
}

struct FunctionVerifier<'a> {
    initial: &'a IRFunction,
    ssa: &'a OwnedSsaFunction,
    initial_blocks: BTreeMap<&'a str, &'a IRBasicBlock>,
    ssa_blocks: BTreeMap<&'a str, &'a aether_ir::OwnedSsaBlock>,
    successors: BTreeMap<String, Vec<String>>,
    predecessors: BTreeMap<String, BTreeSet<String>>,
    reachable: Vec<String>,
    initial_origins: BTreeMap<String, Provenance>,
    load_origins: BTreeMap<(String, usize), Provenance>,
    load_origins_by_name: BTreeMap<String, Provenance>,
    slot_out: BTreeMap<String, SlotState>,
    slot_types: BTreeMap<String, IRType>,
    ssa_origins: BTreeMap<String, Provenance>,
    aligned: Vec<AlignedInstruction<'a>>,
}

impl<'a> FunctionVerifier<'a> {
    fn new(initial: &'a IRFunction, ssa: &'a OwnedSsaFunction) -> Self {
        Self {
            initial,
            ssa,
            initial_blocks: initial
                .blocks
                .iter()
                .map(|block| (block.name.as_str(), block))
                .collect(),
            ssa_blocks: ssa
                .blocks
                .iter()
                .map(|block| (block.id.as_str(), block))
                .collect(),
            successors: BTreeMap::new(),
            predecessors: BTreeMap::new(),
            reachable: Vec::new(),
            initial_origins: BTreeMap::new(),
            load_origins: BTreeMap::new(),
            load_origins_by_name: BTreeMap::new(),
            slot_out: BTreeMap::new(),
            slot_types: BTreeMap::new(),
            ssa_origins: BTreeMap::new(),
            aligned: Vec::new(),
        }
    }

    fn verify(mut self) -> Result<(), SsaRefinementVerificationError> {
        self.verify_function_metadata()?;
        self.derive_cfg()?;
        self.verify_cfg_refinement()?;
        self.index_initial_origins()?;
        self.analyze_promoted_slots()?;
        self.align_preserved_instructions()?;
        self.index_ssa_preserved_origins()?;
        self.derive_phi_origins()?;
        self.verify_phis()?;
        self.verify_preserved_instructions()
    }

    fn fail(
        &self,
        category: SsaRefinementErrorCategory,
        phase: SsaRefinementPhase,
        code: &'static str,
        message: impl Into<String>,
        block: Option<&str>,
        instruction_index: Option<usize>,
        source_location: Option<&IRSourceLocation>,
    ) -> SsaRefinementVerificationError {
        let detail = message.into();
        SsaRefinementVerificationError {
            category,
            phase,
            code,
            message: format!("function '{}': {detail}", self.initial.name),
            function: Some(self.initial.name.clone()),
            block: block.map(str::to_owned),
            instruction_index,
            source_location: source_location.map(RefinementSourceLocation::from),
        }
    }

    fn verify_function_metadata(&mut self) -> Result<(), SsaRefinementVerificationError> {
        if self.initial.name != self.ssa.id.as_str() {
            return Err(self.fail(
                SsaRefinementErrorCategory::Metadata,
                SsaRefinementPhase::FunctionMetadata,
                "SSA-REFINE-FUNCTION-001",
                format!("function identity changed to '{}'", self.ssa.id.as_str()),
                None,
                None,
                None,
            ));
        }
        if self.initial.return_type != self.ssa.return_type {
            return Err(self.fail(
                SsaRefinementErrorCategory::Metadata,
                SsaRefinementPhase::FunctionMetadata,
                "SSA-REFINE-FUNCTION-002",
                "return type changed",
                None,
                None,
                None,
            ));
        }
        if self.initial.may_throw != self.ssa.may_throw {
            return Err(self.fail(
                SsaRefinementErrorCategory::Metadata,
                SsaRefinementPhase::FunctionMetadata,
                "SSA-REFINE-FUNCTION-003",
                "may_throw contract changed",
                None,
                None,
                None,
            ));
        }
        if self.initial.parameters.len() != self.ssa.parameters.len() {
            return Err(self.fail(
                SsaRefinementErrorCategory::Metadata,
                SsaRefinementPhase::FunctionMetadata,
                "SSA-REFINE-FUNCTION-004",
                "parameter count changed",
                None,
                None,
                None,
            ));
        }
        for (index, (initial, ssa)) in self
            .initial
            .parameters
            .iter()
            .zip(&self.ssa.parameters)
            .enumerate()
        {
            if initial.name != ssa.name || initial.r#type != ssa.r#type {
                return Err(self.fail(
                    SsaRefinementErrorCategory::Metadata,
                    SsaRefinementPhase::FunctionMetadata,
                    "SSA-REFINE-FUNCTION-005",
                    format!("parameter {index} changed"),
                    None,
                    None,
                    None,
                ));
            }
            let origin = BTreeSet::from([Origin::Parameter {
                index,
                name: initial.name.clone(),
            }]);
            self.initial_origins
                .insert(initial.name.clone(), origin.clone());
            self.ssa_origins.insert(ssa.name.clone(), origin);
        }
        Ok(())
    }

    fn derive_cfg(&mut self) -> Result<(), SsaRefinementVerificationError> {
        if self.initial.blocks.is_empty() {
            return Err(self.fail(
                SsaRefinementErrorCategory::ControlFlow,
                SsaRefinementPhase::ControlFlow,
                "SSA-REFINE-CFG-001",
                "Initial IR has no entry block",
                None,
                None,
                None,
            ));
        }
        if self.initial_blocks.len() != self.initial.blocks.len() {
            return Err(self.fail(
                SsaRefinementErrorCategory::ControlFlow,
                SsaRefinementPhase::ControlFlow,
                "SSA-REFINE-CFG-002",
                "Initial IR contains duplicate block names",
                None,
                None,
                None,
            ));
        }
        if self.ssa_blocks.len() != self.ssa.blocks.len() {
            return Err(self.fail(
                SsaRefinementErrorCategory::ControlFlow,
                SsaRefinementPhase::ControlFlow,
                "SSA-REFINE-CFG-003",
                "SSA contains duplicate block names",
                None,
                None,
                None,
            ));
        }
        for block in &self.initial.blocks {
            let successors = terminator_successors(block).ok_or_else(|| {
                self.fail(
                    SsaRefinementErrorCategory::ControlFlow,
                    SsaRefinementPhase::ControlFlow,
                    "SSA-REFINE-CFG-004",
                    format!("block '{}' has no supported terminator", block.name),
                    Some(&block.name),
                    block.instructions.len().checked_sub(1),
                    block
                        .instructions
                        .last()
                        .and_then(instruction_source_location),
                )
            })?;
            for target in &successors {
                if !self.initial_blocks.contains_key(target.as_str()) {
                    return Err(self.fail(
                        SsaRefinementErrorCategory::ControlFlow,
                        SsaRefinementPhase::ControlFlow,
                        "SSA-REFINE-CFG-005",
                        format!("block '{}' targets missing block '{target}'", block.name),
                        Some(&block.name),
                        block.instructions.len().checked_sub(1),
                        block
                            .instructions
                            .last()
                            .and_then(instruction_source_location),
                    ));
                }
            }
            self.successors.insert(block.name.clone(), successors);
        }

        let entry = self.initial.blocks[0].name.clone();
        let mut seen = BTreeSet::new();
        let mut worklist = vec![entry];
        while let Some(block) = worklist.pop() {
            if !seen.insert(block.clone()) {
                continue;
            }
            for target in self.successors[&block].iter().rev() {
                worklist.push(target.clone());
            }
        }
        self.reachable = self
            .initial
            .blocks
            .iter()
            .filter(|block| seen.contains(&block.name))
            .map(|block| block.name.clone())
            .collect();
        self.predecessors = self
            .reachable
            .iter()
            .map(|name| (name.clone(), BTreeSet::new()))
            .collect();
        for source in &self.reachable {
            for target in &self.successors[source] {
                if seen.contains(target) {
                    self.predecessors
                        .get_mut(target)
                        .expect("reachable successor")
                        .insert(source.clone());
                }
            }
        }
        Ok(())
    }

    fn verify_cfg_refinement(&self) -> Result<(), SsaRefinementVerificationError> {
        let actual: Vec<&str> = self
            .ssa
            .blocks
            .iter()
            .map(|block| block.id.as_str())
            .collect();
        let expected: Vec<&str> = self.reachable.iter().map(String::as_str).collect();
        if actual != expected {
            return Err(self.fail(
                SsaRefinementErrorCategory::ControlFlow,
                SsaRefinementPhase::ControlFlow,
                "SSA-REFINE-CFG-006",
                format!("reachable block sequence changed: expected {expected:?}, got {actual:?}"),
                None,
                None,
                None,
            ));
        }
        if self.ssa.entry_block.as_str() != expected[0] {
            return Err(self.fail(
                SsaRefinementErrorCategory::ControlFlow,
                SsaRefinementPhase::ControlFlow,
                "SSA-REFINE-CFG-007",
                format!(
                    "entry changed from '{}' to '{}'",
                    expected[0],
                    self.ssa.entry_block.as_str()
                ),
                None,
                None,
                None,
            ));
        }
        Ok(())
    }

    fn index_initial_origins(&mut self) -> Result<(), SsaRefinementVerificationError> {
        for block_name in &self.reachable {
            let block = self.initial_blocks[block_name.as_str()];
            for (index, instruction) in block.instructions.iter().enumerate() {
                match instruction {
                    IRInstruction::IRLoad { slot, .. } | IRInstruction::IRStore { slot, .. } => {
                        if let Some(existing) = self.slot_types.get(&slot.name) {
                            if existing != &slot.r#type {
                                return Err(self.fail(
                                    SsaRefinementErrorCategory::SlotPromotion,
                                    SsaRefinementPhase::InitialProvenance,
                                    "SSA-REFINE-SLOT-001",
                                    format!("slot '{}' changes type", slot.name),
                                    Some(block_name),
                                    Some(index),
                                    instruction_source_location(instruction),
                                ));
                            }
                        } else {
                            self.slot_types
                                .insert(slot.name.clone(), slot.r#type.clone());
                        }
                    }
                    _ => {
                        for (value, field) in instruction_definitions(instruction) {
                            if self.initial_origins.contains_key(&value.name) {
                                return Err(self.fail(
                                    SsaRefinementErrorCategory::Provenance,
                                    SsaRefinementPhase::InitialProvenance,
                                    "SSA-REFINE-PROVENANCE-001",
                                    format!("Initial IR value '{}' is defined twice", value.name),
                                    Some(block_name),
                                    Some(index),
                                    instruction_source_location(instruction),
                                ));
                            }
                            self.initial_origins.insert(
                                value.name.clone(),
                                BTreeSet::from([Origin::Instruction {
                                    block: block_name.clone(),
                                    index,
                                    field,
                                }]),
                            );
                        }
                    }
                }
            }
        }
        Ok(())
    }

    fn analyze_promoted_slots(&mut self) -> Result<(), SsaRefinementVerificationError> {
        let entry = &self.reachable[0];
        let empty_state = || {
            self.slot_types
                .keys()
                .map(|slot| (slot.clone(), Provenance::new()))
                .collect::<SlotState>()
        };
        let mut block_in: BTreeMap<String, SlotState> = self
            .reachable
            .iter()
            .map(|name| (name.clone(), empty_state()))
            .collect();
        let mut block_out = block_in.clone();
        let mut loads: BTreeMap<(String, usize), Provenance> = BTreeMap::new();
        let mut loads_by_name: BTreeMap<String, Provenance> = BTreeMap::new();
        let maximum = self
            .reachable
            .len()
            .saturating_mul(self.slot_types.len().saturating_add(1))
            .saturating_mul(4)
            .max(1);
        for _ in 0..maximum {
            let mut changed = false;
            for block_name in &self.reachable {
                let incoming = if block_name == entry {
                    self.slot_types
                        .keys()
                        .map(|slot| {
                            (
                                slot.clone(),
                                BTreeSet::from([Origin::Uninitialized { slot: slot.clone() }]),
                            )
                        })
                        .collect()
                } else {
                    join_slot_states(
                        self.predecessors[block_name]
                            .iter()
                            .map(|predecessor| &block_out[predecessor]),
                    )
                };
                let mut aliases = self.initial_origins.clone();
                aliases.extend(loads_by_name.clone());
                let mut state = incoming.clone();
                let block = self.initial_blocks[block_name.as_str()];
                for (index, instruction) in block.instructions.iter().enumerate() {
                    match instruction {
                        IRInstruction::IRLoad { result, slot } => {
                            let value = state.get(&slot.name).cloned().unwrap_or_default();
                            if loads.get(&(block_name.clone(), index)) != Some(&value) {
                                changed = true;
                            }
                            aliases.insert(result.name.clone(), value.clone());
                            loads.insert((block_name.clone(), index), value.clone());
                            loads_by_name.insert(result.name.clone(), value);
                        }
                        IRInstruction::IRStore { slot, value } => {
                            state.insert(
                                slot.name.clone(),
                                aliases.get(&value.name).cloned().unwrap_or_default(),
                            );
                        }
                        _ => {}
                    }
                }
                if block_in[block_name] != incoming || block_out[block_name] != state {
                    block_in.insert(block_name.clone(), incoming);
                    block_out.insert(block_name.clone(), state);
                    changed = true;
                }
            }
            if !changed {
                let invalid: Vec<String> = loads
                    .iter()
                    .filter(|(_, provenance)| {
                        provenance.is_empty()
                            || provenance
                                .iter()
                                .any(|origin| matches!(origin, Origin::Uninitialized { .. }))
                    })
                    .filter_map(|((block, index), _)| {
                        let instruction = &self.initial_blocks[block.as_str()].instructions[*index];
                        let IRInstruction::IRLoad { result, .. } = instruction else {
                            return None;
                        };
                        Some(result.name.clone())
                    })
                    .collect();
                if !invalid.is_empty() {
                    return Err(self.fail(
                        SsaRefinementErrorCategory::SlotPromotion,
                        SsaRefinementPhase::SlotAnalysis,
                        "SSA-REFINE-SLOT-002",
                        format!(
                            "promoted loads have no reaching value: {}",
                            invalid.join(", ")
                        ),
                        None,
                        None,
                        None,
                    ));
                }
                self.slot_out = block_out;
                self.load_origins = loads;
                self.load_origins_by_name = loads_by_name;
                return Ok(());
            }
        }
        Err(self.fail(
            SsaRefinementErrorCategory::SlotPromotion,
            SsaRefinementPhase::SlotAnalysis,
            "SSA-REFINE-SLOT-003",
            "reaching-value dataflow did not converge",
            None,
            None,
            None,
        ))
    }

    fn align_preserved_instructions(&mut self) -> Result<(), SsaRefinementVerificationError> {
        for block_name in &self.reachable {
            let initial_block = self.initial_blocks[block_name.as_str()];
            let initial_instructions: Vec<(usize, &IRInstruction)> = initial_block
                .instructions
                .iter()
                .enumerate()
                .filter(|(_, instruction)| !is_promoted_instruction(instruction))
                .collect();
            let ssa_instructions = &self.ssa_blocks[block_name.as_str()].instructions;
            let first_non_phi = ssa_instructions
                .iter()
                .position(|instruction| !matches!(instruction, OwnedSsaInstruction::Phi { .. }))
                .unwrap_or(ssa_instructions.len());
            if ssa_instructions[first_non_phi..]
                .iter()
                .any(|instruction| matches!(instruction, OwnedSsaInstruction::Phi { .. }))
            {
                return Err(self.fail(
                    SsaRefinementErrorCategory::Phi,
                    SsaRefinementPhase::InstructionAlignment,
                    "SSA-REFINE-PHI-001",
                    format!("block '{block_name}' has a non-prefix phi"),
                    Some(block_name),
                    None,
                    None,
                ));
            }
            let preserved = &ssa_instructions[first_non_phi..];
            if initial_instructions.len() != preserved.len() {
                return Err(self.fail(
                    SsaRefinementErrorCategory::Instruction,
                    SsaRefinementPhase::InstructionAlignment,
                    "SSA-REFINE-INSTRUCTION-001",
                    format!(
                        "block '{block_name}' preserved instruction count changed: expected {}, got {}",
                        initial_instructions.len(),
                        preserved.len()
                    ),
                    Some(block_name),
                    None,
                    None,
                ));
            }
            for ((initial_index, initial), ssa) in initial_instructions.into_iter().zip(preserved) {
                let converted = owned_instruction_as_ir(ssa).map_err(|message| {
                    self.fail(
                        SsaRefinementErrorCategory::Instruction,
                        SsaRefinementPhase::InstructionAlignment,
                        "SSA-REFINE-INSTRUCTION-002",
                        message,
                        Some(block_name),
                        Some(initial_index),
                        instruction_source_location(initial),
                    )
                })?;
                if std::mem::discriminant(initial) != std::mem::discriminant(&converted) {
                    return Err(self.fail(
                        SsaRefinementErrorCategory::Instruction,
                        SsaRefinementPhase::InstructionAlignment,
                        "SSA-REFINE-INSTRUCTION-003",
                        format!("block '{block_name}' instruction {initial_index} changed opcode"),
                        Some(block_name),
                        Some(initial_index),
                        instruction_source_location(initial),
                    ));
                }
                self.aligned.push(AlignedInstruction {
                    block: block_name.clone(),
                    initial_index,
                    initial,
                    ssa: converted,
                });
            }
        }
        Ok(())
    }

    fn index_ssa_preserved_origins(&mut self) -> Result<(), SsaRefinementVerificationError> {
        for aligned in &self.aligned {
            let initial_definitions = instruction_definitions(aligned.initial);
            let ssa_definitions = instruction_definitions(&aligned.ssa);
            if initial_definitions.len() != ssa_definitions.len()
                || initial_definitions
                    .iter()
                    .zip(&ssa_definitions)
                    .any(|((_, left), (_, right))| left != right)
            {
                return Err(self.fail(
                    SsaRefinementErrorCategory::Provenance,
                    SsaRefinementPhase::SsaProvenance,
                    "SSA-REFINE-PROVENANCE-002",
                    format!(
                        "block '{}' instruction {} definition shape changed",
                        aligned.block, aligned.initial_index
                    ),
                    Some(&aligned.block),
                    Some(aligned.initial_index),
                    instruction_source_location(aligned.initial),
                ));
            }
            for ((initial_value, _), (ssa_value, _)) in
                initial_definitions.into_iter().zip(ssa_definitions)
            {
                if initial_value.r#type != ssa_value.r#type {
                    return Err(self.fail(
                        SsaRefinementErrorCategory::Provenance,
                        SsaRefinementPhase::SsaProvenance,
                        "SSA-REFINE-PROVENANCE-003",
                        format!(
                            "block '{}' instruction {} result type changed",
                            aligned.block, aligned.initial_index
                        ),
                        Some(&aligned.block),
                        Some(aligned.initial_index),
                        instruction_source_location(aligned.initial),
                    ));
                }
                if self.ssa_origins.contains_key(&ssa_value.name) {
                    return Err(self.fail(
                        SsaRefinementErrorCategory::Provenance,
                        SsaRefinementPhase::SsaProvenance,
                        "SSA-REFINE-PROVENANCE-004",
                        format!("SSA value '{}' is defined twice", ssa_value.name),
                        Some(&aligned.block),
                        Some(aligned.initial_index),
                        instruction_source_location(aligned.initial),
                    ));
                }
                self.ssa_origins.insert(
                    ssa_value.name.clone(),
                    self.initial_origins[&initial_value.name].clone(),
                );
            }
        }
        Ok(())
    }

    fn derive_phi_origins(&mut self) -> Result<(), SsaRefinementVerificationError> {
        let phis: Vec<(&str, &IRValue, &Vec<aether_ir::PhiIncoming>)> = self
            .ssa
            .blocks
            .iter()
            .flat_map(|block| {
                block.instructions.iter().filter_map(move |instruction| {
                    let OwnedSsaInstruction::Phi {
                        result, incoming, ..
                    } = instruction
                    else {
                        return None;
                    };
                    Some((block.id.as_str(), result, incoming))
                })
            })
            .collect();
        for (block, result, _) in &phis {
            if self.ssa_origins.contains_key(&result.name) {
                return Err(self.fail(
                    SsaRefinementErrorCategory::Provenance,
                    SsaRefinementPhase::SsaProvenance,
                    "SSA-REFINE-PROVENANCE-005",
                    format!("SSA value '{}' is defined twice", result.name),
                    Some(block),
                    None,
                    None,
                ));
            }
            self.ssa_origins
                .insert(result.name.clone(), Provenance::new());
        }
        let maximum = phis
            .len()
            .saturating_mul(self.initial_origins.len().saturating_add(1))
            .saturating_add(1)
            .max(1);
        for _ in 0..maximum {
            let mut changed = false;
            for (_, result, incoming) in &phis {
                let mut value = Provenance::new();
                for item in *incoming {
                    if let Some(origin) = self.ssa_origins.get(&item.value.name) {
                        value.extend(origin.iter().cloned());
                    }
                }
                if self.ssa_origins[&result.name] != value {
                    self.ssa_origins.insert(result.name.clone(), value);
                    changed = true;
                }
            }
            if !changed {
                return Ok(());
            }
        }
        Err(self.fail(
            SsaRefinementErrorCategory::Provenance,
            SsaRefinementPhase::SsaProvenance,
            "SSA-REFINE-PROVENANCE-006",
            "SSA phi provenance did not converge",
            None,
            None,
            None,
        ))
    }

    fn verify_phis(&self) -> Result<(), SsaRefinementVerificationError> {
        for block_name in &self.reachable {
            let phis: Vec<(&IRValue, &Vec<aether_ir::PhiIncoming>)> = self.ssa_blocks
                [block_name.as_str()]
            .instructions
            .iter()
            .filter_map(|instruction| {
                let OwnedSsaInstruction::Phi {
                    result, incoming, ..
                } = instruction
                else {
                    return None;
                };
                Some((result, incoming))
            })
            .collect();
            let predecessors = &self.predecessors[block_name];
            let mut candidates = Vec::new();
            for (result, incoming_values) in phis {
                if predecessors.len() < 2 {
                    return Err(self.fail(
                        SsaRefinementErrorCategory::Phi,
                        SsaRefinementPhase::PhiVerification,
                        "SSA-REFINE-PHI-002",
                        format!(
                            "phi '{}' in block '{block_name}' has no control-flow join to justify it",
                            result.name
                        ),
                        Some(block_name),
                        None,
                        None,
                    ));
                }
                let incoming: BTreeMap<&str, &IRValue> = incoming_values
                    .iter()
                    .map(|item| (item.predecessor.as_str(), &item.value))
                    .collect();
                if incoming.len() != incoming_values.len()
                    || incoming.keys().copied().collect::<BTreeSet<_>>()
                        != predecessors.iter().map(String::as_str).collect()
                {
                    return Err(self.fail(
                        SsaRefinementErrorCategory::Phi,
                        SsaRefinementPhase::PhiVerification,
                        "SSA-REFINE-PHI-003",
                        format!(
                            "phi '{}' in block '{block_name}' does not have exactly one incoming per predecessor",
                            result.name
                        ),
                        Some(block_name),
                        None,
                        None,
                    ));
                }
                let mut matching_slots = BTreeSet::new();
                for (slot, slot_type) in &self.slot_types {
                    if &result.r#type != slot_type {
                        continue;
                    }
                    let matches = predecessors.iter().all(|predecessor| {
                        let value = incoming[predecessor.as_str()];
                        value.r#type == *slot_type
                            && self.ssa_origins.get(&value.name)
                                == self.slot_out[predecessor].get(slot)
                    });
                    if matches {
                        matching_slots.insert(slot.clone());
                    }
                }
                if matching_slots.is_empty() {
                    return Err(self.fail(
                        SsaRefinementErrorCategory::Phi,
                        SsaRefinementPhase::PhiVerification,
                        "SSA-REFINE-PHI-004",
                        format!(
                            "phi '{}' in block '{block_name}' is not justified by any promoted slot",
                            result.name
                        ),
                        Some(block_name),
                        None,
                        None,
                    ));
                }
                if self.ssa_origins[&result.name].is_empty() {
                    return Err(self.fail(
                        SsaRefinementErrorCategory::Phi,
                        SsaRefinementPhase::PhiVerification,
                        "SSA-REFINE-PHI-005",
                        format!(
                            "phi '{}' in block '{block_name}' has no value provenance",
                            result.name
                        ),
                        Some(block_name),
                        None,
                        None,
                    ));
                }
                candidates.push(matching_slots);
            }
            if !has_distinct_slot_assignment(&candidates) {
                return Err(self.fail(
                    SsaRefinementErrorCategory::Phi,
                    SsaRefinementPhase::PhiVerification,
                    "SSA-REFINE-PHI-006",
                    format!("block '{block_name}' has duplicate or ambiguous extra phis"),
                    Some(block_name),
                    None,
                    None,
                ));
            }
        }
        Ok(())
    }

    fn verify_preserved_instructions(&self) -> Result<(), SsaRefinementVerificationError> {
        for aligned in &self.aligned {
            if matches!(
                aligned.initial,
                IRInstruction::IRReturn {
                    transferred_storage: Some(_),
                    ..
                }
            ) {
                return Err(self.fail(
                    SsaRefinementErrorCategory::InputContract,
                    SsaRefinementPhase::SemanticPreservation,
                    "SSA-REFINE-INPUT-002",
                    "input is not lifecycle-normalized: return still carries transferred_storage",
                    Some(&aligned.block),
                    Some(aligned.initial_index),
                    instruction_source_location(aligned.initial),
                ));
            }
            let mut initial = aligned.initial.clone();
            let mut ssa = aligned.ssa.clone();
            normalize_ignored_fields(&mut initial);
            normalize_ignored_fields(&mut ssa);
            canonicalize_instruction(&mut initial, |name| self.expected_initial_origin(name));
            canonicalize_instruction(&mut ssa, |name| self.ssa_origins.get(name));
            if initial != ssa {
                return Err(self.fail(
                    SsaRefinementErrorCategory::Instruction,
                    SsaRefinementPhase::SemanticPreservation,
                    "SSA-REFINE-INSTRUCTION-004",
                    format!(
                        "block '{}' instruction {} changed semantic fields or value provenance",
                        aligned.block, aligned.initial_index
                    ),
                    Some(&aligned.block),
                    Some(aligned.initial_index),
                    instruction_source_location(aligned.initial),
                ));
            }
        }
        Ok(())
    }

    fn expected_initial_origin(&self, name: &str) -> Option<&Provenance> {
        self.initial_origins
            .get(name)
            .or_else(|| self.load_origins_by_name.get(name))
    }
}

fn join_slot_states<'a>(states: impl Iterator<Item = &'a SlotState>) -> SlotState {
    let materialized: Vec<&SlotState> = states.collect();
    let mut slots = BTreeSet::new();
    for state in &materialized {
        slots.extend(state.keys().cloned());
    }
    slots
        .into_iter()
        .map(|slot| {
            let mut provenance = Provenance::new();
            for state in &materialized {
                if let Some(value) = state.get(&slot) {
                    provenance.extend(value.iter().cloned());
                }
            }
            (slot, provenance)
        })
        .collect()
}

fn terminator_successors(block: &IRBasicBlock) -> Option<Vec<String>> {
    match block.instructions.last()? {
        IRInstruction::IRBranch {
            true_target,
            false_target,
            ..
        } => {
            let mut result = vec![true_target.clone()];
            if false_target != true_target {
                result.push(false_target.clone());
            }
            Some(result)
        }
        IRInstruction::IRJump { target } => Some(vec![target.clone()]),
        IRInstruction::IRInvoke {
            normal_target,
            exceptional_target,
            ..
        }
        | IRInstruction::IRInvokeIndirect {
            normal_target,
            exceptional_target,
            ..
        }
        | IRInstruction::IRInvokeInterface {
            normal_target,
            exceptional_target,
            ..
        } => {
            let mut result = vec![normal_target.clone()];
            if exceptional_target != normal_target {
                result.push(exceptional_target.clone());
            }
            Some(result)
        }
        IRInstruction::IRThrow { target, .. }
        | IRInstruction::IRRethrow { target, .. }
        | IRInstruction::IRPropagate { target, .. } => Some(target.iter().cloned().collect()),
        IRInstruction::IRReturn { .. } => Some(Vec::new()),
        _ => None,
    }
}

fn is_promoted_instruction(instruction: &IRInstruction) -> bool {
    matches!(
        instruction,
        IRInstruction::IRLoad { .. } | IRInstruction::IRStore { .. }
    )
}

fn instruction_definitions(instruction: &IRInstruction) -> Vec<(&IRValue, DefinitionField)> {
    use IRInstruction as I;
    let result = match instruction {
        I::IRConst { result, .. }
        | I::IRLoad { result, .. }
        | I::IRBinaryOp { result, .. }
        | I::IRUnaryOp { result, .. }
        | I::IRCompareOp { result, .. }
        | I::IRCast { result, .. }
        | I::IRFunctionRef { result, .. }
        | I::IRStructNew { result, .. }
        | I::IRClassNew { result, .. }
        | I::IRClassGet { result, .. }
        | I::IRInterfaceConstruct { result, .. }
        | I::IRStructGet { result, .. }
        | I::IRStructSet { result, .. }
        | I::IRMethodResultNew { result, .. }
        | I::IRMethodResultReceiver { result, .. }
        | I::IRMethodResultValue { result, .. }
        | I::IRArrayNew { result, .. }
        | I::IRListNew { result, .. }
        | I::IRArrayCopy { result, .. }
        | I::IRListCopy { result, .. }
        | I::IRListContains { result, .. }
        | I::IRListIndexOf { result, .. }
        | I::IRListRemoveAt { result, .. }
        | I::IRListPop { result, .. }
        | I::IRVectorNew { result, .. }
        | I::IRMatrixNew { result, .. }
        | I::IRVectorAdd { result, .. }
        | I::IRVectorSub { result, .. }
        | I::IRVectorScale { result, .. }
        | I::IRVectorDot { result, .. }
        | I::IROuterProduct { result, .. }
        | I::IRMatrixAdd { result, .. }
        | I::IRMatrixSub { result, .. }
        | I::IRMatrixScale { result, .. }
        | I::IRMatrixMatMul { result, .. }
        | I::IRMatrixVectorMul { result, .. }
        | I::IRVectorMatrixMul { result, .. }
        | I::IRArrayGet { result, .. }
        | I::IRArraySlice { result, .. }
        | I::IRListSlice { result, .. }
        | I::IRListGet { result, .. }
        | I::IRVectorGet { result, .. }
        | I::IRMatrixGet { result, .. }
        | I::IRVectorLength { result, .. }
        | I::IRMatrixRows { result, .. }
        | I::IRMatrixColumns { result, .. }
        | I::IRArrayLength { result, .. }
        | I::IRListLength { result, .. }
        | I::IRListIsEmpty { result, .. }
        | I::IRPackException { result, .. }
        | I::IRExceptionMatch { result, .. }
        | I::IRExceptionPayload { result, .. } => Some(result),
        _ => None,
    };
    let mut definitions = result
        .map(|value| vec![(value, DefinitionField::Result)])
        .unwrap_or_default();
    match instruction {
        I::IRCall {
            result: Some(result),
            ..
        }
        | I::IRCallIndirect {
            result: Some(result),
            ..
        }
        | I::IRInterfaceCall {
            result: Some(result),
            ..
        } => definitions.push((result, DefinitionField::Result)),
        I::IRInvoke {
            result, exception, ..
        }
        | I::IRInvokeIndirect {
            result, exception, ..
        }
        | I::IRInvokeInterface {
            result, exception, ..
        } => {
            if let Some(result) = result {
                definitions.push((result, DefinitionField::Result));
            }
            definitions.push((exception, DefinitionField::Exception));
        }
        I::IRCatchEntry { event, .. } => definitions.push((event, DefinitionField::Event)),
        _ => {}
    }
    definitions
}

fn owned_instruction_as_ir(value: &OwnedSsaInstruction) -> Result<IRInstruction, String> {
    match value {
        OwnedSsaInstruction::Phi { .. } => {
            Err("phi appeared in preserved instruction range".into())
        }
        OwnedSsaInstruction::Ordinary { instruction, .. } => Ok(instruction.clone()),
        OwnedSsaInstruction::Control { wire } => control_as_ir(wire),
        OwnedSsaInstruction::BoundsChecked { wire } => bounds_checked_as_ir(wire),
    }
}

#[allow(clippy::too_many_lines)]
fn control_as_ir(value: &SSAControlInstructionDTO) -> Result<IRInstruction, String> {
    use SSAControlInstructionDTO as S;
    let dto = match value {
        S::Phi { .. } => return Err("phi appeared in preserved instruction range".into()),
        S::Invoke {
            function,
            arguments,
            result,
            exception,
            normal_target,
            exceptional_target,
            builtin,
            source_location,
            normal_arguments,
            exceptional_arguments,
        } => {
            let expected_normal: Vec<_> = result.0.iter().cloned().collect();
            if normal_arguments != &expected_normal {
                return Err("invoke changed normal edge value".into());
            }
            if exceptional_arguments.as_slice() != std::slice::from_ref(exception) {
                return Err("invoke changed exceptional edge value".into());
            }
            IRInstructionDTO::Invoke {
                function: function.clone(),
                arguments: arguments.clone(),
                result: result.clone(),
                exception: exception.clone(),
                normal_target: normal_target.clone(),
                exceptional_target: exceptional_target.clone(),
                exceptional_target_event: exception.clone(),
                builtin: builtin.clone(),
                source_location: source_location.clone(),
            }
        }
        S::InvokeIndirect {
            callee,
            arguments,
            result,
            exception,
            normal_target,
            exceptional_target,
            normal_arguments,
            exceptional_arguments,
        } => {
            let expected_normal: Vec<_> = result.0.iter().cloned().collect();
            if normal_arguments != &expected_normal {
                return Err("indirect invoke changed normal edge value".into());
            }
            if exceptional_arguments.as_slice() != std::slice::from_ref(exception) {
                return Err("indirect invoke changed exceptional edge value".into());
            }
            IRInstructionDTO::InvokeIndirect {
                callee: callee.clone(),
                arguments: arguments.clone(),
                result: result.clone(),
                exception: exception.clone(),
                normal_target: normal_target.clone(),
                exceptional_target: exceptional_target.clone(),
                exceptional_target_event: exception.clone(),
            }
        }
        S::InvokeInterface {
            receiver,
            arguments,
            slot,
            result,
            exception,
            normal_target,
            exceptional_target,
            normal_arguments,
            exceptional_arguments,
        } => {
            let expected_normal: Vec<_> = result.0.iter().cloned().collect();
            if normal_arguments != &expected_normal {
                return Err("interface invoke changed normal edge value".into());
            }
            if exceptional_arguments.as_slice() != std::slice::from_ref(exception) {
                return Err("interface invoke changed exceptional edge value".into());
            }
            IRInstructionDTO::InvokeInterface {
                receiver: receiver.clone(),
                arguments: arguments.clone(),
                slot: slot.clone(),
                result: result.clone(),
                exception: exception.clone(),
                normal_target: normal_target.clone(),
                exceptional_target: exceptional_target.clone(),
                exceptional_target_event: exception.clone(),
            }
        }
        S::Throw {
            event,
            target,
            exceptional_arguments,
        }
        | S::Rethrow {
            event,
            target,
            exceptional_arguments,
        }
        | S::Propagate {
            event,
            target,
            exceptional_arguments,
        } => {
            let expected: Vec<_> = target
                .0
                .as_ref()
                .map(|_| event.clone())
                .into_iter()
                .collect();
            if exceptional_arguments != &expected {
                return Err("exception transfer changed edge value".into());
            }
            let target_event = NullableDTO(target.0.as_ref().map(|_| event.clone()));
            match value {
                S::Throw { .. } => IRInstructionDTO::Throw {
                    event: event.clone(),
                    target: target.clone(),
                    target_event,
                },
                S::Rethrow { .. } => IRInstructionDTO::Rethrow {
                    event: event.clone(),
                    target: target.clone(),
                    target_event,
                },
                S::Propagate { .. } => IRInstructionDTO::Propagate {
                    event: event.clone(),
                    target: target.clone(),
                    target_event,
                },
                _ => unreachable!(),
            }
        }
    };
    import_instruction(&dto).map_err(|error| format!("owned control conversion failed: {error}"))
}

fn bounds_checked_as_ir(value: &SSABoundsCheckedInstructionV2DTO) -> Result<IRInstruction, String> {
    use SSABoundsCheckedInstructionV2DTO as B;
    let dto = match value {
        B::ArrayGet {
            result,
            array,
            index,
            borrowed,
            borrow_scope,
            source_location,
            bounds_checked,
        } => {
            require_bounds_checked(*bounds_checked)?;
            IRInstructionDTO::ArrayGet {
                result: result.clone(),
                array: array.clone(),
                index: index.clone(),
                borrowed: *borrowed,
                borrow_scope: borrow_scope.clone(),
                source_location: source_location.clone(),
            }
        }
        B::ArraySet {
            array,
            index,
            value,
            bounds_checked,
        } => {
            require_bounds_checked(*bounds_checked)?;
            IRInstructionDTO::ArraySet {
                array: array.clone(),
                index: index.clone(),
                value: value.clone(),
            }
        }
        B::ListGet {
            result,
            list_value,
            index,
            borrowed,
            borrow_scope,
            source_location,
            bounds_checked,
        } => {
            require_bounds_checked(*bounds_checked)?;
            IRInstructionDTO::ListGet {
                result: result.clone(),
                list_value: list_value.clone(),
                index: index.clone(),
                borrowed: *borrowed,
                borrow_scope: borrow_scope.clone(),
                source_location: source_location.clone(),
            }
        }
        B::ListSet {
            list_value,
            index,
            value,
            bounds_checked,
        } => {
            require_bounds_checked(*bounds_checked)?;
            IRInstructionDTO::ListSet {
                list_value: list_value.clone(),
                index: index.clone(),
                value: value.clone(),
            }
        }
        B::VectorGet {
            result,
            vector,
            index,
            bounds_checked,
        } => {
            require_bounds_checked(*bounds_checked)?;
            IRInstructionDTO::VectorGet {
                result: result.clone(),
                vector: vector.clone(),
                index: index.clone(),
            }
        }
        B::VectorSet {
            vector,
            index,
            value,
            bounds_checked,
        } => {
            require_bounds_checked(*bounds_checked)?;
            IRInstructionDTO::VectorSet {
                vector: vector.clone(),
                index: index.clone(),
                value: value.clone(),
            }
        }
        B::MatrixGet {
            result,
            matrix,
            row,
            column,
            shape,
            bounds_checked,
        } => {
            require_bounds_checked(*bounds_checked)?;
            IRInstructionDTO::MatrixGet {
                result: result.clone(),
                matrix: matrix.clone(),
                row: row.clone(),
                column: column.clone(),
                shape: *shape,
            }
        }
        B::MatrixSet {
            matrix,
            row,
            column,
            value,
            shape,
            bounds_checked,
        } => {
            require_bounds_checked(*bounds_checked)?;
            IRInstructionDTO::MatrixSet {
                matrix: matrix.clone(),
                row: row.clone(),
                column: column.clone(),
                value: value.clone(),
                shape: *shape,
            }
        }
    };
    import_instruction(&dto).map_err(|error| format!("owned checked conversion failed: {error}"))
}

fn require_bounds_checked(value: bool) -> Result<(), String> {
    if value {
        Ok(())
    } else {
        Err("SSA instruction disabled bounds checks".into())
    }
}

fn has_distinct_slot_assignment(candidates: &[BTreeSet<String>]) -> bool {
    fn assign(
        phi: usize,
        candidates: &[BTreeSet<String>],
        assigned: &mut BTreeMap<String, usize>,
        visited: &mut BTreeSet<String>,
    ) -> bool {
        for slot in &candidates[phi] {
            if !visited.insert(slot.clone()) {
                continue;
            }
            let previous = assigned.get(slot).copied();
            if previous.is_none_or(|index| assign(index, candidates, assigned, visited)) {
                assigned.insert(slot.clone(), phi);
                return true;
            }
        }
        false
    }

    let mut assigned = BTreeMap::new();
    (0..candidates.len()).all(|phi| assign(phi, candidates, &mut assigned, &mut BTreeSet::new()))
}

fn canonical_name(provenance: Option<&Provenance>, original: &str) -> String {
    match provenance {
        Some(value) => format!("$origin:{value:?}"),
        None => format!("$unknown:{original}"),
    }
}

fn rewrite_value<'p, F>(value: &mut IRValue, provenance: &F)
where
    F: Fn(&str) -> Option<&'p Provenance>,
{
    value.name = canonical_name(provenance(&value.name), &value.name);
}

fn rewrite_values<'p, F>(values: &mut [IRValue], provenance: &F)
where
    F: Fn(&str) -> Option<&'p Provenance>,
{
    for value in values {
        rewrite_value(value, provenance);
    }
}

fn rewrite_optional_value<'p, F>(value: &mut Option<IRValue>, provenance: &F)
where
    F: Fn(&str) -> Option<&'p Provenance>,
{
    if let Some(value) = value {
        rewrite_value(value, provenance);
    }
}

fn rewrite_lifecycle_source<'p, F>(value: &mut LifecycleSource, provenance: &F)
where
    F: Fn(&str) -> Option<&'p Provenance>,
{
    if let LifecycleSource::Value(value) = value {
        rewrite_value(value, provenance);
    }
}

fn normalize_ignored_fields(instruction: &mut IRInstruction) {
    match instruction {
        IRInstruction::IRCall { may_throw, .. } => *may_throw = false,
        IRInstruction::IRInvoke {
            exception,
            exceptional_target_event,
            ..
        }
        | IRInstruction::IRInvokeIndirect {
            exception,
            exceptional_target_event,
            ..
        }
        | IRInstruction::IRInvokeInterface {
            exception,
            exceptional_target_event,
            ..
        } => *exceptional_target_event = exception.clone(),
        IRInstruction::IRThrow { target_event, .. }
        | IRInstruction::IRRethrow { target_event, .. }
        | IRInstruction::IRPropagate { target_event, .. } => *target_event = None,
        _ => {}
    }
}

#[allow(clippy::too_many_lines)]
fn canonicalize_instruction<'p>(
    instruction: &mut IRInstruction,
    provenance: impl Fn(&str) -> Option<&'p Provenance>,
) {
    use IRInstruction as I;
    macro_rules! values {
        ($($value:expr),+ $(,)?) => {{ $(rewrite_value($value, &provenance);)+ }};
    }
    match instruction {
        I::IRConst { result, .. } | I::IRClassNew { result } | I::IRFunctionRef { result, .. } => {
            values!(result);
        }
        I::IRLoad { result, slot } => values!(result, slot),
        I::IRStore { slot, value } => values!(slot, value),
        I::IRInitDefault { .. }
        | I::IRCopyInit { .. }
        | I::IRMoveInit { .. }
        | I::IRAssign { .. }
        | I::IRDestroy { .. }
        | I::IRRelocate { .. }
        | I::IRJump { .. } => {}
        I::IRBinaryOp {
            result,
            left,
            right,
            ..
        }
        | I::IRCompareOp {
            result,
            left,
            right,
            ..
        }
        | I::IRVectorAdd {
            result,
            left,
            right,
            ..
        }
        | I::IRVectorSub {
            result,
            left,
            right,
            ..
        }
        | I::IRVectorDot {
            result,
            left,
            right,
            ..
        }
        | I::IRMatrixAdd {
            result,
            left,
            right,
            ..
        }
        | I::IRMatrixSub {
            result,
            left,
            right,
            ..
        }
        | I::IRMatrixMatMul {
            result,
            left,
            right,
            ..
        } => values!(result, left, right),
        I::IRUnaryOp {
            result, operand, ..
        }
        | I::IRCast {
            result,
            value: operand,
        } => values!(result, operand),
        I::IRCall {
            arguments, result, ..
        } => {
            rewrite_values(arguments, &provenance);
            rewrite_optional_value(result, &provenance);
        }
        I::IRInvoke {
            arguments,
            result,
            exception,
            exceptional_target_event,
            ..
        } => {
            rewrite_values(arguments, &provenance);
            rewrite_optional_value(result, &provenance);
            values!(exception, exceptional_target_event);
        }
        I::IRCallIndirect {
            callee,
            arguments,
            result,
        } => {
            values!(callee);
            rewrite_values(arguments, &provenance);
            rewrite_optional_value(result, &provenance);
        }
        I::IRInvokeIndirect {
            callee,
            arguments,
            result,
            exception,
            exceptional_target_event,
            ..
        } => {
            values!(callee);
            rewrite_values(arguments, &provenance);
            rewrite_optional_value(result, &provenance);
            values!(exception, exceptional_target_event);
        }
        I::IRPrint { value, .. }
        | I::IRListClear { list_value: value }
        | I::IRListReverse { list_value: value }
        | I::IRSequenceSort { sequence: value }
        | I::IRExceptionDestroy { event: value } => values!(value),
        I::IRStructNew { result, fields }
        | I::IRArrayNew {
            result,
            elements: fields,
        }
        | I::IRListNew {
            result,
            elements: fields,
        }
        | I::IRVectorNew {
            result,
            elements: fields,
            ..
        }
        | I::IRMatrixNew {
            result,
            elements: fields,
            ..
        } => {
            values!(result);
            rewrite_values(fields, &provenance);
        }
        I::IRClassGet { result, object, .. } => values!(result, object),
        I::IRClassSet { object, value, .. } => values!(object, value),
        I::IRInterfaceConstruct {
            result, carrier, ..
        } => values!(result, carrier),
        I::IRInterfaceCall {
            receiver,
            arguments,
            result,
            ..
        } => {
            values!(receiver);
            rewrite_values(arguments, &provenance);
            rewrite_optional_value(result, &provenance);
        }
        I::IRInvokeInterface {
            receiver,
            arguments,
            result,
            exception,
            exceptional_target_event,
            ..
        } => {
            values!(receiver);
            rewrite_values(arguments, &provenance);
            rewrite_optional_value(result, &provenance);
            values!(exception, exceptional_target_event);
        }
        I::IRStructGet {
            result, r#struct, ..
        }
        | I::IRMethodResultReceiver {
            result,
            method_result: r#struct,
        }
        | I::IRMethodResultValue {
            result,
            method_result: r#struct,
        }
        | I::IRArrayCopy {
            result,
            array: r#struct,
            ..
        }
        | I::IRListCopy {
            result,
            list_value: r#struct,
            ..
        }
        | I::IRListPop {
            result,
            list_value: r#struct,
        }
        | I::IRVectorLength {
            result,
            vector: r#struct,
        }
        | I::IRMatrixRows {
            result,
            matrix: r#struct,
            ..
        }
        | I::IRMatrixColumns {
            result,
            matrix: r#struct,
            ..
        }
        | I::IRArrayLength {
            result,
            array: r#struct,
        }
        | I::IRListLength {
            result,
            list_value: r#struct,
        }
        | I::IRListIsEmpty {
            result,
            list_value: r#struct,
        } => values!(result, r#struct),
        I::IRStructSet {
            result,
            r#struct,
            value,
            ..
        } => values!(result, r#struct, value),
        I::IRMethodResultNew {
            result,
            receiver,
            value,
        } => {
            values!(result, receiver);
            rewrite_optional_value(value, &provenance);
        }
        I::IRListContains {
            result,
            list_value,
            value,
        }
        | I::IRListIndexOf {
            result,
            list_value,
            value,
        } => values!(result, list_value, value),
        I::IRListPush { list_value, value } => values!(list_value, value),
        I::IRListInsert {
            list_value,
            index,
            value,
        }
        | I::IRListSet {
            list_value,
            index,
            value,
        } => values!(list_value, index, value),
        I::IRListRemoveAt {
            result,
            list_value,
            index,
        }
        | I::IRListGet {
            result,
            list_value,
            index,
            ..
        } => values!(result, list_value, index),
        I::IRVectorScale {
            result,
            vector,
            scalar,
            ..
        } => values!(result, vector, scalar),
        I::IROuterProduct {
            result,
            column,
            row,
            ..
        } => values!(result, column, row),
        I::IRMatrixScale {
            result,
            matrix,
            scalar,
            ..
        } => values!(result, matrix, scalar),
        I::IRMatrixVectorMul {
            result,
            matrix,
            vector,
            ..
        } => values!(result, matrix, vector),
        I::IRVectorMatrixMul {
            result,
            vector,
            matrix,
            ..
        } => values!(result, vector, matrix),
        I::IRArrayGet {
            result,
            array,
            index,
            ..
        } => values!(result, array, index),
        I::IRArraySlice {
            result,
            array,
            start,
            end,
            ..
        } => values!(result, array, start, end),
        I::IRListSlice {
            result,
            list_value,
            start,
            end,
            ..
        } => values!(result, list_value, start, end),
        I::IRVectorGet {
            result,
            vector,
            index,
        } => values!(result, vector, index),
        I::IRMatrixGet {
            result,
            matrix,
            row,
            column,
            ..
        } => values!(result, matrix, row, column),
        I::IRArraySet {
            array,
            index,
            value,
        }
        | I::IRVectorSet {
            vector: array,
            index,
            value,
        } => values!(array, index, value),
        I::IRMatrixSet {
            matrix,
            row,
            column,
            value,
            ..
        } => values!(matrix, row, column, value),
        I::IRPackException {
            result, payload, ..
        } => values!(result, payload),
        I::IRCatchEntry { event, .. } => values!(event),
        I::IRExceptionMatch { result, event, .. } | I::IRExceptionPayload { result, event, .. } => {
            values!(result, event);
        }
        I::IRThrow {
            event,
            target_event,
            ..
        }
        | I::IRRethrow {
            event,
            target_event,
            ..
        }
        | I::IRPropagate {
            event,
            target_event,
            ..
        } => {
            values!(event);
            rewrite_optional_value(target_event, &provenance);
        }
        I::IRBranch { condition, .. } => values!(condition),
        I::IRReturn { value, .. } => {
            if let Some(value) = value {
                rewrite_lifecycle_source(value, &provenance);
            }
        }
    }
}

fn instruction_source_location(instruction: &IRInstruction) -> Option<&IRSourceLocation> {
    match instruction {
        IRInstruction::IRInitDefault {
            source_location, ..
        }
        | IRInstruction::IRCopyInit {
            source_location, ..
        }
        | IRInstruction::IRMoveInit {
            source_location, ..
        }
        | IRInstruction::IRAssign {
            source_location, ..
        }
        | IRInstruction::IRDestroy {
            source_location, ..
        }
        | IRInstruction::IRRelocate {
            source_location, ..
        }
        | IRInstruction::IRBinaryOp {
            source_location, ..
        }
        | IRInstruction::IRCall {
            source_location, ..
        }
        | IRInstruction::IRInvoke {
            source_location, ..
        }
        | IRInstruction::IRArrayCopy {
            source_location, ..
        }
        | IRInstruction::IRListCopy {
            source_location, ..
        }
        | IRInstruction::IRArrayGet {
            source_location, ..
        }
        | IRInstruction::IRArraySlice {
            source_location, ..
        }
        | IRInstruction::IRListSlice {
            source_location, ..
        }
        | IRInstruction::IRListGet {
            source_location, ..
        }
        | IRInstruction::IRPackException {
            source_location, ..
        } => source_location.as_ref(),
        _ => None,
    }
}
