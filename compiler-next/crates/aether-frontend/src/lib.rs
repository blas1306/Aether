//! Source-facing phases for the isolated Aether compiler.

mod ast;
mod diagnostic;
mod hir;
mod lexer;
mod parser;
mod types;

pub use ast::{
    AstAlias, AstBinaryOp, AstBlock, AstExpr, AstExprKind, AstFunction, AstImport, AstParameter,
    AstStmt, AstStmtKind, AstType, AstUnaryOp, ParsedAst,
};
pub use diagnostic::{Diagnostic, DiagnosticCategory, Phase, SourceFile, SourceId, Span};
pub use hir::{
    CastKind, CoercionKind, DeclaredProgram, FloatValue, FunctionId, FunctionSignature,
    HirBinaryOp, HirBlock, HirExpr, HirExprKind, HirFunction, HirLocal, HirParameter, HirStmt,
    HirStmtKind, HirUnaryOp, LocalId, ModuleId, ModuleInfo, ParameterSignature, ParsedModule,
    ParsedProgram, ResolvedImport, TypeAliasInfo, TypedHir, analyze, analyze_bodies,
    analyze_bodies_for_target, collect_program_signatures, collect_signatures, verify_hir,
};
pub use lexer::{Token, TokenKind, lex};
pub use parser::parse;
pub use types::{FloatType, IntegerType, TargetProperties, Type};

/// Lexes and parses one source file.
pub fn parse_source(source: &SourceFile) -> Result<ParsedAst, Vec<Diagnostic>> {
    let tokens = lex(source)?;
    parse(source, tokens)
}
