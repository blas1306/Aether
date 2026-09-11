//! Physical emission decisions over unchanged logical ownership SSA.
//!
//! Every decision is untrusted until the ordinary SSA verifier has checked the
//! graph and this module has reconstructed its proof from that graph.
#![allow(clippy::wildcard_imports)]
use super::*;
use aether_frontend::{ClassId, RequirementId, VirtualSlotId};

/// A balanced physical ARC interval; logical Alias/Drop remain in SSA.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ArcElision {
    pub release: ValueId,
    pub owner: ValueId,
}

/// An exact implementation of a dynamically selected interface requirement.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Devirtualization {
    pub requirement: RequirementId,
    pub class: ClassId,
    pub method: InstanceId,
}

/// An exact implementation of a class virtual slot.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClassDevirtualization {
    pub slot: VirtualSlotId,
    pub class: ClassId,
    pub method: InstanceId,
}

/// Untrusted, deterministic physical lowering requests, independently rechecked.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OopOptimizations {
    pub arc: BTreeMap<ValueId, ArcElision>,
    pub direct: BTreeMap<ValueId, Devirtualization>,
    pub virtual_direct: BTreeMap<ValueId, ClassDevirtualization>,
}

/// Optimizes only physical ownership/dispatch, then re-enters the verifier.
pub fn optimize_oop(ssa: &VerifiedSsa) -> Result<VerifiedSsa, Vec<Diagnostic>> {
    let mut raw = ssa.as_ssa().clone();
    let bounded = bounded_strong_counts(&raw);
    for function in &mut raw.functions {
        function.oop_optimizations = derive(function, &raw.types, &raw.signatures, bounded);
    }
    verify_ssa(raw)
}

