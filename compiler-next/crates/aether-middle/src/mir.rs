//! Explicit control-flow MIR and fail-closed verification.
#![allow(missing_docs)]

use std::collections::{BTreeSet, VecDeque};
use std::fmt::Write;
use std::sync::Arc;

use aether_frontend::{
    CastKind, CoercionKind, Diagnostic, DiagnosticCategory, EnumId, EnumInfo, FieldId, FloatValue,
    FunctionInstanceInfo, HirBinaryOp, HirBlock, HirCallTarget, HirDrop, HirExpr, HirExprKind,
    HirFunction, HirMatchArm, HirPlace, HirPlaceBase, HirPlaceProjection, HirStmtKind, HirUnaryOp,
    InstanceId, LocalId, MatchMode, ModuleInfo, Phase, Span, StructId, StructInfo, Substitution,
    TypeArena, TypeData, TypeId, TypedHir, VariantId, format_type,
};

/// Basic-block identity, equal to its stable vector index.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct BlockId(pub u32);

/// A MIR storage slot or compiler temporary.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MirLocal {
    /// Stable identity.
    pub id: LocalId,
    /// Canonical type.
    pub ty: TypeId,
    /// Source name when this is user storage.
    pub name: Option<String>,
    /// Whether lowering introduced the slot.
    pub temporary: bool,
    /// Stable memory is required because this local is borrowed.
    pub address_taken: bool,
}

/// A parameter's local storage identity and type.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MirParameter {
    /// Function-local identity initialized by the call boundary.
    pub local: LocalId,
    /// Canonical semantic type.
    pub ty: TypeId,
}

/// One compiler-generated root-level conditional ownership flag.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MirDropFlag {
    pub owner: LocalId,
    pub flag: LocalId,
}

/// Reusable assignable storage path. Future projections can add indexing and
/// dereference without changing assignment into a special-case operation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Place {
    pub base: PlaceBase,
    pub projections: Vec<PlaceProjection>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PlaceProjection {
    Field(FieldId),
    Index {
        index: Operand,
        element_type: TypeId,
        bounds_trap: TrapKind,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PlaceBase {
    Local(LocalId),
    Dereference { reference: Operand, mutable: bool },
}

/// MIR operand for scalar or aggregate values.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Operand {
    /// Storage read.
    Local(LocalId),
    /// Signed 64-bit constant.
    Int { value: i128, ty: TypeId },
    /// IEEE literal bits and exact canonical type.
    Float { value: FloatValue, ty: TypeId },
    /// Logical constant.
    Bool(bool),
}

/// Non-recoverable structured runtime failures.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TrapKind {
    /// Checked arithmetic overflow.
    IntegerOverflow,
    /// Integer division or remainder by zero.
    DivisionByZero,
    /// A checked value conversion cannot represent its result.
    ConversionOutOfRange,
    /// Signed `MIN / -1` cannot be represented.
    DivisionOverflow,
    AllocationSizeOverflow,
    AllocationFailure,
    IndexOutOfBounds,
}

/// Explicit scalar unary operations.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UnaryOp {
    /// Checked signed negation.
    NegateIntegerChecked,
    /// IEEE floating negation.
    NegateFloat,
}

/// Explicit scalar binary operations.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BinaryOp {
    /// Checked signed addition.
    AddIntegerChecked,
    /// Checked signed subtraction.
    SubtractIntegerChecked,
    /// Checked signed multiplication.
    MultiplyIntegerChecked,
    DivideIntegerSignedChecked,
    DivideIntegerUnsignedChecked,
    RemainderIntegerSignedChecked,
    RemainderIntegerUnsignedChecked,
    /// IEEE floating operations.
    AddFloat,
    SubtractFloat,
    MultiplyFloat,
    DivideFloat,
    /// Signed comparison.
    Less,
    /// Signed comparison.
    LessEqual,
    /// Signed comparison.
    Greater,
    /// Signed comparison.
    GreaterEqual,
    /// Same-type equality.
    Equal,
    /// Same-type inequality.
    NotEqual,
}

/// Right-hand side of a MIR assignment.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum Rvalue {
    /// Scalar copy.
    Use(Operand),
    /// Read a local or nested subobject place.
    Load(Place),
    /// Create an explicit typed non-owning view of stable storage.
    Borrow {
        place: Place,
        mutable: bool,
    },
    /// Transfer one move-only owner out of an existing place.
    Move {
        source: Place,
    },
    /// Destroy one currently owned value. The boolean result is an internal
    /// sequencing token used by the assignment-shaped bootstrap MIR.
    Drop {
        owner: Place,
    },
    BufferAlloc {
        element_type: TypeId,
        length: Operand,
        initial: Operand,
        size_trap: TrapKind,
        failure_trap: TrapKind,
    },
    View {
        source: Place,
        mutable: bool,
    },
    /// Construct a nominal aggregate in declaration/FieldId order.
    Aggregate {
        struct_id: StructId,
        fields: Vec<(FieldId, Operand)>,
    },
    EnumConstruct {
        enum_id: EnumId,
        variant_id: VariantId,
        payloads: Vec<Operand>,
    },
    EnumDiscriminant {
        value: Operand,
        enum_id: EnumId,
        mode: MatchMode,
    },
    EnumPayload {
        value: Operand,
        enum_id: EnumId,
        variant_id: VariantId,
        index: u32,
        mode: MatchMode,
    },
    /// Finish a consuming enum destructure after active payload transfer.
    ConsumeEnum {
        owner: Place,
    },
    /// Explicit semantic widening.
    Coerce {
        kind: CoercionKind,
        operand: Operand,
        from: TypeId,
    },
    /// Explicit value conversion selected and typed in HIR.
    Cast {
        kind: CastKind,
        operand: Operand,
        from: TypeId,
        trap: Option<TrapKind>,
    },
    /// Unary computation, carrying its required trap effect in the opcode.
    Unary {
        op: UnaryOp,
        operand: Operand,
        trap: Option<TrapKind>,
    },
    /// Binary computation. Checked opcodes carry `IntegerOverflow` explicitly.
    Binary {
        op: BinaryOp,
        left: Operand,
        right: Operand,
        trap: Option<TrapKind>,
        secondary_trap: Option<TrapKind>,
    },
    /// Resolved direct call. The function table, not a source string, is authoritative.
    Call {
        callee: InstanceId,
        args: Vec<Operand>,
    },
}

/// One typed assignment.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MirInstruction {
    /// Destination storage.
    pub destination: Place,
    /// Computed value.
    pub value: Rvalue,
    /// Source provenance.
    pub span: Span,
}

/// Required final instruction of every verified block.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum Terminator {
    /// Unconditional control edge.
    Goto(BlockId),
    /// Boolean branch.
    Branch {
        condition: Operand,
        then_block: BlockId,
        else_block: BlockId,
    },
    /// Reusable integral multi-way control flow. `exhaustive_enum` records the
    /// stronger contract emitted by source enum matching.
    Switch {
        discriminant: Operand,
        cases: Vec<(u32, BlockId)>,
        otherwise: Option<BlockId>,
        exhaustive_enum: Option<EnumId>,
    },
    /// Function result.
    Return(Operand),
    /// Explicit unconditional failure.
    Trap(TrapKind),
}

/// Raw basic block. A raw block may lack a terminator until verification.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BasicBlock {
    /// Stable identity.
    pub id: BlockId,
    /// Assignments in execution order.
    pub instructions: Vec<MirInstruction>,
    /// Control-flow terminator.
    pub terminator: Option<Terminator>,
}

/// Raw function CFG.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MirFunction {
    /// Globally unambiguous session-local function identity.
    pub id: InstanceId,
    pub function_id: aether_frontend::FunctionId,
    /// Parameters in call order.
    pub parameters: Vec<MirParameter>,
    /// Sparse metadata: only roots needing conditional normal cleanup have flags.
    pub drop_flags: Vec<MirDropFlag>,
    /// Canonical return type.
    pub return_type: TypeId,
    /// User locals and expression temporaries.
    pub locals: Vec<MirLocal>,
    /// Entry-first blocks.
    pub blocks: Vec<BasicBlock>,
    /// Entry identity.
    pub entry: BlockId,
}

/// Unverified flow MIR.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FlowMir {
    /// Session-local canonical type identity context.
    pub types: Arc<TypeArena>,
    /// Resolved program module graph and provenance.
    pub modules: Vec<ModuleInfo>,
    /// Nominal aggregate and field metadata.
    pub structs: Vec<StructInfo>,
    /// Nominal tagged aggregate and variant metadata.
    pub enums: Vec<EnumInfo>,
    /// Program-global signature table.
    pub signatures: Vec<FunctionInstanceInfo>,
    /// Function-local CFGs in stable identity order.
    pub functions: Vec<MirFunction>,
    /// Entry function identity.
    pub entry: InstanceId,
}

impl FlowMir {
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

/// Immutable proof wrapper created only by [`verify_mir`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VerifiedMir(FlowMir);

impl VerifiedMir {
    /// Borrows the verified representation without exposing mutation.
    #[must_use]
    pub const fn as_mir(&self) -> &FlowMir {
        &self.0
    }

    /// Deterministic inspection dump.
    #[must_use]
    pub fn dump(&self) -> String {
        self.0.dump()
    }
}

/// Lowers typed, resolved HIR into a raw CFG.
#[must_use]
pub fn lower_hir(hir: TypedHir) -> FlowMir {
    let (modules, types, structs, enums, signatures, functions, entry) = hir.into_parts();
    let functions = functions
        .iter()
        .map(|function| {
            let return_type = signatures[function.id.0 as usize].return_type;
            lower_function(function, return_type, &enums, &types)
        })
        .collect();
    FlowMir {
        modules,
        types: Arc::new(types),
        structs,
        enums,
        signatures,
        functions,
        entry,
    }
}

fn conditional_drop_roots(block: &HirBlock) -> BTreeSet<LocalId> {
    fn visit(block: &HirBlock, roots: &mut BTreeSet<LocalId>) {
        for drop in &block.exit_drops {
            if let HirDrop::Conditional(local) = drop {
                roots.insert(*local);
            }
        }
        for statement in &block.statements {
            match &statement.kind {
                HirStmtKind::If {
                    then_block,
                    else_block,
                    ..
                } => {
                    visit(then_block, roots);
                    if let Some(else_block) = else_block {
                        visit(else_block, roots);
                    }
                }
                HirStmtKind::While { body, .. } => visit(body, roots),
                HirStmtKind::Match { arms, .. } => {
                    for arm in arms {
                        visit(&arm.body, roots);
                    }
                }
                HirStmtKind::Return { drops, .. } => {
                    for drop in drops {
                        if let HirDrop::Conditional(local) = drop {
                            roots.insert(*local);
                        }
                    }
                }
                HirStmtKind::Nop | HirStmtKind::Local { .. } | HirStmtKind::Assign { .. } => {}
            }
        }
    }

    let mut roots = BTreeSet::new();
    visit(block, &mut roots);
    roots
}

fn lower_function(
    function: &HirFunction,
    return_type: TypeId,
    enums: &[EnumInfo],
    types: &TypeArena,
) -> MirFunction {
    let locals = function
        .locals
        .iter()
        .map(|local| MirLocal {
            id: local.id,
            ty: local.ty,
            name: Some(local.name.clone()),
            temporary: false,
            address_taken: local.address_taken,
        })
        .collect();
    let parameters = function
        .parameters
        .iter()
        .map(|parameter| MirParameter {
            local: parameter.local,
            ty: parameter.ty,
        })
        .collect();
    let conditional_roots = conditional_drop_roots(&function.body);
    let mut builder = Builder {
        function: MirFunction {
            id: function.id,
            function_id: function.function_id,
            parameters,
            drop_flags: Vec::new(),
            return_type,
            locals,
            blocks: vec![BasicBlock {
                id: BlockId(0),
                instructions: Vec::new(),
                terminator: None,
            }],
            entry: BlockId(0),
        },
        current: Some(BlockId(0)),
        enums,
        types,
        drop_flag_by_owner: vec![None; function.locals.len()],
    };
    for owner in conditional_roots {
        let flag = builder.temporary(TypeId::BOOL);
        builder.drop_flag_by_owner[owner.0 as usize] = Some(flag);
        builder
            .function
            .drop_flags
            .push(MirDropFlag { owner, flag });
        let initially_owned = function.locals[owner.0 as usize].parameter;
        builder.assign(
            Place {
                base: PlaceBase::Local(flag),
                projections: Vec::new(),
            },
            Rvalue::Use(Operand::Bool(initially_owned)),
            function.span,
        );
    }
    builder.lower_block(&function.body);
    builder.function
}

struct Builder<'a> {
    function: MirFunction,
    current: Option<BlockId>,
    enums: &'a [EnumInfo],
    types: &'a TypeArena,
    drop_flag_by_owner: Vec<Option<LocalId>>,
}

