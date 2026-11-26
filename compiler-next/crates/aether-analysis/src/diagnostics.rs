//! Snapshot-local source mapping and frontend-only editor diagnostics.
#![allow(missing_docs)]

use std::fmt;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use aether_frontend::{
    Diagnostic, DiagnosticCategory, Phase, SourceId, SourceUnitKey, Span, TargetProperties,
    TypedHir, analyze_bodies_for_target, collect_library_program_signatures,
    collect_program_signatures, verify_hir,
};
use aether_package::ProjectKind;

use crate::{
    AnalysisSnapshot, AssignedSource, ContentFingerprint, DocumentId, DocumentVersion, ProjectId,
    SnapshotStamp, SourceProvenance, discover_catalog_with_provider_traced,
};

/// Stable identity used to present one exact snapshot source to an editor.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum SourceIdentity {
    /// A document tracked by the workspace.
    Document(DocumentId),
    /// A source read from the filesystem but not open in the editor.
    Disk(PathBuf),
    /// An immutable compiler-owned source.
    Toolchain(Arc<str>),
}

/// A zero-based editor position measured in UTF-16 code units.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EditorPosition {
    pub line: u32,
    pub character: u32,
}

/// A half-open editor range.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EditorRange {
    pub start: EditorPosition,
    pub end: EditorPosition,
}

/// Invalid conversion between UTF-8 bytes and UTF-16 editor coordinates.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LineIndexError {
    OffsetOutOfRange(usize),
    NotUtf8Boundary(usize),
    LineOutOfRange(u32),
    CharacterOutOfRange { line: u32, character: u32 },
    SplitsSurrogatePair { line: u32, character: u32 },
    ReversedRange,
}

impl fmt::Display for LineIndexError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for LineIndexError {}

/// Validated mapping over the original, unnormalised UTF-8 text.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LineIndex {
    text: Arc<str>,
    starts: Arc<[usize]>,
    ends: Arc<[usize]>,
}

impl LineIndex {
    #[must_use]
    pub fn new(text: Arc<str>) -> Self {
        let bytes = text.as_bytes();
        let mut starts = vec![0];
        let mut ends = Vec::new();
        for (index, byte) in bytes.iter().copied().enumerate() {
            if byte == b'\n' {
                let logical_end = if index > 0 && bytes[index - 1] == b'\r' {
                    index - 1
                } else {
                    index
                };
                ends.push(logical_end);
                starts.push(index + 1);
            }
        }
        ends.push(bytes.len());
        Self {
            text,
            starts: starts.into(),
            ends: ends.into(),
        }
    }

    #[must_use]
    pub fn text(&self) -> &str {
        &self.text
    }

    pub fn byte_to_position(&self, offset: usize) -> Result<EditorPosition, LineIndexError> {
        if offset > self.text.len() {
            return Err(LineIndexError::OffsetOutOfRange(offset));
        }
        if !self.text.is_char_boundary(offset) {
            return Err(LineIndexError::NotUtf8Boundary(offset));
        }
        let line = self.starts.partition_point(|start| *start <= offset) - 1;
        let bounded = offset.min(self.ends[line]);
        let character = self.text[self.starts[line]..bounded]
            .chars()
            .map(char::len_utf16)
            .sum::<usize>();
        Ok(EditorPosition {
            line: u32::try_from(line).expect("source line count fits u32"),
            character: u32::try_from(character).expect("source line length fits u32"),
        })
    }

    pub fn position_to_byte(&self, position: EditorPosition) -> Result<usize, LineIndexError> {
        let line = usize::try_from(position.line).expect("u32 fits usize");
        let Some((&start, &end)) = self.starts.get(line).zip(self.ends.get(line)) else {
            return Err(LineIndexError::LineOutOfRange(position.line));
        };
        let target = usize::try_from(position.character).expect("u32 fits usize");
        let mut utf16 = 0;
        for (relative, character) in self.text[start..end].char_indices() {
            if utf16 == target {
                return Ok(start + relative);
            }
            let next = utf16 + character.len_utf16();
            if target < next {
                return Err(LineIndexError::SplitsSurrogatePair {
                    line: position.line,
                    character: position.character,
                });
            }
            utf16 = next;
        }
        if utf16 == target {
            Ok(end)
        } else {
            Err(LineIndexError::CharacterOutOfRange {
                line: position.line,
                character: position.character,
            })
        }
    }

