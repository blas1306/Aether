//! Bounded concrete class identities and explicit object protocols.
#![allow(missing_docs)]
use crate::{
    AstField, AstFunction, FieldId, FunctionId, HirCallTarget, ModuleId, Span, TypeId, TypeLayout,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ClassId(pub u32);

/// Compiler-only states: none has a source type spelling.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ClassTokenKind {
    Unpublished,
    Receiver { mutable: bool, initializing: bool },
    Keepalive { mutable: bool },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstClass {
    pub relations: Vec<crate::AstType>,
    pub name: String,
    pub public: bool,
    pub fields: Vec<(bool, AstField)>,
    pub methods: Vec<AstClassMethod>,
    pub initializer: Option<AstClassMethod>,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstClassMethod {
    pub public: bool,
    pub mutable: bool,
    pub function: AstFunction,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClassFieldInfo {
    pub id: FieldId,
    pub class: ClassId,
    pub name: String,
    pub ty: TypeId,
    pub public: bool,
    pub index: u32,
    pub offset: u64,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClassMethodInfo {
    pub parameters: Vec<TypeId>,
    pub result: TypeId,
    pub function: FunctionId,
    pub name: String,
    pub public: bool,
    pub mutable: bool,
    pub initializing: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClassInfo {
    pub interfaces: Vec<crate::InterfaceId>,
    pub id: ClassId,
    pub module: ModuleId,
    pub name: String,
    pub public: bool,
    pub fields: Vec<ClassFieldInfo>,
    pub methods: Vec<ClassMethodInfo>,
    pub layout: TypeLayout,
    /// Verified final-release recipe, in execution order.
    pub destruction: Vec<ClassDropStep>,
    pub span: Span,
}

/// These operations survive as ordered semantic effects through MIR and SSA.
/// HIR alone uses `Construct`; its lowering materializes `ObjectAlloc`, `InitCall`, `PublishObject`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ClassOp<O, F = HirCallTarget> {
    InterfaceAdapt {
        class: ClassId,
        interface: crate::InterfaceId,
        witness: crate::WitnessId,
        source: O,
        transfer: bool,
    },
    InterfaceCall {
        requirement: crate::RequirementId,
        slot: u32,
        receiver: O,
        args: Vec<O>,
    },
    Construct {
        class: ClassId,
        initializer: F,
        args: Vec<O>,
    },
    ObjectAlloc {
        class: ClassId,
    },
    InitCall {
        class: ClassId,
        initializer: F,
        object: O,
        args: Vec<O>,
    },
    PublishObject {
        class: ClassId,
        object: O,
    },
    HandleAlias {
        source: O,
    },
    HandleTransfer {
        source: O,
    },
    /// Acquires a strong token from a stable evaluated identity before arguments.
    ReceiverKeepalive {
        source: O,
        mutable: bool,
        transfer: bool,
    },
    FieldRead {
        receiver: O,
        field: FieldId,
    },
    /// initialize is a definite field state, independently checked in each IR.
    FieldWrite {
        receiver: O,
        field: FieldId,
        value: O,
        initialize: bool,
    },
    DirectMethodCall {
        method: F,
        receiver: O,
        args: Vec<O>,
    },
    IdentityEq {
        left: O,
        right: O,
        unequal: bool,
    },
}
impl<O, F> ClassOp<O, F> {
    pub fn operands(&self) -> Vec<&O> {
        match self {
            Self::InterfaceCall { receiver, args, .. }
            | Self::DirectMethodCall { receiver, args, .. } => {
                std::iter::once(receiver).chain(args).collect()
            }
            Self::Construct { args, .. } => args.iter().collect(),
            Self::ObjectAlloc { .. } => vec![],
            Self::InitCall { object, args, .. } => std::iter::once(object).chain(args).collect(),
            Self::PublishObject { object, .. } => vec![object],
            Self::InterfaceAdapt { source, .. }
            | Self::HandleAlias { source }
            | Self::HandleTransfer { source }
            | Self::ReceiverKeepalive { source, .. } => vec![source],
            Self::FieldRead { receiver, .. } => vec![receiver],
            Self::FieldWrite {
                receiver, value, ..
            } => vec![receiver, value],
            Self::IdentityEq { left, right, .. } => vec![left, right],
        }
    }
    pub fn map<P, G, E>(
        &self,
        mut operand: impl FnMut(&O) -> Result<P, E>,
        mut function: impl FnMut(&F) -> Result<G, E>,
    ) -> Result<ClassOp<P, G>, E> {
        Ok(match self {
            Self::InterfaceAdapt {
                class,
                interface,
                witness,
                source,
                transfer,
            } => ClassOp::InterfaceAdapt {
                class: *class,
                interface: *interface,
                witness: *witness,
                source: operand(source)?,
                transfer: *transfer,
            },
            Self::InterfaceCall {
                requirement,
                slot,
                receiver,
                args,
            } => ClassOp::InterfaceCall {
                requirement: *requirement,
                slot: *slot,
                receiver: operand(receiver)?,
                args: args.iter().map(&mut operand).collect::<Result<_, _>>()?,
            },
            Self::Construct {
                class,
                initializer,
                args,
            } => ClassOp::Construct {
                class: *class,
                initializer: function(initializer)?,
                args: args.iter().map(&mut operand).collect::<Result<_, _>>()?,
            },
            Self::ObjectAlloc { class } => ClassOp::ObjectAlloc { class: *class },
            Self::InitCall {
                class,
                initializer,
                object,
                args,
            } => ClassOp::InitCall {
                class: *class,
                initializer: function(initializer)?,
                object: operand(object)?,
                args: args.iter().map(&mut operand).collect::<Result<_, _>>()?,
            },
            Self::PublishObject { class, object } => ClassOp::PublishObject {
                class: *class,
                object: operand(object)?,
            },
            Self::HandleAlias { source } => ClassOp::HandleAlias {
                source: operand(source)?,
            },
            Self::HandleTransfer { source } => ClassOp::HandleTransfer {
                source: operand(source)?,
            },
            Self::ReceiverKeepalive {
                source,
                mutable,
                transfer,
            } => ClassOp::ReceiverKeepalive {
                source: operand(source)?,
                mutable: *mutable,
                transfer: *transfer,
            },
            Self::FieldRead { receiver, field } => ClassOp::FieldRead {
                receiver: operand(receiver)?,
                field: *field,
            },
            Self::FieldWrite {
                receiver,
                field,
                value,
                initialize,
            } => ClassOp::FieldWrite {
                receiver: operand(receiver)?,
                field: *field,
                value: operand(value)?,
                initialize: *initialize,
            },
            Self::DirectMethodCall {
                method,
                receiver,
                args,
            } => ClassOp::DirectMethodCall {
                method: function(method)?,
                receiver: operand(receiver)?,
                args: args.iter().map(&mut operand).collect::<Result<_, _>>()?,
            },
            Self::IdentityEq {
                left,
                right,
                unequal,
            } => ClassOp::IdentityEq {
                left: operand(left)?,
                right: operand(right)?,
                unequal: *unequal,
            },
        })
    }
}

/// Independent phase-local callers supply operand types and immutable signatures.
/// No earlier verifier's success flag is consulted.
#[allow(clippy::too_many_lines)]
pub fn verify_class_op<O, F>(
    op: &ClassOp<O, F>,
    result: TypeId,
    types: &crate::TypeArena,
    operand_ty: impl Fn(&O) -> Result<TypeId, String>,
    signature: impl Fn(&F) -> Result<(FunctionId, Vec<TypeId>, TypeId), String>,
) -> Result<(), String> {
    use crate::TypeData;
    let require = |valid, message: &str| {
        if valid {
            Ok(())
        } else {
            Err(message.to_owned())
        }
    };
    let class_ty = |class| {
        types
            .id_of(TypeData::Class(class))
            .ok_or_else(|| "unknown ClassId".to_owned())
    };
    let token_ty = |class, kind| {
        types
            .id_of(TypeData::ClassToken { class, kind })
            .ok_or_else(|| "unknown class token type".to_owned())
    };
    let call =
        |function: &F, args: &[O], initializing: bool| -> Result<(crate::ClassId, bool), String> {
            let (id, params, ret) = signature(function)?;
            let (class, method) = types
                .class_method(id)
                .ok_or("invalid class method identity")?;
            require(
                method.initializing == initializing,
                "invalid initializer/method role",
            )?;
            require(
                params.len() == args.len() + 1,
                "class method signature arity mismatch",
            )?;
            require(
                params.first().copied()
                    == Some(token_ty(
                        class,
                        ClassTokenKind::Receiver {
                            mutable: method.mutable,
                            initializing,
                        },
                    )?),
                "class method receiver signature mismatch",
            )?;
            for (arg, param) in args.iter().zip(&params[1..]) {
                require(operand_ty(arg)? == *param, "class argument type mismatch")?;
            }
            if !initializing {
                require(result == ret, "class method result mismatch")?;
            }
            Ok((class, method.mutable))
        };
    match op {
        ClassOp::InterfaceAdapt {
            class,
            interface,
            witness,
            source,
            ..
        } => {
            let w = types
                .witnesses()
                .get(witness.0 as usize)
                .ok_or("invalid witness identity")?;
            require(
                w.id == *witness
                    && w.class == *class
                    && w.interface == *interface
                    && types.class_id(operand_ty(source)?) == Some(*class)
                    && types.interface_id(result) == Some(*interface),
                "interface adaptation identity/witness mismatch",
            )?;
            crate::verify_interface_metadata(types)?;
        }
        ClassOp::InterfaceCall {
            requirement,
            slot,
            receiver,
            args,
        } => {
            let r = types
                .requirement(*requirement)
                .ok_or("invalid interface requirement identity")?;
            require(
                *slot == r.id.index && result == r.result && args.len() == r.parameters.len(),
                "interface call slot/result/arity mismatch",
            )?;
            require(
                matches!(types.get(operand_ty(receiver)?), Some(TypeData::InterfaceKeepalive { interface, mutable }) if *interface == r.id.interface && (!r.mutable || *mutable)),
                "interface call requires exact live receiver capability",
            )?;
            for (arg, param) in args.iter().zip(&r.parameters) {
                require(
                    operand_ty(arg)? == *param,
                    "interface argument contract mismatch",
                )?;
            }
        }
        ClassOp::Construct {
            class,
            initializer,
            args,
        } => {
            require(
                call(initializer, args, true)?.0 == *class && result == class_ty(*class)?,
                "constructor class identity mismatch",
            )?;
        }
        ClassOp::ObjectAlloc { class } => {
            require(
                types
                    .classes()
                    .get(class.0 as usize)
                    .is_some_and(|c| c.id == *class),
                "invalid allocation ClassId",
            )?;
            require(
                result == token_ty(*class, ClassTokenKind::Unpublished)?,
                "allocation cannot publish a source handle",
            )?;
        }
        ClassOp::InitCall {
            class,
            initializer,
            object,
            args,
        } => {
            require(
                call(initializer, args, true)?.0 == *class
                    && operand_ty(object)? == token_ty(*class, ClassTokenKind::Unpublished)?
                    && result == TypeId::BOOL,
                "invalid initialization call",
            )?;
        }
        ClassOp::PublishObject { class, object } => require(
            operand_ty(object)? == token_ty(*class, ClassTokenKind::Unpublished)?
                && result == class_ty(*class)?,
            "invalid publication identity/state",
        )?,
        ClassOp::HandleAlias { source } => require(
            types.is_object_owner(result)
                && operand_ty(source)? == result
                && !types.guarantees_copy(result),
            "Alias requires an owning class lvalue; class is not Copy",
        )?,
        ClassOp::HandleTransfer { source } => require(
            types.is_object_owner(result) && operand_ty(source)? == result,
            "Transfer class mismatch",
        )?,
        ClassOp::ReceiverKeepalive {
            source,
            mutable,
            transfer,
        } => {
            let ty = operand_ty(source)?;
            if let Some(interface) = types.interface_id(ty) {
                require(
                    types.get(result)
                        == Some(&TypeData::InterfaceKeepalive {
                            interface,
                            mutable: *mutable,
                        }),
                    "interface keepalive capability mismatch",
                )?;
                return Ok(());
            }
            let class = types
                .object_class(ty)
                .ok_or("keepalive requires class identity")?;
            require(
                result == token_ty(class, ClassTokenKind::Keepalive { mutable: *mutable })?,
                "keepalive capability mismatch",
            )?;
            match types.get(ty) {
                Some(TypeData::Class(_)) => (),
                Some(TypeData::ClassToken {
                    kind:
                        ClassTokenKind::Receiver {
                            mutable: source_mut,
                            initializing: false,
                        },
                    ..
                }) => require(
                    !transfer && (!mutable || *source_mut),
                    "receiver capability escalation",
                )?,
                _ => {
                    return Err(
                        "unpublished object or keepalive cannot be acquired as source receiver"
                            .into(),
                    );
                }
            }
        }
        ClassOp::FieldRead { receiver, field }
        | ClassOp::FieldWrite {
            receiver, field, ..
        } => {
            let info = types.class_field(*field).ok_or("invalid Class FieldId")?;
            let receiver_ty = operand_ty(receiver)?;
            require(
                types.object_class(receiver_ty) == Some(info.class),
                "field belongs to a different class",
            )?;
            match types.get(receiver_ty) {
                Some(
                    TypeData::Class(_)
                    | TypeData::ClassToken {
                        kind: ClassTokenKind::Receiver { .. } | ClassTokenKind::Keepalive { .. },
                        ..
                    },
                ) => (),
                _ => return Err("invalid field receiver state".into()),
            }
            if let ClassOp::FieldWrite {
                value, initialize, ..
            } = op
            {
                require(
                    !matches!(
                        types.get(receiver_ty),
                        Some(TypeData::ClassToken {
                            kind: ClassTokenKind::Receiver { mutable: false, .. }
                                | ClassTokenKind::Keepalive { mutable: false },
                            ..
                        })
                    ),
                    "mutation through read receiver",
                )?;
                require(
                    !initialize
                        || matches!(
                            types.get(receiver_ty),
                            Some(TypeData::ClassToken {
                                kind: ClassTokenKind::Receiver {
                                    initializing: true,
                                    ..
                                },
                                ..
                            })
                        ),
                    "FieldInit requires initializer receiver",
                )?;
                require(
                    operand_ty(value)? == info.ty && result == TypeId::BOOL,
                    "field write type mismatch",
                )?;
            } else {
                require(
                    result == info.ty && types.guarantees_copy(info.ty),
                    "owning field extraction or field read type mismatch",
                )?;
            }
        }
        ClassOp::DirectMethodCall {
            method,
            receiver,
            args,
        } => {
            let (class, mutable) = call(method, args, false)?;
            require(
                matches!(types.get(operand_ty(receiver)?),Some(TypeData::ClassToken { class:c, kind:ClassTokenKind::Keepalive { mutable:m } }) if *c == class && (!mutable || *m)),
                "direct method requires a keepalive of the exact class and capability",
            )?;
        }
        ClassOp::IdentityEq { left, right, .. } => {
            let l = operand_ty(left)?;
            require(
                types.class_id(l).is_some() && operand_ty(right)? == l && result == TypeId::BOOL,
                "identity equality class mismatch",
            )?;
        }
    }
    Ok(())
}

/// Lexical visibility is independent of offsets or public linkage.
pub fn verify_class_access<O, F>(
    op: &ClassOp<O, F>,
    types: &crate::TypeArena,
    caller: FunctionId,
    module: ModuleId,
    function: impl Fn(&F) -> Result<FunctionId, String>,
) -> Result<(), String> {
    let own_class = types.class_method(caller).map(|(c, _)| c);
    let member = |class, public| {
        if public || own_class == Some(class) {
            Ok(())
        } else {
            Err("private class member is inaccessible".to_owned())
        }
    };
    match op {
        ClassOp::Construct {
            class, initializer, ..
        }
        | ClassOp::InitCall {
            class, initializer, ..
        } => {
            let c = types
                .classes()
                .get(class.0 as usize)
                .ok_or("unknown class")?;
            if c.module != module && !c.public {
                return Err("internal class crosses module boundary".into());
            }
            let (_, m) = types
                .class_method(function(initializer)?)
                .ok_or("unknown initializer")?;
            member(*class, m.public)
        }
        ClassOp::DirectMethodCall { method, .. } => {
            let (class, m) = types
                .class_method(function(method)?)
                .ok_or("unknown method")?;
            member(class, m.public)
        }
        ClassOp::FieldRead { field, .. } | ClassOp::FieldWrite { field, .. } => {
            let f = types.class_field(*field).ok_or("unknown class field")?;
            member(f.class, f.public)
        }
        _ => Ok(()),
    }
}

/// Compiler-generated recursive final-release protocol; no user destructor.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ClassDropStep {
    Field { field: FieldId, ty: TypeId },
    Free { layout: TypeLayout },
}

/// Validate object metadata independently at every verified boundary.
pub fn verify_class_metadata(
    types: &crate::TypeArena,
    structs: &[crate::StructInfo],
    enums: &[crate::EnumInfo],
) -> Result<(), String> {
    use crate::TypeData;
    crate::verify_interface_metadata(types)?;
    let mut fields = std::collections::BTreeSet::new();
    let mut methods = std::collections::BTreeSet::new();
    for (index, c) in types.classes().iter().enumerate() {
        if c.id.0 as usize != index || types.id_of(TypeData::Class(c.id)).is_none() {
            return Err("invalid nominal ClassId".into());
        }
        let mut offset = 8_u64;
        let mut align = 8;
        let mut names = std::collections::BTreeSet::new();
        for (index, f) in c.fields.iter().enumerate() {
            if f.class != c.id
                || f.index as usize != index
                || !fields.insert(f.id)
                || !names.insert(&f.name)
                || structs
                    .iter()
                    .flat_map(|s| &s.fields)
                    .any(|sf| sf.id == f.id)
            {
                return Err("invalid class field identity".into());
            }
            if (types.buffer_element(f.ty) != Some(TypeId::INT64) || f.public)
                && (!types.guarantees_copy(f.ty)
                    || types.contains_owning(f.ty)
                    || types.contains_reference(f.ty)
                    || types.contains_view(f.ty)
                    || types.contains_generic(f.ty))
            {
                return Err("inadmissible class field storage or graph edge".into());
            }
            let layout = crate::layout_of(
                types,
                f.ty,
                crate::TargetProperties::LINUX_X86_64,
                structs,
                enums,
            )
            .ok_or("class field has no concrete layout")?;
            align = align.max(layout.align);
            offset = offset.div_ceil(layout.align) * layout.align;
            if f.offset != offset {
                return Err("class field offset differs from target layout".into());
            }
            offset += layout.size;
        }
        let expected = TypeLayout {
            size: offset.div_ceil(align) * align,
            align,
        };
        if c.layout != expected {
            return Err("class object layout mismatch".into());
        }
        let recipe = c
            .fields
            .iter()
            .rev()
            .filter(|f| types.needs_drop(f.ty))
            .map(|f| ClassDropStep::Field {
                field: f.id,
                ty: f.ty,
            })
            .chain(std::iter::once(ClassDropStep::Free { layout: expected }))
            .collect::<Vec<_>>();
        if c.destruction != recipe {
            return Err(
                "class final destruction must drop every owning field once before one object free"
                    .into(),
            );
        }
        if c.methods.iter().filter(|m| m.initializing).count() != 1 {
            return Err("class requires one initializer target".into());
        }
        for m in &c.methods {
            if !methods.insert(m.function) || !names.insert(&m.name) {
                return Err("invalid or conflicting class method identity".into());
            }
        }
    }
    for (id, ty) in types.entries() {
        if types.contains_class(id) && !types.is_object_owner(id) {
            return Err(
                "class-containing storage/reference type requires separate admission".into(),
            );
        }

        if let TypeData::Class(class) | TypeData::ClassToken { class, .. } = ty
            && types.classes().get(class.0 as usize).is_none()
        {
            return Err("type references missing ClassId".into());
        }
    }
    Ok(())
}

/// A borrowed receiver is only the declared first parameter of its exact method.
pub fn verify_class_signature(
    types: &crate::TypeArena,
    function: FunctionId,
    module: ModuleId,
    parameters: &[TypeId],
    result: TypeId,
) -> Result<(), String> {
    use crate::TypeData;
    let method = types.class_method(function);
    if let Some((class, m)) = method {
        let receiver = types.id_of(TypeData::ClassToken {
            class,
            kind: ClassTokenKind::Receiver {
                mutable: m.mutable,
                initializing: m.initializing,
            },
        });
        if parameters.first().copied() != receiver
            || types.classes()[class.0 as usize].module != module
        {
            return Err(
                "class method receiver or declaring module differs from declaration".into(),
            );
        }
        if parameters.get(1..) != Some(m.parameters.as_slice()) || result != m.result {
            return Err("class method signature differs from declaration contract".into());
        }
        if m.initializing && result != TypeId::INT64 {
            return Err("initializer internal completion result mismatch".into());
        }
        if m.public && types.classes()[class.0 as usize].public {
            for ty in parameters
                .iter()
                .skip(1)
                .copied()
                .chain(std::iter::once(result))
            {
                if let Some(i) = types.interface_id(ty)
                    && types
                        .interfaces()
                        .get(i.0 as usize)
                        .is_none_or(|i| !i.public)
                {
                    return Err("public class API exposes an inaccessible interface".into());
                }
                if let Some(c) = types.class_id(ty)
                    && !types.classes()[c.0 as usize].public
                {
                    return Err("public class API exposes an inaccessible class".into());
                }
            }
        }
    }
    for ty in parameters
        .iter()
        .skip(usize::from(method.is_some()))
        .copied()
        .chain(std::iter::once(result))
    {
        if matches!(
            types.get(ty),
            Some(TypeData::ClassToken { .. } | TypeData::InterfaceKeepalive { .. })
        ) {
            return Err("internal class tokens cannot occur in source parameters/results".into());
        }
        if types.contains_class(ty) && !types.is_object_owner(ty) {
            return Err("class-containing references and aggregates are unavailable".into());
        }
    }
    Ok(())
}
