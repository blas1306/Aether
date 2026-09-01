//! Name-resolved and fully typed high-level IR for a discovered source program.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write;

use crate::{
    AstBinaryOp, AstBlock, AstExpr, AstExprKind, AstFunction, AstStmtKind, AstType, AstUnaryOp,
    Diagnostic, DiagnosticCategory, ParsedAst, Phase, SourceId, Span,
};

/// Canonical semantic types admitted by Vertical-1.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Type {
    /// Signed 64-bit integer; the `int` alias canonicalizes here.
    Int64,
    /// Logical boolean.
    Bool,
}

/// Session-local logical module identity. Filesystem paths are never this identity.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ModuleId(pub u32);

/// One import edge after discovery has resolved its target.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedImport {
    /// Source spelling retained for diagnostics and dumps.
    pub name: String,
    /// Semantic target identity.
    pub module: ModuleId,
    /// Import declaration provenance.
    pub span: Span,
}

/// Module graph node and source provenance shared by later phases.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ModuleInfo {
    /// Session-local identity.
    pub id: ModuleId,
    /// Logical bootstrap module name.
    pub name: String,
    /// Source table identity.
    pub source: SourceId,
    /// Display path, retained only as provenance.
    pub source_name: String,
    /// Resolved outgoing graph edges in source order.
    pub imports: Vec<ResolvedImport>,
}

/// One parsed module assembled by module discovery.
#[derive(Clone, Debug)]
pub struct ParsedModule {
    /// Graph/provenance record.
    pub info: ModuleInfo,
    /// Parsed source syntax, produced exactly once for this module.
    pub ast: ParsedAst,
}

/// Complete parsed module graph before declaration collection.
#[derive(Clone, Debug)]
pub struct ParsedProgram {
    /// Canonical module table, indexed by [`ModuleId`].
    pub modules: Vec<ParsedModule>,
    /// Entry source module.
    pub entry: ModuleId,
}

/// Globally unambiguous session-local function identity.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct FunctionId(pub u32);

/// Stable function-local identity, shared by parameters and ordinary locals.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct LocalId(pub u32);

/// One scalar parameter in a collected signature.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParameterSignature {
    /// Source name retained for diagnostics and inspection.
    pub name: String,
    /// Canonical scalar type.
    pub ty: Type,
    /// Declaration span.
    pub span: Span,
}

/// Function identity and type contract, collected before any body is checked.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FunctionSignature {
    /// Stable identity.
    pub id: FunctionId,
    /// Declaring module.
    pub module: ModuleId,
    /// Source name retained as metadata.
    pub name: String,
    /// Scalar parameters in call order.
    pub parameters: Vec<ParameterSignature>,
    /// Scalar result type.
    pub return_type: Type,
    /// Declaration span.
    pub span: Span,
}

/// Type-state proving that all program signatures have been collected and are module-unique.
#[derive(Clone, Debug)]
pub struct DeclaredProgram {
    program: ParsedProgram,
    signatures: Vec<FunctionSignature>,
    names: Vec<BTreeMap<String, FunctionId>>,
    imports: Vec<BTreeMap<String, ModuleId>>,
    module_names: BTreeMap<String, ModuleId>,
    entry: FunctionId,
}

impl DeclaredProgram {
    /// Collected signatures in stable source order.
    #[must_use]
    pub fn signatures(&self) -> &[FunctionSignature] {
        &self.signatures
    }
}

/// A resolved local declaration.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirLocal {
    /// Identity used after resolution.
    pub id: LocalId,
    /// Source spelling retained only for diagnostics/dumps.
    pub name: String,
    /// Canonical type.
    pub ty: Type,
    /// Declaration span.
    pub span: Span,
    /// Parameters are initialized at entry and otherwise behave as scalar locals.
    pub parameter: bool,
}

/// A parameter's function-local identity.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirParameter {
    /// Local identity used by the body.
    pub local: LocalId,
    /// Canonical type.
    pub ty: Type,
    /// Source span.
    pub span: Span,
}

/// Typed HIR type-state. Only semantic analysis can construct it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TypedHir {
    modules: Vec<ModuleInfo>,
    signatures: Vec<FunctionSignature>,
    functions: Vec<HirFunction>,
    entry: FunctionId,
}

impl TypedHir {
    /// Function table in stable identity order.
    #[must_use]
    pub fn signatures(&self) -> &[FunctionSignature] {
        &self.signatures
    }

    /// Resolved module graph in canonical identity order.
    #[must_use]
    pub fn modules(&self) -> &[ModuleInfo] {
        &self.modules
    }

    /// Typed bodies in stable identity order.
    #[must_use]
    pub fn functions(&self) -> &[HirFunction] {
        &self.functions
    }

    /// Source entry function identity.
    #[must_use]
    pub const fn entry(&self) -> FunctionId {
        self.entry
    }

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
                .filter(|function| function.module == module.id)
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

