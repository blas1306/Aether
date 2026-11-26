//! Validation boundary for source-facing semantic declaration facts.

use std::sync::Arc;

use aether_frontend::{
    CompilerEntityId, DeclarationFact, DeclarationKind, LogicalDeclarationKey, SemanticFacts,
    TypedHir,
};

use crate::{AnalysisFailure, SourceTable};

pub(crate) fn validate_declaration_facts(
    facts: &SemanticFacts,
    hir: &TypedHir,
    sources: &SourceTable,
) -> Result<Arc<SemanticFacts>, AnalysisFailure> {
    for fact in facts.declarations() {
        validate_fact(fact, hir, sources)?;
    }
    Ok(Arc::new(facts.clone()))
}

fn invalid(fact: &DeclarationFact, reason: impl AsRef<str>) -> AnalysisFailure {
    AnalysisFailure::Internal(format!(
        "invalid declaration fact {:?}: {}",
        fact.entity,
        reason.as_ref()
    ))
}

fn validate_fact(
    fact: &DeclarationFact,
    hir: &TypedHir,
    sources: &SourceTable,
) -> Result<(), AnalysisFailure> {
    if fact.full_span.source != fact.source || fact.name_span.source != fact.source {
        return Err(invalid(fact, "spans do not share the declared source"));
    }
    if fact.full_span.start > fact.name_span.start
        || fact.name_span.end > fact.full_span.end
        || fact.name_span.start > fact.name_span.end
    {
        return Err(invalid(fact, "name span is not contained in full span"));
    }
    let source = sources
        .get(fact.source)
        .ok_or_else(|| invalid(fact, "unknown SourceId"))?;
    source
        .line_index
        .span_to_range(fact.full_span)
        .map_err(|error| invalid(fact, format!("invalid full span: {error}")))?;
    source
        .line_index
        .span_to_range(fact.name_span)
        .map_err(|error| invalid(fact, format!("invalid name span: {error}")))?;
    if source.text.get(fact.name_span.start..fact.name_span.end) != Some(fact.name.as_str()) {
        return Err(invalid(
            fact,
            "name span does not contain the declared name",
        ));
    }

    let module = hir
        .modules()
        .get(fact.module.0 as usize)
        .filter(|module| module.id == fact.module)
        .ok_or_else(|| invalid(fact, "unknown ModuleId"))?;
    if module.source != fact.source {
        return Err(invalid(fact, "module source does not match fact source"));
    }
    if source.unit.as_ref() != Some(&module.key) {
        return Err(invalid(fact, "module key does not match source catalog"));
    }
    if fact.owner != Some(CompilerEntityId::Module(fact.module)) {
        return Err(invalid(fact, "top-level declaration has invalid owner"));
    }

    match (fact.kind, fact.entity) {
        (DeclarationKind::Function, CompilerEntityId::Function(id)) => {
            let signature = hir
                .signatures()
                .get(id.0 as usize)
                .filter(|signature| signature.id == id)
                .ok_or_else(|| invalid(fact, "unknown FunctionId"))?;
            if signature.module != fact.module
                || signature.name != fact.name
                || signature.span != fact.full_span
            {
                return Err(invalid(fact, "function identity metadata mismatch"));
            }
            let expected =
                LogicalDeclarationKey::PackageMember(signature.symbol_key(hir.modules()));
            if fact.logical.as_ref() != Some(&expected) {
                return Err(invalid(fact, "function logical key mismatch"));
            }
        }
        (DeclarationKind::Struct, CompilerEntityId::Struct(id)) => {
            let info = hir
                .structs()
                .get(id.0 as usize)
                .filter(|info| info.id == id)
                .ok_or_else(|| invalid(fact, "unknown StructId"))?;
            if info.module != fact.module
                || info.name != fact.name
                || info.span != fact.full_span
                || fact.logical.is_some()
            {
                return Err(invalid(fact, "struct identity metadata mismatch"));
            }
        }
        (DeclarationKind::Enum, CompilerEntityId::Enum(id)) => {
            let info = hir
                .enums()
                .get(id.0 as usize)
                .filter(|info| info.id == id)
                .ok_or_else(|| invalid(fact, "unknown EnumId"))?;
            if info.module != fact.module
                || info.name != fact.name
                || info.span != fact.full_span
                || fact.logical.is_some()
            {
                return Err(invalid(fact, "enum identity metadata mismatch"));
            }
        }
        _ => return Err(invalid(fact, "declaration kind/entity mismatch")),
    }
    Ok(())
}
