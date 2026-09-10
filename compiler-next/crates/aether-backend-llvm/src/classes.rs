//! Private one-pointer concrete class ABI. No semantic ownership inference here.
#![allow(clippy::wildcard_imports)]
use super::*;
use aether_frontend::{ClassId, ClassOp, ClassTokenKind};

/// Closed direct-call reachability lets unused class declarations add no ARC
/// runtime. This is emission policy; all functions were already verified.
pub(super) fn reachable_functions(
    program: &aether_middle::SsaIr,
) -> BTreeSet<aether_frontend::InstanceId> {
    let mut reachable = BTreeSet::new();
    let mut pending = vec![program.entry];
    while let Some(id) = pending.pop() {
        if !reachable.insert(id) {
            continue;
        }
        let function = program.functions.iter().find(|f| f.id == id).unwrap();
        for instruction in function.blocks.iter().flat_map(|b| &b.instructions) {
            match &instruction.op {
                SsaOp::Call { callee, .. } => pending.push(*callee),
                SsaOp::Class(op) => match op.as_ref() {
                    ClassOp::InterfaceAdapt { witness, .. } => {
                        for slot in &program.types.witnesses()[witness.0 as usize].slots {
                            pending.push(
                                program
                                    .signatures
                                    .iter()
                                    .find(|s| s.function_id == slot.method)
                                    .unwrap()
                                    .id,
                            );
                        }
                    }
                    ClassOp::DirectMethodCall { method, .. } => pending.push(*method),
                    ClassOp::InitCall { initializer, .. } => pending.push(*initializer),
                    _ => (),
                },
                _ => (),
            }
        }
    }
    reachable
}

pub(super) fn runtime(output: &mut String, types: &TypeArena) {
    for counter in ["alloc", "retain", "release", "destroy", "buffer_drop"] {
        writeln!(
            output,
            "@aether_object_{counter}_count = internal global i64 0"
        )
        .unwrap();
    }
    output.push_str("define internal void @aether_object_retain(ptr %object) {\nentry:\n  %count = load i64, ptr %object\n  %zero = icmp eq i64 %count, 0\n  %full = icmp eq i64 %count, -1\n  %bad = or i1 %zero, %full\n  br i1 %bad, label %invalid, label %live\nlive:\n  %next = add i64 %count, 1\n  store i64 %next, ptr %object\n  %events = load i64, ptr @aether_object_retain_count\n  %events_next = add i64 %events, 1\n  store i64 %events_next, ptr @aether_object_retain_count\n  ret void\ninvalid:\n  call void @llvm.trap()\n  unreachable\n}\n");
    for class in types.classes() {
        writeln!(output,"define internal ptr @aether_object_alloc_{}() {{\nentry:\n  %object = call ptr @aether_alloc(i64 {}, i64 {})\n  store i64 1, ptr %object\n  %events = load i64, ptr @aether_object_alloc_count\n  %next = add i64 %events, 1\n  store i64 %next, ptr @aether_object_alloc_count\n  ret ptr %object\n}}",class.id.0,class.layout.size,class.layout.align).unwrap();
    }
}

pub(super) fn drop_body(output: &mut String, types: &TypeArena, class: ClassId) {
    let info = &types.classes()[class.0 as usize];
    output.push_str("  %count = load i64, ptr %value\n  %zero = icmp eq i64 %count, 0\n  br i1 %zero, label %invalid, label %live\ninvalid:\n  call void @llvm.trap()\n  unreachable\nlive:\n  %next = sub i64 %count, 1\n  store i64 %next, ptr %value\n  %events = load i64, ptr @aether_object_release_count\n  %events_next = add i64 %events, 1\n  store i64 %events_next, ptr @aether_object_release_count\n  %last = icmp eq i64 %next, 0\n  br i1 %last, label %destroy, label %done\ndestroy:\n");
    for step in &info.destruction {
        let aether_frontend::ClassDropStep::Field { field, .. } = step else {
            continue;
        };
        let field = types.class_field(*field).unwrap();
        writeln!(output,"  %field{} = getelementptr i8, ptr %value, i64 {}\n  %owned{} = load {}, ptr %field{}\n  call void @aether_drop_{}({} %owned{})",field.id.0,field.offset,field.id.0,llvm_type(types,field.ty),field.id.0,mangle_type(types,field.ty),llvm_type(types,field.ty),field.id.0).unwrap();
        writeln!(output,"  %bd{} = load i64, ptr @aether_object_buffer_drop_count\n  %bn{} = add i64 %bd{}, 1\n  store i64 %bn{}, ptr @aether_object_buffer_drop_count",field.id.0,field.id.0,field.id.0,field.id.0).unwrap();
    }
    writeln!(output,"  %destroyed = load i64, ptr @aether_object_destroy_count\n  %destroyed_next = add i64 %destroyed, 1\n  store i64 %destroyed_next, ptr @aether_object_destroy_count\n  call void @aether_free(ptr %value, i64 {}, i64 {})\n  br label %done\ndone:\n  ret void\n}}\n",info.layout.size,info.layout.align).unwrap();
}