    /// Consumes the phase wrapper for the one-way production transition.
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

/// Typed function body, deliberately separate from its table signature.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirFunction {
    /// Stable identity selecting the corresponding signature.
    pub id: FunctionId,
    /// Declaring module identity.
    pub module: ModuleId,
    /// Parameter identities in call order.
    pub parameters: Vec<HirParameter>,
    /// All resolved locals, parameters first and then declarations in source order.
    pub locals: Vec<HirLocal>,
    /// Structured, typed body.
    pub body: HirBlock,
    /// Source span.
    pub span: Span,
}

/// Typed lexical block.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirBlock {
    /// Statements.
    pub statements: Vec<HirStmt>,
    /// Source span.
    pub span: Span,
}

/// Typed statement.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirStmt {
    /// Resolved form.
    pub kind: HirStmtKind,
    /// Source span.
    pub span: Span,
}

/// Typed statement forms.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
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

/// Typed expression.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirExpr {
    /// Selected operation/value form.
    pub kind: HirExprKind,
    /// Unique canonical type.
    pub ty: Type,
    /// Source span.
    pub span: Span,
}

/// Resolved expression forms.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum HirExprKind {
    Int(i64),
    Bool(bool),
    Local(LocalId),
    Call {
        callee: FunctionId,
        args: Vec<HirExpr>,
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

/// Semantically selected prefix operators.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HirUnaryOp {
    /// Checked signed `int64` negation.
    NegateChecked,
}

/// Semantically selected infix operators.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HirBinaryOp {
    /// Checked integer addition.
    AddChecked,
    /// Checked integer subtraction.
    SubtractChecked,
    /// Checked integer multiplication.
    MultiplyChecked,
    /// Signed less-than comparison.
    Less,
    /// Signed less-than-or-equal comparison.
    LessEqual,
    /// Signed greater-than comparison.
    Greater,
    /// Signed greater-than-or-equal comparison.
    GreaterEqual,
    /// Same-type equality.
    Equal,
    /// Same-type inequality.
    NotEqual,
}

/// Collects every signature before body analysis, enabling forward calls and recursion.
pub fn collect_signatures(ast: ParsedAst) -> Result<DeclaredProgram, Vec<Diagnostic>> {
    let source = ast
        .functions
        .first()
        .map_or(SourceId(0), |function| function.span.source);
    collect_program_signatures(ParsedProgram {
        modules: vec![ParsedModule {
            info: ModuleInfo {
                id: ModuleId(0),
                name: "main".to_owned(),
                source,
                source_name: "<memory>".to_owned(),
                imports: Vec::new(),
            },
            ast,
        }],
        entry: ModuleId(0),
    })
}

/// Collects declarations globally from an already discovered module graph.
pub fn collect_program_signatures(
    program: ParsedProgram,
) -> Result<DeclaredProgram, Vec<Diagnostic>> {
    validate_parsed_program(&program)?;
    let function_count = program
        .modules
        .iter()
        .map(|module| module.ast.functions.len())
        .sum();
    let mut signatures = Vec::with_capacity(function_count);
    let mut names = vec![BTreeMap::new(); program.modules.len()];
    let imports = program
        .modules
        .iter()
        .map(|module| {
            module
                .info
                .imports
                .iter()
                .map(|import| (import.name.clone(), import.module))
                .collect()
        })
        .collect();
    let module_names = program
        .modules
        .iter()
        .map(|module| (module.info.name.clone(), module.info.id))
        .collect();
    for module in &program.modules {
        let module_names = &mut names[module.info.id.0 as usize];
        for function in &module.ast.functions {
            let id = FunctionId(u32::try_from(signatures.len()).expect("function count fits u32"));
            if module_names.insert(function.name.clone(), id).is_some() {
                return Err(vec![Diagnostic::new(
                    "E0211",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!(
                        "duplicate function `{}` in module `{}`; overloads are not admitted in NEXT-VERTICAL-2",
                        function.name, module.info.name
                    ),
                    Some(function.span),
                )
                .with_source_name(&module.info.source_name)]);
            }
            signatures.push(FunctionSignature {
                id,
                module: module.info.id,
                name: function.name.clone(),
                parameters: function
                    .parameters
                    .iter()
                    .map(|parameter| ParameterSignature {
                        name: parameter.name.clone(),
                        ty: canonical(parameter.ty),
                        span: parameter.span,
                    })
                    .collect(),
                return_type: canonical(function.return_type),
                span: function.span,
            });
        }
    }
    let entry_module = &program.modules[program.entry.0 as usize];
    let Some(entry) = names[program.entry.0 as usize].get("main").copied() else {
        return Err(vec![
            Diagnostic::new(
                "E0200",
                Phase::Semantic,
                DiagnosticCategory::Name,
                "entry module requires `int main()`",
                entry_module
                    .ast
                    .functions
                    .first()
                    .map(|function| function.span),
            )
            .with_source_name(&entry_module.info.source_name),
        ]);
    };
    let main = &signatures[entry.0 as usize];
    if main.return_type != Type::Int64 || !main.parameters.is_empty() {
        return Err(vec![
            Diagnostic::new(
                "E0201",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "entry function must have signature `int main()`",
                Some(main.span),
            )
            .with_source_name(&entry_module.info.source_name),
        ]);
    }
    Ok(DeclaredProgram {
        program,
        signatures,
        names,
        imports,
        module_names,
        entry,
    })
}

