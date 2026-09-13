//! MIR-to-SSA promotion, phi construction, dominance and verification.
#![allow(missing_docs)]

use aether_frontend::{ClassOp, IndexSemantics};
mod classes;
mod oop_opt;
pub use oop_opt::{
    ArcElision, ClassDevirtualization, Devirtualization, OopOptimizations, optimize_oop,
};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fmt::Write;
use std::sync::Arc;

use aether_frontend::{
    CastKind, CatchId, ClassId, CoercionKind, Diagnostic, DiagnosticCategory, EnumId, EnumInfo,
    FieldId, FinallyId, FloatValue, FunctionInstanceInfo, InstanceId, LocalId, MatchMode,
    ModuleInfo, Phase, Span, StructId, StructInfo, StructuralMutation, Substitution, TypeArena,
    TypeData, TypeId, VariantId, format_type,
};

use crate::mir::{ExceptionEventId, FinallyRegion, place_type};
use crate::{
    BinaryOp, BlockId, ElementInitialization, MirDropFlag, MirFunction, Operand, Place, PlaceBase,
    PlaceProjection, PushInit, Relocate, RelocationRange, Rvalue, SlotPlace, TakeState, Terminator,
    TrapKind, UnaryOp, VerifiedMir,
};

/// Fresh SSA value identity.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ValueId(pub u32);

/// SSA operand for scalar or aggregate values.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SsaOperand {
    /// SSA value use.
    Value(ValueId),
    /// Signed 64-bit constant.
    Int { value: i128, ty: TypeId },
    /// IEEE literal bits and canonical type.
    Float { value: FloatValue, ty: TypeId },
    /// Boolean constant.
    Bool(bool),
}

/// Phi definition for a promoted MIR local.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Phi {
    /// Defined value.
    pub result: ValueId,
    /// Canonical type.
    pub ty: TypeId,
    /// Origin local, retained for inspection only.
    pub local: LocalId,
    /// Exactly one value for every predecessor, sorted by block identity.
    pub incoming: Vec<(BlockId, ValueId)>,
}

/// SSA definition introduced by a function parameter.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SsaParameter {
    /// Corresponding MIR local identity, retained for inspection.
    pub local: LocalId,
    /// Entry definition.
    pub value: ValueId,
    /// Canonical semantic type.
    pub ty: TypeId,
}

/// One address-taken MIR local retained as explicit stack-backed storage.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SsaMemoryLocal {
    pub local: LocalId,
    pub ty: TypeId,
    pub parameter: Option<ValueId>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SsaPlace {
    pub base: SsaPlaceBase,
    pub projections: Vec<SsaPlaceProjection>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SsaPlaceProjection {
    Field(FieldId),
    Index {
        index: SsaOperand,
        /// Present exactly for `OneBased2D` Matrix projections.
        column: Option<SsaOperand>,
        element_type: TypeId,
        bounds_trap: TrapKind,
        semantics: IndexSemantics,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SsaPlaceBase {
    MemoryLocal(LocalId),
    /// Descriptor held directly in SSA; index projection turns it into an
    /// address into contiguous storage.
    Value(SsaOperand),
    Dereference {
        reference: SsaOperand,
        mutable: bool,
    },
}

/// SSA computation.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum SsaOp {
    /// Ordered concrete object lifecycle/member operation.
    Class(Box<ClassOp<SsaOperand, InstanceId>>),
    /// Explicit immutable string lifecycle/content operation.
    String(Box<aether_frontend::StringOp<SsaOperand>>),
    /// Canonical standard-library Text operation.
    Text(Box<aether_frontend::TextOp<SsaOperand>>),
    /// Structured mathematical loop; inputs are Copy readable descriptors.
    /// Native oriented algebraic product with a closed concrete schedule.
    AlgebraicProduct {
        left: SsaOperand,
        right: SsaOperand,
        kernel: crate::AlgebraicProductKernel,
    },
    ElementwiseBinary {
        left: SsaOperand,
        right: SsaOperand,
        kernel: crate::ElementwiseKernel,
    },
    /// Scalar copy.
    Use(SsaOperand),
    /// Alias-aware memory read from address-taken storage or a dereference.
    Load {
        place: SsaPlace,
    },
    /// Alias-aware memory write. Its SSA result is an intentionally unused
    /// copy of `value`; the observable operation is the store effect.
    Store {
        place: SsaPlace,
        value: SsaOperand,
    },
    /// Address creation for a typed non-owning reference.
    Borrow {
        place: SsaPlace,
        mutable: bool,
    },
    Move {
        source: SsaPlace,
    },
    ReplaceString {
        destination: SsaPlace,
        value: SsaOperand,
    },
    Drop {
        owner: SsaPlace,
    },
    BufferAlloc {
        element_type: TypeId,
        length: SsaOperand,
        initial: SsaOperand,
        size_trap: TrapKind,
        failure_trap: TrapKind,
    },
    /// Consuming O(1) descriptor transfer; never an element/storage operation.
    VectorTransposeMove {
        operand: SsaOperand,
        source_type: TypeId,
    },
    MatrixInit {
        rows: u64,
        columns: u64,
        /// Retained source row boundaries, checked independently; no runtime field.
        row_ends: Vec<u64>,
        element_type: TypeId,
        elements: Vec<SsaOperand>,
        size_trap: TrapKind,
        failure_trap: TrapKind,
    },
    VectorInit {
        element_type: TypeId,
        elements: Vec<SsaOperand>,
        size_trap: TrapKind,
        failure_trap: TrapKind,
    },
    ArrayInit {
        element_type: TypeId,
        elements: Vec<SsaOperand>,
        size_trap: TrapKind,
        failure_trap: TrapKind,
    },
    ArrayFill {
        element_type: TypeId,
        length: SsaOperand,
        initial: SsaOperand,
        size_trap: TrapKind,
        failure_trap: TrapKind,
    },
    MatrixRows {
        source: SsaPlace,
    },
    MatrixColumns {
        source: SsaPlace,
    },
    VectorDimension {
        source: SsaPlace,
    },
    ArrayLength {
        source: SsaPlace,
    },
    ListInit {
        element_type: TypeId,
        elements: Vec<SsaOperand>,
        size_trap: TrapKind,
        failure_trap: TrapKind,
    },
    ListLength {
        source: SsaPlace,
    },
    ListCapacity {
        source: SsaPlace,
    },
    /// Bounded successor within a verified forward hole transaction.
    HoleNext {
        hole: SsaOperand,
    },
    TailIndex {
        length: SsaOperand,
    },
    Take {
        slot: SlotPlace<SsaPlace, SsaOperand>,
        state: TakeState,
    },
    Relocate {
        source: SlotPlace<SsaPlace, SsaOperand>,
        destination: SlotPlace<SsaPlace, SsaOperand>,
        relocation: Relocate,
    },
    ListSetLength {
        source: SsaPlace,
        length: SsaOperand,
    },
    ListPush {
        source: SsaPlace,
        value: SsaOperand,
        mutation: StructuralMutation,
        initialization: PushInit,
        relocation: Relocate,
        size_trap: TrapKind,
        failure_trap: TrapKind,
    },
    ListReserve {
        source: SsaPlace,
        requested_capacity: SsaOperand,
        mutation: StructuralMutation,
        relocation: Relocate,
        size_trap: TrapKind,
        failure_trap: TrapKind,
    },
    /// Borrow the source backing. Source Place and descriptor copy/use chains
    /// retain provenance; the closed recipe is independently verified.
    MatrixAxisVectorView {
        source: SsaPlace,
        fixed_index: SsaOperand,
        axis: aether_frontend::Orientation,
        mutable: bool,
        descriptor: aether_frontend::MatrixAxisVectorViewDescriptor,
        bounds_trap: TrapKind,
    },
    /// Borrow/transpose an oriented vector with a closed stride recipe.
    VectorView {
        source: SsaPlace,
        mutable: bool,
        transpose: bool,
        descriptor: aether_frontend::VectorViewDescriptor,
    },
    /// Borrow 2D backing with an independently verified shape/stride recipe.
    MatrixView {
        source: SsaPlace,
        mutable: bool,
        transpose: bool,
        descriptor: aether_frontend::MatrixViewDescriptor,
    },
    View {
        source: SsaPlace,
        mutable: bool,
    },
    /// Nominal aggregate construction.
    Aggregate {
        struct_id: StructId,
        fields: Vec<(FieldId, SsaOperand)>,
    },
    EnumConstruct {
        enum_id: EnumId,
        variant_id: VariantId,
        payloads: Vec<SsaOperand>,
    },
    EnumDiscriminant {
        value: SsaOperand,
        enum_id: EnumId,
        mode: MatchMode,
    },
    EnumPayload {
        value: SsaOperand,
        enum_id: EnumId,
        variant_id: VariantId,
        index: u32,
        mode: MatchMode,
    },
    ConsumeEnum {
        owner: SsaPlace,
    },
    /// Pure aggregate projection.
    ExtractField {
        aggregate: SsaOperand,
        projections: Vec<FieldId>,
    },
    /// Pure functional update used to preserve aggregate SSA after place mutation.
    InsertField {
        aggregate: SsaOperand,
        projections: Vec<FieldId>,
        value: SsaOperand,
    },
    /// Explicit widening selected in HIR.
    Coerce {
        kind: CoercionKind,
        operand: SsaOperand,
        from: TypeId,
    },
    /// Explicit value conversion preserved from HIR/MIR.
    Cast {
        kind: CastKind,
        operand: SsaOperand,
        from: TypeId,
        trap: Option<TrapKind>,
    },
    /// Unary computation with explicit trap effect.
    Unary {
        op: UnaryOp,
        operand: SsaOperand,
        trap: Option<TrapKind>,
    },
    /// Binary computation with an optional explicit trap effect.
    Binary {
        op: BinaryOp,
        left: SsaOperand,
        right: SsaOperand,
        trap: Option<TrapKind>,
        secondary_trap: Option<TrapKind>,
    },
    /// Resolved direct call.
    Call {
        callee: InstanceId,
        args: Vec<SsaOperand>,
    },
    ExceptionMatches {
        event: ExceptionEventId,
        catch_class: ClassId,
    },
    CatchBindAlias {
        event: ExceptionEventId,
        catch: CatchId,
        catch_class: ClassId,
    },
    EndCatch {
        event: ExceptionEventId,
    },
    SetPendingFinally {
        finally: FinallyId,
        tag: u32,
    },
    EnterFinally {
        finally: FinallyId,
    },
    ExitFinally {
        finally: FinallyId,
    },
}

/// One SSA definition.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SsaInstruction {
    /// Fresh result identity.
    pub result: ValueId,
    /// Result type.
    pub ty: TypeId,
    /// Computation.
    pub op: SsaOp,
    /// Source provenance.
    pub span: Span,
    pub unwind: Option<BlockId>,
}

/// SSA control-flow terminator.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum SsaTerminator {
    /// Unconditional edge.
    Goto(BlockId),
    /// Boolean branch.
    Branch {
        condition: SsaOperand,
        then_block: BlockId,
        else_block: BlockId,
    },
    Switch {
        discriminant: SsaOperand,
        cases: Vec<(u32, BlockId)>,
        otherwise: Option<BlockId>,
        exhaustive_enum: Option<EnumId>,
    },
    /// Function result.
    Return(SsaOperand),
    /// Explicit failure.
    Trap(TrapKind),
    Throw {
        payload: SsaOperand,
        class: ClassId,
        transfer: bool,
        unwind: Option<BlockId>,
    },
    Rethrow {
        event: ExceptionEventId,
        unwind: Option<BlockId>,
    },
    ResumeUnwind {
        event: ExceptionEventId,
    },
    ForwardUnwind {
        event: ExceptionEventId,
        target_event: ExceptionEventId,
        target: BlockId,
    },
}

/// SSA basic block.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SsaBlock {
    /// Stable block identity.
    pub id: BlockId,
    /// Merge definitions.
    pub phis: Vec<Phi>,
    /// Ordinary definitions.
    pub instructions: Vec<SsaInstruction>,
    /// Required terminator.
    pub terminator: SsaTerminator,
    pub landing_pad: Option<ExceptionEventId>,
    pub landing_pad_catches: bool,
}

/// Raw SSA function.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SsaFunction {
    /// Independently verified physical emission decisions.
    pub oop_optimizations: OopOptimizations,
    /// Globally unambiguous session-local function identity.
    pub id: InstanceId,
    pub function_id: aether_frontend::FunctionId,
    /// Entry parameter definitions in call order.
    pub parameters: Vec<SsaParameter>,
    /// Only address-taken locals cross the SSA/memory boundary.
    pub memory_locals: Vec<SsaMemoryLocal>,
    /// Root-level conditional ownership metadata retained from verified MIR.
    pub drop_flags: Vec<MirDropFlag>,
    /// Canonical return type.
    pub return_type: TypeId,
    /// Entry block.
    pub entry: BlockId,
    /// Blocks in stable MIR order.
    pub blocks: Vec<SsaBlock>,
    pub exception_events: Vec<ExceptionEventId>,
    pub finally_regions: Vec<FinallyRegion>,
    pub constructor_unwind: Option<aether_frontend::ConstructorUnwindPlan>,
}

/// Unverified SSA type-state.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SsaIr {
    /// Session-local canonical type identity context.
    pub types: Arc<TypeArena>,
    /// Resolved program module graph and provenance.
    pub modules: Vec<ModuleInfo>,
    /// Nominal aggregate metadata shared with MIR and the backend.
    pub structs: Vec<StructInfo>,
    /// Nominal enum metadata shared with MIR and the backend.
    pub enums: Vec<EnumInfo>,
    /// Source-unit signature table.
    pub signatures: Vec<FunctionInstanceInfo>,
    /// Function-local SSA graphs in identity order.
    pub functions: Vec<SsaFunction>,
    /// Entry function identity.
    pub entry: InstanceId,
    pub exceptions_enabled: bool,
}

