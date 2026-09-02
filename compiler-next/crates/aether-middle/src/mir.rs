//! Explicit control-flow MIR and fail-closed verification.
#![allow(missing_docs)]

use std::collections::VecDeque;
use std::fmt::Write;

use aether_frontend::{
    CastKind, CoercionKind, Diagnostic, DiagnosticCategory, FieldId, FloatValue, FunctionId,
    FunctionSignature, HirBinaryOp, HirBlock, HirExpr, HirExprKind, HirFunction, HirPlace,
    HirStmtKind, HirUnaryOp, LocalId, ModuleInfo, Phase, Span, StructId, StructInfo, Type,
    TypedHir,
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
    pub ty: Type,
    /// Source name when this is user storage.
    pub name: Option<String>,
    /// Whether lowering introduced the slot.
    pub temporary: bool,
}

/// A parameter's local storage identity and type.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MirParameter {
    /// Function-local identity initialized by the call boundary.
    pub local: LocalId,
    /// Canonical semantic type.
    pub ty: Type,
}

/// Reusable assignable storage path. Future projections can add indexing and
/// dereference without changing assignment into a special-case operation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Place {
    pub local: LocalId,
    pub projections: Vec<FieldId>,
}

/// MIR operand for scalar or aggregate values.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Operand {
    /// Storage read.
    Local(LocalId),
    /// Signed 64-bit constant.
    Int { value: i128, ty: Type },
    /// IEEE literal bits and exact canonical type.
    Float { value: FloatValue, ty: Type },
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
    /// Construct a nominal aggregate in declaration/FieldId order.
    Aggregate {
        struct_id: StructId,
        fields: Vec<(FieldId, Operand)>,
    },
    /// Explicit semantic widening.
    Coerce {
        kind: CoercionKind,
        operand: Operand,
        from: Type,
    },
    /// Explicit value conversion selected and typed in HIR.
    Cast {
        kind: CastKind,
        operand: Operand,
        from: Type,
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
        callee: FunctionId,
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
    pub id: FunctionId,
    /// Parameters in call order.
    pub parameters: Vec<MirParameter>,
    /// Canonical return type.
    pub return_type: Type,
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
    /// Resolved program module graph and provenance.
    pub modules: Vec<ModuleInfo>,
    /// Nominal aggregate and field metadata.
    pub structs: Vec<StructInfo>,
    /// Program-global signature table.
    pub signatures: Vec<FunctionSignature>,
    /// Function-local CFGs in stable identity order.
    pub functions: Vec<MirFunction>,
    /// Entry function identity.
    pub entry: FunctionId,
}

