//! Snapshot-local document symbol queries over validated semantic declaration facts.
#![allow(missing_docs)]

use std::sync::Arc;

use aether_frontend::{
    CompilerEntityId, DeclarationFact, DeclarationKind, LogicalDeclarationKey, ModuleId,
    SemanticFacts, SourceId, SourceUnitKey, Span, TypedHir,
};

use crate::{
    AnalysisCoverage, AnalysisFailure, AnalysisResult, AnalysisState, AnalysisValidity,
    DocumentVersion, EditorRange, RequestCompletion, RequestState, SemanticSnapshot,
    SourceIdentity, SourceTable,
};

/// Protocol-independent category of a source-facing declaration.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DocumentSymbolCategory {
    Function,
    Struct,
    Enum,
}

/// Exact source location of a document symbol in one immutable snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DocumentSymbolLocation {
    pub source: SourceIdentity,
    pub source_unit: Option<SourceUnitKey>,
    pub document_version: Option<DocumentVersion>,
    pub full_span: Span,
    pub selection_span: Span,
    pub full_range: EditorRange,
    pub selection_range: EditorRange,
    pub editable: bool,
}

/// One declaration exposed by the document-symbol service.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DocumentSymbol {
    /// Authoritative compiler identity, meaningful only with `snapshot`.
    pub entity: CompilerEntityId,
    /// Stamp which scopes all dense identities in this value.
    pub snapshot: crate::SnapshotStamp,
    pub name: Arc<str>,
    pub category: DocumentSymbolCategory,
    pub location: DocumentSymbolLocation,
    pub module: ModuleId,
    pub logical: Option<LogicalDeclarationKey>,
    /// Reserved for instrumented ownership relationships in later milestones.
    pub children: Vec<DocumentSymbol>,
}

/// Why document symbols cannot be produced for the requested analysis/source.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DocumentSymbolsUnavailable {
    AnalysisUnavailable(AnalysisState),
    SnapshotStale,
    Cancelled,
    TargetClosed,
    SourceChanged,
    InternalFailure,
    SourceNotFound(SourceId),
    SourceNotEditable(SourceIdentity),
}

/// A valid empty document is represented by `Available([])`, never `Unavailable`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DocumentSymbolResult {
    Available(Vec<DocumentSymbol>),
    Unavailable(DocumentSymbolsUnavailable),
}

impl SemanticSnapshot {
    /// Returns structural declarations owned by `source` in deterministic document order.
    #[must_use]
    pub fn document_symbols(&self, source: SourceId) -> DocumentSymbolResult {
        let Some(snapshot_source) = self.sources.get(source) else {
            return DocumentSymbolResult::Unavailable(DocumentSymbolsUnavailable::SourceNotFound(
                source,
            ));
        };
        let editable = !matches!(snapshot_source.identity, SourceIdentity::Toolchain(_));
        if !editable {
            return DocumentSymbolResult::Unavailable(
                DocumentSymbolsUnavailable::SourceNotEditable(snapshot_source.identity.clone()),
            );
        }

        let mut facts = self
            .facts()
            .declarations()
            .iter()
            .filter(|fact| fact.source == source)
            .collect::<Vec<_>>();
        facts.sort_by_key(|fact| {
            (
                fact.source,
                fact.full_span.start,
                fact.name_span.start,
                fact.entity,
            )
        });

        let mut symbols = Vec::with_capacity(facts.len());
        for fact in facts {
            let Ok(full_range) = snapshot_source.line_index.span_to_range(fact.full_span) else {
                return DocumentSymbolResult::Unavailable(
                    DocumentSymbolsUnavailable::InternalFailure,
                );
            };
            let Ok(selection_range) = snapshot_source.line_index.span_to_range(fact.name_span)
            else {
                return DocumentSymbolResult::Unavailable(
                    DocumentSymbolsUnavailable::InternalFailure,
                );
            };
            if fact.full_span.source != source
                || fact.name_span.source != source
                || fact.full_span.start > fact.name_span.start
                || fact.name_span.end > fact.full_span.end
            {
                return DocumentSymbolResult::Unavailable(
                    DocumentSymbolsUnavailable::InternalFailure,
                );
            }
            symbols.push(DocumentSymbol {
                entity: fact.entity,
                snapshot: self.stamp().clone(),
                name: Arc::from(fact.name.as_str()),
                category: match fact.kind {
                    DeclarationKind::Function => DocumentSymbolCategory::Function,
                    DeclarationKind::Struct => DocumentSymbolCategory::Struct,
                    DeclarationKind::Enum => DocumentSymbolCategory::Enum,
                },
                location: DocumentSymbolLocation {
                    source: snapshot_source.identity.clone(),
                    source_unit: snapshot_source.unit.clone(),
                    document_version: snapshot_source.document_version,
                    full_span: fact.full_span,
                    selection_span: fact.name_span,
                    full_range,
                    selection_range,
                    editable,
                },
                module: fact.module,
                logical: fact.logical.clone(),
                children: Vec::new(),
            });
        }
        DocumentSymbolResult::Available(symbols)
    }
}