pub(super) fn token_suffix(kind: ClassTokenKind) -> &'static str {
    match kind {
        ClassTokenKind::Unpublished => "unpublished",
        ClassTokenKind::Receiver {
            initializing: true, ..
        } => "init_receiver",
        ClassTokenKind::Receiver { mutable: true, .. } => "mut_receiver",
        ClassTokenKind::Receiver { mutable: false, .. } => "read_receiver",
        ClassTokenKind::Keepalive { mutable: true } => "mut_keepalive",
        ClassTokenKind::Keepalive { mutable: false } => "read_keepalive",
    }
}

#[allow(clippy::too_many_arguments, clippy::too_many_lines)]
pub(super) fn emit_op(
    output: &mut String,
    op: &ClassOp<SsaOperand, aether_frontend::InstanceId>,
    result: u32,
    result_type: TypeId,
    types: &TypeArena,
    signatures: &[FunctionInstanceInfo],
    modules: &[ModuleInfo],
    structs: &[StructInfo],
    enums: &[EnumInfo],
) {
    if types.interface_identity(result_type).is_some() {
        match op {
            ClassOp::HandleAlias { source }
            | ClassOp::ReceiverKeepalive {
                source,
                transfer: false,
                ..
            } => {
                writeln!(output, "  %obj{result} = extractvalue {{ ptr, ptr }} {}, 0\n  call void @aether_object_retain(ptr %obj{result})\n  %v{result} = select i1 true, {{ ptr, ptr }} {}, {{ ptr, ptr }} {}",llvm_operand(source),llvm_operand(source),llvm_operand(source)).unwrap();
                return;
            }
            ClassOp::HandleTransfer { source }
            | ClassOp::ReceiverKeepalive {
                source,
                transfer: true,
                ..
            } => {
                writeln!(
                    output,
                    "  %v{result} = select i1 true, {{ ptr, ptr }} {}, {{ ptr, ptr }} {}",
                    llvm_operand(source),
                    llvm_operand(source)
                )
                .unwrap();
                return;
            }
            _ => (),
        }
    }
    match op {
        ClassOp::InterfaceAdapt {
            witness,
            source,
            transfer,
            ..
        } => {
            if !transfer {
                writeln!(
                    output,
                    "  call void @aether_object_retain(ptr {})",
                    llvm_operand(source)
                )
                .unwrap();
            }
            writeln!(output,"  %carrier{result} = insertvalue {{ ptr, ptr }} poison, ptr {}, 0\n  %v{result} = insertvalue {{ ptr, ptr }} %carrier{result}, ptr @aether_witness_{}, 1",llvm_operand(source),witness.0).unwrap();
        }
        ClassOp::InterfaceCall {
            requirement,
            slot,
            receiver,
            args,
        } => {
            let r = types.requirement(*requirement).unwrap();
            writeln!(output,"  %obj{result} = extractvalue {{ ptr, ptr }} {}, 0\n  %wit{result} = extractvalue {{ ptr, ptr }} {}, 1\n  %slot{result} = getelementptr ptr, ptr %wit{result}, i64 {}\n  %target{result} = load ptr, ptr %slot{result}",llvm_operand(receiver),llvm_operand(receiver),slot+1).unwrap();
            let arguments = std::iter::once(format!("ptr %obj{result}"))
                .chain(
                    args.iter()
                        .zip(&r.parameters)
                        .map(|(a, t)| format!("{} {}", llvm_type(types, *t), llvm_operand(a))),
                )
                .collect::<Vec<_>>()
                .join(", ");
            writeln!(
                output,
                "  %v{result} = call {} %target{result}({arguments})",
                llvm_type(types, r.result)
            )
            .unwrap();
        }
        ClassOp::ObjectAlloc { class } => writeln!(
            output,
            "  %v{result} = call ptr @aether_object_alloc_{}()",
            class.0
        )
        .unwrap(),
        ClassOp::HandleAlias { source }
        | ClassOp::ReceiverKeepalive {
            source,
            transfer: false,
            ..
        } => {
            writeln!(output,"  call void @aether_object_retain(ptr {})\n  %v{result} = getelementptr i8, ptr {}, i64 0",llvm_operand(source),llvm_operand(source)).unwrap();
        }
        ClassOp::HandleTransfer { source }
        | ClassOp::ReceiverKeepalive {
            source,
            transfer: true,
            ..
        }
        | ClassOp::PublishObject { object: source, .. } => writeln!(
            output,
            "  %v{result} = getelementptr i8, ptr {}, i64 0",
            llvm_operand(source)
        )
        .unwrap(),
        ClassOp::InitCall {
            initializer: method,
            object: receiver,
            args,
            ..
        }
        | ClassOp::DirectMethodCall {
            method,
            receiver,
            args,
        } => {
            let sig = &signatures[method.0 as usize];
            let arguments = std::iter::once(receiver)
                .chain(args)
                .zip(&sig.parameters)
                .map(|(o, p)| format!("{} {}", llvm_type(types, p.ty), llvm_operand(o)))
                .collect::<Vec<_>>()
                .join(", ");
            let name = bootstrap_symbol(sig, modules, structs, enums, types);
            if matches!(op, ClassOp::InitCall { .. }) {
                writeln!(output,"  %init{result} = call {} @{name}({arguments})\n  %v{result} = or i1 false, true",llvm_type(types,sig.return_type)).unwrap();
            } else {
                writeln!(
                    output,
                    "  %v{result} = call {} @{name}({arguments})",
                    llvm_type(types, sig.return_type)
                )
                .unwrap();
            }
        }
        ClassOp::FieldRead { receiver, field }
        | ClassOp::FieldWrite {
            receiver, field, ..
        } => {
            let field = types.class_field(*field).unwrap();
            let ty = llvm_type(types, field.ty);
            writeln!(
                output,
                "  %field{result} = getelementptr i8, ptr {}, i64 {}",
                llvm_operand(receiver),
                field.offset
            )
            .unwrap();
            if let ClassOp::FieldWrite {
                value, initialize, ..
            } = op
            {
                if !initialize && types.needs_drop(field.ty) {
                    writeln!(output, "  %old{result} = load {ty}, ptr %field{result}").unwrap();
                }
                writeln!(
                    output,
                    "  store {ty} {}, ptr %field{result}",
                    llvm_operand(value)
                )
                .unwrap();
                if !initialize && types.needs_drop(field.ty) {
                    writeln!(
                        output,
                        "  call void @aether_drop_{}({ty} %old{result})",
                        mangle_type(types, field.ty)
                    )
                    .unwrap();
                }
                writeln!(output, "  %v{result} = or i1 false, true").unwrap();
            } else {
                writeln!(output, "  %v{result} = load {ty}, ptr %field{result}").unwrap();
            }
        }
        ClassOp::IdentityEq {
            left,
            right,
            unequal,
        } => writeln!(
            output,
            "  %v{result} = icmp {} ptr {}, {}",
            if *unequal { "ne" } else { "eq" },
            llvm_operand(left),
            llvm_operand(right)
        )
        .unwrap(),
        ClassOp::Construct { .. } => unreachable!("ClassInit must be lowered before LLVM"),
    }
}

