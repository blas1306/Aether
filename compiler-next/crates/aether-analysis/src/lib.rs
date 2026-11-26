//! Canonical source discovery, project catalog and import resolution for Aether.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use aether_frontend::{
    Diagnostic, DiagnosticCategory, LogicalSourceKey, ModuleId, ModuleInfo, OriginKey, PackageId,
    PackageKey, PackagePath, ParsedAst, ParsedModule, ParsedProgram, Phase, ResolvedImport,
    SourceFile, SourceId, SourceUnitKey, Span, parse_source,
};
use aether_package::{PackageInstanceKey, PackageMetadata, ProjectKind, ResolvedPackage};
use sha2::{Digest, Sha256};

mod diagnostics;
mod editor;
mod lifecycle;
mod symbols;

pub use diagnostics::{
    AdaptationFailure, AnalysisCoverage, AnalysisFailure, AnalysisMeasurements, AnalysisRequest,
    AnalysisResult, AnalysisStage, AnalysisState, AnalysisTarget, AnalysisValidity,
    CanonicalAnalyzer, DiagnosticSeverity, EditorDiagnostic, EditorFix, EditorPosition,
    EditorRange, LineIndex, LineIndexError, PartialReason, RelatedInformation, RequestId,
    SemanticSnapshot, SnapshotSource, SourceIdentity, SourceTable,
};

pub use editor::{
    AnalysisConfig, AnalysisSnapshot, ChangeDocument, DiskBase, DocumentId, DocumentLocator,
    DocumentRecord, DocumentState, DocumentVersion, EditorWorkspace, FileChange, OpenDocument,
    OverlaySourceProvider, ProjectId, PublishDecision, SavedDocument, SnapshotDiscovery,
    SnapshotSourceRead, SnapshotStamp, StoreError, WorkspaceId,
};
pub use lifecycle::{
    AnalysisScheduler, CancellationToken, InvalidRequestTransition, RequestCompletion,
    RequestHandle, RequestState, SchedulerMeasurements,
};
pub use symbols::{
    DocumentSymbol, DocumentSymbolCategory, DocumentSymbolLocation, DocumentSymbolResult,
    DocumentSymbolsUnavailable,
};

/// Content digest of the exact immutable bytes returned by a source provider.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ContentFingerprint(pub [u8; 32]);

/// Filesystem subtree whose Aether sources should be enumerated.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SourceScope {
    /// Canonical provider root used to derive logical names.
    pub root: PathBuf,
}

/// Provider-owned locator. It is provenance, not a compiler identity.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum SourceLocator {
    /// Source stored at a disk path.
    Disk(PathBuf),
}

/// One enumerated source, before package or module identity is assigned.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SourceDescriptor {
    /// Provider-relative slash-separated display name.
    pub logical_name: String,
    /// Opaque location accepted by the same provider.
    pub locator: SourceLocator,
}

/// Provenance of exact source content.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SourceProvenance {
    /// Content read from disk.
    Disk {
        /// Path used for the successful read.
        canonical_path: PathBuf,
        /// Digest of the returned content.
        fingerprint: ContentFingerprint,
    },
    /// Content captured from an open editor document.
    Overlay {
        /// Stable document identity in the owning workspace.
        document: DocumentId,
        /// Monotonic version captured by the snapshot.
        version: DocumentVersion,
    },
    /// Compiler-owned source which cannot be replaced by an editor overlay.
    Toolchain {
        /// Stable logical display name.
        logical_name: Arc<str>,
        /// Digest of the embedded source.
        fingerprint: ContentFingerprint,
    },
}

/// Immutable content returned by a provider.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SourceContent {
    /// Exact UTF-8 source text used by this analysis.
    pub text: Arc<str>,
    /// Digest of `text`.
    pub fingerprint: ContentFingerprint,
    /// Origin of `text`.
    pub provenance: SourceProvenance,
}

/// Failure while enumerating or reading provider content.
#[derive(Debug)]
pub struct SourceProviderError {
    pub(crate) message: String,
}

impl std::fmt::Display for SourceProviderError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for SourceProviderError {}

/// Pure source enumeration/read boundary. It never resolves imports or assigns IDs.
pub trait SourceProvider: Send + Sync {
    /// Enumerates candidate source locators under a scope.
    fn enumerate(&self, scope: &SourceScope) -> Result<Vec<SourceDescriptor>, SourceProviderError>;

    /// Reads one descriptor into immutable owned content.
    fn read(&self, locator: &SourceLocator) -> Result<SourceContent, SourceProviderError>;
}

/// Disk-backed provider preserving the batch loader's recursive `.ae` discovery rules.
#[derive(Clone, Copy, Debug, Default)]
pub struct DiskSourceProvider;

impl SourceProvider for DiskSourceProvider {
    fn enumerate(&self, scope: &SourceScope) -> Result<Vec<SourceDescriptor>, SourceProviderError> {
        let mut paths = Vec::new();
        collect_disk_source_paths(&scope.root, &scope.root, &mut paths)?;
        Ok(paths)
    }

    fn read(&self, locator: &SourceLocator) -> Result<SourceContent, SourceProviderError> {
        let SourceLocator::Disk(path) = locator;
        let before = fs::metadata(path).map_err(|error| SourceProviderError {
            message: error.to_string(),
        })?;
        let text = fs::read_to_string(path).map_err(|error| SourceProviderError {
            message: error.to_string(),
        })?;
        let after = fs::metadata(path).map_err(|error| SourceProviderError {
            message: error.to_string(),
        })?;
        if before.len() != after.len() || before.modified().ok() != after.modified().ok() {
            return Err(SourceProviderError {
                message: "source changed while it was being read".into(),
            });
        }
        let fingerprint = ContentFingerprint(Sha256::digest(text.as_bytes()).into());
        Ok(SourceContent {
            text: Arc::from(text),
            fingerprint,
            provenance: SourceProvenance::Disk {
                canonical_path: path.clone(),
                fingerprint,
            },
        })
    }
}

/// One source parsed exactly once during module discovery.
#[derive(Clone, Debug)]
pub struct SessionModule {
    info: ModuleInfo,
    source: SourceFile,
    ast: ParsedAst,
    path: PathBuf,
    fingerprint: ContentFingerprint,
    provenance: SourceProvenance,
}

impl SessionModule {
    /// Resolved module graph node.
    #[must_use]
    pub const fn info(&self) -> &ModuleInfo {
        &self.info
    }

    /// Owned source record.
    #[must_use]
    pub const fn source(&self) -> &SourceFile {
        &self.source
    }

    /// Provider locator used to obtain this exact source.
    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Digest of the exact immutable text parsed for this module.
    #[must_use]
    pub const fn fingerprint(&self) -> ContentFingerprint {
        self.fingerprint
    }

    /// Origin of the exact bytes used by this session.
    #[must_use]
    pub const fn provenance(&self) -> &SourceProvenance {
        &self.provenance
    }
}

/// Per-compilation owner of source files, the module graph and discovery measurements.
#[derive(Clone, Debug)]
pub struct CompilationSession {
    source_root: PathBuf,
    entry: ModuleId,
    modules: Vec<SessionModule>,
    discovery_ns: u128,
    file_load_ns: u128,
    parse_ns: u128,
}

