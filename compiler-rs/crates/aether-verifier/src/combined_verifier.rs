//! Canonical fail-fast orchestration and normalized verifier diagnostics.

use std::error::Error;
use std::fmt;

use aether_ir::{IRConstant, IRInstruction, IRModule};

use crate::dominance_verifier::verify_module_dominance_after_prerequisites;
use crate::lifecycle_verifier::verify_module_lifecycle_after_structure;
use crate::return_verifier::verify_module_returns_after_structure;
use crate::{
    BorrowRule, BorrowRuleError, ControlFlowRuleError, FunctionLifecycleVerificationError,
    FunctionReturnVerificationError, FunctionSSAError, FunctionStructureVerificationError,
    FunctionTypeVerificationError, InstructionKind, LifecycleOperation, LifecycleRuleError,
    ModuleDominanceError, ModuleLifecycleVerificationError, ModuleReturnVerificationError,
    ModuleSSAError, ModuleStructureVerificationError, ModuleTypeVerificationError,
    SSADefinitionError, TypeExpectation, TypeRuleError, verify_module_ssa, verify_module_structure,
    verify_module_types,
};

/// Result returned by [`verify_module`].
///
/// Success is represented by `Ok(())`; failure contains one normalized,
/// deterministic diagnostic and its original typed verifier error.
pub type VerificationResult = Result<(), VerificationFailure>;

/// The verifier pass that rejected a module.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[non_exhaustive]
pub enum VerificationPhase {
    /// Module, declaration, block, terminator, and target structure.
    Structure,
    /// Declaration and instruction-local type contracts.
    Types,
    /// Function-local SSA definitions, ordering, and references.
    Ssa,
    /// Cross-block SSA dominance.
    Dominance,
    /// Storage lifecycle data flow and ownership completion.
    Lifecycle,
    /// Entry-rooted non-void return coverage.
    Returns,
}

impl fmt::Display for VerificationPhase {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Structure => "structure",
            Self::Types => "types",
            Self::Ssa => "ssa",
            Self::Dominance => "dominance",
            Self::Lifecycle => "lifecycle",
            Self::Returns => "returns",
        })
    }
}

/// Stable semantic category for a normalized verification failure.
///
/// These categories mirror the Initial IR invariant inventory and are
/// intentionally independent from the Rust pass that happened to detect the
/// failure.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[non_exhaustive]
pub enum VerificationErrorCategory {
    /// Duplicate or malformed declarations and definitions.
    Definitions,
    /// Type grammar and type-contract failures.
    Types,
    /// Basic control-flow graph failures.
    Cfg,
    /// General instruction-contract failures.
    Instructions,
    /// Return-value and return-path failures.
    Returns,
    /// Lifecycle operation, state, or ownership failures.
    Lifecycle,
    /// SSA/storage availability and state-flow failures.
    DataFlow,
    /// Borrow-scope and borrow-escape failures.
    Borrowing,
    /// Direct, indirect, and function-reference call failures.
    Calls,
    /// Canonical builtin contract failures.
    Builtins,
    /// Constant contract failures.
    Constants,
    /// Scalar and aggregate operator failures.
    Operators,
    /// Nominal struct instruction failures.
    Structs,
    /// Method-result instruction failures.
    MethodResults,
    /// Array and list instruction failures.
    Collections,
    /// Vector and matrix instruction failures.
    LinearAlgebra,
}

impl fmt::Display for VerificationErrorCategory {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Definitions => "definitions",
            Self::Types => "types",
            Self::Cfg => "cfg",
            Self::Instructions => "instructions",
            Self::Returns => "returns",
            Self::Lifecycle => "lifecycle",
            Self::DataFlow => "data_flow",
            Self::Borrowing => "borrowing",
            Self::Calls => "calls",
            Self::Builtins => "builtins",
            Self::Constants => "constants",
            Self::Operators => "operators",
            Self::Structs => "structs",
            Self::MethodResults => "method_results",
            Self::Collections => "collections",
            Self::LinearAlgebra => "linear_algebra",
        })
    }
}

/// Stable retained-IR context for a verification failure.
///
/// A module-level failure has every optional field set to `None`. Nested fields
/// are populated only when the original typed diagnostic identifies them.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
#[non_exhaustive]
pub struct VerificationContext {
    /// Zero-based function index in retained module order.
    pub function_index: Option<usize>,
    /// Exact function name.
    pub function_name: Option<String>,
    /// Zero-based block index in retained function order.
    pub block_index: Option<usize>,
    /// Exact block name.
    pub block_name: Option<String>,
    /// Zero-based instruction index in retained block order.
    pub instruction_index: Option<usize>,
    /// Exact instruction variant.
    pub instruction_kind: Option<InstructionKind>,
}

