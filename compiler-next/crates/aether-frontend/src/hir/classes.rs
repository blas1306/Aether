//! Class admission and semantic receiver/initialization checking.
#![allow(clippy::wildcard_imports)]
use super::*;
use crate::{AstParameter, AstStmt, ClassFieldInfo, ClassInfo, ClassMethodInfo};

pub(super) fn error(code: &'static str, message: impl Into<String>, span: Span) -> Diagnostic {
    Diagnostic::new(
        code,
        Phase::Semantic,
        DiagnosticCategory::Type,
        message,
        Some(span),
    )
}
fn ast_type(name: &str, span: Span) -> AstType {
    AstType {
        module: None,
        name: name.into(),
        arguments: Vec::new(),
        reference: None,
        span,
    }
}
fn has_return(block: &AstBlock) -> bool {
    block.statements.iter().any(|s| match &s.kind {
        AstStmtKind::Return(_) => true,
        AstStmtKind::If {
            then_block,
            else_block,
            ..
        } => has_return(then_block) || else_block.as_ref().is_some_and(has_return),
        AstStmtKind::While { body, .. } => has_return(body),
        AstStmtKind::Match { arms, .. } => arms.iter().any(|a| has_return(&a.body)),
        AstStmtKind::Try { body, catches } => {
            has_return(body) || catches.iter().any(|catch| has_return(&catch.body))
        }
        _ => false,
    })
}

fn ast_definitely_terminates(block: &AstBlock) -> bool {
    block
        .statements
        .last()
        .is_some_and(|statement| match &statement.kind {
            AstStmtKind::Return(_) | AstStmtKind::Throw(_) => true,
            AstStmtKind::If {
                then_block,
                else_block: Some(else_block),
                ..
            } => ast_definitely_terminates(then_block) && ast_definitely_terminates(else_block),
            AstStmtKind::Match { arms, .. } => {
                !arms.is_empty() && arms.iter().all(|arm| ast_definitely_terminates(&arm.body))
            }
            AstStmtKind::Try { body, catches } => {
                ast_definitely_terminates(body)
                    && catches
                        .iter()
                        .all(|catch| ast_definitely_terminates(&catch.body))
            }
            _ => false,
        })
}

fn block_uses_exceptions(block: &AstBlock) -> bool {
    block
        .statements
        .iter()
        .any(|statement| match &statement.kind {
            AstStmtKind::Throw(_) | AstStmtKind::Try { .. } => true,
            AstStmtKind::If {
                then_block,
                else_block,
                ..
            } => {
                block_uses_exceptions(then_block)
                    || else_block.as_ref().is_some_and(block_uses_exceptions)
            }
            AstStmtKind::While { body, .. } => block_uses_exceptions(body),
            AstStmtKind::Match { arms, .. } => {
                arms.iter().any(|arm| block_uses_exceptions(&arm.body))
            }
            _ => false,
        })
}

pub(super) fn inject_exception_core(program: &mut ParsedProgram) -> Result<(), Vec<Diagnostic>> {
    let needed = program.modules.iter().any(|module| {
        module
            .ast
            .functions
            .iter()
            .any(|function| block_uses_exceptions(&function.body))
            || module.ast.classes.iter().any(|class| {
                class
                    .relations
                    .iter()
                    .any(|relation| relation.module.is_none() && relation.name == "Exception")
            })
    });
    if !needed {
        return Ok(());
    }
    if let Some(class) = program
        .modules
        .iter()
        .flat_map(|module| &module.ast.classes)
        .find(|class| class.name == "Exception")
    {
        return Err(vec![error(
            "E0431",
            "Exception is a core-owned open class and cannot be redeclared",
            class.span,
        )]);
    }
    let module = &mut program.modules[program.entry.0 as usize];
    let span = Span::in_source(module.info.source, 0, 0);
    module.ast.classes.insert(
        0,
        crate::AstClass {
            open: true,
            relations: Vec::new(),
            name: "Exception".into(),
            public: true,
            fields: Vec::new(),
            methods: Vec::new(),
            initializer: Some(crate::AstClassMethod {
                open: false,
                overriding: false,
                public: true,
                mutable: true,
                function: AstFunction {
                    return_type: ast_type("int", span),
                    name: "init".into(),
                    generic_parameters: Vec::new(),
                    parameters: Vec::new(),
                    body: AstBlock {
                        statements: Vec::new(),
                        span,
                    },
                    span,
                },
            }),
            span,
        },
    );
    Ok(())
}
pub(super) fn expand_methods(program: &mut ParsedProgram) -> Result<(), Vec<Diagnostic>> {
    for module in &mut program.modules {
        for class in &module.ast.classes {
            if !class.fields.is_empty() && class.initializer.is_none() {
                return Err(vec![error(
                    "E0403",
                    "nonempty class requires an explicit init",
                    class.span,
                )]);
            }
            let mut methods = class.methods.clone();
            let init = class
                .initializer
                .clone()
                .unwrap_or_else(|| crate::AstClassMethod {
                    open: false,
                    overriding: false,
                    public: true,
                    mutable: true,
                    function: AstFunction {
                        name: "init".into(),
                        generic_parameters: Vec::new(),
                        return_type: ast_type("int", class.span),
                        parameters: Vec::new(),
                        body: AstBlock {
                            statements: Vec::new(),
                            span: class.span,
                        },
                        span: class.span,
                    },
                });
            methods.insert(0, init);
            let mut names = BTreeSet::new();
            for (index, method) in methods.into_iter().enumerate() {
                let mut f = method.function;
                if !f.generic_parameters.is_empty()
                    || !names.insert(f.name.clone())
                    || class.fields.iter().any(|(_, field)| field.name == f.name)
                {
                    return Err(vec![error(
                        "E0400",
                        "generic/overloaded or conflicting class members are unavailable",
                        f.span,
                    )]);
                }
                if f.parameters.iter().any(|p| p.name == "this") {
                    return Err(vec![error("E0404", "this is an implicit receiver", f.span)]);
                }
                if f.parameters.iter().any(|p| p.name == "base") {
                    return Err(vec![error(
                        "E0422",
                        "base is a contextual call designator, not a parameter value",
                        f.span,
                    )]);
                }
                if index == 0 {
                    if has_return(&f.body) {
                        return Err(vec![error("E0404", "init cannot return a value", f.span)]);
                    }
                    if !ast_definitely_terminates(&f.body) {
                        f.body.statements.push(AstStmt {
                            kind: AstStmtKind::Return(AstExpr {
                                kind: AstExprKind::Integer("0".into()),
                                span: f.span,
                            }),
                            span: f.span,
                        });
                    }
                }
                f.parameters.insert(
                    0,
                    AstParameter {
                        ty: ast_type(&class.name, f.span),
                        name: "this".into(),
                        span: f.span,
                    },
                );
                f.name = format!("${}.{}", class.name, f.name);
                module.ast.functions.push(f);
            }
        }
    }
    Ok(())
}
pub(super) fn register_identities(program: &ParsedProgram, types: &mut TypeArena) {
    let mut function_base = 0;
    for module in &program.modules {
        for class in module.ast.classes() {
            let id = ClassId(types.classes.len() as u32);
            let mut methods = Vec::new();
            for (index, f) in module.ast.functions.iter().enumerate() {
                let prefix = format!("${}.", class.name);
                if let Some(name) = f.name.strip_prefix(&prefix) {
                    let initializing = name == "init";
                    let source = if initializing {
                        class.initializer.as_ref()
                    } else {
                        class.methods.iter().find(|m| m.function.name == name)
                    };
                    methods.push(ClassMethodInfo {
                        open: source.is_some_and(|m| m.open),
                        overriding: source.is_some_and(|m| m.overriding),
                        virtual_slot: None,
                        override_target: None,
                        parameters: Vec::new(),
                        result: TypeId::INT64,
                        function: FunctionId((function_base + index) as u32),
                        name: name.into(),
                        public: source.is_none_or(|m| m.public),
                        mutable: source.is_none_or(|m| m.mutable),
                        initializing,
                    });
                }
            }
            types.register_class_definition(ClassInfo {
                open: class.open,
                base: None,
                interfaces: Vec::new(),
                id,
                module: module.info.id,
                name: class.name.clone(),
                public: class.public,
                fields: Vec::new(),
                methods,
                destruction: Vec::new(),
                layout: TypeLayout { size: 0, align: 1 },
                span: class.span,
            });
            types.intern(TypeData::Class(id));
            if class.name == "Exception" && module.info.id == program.entry {
                types.set_exception_class(id);
            }
            for kind in [
                ClassTokenKind::Unpublished,
                ClassTokenKind::Keepalive { mutable: false },
                ClassTokenKind::Keepalive { mutable: true },
                ClassTokenKind::Receiver {
                    mutable: false,
                    initializing: false,
                },
                ClassTokenKind::Receiver {
                    mutable: true,
                    initializing: false,
                },
                ClassTokenKind::Receiver {
                    mutable: true,
                    initializing: true,
                },
            ] {
                types.intern(TypeData::ClassToken { class: id, kind });
            }
        }
        function_base += module.ast.functions.len();
    }
}
pub(super) fn resolve_inheritance(types: &mut TypeArena) -> Result<(), Vec<Diagnostic>> {
    let fail = |message, span| vec![error("E0420", message, span)];
    let mut order = (0..types.classes.len()).collect::<Vec<_>>();
    for c in &types.classes {
        types.class_chain(c.id).map_err(|m| fail(m, c.span))?;
        if let Some(base) = c.base {
            let b = &types.classes[base.0 as usize];
            if !b.open || (b.module != c.module && !b.public) || (c.public && !b.public) {
                return Err(fail("base must be accessible and open".into(), c.span));
            }
        }
    }
    order.sort_by_key(|i| types.class_chain(ClassId(*i as u32)).unwrap().len());
    for index in order {
        let mut c = types.classes[index].clone();
        if let Some(base) = c.base {
            for i in &types.classes[base.0 as usize].interfaces {
                if c.interfaces.contains(i) {
                    return Err(fail(
                        "duplicate inherited interface conformance".into(),
                        c.span,
                    ));
                }
                c.interfaces.push(*i);
            }
        }
        for m in &mut c.methods {
            let inherited = c.base.and_then(|b| types.effective_method(b, &m.name));
            if let Some((_, target)) = inherited {
                if !m.overriding
                    || !target.public
                    || target.virtual_slot.is_none()
                    || m.initializing
                    || !m.public
                    || m.parameters != target.parameters
                    || m.result != target.result
                    || m.mutable != target.mutable
                {
                    return Err(fail("override requires an exact accessible open target, signature and receiver capability".into(), c.span));
                }
                m.override_target = Some(target.function);
                m.virtual_slot = target.virtual_slot;
            } else if m.overriding {
                return Err(fail("override has no inherited target".into(), c.span));
            } else if m.open {
                if !c.open || !m.public || m.initializing {
                    return Err(fail(
                        "open method requires an open class and public non-initializer method"
                            .into(),
                        c.span,
                    ));
                }
                m.virtual_slot = Some(crate::VirtualSlotId(m.function));
            }
        }
        types.classes[index] = c.clone();
        for iid in &c.interfaces {
            let mut slots = Vec::new();
            for r in &types.interfaces[iid.0 as usize].requirements {
                let (_, m) = types.effective_method(c.id, &r.name).ok_or_else(|| {
                    fail(format!("missing interface requirement {}", r.name), c.span)
                })?;
                if !m.public
                    || m.mutable != r.mutable
                    || m.parameters != r.parameters
                    || m.result != r.result
                {
                    return Err(fail(
                        "interface requires an exact public method contract".into(),
                        c.span,
                    ));
                }
                slots.push(crate::WitnessSlot {
                    requirement: r.id,
                    method: m.function,
                });
            }
            types.register_witness(crate::WitnessInfo {
                id: crate::WitnessId(types.witnesses.len() as u32),
                class: c.id,
                interface: *iid,
                slots,
            });
        }
    }
    Ok(())
}

