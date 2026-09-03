//! Source-facing phases for the isolated Aether compiler.

mod ast;
mod diagnostic;
mod hir;
mod lexer;
mod parser;
mod types;

pub use ast::{
    AstAlias, AstBinaryOp, AstBlock, AstEnum, AstExpr, AstExprKind, AstField, AstFunction,
    AstGenericParam, AstImport, AstMatchArm, AstMatchMode, AstParameter, AstPlace,
    AstReferenceType, AstStmt, AstStmtKind, AstStruct, AstType, AstUnaryOp, AstVariant,
    AstVariantPattern, ParsedAst,
};
pub use diagnostic::{Diagnostic, DiagnosticCategory, Phase, SourceFile, SourceId, Span};
pub use hir::{
    CastKind, CoercionKind, DeclaredProgram, EnumInfo, FieldInfo, FloatValue, FunctionId,
    FunctionInstanceInfo, FunctionSignature, GenericHirFunction, GenericParamInfo, HirBinaryOp,
    HirBlock, HirCallTarget, HirDrop, HirExpr, HirExprKind, HirFunction, HirLocal, HirMatchArm,
    HirMatchBinding, HirParameter, HirPlace, HirPlaceBase, HirPlaceProjection, HirStmt,
    HirStmtKind, HirUnaryOp, LocalId, MatchMode, ModuleId, ModuleInfo, ParameterSignature,
    ParsedModule, ParsedProgram, ResolvedImport, StructInfo, TypeAliasInfo, TypeLayout, TypedHir,
    VariantInfo, VariantPayloadInfo, analyze, analyze_bodies, analyze_bodies_for_target,
    collect_program_signatures, collect_signatures, format_type, layout_of, verify_hir,
};
pub use lexer::{Token, TokenKind, lex};
pub use parser::parse;
pub use types::{
    EnumId, FieldId, FloatType, GenericOwner, GenericParamId, InstanceId, IntegerType, StructId,
    Substitution, TargetProperties, TypeArena, TypeArgsId, TypeData, TypeId, TypeProperties,
    VariantId,
};

/// Lexes and parses one source file.
pub fn parse_source(source: &SourceFile) -> Result<ParsedAst, Vec<Diagnostic>> {
    let tokens = lex(source)?;
    parse(source, tokens)
}