/// Checks all bodies against an already complete function table.
pub fn analyze_bodies(declared: DeclaredProgram) -> Result<TypedHir, Vec<Diagnostic>> {
    let mut functions = Vec::with_capacity(declared.signatures.len());
    for module in &declared.program.modules {
        for function in &module.ast.functions {
            let id = FunctionId(u32::try_from(functions.len()).expect("function count fits u32"));
            let analyzed = analyze_function(
                function,
                id,
                module.info.id,
                &declared.signatures,
                &declared.names,
                &declared.imports,
                &declared.module_names,
            )
            .map_err(|diagnostics| {
                diagnostics
                    .into_iter()
                    .map(|diagnostic| diagnostic.with_source_name(&module.info.source_name))
                    .collect::<Vec<_>>()
            })?;
            functions.push(analyzed);
        }
    }
    let hir = TypedHir {
        modules: declared
            .program
            .modules
            .iter()
            .map(|module| module.info.clone())
            .collect(),
        signatures: declared.signatures,
        functions,
        entry: declared.entry,
    };
    verify_hir(&hir)?;
    Ok(hir)
}

/// Convenience semantic pipeline for API callers that do not need separate timings.
pub fn analyze(ast: ParsedAst) -> Result<TypedHir, Vec<Diagnostic>> {
    analyze_bodies(collect_signatures(ast)?)
}

fn analyze_function(
    function: &AstFunction,
    id: FunctionId,
    module: ModuleId,
    signatures: &[FunctionSignature],
    names: &[BTreeMap<String, FunctionId>],
    imports: &[BTreeMap<String, ModuleId>],
    module_names: &BTreeMap<String, ModuleId>,
) -> Result<HirFunction, Vec<Diagnostic>> {
    let signature = &signatures[id.0 as usize];
    let mut analyzer = Analyzer {
        scopes: vec![BTreeMap::new()],
        locals: Vec::new(),
        signatures,
        names,
        imports,
        module_names,
        module,
        return_type: signature.return_type,
    };
    let mut parameters = Vec::with_capacity(signature.parameters.len());
    for parameter in &signature.parameters {
        if analyzer.scopes[0].contains_key(&parameter.name) {
            return Err(vec![Diagnostic::new(
                "E0203",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("parameter `{}` is already declared", parameter.name),
                Some(parameter.span),
            )]);
        }
        let local = LocalId(u32::try_from(analyzer.locals.len()).expect("local count fits u32"));
        analyzer.locals.push(HirLocal {
            id: local,
            name: parameter.name.clone(),
            ty: parameter.ty,
            span: parameter.span,
            parameter: true,
        });
        analyzer.scopes[0].insert(parameter.name.clone(), local);
        parameters.push(HirParameter {
            local,
            ty: parameter.ty,
            span: parameter.span,
        });
    }
    let body = analyzer.block(&function.body, false)?;
    if !definitely_returns(&body) {
        return Err(vec![Diagnostic::new(
            "E0207",
            Phase::Semantic,
            DiagnosticCategory::Type,
            format!(
                "every reachable path through `{}` must return {:?}",
                signature.name, signature.return_type
            ),
            Some(function.body.span),
        )]);
    }
    Ok(HirFunction {
        id,
        module,
        parameters,
        locals: analyzer.locals,
        body,
        span: function.span,
    })
}

struct Analyzer<'a> {
    scopes: Vec<BTreeMap<String, LocalId>>,
    locals: Vec<HirLocal>,
    signatures: &'a [FunctionSignature],
    names: &'a [BTreeMap<String, FunctionId>],
    imports: &'a [BTreeMap<String, ModuleId>],
    module_names: &'a BTreeMap<String, ModuleId>,
    module: ModuleId,
    return_type: Type,
}

struct CheckedExpr {
    expr: HirExpr,
    constant_int: Option<i128>,
}

