//! Alias-canonicalized, nominal and fully typed HIR.
#![allow(missing_docs)]
#![allow(
    clippy::cast_possible_truncation,
    clippy::cast_possible_wrap,
    clippy::cast_precision_loss,
    clippy::enum_glob_use,
    clippy::many_single_char_names,
    clippy::float_cmp,
    clippy::semicolon_if_nothing_returned,
    clippy::too_many_lines,
    clippy::unused_self
)]
use crate::{
    AstBinaryOp, AstBlock, AstExpr, AstExprKind, AstFunction, AstMatchArm, AstPlace, AstStmtKind,
    AstType, AstUnaryOp, Diagnostic, DiagnosticCategory, EnumId, FieldId, FloatType, IntegerType,
    ParsedAst, Phase, SourceId, Span, StructId, TargetProperties, Type, VariantId,
};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ModuleId(pub u32);
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedImport {
    pub name: String,
    pub module: ModuleId,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ModuleInfo {
    pub id: ModuleId,
    pub name: String,
    pub source: SourceId,
    pub source_name: String,
    pub imports: Vec<ResolvedImport>,
}
#[derive(Clone, Debug)]
pub struct ParsedModule {
    pub info: ModuleInfo,
    pub ast: ParsedAst,
}
#[derive(Clone, Debug)]
pub struct ParsedProgram {
    pub modules: Vec<ParsedModule>,
    pub entry: ModuleId,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct FunctionId(pub u32);
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct LocalId(pub u32);
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParameterSignature {
    pub name: String,
    pub ty: Type,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FunctionSignature {
    pub id: FunctionId,
    pub module: ModuleId,
    pub name: String,
    pub parameters: Vec<ParameterSignature>,
    pub return_type: Type,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TypeAliasInfo {
    pub module: ModuleId,
    pub name: String,
    pub target_spelling: String,
    pub canonical: Type,
    pub span: Span,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TypeLayout {
    pub size: u64,
    pub align: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldInfo {
    pub id: FieldId,
    pub owner: StructId,
    pub index: u32,
    pub name: String,
    pub ty: Type,
    pub offset: u64,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructInfo {
    pub id: StructId,
    pub module: ModuleId,
    pub name: String,
    pub fields: Vec<FieldInfo>,
    pub layout: TypeLayout,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VariantPayloadInfo {
    pub index: u32,
    pub ty: Type,
    /// Absolute byte offset in the bootstrap typed enum envelope.
    pub offset: u64,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VariantInfo {
    pub id: VariantId,
    pub owner: EnumId,
    pub index: u32,
    pub name: String,
    pub discriminant: u32,
    pub payloads: Vec<VariantPayloadInfo>,
    pub storage_offset: u64,
    pub storage_layout: TypeLayout,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EnumInfo {
    pub id: EnumId,
    pub module: ModuleId,
    pub name: String,
    pub variants: Vec<VariantInfo>,
    pub layout: TypeLayout,
    pub span: Span,
}

#[derive(Clone, Debug)]
pub struct DeclaredProgram {
    program: ParsedProgram,
    signatures: Vec<FunctionSignature>,
    names: Vec<BTreeMap<String, FunctionId>>,
    imports: Vec<BTreeMap<String, ModuleId>>,
    module_names: BTreeMap<String, ModuleId>,
    aliases: Vec<BTreeMap<String, Type>>,
    alias_info: Vec<TypeAliasInfo>,
    structs: Vec<StructInfo>,
    enums: Vec<EnumInfo>,
    struct_names: Vec<BTreeMap<String, StructId>>,
    enum_names: Vec<BTreeMap<String, EnumId>>,
    variant_names: Vec<BTreeMap<String, VariantId>>,
    field_names: Vec<BTreeMap<String, FieldId>>,
    entry: FunctionId,
}
impl DeclaredProgram {
    #[must_use]
    pub fn signatures(&self) -> &[FunctionSignature] {
        &self.signatures
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirLocal {
    pub id: LocalId,
    pub name: String,
    pub ty: Type,
    pub span: Span,
    pub parameter: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirParameter {
    pub local: LocalId,
    pub ty: Type,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TypedHir {
    modules: Vec<ModuleInfo>,
    aliases: Vec<TypeAliasInfo>,
    structs: Vec<StructInfo>,
    enums: Vec<EnumInfo>,
    signatures: Vec<FunctionSignature>,
    functions: Vec<HirFunction>,
    entry: FunctionId,
}
impl TypedHir {
    #[must_use]
    pub fn signatures(&self) -> &[FunctionSignature] {
        &self.signatures
    }
    #[must_use]
    pub fn modules(&self) -> &[ModuleInfo] {
        &self.modules
    }
    #[must_use]
    pub fn aliases(&self) -> &[TypeAliasInfo] {
        &self.aliases
    }
    #[must_use]
    pub fn structs(&self) -> &[StructInfo] {
        &self.structs
    }
    #[must_use]
    pub fn enums(&self) -> &[EnumInfo] {
        &self.enums
    }
    #[must_use]
    pub fn functions(&self) -> &[HirFunction] {
        &self.functions
    }
    #[must_use]
    pub const fn entry(&self) -> FunctionId {
        self.entry
    }
    #[must_use]
    pub fn dump(&self) -> String {
        let mut d = format!(
            "entry: {:#?}\nmodules: {:#?}\naliases (transparent -> canonical): {:#?}\nstructs: {:#?}\nenums: {:#?}\nsignatures: {:#?}",
            self.entry, self.modules, self.aliases, self.structs, self.enums, self.signatures
        );
        for m in &self.modules {
            let f: Vec<_> = self.functions.iter().filter(|f| f.module == m.id).collect();
            write!(d, "\nmodule {:?} `{}` functions: {f:#?}", m.id, m.name).unwrap();
        }
        d
    }
    #[must_use]
    #[allow(clippy::type_complexity)]
    pub fn into_parts(
        self,
    ) -> (
        Vec<ModuleInfo>,
        Vec<StructInfo>,
        Vec<EnumInfo>,
        Vec<FunctionSignature>,
        Vec<HirFunction>,
        FunctionId,
    ) {
        (
            self.modules,
            self.structs,
            self.enums,
            self.signatures,
            self.functions,
            self.entry,
        )
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirFunction {
    pub id: FunctionId,
    pub module: ModuleId,
    pub parameters: Vec<HirParameter>,
    pub locals: Vec<HirLocal>,
    pub body: HirBlock,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirBlock {
    pub statements: Vec<HirStmt>,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirStmt {
    pub kind: HirStmtKind,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HirStmtKind {
    Local {
        local: LocalId,
        initializer: HirExpr,
    },
    Assign {
        place: HirPlace,
        value: HirExpr,
    },
    If {
        condition: HirExpr,
        then_block: HirBlock,
        else_block: Option<HirBlock>,
    },
    While {
        condition: HirExpr,
        body: HirBlock,
    },
    Match {
        scrutinee: HirExpr,
        enum_id: EnumId,
        arms: Vec<HirMatchArm>,
    },
    Return(HirExpr),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirMatchArm {
    pub variant_id: VariantId,
    pub bindings: Vec<HirMatchBinding>,
    pub body: HirBlock,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirMatchBinding {
    pub local: LocalId,
    pub payload_index: u32,
    pub ty: Type,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirPlace {
    pub local: LocalId,
    pub projections: Vec<FieldId>,
    pub ty: Type,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirExpr {
    pub kind: HirExprKind,
    pub ty: Type,
    pub span: Span,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FloatValue {
    Float32(u32),
    Float64(u64),
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HirExprKind {
    Int(i128),
    Float(FloatValue),
    Bool(bool),
    Local(LocalId),
    Load(HirPlace),
    Call {
        callee: FunctionId,
        args: Vec<HirExpr>,
    },
    StructInit {
        struct_id: StructId,
        fields: Vec<(FieldId, HirExpr)>,
    },
    EnumInit {
        enum_id: EnumId,
        variant_id: VariantId,
        payloads: Vec<HirExpr>,
    },
    Coerce {
        kind: CoercionKind,
        operand: Box<HirExpr>,
    },
    ExplicitCast {
        kind: CastKind,
        source_type: Type,
        target_type: Type,
        operand: Box<HirExpr>,
    },
    Unary {
        op: HirUnaryOp,
        operand: Box<HirExpr>,
    },
    Binary {
        op: HirBinaryOp,
        left: Box<HirExpr>,
        right: Box<HirExpr>,
    },
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CoercionKind {
    SignExtend,
    ZeroExtend,
    FloatExtend,
}
/// Value-conversion semantics selected completely by HIR.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CastKind {
    Identity,
    IntegerExtendSigned,
    IntegerExtendUnsigned,
    IntegerNarrowChecked,
    IntegerReencode,
    IntegerSignednessChecked,
    SignedIntegerToFloat,
    UnsignedIntegerToFloat,
    FloatToSignedIntegerChecked,
    FloatToUnsignedIntegerChecked,
    FloatExtend,
    FloatTruncate,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HirUnaryOp {
    NegateIntegerChecked,
    NegateFloat,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HirBinaryOp {
    AddIntegerChecked,
    SubtractIntegerChecked,
    MultiplyIntegerChecked,
    DivideIntegerSignedChecked,
    DivideIntegerUnsignedChecked,
    RemainderIntegerSignedChecked,
    RemainderIntegerUnsignedChecked,
    AddFloat,
    SubtractFloat,
    MultiplyFloat,
    DivideFloat,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    Equal,
    NotEqual,
}

pub fn collect_signatures(ast: ParsedAst) -> Result<DeclaredProgram, Vec<Diagnostic>> {
    let source = ast.functions.first().map_or(SourceId(0), |f| f.span.source);
    collect_program_signatures(ParsedProgram {
        modules: vec![ParsedModule {
            info: ModuleInfo {
                id: ModuleId(0),
                name: "main".into(),
                source,
                source_name: "<memory>".into(),
                imports: vec![],
            },
            ast,
        }],
        entry: ModuleId(0),
    })
}
pub fn collect_program_signatures(
    program: ParsedProgram,
) -> Result<DeclaredProgram, Vec<Diagnostic>> {
    validate_program(&program)?;
    let imports: Vec<BTreeMap<String, ModuleId>> = program
        .modules
        .iter()
        .map(|m| {
            m.info
                .imports
                .iter()
                .map(|i| (i.name.clone(), i.module))
                .collect()
        })
        .collect();
    let module_names: BTreeMap<String, ModuleId> = program
        .modules
        .iter()
        .map(|m| (m.info.name.clone(), m.info.id))
        .collect();

    // One fail-closed top-level namespace per module. This guarantees that a
    // call-like spelling has exactly one semantic interpretation.
    for module in &program.modules {
        let mut declarations = BTreeMap::new();
        for (kind, name, span) in module
            .ast
            .aliases()
            .iter()
            .map(|d| ("alias", &d.name, d.span))
            .chain(
                module
                    .ast
                    .structs()
                    .iter()
                    .map(|d| ("struct", &d.name, d.span)),
            )
            .chain(module.ast.enums().iter().map(|d| ("enum", &d.name, d.span)))
            .chain(
                module
                    .ast
                    .functions()
                    .iter()
                    .map(|d| ("function", &d.name, d.span)),
            )
        {
            let previous = declarations.insert(name.clone(), kind);
            if builtin(name).is_some() || previous.is_some() {
                let code = match previous {
                    Some("function") if kind == "function" => "E0211",
                    Some("alias") if kind == "alias" => "E0225",
                    _ if builtin(name).is_some() && kind == "function" => "E0211",
                    _ if builtin(name).is_some() && kind == "alias" => "E0225",
                    _ => "E0240",
                };
                return Err(vec![src(
                    Diagnostic::new(
                        code,
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!("conflicting top-level declaration `{name}` ({kind})"),
                        Some(span),
                    ),
                    module,
                )]);
            }
        }
    }

    // Nominal identities exist before any field/signature type is resolved.
    let mut struct_names = vec![BTreeMap::new(); program.modules.len()];
    let mut struct_decls = Vec::new();
    for module in &program.modules {
        for declaration in module.ast.structs() {
            let id = StructId(struct_decls.len() as u32);
            struct_names[module.info.id.0 as usize].insert(declaration.name.clone(), id);
            struct_decls.push((id, module.info.id, declaration));
        }
    }

    let mut enum_names = vec![BTreeMap::new(); program.modules.len()];
    let mut enum_decls = Vec::new();
    for module in &program.modules {
        for declaration in module.ast.enums() {
            let id = EnumId(enum_decls.len() as u32);
            enum_names[module.info.id.0 as usize].insert(declaration.name.clone(), id);
            enum_decls.push((id, module.info.id, declaration));
        }
    }

    let mut aliases = vec![BTreeMap::new(); program.modules.len()];
    let mut alias_info = vec![];
    for module in &program.modules {
        let mut declarations = BTreeMap::new();
        for a in module.ast.aliases() {
            declarations.insert(a.name.clone(), a);
        }
        let mut state = BTreeMap::new();
        for name in declarations.keys() {
            resolve_alias(
                name,
                module,
                &declarations,
                &struct_names,
                &enum_names,
                &imports,
                &module_names,
                &mut state,
                &mut aliases[module.info.id.0 as usize],
                &mut alias_info,
            )?;
        }
    }

    let mut structs = Vec::with_capacity(struct_decls.len());
    let mut field_names = Vec::with_capacity(struct_decls.len());
    let mut next_field = 0_u32;
    for (id, module_id, declaration) in struct_decls {
        let module = &program.modules[module_id.0 as usize];
        let mut seen = BTreeMap::new();
        let mut fields = Vec::new();
        for (index, field) in declaration.fields.iter().enumerate() {
            if seen.contains_key(&field.name) {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0241",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!(
                            "duplicate field `{}` in struct `{}`",
                            field.name, declaration.name
                        ),
                        Some(field.span),
                    ),
                    module,
                )]);
            }
            let ty = resolve_type_in_module(
                &field.ty,
                module_id,
                &aliases,
                &struct_names,
                &enum_names,
                &imports,
                &module_names,
            )
            .map_err(|d| vec![src(d, module)])?;
            let field_id = FieldId(next_field);
            next_field += 1;
            seen.insert(field.name.clone(), field_id);
            fields.push(FieldInfo {
                id: field_id,
                owner: id,
                index: index as u32,
                name: field.name.clone(),
                ty,
                offset: 0,
                span: field.span,
            });
        }
        field_names.push(seen);
        structs.push(StructInfo {
            id,
            module: module_id,
            name: declaration.name.clone(),
            fields,
            layout: TypeLayout { size: 0, align: 1 },
            span: declaration.span,
        });
    }

    let mut enums = Vec::with_capacity(enum_decls.len());
    let mut variant_names = Vec::with_capacity(enum_decls.len());
    for (id, module_id, declaration) in enum_decls {
        let module = &program.modules[module_id.0 as usize];
        let mut seen = BTreeMap::new();
        let mut variants = Vec::new();
        for (index, variant) in declaration.variants.iter().enumerate() {
            if seen.contains_key(&variant.name) {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0251",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!(
                            "duplicate variant `{}` in enum `{}`",
                            variant.name, declaration.name
                        ),
                        Some(variant.span),
                    ),
                    module,
                )]);
            }
            let variant_id = VariantId {
                enum_id: id,
                index: index as u32,
            };
            seen.insert(variant.name.clone(), variant_id);
            let payloads = variant
                .payloads
                .iter()
                .enumerate()
                .map(|(payload_index, ty)| {
                    resolve_type_in_module(
                        ty,
                        module_id,
                        &aliases,
                        &struct_names,
                        &enum_names,
                        &imports,
                        &module_names,
                    )
                    .map(|resolved| VariantPayloadInfo {
                        index: payload_index as u32,
                        ty: resolved,
                        offset: 0,
                        span: ty.span,
                    })
                })
                .collect::<Result<Vec<_>, _>>()
                .map_err(|d| vec![src(d, module)])?;
            variants.push(VariantInfo {
                id: variant_id,
                owner: id,
                index: index as u32,
                name: variant.name.clone(),
                discriminant: index as u32,
                payloads,
                storage_offset: 0,
                storage_layout: TypeLayout { size: 0, align: 1 },
                span: variant.span,
            });
        }
        variant_names.push(seen);
        enums.push(EnumInfo {
            id,
            module: module_id,
            name: declaration.name.clone(),
            variants,
            layout: TypeLayout { size: 0, align: 1 },
            span: declaration.span,
        });
    }
    compute_aggregate_layouts(&mut structs, &mut enums, TargetProperties::LINUX_X86_64).map_err(
        |(ty, message)| {
            let (span, module) = match ty {
                Type::Struct(id) => (structs[id.0 as usize].span, structs[id.0 as usize].module),
                Type::Enum(id) => (enums[id.0 as usize].span, enums[id.0 as usize].module),
                _ => unreachable!(),
            };
            let code = if matches!(ty, Type::Struct(_)) {
                "E0242"
            } else {
                "E0259"
            };
            vec![
                Diagnostic::new(
                    code,
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    message,
                    Some(span),
                )
                .with_source_name(&program.modules[module.0 as usize].info.source_name),
            ]
        },
    )?;

    let mut signatures = vec![];
    let mut names = vec![BTreeMap::new(); program.modules.len()];
    for module in &program.modules {
        for f in module.ast.functions() {
            let id = FunctionId(signatures.len() as u32);
            names[module.info.id.0 as usize].insert(f.name.clone(), id);
            let parameters = f
                .parameters
                .iter()
                .map(|p| {
                    resolve_type_in_module(
                        &p.ty,
                        module.info.id,
                        &aliases,
                        &struct_names,
                        &enum_names,
                        &imports,
                        &module_names,
                    )
                    .map(|ty| ParameterSignature {
                        name: p.name.clone(),
                        ty,
                        span: p.span,
                    })
                })
                .collect::<Result<Vec<_>, _>>()
                .map_err(|d| vec![src(d, module)])?;
            let return_type = resolve_type_in_module(
                &f.return_type,
                module.info.id,
                &aliases,
                &struct_names,
                &enum_names,
                &imports,
                &module_names,
            )
            .map_err(|d| vec![src(d, module)])?;
            signatures.push(FunctionSignature {
                id,
                module: module.info.id,
                name: f.name.clone(),
                parameters,
                return_type,
                span: f.span,
            });
        }
    }
    let em = &program.modules[program.entry.0 as usize];
    let Some(entry) = names[program.entry.0 as usize].get("main").copied() else {
        return Err(vec![src(
            Diagnostic::new(
                "E0200",
                Phase::Semantic,
                DiagnosticCategory::Name,
                "entry module requires `int main()`",
                em.ast.functions().first().map(|f| f.span),
            ),
            em,
        )]);
    };
    let main = &signatures[entry.0 as usize];
    if main.return_type != Type::INT64 || !main.parameters.is_empty() {
        return Err(vec![src(
            Diagnostic::new(
                "E0201",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "entry function must have signature `int main()`",
                Some(main.span),
            ),
            em,
        )]);
    }
    Ok(DeclaredProgram {
        program,
        signatures,
        names,
        imports,
        module_names,
        aliases,
        alias_info,
        structs,
        enums,
        struct_names,
        enum_names,
        variant_names,
        field_names,
        entry,
    })
}
#[derive(Clone, Copy, PartialEq, Eq)]
enum AliasState {
    Visiting,
    Done,
}
#[allow(clippy::too_many_arguments)]
fn resolve_alias(
    name: &str,
    module: &ParsedModule,
    decl: &BTreeMap<String, &crate::AstAlias>,
    struct_names: &[BTreeMap<String, StructId>],
    enum_names: &[BTreeMap<String, EnumId>],
    imports: &[BTreeMap<String, ModuleId>],
    module_names: &BTreeMap<String, ModuleId>,
    state: &mut BTreeMap<String, AliasState>,
    resolved: &mut BTreeMap<String, Type>,
    info: &mut Vec<TypeAliasInfo>,
) -> Result<Type, Vec<Diagnostic>> {
    if let Some(t) = resolved.get(name) {
        return Ok(*t);
    }
    if state.get(name) == Some(&AliasState::Visiting) {
        let a = decl[name];
        return Err(vec![src(
            Diagnostic::new(
                "E0226",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!("type alias cycle contains `{name}`"),
                Some(a.span),
            ),
            module,
        )]);
    }
    state.insert(name.into(), AliasState::Visiting);
    let a = decl[name];
    let ty = if a.target.module.is_some() {
        resolve_qualified_type(
            &a.target,
            module.info.id,
            None,
            struct_names,
            enum_names,
            imports,
            module_names,
        )
        .map_err(|d| vec![src(d, module)])?
    } else if let Some(t) = builtin(&a.target.name) {
        t
    } else if let Some(id) = struct_names[module.info.id.0 as usize].get(&a.target.name) {
        Type::Struct(*id)
    } else if let Some(id) = enum_names[module.info.id.0 as usize].get(&a.target.name) {
        Type::Enum(*id)
    } else if decl.contains_key(&a.target.name) {
        resolve_alias(
            &a.target.name,
            module,
            decl,
            struct_names,
            enum_names,
            imports,
            module_names,
            state,
            resolved,
            info,
        )?
    } else {
        return Err(vec![src(unknown_type(&a.target), module)]);
    };
    state.insert(name.into(), AliasState::Done);
    resolved.insert(name.into(), ty);
    info.push(TypeAliasInfo {
        module: module.info.id,
        name: name.into(),
        target_spelling: a.target.name.clone(),
        canonical: ty,
        span: a.span,
    });
    Ok(ty)
}

fn resolve_qualified_type(
    ty: &AstType,
    current: ModuleId,
    aliases: Option<&[BTreeMap<String, Type>]>,
    struct_names: &[BTreeMap<String, StructId>],
    enum_names: &[BTreeMap<String, EnumId>],
    imports: &[BTreeMap<String, ModuleId>],
    module_names: &BTreeMap<String, ModuleId>,
) -> Result<Type, Diagnostic> {
    let module = ty.module.as_ref().expect("qualified type");
    let Some(target) = module_names.get(module).copied() else {
        return Err(Diagnostic::new(
            "E0221",
            Phase::Semantic,
            DiagnosticCategory::Name,
            format!("unknown module `{module}`"),
            Some(ty.span),
        ));
    };
    if imports[current.0 as usize].get(module) != Some(&target) {
        return Err(Diagnostic::new(
            "E0223",
            Phase::Semantic,
            DiagnosticCategory::Name,
            format!("module `{module}` is not directly imported"),
            Some(ty.span),
        ));
    }
    struct_names[target.0 as usize]
        .get(&ty.name)
        .copied()
        .map(Type::Struct)
        .or_else(|| {
            enum_names[target.0 as usize]
                .get(&ty.name)
                .copied()
                .map(Type::Enum)
        })
        .or_else(|| aliases.and_then(|maps| maps[target.0 as usize].get(&ty.name).copied()))
        .ok_or_else(|| unknown_type(ty))
}

fn resolve_type_in_module(
    ty: &AstType,
    current: ModuleId,
    aliases: &[BTreeMap<String, Type>],
    struct_names: &[BTreeMap<String, StructId>],
    enum_names: &[BTreeMap<String, EnumId>],
    imports: &[BTreeMap<String, ModuleId>],
    module_names: &BTreeMap<String, ModuleId>,
) -> Result<Type, Diagnostic> {
    if ty.module.is_some() {
        return resolve_qualified_type(
            ty,
            current,
            Some(aliases),
            struct_names,
            enum_names,
            imports,
            module_names,
        );
    }
    builtin(&ty.name)
        .or_else(|| aliases[current.0 as usize].get(&ty.name).copied())
        .or_else(|| {
            struct_names[current.0 as usize]
                .get(&ty.name)
                .copied()
                .map(Type::Struct)
        })
        .or_else(|| {
            enum_names[current.0 as usize]
                .get(&ty.name)
                .copied()
                .map(Type::Enum)
        })
        .ok_or_else(|| unknown_type(ty))
}

fn align_up(value: u64, align: u64) -> u64 {
    value.div_ceil(align) * align
}

#[allow(clippy::items_after_statements)]
fn compute_aggregate_layouts(
    structs: &mut [StructInfo],
    enums: &mut [EnumInfo],
    target: TargetProperties,
) -> Result<(), (Type, String)> {
    #[derive(Clone, Copy)]
    enum Node {
        Struct(StructId),
        Enum(EnumId),
    }
    fn node_type(node: Node) -> Type {
        match node {
            Node::Struct(id) => Type::Struct(id),
            Node::Enum(id) => Type::Enum(id),
        }
    }
    fn node_index(node: Node, struct_count: usize) -> usize {
        match node {
            Node::Struct(id) => id.0 as usize,
            Node::Enum(id) => struct_count + id.0 as usize,
        }
    }
    fn visit(
        node: Node,
        structs: &[StructInfo],
        enums: &[EnumInfo],
        state: &mut [u8],
    ) -> Result<(), (Type, String)> {
        let index = node_index(node, structs.len());
        if state[index] == 2 {
            return Ok(());
        }
        if state[index] == 1 {
            let name = match node {
                Node::Struct(id) => &structs[id.0 as usize].name,
                Node::Enum(id) => &enums[id.0 as usize].name,
            };
            let identity = enums
                .iter()
                .enumerate()
                .find(|(enum_index, _)| state[structs.len() + enum_index] == 1)
                .map_or_else(
                    || node_type(node),
                    |(enum_index, _)| Type::Enum(EnumId(enum_index as u32)),
                );
            return Err((
                identity,
                format!("recursive by-value aggregate `{name}` has infinite size"),
            ));
        }
        state[index] = 1;
        let types: Vec<Type> = match node {
            Node::Struct(id) => structs[id.0 as usize]
                .fields
                .iter()
                .map(|field| field.ty)
                .collect(),
            Node::Enum(id) => enums[id.0 as usize]
                .variants
                .iter()
                .flat_map(|variant| variant.payloads.iter().map(|payload| payload.ty))
                .collect(),
        };
        for ty in types {
            match ty {
                Type::Struct(id) => visit(Node::Struct(id), structs, enums, state)?,
                Type::Enum(id) => visit(Node::Enum(id), structs, enums, state)?,
                _ => {}
            }
        }
        state[index] = 2;
        Ok(())
    }
    let mut cycle_state = vec![0_u8; structs.len() + enums.len()];
    for index in 0..structs.len() {
        visit(
            Node::Struct(StructId(index as u32)),
            structs,
            enums,
            &mut cycle_state,
        )?;
    }
    for index in 0..enums.len() {
        visit(
            Node::Enum(EnumId(index as u32)),
            structs,
            enums,
            &mut cycle_state,
        )?;
    }

    fn type_layout(
        ty: Type,
        structs: &mut [StructInfo],
        enums: &mut [EnumInfo],
        struct_state: &mut [u8],
        enum_state: &mut [u8],
        target: TargetProperties,
    ) -> TypeLayout {
        match ty {
            Type::Bool => TypeLayout { size: 1, align: 1 },
            Type::Integer(integer) => {
                let bytes = u64::from(integer.bits(target) / 8);
                TypeLayout {
                    size: bytes,
                    align: bytes,
                }
            }
            Type::Float(FloatType::Float32) => TypeLayout { size: 4, align: 4 },
            Type::Float(FloatType::Float64) => TypeLayout { size: 8, align: 8 },
            Type::Struct(id) => struct_layout(id, structs, enums, struct_state, enum_state, target),
            Type::Enum(id) => enum_layout(id, structs, enums, struct_state, enum_state, target),
        }
    }
    fn struct_layout(
        id: StructId,
        structs: &mut [StructInfo],
        enums: &mut [EnumInfo],
        struct_state: &mut [u8],
        enum_state: &mut [u8],
        target: TargetProperties,
    ) -> TypeLayout {
        if struct_state[id.0 as usize] == 2 {
            return structs[id.0 as usize].layout;
        }
        struct_state[id.0 as usize] = 1;
        let field_types: Vec<Type> = structs[id.0 as usize]
            .fields
            .iter()
            .map(|field| field.ty)
            .collect();
        let mut offset = 0;
        let mut aggregate_align = 1;
        let mut offsets = Vec::with_capacity(field_types.len());
        for ty in field_types {
            let layout = type_layout(ty, structs, enums, struct_state, enum_state, target);
            offset = align_up(offset, layout.align);
            offsets.push(offset);
            offset += layout.size;
            aggregate_align = aggregate_align.max(layout.align);
        }
        let layout = TypeLayout {
            size: align_up(offset, aggregate_align),
            align: aggregate_align,
        };
        for (field, field_offset) in structs[id.0 as usize].fields.iter_mut().zip(offsets) {
            field.offset = field_offset;
        }
        structs[id.0 as usize].layout = layout;
        struct_state[id.0 as usize] = 2;
        layout
    }
    fn enum_layout(
        id: EnumId,
        structs: &mut [StructInfo],
        enums: &mut [EnumInfo],
        struct_state: &mut [u8],
        enum_state: &mut [u8],
        target: TargetProperties,
    ) -> TypeLayout {
        if enum_state[id.0 as usize] == 2 {
            return enums[id.0 as usize].layout;
        }
        enum_state[id.0 as usize] = 1;
        let variant_types: Vec<Vec<Type>> = enums[id.0 as usize]
            .variants
            .iter()
            .map(|variant| variant.payloads.iter().map(|payload| payload.ty).collect())
            .collect();
        let mut offset = 4_u64;
        let mut aggregate_align = 4_u64;
        let mut computed = Vec::new();
        for payload_types in variant_types {
            let mut tuple_offset = 0_u64;
            let mut tuple_align = 1_u64;
            let mut payload_offsets = Vec::new();
            for ty in payload_types {
                let layout = type_layout(ty, structs, enums, struct_state, enum_state, target);
                tuple_offset = align_up(tuple_offset, layout.align);
                payload_offsets.push(tuple_offset);
                tuple_offset += layout.size;
                tuple_align = tuple_align.max(layout.align);
            }
            let storage_layout = TypeLayout {
                size: align_up(tuple_offset, tuple_align),
                align: tuple_align,
            };
            offset = align_up(offset, tuple_align);
            let storage_offset = offset;
            offset += storage_layout.size;
            aggregate_align = aggregate_align.max(tuple_align);
            computed.push((storage_offset, storage_layout, payload_offsets));
        }
        let layout = TypeLayout {
            size: align_up(offset, aggregate_align),
            align: aggregate_align,
        };
        for (variant, (storage_offset, storage_layout, payload_offsets)) in
            enums[id.0 as usize].variants.iter_mut().zip(computed)
        {
            variant.storage_offset = storage_offset;
            variant.storage_layout = storage_layout;
            for (payload, relative) in variant.payloads.iter_mut().zip(payload_offsets) {
                payload.offset = storage_offset + relative;
            }
        }
        enums[id.0 as usize].layout = layout;
        enum_state[id.0 as usize] = 2;
        layout
    }

    let mut struct_state = vec![0_u8; structs.len()];
    let mut enum_state = vec![0_u8; enums.len()];
    for index in 0..structs.len() {
        struct_layout(
            StructId(index as u32),
            structs,
            enums,
            &mut struct_state,
            &mut enum_state,
            target,
        );
    }
    for index in 0..enums.len() {
        enum_layout(
            EnumId(index as u32),
            structs,
            enums,
            &mut struct_state,
            &mut enum_state,
            target,
        );
    }
    Ok(())
}

fn src(d: Diagnostic, m: &ParsedModule) -> Diagnostic {
    d.with_source_name(&m.info.source_name)
}

pub fn analyze_bodies(d: DeclaredProgram) -> Result<TypedHir, Vec<Diagnostic>> {
    analyze_bodies_for_target(d, TargetProperties::LINUX_X86_64)
}
pub fn analyze_bodies_for_target(
    d: DeclaredProgram,
    target: TargetProperties,
) -> Result<TypedHir, Vec<Diagnostic>> {
    let mut functions = vec![];
    for m in &d.program.modules {
        for f in m.ast.functions() {
            let id = FunctionId(functions.len() as u32);
            functions.push(
                analyze_function(f, id, m.info.id, &d, target).map_err(|ds| {
                    ds.into_iter()
                        .map(|x| x.with_source_name(&m.info.source_name))
                        .collect::<Vec<_>>()
                })?,
            );
        }
    }
    let hir = TypedHir {
        modules: d.program.modules.iter().map(|m| m.info.clone()).collect(),
        aliases: d.alias_info,
        structs: d.structs,
        enums: d.enums,
        signatures: d.signatures,
        functions,
        entry: d.entry,
    };
    verify_hir(&hir)?;
    Ok(hir)
}
pub fn analyze(ast: ParsedAst) -> Result<TypedHir, Vec<Diagnostic>> {
    analyze_bodies(collect_signatures(ast)?)
}
fn analyze_function(
    f: &AstFunction,
    id: FunctionId,
    module: ModuleId,
    d: &DeclaredProgram,
    target: TargetProperties,
) -> Result<HirFunction, Vec<Diagnostic>> {
    let sig = &d.signatures[id.0 as usize];
    let mut a = Analyzer {
        scopes: vec![BTreeMap::new()],
        locals: vec![],
        signatures: &d.signatures,
        names: &d.names,
        imports: &d.imports,
        module_names: &d.module_names,
        aliases: &d.aliases,
        structs: &d.structs,
        enums: &d.enums,
        struct_names: &d.struct_names,
        enum_names: &d.enum_names,
        variant_names: &d.variant_names,
        field_names: &d.field_names,
        module,
        return_type: sig.return_type,
        target,
    };
    let mut parameters = vec![];
    for p in &sig.parameters {
        if a.scopes[0].contains_key(&p.name) {
            return Err(vec![duplicate("parameter", &p.name, p.span)]);
        }
        let local = LocalId(a.locals.len() as u32);
        a.locals.push(HirLocal {
            id: local,
            name: p.name.clone(),
            ty: p.ty,
            span: p.span,
            parameter: true,
        });
        a.scopes[0].insert(p.name.clone(), local);
        parameters.push(HirParameter {
            local,
            ty: p.ty,
            span: p.span,
        });
    }
    let body = a.block(&f.body, false)?;
    if !definitely_returns(&body) {
        return Err(vec![Diagnostic::new(
            "E0207",
            Phase::Semantic,
            DiagnosticCategory::Type,
            format!(
                "every reachable path through `{}` must return {}",
                sig.name, sig.return_type
            ),
            Some(f.body.span),
        )]);
    }
    Ok(HirFunction {
        id,
        module,
        parameters,
        locals: a.locals,
        body,
        span: f.span,
    })
}

struct Analyzer<'a> {
    scopes: Vec<BTreeMap<String, LocalId>>,
    locals: Vec<HirLocal>,
    signatures: &'a [FunctionSignature],
    names: &'a [BTreeMap<String, FunctionId>],
    imports: &'a [BTreeMap<String, ModuleId>],
    module_names: &'a BTreeMap<String, ModuleId>,
    aliases: &'a [BTreeMap<String, Type>],
    structs: &'a [StructInfo],
    enums: &'a [EnumInfo],
    struct_names: &'a [BTreeMap<String, StructId>],
    enum_names: &'a [BTreeMap<String, EnumId>],
    variant_names: &'a [BTreeMap<String, VariantId>],
    field_names: &'a [BTreeMap<String, FieldId>],
    module: ModuleId,
    return_type: Type,
    target: TargetProperties,
}
struct Checked {
    expr: HirExpr,
    constant: Option<ConstantValue>,
}
#[derive(Clone, Copy)]
enum ConstantValue {
    Integer(i128),
    Float(FloatValue),
}
impl Analyzer<'_> {
    fn block(&mut self, b: &AstBlock, nested: bool) -> Result<HirBlock, Vec<Diagnostic>> {
        if nested {
            self.scopes.push(BTreeMap::new())
        }
        let mut statements = vec![];
        let mut ended = false;
        for s in &b.statements {
            if ended {
                return Err(vec![Diagnostic::new(
                    "E0208",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    "unreachable statement",
                    Some(s.span),
                )]);
            }
            let kind = match &s.kind {
                AstStmtKind::Local {
                    ty,
                    name,
                    initializer,
                } => {
                    if self.scopes.last().is_some_and(|x| x.contains_key(name)) {
                        return Err(vec![duplicate("local", name, s.span)]);
                    }
                    let ty = resolve_type_in_module(
                        ty,
                        self.module,
                        self.aliases,
                        self.struct_names,
                        self.enum_names,
                        self.imports,
                        self.module_names,
                    )
                    .map_err(|d| vec![d])?;
                    let initializer = self.expression(initializer, Some(ty))?.expr;
                    let local = LocalId(self.locals.len() as u32);
                    self.locals.push(HirLocal {
                        id: local,
                        name: name.clone(),
                        ty,
                        span: s.span,
                        parameter: false,
                    });
                    self.scopes.last_mut().unwrap().insert(name.clone(), local);
                    HirStmtKind::Local { local, initializer }
                }
                AstStmtKind::Assign { place, value } => {
                    let place = self.resolve_place(place)?;
                    let value = self
                        .expression(value, Some(place.ty))
                        .map_err(|mut ds| {
                            if !place.projections.is_empty() {
                                if let Some(diagnostic) = ds.first_mut() {
                                    diagnostic.code = "E0245";
                                    diagnostic.message = format!(
                                        "field assignment requires {}: {}",
                                        place.ty, diagnostic.message
                                    );
                                }
                            }
                            ds
                        })?
                        .expr;
                    HirStmtKind::Assign { place, value }
                }
                AstStmtKind::If {
                    condition,
                    then_block,
                    else_block,
                } => HirStmtKind::If {
                    condition: self.expression(condition, Some(Type::Bool))?.expr,
                    then_block: self.block(then_block, true)?,
                    else_block: else_block
                        .as_ref()
                        .map(|x| self.block(x, true))
                        .transpose()?,
                },
                AstStmtKind::While { condition, body } => HirStmtKind::While {
                    condition: self.expression(condition, Some(Type::Bool))?.expr,
                    body: self.block(body, true)?,
                },
                AstStmtKind::Match { scrutinee, arms } => self.match_statement(scrutinee, arms)?,
                AstStmtKind::Return(v) => {
                    HirStmtKind::Return(self.expression(v, Some(self.return_type))?.expr)
                }
            };
            let hs = HirStmt { kind, span: s.span };
            ended = statement_returns(&hs);
            statements.push(hs)
        }
        if nested {
            self.scopes.pop();
        }
        Ok(HirBlock {
            statements,
            span: b.span,
        })
    }

    fn match_statement(
        &mut self,
        scrutinee: &AstExpr,
        arms: &[AstMatchArm],
    ) -> Result<HirStmtKind, Vec<Diagnostic>> {
        let scrutinee = self.expression(scrutinee, None)?.expr;
        let Some(enum_id) = scrutinee.ty.as_enum() else {
            return Err(vec![Diagnostic::new(
                "E0255",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!("match scrutinee must be an enum, found {}", scrutinee.ty),
                Some(scrutinee.span),
            )]);
        };
        let enum_info = &self.enums[enum_id.0 as usize];
        let mut seen = BTreeSet::new();
        let mut resolved_arms = Vec::new();
        for arm in arms {
            let pattern_ty = AstType {
                module: arm.pattern.module.clone(),
                name: arm.pattern.enum_name.clone(),
                span: arm.pattern.span,
            };
            let resolved_ty = resolve_type_in_module(
                &pattern_ty,
                self.module,
                self.aliases,
                self.struct_names,
                self.enum_names,
                self.imports,
                self.module_names,
            )
            .map_err(|diagnostic| vec![diagnostic])?;
            let Some(pattern_enum) = resolved_ty.as_enum() else {
                return Err(vec![Diagnostic::new(
                    "E0255",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "match pattern qualifier `{}` is not an enum",
                        arm.pattern.enum_name
                    ),
                    Some(arm.pattern.span),
                )]);
            };
            if pattern_enum != enum_id {
                return Err(vec![Diagnostic::new(
                    "E0257",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "variant pattern belongs to enum `{}`, not `{}`",
                        self.enums[pattern_enum.0 as usize].name, enum_info.name
                    ),
                    Some(arm.pattern.span),
                )]);
            }
            let Some(variant_id) = self.variant_names[enum_id.0 as usize]
                .get(&arm.pattern.variant)
                .copied()
            else {
                return Err(vec![Diagnostic::new(
                    "E0252",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!(
                        "unknown variant `{}` on enum `{}`",
                        arm.pattern.variant, enum_info.name
                    ),
                    Some(arm.pattern.span),
                )]);
            };
            if !seen.insert(variant_id) {
                return Err(vec![Diagnostic::new(
                    "E0256",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!(
                        "duplicate match arm for `{}.{}`",
                        enum_info.name, arm.pattern.variant
                    ),
                    Some(arm.pattern.span),
                )]);
            }
            let variant = &enum_info.variants[variant_id.index as usize];
            if arm.pattern.bindings.len() != variant.payloads.len() {
                return Err(vec![Diagnostic::new(
                    "E0253",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "variant `{}.{}` expects {} payload bindings, found {}",
                        enum_info.name,
                        variant.name,
                        variant.payloads.len(),
                        arm.pattern.bindings.len()
                    ),
                    Some(arm.pattern.span),
                )]);
            }
            self.scopes.push(BTreeMap::new());
            let mut bindings = Vec::new();
            for ((name, span), payload) in arm.pattern.bindings.iter().zip(&variant.payloads) {
                if self.scopes.last().unwrap().contains_key(name) {
                    self.scopes.pop();
                    return Err(vec![duplicate("match binding", name, *span)]);
                }
                let local = LocalId(self.locals.len() as u32);
                self.locals.push(HirLocal {
                    id: local,
                    name: name.clone(),
                    ty: payload.ty,
                    span: *span,
                    parameter: false,
                });
                self.scopes.last_mut().unwrap().insert(name.clone(), local);
                bindings.push(HirMatchBinding {
                    local,
                    payload_index: payload.index,
                    ty: payload.ty,
                    span: *span,
                });
            }
            let body = self.block(&arm.body, false)?;
            self.scopes.pop();
            resolved_arms.push(HirMatchArm {
                variant_id,
                bindings,
                body,
                span: arm.span,
            });
        }
        if seen.len() != enum_info.variants.len() {
            let missing = enum_info
                .variants
                .iter()
                .filter(|variant| !seen.contains(&variant.id))
                .map(|variant| variant.name.as_str())
                .collect::<Vec<_>>()
                .join(", ");
            return Err(vec![Diagnostic::new(
                "E0258",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "non-exhaustive match on `{}`; missing: {missing}",
                    enum_info.name
                ),
                Some(scrutinee.span),
            )]);
        }
        Ok(HirStmtKind::Match {
            scrutinee,
            enum_id,
            arms: resolved_arms,
        })
    }

    fn resolve_place(&self, place: &AstPlace) -> Result<HirPlace, Vec<Diagnostic>> {
        let Some(local) = self.lookup(&place.root) else {
            return Err(vec![unknown_name(&place.root, place.span)]);
        };
        let mut resolved = HirPlace {
            local,
            projections: Vec::new(),
            ty: self.locals[local.0 as usize].ty,
        };
        for (name, span) in &place.fields {
            self.project_field(&mut resolved, name, *span)?;
        }
        Ok(resolved)
    }

    fn resolve_expr_place(&self, expression: &AstExpr) -> Result<HirPlace, Vec<Diagnostic>> {
        match &expression.kind {
            AstExprKind::Name(name) => {
                let Some(local) = self.lookup(name) else {
                    return Err(vec![unknown_name(name, expression.span)]);
                };
                Ok(HirPlace {
                    local,
                    projections: Vec::new(),
                    ty: self.locals[local.0 as usize].ty,
                })
            }
            AstExprKind::Field {
                base,
                name,
                name_span,
            } => {
                if let AstExprKind::Name(module) = &base.kind {
                    if self.module_names.contains_key(module) && self.lookup(module).is_none() {
                        return Err(vec![Diagnostic::new(
                            "E0224",
                            Phase::Semantic,
                            DiagnosticCategory::Unsupported,
                            format!("qualified value `{module}.{name}` is not admitted"),
                            Some(expression.span),
                        )]);
                    }
                }
                let mut place = self.resolve_expr_place(base)?;
                self.project_field(&mut place, name, *name_span)?;
                Ok(place)
            }
            _ => Err(vec![Diagnostic::new(
                "E0244",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "field access requires an addressable local value",
                Some(expression.span),
            )]),
        }
    }

    fn project_field(
        &self,
        place: &mut HirPlace,
        name: &str,
        span: Span,
    ) -> Result<(), Vec<Diagnostic>> {
        let Some(struct_id) = place.ty.as_struct() else {
            return Err(vec![Diagnostic::new(
                "E0244",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!("field access on non-struct type {}", place.ty),
                Some(span),
            )]);
        };
        let Some(field_id) = self.field_names[struct_id.0 as usize].get(name).copied() else {
            return Err(vec![Diagnostic::new(
                "E0243",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!(
                    "unknown field `{name}` on struct `{}`",
                    self.structs[struct_id.0 as usize].name
                ),
                Some(span),
            )]);
        };
        let field = self.structs[struct_id.0 as usize]
            .fields
            .iter()
            .find(|field| field.id == field_id)
            .expect("field-name index is coherent");
        place.projections.push(field_id);
        place.ty = field.ty;
        Ok(())
    }

    fn expression(&self, e: &AstExpr, expected: Option<Type>) -> Result<Checked, Vec<Diagnostic>> {
        if let AstExprKind::Integer(t) = &e.kind {
            return self.integer(t, false, expected, e.span);
        }
        if let AstExprKind::Float(t) = &e.kind {
            return self.float(t, false, expected, e.span);
        }
        if let AstExprKind::Unary {
            op: AstUnaryOp::Negate,
            operand,
        } = &e.kind
        {
            if let AstExprKind::Integer(t) = &operand.kind {
                return self.integer(t, true, expected, e.span);
            }
            if let AstExprKind::Float(t) = &operand.kind {
                return self.float(t, true, expected, e.span);
            }
        }
        let c = match &e.kind {
            AstExprKind::Bool(v) => Checked {
                expr: HirExpr {
                    kind: HirExprKind::Bool(*v),
                    ty: Type::Bool,
                    span: e.span,
                },
                constant: None,
            },
            AstExprKind::Name(n) => {
                if self.names[self.module.0 as usize].contains_key(n) {
                    return Err(vec![Diagnostic::new(
                        "E0215",
                        Phase::Semantic,
                        DiagnosticCategory::Unsupported,
                        "function values are not admitted",
                        Some(e.span),
                    )]);
                }
                let Some(l) = self.lookup(n) else {
                    return Err(vec![unknown_name(n, e.span)]);
                };
                Checked {
                    expr: HirExpr {
                        kind: HirExprKind::Local(l),
                        ty: self.locals[l.0 as usize].ty,
                        span: e.span,
                    },
                    constant: None,
                }
            }
            AstExprKind::Call { callee, args } => {
                if let Some(target) = builtin(callee)
                    .or_else(|| self.aliases[self.module.0 as usize].get(callee).copied())
                {
                    if let Type::Struct(id) = target {
                        self.struct_init(id, callee, args, e.span)?
                    } else if let Type::Enum(_) = target {
                        return Err(vec![Diagnostic::new(
                            "E0250",
                            Phase::Semantic,
                            DiagnosticCategory::Syntax,
                            "enum construction requires a qualified variant",
                            Some(e.span),
                        )]);
                    } else {
                        self.explicit_cast(callee, target, args, e.span)?
                    }
                } else if let Some(id) = self.struct_names[self.module.0 as usize].get(callee) {
                    self.struct_init(*id, callee, args, e.span)?
                } else {
                    self.call(callee, args, e.span)?
                }
            }
            AstExprKind::QualifiedCall {
                module,
                function,
                args,
            } => {
                if let Some(enum_id) = self.local_enum_id(module) {
                    self.enum_init(enum_id, function, args, true, e.span)?
                } else {
                    self.qualified_apply(module, function, args, e.span)?
                }
            }
            AstExprKind::VariantCall {
                module,
                enum_name,
                variant,
                args,
            } => {
                let enum_id = self.qualified_enum_id(module, enum_name, e.span)?;
                self.enum_init(enum_id, variant, args, true, e.span)?
            }
            AstExprKind::Field { base, name, .. } => {
                if let AstExprKind::Field {
                    base: qualifier,
                    name: enum_name,
                    ..
                } = &base.kind
                    && let AstExprKind::Name(module) = &qualifier.kind
                    && self.lookup(module).is_none()
                    && self.module_names.contains_key(module)
                {
                    let enum_id = self.qualified_enum_id(module, enum_name, e.span)?;
                    self.enum_init(enum_id, name, &[], false, e.span)?
                } else if let AstExprKind::Name(type_name) = &base.kind {
                    if let Some(enum_id) = self.local_enum_id(type_name) {
                        self.enum_init(enum_id, name, &[], false, e.span)?
                    } else {
                        let place = self.resolve_expr_place(e)?;
                        Checked {
                            expr: HirExpr {
                                ty: place.ty,
                                kind: HirExprKind::Load(place),
                                span: e.span,
                            },
                            constant: None,
                        }
                    }
                } else {
                    let place = self.resolve_expr_place(e)?;
                    Checked {
                        expr: HirExpr {
                            ty: place.ty,
                            kind: HirExprKind::Load(place),
                            span: e.span,
                        },
                        constant: None,
                    }
                }
            }
            AstExprKind::QualifiedName { module, member } => {
                return Err(vec![Diagnostic::new(
                    "E0224",
                    Phase::Semantic,
                    DiagnosticCategory::Unsupported,
                    format!("qualified value `{module}.{member}` is not admitted"),
                    Some(e.span),
                )]);
            }
            AstExprKind::Unary { operand, .. } => self.negate(operand, e.span)?,
            AstExprKind::Binary { op, left, right } => {
                self.binary(*op, left, right, expected, e.span)?
            }
            _ => unreachable!(),
        };
        self.coerce(c, expected)
    }
    fn integer(
        &self,
        text: &str,
        neg: bool,
        expected: Option<Type>,
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let ty = expected.unwrap_or(Type::INT64);
        let Some(it) = ty.as_integer() else {
            return Err(vec![type_error(
                format!("integer literal cannot initialize {ty}"),
                span,
            )]);
        };
        let mag = text
            .parse::<u128>()
            .map_err(|_| vec![range(text, ty, span, self.target)])?;
        let value = if neg {
            if mag > 1u128 << 127 {
                return Err(vec![range(text, ty, span, self.target)]);
            }
            if mag == 1u128 << 127 {
                i128::MIN
            } else {
                -(mag as i128)
            }
        } else {
            i128::try_from(mag).map_err(|_| vec![range(text, ty, span, self.target)])?
        };
        let (min, max) = it.range(self.target);
        if value < min || value > max {
            return Err(vec![range(
                if neg { "negative integer" } else { text },
                ty,
                span,
                self.target,
            )]);
        }
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::Int(value),
                ty,
                span,
            },
            constant: Some(ConstantValue::Integer(value)),
        })
    }
    fn float(
        &self,
        text: &str,
        neg: bool,
        expected: Option<Type>,
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let ty = expected.unwrap_or(Type::Float(FloatType::Float64));
        let Some(ft) = ty.as_float() else {
            return Err(vec![type_error(
                format!("floating literal cannot initialize {ty}"),
                span,
            )]);
        };
        let s = if neg { format!("-{text}") } else { text.into() };
        let value = match ft {
            FloatType::Float32 => s
                .parse::<f32>()
                .ok()
                .filter(|v| v.is_finite())
                .map(|v| FloatValue::Float32(v.to_bits())),
            FloatType::Float64 => s
                .parse::<f64>()
                .ok()
                .filter(|v| v.is_finite())
                .map(|v| FloatValue::Float64(v.to_bits())),
        }
        .ok_or_else(|| {
            vec![Diagnostic::new(
                "E0216",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!("floating literal `{s}` is outside {ty} finite range"),
                Some(span),
            )]
        })?;
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::Float(value),
                ty,
                span,
            },
            constant: Some(ConstantValue::Float(value)),
        })
    }
    fn negate(&self, o: &AstExpr, span: Span) -> Result<Checked, Vec<Diagnostic>> {
        let c = self.expression(o, None)?;
        let ty = c.expr.ty;
        let op = match ty {
            Type::Integer(i) if i.is_signed() => HirUnaryOp::NegateIntegerChecked,
            Type::Integer(_) => {
                return Err(vec![Diagnostic::new(
                    "E0217",
                    Phase::Semantic,
                    DiagnosticCategory::Integer,
                    "unary `-` is invalid for unsigned values",
                    Some(span),
                )]);
            }
            Type::Float(_) => HirUnaryOp::NegateFloat,
            Type::Bool | Type::Struct(_) | Type::Enum(_) => {
                return Err(vec![type_error(
                    format!("{ty} cannot be used numerically"),
                    span,
                )]);
            }
        };
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::Unary {
                    op,
                    operand: Box::new(c.expr),
                },
                ty,
                span,
            },
            constant: match c.constant {
                Some(ConstantValue::Integer(value)) => {
                    value.checked_neg().map(ConstantValue::Integer)
                }
                Some(ConstantValue::Float(FloatValue::Float32(bits))) => Some(
                    ConstantValue::Float(FloatValue::Float32((-f32::from_bits(bits)).to_bits())),
                ),
                Some(ConstantValue::Float(FloatValue::Float64(bits))) => Some(
                    ConstantValue::Float(FloatValue::Float64((-f64::from_bits(bits)).to_bits())),
                ),
                None => None,
            },
        })
    }
    fn explicit_cast(
        &self,
        spelling: &str,
        target: Type,
        args: &[AstExpr],
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if args.len() != 1 {
            return Err(vec![Diagnostic::new(
                "E0230",
                Phase::Semantic,
                DiagnosticCategory::Conversion,
                format!("conversion target `{spelling}` expects exactly one operand"),
                Some(span),
            )]);
        }
        let operand = match self.expression(&args[0], None) {
            Ok(value) => value,
            Err(diagnostics)
                if target.as_integer().is_some()
                    && diagnostics.first().is_some_and(|d| d.code == "E0209") =>
            {
                self.expression(&args[0], Some(target))?
            }
            Err(diagnostics) => return Err(diagnostics),
        };
        let source = operand.expr.ty;
        if source == Type::Bool || target == Type::Bool {
            return Err(vec![Diagnostic::new(
                "E0232",
                Phase::Semantic,
                DiagnosticCategory::Conversion,
                format!("bool has no numeric conversions ({source} to {target})"),
                Some(span),
            )]);
        }
        let kind = select_cast_kind(source, target, self.target).ok_or_else(|| {
            vec![Diagnostic::new(
                "E0230",
                Phase::Semantic,
                DiagnosticCategory::Conversion,
                format!("invalid explicit scalar conversion from {source} to {target}"),
                Some(span),
            )]
        })?;
        let constant = operand
            .constant
            .map(|value| convert_constant(value, target, self.target, span))
            .transpose()?;
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::ExplicitCast {
                    kind,
                    source_type: source,
                    target_type: target,
                    operand: Box::new(operand.expr),
                },
                ty: target,
                span,
            },
            constant,
        })
    }
    fn call(&self, n: &str, args: &[AstExpr], span: Span) -> Result<Checked, Vec<Diagnostic>> {
        let Some(id) = self.names[self.module.0 as usize].get(n).copied() else {
            return Err(vec![Diagnostic::new(
                "E0212",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("unknown function `{n}`"),
                Some(span),
            )]);
        };
        self.call_id(id, n, args, span)
    }
    fn local_enum_id(&self, name: &str) -> Option<EnumId> {
        self.aliases[self.module.0 as usize]
            .get(name)
            .copied()
            .and_then(Type::as_enum)
            .or_else(|| self.enum_names[self.module.0 as usize].get(name).copied())
    }

    fn qualified_enum_id(
        &self,
        module: &str,
        name: &str,
        span: Span,
    ) -> Result<EnumId, Vec<Diagnostic>> {
        let ty = AstType {
            module: Some(module.into()),
            name: name.into(),
            span,
        };
        let resolved = resolve_type_in_module(
            &ty,
            self.module,
            self.aliases,
            self.struct_names,
            self.enum_names,
            self.imports,
            self.module_names,
        )
        .map_err(|diagnostic| vec![diagnostic])?;
        resolved.as_enum().ok_or_else(|| {
            vec![Diagnostic::new(
                "E0250",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!("`{module}.{name}` is not an enum"),
                Some(span),
            )]
        })
    }
    fn qualified_apply(
        &self,
        m: &str,
        f: &str,
        args: &[AstExpr],
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let Some(mid) = self.module_names.get(m).copied() else {
            return Err(vec![Diagnostic::new(
                "E0221",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("unknown module `{m}`"),
                Some(span),
            )]);
        };
        if self.imports[self.module.0 as usize].get(m) != Some(&mid) {
            return Err(vec![Diagnostic::new(
                "E0223",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("module `{m}` is not directly imported"),
                Some(span),
            )]);
        }
        if let Some(id) = self.names[mid.0 as usize].get(f).copied() {
            return self.call_id(id, &format!("{m}.{f}"), args, span);
        }
        if let Some(id) = self.struct_names[mid.0 as usize].get(f).copied() {
            return self.struct_init(id, &format!("{m}.{f}"), args, span);
        }
        if let Some(Type::Struct(id)) = self.aliases[mid.0 as usize].get(f).copied() {
            return self.struct_init(id, &format!("{m}.{f}"), args, span);
        }
        Err(vec![Diagnostic::new(
            "E0222",
            Phase::Semantic,
            DiagnosticCategory::Name,
            format!("unknown function or struct `{f}` in module `{m}`"),
            Some(span),
        )])
    }

    fn struct_init(
        &self,
        id: StructId,
        spelling: &str,
        args: &[AstExpr],
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let info = &self.structs[id.0 as usize];
        if args.len() != info.fields.len() {
            return Err(vec![Diagnostic::new(
                "E0246",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "struct `{spelling}` expects {} positional arguments, found {}",
                    info.fields.len(),
                    args.len()
                ),
                Some(span),
            )]);
        }
        let mut fields = Vec::with_capacity(args.len());
        for (index, (argument, field)) in args.iter().zip(&info.fields).enumerate() {
            match self.expression(argument, Some(field.ty)) {
                Ok(value) => fields.push((field.id, value.expr)),
                Err(mut diagnostics) => {
                    if let Some(diagnostic) = diagnostics.first_mut() {
                        diagnostic.code = "E0247";
                        diagnostic.message = format!(
                            "argument {} for field `{}` of `{spelling}` requires {}: {}",
                            index + 1,
                            field.name,
                            field.ty,
                            diagnostic.message
                        );
                    }
                    return Err(diagnostics);
                }
            }
        }
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::StructInit {
                    struct_id: id,
                    fields,
                },
                ty: Type::Struct(id),
                span,
            },
            constant: None,
        })
    }
    fn enum_init(
        &self,
        id: EnumId,
        variant_name: &str,
        args: &[AstExpr],
        parenthesized: bool,
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let info = &self.enums[id.0 as usize];
        let Some(variant_id) = self.variant_names[id.0 as usize].get(variant_name).copied() else {
            return Err(vec![Diagnostic::new(
                "E0252",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("unknown variant `{variant_name}` on enum `{}`", info.name),
                Some(span),
            )]);
        };
        let variant = &info.variants[variant_id.index as usize];
        if parenthesized == variant.payloads.is_empty() {
            return Err(vec![Diagnostic::new(
                "E0250",
                Phase::Semantic,
                DiagnosticCategory::Syntax,
                if parenthesized {
                    format!(
                        "payloadless variant `{}.{}` must be constructed without `()`",
                        info.name, variant.name
                    )
                } else {
                    format!(
                        "payload variant `{}.{}` requires parenthesized arguments",
                        info.name, variant.name
                    )
                },
                Some(span),
            )]);
        }
        if args.len() != variant.payloads.len() {
            return Err(vec![Diagnostic::new(
                "E0253",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "variant `{}.{}` expects {} payload arguments, found {}",
                    info.name,
                    variant.name,
                    variant.payloads.len(),
                    args.len()
                ),
                Some(span),
            )]);
        }
        let mut payloads = Vec::with_capacity(args.len());
        for (index, (argument, payload)) in args.iter().zip(&variant.payloads).enumerate() {
            match self.expression(argument, Some(payload.ty)) {
                Ok(value) => payloads.push(value.expr),
                Err(mut diagnostics) => {
                    if let Some(diagnostic) = diagnostics.first_mut() {
                        diagnostic.code = "E0254";
                        diagnostic.message = format!(
                            "payload {} of `{}.{}` requires {}: {}",
                            index + 1,
                            info.name,
                            variant.name,
                            payload.ty,
                            diagnostic.message
                        );
                    }
                    return Err(diagnostics);
                }
            }
        }
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::EnumInit {
                    enum_id: id,
                    variant_id,
                    payloads,
                },
                ty: Type::Enum(id),
                span,
            },
            constant: None,
        })
    }
    fn call_id(
        &self,
        id: FunctionId,
        name: &str,
        args: &[AstExpr],
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let s = &self.signatures[id.0 as usize];
        if args.len() != s.parameters.len() {
            return Err(vec![Diagnostic::new(
                "E0213",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "function `{name}` expects {} arguments, found {}",
                    s.parameters.len(),
                    args.len()
                ),
                Some(span),
            )]);
        }
        let mut out = vec![];
        for (index, (a, p)) in args.iter().zip(&s.parameters).enumerate() {
            match self.expression(a, Some(p.ty)) {
                Ok(x) => out.push(x.expr),
                Err(mut ds) => {
                    if let Some(d) = ds.first_mut() {
                        d.code = "E0214";
                        d.message = format!(
                            "argument {} to `{name}` requires {}: {}",
                            index + 1,
                            p.ty,
                            d.message
                        )
                    }
                    return Err(ds);
                }
            }
        }
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::Call {
                    callee: id,
                    args: out,
                },
                ty: s.return_type,
                span,
            },
            constant: None,
        })
    }
    fn binary(
        &self,
        op: AstBinaryOp,
        la: &AstExpr,
        ra: &AstExpr,
        expected: Option<Type>,
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let ll = literal(la);
        let rl = literal(ra);
        let (l, r) = if ll && !rl {
            let r = self.expression(ra, None)?;
            (self.expression(la, Some(r.expr.ty))?, r)
        } else if rl && !ll {
            let l = self.expression(la, None)?;
            let r = self.expression(ra, Some(l.expr.ty))?;
            (l, r)
        } else if ll && rl {
            let c = expected.filter(|t| t.is_numeric());
            (self.expression(la, c)?, self.expression(ra, c)?)
        } else {
            (self.expression(la, None)?, self.expression(ra, None)?)
        };
        let equality = matches!(op, AstBinaryOp::Equal | AstBinaryOp::NotEqual);
        if l.expr.ty == Type::Bool || r.expr.ty == Type::Bool {
            if l.expr.ty == Type::Bool && r.expr.ty == Type::Bool && equality {
                return Ok(bin_result(op, l, r, Type::Bool, None));
            }
            return Err(vec![type_error(
                "bool cannot be used numerically or compared with a number",
                span,
            )]);
        }
        if l.expr.ty.as_struct().is_some() || r.expr.ty.as_struct().is_some() {
            return Err(vec![type_error(
                "struct values do not have implicit arithmetic or equality operators in Vertical-5",
                span,
            )]);
        }
        let common = common(l.expr.ty, r.expr.ty)
            .ok_or_else(|| vec![conversion_error(l.expr.ty, r.expr.ty, span)])?;
        let l = self.coerce(l, Some(common))?;
        let r = self.coerce(r, Some(common))?;
        if matches!(op, AstBinaryOp::Remainder) && common.as_float().is_some() {
            return Err(vec![Diagnostic::new(
                "E0235",
                Phase::Semantic,
                DiagnosticCategory::Division,
                "floating `%` is not supported; `%` is the integer remainder operator",
                Some(span),
            )]);
        }
        let arithmetic = matches!(
            op,
            AstBinaryOp::Add
                | AstBinaryOp::Subtract
                | AstBinaryOp::Multiply
                | AstBinaryOp::Divide
                | AstBinaryOp::Remainder
        );
        let result = if arithmetic { common } else { Type::Bool };
        let known_integer = common.as_integer().is_some()
            && arithmetic
            && l.constant.is_some()
            && r.constant.is_some();
        let constant = if let Some(integer) = common.as_integer() {
            const_bin(op, l.constant, r.constant, integer, span, self.target)?
        } else {
            None
        };
        if known_integer && constant.is_none() {
            return Err(vec![Diagnostic::new(
                "E0210",
                Phase::Semantic,
                DiagnosticCategory::Integer,
                format!("constant integer expression overflows {common}"),
                Some(span),
            )]);
        }
        if let Some(ConstantValue::Integer(v)) = constant {
            check_value(v, common, span, self.target)?
        }
        Ok(bin_result(op, l, r, result, constant))
    }
    fn coerce(&self, c: Checked, expected: Option<Type>) -> Result<Checked, Vec<Diagnostic>> {
        let Some(to) = expected else { return Ok(c) };
        if c.expr.ty == to {
            return Ok(c);
        }
        let kind = match (c.expr.ty, to) {
            (Type::Integer(a), Type::Integer(b)) if a.can_widen_to(b) => {
                if a.is_signed() {
                    CoercionKind::SignExtend
                } else {
                    CoercionKind::ZeroExtend
                }
            }
            (Type::Float(FloatType::Float32), Type::Float(FloatType::Float64)) => {
                CoercionKind::FloatExtend
            }
            _ => return Err(vec![conversion_error(c.expr.ty, to, c.expr.span)]),
        };
        let span = c.expr.span;
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::Coerce {
                    kind,
                    operand: Box::new(c.expr),
                },
                ty: to,
                span,
            },
            constant: c.constant,
        })
    }
    fn lookup(&self, n: &str) -> Option<LocalId> {
        self.scopes.iter().rev().find_map(|s| s.get(n).copied())
    }
}

