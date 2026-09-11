//! Independent path validation of class tokens in actual SSA (including phi edges).
#![allow(clippy::wildcard_imports)]
use super::*;
use aether_frontend::ClassTokenKind;

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
struct State {
    owned: BTreeSet<ValueId>,
    memory: BTreeSet<LocalId>,
    booleans: BTreeMap<ValueId, bool>,
    fields: aether_frontend::ClassInitializationState,
    allocations: BTreeMap<ValueId, bool>,
    construction_cleaned: bool,
}
#[allow(clippy::too_many_lines)]
pub(super) fn verify(
    function: &SsaFunction,
    signatures: &[FunctionInstanceInfo],
    types: &TypeArena,
    operand_ty: &impl Fn(&SsaOperand) -> Result<TypeId, String>,
) -> Result<(), String> {
    let sig = &signatures[function.id.0 as usize];
    aether_frontend::verify_class_signature(
        types,
        function.function_id,
        sig.module,
        &function.parameters.iter().map(|p| p.ty).collect::<Vec<_>>(),
        function.return_type,
    )?;
    if !function
        .parameters
        .iter()
        .any(|p| types.object_class(p.ty).is_some() || types.interface_identity(p.ty).is_some())
        && !function
            .blocks
            .iter()
            .flat_map(|b| &b.instructions)
            .any(|i| {
                matches!(i.op, SsaOp::Class(_))
                    || types.object_class(i.ty).is_some()
                    || types.interface_identity(i.ty).is_some()
            })
    {
        return Ok(());
    }
    if function
        .memory_locals
        .iter()
        .any(|l| types.object_class(l.ty).is_some() || types.interface_identity(l.ty).is_some())
    {
        return Err("SSA class handle slot borrowing is unavailable in OOP-V1".into());
    }
    let init = types
        .class_method(function.function_id)
        .filter(|(_, m)| m.initializing)
        .map(|(c, _)| c);
    match (init, function.constructor_unwind.as_ref()) {
        (None, None) => {}
        (Some(class), Some(plan)) => {
            let expected = types.classes()[class.0 as usize]
                .destruction
                .iter()
                .filter_map(|step| match step {
                    aether_frontend::ClassDropStep::Field { field, .. } => Some(*field),
                    aether_frontend::ClassDropStep::Free { .. } => None,
                })
                .collect::<Vec<_>>();
            if plan.class != class
                || plan.cleanup_fields != expected
                || function.parameters.first().map(|parameter| parameter.local)
                    != Some(plan.receiver)
            {
                return Err("SSA constructor unwind plan is invalid".into());
            }
        }
        _ => return Err("SSA constructor unwind plan presence is invalid".into()),
    }
    // Class tokens and the narrowly admitted Buffer owner have this additional
    // SSA ledger. Other value/container protocols retain their existing verifiers.
    let tracked = |ty| {
        !types.is_copy(ty)
            && (types.object_class(ty).is_some()
                || types.interface_identity(ty).is_some()
                || types.buffer_element(ty).is_some())
    };
    let initial = State {
        owned: function
            .parameters
            .iter()
            .filter(|p| {
                tracked(p.ty)
                    && !function
                        .memory_locals
                        .iter()
                        .any(|m| m.parameter == Some(p.value))
            })
            .map(|p| p.value)
            .collect(),
        memory: function
            .memory_locals
            .iter()
            .filter(|m| tracked(m.ty) && m.parameter.is_some())
            .map(|m| m.local)
            .collect(),
        booleans: BTreeMap::new(),
        fields: aether_frontend::ClassInitializationState::default(),
        allocations: BTreeMap::new(),
        construction_cleaned: false,
    };
    let mut work = VecDeque::from([(function.entry, initial)]);
    let mut seen = BTreeSet::new();
    let consume = |operand: &SsaOperand, state: &mut State| -> Result<(), String> {
        if tracked(operand_ty(operand)?) {
            let SsaOperand::Value(id) = operand else {
                return Err("SSA owner has no token".into());
            };
            if !state.owned.remove(id) {
                return Err(
                    "SSA ownership token duplicated, released twice or used after Transfer".into(),
                );
            }
        }
        Ok(())
    };
    while let Some((block_id, mut state)) = work.pop_front() {
        if !seen.insert((block_id, state.clone())) {
            continue;
        }
        let block = &function.blocks[block_id.0 as usize];
        for i in &block.instructions {
            let mut exceptional_state = None;
            for o in op_operands(&i.op) {
                if tracked(operand_ty(o)?)
                    && let SsaOperand::Value(id) = o
                    && !state.owned.contains(id)
                {
                    return Err("SSA operation uses a released/transferred owner".into());
                }
            }
            let known_bool = match &i.op {
                SsaOp::Use(SsaOperand::Bool(v)) => Some(*v),
                SsaOp::Use(SsaOperand::Value(v)) => state.booleans.get(v).copied(),
                _ => None,
            };
            state.booleans.remove(&i.result);
            if let Some(value) = known_bool {
                state.booleans.insert(i.result, value);
            }
            match &i.op {
                SsaOp::Store { place, value } => {
                    if tracked(operand_ty(value)?) {
                        consume(value, &mut state)?;
                        if let SsaPlaceBase::MemoryLocal(local) = place.base
                            && place.projections.is_empty()
                            && !state.memory.insert(local)
                        {
                            return Err("SSA overwrites a live Buffer owner".into());
                        }
                    }
                }
                SsaOp::ListPush { value, .. } => consume(value, &mut state)?,
                SsaOp::Class(op) => {
                    aether_frontend::verify_class_access(
                        op,
                        types,
                        function.function_id,
                        sig.module,
                        |id| {
                            signatures
                                .get(id.0 as usize)
                                .map(|s| s.function_id)
                                .ok_or_else(|| "unknown method".into())
                        },
                    )?;
                    match op.as_ref() {
                        ClassOp::BaseInit { base, args, .. } => {
                            for arg in args {
                                consume(arg, &mut state)?;
                            }
                            if i.unwind.is_some() {
                                exceptional_state = Some(state.clone());
                            }
                            state.fields.complete_base(types, *base)?;
                        }
                        ClassOp::ObjectAlloc { .. } => {
                            if state.allocations.insert(i.result, false).is_some() {
                                return Err("SSA allocation overwrites unpublished object".into());
                            }
                        }
                        ClassOp::InitCall { object, args, .. } => {
                            let SsaOperand::Value(object) = object else {
                                return Err("SSA initializer has no allocation".into());
                            };
                            if state.allocations.get(object) != Some(&false) {
                                return Err(
                                    "SSA initialization requires one preceding allocation".into()
                                );
                            }
                            for arg in args {
                                consume(arg, &mut state)?;
                            }
                            if i.unwind.is_some() {
                                exceptional_state = Some(state.clone());
                            }
                            state.allocations.insert(*object, true);
                        }
                        ClassOp::PublishObject { object, .. } => {
                            let SsaOperand::Value(id) = object else {
                                return Err("SSA publication has no allocation".into());
                            };
                            if state.allocations.remove(id) != Some(true) {
                                return Err("SSA publication before initialization or duplicate publication".into());
                            }
                            consume(object, &mut state)?;
                        }
                        ClassOp::ConstructionCleanup {
                            class,
                            object,
                            fields,
                            free_allocation,
                        } => {
                            if *free_allocation {
                                let SsaOperand::Value(object_id) = object else {
                                    return Err("SSA allocation cleanup has no object value".into());
                                };
                                if !fields.is_empty()
                                    || state.allocations.remove(object_id) != Some(false)
                                {
                                    return Err("SSA allocation cleanup is not exactly once before publication".into());
                                }
                                consume(object, &mut state)?;
                            } else {
                                if init != Some(*class) || state.construction_cleaned {
                                    return Err("SSA partial-construction cleanup is duplicated or outside init".into());
                                }
                                let expected =
                                    types.classes()[class.0 as usize]
                                        .destruction
                                        .iter()
                                        .filter_map(|step| match step {
                                            aether_frontend::ClassDropStep::Field {
                                                field, ..
                                            } if state.fields.contains(field) => Some(*field),
                                            _ => None,
                                        })
                                        .collect::<Vec<_>>();
                                if *fields != expected {
                                    return Err("SSA partial-construction cleanup omits, duplicates or reorders fields".into());
                                }
                                state.fields = aether_frontend::ClassInitializationState::default();
                                state.construction_cleaned = true;
                            }
                        }
                        ClassOp::ClassUpcast {
                            source,
                            transfer: true,
                            ..
                        }
                        | ClassOp::InterfaceAdapt {
                            source,
                            transfer: true,
                            ..
                        }
                        | ClassOp::HandleTransfer { source }
                        | ClassOp::ReceiverKeepalive {
                            source,
                            transfer: true,
                            ..
                        } => consume(source, &mut state)?,
                        ClassOp::BaseMethodCall { args, .. }
                        | ClassOp::VirtualCall { args, .. }
                        | ClassOp::DirectMethodCall { args, .. }
                        | ClassOp::InterfaceCall { args, .. } => {
                            for arg in args {
                                consume(arg, &mut state)?;
                            }
                        }
                        ClassOp::FieldRead { receiver, field }
                        | ClassOp::FieldWrite {
                            receiver, field, ..
                        } => {
                            if matches!(
                                types.get(operand_ty(receiver)?),
                                Some(TypeData::ClassToken {
                                    kind: ClassTokenKind::Receiver {
                                        initializing: true,
                                        ..
                                    },
                                    ..
                                })
                            ) {
                                if init != types.object_class(operand_ty(receiver)?) {
                                    return Err("SSA invalid initializing receiver".into());
                                }
                                state.fields.require_base(
                                    types,
                                    init.ok_or("base init outside initializer")?,
                                )?;
                                if let ClassOp::FieldWrite { initialize, .. } = op.as_ref() {
                                    if (!*initialize && !state.fields.contains(field))
                                        || (*initialize
                                            && state.fields.contains(field)
                                            && types
                                                .class_field(*field)
                                                .is_some_and(|f| types.needs_drop(f.ty)))
                                    {
                                        return Err(
                                            "SSA FieldInit/replacement state mismatch".into()
                                        );
                                    }
                                    state.fields.insert(*field);
                                } else if !state.fields.contains(field) {
                                    return Err("SSA field read before initialization".into());
                                }
                            }
                            if let ClassOp::FieldWrite { value, .. } = op.as_ref() {
                                consume(value, &mut state)?;
                            }
                        }
                        _ => (),
                    }
                }
                SsaOp::Move { source } | SsaOp::Drop { owner: source } => {
                    if let SsaPlaceBase::MemoryLocal(local) = source.base
                        && source.projections.is_empty()
                        && function
                            .memory_locals
                            .iter()
                            .any(|m| m.local == local && tracked(m.ty))
                        && !state.memory.remove(&local)
                    {
                        return Err("SSA moves/releases an unowned Buffer memory slot".into());
                    }
                    if let SsaPlaceBase::Value(o) = &source.base
                        && source.projections.is_empty()
                    {
                        if matches!(
                            types.get(operand_ty(o)?),
                            Some(TypeData::ClassToken {
                                kind: ClassTokenKind::Unpublished,
                                ..
                            })
                        ) {
                            return Err("SSA unpublished object cannot move/drop normally".into());
                        }
                        consume(o, &mut state)?;
                    }
                }
                SsaOp::Call { callee, args } => {
                    if types
                        .class_method(signatures[callee.0 as usize].function_id)
                        .is_some()
                    {
                        return Err("SSA ordinary call bypasses class receiver protocol".into());
                    }
                    for arg in args {
                        consume(arg, &mut state)?;
                    }
                }
                SsaOp::Use(o) | SsaOp::ExtractField { aggregate: o, .. }
                    if tracked(operand_ty(o)?) =>
                {
                    return Err("SSA implicit duplication of a non-Copy owner".into());
                }
                SsaOp::Aggregate { fields, .. } => {
                    for (_, arg) in fields {
                        consume(arg, &mut state)?;
                    }
                }
                SsaOp::EnumConstruct { payloads, .. } => {
                    for arg in payloads {
                        consume(arg, &mut state)?;
                    }
                }
                SsaOp::VectorTransposeMove { operand, .. } => consume(operand, &mut state)?,
                SsaOp::ArrayInit { elements, .. }
                | SsaOp::ListInit { elements, .. }
                | SsaOp::VectorInit { elements, .. }
                | SsaOp::MatrixInit { elements, .. } => {
                    for arg in elements {
                        consume(arg, &mut state)?;
                    }
                }
                _ => (),
            }
            if let Some(unwind) = i.unwind {
                work.push_back((unwind, exceptional_state.unwrap_or_else(|| state.clone())));
            }
            if tracked(i.ty) && !state.owned.insert(i.result) {
                return Err("SSA duplicates an owning result token".into());
            }
        }
        if let SsaTerminator::Throw { payload, .. } = &block.terminator {
            consume(payload, &mut state)?;
        }
        if let SsaTerminator::Return(value) = &block.terminator {
            if let Some(c) = init {
                state.fields.require_base(types, c)?;
            }
            consume(value, &mut state)?;
            if !state.owned.is_empty() || !state.memory.is_empty() || !state.allocations.is_empty()
            {
                return Err(format!(
                    "SSA normal return leaks ownership tokens {:?}",
                    state.owned
                ));
            }
            if state.construction_cleaned {
                return Err(
                    "SSA normal initializer path used exceptional construction cleanup".into(),
                );
            }
            if init.is_some_and(|c| {
                types.classes()[c.0 as usize]
                    .fields
                    .iter()
                    .any(|f| !state.fields.contains(&f.id))
            }) {
                return Err("SSA initializer returns before complete field initialization".into());
            }
        }
        if matches!(block.terminator, SsaTerminator::ResumeUnwind { .. }) {
            if !state.allocations.is_empty() {
                return Err("SSA exceptional exit leaks an unpublished allocation".into());
            }
            if init.is_some() && !state.construction_cleaned {
                return Err(
                    "SSA initializer exceptional exit omits partial-construction cleanup".into(),
                );
            }
        }
        for target in ssa_targets(&block.terminator) {
            if let SsaTerminator::Branch {
                condition,
                then_block,
                else_block,
            } = &block.terminator
            {
                let known = match condition {
                    SsaOperand::Bool(v) => Some(*v),
                    SsaOperand::Value(v) => state.booleans.get(v).copied(),
                    _ => None,
                };
                if known.is_some_and(|v| target != if v { *then_block } else { *else_block }) {
                    continue;
                }
            }
            let mut outgoing = state.clone();
            // Phi input tokens move simultaneously on the selected edge. A source
            // cannot satisfy two owning phis, even if both contain equal pointers.
            let mut results = Vec::new();
            for phi in &function.blocks[target.0 as usize].phis {
                if phi.ty == TypeId::BOOL {
                    let (_, input) = phi
                        .incoming
                        .iter()
                        .find(|(pred, _)| *pred == block_id)
                        .ok_or("missing bool phi edge")?;
                    outgoing.booleans.remove(&phi.result);
                    if let Some(value) = state.booleans.get(input) {
                        outgoing.booleans.insert(phi.result, *value);
                    }
                }
                if tracked(phi.ty) {
                    let (_, input) = phi
                        .incoming
                        .iter()
                        .find(|(pred, _)| *pred == block_id)
                        .ok_or("missing SSA phi edge")?;
                    consume(&SsaOperand::Value(*input), &mut outgoing)?;
                    results.push(phi.result);
                }
            }
            for result in results {
                if !outgoing.owned.insert(result) {
                    return Err("SSA phi duplicates an ownership token".into());
                }
            }
            work.push_back((target, outgoing));
        }
    }
    Ok(())
}