impl SsaIr {
    /// Deterministic inspection dump.
    #[must_use]
    pub fn dump(&self) -> String {
        let type_table = self
            .types
            .entries()
            .map(|(id, _)| {
                format!(
                    "  {id:?} = {}; properties={:?}",
                    format_type(&self.types, id, &self.structs, &self.enums),
                    self.types.properties(id).expect("dumped valid TypeId")
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        let mut dump = format!(
            "types (session-local):\n{type_table}\nentry: {:#?}\nmodules: {:#?}\nstructs: {:#?}\nenums: {:#?}\nsignatures: {:#?}",
            self.entry, self.modules, self.structs, self.enums, self.signatures
        );
        if !self.types.classes().is_empty() {
            write!(
                dump,
                "\nclasses (fields, capabilities, destruction): {:#?}",
                self.types.classes()
            )
            .unwrap();
        }
        for module in &self.modules {
            let functions: Vec<_> = self
                .functions
                .iter()
                .filter(|function| self.signatures[function.id.0 as usize].module == module.id)
                .collect();
            write!(
                dump,
                "\nmodule {:?} `{}` functions: {functions:#?}",
                module.id, module.name
            )
            .unwrap();
        }
        for function in &self.functions {
            for (retain, pair) in &function.oop_optimizations.arc {
                writeln!(dump, "\nARC elision {:?}: retain {retain:?}, release {:?}; independent owner {:?} stays owned through same-block cleanup; nonescaping token; strong count bounded", function.id, pair.release, pair.owner).unwrap();
            }
            for (call, direct) in &function.oop_optimizations.direct {
                writeln!(dump, "\ninterface devirtualization {:?} {call:?}: {:?} {:?} -> exact {:?}, direct {:?}", function.id, direct.requirement.interface, direct.requirement, direct.class, direct.method).unwrap();
            }
            for (call, direct) in &function.oop_optimizations.virtual_direct {
                writeln!(
                    dump,
                    "\nclass devirtualization {:?} {call:?}: slot {:?} -> exact {:?}, direct {:?}",
                    function.id, direct.slot, direct.class, direct.method
                )
                .unwrap();
            }
        }
        dump
    }
}

/// Immutable proof wrapper created only by [`verify_ssa`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VerifiedSsa(SsaIr);

impl VerifiedSsa {
    /// Borrows verified SSA without exposing mutation.
    #[must_use]
    pub const fn as_ssa(&self) -> &SsaIr {
        &self.0
    }

    /// Deterministic inspection dump.
    #[must_use]
    pub fn dump(&self) -> String {
        self.0.dump()
    }
}

/// Promotes scalar and aggregate MIR locals using dominance-frontier phi placement.
#[must_use]
pub fn build_ssa(mir: &VerifiedMir) -> SsaIr {
    let mir = mir.as_mir();
    SsaIr {
        modules: mir.modules.clone(),
        types: mir.types.clone(),
        structs: mir.structs.clone(),
        enums: mir.enums.clone(),
        signatures: mir.signatures.clone(),
        functions: mir
            .functions
            .iter()
            .map(|function| build_function_ssa(function, &mir.types, &mir.structs))
            .collect(),
        entry: mir.entry,
        exceptions_enabled: mir.exceptions_enabled,
    }
}

#[allow(clippy::too_many_lines)]
fn build_function_ssa(
    function: &MirFunction,
    types: &TypeArena,
    structs: &[StructInfo],
) -> SsaFunction {
    let cfg = Cfg::new(function);
    let dominance = Dominance::compute(&cfg, function.entry);
    let live_in = mir_liveness(function, &cfg);
    let mut phi_locals = vec![BTreeSet::new(); function.blocks.len()];

    let mut definitions = vec![BTreeSet::new(); function.locals.len()];
    for block in &function.blocks {
        for instruction in &block.instructions {
            if let PlaceBase::Local(local) = &instruction.destination.base
                && !function.locals[local.0 as usize].address_taken
            {
                definitions[local.0 as usize].insert(block.id);
            }
        }
    }
    for (local_index, blocks) in definitions.iter().enumerate() {
        let local = LocalId(u32::try_from(local_index).expect("local index fits"));
        let mut work: VecDeque<_> = blocks.iter().copied().collect();
        let mut placed = BTreeSet::new();
        while let Some(block) = work.pop_front() {
            for frontier in &dominance.frontier[block.0 as usize] {
                if live_in[frontier.0 as usize].contains(&local) && placed.insert(*frontier) {
                    phi_locals[frontier.0 as usize].insert(local);
                    if !blocks.contains(frontier) {
                        work.push_back(*frontier);
                    }
                }
            }
        }
    }

    let parameters: Vec<_> = function
        .parameters
        .iter()
        .enumerate()
        .map(|(index, parameter)| SsaParameter {
            local: parameter.local,
            value: ValueId(u32::try_from(index).expect("parameter count fits u32")),
            ty: parameter.ty,
        })
        .collect();
    let memory_locals = function
        .locals
        .iter()
        .filter(|local| local.address_taken)
        .map(|local| SsaMemoryLocal {
            local: local.id,
            ty: local.ty,
            parameter: parameters
                .iter()
                .find(|parameter| parameter.local == local.id)
                .map(|parameter| parameter.value),
        })
        .collect();
    let mut next_value = u32::try_from(parameters.len()).expect("parameter count fits u32");
    let mut phi_results: Vec<BTreeMap<LocalId, ValueId>> =
        vec![BTreeMap::new(); function.blocks.len()];
    for (block_index, locals) in phi_locals.iter().enumerate() {
        for local in locals {
            phi_results[block_index].insert(*local, ValueId(next_value));
            next_value += 1;
        }
    }
    let placeholder = SsaTerminator::Trap(TrapKind::IntegerOverflow);
    let mut blocks: Vec<SsaBlock> = function
        .blocks
        .iter()
        .map(|block| SsaBlock {
            id: block.id,
            phis: phi_results[block.id.0 as usize]
                .iter()
                .map(|(local, result)| Phi {
                    result: *result,
                    ty: function.locals[local.0 as usize].ty,
                    local: *local,
                    incoming: Vec::new(),
                })
                .collect(),
            instructions: Vec::new(),
            terminator: placeholder.clone(),
            landing_pad: block.landing_pad,
            landing_pad_catches: block.landing_pad_catches,
        })
        .collect();
    let mut stacks = vec![Vec::<ValueId>::new(); function.locals.len()];
    for parameter in &parameters {
        stacks[parameter.local.0 as usize].push(parameter.value);
    }
    rename_block(
        function.entry,
        function,
        &cfg,
        &dominance,
        &phi_results,
        &mut blocks,
        &mut stacks,
        &mut next_value,
        types,
        structs,
    );
    for block in &mut blocks {
        for phi in &mut block.phis {
            phi.incoming.sort_by_key(|(predecessor, _)| *predecessor);
        }
    }
    SsaFunction {
        oop_optimizations: OopOptimizations::default(),
        id: function.id,
        function_id: function.function_id,
        parameters,
        memory_locals,
        drop_flags: function.drop_flags.clone(),
        return_type: function.return_type,
        entry: function.entry,
        blocks,
        exception_events: function.exception_events.clone(),
        finally_regions: function.finally_regions.clone(),
        constructor_unwind: function.constructor_unwind.clone(),
    }
}

#[allow(clippy::too_many_arguments, clippy::too_many_lines)]
fn rename_block(
    block_id: BlockId,
    mir: &MirFunction,
    cfg: &Cfg,
    dominance: &Dominance,
    phi_results: &[BTreeMap<LocalId, ValueId>],
    blocks: &mut [SsaBlock],
    stacks: &mut [Vec<ValueId>],
    next_value: &mut u32,
    types: &TypeArena,
    structs: &[StructInfo],
) {
    let block_index = block_id.0 as usize;
    let mut pushes = vec![0_usize; stacks.len()];
    for (local, result) in &phi_results[block_index] {
        stacks[local.0 as usize].push(*result);
        pushes[local.0 as usize] += 1;
    }
    for instruction in &mir.blocks[block_index].instructions {
        let memory_destination = match &instruction.destination.base {
            PlaceBase::Local(local) => {
                mir.locals[local.0 as usize].address_taken
                    || instruction
                        .destination
                        .projections
                        .iter()
                        .any(|projection| matches!(projection, PlaceProjection::Index { .. }))
            }
            PlaceBase::Dereference { .. } => true,
        };
        if memory_destination {
            let value_ty = rvalue_result_type(
                mir,
                &instruction.destination,
                &instruction.value,
                structs,
                types,
            );
            let value_result = ValueId(*next_value);
            *next_value += 1;
            blocks[block_index].instructions.push(SsaInstruction {
                result: value_result,
                ty: value_ty,
                op: rename_rvalue(&instruction.value, stacks, mir),
                span: instruction.span,
                unwind: instruction.unwind,
            });
            let store_result = ValueId(*next_value);
            *next_value += 1;
            let store_result_ty = if types.needs_drop(value_ty) {
                TypeId::BOOL
            } else {
                value_ty
            };
            blocks[block_index].instructions.push(SsaInstruction {
                result: store_result,
                ty: store_result_ty,
                op: SsaOp::Store {
                    place: rename_place(&instruction.destination, stacks, mir),
                    value: SsaOperand::Value(value_result),
                },
                span: instruction.span,
                unwind: None,
            });
            continue;
        }
        let PlaceBase::Local(destination_local) = &instruction.destination.base else {
            unreachable!("memory destinations handled above")
        };
        let destination_local = *destination_local;
        let op = if instruction.destination.projections.is_empty() {
            rename_rvalue(&instruction.value, stacks, mir)
        } else {
            let value = if let Rvalue::Use(value) = &instruction.value {
                rename_operand(value, stacks)
            } else {
                let value_ty = rvalue_result_type(
                    mir,
                    &instruction.destination,
                    &instruction.value,
                    structs,
                    types,
                );
                let value_result = ValueId(*next_value);
                *next_value += 1;
                blocks[block_index].instructions.push(SsaInstruction {
                    result: value_result,
                    ty: value_ty,
                    op: rename_rvalue(&instruction.value, stacks, mir),
                    span: instruction.span,
                    unwind: instruction.unwind,
                });
                SsaOperand::Value(value_result)
            };
            SsaOp::InsertField {
                aggregate: SsaOperand::Value(
                    *stacks[destination_local.0 as usize]
                        .last()
                        .expect("projected store base is initialized"),
                ),
                projections: instruction
                    .destination
                    .projections
                    .iter()
                    .map(|projection| match projection {
                        PlaceProjection::Field(field) => *field,
                        PlaceProjection::Index { .. } => {
                            unreachable!("index stores are memory effects")
                        }
                    })
                    .collect(),
                value,
            }
        };
        let result = ValueId(*next_value);
        *next_value += 1;
        let ty = mir.locals[destination_local.0 as usize].ty;
        blocks[block_index].instructions.push(SsaInstruction {
            result,
            ty,
            op,
            span: instruction.span,
            unwind: if instruction.destination.projections.is_empty() {
                instruction.unwind
            } else {
                None
            },
        });
        stacks[destination_local.0 as usize].push(result);
        pushes[destination_local.0 as usize] += 1;
    }
    blocks[block_index].terminator = rename_terminator(
        mir.blocks[block_index]
            .terminator
            .as_ref()
            .expect("verified MIR has terminator"),
        stacks,
    );
    for successor in &cfg.successors[block_index] {
        let successor_index = successor.0 as usize;
        for phi in &mut blocks[successor_index].phis {
            let value = *stacks[phi.local.0 as usize]
                .last()
                .expect("verified MIR guarantees initialization");
            phi.incoming.push((block_id, value));
        }
    }
    for child in &dominance.children[block_index] {
        rename_block(
            *child,
            mir,
            cfg,
            dominance,
            phi_results,
            blocks,
            stacks,
            next_value,
            types,
            structs,
        );
    }
    for (local, count) in pushes.into_iter().enumerate() {
        let new_len = stacks[local].len() - count;
        stacks[local].truncate(new_len);
    }
}

#[allow(clippy::too_many_lines)]
fn rename_rvalue(value: &Rvalue, stacks: &[Vec<ValueId>], mir: &MirFunction) -> SsaOp {
    match value {
        Rvalue::Class(op) => SsaOp::Class(Box::new(
            op.map(
                |o| Ok::<_, std::convert::Infallible>(rename_operand(o, stacks)),
                |f| Ok(*f),
            )
            .unwrap(),
        )),
        Rvalue::String(op) => SsaOp::String(Box::new(
            op.clone()
                .map(|operand| Ok::<_, std::convert::Infallible>(rename_operand(&operand, stacks)))
                .unwrap(),
        )),
        Rvalue::Text(op) => SsaOp::Text(Box::new(
            op.clone()
                .map(|operand| Ok::<_, std::convert::Infallible>(rename_operand(&operand, stacks)))
                .unwrap(),
        )),
        Rvalue::Use(operand) => SsaOp::Use(rename_operand(operand, stacks)),
        Rvalue::Load(place) => match &place.base {
            PlaceBase::Local(local)
                if !mir.locals[local.0 as usize].address_taken
                    && place
                        .projections
                        .iter()
                        .all(|projection| matches!(projection, PlaceProjection::Field(_))) =>
            {
                SsaOp::ExtractField {
                    aggregate: SsaOperand::Value(
                        *stacks[local.0 as usize]
                            .last()
                            .expect("verified MIR load has reaching aggregate definition"),
                    ),
                    projections: place
                        .projections
                        .iter()
                        .map(|projection| match projection {
                            PlaceProjection::Field(field) => *field,
                            PlaceProjection::Index { .. } => unreachable!(),
                        })
                        .collect(),
                }
            }
            _ => SsaOp::Load {
                place: rename_place(place, stacks, mir),
            },
        },
        Rvalue::Borrow { place, mutable } => SsaOp::Borrow {
            place: rename_place(place, stacks, mir),
            mutable: *mutable,
        },
        Rvalue::Move { source } => SsaOp::Move {
            source: rename_place(source, stacks, mir),
        },
        Rvalue::ReplaceString { destination, value } => SsaOp::ReplaceString {
            destination: rename_place(destination, stacks, mir),
            value: rename_operand(value, stacks),
        },
        Rvalue::Drop { owner } => SsaOp::Drop {
            owner: rename_place(owner, stacks, mir),
        },
        Rvalue::BufferAlloc {
            element_type,
            length,
            initial,
            size_trap,
            failure_trap,
        } => SsaOp::BufferAlloc {
            element_type: *element_type,
            length: rename_operand(length, stacks),
            initial: rename_operand(initial, stacks),
            size_trap: *size_trap,
            failure_trap: *failure_trap,
        },
        Rvalue::VectorTransposeMove {
            operand,
            source_type,
        } => SsaOp::VectorTransposeMove {
            operand: rename_operand(operand, stacks),
            source_type: *source_type,
        },
        Rvalue::MatrixInit {
            rows,
            columns,
            row_ends,
            element_type,
            elements,
            size_trap,
            failure_trap,
        } => SsaOp::MatrixInit {
            rows: *rows,
            columns: *columns,
            row_ends: row_ends.clone(),
            element_type: *element_type,
            elements: elements
                .iter()
                .map(|element| rename_operand(element, stacks))
                .collect(),
            size_trap: *size_trap,
            failure_trap: *failure_trap,
        },
        Rvalue::VectorInit {
            element_type,
            elements,
            size_trap,
            failure_trap,
        } => SsaOp::VectorInit {
            element_type: *element_type,
            elements: elements
                .iter()
                .map(|element| rename_operand(element, stacks))
                .collect(),
            size_trap: *size_trap,
            failure_trap: *failure_trap,
        },
        Rvalue::ArrayInit {
            element_type,
            elements,
            size_trap,
            failure_trap,
        } => SsaOp::ArrayInit {
            element_type: *element_type,
            elements: elements
                .iter()
                .map(|element| rename_operand(element, stacks))
                .collect(),
            size_trap: *size_trap,
            failure_trap: *failure_trap,
        },
        Rvalue::ArrayFill {
            element_type,
            length,
            initial,
            size_trap,
            failure_trap,
        } => SsaOp::ArrayFill {
            element_type: *element_type,
            length: rename_operand(length, stacks),
            initial: rename_operand(initial, stacks),
            size_trap: *size_trap,
            failure_trap: *failure_trap,
        },
        Rvalue::MatrixRows { source } => SsaOp::MatrixRows {
            source: rename_place(source, stacks, mir),
        },
        Rvalue::MatrixColumns { source } => SsaOp::MatrixColumns {
            source: rename_place(source, stacks, mir),
        },
        Rvalue::VectorDimension { source } => SsaOp::VectorDimension {
            source: rename_place(source, stacks, mir),
        },
        Rvalue::ArrayLength { source } => SsaOp::ArrayLength {
            source: rename_place(source, stacks, mir),
        },
        Rvalue::ListInit {
            element_type,
            elements,
            size_trap,
            failure_trap,
        } => SsaOp::ListInit {
            element_type: *element_type,
            elements: elements
                .iter()
                .map(|element| rename_operand(element, stacks))
                .collect(),
            size_trap: *size_trap,
            failure_trap: *failure_trap,
        },
        Rvalue::ListLength { source } => SsaOp::ListLength {
            source: rename_place(source, stacks, mir),
        },
        Rvalue::ListCapacity { source } => SsaOp::ListCapacity {
            source: rename_place(source, stacks, mir),
        },
        Rvalue::HoleNext { hole } => SsaOp::HoleNext {
            hole: rename_operand(hole, stacks),
        },
        Rvalue::TailIndex { length } => SsaOp::TailIndex {
            length: rename_operand(length, stacks),
        },
        Rvalue::Take { slot, state } => SsaOp::Take {
            slot: SlotPlace {
                root: rename_place(&slot.root, stacks, mir),
                index: rename_operand(&slot.index, stacks),
                type_id: slot.type_id,
            },
            state: *state,
        },
        Rvalue::Relocate {
            source,
            destination,
            relocation,
        } => SsaOp::Relocate {
            source: SlotPlace {
                root: rename_place(&source.root, stacks, mir),
                index: rename_operand(&source.index, stacks),
                type_id: source.type_id,
            },
            destination: SlotPlace {
                root: rename_place(&destination.root, stacks, mir),
                index: rename_operand(&destination.index, stacks),
                type_id: destination.type_id,
            },
            relocation: *relocation,
        },
        Rvalue::ListSetLength { source, length } => SsaOp::ListSetLength {
            source: rename_place(source, stacks, mir),
            length: rename_operand(length, stacks),
        },
        Rvalue::ListPush {
            source,
            value,
            mutation,
            initialization,
            relocation,
            size_trap,
            failure_trap,
        } => SsaOp::ListPush {
            source: rename_place(source, stacks, mir),
            value: rename_operand(value, stacks),
            mutation: *mutation,
            initialization: *initialization,
            relocation: *relocation,
            size_trap: *size_trap,
            failure_trap: *failure_trap,
        },
        Rvalue::ListReserve {
            source,
            requested_capacity,
            mutation,
            relocation,
            size_trap,
            failure_trap,
        } => SsaOp::ListReserve {
            source: rename_place(source, stacks, mir),
            requested_capacity: rename_operand(requested_capacity, stacks),
            mutation: *mutation,
            relocation: *relocation,
            size_trap: *size_trap,
            failure_trap: *failure_trap,
        },
        Rvalue::AlgebraicProduct {
            left,
            right,
            kernel,
        } => SsaOp::AlgebraicProduct {
            left: rename_operand(left, stacks),
            right: rename_operand(right, stacks),
            kernel: kernel.clone(),
        },
        Rvalue::ElementwiseBinary {
            left,
            right,
            kernel,
        } => SsaOp::ElementwiseBinary {
            left: rename_operand(left, stacks),
            right: rename_operand(right, stacks),
            kernel: kernel.clone(),
        },
        Rvalue::MatrixAxisVectorView {
            source,
            fixed_index,
            axis,
            mutable,
            descriptor,
            bounds_trap,
        } => SsaOp::MatrixAxisVectorView {
            source: rename_place(source, stacks, mir),
            fixed_index: rename_operand(fixed_index, stacks),
            axis: *axis,
            mutable: *mutable,
            descriptor: *descriptor,
            bounds_trap: *bounds_trap,
        },
        Rvalue::VectorView {
            source,
            mutable,
            transpose,
            descriptor,
        } => SsaOp::VectorView {
            source: rename_place(source, stacks, mir),
            mutable: *mutable,
            transpose: *transpose,
            descriptor: *descriptor,
        },
        Rvalue::MatrixView {
            source,
            mutable,
            transpose,
            descriptor,
        } => SsaOp::MatrixView {
            source: rename_place(source, stacks, mir),
            mutable: *mutable,
            transpose: *transpose,
            descriptor: *descriptor,
        },
        Rvalue::View { source, mutable } => SsaOp::View {
            source: rename_place(source, stacks, mir),
            mutable: *mutable,
        },
        Rvalue::Aggregate { struct_id, fields } => SsaOp::Aggregate {
            struct_id: *struct_id,
            fields: fields
                .iter()
                .map(|(field, operand)| (*field, rename_operand(operand, stacks)))
                .collect(),
        },
        Rvalue::EnumConstruct {
            enum_id,
            variant_id,
            payloads,
        } => SsaOp::EnumConstruct {
            enum_id: *enum_id,
            variant_id: *variant_id,
            payloads: payloads
                .iter()
                .map(|operand| rename_operand(operand, stacks))
                .collect(),
        },
        Rvalue::EnumDiscriminant {
            value,
            enum_id,
            mode,
        } => SsaOp::EnumDiscriminant {
            value: rename_operand(value, stacks),
            enum_id: *enum_id,
            mode: *mode,
        },
        Rvalue::EnumPayload {
            value,
            enum_id,
            variant_id,
            index,
            mode,
        } => SsaOp::EnumPayload {
            value: rename_operand(value, stacks),
            enum_id: *enum_id,
            variant_id: *variant_id,
            index: *index,
            mode: *mode,
        },
        Rvalue::ConsumeEnum { owner } => SsaOp::ConsumeEnum {
            owner: rename_place(owner, stacks, mir),
        },
        Rvalue::Coerce {
            kind,
            operand,
            from,
        } => SsaOp::Coerce {
            kind: *kind,
            operand: rename_operand(operand, stacks),
            from: *from,
        },
        Rvalue::Cast {
            kind,
            operand,
            from,
            trap,
        } => SsaOp::Cast {
            kind: *kind,
            operand: rename_operand(operand, stacks),
            from: *from,
            trap: *trap,
        },
        Rvalue::Unary { op, operand, trap } => SsaOp::Unary {
            op: *op,
            operand: rename_operand(operand, stacks),
            trap: *trap,
        },
        Rvalue::Binary {
            op,
            left,
            right,
            trap,
            secondary_trap,
        } => SsaOp::Binary {
            op: *op,
            left: rename_operand(left, stacks),
            right: rename_operand(right, stacks),
            trap: *trap,
            secondary_trap: *secondary_trap,
        },
        Rvalue::Call { callee, args } => SsaOp::Call {
            callee: *callee,
            args: args
                .iter()
                .map(|argument| rename_operand(argument, stacks))
                .collect(),
        },
        Rvalue::ExceptionMatches { event, catch_class } => SsaOp::ExceptionMatches {
            event: *event,
            catch_class: *catch_class,
        },
        Rvalue::CatchBindAlias {
            event,
            catch,
            catch_class,
        } => SsaOp::CatchBindAlias {
            event: *event,
            catch: *catch,
            catch_class: *catch_class,
        },
        Rvalue::EndCatch { event } => SsaOp::EndCatch { event: *event },
        Rvalue::SetPendingFinally { finally, tag } => SsaOp::SetPendingFinally {
            finally: *finally,
            tag: *tag,
        },
        Rvalue::EnterFinally { finally } => SsaOp::EnterFinally { finally: *finally },
        Rvalue::ExitFinally { finally } => SsaOp::ExitFinally { finally: *finally },
    }
}

fn rename_place(place: &Place, stacks: &[Vec<ValueId>], mir: &MirFunction) -> SsaPlace {
    SsaPlace {
        base: match &place.base {
            PlaceBase::Local(local) => {
                if mir.locals[local.0 as usize].address_taken {
                    SsaPlaceBase::MemoryLocal(*local)
                } else {
                    SsaPlaceBase::Value(SsaOperand::Value(
                        *stacks[local.0 as usize]
                            .last()
                            .expect("verified MIR place has reaching definition"),
                    ))
                }
            }
            PlaceBase::Dereference { reference, mutable } => SsaPlaceBase::Dereference {
                reference: rename_operand(reference, stacks),
                mutable: *mutable,
            },
        },
        projections: place
            .projections
            .iter()
            .map(|projection| match projection {
                PlaceProjection::Field(field) => SsaPlaceProjection::Field(*field),
                PlaceProjection::Index {
                    index,
                    column,
                    element_type,
                    bounds_trap,
                    semantics,
                } => SsaPlaceProjection::Index {
                    index: rename_operand(index, stacks),
                    column: column.as_ref().map(|c| rename_operand(c, stacks)),
                    element_type: *element_type,
                    bounds_trap: *bounds_trap,
                    semantics: *semantics,
                },
            })
            .collect(),
    }
}

fn rvalue_result_type(
    function: &MirFunction,
    destination: &Place,
    value: &Rvalue,
    structs: &[StructInfo],
    types: &TypeArena,
) -> TypeId {
    match value {
        Rvalue::Use(operand) => mir_operand_type(function, operand),
        _ => match &destination.base {
            PlaceBase::Local(local) if destination.projections.is_empty() => {
                function.locals[local.0 as usize].ty
            }
            _ => place_type(function, destination, structs, types)
                .expect("verified MIR destination has a type"),
        },
    }
}

fn mir_operand_type(function: &MirFunction, operand: &Operand) -> TypeId {
    match operand {
        Operand::Local(local) => function.locals[local.0 as usize].ty,
        Operand::Int { ty, .. } | Operand::Float { ty, .. } => *ty,
        Operand::Bool(_) => TypeId::BOOL,
    }
}

fn rename_operand(operand: &Operand, stacks: &[Vec<ValueId>]) -> SsaOperand {
    match operand {
        Operand::Local(local) => SsaOperand::Value(
            *stacks[local.0 as usize]
                .last()
                .expect("verified MIR use has reaching definition"),
        ),
        Operand::Int { value, ty } => SsaOperand::Int {
            value: *value,
            ty: *ty,
        },
        Operand::Float { value, ty } => SsaOperand::Float {
            value: *value,
            ty: *ty,
        },
        Operand::Bool(value) => SsaOperand::Bool(*value),
    }
}

fn rename_terminator(terminator: &Terminator, stacks: &[Vec<ValueId>]) -> SsaTerminator {
    match terminator {
        Terminator::Goto(target) => SsaTerminator::Goto(*target),
        Terminator::Branch {
            condition,
            then_block,
            else_block,
        } => SsaTerminator::Branch {
            condition: rename_operand(condition, stacks),
            then_block: *then_block,
            else_block: *else_block,
        },
        Terminator::Switch {
            discriminant,
            cases,
            otherwise,
            exhaustive_enum,
        } => SsaTerminator::Switch {
            discriminant: rename_operand(discriminant, stacks),
            cases: cases.clone(),
            otherwise: *otherwise,
            exhaustive_enum: *exhaustive_enum,
        },
        Terminator::Return(value) => SsaTerminator::Return(rename_operand(value, stacks)),
        Terminator::Trap(kind) => SsaTerminator::Trap(*kind),
        Terminator::Throw {
            payload,
            class,
            transfer,
            unwind,
        } => SsaTerminator::Throw {
            payload: rename_operand(payload, stacks),
            class: *class,
            transfer: *transfer,
            unwind: *unwind,
        },
        Terminator::Rethrow { event, unwind } => SsaTerminator::Rethrow {
            event: *event,
            unwind: *unwind,
        },
        Terminator::ResumeUnwind { event } => SsaTerminator::ResumeUnwind { event: *event },
        Terminator::ForwardUnwind {
            event,
            target_event,
            target,
        } => SsaTerminator::ForwardUnwind {
            event: *event,
            target_event: *target_event,
            target: *target,
        },
    }
}

struct Cfg {
    successors: Vec<Vec<BlockId>>,
    predecessors: Vec<Vec<BlockId>>,
}

impl Cfg {
    fn new(function: &MirFunction) -> Self {
        let mut successors = vec![Vec::new(); function.blocks.len()];
        let mut predecessors = vec![Vec::new(); function.blocks.len()];
        for block in &function.blocks {
            let mut targets = mir_targets(block.terminator.as_ref().expect("verified MIR"));
            targets.extend(
                block
                    .instructions
                    .iter()
                    .filter_map(|instruction| instruction.unwind),
            );
            targets.sort();
            targets.dedup();
            successors[block.id.0 as usize].clone_from(&targets);
            for target in targets {
                predecessors[target.0 as usize].push(block.id);
            }
        }
        for values in &mut predecessors {
            values.sort();
            values.dedup();
        }
        Self {
            successors,
            predecessors,
        }
    }
}

struct Dominance {
    sets: Vec<Vec<bool>>,
    children: Vec<Vec<BlockId>>,
    frontier: Vec<Vec<BlockId>>,
}

impl Dominance {
    fn compute(cfg: &Cfg, entry: BlockId) -> Self {
        let count = cfg.successors.len();
        let mut sets = vec![vec![true; count]; count];
        sets[entry.0 as usize].fill(false);
        sets[entry.0 as usize][entry.0 as usize] = true;
        let mut changed = true;
        while changed {
            changed = false;
            for block in 0..count {
                if block == entry.0 as usize {
                    continue;
                }
                let mut next = vec![true; count];
                for predecessor in &cfg.predecessors[block] {
                    for (value, pred_value) in next.iter_mut().zip(&sets[predecessor.0 as usize]) {
                        *value &= *pred_value;
                    }
                }
                next[block] = true;
                if next != sets[block] {
                    sets[block] = next;
                    changed = true;
                }
            }
        }
        let mut idom = vec![None; count];
        for block in 0..count {
            if block == entry.0 as usize {
                continue;
            }
            let strict: Vec<usize> = (0..count)
                .filter(|candidate| *candidate != block && sets[block][*candidate])
                .collect();
            let immediate = strict
                .iter()
                .copied()
                .max_by_key(|candidate| sets[*candidate].iter().filter(|value| **value).count());
            idom[block] = immediate
                .map(|value| BlockId(u32::try_from(value).expect("verified block count fits u32")));
        }
        let mut children = vec![Vec::new(); count];
        for (block, parent) in idom.iter().enumerate() {
            if let Some(parent) = parent {
                children[parent.0 as usize].push(BlockId(
                    u32::try_from(block).expect("verified block count fits u32"),
                ));
            }
        }
        let mut frontier = vec![BTreeSet::new(); count];
        for block in 0..count {
            if cfg.predecessors[block].len() < 2 {
                continue;
            }
            let stop = idom[block];
            for predecessor in &cfg.predecessors[block] {
                let mut runner = Some(*predecessor);
                while runner != stop {
                    let value = runner.expect("reachable predecessor has idom chain");
                    frontier[value.0 as usize].insert(BlockId(
                        u32::try_from(block).expect("verified block count fits u32"),
                    ));
                    runner = idom[value.0 as usize];
                }
            }
        }
        Self {
            sets,
            children,
            frontier: frontier
                .into_iter()
                .map(|values| values.into_iter().collect())
                .collect(),
        }
    }

    fn dominates(&self, dominator: BlockId, block: BlockId) -> bool {
        self.sets[block.0 as usize][dominator.0 as usize]
    }
}

fn mir_liveness(function: &MirFunction, cfg: &Cfg) -> Vec<BTreeSet<LocalId>> {
    let count = function.blocks.len();
    let mut uses = vec![BTreeSet::new(); count];
    let mut definitions = vec![BTreeSet::new(); count];
    for block in &function.blocks {
        let index = block.id.0 as usize;
        for instruction in &block.instructions {
            for local in rvalue_locals(function, &instruction.value) {
                if !definitions[index].contains(&local) {
                    uses[index].insert(local);
                }
            }
            if let PlaceBase::Local(local) = &instruction.destination.base
                && !function.locals[local.0 as usize].address_taken
            {
                if !instruction.destination.projections.is_empty()
                    && !definitions[index].contains(local)
                {
                    uses[index].insert(*local);
                }
                definitions[index].insert(*local);
            }
        }
        for local in terminator_locals(block.terminator.as_ref().expect("verified MIR")) {
            if !definitions[index].contains(&local) {
                uses[index].insert(local);
            }
        }
    }
    let mut live_in = vec![BTreeSet::new(); count];
    let mut live_out = vec![BTreeSet::new(); count];
    let mut changed = true;
    while changed {
        changed = false;
        for block in (0..count).rev() {
            let next_out: BTreeSet<_> = cfg.successors[block]
                .iter()
                .flat_map(|successor| live_in[successor.0 as usize].iter().copied())
                .collect();
            let mut next_in = uses[block].clone();
            next_in.extend(next_out.difference(&definitions[block]).copied());
            if next_in != live_in[block] || next_out != live_out[block] {
                live_in[block] = next_in;
                live_out[block] = next_out;
                changed = true;
            }
        }
    }
    live_in
}

#[allow(clippy::too_many_lines)]
fn rvalue_locals(function: &MirFunction, value: &Rvalue) -> Vec<LocalId> {
    match value {
        Rvalue::String(op) => op
            .operands()
            .into_iter()
            .filter_map(operand_local)
            .collect(),
        Rvalue::Text(op) => op
            .operands()
            .into_iter()
            .filter_map(operand_local)
            .collect(),
        Rvalue::Use(operand)
        | Rvalue::VectorTransposeMove { operand, .. }
        | Rvalue::Coerce { operand, .. }
        | Rvalue::Cast { operand, .. }
        | Rvalue::Unary { operand, .. } => operand_local(operand).into_iter().collect(),
        Rvalue::MatrixAxisVectorView {
            source,
            fixed_index,
            ..
        } => place_locals(function, source)
            .into_iter()
            .chain(operand_local(fixed_index))
            .collect(),
        Rvalue::Load(place)
        | Rvalue::Borrow { place, .. }
        | Rvalue::Move { source: place }
        | Rvalue::Drop { owner: place }
        | Rvalue::ConsumeEnum { owner: place }
        | Rvalue::VectorView { source: place, .. }
        | Rvalue::MatrixView { source: place, .. }
        | Rvalue::View { source: place, .. }
        | Rvalue::MatrixRows { source: place }
        | Rvalue::MatrixColumns { source: place }
        | Rvalue::VectorDimension { source: place }
        | Rvalue::ArrayLength { source: place }
        | Rvalue::ListLength { source: place }
        | Rvalue::ListCapacity { source: place } => place_locals(function, place),
        Rvalue::ReplaceString { destination, value } => place_locals(function, destination)
            .into_iter()
            .chain(operand_local(value))
            .collect(),
        Rvalue::BufferAlloc {
            length, initial, ..
        }
        | Rvalue::ArrayFill {
            length, initial, ..
        } => operand_local(length)
            .into_iter()
            .chain(operand_local(initial))
            .collect(),
        Rvalue::MatrixInit { elements, .. }
        | Rvalue::VectorInit { elements, .. }
        | Rvalue::ArrayInit { elements, .. }
        | Rvalue::ListInit { elements, .. } => elements.iter().filter_map(operand_local).collect(),
        Rvalue::HoleNext { hole: length } | Rvalue::TailIndex { length } => {
            operand_local(length).into_iter().collect()
        }
        Rvalue::Take { slot, .. } => place_locals(function, &slot.root)
            .into_iter()
            .chain(operand_local(&slot.index))
            .collect(),
        Rvalue::Relocate {
            source,
            destination,
            ..
        } => [source, destination]
            .into_iter()
            .flat_map(|slot| {
                place_locals(function, &slot.root)
                    .into_iter()
                    .chain(operand_local(&slot.index))
            })
            .collect(),
        Rvalue::ListSetLength { source, length } => place_locals(function, source)
            .into_iter()
            .chain(operand_local(length))
            .collect(),
        Rvalue::ListPush { source, value, .. } => place_locals(function, source)
            .into_iter()
            .chain(operand_local(value))
            .collect(),
        Rvalue::ListReserve {
            source,
            requested_capacity,
            ..
        } => place_locals(function, source)
            .into_iter()
            .chain(operand_local(requested_capacity))
            .collect(),
        Rvalue::Aggregate { fields, .. } => fields
            .iter()
            .filter_map(|(_, operand)| operand_local(operand))
            .collect(),
        Rvalue::EnumConstruct { payloads, .. } => {
            payloads.iter().filter_map(operand_local).collect()
        }
        Rvalue::EnumDiscriminant { value, .. } | Rvalue::EnumPayload { value, .. } => {
            operand_local(value).into_iter().collect()
        }
        Rvalue::AlgebraicProduct { left, right, .. }
        | Rvalue::ElementwiseBinary { left, right, .. }
        | Rvalue::Binary { left, right, .. } => operand_local(left)
            .into_iter()
            .chain(operand_local(right))
            .collect(),
        Rvalue::Class(op) => op
            .operands()
            .into_iter()
            .filter_map(operand_local)
            .collect(),
        Rvalue::Call { args, .. } => args.iter().filter_map(operand_local).collect(),
        Rvalue::ExceptionMatches { .. }
        | Rvalue::CatchBindAlias { .. }
        | Rvalue::EndCatch { .. }
        | Rvalue::SetPendingFinally { .. }
        | Rvalue::EnterFinally { .. }
        | Rvalue::ExitFinally { .. } => vec![],
    }
}

fn place_locals(function: &MirFunction, place: &Place) -> Vec<LocalId> {
    let mut locals = match &place.base {
        PlaceBase::Local(local) if !function.locals[local.0 as usize].address_taken => vec![*local],
        PlaceBase::Local(_) => Vec::new(),
        PlaceBase::Dereference { reference, .. } => operand_local(reference).into_iter().collect(),
    };
    locals.extend(place.projections.iter().flat_map(|projection| {
        match projection {
            PlaceProjection::Index { index, column, .. } => operand_local(index)
                .into_iter()
                .chain(column.as_ref().and_then(operand_local))
                .collect::<Vec<_>>(),
            PlaceProjection::Field(_) => vec![],
        }
    }));
    locals
}

fn terminator_locals(terminator: &Terminator) -> Vec<LocalId> {
    match terminator {
        Terminator::Branch { condition, .. } | Terminator::Return(condition) => {
            operand_local(condition).into_iter().collect()
        }
        Terminator::Switch { discriminant, .. } => {
            operand_local(discriminant).into_iter().collect()
        }
        Terminator::Throw { payload, .. } => operand_local(payload).into_iter().collect(),
        Terminator::Goto(_)
        | Terminator::Trap(_)
        | Terminator::Rethrow { .. }
        | Terminator::ResumeUnwind { .. }
        | Terminator::ForwardUnwind { .. } => vec![],
    }
}

fn operand_local(operand: &Operand) -> Option<LocalId> {
    if let Operand::Local(local) = operand {
        Some(*local)
    } else {
        None
    }
}

/// Verifies structure, single definition, uses, dominance, phi edges and types.
#[allow(clippy::too_many_lines, clippy::items_after_statements)]
pub fn verify_ssa(ssa: SsaIr) -> Result<VerifiedSsa, Vec<Diagnostic>> {
    let fail = |message: String| {
        vec![Diagnostic::new(
            "E0400",
            Phase::Ssa,
            DiagnosticCategory::Verification,
            message,
            None,
        )]
    };
    if ssa.modules.is_empty()
        || ssa.entry.0 as usize >= ssa.signatures.len()
        || ssa.functions.len() != ssa.signatures.len()
    {
        return Err(fail(
            "SSA function table/body cardinality is invalid".into(),
        ));
    }
    // The shared arena retains generic declaration metadata. Runtime uses are
    // checked for concreteness below; only concrete entries need this audit.
    if ssa
        .types
        .entries()
        .filter(|(ty, _)| !ssa.types.contains_generic(*ty))
        .any(|(_, data)| match data {
            TypeData::Buffer { element } | TypeData::View { element, .. } => {
                !ssa.types.is_admitted_buffer_element(*element)
            }
            TypeData::Matrix { element } => !ssa.types.is_admitted_matrix_element(*element),
            TypeData::Vector { element, .. } => !ssa.types.is_admitted_vector_element(*element),
            TypeData::Array { element } => !ssa.types.is_admitted_array_element(*element),
            TypeData::List { element } => !ssa.types.is_admitted_list_element(*element),
            _ => false,
        })
    {
        return Err(fail(
            "SSA contains a Buffer/View/Array/List/Vector with an inadmissible element type".into(),
        ));
    }
    for ty in ssa
        .signatures
        .iter()
        .flat_map(|signature| {
            signature
                .parameters
                .iter()
                .map(|p| p.ty)
                .chain(std::iter::once(signature.return_type))
        })
        .chain(
            ssa.structs
                .iter()
                .flat_map(|info| info.fields.iter().map(|field| field.ty)),
        )
        .chain(ssa.enums.iter().flat_map(|info| {
            info.variants
                .iter()
                .flat_map(|variant| variant.payloads.iter().map(|payload| payload.ty))
        }))
        .chain(ssa.functions.iter().flat_map(|function| {
            function
                .parameters
                .iter()
                .map(|parameter| parameter.ty)
                .chain(function.blocks.iter().flat_map(|block| {
                    block
                        .phis
                        .iter()
                        .map(|phi| phi.ty)
                        .chain(block.instructions.iter().map(|instruction| instruction.ty))
                }))
                .chain(function.memory_locals.iter().map(|memory| memory.ty))
        }))
    {
        if !ssa.types.is_valid(ty) {
            return Err(fail(format!("SSA references invalid TypeId({})", ty.0)));
        }
    }
    for (index, (signature, function)) in ssa.signatures.iter().zip(&ssa.functions).enumerate() {
        if signature.id.0 as usize != index || function.id != signature.id {
            return Err(fail("SSA function identities are not canonical".into()));
        }
        if signature.module.0 as usize >= ssa.modules.len() {
            return Err(fail("SSA signature names an unknown module".into()));
        }
        if ssa.types.contains_reference(signature.return_type)
            || ssa.types.contains_view(signature.return_type)
            || ssa.structs.iter().any(|info| {
                info.fields.iter().any(|field| {
                    ssa.types.contains_reference(field.ty) || ssa.types.contains_view(field.ty)
                })
            })
            || ssa.enums.iter().any(|info| {
                info.variants.iter().any(|variant| {
                    variant.payloads.iter().any(|payload| {
                        ssa.types.contains_reference(payload.ty)
                            || ssa.types.contains_view(payload.ty)
                    })
                })
            })
        {
            return Err(fail(
                "SSA violates borrowed-value non-escape storage rules".into(),
            ));
        }
        if signature
            .parameters
            .iter()
            .any(|parameter| ssa.types.contains_generic(parameter.ty))
            || ssa.types.contains_generic(signature.return_type)
            || function
                .parameters
                .iter()
                .any(|parameter| ssa.types.contains_generic(parameter.ty))
            || function.blocks.iter().any(|block| {
                block
                    .phis
                    .iter()
                    .any(|phi| ssa.types.contains_generic(phi.ty))
                    || block
                        .instructions
                        .iter()
                        .any(|instruction| ssa.types.contains_generic(instruction.ty))
            })
        {
            return Err(fail(
                "unresolved generic parameter reached SSA codegen".into(),
            ));
        }
        verify_ssa_function(
            function,
            signature,
            &ssa.signatures,
            &ssa.structs,
            &ssa.enums,
            &ssa.types,
            &fail,
        )?;
    }
    oop_opt::verify(&ssa).map_err(fail)?;
    Ok(VerifiedSsa(ssa))
}

#[allow(clippy::too_many_lines, clippy::items_after_statements)]
fn verify_ssa_function(
    function: &SsaFunction,
    signature: &FunctionInstanceInfo,
    signatures: &[FunctionInstanceInfo],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    if function.return_type != signature.return_type
        || function.parameters.len() != signature.parameters.len()
    {
        return Err(fail("SSA function signature cache mismatch".into()));
    }
    if function.blocks.is_empty() || function.entry.0 as usize >= function.blocks.len() {
        return Err(fail("SSA entry block does not exist".into()));
    }
    for (index, event) in function.exception_events.iter().enumerate() {
        if event.0 as usize != index {
            return Err(fail("SSA exception event identity is not canonical".into()));
        }
    }
    let mut unwind_predecessors = vec![0_usize; function.blocks.len()];
    let mut ordinary_predecessors = vec![0_usize; function.blocks.len()];
    for (index, block) in function.blocks.iter().enumerate() {
        if block.id.0 as usize != index {
            return Err(fail("SSA block identity is not canonical".into()));
        }
        for target in ssa_targets(&block.terminator) {
            if target.0 as usize >= function.blocks.len() {
                return Err(fail(format!("SSA target {target:?} does not exist")));
            }
            let exceptional = matches!(
                &block.terminator,
                SsaTerminator::Throw {
                    unwind: Some(edge),
                    ..
                } | SsaTerminator::Rethrow {
                    unwind: Some(edge),
                    ..
                } if *edge == target
            );
            if exceptional {
                unwind_predecessors[target.0 as usize] += 1;
            } else {
                ordinary_predecessors[target.0 as usize] += 1;
            }
        }
        if block
            .landing_pad
            .is_some_and(|event| function.exception_events.get(event.0 as usize) != Some(&event))
        {
            return Err(fail("SSA landing pad names an unknown event".into()));
        }
        if block.landing_pad_catches && block.landing_pad.is_none() {
            return Err(fail("SSA catch landing marker has no landing pad".into()));
        }
        for instruction in &block.instructions {
            if instruction
                .unwind
                .is_some_and(|target| target.0 as usize >= function.blocks.len())
            {
                return Err(fail("SSA instruction unwind target does not exist".into()));
            }
            if let Some(target) = instruction.unwind {
                unwind_predecessors[target.0 as usize] += 1;
            }
            let may_throw = matches!(instruction.op, SsaOp::Call { .. })
                || matches!(
                    instruction.op,
                    SsaOp::Class(ref op)
                        if matches!(
                            op.as_ref(),
                            ClassOp::DirectMethodCall { .. }
                                | ClassOp::BaseMethodCall { .. }
                                | ClassOp::VirtualCall { .. }
                                | ClassOp::InterfaceCall { .. }
                                | ClassOp::BaseInit { .. }
                                | ClassOp::InitCall { .. }
                        )
                );
            if !function.exception_events.is_empty() && instruction.unwind.is_some() != may_throw {
                return Err(fail("SSA invoke/unwind edge contract is invalid".into()));
            }
        }
    }
    for block in &function.blocks {
        let index = block.id.0 as usize;
        if block.landing_pad.is_some() {
            if unwind_predecessors[index] == 0 || ordinary_predecessors[index] != 0 {
                return Err(fail(
                    "SSA landing pads require only explicit unwind predecessors".into(),
                ));
            }
        } else if unwind_predecessors[index] != 0 {
            return Err(fail("SSA unwind edge does not target a landing pad".into()));
        }
    }
    let cfg = ssa_cfg(function);
    if reachable_ssa(function).iter().any(|value| !value) {
        return Err(fail("SSA contains unreachable blocks".into()));
    }
    verify_ssa_finally_regions(function, &cfg, fail)?;
    let dominance = dominance_for_ssa(&cfg, function.entry);

    #[derive(Clone, Copy)]
    enum Position {
        Parameter,
        Phi,
        Instruction(usize),
    }
    #[derive(Clone, Copy)]
    struct Definition {
        block: BlockId,
        position: Position,
        ty: TypeId,
    }
    let mut definitions: BTreeMap<ValueId, Definition> = BTreeMap::new();
    for (parameter, declared) in function.parameters.iter().zip(&signature.parameters) {
        if parameter.ty != declared.ty {
            return Err(fail("SSA parameter type mismatch".into()));
        }
        if definitions
            .insert(
                parameter.value,
                Definition {
                    block: function.entry,
                    position: Position::Parameter,
                    ty: parameter.ty,
                },
            )
            .is_some()
        {
            return Err(fail("SSA parameter value has multiple definitions".into()));
        }
    }
    let mut seen_memory = BTreeSet::new();
    for memory in &function.memory_locals {
        if !seen_memory.insert(memory.local)
            || memory.parameter.is_some_and(|value| {
                !function
                    .parameters
                    .iter()
                    .any(|parameter| parameter.local == memory.local && parameter.value == value)
            })
        {
            return Err(fail("SSA memory-local metadata is invalid".into()));
        }
    }
    let mut drop_flag_owners = BTreeSet::new();
    let mut drop_flag_locals = BTreeSet::new();
    for entry in &function.drop_flags {
        if !drop_flag_owners.insert(entry.owner)
            || !drop_flag_locals.insert(entry.flag)
            || entry.owner == entry.flag
            || function
                .memory_locals
                .iter()
                .any(|memory| memory.local == entry.flag)
        {
            return Err(fail("SSA root-level drop-flag metadata is invalid".into()));
        }
        let phi_results = function
            .blocks
            .iter()
            .flat_map(|block| &block.phis)
            .filter(|phi| phi.local == entry.flag)
            .map(|phi| {
                if phi.ty != TypeId::BOOL {
                    return Err(fail("SSA drop-flag phi is not boolean".into()));
                }
                Ok(phi.result)
            })
            .collect::<Result<BTreeSet<_>, Vec<Diagnostic>>>()?;
        let has_cleanup_branch = function.blocks.iter().any(|block| {
            matches!(
                &block.terminator,
                SsaTerminator::Branch {
                    condition: SsaOperand::Value(value),
                    ..
                } if phi_results.contains(value) || !function.exception_events.is_empty()
            )
        });
        if function.exception_events.is_empty() && (phi_results.is_empty() || !has_cleanup_branch) {
            return Err(fail(
                "SSA conditional cleanup is disconnected from its drop flag".into(),
            ));
        }
    }
    for block in &function.blocks {
        for phi in &block.phis {
            if definitions
                .insert(
                    phi.result,
                    Definition {
                        block: block.id,
                        position: Position::Phi,
                        ty: phi.ty,
                    },
                )
                .is_some()
            {
                return Err(fail(format!(
                    "SSA value {:?} has multiple definitions",
                    phi.result
                )));
            }
        }
        for (index, instruction) in block.instructions.iter().enumerate() {
            if definitions
                .insert(
                    instruction.result,
                    Definition {
                        block: block.id,
                        position: Position::Instruction(index),
                        ty: instruction.ty,
                    },
                )
                .is_some()
            {
                return Err(fail(format!(
                    "SSA value {:?} has multiple definitions",
                    instruction.result
                )));
            }
        }
    }
    for (expected, actual) in definitions.keys().enumerate() {
        if actual.0 as usize != expected {
            return Err(fail(
                "SSA value identities are not dense and canonical".into(),
            ));
        }
    }

    let operand_ty = |operand: &SsaOperand| -> Result<TypeId, String> {
        match operand {
            SsaOperand::Value(value) => definitions
                .get(value)
                .map(|definition| definition.ty)
                .ok_or_else(|| format!("SSA use of undefined value {value:?}")),
            SsaOperand::Int { ty, .. } | SsaOperand::Float { ty, .. } => Ok(*ty),
            SsaOperand::Bool(_) => Ok(TypeId::BOOL),
        }
    };
    let validate_use = |operand: &SsaOperand,
                        use_block: BlockId,
                        use_index: Option<usize>|
     -> Result<(), String> {
        let SsaOperand::Value(value) = operand else {
            return Ok(());
        };
        let definition = definitions
            .get(value)
            .ok_or_else(|| format!("SSA use of undefined value {value:?}"))?;
        if definition.block == use_block {
            if let (Position::Instruction(def_index), Some(use_index)) =
                (definition.position, use_index)
            {
                if def_index >= use_index {
                    return Err(format!("SSA value {value:?} is used before its definition"));
                }
            }
        } else if !dominance.dominates(definition.block, use_block) {
            return Err(format!(
                "SSA definition of {value:?} does not dominate its use"
            ));
        }
        Ok(())
    };

    for block in &function.blocks {
        let expected_predecessors: BTreeSet<_> = cfg.predecessors[block.id.0 as usize]
            .iter()
            .copied()
            .collect();
        let mut seen_locals = BTreeSet::new();
        for phi in &block.phis {
            if !seen_locals.insert(phi.local) {
                return Err(fail(format!("duplicate phi for local {:?}", phi.local)));
            }
            let incoming_predecessors: BTreeSet<_> = phi
                .incoming
                .iter()
                .map(|(predecessor, _)| *predecessor)
                .collect();
            if incoming_predecessors != expected_predecessors
                || phi.incoming.len() != expected_predecessors.len()
            {
                return Err(fail(format!(
                    "phi {:?} incoming edges do not match predecessors",
                    phi.result
                )));
            }
            for (predecessor, value) in &phi.incoming {
                let definition = definitions
                    .get(value)
                    .ok_or_else(|| fail(format!("phi uses undefined value {value:?}")))?;
                if definition.ty != phi.ty {
                    return Err(fail(format!("phi {:?} incoming type mismatch", phi.result)));
                }
                if definition.block != *predecessor
                    && !dominance.dominates(definition.block, *predecessor)
                {
                    return Err(fail(format!(
                        "phi incoming {value:?} does not dominate predecessor {predecessor:?}"
                    )));
                }
            }
        }
        for (index, instruction) in block.instructions.iter().enumerate() {
            let event = match &instruction.op {
                SsaOp::ExceptionMatches { event, .. }
                | SsaOp::CatchBindAlias { event, .. }
                | SsaOp::EndCatch { event } => Some(*event),
                _ => None,
            };
            if event.is_some_and(|event| {
                function.exception_events.get(event.0 as usize) != Some(&event)
            }) {
                return Err(fail(
                    "SSA exception operation names an unknown event".into(),
                ));
            }
            for operand in op_operands(&instruction.op) {
                validate_use(operand, block.id, Some(index)).map_err(&fail)?;
            }
            verify_op(
                &instruction.op,
                instruction.ty,
                signatures,
                structs,
                enums,
                types,
                &function.memory_locals,
                &operand_ty,
            )
            .map_err(&fail)?;
        }
        match &block.terminator {
            SsaTerminator::Branch { condition, .. } => {
                validate_use(condition, block.id, Some(block.instructions.len())).map_err(&fail)?;
                if operand_ty(condition).map_err(&fail)? != TypeId::BOOL {
                    return Err(fail("SSA branch condition is not bool".into()));
                }
            }
            SsaTerminator::Switch {
                discriminant,
                cases,
                otherwise,
                exhaustive_enum,
            } => {
                validate_use(discriminant, block.id, Some(block.instructions.len()))
                    .map_err(&fail)?;
                if operand_ty(discriminant).map_err(&fail)? != TypeId::UINT32 {
                    return Err(fail("SSA switch discriminant is not uint32".into()));
                }
                let values = cases
                    .iter()
                    .map(|(value, _)| *value)
                    .collect::<BTreeSet<_>>();
                if values.len() != cases.len() || cases.is_empty() {
                    return Err(fail("SSA switch cases are empty or duplicated".into()));
                }
                if let Some(enum_id) = exhaustive_enum {
                    let info = enums
                        .get(enum_id.0 as usize)
                        .filter(|info| info.id == *enum_id)
                        .ok_or_else(|| fail("SSA exhaustive switch names unknown enum".into()))?;
                    let expected = info
                        .variants
                        .iter()
                        .map(|variant| variant.discriminant)
                        .collect::<BTreeSet<_>>();
                    if values != expected || otherwise.is_some() {
                        return Err(fail(
                            "SSA exhaustive enum switch does not cover exact tags".into(),
                        ));
                    }
                    let SsaOperand::Value(tag_value) = discriminant else {
                        return Err(fail(
                            "SSA exhaustive enum switch requires an extracted tag value".into(),
                        ));
                    };
                    let tag_definition = function
                        .blocks
                        .iter()
                        .flat_map(|candidate| &candidate.instructions)
                        .find(|instruction| instruction.result == *tag_value);
                    if !tag_definition.is_some_and(|instruction| {
                        matches!(instruction.op, SsaOp::EnumDiscriminant { enum_id: extracted, .. } if extracted == *enum_id)
                    }) {
                        return Err(fail(
                            "SSA exhaustive switch tag does not originate from its enum".into(),
                        ));
                    }
                }
            }
            SsaTerminator::Return(value) => {
                validate_use(value, block.id, Some(block.instructions.len())).map_err(&fail)?;
                if operand_ty(value).map_err(&fail)? != function.return_type {
                    return Err(fail("SSA return type mismatch".into()));
                }
            }
            SsaTerminator::Throw {
                payload,
                class,
                unwind,
                ..
            } => {
                validate_use(payload, block.id, Some(block.instructions.len())).map_err(&fail)?;
                if types.class_id(operand_ty(payload).map_err(&fail)?) != Some(*class)
                    || !types.is_exception_class(*class)
                    || unwind.is_none()
                {
                    return Err(fail("SSA throw class/edge contract is invalid".into()));
                }
            }
            SsaTerminator::Rethrow { event, unwind } => {
                if function.exception_events.get(event.0 as usize) != Some(event)
                    || unwind.is_none()
                {
                    return Err(fail("SSA rethrow event/edge contract is invalid".into()));
                }
            }
            SsaTerminator::ResumeUnwind { event } => {
                if function.exception_events.get(event.0 as usize) != Some(event) {
                    return Err(fail("SSA resume names an unknown event".into()));
                }
            }
            SsaTerminator::ForwardUnwind {
                event,
                target_event,
                ..
            } => {
                if function.exception_events.get(event.0 as usize) != Some(event)
                    || function.exception_events.get(target_event.0 as usize) != Some(target_event)
                {
                    return Err(fail("SSA forward names an unknown event".into()));
                }
            }
            SsaTerminator::Goto(_) | SsaTerminator::Trap(_) => {}
        }
    }
    aether_frontend::verify_class_metadata(types, structs, enums).map_err(fail)?;
    classes::verify(function, signatures, types, &operand_ty).map_err(fail)?;
    verify_string_ownership(function, types, fail)?;
    verify_vector_transpose_ownership(function, fail)?;
    verify_matrix_literal_ownership(function, types, fail)?;
    verify_take_protocol(function, types, fail)?;
    Ok(())
}

/// Every SSA value carrying a string owner, directly or structurally, must
/// have an explicit transfer or Drop site. Borrowing string operations do not
/// discharge ownership.
fn consume_string_operand(
    block: BlockId,
    operand: &SsaOperand,
    owners: &BTreeSet<ValueId>,
    consumed: &mut BTreeSet<(BlockId, ValueId)>,
) -> bool {
    let SsaOperand::Value(value) = operand else {
        return false;
    };
    owners.contains(value) && !consumed.insert((block, *value))
}

fn consume_string_operands<'a>(
    block: BlockId,
    operands: impl IntoIterator<Item = &'a SsaOperand>,
    owners: &BTreeSet<ValueId>,
    consumed: &mut BTreeSet<(BlockId, ValueId)>,
) -> bool {
    operands
        .into_iter()
        .any(|operand| consume_string_operand(block, operand, owners, consumed))
}

#[allow(clippy::too_many_lines)]
fn verify_string_ownership(
    function: &SsaFunction,
    types: &TypeArena,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    let carries_string_owner = |ty| types.contains_string(ty) && types.needs_drop(ty);
    let mut owners = function
        .parameters
        .iter()
        .filter(|parameter| carries_string_owner(parameter.ty))
        .map(|parameter| parameter.value)
        .collect::<BTreeSet<_>>();
    for block in &function.blocks {
        owners.extend(
            block
                .phis
                .iter()
                .filter(|phi| carries_string_owner(phi.ty))
                .map(|phi| phi.result),
        );
        owners.extend(
            block
                .instructions
                .iter()
                .filter(|instruction| carries_string_owner(instruction.ty))
                .map(|instruction| instruction.result),
        );
    }
    let mut consumed_on_path = BTreeSet::new();
    let value_from_place = |place: &SsaPlace| match &place.base {
        SsaPlaceBase::Value(SsaOperand::Value(value)) if place.projections.is_empty() => {
            Some(*value)
        }
        _ => None,
    };

    for block in &function.blocks {
        for phi in &block.phis {
            if carries_string_owner(phi.ty) {
                for (predecessor, value) in &phi.incoming {
                    if !consumed_on_path.insert((*predecessor, *value)) {
                        return Err(fail(
                            "SSA string owner is consumed twice on one control-flow path".into(),
                        ));
                    }
                }
            }
        }
        for instruction in &block.instructions {
            match &instruction.op {
                SsaOp::Move { source } | SsaOp::Drop { owner: source } => {
                    if let Some(value) = value_from_place(source)
                        && !consumed_on_path.insert((block.id, value))
                    {
                        return Err(fail(
                            "SSA string owner is consumed twice on one control-flow path".into(),
                        ));
                    }
                }
                SsaOp::Call { args, .. } => {
                    if consume_string_operands(block.id, args, &owners, &mut consumed_on_path) {
                        return Err(fail(
                            "SSA string owner is consumed twice on one control-flow path".into(),
                        ));
                    }
                }
                SsaOp::Aggregate { fields, .. } => {
                    if consume_string_operands(
                        block.id,
                        fields.iter().map(|(_, value)| value),
                        &owners,
                        &mut consumed_on_path,
                    ) {
                        return Err(fail(
                            "SSA string owner is consumed twice on one control-flow path".into(),
                        ));
                    }
                }
                SsaOp::EnumConstruct { payloads, .. }
                | SsaOp::ArrayInit {
                    elements: payloads, ..
                }
                | SsaOp::ListInit {
                    elements: payloads, ..
                } => {
                    if consume_string_operands(block.id, payloads, &owners, &mut consumed_on_path) {
                        return Err(fail(
                            "SSA string owner is consumed twice on one control-flow path".into(),
                        ));
                    }
                }
                SsaOp::ListPush { value, .. }
                | SsaOp::ReplaceString { value, .. }
                | SsaOp::Store { value, .. }
                | SsaOp::InsertField {
                    aggregate: value, ..
                } => {
                    if consume_string_operand(block.id, value, &owners, &mut consumed_on_path) {
                        return Err(fail(
                            "SSA string-composed owner is consumed twice on one control-flow path"
                                .into(),
                        ));
                    }
                }
                SsaOp::ConsumeEnum { owner } => {
                    if let Some(value) = value_from_place(owner)
                        && !consumed_on_path.insert((block.id, value))
                    {
                        return Err(fail(
                            "SSA string-composed owner is consumed twice on one control-flow path"
                                .into(),
                        ));
                    }
                }
                _ => {}
            }
        }
        if let SsaTerminator::Return(SsaOperand::Value(value)) = &block.terminator
            && carries_string_owner(function.return_type)
            && !consumed_on_path.insert((block.id, *value))
        {
            return Err(fail(
                "SSA string owner is consumed twice on one control-flow path".into(),
            ));
        }
    }
    if owners.iter().any(|owner| {
        !consumed_on_path
            .iter()
            .any(|(_, consumed)| consumed == owner)
    }) {
        return Err(fail(
            "SSA string-composed owner has no explicit Transfer or Drop".into(),
        ));
    }
    Ok(())
}

#[allow(clippy::too_many_lines)]
fn verify_ssa_finally_regions(
    function: &SsaFunction,
    cfg: &Cfg,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    let known = function
        .finally_regions
        .iter()
        .map(|region| region.id)
        .collect::<BTreeSet<_>>();
    if known.len() != function.finally_regions.len()
        || function
            .finally_regions
            .iter()
            .enumerate()
            .any(|(index, region)| region.id.0 as usize != index)
    {
        return Err(fail("SSA finally identities are not canonical".into()));
    }
    for block in &function.blocks {
        for instruction in &block.instructions {
            let marker = match instruction.op {
                SsaOp::SetPendingFinally { finally, .. }
                | SsaOp::EnterFinally { finally }
                | SsaOp::ExitFinally { finally } => Some(finally),
                _ => None,
            };
            if marker.is_some_and(|id| !known.contains(&id)) {
                return Err(fail("SSA finally marker names an unknown region".into()));
            }
        }
    }
    for region in &function.finally_regions {
        if region.body_blocks.is_empty()
            || !region.body_blocks.contains(&region.entry)
            || !region.body_blocks.contains(&region.dispatch)
            || region.exits.is_empty()
            || region
                .body_blocks
                .iter()
                .chain(&region.exits)
                .any(|block| block.0 as usize >= function.blocks.len())
        {
            return Err(fail("SSA finally region metadata is invalid".into()));
        }
        let entry = &function.blocks[region.entry.0 as usize];
        let dispatch = &function.blocks[region.dispatch.0 as usize];
        let selector = entry
            .phis
            .iter()
            .find(|phi| phi.local == region.selector)
            .filter(|phi| phi.ty == TypeId::UINT32);
        let SsaTerminator::Switch {
            discriminant: SsaOperand::Value(discriminant),
            cases,
            otherwise: None,
            exhaustive_enum: None,
        } = &dispatch.terminator
        else {
            return Err(fail("SSA finally dispatch is not canonical".into()));
        };
        let expected = region
            .exits
            .iter()
            .enumerate()
            .map(|(tag, target)| {
                (
                    u32::try_from(tag).expect("verified finally exit count fits u32"),
                    *target,
                )
            })
            .collect::<Vec<_>>();
        if cases != &expected {
            return Err(fail("SSA finally exit ordering is invalid".into()));
        }
        let enters = function
            .blocks
            .iter()
            .flat_map(|block| &block.instructions)
            .filter(|instruction| {
                matches!(instruction.op, SsaOp::EnterFinally { finally } if finally == region.id)
            })
            .count();
        let exits = function
            .blocks
            .iter()
            .flat_map(|block| &block.instructions)
            .filter(|instruction| {
                matches!(instruction.op, SsaOp::ExitFinally { finally } if finally == region.id)
            })
            .count();
        if enters != 1
            || exits != 1
            || !entry.instructions.iter().any(
                |instruction| matches!(instruction.op, SsaOp::EnterFinally { finally } if finally == region.id),
            )
            || !dispatch.instructions.iter().any(
                |instruction| matches!(instruction.op, SsaOp::ExitFinally { finally } if finally == region.id),
            )
        {
            return Err(fail("SSA finally enter/exit markers are invalid".into()));
        }
        let pending = function
            .blocks
            .iter()
            .flat_map(|block| {
                block.instructions.iter().filter_map(move |instruction| {
                    if let SsaOp::SetPendingFinally { finally, tag } = instruction.op
                        && finally == region.id
                    {
                        Some((block.id, tag, instruction.result, instruction.ty))
                    } else {
                        None
                    }
                })
            })
            .collect::<Vec<_>>();
        let phi_incoming = selector
            .map(|phi| phi.incoming.iter().copied().collect::<BTreeSet<_>>())
            .unwrap_or_default();
        let selector_is_valid = selector.map_or_else(
            || {
                pending
                    .as_slice()
                    .first()
                    .is_some_and(|(block, _, result, _)| {
                        pending.len() == 1
                            && *discriminant == *result
                            && cfg.predecessors[region.entry.0 as usize] == [*block]
                    })
            },
            |phi| *discriminant == phi.result,
        );
        if pending.len() != region.exits.len()
            || !selector_is_valid
            || pending.iter().any(|(block, tag, result, ty)| {
                *tag as usize >= region.exits.len()
                    || *ty != TypeId::UINT32
                    || !matches!(
                        function.blocks[block.0 as usize].terminator,
                        SsaTerminator::Goto(target) if target == region.entry
                    )
                    || (selector.is_some() && !phi_incoming.contains(&(*block, *result)))
            })
            || pending
                .iter()
                .map(|(_, tag, _, _)| *tag)
                .collect::<BTreeSet<_>>()
                .len()
                != region.exits.len()
            || (selector.is_some() && phi_incoming.len() != pending.len())
        {
            return Err(fail(
                "SSA pending control does not enter finally exactly once".into(),
            ));
        }
        let pending_blocks = pending
            .iter()
            .map(|(block, _, _, _)| *block)
            .collect::<BTreeSet<_>>();
        if cfg.predecessors[region.entry.0 as usize]
            .iter()
            .copied()
            .collect::<BTreeSet<_>>()
            != pending_blocks
            || region.body_blocks.iter().any(|body| {
                *body != region.entry
                    && cfg.predecessors[body.0 as usize]
                        .iter()
                        .any(|predecessor| !region.body_blocks.contains(predecessor))
            })
            || region.body_blocks.iter().any(|body| {
                *body != region.dispatch
                    && ssa_targets(&function.blocks[body.0 as usize].terminator)
                        .iter()
                        .any(|target| !region.body_blocks.contains(target))
            })
        {
            return Err(fail("SSA finally region has a bypass edge".into()));
        }
        for exit in &region.exits {
            if cfg.predecessors[exit.0 as usize] != [region.dispatch] {
                return Err(fail(
                    "SSA finally exit has a noncanonical predecessor".into(),
                ));
            }
        }
        for block in &region.body_blocks {
            let block = &function.blocks[block.0 as usize];
            if block.instructions.iter().any(|instruction| {
                instruction.unwind.is_some()
                    || matches!(instruction.op, SsaOp::Call { .. })
                    || matches!(instruction.op, SsaOp::Class(ref op) if matches!(op.as_ref(), ClassOp::DirectMethodCall { .. } | ClassOp::BaseMethodCall { .. } | ClassOp::VirtualCall { .. } | ClassOp::InterfaceCall { .. } | ClassOp::InitCall { .. } | ClassOp::BaseInit { .. }))
            }) || matches!(
                block.terminator,
                SsaTerminator::Return(_)
                    | SsaTerminator::Throw { .. }
                    | SsaTerminator::Rethrow { .. }
                    | SsaTerminator::ResumeUnwind { .. }
                    | SsaTerminator::ForwardUnwind { .. }
            ) {
                return Err(fail("SSA finally region can throw or transfer control".into()));
            }
        }
    }
    Ok(())
}

#[allow(clippy::too_many_lines)]
#[allow(clippy::too_many_arguments)]
fn verify_op(
    op: &SsaOp,
    result: TypeId,
    signatures: &[FunctionInstanceInfo],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
    memory_locals: &[SsaMemoryLocal],
    operand_ty: &impl Fn(&SsaOperand) -> Result<TypeId, String>,
) -> Result<(), String> {
    let writable = |place: &SsaPlace| -> Result<bool, String> {
        if matches!(place.base, SsaPlaceBase::Dereference { mutable: false, .. }) {
            return Ok(false);
        }
        for (position, projection) in place.projections.iter().enumerate() {
            if matches!(projection, SsaPlaceProjection::Index { .. }) {
                let prefix = SsaPlace {
                    base: place.base.clone(),
                    projections: place.projections[..position].to_vec(),
                };
                if types
                    .borrowed_view_info(ssa_place_type(
                        &prefix,
                        memory_locals,
                        structs,
                        types,
                        operand_ty,
                    )?)
                    .is_some_and(|(_, m)| !m)
                {
                    return Ok(false);
                }
            }
        }
        Ok(true)
    };
    match op {
        SsaOp::Class(op) => {
            if matches!(op.as_ref(), ClassOp::Construct { .. }) {
                return Err("unlowered ClassInit reached SSA".into());
            }
            aether_frontend::verify_class_op(op, result, types, operand_ty, |id| {
                signatures
                    .get(id.0 as usize)
                    .filter(|s| s.id == *id)
                    .map(|s| {
                        (
                            s.function_id,
                            s.parameters.iter().map(|p| p.ty).collect(),
                            s.return_type,
                        )
                    })
                    .ok_or_else(|| "unknown class method target".into())
            })?;
        }

        SsaOp::String(op) => {
            aether_frontend::verify_string_op(op, result, types, operand_ty)?;
        }
        SsaOp::Text(op) => {
            aether_frontend::verify_text_op(op, result, types, structs, enums, operand_ty)?;
        }

        SsaOp::Use(operand) => {
            if operand_ty(operand)? != result || !types.is_copy(result) {
                return Err("SSA copy type mismatch".into());
            }
        }
        SsaOp::Load { place } => {
            if ssa_place_type(place, memory_locals, structs, types, operand_ty)? != result {
                return Err("SSA memory load type mismatch".into());
            }
        }
        SsaOp::Store { place, value } => {
            if !writable(place)? {
                return Err("SSA store through shared view/reference".into());
            }
            let place_ty = ssa_place_type(place, memory_locals, structs, types, operand_ty)?;
            let value_ty = operand_ty(value)?;
            if place_ty != value_ty
                || (result != value_ty && !(types.needs_drop(value_ty) && result == TypeId::BOOL))
            {
                return Err("SSA memory store type mismatch".into());
            }
            if matches!(
                &place.base,
                SsaPlaceBase::Dereference { mutable: false, .. }
            ) {
                return Err("SSA store through shared reference".into());
            }
            let base_ty = match &place.base {
                SsaPlaceBase::Value(value) => Some(operand_ty(value)?),
                SsaPlaceBase::MemoryLocal(local) => memory_locals
                    .iter()
                    .find(|memory| memory.local == *local)
                    .map(|memory| memory.ty),
                SsaPlaceBase::Dereference { .. } => None,
            };
            if base_ty
                .and_then(|ty| types.borrowed_view_info(ty))
                .is_some_and(|(_, mutable)| !mutable)
                && place
                    .projections
                    .iter()
                    .any(|projection| matches!(projection, SsaPlaceProjection::Index { .. }))
            {
                return Err("SSA store through read-only View".into());
            }
        }
        SsaOp::Borrow { place, mutable } => {
            let pointee = ssa_place_type(place, memory_locals, structs, types, operand_ty)?;
            if types.reference_info(result) != Some((pointee, *mutable)) {
                return Err("SSA borrow result type mismatch".into());
            }
            if *mutable && !writable(place)? {
                return Err("SSA mutable borrow through shared reference".into());
            }
        }
        SsaOp::AlgebraicProduct {
            left,
            right,
            kernel,
        } => {
            kernel.verify(types, operand_ty(left)?, operand_ty(right)?, result)?;
        }
        SsaOp::ElementwiseBinary {
            left,
            right,
            kernel,
        } => {
            kernel.verify(types, operand_ty(left)?, operand_ty(right)?, result)?;
        }
        SsaOp::Move { source } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            if source_ty != result || types.is_copy(source_ty) || !source.projections.is_empty() {
                return Err("SSA Move contract invalid".into());
            }
        }
        SsaOp::ReplaceString { destination, value } => {
            if result != TypeId::BOOL
                || ssa_place_type(destination, memory_locals, structs, types, operand_ty)?
                    != TypeId::STRING
                || operand_ty(value)? != TypeId::STRING
                || !writable(destination)?
            {
                return Err("SSA string replacement contract invalid".into());
            }
        }
        SsaOp::Drop { owner } => {
            let owner_ty = ssa_place_type(owner, memory_locals, structs, types, operand_ty)?;
            if result != TypeId::BOOL
                || !types.needs_drop(owner_ty)
                || !owner.projections.is_empty()
            {
                return Err("SSA Drop contract invalid".into());
            }
        }
        SsaOp::BufferAlloc {
            element_type,
            length,
            initial,
            size_trap,
            failure_trap,
        } => {
            if types.buffer_element(result) != Some(*element_type)
                || operand_ty(length)? != TypeId::USIZE
                || operand_ty(initial)? != *element_type
                || !types.is_copy(*element_type)
                || types.needs_drop(*element_type)
                || *size_trap != TrapKind::AllocationSizeOverflow
                || *failure_trap != TrapKind::AllocationFailure
            {
                return Err("SSA Buffer allocation contract invalid".into());
            }
        }
        SsaOp::VectorTransposeMove {
            operand,
            source_type,
        } => {
            if operand_ty(operand)? != *source_type
                || !matches!((types.get(*source_type), types.get(result)),
                (Some(TypeData::Vector { element: a, orientation: x }),
                 Some(TypeData::Vector { element: b, orientation: y }))
                if a == b && x.transposed() == *y)
            {
                return Err("SSA Vector transpose orientation/type contract invalid".into());
            }
        }
        SsaOp::MatrixInit {
            rows,
            columns,
            row_ends,
            element_type,
            elements,
            size_trap,
            failure_trap,
        } => {
            if !valid_matrix_literal_shape(*rows, *columns, row_ends, elements.len())
                || types.matrix_element(result) != Some(*element_type)
                || elements
                    .iter()
                    .any(|element| operand_ty(element).ok() != Some(*element_type))
                || !types.is_admitted_matrix_element(*element_type)
                || *size_trap != TrapKind::AllocationSizeOverflow
                || *failure_trap != TrapKind::AllocationFailure
            {
                return Err("SSA Matrix literal allocation contract invalid".into());
            }
        }
        SsaOp::VectorInit {
            element_type,
            elements,
            size_trap,
            failure_trap,
        } => {
            if types.vector_element(result) != Some(*element_type)
                || elements
                    .iter()
                    .any(|element| operand_ty(element).ok() != Some(*element_type))
                || !types.is_admitted_vector_element(*element_type)
                || *size_trap != TrapKind::AllocationSizeOverflow
                || *failure_trap != TrapKind::AllocationFailure
            {
                return Err("SSA Vector literal allocation contract invalid".into());
            }
        }
        SsaOp::ArrayInit {
            element_type,
            elements,
            size_trap,
            failure_trap,
        } => {
            if types.array_element(result) != Some(*element_type)
                || elements
                    .iter()
                    .any(|element| operand_ty(element).ok() != Some(*element_type))
                || !types.is_admitted_array_element(*element_type)
                || *size_trap != TrapKind::AllocationSizeOverflow
                || *failure_trap != TrapKind::AllocationFailure
            {
                return Err("SSA Array literal allocation contract invalid".into());
            }
        }
        SsaOp::ArrayFill {
            element_type,
            length,
            initial,
            size_trap,
            failure_trap,
        } => {
            if types.array_element(result) != Some(*element_type)
                || operand_ty(length)? != TypeId::USIZE
                || operand_ty(initial)? != *element_type
                || !types.is_admitted_array_element(*element_type)
                || !types.is_copy(*element_type)
                || *size_trap != TrapKind::AllocationSizeOverflow
                || *failure_trap != TrapKind::AllocationFailure
            {
                return Err("SSA Array fill allocation contract invalid".into());
            }
        }
        SsaOp::MatrixRows { source } | SsaOp::MatrixColumns { source } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            if result != TypeId::USIZE || types.matrix_like_element(source_ty).is_none() {
                return Err("SSA Matrix shape contract invalid".into());
            }
        }
        SsaOp::VectorDimension { source } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            if result != TypeId::USIZE || types.vector_like_info(source_ty).is_none() {
                return Err("SSA Vector dimension contract invalid".into());
            }
        }
        SsaOp::ArrayLength { source } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            if result != TypeId::USIZE || types.array_element(source_ty).is_none() {
                return Err("SSA Array length contract invalid".into());
            }
        }
        SsaOp::ListInit {
            element_type,
            elements,
            size_trap,
            failure_trap,
        } => {
            if types.list_element(result) != Some(*element_type)
                || elements
                    .iter()
                    .any(|element| operand_ty(element).ok() != Some(*element_type))
                || !types.is_admitted_list_element(*element_type)
                || *size_trap != TrapKind::AllocationSizeOverflow
                || *failure_trap != TrapKind::AllocationFailure
            {
                return Err("SSA List literal allocation contract invalid".into());
            }
        }
        SsaOp::ListLength { source } | SsaOp::ListCapacity { source } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            if result != TypeId::USIZE || types.list_element(source_ty).is_none() {
                return Err("SSA List metadata query contract invalid".into());
            }
        }
        SsaOp::HoleNext { hole: length } | SsaOp::TailIndex { length } => {
            if result != TypeId::USIZE || operand_ty(length)? != TypeId::USIZE {
                return Err("SSA invalid Take tail index type".into());
            }
        }
        SsaOp::Take { slot, state } => {
            let source_ty = ssa_place_type(&slot.root, memory_locals, structs, types, operand_ty)?;
            if result != slot.type_id
                || operand_ty(&slot.index)? != TypeId::USIZE
                || types.list_element(source_ty) != Some(slot.type_id)
                || !types.is_admitted_list_element(slot.type_id)
                || *state != TakeState::INITIALIZED_TO_UNINITIALIZED
            {
                return Err("SSA invalid Take initialization/type contract".into());
            }
        }
        SsaOp::Relocate {
            source,
            destination,
            relocation,
        } => {
            for slot in [source, destination] {
                let ty = ssa_place_type(&slot.root, memory_locals, structs, types, operand_ty)?;
                if operand_ty(&slot.index)? != TypeId::USIZE
                    || types.list_element(ty) != Some(slot.type_id)
                    || !types.is_admitted_list_element(slot.type_id)
                {
                    return Err("SSA invalid Relocate slot type".into());
                }
            }
            if result != TypeId::BOOL
                || source.type_id != destination.type_id
                || *relocation != Relocate::single_slot(source.type_id)
            {
                return Err("SSA invalid Relocate initialization contract".into());
            }
        }
        SsaOp::ListSetLength { source, length } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            let root = SsaPlace {
                base: source.base.clone(),
                projections: Vec::new(),
            };
            let root_ty = ssa_place_type(&root, memory_locals, structs, types, operand_ty)?;
            if types
                .borrowed_view_info(root_ty)
                .is_some_and(|(_, mutable)| !mutable)
                || result != TypeId::BOOL
                || operand_ty(length)? != TypeId::USIZE
                || types.list_element(source_ty).is_none()
                || matches!(
                    source.base,
                    SsaPlaceBase::Dereference { mutable: false, .. } | SsaPlaceBase::Value(_)
                )
            {
                return Err("SSA invalid Take length commit / writable storage root".into());
            }
        }
        SsaOp::ListPush {
            source,
            value,
            mutation,
            initialization,
            relocation,
            size_trap,
            failure_trap,
        } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            if result != source_ty
                || types.list_element(source_ty) != Some(operand_ty(value)?)
                || !valid_list_relocation(types, relocation, types.list_element(source_ty))
                || *initialization != PushInit::tail(operand_ty(value)?)
                || *mutation != StructuralMutation::Push
                || *size_trap != TrapKind::AllocationSizeOverflow
                || *failure_trap != TrapKind::AllocationFailure
            {
                return Err("SSA List push contract invalid".into());
            }
        }
        SsaOp::ListReserve {
            source,
            requested_capacity,
            mutation,
            relocation,
            size_trap,
            failure_trap,
        } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            if result != source_ty
                || types.list_element(source_ty).is_none()
                || !valid_list_relocation(types, relocation, types.list_element(source_ty))
                || operand_ty(requested_capacity)? != TypeId::USIZE
                || *mutation != StructuralMutation::Reserve
                || *size_trap != TrapKind::AllocationSizeOverflow
                || *failure_trap != TrapKind::AllocationFailure
            {
                return Err("SSA List reserve contract invalid".into());
            }
        }
        SsaOp::MatrixAxisVectorView {
            source,
            fixed_index,
            axis,
            mutable,
            descriptor,
            bounds_trap,
        } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            let element = types
                .matrix_like_element(source_ty)
                .ok_or_else(|| "SSA MatrixAxisVectorView source rank/type invalid".to_string())?;
            if types.vector_view_info(result) != Some((element, *axis, *mutable))
                || operand_ty(fixed_index)? != TypeId::USIZE
                || *bounds_trap != TrapKind::IndexOutOfBounds
                || *descriptor != aether_frontend::MatrixAxisVectorViewDescriptor::derived(*axis)
                || (*mutable
                    && (types.matrix_view_info(source_ty).is_some_and(|(_, m)| !m)
                        || !writable(source)?))
            {
                return Err("SSA MatrixAxisVectorView bounds/recipe/orientation/capability contract invalid".into());
            }
        }
        SsaOp::VectorView {
            source,
            mutable,
            transpose,
            descriptor,
        } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            let (element, orientation) = types
                .vector_like_info(source_ty)
                .ok_or_else(|| "SSA VectorView source invalid".to_string())?;
            if types.vector_view_info(result)
                != Some((
                    element,
                    if *transpose {
                        orientation.transposed()
                    } else {
                        orientation
                    },
                    *mutable,
                ))
                || *descriptor
                    != aether_frontend::VectorViewDescriptor::derived(
                        types.vector_view_info(source_ty).is_some(),
                    )
                || (*mutable
                    && (types
                        .vector_view_info(source_ty)
                        .is_some_and(|(_, _, m)| !m)
                        || !writable(source)?))
            {
                return Err("SSA VectorView stride/type/capability contract invalid".into());
            }
        }
        SsaOp::MatrixView {
            source,
            mutable,
            transpose,
            descriptor,
        } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            let element = types
                .matrix_like_element(source_ty)
                .ok_or_else(|| "SSA MatrixView source invalid".to_string())?;
            if types.matrix_view_info(result) != Some((element, *mutable))
                || *descriptor
                    != aether_frontend::MatrixViewDescriptor::derived(
                        types.matrix_view_info(source_ty).is_some(),
                        *transpose,
                    )
                || (*mutable
                    && (types.matrix_view_info(source_ty).is_some_and(|(_, m)| !m)
                        || !writable(source)?))
            {
                return Err("SSA MatrixView stride/type/capability contract invalid".into());
            }
        }
        SsaOp::View { source, mutable } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            let element = types
                .owning_contiguous_element(source_ty)
                .filter(|_| {
                    types.vector_element(source_ty).is_none()
                        && types.matrix_element(source_ty).is_none()
                })
                .ok_or_else(|| "SSA View source is not Buffer/Array/List".to_string())?;
            if types.view_info(result) != Some((element, *mutable)) {
                return Err("SSA View contract invalid".into());
            }
        }
        SsaOp::Aggregate { struct_id, fields } => {
            let info = structs
                .get(struct_id.0 as usize)
                .filter(|info| info.id == *struct_id)
                .ok_or_else(|| "SSA aggregate names unknown struct".to_string())?;
            if types.struct_id(result) != Some(*struct_id) || fields.len() != info.fields.len() {
                return Err("SSA aggregate arity/result mismatch".into());
            }
            for ((field_id, operand), declared) in fields.iter().zip(&info.fields) {
                let expected = concrete_struct_member(types, structs, result, declared.ty)?;
                if *field_id != declared.id || operand_ty(operand)? != expected {
                    return Err("SSA aggregate field identity/type mismatch".into());
                }
            }
        }
        SsaOp::EnumConstruct {
            enum_id,
            variant_id,
            payloads,
        } => {
            let info = enums
                .get(enum_id.0 as usize)
                .filter(|info| info.id == *enum_id)
                .ok_or_else(|| "SSA enum construction names unknown enum".to_string())?;
            let variant = info
                .variants
                .get(variant_id.index as usize)
                .filter(|variant| variant.id == *variant_id)
                .ok_or_else(|| "SSA enum construction names wrong variant".to_string())?;
            if types.enum_id(result) != Some(*enum_id) || payloads.len() != variant.payloads.len() {
                return Err("SSA enum construction arity/result mismatch".into());
            }
            for (operand, declared) in payloads.iter().zip(&variant.payloads) {
                let expected = concrete_enum_member(types, enums, result, declared.ty)?;
                if operand_ty(operand)? != expected {
                    return Err("SSA enum payload type mismatch".into());
                }
            }
        }
        SsaOp::EnumDiscriminant {
            value,
            enum_id,
            mode,
        } => {
            let value_ty = operand_ty(value)?;
            let enum_ty = match mode {
                MatchMode::Value => value_ty,
                MatchMode::SharedRef => types
                    .reference_info(value_ty)
                    .filter(|(_, mutable)| !*mutable)
                    .map(|(pointee, _)| pointee)
                    .ok_or_else(|| {
                        "SSA shared match source is not a shared reference".to_string()
                    })?,
                MatchMode::MutableRef => types
                    .reference_info(value_ty)
                    .filter(|(_, mutable)| *mutable)
                    .map(|(pointee, _)| pointee)
                    .ok_or_else(|| {
                        "SSA mutable match source is not a mutable reference".to_string()
                    })?,
            };
            if enums.get(enum_id.0 as usize).map(|info| info.id) != Some(*enum_id)
                || types.enum_id(enum_ty) != Some(*enum_id)
                || result != TypeId::UINT32
            {
                return Err("SSA enum discriminant contract invalid".into());
            }
        }
        SsaOp::EnumPayload {
            value,
            enum_id,
            variant_id,
            index,
            mode,
        } => {
            let info = enums
                .get(enum_id.0 as usize)
                .filter(|info| info.id == *enum_id)
                .ok_or_else(|| "SSA enum payload names unknown enum".to_string())?;
            let variant = info
                .variants
                .get(variant_id.index as usize)
                .filter(|variant| variant.id == *variant_id)
                .ok_or_else(|| "SSA enum payload names wrong variant".to_string())?;
            let payload = variant
                .payloads
                .get(*index as usize)
                .ok_or_else(|| "SSA enum payload slot out of bounds".to_string())?;
            let value_ty = operand_ty(value)?;
            let enum_ty = match mode {
                MatchMode::Value => value_ty,
                MatchMode::SharedRef => types
                    .reference_info(value_ty)
                    .filter(|(_, mutable)| !*mutable)
                    .map(|(pointee, _)| pointee)
                    .ok_or_else(|| {
                        "SSA shared payload source is not a shared reference".to_string()
                    })?,
                MatchMode::MutableRef => types
                    .reference_info(value_ty)
                    .filter(|(_, mutable)| *mutable)
                    .map(|(pointee, _)| pointee)
                    .ok_or_else(|| {
                        "SSA mutable payload source is not a mutable reference".to_string()
                    })?,
            };
            let payload_ty = concrete_enum_member(types, enums, enum_ty, payload.ty)?;
            let expected = match mode {
                MatchMode::Value => payload_ty,
                MatchMode::SharedRef => types
                    .id_of(TypeData::Reference {
                        pointee: payload_ty,
                        mutable: false,
                    })
                    .ok_or_else(|| "SSA shared payload reference type missing".to_string())?,
                MatchMode::MutableRef => types
                    .id_of(TypeData::Reference {
                        pointee: payload_ty,
                        mutable: true,
                    })
                    .ok_or_else(|| "SSA mutable payload reference type missing".to_string())?,
            };
            if types.enum_id(enum_ty) != Some(*enum_id) || result != expected {
                return Err("SSA enum payload extraction type mismatch".into());
            }
        }
        SsaOp::ConsumeEnum { owner } => {
            let owner_ty = ssa_place_type(owner, memory_locals, structs, types, operand_ty)?;
            if result != TypeId::BOOL
                || types.enum_id(owner_ty).is_none()
                || types.is_copy(owner_ty)
                || !owner.projections.is_empty()
            {
                return Err("SSA consuming enum match contract invalid".into());
            }
        }
        SsaOp::ExtractField {
            aggregate,
            projections,
        } => {
            if projections.is_empty()
                || field_path_type(operand_ty(aggregate)?, projections, structs, types)? != result
            {
                return Err("SSA extract-field contract invalid".into());
            }
        }
        SsaOp::InsertField {
            aggregate,
            projections,
            value,
        } => {
            let aggregate_ty = operand_ty(aggregate)?;
            if aggregate_ty != result
                || types.struct_id(result).is_none()
                || projections.is_empty()
                || field_path_type(aggregate_ty, projections, structs, types)? != operand_ty(value)?
            {
                return Err("SSA insert-field contract invalid".into());
            }
        }
        SsaOp::Coerce {
            kind,
            operand,
            from,
        } => {
            if operand_ty(operand)? != *from || !valid_coercion(types, *kind, *from, result) {
                return Err("invalid SSA coercion contract".into());
            }
        }
        SsaOp::Cast {
            kind,
            operand,
            from,
            trap,
        } => {
            let required_trap = crate::mir::cast_can_fail(types, *from, result)
                .then_some(TrapKind::ConversionOutOfRange);
            if operand_ty(operand)? != *from
                || !crate::mir::valid_cast(types, *kind, *from, result)
                || *trap != required_trap
            {
                return Err("invalid SSA explicit-cast contract".into());
            }
        }
        SsaOp::Unary { op, operand, trap } => {
            let ty = operand_ty(operand)?;
            let valid = match op {
                UnaryOp::NegateIntegerChecked => types
                    .integer_info(ty)
                    .is_some_and(aether_frontend::IntegerType::is_signed),
                UnaryOp::NegateFloat => types.float_info(ty).is_some(),
            };
            let required_trap =
                matches!(op, UnaryOp::NegateIntegerChecked).then_some(TrapKind::IntegerOverflow);
            if result != ty || !valid || *trap != required_trap {
                return Err("invalid SSA checked-negation contract".into());
            }
        }
        SsaOp::Binary {
            op,
            left,
            right,
            trap,
            secondary_trap,
        } => {
            let left = operand_ty(left)?;
            let right = operand_ty(right)?;
            if left != right {
                return Err("SSA binary operand type mismatch".into());
            }
            let (required, output, required_trap, required_secondary) =
                crate::mir::binary_contract(types, *op, left)?;
            if left != required
                || result != output
                || *trap != required_trap
                || *secondary_trap != required_secondary
            {
                return Err(format!("invalid SSA contract for {op:?}"));
            }
        }
        SsaOp::Call { callee, args } => {
            let signature = signatures
                .get(callee.0 as usize)
                .filter(|signature| signature.id == *callee)
                .ok_or_else(|| format!("SSA call target {callee:?} does not exist"))?;
            if args.len() != signature.parameters.len() || result != signature.return_type {
                return Err("SSA call result/arity violates signature".into());
            }
            for (argument, parameter) in args.iter().zip(&signature.parameters) {
                if operand_ty(argument)? != parameter.ty {
                    return Err("SSA call argument type mismatch".into());
                }
            }
        }
        SsaOp::ExceptionMatches { event, catch_class } => {
            if result != TypeId::BOOL || !types.is_exception_class(*catch_class) {
                return Err(format!("invalid SSA exception match for event {event:?}"));
            }
        }
        SsaOp::CatchBindAlias {
            event, catch_class, ..
        } => {
            if types.class_id(result) != Some(*catch_class)
                || !types.is_exception_class(*catch_class)
            {
                return Err(format!("invalid SSA catch binding for event {event:?}"));
            }
        }
        SsaOp::EndCatch { .. } | SsaOp::EnterFinally { .. } | SsaOp::ExitFinally { .. }
            if result == TypeId::BOOL => {}
        SsaOp::EndCatch { .. } => return Err("SSA end-catch result is not bool".into()),
        SsaOp::SetPendingFinally { .. } if result == TypeId::UINT32 => {}
        SsaOp::SetPendingFinally { .. } => {
            return Err("SSA pending-finally tag result is not uint32".into());
        }
        SsaOp::EnterFinally { .. } | SsaOp::ExitFinally { .. } => {
            return Err("SSA finally marker result is not bool".into());
        }
    }
    Ok(())
}