fn literal(e: &AstExpr) -> bool {
    matches!(e.kind, AstExprKind::Integer(_) | AstExprKind::Float(_))
        || matches!(&e.kind,AstExprKind::Unary{operand,..}if matches!(operand.kind,AstExprKind::Integer(_)|AstExprKind::Float(_)))
}
fn common(a: Type, b: Type) -> Option<Type> {
    if a == b {
        return Some(a);
    }
    match (a, b) {
        (Type::Integer(x), Type::Integer(y)) if x.can_widen_to(y) => Some(b),
        (Type::Integer(x), Type::Integer(y)) if y.can_widen_to(x) => Some(a),
        (Type::Float(FloatType::Float32), Type::Float(FloatType::Float64)) => Some(b),
        (Type::Float(FloatType::Float64), Type::Float(FloatType::Float32)) => Some(a),
        _ => None,
    }
}
fn select_cast_kind(from: Type, to: Type, target: TargetProperties) -> Option<CastKind> {
    Some(match (from, to) {
        (a, b) if a == b => CastKind::Identity,
        (Type::Integer(a), Type::Integer(b)) if a.is_signed() != b.is_signed() => {
            CastKind::IntegerSignednessChecked
        }
        (Type::Integer(a), Type::Integer(b)) => match a.bits(target).cmp(&b.bits(target)) {
            std::cmp::Ordering::Less if a.is_signed() => CastKind::IntegerExtendSigned,
            std::cmp::Ordering::Less => CastKind::IntegerExtendUnsigned,
            std::cmp::Ordering::Equal => CastKind::IntegerReencode,
            std::cmp::Ordering::Greater => CastKind::IntegerNarrowChecked,
        },
        (Type::Integer(a), Type::Float(_)) if a.is_signed() => CastKind::SignedIntegerToFloat,
        (Type::Integer(_), Type::Float(_)) => CastKind::UnsignedIntegerToFloat,
        (Type::Float(_), Type::Integer(b)) if b.is_signed() => {
            CastKind::FloatToSignedIntegerChecked
        }
        (Type::Float(_), Type::Integer(_)) => CastKind::FloatToUnsignedIntegerChecked,
        (Type::Float(FloatType::Float32), Type::Float(FloatType::Float64)) => CastKind::FloatExtend,
        (Type::Float(FloatType::Float64), Type::Float(FloatType::Float32)) => {
            CastKind::FloatTruncate
        }
        _ => return None,
    })
}

