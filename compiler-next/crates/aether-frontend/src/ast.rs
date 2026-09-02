//! Source-structured AST. It deliberately has no resolved identities or semantic types.

use crate::Span;

/// Parsed compilation unit. Construction is restricted to the parser.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParsedAst {
    pub(crate) imports: Vec<AstImport>,
    pub(crate) aliases: Vec<AstAlias>,
    pub(crate) structs: Vec<AstStruct>,
    pub(crate) functions: Vec<AstFunction>,
}

impl ParsedAst {
    /// Functions in deterministic source order.
    #[must_use]
    pub fn functions(&self) -> &[AstFunction] {
        &self.functions
    }

    /// Imports in deterministic source order.
    #[must_use]
    pub fn imports(&self) -> &[AstImport] {
        &self.imports
    }

    /// User type aliases in deterministic source order.
    #[must_use]
    pub fn aliases(&self) -> &[AstAlias] {
        &self.aliases
    }

    /// Struct declarations in deterministic source order.
    #[must_use]
    pub fn structs(&self) -> &[AstStruct] {
        &self.structs
    }

    /// Deterministic inspection dump.
    #[must_use]
    pub fn dump(&self) -> String {
        format!(
            "imports: {:#?}\naliases: {:#?}\nstructs: {:#?}\nfunctions: {:#?}",
            self.imports, self.aliases, self.structs, self.functions
        )
    }
}

/// Nominal value-aggregate declaration.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstStruct {
    /// Declared nominal name.
    pub name: String,
    /// Fields in semantically significant declaration order.
    pub fields: Vec<AstField>,
    /// Full declaration provenance.
    pub span: Span,
}

/// One struct field. Source order is semantically significant.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstField {
    /// Written field type.
    pub ty: AstType,
    /// Source field name.
    pub name: String,
    /// Field declaration provenance.
    pub span: Span,
}

/// Transparent source-level type alias.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstAlias {
    /// New transparent spelling.
    pub name: String,
    /// Aliased source type.
    pub target: AstType,
    /// Declaration provenance.
    pub span: Span,
}

/// Minimal source import, unresolved until module discovery.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstImport {
    /// Logical module spelling.
    pub module: String,
    /// Full import declaration span.
    pub span: Span,
}

/// Source-level function.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstFunction {
    /// Written return type.
    pub return_type: AstType,
    /// Written function name.
    pub name: String,
    /// Scalar parameters in source order.
    pub parameters: Vec<AstParameter>,
    /// Function body.
    pub body: AstBlock,
    /// Full declaration span.
    pub span: Span,
}

/// Source-level scalar parameter.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstParameter {
    /// Written type.
    pub ty: AstType,
    /// Source name.
    pub name: String,
    /// Declaration span.
    pub span: Span,
}

/// Admitted source type spelling.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstType {
    /// Optional module qualifier; imported types never enter unqualified scope.
    pub module: Option<String>,
    /// Exact final source spelling, resolved and canonicalized during semantics.
    pub name: String,
    /// Type-token provenance.
    pub span: Span,
}

/// Lexical statement block.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstBlock {
    /// Statements in source order.
    pub statements: Vec<AstStmt>,
    /// Delimiter-inclusive span.
    pub span: Span,
}

/// Spanned source statement.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstStmt {
    /// Statement form.
    pub kind: AstStmtKind,
    /// Source span.
    pub span: Span,
}

/// Source statement forms admitted by the scalar verticals.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum AstStmtKind {
    /// Explicitly typed and initialized local.
    Local {
        ty: AstType,
        name: String,
        initializer: AstExpr,
    },
    /// Assignment to a local or nested field place.
    Assign { place: AstPlace, value: AstExpr },
    /// Conditional statement.
    If {
        condition: AstExpr,
        then_block: AstBlock,
        else_block: Option<AstBlock>,
    },
    /// Pre-test loop.
    While { condition: AstExpr, body: AstBlock },
    /// Value return.
    Return(AstExpr),
}

/// Source-level assignable place. Resolution assigns semantic field identities.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstPlace {
    /// Root local spelling.
    pub root: String,
    /// Nested field spellings and their individual spans.
    pub fields: Vec<(String, Span)>,
    /// Complete place span.
    pub span: Span,
}

/// Spanned source expression.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstExpr {
    /// Expression form.
    pub kind: AstExprKind,
    /// Source span.
    pub span: Span,
}

/// Source expression forms.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub enum AstExprKind {
    /// Exact decimal spelling, not yet a host integer.
    Integer(String),
    /// Exact source spelling, not yet rounded to a concrete IEEE format.
    Float(String),
    /// Boolean literal.
    Bool(bool),
    /// Unresolved name.
    Name(String),
    /// Unresolved direct call.
    Call { callee: String, args: Vec<AstExpr> },
    /// Unresolved qualified direct call.
    QualifiedCall {
        module: String,
        function: String,
        args: Vec<AstExpr>,
    },
    /// Qualified value syntax retained so semantic analysis can reject it precisely.
    QualifiedName { module: String, member: String },
    /// Unresolved field projection.
    Field {
        base: Box<AstExpr>,
        name: String,
        name_span: Span,
    },
    /// Prefix operation.
    Unary {
        op: AstUnaryOp,
        operand: Box<AstExpr>,
    },
    /// Infix operation.
    Binary {
        op: AstBinaryOp,
        left: Box<AstExpr>,
        right: Box<AstExpr>,
    },
}

/// Prefix operators.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AstUnaryOp {
    /// Checked signed negation.
    Negate,
}

/// Infix operators.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AstBinaryOp {
    /// Checked integer addition.
    Add,
    /// Checked integer subtraction.
    Subtract,
    /// Checked integer multiplication.
    Multiply,
    /// Division; semantic analysis selects integer or IEEE behavior.
    Divide,
    /// Integer remainder.
    Remainder,
    /// Ordered comparison.
    Less,
    /// Ordered comparison.
    LessEqual,
    /// Ordered comparison.
    Greater,
    /// Ordered comparison.
    GreaterEqual,
    /// Equality.
    Equal,
    /// Inequality.
    NotEqual,
}