impl Builder<'_> {
    fn lower_block(&mut self, block: &HirBlock) {
        for statement in &block.statements {
            match &statement.kind {
                HirStmtKind::Nop => {}
                HirStmtKind::Local { local, initializer } => {
                    let value = self.lower_expr(initializer);
                    let rvalue = if self.types.is_copy(initializer.ty) {
                        Rvalue::Use(value)
                    } else {
                        Rvalue::Move {
                            source: operand_place(&value),
                        }
                    };
                    self.assign(
                        Place {
                            base: PlaceBase::Local(*local),
                            projections: vec![],
                        },
                        rvalue,
                        statement.span,
                    );
                    if !self.types.is_copy(initializer.ty) {
                        self.set_drop_flag(*local, true, statement.span);
                    }
                }
                HirStmtKind::Assign { place, value } => {
                    let value = self.lower_expr(value);
                    let place = self.lower_place(place);
                    if self.types.is_copy(value_type(&self.function, &value)) {
                        self.assign(place, Rvalue::Use(value), statement.span);
                    } else {
                        let destination_owner = match &place.base {
                            PlaceBase::Local(local) if place.projections.is_empty() => Some(*local),
                            _ => None,
                        };
                        if self.types.needs_drop(value_type(&self.function, &value)) {
                            self.emit_drop(place.clone(), statement.span);
                        }
                        self.assign(
                            place,
                            Rvalue::Move {
                                source: operand_place(&value),
                            },
                            statement.span,
                        );
                        if let Some(local) = destination_owner {
                            self.set_drop_flag(local, true, statement.span);
                        }
                    }
                }
                HirStmtKind::Return { value, drops } => {
                    let value = self.lower_expr(value);
                    for drop in drops {
                        self.emit_hir_drop(*drop, statement.span);
                    }
                    self.terminate(Terminator::Return(value));
                }
                HirStmtKind::If {
                    condition,
                    then_block,
                    else_block,
                } => self.lower_if(condition, then_block, else_block.as_ref()),
                HirStmtKind::While { condition, body } => self.lower_while(condition, body),
                HirStmtKind::Match {
                    mode,
                    scrutinee,
                    enum_type,
                    enum_id,
                    arms,
                } => self.lower_match(*mode, scrutinee, *enum_type, *enum_id, arms),
            }
        }
        if self.current.is_some() {
            for drop in &block.exit_drops {
                self.emit_hir_drop(*drop, block.span);
            }
        }
    }

    fn lower_if(
        &mut self,
        condition: &HirExpr,
        then_block: &HirBlock,
        else_block: Option<&HirBlock>,
    ) {
        let condition = self.lower_expr(condition);
        let then_id = self.new_block();
        let else_id = self.new_block();
        self.terminate(Terminator::Branch {
            condition,
            then_block: then_id,
            else_block: else_id,
        });

        self.current = Some(then_id);
        self.lower_block(then_block);
        let then_end = self.current;

        self.current = Some(else_id);
        if let Some(block) = else_block {
            self.lower_block(block);
        }
        let else_end = self.current;

        if then_end.is_none() && else_end.is_none() {
            self.current = None;
            return;
        }
        let join = self.new_block();
        if let Some(block) = then_end {
            self.current = Some(block);
            self.terminate(Terminator::Goto(join));
        }
        if let Some(block) = else_end {
            self.current = Some(block);
            self.terminate(Terminator::Goto(join));
        }
        self.current = Some(join);
    }

    fn lower_while(&mut self, condition: &HirExpr, body: &HirBlock) {
        let header = self.new_block();
        let body_id = self.new_block();
        let exit = self.new_block();
        self.terminate(Terminator::Goto(header));
        self.current = Some(header);
        let condition = self.lower_expr(condition);
        self.terminate(Terminator::Branch {
            condition,
            then_block: body_id,
            else_block: exit,
        });
        self.current = Some(body_id);
        self.lower_block(body);
        if let Some(end) = self.current {
            self.current = Some(end);
            self.terminate(Terminator::Goto(header));
        }
        self.current = Some(exit);
    }

    #[allow(clippy::too_many_lines)]
    fn lower_match(
        &mut self,
        mode: MatchMode,
        scrutinee: &HirExpr,
        enum_type: TypeId,
        enum_id: EnumId,
        arms: &[HirMatchArm],
    ) {
        let enum_value = self.lower_expr(scrutinee);
        let tag = self.temporary(TypeId::UINT32);
        self.assign(
            Place {
                base: PlaceBase::Local(tag),
                projections: vec![],
            },
            Rvalue::EnumDiscriminant {
                value: enum_value.clone(),
                enum_id,
                mode,
            },
            scrutinee.span,
        );
        let arm_blocks: Vec<BlockId> = arms.iter().map(|_| self.new_block()).collect();
        let info = &self.enums[enum_id.0 as usize];
        let cases = arms
            .iter()
            .zip(&arm_blocks)
            .map(|(arm, block)| {
                let variant = &info.variants[arm.variant_id.index as usize];
                (variant.discriminant, *block)
            })
            .collect();
        self.terminate(Terminator::Switch {
            discriminant: Operand::Local(tag),
            cases,
            otherwise: None,
            exhaustive_enum: Some(enum_id),
        });
        let mut open_ends = Vec::new();
        for (arm, block_id) in arms.iter().zip(arm_blocks) {
            self.current = Some(block_id);
            let variant = &info.variants[arm.variant_id.index as usize];
            let consuming = mode == MatchMode::Value && !self.types.is_copy(enum_type);
            let mut ignored_owners = Vec::new();
            for payload in &variant.payloads {
                let binding = arm
                    .bindings
                    .iter()
                    .find(|binding| binding.payload_index == payload.index);
                if let Some(binding) = binding {
                    self.assign(
                        Place {
                            base: PlaceBase::Local(binding.local),
                            projections: vec![],
                        },
                        Rvalue::EnumPayload {
                            value: enum_value.clone(),
                            enum_id,
                            variant_id: arm.variant_id,
                            index: binding.payload_index,
                            mode,
                        },
                        binding.span,
                    );
                    if !self.types.is_copy(binding.ty) {
                        self.set_drop_flag(binding.local, true, binding.span);
                    }
                } else if consuming {
                    let payload_ty =
                        concrete_enum_member(self.types, self.enums, enum_type, payload.ty)
                            .expect("verified concrete match payload type");
                    if self.types.needs_drop(payload_ty) {
                        let temporary = self.temporary(payload_ty);
                        self.assign(
                            Place {
                                base: PlaceBase::Local(temporary),
                                projections: Vec::new(),
                            },
                            Rvalue::EnumPayload {
                                value: enum_value.clone(),
                                enum_id,
                                variant_id: arm.variant_id,
                                index: payload.index,
                                mode,
                            },
                            arm.span,
                        );
                        ignored_owners.push(temporary);
                    }
                }
            }
            if consuming {
                self.emit_consume_enum(operand_place(&enum_value), arm.span);
                for owner in ignored_owners.into_iter().rev() {
                    self.emit_drop(
                        Place {
                            base: PlaceBase::Local(owner),
                            projections: Vec::new(),
                        },
                        arm.span,
                    );
                }
            }
            self.lower_block(&arm.body);
            if let Some(end) = self.current {
                open_ends.push(end);
            }
        }
        if open_ends.is_empty() {
            self.current = None;
        } else {
            let join = self.new_block();
            for end in open_ends {
                self.current = Some(end);
                self.terminate(Terminator::Goto(join));
            }
            self.current = Some(join);
        }
    }

    #[allow(clippy::too_many_lines)]
    fn lower_expr(&mut self, expression: &HirExpr) -> Operand {
        match &expression.kind {
            HirExprKind::Int(value) => Operand::Int {
                value: *value,
                ty: expression.ty,
            },
            HirExprKind::Float(value) => Operand::Float {
                value: *value,
                ty: expression.ty,
            },
            HirExprKind::Bool(value) => Operand::Bool(*value),
            HirExprKind::Local(local) => {
                if self.function.locals[local.0 as usize].address_taken {
                    let destination = self.temporary(expression.ty);
                    self.assign(
                        Place {
                            base: PlaceBase::Local(destination),
                            projections: vec![],
                        },
                        Rvalue::Load(Place {
                            base: PlaceBase::Local(*local),
                            projections: vec![],
                        }),
                        expression.span,
                    );
                    Operand::Local(destination)
                } else {
                    Operand::Local(*local)
                }
            }
            HirExprKind::Move(local) => {
                let destination = self.temporary(expression.ty);
                self.assign(
                    Place {
                        base: PlaceBase::Local(destination),
                        projections: vec![],
                    },
                    Rvalue::Move {
                        source: Place {
                            base: PlaceBase::Local(*local),
                            projections: vec![],
                        },
                    },
                    expression.span,
                );
                self.set_drop_flag(*local, false, expression.span);
                Operand::Local(destination)
            }
            HirExprKind::Load(place) => {
                let destination = self.temporary(expression.ty);
                let place = self.lower_place(place);
                self.assign(
                    Place {
                        base: PlaceBase::Local(destination),
                        projections: vec![],
                    },
                    Rvalue::Load(place),
                    expression.span,
                );
                Operand::Local(destination)
            }
            HirExprKind::Borrow { place, mutable } => {
                let place = self.lower_place(place);
                let destination = self.temporary(expression.ty);
                self.assign(
                    Place {
                        base: PlaceBase::Local(destination),
                        projections: vec![],
                    },
                    Rvalue::Borrow {
                        place,
                        mutable: *mutable,
                    },
                    expression.span,
                );
                Operand::Local(destination)
            }
            HirExprKind::BufferInit {
                element_type,
                length,
                initial,
            } => {
                let length = self.lower_expr(length);
                let initial = self.lower_expr(initial);
                let destination = self.temporary(expression.ty);
                self.assign(
                    Place {
                        base: PlaceBase::Local(destination),
                        projections: vec![],
                    },
                    Rvalue::BufferAlloc {
                        element_type: *element_type,
                        length,
                        initial,
                        size_trap: TrapKind::AllocationSizeOverflow,
                        failure_trap: TrapKind::AllocationFailure,
                    },
                    expression.span,
                );
                Operand::Local(destination)
            }
            HirExprKind::View { source, mutable } => {
                let source = self.lower_place(source);
                let destination = self.temporary(expression.ty);
                self.assign(
                    Place {
                        base: PlaceBase::Local(destination),
                        projections: vec![],
                    },
                    Rvalue::View {
                        source,
                        mutable: *mutable,
                    },
                    expression.span,
                );
                Operand::Local(destination)
            }
            HirExprKind::Call { callee, args, .. } => {
                let args = args
                    .iter()
                    .map(|argument| self.lower_expr(argument))
                    .collect();
                let destination = self.temporary(expression.ty);
                self.assign(
                    Place {
                        base: PlaceBase::Local(destination),
                        projections: vec![],
                    },
                    Rvalue::Call {
                        callee: match callee {
                            HirCallTarget::Instance(instance) => *instance,
                            HirCallTarget::Declaration(_) => {
                                unreachable!("verified concrete HIR call")
                            }
                        },
                        args,
                    },
                    expression.span,
                );
                Operand::Local(destination)
            }
            HirExprKind::StructInit { struct_id, fields } => {
                let fields = fields
                    .iter()
                    .map(|(field, value)| (*field, self.lower_expr(value)))
                    .collect();
                let destination = self.temporary(expression.ty);
                self.assign(
                    Place {
                        base: PlaceBase::Local(destination),
                        projections: vec![],
                    },
                    Rvalue::Aggregate {
                        struct_id: *struct_id,
                        fields,
                    },
                    expression.span,
                );
                Operand::Local(destination)
            }
            HirExprKind::EnumInit {
                enum_id,
                variant_id,
                payloads,
            } => {
                let payloads = payloads
                    .iter()
                    .map(|payload| self.lower_expr(payload))
                    .collect();
                let destination = self.temporary(expression.ty);
                self.assign(
                    Place {
                        base: PlaceBase::Local(destination),
                        projections: vec![],
                    },
                    Rvalue::EnumConstruct {
                        enum_id: *enum_id,
                        variant_id: *variant_id,
                        payloads,
                    },
                    expression.span,
                );
                Operand::Local(destination)
            }
            HirExprKind::Coerce { kind, operand } => {
                let from = operand.ty;
                let operand = self.lower_expr(operand);
                let destination = self.temporary(expression.ty);
                self.assign(
                    Place {
                        base: PlaceBase::Local(destination),
                        projections: vec![],
                    },
                    Rvalue::Coerce {
                        kind: *kind,
                        operand,
                        from,
                    },
                    expression.span,
                );
                Operand::Local(destination)
            }
            HirExprKind::ExplicitCast {
                kind,
                source_type,
                target_type,
                operand,
            } => {
                let operand = self.lower_expr(operand);
                let destination = self.temporary(*target_type);
                let trap = cast_can_fail(self.types, *source_type, *target_type)
                    .then_some(TrapKind::ConversionOutOfRange);
                self.assign(
                    Place {
                        base: PlaceBase::Local(destination),
                        projections: vec![],
                    },
                    Rvalue::Cast {
                        kind: *kind,
                        operand,
                        from: *source_type,
                        trap,
                    },
                    expression.span,
                );
                Operand::Local(destination)
            }
            HirExprKind::Unary { op, operand } => {
                let operand = self.lower_expr(operand);
                let destination = self.temporary(expression.ty);
                let (op, trap) = match op {
                    HirUnaryOp::NegateIntegerChecked => (
                        UnaryOp::NegateIntegerChecked,
                        Some(TrapKind::IntegerOverflow),
                    ),
                    HirUnaryOp::NegateFloat => (UnaryOp::NegateFloat, None),
                };
                self.assign(
                    Place {
                        base: PlaceBase::Local(destination),
                        projections: vec![],
                    },
                    Rvalue::Unary { op, operand, trap },
                    expression.span,
                );
                Operand::Local(destination)
            }
            HirExprKind::Binary { op, left, right } => {
                let left = self.lower_expr(left);
                let right = self.lower_expr(right);
                let (op, trap, secondary_trap) = match op {
                    HirBinaryOp::AddIntegerChecked => (
                        BinaryOp::AddIntegerChecked,
                        Some(TrapKind::IntegerOverflow),
                        None,
                    ),
                    HirBinaryOp::SubtractIntegerChecked => (
                        BinaryOp::SubtractIntegerChecked,
                        Some(TrapKind::IntegerOverflow),
                        None,
                    ),
                    HirBinaryOp::MultiplyIntegerChecked => (
                        BinaryOp::MultiplyIntegerChecked,
                        Some(TrapKind::IntegerOverflow),
                        None,
                    ),
                    HirBinaryOp::DivideIntegerSignedChecked => (
                        BinaryOp::DivideIntegerSignedChecked,
                        Some(TrapKind::DivisionByZero),
                        Some(TrapKind::DivisionOverflow),
                    ),
                    HirBinaryOp::DivideIntegerUnsignedChecked => (
                        BinaryOp::DivideIntegerUnsignedChecked,
                        Some(TrapKind::DivisionByZero),
                        None,
                    ),
                    HirBinaryOp::RemainderIntegerSignedChecked => (
                        BinaryOp::RemainderIntegerSignedChecked,
                        Some(TrapKind::DivisionByZero),
                        None,
                    ),
                    HirBinaryOp::RemainderIntegerUnsignedChecked => (
                        BinaryOp::RemainderIntegerUnsignedChecked,
                        Some(TrapKind::DivisionByZero),
                        None,
                    ),
                    HirBinaryOp::AddFloat => (BinaryOp::AddFloat, None, None),
                    HirBinaryOp::SubtractFloat => (BinaryOp::SubtractFloat, None, None),
                    HirBinaryOp::MultiplyFloat => (BinaryOp::MultiplyFloat, None, None),
                    HirBinaryOp::DivideFloat => (BinaryOp::DivideFloat, None, None),
                    HirBinaryOp::Less => (BinaryOp::Less, None, None),
                    HirBinaryOp::LessEqual => (BinaryOp::LessEqual, None, None),
                    HirBinaryOp::Greater => (BinaryOp::Greater, None, None),
                    HirBinaryOp::GreaterEqual => (BinaryOp::GreaterEqual, None, None),
                    HirBinaryOp::Equal => (BinaryOp::Equal, None, None),
                    HirBinaryOp::NotEqual => (BinaryOp::NotEqual, None, None),
                };
                let destination = self.temporary(expression.ty);
                self.assign(
                    Place {
                        base: PlaceBase::Local(destination),
                        projections: vec![],
                    },
                    Rvalue::Binary {
                        op,
                        left,
                        right,
                        trap,
                        secondary_trap,
                    },
                    expression.span,
                );
                Operand::Local(destination)
            }
        }
    }

    fn temporary(&mut self, ty: TypeId) -> LocalId {
        let id = LocalId(u32::try_from(self.function.locals.len()).expect("local count fits u32"));
        self.function.locals.push(MirLocal {
            id,
            ty,
            name: None,
            temporary: true,
            address_taken: false,
        });
        id
    }

    fn new_block(&mut self) -> BlockId {
        let id = BlockId(u32::try_from(self.function.blocks.len()).expect("block count fits u32"));
        self.function.blocks.push(BasicBlock {
            id,
            instructions: Vec::new(),
            terminator: None,
        });
        id
    }

    fn assign(&mut self, destination: Place, value: Rvalue, span: Span) {
        let block = self
            .current
            .expect("typed HIR has no unreachable statements");
        self.function.blocks[block.0 as usize]
            .instructions
            .push(MirInstruction {
                destination,
                value,
                span,
            });
    }

    fn emit_drop(&mut self, owner: Place, span: Span) {
        let root = place_root_local(&owner);
        let token = self.temporary(TypeId::BOOL);
        self.assign(
            Place {
                base: PlaceBase::Local(token),
                projections: vec![],
            },
            Rvalue::Drop { owner },
            span,
        );
        if let Some(owner) = root {
            self.set_drop_flag(owner, false, span);
        }
    }

    fn emit_consume_enum(&mut self, owner: Place, span: Span) {
        let root = place_root_local(&owner);
        let token = self.temporary(TypeId::BOOL);
        self.assign(
            Place {
                base: PlaceBase::Local(token),
                projections: Vec::new(),
            },
            Rvalue::ConsumeEnum { owner },
            span,
        );
        if let Some(owner) = root {
            self.set_drop_flag(owner, false, span);
        }
    }

    fn set_drop_flag(&mut self, owner: LocalId, value: bool, span: Span) {
        let Some(flag) = self
            .drop_flag_by_owner
            .get(owner.0 as usize)
            .copied()
            .flatten()
        else {
            return;
        };
        self.assign(
            Place {
                base: PlaceBase::Local(flag),
                projections: Vec::new(),
            },
            Rvalue::Use(Operand::Bool(value)),
            span,
        );
    }

    fn emit_hir_drop(&mut self, drop: HirDrop, span: Span) {
        let owner = drop.local();
        let owner_place = || Place {
            base: PlaceBase::Local(owner),
            projections: Vec::new(),
        };
        match drop {
            HirDrop::Unconditional(_) => self.emit_drop(owner_place(), span),
            HirDrop::Conditional(_) => {
                let flag = self.drop_flag_by_owner[owner.0 as usize]
                    .expect("conditional HIR cleanup has a generated flag");
                let drop_block = self.new_block();
                let continue_block = self.new_block();
                self.terminate(Terminator::Branch {
                    condition: Operand::Local(flag),
                    then_block: drop_block,
                    else_block: continue_block,
                });
                self.current = Some(drop_block);
                self.emit_drop(owner_place(), span);
                self.terminate(Terminator::Goto(continue_block));
                self.current = Some(continue_block);
            }
        }
    }

    fn terminate(&mut self, terminator: Terminator) {
        let block = self.current.take().expect("current block is open");
        self.function.blocks[block.0 as usize].terminator = Some(terminator);
    }
    fn lower_place(&mut self, place: &HirPlace) -> Place {
        Place {
            base: match &place.base {
                HirPlaceBase::Local(local) => PlaceBase::Local(*local),
                HirPlaceBase::Dereference { reference, mutable } => PlaceBase::Dereference {
                    reference: self.lower_expr(reference),
                    mutable: *mutable,
                },
            },
            projections: place
                .projections
                .iter()
                .map(|projection| match projection {
                    HirPlaceProjection::Field(field) => PlaceProjection::Field(*field),
                    HirPlaceProjection::Index {
                        index,
                        element_type,
                        checked: _,
                    } => PlaceProjection::Index {
                        index: self.lower_expr(index),
                        element_type: *element_type,
                        bounds_trap: TrapKind::IndexOutOfBounds,
                    },
                })
                .collect(),
        }
    }
}

