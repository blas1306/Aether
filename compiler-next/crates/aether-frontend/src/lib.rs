//! Source-facing phases for the isolated Aether compiler.

mod ast;
mod core;
mod diagnostic;
mod hir;
mod interfaces;
mod lexer;
mod oop;
pub use interfaces::*;
mod parser;
mod strings;
mod text;
mod types;
pub use oop::*;

pub use ast::{
    AstAlias, AstBinaryOp, AstBlock, AstCapabilityConstraint, AstCatch, AstEnum, AstExpr,
    AstExprKind, AstField, AstForBinding, AstFunction, AstGenericParam, AstImport,
    AstInterpolationFragment, AstMatchArm, AstMatchMode, AstPackage, AstParameter, AstPlace,
    AstReferenceType, AstStmt, AstStmtKind, AstStruct, AstType, AstUnaryOp, AstVariant,
    AstVariantPattern, ParsedAst,
};
pub use core::{
    CORE_V1_PROFILE, CoreCall, CoreFunction, CoreSymbol, CoreSymbolKey, PRELUDE_V1, prelude_symbol,
    verify_core_call,
};
pub use diagnostic::{Diagnostic, DiagnosticCategory, FixIt, Phase, SourceFile, SourceId, Span};
pub use hir::{
    AlgebraicProductKind, CallBorrowOrigin, CallBorrowSource, CallSiteId, CastKind, CatchId,
    CoercionKind, CollectionIterationSource, DeclaredProgram, EnumInfo, FieldInfo, FinallyId,
    FloatValue, FunctionId, FunctionInstanceInfo, FunctionSignature, GenericHirFunction,
    GenericParamInfo, HirBinaryOp, HirBlock, HirCallTarget, HirCatch, HirDrop, HirExpr,
    HirExprKind, HirFinally, HirFunction, HirLocal, HirMatchArm, HirMatchBinding, HirParameter,
    HirPlace, HirPlaceBase, HirPlaceProjection, HirStmt, HirStmtKind, HirUnaryOp,
    InvalidationShape, IterationBindingCategory, LocalId, LogicalSourceKey, LoopId, MatchMode,
    MathElementOp, MathShapeCheck, MatrixProductExtent, ModuleId, ModuleInfo, MutationEffect,
    OriginKey, PackageId, PackageKey, PackagePath, ParameterSignature, ParsedModule, ParsedProgram,
    ResolvedImport, ScalarSide, SourceUnitKey, StructInfo, StructuralMutation, SymbolKey,
    TypeAliasInfo, TypeLayout, TypedHir, VariantInfo, VariantPayloadInfo, analyze, analyze_bodies,
    analyze_bodies_for_target, collect_program_signatures, collect_signatures, format_type,
    layout_of, verify_hir,
};
pub use lexer::{Token, TokenKind, lex};
pub use parser::parse;
pub use strings::{
    InterpolationConversion, InterpolationFragment, InterpolationSizePlan, StringOp,
    StringOwnership, verify_string_op,
};
pub use text::{TextOp, verify_text_op};
pub use types::{
    AlgebraicCapability, BehavioralCapability, Capability, CollectionElementAdmission,
    CollectionKind, EnumId, FieldId, FloatType, GenericOwner, GenericParamId, IndexSemantics,
    InstanceId, IntegerType, MatrixAxisVectorViewDescriptor, MatrixViewDescriptor, MatrixViewField,
    Orientation, StructId, Substitution, TargetProperties, TypeArena, TypeArgsId, TypeData, TypeId,
    TypeProperties, VariantId, VectorViewDescriptor, VectorViewField,
};

/// Lexes and parses one source file.
pub fn parse_source(source: &SourceFile) -> Result<ParsedAst, Vec<Diagnostic>> {
    let tokens = lex(source)?;
    parse(source, tokens)
}