pub(super) fn compute_layouts(
    types: &mut TypeArena,
    structs: &[StructInfo],
    enums: &[EnumInfo],
    target: TargetProperties,
) -> Result<(), Vec<Diagnostic>> {
    let mut order = (0..types.classes.len()).collect::<Vec<_>>();
    order.sort_by_key(|i| types.class_chain(ClassId(*i as u32)).unwrap().len());
    for index in order {
        let mut class = types.classes[index].clone();
        let mut alignment = u64::from(target.pointer_width / 8);
        // Private object header: one shared strong count and an immutable
        // dynamic descriptor pointer. Source handles remain one pointer.
        let mut offset = 2 * alignment;
        if let Some(base) = class.base {
            offset = types.classes[base.0 as usize].layout.size;
            alignment = alignment.max(types.classes[base.0 as usize].layout.align);
            for field in &class.fields {
                if types.inherited_field(base, &field.name).is_some()
                    || types.effective_method(base, &field.name).is_some()
                {
                    return Err(vec![error(
                        "E0420",
                        "inherited member hiding is unavailable",
                        field.span,
                    )]);
                }
            }
        }
        for field in &mut class.fields {
            let layout = layout_of(types, field.ty, target, structs, enums).ok_or_else(|| {
                vec![error(
                    "E0401",
                    "class field requires a finite concrete layout",
                    field.span,
                )]
            })?;
            alignment = alignment.max(layout.align);
            offset = align_up(offset, layout.align);
            field.offset = offset;
            offset += layout.size;
        }
        class.layout = TypeLayout {
            size: align_up(offset, alignment),
            align: alignment,
        };
        class.destruction = class
            .fields
            .iter()
            .rev()
            .filter(|f| types.needs_drop(f.ty))
            .map(|f| crate::ClassDropStep::Field {
                field: f.id,
                ty: f.ty,
            })
            .chain(class.base.into_iter().flat_map(|b| {
                types.classes[b.0 as usize]
                    .destruction
                    .iter()
                    .filter(|s| matches!(s, crate::ClassDropStep::Field { .. }))
                    .cloned()
            }))
            .chain(std::iter::once(crate::ClassDropStep::Free {
                layout: class.layout,
            }))
            .collect();
        types.register_class_definition(class);
    }
    Ok(())
}
impl Analyzer<'_> {
    fn class_named(&self, module: ModuleId, name: &str) -> Option<ClassId> {
        self.aliases[module.0 as usize]
            .get(name)
            .and_then(|t| self.types.class_id(*t))
            .or_else(|| {
                self.types
                    .classes
                    .iter()
                    .find(|c| c.module == module && c.name == name)
                    .map(|c| c.id)
            })
            .or_else(|| {
                (name == "Exception")
                    .then(|| self.types.exception_class())
                    .flatten()
            })
    }
    fn class_source_type(&self, e: &AstExpr) -> Option<ClassId> {
        match &e.kind {
            AstExprKind::Name(n) => self
                .lookup(n)
                .and_then(|l| self.types.object_class(self.locals[l.0 as usize].ty)),
            AstExprKind::Call { callee, .. } => {
                self.class_named(self.module, callee).or_else(|| {
                    self.names[self.module.0 as usize]
                        .get(callee)
                        .and_then(|f| {
                            self.types
                                .class_id(self.signatures[f.0 as usize].return_type)
                        })
                })
            }
            AstExprKind::QualifiedCall {
                module, function, ..
            } => self.imports[self.module.0 as usize]
                .get(module)
                .and_then(|m| self.class_named(*m, function)),
            _ => None,
        }
    }
    fn raw_receiver(&mut self, e: &AstExpr) -> Result<HirExpr, Vec<Diagnostic>> {
        if let AstExprKind::Name(n) = &e.kind
            && let Some(l) = self.lookup(n)
            && (self.types.is_object_owner(self.locals[l.0 as usize].ty)
                || self
                    .types
                    .object_class(self.locals[l.0 as usize].ty)
                    .is_some())
        {
            return Ok(HirExpr {
                kind: HirExprKind::Local(l),
                ty: self.locals[l.0 as usize].ty,
                span: e.span,
            });
        }
        Ok(self.expression(e, None)?.expr)
    }
    fn this_expr(&self, span: Span) -> AstExpr {
        AstExpr {
            kind: AstExprKind::Name("this".into()),
            span,
        }
    }
    fn class_field_source(&self, e: &AstExpr) -> Option<(AstExpr, ClassFieldInfo)> {
        let (base, name) = match &e.kind {
            AstExprKind::Name(n) if self.lookup(n).is_none() && self.class_method.is_some() => {
                (self.this_expr(e.span), n)
            }
            AstExprKind::Field { base, name, .. } => ((**base).clone(), name),
            _ => return None,
        };
        let class = self.class_source_type(&base)?;
        self.types
            .inherited_field(class, name)
            .cloned()
            .map(|f| (base, f))
    }
    fn check_member_access(
        &self,
        class: ClassId,
        public: bool,
        span: Span,
    ) -> Result<(), Vec<Diagnostic>> {
        if !public && self.class_method.as_ref().is_none_or(|(c, _)| *c != class) {
            return Err(vec![error(
                "E0402",
                "private class member is inaccessible",
                span,
            )]);
        }
        Ok(())
    }
    fn class_checked(&self, op: ClassOp<HirExpr>, ty: TypeId, span: Span) -> Checked {
        Checked {
            expr: HirExpr {
                kind: HirExprKind::Class(Box::new(op)),
                ty,
                span,
            },
            constant: None,
        }
    }
    pub(super) fn class_sink(&mut self, initializer: HirExpr, span: Span) -> HirStmtKind {
        let local = LocalId(self.locals.len() as u32);
        self.locals.push(HirLocal {
            id: local,
            name: format!("$class_effect{}", local.0),
            ty: initializer.ty,
            span,
            parameter: false,
            address_taken: false,
        });
        HirStmtKind::Local { local, initializer }
    }
    pub(super) fn class_field_write(
        &mut self,
        place: &AstExpr,
        value: &AstExpr,
    ) -> Option<Result<HirExpr, Vec<Diagnostic>>> {
        let (base, field) = self.class_field_source(place)?;
        Some((|| {
            self.check_member_access(field.class, field.public, place.span)?;
            let receiver = self.raw_receiver(&base)?;
            if matches!(
                self.types.get(receiver.ty),
                Some(TypeData::ClassToken {
                    kind: ClassTokenKind::Receiver { mutable: false, .. },
                    ..
                })
            ) {
                return Err(vec![error(
                    "E0405",
                    "field mutation requires a declared mut receiver",
                    place.span,
                )]);
            }
            let initializing = matches!(
                self.types.get(receiver.ty),
                Some(TypeData::ClassToken {
                    kind: ClassTokenKind::Receiver {
                        initializing: true,
                        ..
                    },
                    ..
                })
            );
            let initialize = initializing && !self.initialized_fields.contains(&field.id);
            let value = self.expression(value, Some(field.ty))?.expr;
            if initializing {
                self.initialized_fields.insert(field.id);
            }
            Ok(self
                .class_checked(
                    ClassOp::FieldWrite {
                        receiver,
                        field: field.id,
                        value,
                        initialize,
                    },
                    TypeId::BOOL,
                    place.span,
                )
                .expr)
        })())
    }
    pub(super) fn class_expression(
        &mut self,
        e: &AstExpr,
        expected: Option<TypeId>,
    ) -> Option<Result<Checked, Vec<Diagnostic>>> {
        if let AstExprKind::Call { callee, args, .. } = &e.kind
            && callee == "$base"
        {
            return Some((|| {
                let (class, method) = self
                    .class_method
                    .clone()
                    .ok_or_else(|| vec![error("E0421", "base init outside initializer", e.span)])?;
                let base = self.types.classes[class.0 as usize]
                    .base
                    .filter(|_| method.initializing)
                    .ok_or_else(|| {
                        vec![error(
                            "E0421",
                            "base init requires derived initializer",
                            e.span,
                        )]
                    })?;
                let init = self.types.classes[base.0 as usize]
                    .methods
                    .iter()
                    .find(|m| m.initializing)
                    .unwrap()
                    .clone();
                self.check_member_access(base, init.public, e.span)?;
                let args = self.class_arguments(init.function, args, e.span)?;
                let object = self.raw_receiver(&self.this_expr(e.span))?;
                for id in self.types.class_chain(base).unwrap() {
                    self.initialized_fields.extend(
                        self.types.classes[id.0 as usize]
                            .fields
                            .iter()
                            .map(|f| f.id),
                    );
                }
                Ok(self.class_checked(
                    ClassOp::BaseInit {
                        class,
                        base,
                        initializer: HirCallTarget::Declaration(init.function),
                        object,
                        args,
                    },
                    TypeId::BOOL,
                    e.span,
                ))
            })());
        }
        if matches!(&e.kind, AstExprKind::Name(name) if name == "base")
            && self.class_method.is_some()
        {
            return Some(Err(vec![error(
                "E0422",
                "base is not a value; only base.method(...) is valid",
                e.span,
            )]));
        }
        if let Some((base, field)) = self.class_field_source(e) {
            return Some((|| {
                if !matches!(base.kind, AstExprKind::Name(_)) {
                    return Err(vec![error(
                        "E0406",
                        "temporary field receivers are unavailable; bind the object or use a read method",
                        e.span,
                    )]);
                }

                self.check_member_access(field.class, field.public, e.span)?;
                if !self.types.guarantees_copy(field.ty) {
                    return Err(vec![error(
                        "E0406",
                        "owning fields cannot be extracted or borrowed from a live object",
                        e.span,
                    )]);
                }
                let receiver = self.raw_receiver(&base)?;
                if matches!(
                    self.types.get(receiver.ty),
                    Some(TypeData::ClassToken {
                        kind: ClassTokenKind::Receiver {
                            initializing: true,
                            ..
                        },
                        ..
                    })
                ) && !self.initialized_fields.contains(&field.id)
                {
                    return Err(vec![error(
                        "E0403",
                        "field read before initialization",
                        e.span,
                    )]);
                }
                self.coerce(
                    self.class_checked(
                        ClassOp::FieldRead {
                            receiver,
                            field: field.id,
                        },
                        field.ty,
                        e.span,
                    ),
                    expected,
                )
            })());
        }
        let base_call = match &e.kind {
            AstExprKind::MethodCall {
                receiver,
                method,
                args,
            } if matches!(&receiver.kind, AstExprKind::Name(name) if name == "base") => {
                Some((method.as_str(), args.as_slice()))
            }
            AstExprKind::QualifiedCall {
                module,
                function,
                type_arguments,
                args,
                parenthesized: true,
            } if module == "base" && type_arguments.is_empty() => {
                Some((function.as_str(), args.as_slice()))
            }
            _ => None,
        };
        if let Some((name, args)) = base_call {
            return Some((|| {
                let (class, current) = self.class_method.clone().ok_or_else(|| {
                    vec![error(
                        "E0422",
                        "base.method is available only inside a derived class method",
                        e.span,
                    )]
                })?;
                if current.initializing {
                    return Err(vec![error(
                        "E0422",
                        "base.method is unavailable during initialization",
                        e.span,
                    )]);
                }
                let base = self.types.classes[class.0 as usize].base.ok_or_else(|| {
                    vec![error(
                        "E0422",
                        "base.method requires an immediate base class",
                        e.span,
                    )]
                })?;
                let (declaring, target) = self
                    .types
                    .effective_method(base, name)
                    .map(|(owner, method)| (owner, method.clone()))
                    .ok_or_else(|| vec![error("E0422", "unknown base method", e.span)])?;
                self.check_member_access(declaring, target.public, e.span)?;
                if target.mutable && !current.mutable {
                    return Err(vec![error(
                        "E0405",
                        "mut base method requires a mut current receiver",
                        e.span,
                    )]);
                }
                // The caller of the current method already owns the keepalive
                // spanning this complete body. Keep `base` non-owning and invoke
                // the selected immediate-base implementation on borrowed `this`.
                let receiver = self.raw_receiver(&self.this_expr(e.span))?;
                let args = self.class_arguments(target.function, args, e.span)?;
                let result = self.signatures[target.function.0 as usize].return_type;
                self.coerce(
                    self.class_checked(
                        ClassOp::BaseMethodCall {
                            class,
                            base,
                            slot: target.virtual_slot,
                            method: HirCallTarget::Declaration(target.function),
                            receiver,
                            args,
                        },
                        result,
                        e.span,
                    ),
                    expected,
                )
            })());
        }
        let method = match &e.kind {
            AstExprKind::MethodCall {
                receiver,
                method,
                args,
            } => Some(((**receiver).clone(), method.as_str(), args.as_slice())),
            AstExprKind::QualifiedCall {
                module,
                function,
                args,
                type_arguments,
                ..
            } if self.lookup(module).is_some() && type_arguments.is_empty() => Some((
                AstExpr {
                    kind: AstExprKind::Name(module.clone()),
                    span: e.span,
                },
                function.as_str(),
                args.as_slice(),
            )),
            AstExprKind::Call {
                callee,
                args,
                type_arguments,
            } if self.class_method.is_some()
                && type_arguments.is_empty()
                && !self.names[self.module.0 as usize].contains_key(callee)
                && self
                    .types
                    .effective_method(self.class_method.as_ref().unwrap().0, callee)
                    .is_some() =>
            {
                Some((self.this_expr(e.span), callee.as_str(), args.as_slice()))
            }
            _ => None,
        };
        if let Some((receiver, name, args)) = method {
            return Some(
                self.class_call(&receiver, name, args, e.span)
                    .and_then(|c| self.coerce(c, expected)),
            );
        }
        let construction = match &e.kind {
            AstExprKind::Call {
                callee,
                args,
                type_arguments,
            } => self
                .class_named(self.module, callee)
                .map(|c| (c, args, type_arguments)),
            AstExprKind::QualifiedCall {
                module,
                function,
                args,
                type_arguments,
                ..
            } if self.lookup(module).is_none() => self.imports[self.module.0 as usize]
                .get(module)
                .and_then(|m| self.class_named(*m, function))
                .map(|c| (c, args, type_arguments)),
            _ => None,
        };
        if let Some((class, args, type_arguments)) = construction {
            return Some((|| {
                if !type_arguments.is_empty() {
                    return Err(vec![error(
                        "E0400",
                        "generic classes are unavailable",
                        e.span,
                    )]);
                }
                let info = &self.types.classes[class.0 as usize];
                if info.module != self.module && !info.public {
                    return Err(vec![error(
                        "E0402",
                        "class is internal to its module",
                        e.span,
                    )]);
                }
                let init = info
                    .methods
                    .iter()
                    .find(|m| m.initializing)
                    .unwrap()
                    .clone();
                self.check_member_access(class, init.public, e.span)?;
                let args = self.class_arguments(init.function, args, e.span)?;
                let ty = self.types.id_of(TypeData::Class(class)).unwrap();
                let constructed = self
                    .class_checked(
                        ClassOp::Construct {
                            class,
                            initializer: HirCallTarget::Declaration(init.function),
                            args,
                        },
                        ty,
                        e.span,
                    )
                    .expr;
                self.coerce(
                    self.class_checked(
                        ClassOp::HandleTransfer {
                            source: constructed,
                        },
                        ty,
                        e.span,
                    ),
                    expected,
                )
            })());
        }
        if let AstExprKind::Binary { op, left, right } = &e.kind
            && self.class_source_type(left).is_some()
        {
            return Some((|| {
                if !matches!(op, AstBinaryOp::Equal | AstBinaryOp::NotEqual) {
                    return Err(vec![error(
                        "E0407",
                        "classes support only identity == and !=",
                        e.span,
                    )]);
                }
                let left = self.raw_receiver(left)?;
                let right = self.raw_receiver(right)?;
                if !self
                    .types
                    .class_id(left.ty)
                    .zip(self.types.class_id(right.ty))
                    .is_some_and(|(l, r)| {
                        self.types.is_subclass(l, r) || self.types.is_subclass(r, l)
                    })
                {
                    return Err(vec![error(
                        "E0407",
                        "identity comparison requires compatible class views",
                        e.span,
                    )]);
                }
                self.coerce(
                    self.class_checked(
                        ClassOp::IdentityEq {
                            left,
                            right,
                            unequal: *op == AstBinaryOp::NotEqual,
                        },
                        TypeId::BOOL,
                        e.span,
                    ),
                    expected,
                )
            })());
        }
        None
    }
    fn class_arguments(
        &mut self,
        function: FunctionId,
        args: &[AstExpr],
        span: Span,
    ) -> Result<Vec<HirExpr>, Vec<Diagnostic>> {
        let parameters = self.signatures[function.0 as usize].parameters[1..].to_vec();
        if parameters.len() != args.len() {
            return Err(vec![error(
                "E0408",
                "class member argument count mismatch",
                span,
            )]);
        }
        args.iter()
            .zip(parameters)
            .map(|(arg, p)| self.expression(arg, Some(p.ty)).map(|c| c.expr))
            .collect()
    }
    fn class_call(
        &mut self,
        receiver: &AstExpr,
        name: &str,
        args: &[AstExpr],
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let source = self.raw_receiver(receiver)?;
        if let Some(interface) = self.types.interface_id(source.ty) {
            let r = self.types.interfaces()[interface.0 as usize]
                .requirements
                .iter()
                .find(|r| r.name == name)
                .cloned()
                .ok_or_else(|| vec![error("E0414", "unknown interface requirement", span)])?;
            let mutable = matches!(source.kind, HirExprKind::Local(_));
            if r.mutable && !mutable {
                return Err(vec![error(
                    "E0414",
                    "mut interface requirement needs writable local receiver",
                    span,
                )]);
            }
            let ty = self
                .types
                .id_of(TypeData::InterfaceKeepalive { interface, mutable })
                .unwrap();
            let receiver = self
                .class_checked(
                    ClassOp::ReceiverKeepalive {
                        source,
                        mutable,
                        transfer: !mutable,
                    },
                    ty,
                    span,
                )
                .expr;
            if args.len() != r.parameters.len() {
                return Err(vec![error(
                    "E0414",
                    "interface argument count mismatch",
                    span,
                )]);
            }
            let args = args
                .iter()
                .zip(&r.parameters)
                .map(|(a, t)| self.expression(a, Some(*t)).map(|c| c.expr))
                .collect::<Result<Vec<_>, _>>()?;
            return Ok(self.class_checked(
                ClassOp::InterfaceCall {
                    requirement: r.id,
                    slot: r.id.index,
                    receiver,
                    args,
                },
                r.result,
                span,
            ));
        }
        let class = self.types.object_class(source.ty).ok_or_else(|| {
            vec![error(
                "E0408",
                "method receiver must be a concrete class",
                span,
            )]
        })?;
        let (declaring, method) = self
            .types
            .effective_method(class, name)
            .map(|(c, m)| (c, m.clone()))
            .ok_or_else(|| vec![error("E0408", "unknown direct class method", span)])?;
        self.check_member_access(declaring, method.public, span)?;
        let path_mutable = match self.types.get(source.ty) {
            Some(TypeData::ClassToken {
                kind:
                    ClassTokenKind::Receiver {
                        initializing: true, ..
                    },
                ..
            }) => {
                return Err(vec![error(
                    "E0404",
                    "method calls on this during init are forbidden",
                    span,
                )]);
            }
            Some(TypeData::ClassToken {
                kind: ClassTokenKind::Receiver { mutable, .. },
                ..
            }) => *mutable,
            _ => matches!(source.kind, HirExprKind::Local(_)),
        };
        if method.mutable && !path_mutable {
            return Err(vec![error(
                "E0405",
                "mut method requires an addressable writable receiver",
                span,
            )]);
        }
        let transfer = !matches!(source.kind, HirExprKind::Local(_));
        let ty = self
            .types
            .id_of(TypeData::ClassToken {
                class,
                kind: ClassTokenKind::Keepalive {
                    mutable: path_mutable,
                },
            })
            .unwrap();
        let receiver = self
            .class_checked(
                ClassOp::ReceiverKeepalive {
                    source,
                    mutable: path_mutable,
                    transfer,
                },
                ty,
                span,
            )
            .expr;
        let args = self.class_arguments(method.function, args, span)?;
        let result = self.signatures[method.function.0 as usize].return_type;
        Ok(self.class_checked(
            if let Some(slot) = method.virtual_slot {
                ClassOp::VirtualCall {
                    class,
                    slot,
                    method: HirCallTarget::Declaration(method.function),
                    receiver,
                    args,
                }
            } else {
                ClassOp::DirectMethodCall {
                    method: HirCallTarget::Declaration(method.function),
                    receiver,
                    args,
                }
            },
            result,
            span,
        ))
    }
}