impl FlowMir {
    /// Deterministic inspection dump.
    #[must_use]
    pub fn dump(&self) -> String {
        let mut dump = format!(
            "entry: {:#?}\nmodules: {:#?}\nstructs: {:#?}\nsignatures: {:#?}",
            self.entry, self.modules, self.structs, self.signatures
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
    let (modules, structs, signatures, functions, entry) = hir.into_parts();
    let functions = functions
        .iter()
        .map(|function| {
            let return_type = signatures[function.id.0 as usize].return_type;
            lower_function(function, return_type)
        })
        .collect();
    FlowMir {
        modules,
        structs,
        signatures,
        functions,
        entry,
    }
}

fn lower_function(function: &HirFunction, return_type: Type) -> MirFunction {
    let locals = function
        .locals
        .iter()
        .map(|local| MirLocal {
            id: local.id,
            ty: local.ty,
            name: Some(local.name.clone()),
            temporary: false,
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
    let mut builder = Builder {
        function: MirFunction {
            id: function.id,
            parameters,
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
    };
    builder.lower_block(&function.body);
    builder.function
}

struct Builder {
    function: MirFunction,
    current: Option<BlockId>,
}

impl Builder {
    fn lower_block(&mut self, block: &HirBlock) {
        for statement in &block.statements {
            match &statement.kind {
                HirStmtKind::Local { local, initializer } => {
                    let value = self.lower_expr(initializer);
                    self.assign(
                        Place {
                            local: *local,
                            projections: vec![],
                        },
                        Rvalue::Use(value),
                        statement.span,
                    );
                }
                HirStmtKind::Assign { place, value } => {
                    let value = self.lower_expr(value);
                    self.assign(lower_place(place), Rvalue::Use(value), statement.span);
                }
                HirStmtKind::Return(value) => {
                    let value = self.lower_expr(value);
                    self.terminate(Terminator::Return(value));
                }
                HirStmtKind::If {
                    condition,
                    then_block,
                    else_block,
                } => self.lower_if(condition, then_block, else_block.as_ref()),
                HirStmtKind::While { condition, body } => self.lower_while(condition, body),
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
            HirExprKind::Local(local) => Operand::Local(*local),
            HirExprKind::Load(place) => {
                let destination = self.temporary(expression.ty);
                self.assign(
                    Place {
                        local: destination,
                        projections: vec![],
                    },
                    Rvalue::Load(lower_place(place)),
                    expression.span,
                );
                Operand::Local(destination)
            }
            HirExprKind::Call { callee, args } => {
                let args = args
                    .iter()
                    .map(|argument| self.lower_expr(argument))
                    .collect();
                let destination = self.temporary(expression.ty);
                self.assign(
                    Place {
                        local: destination,
                        projections: vec![],
                    },
                    Rvalue::Call {
                        callee: *callee,
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
                        local: destination,
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
            HirExprKind::Coerce { kind, operand } => {
                let from = operand.ty;
                let operand = self.lower_expr(operand);
                let destination = self.temporary(expression.ty);
                self.assign(
                    Place {
                        local: destination,
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
                let trap = cast_can_fail(*source_type, *target_type)
                    .then_some(TrapKind::ConversionOutOfRange);
                self.assign(
                    Place {
                        local: destination,
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
                        local: destination,
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
                        local: destination,
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

    fn temporary(&mut self, ty: Type) -> LocalId {
        let id = LocalId(u32::try_from(self.function.locals.len()).expect("local count fits u32"));
        self.function.locals.push(MirLocal {
            id,
            ty,
            name: None,
            temporary: true,
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

    fn terminate(&mut self, terminator: Terminator) {
        let block = self.current.take().expect("current block is open");
        self.function.blocks[block.0 as usize].terminator = Some(terminator);
    }
}

fn lower_place(place: &HirPlace) -> Place {
    Place {
        local: place.local,
        projections: place.projections.clone(),
    }
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
    for (index, (signature, function)) in mir.signatures.iter().zip(&mir.functions).enumerate() {
        if signature.id.0 as usize != index || function.id != signature.id {
            return Err(fail("MIR function identities are not canonical".into()));
        }
        if signature.module.0 as usize >= mir.modules.len() {
            return Err(fail("MIR signature names an unknown module".into()));
        }
        verify_mir_function(function, signature, &mir.signatures, &mir.structs, &fail)?;
    }
    Ok(VerifiedMir(mir))
}

#[allow(clippy::too_many_lines)]
fn verify_mir_function(
    function: &MirFunction,
    signature: &FunctionSignature,
    signatures: &[FunctionSignature],
    structs: &[StructInfo],
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
                    outgoing[instruction.destination.local.0 as usize] = true;
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
            let Some(destination) = function
                .locals
                .get(instruction.destination.local.0 as usize)
            else {
                return Err(fail(format!(
                    "assignment destination {:?} does not exist",
                    instruction.destination
                )));
            };
            if !instruction.destination.projections.is_empty()
                && !initialized[instruction.destination.local.0 as usize]
            {
                return Err(fail(
                    "MIR projected store reads an uninitialized aggregate".into(),
                ));
            }
            if !instruction.destination.projections.is_empty()
                && !matches!(instruction.value, Rvalue::Use(_))
            {
                return Err(fail(
                    "MIR projected store requires a materialized value operand".into(),
                ));
            }
            let destination_ty =
                place_type(function, &instruction.destination, structs).map_err(&fail)?;
            validate_rvalue(
                function,
                signatures,
                structs,
                &instruction.value,
                destination_ty,
                &initialized,
            )
            .map_err(&fail)?;
            let _ = destination;
            initialized[instruction.destination.local.0 as usize] = true;
        }
        let terminator = block.terminator.as_ref().expect("checked above");
        match terminator {
            Terminator::Branch { condition, .. } => {
                validate_operand(function, condition, &initialized)
                    .map_err(|message| fail(message.clone()))?;
                if operand_type(function, condition).map_err(|message| fail(message.clone()))?
                    != Type::Bool
                {
                    return Err(fail("MIR branch condition is not bool".into()));
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
fn validate_rvalue(
    function: &MirFunction,
    signatures: &[FunctionSignature],
    structs: &[StructInfo],
    value: &Rvalue,
    destination: Type,
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
            validate_place_read(function, place, structs, initialized)?;
            if place_type(function, place, structs)? != destination {
                return Err("MIR place load type mismatch".into());
            }
        }
        Rvalue::Aggregate { struct_id, fields } => {
            let info = structs
                .get(struct_id.0 as usize)
                .filter(|info| info.id == *struct_id)
                .ok_or_else(|| "MIR aggregate names unknown struct".to_string())?;
            if destination != Type::Struct(*struct_id) || fields.len() != info.fields.len() {
                return Err("MIR aggregate arity/result mismatch".into());
            }
            for ((field_id, operand), declared) in fields.iter().zip(&info.fields) {
                validate_operand(function, operand, initialized)?;
                if *field_id != declared.id || operand_type(function, operand)? != declared.ty {
                    return Err("MIR aggregate field identity/type mismatch".into());
                }
            }
        }
        Rvalue::Coerce {
            kind,
            operand,
            from,
        } => {
            validate_operand(function, operand, initialized)?;
            if operand_type(function, operand)? != *from
                || !valid_coercion(*kind, *from, destination)
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
                cast_can_fail(*from, destination).then_some(TrapKind::ConversionOutOfRange);
            if operand_type(function, operand)? != *from
                || !valid_cast(*kind, *from, destination)
                || *trap != required_trap
            {
                return Err("invalid MIR explicit-cast contract".into());
            }
        }
        Rvalue::Unary { op, operand, trap } => {
            validate_operand(function, operand, initialized)?;
            let operand_ty = operand_type(function, operand)?;
            let valid = match op {
                UnaryOp::NegateIntegerChecked => operand_ty
                    .as_integer()
                    .is_some_and(aether_frontend::IntegerType::is_signed),
                UnaryOp::NegateFloat => operand_ty.as_float().is_some(),
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
                binary_contract(*op, left_ty)?;
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
    initialized: &[bool],
) -> Result<(), String> {
    place_type(function, place, structs)?;
    if !initialized
        .get(place.local.0 as usize)
        .copied()
        .unwrap_or(false)
    {
        return Err(format!(
            "MIR local {:?} is read before initialization",
            place.local
        ));
    }
    Ok(())
}

fn place_type(
    function: &MirFunction,
    place: &Place,
    structs: &[StructInfo],
) -> Result<Type, String> {
    let mut ty = function
        .locals
        .get(place.local.0 as usize)
        .map(|local| local.ty)
        .ok_or_else(|| format!("unknown MIR place local {:?}", place.local))?;
    for field_id in &place.projections {
        let owner = ty
            .as_struct()
            .ok_or_else(|| "MIR place projects non-struct type".to_string())?;
        let field = structs
            .get(owner.0 as usize)
            .and_then(|info| info.fields.iter().find(|field| field.id == *field_id))
            .ok_or_else(|| "MIR place field does not belong to aggregate".to_string())?;
        ty = field.ty;
    }
    Ok(ty)
}

pub(crate) fn binary_contract(
    op: BinaryOp,
    operand: Type,
) -> Result<(Type, Type, Option<TrapKind>, Option<TrapKind>), String> {
    match op {
        BinaryOp::AddIntegerChecked
        | BinaryOp::SubtractIntegerChecked
        | BinaryOp::MultiplyIntegerChecked
            if operand.as_integer().is_some() =>
        {
            Ok((operand, operand, Some(TrapKind::IntegerOverflow), None))
        }
        BinaryOp::DivideIntegerSignedChecked
            if operand
                .as_integer()
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
            if operand
                .as_integer()
                .is_some_and(|integer| !integer.is_signed()) =>
        {
            Ok((operand, operand, Some(TrapKind::DivisionByZero), None))
        }
        BinaryOp::RemainderIntegerSignedChecked
            if operand
                .as_integer()
                .is_some_and(aether_frontend::IntegerType::is_signed) =>
        {
            Ok((operand, operand, Some(TrapKind::DivisionByZero), None))
        }
        BinaryOp::AddFloat
        | BinaryOp::SubtractFloat
        | BinaryOp::MultiplyFloat
        | BinaryOp::DivideFloat
            if operand.as_float().is_some() =>
        {
            Ok((operand, operand, None, None))
        }
        BinaryOp::Less | BinaryOp::LessEqual | BinaryOp::Greater | BinaryOp::GreaterEqual => {
            if operand.is_numeric() {
                Ok((operand, Type::Bool, None, None))
            } else {
                Err("ordered comparison requires numeric operands".into())
            }
        }
        BinaryOp::Equal | BinaryOp::NotEqual if operand == Type::Bool || operand.is_numeric() => {
            Ok((operand, Type::Bool, None, None))
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
        if function.locals.get(local.0 as usize).is_none() {
            return Err(format!("MIR operand local {local:?} does not exist"));
        }
        if !initialized.get(local.0 as usize).copied().unwrap_or(false) {
            return Err(format!("MIR local {local:?} is read before initialization"));
        }
    }
    Ok(())
}

fn operand_type(function: &MirFunction, operand: &Operand) -> Result<Type, String> {
    match operand {
        Operand::Local(local) => function
            .locals
            .get(local.0 as usize)
            .map(|local| local.ty)
            .ok_or_else(|| format!("unknown MIR local {local:?}")),
        Operand::Int { ty, .. } | Operand::Float { ty, .. } => Ok(*ty),
        Operand::Bool(_) => Ok(Type::Bool),
    }
}

fn valid_coercion(kind: CoercionKind, from: Type, to: Type) -> bool {
    match (kind, from, to) {
        (CoercionKind::SignExtend, Type::Integer(a), Type::Integer(b)) => {
            a.is_signed() && a.can_widen_to(b)
        }
        (CoercionKind::ZeroExtend, Type::Integer(a), Type::Integer(b)) => {
            !a.is_signed() && a.can_widen_to(b)
        }
        (
            CoercionKind::FloatExtend,
            Type::Float(aether_frontend::FloatType::Float32),
            Type::Float(aether_frontend::FloatType::Float64),
        ) => true,
        _ => false,
    }
}

pub(crate) fn valid_cast(kind: CastKind, from: Type, to: Type) -> bool {
    use aether_frontend::{FloatType, TargetProperties};
    let target = TargetProperties::LINUX_X86_64;
    match (kind, from, to) {
        (CastKind::Identity, a, b) => a == b && a != Type::Bool,
        (CastKind::IntegerExtendSigned, Type::Integer(a), Type::Integer(b)) => {
            a.is_signed() && b.is_signed() && a.bits(target) < b.bits(target)
        }
        (CastKind::IntegerExtendUnsigned, Type::Integer(a), Type::Integer(b)) => {
            !a.is_signed() && !b.is_signed() && a.bits(target) < b.bits(target)
        }
        (CastKind::IntegerNarrowChecked, Type::Integer(a), Type::Integer(b)) => {
            a.is_signed() == b.is_signed() && a.bits(target) > b.bits(target)
        }
        (CastKind::IntegerReencode, Type::Integer(a), Type::Integer(b)) => {
            a != b && a.is_signed() == b.is_signed() && a.bits(target) == b.bits(target)
        }
        (CastKind::IntegerSignednessChecked, Type::Integer(a), Type::Integer(b)) => {
            a.is_signed() != b.is_signed()
        }
        (CastKind::SignedIntegerToFloat, Type::Integer(a), Type::Float(_)) => a.is_signed(),
        (CastKind::UnsignedIntegerToFloat, Type::Integer(a), Type::Float(_)) => !a.is_signed(),
        (CastKind::FloatToSignedIntegerChecked, Type::Float(_), Type::Integer(b)) => b.is_signed(),
        (CastKind::FloatToUnsignedIntegerChecked, Type::Float(_), Type::Integer(b)) => {
            !b.is_signed()
        }
        (
            CastKind::FloatExtend,
            Type::Float(FloatType::Float32),
            Type::Float(FloatType::Float64),
        )
        | (
            CastKind::FloatTruncate,
            Type::Float(FloatType::Float64),
            Type::Float(FloatType::Float32),
        ) => true,
        _ => false,
    }
}

pub(crate) fn cast_can_fail(from: Type, to: Type) -> bool {
    use aether_frontend::TargetProperties;
    match (from, to) {
        (Type::Integer(a), Type::Integer(b)) => {
            let target = TargetProperties::LINUX_X86_64;
            let (source_min, source_max) = a.range(target);
            let (target_min, target_max) = b.range(target);
            source_min < target_min || source_max > target_max
        }
        (Type::Float(_), Type::Integer(_)) => true,
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

#[cfg(test)]
mod tests {
    use aether_frontend::{
        FunctionId, FunctionSignature, ModuleId, ModuleInfo, SourceFile, SourceId, analyze,
        parse_source,
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
    }

    #[test]
    fn trap_terminator_represents_division_failure() {
        let raw = FlowMir {
            modules: vec![ModuleInfo {
                id: ModuleId(0),
                name: "main".into(),
                source: SourceId(0),
                source_name: "<memory>".into(),
                imports: vec![],
            }],
            structs: vec![],
            signatures: vec![FunctionSignature {
                id: FunctionId(0),
                module: ModuleId(0),
                name: "main".into(),
                parameters: vec![],
                return_type: Type::INT64,
                span: Span::new(0, 0),
            }],
            functions: vec![MirFunction {
                id: FunctionId(0),
                parameters: vec![],
                return_type: Type::INT64,
                locals: vec![],
                blocks: vec![BasicBlock {
                    id: BlockId(0),
                    instructions: vec![],
                    terminator: Some(Terminator::Trap(TrapKind::DivisionByZero)),
                }],
                entry: BlockId(0),
            }],
            entry: FunctionId(0),
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
                        callee: FunctionId(0),
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
            *callee = FunctionId(99);
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
        store.destination.projections[0] = aether_frontend::FieldId(999);
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
}