impl CompilationSession {
    /// Discovers, reads and parses the entry module and all imports transitively.
    pub fn discover(entry_path: &Path) -> Result<Self, Vec<Diagnostic>> {
        discover_catalog(entry_path)
    }

    /// Explicit bootstrap source root: the entry file's containing directory.
    #[must_use]
    pub fn source_root(&self) -> &Path {
        &self.source_root
    }

    /// Entry module identity.
    #[must_use]
    pub const fn entry(&self) -> ModuleId {
        self.entry
    }

    /// Canonical module table. Its length is also the read/parse count.
    #[must_use]
    pub fn modules(&self) -> &[SessionModule] {
        &self.modules
    }

    /// Consumes the session into the frontend's canonical parsed program.
    #[must_use]
    pub fn into_parsed_program(self) -> ParsedProgram {
        ParsedProgram {
            modules: self
                .modules
                .into_iter()
                .map(|module| ParsedModule {
                    info: module.info,
                    ast: module.ast,
                })
                .collect(),
            entry: self.entry,
        }
    }

    /// Produces the deterministic batch AST dump.
    #[must_use]
    pub fn ast_dump(&self) -> String {
        self.modules
            .iter()
            .map(|module| format!("module: {:#?}\nast: {}", module.info, module.ast.dump()))
            .collect::<Vec<_>>()
            .join("\n")
    }

    /// Discovery, source loading and parsing timings used by batch reporting.
    #[must_use]
    pub const fn timings_ns(&self) -> (u128, u128, u128) {
        (self.discovery_ns, self.file_load_ns, self.parse_ns)
    }
}

#[derive(Debug)]
struct CatalogUnit {
    path: PathBuf,
    logical: String,
    source: SourceFile,
    ast: ParsedAst,
    package: PackageKey,
    toolchain: bool,
    owner: Option<PackageInstanceKey>,
    fingerprint: ContentFingerprint,
    provenance: SourceProvenance,
}

struct SourceCandidate {
    path: PathBuf,
    logical: String,
    text: String,
    package_path: Option<Vec<String>>,
    owner: Option<PackageInstanceKey>,
    owner_name: Option<String>,
    fingerprint: ContentFingerprint,
    provenance: SourceProvenance,
}

#[derive(Clone, Debug)]
pub(crate) struct AssignedSource {
    pub(crate) source: SourceFile,
    pub(crate) fingerprint: ContentFingerprint,
    pub(crate) provenance: SourceProvenance,
}

#[allow(clippy::cast_possible_truncation, clippy::too_many_lines)]
fn discover_catalog(entry_path: &Path) -> Result<CompilationSession, Vec<Diagnostic>> {
    discover_catalog_with_provider(entry_path, None, &DiskSourceProvider)
}

#[allow(clippy::cast_possible_truncation, clippy::too_many_lines)]
/// Discovers a project through the canonical disk provider.
pub fn discover_catalog_with_plan(
    entry_path: &Path,
    project: Option<&ProjectPlan>,
) -> Result<CompilationSession, Vec<Diagnostic>> {
    discover_catalog_with_provider(entry_path, project, &DiskSourceProvider)
}

/// Canonical catalog construction using injectable source contents.
#[allow(clippy::cast_possible_truncation, clippy::too_many_lines)]
pub fn discover_catalog_with_provider(
    entry_path: &Path,
    project: Option<&ProjectPlan>,
    provider: &dyn SourceProvider,
) -> Result<CompilationSession, Vec<Diagnostic>> {
    discover_catalog_with_provider_traced(entry_path, project, provider, &mut |_| {})
}