fn valid_list_relocation(
    types: &TypeArena,
    relocation: &Relocate,
    expected_element: Option<TypeId>,
) -> bool {
    expected_element == Some(relocation.type_id)
        && types.is_admitted_list_element(relocation.type_id)
        && types.is_relocatable(relocation.type_id)
        && relocation.destination_after == ElementInitialization::Initialized
        && relocation.range == RelocationRange::ListInitializedPrefix
        && relocation.source_before == ElementInitialization::Initialized
        && relocation.destination_before == ElementInitialization::Uninitialized
        && relocation.source_after == ElementInitialization::Uninitialized
        && relocation.increasing_order
        && relocation.non_trapping
}

fn ssa_place_type(
    place: &SsaPlace,
    memory_locals: &[SsaMemoryLocal],
    structs: &[StructInfo],
    types: &TypeArena,
    operand_ty: &impl Fn(&SsaOperand) -> Result<TypeId, String>,
) -> Result<TypeId, String> {
    let mut ty = match &place.base {
        SsaPlaceBase::MemoryLocal(local) => memory_locals
            .iter()
            .find(|memory| memory.local == *local)
            .map(|memory| memory.ty)
            .ok_or_else(|| "SSA place names unknown memory local".to_string())?,
        SsaPlaceBase::Dereference { reference, mutable } => {
            let (pointee, capability) = types
                .reference_info(operand_ty(reference)?)
                .ok_or_else(|| "SSA place dereferences non-reference".to_string())?;
            if capability != *mutable {
                return Err("SSA dereference capability cache mismatch".into());
            }
            pointee
        }
        SsaPlaceBase::Value(value) => operand_ty(value)?,
    };
    for projection in &place.projections {
        match projection {
            SsaPlaceProjection::Field(field) => {
                ty = field_path_type(ty, &[*field], structs, types)?;
            }
            SsaPlaceProjection::Index {
                index,
                column,
                element_type,
                bounds_trap,
                semantics,
            } => {
                let element = types
                    .buffer_element(ty)
                    .or_else(|| types.array_element(ty))
                    .or_else(|| types.vector_element(ty))
                    .or_else(|| types.matrix_element(ty))
                    .or_else(|| types.list_element(ty))
                    .or_else(|| types.borrowed_view_info(ty).map(|(element, _)| element))
                    .ok_or_else(|| "SSA index projection has non-contiguous base".to_string())?;
                if column.is_some() != types.matrix_like_element(ty).is_some()
                    || column
                        .as_ref()
                        .is_some_and(|c| operand_ty(c).ok() != Some(TypeId::USIZE))
                    || operand_ty(index)? != TypeId::USIZE
                    || element != *element_type
                    || types.index_semantics(ty) != Some(*semantics)
                    || *bounds_trap != TrapKind::IndexOutOfBounds
                {
                    return Err("SSA index projection contract invalid".into());
                }
                ty = element;
            }
        }
    }
    Ok(ty)
}