impl AnalysisResult {
    /// Queries only a complete, valid semantic snapshot from this exact analysis result.
    #[must_use]
    pub fn document_symbols(&self, source: SourceId) -> DocumentSymbolResult {
        let valid = self.state
            == (AnalysisState {
                coverage: AnalysisCoverage::Complete,
                validity: AnalysisValidity::Valid,
            });
        if !valid {
            return DocumentSymbolResult::Unavailable(
                DocumentSymbolsUnavailable::AnalysisUnavailable(self.state),
            );
        }
        match &self.semantic {
            Some(snapshot) if snapshot.stamp() == &self.stamp => snapshot.document_symbols(source),
            _ => DocumentSymbolResult::Unavailable(DocumentSymbolsUnavailable::InternalFailure),
        }
    }
}

impl RequestCompletion {
    /// Applies lifecycle publication gates before exposing document symbols.
    #[must_use]
    pub fn document_symbols(&self, source: SourceId) -> DocumentSymbolResult {
        match self.state {
            RequestState::Published => self.result.as_ref().map_or_else(
                || DocumentSymbolResult::Unavailable(DocumentSymbolsUnavailable::InternalFailure),
                |result| result.document_symbols(source),
            ),
            RequestState::Stale => {
                DocumentSymbolResult::Unavailable(DocumentSymbolsUnavailable::SnapshotStale)
            }
            RequestState::Cancelled => {
                DocumentSymbolResult::Unavailable(DocumentSymbolsUnavailable::Cancelled)
            }
            RequestState::TargetClosed => {
                DocumentSymbolResult::Unavailable(DocumentSymbolsUnavailable::TargetClosed)
            }
            RequestState::SourceChanged => {
                DocumentSymbolResult::Unavailable(DocumentSymbolsUnavailable::SourceChanged)
            }
            RequestState::InternalFailure | RequestState::Queued | RequestState::Running => {
                DocumentSymbolResult::Unavailable(DocumentSymbolsUnavailable::InternalFailure)
            }
        }
    }
}

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

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicU64, Ordering};

    use crate::{
        AnalysisRequest, AnalysisTarget, CancellationToken, CanonicalAnalyzer, ChangeDocument,
        DocumentLocator, EditorPosition, EditorWorkspace, OpenDocument, RequestId,
    };

    static NEXT_TEST: AtomicU64 = AtomicU64::new(1);

    struct TestProject {
        root: PathBuf,
        workspace: EditorWorkspace,
        document: crate::DocumentId,
    }

    impl TestProject {
        fn new(text: &str) -> Self {
            let root = std::env::temp_dir().join(format!(
                "aether-document-symbols-{}-{}",
                std::process::id(),
                NEXT_TEST.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&root).unwrap();
            let entry = root.join("main.ae");
            fs::write(&entry, text).unwrap();
            let workspace = EditorWorkspace::new(&root).unwrap();
            let document = workspace
                .open(OpenDocument {
                    locator: DocumentLocator::file(&entry).unwrap(),
                    text: Arc::from(text),
                    client_version: Some(1),
                    project: None,
                })
                .unwrap();
            Self {
                root,
                workspace,
                document,
            }
        }

        fn write(&self, name: &str, text: &str) -> PathBuf {
            let path = self.root.join(name);
            fs::write(&path, text).unwrap();
            path
        }

        fn open(&self, path: &Path, text: &str, version: i64) -> crate::DocumentId {
            self.workspace
                .open(OpenDocument {
                    locator: DocumentLocator::file(path).unwrap(),
                    text: Arc::from(text),
                    client_version: Some(version),
                    project: None,
                })
                .unwrap()
        }

        fn analyze(&self, request: u64) -> AnalysisResult {
            CanonicalAnalyzer
                .analyze(AnalysisRequest {
                    id: RequestId(request),
                    target: AnalysisTarget::Document(self.document),
                    snapshot: self.workspace.snapshot(),
                    cancellation: CancellationToken::new(),
                })
                .unwrap()
        }
    }

    impl Drop for TestProject {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    fn available(result: DocumentSymbolResult) -> Vec<DocumentSymbol> {
        let DocumentSymbolResult::Available(symbols) = result else {
            panic!("expected available document symbols, got {result:?}");
        };
        symbols
    }

    fn source_for(result: &AnalysisResult, identity: &SourceIdentity) -> SourceId {
        result
            .semantic
            .as_ref()
            .unwrap_or_else(|| {
                panic!(
                    "expected semantic snapshot, state={:?}, diagnostics={:?}",
                    result.state, result.diagnostics
                )
            })
            .sources
            .iter()
            .find(|source| &source.identity == identity)
            .unwrap()
            .source_id
    }

    #[test]
    fn structural_declarations_keep_categories_hierarchy_ranges_and_official_identity() {
        let text = "// é e\u{301} 😀\r\nstruct Box<T>{int value;}\r\nenum Choice{One,Two}\r\nint helper<T>(T value){return 1;}\r\nint main(){return helper<int>(1);}";
        let project = TestProject::new(text);
        let result = project.analyze(1);
        let source = source_for(&result, &SourceIdentity::Document(project.document));
        let facts = result
            .semantic
            .as_ref()
            .unwrap()
            .facts()
            .declarations()
            .iter()
            .filter(|fact| fact.source == source)
            .cloned()
            .collect::<Vec<_>>();
        let symbols = available(result.document_symbols(source));

        assert_eq!(
            symbols
                .iter()
                .map(|symbol| symbol.name.as_ref())
                .collect::<Vec<_>>(),
            ["Box", "Choice", "helper", "main"]
        );
        assert_eq!(
            symbols
                .iter()
                .map(|symbol| symbol.category)
                .collect::<Vec<_>>(),
            [
                DocumentSymbolCategory::Struct,
                DocumentSymbolCategory::Enum,
                DocumentSymbolCategory::Function,
                DocumentSymbolCategory::Function,
            ]
        );
        for (symbol, fact) in symbols.iter().zip(facts) {
            assert_eq!(symbol.entity, fact.entity);
            assert_eq!(symbol.module, fact.module);
            assert_eq!(symbol.logical, fact.logical);
            assert_eq!(symbol.location.full_span, fact.full_span);
            assert_eq!(symbol.location.selection_span, fact.name_span);
            assert!(symbol.children.is_empty());
            assert_eq!(symbol.snapshot, result.stamp);
            assert_eq!(symbol.location.document_version, Some(DocumentVersion(1)));
        }
        assert_eq!(
            symbols[0].location.selection_range.start,
            EditorPosition {
                line: 1,
                character: 7,
            }
        );
    }

    #[test]
    fn functions_overloads_generics_and_synthetics_are_handled_without_name_deduplication() {
        let text = "int value(int x){return x;} int value(float64 x){return 2;} int helper<T>(T x){return 1;} int main(){var f=()=>1;return helper<int>(1);}";
        let project = TestProject::new(text);
        let result = project.analyze(2);
        let source = source_for(&result, &SourceIdentity::Document(project.document));
        let first = available(result.document_symbols(source));
        let second = available(result.document_symbols(source));
        assert_eq!(first, second);
        assert_eq!(
            first
                .iter()
                .map(|symbol| symbol.name.as_ref())
                .collect::<Vec<_>>(),
            ["value", "value", "helper", "main"]
        );
        assert_ne!(first[0].entity, first[1].entity);
        assert!(first.iter().all(|symbol| !symbol.name.starts_with('$')));
        assert!(first.iter().all(|symbol| symbol.logical.is_some()));
    }

    #[test]
    fn empty_document_is_available_but_invalid_analysis_is_unavailable() {
        let test = TestProject::new("import Empty; int main(){return 0;}");
        let empty_text = "package Empty; // no declarations\n";
        let empty_path = test.write("empty.ae", empty_text);
        let empty_document = test.open(&empty_path, empty_text, 1);
        let valid = test.analyze(3);
        let source = source_for(&valid, &SourceIdentity::Document(empty_document));
        assert_eq!(
            valid.document_symbols(source),
            DocumentSymbolResult::Available(Vec::new())
        );

        test.workspace
            .change(ChangeDocument {
                document: test.document,
                text: Arc::from("int broken( { return 0; }"),
                client_version: Some(2),
            })
            .unwrap();
        let invalid = test.analyze(4);
        assert!(matches!(
            invalid.document_symbols(source),
            DocumentSymbolResult::Unavailable(DocumentSymbolsUnavailable::AnalysisUnavailable(
                AnalysisState {
                    coverage: AnalysisCoverage::Partial { .. },
                    validity: AnalysisValidity::Invalid,
                }
            ))
        ));

        test.workspace
            .change(ChangeDocument {
                document: test.document,
                text: Arc::from("int main(){return missing;}"),
                client_version: Some(3),
            })
            .unwrap();
        let semantic_error = test.analyze(40);
        assert!(matches!(
            semantic_error.document_symbols(source),
            DocumentSymbolResult::Unavailable(DocumentSymbolsUnavailable::AnalysisUnavailable(
                AnalysisState {
                    coverage: AnalysisCoverage::Partial {
                        reached: crate::AnalysisStage::Semantic,
                        ..
                    },
                    validity: AnalysisValidity::Invalid,
                }
            ))
        ));
    }

    #[test]
    fn imported_declarations_stay_with_their_source_and_equal_names_remain_distinct() {
        let entry = "import Alpha; import Beta; int value(){return Alpha.value()+Beta.value();} int main(){return value();}";
        let test = TestProject::new(entry);
        let alpha_text = "package Alpha; public int value(){return 1;}";
        let beta_text = "package Beta; public int value(){return 2;}";
        let alpha_path = test.write("alpha.ae", alpha_text);
        let beta_path = test.write("beta.ae", beta_text);
        let alpha_document = test.open(&alpha_path, alpha_text, 4);
        let beta_document = test.open(&beta_path, beta_text, 5);
        let result = test.analyze(5);
        let entry_source = source_for(&result, &SourceIdentity::Document(test.document));
        let alpha_source = source_for(&result, &SourceIdentity::Document(alpha_document));
        let beta_source = source_for(&result, &SourceIdentity::Document(beta_document));

        let entry_symbols = available(result.document_symbols(entry_source));
        let alpha_symbols = available(result.document_symbols(alpha_source));
        let beta_symbols = available(result.document_symbols(beta_source));
        assert_eq!(
            entry_symbols
                .iter()
                .map(|symbol| symbol.name.as_ref())
                .collect::<Vec<_>>(),
            ["value", "main"]
        );
        assert_eq!(alpha_symbols[0].name.as_ref(), "value");
        assert_eq!(beta_symbols[0].name.as_ref(), "value");
        assert_ne!(alpha_symbols[0].module, beta_symbols[0].module);
        assert_ne!(alpha_symbols[0].entity, beta_symbols[0].entity);
        assert_eq!(
            alpha_symbols[0].location.document_version,
            Some(DocumentVersion(1))
        );
        assert_eq!(
            beta_symbols[0].location.document_version,
            Some(DocumentVersion(1))
        );
    }

    #[test]
    fn overlay_edits_create_new_stamps_versions_and_positions() {
        let test = TestProject::new("int main(){return 0;}");
        let first = test.analyze(6);
        let source = source_for(&first, &SourceIdentity::Document(test.document));
        let first_symbol = available(first.document_symbols(source)).remove(0);

        test.workspace
            .change(ChangeDocument {
                document: test.document,
                text: Arc::from("\n\nint main(){return 1;}"),
                client_version: Some(9),
            })
            .unwrap();
        let second = test.analyze(7);
        let second_source = source_for(&second, &SourceIdentity::Document(test.document));
        let second_symbol = available(second.document_symbols(second_source)).remove(0);
        assert_ne!(first_symbol.snapshot, second_symbol.snapshot);
        assert_eq!(
            second_symbol.location.document_version,
            Some(DocumentVersion(2))
        );
        assert_eq!(second_symbol.location.selection_range.start.line, 2);
        assert!(second_symbol.location.full_span.start > first_symbol.location.full_span.start);
    }

    #[test]
    fn unknown_and_non_editable_sources_are_explicitly_unavailable() {
        let test = TestProject::new("import std.Format; int main(){return 0;}");
        let result = test.analyze(8);
        assert_eq!(
            result.document_symbols(SourceId(u32::MAX)),
            DocumentSymbolResult::Unavailable(DocumentSymbolsUnavailable::SourceNotFound(
                SourceId(u32::MAX)
            ))
        );
        if let Some(toolchain) = result
            .semantic
            .as_ref()
            .unwrap()
            .sources
            .iter()
            .find(|source| matches!(source.identity, SourceIdentity::Toolchain(_)))
        {
            assert!(matches!(
                result.document_symbols(toolchain.source_id),
                DocumentSymbolResult::Unavailable(DocumentSymbolsUnavailable::SourceNotEditable(
                    SourceIdentity::Toolchain(_)
                ))
            ));
        }
    }

    #[test]
    fn lifecycle_states_never_fall_back_to_empty_or_old_symbols() {
        for (state, reason) in [
            (
                RequestState::Stale,
                DocumentSymbolsUnavailable::SnapshotStale,
            ),
            (
                RequestState::Cancelled,
                DocumentSymbolsUnavailable::Cancelled,
            ),
            (
                RequestState::TargetClosed,
                DocumentSymbolsUnavailable::TargetClosed,
            ),
            (
                RequestState::SourceChanged,
                DocumentSymbolsUnavailable::SourceChanged,
            ),
            (
                RequestState::InternalFailure,
                DocumentSymbolsUnavailable::InternalFailure,
            ),
        ] {
            let completion = RequestCompletion {
                request: RequestId(99),
                state,
                result: None,
                failure: None,
            };
            assert_eq!(
                completion.document_symbols(SourceId(0)),
                DocumentSymbolResult::Unavailable(reason)
            );
        }
    }
}