#[allow(clippy::cast_possible_truncation, clippy::too_many_lines)]
pub(crate) fn discover_catalog_with_provider_traced(
    entry_path: &Path,
    project: Option<&ProjectPlan>,
    provider: &dyn SourceProvider,
    assigned: &mut dyn FnMut(AssignedSource),
) -> Result<CompilationSession, Vec<Diagnostic>> {
    let discovery_started = Instant::now();
    let entry_absolute = match entry_path.canonicalize() {
        Ok(path) => path,
        Err(canonical_error) => {
            let path = canonical_or_lexical_absolute(entry_path).map_err(|error| {
                vec![io_diagnostic(format!(
                    "could not read entry source `{}`: {error}",
                    entry_path.display()
                ))]
            })?;
            provider
                .read(&SourceLocator::Disk(path.clone()))
                .map_err(|_| {
                    vec![io_diagnostic(format!(
                        "could not read entry source `{}`: {canonical_error}",
                        entry_path.display()
                    ))]
                })?;
            path
        }
    };
    let source_root = source_root_for_entry(&entry_absolute);
    let mut paths = Vec::new();
    if let Some(plan) = project {
        for (instance, package) in plan.packages() {
            let root = package
                .source()
                .parent()
                .ok_or_else(|| vec![io_diagnostic("package source has no provider root")])?;
            let provider_paths = provider
                .enumerate(&SourceScope { root: root.into() })
                .map_err(|error| vec![io_diagnostic(error.to_string())])?;
            for descriptor in provider_paths {
                let logical = descriptor.logical_name;
                let SourceLocator::Disk(path) = descriptor.locator;
                paths.push((
                    format!("{}::{logical}", instance.canonical()),
                    path,
                    Some(instance.clone()),
                    Some(package.package().name.as_str().to_owned()),
                ));
            }
        }
    } else {
        let standalone_paths = provider
            .enumerate(&SourceScope {
                root: source_root.clone(),
            })
            .map_err(|error| vec![io_diagnostic(error.to_string())])?;
        paths.extend(standalone_paths.into_iter().map(|descriptor| {
            let SourceLocator::Disk(path) = descriptor.locator;
            (descriptor.logical_name, path, None, None)
        }));
    }
    paths.sort_by(|left, right| left.0.cmp(&right.0));
    let mut file_load_ns = 0_u128;
    let mut candidates = Vec::new();
    for (logical, path, owner, owner_name) in paths {
        let started = Instant::now();
        let content = provider
            .read(&SourceLocator::Disk(path.clone()))
            .map_err(|error| {
                vec![io_diagnostic(format!(
                    "could not read source unit `{logical}`: {error}"
                ))]
            })?;
        let text = content.text.to_string();
        let fingerprint = content.fingerprint;
        let provenance = content.provenance;
        file_load_ns += started.elapsed().as_nanos();
        let package_path = catalog_package_header(&text);
        if package_path
            .as_ref()
            .is_some_and(|path| path.first().is_some_and(|segment| segment == "std"))
        {
            return Err(vec![
                Diagnostic::new(
                    "E0231",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    "project source cannot declare reserved package root `std`",
                    None,
                )
                .with_source_name(&logical),
            ]);
        }
        candidates.push(SourceCandidate {
            path,
            logical: logical.clone(),
            text,
            package_path,
            owner,
            owner_name,
            fingerprint,
            provenance,
        });
    }
    let entry_candidate = candidates
        .iter()
        .position(|candidate| paths_refer_to_same_source(&candidate.path, &entry_absolute))
        .ok_or_else(|| {
            vec![io_diagnostic(
                "entry source is outside its source root catalog",
            )]
        })?;
    let mut parse_ns = 0_u128;
    let mut units = Vec::new();
    let entry_package = candidates[entry_candidate]
        .package_path
        .clone()
        .map(|path| PackageKey::named(OriginKey::Project, PackagePath(path)));
    let mut pending = BTreeSet::new();
    let mut descendant_grants = BTreeSet::new();
    let mut visited = BTreeSet::new();
    let mut loaded_sources = BTreeSet::new();
    if project.is_some() {
        for candidate in &candidates {
            let source_id = SourceId(units.len() as u32);
            let source =
                SourceFile::with_id(source_id, candidate.logical.clone(), candidate.text.clone());
            assigned(AssignedSource {
                source: source.clone(),
                fingerprint: candidate.fingerprint,
                provenance: candidate.provenance.clone(),
            });
            let started = Instant::now();
            let ast = parse_source(&source).map_err(|diagnostics| {
                diagnostics
                    .into_iter()
                    .map(|d| d.with_source_name(&candidate.logical))
                    .collect::<Vec<_>>()
            })?;
            parse_ns += started.elapsed().as_nanos();
            let is_entry = paths_refer_to_same_source(&candidate.path, &entry_absolute);
            let package = match ast.package() {
                Some(declaration) => {
                    let owner_name = candidate
                        .owner_name
                        .as_deref()
                        .expect("project candidate owner");
                    if declaration.path.first().map(String::as_str) != Some(owner_name) {
                        return Err(vec![Diagnostic::new("E0241", Phase::Semantic, DiagnosticCategory::Name, format!("source package `{}` is outside owning package root `{owner_name}`", declaration.path.join(".")), Some(declaration.span)).with_source_name(&candidate.logical)]);
                    }
                    PackageKey::named(
                        OriginKey::Package(
                            candidate.owner.clone().expect("project candidate owner"),
                        ),
                        PackagePath(declaration.path.clone()),
                    )
                }
                None if is_entry
                    && project.is_some_and(|plan| {
                        plan.root_instance() == candidate.owner.as_ref().expect("owner")
                    }) =>
                {
                    PackageKey::Anonymous
                }
                None => {
                    return Err(vec![
                        Diagnostic::new(
                            "E0220",
                            Phase::Semantic,
                            DiagnosticCategory::Name,
                            "non-entry package source must declare its owning package",
                            None,
                        )
                        .with_source_name(&candidate.logical),
                    ]);
                }
            };
            units.push(CatalogUnit {
                path: candidate.path.clone(),
                logical: candidate.logical.clone(),
                source,
                ast,
                package,
                toolchain: false,
                owner: candidate.owner.clone(),
                fingerprint: candidate.fingerprint,
                provenance: candidate.provenance.clone(),
            });
        }
    } else if let Some(package) = entry_package {
        pending.insert(package);
    } else {
        let candidate = &candidates[entry_candidate];
        let source = SourceFile::with_id(
            SourceId(0),
            candidate.logical.clone(),
            candidate.text.clone(),
        );
        assigned(AssignedSource {
            source: source.clone(),
            fingerprint: candidate.fingerprint,
            provenance: candidate.provenance.clone(),
        });
        let started = Instant::now();
        let ast = parse_source(&source).map_err(|diagnostics| {
            diagnostics
                .into_iter()
                .map(|d| d.with_source_name(&candidate.logical))
                .collect::<Vec<_>>()
        })?;
        parse_ns += started.elapsed().as_nanos();
        for import in ast.imports() {
            if import.path != ["Text"] && import.path != ["std"] {
                let origin = if import.path.first().is_some_and(|segment| segment == "std") {
                    OriginKey::Toolchain
                } else {
                    OriginKey::Project
                };
                let imported = PackageKey::named(origin.clone(), PackagePath(import.path.clone()));
                if origin == OriginKey::Project {
                    descendant_grants.insert(imported.clone());
                }
                pending.insert(imported);
            }
        }
        loaded_sources.insert(candidate.logical.clone());
        units.push(CatalogUnit {
            path: candidate.path.clone(),
            logical: candidate.logical.clone(),
            source,
            ast,
            package: PackageKey::Anonymous,
            toolchain: false,
            owner: None,
            fingerprint: candidate.fingerprint,
            provenance: candidate.provenance.clone(),
        });
    }
    while let Some(package) = pending.pop_first() {
        let PackageKey::Named { origin, path } = &package else {
            return Err(vec![io_diagnostic(
                "anonymous package cannot be a discovery or import target",
            )]);
        };
        if !visited.insert(package.clone()) || *origin == OriginKey::Toolchain {
            continue;
        }
        let include_descendants = descendant_grants.contains(&package);
        let matching_candidates = candidates
            .iter()
            .filter(|candidate| {
                candidate
                    .package_path
                    .as_ref()
                    .is_some_and(|candidate_path| {
                        candidate_path == &path.0
                            || (include_descendants && candidate_path.starts_with(&path.0))
                    })
                    && !loaded_sources.contains(&candidate.logical)
            })
            .collect::<Vec<_>>();
        for candidate in matching_candidates {
            loaded_sources.insert(candidate.logical.clone());
            let source_id = SourceId(units.len() as u32);
            let source =
                SourceFile::with_id(source_id, candidate.logical.clone(), candidate.text.clone());
            assigned(AssignedSource {
                source: source.clone(),
                fingerprint: candidate.fingerprint,
                provenance: candidate.provenance.clone(),
            });
            let started = Instant::now();
            let ast = parse_source(&source).map_err(|diagnostics| {
                diagnostics
                    .into_iter()
                    .map(|d| d.with_source_name(&candidate.logical))
                    .collect::<Vec<_>>()
            })?;
            parse_ns += started.elapsed().as_nanos();
            let verified = explicit_project_package(&ast, &candidate.logical)?;
            for import in ast.imports() {
                if import.path != ["Text"] && import.path != ["std"] {
                    let origin = if import.path.first().is_some_and(|segment| segment == "std") {
                        OriginKey::Toolchain
                    } else {
                        OriginKey::Project
                    };
                    let imported =
                        PackageKey::named(origin.clone(), PackagePath(import.path.clone()));
                    if origin == OriginKey::Project {
                        descendant_grants.insert(imported.clone());
                    }
                    pending.insert(imported);
                }
            }
            units.push(CatalogUnit {
                path: candidate.path.clone(),
                logical: candidate.logical.clone(),
                source,
                ast,
                package: verified,
                toolchain: false,
                owner: None,
                fingerprint: candidate.fingerprint,
                provenance: candidate.provenance.clone(),
            });
        }
    }
    let mut std_grants = units
        .iter()
        .flat_map(|unit| unit.ast.imports())
        .filter(|import| import.path.first().is_some_and(|segment| segment == "std"))
        .map(|import| PackagePath(import.path.clone()))
        .collect::<BTreeSet<_>>();
    let file_granted = std_grants.contains(&PackagePath(vec!["std".into(), "File".into()]));
    if file_granted {
        std_grants.insert(PackagePath(vec!["std".into(), "IO".into()]));
    }
    let core_output_used = units.iter().filter(|unit| !unit.toolchain).any(|unit| {
        let declared = unit
            .ast
            .functions()
            .iter()
            .map(|function| function.name.as_str())
            .collect::<BTreeSet<_>>();
        aether_frontend::lex(&unit.source).is_ok_and(|tokens| {
            tokens.iter().enumerate().any(|(index, token)| {
                token.kind == aether_frontend::TokenKind::Identifier
                    && matches!(token.lexeme.as_str(), "print" | "println")
                    && !declared.contains(token.lexeme.as_str())
                    && tokens
                        .get(index + 1)
                        .is_some_and(|next| next.kind == aether_frontend::TokenKind::LeftParen)
                    && index.checked_sub(1).is_none_or(|previous| {
                        tokens[previous].kind != aether_frontend::TokenKind::Dot
                    })
            })
        })
    });
    let io_public = std_grants.contains(&PackagePath(vec!["std".into(), "IO".into()]));
    let toolchain_packages = [
        (vec!["std", "Math"], "package std.Math;"),
        (
            vec!["std", "Math", "LinearAlgebra"],
            "package std.Math.LinearAlgebra; public Matrix<T> transposeCopy<T: Storable + Copy + Zero>(ref Matrix<T> source){usize m=rows(*source);usize n=columns(*source);Matrix<T> result=matrixFilled<T>(n,m,0);usize i=1;while(i<=m){usize j=1;while(j<=n){result[j,i]=(*source)[i,j];j=j+1;}i=i+1;}return result;} public Matrix<T> diagonalMatrix<T: Storable + Copy + Zero>(ref Vector<T,Column> values){usize k=dimension(*values);Matrix<T> result=matrixFilled<T>(k,k,0);usize i=1;while(i<=k){result[i,i]=(*values)[i];i=i+1;}return result;} public Matrix<T> diagonalMatrix<T: Storable + Copy + Zero>(ref Vector<T,Row> values){usize k=dimension(*values);Matrix<T> result=matrixFilled<T>(k,k,0);usize i=1;while(i<=k){result[i,i]=(*values)[i];i=i+1;}return result;}",
        ),
        (
            vec!["std", "Text"],
            "package std.Text; public class InvalidUtf8Exception:Exception{public init(){}} public string fromUtf8(ref Buffer<uint8> bytes,usize length){return \"\";} public struct ScalarOffset { usize value; } enum FindResult { Found(ScalarOffset), NotFound, } enum ByteSliceResult { Slice(string), InvalidRange, OutOfBounds, InvalidBoundary, } enum IntParseResult { Value(int), Invalid, Overflow, } enum DoubleParseResult { Value(double), Invalid, Overflow, Underflow, }",
        ),
        (
            vec!["std", "Format"],
            "package std.Format; public string fixed(float32 value,usize fractionalDigits){return \"\";} public string fixed(float64 value,usize fractionalDigits){return \"\";} public string scientific(float32 value,usize fractionalDigits){return \"\";} public string scientific(float64 value,usize fractionalDigits){return \"\";}",
        ),
        (
            vec!["std", "IO"],
            if io_public {
                "package std.IO; public open class IOException:Exception{public init(){}} public class InvalidTextEncodingException:IOException{public init():base(){}} enum ReadLineResult{Line(string),End,} public ReadLineResult readLine(){ReadLineResult result=ReadLineResult.End;return result;} public void eprint(ref string value){return;} public void eprintln(ref string value){return;}"
            } else {
                "package std.IO; public open class IOException:Exception{public init(){}}"
            },
        ),
        (
            vec!["std", "File"],
            "package std.File; import std.IO; public class FileNotFoundException:std.IO.IOException{public init():base(){}} public class PermissionDeniedException:std.IO.IOException{public init():base(){}} public string readText(ref string path){return \"\";} public void writeText(ref string path,ref string value){return;} public void writeTextAtomic(ref string path,ref string value){return;}",
        ),
        (
            vec!["std", "Process"],
            "package std.Process; public class InvalidArgumentEncodingException:Exception{public init(){}} public Array<string> args(){Array<string> values={};return values;}",
        ),
    ];
    for (segments, text) in toolchain_packages {
        let path = PackagePath(segments.into_iter().map(str::to_owned).collect());
        let granted = std_grants.iter().any(|grant| path.starts_with(grant));
        let core_io = path == PackagePath(vec!["std".into(), "IO".into()]) && core_output_used;
        if !(granted || core_io) {
            continue;
        }
        let std_source_id = SourceId(units.len() as u32);
        let logical = format!("{}/package.ae", path.0.join("/"));
        let std_source = SourceFile::with_id(std_source_id, format!("<toolchain>/{logical}"), text);
        let fingerprint = ContentFingerprint(Sha256::digest(text.as_bytes()).into());
        let provenance = SourceProvenance::Toolchain {
            logical_name: Arc::from(format!("<toolchain>/{logical}")),
            fingerprint,
        };
        assigned(AssignedSource {
            source: std_source.clone(),
            fingerprint,
            provenance: provenance.clone(),
        });
        let started = Instant::now();
        let std_ast = parse_source(&std_source)?;
        parse_ns += started.elapsed().as_nanos();
        units.push(CatalogUnit {
            path: PathBuf::from(format!("<toolchain>/{logical}")),
            logical: logical.clone(),
            source: std_source,
            ast: std_ast,
            package: PackageKey::named(OriginKey::Toolchain, path),
            toolchain: true,
            owner: None,
            fingerprint,
            provenance,
        });
    }

    let mut package_ids = BTreeMap::new();
    let package_keys = units
        .iter()
        .flat_map(|unit| match unit.package.named_parts() {
            Some((origin, path)) => (1..=path.0.len())
                .map(|length| {
                    PackageKey::named(origin.clone(), PackagePath(path.0[..length].to_vec()))
                })
                .collect::<Vec<_>>(),
            None => vec![PackageKey::Anonymous],
        })
        .collect::<BTreeSet<_>>();
    for key in package_keys {
        let id = PackageId(package_ids.len() as u32);
        package_ids.insert(key, id);
    }
    let mut representatives = BTreeMap::new();
    for (index, unit) in units.iter().enumerate() {
        if let Some((origin, path)) = unit.package.named_parts() {
            for length in 1..=path.0.len() {
                let prefix =
                    PackageKey::named(origin.clone(), PackagePath(path.0[..length].to_vec()));
                representatives
                    .entry(prefix)
                    .or_insert(ModuleId(index as u32));
            }
        }
    }
    validate_package_members(&units)?;
    let mut modules = units
        .iter()
        .enumerate()
        .map(|(index, unit)| SessionModule {
            info: ModuleInfo {
                id: ModuleId(index as u32),
                key: SourceUnitKey {
                    package: unit.package.clone(),
                    logical_source: LogicalSourceKey(unit.logical.clone()),
                },
                package: package_ids[&unit.package],
                display_name: unit.package.display(),
                source: unit.source.id,
                source_name: if unit.toolchain {
                    format!("<toolchain>/{}", unit.logical)
                } else {
                    unit.logical.clone()
                },
                imports: Vec::new(),
                semantic_dependencies: BTreeSet::new(),
            },
            source: unit.source.clone(),
            ast: unit.ast.clone(),
            path: unit.path.clone(),
            fingerprint: unit.fingerprint,
            provenance: unit.provenance.clone(),
        })
        .collect::<Vec<_>>();
    for (index, unit) in units.iter().enumerate() {
        modules[index].info.imports =
            resolve_imports(unit, &package_ids, &representatives, project)?;
    }
    let entry = units
        .iter()
        .position(|unit| !unit.toolchain && paths_refer_to_same_source(&unit.path, &entry_absolute))
        .map(|index| ModuleId(index as u32))
        .ok_or_else(|| {
            vec![io_diagnostic(
                "entry source is outside its source root catalog",
            )]
        })?;
    Ok(CompilationSession {
        source_root,
        entry,
        modules,
        discovery_ns: discovery_started.elapsed().as_nanos(),
        file_load_ns,
        parse_ns,
    })
}