fn field_path_type(
    mut ty: TypeId,
    projections: &[FieldId],
    structs: &[StructInfo],
    types: &TypeArena,
) -> Result<TypeId, String> {
    for field_id in projections {
        let owner = types
            .struct_id(ty)
            .ok_or_else(|| "field path projects non-struct type".to_string())?;
        let field = structs
            .get(owner.0 as usize)
            .and_then(|info| info.fields.iter().find(|field| field.id == *field_id))
            .ok_or_else(|| "field path identity does not belong to struct".to_string())?;
        ty = concrete_struct_member(types, structs, ty, field.ty)?;
    }
    Ok(ty)
}

fn concrete_struct_member(
    types: &TypeArena,
    structs: &[StructInfo],
    aggregate: TypeId,
    member: TypeId,
) -> Result<TypeId, String> {
    let Some(TypeData::StructInstance(id, args)) = types.get(aggregate) else {
        return Ok(member);
    };
    let parameters = &structs
        .get(id.0 as usize)
        .ok_or_else(|| "unknown generic struct".to_string())?
        .generic_parameters;
    let substitution = Substitution::new(
        parameters.iter().map(|parameter| parameter.id),
        types
            .arguments(*args)
            .ok_or_else(|| "invalid struct arguments".to_string())?
            .iter()
            .copied(),
    );
    types
        .substituted_existing(member, &substitution)
        .map_err(|_| "incomplete struct substitution".to_string())
}

