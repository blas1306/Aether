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
    pub(super) fn lower_class(&mut self, op: &ClassOp<HirExpr>, ty: TypeId, span: Span) -> Operand {
        if let ClassOp::Construct {
            class,
            initializer,
            args,
        } = op
        {
            let args = args.iter().map(|e| self.lower_expr(e)).collect();
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
            self.class_value(
                ClassOp::InitCall {
                    class: *class,
                    initializer: *initializer,
                    object: object.clone(),
                    args,
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
        if let ClassOp::DirectMethodCall { receiver, .. } = &mapped {
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
        let result = self.class_value(mapped, ty, span);
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
    let mut work = VecDeque::from([(
        function.entry,
        BTreeSet::<FieldId>::new(),
        BTreeMap::<LocalId, bool>::new(),
    )]);
    let mut visited = BTreeSet::new();
    while let Some((block, mut fields, mut allocations)) = work.pop_front() {
        if !visited.insert((block, fields.clone(), allocations.clone())) {
            continue;
        }
        for instruction in &function.blocks[block.0 as usize].instructions {
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
        }
        let term = function.blocks[block.0 as usize]
            .terminator
            .as_ref()
            .unwrap();
        if matches!(term, Terminator::Return(_)) {
            if !allocations.is_empty() {
                return Err("MIR normal return leaves unpublished allocation".into());
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
        for target in targets(term) {
            work.push_back((target, fields.clone(), allocations.clone()));
        }
    }
    Ok(())
}