impl Analyzer<'_> {
    #[allow(clippy::too_many_lines)]
    fn block(&mut self, block: &AstBlock, nested: bool) -> Result<HirBlock, Vec<Diagnostic>> {
        if nested {
            self.scopes.push(BTreeMap::new());
        }
        let mut statements = Vec::with_capacity(block.statements.len());
        let mut terminated = false;
        for statement in &block.statements {
            if terminated {
                return Err(vec![Diagnostic::new(
                    "E0208",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    "unreachable statement after a guaranteed return",
                    Some(statement.span),
                )]);
            }
            let kind = match &statement.kind {
                AstStmtKind::Local {
                    ty,
                    name,
                    initializer,
                } => {
                    if self
                        .scopes
                        .last()
                        .is_some_and(|scope| scope.contains_key(name))
                    {
                        return Err(vec![Diagnostic::new(
                            "E0203",
                            Phase::Semantic,
                            DiagnosticCategory::Name,
                            format!("local `{name}` is already declared in this scope"),
                            Some(statement.span),
                        )]);
                    }
                    let ty = canonical(*ty);
                    let initializer = self.expression(initializer, Some(ty))?;
                    require_type(&initializer.expr, ty, "local initializer")?;
                    let id =
                        LocalId(u32::try_from(self.locals.len()).expect("local count fits u32"));
                    self.locals.push(HirLocal {
                        id,
                        name: name.clone(),
                        ty,
                        span: statement.span,
                        parameter: false,
                    });
                    self.scopes
                        .last_mut()
                        .expect("scope exists")
                        .insert(name.clone(), id);
                    HirStmtKind::Local {
                        local: id,
                        initializer: initializer.expr,
                    }
                }
                AstStmtKind::Assign { name, value } => {
                    let Some(local) = self.lookup(name) else {
                        return Err(vec![unknown_name(name, statement.span)]);
                    };
                    let ty = self.locals[local.0 as usize].ty;
                    let value = self.expression(value, Some(ty))?;
                    require_type(&value.expr, ty, "assignment")?;
                    HirStmtKind::Assign {
                        local,
                        value: value.expr,
                    }
                }
                AstStmtKind::If {
                    condition,
                    then_block,
                    else_block,
                } => {
                    let condition = self.expression(condition, Some(Type::Bool))?;
                    require_type(&condition.expr, Type::Bool, "if condition")?;
                    let then_block = self.block(then_block, true)?;
                    let else_block = else_block
                        .as_ref()
                        .map(|value| self.block(value, true))
                        .transpose()?;
                    HirStmtKind::If {
                        condition: condition.expr,
                        then_block,
                        else_block,
                    }
                }
                AstStmtKind::While { condition, body } => {
                    let condition = self.expression(condition, Some(Type::Bool))?;
                    require_type(&condition.expr, Type::Bool, "while condition")?;
                    let body = self.block(body, true)?;
                    HirStmtKind::While {
                        condition: condition.expr,
                        body,
                    }
                }
                AstStmtKind::Return(value) => {
                    let value = self.expression(value, Some(self.return_type))?;
                    require_type(&value.expr, self.return_type, "return")?;
                    HirStmtKind::Return(value.expr)
                }
            };
            let hir = HirStmt {
                kind,
                span: statement.span,
            };
            terminated = statement_returns(&hir);
            statements.push(hir);
        }
        if nested {
            self.scopes.pop();
        }
        Ok(HirBlock {
            statements,
            span: block.span,
        })
    }

    #[allow(clippy::too_many_lines)]
    fn expression(
        &self,
        expression: &AstExpr,
        expected: Option<Type>,
    ) -> Result<CheckedExpr, Vec<Diagnostic>> {
        let checked = match &expression.kind {
            AstExprKind::Integer(text) => {
                if expected == Some(Type::Bool) {
                    return Err(vec![type_error(
                        "integer literal has type int, expected bool",
                        expression.span,
                    )]);
                }
                let magnitude = parse_magnitude(text, expression.span)?;
                if magnitude > i64::MAX as u128 {
                    return Err(vec![integer_range(text, expression.span)]);
                }
                let value = i64::try_from(magnitude).expect("range checked");
                CheckedExpr {
                    expr: HirExpr {
                        kind: HirExprKind::Int(value),
                        ty: Type::Int64,
                        span: expression.span,
                    },
                    constant_int: Some(i128::from(value)),
                }
            }
            AstExprKind::Bool(value) => {
                if expected == Some(Type::Int64) {
                    return Err(vec![type_error(
                        "boolean literal has type bool, expected int",
                        expression.span,
                    )]);
                }
                CheckedExpr {
                    expr: HirExpr {
                        kind: HirExprKind::Bool(*value),
                        ty: Type::Bool,
                        span: expression.span,
                    },
                    constant_int: None,
                }
            }
            AstExprKind::Name(name) => {
                if self.names[self.module.0 as usize].contains_key(name) {
                    return Err(vec![Diagnostic::new(
                        "E0215",
                        Phase::Semantic,
                        DiagnosticCategory::Unsupported,
                        format!("function values are not admitted; call `{name}(...)` directly"),
                        Some(expression.span),
                    )]);
                }
                let Some(local) = self.lookup(name) else {
                    return Err(vec![unknown_name(name, expression.span)]);
                };
                let ty = self.locals[local.0 as usize].ty;
                CheckedExpr {
                    expr: HirExpr {
                        kind: HirExprKind::Local(local),
                        ty,
                        span: expression.span,
                    },
                    constant_int: None,
                }
            }
            AstExprKind::Call { callee, args } => self.call(callee, args, expression.span)?,
            AstExprKind::QualifiedCall {
                module,
                function,
                args,
            } => self.qualified_call(module, function, args, expression.span)?,
            AstExprKind::QualifiedName { module, member } => {
                return Err(vec![Diagnostic::new(
                    "E0224",
                    Phase::Semantic,
                    DiagnosticCategory::Unsupported,
                    format!(
                        "invalid qualified expression `{module}.{member}`; qualified names are admitted only as direct calls"
                    ),
                    Some(expression.span),
                )]);
            }
            AstExprKind::Unary {
                op: AstUnaryOp::Negate,
                operand,
            } => {
                if let AstExprKind::Integer(text) = &operand.kind {
                    let magnitude = parse_magnitude(text, operand.span)?;
                    if magnitude == (i64::MAX as u128) + 1 {
                        return Ok(CheckedExpr {
                            expr: HirExpr {
                                kind: HirExprKind::Int(i64::MIN),
                                ty: Type::Int64,
                                span: expression.span,
                            },
                            constant_int: Some(i128::from(i64::MIN)),
                        });
                    }
                }
                let operand = self.expression(operand, Some(Type::Int64))?;
                require_type(&operand.expr, Type::Int64, "unary `-`")?;
                let constant_int = operand.constant_int.map(|value| -value);
                check_constant_range(constant_int, expression.span)?;
                CheckedExpr {
                    expr: HirExpr {
                        kind: HirExprKind::Unary {
                            op: HirUnaryOp::NegateChecked,
                            operand: Box::new(operand.expr),
                        },
                        ty: Type::Int64,
                        span: expression.span,
                    },
                    constant_int,
                }
            }
            AstExprKind::Binary { op, left, right } => {
                self.binary(*op, left, right, expression.span)?
            }
        };
        if let Some(expected) = expected {
            if checked.expr.ty != expected {
                return Err(vec![type_mismatch(
                    checked.expr.ty,
                    expected,
                    expression.span,
                )]);
            }
        }
        Ok(checked)
    }

    fn call(
        &self,
        name: &str,
        args: &[AstExpr],
        span: Span,
    ) -> Result<CheckedExpr, Vec<Diagnostic>> {
        let Some(id) = self.names[self.module.0 as usize].get(name).copied() else {
            return Err(vec![Diagnostic::new(
                "E0212",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("unknown function `{name}`"),
                Some(span),
            )]);
        };
        self.call_id(id, name, args, span)
    }

    fn qualified_call(
        &self,
        module_name: &str,
        function: &str,
        args: &[AstExpr],
        span: Span,
    ) -> Result<CheckedExpr, Vec<Diagnostic>> {
        let imported = self.imports[self.module.0 as usize]
            .get(module_name)
            .copied();
        let Some(target_module) = imported else {
            let known = self.module_names.contains_key(module_name);
            let (code, message) = if known {
                (
                    "E0223",
                    format!("module `{module_name}` is referenced without an import"),
                )
            } else {
                ("E0221", format!("unknown module `{module_name}`"))
            };
            return Err(vec![Diagnostic::new(
                code,
                Phase::Semantic,
                DiagnosticCategory::Name,
                message,
                Some(span),
            )]);
        };
        let Some(id) = self.names[target_module.0 as usize].get(function).copied() else {
            return Err(vec![Diagnostic::new(
                "E0222",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("unknown function `{function}` in module `{module_name}`"),
                Some(span),
            )]);
        };
        self.call_id(id, &format!("{module_name}.{function}"), args, span)
    }

    fn call_id(
        &self,
        id: FunctionId,
        display_name: &str,
        args: &[AstExpr],
        span: Span,
    ) -> Result<CheckedExpr, Vec<Diagnostic>> {
        let signature = &self.signatures[id.0 as usize];
        if args.len() != signature.parameters.len() {
            return Err(vec![Diagnostic::new(
                "E0213",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "function `{display_name}` expects {} arguments, found {}",
                    signature.parameters.len(),
                    args.len()
                ),
                Some(span),
            )]);
        }
        let mut checked_args = Vec::with_capacity(args.len());
        for (index, (arg, parameter)) in args.iter().zip(&signature.parameters).enumerate() {
            match self.expression(arg, Some(parameter.ty)) {
                Ok(arg) => checked_args.push(arg.expr),
                Err(mut diagnostics) => {
                    let diagnostic = diagnostics.first_mut().expect("expression error");
                    if diagnostic.code == "E0205" {
                        diagnostic.code = "E0214";
                        diagnostic.message = format!(
                            "argument {} to `{display_name}` must have type {:?}: {}",
                            index + 1,
                            parameter.ty,
                            diagnostic.message
                        );
                    }
                    return Err(diagnostics);
                }
            }
        }
        Ok(CheckedExpr {
            expr: HirExpr {
                kind: HirExprKind::Call {
                    callee: id,
                    args: checked_args,
                },
                ty: signature.return_type,
                span,
            },
            constant_int: None,
        })
    }

    fn binary(
        &self,
        op: AstBinaryOp,
        left: &AstExpr,
        right: &AstExpr,
        span: Span,
    ) -> Result<CheckedExpr, Vec<Diagnostic>> {
        let arithmetic = matches!(
            op,
            AstBinaryOp::Add | AstBinaryOp::Subtract | AstBinaryOp::Multiply
        );
        let ordered = matches!(
            op,
            AstBinaryOp::Less
                | AstBinaryOp::LessEqual
                | AstBinaryOp::Greater
                | AstBinaryOp::GreaterEqual
        );
        let left = self.expression(left, (arithmetic || ordered).then_some(Type::Int64))?;
        let right = self.expression(right, Some(left.expr.ty))?;
        if (arithmetic || ordered) && left.expr.ty != Type::Int64 {
            return Err(vec![type_error(
                "arithmetic and ordered comparisons require int operands",
                span,
            )]);
        }
        let (op, ty, constant_int) = match op {
            AstBinaryOp::Add => (
                HirBinaryOp::AddChecked,
                Type::Int64,
                constants(&left, &right, |a, b| a + b),
            ),
            AstBinaryOp::Subtract => (
                HirBinaryOp::SubtractChecked,
                Type::Int64,
                constants(&left, &right, |a, b| a - b),
            ),
            AstBinaryOp::Multiply => (
                HirBinaryOp::MultiplyChecked,
                Type::Int64,
                constants(&left, &right, |a, b| a * b),
            ),
            AstBinaryOp::Less => (HirBinaryOp::Less, Type::Bool, None),
            AstBinaryOp::LessEqual => (HirBinaryOp::LessEqual, Type::Bool, None),
            AstBinaryOp::Greater => (HirBinaryOp::Greater, Type::Bool, None),
            AstBinaryOp::GreaterEqual => (HirBinaryOp::GreaterEqual, Type::Bool, None),
            AstBinaryOp::Equal => (HirBinaryOp::Equal, Type::Bool, None),
            AstBinaryOp::NotEqual => (HirBinaryOp::NotEqual, Type::Bool, None),
        };
        check_constant_range(constant_int, span)?;
        Ok(CheckedExpr {
            expr: HirExpr {
                kind: HirExprKind::Binary {
                    op,
                    left: Box::new(left.expr),
                    right: Box::new(right.expr),
                },
                ty,
                span,
            },
            constant_int,
        })
    }

    fn lookup(&self, name: &str) -> Option<LocalId> {
        self.scopes
            .iter()
            .rev()
            .find_map(|scope| scope.get(name).copied())
    }
}