fn concrete_enum_member(
    types: &TypeArena,
    enums: &[EnumInfo],
    aggregate: TypeId,
    member: TypeId,
) -> Result<TypeId, String> {
    let Some(TypeData::EnumInstance(id, args)) = types.get(aggregate) else {
        return Ok(member);
    };
    let parameters = &enums
        .get(id.0 as usize)
        .ok_or_else(|| "unknown generic enum".to_string())?
        .generic_parameters;
    let substitution = Substitution::new(
        parameters.iter().map(|parameter| parameter.id),
        types
            .arguments(*args)
            .ok_or_else(|| "invalid enum arguments".to_string())?
            .iter()
            .copied(),
    );
    types
        .substituted_existing(member, &substitution)
        .map_err(|_| "incomplete enum substitution".to_string())
}

fn valid_coercion(types: &TypeArena, kind: CoercionKind, from: TypeId, to: TypeId) -> bool {
    match (kind, types.integer_info(from), types.integer_info(to)) {
        (CoercionKind::SignExtend, Some(a), Some(b)) => a.is_signed() && a.can_widen_to(b),
        (CoercionKind::ZeroExtend, Some(a), Some(b)) => !a.is_signed() && a.can_widen_to(b),
        (CoercionKind::FloatExtend, _, _) if from == TypeId::FLOAT32 && to == TypeId::FLOAT64 => {
            true
        }
        _ => false,
    }
}