pub(super) fn witnesses(output: &mut String, program: &aether_middle::SsaIr) {
    let reachable = reachable_functions(program);
    let used = program
        .functions
        .iter()
        .filter(|f| reachable.contains(&f.id))
        .flat_map(|f| &f.blocks)
        .flat_map(|b| &b.instructions)
        .filter_map(|i| {
            if let SsaOp::Class(op) = &i.op
                && let ClassOp::InterfaceAdapt { witness, .. } = op.as_ref()
            {
                Some(*witness)
            } else {
                None
            }
        })
        .collect::<BTreeSet<_>>();
    for id in used {
        let w = &program.types.witnesses()[id.0 as usize];
        let ty = program.types.id_of(TypeData::Class(w.class)).unwrap();
        let mut slots = vec![format!(
            "ptr @aether_drop_{}",
            mangle_type(&program.types, ty)
        )];
        for s in &w.slots {
            let sig = program
                .signatures
                .iter()
                .find(|f| f.function_id == s.method)
                .unwrap();
            // The erased and concrete receivers both lower to ptr. All remaining
            // parameter/result types are exact; no ABI adaptation thunk is needed.
            slots.push(format!(
                "ptr @{}",
                bootstrap_symbol(
                    sig,
                    &program.modules,
                    &program.structs,
                    &program.enums,
                    &program.types
                )
            ));
        }
        writeln!(
            output,
            "@aether_witness_{} = internal constant [{} x ptr] [{}]",
            id.0,
            slots.len(),
            slots.join(", ")
        )
        .unwrap();
    }
}
