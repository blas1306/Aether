//! Materialize class ownership before LLVM.
#![allow(clippy::wildcard_imports)]
use super::*;
impl Builder<'_> {
    fn class_value(&mut self, op: ClassOp<Operand, InstanceId>, ty: TypeId, span: Span) -> Operand {
        let result = self.temporary(ty);
        self.assign(
            Place {
                base: PlaceBase::Local(result),
                projections: Vec::new(),
            },
            Rvalue::Class(Box::new(op)),
            span,
        );
        Operand::Local(result)
    }
    #[allow(clippy::too_many_lines)]
    pub(super) fn lower_class(&mut self, op: &ClassOp<HirExpr>, ty: TypeId, span: Span) -> Operand {
        if let ClassOp::Construct {
            class,
            initializer,
            args,
        } = op
        {
            let temporary_start = self.active_temporary_owners.len();
            let mut lowered_args = Vec::with_capacity(args.len());
            for argument in args {
                let lowered = self.lower_expr(argument);
                if self.types.needs_drop(argument.ty)
                    && let Some(local) = operand_local_id(&lowered)
                    && !self.active_owners.contains(&local)
                {
                    self.active_temporary_owners.push(local);
                }
                lowered_args.push(lowered);
            }
            let unpublished = self
                .types
                .id_of(TypeData::ClassToken {
                    class: *class,
                    kind: ClassTokenKind::Unpublished,
                })
                .unwrap();
            let object =
                self.class_value(ClassOp::ObjectAlloc { class: *class }, unpublished, span);
            let HirCallTarget::Instance(initializer) = initializer else {
                unreachable!("verified concrete class initializer")
            };
            self.active_temporary_owners.truncate(temporary_start);
            self.class_value(
                ClassOp::InitCall {
                    class: *class,
                    initializer: *initializer,
                    object: object.clone(),
                    args: lowered_args,
                },
                TypeId::BOOL,
                span,
            );
            return self.class_value(
                ClassOp::PublishObject {
                    class: *class,
                    object,
                },
                ty,
                span,
            );
        }
        if matches!(
            op,
            ClassOp::VirtualCall { .. }
                | ClassOp::DirectMethodCall { .. }
                | ClassOp::BaseMethodCall { .. }
                | ClassOp::InterfaceCall { .. }
        ) {
            let temporary_start = self.active_temporary_owners.len();
            let (ClassOp::VirtualCall {
                receiver,
                args: arguments,
                ..
            }
            | ClassOp::DirectMethodCall {
                receiver,
                args: arguments,
                ..
            }
            | ClassOp::BaseMethodCall {
                receiver,
                args: arguments,
                ..
            }
            | ClassOp::InterfaceCall {
                receiver,
                args: arguments,
                ..
            }) = op
            else {
                unreachable!()
            };
            let receiver = self.lower_expr(receiver);
            if self.types.needs_drop(value_type(&self.function, &receiver))
                && let Some(local) = operand_local_id(&receiver)
                && !self.active_owners.contains(&local)
            {
                self.active_temporary_owners.push(local);
            }
            let mut args = Vec::with_capacity(arguments.len());
            for argument in arguments {
                let lowered = self.lower_expr(argument);
                if self.types.needs_drop(argument.ty)
                    && let Some(local) = operand_local_id(&lowered)
                    && !self.active_owners.contains(&local)
                {
                    self.active_temporary_owners.push(local);
                }
                args.push(lowered);
            }
            let receiver_drop =
                (!matches!(op, ClassOp::BaseMethodCall { .. })).then(|| receiver.clone());
            let mapped = match op {
                ClassOp::VirtualCall {
                    class,
                    slot,
                    method,
                    ..
                } => ClassOp::VirtualCall {
                    class: *class,
                    slot: *slot,
                    method: match method {
                        HirCallTarget::Instance(id) => *id,
                        HirCallTarget::Declaration(_) => unreachable!("verified concrete method"),
                    },
                    receiver,
                    args,
                },
                ClassOp::DirectMethodCall { method, .. } => ClassOp::DirectMethodCall {
                    method: match method {
                        HirCallTarget::Instance(id) => *id,
                        HirCallTarget::Declaration(_) => unreachable!("verified concrete method"),
                    },
                    receiver,
                    args,
                },
                ClassOp::BaseMethodCall {
                    class,
                    base,
                    slot,
                    method,
                    ..
                } => ClassOp::BaseMethodCall {
                    class: *class,
                    base: *base,
                    slot: *slot,
                    method: match method {
                        HirCallTarget::Instance(id) => *id,
                        HirCallTarget::Declaration(_) => unreachable!("verified concrete method"),
                    },
                    receiver,
                    args,
                },
                ClassOp::InterfaceCall {
                    requirement, slot, ..
                } => ClassOp::InterfaceCall {
                    requirement: *requirement,
                    slot: *slot,
                    receiver,
                    args,
                },
                _ => unreachable!(),
            };
            self.active_temporary_owners.truncate(temporary_start);
            let result = self.class_value(mapped, ty, span);
            if let Some(receiver) = receiver_drop {
                self.emit_drop(operand_place(&receiver), span);
            }
            return result;
        }
        // map evaluates receiver before arguments and each operand exactly once.
        let mapped = op
            .map(
                |e| Ok::<_, std::convert::Infallible>(self.lower_expr(e)),
                |target| {
                    let HirCallTarget::Instance(id) = target else {
                        unreachable!("verified direct method")
                    };
                    Ok(*id)
                },
            )
            .unwrap();
        let mut drops = Vec::new();
        if let ClassOp::VirtualCall { receiver, .. }
        | ClassOp::DirectMethodCall { receiver, .. }
        | ClassOp::InterfaceCall { receiver, .. } = &mapped
        {
            drops.push(receiver.clone());
        }
        if let (
            ClassOp::IdentityEq { left, right, .. },
            ClassOp::IdentityEq {
                left: l, right: r, ..
            },
        ) = (op, &mapped)
        {
            if !matches!(left.kind, HirExprKind::Local(_)) {
                drops.push(l.clone());
            }
            if !matches!(right.kind, HirExprKind::Local(_)) {
                drops.push(r.clone());
            }
        }
        let state_change = match &mapped {
            ClassOp::BaseInit { base, .. } => Some((Some(*base), None)),
            ClassOp::FieldWrite {
                field,
                initialize: true,
                ..
            } => Some((None, Some(*field))),
            _ => None,
        };
        let result = self.class_value(mapped, ty, span);
        if let Some((base, field)) = state_change
            && let Some(state) = &mut self.construction_state
        {
            if let Some(base) = base {
                state
                    .complete_base(self.types, base)
                    .expect("verified HIR base initialization state");
            }
            if let Some(field) = field {
                state.insert(field);
            }
        }
        for drop in drops {
            self.emit_drop(operand_place(&drop), span);
        }
        result
    }
}