/// Returns the standalone source root used by canonical discovery.
#[must_use]
pub fn source_root_for_entry(entry_path: &Path) -> PathBuf {
    entry_path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."))
        .to_path_buf()
}

fn canonical_or_lexical_absolute(path: &Path) -> std::io::Result<PathBuf> {
    if let Ok(canonical) = path.canonicalize() {
        return Ok(canonical);
    }
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()?.join(path)
    };
    let Some(parent) = absolute.parent() else {
        return Ok(absolute);
    };
    Ok(parent
        .canonicalize()
        .unwrap_or_else(|_| parent.to_path_buf())
        .join(absolute.file_name().unwrap_or_default()))
}

fn paths_refer_to_same_source(left: &Path, right: &Path) -> bool {
    canonical_or_lexical_absolute(left).ok() == canonical_or_lexical_absolute(right).ok()
}

fn catalog_package_header(text: &str) -> Option<Vec<String>> {
    let source = SourceFile::new("<catalog>", text);
    let tokens = aether_frontend::lex(&source).ok()?;
    if tokens.first()?.kind != aether_frontend::TokenKind::KwPackage {
        return None;
    }
    let mut path = Vec::new();
    let mut index = 1;
    loop {
        let token = tokens.get(index)?;
        if token.kind != aether_frontend::TokenKind::Identifier {
            return None;
        }
        path.push(token.lexeme.clone());
        index += 1;
        match tokens.get(index)?.kind {
            aether_frontend::TokenKind::Dot => index += 1,
            aether_frontend::TokenKind::Semicolon => return Some(path),
            _ => return None,
        }
    }
}