fn convert_constant(
    value: ConstantValue,
    target: Type,
    properties: TargetProperties,
    span: Span,
) -> Result<ConstantValue, Vec<Diagnostic>> {
    match (value, target) {
        (ConstantValue::Integer(value), Type::Integer(integer)) => {
            let (min, max) = integer.range(properties);
            if value < min || value > max {
                return Err(vec![cast_range(value.to_string(), target, span)]);
            }
            Ok(ConstantValue::Integer(value))
        }
        (ConstantValue::Integer(value), Type::Float(FloatType::Float32)) => Ok(
            ConstantValue::Float(FloatValue::Float32((value as f32).to_bits())),
        ),
        (ConstantValue::Integer(value), Type::Float(FloatType::Float64)) => Ok(
            ConstantValue::Float(FloatValue::Float64((value as f64).to_bits())),
        ),
        (ConstantValue::Float(value), Type::Integer(integer)) => {
            let number = float_as_f64(value);
            let (min, max) = integer.range(properties);
            let lower_ok = if integer.is_signed() {
                let min_float = integer_boundary_as_f64(value, min);
                let below = integer_boundary_as_f64(value, min - 1);
                if below == min_float {
                    number >= min_float
                } else {
                    number > below
                }
            } else {
                number > -1.0
            };
            let upper_exclusive = integer_boundary_as_f64(value, max + 1);
            if !number.is_finite() || !lower_ok || number >= upper_exclusive {
                return Err(vec![cast_range(format_float(value), target, span)]);
            }
            Ok(ConstantValue::Integer(number.trunc() as i128))
        }
        (ConstantValue::Float(value), Type::Float(FloatType::Float32)) => Ok(ConstantValue::Float(
            FloatValue::Float32((float_as_f64(value) as f32).to_bits()),
        )),
        (ConstantValue::Float(value), Type::Float(FloatType::Float64)) => Ok(ConstantValue::Float(
            FloatValue::Float64(float_as_f64(value).to_bits()),
        )),
        _ => unreachable!("bool conversions are rejected before constant conversion"),
    }
}

