//! MIR-to-SSA promotion, phi construction, dominance and verification.
#![allow(missing_docs)]

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fmt::Write;

use aether_frontend::{
    CastKind, CoercionKind, Diagnostic, DiagnosticCategory, FloatValue, FunctionId,
    FunctionSignature, LocalId, ModuleInfo, Phase, Span, Type,
};

use crate::{
    BinaryOp, BlockId, MirFunction, Operand, Rvalue, Terminator, TrapKind, UnaryOp, VerifiedMir,
};

/// Fresh SSA value identity.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ValueId(pub u32);

/// Scalar SSA operand.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SsaOperand {
    /// SSA value use.
    Value(ValueId),
    /// Signed 64-bit constant.
    Int { value: i128, ty: Type },
    /// IEEE literal bits and canonical type.
    Float { value: FloatValue, ty: Type },
    /// Boolean constant.
    Bool(bool),
}

/// Phi definition for a promoted MIR local.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Phi {
    /// Defined value.
    pub result: ValueId,
    /// Canonical type.
    pub ty: Type,
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
    /// Canonical scalar type.
    pub ty: Type,
}

/// SSA computation.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum SsaOp {
    /// Scalar copy.
    Use(SsaOperand),
    /// Explicit widening selected in HIR.
    Coerce {
        kind: CoercionKind,
        operand: SsaOperand,
        from: Type,
    },
    /// Explicit value conversion preserved from HIR/MIR.
    Cast {
        kind: CastKind,
        operand: SsaOperand,
        from: Type,
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
        callee: FunctionId,
        args: Vec<SsaOperand>,
    },
}

/// One SSA definition.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SsaInstruction {
    /// Fresh result identity.
    pub result: ValueId,
    /// Result type.
    pub ty: Type,
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
    pub id: FunctionId,
    /// Entry parameter definitions in call order.
    pub parameters: Vec<SsaParameter>,
    /// Canonical return type.
    pub return_type: Type,
    /// Entry block.
    pub entry: BlockId,
    /// Blocks in stable MIR order.
    pub blocks: Vec<SsaBlock>,
}

/// Unverified SSA type-state.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SsaIr {
    /// Resolved program module graph and provenance.
    pub modules: Vec<ModuleInfo>,
    /// Source-unit signature table.
    pub signatures: Vec<FunctionSignature>,
    /// Function-local SSA graphs in identity order.
    pub functions: Vec<SsaFunction>,
    /// Entry function identity.
    pub entry: FunctionId,
}