fn validate_parsed_program(program: &ParsedProgram) -> Result<(), Vec<Diagnostic>> {
    let fail = |message: String| {
        vec![Diagnostic::new(
            "E0220",
            Phase::Semantic,
            DiagnosticCategory::Name,
            message,
            None,
        )]
    };
    if program.modules.is_empty() || program.entry.0 as usize >= program.modules.len() {
        return Err(fail("module graph has no valid entry module".into()));
    }
    let mut module_names = BTreeSet::new();
    let mut source_ids = BTreeSet::new();
    for (index, module) in program.modules.iter().enumerate() {
        if module.info.id.0 as usize != index
            || !module_names.insert(&module.info.name)
            || !source_ids.insert(module.info.source)
        {
            return Err(fail(
                "duplicate or non-canonical module/source identity in module graph".into(),
            ));
        }
        let mut imports = BTreeSet::new();
        for import in &module.info.imports {
            if import.module.0 as usize >= program.modules.len()
                || program.modules[import.module.0 as usize].info.name != import.name
                || !imports.insert(&import.name)
            {
                return Err(vec![
                    Diagnostic::new(
                        "E0220",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!("duplicate or invalid import `{}`", import.name),
                        Some(import.span),
                    )
                    .with_source_name(&module.info.source_name),
                ]);
            }
        }
    }
    Ok(())
}