/// Original typed error selected by the combined verifier.
///
/// Variants are boxed to keep the public result small. [`Error::source`]
/// exposes the corresponding existing module-level verifier error.
#[derive(Clone, Debug, PartialEq, Eq)]
#[non_exhaustive]
pub enum VerificationError {
    /// Structural verifier failure.
    Structure(Box<ModuleStructureVerificationError>),
    /// Type verifier failure.
    Types(Box<ModuleTypeVerificationError>),
    /// SSA verifier failure.
    Ssa(Box<ModuleSSAError>),
    /// Dominance verifier failure.
    Dominance(Box<ModuleDominanceError>),
    /// Complete lifecycle verifier failure.
    Lifecycle(Box<ModuleLifecycleVerificationError>),
    /// All-path return verifier failure.
    Returns(Box<ModuleReturnVerificationError>),
}

impl VerificationError {
    fn phase(&self) -> VerificationPhase {
        match self {
            Self::Structure(_) => VerificationPhase::Structure,
            Self::Types(_) => VerificationPhase::Types,
            Self::Ssa(_) => VerificationPhase::Ssa,
            Self::Dominance(_) => VerificationPhase::Dominance,
            Self::Lifecycle(_) => VerificationPhase::Lifecycle,
            Self::Returns(_) => VerificationPhase::Returns,
        }
    }
}

impl fmt::Display for VerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Structure(error) => error.fmt(formatter),
            Self::Types(error) => error.fmt(formatter),
            Self::Ssa(error) => error.fmt(formatter),
            Self::Dominance(error) => error.fmt(formatter),
            Self::Lifecycle(error) => error.fmt(formatter),
            Self::Returns(error) => error.fmt(formatter),
        }
    }
}

impl Error for VerificationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(match self {
            Self::Structure(error) => error.as_ref(),
            Self::Types(error) => error.as_ref(),
            Self::Ssa(error) => error.as_ref(),
            Self::Dominance(error) => error.as_ref(),
            Self::Lifecycle(error) => error.as_ref(),
            Self::Returns(error) => error.as_ref(),
        })
    }
}

/// One normalized, deterministic rejection from [`verify_module`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VerificationFailure {
    phase: VerificationPhase,
    category: VerificationErrorCategory,
    invariant_id: Option<&'static str>,
    context: VerificationContext,
    message: String,
    source: VerificationError,
}

impl VerificationFailure {
    /// Returns the pass that rejected the module.
    #[must_use]
    pub const fn phase(&self) -> VerificationPhase {
        self.phase
    }

    /// Returns the stable semantic diagnostic category.
    #[must_use]
    pub const fn category(&self) -> VerificationErrorCategory {
        self.category
    }

    /// Returns the stable `IRV-NNN` identifier when normalization can identify it.
    #[must_use]
    pub const fn invariant_id(&self) -> Option<&'static str> {
        self.invariant_id
    }

    /// Returns retained function, block, and instruction context.
    #[must_use]
    pub const fn context(&self) -> &VerificationContext {
        &self.context
    }

    /// Returns the deterministic human-readable message.
    #[must_use]
    pub fn message(&self) -> &str {
        &self.message
    }

    /// Returns the original typed module-level verifier error.
    #[must_use]
    pub const fn underlying_error(&self) -> &VerificationError {
        &self.source
    }
}

impl fmt::Display for VerificationFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for VerificationFailure {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(&self.source)
    }
}

/// Runs every complete Initial IR verifier pass in canonical fail-fast order.
///
/// The order is structure, types, SSA, dominance, lifecycle, then returns.
/// Each existing module pass remains independently callable; this function
/// only orchestrates them and stops at the first failure.
pub fn verify_module(module: &IRModule) -> VerificationResult {
    verify_module_structure(module).map_err(|error| {
        normalize_failure(module, VerificationError::Structure(Box::new(error)))
    })?;
    verify_module_types(module)
        .map_err(|error| normalize_failure(module, VerificationError::Types(Box::new(error))))?;
    verify_module_ssa(module)
        .map_err(|error| normalize_failure(module, VerificationError::Ssa(Box::new(error))))?;
    verify_module_dominance_after_prerequisites(module).map_err(|error| {
        normalize_failure(module, VerificationError::Dominance(Box::new(error)))
    })?;
    verify_module_lifecycle_after_structure(module).map_err(|error| {
        normalize_failure(module, VerificationError::Lifecycle(Box::new(error)))
    })?;
    verify_module_returns_after_structure(module)
        .map_err(|error| normalize_failure(module, VerificationError::Returns(Box::new(error))))?;
    Ok(())
}