pub(super) fn verify(program: &SsaIr) -> Result<(), String> {
    if program
        .functions
        .iter()
        .all(|f| f.oop_optimizations == OopOptimizations::default())
    {
        return Ok(());
    }
    let bounded = bounded_strong_counts(program);
    for function in &program.functions {
        let expected = derive(function, &program.types, &program.signatures, bounded);
        // Subsets permit subsequent passes to discard decisions. An entry cannot
        // be trusted just because an earlier verified wrapper contained it.
        if function
            .oop_optimizations
            .arc
            .iter()
            .any(|(id, p)| expected.arc.get(id) != Some(p))
            || function
                .oop_optimizations
                .direct
                .iter()
                .any(|(id, p)| expected.direct.get(id) != Some(p))
            || function
                .oop_optimizations
                .virtual_direct
                .iter()
                .any(|(id, p)| expected.virtual_direct.get(id) != Some(p))
        {
            return Err("SSA OOP optimization lacks a current ownership/provenance proof".into());
        }
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Provenance {
    Bottom,
    Exact(ClassId),
    Unknown,
}
impl Provenance {
    fn join(self, other: Self) -> Self {
        match (self, other) {
            (Self::Bottom, x) | (x, Self::Bottom) => x,
            (Self::Exact(a), Self::Exact(b)) if a == b => self,
            _ => Self::Unknown,
        }
    }
}
fn value(operand: &SsaOperand) -> Option<ValueId> {
    if let SsaOperand::Value(id) = operand {
        Some(*id)
    } else {
        None
    }
}
fn whole(place: &SsaPlace) -> Option<ValueId> {
    if place.projections.is_empty()
        && let SsaPlaceBase::Value(o) = &place.base
    {
        value(o)
    } else {
        None
    }
}
fn forwarding(op: &SsaOp) -> Option<ValueId> {
    match op {
        SsaOp::Move { source } => whole(source),
        SsaOp::Class(op) => match op.as_ref() {
            ClassOp::ClassUpcast { source, .. }
            | ClassOp::InterfaceAdapt { source, .. }
            | ClassOp::HandleAlias { source }
            | ClassOp::HandleTransfer { source }
            | ClassOp::ReceiverKeepalive { source, .. } => value(source),
            _ => None,
        },
        _ => None,
    }
}
fn provenance(function: &SsaFunction) -> BTreeMap<ValueId, Provenance> {
    let mut facts = BTreeMap::new();
    for parameter in &function.parameters {
        facts.insert(parameter.value, Provenance::Unknown);
    }
    // Least fixed point: Bottom is analysis-unresolved, never authority for a
    // rewrite. Every phi edge participates, including loop backedges.
    loop {
        let mut changed = false;
        for block in &function.blocks {
            for phi in &block.phis {
                let fact = phi.incoming.iter().fold(Provenance::Bottom, |f, (_, v)| {
                    f.join(*facts.get(v).unwrap_or(&Provenance::Bottom))
                });
                changed |= facts.insert(phi.result, fact) != Some(fact);
            }
            for i in &block.instructions {
                let fact = if let Some(source) = forwarding(&i.op) {
                    *facts.get(&source).unwrap_or(&Provenance::Bottom)
                } else if let SsaOp::Class(op) = &i.op {
                    match op.as_ref() {
                        ClassOp::ObjectAlloc { class } | ClassOp::PublishObject { class, .. } => {
                            Provenance::Exact(*class)
                        }
                        _ => Provenance::Unknown,
                    }
                } else {
                    Provenance::Unknown
                };
                changed |= facts.insert(i.result, fact) != Some(fact);
            }
        }
        if !changed {
            return facts;
        }
    }
}

fn derive(
    function: &SsaFunction,
    types: &TypeArena,
    signatures: &[FunctionInstanceInfo],
    bounded: bool,
) -> OopOptimizations {
    let mut result = OopOptimizations::default();
    let facts = provenance(function);
    for i in function.blocks.iter().flat_map(|b| &b.instructions) {
        if let SsaOp::Class(op) = &i.op
            && let ClassOp::InterfaceCall {
                requirement,
                receiver,
                ..
            } = op.as_ref()
            && let Some(Provenance::Exact(class)) = value(receiver).and_then(|v| facts.get(&v))
            && let Some(witness) = types
                .witnesses()
                .iter()
                .find(|w| w.class == *class && w.interface == requirement.interface)
            && let Some(slot) = witness.slots.iter().find(|s| s.requirement == *requirement)
            && let Some(method) = signatures.iter().find(|s| s.function_id == slot.method)
        {
            result.direct.insert(
                i.result,
                Devirtualization {
                    requirement: *requirement,
                    class: *class,
                    method: method.id,
                },
            );
        }
        if let SsaOp::Class(op) = &i.op
            && let ClassOp::VirtualCall {
                class: static_class,
                slot,
                receiver,
                ..
            } = op.as_ref()
            && let Some(Provenance::Exact(class)) = value(receiver).and_then(|v| facts.get(&v))
            && types.is_subclass(*class, *static_class)
            && let Some(target) = types.virtual_implementation(*class, *slot)
            && let Some(method) = signatures.iter().find(|s| s.function_id == target.function)
        {
            result.virtual_direct.insert(
                i.result,
                ClassDevirtualization {
                    slot: *slot,
                    class: *class,
                    method: method.id,
                },
            );
        }
    }
    if bounded {
        result.arc = arc_pairs(function, types, &facts);
    }
    result
}

// True only for a use that cannot consume the specified token. Future opaque
// operations fail closed instead of being assumed harmless from pointer uses.
fn borrows(op: &SsaOp, id: ValueId) -> bool {
    let is = |o: &SsaOperand| value(o) == Some(id);
    match op {
        SsaOp::Class(op) => match op.as_ref() {
            ClassOp::HandleAlias { .. }
            | ClassOp::IdentityEq { .. }
            | ClassOp::FieldRead { .. }
            | ClassOp::ObjectAlloc { .. } => true,
            ClassOp::ReceiverKeepalive {
                source, transfer, ..
            }
            | ClassOp::InterfaceAdapt {
                source, transfer, ..
            }
            | ClassOp::ClassUpcast {
                source, transfer, ..
            } => !*transfer || !is(source),
            ClassOp::BaseInit { args, .. }
            | ClassOp::BaseMethodCall { args, .. }
            | ClassOp::VirtualCall { args, .. }
            | ClassOp::DirectMethodCall { args, .. }
            | ClassOp::InterfaceCall { args, .. }
            | ClassOp::InitCall { args, .. } => !args.iter().any(is),
            ClassOp::FieldWrite { value, .. } => !is(value),
            ClassOp::HandleTransfer { source } => !is(source),
            ClassOp::PublishObject { object, .. } => !is(object),
            ClassOp::Construct { .. } => false,
        },
        // Scalar/memory effects stay in exactly the same order. They cannot
        // address class/interface slots (independently prohibited by verifier).
        SsaOp::Use(_)
        | SsaOp::Binary { .. }
        | SsaOp::Unary { .. }
        | SsaOp::Coerce { .. }
        | SsaOp::Cast { .. }
        | SsaOp::Load { .. }
        | SsaOp::Store { .. }
        | SsaOp::Borrow { .. }
        | SsaOp::Move { .. }
        | SsaOp::Drop { .. } => !op_operands(op).iter().any(|o| is(o)),
        _ => false,
    }
}

fn arc_pairs(
    function: &SsaFunction,
    types: &TypeArena,
    facts: &BTreeMap<ValueId, Provenance>,
) -> BTreeMap<ValueId, ArcElision> {
    let mut pairs = BTreeMap::new();
    let mut nonphysical = BTreeSet::new();
    let value_types: BTreeMap<_, _> = function
        .parameters
        .iter()
        .map(|p| (p.value, p.ty))
        .chain(
            function
                .blocks
                .iter()
                .flat_map(|b| b.phis.iter().map(|p| (p.result, p.ty))),
        )
        .chain(
            function
                .blocks
                .iter()
                .flat_map(|b| b.instructions.iter().map(|i| (i.result, i.ty))),
        )
        .collect();
    for block in &function.blocks {
        for (start, instruction) in block.instructions.iter().enumerate() {
            let SsaOp::Class(op) = &instruction.op else {
                continue;
            };
            let (ClassOp::HandleAlias { source }
            | ClassOp::ReceiverKeepalive {
                source,
                transfer: false,
                ..
            }) = op.as_ref()
            else {
                continue;
            };
            let Some(owner) = value(source) else { continue };
            if types.interface_identity(instruction.ty).is_some()
                && !matches!(facts.get(&owner), Some(Provenance::Exact(_)))
            {
                continue;
            }
            if nonphysical.contains(&owner)
                || !value_types.get(&owner).is_some_and(|t| {
                    !types.is_copy(*t)
                        && (types.object_class(*t).is_some()
                            || types.interface_identity(*t).is_some())
                })
            {
                continue;
            }
            let mut token = instruction.result;
            let mut chain = BTreeSet::from([token]);
            for next in &block.instructions[start + 1..] {
                if !borrows(&next.op, owner) {
                    break;
                }
                if let SsaOp::Drop { owner: place } = &next.op
                    && whole(place) == Some(token)
                {
                    pairs.insert(
                        instruction.result,
                        ArcElision {
                            release: next.result,
                            owner,
                        },
                    );
                    nonphysical.extend(chain);
                    break;
                }
                let transfer = match &next.op {
                    SsaOp::Move { source } => whole(source),
                    SsaOp::Class(op) => match op.as_ref() {
                        ClassOp::HandleTransfer { source } => value(source),
                        _ => None,
                    },
                    _ => None,
                };
                if transfer == Some(token) {
                    token = next.result;
                    chain.insert(token);
                } else if !borrows(&next.op, token) {
                    break;
                }
            }
        }
    }
    pairs
}

// Removing a checked retain also requires proving that count overflow cannot
// change trap behavior. With no stored class graphs/globals and no recursion,
// live tokens are bounded by static definitions times maximum call-stack depth.
// Recursive programs keep ARC; provenance optimization is independent.
fn bounded_strong_counts(program: &SsaIr) -> bool {
    let mut edges = vec![BTreeSet::new(); program.functions.len()];
    let mut definitions = 0_u128;
    for function in &program.functions {
        definitions += function.parameters.len() as u128;
        for block in &function.blocks {
            definitions += (block.phis.len() + block.instructions.len()) as u128;
            for i in &block.instructions {
                match &i.op {
                    SsaOp::Call { callee, .. } => {
                        edges[function.id.0 as usize].insert(*callee);
                    }
                    SsaOp::Class(op) => match op.as_ref() {
                        ClassOp::BaseInit {
                            initializer: method,
                            ..
                        }
                        | ClassOp::BaseMethodCall { method, .. }
                        | ClassOp::DirectMethodCall { method, .. }
                        | ClassOp::InitCall {
                            initializer: method,
                            ..
                        } => {
                            edges[function.id.0 as usize].insert(*method);
                        }
                        ClassOp::VirtualCall { slot, .. } => {
                            for s in &program.signatures {
                                if program
                                    .types
                                    .class_method(s.function_id)
                                    .is_some_and(|(_, m)| m.virtual_slot == Some(*slot))
                                {
                                    edges[function.id.0 as usize].insert(s.id);
                                }
                            }
                        }
                        ClassOp::InterfaceCall { requirement, .. } => {
                            for w in program.types.witnesses() {
                                if let Some(s) =
                                    w.slots.iter().find(|s| s.requirement == *requirement)
                                    && let Some(f) = program
                                        .signatures
                                        .iter()
                                        .find(|f| f.function_id == s.method)
                                {
                                    edges[function.id.0 as usize].insert(f.id);
                                }
                            }
                        }
                        _ => (),
                    },
                    _ => (),
                }
            }
        }
    }
    let mut remaining = (0..edges.len()).collect::<BTreeSet<_>>();
    loop {
        let leaves: Vec<_> = remaining
            .iter()
            .copied()
            .filter(|i| {
                edges[*i]
                    .iter()
                    .all(|e| !remaining.contains(&(e.0 as usize)))
            })
            .collect();
        if leaves.is_empty() {
            break;
        }
        for leaf in leaves {
            remaining.remove(&leaf);
        }
    }
    remaining.is_empty()
        && definitions.saturating_mul(program.functions.len() as u128 + 1) < u128::from(u64::MAX)
}