fn float_as_f64(value: FloatValue) -> f64 {
    match value {
        FloatValue::Float32(bits) => f64::from(f32::from_bits(bits)),
        FloatValue::Float64(bits) => f64::from_bits(bits),
    }
}

fn integer_boundary_as_f64(source: FloatValue, value: i128) -> f64 {
    match source {
        FloatValue::Float32(_) => f64::from(value as f32),
        FloatValue::Float64(_) => value as f64,
    }
}

fn format_float(value: FloatValue) -> String {
    match value {
        FloatValue::Float32(bits) => f32::from_bits(bits).to_string(),
        FloatValue::Float64(bits) => f64::from_bits(bits).to_string(),
    }
}

fn cast_range(value: impl std::fmt::Display, target: Type, span: Span) -> Diagnostic {
    Diagnostic::new(
        "E0231",
        Phase::Semantic,
        DiagnosticCategory::Conversion,
        format!("constant value `{value}` is outside the representable range of {target}"),
        Some(span),
    )
}
fn bin_result(
    aop: AstBinaryOp,
    l: Checked,
    r: Checked,
    ty: Type,
    constant: Option<ConstantValue>,
) -> Checked {
    let float = l.expr.ty.as_float().is_some();
    let op = match aop {
        AstBinaryOp::Add if float => HirBinaryOp::AddFloat,
        AstBinaryOp::Subtract if float => HirBinaryOp::SubtractFloat,
        AstBinaryOp::Multiply if float => HirBinaryOp::MultiplyFloat,
        AstBinaryOp::Divide if float => HirBinaryOp::DivideFloat,
        AstBinaryOp::Add => HirBinaryOp::AddIntegerChecked,
        AstBinaryOp::Subtract => HirBinaryOp::SubtractIntegerChecked,
        AstBinaryOp::Multiply => HirBinaryOp::MultiplyIntegerChecked,
        AstBinaryOp::Divide => {
            if l.expr.ty.as_integer().unwrap().is_signed() {
                HirBinaryOp::DivideIntegerSignedChecked
            } else {
                HirBinaryOp::DivideIntegerUnsignedChecked
            }
        }
        AstBinaryOp::Remainder => {
            if l.expr.ty.as_integer().unwrap().is_signed() {
                HirBinaryOp::RemainderIntegerSignedChecked
            } else {
                HirBinaryOp::RemainderIntegerUnsignedChecked
            }
        }
        AstBinaryOp::Less => HirBinaryOp::Less,
        AstBinaryOp::LessEqual => HirBinaryOp::LessEqual,
        AstBinaryOp::Greater => HirBinaryOp::Greater,
        AstBinaryOp::GreaterEqual => HirBinaryOp::GreaterEqual,
        AstBinaryOp::Equal => HirBinaryOp::Equal,
        AstBinaryOp::NotEqual => HirBinaryOp::NotEqual,
    };
    let span = l.expr.span.through(r.expr.span);
    Checked {
        expr: HirExpr {
            kind: HirExprKind::Binary {
                op,
                left: Box::new(l.expr),
                right: Box::new(r.expr),
            },
            ty,
            span,
        },
        constant,
    }
}
fn const_bin(
    op: AstBinaryOp,
    a: Option<ConstantValue>,
    b: Option<ConstantValue>,
    ty: IntegerType,
    span: Span,
    target: TargetProperties,
) -> Result<Option<ConstantValue>, Vec<Diagnostic>> {
    let (Some(ConstantValue::Integer(a)), Some(ConstantValue::Integer(b))) = (a, b) else {
        return Ok(None);
    };
    let value = match op {
        AstBinaryOp::Add => a.checked_add(b),
        AstBinaryOp::Subtract => a.checked_sub(b),
        AstBinaryOp::Multiply => a.checked_mul(b),
        AstBinaryOp::Divide | AstBinaryOp::Remainder if b == 0 => {
            return Err(vec![Diagnostic::new(
                "E0233",
                Phase::Semantic,
                DiagnosticCategory::Division,
                "constant integer division or remainder by zero",
                Some(span),
            )]);
        }
        AstBinaryOp::Divide if ty.is_signed() && a == ty.range(target).0 && b == -1 => {
            return Err(vec![Diagnostic::new(
                "E0234",
                Phase::Semantic,
                DiagnosticCategory::Division,
                format!("constant signed division overflows {ty}: MIN / -1"),
                Some(span),
            )]);
        }
        AstBinaryOp::Divide => a.checked_div(b),
        AstBinaryOp::Remainder if ty.is_signed() && a == ty.range(target).0 && b == -1 => Some(0),
        AstBinaryOp::Remainder => a.checked_rem(b),
        _ => return Ok(None),
    };
    Ok(value.map(ConstantValue::Integer))
}
fn builtin(n: &str) -> Option<Type> {
    use IntegerType::*;
    Some(match n {
        "bool" => Type::Bool,
        "int8" => Type::Integer(Int8),
        "int16" => Type::Integer(Int16),
        "int32" => Type::Integer(Int32),
        "int64" | "int" => Type::Integer(Int64),
        "uint8" | "byte" => Type::Integer(Uint8),
        "uint16" => Type::Integer(Uint16),
        "uint32" => Type::Integer(Uint32),
        "uint64" => Type::Integer(Uint64),
        "isize" => Type::Integer(Isize),
        "usize" => Type::Integer(Usize),
        "float32" | "float" => Type::Float(FloatType::Float32),
        "float64" | "double" => Type::Float(FloatType::Float64),
        _ => return None,
    })
}
fn unknown_type(t: &AstType) -> Diagnostic {
    Diagnostic::new(
        "E0204",
        Phase::Semantic,
        DiagnosticCategory::Type,
        format!("unknown type `{}`", t.name),
        Some(t.span),
    )
}
fn duplicate(k: &str, n: &str, s: Span) -> Diagnostic {
    Diagnostic::new(
        "E0203",
        Phase::Semantic,
        DiagnosticCategory::Name,
        format!("{k} `{n}` is already declared"),
        Some(s),
    )
}
fn unknown_name(n: &str, s: Span) -> Diagnostic {
    Diagnostic::new(
        "E0202",
        Phase::Semantic,
        DiagnosticCategory::Name,
        format!("unknown identifier `{n}`"),
        Some(s),
    )
}
fn type_error(m: impl Into<String>, s: Span) -> Diagnostic {
    Diagnostic::new(
        "E0205",
        Phase::Semantic,
        DiagnosticCategory::Type,
        m,
        Some(s),
    )
}
fn conversion_error(a: Type, b: Type, s: Span) -> Diagnostic {
    let detail = match (a, b) {
        (Type::Integer(x), Type::Integer(y)) if x.is_signed() != y.is_signed() => {
            "mixed signed/unsigned operation"
        }
        (Type::Integer(_), Type::Integer(_)) | (Type::Float(_), Type::Float(_)) => {
            "unsupported narrowing"
        }
        (Type::Bool, _) | (_, Type::Bool) => "bool has no numeric conversions",
        _ => "integer/float conversion is not implicit",
    };
    let code = if matches!(a, Type::Bool) || matches!(b, Type::Bool) {
        "E0205"
    } else {
        "E0218"
    };
    Diagnostic::new(
        code,
        Phase::Semantic,
        DiagnosticCategory::Type,
        format!("invalid implicit conversion from {a} to {b}: {detail}"),
        Some(s),
    )
}
fn range(text: &str, ty: Type, s: Span, t: TargetProperties) -> Diagnostic {
    let (min, max) = ty.as_integer().unwrap_or(IntegerType::Int64).range(t);
    Diagnostic::new(
        "E0209",
        Phase::Semantic,
        DiagnosticCategory::Integer,
        format!("integer literal `{text}` is outside {ty} range [{min}, {max}]"),
        Some(s),
    )
}
fn check_value(v: i128, ty: Type, s: Span, t: TargetProperties) -> Result<(), Vec<Diagnostic>> {
    let (min, max) = ty.as_integer().unwrap().range(t);
    if v < min || v > max {
        Err(vec![Diagnostic::new(
            "E0210",
            Phase::Semantic,
            DiagnosticCategory::Integer,
            format!("constant integer expression overflows {ty}"),
            Some(s),
        )])
    } else {
        Ok(())
    }
}
fn validate_program(p: &ParsedProgram) -> Result<(), Vec<Diagnostic>> {
    let fail = |m| {
        vec![Diagnostic::new(
            "E0220",
            Phase::Semantic,
            DiagnosticCategory::Name,
            m,
            None,
        )]
    };
    if p.modules.is_empty() || p.entry.0 as usize >= p.modules.len() {
        return Err(fail("module graph has no valid entry module"));
    }
    let mut names = BTreeSet::new();
    let mut sources = BTreeSet::new();
    for (i, m) in p.modules.iter().enumerate() {
        if m.info.id.0 as usize != i
            || !names.insert(&m.info.name)
            || !sources.insert(m.info.source)
        {
            return Err(fail("duplicate or non-canonical module/source identity"));
        }
        let mut imports = BTreeSet::new();
        for x in &m.info.imports {
            if x.module.0 as usize >= p.modules.len()
                || p.modules[x.module.0 as usize].info.name != x.name
                || !imports.insert(&x.name)
            {
                return Err(vec![
                    Diagnostic::new(
                        "E0220",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!("duplicate or invalid import `{}`", x.name),
                        Some(x.span),
                    )
                    .with_source_name(&m.info.source_name),
                ]);
            }
        }
    }
    Ok(())
}