fn collect_disk_source_paths(
    root: &Path,
    directory: &Path,
    output: &mut Vec<SourceDescriptor>,
) -> Result<(), SourceProviderError> {
    let entries = fs::read_dir(directory).map_err(|error| SourceProviderError {
        message: format!("could not scan source root `{}`: {error}", root.display()),
    })?;
    for entry in entries {
        let entry = entry.map_err(|error| SourceProviderError {
            message: format!("could not inspect source root entry: {error}"),
        })?;
        let kind = entry.file_type().map_err(|error| SourceProviderError {
            message: format!("could not inspect `{}`: {error}", entry.path().display()),
        })?;
        if kind.is_symlink() {
            return Err(SourceProviderError {
                message: format!(
                    "symlink source-provider entry `{}` is ambiguous",
                    entry.path().display()
                ),
            });
        }
        if kind.is_dir() {
            collect_disk_source_paths(root, &entry.path(), output)?;
        } else if kind.is_file()
            && entry.path().extension().and_then(|ext| ext.to_str()) == Some("ae")
        {
            let entry_path = entry.path();
            let relative = entry_path.strip_prefix(root).expect("walked below root");
            let logical = relative
                .components()
                .map(|component| component.as_os_str().to_string_lossy())
                .collect::<Vec<_>>()
                .join("/");
            output.push(SourceDescriptor {
                logical_name: logical,
                locator: SourceLocator::Disk(entry_path),
            });
        }
    }
    Ok(())
}

fn explicit_project_package(
    ast: &ParsedAst,
    source_name: &str,
) -> Result<PackageKey, Vec<Diagnostic>> {
    let Some(package) = ast.package() else {
        return Err(vec![
            Diagnostic::new(
                "E0220",
                Phase::Semantic,
                DiagnosticCategory::Name,
                "catalog classified an anonymous source unit as a named package contribution",
                None,
            )
            .with_source_name(source_name),
        ]);
    };
    if package.path.first().is_some_and(|segment| segment == "std") {
        return Err(vec![
            Diagnostic::new(
                "E0231",
                Phase::Semantic,
                DiagnosticCategory::Name,
                "project source cannot declare reserved package root `std`",
                Some(package.span),
            )
            .with_source_name(source_name),
        ]);
    }
    Ok(PackageKey::named(
        OriginKey::Project,
        PackagePath(package.path.clone()),
    ))
}