/// Per-path construction state, independent of HIR initialization facts.
#[allow(clippy::too_many_lines)]
pub(super) fn verify(
    function: &MirFunction,
    signatures: &[FunctionInstanceInfo],
    types: &TypeArena,
) -> Result<(), String> {
    use std::collections::{BTreeMap, BTreeSet, VecDeque};
    if types.classes().is_empty() {
        return Ok(());
    }
    let sig = &signatures[function.id.0 as usize];
    aether_frontend::verify_class_signature(
        types,
        function.function_id,
        sig.module,
        &function.parameters.iter().map(|p| p.ty).collect::<Vec<_>>(),
        function.return_type,
    )?;
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
                return Err("MIR constructor unwind plan is invalid".into());
            }
        }
        _ => return Err("MIR constructor unwind plan presence is invalid".into()),
    }
    let mut work = VecDeque::from([(
        function.entry,
        aether_frontend::ClassInitializationState::default(),
        BTreeMap::<LocalId, bool>::new(),
        false,
    )]);
    let mut visited = BTreeSet::new();
    while let Some((block, mut fields, mut allocations, mut construction_cleaned)) =
        work.pop_front()
    {
        if !visited.insert((
            block,
            fields.clone(),
            allocations.clone(),
            construction_cleaned,
        )) {
            continue;
        }
        for instruction in &function.blocks[block.0 as usize].instructions {
            let exceptional = instruction.unwind.map(|target| {
                (
                    target,
                    fields.clone(),
                    allocations.clone(),
                    construction_cleaned,
                )
            });
            match &instruction.value {
                Rvalue::Class(op) => {
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
                        ClassOp::BaseInit { base, .. } => fields.complete_base(types, *base)?,
                        ClassOp::ObjectAlloc { .. } => {
                            let result = place_root_local(&instruction.destination)
                                .ok_or("allocation must own a local")?;
                            if allocations.insert(result, false).is_some() {
                                return Err(
                                    "MIR allocation overwrites an unpublished object".into()
                                );
                            }
                        }
                        ClassOp::InitCall { object, .. } => {
                            let object = operand_local_id(object)
                                .ok_or("initializer requires allocated object")?;
                            if allocations.get(&object) != Some(&false) {
                                return Err(
                                    "MIR initializer requires one preceding allocation".into()
                                );
                            }
                            allocations.insert(object, true);
                        }
                        ClassOp::PublishObject { object, .. } => {
                            let object = operand_local_id(object)
                                .ok_or("publication requires allocated object")?;
                            if allocations.remove(&object) != Some(true) {
                                return Err("MIR publication requires completed initialization exactly once".into());
                            }
                        }
                        ClassOp::ConstructionCleanup {
                            class,
                            object,
                            fields: cleanup,
                            free_allocation,
                        } => {
                            if *free_allocation {
                                let object = operand_local_id(object)
                                    .ok_or("allocation cleanup requires unpublished object")?;
                                if !cleanup.is_empty() || allocations.remove(&object) != Some(false)
                                {
                                    return Err("MIR allocation cleanup is not exactly once before publication".into());
                                }
                            } else {
                                if init != Some(*class) || construction_cleaned {
                                    return Err("MIR partial-construction cleanup is duplicated or outside init".into());
                                }
                                let expected =
                                    types.classes()[class.0 as usize]
                                        .destruction
                                        .iter()
                                        .filter_map(|step| match step {
                                            aether_frontend::ClassDropStep::Field {
                                                field, ..
                                            } if fields.contains(field) => Some(*field),
                                            _ => None,
                                        })
                                        .collect::<Vec<_>>();
                                if *cleanup != expected {
                                    return Err("MIR partial-construction cleanup omits, duplicates or reorders fields".into());
                                }
                                fields = aether_frontend::ClassInitializationState::default();
                                construction_cleaned = true;
                            }
                        }
                        ClassOp::FieldRead { receiver, field }
                        | ClassOp::FieldWrite {
                            receiver, field, ..
                        } if matches!(
                            types.get(operand_type(function, receiver)?),
                            Some(TypeData::ClassToken {
                                kind: ClassTokenKind::Receiver {
                                    initializing: true,
                                    ..
                                },
                                ..
                            })
                        ) =>
                        {
                            fields.require_base(
                                types,
                                init.ok_or("base init outside initializer")?,
                            )?;
                            if init != types.object_class(operand_type(function, receiver)?) {
                                return Err(
                                    "MIR initializer receiver outside its constructor".into()
                                );
                            }
                            if let ClassOp::FieldWrite { initialize, .. } = op.as_ref() {
                                if (!*initialize && !fields.contains(field))
                                    || (*initialize
                                        && fields.contains(field)
                                        && types
                                            .class_field(*field)
                                            .is_some_and(|f| types.needs_drop(f.ty)))
                                {
                                    return Err("MIR FieldInit/replace state mismatch".into());
                                }
                                fields.insert(*field);
                            } else if !fields.contains(field) {
                                return Err("MIR field read before initialization".into());
                            }
                        }
                        _ => (),
                    }
                }
                Rvalue::Call { callee, .. }
                    if signatures
                        .get(callee.0 as usize)
                        .is_some_and(|s| types.class_method(s.function_id).is_some()) =>
                {
                    return Err("MIR ordinary call bypasses receiver/constructor protocol".into());
                }
                Rvalue::Move { source } | Rvalue::Drop { owner: source }
                    if place_root_local(source).is_some_and(|l| {
                        matches!(
                            types.get(function.locals[l.0 as usize].ty),
                            Some(TypeData::ClassToken {
                                kind: ClassTokenKind::Unpublished,
                                ..
                            })
                        )
                    }) =>
                {
                    return Err("MIR unpublished object cannot move/drop through ordinary ownership operations".into());
                }
                _ => (),
            }
            if let Some(edge) = exceptional {
                work.push_back(edge);
            }
        }
        let term = function.blocks[block.0 as usize]
            .terminator
            .as_ref()
            .unwrap();
        if matches!(term, Terminator::Return(_)) {
            if let Some(c) = init {
                fields.require_base(types, c)?;
            }
            if !allocations.is_empty() {
                return Err("MIR normal return leaves unpublished allocation".into());
            }
            if construction_cleaned {
                return Err(
                    "MIR normal initializer path used exceptional construction cleanup".into(),
                );
            }
            if init.is_some_and(|c| {
                types.classes()[c.0 as usize]
                    .fields
                    .iter()
                    .any(|f| !fields.contains(&f.id))
            }) {
                return Err("MIR initializer returns before every field is initialized".into());
            }
        }
        if matches!(term, Terminator::ResumeUnwind { .. }) {
            if !allocations.is_empty() {
                return Err("MIR exceptional exit leaks an unpublished allocation".into());
            }
            if init.is_some() && !construction_cleaned {
                return Err(
                    "MIR initializer exceptional exit omits partial-construction cleanup".into(),
                );
            }
        }
        for target in targets(term) {
            work.push_back((
                target,
                fields.clone(),
                allocations.clone(),
                construction_cleaned,
            ));
        }
    }
    Ok(())
}