fn op_operands(op: &SsaOp) -> Vec<&SsaOperand> {
    match op {
        SsaOp::String(op) => op.operands(),
        SsaOp::Text(op) => op.operands(),
        SsaOp::Use(value)
        | SsaOp::VectorTransposeMove { operand: value, .. }
        | SsaOp::Coerce { operand: value, .. }
        | SsaOp::Cast { operand: value, .. }
        | SsaOp::EnumDiscriminant { value, .. }
        | SsaOp::EnumPayload { value, .. } => vec![value],
        SsaOp::MatrixAxisVectorView {
            source,
            fixed_index,
            ..
        } => place_operands(source)
            .into_iter()
            .chain(std::iter::once(fixed_index))
            .collect(),
        SsaOp::Load { place }
        | SsaOp::Borrow { place, .. }
        | SsaOp::Move { source: place }
        | SsaOp::Drop { owner: place }
        | SsaOp::ConsumeEnum { owner: place }
        | SsaOp::VectorView { source: place, .. }
        | SsaOp::MatrixView { source: place, .. }
        | SsaOp::View { source: place, .. }
        | SsaOp::MatrixRows { source: place }
        | SsaOp::MatrixColumns { source: place }
        | SsaOp::VectorDimension { source: place }
        | SsaOp::ArrayLength { source: place }
        | SsaOp::ListLength { source: place }
        | SsaOp::ListCapacity { source: place } => place_operands(place),
        SsaOp::ReplaceString { destination, value } => place_operands(destination)
            .into_iter()
            .chain(std::iter::once(value))
            .collect(),
        SsaOp::Store { place, value } => place_operands(place)
            .into_iter()
            .chain(std::iter::once(value))
            .collect(),
        SsaOp::BufferAlloc {
            length, initial, ..
        }
        | SsaOp::ArrayFill {
            length, initial, ..
        } => vec![length, initial],
        SsaOp::MatrixInit { elements, .. }
        | SsaOp::VectorInit { elements, .. }
        | SsaOp::ArrayInit { elements, .. }
        | SsaOp::ListInit { elements, .. } => elements.iter().collect(),
        SsaOp::HoleNext { hole: length } | SsaOp::TailIndex { length } => vec![length],
        SsaOp::Take { slot, .. } => place_operands(&slot.root)
            .into_iter()
            .chain(std::iter::once(&slot.index))
            .collect(),
        SsaOp::Relocate {
            source,
            destination,
            ..
        } => [source, destination]
            .into_iter()
            .flat_map(|slot| place_operands(&slot.root).into_iter().chain([&slot.index]))
            .collect(),
        SsaOp::ListSetLength { source, length } => place_operands(source)
            .into_iter()
            .chain(std::iter::once(length))
            .collect(),
        SsaOp::ListPush { source, value, .. } => place_operands(source)
            .into_iter()
            .chain(std::iter::once(value))
            .collect(),
        SsaOp::ListReserve {
            source,
            requested_capacity,
            ..
        } => place_operands(source)
            .into_iter()
            .chain(std::iter::once(requested_capacity))
            .collect(),
        SsaOp::Aggregate { fields, .. } => fields.iter().map(|(_, value)| value).collect(),
        SsaOp::EnumConstruct { payloads, .. } => payloads.iter().collect(),
        SsaOp::ExtractField { aggregate, .. } => vec![aggregate],
        SsaOp::InsertField {
            aggregate, value, ..
        } => vec![aggregate, value],
        SsaOp::Unary { operand, .. } => vec![operand],
        SsaOp::AlgebraicProduct { left, right, .. }
        | SsaOp::ElementwiseBinary { left, right, .. }
        | SsaOp::Binary { left, right, .. } => {
            vec![left, right]
        }
        SsaOp::Class(op) => op.operands(),
        SsaOp::Call { args, .. } => args.iter().collect(),
        SsaOp::ExceptionMatches { .. }
        | SsaOp::CatchBindAlias { .. }
        | SsaOp::EndCatch { .. }
        | SsaOp::SetPendingFinally { .. }
        | SsaOp::EnterFinally { .. }
        | SsaOp::ExitFinally { .. } => vec![],
    }
}