fn normalize_failure(module: &IRModule, source: VerificationError) -> VerificationFailure {
    let phase = source.phase();
    let context = verification_context(&source);
    let classification = classify_failure(module, &source, &context);
    let message = source.to_string();
    VerificationFailure {
        phase,
        category: classification.category,
        invariant_id: classification.invariant_id,
        context,
        message,
        source,
    }
}

#[derive(Clone, Copy)]
struct Classification {
    invariant_id: Option<&'static str>,
    category: VerificationErrorCategory,
}

const fn classified(
    invariant_id: &'static str,
    category: VerificationErrorCategory,
) -> Classification {
    Classification {
        invariant_id: Some(invariant_id),
        category,
    }
}

const fn unclassified(category: VerificationErrorCategory) -> Classification {
    Classification {
        invariant_id: None,
        category,
    }
}

fn verification_context(error: &VerificationError) -> VerificationContext {
    match error {
        VerificationError::Structure(error) => structure_context(error),
        VerificationError::Types(error) => type_context(error),
        VerificationError::Ssa(error) => ssa_context(error),
        VerificationError::Dominance(error) => {
            let mut context = VerificationContext {
                function_index: Some(error.function_index),
                function_name: Some(error.function_name.clone()),
                ..VerificationContext::default()
            };
            if let crate::FunctionDominanceError::Block {
                block_index,
                block_name,
                source,
                ..
            } = error.source.as_ref()
            {
                context.block_index = Some(*block_index);
                context.block_name = Some(block_name.clone());
                context.instruction_index = Some(source.instruction_index);
                context.instruction_kind = Some(source.instruction_kind);
            }
            context
        }
        VerificationError::Lifecycle(error) => lifecycle_context(error),
        VerificationError::Returns(error) => return_context(error),
    }
}

fn structure_context(error: &ModuleStructureVerificationError) -> VerificationContext {
    let ModuleStructureVerificationError::Function {
        function_index,
        function_name,
        source,
    } = error
    else {
        return VerificationContext::default();
    };
    let mut context = VerificationContext {
        function_index: Some(*function_index),
        function_name: Some(function_name.clone()),
        ..VerificationContext::default()
    };
    match source.as_ref() {
        FunctionStructureVerificationError::DuplicateBlockName {
            block_index,
            block_name,
            ..
        } => {
            context.block_index = Some(*block_index);
            context.block_name = Some(block_name.clone());
        }
        FunctionStructureVerificationError::Block {
            block_index,
            block_name,
            source,
            ..
        } => {
            context.block_index = Some(*block_index);
            context.block_name = Some(block_name.clone());
            context.instruction_index = source.instruction_index;
            context.instruction_kind = source.instruction_kind;
        }
        FunctionStructureVerificationError::DuplicateParameterName { .. }
        | FunctionStructureVerificationError::EmptyFunction { .. }
        | FunctionStructureVerificationError::MissingEntryBlock { .. } => {}
    }
    context
}

fn type_context(error: &ModuleTypeVerificationError) -> VerificationContext {
    let ModuleTypeVerificationError::Function {
        function_index,
        function_name,
        source,
    } = error
    else {
        return VerificationContext::default();
    };
    let mut context = VerificationContext {
        function_index: Some(*function_index),
        function_name: Some(function_name.clone()),
        ..VerificationContext::default()
    };
    if let FunctionTypeVerificationError::Block {
        block_index,
        block_name,
        source,
        ..
    } = source
    {
        context.block_index = Some(*block_index);
        context.block_name = Some(block_name.clone());
        context.instruction_index = Some(source.instruction_index);
        context.instruction_kind = Some(source.instruction_kind);
    }
    context
}

fn ssa_context(error: &ModuleSSAError) -> VerificationContext {
    let mut context = VerificationContext {
        function_index: Some(error.function_index),
        function_name: Some(error.function_name.clone()),
        ..VerificationContext::default()
    };
    match error.source.as_ref() {
        FunctionSSAError::Definition { source, .. } => {
            if let SSADefinitionError::DuplicateDefinition {
                duplicate_definition_location: crate::SSADefinitionLocation::Instruction(location),
                ..
            } = source
            {
                set_ssa_instruction_context(&mut context, location);
            }
        }
        FunctionSSAError::Block {
            block_index,
            block_name,
            source,
            ..
        } => {
            context.block_index = Some(*block_index);
            context.block_name = Some(block_name.clone());
            context.instruction_index = Some(source.instruction_index);
            context.instruction_kind = Some(source.instruction_kind);
        }
    }
    context
}

fn set_ssa_instruction_context(
    context: &mut VerificationContext,
    location: &crate::SSAInstructionLocation,
) {
    context.block_index = Some(location.block_index);
    context.block_name = Some(location.block_name.clone());
    context.instruction_index = Some(location.instruction_index);
    context.instruction_kind = Some(location.instruction_kind);
}