fn operand_place(operand: &Operand) -> Place {
    match operand {
        Operand::Local(local) => Place {
            base: PlaceBase::Local(*local),
            projections: vec![],
        },
        _ => panic!("move-only values are always materialized in MIR locals"),
    }
}

fn value_type(function: &MirFunction, operand: &Operand) -> TypeId {
    operand_type(function, operand).expect("lowered operand has a valid type")
}

/// Verifies CFG, type, storage, return, trap and definite-initialization invariants.
#[allow(clippy::too_many_lines)]
pub fn verify_mir(mir: FlowMir) -> Result<VerifiedMir, Vec<Diagnostic>> {
    let fail = |message: String| {
        vec![Diagnostic::new(
            "E0300",
            Phase::Mir,
            DiagnosticCategory::Verification,
            message,
            None,
        )]
    };
    if mir.modules.is_empty()
        || mir.entry.0 as usize >= mir.signatures.len()
        || mir.functions.len() != mir.signatures.len()
    {
        return Err(fail(
            "MIR function table/body cardinality is invalid".into(),
        ));
    }
    if mir.types.entries().any(|(_, data)| match data {
        TypeData::Buffer { element } | TypeData::View { element, .. } => {
            !mir.types.is_admitted_buffer_element(*element)
        }
        _ => false,
    }) {
        return Err(fail(
            "MIR contains a Buffer/View with an inadmissible element type".into(),
        ));
    }
    for ty in mir
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
            mir.structs
                .iter()
                .flat_map(|info| info.fields.iter().map(|field| field.ty)),
        )
        .chain(mir.enums.iter().flat_map(|info| {
            info.variants
                .iter()
                .flat_map(|variant| variant.payloads.iter().map(|payload| payload.ty))
        }))
        .chain(
            mir.functions
                .iter()
                .flat_map(|function| function.locals.iter().map(|local| local.ty)),
        )
    {
        if !mir.types.is_valid(ty) {
            return Err(fail(format!("MIR references invalid TypeId({})", ty.0)));
        }
    }
    for (index, (signature, function)) in mir.signatures.iter().zip(&mir.functions).enumerate() {
        if signature.id.0 as usize != index || function.id != signature.id {
            return Err(fail("MIR function identities are not canonical".into()));
        }
        if signature.module.0 as usize >= mir.modules.len() {
            return Err(fail("MIR signature names an unknown module".into()));
        }
        if mir.types.contains_reference(signature.return_type)
            || mir.types.contains_view(signature.return_type)
            || mir.structs.iter().any(|info| {
                info.fields.iter().any(|field| {
                    mir.types.contains_reference(field.ty) || mir.types.contains_view(field.ty)
                })
            })
            || mir.enums.iter().any(|info| {
                info.variants.iter().any(|variant| {
                    variant.payloads.iter().any(|payload| {
                        mir.types.contains_reference(payload.ty)
                            || mir.types.contains_view(payload.ty)
                    })
                })
            })
        {
            return Err(fail(
                "MIR violates borrowed-value non-escape storage rules".into(),
            ));
        }
        if signature
            .parameters
            .iter()
            .any(|parameter| mir.types.contains_generic(parameter.ty))
            || mir.types.contains_generic(signature.return_type)
            || function
                .locals
                .iter()
                .any(|local| mir.types.contains_generic(local.ty))
        {
            return Err(fail(
                "unresolved generic parameter reached MIR codegen".into(),
            ));
        }
        verify_mir_function(
            function,
            signature,
            &mir.signatures,
            &mir.structs,
            &mir.enums,
            &mir.types,
            &fail,
        )?;
    }
    Ok(VerifiedMir(mir))
}