pub fn verify_hir(h: &TypedHir) -> Result<(), Vec<Diagnostic>> {
    let fail = |m: String| {
        vec![Diagnostic::new(
            "E0290",
            Phase::Semantic,
            DiagnosticCategory::Verification,
            m,
            None,
        )]
    };
    if h.modules.is_empty()
        || h.entry.0 as usize >= h.signatures.len()
        || h.functions.len() != h.signatures.len()
    {
        return Err(fail("HIR cardinality invalid".into()));
    }
    let e = &h.signatures[h.entry.0 as usize];
    if e.name != "main" || e.return_type != Type::INT64 || !e.parameters.is_empty() {
        return Err(fail("HIR entry invalid".into()));
    }
    let mut next_field = 0_u32;
    for (index, info) in h.structs.iter().enumerate() {
        if info.id.0 as usize != index || info.layout.align == 0 {
            return Err(fail("HIR struct identity/layout invalid".into()));
        }
        for (field_index, field) in info.fields.iter().enumerate() {
            if field.id.0 != next_field
                || field.owner != info.id
                || field.index as usize != field_index
            {
                return Err(fail("HIR field identity invalid".into()));
            }
            next_field += 1;
        }
    }
    for (index, info) in h.enums.iter().enumerate() {
        if info.id.0 as usize != index || info.layout.align == 0 || info.variants.is_empty() {
            return Err(fail("HIR enum identity/layout invalid".into()));
        }
        for (variant_index, variant) in info.variants.iter().enumerate() {
            if variant.id
                != (VariantId {
                    enum_id: info.id,
                    index: variant_index as u32,
                })
                || variant.owner != info.id
                || variant.index as usize != variant_index
                || variant.discriminant != variant.index
            {
                return Err(fail("HIR variant identity invalid".into()));
            }
            for (payload_index, payload) in variant.payloads.iter().enumerate() {
                if payload.index as usize != payload_index {
                    return Err(fail("HIR variant payload identity invalid".into()));
                }
            }
        }
    }
    for (i, (s, f)) in h.signatures.iter().zip(&h.functions).enumerate() {
        if s.id.0 as usize != i || f.id != s.id || f.module != s.module {
            return Err(fail("HIR function identity mismatch".into()));
        }
        for (j, l) in f.locals.iter().enumerate() {
            if l.id.0 as usize != j {
                return Err(fail("HIR local identity invalid".into()));
            }
        }
        verify_block(
            &f.body,
            f,
            s.return_type,
            &h.signatures,
            &h.structs,
            &h.enums,
            &fail,
        )?
    }
    Ok(())
}
fn verify_block(
    b: &HirBlock,
    f: &HirFunction,
    ret: Type,
    sigs: &[FunctionSignature],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    for s in &b.statements {
        match &s.kind {
            HirStmtKind::Local { local, initializer } => {
                verify_expr(initializer, f, sigs, structs, enums, fail)?;
                if f.locals.get(local.0 as usize).map(|l| l.ty) != Some(initializer.ty) {
                    return Err(fail("HIR assignment mismatch".into()));
                }
            }
            HirStmtKind::Assign { place, value } => {
                verify_expr(value, f, sigs, structs, enums, fail)?;
                verify_place(place, f, structs, fail)?;
                if place.ty != value.ty {
                    return Err(fail("HIR field assignment mismatch".into()));
                }
            }
            HirStmtKind::If {
                condition,
                then_block,
                else_block,
            } => {
                verify_expr(condition, f, sigs, structs, enums, fail)?;
                if condition.ty != Type::Bool {
                    return Err(fail("HIR condition not bool".into()));
                }
                verify_block(then_block, f, ret, sigs, structs, enums, fail)?;
                if let Some(x) = else_block {
                    verify_block(x, f, ret, sigs, structs, enums, fail)?
                }
            }
            HirStmtKind::While { condition, body } => {
                verify_expr(condition, f, sigs, structs, enums, fail)?;
                if condition.ty != Type::Bool {
                    return Err(fail("HIR condition not bool".into()));
                }
                verify_block(body, f, ret, sigs, structs, enums, fail)?
            }
            HirStmtKind::Match {
                scrutinee,
                enum_id,
                arms,
            } => {
                verify_expr(scrutinee, f, sigs, structs, enums, fail)?;
                let Some(info) = enums
                    .get(enum_id.0 as usize)
                    .filter(|info| info.id == *enum_id)
                else {
                    return Err(fail("HIR match has unknown enum".into()));
                };
                if scrutinee.ty != Type::Enum(*enum_id) || arms.len() != info.variants.len() {
                    return Err(fail("HIR match type/exhaustiveness invalid".into()));
                }
                let mut seen = BTreeSet::new();
                for arm in arms {
                    let Some(variant) = info
                        .variants
                        .get(arm.variant_id.index as usize)
                        .filter(|variant| variant.id == arm.variant_id)
                    else {
                        return Err(fail("HIR match variant does not belong to enum".into()));
                    };
                    if !seen.insert(arm.variant_id) || arm.bindings.len() != variant.payloads.len()
                    {
                        return Err(fail(
                            "HIR match variant duplication/binding arity invalid".into(),
                        ));
                    }
                    for (binding, payload) in arm.bindings.iter().zip(&variant.payloads) {
                        if binding.payload_index != payload.index
                            || binding.ty != payload.ty
                            || f.locals.get(binding.local.0 as usize).map(|local| local.ty)
                                != Some(payload.ty)
                        {
                            return Err(fail("HIR match payload binding invalid".into()));
                        }
                    }
                    verify_block(&arm.body, f, ret, sigs, structs, enums, fail)?;
                }
            }
            HirStmtKind::Return(v) => {
                verify_expr(v, f, sigs, structs, enums, fail)?;
                if v.ty != ret {
                    return Err(fail("HIR return mismatch".into()));
                }
            }
        }
    }
    Ok(())
}
fn verify_expr(
    e: &HirExpr,
    f: &HirFunction,
    sigs: &[FunctionSignature],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    match &e.kind {
        HirExprKind::Int(_) if e.ty.as_integer().is_none() => {
            return Err(fail("HIR integer literal mismatch".into()));
        }
        HirExprKind::Float(FloatValue::Float32(_)) if e.ty != Type::Float(FloatType::Float32) => {
            return Err(fail("HIR float32 mismatch".into()));
        }
        HirExprKind::Float(FloatValue::Float64(_)) if e.ty != Type::Float(FloatType::Float64) => {
            return Err(fail("HIR float64 mismatch".into()));
        }
        HirExprKind::Bool(_) if e.ty != Type::Bool => return Err(fail("HIR bool mismatch".into())),
        HirExprKind::Local(l) if f.locals.get(l.0 as usize).map(|x| x.ty) != Some(e.ty) => {
            return Err(fail("HIR local mismatch".into()));
        }
        HirExprKind::Load(place) => {
            verify_place(place, f, structs, fail)?;
            if place.ty != e.ty {
                return Err(fail("HIR load/place type mismatch".into()));
            }
        }
        HirExprKind::Call { callee, args } => {
            let Some(s) = sigs.get(callee.0 as usize) else {
                return Err(fail("HIR callee missing".into()));
            };
            if s.return_type != e.ty || args.len() != s.parameters.len() {
                return Err(fail("HIR call mismatch".into()));
            }
            for (a, p) in args.iter().zip(&s.parameters) {
                verify_expr(a, f, sigs, structs, enums, fail)?;
                if a.ty != p.ty {
                    return Err(fail("HIR argument mismatch".into()));
                }
            }
        }
        HirExprKind::StructInit { struct_id, fields } => {
            let Some(info) = structs
                .get(struct_id.0 as usize)
                .filter(|info| info.id == *struct_id)
            else {
                return Err(fail("HIR struct initializer has unknown identity".into()));
            };
            if e.ty != Type::Struct(*struct_id) || fields.len() != info.fields.len() {
                return Err(fail("HIR struct initializer arity/type mismatch".into()));
            }
            for ((field_id, value), declared) in fields.iter().zip(&info.fields) {
                verify_expr(value, f, sigs, structs, enums, fail)?;
                if *field_id != declared.id || value.ty != declared.ty {
                    return Err(fail("HIR struct initializer field mismatch".into()));
                }
            }
        }
        HirExprKind::EnumInit {
            enum_id,
            variant_id,
            payloads,
        } => {
            let Some(info) = enums
                .get(enum_id.0 as usize)
                .filter(|info| info.id == *enum_id)
            else {
                return Err(fail("HIR enum initializer has unknown identity".into()));
            };
            let Some(variant) = info
                .variants
                .get(variant_id.index as usize)
                .filter(|variant| variant.id == *variant_id)
            else {
                return Err(fail("HIR enum initializer variant mismatch".into()));
            };
            if e.ty != Type::Enum(*enum_id) || payloads.len() != variant.payloads.len() {
                return Err(fail("HIR enum initializer arity/type mismatch".into()));
            }
            for (value, declared) in payloads.iter().zip(&variant.payloads) {
                verify_expr(value, f, sigs, structs, enums, fail)?;
                if value.ty != declared.ty {
                    return Err(fail("HIR enum initializer payload mismatch".into()));
                }
            }
        }
        HirExprKind::Coerce { kind, operand } => {
            verify_expr(operand, f, sigs, structs, enums, fail)?;
            let ok = match (kind, operand.ty, e.ty) {
                (CoercionKind::SignExtend, Type::Integer(a), Type::Integer(b)) => {
                    a.is_signed() && a.can_widen_to(b)
                }
                (CoercionKind::ZeroExtend, Type::Integer(a), Type::Integer(b)) => {
                    !a.is_signed() && a.can_widen_to(b)
                }
                (
                    CoercionKind::FloatExtend,
                    Type::Float(FloatType::Float32),
                    Type::Float(FloatType::Float64),
                ) => true,
                _ => false,
            };
            if !ok {
                return Err(fail("HIR coercion invalid".into()));
            }
        }
        HirExprKind::ExplicitCast {
            kind,
            source_type,
            target_type,
            operand,
        } => {
            verify_expr(operand, f, sigs, structs, enums, fail)?;
            if operand.ty != *source_type
                || e.ty != *target_type
                || select_cast_kind(*source_type, *target_type, TargetProperties::LINUX_X86_64)
                    != Some(*kind)
            {
                return Err(fail("HIR explicit cast contract invalid".into()));
            }
        }
        HirExprKind::Unary { op, operand } => {
            verify_expr(operand, f, sigs, structs, enums, fail)?;
            let ok = match op {
                HirUnaryOp::NegateIntegerChecked => {
                    operand.ty.as_integer().is_some_and(IntegerType::is_signed)
                }
                HirUnaryOp::NegateFloat => operand.ty.as_float().is_some(),
            } && e.ty == operand.ty;
            if !ok {
                return Err(fail("HIR unary invalid".into()));
            }
        }
        HirExprKind::Binary { op, left, right } => {
            verify_expr(left, f, sigs, structs, enums, fail)?;
            verify_expr(right, f, sigs, structs, enums, fail)?;
            if left.ty != right.ty {
                return Err(fail("HIR binary operand mismatch".into()));
            }
            let ok = match op {
                HirBinaryOp::AddIntegerChecked
                | HirBinaryOp::SubtractIntegerChecked
                | HirBinaryOp::MultiplyIntegerChecked => {
                    left.ty.as_integer().is_some() && e.ty == left.ty
                }
                HirBinaryOp::DivideIntegerSignedChecked
                | HirBinaryOp::RemainderIntegerSignedChecked => {
                    left.ty.as_integer().is_some_and(IntegerType::is_signed) && e.ty == left.ty
                }
                HirBinaryOp::DivideIntegerUnsignedChecked
                | HirBinaryOp::RemainderIntegerUnsignedChecked => {
                    left.ty
                        .as_integer()
                        .is_some_and(|integer| !integer.is_signed())
                        && e.ty == left.ty
                }
                HirBinaryOp::AddFloat
                | HirBinaryOp::SubtractFloat
                | HirBinaryOp::MultiplyFloat
                | HirBinaryOp::DivideFloat => left.ty.as_float().is_some() && e.ty == left.ty,
                HirBinaryOp::Less
                | HirBinaryOp::LessEqual
                | HirBinaryOp::Greater
                | HirBinaryOp::GreaterEqual => left.ty.is_numeric() && e.ty == Type::Bool,
                HirBinaryOp::Equal | HirBinaryOp::NotEqual => {
                    (left.ty == Type::Bool || left.ty.is_numeric()) && e.ty == Type::Bool
                }
            };
            if !ok {
                return Err(fail("HIR binary invalid".into()));
            }
        }
        _ => {}
    }
    Ok(())
}