/// Re-checks typed HIR table/body consistency before MIR lowering.
pub fn verify_hir(hir: &TypedHir) -> Result<(), Vec<Diagnostic>> {
    let fail = |message: String| {
        vec![Diagnostic::new(
            "E0290",
            Phase::Semantic,
            DiagnosticCategory::Verification,
            message,
            None,
        )]
    };
    if hir.modules.is_empty()
        || hir.entry.0 as usize >= hir.signatures.len()
        || hir.functions.len() != hir.signatures.len()
    {
        return Err(fail(
            "HIR function table/body cardinality is invalid".into(),
        ));
    }
    let entry = &hir.signatures[hir.entry.0 as usize];
    if entry.name != "main" || entry.return_type != Type::Int64 || !entry.parameters.is_empty() {
        return Err(fail("HIR semantic entry function is invalid".into()));
    }
    let mut module_names = BTreeSet::new();
    let mut source_ids = BTreeSet::new();
    for (index, module) in hir.modules.iter().enumerate() {
        if module.id.0 as usize != index
            || !module_names.insert(&module.name)
            || !source_ids.insert(module.source)
        {
            return Err(fail("HIR module graph is invalid".into()));
        }
        let mut import_names = BTreeSet::new();
        for import in &module.imports {
            if import.module.0 as usize >= hir.modules.len()
                || hir.modules[import.module.0 as usize].name != import.name
                || !import_names.insert(&import.name)
            {
                return Err(fail("HIR module graph contains an invalid import".into()));
            }
        }
    }
    let mut names = BTreeSet::new();
    for (index, (signature, function)) in hir.signatures.iter().zip(&hir.functions).enumerate() {
        if signature.id.0 as usize != index
            || function.id != signature.id
            || function.module != signature.module
            || signature.module.0 as usize >= hir.modules.len()
            || !names.insert((signature.module, &signature.name))
        {
            return Err(fail(
                "HIR function identities or names are not unique and canonical".into(),
            ));
        }
        if function.parameters.len() != signature.parameters.len() {
            return Err(fail(format!(
                "HIR parameter count mismatch for {:?}",
                function.id
            )));
        }
        for (local_index, local) in function.locals.iter().enumerate() {
            if local.id.0 as usize != local_index {
                return Err(fail(format!(
                    "HIR local identity is not canonical in {:?}",
                    function.id
                )));
            }
        }
        for (parameter, declared) in function.parameters.iter().zip(&signature.parameters) {
            let Some(local) = function.locals.get(parameter.local.0 as usize) else {
                return Err(fail("HIR parameter local does not exist".into()));
            };
            if !local.parameter || local.ty != declared.ty || parameter.ty != declared.ty {
                return Err(fail(
                    "HIR parameter identity/type contract is invalid".into(),
                ));
            }
        }
        verify_hir_block(
            &function.body,
            function,
            signature.return_type,
            &hir.signatures,
            &fail,
        )?;
    }
    Ok(())
}