fn place_children(place: &HirPlace) -> Vec<&HirExpr> {
    let mut result = Vec::new();
    if let HirPlaceBase::Dereference { reference, .. } = &place.base {
        result.push(reference.as_ref());
    }
    for projection in &place.projections {
        if let HirPlaceProjection::Index { index, column, .. } = projection {
            result.push(index.as_ref());
            if let Some(column) = column {
                result.push(column.as_ref());
            }
        }
    }
    result
}

// Exhaustive child enumeration prevents ordinary aggregates/math/places from
// hiding a receiver read or call from independent HIR construction verification.
fn expression_children(e: &HirExpr) -> Vec<&HirExpr> {
    use HirExprKind as E;
    match &e.kind {
        E::Class(op) => op.operands(),
        E::Int(_)
        | E::Float(_)
        | E::Bool(_)
        | E::Local(_)
        | E::Move(_)
        | E::AlgebraicValue { .. } => Vec::new(),
        E::Load(source)
        | E::Borrow { place: source, .. }
        | E::MatrixRows { source }
        | E::MatrixColumns { source }
        | E::VectorDimension { source }
        | E::ArrayLength { source }
        | E::ListLength { source }
        | E::ListCapacity { source }
        | E::ListPop { source, .. }
        | E::VectorView { source, .. }
        | E::MatrixView { source, .. }
        | E::View { source, .. } => place_children(source),
        E::ListSwapRemove { source, index, .. }
        | E::ListRemove { source, index, .. }
        | E::MatrixAxisVectorView {
            source,
            fixed_index: index,
            ..
        } => {
            let mut children = place_children(source);
            children.push(index);
            children
        }
        E::BufferInit {
            length, initial, ..
        }
        | E::ArrayFill {
            length, initial, ..
        } => vec![length, initial],
        E::VectorTranspose { operand, .. }
        | E::Coerce { operand, .. }
        | E::ExplicitCast { operand, .. }
        | E::Unary { operand, .. } => vec![operand],
        E::MatrixInit { elements, .. }
        | E::VectorInit { elements, .. }
        | E::ArrayInit { elements, .. }
        | E::ListInit { elements, .. }
        | E::Call { args: elements, .. }
        | E::EnumInit {
            payloads: elements, ..
        } => elements.iter().collect(),
        E::StructInit { fields, .. } => fields.iter().map(|(_, e)| e).collect(),
        E::CapabilityBinary { left, right, .. }
        | E::VectorScalarMultiply { left, right, .. }
        | E::MatrixScalarMultiply { left, right, .. }
        | E::VectorElementwiseBinary { left, right, .. }
        | E::MatrixElementwiseBinary { left, right, .. }
        | E::Binary { left, right, .. } => vec![left, right],
        E::AlgebraicProduct {
            left,
            right,
            product,
            ..
        } => {
            let mut children = vec![left.as_ref(), right.as_ref()];
            match product {
                AlgebraicProductKind::MatrixMatrix { zero, .. }
                | AlgebraicProductKind::MatrixVector { zero, .. }
                | AlgebraicProductKind::Inner { zero, .. } => children.push(zero),
                AlgebraicProductKind::Outer { .. } => (),
            }
            children
        }
    }
}