fn place_operands(place: &SsaPlace) -> Vec<&SsaOperand> {
    let mut operands = match &place.base {
        SsaPlaceBase::MemoryLocal(_) => Vec::new(),
        SsaPlaceBase::Dereference { reference, .. } | SsaPlaceBase::Value(reference) => {
            vec![reference]
        }
    };
    operands.extend(place.projections.iter().flat_map(|projection| {
        match projection {
            SsaPlaceProjection::Index { index, column, .. } => std::iter::once(index)
                .chain(column.iter())
                .collect::<Vec<_>>(),
            SsaPlaceProjection::Field(_) => vec![],
        }
    }));
    operands
}

fn mir_targets(terminator: &Terminator) -> Vec<BlockId> {
    match terminator {
        Terminator::Goto(target) | Terminator::ForwardUnwind { target, .. } => vec![*target],
        Terminator::Branch {
            then_block,
            else_block,
            ..
        } => vec![*then_block, *else_block],
        Terminator::Switch {
            cases, otherwise, ..
        } => {
            let mut targets: Vec<_> = cases.iter().map(|(_, target)| *target).collect();
            targets.extend(otherwise.iter().copied());
            targets.sort();
            targets.dedup();
            targets
        }
        Terminator::Throw { unwind, .. } | Terminator::Rethrow { unwind, .. } => {
            unwind.iter().copied().collect()
        }
        Terminator::Return(_) | Terminator::Trap(_) | Terminator::ResumeUnwind { .. } => vec![],
    }
}

fn ssa_targets(terminator: &SsaTerminator) -> Vec<BlockId> {
    match terminator {
        SsaTerminator::Goto(target) | SsaTerminator::ForwardUnwind { target, .. } => vec![*target],
        SsaTerminator::Branch {
            then_block,
            else_block,
            ..
        } => vec![*then_block, *else_block],
        SsaTerminator::Switch {
            cases, otherwise, ..
        } => {
            let mut targets: Vec<_> = cases.iter().map(|(_, target)| *target).collect();
            targets.extend(otherwise.iter().copied());
            targets.sort();
            targets.dedup();
            targets
        }
        SsaTerminator::Throw { unwind, .. } | SsaTerminator::Rethrow { unwind, .. } => {
            unwind.iter().copied().collect()
        }
        SsaTerminator::Return(_) | SsaTerminator::Trap(_) | SsaTerminator::ResumeUnwind { .. } => {
            vec![]
        }
    }
}

fn ssa_cfg(function: &SsaFunction) -> Cfg {
    let mut successors = vec![Vec::new(); function.blocks.len()];
    let mut predecessors = vec![Vec::new(); function.blocks.len()];
    for block in &function.blocks {
        successors[block.id.0 as usize] = ssa_block_targets(block);
        for target in &successors[block.id.0 as usize] {
            predecessors[target.0 as usize].push(block.id);
        }
    }
    for values in &mut predecessors {
        values.sort();
        values.dedup();
    }
    Cfg {
        successors,
        predecessors,
    }
}

fn dominance_for_ssa(cfg: &Cfg, entry: BlockId) -> Dominance {
    Dominance::compute(cfg, entry)
}

fn reachable_ssa(function: &SsaFunction) -> Vec<bool> {
    let mut reachable = vec![false; function.blocks.len()];
    let mut queue = VecDeque::from([function.entry]);
    while let Some(block) = queue.pop_front() {
        if reachable[block.0 as usize] {
            continue;
        }
        reachable[block.0 as usize] = true;
        queue.extend(ssa_block_targets(&function.blocks[block.0 as usize]));
    }
    reachable
}

fn ssa_block_targets(block: &SsaBlock) -> Vec<BlockId> {
    let mut targets = ssa_targets(&block.terminator);
    targets.extend(
        block
            .instructions
            .iter()
            .filter_map(|instruction| instruction.unwind),
    );
    targets.sort();
    targets.dedup();
    targets
}