fn lifecycle_context(error: &ModuleLifecycleVerificationError) -> VerificationContext {
    let mut context = VerificationContext {
        function_index: Some(error.function_index),
        function_name: Some(error.function_name.clone()),
        ..VerificationContext::default()
    };
    if let FunctionLifecycleVerificationError::Block {
        block_index,
        block_name,
        source,
        ..
    } = error.source.as_ref()
    {
        context.block_index = Some(*block_index);
        context.block_name = Some(block_name.clone());
        context.instruction_index = Some(source.instruction_index);
        context.instruction_kind = Some(source.instruction_kind);
    }
    context
}

fn return_context(error: &ModuleReturnVerificationError) -> VerificationContext {
    let mut context = VerificationContext {
        function_index: Some(error.function_index),
        function_name: Some(error.function_name.clone()),
        ..VerificationContext::default()
    };
    if let FunctionReturnVerificationError::NonVoidPathWithoutReturn { source, .. } =
        error.source.as_ref()
    {
        let crate::ReturnPathRuleError::ValuelessReturn {
            block_index,
            block_name,
            instruction_index,
        } = source;
        context.block_index = Some(*block_index);
        context.block_name = Some(block_name.clone());
        context.instruction_index = Some(*instruction_index);
        context.instruction_kind = Some(InstructionKind::IRReturn);
    }
    context
}

fn classify_failure(
    module: &IRModule,
    error: &VerificationError,
    context: &VerificationContext,
) -> Classification {
    match error {
        VerificationError::Structure(error) => classify_structure(error),
        VerificationError::Types(error) => classify_types(module, error, context),
        VerificationError::Ssa(error) => classify_ssa(error),
        VerificationError::Dominance(_) => {
            classified("IRV-029", VerificationErrorCategory::DataFlow)
        }
        VerificationError::Lifecycle(error) => classify_lifecycle(error),
        VerificationError::Returns(_) => classified("IRV-024", VerificationErrorCategory::Returns),
    }
}

fn classify_structure(error: &ModuleStructureVerificationError) -> Classification {
    match error {
        ModuleStructureVerificationError::DuplicateStructName { .. } => {
            classified("IRV-001", VerificationErrorCategory::Definitions)
        }
        ModuleStructureVerificationError::EmptyStructName { .. } => {
            classified("IRV-002", VerificationErrorCategory::Definitions)
        }
        ModuleStructureVerificationError::DuplicateStructFieldName { .. } => {
            classified("IRV-003", VerificationErrorCategory::Definitions)
        }
        ModuleStructureVerificationError::DuplicateFunctionName { .. } => {
            classified("IRV-006", VerificationErrorCategory::Definitions)
        }
        ModuleStructureVerificationError::Function { source, .. } => match source.as_ref() {
            FunctionStructureVerificationError::DuplicateParameterName { .. } => {
                classified("IRV-007", VerificationErrorCategory::Definitions)
            }
            FunctionStructureVerificationError::DuplicateBlockName { .. } => {
                classified("IRV-008", VerificationErrorCategory::Definitions)
            }
            FunctionStructureVerificationError::EmptyFunction { .. } => {
                classified("IRV-016", VerificationErrorCategory::Cfg)
            }
            FunctionStructureVerificationError::MissingEntryBlock { .. } => {
                classified("IRV-017", VerificationErrorCategory::Cfg)
            }
            FunctionStructureVerificationError::Block { source, .. } => match &source.source {
                ControlFlowRuleError::MissingTerminator { .. } => {
                    classified("IRV-018", VerificationErrorCategory::Cfg)
                }
                ControlFlowRuleError::InstructionAfterTerminator { .. }
                | ControlFlowRuleError::MultipleTerminators { .. } => {
                    classified("IRV-019", VerificationErrorCategory::Cfg)
                }
                ControlFlowRuleError::UnknownJumpTarget { .. }
                | ControlFlowRuleError::UnknownBranchTarget { .. } => {
                    classified("IRV-020", VerificationErrorCategory::Cfg)
                }
                ControlFlowRuleError::InvalidInvokeSuccessors { .. } => {
                    classified("IRV-136", VerificationErrorCategory::Cfg)
                }
            },
        },
    }
}