#[allow(clippy::items_after_statements)]
pub(super) fn verify_body(
    body: &HirBlock,
    locals: &[HirLocal],
    parameters: &[HirParameter],
    function: FunctionId,
    module: ModuleId,
    types: &TypeArena,
    signatures: VerificationSignatures<'_>,
) -> Result<(), String> {
    if types.classes().is_empty() && types.interfaces().is_empty() {
        return Ok(());
    }
    let init_class = types
        .class_method(function)
        .filter(|(_, m)| m.initializing)
        .map(|(c, _)| c);
    fn visit_expr(
        e: &HirExpr,
        state: &mut crate::ClassInitializationState,
        types: &TypeArena,
        function: FunctionId,
        module: ModuleId,
        signatures: VerificationSignatures<'_>,
    ) -> Result<(), String> {
        if let HirExprKind::Class(op) = &e.kind {
            for operand in op.operands() {
                visit_expr(operand, state, types, function, module, signatures)?;
            }
            if let ClassOp::Construct { args, .. }
            | ClassOp::BaseInit { args, .. }
            | ClassOp::BaseMethodCall { args, .. }
            | ClassOp::VirtualCall { args, .. }
            | ClassOp::DirectMethodCall { args, .. }
            | ClassOp::InterfaceCall { args, .. } = op.as_ref()
            {
                for arg in args {
                    owning_use(arg, types)?;
                }
            }
            crate::verify_class_access(op, types, function, module, |target| {
                match (signatures, target) {
                    (VerificationSignatures::Parametric(s), HirCallTarget::Declaration(id)) => {
                        s.get(id.0 as usize).map(|s| s.id)
                    }
                    (VerificationSignatures::Concrete(s), HirCallTarget::Instance(id)) => {
                        s.get(id.0 as usize).map(|s| s.function_id)
                    }
                    _ => None,
                }
                .ok_or_else(|| "invalid class target".into())
            })?;
            if matches!(
                op.as_ref(),
                ClassOp::ObjectAlloc { .. }
                    | ClassOp::InitCall { .. }
                    | ClassOp::PublishObject { .. }
            ) {
                return Err("low-level publication injected into HIR".into());
            }
            match op.as_ref() {
                ClassOp::BaseInit { base, .. } => state.complete_base(types, *base)?,
                ClassOp::FieldRead { receiver, field }
                | ClassOp::FieldWrite {
                    receiver, field, ..
                } if matches!(
                    types.get(receiver.ty),
                    Some(TypeData::ClassToken {
                        kind: ClassTokenKind::Receiver {
                            initializing: true,
                            ..
                        },
                        ..
                    })
                ) =>
                {
                    state.require_base(
                        types,
                        types
                            .object_class(receiver.ty)
                            .ok_or("invalid init receiver")?,
                    )?;
                    if let ClassOp::FieldWrite { initialize, .. } = op.as_ref() {
                        if (!*initialize && !state.contains(field))
                            || (*initialize
                                && state.contains(field)
                                && types
                                    .class_field(*field)
                                    .is_some_and(|f| types.needs_drop(f.ty)))
                        {
                            return Err(
                                "HIR field initialization/replacement state mismatch".into()
                            );
                        }
                        state.insert(*field);
                    } else if !state.contains(field) {
                        return Err("HIR field read before initialization".into());
                    }
                }
                ClassOp::ReceiverKeepalive {
                    source, transfer, ..
                }
                | ClassOp::ClassUpcast {
                    source, transfer, ..
                }
                | ClassOp::InterfaceAdapt {
                    source, transfer, ..
                } if *transfer == matches!(source.kind, HirExprKind::Local(_)) => {
                    return Err(
                        "HIR keepalive must alias lvalues and transfer fresh results".into(),
                    );
                }
                _ => (),
            }
        } else {
            for operand in expression_children(e) {
                owning_use(operand, types)?;
                visit_expr(operand, state, types, function, module, signatures)?;
            }
        }
        Ok(())
    }
    fn owning_use(e: &HirExpr, types: &TypeArena) -> Result<(), String> {
        if types.is_object_owner(e.ty)
            && matches!(
                e.kind,
                HirExprKind::Local(_) | HirExprKind::Load(_) | HirExprKind::Move(_)
            )
        {
            return Err("class owning use is missing explicit Alias/Transfer".into());
        }
        Ok(())
    }
    #[allow(clippy::too_many_arguments)]
    fn block(
        b: &HirBlock,
        state: &mut crate::ClassInitializationState,
        init: Option<ClassId>,
        types: &TypeArena,
        function: FunctionId,
        module: ModuleId,
        sigs: VerificationSignatures<'_>,
    ) -> Result<(), String> {
        for s in &b.statements {
            if let HirStmtKind::Assign { place, .. } = &s.kind {
                for e in place_children(place) {
                    visit_expr(e, state, types, function, module, sigs)?;
                }
            }
            match &s.kind {
                HirStmtKind::Local {
                    initializer: value, ..
                }
                | HirStmtKind::Assign { value, .. }
                | HirStmtKind::Return { value, .. }
                | HirStmtKind::Throw { value, .. } => {
                    owning_use(value, types)?;
                    visit_expr(value, state, types, function, module, sigs)?;
                    if matches!(s.kind, HirStmtKind::Return { .. })
                        && let Some(c) = init
                    {
                        state.require_base(types, c)?;
                    }
                    if matches!(s.kind, HirStmtKind::Return { .. })
                        && init.is_some_and(|c| {
                            types.classes[c.0 as usize]
                                .fields
                                .iter()
                                .any(|f| !state.contains(&f.id))
                        })
                    {
                        return Err(
                            "HIR initializer completes before definite field initialization".into(),
                        );
                    }
                }
                HirStmtKind::If {
                    condition,
                    then_block,
                    else_block,
                } => {
                    visit_expr(condition, state, types, function, module, sigs)?;
                    let mut other = state.clone();
                    block(then_block, state, init, types, function, module, sigs)?;
                    if let Some(b) = else_block {
                        block(b, &mut other, init, types, function, module, sigs)?;
                    }
                    state.fields = state.intersection(&other).copied().collect();
                    state.base_completed &= other.base_completed;
                }
                HirStmtKind::While { condition, body } => {
                    visit_expr(condition, state, types, function, module, sigs)?;
                    let before = state.clone();
                    block(body, state, init, types, function, module, sigs)?;
                    if *state != before {
                        return Err("HIR loop changes constructor initialization state".into());
                    }
                }
                HirStmtKind::Match {
                    arms, scrutinee, ..
                } => {
                    visit_expr(scrutinee, state, types, function, module, sigs)?;
                    for arm in arms {
                        let mut arm_state = state.clone();
                        block(
                            &arm.body,
                            &mut arm_state,
                            init,
                            types,
                            function,
                            module,
                            sigs,
                        )?;
                        if init.is_some() && arm_state != *state {
                            return Err("class initialization in match is unavailable".into());
                        }
                    }
                }
                HirStmtKind::Try { body, catches } => {
                    block(body, state, init, types, function, module, sigs)?;
                    for catch in catches {
                        let mut catch_state = state.clone();
                        block(
                            &catch.body,
                            &mut catch_state,
                            init,
                            types,
                            function,
                            module,
                            sigs,
                        )?;
                    }
                }
                HirStmtKind::ListPush { target, value, .. } => {
                    for e in place_children(target) {
                        visit_expr(e, state, types, function, module, sigs)?;
                    }
                    visit_expr(value, state, types, function, module, sigs)?;
                }
                HirStmtKind::ListReserve {
                    target,
                    requested_capacity,
                    ..
                } => {
                    for e in place_children(target) {
                        visit_expr(e, state, types, function, module, sigs)?;
                    }
                    visit_expr(requested_capacity, state, types, function, module, sigs)?;
                }
                HirStmtKind::Nop | HirStmtKind::Rethrow { .. } => (),
            }
        }
        Ok(())
    }
    block(
        body,
        &mut crate::ClassInitializationState::default(),
        init_class,
        types,
        function,
        module,
        signatures,
    )?;
    // Recompute ownership centrally; supplied cleanup lists are untrusted.
    let mut synthesized = body.clone();
    synthesize_ownership(&mut synthesized, locals, parameters, types)
        .map_err(|d| format!("HIR class ownership: {d:?}"))?;
    if synthesized != *body {
        return Err("HIR class cleanup obligations differ from ownership synthesis".into());
    }
    Ok(())
}

