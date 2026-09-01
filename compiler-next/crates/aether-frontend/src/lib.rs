//! Source-facing phases for the isolated Aether compiler.

mod ast;
mod diagnostic;
mod hir;
mod lexer;
mod parser;

pub use ast::{
    AstBinaryOp, AstBlock, AstExpr, AstExprKind, AstFunction, AstImport, AstParameter, AstStmt,
    AstStmtKind, AstType, AstUnaryOp, ParsedAst,
};
pub use diagnostic::{Diagnostic, DiagnosticCategory, Phase, SourceFile, SourceId, Span};
pub use hir::{
    DeclaredProgram, FunctionId, FunctionSignature, HirBinaryOp, HirBlock, HirExpr, HirExprKind,
    HirFunction, HirLocal, HirParameter, HirStmt, HirStmtKind, HirUnaryOp, LocalId, ModuleId,
    ModuleInfo, ParameterSignature, ParsedModule, ParsedProgram, ResolvedImport, Type, TypedHir,
    analyze, analyze_bodies, collect_program_signatures, collect_signatures, verify_hir,
};
pub use lexer::{Token, TokenKind, lex};
pub use parser::parse;

/// Lexes and parses one source file.
pub fn parse_source(source: &SourceFile) -> Result<ParsedAst, Vec<Diagnostic>> {
    let tokens = lex(source)?;
    parse(source, tokens)
}