fn verify_place(
    place: &HirPlace,
    function: &HirFunction,
    structs: &[StructInfo],
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    let Some(local) = function.locals.get(place.local.0 as usize) else {
        return Err(fail("HIR place has unknown local".into()));
    };
    let mut ty = local.ty;
    for field_id in &place.projections {
        let Some(owner) = ty.as_struct() else {
            return Err(fail("HIR place projects a non-struct".into()));
        };
        let Some(field) = structs
            .get(owner.0 as usize)
            .and_then(|info| info.fields.iter().find(|field| field.id == *field_id))
        else {
            return Err(fail("HIR place field does not belong to struct".into()));
        };
        ty = field.ty;
    }
    if ty != place.ty {
        return Err(fail("HIR place cached type is invalid".into()));
    }
    Ok(())
}
fn statement_returns(s: &HirStmt) -> bool {
    match &s.kind {
        HirStmtKind::Return(_) => true,
        HirStmtKind::If {
            then_block,
            else_block: Some(e),
            ..
        } => definitely_returns(then_block) && definitely_returns(e),
        HirStmtKind::Match { arms, .. } => {
            !arms.is_empty() && arms.iter().all(|arm| definitely_returns(&arm.body))
        }
        _ => false,
    }
}
fn definitely_returns(b: &HirBlock) -> bool {
    b.statements.last().is_some_and(statement_returns)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{SourceFile, parse_source};
    fn check(s: &str) -> Result<TypedHir, Vec<Diagnostic>> {
        analyze(parse_source(&SourceFile::new("test.ae", s)).unwrap())
    }
    #[test]
    fn scalar_aliases() {
        let h=check("alias Small=int8;int64 widen(Small x){return x;}int main(){Small x=-128;uint8 y=255;float32 f=1.5;float64 g=f+2.0;return widen(x);}").unwrap();
        assert_eq!(h.aliases()[0].canonical, Type::Integer(IntegerType::Int8));
    }
    #[test]
    fn failures() {
        assert_eq!(
            check("alias A=B;alias B=A;int main(){return 0;}").unwrap_err()[0].code,
            "E0226"
        );
        assert_eq!(
            check("int main(){int8 x=128;return x;}").unwrap_err()[0].code,
            "E0209"
        );
    }
    #[test]
    fn recursion() {
        check("int fact(int n){if(n<=1){return 1;}return n*fact(n-1);}int main(){return fact(5);}")
            .unwrap();
    }
    #[test]
    fn explicit_scalar_casts_are_typed_and_constant_checked() {
        let hir = check("alias Tiny=int8;int main(){int64 x=127;Tiny y=Tiny(x);uint16 u=uint16(y);float64 f=double(u);return int32(f);}").unwrap();
        let dump = hir.dump();
        assert!(dump.contains("ExplicitCast"));
        assert!(dump.contains("source_type"));
        assert!(dump.contains("target_type"));
        check("int main(){uint64 x=uint64(18446744073709551615);return 0;}").unwrap();
        check("int main(){return int8(-128.9);}").unwrap();

        for (source, code) in [
            ("int main(){return int8(128);}", "E0231"),
            ("int main(){return uint32(-1);}", "E0231"),
            ("int main(){return int8(-129.0);}", "E0231"),
            ("int main(){return int(true);}", "E0232"),
            ("int main(){return bool(1);}", "E0232"),
            ("int main(){return int32(1.0,2.0);}", "E0230"),
        ] {
            assert_eq!(check(source).unwrap_err()[0].code, code, "{source}");
        }
    }
    #[test]
    fn division_and_remainder_constants_follow_v1_rules() {
        check("int main(){if(-5/2==-2){if(-5%2==-1){return 42;}}return 0;}").unwrap();
        check("int main(){int8 a=7;int16 b=2;return a/b;}").unwrap();
        check("int main(){float32 a=5.0;float64 b=2.0;float64 c=a/b;return int(c);}").unwrap();
        for (source, code) in [
            ("int main(){return 1/0;}", "E0233"),
            ("int main(){return -9223372036854775808/-1;}", "E0234"),
            ("int main(){return int(4.0%2.0);}", "E0235"),
        ] {
            assert_eq!(check(source).unwrap_err()[0].code, code, "{source}");
        }
        check("int main(){return -9223372036854775808%-1;}").unwrap();
    }

    #[test]
    fn nominal_structs_resolve_and_hir_verifies_field_identity() {
        let hir =
            check("struct P{int x;float64 y;}alias A=P;int main(){A p=A(1,2.0);p.x=3;return p.x;}")
                .unwrap();
        assert_eq!(hir.structs[0].layout, TypeLayout { size: 16, align: 8 });
        assert!(hir.dump().contains("StructInit"));

        let mut corrupt = hir;
        let initializer = corrupt.functions[0]
            .body
            .statements
            .iter_mut()
            .find_map(|statement| match &mut statement.kind {
                HirStmtKind::Local { initializer, .. } => Some(initializer),
                _ => None,
            })
            .unwrap();
        if let HirExprKind::StructInit { fields, .. } = &mut initializer.kind {
            fields[0].0 = FieldId(999);
        }
        assert!(verify_hir(&corrupt).is_err());
    }
}