#[allow(clippy::too_many_lines)]
fn resolve_imports(
    unit: &CatalogUnit,
    packages: &BTreeMap<PackageKey, PackageId>,
    representatives: &BTreeMap<PackageKey, ModuleId>,
    project: Option<&ProjectPlan>,
) -> Result<Vec<ResolvedImport>, Vec<Diagnostic>> {
    let mut seen_targets = BTreeSet::new();
    let mut bindings = BTreeMap::<String, Span>::new();
    let declarations = unit
        .ast
        .aliases()
        .iter()
        .map(|d| d.name.as_str())
        .chain(unit.ast.structs().iter().map(|d| d.name.as_str()))
        .chain(unit.ast.enums().iter().map(|d| d.name.as_str()))
        .chain(unit.ast.classes().iter().map(|d| d.name.as_str()))
        .chain(unit.ast.interfaces().iter().map(|d| d.name.as_str()))
        .chain(unit.ast.functions().iter().map(|d| d.name.as_str()))
        .collect::<BTreeSet<_>>();
    let mut resolved = Vec::new();
    for import in unit.ast.imports() {
        if import.path == ["Text"] {
            return Err(vec![
                Diagnostic::new(
                    "E0232",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    "legacy `import Text` is invalid; replace it with `import std.Text`",
                    Some(import.span),
                )
                .with_fixit(import.span, "import std.Text;")
                .with_source_name(&unit.logical),
            ]);
        }
        if import.path == ["std"] {
            return Err(vec![
                Diagnostic::new(
                    "E0233",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    "`import std;` is invalid; import a concrete `std.X` branch",
                    Some(import.span),
                )
                .with_source_name(&unit.logical),
            ]);
        }
        let origin = if import.path.first().is_some_and(|segment| segment == "std") {
            OriginKey::Toolchain
        } else if let Some(plan) = project {
            let owner = unit.owner.as_ref().ok_or_else(|| {
                vec![io_diagnostic(
                    "non-toolchain project source has no owning package instance",
                )]
            })?;
            let owner_node = plan.packages().get(owner).expect("validated owner node");
            let import_root = &import.path[0];
            let target_instance = if import_root == owner_node.package().name.as_str() {
                owner.clone()
            } else if let Some(target) = owner_node.dependencies().get(import_root) {
                target.clone()
            } else {
                return Err(vec![
                    Diagnostic::new(
                        "E0242",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!(
                            "package `{}` does not declare direct dependency `{import_root}`",
                            owner_node.package().name.as_str()
                        ),
                        Some(import.span),
                    )
                    .with_source_name(&unit.logical),
                ]);
            };
            OriginKey::Package(target_instance)
        } else {
            OriginKey::Project
        };
        let target = PackageKey::named(origin, PackagePath(import.path.clone()));
        let Some(package) = packages.get(&target).copied() else {
            return Err(vec![
                Diagnostic::new(
                    "E0221",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!("package path `{}` does not exist", import.path.join(".")),
                    Some(import.span),
                )
                .with_source_name(&unit.logical),
            ]);
        };
        if !seen_targets.insert(target.clone()) {
            return Err(vec![
                Diagnostic::new(
                    "E0220",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!(
                        "duplicate import of canonical package `{}`",
                        target
                            .named_parts()
                            .expect("source import target is named")
                            .1
                            .canonical()
                    ),
                    Some(import.span),
                )
                .with_source_name(&unit.logical),
            ]);
        }
        let binding = import
            .alias
            .clone()
            .unwrap_or_else(|| import.path[0].clone());
        if binding == "std" && import.alias.is_some() {
            return Err(vec![
                Diagnostic::new(
                    "E0234",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    "`std` is reserved and cannot be an import alias",
                    Some(import.span),
                )
                .with_source_name(&unit.logical),
            ]);
        }
        if let Some(previous) = bindings.insert(binding.clone(), import.span) {
            if import.alias.is_some() {
                return Err(vec![
                    Diagnostic::new(
                        "E0220",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!(
                            "duplicate namespace binding `{binding}`; previous binding at {}..{}",
                            previous.start, previous.end
                        ),
                        Some(import.span),
                    )
                    .with_source_name(&unit.logical),
                ]);
            }
        }
        if declarations.contains(binding.as_str()) {
            return Err(vec![
                Diagnostic::new(
                    "E0235",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!("namespace binding `{binding}` conflicts with a package member"),
                    Some(import.span),
                )
                .with_source_name(&unit.logical),
            ]);
        }
        resolved.push(ResolvedImport {
            name: import
                .alias
                .clone()
                .unwrap_or_else(|| import.path.join(".")),
            module: representatives[&target],
            package,
            target,
            alias: import.alias.clone(),
            span: import.span,
        });
    }
    Ok(resolved)
}

fn validate_package_members(units: &[CatalogUnit]) -> Result<(), Vec<Diagnostic>> {
    let mut members = BTreeMap::<PackageKey, BTreeMap<String, (&str, Span, &str)>>::new();
    for unit in units {
        let table = members.entry(unit.package.clone()).or_default();
        for (kind, name, span) in unit
            .ast
            .aliases()
            .iter()
            .map(|d| ("alias", &d.name, d.span))
            .chain(
                unit.ast
                    .structs()
                    .iter()
                    .map(|d| ("struct", &d.name, d.span)),
            )
            .chain(unit.ast.enums().iter().map(|d| ("enum", &d.name, d.span)))
            .chain(
                unit.ast
                    .classes()
                    .iter()
                    .map(|d| ("class", &d.name, d.span)),
            )
            .chain(
                unit.ast
                    .interfaces()
                    .iter()
                    .map(|d| ("interface", &d.name, d.span)),
            )
            .chain(
                unit.ast
                    .functions()
                    .iter()
                    .map(|d| ("function", &d.name, d.span)),
            )
        {
            if let Some((previous_kind, previous_span, previous_source)) =
                table.insert(name.clone(), (kind, span, &unit.logical))
            {
                if kind == "function" && previous_kind == "function" {
                    continue;
                }
                return Err(vec![Diagnostic::new("E0240", Phase::Semantic, DiagnosticCategory::Name, format!("duplicate package member `{}` across `{previous_source}` ({previous_kind} at {}..{}) and `{}` ({kind})", name, previous_span.start, previous_span.end, unit.logical), Some(span)).with_source_name(&unit.logical)]);
            }
        }
    }
    let keys = members.keys().cloned().collect::<Vec<_>>();
    for package in &keys {
        let Some((origin, path)) = package.named_parts() else {
            continue;
        };
        for child in keys.iter().filter(|candidate| {
            candidate
                .named_parts()
                .is_some_and(|(candidate_origin, candidate_path)| {
                    candidate_origin == origin
                        && candidate_path.0.len() == path.0.len() + 1
                        && candidate_path.0.starts_with(&path.0)
                })
        }) {
            let child_path = child.named_parts().expect("filtered named child").1;
            let child_name = child_path.0.last().unwrap();
            if let Some((kind, span, source)) = members[package].get(child_name) {
                return Err(vec![Diagnostic::new("E0236", Phase::Semantic, DiagnosticCategory::Name, format!("package member `{child_name}` ({kind}) collides with child package `{}`", child_path.canonical()), Some(*span)).with_source_name(*source)]);
            }
        }
    }
    Ok(())
}

/// A canonical standalone Aether source selected by an embedding frontend.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StandaloneFile {
    path: PathBuf,
}

/// Fully resolved and validated project boundary supplied by a frontend.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProjectPlan {
    root: PathBuf,
    manifest: PathBuf,
    package: PackageMetadata,
    source: PathBuf,
    kind: ProjectKind,
    root_instance: PackageInstanceKey,
    packages: BTreeMap<PackageInstanceKey, ResolvedPackage>,
}

impl ProjectPlan {
    /// Loads the existing package lock through the package authority without network or writes.
    pub fn load_read_only(root: &Path) -> Result<Self, String> {
        let graph = aether_package::load_locked(root, None)?;
        Self::resolved(graph.root, &graph.packages).map_err(|diagnostics| {
            diagnostics
                .into_iter()
                .map(|diagnostic| diagnostic.message)
                .collect::<Vec<_>>()
                .join("; ")
        })
    }