    pub fn span_to_range(&self, span: Span) -> Result<EditorRange, LineIndexError> {
        if span.start > span.end {
            return Err(LineIndexError::ReversedRange);
        }
        Ok(EditorRange {
            start: self.byte_to_position(span.start)?,
            end: self.byte_to_position(span.end)?,
        })
    }
}

/// Exact source record owned by one frontend session.
#[derive(Clone, Debug)]
pub struct SnapshotSource {
    pub source_id: SourceId,
    pub identity: SourceIdentity,
    pub document_version: Option<DocumentVersion>,
    pub unit: Option<SourceUnitKey>,
    pub text: Arc<str>,
    pub fingerprint: ContentFingerprint,
    pub line_index: Arc<LineIndex>,
}

/// `SourceId` mapping that never falls back to display names.
#[derive(Clone, Debug, Default)]
pub struct SourceTable {
    by_id: Vec<Option<SnapshotSource>>,
}

impl SourceTable {
    fn insert(&mut self, source: SnapshotSource) -> Result<(), AnalysisFailure> {
        let index = source.source_id.0 as usize;
        if self.by_id.len() <= index {
            self.by_id.resize_with(index + 1, || None);
        }
        if self.by_id[index].replace(source).is_some() {
            return Err(AnalysisFailure::Internal(
                "duplicate SourceId in session".into(),
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn get(&self, source: SourceId) -> Option<&SnapshotSource> {
        self.by_id.get(source.0 as usize).and_then(Option::as_ref)
    }

    pub fn iter(&self) -> impl Iterator<Item = &SnapshotSource> {
        self.by_id.iter().filter_map(Option::as_ref)
    }
}

fn identity(provenance: &SourceProvenance) -> (SourceIdentity, Option<DocumentVersion>) {
    match provenance {
        SourceProvenance::Overlay { document, version } => {
            (SourceIdentity::Document(*document), Some(*version))
        }
        SourceProvenance::Disk { canonical_path, .. } => {
            (SourceIdentity::Disk(canonical_path.clone()), None)
        }
        SourceProvenance::Toolchain { logical_name, .. } => {
            (SourceIdentity::Toolchain(Arc::clone(logical_name)), None)
        }
    }
}

fn table_from_session(session: &crate::CompilationSession) -> Result<SourceTable, AnalysisFailure> {
    let mut table = SourceTable::default();
    for module in session.modules() {
        let text: Arc<str> = Arc::from(module.source().text.as_str());
        let (identity, document_version) = identity(module.provenance());
        table.insert(SnapshotSource {
            source_id: module.source().id,
            identity,
            document_version,
            unit: Some(module.info().key.clone()),
            line_index: Arc::new(LineIndex::new(Arc::clone(&text))),
            text,
            fingerprint: module.fingerprint(),
        })?;
    }
    Ok(table)
}

/// Explicit severity; all current frontend diagnostics are errors.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DiagnosticSeverity {
    Error,
    Warning,
    Information,
    Hint,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RelatedInformation {
    pub source: SourceIdentity,
    pub range: EditorRange,
    pub message: Arc<str>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EditorFix {
    pub source: SourceIdentity,
    pub range: EditorRange,
    pub replacement: Arc<str>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EditorDiagnostic {
    pub source: Option<SourceIdentity>,
    pub range: Option<EditorRange>,
    pub source_name: Option<Arc<str>>,
    pub code: Arc<str>,
    pub severity: DiagnosticSeverity,
    pub phase: Phase,
    pub category: DiagnosticCategory,
    pub message: Arc<str>,
    pub related: Vec<RelatedInformation>,
    pub fixes: Vec<EditorFix>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AdaptationFailure {
    InvalidFix {
        code: Arc<str>,
        error: LineIndexError,
    },
}

fn adapt_diagnostics(
    diagnostics: Vec<Diagnostic>,
    sources: &SourceTable,
    failures: &mut Vec<AdaptationFailure>,
) -> Result<Vec<EditorDiagnostic>, AnalysisFailure> {
    diagnostics
        .into_iter()
        .map(|diagnostic| {
            let (source, range) = if let Some(span) = diagnostic.span {
                let mapped = sources.get(span.source).ok_or_else(|| {
                    AnalysisFailure::Internal(format!(
                        "diagnostic {} references unknown SourceId {}",
                        diagnostic.code, span.source.0
                    ))
                })?;
                let range = mapped.line_index.span_to_range(span).map_err(|error| {
                    AnalysisFailure::Internal(format!(
                        "diagnostic {} has invalid primary span: {error}",
                        diagnostic.code
                    ))
                })?;
                (Some(mapped.identity.clone()), Some(range))
            } else {
                (None, None)
            };
            let mut fixes = Vec::new();
            for fix in &diagnostic.fixits {
                let Some(mapped) = sources.get(fix.span.source) else {
                    failures.push(AdaptationFailure::InvalidFix {
                        code: Arc::from(diagnostic.code),
                        error: LineIndexError::OffsetOutOfRange(fix.span.start),
                    });
                    continue;
                };
                match mapped.line_index.span_to_range(fix.span) {
                    Ok(range) => fixes.push(EditorFix {
                        source: mapped.identity.clone(),
                        range,
                        replacement: Arc::from(fix.replacement.as_str()),
                    }),
                    Err(error) => failures.push(AdaptationFailure::InvalidFix {
                        code: Arc::from(diagnostic.code),
                        error,
                    }),
                }
            }
            Ok(EditorDiagnostic {
                source,
                range,
                source_name: diagnostic.source_name.as_deref().map(Arc::from),
                code: Arc::from(diagnostic.code),
                severity: DiagnosticSeverity::Error,
                phase: diagnostic.phase,
                category: diagnostic.category,
                message: Arc::from(diagnostic.message),
                related: Vec::new(),
                fixes,
            })
        })
        .collect()
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct RequestId(pub u64);

#[derive(Clone, Debug)]
pub enum AnalysisTarget {
    Document(DocumentId),
    Project(ProjectId),
    Path {
        entry: PathBuf,
        project: Option<ProjectId>,
    },
}

#[derive(Clone, Debug)]
pub struct AnalysisRequest {
    pub id: RequestId,
    pub target: AnalysisTarget,
    pub snapshot: AnalysisSnapshot,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AnalysisStage {
    Input,
    Lex,
    Parse,
    Declarations,
    Semantic,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PartialReason {
    FrontendStopped,
    MissingInput,
    InternalFailure,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AnalysisCoverage {
    Complete,
    Partial {
        reached: AnalysisStage,
        reason: PartialReason,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AnalysisValidity {
    Valid,
    Invalid,
    Unknown,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AnalysisState {
    pub coverage: AnalysisCoverage,
    pub validity: AnalysisValidity,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct AnalysisMeasurements {
    pub discovery_ns: u128,
    pub declarations_ns: u128,
    pub semantic_ns: u128,
    pub verification_ns: u128,
}

#[derive(Debug)]
pub struct SemanticSnapshot {
    pub sources: Arc<SourceTable>,
    hir: TypedHir,
}

impl SemanticSnapshot {
    #[must_use]
    pub const fn hir(&self) -> &TypedHir {
        &self.hir
    }
}

#[derive(Debug)]
pub struct AnalysisResult {
    pub request: RequestId,
    pub stamp: SnapshotStamp,
    pub state: AnalysisState,
    pub diagnostics: Vec<EditorDiagnostic>,
    pub semantic: Option<Arc<SemanticSnapshot>>,
    pub measurements: AnalysisMeasurements,
    pub adaptation_failures: Vec<AdaptationFailure>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AnalysisFailure {
    UnknownTarget,
    ClosedDocument(DocumentId),
    VirtualDocument(DocumentId),
    Internal(String),
}

impl fmt::Display for AnalysisFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for AnalysisFailure {}

#[derive(Clone, Copy, Debug, Default)]
pub struct CanonicalAnalyzer;

impl CanonicalAnalyzer {
    #[allow(clippy::too_many_lines)]
    pub fn analyze(&self, request: AnalysisRequest) -> Result<AnalysisResult, AnalysisFailure> {
        let (entry, project_id) = match &request.target {
            AnalysisTarget::Document(document) => {
                let Some((path, project, open)) = request.snapshot.document_target(*document)
                else {
                    return Err(AnalysisFailure::UnknownTarget);
                };
                if !open {
                    return Err(AnalysisFailure::ClosedDocument(*document));
                }
                let Some(path) = path else {
                    return Err(AnalysisFailure::VirtualDocument(*document));
                };
                (path.to_path_buf(), project)
            }
            AnalysisTarget::Project(project) => {
                let plan = request
                    .snapshot
                    .project(*project)
                    .ok_or(AnalysisFailure::UnknownTarget)?;
                (plan.source().to_path_buf(), Some(*project))
            }
            AnalysisTarget::Path { entry, project } => (entry.clone(), *project),
        };
        let project = project_id
            .map(|id| {
                request
                    .snapshot
                    .project(id)
                    .ok_or(AnalysisFailure::UnknownTarget)
            })
            .transpose()?;
        let library = project.is_some_and(|plan| plan.kind() == ProjectKind::Library);
        let provider = request.snapshot.provider();
        let mut assigned = Vec::new();
        let discovery_started = Instant::now();
        let session =
            match discover_catalog_with_provider_traced(&entry, project, &provider, &mut |source| {
                assigned.push(source);
            }) {
                Ok(session) => session,
                Err(diagnostics) => {
                    let measurements = AnalysisMeasurements {
                        discovery_ns: discovery_started.elapsed().as_nanos(),
                        ..AnalysisMeasurements::default()
                    };
                    return partial_discovery_result(request, diagnostics, &assigned, measurements);
                }
            };
        let mut measurements = AnalysisMeasurements {
            discovery_ns: discovery_started.elapsed().as_nanos(),
            ..AnalysisMeasurements::default()
        };
        let sources = Arc::new(table_from_session(&session)?);
        let declarations_started = Instant::now();
        let declared = if library {
            collect_library_program_signatures(session.into_parsed_program())
        } else {
            collect_program_signatures(session.into_parsed_program())
        };
        measurements.declarations_ns = declarations_started.elapsed().as_nanos();
        let declared = match declared {
            Ok(declared) => declared,
            Err(diagnostics) => {
                return frontend_error_result(
                    request,
                    &sources,
                    diagnostics,
                    AnalysisStage::Declarations,
                    measurements,
                );
            }
        };
        let semantic_started = Instant::now();
        let hir = analyze_bodies_for_target(declared, TargetProperties::LINUX_X86_64);
        measurements.semantic_ns = semantic_started.elapsed().as_nanos();
        let hir = match hir {
            Ok(hir) => hir,
            Err(diagnostics) => {
                return frontend_error_result(
                    request,
                    &sources,
                    diagnostics,
                    AnalysisStage::Semantic,
                    measurements,
                );
            }
        };
        let verification_started = Instant::now();
        if let Err(diagnostics) = verify_hir(&hir) {
            measurements.verification_ns = verification_started.elapsed().as_nanos();
            return frontend_error_result(
                request,
                &sources,
                diagnostics,
                AnalysisStage::Semantic,
                measurements,
            );
        }
        measurements.verification_ns = verification_started.elapsed().as_nanos();
        Ok(AnalysisResult {
            request: request.id,
            stamp: request.snapshot.stamp,
            state: AnalysisState {
                coverage: AnalysisCoverage::Complete,
                validity: AnalysisValidity::Valid,
            },
            diagnostics: Vec::new(),
            semantic: Some(Arc::new(SemanticSnapshot { sources, hir })),
            measurements,
            adaptation_failures: Vec::new(),
        })
    }
}

fn frontend_error_result(
    request: AnalysisRequest,
    sources: &SourceTable,
    diagnostics: Vec<Diagnostic>,
    reached: AnalysisStage,
    measurements: AnalysisMeasurements,
) -> Result<AnalysisResult, AnalysisFailure> {
    let mut adaptation_failures = Vec::new();
    let diagnostics = adapt_diagnostics(diagnostics, sources, &mut adaptation_failures)?;
    Ok(AnalysisResult {
        request: request.id,
        stamp: request.snapshot.stamp,
        state: AnalysisState {
            coverage: AnalysisCoverage::Partial {
                reached,
                reason: PartialReason::FrontendStopped,
            },
            validity: AnalysisValidity::Invalid,
        },
        diagnostics,
        semantic: None,
        measurements,
        adaptation_failures,
    })
}

fn partial_discovery_result(
    request: AnalysisRequest,
    diagnostics: Vec<Diagnostic>,
    assigned: &[AssignedSource],
    measurements: AnalysisMeasurements,
) -> Result<AnalysisResult, AnalysisFailure> {
    let mut table = SourceTable::default();
    for diagnostic in &diagnostics {
        let Some(span) = diagnostic.span else {
            continue;
        };
        if table.get(span.source).is_some() {
            continue;
        }
        let Some(source) = assigned
            .iter()
            .find(|source| source.source.id == span.source)
        else {
            return Err(AnalysisFailure::Internal(format!(
                "canonical discovery did not register SourceId {} before stopping",
                span.source.0
            )));
        };
        let (identity, document_version) = identity(&source.provenance);
        let text: Arc<str> = Arc::from(source.source.text.as_str());
        table.insert(SnapshotSource {
            source_id: span.source,
            identity,
            document_version,
            unit: None,
            text: Arc::clone(&text),
            fingerprint: source.fingerprint,
            line_index: Arc::new(LineIndex::new(text)),
        })?;
    }
    let reached = diagnostics
        .first()
        .map_or(AnalysisStage::Input, |diagnostic| match diagnostic.phase {
            Phase::Lex => AnalysisStage::Lex,
            Phase::Parse | Phase::Semantic => AnalysisStage::Parse,
            _ => AnalysisStage::Input,
        });
    frontend_error_result(request, &table, diagnostics, reached, measurements)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::sync::atomic::{AtomicU64, Ordering};

    use crate::{DocumentLocator, EditorWorkspace, OpenDocument};

    static NEXT_TEST: AtomicU64 = AtomicU64::new(1);

    struct TestDir(PathBuf);

    impl TestDir {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "aether-editor-diagnostics-{}-{}",
                std::process::id(),
                NEXT_TEST.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn line_index_round_trips_unicode_and_crlf() {
        let text: Arc<str> = Arc::from("aé中😀e\u{301}\r\nnext");
        let index = LineIndex::new(Arc::clone(&text));
        for offset in 0..=text.len() {
            if text.is_char_boundary(offset)
                && !matches!(text.as_bytes().get(offset), Some(b'\r' | b'\n'))
            {
                let position = index.byte_to_position(offset).unwrap();
                assert_eq!(index.position_to_byte(position).unwrap(), offset);
            }
        }
        assert_eq!(
            index.byte_to_position(15).unwrap(),
            EditorPosition {
                line: 1,
                character: 0
            }
        );
        assert_eq!(
            index
                .position_to_byte(EditorPosition {
                    line: 0,
                    character: 5
                })
                .unwrap(),
            10
        );
        assert_eq!(
            index.position_to_byte(EditorPosition {
                line: 0,
                character: 4
            }),
            Err(LineIndexError::SplitsSurrogatePair {
                line: 0,
                character: 4
            })
        );
    }

    #[test]
    fn line_index_rejects_invalid_bytes_and_positions() {
        let index = LineIndex::new(Arc::from("é😀"));
        assert_eq!(
            index.byte_to_position(1),
            Err(LineIndexError::NotUtf8Boundary(1))
        );
        assert_eq!(
            index.byte_to_position(7),
            Err(LineIndexError::OffsetOutOfRange(7))
        );
        assert!(matches!(
            index.position_to_byte(EditorPosition {
                line: 0,
                character: 2
            }),
            Err(LineIndexError::SplitsSurrogatePair { .. })
        ));
        assert!(matches!(
            index.position_to_byte(EditorPosition {
                line: 1,
                character: 0
            }),
            Err(LineIndexError::LineOutOfRange(1))
        ));
    }

    fn source_table_for(text: &str) -> SourceTable {
        let text: Arc<str> = Arc::from(text);
        let mut sources = SourceTable::default();
        sources
            .insert(SnapshotSource {
                source_id: SourceId(0),
                identity: SourceIdentity::Disk(PathBuf::from("test.ae")),
                document_version: None,
                unit: None,
                line_index: Arc::new(LineIndex::new(Arc::clone(&text))),
                text,
                fingerprint: ContentFingerprint([0; 32]),
            })
            .unwrap();
        sources
    }

    #[test]
    fn diagnostic_adaptation_rejects_unknown_primary_source_and_omits_invalid_fix() {
        let sources = source_table_for("int main(){return 0;}");
        let unknown = Diagnostic::new(
            "E9998",
            Phase::Semantic,
            DiagnosticCategory::Name,
            "unknown source",
            Some(Span::in_source(SourceId(99), 0, 1)),
        );
        let mut failures = Vec::new();
        assert!(matches!(
            adapt_diagnostics(vec![unknown], &sources, &mut failures),
            Err(AnalysisFailure::Internal(message)) if message.contains("unknown SourceId 99")
        ));

        let invalid_fix = Diagnostic::new(
            "E9999",
            Phase::Semantic,
            DiagnosticCategory::Name,
            "invalid fix",
            Some(Span::in_source(SourceId(0), 0, 3)),
        )
        .with_fixit(Span::in_source(SourceId(0), 0, 99), "void");
        let mut failures = Vec::new();
        let adapted = adapt_diagnostics(vec![invalid_fix], &sources, &mut failures).unwrap();
        assert!(adapted[0].fixes.is_empty());
        assert!(matches!(
            failures.as_slice(),
            [AdaptationFailure::InvalidFix {
                code,
                error: LineIndexError::OffsetOutOfRange(99)
            }] if code.as_ref() == "E9999"
        ));
    }

    #[test]
    fn analyzer_qualifies_only_verified_frontend_as_complete_valid() {
        let directory = TestDir::new();
        let entry = directory.0.join("main.ae");
        fs::write(&entry, "int main(){return 0;}").unwrap();
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let document = workspace
            .open(OpenDocument {
                locator: DocumentLocator::file(&entry).unwrap(),
                text: Arc::from("int main(){return 0;}"),
                client_version: Some(1),
                project: None,
            })
            .unwrap();
        let result = CanonicalAnalyzer
            .analyze(AnalysisRequest {
                id: RequestId(1),
                target: AnalysisTarget::Document(document),
                snapshot: workspace.snapshot(),
            })
            .unwrap();
        assert_eq!(result.state.coverage, AnalysisCoverage::Complete);
        assert_eq!(result.state.validity, AnalysisValidity::Valid);
        let semantic = result.semantic.unwrap();
        assert_eq!(semantic.sources.iter().count(), 1);
        assert_eq!(
            semantic.sources.get(SourceId(0)).unwrap().identity,
            SourceIdentity::Document(document)
        );
    }

    #[test]
    fn analyzer_returns_structured_parse_error_for_unsaved_overlay() {
        let directory = TestDir::new();
        let entry = directory.0.join("main.ae");
        fs::write(&entry, "int main(){return 0;}").unwrap();
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let document = workspace
            .open(OpenDocument {
                locator: DocumentLocator::file(&entry).unwrap(),
                text: Arc::from("int main( { return 0; }"),
                client_version: Some(1),
                project: None,
            })
            .unwrap();
        let result = CanonicalAnalyzer
            .analyze(AnalysisRequest {
                id: RequestId(2),
                target: AnalysisTarget::Document(document),
                snapshot: workspace.snapshot(),
            })
            .unwrap();
        assert_eq!(result.state.validity, AnalysisValidity::Invalid);
        assert!(matches!(
            result.state.coverage,
            AnalysisCoverage::Partial { .. }
        ));
        assert_eq!(result.diagnostics[0].severity, DiagnosticSeverity::Error);
        assert_eq!(
            result.diagnostics[0].source,
            Some(SourceIdentity::Document(document))
        );
        assert!(result.diagnostics[0].range.is_some());
        assert!(result.semantic.is_none());
    }

    #[test]
    fn analyzer_distinguishes_lexical_and_semantic_ownership_failures() {
        let directory = TestDir::new();
        let entry = directory.0.join("main.ae");
        fs::write(&entry, "int main(){return 0;}").unwrap();
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let document = workspace
            .open(OpenDocument {
                locator: DocumentLocator::file(&entry).unwrap(),
                text: Arc::from("int main(){return \"unterminated;}"),
                client_version: Some(1),
                project: None,
            })
            .unwrap();
        let lexical = CanonicalAnalyzer
            .analyze(AnalysisRequest {
                id: RequestId(4),
                target: AnalysisTarget::Document(document),
                snapshot: workspace.snapshot(),
            })
            .unwrap();
        assert_eq!(
            lexical.state,
            AnalysisState {
                coverage: AnalysisCoverage::Partial {
                    reached: AnalysisStage::Lex,
                    reason: PartialReason::FrontendStopped,
                },
                validity: AnalysisValidity::Invalid,
            }
        );
        assert_eq!(lexical.diagnostics[0].phase, Phase::Lex);
        assert!(lexical.semantic.is_none());

        workspace
            .change(crate::ChangeDocument {
                document,
                text: Arc::from(
                    "struct S{Buffer<int> b;}int main(){S a=S(Buffer<int>(1,0));S c=a;return a.b[0];}",
                ),
                client_version: Some(2),
            })
            .unwrap();
        let ownership = CanonicalAnalyzer
            .analyze(AnalysisRequest {
                id: RequestId(5),
                target: AnalysisTarget::Document(document),
                snapshot: workspace.snapshot(),
            })
            .unwrap();
        assert_eq!(
            ownership.state,
            AnalysisState {
                coverage: AnalysisCoverage::Partial {
                    reached: AnalysisStage::Semantic,
                    reason: PartialReason::FrontendStopped,
                },
                validity: AnalysisValidity::Invalid,
            }
        );
        assert!(ownership.diagnostics.iter().any(|diagnostic| {
            diagnostic.code.as_ref() == "E0291" && diagnostic.phase == Phase::Semantic
        }));
        assert!(ownership.semantic.is_none());
    }

    #[test]
    fn imported_overlay_diagnostic_keeps_imported_document_identity() {
        let directory = TestDir::new();
        let entry = directory.0.join("main.ae");
        let imported = directory.0.join("alpha.ae");
        fs::write(&entry, "import Alpha; int main(){return Alpha.value();}").unwrap();
        fs::write(&imported, "package Alpha; public int value(){return 1;}").unwrap();
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let entry_document = workspace
            .open(OpenDocument {
                locator: DocumentLocator::file(&entry).unwrap(),
                text: Arc::from("import Alpha; int main(){return Alpha.value();}"),
                client_version: Some(1),
                project: None,
            })
            .unwrap();
        let imported_document = workspace
            .open(OpenDocument {
                locator: DocumentLocator::file(&imported).unwrap(),
                text: Arc::from("package Alpha; public int value(){return missing;}"),
                client_version: Some(1),
                project: None,
            })
            .unwrap();
        let result = CanonicalAnalyzer
            .analyze(AnalysisRequest {
                id: RequestId(3),
                target: AnalysisTarget::Document(entry_document),
                snapshot: workspace.snapshot(),
            })
            .unwrap();
        assert_eq!(result.state.validity, AnalysisValidity::Invalid);
        assert!(result.diagnostics.iter().any(
            |diagnostic| diagnostic.source == Some(SourceIdentity::Document(imported_document))
        ));
    }
}