impl SsaIr {
    /// Deterministic inspection dump.
    #[must_use]
    pub fn dump(&self) -> String {
        let mut dump = format!(
            "entry: {:#?}\nmodules: {:#?}\nsignatures: {:#?}",
            self.entry, self.modules, self.signatures
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

/// Promotes all scalar MIR locals to SSA using dominance-frontier phi placement.
#[must_use]
pub fn build_ssa(mir: &VerifiedMir) -> SsaIr {
    let mir = mir.as_mir();
    SsaIr {
        modules: mir.modules.clone(),
        signatures: mir.signatures.clone(),
        functions: mir.functions.iter().map(build_function_ssa).collect(),
        entry: mir.entry,
    }
}

fn build_function_ssa(function: &MirFunction) -> SsaFunction {
    let cfg = Cfg::new(function);
    let dominance = Dominance::compute(&cfg, function.entry);
    let live_in = mir_liveness(function, &cfg);
    let mut phi_locals = vec![BTreeSet::new(); function.blocks.len()];

    let mut definitions = vec![BTreeSet::new(); function.locals.len()];
    for block in &function.blocks {
        for instruction in &block.instructions {
            definitions[instruction.destination.0 as usize].insert(block.id);
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
    );
    for block in &mut blocks {
        for phi in &mut block.phis {
            phi.incoming.sort_by_key(|(predecessor, _)| *predecessor);
        }
    }
    SsaFunction {
        id: function.id,
        parameters,
        return_type: function.return_type,
        entry: function.entry,
        blocks,
    }
}

#[allow(clippy::too_many_arguments)]
fn rename_block(
    block_id: BlockId,
    mir: &MirFunction,
    cfg: &Cfg,
    dominance: &Dominance,
    phi_results: &[BTreeMap<LocalId, ValueId>],
    blocks: &mut [SsaBlock],
    stacks: &mut [Vec<ValueId>],
    next_value: &mut u32,
) {
    let block_index = block_id.0 as usize;
    let mut pushes = vec![0_usize; stacks.len()];
    for (local, result) in &phi_results[block_index] {
        stacks[local.0 as usize].push(*result);
        pushes[local.0 as usize] += 1;
    }
    for instruction in &mir.blocks[block_index].instructions {
        let op = rename_rvalue(&instruction.value, stacks);
        let result = ValueId(*next_value);
        *next_value += 1;
        let ty = mir.locals[instruction.destination.0 as usize].ty;
        blocks[block_index].instructions.push(SsaInstruction {
            result,
            ty,
            op,
            span: instruction.span,
        });
        stacks[instruction.destination.0 as usize].push(result);
        pushes[instruction.destination.0 as usize] += 1;
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
        );
    }
    for (local, count) in pushes.into_iter().enumerate() {
        let new_len = stacks[local].len() - count;
        stacks[local].truncate(new_len);
    }
}

fn rename_rvalue(value: &Rvalue, stacks: &[Vec<ValueId>]) -> SsaOp {
    match value {
        Rvalue::Use(operand) => SsaOp::Use(rename_operand(operand, stacks)),
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
            for local in rvalue_locals(&instruction.value) {
                if !definitions[index].contains(&local) {
                    uses[index].insert(local);
                }
            }
            definitions[index].insert(instruction.destination);
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

fn rvalue_locals(value: &Rvalue) -> Vec<LocalId> {
    match value {
        Rvalue::Use(operand)
        | Rvalue::Coerce { operand, .. }
        | Rvalue::Cast { operand, .. }
        | Rvalue::Unary { operand, .. } => operand_local(operand).into_iter().collect(),
        Rvalue::Binary { left, right, .. } => operand_local(left)
            .into_iter()
            .chain(operand_local(right))
            .collect(),
        Rvalue::Call { args, .. } => args.iter().filter_map(operand_local).collect(),
    }
}

fn terminator_locals(terminator: &Terminator) -> Vec<LocalId> {
    match terminator {
        Terminator::Branch { condition, .. } | Terminator::Return(condition) => {
            operand_local(condition).into_iter().collect()
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
    for (index, (signature, function)) in ssa.signatures.iter().zip(&ssa.functions).enumerate() {
        if signature.id.0 as usize != index || function.id != signature.id {
            return Err(fail("SSA function identities are not canonical".into()));
        }
        if signature.module.0 as usize >= ssa.modules.len() {
            return Err(fail("SSA signature names an unknown module".into()));
        }
        verify_ssa_function(function, signature, &ssa.signatures, &fail)?;
    }
    Ok(VerifiedSsa(ssa))
}

#[allow(clippy::too_many_lines, clippy::items_after_statements)]
fn verify_ssa_function(
    function: &SsaFunction,
    signature: &FunctionSignature,
    signatures: &[FunctionSignature],
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
        ty: Type,
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

    let operand_ty = |operand: &SsaOperand| -> Result<Type, String> {
        match operand {
            SsaOperand::Value(value) => definitions
                .get(value)
                .map(|definition| definition.ty)
                .ok_or_else(|| format!("SSA use of undefined value {value:?}")),
            SsaOperand::Int { ty, .. } | SsaOperand::Float { ty, .. } => Ok(*ty),
            SsaOperand::Bool(_) => Ok(Type::Bool),
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
            verify_op(&instruction.op, instruction.ty, signatures, &operand_ty).map_err(&fail)?;
        }
        match &block.terminator {
            SsaTerminator::Branch { condition, .. } => {
                validate_use(condition, block.id, Some(block.instructions.len())).map_err(&fail)?;
                if operand_ty(condition).map_err(&fail)? != Type::Bool {
                    return Err(fail("SSA branch condition is not bool".into()));
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

fn verify_op(
    op: &SsaOp,
    result: Type,
    signatures: &[FunctionSignature],
    operand_ty: &impl Fn(&SsaOperand) -> Result<Type, String>,
) -> Result<(), String> {
    match op {
        SsaOp::Use(operand) => {
            if operand_ty(operand)? != result {
                return Err("SSA copy type mismatch".into());
            }
        }
        SsaOp::Coerce {
            kind,
            operand,
            from,
        } => {
            if operand_ty(operand)? != *from || !valid_coercion(*kind, *from, result) {
                return Err("invalid SSA coercion contract".into());
            }
        }
        SsaOp::Cast {
            kind,
            operand,
            from,
            trap,
        } => {
            let required_trap =
                crate::mir::cast_can_fail(*from, result).then_some(TrapKind::ConversionOutOfRange);
            if operand_ty(operand)? != *from
                || !crate::mir::valid_cast(*kind, *from, result)
                || *trap != required_trap
            {
                return Err("invalid SSA explicit-cast contract".into());
            }
        }
        SsaOp::Unary { op, operand, trap } => {
            let ty = operand_ty(operand)?;
            let valid = match op {
                UnaryOp::NegateIntegerChecked => ty
                    .as_integer()
                    .is_some_and(aether_frontend::IntegerType::is_signed),
                UnaryOp::NegateFloat => ty.as_float().is_some(),
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
                crate::mir::binary_contract(*op, left)?;
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

fn op_operands(op: &SsaOp) -> Vec<&SsaOperand> {
    match op {
        SsaOp::Use(value)
        | SsaOp::Coerce { operand: value, .. }
        | SsaOp::Cast { operand: value, .. } => vec![value],
        SsaOp::Unary { operand, .. } => vec![operand],
        SsaOp::Binary { left, right, .. } => vec![left, right],
        SsaOp::Call { args, .. } => args.iter().collect(),
    }
}

fn mir_targets(terminator: &Terminator) -> Vec<BlockId> {
    match terminator {
        Terminator::Goto(target) => vec![*target],
        Terminator::Branch {
            then_block,
            else_block,
            ..
        } => vec![*then_block, *else_block],
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
                        callee: FunctionId(0),
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
                ty: Type::INT64,
            };
        }
        assert!(verify_ssa(ssa).is_err());
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
}