fn verify_hir_block(
    block: &HirBlock,
    function: &HirFunction,
    return_type: Type,
    signatures: &[FunctionSignature],
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    for statement in &block.statements {
        match &statement.kind {
            HirStmtKind::Local { local, initializer }
            | HirStmtKind::Assign {
                local,
                value: initializer,
            } => {
                let Some(declared) = function.locals.get(local.0 as usize) else {
                    return Err(fail("HIR statement names an unknown local".into()));
                };
                verify_hir_expr(initializer, function, signatures, fail)?;
                if declared.ty != initializer.ty {
                    return Err(fail("HIR assignment type mismatch".into()));
                }
            }
            HirStmtKind::If {
                condition,
                then_block,
                else_block,
            } => {
                verify_hir_expr(condition, function, signatures, fail)?;
                if condition.ty != Type::Bool {
                    return Err(fail("HIR if condition is not bool".into()));
                }
                verify_hir_block(then_block, function, return_type, signatures, fail)?;
                if let Some(block) = else_block {
                    verify_hir_block(block, function, return_type, signatures, fail)?;
                }
            }
            HirStmtKind::While { condition, body } => {
                verify_hir_expr(condition, function, signatures, fail)?;
                if condition.ty != Type::Bool {
                    return Err(fail("HIR while condition is not bool".into()));
                }
                verify_hir_block(body, function, return_type, signatures, fail)?;
            }
            HirStmtKind::Return(value) => {
                verify_hir_expr(value, function, signatures, fail)?;
                if value.ty != return_type {
                    return Err(fail("HIR return type mismatch".into()));
                }
            }
        }
    }
    Ok(())
}

fn verify_hir_expr(
    expression: &HirExpr,
    function: &HirFunction,
    signatures: &[FunctionSignature],
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    match &expression.kind {
        HirExprKind::Int(_) if expression.ty != Type::Int64 => {
            return Err(fail("HIR int literal type mismatch".into()));
        }
        HirExprKind::Bool(_) if expression.ty != Type::Bool => {
            return Err(fail("HIR bool literal type mismatch".into()));
        }
        HirExprKind::Local(local) => {
            if function.locals.get(local.0 as usize).map(|local| local.ty) != Some(expression.ty) {
                return Err(fail("HIR local use identity/type mismatch".into()));
            }
        }
        HirExprKind::Call { callee, args } => {
            let Some(signature) = signatures.get(callee.0 as usize) else {
                return Err(fail("HIR call target does not exist".into()));
            };
            if signature.id != *callee
                || args.len() != signature.parameters.len()
                || expression.ty != signature.return_type
            {
                return Err(fail("HIR call signature mismatch".into()));
            }
            for (arg, parameter) in args.iter().zip(&signature.parameters) {
                verify_hir_expr(arg, function, signatures, fail)?;
                if arg.ty != parameter.ty {
                    return Err(fail("HIR call argument type mismatch".into()));
                }
            }
        }
        HirExprKind::Unary {
            op: HirUnaryOp::NegateChecked,
            operand,
        } => {
            verify_hir_expr(operand, function, signatures, fail)?;
            if operand.ty != Type::Int64 || expression.ty != Type::Int64 {
                return Err(fail("HIR checked-negation type contract is invalid".into()));
            }
        }
        HirExprKind::Binary { op, left, right } => {
            verify_hir_expr(left, function, signatures, fail)?;
            verify_hir_expr(right, function, signatures, fail)?;
            let valid = match op {
                HirBinaryOp::AddChecked
                | HirBinaryOp::SubtractChecked
                | HirBinaryOp::MultiplyChecked => {
                    left.ty == Type::Int64
                        && right.ty == Type::Int64
                        && expression.ty == Type::Int64
                }
                HirBinaryOp::Less
                | HirBinaryOp::LessEqual
                | HirBinaryOp::Greater
                | HirBinaryOp::GreaterEqual => {
                    left.ty == Type::Int64 && right.ty == Type::Int64 && expression.ty == Type::Bool
                }
                HirBinaryOp::Equal | HirBinaryOp::NotEqual => {
                    left.ty == right.ty
                        && matches!(left.ty, Type::Int64 | Type::Bool)
                        && expression.ty == Type::Bool
                }
            };
            if !valid {
                return Err(fail("HIR binary operation type contract is invalid".into()));
            }
        }
        HirExprKind::Int(_) | HirExprKind::Bool(_) => {}
    }
    Ok(())
}