    /// Revalidates canonical paths and critical V1 project invariants.
    pub fn new(
        root: impl AsRef<Path>,
        manifest: impl AsRef<Path>,
        package: PackageMetadata,
        source: impl AsRef<Path>,
        kind: ProjectKind,
    ) -> Result<Self, Vec<Diagnostic>> {
        let root = root.as_ref().canonicalize().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not resolve project root: {error}"
            ))]
        })?;
        if !root.is_dir() {
            return Err(vec![io_diagnostic("project root is not a directory")]);
        }
        if package.aether.as_deref().is_some_and(|value| value != "1") {
            return Err(vec![io_diagnostic(
                "package Aether compatibility currently accepts only `1`",
            )]);
        }
        let expected_manifest = root.join("aether.toml").canonicalize().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not resolve direct project manifest: {error}"
            ))]
        })?;
        let manifest = manifest.as_ref().canonicalize().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not resolve project manifest: {error}"
            ))]
        })?;
        if manifest != expected_manifest || !manifest.is_file() {
            return Err(vec![io_diagnostic(
                "project manifest must be the regular file `<root>/aether.toml`",
            )]);
        }
        let source = source.as_ref().canonicalize().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not resolve project source: {error}"
            ))]
        })?;
        if !source.starts_with(&root)
            || !source.is_file()
            || source.extension().and_then(|value| value.to_str()) != Some("ae")
        {
            return Err(vec![io_diagnostic(
                "project source must be a regular `.ae` file confined to the project root",
            )]);
        }
        if kind == ProjectKind::Library {
            let expected_library = root.join("src/lib.ae").canonicalize().map_err(|error| {
                vec![io_diagnostic(format!(
                    "could not resolve V1 library source: {error}"
                ))]
            })?;
            if source != expected_library {
                return Err(vec![io_diagnostic(
                    "V1 library source must be `<root>/src/lib.ae`",
                )]);
            }
        }
        let root_instance = PackageInstanceKey::Root {
            manifest: manifest.to_string_lossy().into_owned(),
            name: package.name.as_str().to_owned(),
            version: package.version.as_str().to_owned(),
        };
        let root_package = ResolvedPackage::new(
            root_instance.clone(),
            root.clone(),
            manifest.clone(),
            package.clone(),
            source.clone(),
            kind,
            BTreeMap::new(),
        );
        Ok(Self {
            root,
            manifest,
            package,
            source,
            kind,
            root_instance: root_instance.clone(),
            packages: BTreeMap::from([(root_instance, root_package)]),
        })
    }

    /// Builds a resolved multi-root graph. The compiler receives only canonical package nodes
    /// and exact dependency edges; it never reads manifests or dependency locators.
    pub fn resolved(
        root_instance: PackageInstanceKey,
        packages: &BTreeMap<PackageInstanceKey, ResolvedPackage>,
    ) -> Result<Self, Vec<Diagnostic>> {
        if !matches!(root_instance, PackageInstanceKey::Root { .. }) {
            return Err(vec![io_diagnostic(
                "resolved package graph root does not have root identity",
            )]);
        }
        if !packages.contains_key(&root_instance) {
            return Err(vec![io_diagnostic(
                "resolved package graph has no root node",
            )]);
        }
        let mut validated = BTreeMap::new();
        for (key, node) in packages {
            if key != &root_instance
                && (matches!(key, PackageInstanceKey::Root { .. })
                    || node.kind() != ProjectKind::Library)
            {
                return Err(vec![io_diagnostic(
                    "resolved dependency nodes must be non-root library packages",
                )]);
            }
            if key != node.instance() {
                return Err(vec![io_diagnostic(
                    "resolved package graph key does not match its node identity",
                )]);
            }
            let rebuilt = Self::new(
                node.root(),
                node.manifest(),
                node.package.clone(),
                node.source(),
                node.kind,
            )?;
            let expected = match key {
                PackageInstanceKey::Root {
                    manifest,
                    name,
                    version,
                }
                | PackageInstanceKey::Path {
                    manifest,
                    name,
                    version,
                } => {
                    manifest == &node.manifest.to_string_lossy()
                        && name == node.package.name.as_str()
                        && version == node.package.version.as_str()
                }
                PackageInstanceKey::Registry {
                    name,
                    version,
                    checksum,
                    ..
                } => {
                    name == node.package.name.as_str()
                        && version == node.package.version.as_str()
                        && !checksum.is_empty()
                }
            };
            if !expected {
                return Err(vec![io_diagnostic(
                    "package instance identity does not match canonical manifest metadata",
                )]);
            }
            for (name, target) in &node.dependencies {
                let Some(target_node) = packages.get(target) else {
                    return Err(vec![io_diagnostic(format!(
                        "dependency edge `{name}` has no resolved target"
                    ))]);
                };
                if name != target_node.package.name.as_str() {
                    return Err(vec![io_diagnostic(format!(
                        "dependency edge `{name}` does not match target package `{}`",
                        target_node.package.name.as_str()
                    ))]);
                }
            }
            let mut canonical = rebuilt.packages.into_values().next().expect("root package");
            canonical.instance = key.clone();
            canonical.dependencies.clone_from(&node.dependencies);
            validated.insert(key.clone(), canonical);
        }
        validate_resolved_acyclic(&validated)?;
        let root_package = validated.get(&root_instance).expect("validated root");
        Ok(Self {
            root: root_package.root.clone(),
            manifest: root_package.manifest.clone(),
            package: root_package.package.clone(),
            source: root_package.source.clone(),
            kind: root_package.kind,
            root_instance,
            packages: validated,
        })
    }

    /// Canonical project root.
    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }
    /// Canonical direct manifest.
    #[must_use]
    pub fn manifest(&self) -> &Path {
        &self.manifest
    }
    /// Validated package metadata.
    #[must_use]
    pub const fn package(&self) -> &PackageMetadata {
        &self.package
    }
    /// Canonical selected source root file.
    #[must_use]
    pub fn source(&self) -> &Path {
        &self.source
    }
    /// Selected package class.
    #[must_use]
    pub const fn kind(&self) -> ProjectKind {
        self.kind
    }
    /// Exact root instance identity.
    #[must_use]
    pub const fn root_instance(&self) -> &PackageInstanceKey {
        &self.root_instance
    }
    /// All resolved nodes indexed by exact identity.
    #[must_use]
    pub const fn packages(&self) -> &BTreeMap<PackageInstanceKey, ResolvedPackage> {
        &self.packages
    }
    /// Canonical bootstrap build directory.
    #[must_use]
    pub fn build_directory(&self) -> PathBuf {
        self.root.join(".aether/build")
    }
    /// Canonical retained artifact path for this package.
    #[must_use]
    pub fn artifact_path(&self) -> PathBuf {
        let name = self.package.name.as_str();
        match self.kind {
            ProjectKind::Application => self.build_directory().join(name),
            ProjectKind::Library => self.build_directory().join(format!("{name}.aetherlib")),
        }
    }
}

fn instance_display_name(instance: &PackageInstanceKey) -> String {
    match instance {
        PackageInstanceKey::Root { name, .. }
        | PackageInstanceKey::Path { name, .. }
        | PackageInstanceKey::Registry { name, .. } => name.clone(),
    }
}

fn validate_resolved_acyclic(
    packages: &BTreeMap<PackageInstanceKey, ResolvedPackage>,
) -> Result<(), Vec<Diagnostic>> {
    fn visit(
        key: &PackageInstanceKey,
        packages: &BTreeMap<PackageInstanceKey, ResolvedPackage>,
        states: &mut BTreeMap<PackageInstanceKey, u8>,
        stack: &mut Vec<PackageInstanceKey>,
    ) -> Result<(), Vec<Diagnostic>> {
        match states.get(key).copied() {
            Some(2) => return Ok(()),
            Some(1) => {
                let position = stack.iter().position(|item| item == key).unwrap_or(0);
                let mut names = stack[position..]
                    .iter()
                    .map(instance_display_name)
                    .collect::<Vec<_>>();
                names.push(instance_display_name(key));
                return Err(vec![io_diagnostic(format!(
                    "resolved package cycle: {}",
                    names.join(" -> ")
                ))]);
            }
            _ => {}
        }
        states.insert(key.clone(), 1);
        stack.push(key.clone());
        for target in packages[key].dependencies.values() {
            visit(target, packages, states, stack)?;
        }
        stack.pop();
        states.insert(key.clone(), 2);
        Ok(())
    }

    let mut states = BTreeMap::new();
    let mut stack = Vec::new();
    for key in packages.keys() {
        visit(key, packages, &mut states, &mut stack)?;
    }
    Ok(())
}