fn classify_types(
    module: &IRModule,
    error: &ModuleTypeVerificationError,
    context: &VerificationContext,
) -> Classification {
    match error {
        ModuleTypeVerificationError::StructField { .. } => {
            classified("IRV-004", VerificationErrorCategory::Types)
        }
        ModuleTypeVerificationError::StructLayout { .. } => {
            classified("IRV-005", VerificationErrorCategory::Types)
        }
        ModuleTypeVerificationError::Function { source, .. } => match source {
            FunctionTypeVerificationError::ConstructorReceiverOwnership { .. } => {
                classified("IRV-150", VerificationErrorCategory::Lifecycle)
            }
            FunctionTypeVerificationError::ExceptionEventOwnership { .. } => {
                classified("IRV-149", VerificationErrorCategory::Lifecycle)
            }
            FunctionTypeVerificationError::Parameter { .. }
            | FunctionTypeVerificationError::ReturnType { .. } => {
                classified("IRV-011", VerificationErrorCategory::Types)
            }
            FunctionTypeVerificationError::Block { source, .. } => {
                let rule = &source.source.source;
                if let Some(classification) = classify_special_type_rule(rule) {
                    return classification;
                }
                instruction_at(module, context).map_or_else(
                    || unclassified(VerificationErrorCategory::Types),
                    |instruction| classify_instruction(instruction, rule),
                )
            }
        },
    }
}

fn classify_special_type_rule(rule: &TypeRuleError) -> Option<Classification> {
    match rule {
        TypeRuleError::TypeConstraint {
            expected: TypeExpectation::Valid,
            ..
        } => Some(classified("IRV-011", VerificationErrorCategory::Types)),
        TypeRuleError::StorageReturnOperand { .. } => {
            Some(classified("IRV-026", VerificationErrorCategory::Returns))
        }
        TypeRuleError::BorrowViolation { source } => Some(classified(
            borrow_invariant(source),
            VerificationErrorCategory::Borrowing,
        )),
        TypeRuleError::InvalidRetainReleaseSignature { .. }
        | TypeRuleError::InvalidRetainReleaseType { .. } => {
            Some(classified("IRV-066", VerificationErrorCategory::Builtins))
        }
        _ => None,
    }
}

fn borrow_invariant(error: &BorrowRuleError) -> &'static str {
    let rule = match error {
        BorrowRuleError::MissingBorrowScope { rule, .. }
        | BorrowRuleError::BorrowScopeMismatch { rule, .. }
        | BorrowRuleError::OwnedGetDeclaresBorrowScope { rule, .. }
        | BorrowRuleError::BorrowedOwningStoreWithoutAcquisition { rule, .. }
        | BorrowRuleError::BorrowedValueReturned { rule, .. }
        | BorrowRuleError::MutationThroughBorrow { rule, .. } => rule,
    };
    match rule {
        BorrowRule::Irv037 => "IRV-037",
        BorrowRule::Irv038 => "IRV-038",
        BorrowRule::Irv039 => "IRV-039",
        BorrowRule::Irv040 => "IRV-040",
        BorrowRule::Irv041 => "IRV-041",
        BorrowRule::Irv042 => "IRV-042",
    }
}

fn instruction_at<'module>(
    module: &'module IRModule,
    context: &VerificationContext,
) -> Option<&'module IRInstruction> {
    module
        .functions
        .get(context.function_index?)?
        .blocks
        .get(context.block_index?)?
        .instructions
        .get(context.instruction_index?)
}