pub(super) fn verify_constructor_unwind_plan(
    plan: Option<&crate::ConstructorUnwindPlan>,
    locals: &[HirLocal],
    parameters: &[HirParameter],
    function: FunctionId,
    types: &TypeArena,
) -> Result<(), String> {
    let initializer = types
        .class_method(function)
        .filter(|(_, method)| method.initializing)
        .map(|(class, _)| class);
    let Some(class) = initializer else {
        return if plan.is_none() {
            Ok(())
        } else {
            Err("non-initializer carries a constructor unwind plan".into())
        };
    };
    let plan = plan.ok_or("initializer is missing its constructor unwind plan")?;
    let expected_fields = types.classes()[class.0 as usize]
        .destruction
        .iter()
        .filter_map(|step| match step {
            crate::ClassDropStep::Field { field, .. } => Some(*field),
            crate::ClassDropStep::Free { .. } => None,
        })
        .collect::<Vec<_>>();
    let receiver_ty = types
        .id_of(TypeData::ClassToken {
            class,
            kind: ClassTokenKind::Receiver {
                mutable: true,
                initializing: true,
            },
        })
        .ok_or("initializer receiver type is unavailable")?;
    if plan.class != class
        || plan.cleanup_fields != expected_fields
        || parameters.first().map(|parameter| parameter.local) != Some(plan.receiver)
        || locals.get(plan.receiver.0 as usize).map(|local| local.ty) != Some(receiver_ty)
    {
        return Err("constructor unwind plan does not match class metadata/receiver".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    const SOURCE: &str = "class C{int n;public init(){n=1;}public mut int inc(){n=n+1;return n;}public int get(){return n;}}class D{int n;public init(){n=1;}public int get(){return n;}} int main(){C a=C();C b=a;b.inc();if(a==b){return a.get();}return 0;}";
    fn valid() -> TypedHir {
        analyze(crate::parse_source(&crate::SourceFile::new("oop.ae", SOURCE)).unwrap()).unwrap()
    }

    #[test]
    fn constructor_unwind_plan_corruption_is_rejected() {
        let mut hir = valid();
        let plan = hir
            .functions
            .iter_mut()
            .find_map(|function| function.constructor_unwind.as_mut())
            .expect("class initializer plan");
        plan.class = ClassId(999);
        assert!(crate::verify_hir(&hir).is_err());
    }
    // Find a class expression recursively, without changing unrelated operands.
    fn mutate_expr(e: &mut HirExpr, kind: u32) -> bool {
        let HirExprKind::Class(op) = &mut e.kind else {
            return false;
        };
        match (kind, op.as_mut()) {
            (20, ClassOp::InterfaceAdapt { interface, .. }) => {
                *interface = crate::InterfaceId(1);
                return true;
            }
            (21, ClassOp::InterfaceAdapt { witness, .. }) => {
                *witness = crate::WitnessId(1);
                return true;
            }
            (22, ClassOp::InterfaceAdapt { transfer, .. }) => {
                *transfer = true;
                return true;
            }
            (23, ClassOp::InterfaceCall { requirement, .. }) => {
                requirement.index = 0;
                return true;
            }
            (24, ClassOp::InterfaceCall { .. }) => {
                e.ty = TypeId::BOOL;
                return true;
            }
            (25, ClassOp::ReceiverKeepalive { mutable, .. }) => {
                *mutable = false;
                return true;
            }
            (26, ClassOp::InterfaceCall { slot, .. }) => {
                *slot = 0;
                return true;
            }
            (27, ClassOp::InterfaceCall { receiver, .. }) => {
                receiver.ty = TypeId::INT64;
                return true;
            }
            (28, ClassOp::DirectMethodCall { receiver, args, .. }) => {
                **op = ClassOp::InterfaceCall {
                    requirement: crate::RequirementId {
                        interface: crate::InterfaceId(0),
                        index: 0,
                    },
                    slot: 0,
                    receiver: receiver.clone(),
                    args: args.clone(),
                };
                return true;
            }
            (29, ClassOp::BaseMethodCall { base, .. }) => {
                *base = ClassId(999);
                return true;
            }
            (0, ClassOp::Construct { class, .. }) => {
                *class = ClassId(999);
                return true;
            }
            (1, ClassOp::FieldRead { field, .. }) => {
                *field = FieldId(999);
                return true;
            }
            (2, ClassOp::DirectMethodCall { method, .. })
            | (30, ClassOp::BaseMethodCall { method, .. }) => {
                *method = HirCallTarget::Instance(crate::InstanceId(999));
                return true;
            }
            (3, ClassOp::ReceiverKeepalive { mutable, .. }) => {
                *mutable = !*mutable;
                return true;
            }
            (4, ClassOp::HandleAlias { source }) => {
                **op = ClassOp::HandleTransfer {
                    source: source.clone(),
                };
                return true;
            }
            (5, ClassOp::HandleAlias { source }) => {
                *e = source.clone();
                return true;
            }
            (6, ClassOp::Construct { class, .. }) => {
                **op = ClassOp::PublishObject {
                    class: *class,
                    object: HirExpr {
                        kind: HirExprKind::Int(0),
                        ty: TypeId::INT64,
                        span: e.span,
                    },
                };
                return true;
            }
            (7, ClassOp::IdentityEq { right, .. }) => {
                right.ty = TypeId::INT64;
                return true;
            }
            (8, ClassOp::FieldWrite { initialize, .. }) if *initialize => {
                *initialize = false;
                return true;
            }
            _ => (),
        }
        let mut changed = false;
        let mapped = op
            .map(
                |operand| {
                    let mut operand = operand.clone();
                    if !changed {
                        changed = mutate_expr(&mut operand, kind);
                    }
                    Ok::<_, std::convert::Infallible>(operand)
                },
                |f| Ok(*f),
            )
            .unwrap();
        **op = mapped;
        changed
    }
    fn mutate_block(b: &mut HirBlock, kind: u32) -> bool {
        for s in &mut b.statements {
            match &mut s.kind {
                HirStmtKind::Local { initializer, .. }
                | HirStmtKind::Assign {
                    value: initializer, ..
                }
                | HirStmtKind::Return {
                    value: initializer, ..
                } => {
                    if mutate_expr(initializer, kind) {
                        return true;
                    }
                }
                HirStmtKind::If {
                    condition,
                    then_block,
                    else_block,
                } => {
                    if mutate_expr(condition, kind)
                        || mutate_block(then_block, kind)
                        || else_block.as_mut().is_some_and(|b| mutate_block(b, kind))
                    {
                        return true;
                    }
                }
                _ => (),
            }
        }
        false
    }
    #[test]
    fn hir_class_corruptions_reject_without_lowering() {
        let valid = valid();
        for kind in 0..9 {
            let mut bad = valid.clone();
            assert!(
                bad.functions
                    .iter_mut()
                    .any(|f| mutate_block(&mut f.body, kind)),
                "mutation {kind} was not applied"
            );
            assert!(verify_hir(&bad).is_err(), "HIR mutation {kind}");
        }
        let mut bad = valid.clone();
        let main = &mut bad.functions[bad.entry.0 as usize];
        if let HirStmtKind::Return { drops, .. } =
            &mut main.body.statements.last_mut().unwrap().kind
        {
            drops.clear();
        } else {
            panic!("expected return");
        }
        assert!(verify_hir(&bad).is_err());
    }
    #[test]
    fn object_metadata_drop_recipe_is_independently_validated() {
        let source = "class Owner{Buffer<int> data;public init(Buffer<int> b){data=b;}}int main(){Owner a=Owner(Buffer<int>(2,1));}";
        let h = analyze(crate::parse_source(&crate::SourceFile::new("oop.ae", source)).unwrap())
            .unwrap();
        for mutation in 0..8 {
            let mut types = h.types.clone();
            let c = &mut types.classes[0];
            match mutation {
                0 => {
                    c.destruction.remove(0);
                }
                1 => {
                    c.destruction.insert(0, c.destruction[0].clone());
                }
                2 => c.destruction.reverse(),
                3 => c.fields[0].offset += 8,
                4 => c.fields[0].id = FieldId(999),
                5 => c.fields[0].class = ClassId(999),
                6 => c.layout.size += 8,
                7 => c.methods.clear(),
                _ => unreachable!(),
            }
            assert!(
                crate::verify_class_metadata(&types, &h.structs, &h.enums).is_err(),
                "metadata mutation {mutation}"
            );
        }
    }
    const INTERFACE_SOURCE: &str = "interface I{int get();mut int inc();}interface J{int get();}class C:I,J{int n;public init(){n=0;}public int get(){return n;}public mut int inc(){n=n+1;return n;}}int main(){C c=C();I i=c;int n=i.inc();return c.get();}";
    #[test]
    fn hir_interface_corruptions_reject_without_lowering() {
        let valid = analyze(
            crate::parse_source(&crate::SourceFile::new("interfaces.ae", INTERFACE_SOURCE))
                .unwrap(),
        )
        .unwrap();
        for kind in 20..29 {
            let mut bad = valid.clone();
            assert!(
                bad.functions
                    .iter_mut()
                    .any(|f| mutate_block(&mut f.body, kind)),
                "mutation {kind} not applied"
            );
            assert!(verify_hir(&bad).is_err(), "HIR interface mutation {kind}");
        }
    }
    #[test]
    fn interface_metadata_corruptions_reject_independently() {
        let valid = analyze(
            crate::parse_source(&crate::SourceFile::new("interfaces.ae", INTERFACE_SOURCE))
                .unwrap(),
        )
        .unwrap();
        for mutation in 0..15 {
            let mut bad = valid.clone();
            let types = &mut bad.types;
            match mutation {
                0 => types.witnesses[0].class = ClassId(999),
                1 => types.witnesses[0].interface = crate::InterfaceId(999),
                2 => {
                    types.witnesses[0].slots.pop();
                }
                3 => types.witnesses[0].slots[1] = types.witnesses[0].slots[0].clone(),
                4 => types.witnesses[0].slots[0].requirement.interface = crate::InterfaceId(1),
                5 => types.witnesses[0].slots[0].method = FunctionId(999),
                6 => {
                    types.classes[0]
                        .methods
                        .iter_mut()
                        .find(|m| m.name == "get")
                        .unwrap()
                        .public = false
                }
                7 => {
                    types.classes[0]
                        .methods
                        .iter_mut()
                        .find(|m| m.name == "get")
                        .unwrap()
                        .mutable = true
                }
                8 => types.classes[0]
                    .methods
                    .iter_mut()
                    .find(|m| m.name == "get")
                    .unwrap()
                    .parameters
                    .push(TypeId::BOOL),
                9 => {
                    types.classes[0]
                        .methods
                        .iter_mut()
                        .find(|m| m.name == "get")
                        .unwrap()
                        .result = TypeId::BOOL
                }
                10 => types.witnesses[0].slots.reverse(),
                11 => types.classes[0].interfaces.clear(),
                12 => types.classes[0].interfaces.push(crate::InterfaceId(0)),
                13 => types.interfaces[0].requirements[0].id.index = 1,
                14 => types.witnesses[0].id = crate::WitnessId(999),
                _ => unreachable!(),
            }
            assert!(
                crate::verify_interface_metadata(types).is_err(),
                "metadata mutation {mutation}"
            );
            assert!(
                verify_hir(&bad).is_err(),
                "HIR metadata mutation {mutation}"
            );
        }
    }

    #[test]
    fn hir_base_method_target_corruptions_reject_without_lowering() {
        let source = "open class A{public open int f(){return 1;}}class B:A{public override int f(){return 2;}public int parent(){return base.f();}}int main(){B b=B();return b.parent();}";
        let valid =
            analyze(crate::parse_source(&crate::SourceFile::new("base.ae", source)).unwrap())
                .unwrap();
        for kind in 29..31 {
            let mut bad = valid.clone();
            assert!(
                bad.functions
                    .iter_mut()
                    .any(|f| mutate_block(&mut f.body, kind)),
                "mutation {kind} not applied"
            );
            assert!(verify_hir(&bad).is_err(), "HIR base mutation {kind}");
        }
    }
}

#[cfg(test)]
mod inheritance_tests {
    use super::*;
    const SOURCE: &str = "interface I{int f();}open class A:I{Buffer<int> a;public init(Buffer<int> a){this.a=a;}public open int f(){return 1;}}class B:A{Buffer<int> b;public init(Buffer<int> a,Buffer<int> b):base(a){this.b=b;}public override int f(){return 7;}}int main(){B b=B(Buffer<int>(2,1),Buffer<int>(2,2));A a=b;I i=a;return a.f()+i.f();}";
    fn mutate(e: &mut HirExpr, mutation: u32) -> bool {
        if let HirExprKind::Class(op) = &mut e.kind {
            match (mutation, op.as_mut()) {
                (0, ClassOp::ClassUpcast { path, .. }) => {
                    path.reverse();
                    return true;
                }
                (1, ClassOp::ClassUpcast { transfer, .. }) => {
                    *transfer = !*transfer;
                    return true;
                }
                (2, ClassOp::BaseInit { base, .. }) => {
                    *base = ClassId(999);
                    return true;
                }
                (3, ClassOp::VirtualCall { slot, .. }) => {
                    *slot = crate::VirtualSlotId(FunctionId(999));
                    return true;
                }
                (4, ClassOp::VirtualCall { method, .. }) => {
                    *method = HirCallTarget::Instance(crate::InstanceId(999));
                    return true;
                }
                _ => (),
            }
            let mut changed = false;
            **op = op
                .map(
                    |e| {
                        let mut e = e.clone();
                        if !changed {
                            changed = mutate(&mut e, mutation);
                        }
                        Ok::<_, std::convert::Infallible>(e)
                    },
                    |f| Ok(*f),
                )
                .unwrap();
            return changed;
        }
        if let HirExprKind::Binary { left, right, .. } = &mut e.kind {
            return mutate(left, mutation) || mutate(right, mutation);
        }
        false
    }
    #[test]
    fn hir_inheritance_corruptions_reject_independently() {
        let valid = analyze(crate::parse_source(&crate::SourceFile::new("v3.ae", SOURCE)).unwrap())
            .unwrap();
        for mutation in 0..5 {
            let mut bad = valid.clone();
            assert!(
                bad.functions
                    .iter_mut()
                    .flat_map(|f| &mut f.body.statements)
                    .any(|s| match &mut s.kind {
                        HirStmtKind::Local { initializer, .. }
                        | HirStmtKind::Return {
                            value: initializer, ..
                        } => mutate(initializer, mutation),
                        _ => false,
                    })
            );
            assert!(verify_hir(&bad).is_err(), "HIR operation {mutation}");
        }
        for mutation in 0..9 {
            let mut bad = valid.clone();
            match mutation {
                0 => bad.types.classes[0].open = false,
                1 => bad.types.classes[1].base = Some(ClassId(1)),
                2 => bad.types.classes[1].methods[1].virtual_slot = None,
                3 => bad.types.classes[1].methods[1].override_target = None,
                4 => bad.types.classes[1].interfaces.clear(),
                5 => {
                    bad.types.witnesses[1].slots[0].method = bad.types.witnesses[0].slots[0].method
                }
                6 => bad.types.classes[1].destruction = bad.types.classes[0].destruction.clone(),
                7 => bad.types.classes[1].methods[1].mutable = true,
                8 => bad.types.classes[1].base = None,
                _ => unreachable!(),
            }
            assert!(verify_hir(&bad).is_err(), "HIR metadata {mutation}");
        }
    }
}
