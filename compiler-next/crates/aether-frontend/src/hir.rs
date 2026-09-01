//! Alias-canonicalized and fully typed scalar HIR.
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
    AstBinaryOp, AstBlock, AstExpr, AstExprKind, AstFunction, AstStmtKind, AstType, AstUnaryOp,
    Diagnostic, DiagnosticCategory, FloatType, IntegerType, ParsedAst, Phase, SourceId, Span,
    TargetProperties, Type,
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

#[derive(Clone, Debug)]
pub struct DeclaredProgram {
    program: ParsedProgram,
    signatures: Vec<FunctionSignature>,
    names: Vec<BTreeMap<String, FunctionId>>,
    imports: Vec<BTreeMap<String, ModuleId>>,
    module_names: BTreeMap<String, ModuleId>,
    aliases: Vec<BTreeMap<String, Type>>,
    alias_info: Vec<TypeAliasInfo>,
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
            "entry: {:#?}\nmodules: {:#?}\naliases (transparent -> canonical): {:#?}\nsignatures: {:#?}",
            self.entry, self.modules, self.aliases, self.signatures
        );
        for m in &self.modules {
            let f: Vec<_> = self.functions.iter().filter(|f| f.module == m.id).collect();
            write!(d, "\nmodule {:?} `{}` functions: {f:#?}", m.id, m.name).unwrap();
        }
        d
    }
    #[must_use]
    pub fn into_parts(
        self,
    ) -> (
        Vec<ModuleInfo>,
        Vec<FunctionSignature>,
        Vec<HirFunction>,
        FunctionId,
    ) {
        (self.modules, self.signatures, self.functions, self.entry)
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
        local: LocalId,
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
    Return(HirExpr),
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
    Call {
        callee: FunctionId,
        args: Vec<HirExpr>,
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
    let mut aliases = vec![BTreeMap::new(); program.modules.len()];
    let mut alias_info = vec![];
    for module in &program.modules {
        let mut declarations = BTreeMap::new();
        for a in module.ast.aliases() {
            if builtin(&a.name).is_some()
                || declarations.insert(a.name.clone(), a).is_some()
                || module.ast.functions().iter().any(|f| f.name == a.name)
            {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0225",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!("duplicate alias or declaration name `{}`", a.name),
                        Some(a.span),
                    ),
                    module,
                )]);
            }
        }
        let mut state = BTreeMap::new();
        for name in declarations.keys() {
            resolve_alias(
                name,
                module,
                &declarations,
                &mut state,
                &mut aliases[module.info.id.0 as usize],
                &mut alias_info,
            )?;
        }
    }
    let mut signatures = vec![];
    let mut names = vec![BTreeMap::new(); program.modules.len()];
    for module in &program.modules {
        for f in module.ast.functions() {
            let id = FunctionId(signatures.len() as u32);
            if builtin(&f.name).is_some()
                || aliases[module.info.id.0 as usize].contains_key(&f.name)
                || names[module.info.id.0 as usize]
                    .insert(f.name.clone(), id)
                    .is_some()
            {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0211",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!("duplicate function or type name `{}`", f.name),
                        Some(f.span),
                    ),
                    module,
                )]);
            }
            let amap = &aliases[module.info.id.0 as usize];
            let parameters = f
                .parameters
                .iter()
                .map(|p| {
                    resolve_type(&p.ty, amap).map(|ty| ParameterSignature {
                        name: p.name.clone(),
                        ty,
                        span: p.span,
                    })
                })
                .collect::<Result<Vec<_>, _>>()
                .map_err(|d| vec![src(d, module)])?;
            let return_type =
                resolve_type(&f.return_type, amap).map_err(|d| vec![src(d, module)])?;
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
    let imports = program
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
    let module_names = program
        .modules
        .iter()
        .map(|m| (m.info.name.clone(), m.info.id))
        .collect();
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
        entry,
    })
}
#[derive(Clone, Copy, PartialEq, Eq)]
enum AliasState {
    Visiting,
    Done,
}
fn resolve_alias(
    name: &str,
    module: &ParsedModule,
    decl: &BTreeMap<String, &crate::AstAlias>,
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
    let ty = if let Some(t) = builtin(&a.target.name) {
        t
    } else if decl.contains_key(&a.target.name) {
        resolve_alias(&a.target.name, module, decl, state, resolved, info)?
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
        aliases: &d.aliases[module.0 as usize],
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
    aliases: &'a BTreeMap<String, Type>,
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
                    let ty = resolve_type(ty, self.aliases).map_err(|d| vec![d])?;
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
                AstStmtKind::Assign { name, value } => {
                    let Some(local) = self.lookup(name) else {
                        return Err(vec![unknown_name(name, s.span)]);
                    };
                    let value = self
                        .expression(value, Some(self.locals[local.0 as usize].ty))?
                        .expr;
                    HirStmtKind::Assign { local, value }
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
                if let Some(target) = builtin(callee).or_else(|| self.aliases.get(callee).copied())
                {
                    self.explicit_cast(callee, target, args, e.span)?
                } else {
                    self.call(callee, args, e.span)?
                }
            }
            AstExprKind::QualifiedCall {
                module,
                function,
                args,
            } => self.qcall(module, function, args, e.span)?,
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
            Type::Bool => return Err(vec![type_error("bool cannot be used numerically", span)]),
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
    fn qcall(
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
        let Some(id) = self.names[mid.0 as usize].get(f).copied() else {
            return Err(vec![Diagnostic::new(
                "E0222",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("unknown function `{f}` in module `{m}`"),
                Some(span),
            )]);
        };
        self.call_id(id, &format!("{m}.{f}"), args, span)
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
fn resolve_type(t: &AstType, a: &BTreeMap<String, Type>) -> Result<Type, Diagnostic> {
    builtin(&t.name)
        .or_else(|| a.get(&t.name).copied())
        .ok_or_else(|| unknown_type(t))
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
    for (i, (s, f)) in h.signatures.iter().zip(&h.functions).enumerate() {
        if s.id.0 as usize != i || f.id != s.id || f.module != s.module {
            return Err(fail("HIR function identity mismatch".into()));
        }
        for (j, l) in f.locals.iter().enumerate() {
            if l.id.0 as usize != j {
                return Err(fail("HIR local identity invalid".into()));
            }
        }
        verify_block(&f.body, f, s.return_type, &h.signatures, &fail)?
    }
    Ok(())
}
fn verify_block(
    b: &HirBlock,
    f: &HirFunction,
    ret: Type,
    sigs: &[FunctionSignature],
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    for s in &b.statements {
        match &s.kind {
            HirStmtKind::Local { local, initializer }
            | HirStmtKind::Assign {
                local,
                value: initializer,
            } => {
                verify_expr(initializer, f, sigs, fail)?;
                if f.locals.get(local.0 as usize).map(|l| l.ty) != Some(initializer.ty) {
                    return Err(fail("HIR assignment mismatch".into()));
                }
            }
            HirStmtKind::If {
                condition,
                then_block,
                else_block,
            } => {
                verify_expr(condition, f, sigs, fail)?;
                if condition.ty != Type::Bool {
                    return Err(fail("HIR condition not bool".into()));
                }
                verify_block(then_block, f, ret, sigs, fail)?;
                if let Some(x) = else_block {
                    verify_block(x, f, ret, sigs, fail)?
                }
            }
            HirStmtKind::While { condition, body } => {
                verify_expr(condition, f, sigs, fail)?;
                if condition.ty != Type::Bool {
                    return Err(fail("HIR condition not bool".into()));
                }
                verify_block(body, f, ret, sigs, fail)?
            }
            HirStmtKind::Return(v) => {
                verify_expr(v, f, sigs, fail)?;
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
        HirExprKind::Call { callee, args } => {
            let Some(s) = sigs.get(callee.0 as usize) else {
                return Err(fail("HIR callee missing".into()));
            };
            if s.return_type != e.ty || args.len() != s.parameters.len() {
                return Err(fail("HIR call mismatch".into()));
            }
            for (a, p) in args.iter().zip(&s.parameters) {
                verify_expr(a, f, sigs, fail)?;
                if a.ty != p.ty {
                    return Err(fail("HIR argument mismatch".into()));
                }
            }
        }
        HirExprKind::Coerce { kind, operand } => {
            verify_expr(operand, f, sigs, fail)?;
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
            verify_expr(operand, f, sigs, fail)?;
            if operand.ty != *source_type
                || e.ty != *target_type
                || select_cast_kind(*source_type, *target_type, TargetProperties::LINUX_X86_64)
                    != Some(*kind)
            {
                return Err(fail("HIR explicit cast contract invalid".into()));
            }
        }
        HirExprKind::Unary { op, operand } => {
            verify_expr(operand, f, sigs, fail)?;
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
            verify_expr(left, f, sigs, fail)?;
            verify_expr(right, f, sigs, fail)?;
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
                HirBinaryOp::Equal | HirBinaryOp::NotEqual => e.ty == Type::Bool,
            };
            if !ok {
                return Err(fail("HIR binary invalid".into()));
            }
        }
        _ => {}
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
}