#[allow(clippy::too_many_lines)]
fn classify_instruction(instruction: &IRInstruction, rule: &TypeRuleError) -> Classification {
    match instruction {
        IRInstruction::IRConst { value, .. } => {
            if matches!(value, IRConstant::Enum(_)) {
                classified("IRV-068", VerificationErrorCategory::Constants)
            } else {
                classified("IRV-069", VerificationErrorCategory::Constants)
            }
        }
        IRInstruction::IRLoad { .. } => classified("IRV-033", VerificationErrorCategory::Types),
        IRInstruction::IRStore { .. } => classified("IRV-034", VerificationErrorCategory::DataFlow),
        IRInstruction::IRInitDefault { .. } => {
            classified("IRV-044", VerificationErrorCategory::Lifecycle)
        }
        IRInstruction::IRCopyInit { .. } => {
            classified("IRV-045", VerificationErrorCategory::Lifecycle)
        }
        IRInstruction::IRMoveInit { .. } => {
            classified("IRV-046", VerificationErrorCategory::Lifecycle)
        }
        IRInstruction::IRAssign { .. } => {
            classified("IRV-047", VerificationErrorCategory::Lifecycle)
        }
        IRInstruction::IRDestroy { .. } => {
            classified("IRV-048", VerificationErrorCategory::Lifecycle)
        }
        IRInstruction::IRRelocate { .. } => {
            classified("IRV-049", VerificationErrorCategory::Lifecycle)
        }
        IRInstruction::IRBinaryOp { operator, .. } => {
            let invariant = if matches!(
                operator.as_str(),
                "add" | "sub" | "mul" | "div" | "rem" | "mod" | "pow"
            ) {
                "IRV-070"
            } else if matches!(operator.as_str(), "eq" | "ne") {
                "IRV-071"
            } else if matches!(operator.as_str(), "lt" | "le" | "gt" | "ge") {
                "IRV-072"
            } else {
                "IRV-073"
            };
            classified(invariant, VerificationErrorCategory::Operators)
        }
        IRInstruction::IRUnaryOp { .. } => {
            classified("IRV-074", VerificationErrorCategory::Operators)
        }
        IRInstruction::IRCompareOp {
            aggregate_shape, ..
        } => {
            let invariant = if aggregate_shape.is_some() {
                "IRV-075"
            } else {
                "IRV-076"
            };
            classified(invariant, VerificationErrorCategory::Operators)
        }
        IRInstruction::IRCast { .. } => classified("IRV-077", VerificationErrorCategory::Types),
        IRInstruction::IRCall { builtin, .. } => classify_call(builtin.as_deref(), rule),
        IRInstruction::IRInvoke { builtin, .. } => classify_call(builtin.as_deref(), rule),
        IRInstruction::IRFunctionRef { .. } => {
            classified("IRV-051", VerificationErrorCategory::Calls)
        }
        IRInstruction::IRCallIndirect { .. } => {
            classified("IRV-053", VerificationErrorCategory::Calls)
        }
        IRInstruction::IRInvokeIndirect { .. } => {
            classified("IRV-053", VerificationErrorCategory::Calls)
        }
        IRInstruction::IRPrint { .. } => {
            classified("IRV-078", VerificationErrorCategory::Instructions)
        }
        IRInstruction::IRStructNew { .. } => {
            classified("IRV-079", VerificationErrorCategory::Structs)
        }
        IRInstruction::IRClassNew { .. } => {
            classified("IRV-125", VerificationErrorCategory::Instructions)
        }
        IRInstruction::IRClassGet { .. } => {
            classified("IRV-126", VerificationErrorCategory::Structs)
        }
        IRInstruction::IRClassSet { .. } => {
            classified("IRV-127", VerificationErrorCategory::Structs)
        }
        IRInstruction::IRInterfaceConstruct { .. } => {
            classified("IRV-128", VerificationErrorCategory::Instructions)
        }
        IRInstruction::IRInterfaceCall { .. } => {
            classified("IRV-129", VerificationErrorCategory::Calls)
        }
        IRInstruction::IRInvokeInterface { .. } => {
            classified("IRV-129", VerificationErrorCategory::Calls)
        }
        IRInstruction::IRStructGet { .. } => {
            classified("IRV-080", VerificationErrorCategory::Structs)
        }
        IRInstruction::IRStructSet { .. } => {
            classified("IRV-081", VerificationErrorCategory::Structs)
        }
        IRInstruction::IRMethodResultNew { .. } => {
            classified("IRV-082", VerificationErrorCategory::MethodResults)
        }
        IRInstruction::IRMethodResultReceiver { .. } => {
            classified("IRV-083", VerificationErrorCategory::MethodResults)
        }
        IRInstruction::IRMethodResultValue { .. } => {
            classified("IRV-084", VerificationErrorCategory::MethodResults)
        }
        IRInstruction::IRArrayNew { .. } => {
            classified("IRV-085", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListNew { .. } => {
            classified("IRV-086", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRArrayGet { .. } => {
            classified("IRV-087", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRArraySet { .. } => {
            classified("IRV-088", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRArraySlice { .. } => {
            classified("IRV-089", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRArrayLength { .. } => {
            classified("IRV-090", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRArrayCopy { .. } => {
            classified("IRV-091", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListGet { .. } => {
            classified("IRV-092", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListSet { .. } => {
            classified("IRV-093", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListSlice { .. } => {
            classified("IRV-094", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListLength { .. } => {
            classified("IRV-095", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListIsEmpty { .. } => {
            classified("IRV-096", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRPackException { .. }
        | IRInstruction::IRCatchEntry { .. }
        | IRInstruction::IRExceptionMatch { .. }
        | IRInstruction::IRExceptionPayload { .. }
        | IRInstruction::IRExceptionDestroy { .. }
        | IRInstruction::IRThrow { .. }
        | IRInstruction::IRRethrow { .. }
        | IRInstruction::IRPropagate { .. } => {
            classified("IRV-130", VerificationErrorCategory::Instructions)
        }
        IRInstruction::IRListCopy { .. } => {
            classified("IRV-097", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListContains { .. } => {
            classified("IRV-098", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListIndexOf { .. } => {
            classified("IRV-099", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListClear { .. } => {
            classified("IRV-100", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListReverse { .. } => {
            classified("IRV-101", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListPush { .. } => {
            classified("IRV-102", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListInsert { .. } => {
            classified("IRV-103", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListPop { .. } => {
            classified("IRV-104", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRListRemoveAt { .. } => {
            classified("IRV-105", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRSequenceSort { .. } => {
            classified("IRV-106", VerificationErrorCategory::Collections)
        }
        IRInstruction::IRVectorNew { .. } => {
            classified("IRV-107", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRMatrixNew { .. } => {
            classified("IRV-108", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRVectorAdd { .. } | IRInstruction::IRVectorSub { .. } => {
            classified("IRV-109", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRVectorScale { .. } => {
            classified("IRV-110", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRVectorDot { .. } => {
            classified("IRV-111", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IROuterProduct { .. } => {
            classified("IRV-112", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRMatrixAdd { .. } | IRInstruction::IRMatrixSub { .. } => {
            classified("IRV-113", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRMatrixScale { .. } => {
            classified("IRV-114", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRMatrixMatMul { .. } => {
            classified("IRV-115", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRMatrixVectorMul { .. } => {
            classified("IRV-116", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRVectorMatrixMul { .. } => {
            classified("IRV-117", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRVectorGet { .. } => {
            classified("IRV-118", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRVectorSet { .. } => {
            classified("IRV-119", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRMatrixGet { .. } => {
            classified("IRV-120", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRMatrixSet { .. } => {
            classified("IRV-121", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRVectorLength { .. } => {
            classified("IRV-122", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRMatrixRows { .. } => {
            classified("IRV-123", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRMatrixColumns { .. } => {
            classified("IRV-124", VerificationErrorCategory::LinearAlgebra)
        }
        IRInstruction::IRBranch { .. } => classified("IRV-021", VerificationErrorCategory::Cfg),
        IRInstruction::IRJump { .. } => classified("IRV-020", VerificationErrorCategory::Cfg),
        IRInstruction::IRReturn { .. } => classified("IRV-025", VerificationErrorCategory::Returns),
    }
}

fn classify_call(builtin: Option<&str>, rule: &TypeRuleError) -> Classification {
    let Some(builtin) = builtin else {
        return classified("IRV-052", VerificationErrorCategory::Calls);
    };
    let invariant = match builtin {
        "System.args" => "IRV-055",
        "__aether_range_step_nonzero" => "IRV-056",
        "__aether_string_byte_length" => "IRV-057",
        "__aether_string_trim" => "IRV-058",
        "__aether_string_split" => "IRV-059",
        "parseInt" | "parseDouble" => {
            if type_rule_field(rule).is_some_and(|field| field.starts_with("result.fields"))
                || matches!(rule, TypeRuleError::UnknownStruct { .. })
            {
                "IRV-061"
            } else {
                "IRV-060"
            }
        }
        "io.readText" => {
            if type_rule_field(rule).is_some_and(|field| field.starts_with("result.fields"))
                || matches!(rule, TypeRuleError::UnknownStruct { .. })
            {
                "IRV-063"
            } else {
                "IRV-062"
            }
        }
        "io.writeText" | "io.writeTextAtomic" | "io.appendText" => {
            if type_rule_field(rule).is_some_and(|field| field == "result") {
                "IRV-064"
            } else {
                "IRV-062"
            }
        }
        "text.byteAt"
        | "text.byteSlice"
        | "text.formatInt"
        | "text.formatDouble"
        | "text.concatFragments" => "IRV-065",
        "__aether_retain" | "__aether_release" | "__aether_interface_copy_owned" => "IRV-066",
        _ => "IRV-067",
    };
    classified(invariant, VerificationErrorCategory::Builtins)
}

fn type_rule_field(rule: &TypeRuleError) -> Option<&str> {
    match rule {
        TypeRuleError::TypeMismatch { field, .. }
        | TypeRuleError::TypeConstraint { field, .. }
        | TypeRuleError::CountMismatch { field, .. }
        | TypeRuleError::MissingResult { field, .. }
        | TypeRuleError::UnexpectedResult { field, .. }
        | TypeRuleError::UnknownStruct { field, .. }
        | TypeRuleError::InvalidFieldIndex { field, .. }
        | TypeRuleError::UnsupportedOperator { field, .. }
        | TypeRuleError::MetadataMismatch { field, .. }
        | TypeRuleError::InvalidAggregateShape { field, .. }
        | TypeRuleError::InvalidVectorLength { field, .. }
        | TypeRuleError::InvalidEnumConstant { field, .. } => Some(field),
        TypeRuleError::ConstructorReceiverOwnership { .. }
        | TypeRuleError::ExceptionEventOwnership { .. }
        | TypeRuleError::StorageReturnOperand { .. }
        | TypeRuleError::BorrowViolation { .. }
        | TypeRuleError::MissingCollectionLifecycleCapability { .. }
        | TypeRuleError::InvalidBuiltinIdentity { .. }
        | TypeRuleError::InvalidRetainReleaseSignature { .. }
        | TypeRuleError::InvalidRetainReleaseType { .. }
        | TypeRuleError::UnknownFunction { .. }
        | TypeRuleError::InvalidMatrixDimensions { .. }
        | TypeRuleError::InvalidMatrixCardinality { .. }
        | TypeRuleError::RecursiveStructLayout { .. } => None,
    }
}

fn classify_ssa(error: &ModuleSSAError) -> Classification {
    let source = match error.source.as_ref() {
        FunctionSSAError::Definition { source, .. } => source,
        FunctionSSAError::Block { source, .. } => &source.source,
    };
    match source {
        SSADefinitionError::DuplicateDefinition { .. } => {
            classified("IRV-009", VerificationErrorCategory::Definitions)
        }
        SSADefinitionError::UndefinedReference { .. }
        | SSADefinitionError::UseBeforeDefinition { .. } => {
            classified("IRV-029", VerificationErrorCategory::DataFlow)
        }
        SSADefinitionError::ReferenceTypeMismatch { .. } => {
            classified("IRV-030", VerificationErrorCategory::DataFlow)
        }
    }
}

fn classify_lifecycle(error: &ModuleLifecycleVerificationError) -> Classification {
    let FunctionLifecycleVerificationError::Block { source, .. } = error.source.as_ref() else {
        return unclassified(VerificationErrorCategory::Cfg);
    };
    match &source.source {
        LifecycleRuleError::StorageTypeMismatch { .. } => {
            classified("IRV-010", VerificationErrorCategory::Types)
        }
        LifecycleRuleError::OperationTypeMismatch { operation, .. }
        | LifecycleRuleError::ForbiddenSourceDestinationAlias { operation, .. } => {
            classify_lifecycle_operation(*operation)
        }
        LifecycleRuleError::InvalidLifecycleType {
            operation, reason, ..
        } => {
            if reason == "void has no storage" {
                classified("IRV-043", VerificationErrorCategory::Lifecycle)
            } else {
                classify_lifecycle_operation(*operation)
            }
        }
        LifecycleRuleError::ReturnTransferTypeMismatch { .. } => {
            classified("IRV-027", VerificationErrorCategory::Lifecycle)
        }
        LifecycleRuleError::InvalidRelocateCount { .. } => {
            classified("IRV-049", VerificationErrorCategory::Lifecycle)
        }
        LifecycleRuleError::DoubleInitialization { operation, .. }
        | LifecycleRuleError::UseBeforeInitialization { operation, .. }
        | LifecycleRuleError::UseAfterLocalInvalidation { operation, .. } => {
            classify_lifecycle_state_failure(*operation)
        }
        LifecycleRuleError::AssignmentToUninitialized { .. }
        | LifecycleRuleError::DestroyOfUninitialized { .. }
        | LifecycleRuleError::DoubleDestroy { .. } => {
            classified("IRV-050", VerificationErrorCategory::Lifecycle)
        }
        LifecycleRuleError::InvalidMergedState { operation, .. } => {
            if *operation == LifecycleOperation::Load {
                classified("IRV-032", VerificationErrorCategory::DataFlow)
            } else {
                classified("IRV-050", VerificationErrorCategory::Lifecycle)
            }
        }
        LifecycleRuleError::IncompleteOwnershipAtExit { .. } => {
            classified("IRV-028", VerificationErrorCategory::Lifecycle)
        }
    }
}

const fn classify_lifecycle_state_failure(operation: LifecycleOperation) -> Classification {
    if matches!(operation, LifecycleOperation::Load) {
        classified("IRV-032", VerificationErrorCategory::DataFlow)
    } else {
        classified("IRV-050", VerificationErrorCategory::Lifecycle)
    }
}

const fn classify_lifecycle_operation(operation: LifecycleOperation) -> Classification {
    match operation {
        LifecycleOperation::Load => classified("IRV-032", VerificationErrorCategory::DataFlow),
        LifecycleOperation::Store => classified("IRV-034", VerificationErrorCategory::DataFlow),
        LifecycleOperation::InitDefault => {
            classified("IRV-044", VerificationErrorCategory::Lifecycle)
        }
        LifecycleOperation::CopyInit => classified("IRV-045", VerificationErrorCategory::Lifecycle),
        LifecycleOperation::MoveInit => classified("IRV-046", VerificationErrorCategory::Lifecycle),
        LifecycleOperation::Assign => classified("IRV-047", VerificationErrorCategory::Lifecycle),
        LifecycleOperation::Destroy => classified("IRV-048", VerificationErrorCategory::Lifecycle),
        LifecycleOperation::Relocate => classified("IRV-049", VerificationErrorCategory::Lifecycle),
        LifecycleOperation::ReturnTransfer => {
            classified("IRV-027", VerificationErrorCategory::Lifecycle)
        }
    }
}