/// Recognize only the bounded indexed extraction diamond. The two outgoing
/// states join with the same initialized prefix; no arbitrary slot dataflow.
#[allow(clippy::too_many_lines)]
fn verify_swap_remove_protocol(
    function: &SsaFunction,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<BTreeSet<(BlockId, usize)>, Vec<Diagnostic>> {
    let mut covered = BTreeSet::new();
    let predecessors = |id| {
        function
            .blocks
            .iter()
            .filter(|b| ssa_targets(&b.terminator).contains(&id))
            .map(|b| b.id)
            .collect::<BTreeSet<_>>()
    };
    let value = |i: &SsaInstruction| -> Result<SsaOperand, Vec<Diagnostic>> {
        Ok(SsaOperand::Value(i.result))
    };
    for block in &function.blocks {
        let [tail, take, decision] = block.instructions.as_slice() else {
            continue;
        };
        let SsaOp::TailIndex { length: old_length } = &tail.op else {
            continue;
        };
        let SsaOp::Binary {
            op: BinaryOp::Equal,
            left: requested,
            right: compared_tail,
            trap: None,
            secondary_trap: None,
        } = &decision.op
        else {
            continue;
        };
        let SsaOp::Take { slot, state } = &take.op else {
            return Err(fail("invalid indexed transaction: missing Take".into()));
        };
        let tail_value = value(tail)?;
        if *compared_tail != tail_value
            || slot.index != *requested
            || *state != TakeState::INITIALIZED_TO_UNINITIALIZED
        {
            return Err(fail(
                "invalid indexed transaction: removed slot or tail identity".into(),
            ));
        }
        value(take)?;
        let SsaTerminator::Branch {
            condition,
            then_block,
            else_block,
        } = &block.terminator
        else {
            return Err(fail(
                "invalid indexed transaction: missing tail decision".into(),
            ));
        };
        if *condition != value(decision)? || then_block == else_block {
            return Err(fail("invalid indexed transaction: aliased paths".into()));
        }
        let tail_path = &function.blocks[then_block.0 as usize];
        let non_tail = &function.blocks[else_block.0 as usize];
        if !tail_path.instructions.is_empty()
            || predecessors(*then_block) != BTreeSet::from([block.id])
            || predecessors(*else_block) != BTreeSet::from([block.id])
        {
            return Err(fail(
                "invalid indexed transaction: relocation in tail path or foreign predecessor"
                    .into(),
            ));
        }
        let [transfer] = non_tail.instructions.as_slice() else {
            return Err(fail(
                "invalid indexed transaction: missing/double relocation".into(),
            ));
        };
        let SsaOp::Relocate {
            source,
            destination,
            relocation,
        } = &transfer.op
        else {
            return Err(fail(
                "invalid indexed transaction: missing relocation".into(),
            ));
        };
        if source.root != slot.root
            || source.type_id != slot.type_id
            || source.index != tail_value
            || destination != slot
            || *relocation != Relocate::single_slot(slot.type_id)
        {
            return Err(fail("invalid indexed transaction: relocation must initialize exactly the hole and end tail liveness".into()));
        }
        value(transfer)?;
        let SsaTerminator::Goto(commit_id) = &tail_path.terminator else {
            return Err(fail(
                "invalid indexed transaction: missing commit edge".into(),
            ));
        };
        if non_tail.terminator != SsaTerminator::Goto(*commit_id)
            || predecessors(*commit_id) != BTreeSet::from([*then_block, *else_block])
        {
            return Err(fail(
                "invalid indexed transaction: incomplete states at commit".into(),
            ));
        }
        let commit_block = &function.blocks[commit_id.0 as usize];
        let Some(commit) = commit_block.instructions.first() else {
            return Err(fail(
                "invalid indexed transaction: missing length commit".into(),
            ));
        };
        if !matches!(&commit.op, SsaOp::ListSetLength { source, length } if *source == slot.root && *length == tail_value)
        {
            return Err(fail(
                "invalid indexed transaction: hole or old tail within committed prefix".into(),
            ));
        }
        value(commit)?;
        let parents = predecessors(block.id);
        if parents.len() != 1 {
            return Err(fail(
                "invalid indexed transaction: missing unique bounds edge".into(),
            ));
        }
        let guard = &function.blocks[parents.first().unwrap().0 as usize];
        let SsaTerminator::Branch {
            condition,
            then_block: success,
            else_block: trap,
        } = &guard.terminator
        else {
            return Err(fail(
                "invalid indexed transaction: missing bounds guard".into(),
            ));
        };
        let trap_block = &function.blocks[trap.0 as usize];
        if *success != block.id
            || !trap_block.instructions.is_empty()
            || trap_block.terminator != SsaTerminator::Trap(TrapKind::IndexOutOfBounds)
        {
            return Err(fail(
                "invalid indexed transaction: bounds must trap before tail subtraction and Take"
                    .into(),
            ));
        }
        let [.., index, read, check] = guard.instructions.as_slice() else {
            return Err(fail(
                "invalid indexed transaction: missing fresh operands".into(),
            ));
        };
        if !matches!(index.op, SsaOp::Use(_))
            || value(index)? != *requested
            || !matches!(&read.op, SsaOp::ListLength { source } if *source == slot.root)
            || value(read)? != *old_length
            || value(check)? != *condition
            || !matches!(&check.op, SsaOp::Binary { op: BinaryOp::Less, left, right, trap: None, secondary_trap: None } if left == requested && right == old_length)
        {
            return Err(fail(
                "invalid indexed transaction: stale index/length/root in bounds check".into(),
            ));
        }
        if [block, tail_path, non_tail, commit_block]
            .iter()
            .any(|b| !b.phis.is_empty())
        {
            return Err(fail(
                "invalid indexed transaction: slot states cannot be merged by phi".into(),
            ));
        }
        covered.extend([
            (block.id, 0),
            (block.id, 1),
            (block.id, 2),
            (non_tail.id, 0),
            (*commit_id, 0),
        ]);
    }
    Ok(covered)
}

/// Prove the forward overlapping shift inductively on this layer's actual CFG.
/// Recognition is deliberately closed: no other effect or edge may observe a hole.
#[allow(clippy::too_many_lines)]
fn verify_remove_protocol(
    function: &SsaFunction,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<BTreeSet<(BlockId, usize)>, Vec<Diagnostic>> {
    let mut covered = BTreeSet::new();
    let predecessors = |id| {
        function
            .blocks
            .iter()
            .filter(|b| ssa_targets(&b.terminator).contains(&id))
            .map(|b| b.id)
            .collect::<BTreeSet<_>>()
    };
    let value = |i: &SsaInstruction| -> Result<SsaOperand, Vec<Diagnostic>> {
        Ok(SsaOperand::Value(i.result))
    };
    for block in &function.blocks {
        let [tail, take, seed] = block.instructions.as_slice() else {
            continue;
        };
        let SsaOp::TailIndex { length: old_length } = &tail.op else {
            continue;
        };
        let SsaOp::Use(requested) = &seed.op else {
            continue;
        };
        let SsaOp::Take { slot, state } = &take.op else {
            return Err(fail("invalid remove transaction: missing Take".into()));
        };
        let tail_value = value(tail)?;
        value(take)?;
        if !slot.root.projections.is_empty()
            || slot.index != *requested
            || *state != TakeState::INITIALIZED_TO_UNINITIALIZED
        {
            return Err(fail(
                "invalid remove transaction: Take must create the initial hole".into(),
            ));
        }
        let SsaTerminator::Goto(header_id) = &block.terminator else {
            return Err(fail(
                "invalid remove transaction: missing loop entry".into(),
            ));
        };
        let header = &function.blocks[header_id.0 as usize];
        let [test] = header.instructions.as_slice() else {
            return Err(fail(
                "invalid remove transaction: observable effect in hole header".into(),
            ));
        };
        let SsaTerminator::Branch {
            condition,
            then_block: body_id,
            else_block: commit_id,
        } = &header.terminator
        else {
            return Err(fail(
                "invalid remove transaction: missing bounded forward loop".into(),
            ));
        };
        let body = &function.blocks[body_id.0 as usize];
        let [next, transfer, update] = body.instructions.as_slice() else {
            return Err(fail(
                "invalid remove transaction: missing/duplicate relocation or effect in loop".into(),
            ));
        };
        let [phi] = header.phis.as_slice() else {
            return Err(fail(
                "invalid remove transaction: expected only hole phi".into(),
            ));
        };
        let hole = SsaOperand::Value(phi.result);
        if phi.ty != TypeId::USIZE
            || phi.incoming.len() != 2
            || !phi.incoming.contains(&(block.id, seed.result))
            || !phi.incoming.contains(&(*body_id, update.result))
            || [block, body, &function.blocks[commit_id.0 as usize]]
                .iter()
                .any(|b| !b.phis.is_empty())
        {
            return Err(fail(
                "invalid remove transaction: phi must merge only initial hole and exact successor"
                    .into(),
            ));
        }
        if !matches!(&test.op, SsaOp::Binary { op: BinaryOp::Less, left, right, trap: None, secondary_trap: None } if *left == hole && *right == tail_value)
            || *condition != value(test)?
            || !matches!(&next.op, SsaOp::HoleNext { hole: h } if *h == hole)
            || !matches!(&update.op, SsaOp::Use(v) if *v == value(next)?)
            || body.terminator != SsaTerminator::Goto(*header_id)
            || predecessors(*header_id) != BTreeSet::from([block.id, *body_id])
            || predecessors(*body_id) != BTreeSet::from([*header_id])
            || predecessors(*commit_id) != BTreeSet::from([*header_id])
        {
            return Err(fail(
                "invalid remove transaction: hole successor, loop bound, update or exit".into(),
            ));
        }
        let SsaOp::Relocate {
            source,
            destination,
            relocation,
        } = &transfer.op
        else {
            return Err(fail(
                "invalid remove transaction: missing forward Relocate".into(),
            ));
        };
        if source.root != slot.root
            || destination.root != slot.root
            || source.type_id != slot.type_id
            || destination.type_id != slot.type_id
            || source.index != value(next)?
            || destination.index != hole
            || *relocation != Relocate::single_slot(slot.type_id)
        {
            return Err(fail(
                "invalid remove transaction: require initialized hole+1 -> raw hole, forward only"
                    .into(),
            ));
        }
        value(transfer)?;
        // Base: Take made i raw. Step: h+1 -> h makes precisely h+1 raw.
        // h < tail authorizes h+1 <= tail without overflow. The sole exit h >= tail
        // therefore has h == tail and [0,tail) initialized; no bitmap is needed.
        let commit_block = &function.blocks[commit_id.0 as usize];
        let Some(commit) = commit_block.instructions.first() else {
            return Err(fail(
                "invalid remove transaction: missing prefix commit".into(),
            ));
        };
        if !matches!(&commit.op, SsaOp::ListSetLength { source, length } if *source == slot.root && *length == tail_value)
        {
            return Err(fail(
                "invalid remove transaction: commit before hole reaches old tail or wrong length"
                    .into(),
            ));
        }
        value(commit)?;
        let parents = predecessors(block.id);
        if parents.len() != 1 {
            return Err(fail(
                "invalid remove transaction: missing unique bounds edge".into(),
            ));
        }
        let guard = &function.blocks[parents.first().unwrap().0 as usize];
        let SsaTerminator::Branch {
            condition,
            then_block: success,
            else_block: trap,
        } = &guard.terminator
        else {
            return Err(fail(
                "invalid remove transaction: missing bounds guard".into(),
            ));
        };
        let trap_block = &function.blocks[trap.0 as usize];
        if *success != block.id
            || !trap_block.instructions.is_empty()
            || trap_block.terminator != SsaTerminator::Trap(TrapKind::IndexOutOfBounds)
        {
            return Err(fail(
                "invalid remove transaction: bounds must trap before tail subtraction and Take"
                    .into(),
            ));
        }
        let [.., index, read, check] = guard.instructions.as_slice() else {
            return Err(fail(
                "invalid remove transaction: missing fresh operands".into(),
            ));
        };
        if !matches!(index.op, SsaOp::Use(_))
            || value(index)? != *requested
            || !matches!(&read.op, SsaOp::ListLength { source } if *source == slot.root)
            || value(read)? != *old_length
            || value(check)? != *condition
            || !matches!(&check.op, SsaOp::Binary { op: BinaryOp::Less, left, right, trap: None, secondary_trap: None } if left == requested && right == old_length)
        {
            return Err(fail(
                "invalid remove transaction: stale index/length/root in bounds check".into(),
            ));
        }
        covered.extend([
            (block.id, 0),
            (block.id, 1),
            (block.id, 2),
            (header.id, 0),
            (body.id, 0),
            (body.id, 1),
            (body.id, 2),
            (*commit_id, 0),
        ]);
    }
    Ok(covered)
}

/// Transpose consumes a materialized owner and produces a materialized owner.
/// Both temporaries must transfer exactly once before any phi; ordinary root
/// Move operations retain the existing conditional cleanup representation.
fn verify_vector_transpose_ownership(
    function: &SsaFunction,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    let mut owners = BTreeSet::new();
    for instruction in function.blocks.iter().flat_map(|b| &b.instructions) {
        let SsaOp::VectorTransposeMove { operand, .. } = &instruction.op else {
            continue;
        };
        let SsaOperand::Value(source) = operand else {
            return Err(fail("SSA Vector transpose source is not an owner".into()));
        };
        owners.extend([*source, instruction.result]);
    }
    if owners.is_empty() {
        return Ok(());
    }
    // Count once over the function, not once per transpose. SSA builder always
    // materializes these temporary transfers before root assignment/phis.
    let mut uses = BTreeMap::<ValueId, usize>::new();
    for block in &function.blocks {
        for instruction in &block.instructions {
            for operand in op_operands(&instruction.op) {
                if let SsaOperand::Value(value) = operand
                    && owners.contains(value)
                {
                    *uses.entry(*value).or_default() += 1;
                }
            }
        }
        if let SsaTerminator::Return(SsaOperand::Value(value)) = &block.terminator
            && owners.contains(value)
        {
            *uses.entry(*value).or_default() += 1;
        }
        if block
            .phis
            .iter()
            .any(|p| p.incoming.iter().any(|(_, v)| owners.contains(v)))
        {
            return Err(fail(
                "SSA Vector transpose owner must transfer before a phi".into(),
            ));
        }
    }
    if owners.iter().any(|owner| uses.get(owner) != Some(&1)) {
        return Err(fail(
            "SSA Vector transpose owner must transfer exactly once".into(),
        ));
    }
    Ok(())
}

fn verify_matrix_literal_ownership(
    function: &SsaFunction,
    types: &TypeArena,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    let mut owners = BTreeSet::new();
    for instruction in function.blocks.iter().flat_map(|b| &b.instructions) {
        let SsaOp::MatrixInit {
            elements,
            element_type,
            ..
        } = &instruction.op
        else {
            continue;
        };
        owners.insert(instruction.result);
        if !types.is_copy(*element_type) {
            for element in elements {
                let SsaOperand::Value(source) = element else {
                    return Err(fail(
                        "SSA Matrix element must be a materialized owner".into(),
                    ));
                };
                owners.insert(*source);
            }
        }
    }
    if owners.is_empty() {
        return Ok(());
    }
    // Count once over the function, not once per transpose. SSA builder always
    // materializes these temporary transfers before root assignment/phis.
    let mut uses = BTreeMap::<ValueId, usize>::new();
    for block in &function.blocks {
        for instruction in &block.instructions {
            for operand in op_operands(&instruction.op) {
                if let SsaOperand::Value(value) = operand
                    && owners.contains(value)
                {
                    *uses.entry(*value).or_default() += 1;
                }
            }
        }
        if let SsaTerminator::Return(SsaOperand::Value(value)) = &block.terminator
            && owners.contains(value)
        {
            *uses.entry(*value).or_default() += 1;
        }
        if block
            .phis
            .iter()
            .any(|p| p.incoming.iter().any(|(_, v)| owners.contains(v)))
        {
            return Err(fail(
                "SSA Matrix literal owner must transfer before a phi".into(),
            ));
        }
    }
    if owners.iter().any(|owner| uses.get(owner) != Some(&1)) {
        return Err(fail(
            "SSA Matrix literal owner must transfer exactly once".into(),
        ));
    }
    Ok(())
}

/// Validate the initialized-prefix transaction on the actual CFG. Every Take
/// must be the single extraction between a fresh nonempty check and an
/// immediate boundary commit. No slot handle can escape this three-op region.
#[allow(clippy::too_many_lines)]
fn verify_take_protocol(
    function: &SsaFunction,
    types: &TypeArena,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    let mut indexed = verify_swap_remove_protocol(function, fail)?;
    indexed.extend(verify_remove_protocol(function, fail)?);
    // Check extracted ownership directly in SSA, including the indexed diamond.
    for take in function.blocks.iter().flat_map(|b| &b.instructions) {
        if let SsaOp::Take { slot, .. } = &take.op {
            if types.is_copy(slot.type_id) {
                continue;
            }
            let value = SsaOperand::Value(take.result);
            let mut uses = 0;
            for b in &function.blocks {
                for i in &b.instructions {
                    uses += op_operands(&i.op).iter().filter(|v| ***v == value).count();
                }
                if matches!(&b.terminator, SsaTerminator::Return(v) if *v == value) {
                    uses += 1;
                }
                if b.phis
                    .iter()
                    .any(|p| p.incoming.iter().any(|(_, v)| *v == take.result))
                {
                    return Err(fail(
                        "invalid Take: extracted temporary must transfer before a phi".into(),
                    ));
                }
            }
            if uses != 1 {
                return Err(fail(
                    "invalid Take: extracted owner must transfer exactly once".into(),
                ));
            }
        }
    }
    for block in &function.blocks {
        for (position, instruction) in block.instructions.iter().enumerate() {
            if indexed.contains(&(block.id, position)) {
                continue;
            }
            match &instruction.op {
                SsaOp::HoleNext { .. } | SsaOp::Relocate { .. } => {
                    return Err(fail("Relocate outside verified slot transaction".into()));
                }
                SsaOp::TailIndex { .. } if position != 0 => {
                    return Err(fail(
                        "invalid Take: tail selection outside checked transaction".into(),
                    ));
                }
                SsaOp::Take { .. } if position != 1 => {
                    return Err(fail(
                        "invalid Take: uninitialized/stale slot or double Take".into(),
                    ));
                }
                SsaOp::ListSetLength { .. } if position != 2 => {
                    return Err(fail(
                        "invalid Take: unpaired initialized-prefix commit".into(),
                    ));
                }
                SsaOp::TailIndex { .. } | SsaOp::Take { .. } | SsaOp::ListSetLength { .. } => {}
                _ => continue,
            }
            let [tail, take, commit, ..] = block.instructions.as_slice() else {
                return Err(fail(
                    "invalid Take: missing initialization transition or length commit".into(),
                ));
            };
            let SsaOp::TailIndex { length: old_length } = &tail.op else {
                return Err(fail("invalid Take: no tail authority".into()));
            };
            let SsaOp::Take { slot, state } = &take.op else {
                return Err(fail(
                    "invalid Take: tail must be extracted exactly once".into(),
                ));
            };
            let SsaOp::ListSetLength { source, length } = &commit.op else {
                return Err(fail(
                    "invalid Take: length still includes uninitialized tail".into(),
                ));
            };
            if slot.root != *source
                || slot.index != SsaOperand::Value(tail.result)
                || *length != slot.index
                || *state != TakeState::INITIALIZED_TO_UNINITIALIZED
            {
                return Err(fail(
                    "invalid Take: stale slot, initialization transition or prefix boundary".into(),
                ));
            }
            let predecessors = function
                .blocks
                .iter()
                .filter(|candidate| ssa_targets(&candidate.terminator).contains(&block.id))
                .collect::<Vec<_>>();
            let [guard] = predecessors.as_slice() else {
                return Err(fail(
                    "invalid Take: slot lacks a unique nonempty edge".into(),
                ));
            };
            let SsaTerminator::Branch {
                condition,
                then_block,
                else_block,
            } = &guard.terminator
            else {
                return Err(fail("invalid Take: missing empty check".into()));
            };
            if *then_block != block.id
                || !matches!(
                    &function.blocks[else_block.0 as usize].terminator,
                    SsaTerminator::Trap(TrapKind::ListEmpty)
                )
                || !function.blocks[else_block.0 as usize]
                    .instructions
                    .is_empty()
            {
                return Err(fail(
                    "invalid Take: empty path must trap before storage changes".into(),
                ));
            }
            let [.., read, check] = guard.instructions.as_slice() else {
                return Err(fail("invalid Take: missing length check".into()));
            };
            if !matches!(&read.op, SsaOp::ListLength { source: root } if root == source)
                || SsaOperand::Value(read.result) != *old_length
                || SsaOperand::Value(check.result) != *condition
                || !matches!(&check.op, SsaOp::Binary { op: BinaryOp::NotEqual, left, right: SsaOperand::Int { value: 0, ty: TypeId::USIZE }, trap: None, secondary_trap: None } if left == old_length)
            {
                return Err(fail(
                    "invalid Take: check must use the fresh owning descriptor length".into(),
                ));
            }
            if !block.phis.is_empty() {
                return Err(fail(
                    "invalid Take: transaction cannot merge storage states".into(),
                ));
            }
        }
    }
    Ok(())
}

fn valid_matrix_literal_shape(rows: u64, columns: u64, row_ends: &[u64], count: usize) -> bool {
    rows.checked_mul(columns) == u64::try_from(count).ok()
        && (rows == 0) == (columns == 0)
        && u64::try_from(row_ends.len()).ok() == Some(rows)
        && row_ends
            .iter()
            .enumerate()
            .all(|(i, end)| (i as u64 + 1).checked_mul(columns) == Some(*end))
}

#[cfg(test)]
mod tests {
    use aether_frontend::{SourceFile, analyze, parse_source};

    use crate::{lower_hir, verify_mir};

    use super::*;

    fn raw_ssa(text: &str) -> SsaIr {
        let hir = analyze(parse_source(&SourceFile::new("test.ae", text)).unwrap()).unwrap();
        build_ssa(&verify_mir(lower_hir(hir)).unwrap())
    }

    #[test]
    fn loop_and_branch_receive_coherent_phis() {
        let ssa = raw_ssa(
            "int main(){int i=0;int x=0;while(i<4){if(i==2){x=x+3;}else{x=x+1;}i=i+1;}return x;}",
        );
        assert!(
            ssa.functions[0]
                .blocks
                .iter()
                .any(|block| !block.phis.is_empty())
        );
        verify_ssa(ssa).unwrap();
    }

    #[test]
    fn verifier_rejects_phi_edge_and_dominance_corruption() {
        let mut phi_bad = raw_ssa("int main(){int i=0;while(i<2){i=i+1;}return i;}");
        let phi = phi_bad.functions[0]
            .blocks
            .iter_mut()
            .find_map(|block| block.phis.first_mut())
            .unwrap();
        phi.incoming.pop();
        assert!(verify_ssa(phi_bad).is_err());

        let mut phi_type_bad = raw_ssa("int main(){int i=0;while(i<2){i=i+1;}return i;}");
        let phi = phi_type_bad.functions[0]
            .blocks
            .iter_mut()
            .find_map(|block| block.phis.first_mut())
            .unwrap();
        phi.ty = TypeId::UINT64;
        assert!(verify_ssa(phi_type_bad).is_err());

        let mut use_bad = raw_ssa("int main(){int x=1;return x;}");
        if let SsaTerminator::Return(value) = &mut use_bad.functions[0].blocks[0].terminator {
            *value = SsaOperand::Value(ValueId(999));
        }
        assert!(verify_ssa(use_bad).is_err());
    }

    #[test]
    fn verifier_rejects_duplicate_definition() {
        let mut ssa = raw_ssa("int main(){int x=1;return x;}");
        let duplicate = ssa.functions[0].blocks[0].instructions[0].clone();
        ssa.functions[0].blocks[0].instructions.push(duplicate);
        assert!(verify_ssa(ssa).is_err());
    }

    #[test]
    fn conditional_drop_flag_ssa_is_connected_to_cleanup_branch() {
        let source = "int take(Buffer<int> value){return value[0];}int main(){Buffer<int> value=Buffer<int>(1,0);if(true){int used=take(value);}return 0;}";
        let ssa = raw_ssa(source);
        assert_eq!(ssa.functions[1].drop_flags.len(), 1);
        verify_ssa(ssa.clone()).unwrap();

        let mut disconnected = ssa;
        let flag = disconnected.functions[1].drop_flags[0].flag;
        let phi_values = disconnected.functions[1]
            .blocks
            .iter()
            .flat_map(|block| &block.phis)
            .filter(|phi| phi.local == flag)
            .map(|phi| phi.result)
            .collect::<BTreeSet<_>>();
        let branch = disconnected.functions[1]
            .blocks
            .iter_mut()
            .find(|block| {
                matches!(
                    block.terminator,
                    SsaTerminator::Branch {
                        condition: SsaOperand::Value(value),
                        ..
                    } if phi_values.contains(&value)
                )
            })
            .unwrap();
        if let SsaTerminator::Branch { condition, .. } = &mut branch.terminator {
            *condition = SsaOperand::Bool(false);
        }
        assert!(verify_ssa(disconnected).is_err());
    }

    #[test]
    fn verifier_rejects_invalid_type_identity() {
        let mut ssa = raw_ssa("int main(){return 0;}");
        ssa.functions[0].blocks[0].terminator = SsaTerminator::Return(SsaOperand::Int {
            value: 0,
            ty: TypeId(u32::MAX),
        });
        assert!(verify_ssa(ssa).is_err());
    }

    #[test]
    fn parameters_seed_function_local_ssa_and_calls_keep_identity() {
        let ssa = raw_ssa("int add(int a,int b){return a+b;}int main(){return add(20,22);}");
        assert_eq!(ssa.functions[0].parameters.len(), 2);
        assert_eq!(ssa.functions[0].parameters[0].value, ValueId(0));
        assert!(
            ssa.functions[1]
                .blocks
                .iter()
                .flat_map(|block| &block.instructions)
                .any(|instruction| matches!(
                    instruction.op,
                    SsaOp::Call {
                        callee: InstanceId(0),
                        ..
                    }
                ))
        );
        verify_ssa(ssa).unwrap();
    }

    #[test]
    fn verifier_rejects_corrupt_ssa_call_contract() {
        let mut ssa = raw_ssa(
            "bool yes(bool value){return value;}int main(){if(yes(true)){return 1;}return 0;}",
        );
        let call = ssa.functions[1]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.op, SsaOp::Call { .. }))
            .unwrap();
        if let SsaOp::Call { args, .. } = &mut call.op {
            args[0] = SsaOperand::Int {
                value: 1,
                ty: TypeId::INT64,
            };
        }
        assert!(verify_ssa(ssa).is_err());
    }

    #[test]
    fn enum_ssa_switch_and_payload_contracts_are_verified() {
        let source =
            "enum E{A,B(int),}int main(){E e=E.B(7);match(e){E.A=>{return 0;}E.B(x)=>{return x;}}}";
        let raw = raw_ssa(source);
        assert!(
            raw.functions[0]
                .blocks
                .iter()
                .any(|block| matches!(block.terminator, SsaTerminator::Switch { .. }))
        );
        verify_ssa(raw).unwrap();

        let mut bad = raw_ssa(source);
        let extraction = bad.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.op, SsaOp::EnumPayload { .. }))
            .unwrap();
        if let SsaOp::EnumPayload { variant_id, .. } = &mut extraction.op {
            *variant_id = VariantId {
                enum_id: EnumId(0),
                index: 99,
            };
        }
        assert!(verify_ssa(bad).is_err());
    }

    #[test]
    fn verifier_rejects_corrupt_ssa_cast_and_division_contracts() {
        let mut cast =
            raw_ssa("int8 narrow(int64 x){return int8(x);}int main(){return narrow(1);}");
        let instruction = cast.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.op, SsaOp::Cast { .. }))
            .unwrap();
        if let SsaOp::Cast { trap, .. } = &mut instruction.op {
            *trap = None;
        }
        assert!(verify_ssa(cast).is_err());

        let mut division =
            raw_ssa("int64 divide(int64 a,int64 b){return a/b;}int main(){return divide(4,2);}");
        let instruction = division.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.op, SsaOp::Binary { .. }))
            .unwrap();
        if let SsaOp::Binary { secondary_trap, .. } = &mut instruction.op {
            *secondary_trap = None;
        }
        assert!(verify_ssa(division).is_err());
    }

    #[test]
    fn verifier_rejects_corrupt_aggregate_projection() {
        let mut ssa = raw_ssa(
            "struct Inner{int x;}struct Outer{Inner inner;}int main(){Outer o=Outer(Inner(1));o.inner.x=2;return o.inner.x;}",
        );
        let insertion = ssa.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.op, SsaOp::InsertField { .. }))
            .unwrap();
        if let SsaOp::InsertField { projections, .. } = &mut insertion.op {
            projections.reverse();
        }
        assert!(verify_ssa(ssa).is_err());
    }

    #[test]
    fn verifier_rejects_corrupt_list_relocation_contract() {
        let mut ssa = raw_ssa(
            "int main(){List<Buffer<int>> values={Buffer<int>(1,1)};push(values,Buffer<int>(1,2));return values[1][0]-2;}",
        );
        let relocation = ssa.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find_map(|instruction| match &mut instruction.op {
                SsaOp::ListPush { relocation, .. } => Some(relocation),
                _ => None,
            })
            .unwrap();
        relocation.increasing_order = false;
        assert!(verify_ssa(ssa).is_err());
    }
}
