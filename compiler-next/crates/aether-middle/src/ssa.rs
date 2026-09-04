//! MIR-to-SSA promotion, phi construction, dominance and verification.
#![allow(missing_docs)]

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fmt::Write;
use std::sync::Arc;

use aether_frontend::{
    CastKind, CoercionKind, Diagnostic, DiagnosticCategory, EnumId, EnumInfo, FieldId, FloatValue,
    FunctionInstanceInfo, InstanceId, LocalId, MatchMode, ModuleInfo, Phase, Span, StructId,
    StructInfo, StructuralMutation, Substitution, TypeArena, TypeData, TypeId, VariantId,
    format_type,
};

use crate::mir::place_type;
use crate::{
    BinaryOp, BlockId, MirDropFlag, MirFunction, Operand, Place, PlaceBase, PlaceProjection,
    Rvalue, Terminator, TrapKind, UnaryOp, VerifiedMir,
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
        element_type: TypeId,
        bounds_trap: TrapKind,
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
    ListPush {
        source: SsaPlace,
        value: SsaOperand,
        mutation: StructuralMutation,
        size_trap: TrapKind,
        failure_trap: TrapKind,
    },
    ListReserve {
        source: SsaPlace,
        requested_capacity: SsaOperand,
        mutation: StructuralMutation,
        size_trap: TrapKind,
        failure_trap: TrapKind,
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
}

/// Raw SSA function.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SsaFunction {
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
        id: function.id,
        function_id: function.function_id,
        parameters,
        memory_locals,
        drop_flags: function.drop_flags.clone(),
        return_type: function.return_type,
        entry: function.entry,
        blocks,
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
        Rvalue::ListPush {
            source,
            value,
            mutation,
            size_trap,
            failure_trap,
        } => SsaOp::ListPush {
            source: rename_place(source, stacks, mir),
            value: rename_operand(value, stacks),
            mutation: *mutation,
            size_trap: *size_trap,
            failure_trap: *failure_trap,
        },
        Rvalue::ListReserve {
            source,
            requested_capacity,
            mutation,
            size_trap,
            failure_trap,
        } => SsaOp::ListReserve {
            source: rename_place(source, stacks, mir),
            requested_capacity: rename_operand(requested_capacity, stacks),
            mutation: *mutation,
            size_trap: *size_trap,
            failure_trap: *failure_trap,
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
                    element_type,
                    bounds_trap,
                } => SsaPlaceProjection::Index {
                    index: rename_operand(index, stacks),
                    element_type: *element_type,
                    bounds_trap: *bounds_trap,
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
            let targets = mir_targets(block.terminator.as_ref().expect("verified MIR"));
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

fn rvalue_locals(function: &MirFunction, value: &Rvalue) -> Vec<LocalId> {
    match value {
        Rvalue::Use(operand)
        | Rvalue::Coerce { operand, .. }
        | Rvalue::Cast { operand, .. }
        | Rvalue::Unary { operand, .. } => operand_local(operand).into_iter().collect(),
        Rvalue::Load(place)
        | Rvalue::Borrow { place, .. }
        | Rvalue::Move { source: place }
        | Rvalue::Drop { owner: place }
        | Rvalue::ConsumeEnum { owner: place }
        | Rvalue::View { source: place, .. }
        | Rvalue::ArrayLength { source: place }
        | Rvalue::ListLength { source: place }
        | Rvalue::ListCapacity { source: place } => place_locals(function, place),
        Rvalue::BufferAlloc {
            length, initial, ..
        }
        | Rvalue::ArrayFill {
            length, initial, ..
        } => operand_local(length)
            .into_iter()
            .chain(operand_local(initial))
            .collect(),
        Rvalue::ArrayInit { elements, .. } | Rvalue::ListInit { elements, .. } => {
            elements.iter().filter_map(operand_local).collect()
        }
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
        Rvalue::Binary { left, right, .. } => operand_local(left)
            .into_iter()
            .chain(operand_local(right))
            .collect(),
        Rvalue::Call { args, .. } => args.iter().filter_map(operand_local).collect(),
    }
}

fn place_locals(function: &MirFunction, place: &Place) -> Vec<LocalId> {
    let mut locals = match &place.base {
        PlaceBase::Local(local) if !function.locals[local.0 as usize].address_taken => vec![*local],
        PlaceBase::Local(_) => Vec::new(),
        PlaceBase::Dereference { reference, .. } => operand_local(reference).into_iter().collect(),
    };
    locals.extend(
        place
            .projections
            .iter()
            .filter_map(|projection| match projection {
                PlaceProjection::Index { index, .. } => operand_local(index),
                PlaceProjection::Field(_) => None,
            }),
    );
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
        Terminator::Goto(_) | Terminator::Trap(_) => vec![],
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
    if ssa.types.entries().any(|(_, data)| match data {
        TypeData::Buffer { element } | TypeData::View { element, .. } => {
            !ssa.types.is_admitted_buffer_element(*element)
        }
        TypeData::Array { element } => !ssa.types.is_admitted_array_element(*element),
        TypeData::List { element } => !ssa.types.is_admitted_list_element(*element),
        _ => false,
    }) {
        return Err(fail(
            "SSA contains a Buffer/View/Array/List with an inadmissible element type".into(),
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
    for (index, block) in function.blocks.iter().enumerate() {
        if block.id.0 as usize != index {
            return Err(fail("SSA block identity is not canonical".into()));
        }
        for target in ssa_targets(&block.terminator) {
            if target.0 as usize >= function.blocks.len() {
                return Err(fail(format!("SSA target {target:?} does not exist")));
            }
        }
    }
    let cfg = ssa_cfg(function);
    if reachable_ssa(function).iter().any(|value| !value) {
        return Err(fail("SSA contains unreachable blocks".into()));
    }
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
        if phi_results.is_empty()
            || !function.blocks.iter().any(|block| {
                matches!(
                    &block.terminator,
                    SsaTerminator::Branch {
                        condition: SsaOperand::Value(value),
                        ..
                    } if phi_results.contains(value)
                )
            })
        {
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
            SsaTerminator::Goto(_) | SsaTerminator::Trap(_) => {}
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
    match op {
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
                .and_then(|ty| types.view_info(ty))
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
            if *mutable
                && matches!(
                    &place.base,
                    SsaPlaceBase::Dereference { mutable: false, .. }
                )
            {
                return Err("SSA mutable borrow through shared reference".into());
            }
        }
        SsaOp::Move { source } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            if source_ty != result || types.is_copy(source_ty) || !source.projections.is_empty() {
                return Err("SSA Move contract invalid".into());
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
                || *size_trap != TrapKind::AllocationSizeOverflow
                || *failure_trap != TrapKind::AllocationFailure
            {
                return Err("SSA Array fill allocation contract invalid".into());
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
        SsaOp::ListPush {
            source,
            value,
            mutation,
            size_trap,
            failure_trap,
        } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            if result != source_ty
                || types.list_element(source_ty) != Some(operand_ty(value)?)
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
            size_trap,
            failure_trap,
        } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            if result != source_ty
                || types.list_element(source_ty).is_none()
                || operand_ty(requested_capacity)? != TypeId::USIZE
                || *mutation != StructuralMutation::Reserve
                || *size_trap != TrapKind::AllocationSizeOverflow
                || *failure_trap != TrapKind::AllocationFailure
            {
                return Err("SSA List reserve contract invalid".into());
            }
        }
        SsaOp::View { source, mutable } => {
            let source_ty = ssa_place_type(source, memory_locals, structs, types, operand_ty)?;
            let element = types
                .owning_contiguous_element(source_ty)
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
    }
    Ok(())
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
                element_type,
                bounds_trap,
            } => {
                let element = types
                    .buffer_element(ty)
                    .or_else(|| types.array_element(ty))
                    .or_else(|| types.list_element(ty))
                    .or_else(|| types.view_info(ty).map(|(element, _)| element))
                    .ok_or_else(|| "SSA index projection has non-contiguous base".to_string())?;
                if operand_ty(index)? != TypeId::USIZE
                    || element != *element_type
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
        SsaOp::Use(value)
        | SsaOp::Coerce { operand: value, .. }
        | SsaOp::Cast { operand: value, .. }
        | SsaOp::EnumDiscriminant { value, .. }
        | SsaOp::EnumPayload { value, .. } => vec![value],
        SsaOp::Load { place }
        | SsaOp::Borrow { place, .. }
        | SsaOp::Move { source: place }
        | SsaOp::Drop { owner: place }
        | SsaOp::ConsumeEnum { owner: place }
        | SsaOp::View { source: place, .. }
        | SsaOp::ArrayLength { source: place }
        | SsaOp::ListLength { source: place }
        | SsaOp::ListCapacity { source: place } => place_operands(place),
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
        SsaOp::ArrayInit { elements, .. } | SsaOp::ListInit { elements, .. } => {
            elements.iter().collect()
        }
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
        SsaOp::Binary { left, right, .. } => vec![left, right],
        SsaOp::Call { args, .. } => args.iter().collect(),
    }
}

fn place_operands(place: &SsaPlace) -> Vec<&SsaOperand> {
    let mut operands = match &place.base {
        SsaPlaceBase::MemoryLocal(_) => Vec::new(),
        SsaPlaceBase::Dereference { reference, .. } | SsaPlaceBase::Value(reference) => {
            vec![reference]
        }
    };
    operands.extend(
        place
            .projections
            .iter()
            .filter_map(|projection| match projection {
                SsaPlaceProjection::Index { index, .. } => Some(index),
                SsaPlaceProjection::Field(_) => None,
            }),
    );
    operands
}

fn mir_targets(terminator: &Terminator) -> Vec<BlockId> {
    match terminator {
        Terminator::Goto(target) => vec![*target],
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
        Terminator::Return(_) | Terminator::Trap(_) => vec![],
    }
}

fn ssa_targets(terminator: &SsaTerminator) -> Vec<BlockId> {
    match terminator {
        SsaTerminator::Goto(target) => vec![*target],
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
        SsaTerminator::Return(_) | SsaTerminator::Trap(_) => vec![],
    }
}

fn ssa_cfg(function: &SsaFunction) -> Cfg {
    let mut successors = vec![Vec::new(); function.blocks.len()];
    let mut predecessors = vec![Vec::new(); function.blocks.len()];
    for block in &function.blocks {
        successors[block.id.0 as usize] = ssa_targets(&block.terminator);
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
        queue.extend(ssa_targets(&function.blocks[block.0 as usize].terminator));
    }
    reachable
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
}