#[allow(clippy::too_many_lines)]
fn verify_mir_function(
    function: &MirFunction,
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
        return Err(fail(format!(
            "MIR signature cache mismatch for {:?}",
            function.id
        )));
    }
    if function.blocks.is_empty() || function.entry.0 as usize >= function.blocks.len() {
        return Err(fail("MIR entry block does not exist".into()));
    }
    for (index, local) in function.locals.iter().enumerate() {
        if local.id.0 as usize != index {
            return Err(fail(format!(
                "MIR local {:?} has non-canonical identity",
                local.id
            )));
        }
    }
    for (parameter, declared) in function.parameters.iter().zip(&signature.parameters) {
        if function
            .locals
            .get(parameter.local.0 as usize)
            .map(|local| local.ty)
            != Some(declared.ty)
            || parameter.ty != declared.ty
        {
            return Err(fail(
                "MIR parameter identity/type contract is invalid".into(),
            ));
        }
    }
    let mut predecessors = vec![Vec::new(); function.blocks.len()];
    for (index, block) in function.blocks.iter().enumerate() {
        if block.id.0 as usize != index {
            return Err(fail(format!(
                "MIR block {:?} has non-canonical identity",
                block.id
            )));
        }
        let Some(terminator) = &block.terminator else {
            return Err(fail(format!("MIR block {:?} has no terminator", block.id)));
        };
        for target in targets(terminator) {
            if target.0 as usize >= function.blocks.len() {
                return Err(fail(format!("MIR target {target:?} does not exist")));
            }
            predecessors[target.0 as usize].push(block.id);
        }
    }

    let reachable = reachability(function);
    if reachable.iter().any(|value| !value) {
        return Err(fail("MIR contains an unreachable block".into()));
    }
    verify_drop_flag_contract(function, signatures, types, fail)?;
    verify_ownership(function, signatures, types, fail)?;
    let all = vec![true; function.locals.len()];
    let mut initialized_in = vec![all.clone(); function.blocks.len()];
    initialized_in[function.entry.0 as usize].fill(false);
    for parameter in &function.parameters {
        initialized_in[function.entry.0 as usize][parameter.local.0 as usize] = true;
    }
    let mut changed = true;
    while changed {
        changed = false;
        for block in &function.blocks {
            if block.id == function.entry {
                continue;
            }
            let preds = &predecessors[block.id.0 as usize];
            let mut incoming = all.clone();
            for predecessor in preds {
                let mut outgoing = initialized_in[predecessor.0 as usize].clone();
                for instruction in &function.blocks[predecessor.0 as usize].instructions {
                    if let Some(local) = place_root_local(&instruction.destination) {
                        outgoing[local.0 as usize] = true;
                    }
                }
                for (slot, pred_value) in incoming.iter_mut().zip(outgoing) {
                    *slot &= pred_value;
                }
            }
            if incoming != initialized_in[block.id.0 as usize] {
                initialized_in[block.id.0 as usize] = incoming;
                changed = true;
            }
        }
    }

    for block in &function.blocks {
        let mut initialized = initialized_in[block.id.0 as usize].clone();
        for instruction in &block.instructions {
            if let Some(local) = place_root_local(&instruction.destination) {
                if function.locals.get(local.0 as usize).is_none() {
                    return Err(fail(format!(
                        "assignment destination {:?} does not exist",
                        instruction.destination
                    )));
                }
                if !instruction.destination.projections.is_empty() && !initialized[local.0 as usize]
                {
                    return Err(fail(
                        "MIR projected store reads an uninitialized aggregate".into(),
                    ));
                }
            }
            if !instruction.destination.projections.is_empty()
                && !matches!(instruction.value, Rvalue::Use(_))
            {
                return Err(fail(
                    "MIR projected store requires a materialized value operand".into(),
                ));
            }
            if let PlaceBase::Dereference { reference, mutable } = &instruction.destination.base {
                validate_operand(function, reference, &initialized).map_err(&fail)?;
                if !*mutable {
                    return Err(fail("MIR store through shared reference".into()));
                }
            }
            if place_has_index(&instruction.destination)
                && let PlaceBase::Local(local) = &instruction.destination.base
                && types
                    .view_info(function.locals[local.0 as usize].ty)
                    .is_some_and(|(_, mutable)| !mutable)
            {
                return Err(fail("MIR store through read-only View".into()));
            }
            let destination_ty =
                place_type(function, &instruction.destination, structs, types).map_err(&fail)?;
            validate_rvalue(
                function,
                signatures,
                structs,
                enums,
                types,
                &instruction.value,
                destination_ty,
                &initialized,
            )
            .map_err(&fail)?;
            if let Some(local) = place_root_local(&instruction.destination) {
                initialized[local.0 as usize] = true;
            }
        }
        let terminator = block.terminator.as_ref().expect("checked above");
        match terminator {
            Terminator::Branch { condition, .. } => {
                validate_operand(function, condition, &initialized)
                    .map_err(|message| fail(message.clone()))?;
                if operand_type(function, condition).map_err(|message| fail(message.clone()))?
                    != TypeId::BOOL
                {
                    return Err(fail("MIR branch condition is not bool".into()));
                }
            }
            Terminator::Switch {
                discriminant,
                cases,
                otherwise,
                exhaustive_enum,
            } => {
                validate_operand(function, discriminant, &initialized)
                    .map_err(|message| fail(message.clone()))?;
                if operand_type(function, discriminant).map_err(|message| fail(message.clone()))?
                    != TypeId::UINT32
                {
                    return Err(fail("MIR switch discriminant is not uint32".into()));
                }
                let mut values = std::collections::BTreeSet::new();
                if cases.is_empty() || cases.iter().any(|(value, _)| !values.insert(*value)) {
                    return Err(fail("MIR switch cases are empty or duplicated".into()));
                }
                if let Some(enum_id) = exhaustive_enum {
                    let Some(info) = enums
                        .get(enum_id.0 as usize)
                        .filter(|info| info.id == *enum_id)
                    else {
                        return Err(fail("MIR exhaustive switch names unknown enum".into()));
                    };
                    let expected = info
                        .variants
                        .iter()
                        .map(|variant| variant.discriminant)
                        .collect::<std::collections::BTreeSet<_>>();
                    if values != expected || otherwise.is_some() {
                        return Err(fail(
                            "MIR exhaustive enum switch does not cover exact tags".into(),
                        ));
                    }
                    let Operand::Local(tag_local) = discriminant else {
                        return Err(fail(
                            "MIR exhaustive enum switch requires an extracted tag local".into(),
                        ));
                    };
                    let definitions = function
                        .blocks
                        .iter()
                        .flat_map(|candidate| &candidate.instructions)
                        .filter(|instruction| {
                            place_root_local(&instruction.destination) == Some(*tag_local)
                                && instruction.destination.projections.is_empty()
                        })
                        .collect::<Vec<_>>();
                    if definitions.len() != 1
                        || !matches!(
                            definitions[0].value,
                            Rvalue::EnumDiscriminant { enum_id: extracted, .. } if extracted == *enum_id
                        )
                    {
                        return Err(fail(
                            "MIR exhaustive switch tag does not originate from its enum".into(),
                        ));
                    }
                }
            }
            Terminator::Return(value) => {
                validate_operand(function, value, &initialized)
                    .map_err(|message| fail(message.clone()))?;
                if operand_type(function, value).map_err(|message| fail(message.clone()))?
                    != function.return_type
                {
                    return Err(fail("MIR return operand has wrong type".into()));
                }
            }
            Terminator::Goto(_) | Terminator::Trap(_) => {}
        }
    }
    Ok(())
}