impl StandaloneFile {
    /// Validates and canonicalizes one regular `.ae` file.
    pub fn new(path: impl AsRef<Path>) -> Result<Self, Vec<Diagnostic>> {
        let spelling = path.as_ref();
        let path = spelling.canonicalize().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not resolve standalone source `{}`: {error}",
                spelling.display()
            ))]
        })?;
        let metadata = path.metadata().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not inspect standalone source `{}`: {error}",
                path.display()
            ))]
        })?;
        if !metadata.is_file() {
            return Err(vec![io_diagnostic(format!(
                "standalone source is not a regular file: `{}`",
                path.display()
            ))]);
        }
        if path.extension().and_then(|extension| extension.to_str()) != Some("ae") {
            return Err(vec![io_diagnostic(format!(
                "standalone source must have extension `.ae`: `{}`",
                path.display()
            ))]);
        }
        Ok(Self { path })
    }

    /// Canonical source path.
    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Explicit source root used for the existing standalone import graph.
    #[must_use]
    pub fn source_root(&self) -> &Path {
        self.path.parent().unwrap_or_else(|| Path::new("."))
    }
}
fn io_diagnostic(message: impl Into<String>) -> Diagnostic {
    Diagnostic::new(
        "E0700",
        Phase::Driver,
        DiagnosticCategory::Io,
        message,
        None,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_DIRECTORY: AtomicU64 = AtomicU64::new(0);

    struct TestDirectory(PathBuf);

    impl TestDirectory {
        fn new(label: &str) -> Self {
            let sequence = NEXT_DIRECTORY.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "aether-analysis-{label}-{}-{sequence}",
                std::process::id()
            ));
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }

        fn write(&self, relative: &str, text: &str) -> PathBuf {
            let path = self.0.join(relative);
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent).unwrap();
            }
            fs::write(&path, text).unwrap();
            path
        }
    }

    impl Drop for TestDirectory {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    struct ReverseDiskProvider;

    impl SourceProvider for ReverseDiskProvider {
        fn enumerate(
            &self,
            scope: &SourceScope,
        ) -> Result<Vec<SourceDescriptor>, SourceProviderError> {
            let mut sources = DiskSourceProvider.enumerate(scope)?;
            sources.reverse();
            Ok(sources)
        }

        fn read(&self, locator: &SourceLocator) -> Result<SourceContent, SourceProviderError> {
            DiskSourceProvider.read(locator)
        }
    }

    struct FailingReadProvider;

    impl SourceProvider for FailingReadProvider {
        fn enumerate(
            &self,
            scope: &SourceScope,
        ) -> Result<Vec<SourceDescriptor>, SourceProviderError> {
            DiskSourceProvider.enumerate(scope)
        }

        fn read(&self, _locator: &SourceLocator) -> Result<SourceContent, SourceProviderError> {
            Err(SourceProviderError {
                message: "injected read failure".into(),
            })
        }
    }

    #[test]
    fn standalone_discovers_direct_and_transitive_imports_with_aliases() {
        let directory = TestDirectory::new("transitive");
        let entry = directory.write(
            "main.ae",
            "import Alpha as a; int main(){return a.answer();}",
        );
        directory.write(
            "alpha.ae",
            "package Alpha; import Beta; public int answer(){return Beta.value();}",
        );
        directory.write("beta.ae", "package Beta; public int value(){return 0;}");

        let session = CompilationSession::discover(&entry).unwrap();
        let names = session
            .modules()
            .iter()
            .map(|module| module.info().display_name.as_str())
            .collect::<Vec<_>>();
        assert!(names.contains(&"Alpha"));
        assert!(names.contains(&"Beta"));
        let entry_module = &session.modules()[session.entry().0 as usize];
        assert_eq!(entry_module.info().imports[0].alias.as_deref(), Some("a"));
    }

    #[test]
    fn enumeration_order_does_not_change_dense_or_logical_identities() {
        let directory = TestDirectory::new("ordering");
        let entry = directory.write(
            "main.ae",
            "import Alpha; int main(){return Alpha.answer();}",
        );
        directory.write("z.ae", "package Alpha; public int answer(){return 0;}");
        directory.write("a.ae", "package Alpha; public int helper(){return 1;}");

        let normal = discover_catalog_with_provider(&entry, None, &DiskSourceProvider).unwrap();
        let reversed = discover_catalog_with_provider(&entry, None, &ReverseDiskProvider).unwrap();
        let identity = |session: &CompilationSession| {
            session
                .modules()
                .iter()
                .map(|module| {
                    (
                        module.info().id,
                        module.info().key.clone(),
                        module.info().source_name.clone(),
                    )
                })
                .collect::<Vec<_>>()
        };
        assert_eq!(identity(&normal), identity(&reversed));
    }

    #[test]
    fn disk_content_has_exact_fingerprint_and_provenance() {
        let directory = TestDirectory::new("fingerprint");
        let path = directory.write("main.ae", "int main(){return 0;}");
        let content = DiskSourceProvider
            .read(&SourceLocator::Disk(path.clone()))
            .unwrap();
        assert_eq!(
            content.fingerprint.0,
            Sha256::digest(content.text.as_bytes()).as_slice()
        );
        assert!(
            matches!(content.provenance, SourceProvenance::Disk { canonical_path, .. } if canonical_path == path)
        );
    }

    #[test]
    fn provider_read_errors_preserve_loader_diagnostic_phase() {
        let directory = TestDirectory::new("read-error");
        let entry = directory.write("main.ae", "int main(){return 0;}");
        let errors =
            discover_catalog_with_provider(&entry, None, &FailingReadProvider).unwrap_err();
        assert_eq!(errors[0].code, "E0700");
        assert_eq!(errors[0].phase, Phase::Driver);
        assert!(errors[0].message.contains("injected read failure"));
    }

    #[test]
    fn discovery_adds_toolchain_sources_without_writing_project_files() {
        let directory = TestDirectory::new("toolchain-no-write");
        let entry = directory.write("main.ae", "import std.Math; int main(){return 0;}");
        let before = fs::read_dir(&directory.0).unwrap().count();
        let session = CompilationSession::discover(&entry).unwrap();
        let after = fs::read_dir(&directory.0).unwrap().count();
        assert_eq!(before, after);
        assert!(
            session
                .modules()
                .iter()
                .any(|module| module.info().display_name == "std.Math")
        );
        assert!(!directory.0.join("aether.lock").exists());
        assert!(!directory.0.join("aether.toml").exists());
    }

    #[test]
    fn missing_entries_keep_the_canonical_io_diagnostic() {
        let directory = TestDirectory::new("missing");
        let errors = CompilationSession::discover(&directory.0.join("missing.ae")).unwrap_err();
        assert_eq!(errors[0].code, "E0700");
        assert!(errors[0].message.contains("could not read entry source"));
    }
}
