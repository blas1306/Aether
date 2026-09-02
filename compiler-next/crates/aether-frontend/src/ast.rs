//! Source-structured AST. It deliberately has no resolved identities or semantic types.

use crate::Span;

/// Parsed compilation unit. Construction is restricted to the parser.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParsedAst {
    pub(crate) imports: Vec<AstImport>,
    pub(crate) aliases: Vec<AstAlias>,
    pub(crate) structs: Vec<AstStruct>,
    pub(crate) enums: Vec<AstEnum>,
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

    /// Enum declarations in deterministic source order.
    #[must_use]
    pub fn enums(&self) -> &[AstEnum] {
        &self.enums
    }

    /// Deterministic inspection dump.
    #[must_use]
    pub fn dump(&self) -> String {
        format!(
            "imports: {:#?}\naliases: {:#?}\nstructs: {:#?}\nenums: {:#?}\nfunctions: {:#?}",
            self.imports, self.aliases, self.structs, self.enums, self.functions
        )
    }
}

/// Nominal tagged value declaration.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub struct AstEnum {
    pub name: String,
    pub generic_parameters: Vec<AstGenericParam>,
    pub variants: Vec<AstVariant>,
    pub span: Span,
}

/// One enum variant with positional payload type spellings.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub struct AstVariant {
    pub name: String,
    pub payloads: Vec<AstType>,
    pub span: Span,
}

/// Nominal value-aggregate declaration.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstStruct {
    /// Declared nominal name.
    pub name: String,
    /// Unconstrained type parameters in declaration order.
    pub generic_parameters: Vec<AstGenericParam>,
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
    /// Unconstrained type parameters in declaration order.
    pub generic_parameters: Vec<AstGenericParam>,
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
    /// Recursive generic application arguments.
    pub arguments: Vec<AstType>,
    /// Reference wrapper when this spelling is `ref T` or `ref mut T`.
    pub reference: Option<AstReferenceType>,
    /// Type-token provenance.
    pub span: Span,
}

/// Explicit non-owning source reference type.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstReferenceType {
    /// Referenced semantic type spelling.
    pub pointee: Box<AstType>,
    /// Write capability; this does not imply uniqueness.
    pub mutable: bool,
}

/// Source generic binder. Semantic identity is assigned during declaration
/// collection and never derives from this spelling.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstGenericParam {
    /// Source spelling used for resolution and diagnostics.
    pub name: String,
    /// Binder-token provenance.
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
    Assign { place: AstExpr, value: AstExpr },
    /// Conditional statement.
    If {
        condition: AstExpr,
        then_block: AstBlock,
        else_block: Option<AstBlock>,
    },
    /// Pre-test loop.
    While { condition: AstExpr, body: AstBlock },
    /// Exhaustive enum match with block arms.
    Match {
        scrutinee: AstExpr,
        arms: Vec<AstMatchArm>,
    },
    /// Value return.
    Return(AstExpr),
}

/// One source match arm.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub struct AstMatchArm {
    pub pattern: AstVariantPattern,
    pub body: AstBlock,
    pub span: Span,
}

/// Minimal qualified variant pattern with positional name bindings.
#[derive(Clone, Debug, PartialEq, Eq)]
#[allow(missing_docs)]
pub struct AstVariantPattern {
    pub module: Option<String>,
    pub enum_name: String,
    pub type_arguments: Vec<AstType>,
    pub variant: String,
    pub bindings: Vec<(String, Span)>,
    pub span: Span,
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
    Call {
        callee: String,
        type_arguments: Vec<AstType>,
        args: Vec<AstExpr>,
    },
    /// Unresolved qualified direct call.
    QualifiedCall {
        module: String,
        function: String,
        type_arguments: Vec<AstType>,
        args: Vec<AstExpr>,
        parenthesized: bool,
    },
    /// Qualified value syntax retained so semantic analysis can reject it precisely.
    QualifiedName { module: String, member: String },
    /// Three-part imported enum variant construction.
    VariantCall {
        module: String,
        enum_name: String,
        type_arguments: Vec<AstType>,
        variant: String,
        args: Vec<AstExpr>,
        parenthesized: bool,
    },
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
    /// Read through a non-owning reference; also forms a place in place context.
    Dereference,
    /// Shared/read-only borrow of an addressable place.
    BorrowShared,
    /// Writable borrow of an addressable place. It does not imply exclusivity.
    BorrowMutable,
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