#[allow(clippy::too_many_lines)]
fn verify_drop_flag_contract(
    function: &MirFunction,
    signatures: &[FunctionInstanceInfo],
    types: &TypeArena,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    let mut owners = BTreeSet::new();
    let mut flags = BTreeSet::new();
    for entry in &function.drop_flags {
        let Some(owner) = function.locals.get(entry.owner.0 as usize) else {
            return Err(fail("MIR drop flag names an unknown owner".into()));
        };
        let Some(flag) = function.locals.get(entry.flag.0 as usize) else {
            return Err(fail("MIR drop flag names an unknown flag local".into()));
        };
        if !owners.insert(entry.owner)
            || !flags.insert(entry.flag)
            || owner.temporary
            || types.is_copy(owner.ty)
            || !types.needs_drop(owner.ty)
            || flag.ty != TypeId::BOOL
            || !flag.temporary
            || flag.address_taken
        {
            return Err(fail("MIR root-level drop flag metadata is invalid".into()));
        }
    }

    let entry_block = &function.blocks[function.entry.0 as usize];
    let mut allowed_writes = BTreeSet::new();
    for (index, entry) in function.drop_flags.iter().enumerate() {
        let expected = function
            .parameters
            .iter()
            .any(|parameter| parameter.local == entry.owner);
        let Some(instruction) = entry_block.instructions.get(index) else {
            return Err(fail(
                "MIR drop flag is not initialized at function entry".into(),
            ));
        };
        if place_root_local(&instruction.destination) != Some(entry.flag)
            || !instruction.destination.projections.is_empty()
            || !matches!(instruction.value, Rvalue::Use(Operand::Bool(value)) if value == expected)
        {
            return Err(fail("MIR drop flag has an invalid initial value".into()));
        }
        allowed_writes.insert((function.entry, index));
    }

    let flag_for = |owner: LocalId| {
        function
            .drop_flags
            .iter()
            .find(|entry| entry.owner == owner)
            .map(|entry| entry.flag)
    };
    for block in &function.blocks {
        for (index, instruction) in block.instructions.iter().enumerate() {
            let destination = place_root_local(&instruction.destination);
            let mut transitions = Vec::new();
            let consume_operand = |operand: &Operand, transitions: &mut Vec<(LocalId, bool)>| {
                if let Some(owner) = operand_local_id(operand)
                    && let Some(flag) = flag_for(owner)
                {
                    transitions.push((flag, false));
                }
            };
            match &instruction.value {
                Rvalue::Move { source } => {
                    if let Some(owner) = place_root_local(source)
                        && let Some(flag) = flag_for(owner)
                    {
                        transitions.push((flag, false));
                    }
                    if let Some(owner) = destination
                        && let Some(flag) = flag_for(owner)
                    {
                        transitions.push((flag, true));
                    }
                }
                Rvalue::Drop { owner } | Rvalue::ConsumeEnum { owner } => {
                    if let Some(owner) = place_root_local(owner)
                        && let Some(flag) = flag_for(owner)
                    {
                        transitions.push((flag, false));
                    }
                }
                Rvalue::BufferAlloc { .. }
                | Rvalue::EnumPayload {
                    mode: MatchMode::Value,
                    ..
                } => {
                    if let Some(owner) = destination
                        && let Some(flag) = flag_for(owner)
                    {
                        transitions.push((flag, true));
                    }
                }
                Rvalue::Call { callee, args } => {
                    let Some(signature) = signatures
                        .get(callee.0 as usize)
                        .filter(|signature| signature.id == *callee)
                    else {
                        return Err(fail(
                            "MIR drop-flag analysis found unknown call target".into(),
                        ));
                    };
                    for (argument, parameter) in args.iter().zip(&signature.parameters) {
                        if !types.is_copy(parameter.ty) {
                            consume_operand(argument, &mut transitions);
                        }
                    }
                    if let Some(owner) = destination
                        && let Some(flag) = flag_for(owner)
                    {
                        transitions.push((flag, true));
                    }
                }
                Rvalue::Aggregate { fields, .. } => {
                    for (_, operand) in fields {
                        if !types.is_copy(operand_type(function, operand).map_err(fail)?) {
                            consume_operand(operand, &mut transitions);
                        }
                    }
                    if let Some(owner) = destination
                        && let Some(flag) = flag_for(owner)
                    {
                        transitions.push((flag, true));
                    }
                }
                Rvalue::EnumConstruct { payloads, .. } => {
                    for operand in payloads {
                        if !types.is_copy(operand_type(function, operand).map_err(fail)?) {
                            consume_operand(operand, &mut transitions);
                        }
                    }
                    if let Some(owner) = destination
                        && let Some(flag) = flag_for(owner)
                    {
                        transitions.push((flag, true));
                    }
                }
                _ => {}
            }
            for (offset, (flag, value)) in transitions.into_iter().enumerate() {
                let write_index = index + offset + 1;
                let Some(write) = block.instructions.get(write_index) else {
                    return Err(fail(
                        "MIR ownership transition is missing its drop-flag update".into(),
                    ));
                };
                if place_root_local(&write.destination) != Some(flag)
                    || !write.destination.projections.is_empty()
                    || !matches!(write.value, Rvalue::Use(Operand::Bool(actual)) if actual == value)
                {
                    return Err(fail(
                        "MIR ownership transition has a stale drop flag".into(),
                    ));
                }
                allowed_writes.insert((block.id, write_index));
            }
        }
    }
    for block in &function.blocks {
        for (index, instruction) in block.instructions.iter().enumerate() {
            if place_root_local(&instruction.destination)
                .is_some_and(|local| flags.contains(&local))
                && !allowed_writes.contains(&(block.id, index))
            {
                return Err(fail("MIR contains an unpaired drop-flag transition".into()));
            }
        }
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum MirOwnerState {
    Uninitialized,
    Owned,
    Moved,
    MaybeMoved,
    Dropped,
}

#[allow(clippy::too_many_lines)]
fn verify_ownership(
    function: &MirFunction,
    signatures: &[FunctionInstanceInfo],
    types: &TypeArena,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    let mut predecessors = vec![Vec::new(); function.blocks.len()];
    for block in &function.blocks {
        for target in targets(block.terminator.as_ref().expect("verified CFG")) {
            predecessors[target.0 as usize].push(block.id);
        }
    }
    let has_backedge = predecessors
        .iter()
        .enumerate()
        .map(|(target, incoming)| {
            let target = BlockId(u32::try_from(target).expect("block count fits u32"));
            incoming
                .iter()
                .any(|source| block_reaches(function, target, *source))
        })
        .collect::<Vec<_>>();
    let mut seen_predecessors = vec![BTreeSet::new(); function.blocks.len()];
    let mut entry = vec![MirOwnerState::Uninitialized; function.locals.len()];
    for parameter in &function.parameters {
        if !types.is_copy(parameter.ty) {
            entry[parameter.local.0 as usize] = MirOwnerState::Owned;
        }
    }
    let mut incoming: Vec<Option<Vec<MirOwnerState>>> = vec![None; function.blocks.len()];
    incoming[function.entry.0 as usize] = Some(entry);
    let mut queue = VecDeque::from([function.entry]);
    while let Some(block_id) = queue.pop_front() {
        let mut state = incoming[block_id.0 as usize]
            .clone()
            .expect("queued ownership state");
        let block = &function.blocks[block_id.0 as usize];
        for instruction in &block.instructions {
            let destination = place_root_local(&instruction.destination);
            match &instruction.value {
                Rvalue::Move { source } => {
                    let source = place_root_local(source)
                        .ok_or_else(|| fail("MIR Move source has no owning local".into()))?;
                    consume_owner(function, types, &mut state, source, "Move", fail)?;
                    initialize_owner(function, types, &mut state, destination, fail)?;
                }
                Rvalue::Drop { owner } => {
                    let owner = place_root_local(owner)
                        .ok_or_else(|| fail("MIR Drop owner has no local".into()))?;
                    if state[owner.0 as usize] != MirOwnerState::Owned {
                        return Err(fail(
                            "MIR Drop is not exactly-once on an owned value".into(),
                        ));
                    }
                    state[owner.0 as usize] = MirOwnerState::Dropped;
                }
                Rvalue::ConsumeEnum { owner } => {
                    let owner = place_root_local(owner)
                        .ok_or_else(|| fail("MIR consuming match owner has no local".into()))?;
                    consume_owner(function, types, &mut state, owner, "consuming match", fail)?;
                }
                Rvalue::BufferAlloc { .. } => {
                    initialize_owner(function, types, &mut state, destination, fail)?;
                }
                Rvalue::Call { callee, args } => {
                    let signature = signatures
                        .get(callee.0 as usize)
                        .filter(|signature| signature.id == *callee)
                        .ok_or_else(|| {
                            fail("MIR ownership analysis found unknown call target".into())
                        })?;
                    for (argument, parameter) in args.iter().zip(&signature.parameters) {
                        if !types.is_copy(parameter.ty) {
                            let local = operand_local_id(argument).ok_or_else(|| {
                                fail("owned call argument is not materialized".into())
                            })?;
                            consume_owner(function, types, &mut state, local, "call", fail)?;
                        }
                    }
                    initialize_owner(function, types, &mut state, destination, fail)?;
                }
                Rvalue::Use(operand) => {
                    if !types.is_copy(operand_type(function, operand).map_err(fail)?) {
                        return Err(fail("implicit copy of a non-Copy value in MIR".into()));
                    }
                }
                Rvalue::Load(place)
                | Rvalue::Borrow { place, .. }
                | Rvalue::View { source: place, .. } => {
                    require_place_owner(function, types, &state, place, fail)?;
                }
                Rvalue::Aggregate { fields, .. } => {
                    for (_, operand) in fields {
                        let ty = operand_type(function, operand).map_err(fail)?;
                        if !types.is_copy(ty) {
                            let local = operand_local_id(operand).ok_or_else(|| {
                                fail("non-Copy aggregate field is not materialized".into())
                            })?;
                            consume_owner(
                                function,
                                types,
                                &mut state,
                                local,
                                "aggregate construction",
                                fail,
                            )?;
                        }
                    }
                    initialize_owner(function, types, &mut state, destination, fail)?;
                }
                Rvalue::EnumConstruct { payloads, .. } => {
                    for operand in payloads {
                        let ty = operand_type(function, operand).map_err(fail)?;
                        if !types.is_copy(ty) {
                            let local = operand_local_id(operand).ok_or_else(|| {
                                fail("non-Copy enum payload is not materialized".into())
                            })?;
                            consume_owner(
                                function,
                                types,
                                &mut state,
                                local,
                                "enum construction",
                                fail,
                            )?;
                        }
                    }
                    initialize_owner(function, types, &mut state, destination, fail)?;
                }
                Rvalue::EnumDiscriminant { value, mode, .. }
                | Rvalue::EnumPayload { value, mode, .. } => {
                    if let Some(local) = operand_local_id(value)
                        && *mode == MatchMode::Value
                        && !types.is_copy(function.locals[local.0 as usize].ty)
                        && matches!(
                            state[local.0 as usize],
                            MirOwnerState::Moved
                                | MirOwnerState::MaybeMoved
                                | MirOwnerState::Dropped
                        )
                    {
                        return Err(fail(
                            "MIR enum inspection uses a moved/dropped owner".into(),
                        ));
                    }
                    if matches!(
                        instruction.value,
                        Rvalue::EnumPayload {
                            mode: MatchMode::Value,
                            ..
                        }
                    ) && !types.is_copy(
                        function.locals[destination.expect("payload destination").0 as usize].ty,
                    ) {
                        initialize_owner(function, types, &mut state, destination, fail)?;
                    }
                }
                _ => {}
            }
            if place_has_index(&instruction.destination) {
                require_place_owner(function, types, &state, &instruction.destination, fail)?;
            }
        }
        let terminator = block.terminator.as_ref().expect("CFG verified");
        if let Terminator::Return(value) = terminator {
            if !types.is_copy(function.return_type) {
                let local = operand_local_id(value)
                    .ok_or_else(|| fail("owned return is not materialized".into()))?;
                consume_owner(function, types, &mut state, local, "return", fail)?;
            }
            if let Some(local) = function.locals.iter().find(|local| {
                types.needs_drop(local.ty)
                    && matches!(
                        state[local.id.0 as usize],
                        MirOwnerState::Owned | MirOwnerState::MaybeMoved
                    )
            }) {
                return Err(fail(format!(
                    "MIR function {:?} normal return leaks owning local {:?} in state {:?}",
                    function.id, local.id, state[local.id.0 as usize]
                )));
            }
        }
        for target in targets(terminator) {
            let mut outgoing = state.clone();
            if let Terminator::Branch {
                condition: Operand::Local(flag),
                then_block,
                else_block,
            } = terminator
                && let Some(drop_flag) =
                    function.drop_flags.iter().find(|entry| entry.flag == *flag)
                && state[drop_flag.owner.0 as usize] == MirOwnerState::MaybeMoved
            {
                outgoing[drop_flag.owner.0 as usize] = if target == *then_block {
                    MirOwnerState::Owned
                } else if target == *else_block {
                    MirOwnerState::Moved
                } else {
                    unreachable!("branch target enumeration is exact")
                };
            }
            let target_index = target.0 as usize;
            let was_ready = target == function.entry
                || has_backedge[target_index]
                || seen_predecessors[target_index].len() == predecessors[target_index].len();
            seen_predecessors[target_index].insert(block_id);
            let mut changed_target = false;
            match incoming[target.0 as usize].clone() {
                None => {
                    incoming[target.0 as usize] = Some(outgoing);
                    changed_target = true;
                }
                Some(previous) => {
                    let mut merged = previous.clone();
                    for ((merged_state, previous_state), incoming_state) in
                        merged.iter_mut().zip(&previous).zip(&outgoing)
                    {
                        if previous_state == incoming_state {
                            continue;
                        }
                        *merged_state = merge_mir_owner_state(*previous_state, *incoming_state);
                    }
                    if merged != previous {
                        incoming[target.0 as usize] = Some(merged);
                        changed_target = true;
                    }
                }
            }
            let ready = target == function.entry
                || has_backedge[target_index]
                || seen_predecessors[target_index].len() == predecessors[target_index].len();
            if ready && (changed_target || !was_ready) {
                queue.push_back(target);
            }
        }
    }
    Ok(())
}

fn initialize_owner(
    function: &MirFunction,
    types: &TypeArena,
    state: &mut [MirOwnerState],
    destination: Option<LocalId>,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    let Some(local) = destination else {
        return Ok(());
    };
    if types.is_copy(function.locals[local.0 as usize].ty) {
        return Ok(());
    }
    if state[local.0 as usize] == MirOwnerState::Owned {
        return Err(fail(
            "MIR overwrites a live non-Copy value without transfer/drop".into(),
        ));
    }
    state[local.0 as usize] = MirOwnerState::Owned;
    Ok(())
}

fn merge_mir_owner_state(left: MirOwnerState, right: MirOwnerState) -> MirOwnerState {
    use MirOwnerState::{Dropped, MaybeMoved, Moved, Owned, Uninitialized};
    match (left, right) {
        (Uninitialized, Uninitialized) => Uninitialized,
        (Owned, Owned) => Owned,
        (Moved | Dropped, Moved | Uninitialized)
        | (Moved, Dropped)
        | (Uninitialized, Moved | Dropped) => Moved,
        (Dropped, Dropped) => Dropped,
        (MaybeMoved, _)
        | (_, MaybeMoved)
        | (Owned, Moved | Dropped | Uninitialized)
        | (Moved | Dropped | Uninitialized, Owned) => MaybeMoved,
    }
}

fn consume_owner(
    function: &MirFunction,
    types: &TypeArena,
    state: &mut [MirOwnerState],
    local: LocalId,
    operation: &str,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    if types.is_copy(function.locals[local.0 as usize].ty)
        || state[local.0 as usize] != MirOwnerState::Owned
    {
        return Err(fail(format!(
            "MIR {operation} uses a non-owned or moved value"
        )));
    }
    state[local.0 as usize] = MirOwnerState::Moved;
    Ok(())
}

fn require_place_owner(
    function: &MirFunction,
    types: &TypeArena,
    state: &[MirOwnerState],
    place: &Place,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    if let Some(local) = place_root_local(place)
        && !types.is_copy(function.locals[local.0 as usize].ty)
        && state[local.0 as usize] != MirOwnerState::Owned
    {
        return Err(fail("MIR place uses moved/dropped non-Copy storage".into()));
    }
    Ok(())
}

fn operand_local_id(operand: &Operand) -> Option<LocalId> {
    match operand {
        Operand::Local(local) => Some(*local),
        _ => None,
    }
}

#[allow(clippy::too_many_arguments, clippy::too_many_lines)]
fn validate_rvalue(
    function: &MirFunction,
    signatures: &[FunctionInstanceInfo],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
    value: &Rvalue,
    destination: TypeId,
    initialized: &[bool],
) -> Result<(), String> {
    match value {
        Rvalue::Use(operand) => {
            validate_operand(function, operand, initialized)?;
            if operand_type(function, operand)? != destination {
                return Err("MIR copy type mismatch".into());
            }
        }
        Rvalue::Load(place) => {
            validate_place_read(function, place, structs, types, initialized)?;
            if place_type(function, place, structs, types)? != destination {
                return Err("MIR place load type mismatch".into());
            }
        }
        Rvalue::Borrow { place, mutable } => {
            validate_place_read(function, place, structs, types, initialized)?;
            let pointee = place_type(function, place, structs, types)?;
            if types.reference_info(destination) != Some((pointee, *mutable)) {
                return Err("MIR borrow result type/capability mismatch".into());
            }
            if *mutable && matches!(&place.base, PlaceBase::Dereference { mutable: false, .. }) {
                return Err("MIR mutable borrow through shared reference".into());
            }
            if let PlaceBase::Local(local) = &place.base
                && !place_has_index(place)
                && !function.locals[local.0 as usize].address_taken
            {
                return Err("MIR borrowed local is not address-taken".into());
            }
        }
        Rvalue::Move { source } => {
            validate_place_read(function, source, structs, types, initialized)?;
            let source_ty = place_type(function, source, structs, types)?;
            if source_ty != destination
                || types.is_copy(source_ty)
                || !source.projections.is_empty()
            {
                return Err("MIR Move requires one whole move-only owner".into());
            }
        }
        Rvalue::Drop { owner } => {
            validate_place_read(function, owner, structs, types, initialized)?;
            let owner_ty = place_type(function, owner, structs, types)?;
            if destination != TypeId::BOOL
                || !types.needs_drop(owner_ty)
                || !owner.projections.is_empty()
            {
                return Err("MIR Drop contract invalid".into());
            }
        }
        Rvalue::BufferAlloc {
            element_type,
            length,
            initial,
            size_trap,
            failure_trap,
        } => {
            validate_operand(function, length, initialized)?;
            validate_operand(function, initial, initialized)?;
            if types.buffer_element(destination) != Some(*element_type)
                || operand_type(function, length)? != TypeId::USIZE
                || operand_type(function, initial)? != *element_type
                || !types.is_copy(*element_type)
                || types.needs_drop(*element_type)
                || *size_trap != TrapKind::AllocationSizeOverflow
                || *failure_trap != TrapKind::AllocationFailure
            {
                return Err("MIR Buffer allocation contract invalid".into());
            }
        }
        Rvalue::View { source, mutable } => {
            validate_place_read(function, source, structs, types, initialized)?;
            let source_ty = place_type(function, source, structs, types)?;
            let element = types
                .buffer_element(source_ty)
                .ok_or_else(|| "MIR View source is not Buffer".to_string())?;
            if types.view_info(destination) != Some((element, *mutable)) {
                return Err("MIR View contract invalid".into());
            }
        }
        Rvalue::Aggregate { struct_id, fields } => {
            let info = structs
                .get(struct_id.0 as usize)
                .filter(|info| info.id == *struct_id)
                .ok_or_else(|| "MIR aggregate names unknown struct".to_string())?;
            if types.struct_id(destination) != Some(*struct_id) || fields.len() != info.fields.len()
            {
                return Err("MIR aggregate arity/result mismatch".into());
            }
            for ((field_id, operand), declared) in fields.iter().zip(&info.fields) {
                validate_operand(function, operand, initialized)?;
                let expected = concrete_struct_member(types, structs, destination, declared.ty)?;
                if *field_id != declared.id || operand_type(function, operand)? != expected {
                    return Err("MIR aggregate field identity/type mismatch".into());
                }
            }
        }
        Rvalue::EnumConstruct {
            enum_id,
            variant_id,
            payloads,
        } => {
            let info = enums
                .get(enum_id.0 as usize)
                .filter(|info| info.id == *enum_id)
                .ok_or_else(|| "MIR enum construction names unknown enum".to_string())?;
            let variant = info
                .variants
                .get(variant_id.index as usize)
                .filter(|variant| variant.id == *variant_id)
                .ok_or_else(|| "MIR enum construction names wrong variant".to_string())?;
            if types.enum_id(destination) != Some(*enum_id)
                || payloads.len() != variant.payloads.len()
            {
                return Err("MIR enum construction arity/result mismatch".into());
            }
            for (operand, declared) in payloads.iter().zip(&variant.payloads) {
                validate_operand(function, operand, initialized)?;
                let expected = concrete_enum_member(types, enums, destination, declared.ty)?;
                if operand_type(function, operand)? != expected {
                    return Err("MIR enum payload type mismatch".into());
                }
            }
        }
        Rvalue::EnumDiscriminant {
            value,
            enum_id,
            mode,
        } => {
            validate_operand(function, value, initialized)?;
            let value_ty = operand_type(function, value)?;
            let enum_ty = match mode {
                MatchMode::Value => value_ty,
                MatchMode::SharedRef => types
                    .reference_info(value_ty)
                    .filter(|(_, mutable)| !*mutable)
                    .map(|(pointee, _)| pointee)
                    .ok_or_else(|| {
                        "MIR shared-ref match discriminant is not a shared reference".to_string()
                    })?,
                MatchMode::MutableRef => types
                    .reference_info(value_ty)
                    .filter(|(_, mutable)| *mutable)
                    .map(|(pointee, _)| pointee)
                    .ok_or_else(|| {
                        "MIR ref-mut match discriminant is not a mutable reference".to_string()
                    })?,
            };
            if enums.get(enum_id.0 as usize).map(|info| info.id) != Some(*enum_id)
                || types.enum_id(enum_ty) != Some(*enum_id)
                || destination != TypeId::UINT32
            {
                return Err("MIR enum discriminant contract invalid".into());
            }
        }
        Rvalue::EnumPayload {
            value,
            enum_id,
            variant_id,
            index,
            mode,
        } => {
            validate_operand(function, value, initialized)?;
            let info = enums
                .get(enum_id.0 as usize)
                .filter(|info| info.id == *enum_id)
                .ok_or_else(|| "MIR enum payload names unknown enum".to_string())?;
            let variant = info
                .variants
                .get(variant_id.index as usize)
                .filter(|variant| variant.id == *variant_id)
                .ok_or_else(|| "MIR enum payload names wrong variant".to_string())?;
            let payload = variant
                .payloads
                .get(*index as usize)
                .ok_or_else(|| "MIR enum payload slot out of bounds".to_string())?;
            let value_ty = operand_type(function, value)?;
            let enum_ty = match mode {
                MatchMode::Value => value_ty,
                MatchMode::SharedRef => types
                    .reference_info(value_ty)
                    .filter(|(_, mutable)| !*mutable)
                    .map(|(pointee, _)| pointee)
                    .ok_or_else(|| {
                        "MIR shared payload source is not a shared reference".to_string()
                    })?,
                MatchMode::MutableRef => types
                    .reference_info(value_ty)
                    .filter(|(_, mutable)| *mutable)
                    .map(|(pointee, _)| pointee)
                    .ok_or_else(|| {
                        "MIR mutable payload source is not a mutable reference".to_string()
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
                    .ok_or_else(|| "MIR shared payload reference type missing".to_string())?,
                MatchMode::MutableRef => types
                    .id_of(TypeData::Reference {
                        pointee: payload_ty,
                        mutable: true,
                    })
                    .ok_or_else(|| "MIR mutable payload reference type missing".to_string())?,
            };
            if types.enum_id(enum_ty) != Some(*enum_id) || destination != expected {
                return Err("MIR enum payload extraction type mismatch".into());
            }
        }
        Rvalue::ConsumeEnum { owner } => {
            validate_place_read(function, owner, structs, types, initialized)?;
            let owner_ty = place_type(function, owner, structs, types)?;
            if destination != TypeId::BOOL
                || types.enum_id(owner_ty).is_none()
                || types.is_copy(owner_ty)
                || !owner.projections.is_empty()
            {
                return Err("MIR consuming enum match contract invalid".into());
            }
        }
        Rvalue::Coerce {
            kind,
            operand,
            from,
        } => {
            validate_operand(function, operand, initialized)?;
            if operand_type(function, operand)? != *from
                || !valid_coercion(types, *kind, *from, destination)
            {
                return Err("invalid MIR coercion contract".into());
            }
        }
        Rvalue::Cast {
            kind,
            operand,
            from,
            trap,
        } => {
            validate_operand(function, operand, initialized)?;
            let required_trap =
                cast_can_fail(types, *from, destination).then_some(TrapKind::ConversionOutOfRange);
            if operand_type(function, operand)? != *from
                || !valid_cast(types, *kind, *from, destination)
                || *trap != required_trap
            {
                return Err("invalid MIR explicit-cast contract".into());
            }
        }
        Rvalue::Unary { op, operand, trap } => {
            validate_operand(function, operand, initialized)?;
            let operand_ty = operand_type(function, operand)?;
            let valid = match op {
                UnaryOp::NegateIntegerChecked => types
                    .integer_info(operand_ty)
                    .is_some_and(aether_frontend::IntegerType::is_signed),
                UnaryOp::NegateFloat => types.float_info(operand_ty).is_some(),
            };
            let required_trap =
                matches!(op, UnaryOp::NegateIntegerChecked).then_some(TrapKind::IntegerOverflow);
            if destination != operand_ty || !valid || *trap != required_trap {
                return Err("invalid checked-negation MIR contract".into());
            }
        }
        Rvalue::Binary {
            op,
            left,
            right,
            trap,
            secondary_trap,
        } => {
            validate_operand(function, left, initialized)?;
            validate_operand(function, right, initialized)?;
            let left_ty = operand_type(function, left)?;
            let right_ty = operand_type(function, right)?;
            if left_ty != right_ty {
                return Err("MIR binary operands have different types".into());
            }
            let (required_operand, result, required_trap, required_secondary) =
                binary_contract(types, *op, left_ty)?;
            if left_ty != required_operand
                || destination != result
                || *trap != required_trap
                || *secondary_trap != required_secondary
            {
                return Err(format!(
                    "MIR binary operation {op:?} violates its type/trap contract"
                ));
            }
        }
        Rvalue::Call { callee, args } => {
            let signature = signatures
                .get(callee.0 as usize)
                .filter(|signature| signature.id == *callee)
                .ok_or_else(|| format!("MIR call target {callee:?} does not exist"))?;
            if args.len() != signature.parameters.len() || destination != signature.return_type {
                return Err("MIR call result/arity violates its signature".into());
            }
            for (argument, parameter) in args.iter().zip(&signature.parameters) {
                validate_operand(function, argument, initialized)?;
                if operand_type(function, argument)? != parameter.ty {
                    return Err("MIR call argument type mismatch".into());
                }
            }
        }
    }
    Ok(())
}

fn validate_place_read(
    function: &MirFunction,
    place: &Place,
    structs: &[StructInfo],
    types: &TypeArena,
    initialized: &[bool],
) -> Result<(), String> {
    place_type(function, place, structs, types)?;
    match &place.base {
        PlaceBase::Local(local) => {
            if !initialized.get(local.0 as usize).copied().unwrap_or(false) {
                return Err(format!("MIR local {local:?} is read before initialization"));
            }
        }
        PlaceBase::Dereference { reference, .. } => {
            validate_operand(function, reference, initialized)?;
        }
    }
    for projection in &place.projections {
        if let PlaceProjection::Index { index, .. } = projection {
            validate_operand(function, index, initialized)?;
        }
    }
    Ok(())
}

fn place_has_index(place: &Place) -> bool {
    place
        .projections
        .iter()
        .any(|projection| matches!(projection, PlaceProjection::Index { .. }))
}

fn place_type(
    function: &MirFunction,
    place: &Place,
    structs: &[StructInfo],
    types: &TypeArena,
) -> Result<TypeId, String> {
    let mut ty = match &place.base {
        PlaceBase::Local(local) => function
            .locals
            .get(local.0 as usize)
            .map(|local| local.ty)
            .ok_or_else(|| format!("unknown MIR place local {local:?}"))?,
        PlaceBase::Dereference { reference, mutable } => {
            let reference_ty = operand_type(function, reference)?;
            let (pointee, capability) = types
                .reference_info(reference_ty)
                .ok_or_else(|| "MIR place dereferences non-reference operand".to_string())?;
            if capability != *mutable {
                return Err("MIR dereference capability cache mismatch".into());
            }
            pointee
        }
    };
    for projection in &place.projections {
        match projection {
            PlaceProjection::Field(field_id) => {
                let owner = types
                    .struct_id(ty)
                    .ok_or_else(|| "MIR place projects non-struct type".to_string())?;
                let field = structs
                    .get(owner.0 as usize)
                    .and_then(|info| info.fields.iter().find(|field| field.id == *field_id))
                    .ok_or_else(|| "MIR place field does not belong to aggregate".to_string())?;
                ty = concrete_struct_member(types, structs, ty, field.ty)?;
            }
            PlaceProjection::Index {
                index,
                element_type,
                bounds_trap,
            } => {
                let element = types
                    .buffer_element(ty)
                    .or_else(|| types.view_info(ty).map(|(element, _)| element))
                    .ok_or_else(|| "MIR index projection has non-contiguous base".to_string())?;
                if operand_type(function, index)? != TypeId::USIZE
                    || element != *element_type
                    || *bounds_trap != TrapKind::IndexOutOfBounds
                {
                    return Err("MIR index projection contract invalid".into());
                }
                ty = element;
            }
        }
    }
    Ok(ty)
}

fn place_root_local(place: &Place) -> Option<LocalId> {
    match &place.base {
        PlaceBase::Local(local) => Some(*local),
        PlaceBase::Dereference { .. } => None,
    }
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

pub(crate) fn binary_contract(
    types: &TypeArena,
    op: BinaryOp,
    operand: TypeId,
) -> Result<(TypeId, TypeId, Option<TrapKind>, Option<TrapKind>), String> {
    match op {
        BinaryOp::AddIntegerChecked
        | BinaryOp::SubtractIntegerChecked
        | BinaryOp::MultiplyIntegerChecked
            if types.integer_info(operand).is_some() =>
        {
            Ok((operand, operand, Some(TrapKind::IntegerOverflow), None))
        }
        BinaryOp::DivideIntegerSignedChecked
            if types
                .integer_info(operand)
                .is_some_and(aether_frontend::IntegerType::is_signed) =>
        {
            Ok((
                operand,
                operand,
                Some(TrapKind::DivisionByZero),
                Some(TrapKind::DivisionOverflow),
            ))
        }
        BinaryOp::DivideIntegerUnsignedChecked | BinaryOp::RemainderIntegerUnsignedChecked
            if types
                .integer_info(operand)
                .is_some_and(|integer| !integer.is_signed()) =>
        {
            Ok((operand, operand, Some(TrapKind::DivisionByZero), None))
        }
        BinaryOp::RemainderIntegerSignedChecked
            if types
                .integer_info(operand)
                .is_some_and(aether_frontend::IntegerType::is_signed) =>
        {
            Ok((operand, operand, Some(TrapKind::DivisionByZero), None))
        }
        BinaryOp::AddFloat
        | BinaryOp::SubtractFloat
        | BinaryOp::MultiplyFloat
        | BinaryOp::DivideFloat
            if types.float_info(operand).is_some() =>
        {
            Ok((operand, operand, None, None))
        }
        BinaryOp::Less | BinaryOp::LessEqual | BinaryOp::Greater | BinaryOp::GreaterEqual => {
            if types.is_numeric(operand) {
                Ok((operand, TypeId::BOOL, None, None))
            } else {
                Err("ordered comparison requires numeric operands".into())
            }
        }
        BinaryOp::Equal | BinaryOp::NotEqual
            if operand == TypeId::BOOL || types.is_numeric(operand) =>
        {
            Ok((operand, TypeId::BOOL, None, None))
        }
        _ => Err("MIR numeric opcode/type mismatch".into()),
    }
}

fn validate_operand(
    function: &MirFunction,
    operand: &Operand,
    initialized: &[bool],
) -> Result<(), String> {
    if let Operand::Local(local) = operand {
        let Some(info) = function.locals.get(local.0 as usize) else {
            return Err(format!("MIR operand local {local:?} does not exist"));
        };
        if info.address_taken {
            return Err(format!(
                "address-taken MIR local {local:?} must be read through a Place load"
            ));
        }
        if !initialized.get(local.0 as usize).copied().unwrap_or(false) {
            return Err(format!("MIR local {local:?} is read before initialization"));
        }
    }
    Ok(())
}

fn operand_type(function: &MirFunction, operand: &Operand) -> Result<TypeId, String> {
    match operand {
        Operand::Local(local) => function
            .locals
            .get(local.0 as usize)
            .map(|local| local.ty)
            .ok_or_else(|| format!("unknown MIR local {local:?}")),
        Operand::Int { ty, .. } | Operand::Float { ty, .. } => Ok(*ty),
        Operand::Bool(_) => Ok(TypeId::BOOL),
    }
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

pub(crate) fn valid_cast(types: &TypeArena, kind: CastKind, from: TypeId, to: TypeId) -> bool {
    use aether_frontend::TargetProperties;
    let target = TargetProperties::LINUX_X86_64;
    let from_integer = types.integer_info(from);
    let to_integer = types.integer_info(to);
    let from_float = types.float_info(from);
    let to_float = types.float_info(to);
    match kind {
        CastKind::Identity => from == to && from != TypeId::BOOL,
        CastKind::IntegerExtendSigned if let (Some(a), Some(b)) = (from_integer, to_integer) => {
            a.is_signed() && b.is_signed() && a.bits(target) < b.bits(target)
        }
        CastKind::IntegerExtendUnsigned if let (Some(a), Some(b)) = (from_integer, to_integer) => {
            !a.is_signed() && !b.is_signed() && a.bits(target) < b.bits(target)
        }
        CastKind::IntegerNarrowChecked if let (Some(a), Some(b)) = (from_integer, to_integer) => {
            a.is_signed() == b.is_signed() && a.bits(target) > b.bits(target)
        }
        CastKind::IntegerReencode if let (Some(a), Some(b)) = (from_integer, to_integer) => {
            a != b && a.is_signed() == b.is_signed() && a.bits(target) == b.bits(target)
        }
        CastKind::IntegerSignednessChecked
            if let (Some(a), Some(b)) = (from_integer, to_integer) =>
        {
            a.is_signed() != b.is_signed()
        }
        CastKind::SignedIntegerToFloat if to_float.is_some() => {
            from_integer.is_some_and(aether_frontend::IntegerType::is_signed)
        }
        CastKind::UnsignedIntegerToFloat if to_float.is_some() => {
            from_integer.is_some_and(|a| !a.is_signed())
        }
        CastKind::FloatToSignedIntegerChecked if from_float.is_some() => {
            to_integer.is_some_and(aether_frontend::IntegerType::is_signed)
        }
        CastKind::FloatToUnsignedIntegerChecked if from_float.is_some() => {
            to_integer.is_some_and(|b| !b.is_signed())
        }
        CastKind::FloatExtend => from == TypeId::FLOAT32 && to == TypeId::FLOAT64,
        CastKind::FloatTruncate => from == TypeId::FLOAT64 && to == TypeId::FLOAT32,
        _ => false,
    }
}

pub(crate) fn cast_can_fail(types: &TypeArena, from: TypeId, to: TypeId) -> bool {
    use aether_frontend::TargetProperties;
    match (types.get(from), types.get(to)) {
        (Some(TypeData::Integer(a)), Some(TypeData::Integer(b))) => {
            let target = TargetProperties::LINUX_X86_64;
            let (source_min, source_max) = a.range(target);
            let (target_min, target_max) = b.range(target);
            source_min < target_min || source_max > target_max
        }
        (Some(TypeData::Float(_)), Some(TypeData::Integer(_))) => true,
        _ => false,
    }
}

fn targets(terminator: &Terminator) -> Vec<BlockId> {
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
        Terminator::Return(_) | Terminator::Trap(_) => Vec::new(),
    }
}

fn reachability(function: &MirFunction) -> Vec<bool> {
    let mut reachable = vec![false; function.blocks.len()];
    let mut queue = VecDeque::from([function.entry]);
    while let Some(block) = queue.pop_front() {
        if reachable[block.0 as usize] {
            continue;
        }
        reachable[block.0 as usize] = true;
        if let Some(terminator) = &function.blocks[block.0 as usize].terminator {
            queue.extend(targets(terminator));
        }
    }
    reachable
}

fn block_reaches(function: &MirFunction, start: BlockId, target: BlockId) -> bool {
    let mut seen = vec![false; function.blocks.len()];
    let mut queue = VecDeque::from([start]);
    while let Some(block) = queue.pop_front() {
        if block == target {
            return true;
        }
        if seen[block.0 as usize] {
            continue;
        }
        seen[block.0 as usize] = true;
        if let Some(terminator) = &function.blocks[block.0 as usize].terminator {
            queue.extend(targets(terminator));
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use aether_frontend::{
        FunctionId, FunctionInstanceInfo, InstanceId, ModuleId, ModuleInfo, SourceFile, SourceId,
        analyze, parse_source,
    };

    use super::*;

    fn mir(text: &str) -> FlowMir {
        lower_hir(analyze(parse_source(&SourceFile::new("test.ae", text)).unwrap()).unwrap())
    }

    #[test]
    fn loop_has_real_cfg_and_checked_trap_effects() {
        let mir = mir("int main(){int i=0;while(i<3){i=i+1;}return i;}");
        assert!(mir.functions[0].blocks.len() >= 4);
        assert!(
            mir.functions[0]
                .blocks
                .iter()
                .flat_map(|block| &block.instructions)
                .any(|instruction| {
                    matches!(
                        instruction.value,
                        Rvalue::Binary {
                            op: BinaryOp::AddIntegerChecked,
                            trap: Some(TrapKind::IntegerOverflow),
                            ..
                        }
                    )
                })
        );
        verify_mir(mir).unwrap();
    }

    #[test]
    fn verifier_rejects_missing_terminator_and_bad_types() {
        let mut missing = mir("int main(){return 0;}");
        missing.functions[0].blocks[0].terminator = None;
        assert!(verify_mir(missing).is_err());

        let mut bad = mir("int main(){return 0;}");
        bad.functions[0].blocks[0].terminator = Some(Terminator::Return(Operand::Bool(false)));
        assert!(verify_mir(bad).is_err());

        let mut invalid = mir("int main(){int x=0;return x;}");
        invalid.functions[0].locals[0].ty = TypeId(u32::MAX);
        assert!(verify_mir(invalid).is_err());
    }

    #[test]
    fn conditional_drop_flags_are_sparse_and_transitions_fail_closed() {
        let source = "int take(Buffer<int> value){return value[0];}int main(){Buffer<int> value=Buffer<int>(1,0);if(true){int used=take(value);}return 0;}";
        let raw = mir(source);
        assert_eq!(raw.functions[1].drop_flags.len(), 1);
        verify_mir(raw.clone()).unwrap();

        let mut stale = raw.clone();
        let flag = stale.functions[1].drop_flags[0].flag;
        let block = stale.functions[1]
            .blocks
            .iter_mut()
            .find(|block| {
                block
                    .instructions
                    .iter()
                    .filter(|instruction| place_root_local(&instruction.destination) == Some(flag))
                    .count()
                    > 1
            })
            .unwrap();
        let update = block
            .instructions
            .iter()
            .rposition(|instruction| place_root_local(&instruction.destination) == Some(flag))
            .unwrap();
        block.instructions.remove(update);
        assert!(verify_mir(stale).is_err());

        let mut invalid = raw;
        invalid.functions[1].drop_flags[0].flag = invalid.functions[1].drop_flags[0].owner;
        assert!(verify_mir(invalid).is_err());
    }

    #[test]
    fn trap_terminator_represents_division_failure() {
        let raw = FlowMir {
            types: Arc::new(TypeArena::new()),
            modules: vec![ModuleInfo {
                id: ModuleId(0),
                name: "main".into(),
                source: SourceId(0),
                source_name: "<memory>".into(),
                imports: vec![],
            }],
            structs: vec![],
            enums: vec![],
            signatures: vec![FunctionInstanceInfo {
                id: InstanceId(0),
                function_id: FunctionId(0),
                module: ModuleId(0),
                name: "main".into(),
                type_arguments: vec![],
                parameters: vec![],
                return_type: TypeId::INT64,
                span: Span::new(0, 0),
            }],
            functions: vec![MirFunction {
                id: InstanceId(0),
                function_id: FunctionId(0),
                parameters: vec![],
                drop_flags: vec![],
                return_type: TypeId::INT64,
                locals: vec![],
                blocks: vec![BasicBlock {
                    id: BlockId(0),
                    instructions: vec![],
                    terminator: Some(Terminator::Trap(TrapKind::DivisionByZero)),
                }],
                entry: BlockId(0),
            }],
            entry: InstanceId(0),
        };
        verify_mir(raw).unwrap();
    }

    #[test]
    fn calls_and_parameters_are_explicit_and_verified() {
        let raw = mir("int add(int a,int b){return a+b;}int main(){return add(20,22);}");
        assert_eq!(raw.functions.len(), 2);
        assert_eq!(raw.functions[0].parameters.len(), 2);
        assert!(
            raw.functions[1]
                .blocks
                .iter()
                .flat_map(|block| &block.instructions)
                .any(|instruction| matches!(
                    instruction.value,
                    Rvalue::Call {
                        callee: InstanceId(0),
                        ..
                    }
                ))
        );
        verify_mir(raw).unwrap();
    }

    #[test]
    fn verifier_rejects_corrupt_direct_call_contracts() {
        let mut unknown = mir("int id(int x){return x;}int main(){return id(1);}");
        let call = unknown.functions[1]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.value, Rvalue::Call { .. }))
            .unwrap();
        if let Rvalue::Call { callee, .. } = &mut call.value {
            *callee = InstanceId(99);
        }
        assert!(verify_mir(unknown).is_err());

        let mut arity = mir("int id(int x){return x;}int main(){return id(1);}");
        let call = arity.functions[1]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.value, Rvalue::Call { .. }))
            .unwrap();
        if let Rvalue::Call { args, .. } = &mut call.value {
            args.clear();
        }
        assert!(verify_mir(arity).is_err());
    }

    #[test]
    fn verifier_rejects_corrupt_cast_and_division_contracts() {
        let mut cast = mir("int8 narrow(int64 x){return int8(x);}int main(){return narrow(1);}");
        let instruction = cast.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.value, Rvalue::Cast { .. }))
            .unwrap();
        if let Rvalue::Cast { kind, .. } = &mut instruction.value {
            *kind = CastKind::Identity;
        }
        assert!(verify_mir(cast).is_err());

        let mut division =
            mir("int64 divide(int64 a,int64 b){return a/b;}int main(){return divide(4,2);}");
        let instruction = division.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.value, Rvalue::Binary { .. }))
            .unwrap();
        if let Rvalue::Binary { secondary_trap, .. } = &mut instruction.value {
            *secondary_trap = None;
        }
        assert!(verify_mir(division).is_err());
    }

    #[test]
    fn aggregate_places_and_field_ids_are_verified() {
        let mut raw = mir("struct P{int x;}int main(){P p=P(1);p.x=2;return p.x;}");
        let store = raw.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| !instruction.destination.projections.is_empty())
            .unwrap();
        store.destination.projections[0] = PlaceProjection::Field(aether_frontend::FieldId(999));
        assert!(verify_mir(raw).is_err());

        let mut raw = mir("struct P{int x;}int main(){P p=P(1);return p.x;}");
        let aggregate = raw.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.value, Rvalue::Aggregate { .. }))
            .unwrap();
        if let Rvalue::Aggregate { fields, .. } = &mut aggregate.value {
            fields[0].0 = aether_frontend::FieldId(999);
        }
        assert!(verify_mir(raw).is_err());
    }

    #[test]
    fn buffer_ownership_and_index_contracts_fail_closed() {
        let mut leaked = mir("int main(){Buffer<int> values=Buffer<int>(1,7);return values[0];}");
        for block in &mut leaked.functions[0].blocks {
            block
                .instructions
                .retain(|instruction| !matches!(instruction.value, Rvalue::Drop { .. }));
        }
        assert!(verify_mir(leaked).is_err());

        let mut copied = mir(
            "int main(){Buffer<int> source=Buffer<int>(1,7);Buffer<int> destination=source;return destination[0];}",
        );
        let ownership_move = copied.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.value, Rvalue::Move { .. }))
            .unwrap();
        let Rvalue::Move { source } = &ownership_move.value else {
            unreachable!()
        };
        let PlaceBase::Local(source) = source.base else {
            unreachable!()
        };
        ownership_move.value = Rvalue::Use(Operand::Local(source));
        assert!(verify_mir(copied).is_err());

        let mut unchecked =
            mir("int main(){Buffer<int> values=Buffer<int>(1,7);return values[0];}");
        let index = unchecked.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find_map(|instruction| match &mut instruction.value {
                Rvalue::Load(place) => {
                    place
                        .projections
                        .iter_mut()
                        .find_map(|projection| match projection {
                            PlaceProjection::Index { bounds_trap, .. } => Some(bounds_trap),
                            PlaceProjection::Field(_) => None,
                        })
                }
                _ => None,
            })
            .unwrap();
        *index = TrapKind::DivisionByZero;
        assert!(verify_mir(unchecked).is_err());

        let mut invalid_element = mir("int main(){return 0;}");
        let types = Arc::make_mut(&mut invalid_element.types);
        let inner = types.intern_buffer(TypeId::INT64);
        types.intern_buffer(inner);
        assert!(verify_mir(invalid_element).is_err());
    }

    #[test]
    fn enum_switch_and_payload_contracts_are_verified() {
        let source =
            "enum E{A,B(int),}int main(){E e=E.B(7);match(e){E.A=>{return 0;}E.B(x)=>{return x;}}}";
        let raw = mir(source);
        assert!(
            raw.functions[0]
                .blocks
                .iter()
                .any(|block| matches!(block.terminator, Some(Terminator::Switch { .. })))
        );
        verify_mir(raw).unwrap();

        let mut bad_switch = mir(source);
        let switch = bad_switch.functions[0]
            .blocks
            .iter_mut()
            .find_map(|block| {
                if let Some(Terminator::Switch { cases, .. }) = &mut block.terminator {
                    Some(cases)
                } else {
                    None
                }
            })
            .unwrap();
        switch.pop();
        assert!(verify_mir(bad_switch).is_err());

        let mut bad_payload = mir(source);
        let extraction = bad_payload.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find(|instruction| matches!(instruction.value, Rvalue::EnumPayload { .. }))
            .unwrap();
        if let Rvalue::EnumPayload { index, .. } = &mut extraction.value {
            *index = 99;
        }
        assert!(verify_mir(bad_payload).is_err());
    }
}