fn canonical(ty: AstType) -> Type {
    match ty {
        AstType::Int => Type::Int64,
        AstType::Bool => Type::Bool,
    }
}

fn parse_magnitude(text: &str, span: Span) -> Result<u128, Vec<Diagnostic>> {
    text.parse::<u128>()
        .map_err(|_| vec![integer_range(text, span)])
}

fn constants(
    left: &CheckedExpr,
    right: &CheckedExpr,
    op: impl FnOnce(i128, i128) -> i128,
) -> Option<i128> {
    Some(op(left.constant_int?, right.constant_int?))
}

fn check_constant_range(value: Option<i128>, span: Span) -> Result<(), Vec<Diagnostic>> {
    if value.is_some_and(|value| value < i128::from(i64::MIN) || value > i128::from(i64::MAX)) {
        Err(vec![Diagnostic::new(
            "E0210",
            Phase::Semantic,
            DiagnosticCategory::Integer,
            "constant integer expression overflows int64",
            Some(span),
        )])
    } else {
        Ok(())
    }
}

fn require_type(expr: &HirExpr, expected: Type, context: &str) -> Result<(), Vec<Diagnostic>> {
    if expr.ty == expected {
        Ok(())
    } else {
        Err(vec![type_error(
            format!("{context} requires {expected:?}, found {:?}", expr.ty),
            expr.span,
        )])
    }
}

fn type_mismatch(found: Type, expected: Type, span: Span) -> Diagnostic {
    type_error(
        format!("type mismatch: expected {expected:?}, found {found:?}"),
        span,
    )
}

fn type_error(message: impl Into<String>, span: Span) -> Diagnostic {
    Diagnostic::new(
        "E0205",
        Phase::Semantic,
        DiagnosticCategory::Type,
        message,
        Some(span),
    )
}

fn unknown_name(name: &str, span: Span) -> Diagnostic {
    Diagnostic::new(
        "E0202",
        Phase::Semantic,
        DiagnosticCategory::Name,
        format!("unknown identifier `{name}`"),
        Some(span),
    )
}

fn integer_range(text: &str, span: Span) -> Diagnostic {
    Diagnostic::new(
        "E0209",
        Phase::Semantic,
        DiagnosticCategory::Integer,
        format!(
            "integer literal `{text}` is outside int64 range [-9223372036854775808, 9223372036854775807]"
        ),
        Some(span),
    )
}

fn statement_returns(statement: &HirStmt) -> bool {
    match &statement.kind {
        HirStmtKind::Return(_) => true,
        HirStmtKind::If {
            then_block,
            else_block: Some(else_block),
            ..
        } => definitely_returns(then_block) && definitely_returns(else_block),
        _ => false,
    }
}

fn definitely_returns(block: &HirBlock) -> bool {
    block.statements.last().is_some_and(statement_returns)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{SourceFile, parse_source};

    fn check(text: &str) -> Result<TypedHir, Vec<Diagnostic>> {
        analyze(parse_source(&SourceFile::new("test.ae", text)).unwrap())
    }

    #[test]
    fn resolves_forward_calls_parameters_and_recursion() {
        let hir = check("int first(int x){return second(x);}int second(int x){return x+1;}int main(){return first(10);}").unwrap();
        assert_eq!(hir.functions().len(), 3);
        assert_eq!(hir.functions()[0].parameters[0].local, LocalId(0));
        verify_hir(&hir).unwrap();
        check("int fact(int n){if(n<=1){return 1;}return n*fact(n-1);}int main(){return fact(5);}")
            .unwrap();
    }

    #[test]
    fn rejects_call_contract_errors() {
        assert_eq!(
            check("int main(){return missing();}").unwrap_err()[0].code,
            "E0212"
        );
        assert_eq!(
            check("int f(int x){return x;}int main(){return f();}").unwrap_err()[0].code,
            "E0213"
        );
        assert_eq!(
            check("int f(int x){return x;}int main(){return f(true);}").unwrap_err()[0].code,
            "E0214"
        );
        assert_eq!(
            check("int f(){return 1;}bool f(){return true;}int main(){return 0;}").unwrap_err()[0]
                .code,
            "E0211"
        );
    }

    #[test]
    fn accepts_ranges_and_checks_missing_return() {
        check("int main(){return -9223372036854775808;}").unwrap();
        assert_eq!(
            check("int main(){return 9223372036854775808;}").unwrap_err()[0].code,
            "E0209"
        );
        assert_eq!(
            check("int main(){return 9223372036854775807+1;}").unwrap_err()[0].code,
            "E0210"
        );
        assert_eq!(
            check("bool f(){bool x=true;}int main(){return 0;}").unwrap_err()[0].code,
            "E0207"
        );
    }

    #[test]
    fn parameters_have_value_semantics_as_locals() {
        check("int increment(int x){x=x+1;return x;}int main(){int x=4;int y=increment(x);return x+y;}").unwrap();
    }
}
