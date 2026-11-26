//! Immutable editor document snapshots layered over the canonical source provider.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, RwLock};

use sha2::{Digest, Sha256};

use crate::{
    CompilationSession, ContentFingerprint, DiskSourceProvider, ProjectPlan, SourceContent,
    SourceDescriptor, SourceLocator, SourceProvenance, SourceProvider, SourceProviderError,
    SourceScope, discover_catalog_with_provider,
};

static NEXT_WORKSPACE_ID: AtomicU64 = AtomicU64::new(1);

macro_rules! numeric_id {
    ($name:ident) => {
        #[doc = concat!("Opaque ", stringify!($name), " value.")]
        #[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
        pub struct $name(pub u64);
    };
}

numeric_id!(WorkspaceId);
numeric_id!(ProjectId);
numeric_id!(DocumentId);
numeric_id!(DocumentVersion);

/// Location of an editor document. It is provenance, never semantic package identity.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum DocumentLocator {
    /// A workspace file, preserving its spelling and optional canonical target.
    File {
        /// Absolute, lexically normalized workspace path.
        logical_path: PathBuf,
        /// Canonical target when the file currently exists.
        canonical_path: Option<PathBuf>,
    },
    /// A document with no filesystem backing.
    Virtual {
        /// Stable editor URI.
        uri: Arc<str>,
    },
}

impl DocumentLocator {
    /// Creates a file locator. Existing symlink aliases collapse to the same canonical target.
    pub fn file(path: impl AsRef<Path>) -> Result<Self, StoreError> {
        let spelling = path.as_ref();
        if is_toolchain_path(spelling) {
            return Err(StoreError::ToolchainImmutable);
        }
        let logical_path = lexical_absolute(spelling)?;
        let canonical_path = logical_path.canonicalize().ok();
        Ok(Self::File {
            logical_path,
            canonical_path,
        })
    }

    /// Creates a virtual locator.
    pub fn virtual_document(uri: impl Into<Arc<str>>) -> Result<Self, StoreError> {
        let uri = uri.into();
        if uri.starts_with("aether-toolchain:") || uri.starts_with("<toolchain>") {
            return Err(StoreError::ToolchainImmutable);
        }
        Ok(Self::Virtual { uri })
    }

    fn identity(&self) -> LocatorIdentity {
        match self {
            Self::File {
                logical_path,
                canonical_path,
            } => LocatorIdentity::File(canonical_path.as_ref().unwrap_or(logical_path).clone()),
            Self::Virtual { uri } => LocatorIdentity::Virtual(Arc::clone(uri)),
        }
    }

    fn disk_path(&self) -> Option<&Path> {
        match self {
            Self::File {
                logical_path,
                canonical_path,
            } => Some(canonical_path.as_deref().unwrap_or(logical_path)),
            Self::Virtual { .. } => None,
        }
    }
}

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
enum LocatorIdentity {
    File(PathBuf),
    Virtual(Arc<str>),
}

/// Last observed state of a document's filesystem backing.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DiskBase {
    /// A regular readable file was observed.
    Present {
        /// Fingerprint of the exact bytes observed.
        fingerprint: ContentFingerprint,
    },
    /// No file currently exists.
    Missing,
    /// Virtual documents have no disk backing.
    NotApplicable,
}

/// Mutable lifecycle state copied into immutable snapshots.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DocumentState {
    /// The editor text is authoritative.
    Open {
        /// Immutable complete document text.
        text: Arc<str>,
        /// Last observed disk state.
        disk_base: DiskBase,
        /// Whether overlay text differs from the observed disk content.
        dirty: bool,
    },
    /// No overlay is installed; future reads use the filesystem.
    Closed {
        /// Last observed disk state.
        disk_base: DiskBase,
    },
}

/// One document tracked for the lifetime of a workspace.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DocumentRecord {
    /// Stable workspace-local identity.
    pub id: DocumentId,
    /// Location/provenance, distinct from compiler identities.
    pub locator: DocumentLocator,
    /// Monotonic store-owned version.
    pub version: DocumentVersion,
    /// Last accepted protocol version, if supplied.
    pub client_version: Option<i64>,
    /// Current lifecycle state.
    pub state: DocumentState,
    /// Optional owning project identity.
    pub project: Option<ProjectId>,
}

/// Input for opening or reopening a document.
#[derive(Clone, Debug)]
pub struct OpenDocument {
    /// File or virtual location.
    pub locator: DocumentLocator,
    /// Complete editor text.
    pub text: Arc<str>,
    /// Optional protocol version.
    pub client_version: Option<i64>,
    /// Optional validated project association.
    pub project: Option<ProjectId>,
}

/// Input for replacing the complete text of an open document.
#[derive(Clone, Debug)]
pub struct ChangeDocument {
    /// Open document being changed.
    pub document: DocumentId,
    /// New complete editor text.
    pub text: Arc<str>,
    /// Optional monotonic protocol version.
    pub client_version: Option<i64>,
}

/// Input for the save notification. Disk is independently re-read and verified.
#[derive(Clone, Copy, Debug)]
pub struct SavedDocument {
    /// Open document being saved.
    pub document: DocumentId,
    /// Optional protocol version accompanying the notification.
    pub client_version: Option<i64>,
}

/// Filesystem notification. It never writes the changed path.
#[derive(Clone, Debug)]
pub struct FileChange {
    /// Changed path or symlink spelling.
    pub path: PathBuf,
}

/// Analysis configuration captured atomically with overlays.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct AnalysisConfig {
    /// User-facing target name, if configured by the embedding frontend.
    pub target: Option<Arc<str>>,
}

/// Document-store failure.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StoreError {
    /// The document identity is unknown in this workspace.
    UnknownDocument(DocumentId),
    /// The operation requires an open document.
    DocumentClosed(DocumentId),
    /// The document is already open.
    AlreadyOpen(DocumentId),
    /// A client version moved backwards.
    RegressiveClientVersion {
        /// Last version accepted by the store.
        previous: i64,
        /// Version supplied by the client operation.
        received: i64,
    },
    /// Compiler-owned toolchain content is immutable.
    ToolchainImmutable,
    /// The path cannot be represented inside the store.
    InvalidPath(String),
}

impl fmt::Display for StoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownDocument(id) => write!(formatter, "unknown document {}", id.0),
            Self::DocumentClosed(id) => write!(formatter, "document {} is closed", id.0),
            Self::AlreadyOpen(id) => write!(formatter, "document {} is already open", id.0),
            Self::RegressiveClientVersion { previous, received } => write!(
                formatter,
                "client version {received} regresses from {previous}"
            ),
            Self::ToolchainImmutable => formatter.write_str("toolchain sources are immutable"),
            Self::InvalidPath(message) => formatter.write_str(message),
        }
    }
}

impl std::error::Error for StoreError {}

#[derive(Debug)]
struct WorkspaceState {
    revision: u64,
    next_document: u64,
    documents: BTreeMap<DocumentId, DocumentRecord>,
    locators: BTreeMap<LocatorIdentity, DocumentId>,
    project_generations: BTreeMap<ProjectId, u64>,
    projects: BTreeMap<ProjectId, Arc<ProjectPlan>>,
    config: Arc<AnalysisConfig>,
}

/// Thread-safe owner of editor document state.
#[derive(Debug)]
pub struct EditorWorkspace {
    id: WorkspaceId,
    root: PathBuf,
    state: RwLock<WorkspaceState>,
}

impl EditorWorkspace {
    /// Creates an isolated workspace. The root must already exist.
    pub fn new(root: impl AsRef<Path>) -> Result<Self, StoreError> {
        let root = root
            .as_ref()
            .canonicalize()
            .map_err(|error| StoreError::InvalidPath(error.to_string()))?;
        Ok(Self {
            id: WorkspaceId(NEXT_WORKSPACE_ID.fetch_add(1, Ordering::Relaxed)),
            root,
            state: RwLock::new(WorkspaceState {
                revision: 0,
                next_document: 1,
                documents: BTreeMap::new(),
                locators: BTreeMap::new(),
                project_generations: BTreeMap::new(),
                projects: BTreeMap::new(),
                config: Arc::new(AnalysisConfig::default()),
            }),
        })
    }

    /// Stable workspace identity.
    #[must_use]
    pub const fn id(&self) -> WorkspaceId {
        self.id
    }

    /// Opens a document and installs its overlay.
    pub fn open(&self, mut input: OpenDocument) -> Result<DocumentId, StoreError> {
        validate_locator(&input.locator)?;
        refresh_locator(&mut input.locator);
        let identity = input.locator.identity();
        let disk_base = observe_disk(input.locator.disk_path()).0;
        let dirty = disk_text(input.locator.disk_path()).as_deref() != Some(input.text.as_ref());
        let mut state = self.state.write().expect("document store poisoned");
        let existing = state.locators.get(&identity).copied().or_else(|| {
            state.documents.values().find_map(|record| {
                (record.locator.identity() == identity
                    || same_logical_file(&record.locator, &input.locator))
                .then_some(record.id)
            })
        });
        let id = if let Some(id) = existing {
            let record = state
                .documents
                .get_mut(&id)
                .expect("locator index is valid");
            if matches!(record.state, DocumentState::Open { .. }) {
                return Err(StoreError::AlreadyOpen(id));
            }
            record.version.0 += 1;
            record.locator = input.locator;
            record.client_version = input.client_version;
            record.project = input.project;
            record.state = DocumentState::Open {
                text: input.text,
                disk_base,
                dirty,
            };
            state.locators.insert(identity, id);
            id
        } else {
            let id = DocumentId(state.next_document);
            state.next_document += 1;
            state.locators.insert(identity, id);
            state.documents.insert(
                id,
                DocumentRecord {
                    id,
                    locator: input.locator,
                    version: DocumentVersion(1),
                    client_version: input.client_version,
                    state: DocumentState::Open {
                        text: input.text,
                        disk_base,
                        dirty,
                    },
                    project: input.project,
                },
            );
            id
        };
        state.revision += 1;
        Ok(id)
    }

    /// Replaces the complete text of an open document.
    pub fn change(&self, input: ChangeDocument) -> Result<DocumentVersion, StoreError> {
        let mut state = self.state.write().expect("document store poisoned");
        let record = state
            .documents
            .get_mut(&input.document)
            .ok_or(StoreError::UnknownDocument(input.document))?;
        ensure_client_version(record.client_version, input.client_version)?;
        let DocumentState::Open { disk_base, .. } = record.state else {
            return Err(StoreError::DocumentClosed(input.document));
        };
        let text = input.text;
        let dirty = disk_text(record.locator.disk_path()).as_deref() != Some(text.as_ref());
        record.version.0 += 1;
        record.client_version = input.client_version.or(record.client_version);
        record.state = DocumentState::Open {
            text,
            disk_base,
            dirty,
        };
        let version = record.version;
        state.revision += 1;
        Ok(version)
    }

    /// Refreshes disk state after a save notification without trusting or writing client data.
    pub fn saved(&self, input: SavedDocument) -> Result<DocumentVersion, StoreError> {
        let mut state = self.state.write().expect("document store poisoned");
        let record = state
            .documents
            .get_mut(&input.document)
            .ok_or(StoreError::UnknownDocument(input.document))?;
        ensure_client_version(record.client_version, input.client_version)?;
        let DocumentState::Open { text, .. } = &record.state else {
            return Err(StoreError::DocumentClosed(input.document));
        };
        let text = Arc::clone(text);
        let (disk_base, observed) = observe_disk(record.locator.disk_path());
        record.version.0 += 1;
        record.client_version = input.client_version.or(record.client_version);
        record.state = DocumentState::Open {
            dirty: observed.as_deref() != Some(text.as_ref()),
            text,
            disk_base,
        };
        let version = record.version;
        state.revision += 1;
        Ok(version)
    }

    /// Removes an overlay while retaining stable document identity and version history.
    pub fn close(&self, document: DocumentId) -> Result<(), StoreError> {
        let mut state = self.state.write().expect("document store poisoned");
        let record = state
            .documents
            .get_mut(&document)
            .ok_or(StoreError::UnknownDocument(document))?;
        if matches!(record.state, DocumentState::Closed { .. }) {
            return Err(StoreError::DocumentClosed(document));
        }
        let disk_base = observe_disk(record.locator.disk_path()).0;
        record.version.0 += 1;
        record.state = DocumentState::Closed { disk_base };
        state.revision += 1;
        Ok(())
    }

    /// Applies an external filesystem notification to matching documents.
    pub fn filesystem_changed(&self, change: FileChange) -> Result<(), StoreError> {
        let FileChange { path: changed_path } = change;
        let changed = DocumentLocator::file(&changed_path)?;
        let changed_identity = changed.identity();
        let mut state = self.state.write().expect("document store poisoned");
        let mut matched = false;
        for record in state.documents.values_mut() {
            let logical_match = record.locator.disk_path().is_some_and(|path| {
                lexical_absolute(path).ok() == lexical_absolute(&changed_path).ok()
            });
            if record.locator.identity() != changed_identity && !logical_match {
                continue;
            }
            matched = true;
            refresh_locator(&mut record.locator);
            let (disk_base, observed) = observe_disk(record.locator.disk_path());
            match &record.state {
                DocumentState::Open { text, .. } => {
                    record.state = DocumentState::Open {
                        dirty: observed.as_deref() != Some(text.as_ref()),
                        text: Arc::clone(text),
                        disk_base,
                    };
                }
                DocumentState::Closed { .. } => {
                    record.state = DocumentState::Closed { disk_base };
                }
            }
        }
        // Even an untracked manifest/lock/source change invalidates topology.
        if matched || changed_path.starts_with(&self.root) {
            state.revision += 1;
        }
        Ok(())
    }

    /// Returns a copy suitable for UI state inspection.
    #[must_use]
    pub fn document(&self, document: DocumentId) -> Option<DocumentRecord> {
        self.state
            .read()
            .expect("document store poisoned")
            .documents
            .get(&document)
            .cloned()
    }

    /// Updates analysis configuration and invalidates prior results.
    pub fn set_config(&self, config: AnalysisConfig) {
        let mut state = self.state.write().expect("document store poisoned");
        state.config = Arc::new(config);
        state.revision += 1;
    }

    /// Records a validated project generation (manifest/lock changes create a new generation).
    pub fn set_project_generation(&self, project: ProjectId, generation: u64) {
        let mut state = self.state.write().expect("document store poisoned");
        if state.project_generations.insert(project, generation) != Some(generation) {
            state.revision += 1;
        }
    }

    /// Installs an already validated read-only project plan in the workspace.
    pub fn set_project(&self, project: ProjectId, generation: u64, plan: ProjectPlan) {
        let mut state = self.state.write().expect("document store poisoned");
        state.project_generations.insert(project, generation);
        state.projects.insert(project, Arc::new(plan));
        state.revision += 1;
    }

    /// Captures all overlays, versions, projects and configuration under one short read lock.
    #[must_use]
    pub fn snapshot(&self) -> AnalysisSnapshot {
        let state = self.state.read().expect("document store poisoned");
        let mut overlays = BTreeMap::new();
        let mut documents = BTreeMap::new();
        let mut document_versions = Vec::new();
        for record in state.documents.values() {
            document_versions.push((record.id, record.version));
            documents.insert(
                record.id,
                SnapshotDocument {
                    path: record.locator.disk_path().map(Path::to_path_buf),
                    project: record.project,
                    open: matches!(record.state, DocumentState::Open { .. }),
                },
            );
            let DocumentState::Open { text, .. } = &record.state else {
                continue;
            };
            if let Some(path) = record.locator.disk_path() {
                overlays.insert(
                    path.to_path_buf(),
                    OverlayEntry {
                        document: record.id,
                        version: record.version,
                        text: Arc::clone(text),
                    },
                );
            }
        }
        let project_generations = state
            .project_generations
            .iter()
            .map(|(id, generation)| (*id, *generation))
            .collect::<Vec<_>>();
        AnalysisSnapshot {
            stamp: SnapshotStamp {
                workspace: self.id,
                revision: state.revision,
                document_versions: document_versions.into(),
                project_generations: project_generations.into(),
            },
            overlays: Arc::new(overlays),
            config: Arc::clone(&state.config),
            projects: Arc::new(state.projects.clone()),
            documents: Arc::new(documents),
        }
    }

    /// Validates whether a completed snapshot analysis can still be published.
    #[must_use]
    pub fn may_publish(
        &self,
        result: &SnapshotDiscovery,
        target: Option<DocumentId>,
    ) -> PublishDecision {
        let state = self.state.read().expect("document store poisoned");
        if result.stamp.workspace != self.id || result.stamp.revision != state.revision {
            return PublishDecision::Stale;
        }
        if let Some(document) = target {
            let Some(record) = state.documents.get(&document) else {
                return PublishDecision::DocumentClosed;
            };
            if matches!(record.state, DocumentState::Closed { .. }) {
                return PublishDecision::DocumentClosed;
            }
        }
        drop(state);
        for read in result
            .sources
            .iter()
            .filter(|read| !read.from_overlay && !read.toolchain)
        {
            match DiskSourceProvider.read(&SourceLocator::Disk(read.path.clone())) {
                Ok(content) if content.fingerprint == read.fingerprint => {}
                Ok(_) => return PublishDecision::SourceChanged,
                Err(error) => return PublishDecision::ProviderError(error.to_string()),
            }
        }
        PublishDecision::Current
    }
}

/// Complete identity/revision label for one immutable snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SnapshotStamp {
    /// Workspace that created the snapshot.
    pub workspace: WorkspaceId,
    /// Overlay/project/config revision.
    pub revision: u64,
    /// All known document versions in deterministic ID order.
    pub document_versions: Arc<[(DocumentId, DocumentVersion)]>,
    /// Validated project generations in deterministic ID order.
    pub project_generations: Arc<[(ProjectId, u64)]>,
}

#[derive(Clone, Debug)]
struct OverlayEntry {
    document: DocumentId,
    version: DocumentVersion,
    text: Arc<str>,
}

/// Immutable document/config capture. Disk reads happen later and are inventoried separately.
#[derive(Clone, Debug)]
pub struct AnalysisSnapshot {
    /// Revision label used for stale suppression.
    pub stamp: SnapshotStamp,
    overlays: Arc<BTreeMap<PathBuf, OverlayEntry>>,
    config: Arc<AnalysisConfig>,
    projects: Arc<BTreeMap<ProjectId, Arc<ProjectPlan>>>,
    documents: Arc<BTreeMap<DocumentId, SnapshotDocument>>,
}

#[derive(Clone, Debug)]
pub(crate) struct SnapshotDocument {
    pub(crate) path: Option<PathBuf>,
    pub(crate) project: Option<ProjectId>,
    pub(crate) open: bool,
}

impl AnalysisSnapshot {
    /// Captured analysis configuration.
    #[must_use]
    pub fn config(&self) -> &AnalysisConfig {
        &self.config
    }

    /// Constructs a provider sharing exactly this snapshot's overlays.
    #[must_use]
    pub fn provider(&self) -> OverlaySourceProvider<DiskSourceProvider> {
        self.overlay_provider(DiskSourceProvider)
    }

    /// Composes an arbitrary base provider with this snapshot's overlays.
    #[must_use]
    pub fn overlay_provider<P>(&self, base: P) -> OverlaySourceProvider<P> {
        OverlaySourceProvider::new(base, Arc::clone(&self.overlays))
    }

    /// Returns a validated project plan owned by this immutable snapshot.
    #[must_use]
    pub fn project(&self, project: ProjectId) -> Option<&ProjectPlan> {
        self.projects.get(&project).map(AsRef::as_ref)
    }

    pub(crate) fn document_target(
        &self,
        document: DocumentId,
    ) -> Option<(Option<&Path>, Option<ProjectId>, bool)> {
        self.documents
            .get(&document)
            .map(|item| (item.path.as_deref(), item.project, item.open))
    }

    /// Runs the existing canonical discovery implementation and labels its output.
    pub fn discover(
        &self,
        entry: &Path,
        project: Option<&ProjectPlan>,
    ) -> Result<SnapshotDiscovery, Vec<aether_frontend::Diagnostic>> {
        let provider = self.provider();
        let session = discover_catalog_with_provider(entry, project, &provider)?;
        let mut sources = provider.source_inventory();
        sources.extend(
            session
                .modules()
                .iter()
                .filter(|module| module.source().name.starts_with("<toolchain>/"))
                .map(|module| SnapshotSourceRead {
                    path: PathBuf::from(&module.source().name),
                    fingerprint: fingerprint(&module.source().text),
                    from_overlay: false,
                    toolchain: true,
                    document: None,
                    text: Arc::from(module.source().text.as_str()),
                }),
        );
        sources.sort_by(|left, right| left.path.cmp(&right.path));
        Ok(SnapshotDiscovery {
            stamp: self.stamp.clone(),
            session,
            sources: sources.into(),
        })
    }
}

/// One source effectively read while constructing a canonical session.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SnapshotSourceRead {
    /// Provider path.
    pub path: PathBuf,
    /// Fingerprint of exact bytes returned.
    pub fingerprint: ContentFingerprint,
    /// Whether an immutable editor overlay supplied the bytes.
    pub from_overlay: bool,
    /// Whether the compiler's embedded immutable toolchain supplied the bytes.
    pub toolchain: bool,
    /// Overlay identity/version, absent for disk.
    pub document: Option<(DocumentId, DocumentVersion)>,
    /// Exact immutable UTF-8 text returned by the provider.
    pub text: Arc<str>,
}

/// Canonical discovery output unambiguously associated with its input snapshot.
#[derive(Clone, Debug)]
pub struct SnapshotDiscovery {
    /// Snapshot that originated this result.
    pub stamp: SnapshotStamp,
    /// Canonical module/catalog session.
    pub session: CompilationSession,
    /// Deterministic inventory of content actually read.
    pub sources: Arc<[SnapshotSourceRead]>,
}

/// Result of comparing completed work with current workspace/external source state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PublishDecision {
    /// Overlay revision and external disk inputs still match.
    Current,
    /// A later workspace revision exists.
    Stale,
    /// The target is no longer open.
    DocumentClosed,
    /// A disk source changed after analysis.
    SourceChanged,
    /// A disk source can no longer be verified.
    ProviderError(String),
}

/// Provider composition used by editor snapshots. It never assigns semantic identities.
#[derive(Debug)]
pub struct OverlaySourceProvider<P> {
    base: P,
    overlays: Arc<BTreeMap<PathBuf, OverlayEntry>>,
    reads: Arc<Mutex<BTreeMap<PathBuf, SnapshotSourceRead>>>,
}

impl<P: Clone> Clone for OverlaySourceProvider<P> {
    fn clone(&self) -> Self {
        Self {
            base: self.base.clone(),
            overlays: Arc::clone(&self.overlays),
            reads: Arc::clone(&self.reads),
        }
    }
}

impl<P> OverlaySourceProvider<P> {
    fn new(base: P, overlays: Arc<BTreeMap<PathBuf, OverlayEntry>>) -> Self {
        Self {
            base,
            overlays,
            reads: Arc::new(Mutex::new(BTreeMap::new())),
        }
    }

    /// Returns the deterministic external-content inventory observed so far.
    #[must_use]
    pub fn source_inventory(&self) -> Vec<SnapshotSourceRead> {
        self.reads
            .lock()
            .expect("source inventory poisoned")
            .values()
            .cloned()
            .collect()
    }

    fn overlay_for(&self, path: &Path) -> Option<(&PathBuf, &OverlayEntry)> {
        self.overlays.get_key_value(path).or_else(|| {
            let canonical = path.canonicalize().ok()?;
            self.overlays
                .iter()
                .find(|(candidate, _)| candidate.canonicalize().ok().as_ref() == Some(&canonical))
        })
    }
}

impl<P: SourceProvider> SourceProvider for OverlaySourceProvider<P> {
    fn enumerate(&self, scope: &SourceScope) -> Result<Vec<SourceDescriptor>, SourceProviderError> {
        let mut descriptors = self.base.enumerate(scope)?;
        let mut known = descriptors
            .iter()
            .map(|descriptor| descriptor.locator.clone())
            .collect::<BTreeSet<_>>();
        for path in self.overlays.keys() {
            if path.extension().and_then(|extension| extension.to_str()) != Some("ae")
                || !path.starts_with(&scope.root)
            {
                continue;
            }
            let locator = SourceLocator::Disk(path.clone());
            if known.insert(locator.clone()) {
                let relative = path.strip_prefix(&scope.root).expect("checked prefix");
                descriptors.push(SourceDescriptor {
                    logical_name: relative
                        .components()
                        .map(|component| component.as_os_str().to_string_lossy())
                        .collect::<Vec<_>>()
                        .join("/"),
                    locator,
                });
            }
        }
        descriptors.sort_by(|left, right| left.logical_name.cmp(&right.logical_name));
        Ok(descriptors)
    }

    fn read(&self, locator: &SourceLocator) -> Result<SourceContent, SourceProviderError> {
        let SourceLocator::Disk(path) = locator;
        if is_toolchain_path(path) {
            return Err(SourceProviderError {
                message: "toolchain sources cannot be supplied by an overlay provider".into(),
            });
        }
        let (content, read) = if let Some((overlay_path, overlay)) = self.overlay_for(path) {
            let fingerprint = fingerprint(&overlay.text);
            (
                SourceContent {
                    text: Arc::clone(&overlay.text),
                    fingerprint,
                    provenance: SourceProvenance::Overlay {
                        document: overlay.document,
                        version: overlay.version,
                    },
                },
                SnapshotSourceRead {
                    path: overlay_path.clone(),
                    fingerprint,
                    from_overlay: true,
                    toolchain: false,
                    document: Some((overlay.document, overlay.version)),
                    text: Arc::clone(&overlay.text),
                },
            )
        } else {
            let content = self.base.read(locator)?;
            let read = SnapshotSourceRead {
                path: path.clone(),
                fingerprint: content.fingerprint,
                from_overlay: false,
                toolchain: false,
                document: None,
                text: Arc::clone(&content.text),
            };
            (content, read)
        };
        self.reads
            .lock()
            .expect("source inventory poisoned")
            .insert(read.path.clone(), read);
        Ok(content)
    }
}

fn ensure_client_version(previous: Option<i64>, received: Option<i64>) -> Result<(), StoreError> {
    if let (Some(previous), Some(received)) = (previous, received)
        && received < previous
    {
        return Err(StoreError::RegressiveClientVersion { previous, received });
    }
    Ok(())
}

fn validate_locator(locator: &DocumentLocator) -> Result<(), StoreError> {
    match locator {
        DocumentLocator::File { logical_path, .. } if is_toolchain_path(logical_path) => {
            Err(StoreError::ToolchainImmutable)
        }
        DocumentLocator::Virtual { uri }
            if uri.starts_with("aether-toolchain:") || uri.starts_with("<toolchain>") =>
        {
            Err(StoreError::ToolchainImmutable)
        }
        _ => Ok(()),
    }
}

fn same_logical_file(left: &DocumentLocator, right: &DocumentLocator) -> bool {
    match (left, right) {
        (
            DocumentLocator::File {
                logical_path: left, ..
            },
            DocumentLocator::File {
                logical_path: right,
                ..
            },
        ) => left == right,
        _ => false,
    }
}

fn refresh_locator(locator: &mut DocumentLocator) {
    if let DocumentLocator::File {
        logical_path,
        canonical_path,
    } = locator
    {
        *canonical_path = logical_path.canonicalize().ok();
    }
}

fn observe_disk(path: Option<&Path>) -> (DiskBase, Option<Arc<str>>) {
    let Some(path) = path else {
        return (DiskBase::NotApplicable, None);
    };
    let Ok(bytes) = fs::read(path) else {
        return (DiskBase::Missing, None);
    };
    let fingerprint = ContentFingerprint(Sha256::digest(&bytes).into());
    let text = String::from_utf8(bytes).ok().map(Arc::from);
    (DiskBase::Present { fingerprint }, text)
}

fn disk_text(path: Option<&Path>) -> Option<Arc<str>> {
    observe_disk(path).1
}

fn fingerprint(text: &str) -> ContentFingerprint {
    ContentFingerprint(Sha256::digest(text.as_bytes()).into())
}

fn lexical_absolute(path: &Path) -> Result<PathBuf, StoreError> {
    let path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|error| StoreError::InvalidPath(error.to_string()))?
            .join(path)
    };
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                if !normalized.pop() {
                    return Err(StoreError::InvalidPath(format!(
                        "path escapes its absolute root: {}",
                        path.display()
                    )));
                }
            }
            other => normalized.push(other.as_os_str()),
        }
    }
    Ok(normalized)
}

fn is_toolchain_path(path: &Path) -> bool {
    path.components()
        .any(|component| component.as_os_str() == "<toolchain>")
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
                "aether-editor-{label}-{}-{sequence}",
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

    fn open_file(workspace: &EditorWorkspace, path: &Path, text: &str) -> DocumentId {
        workspace
            .open(OpenDocument {
                locator: DocumentLocator::file(path).unwrap(),
                text: Arc::from(text),
                client_version: Some(1),
                project: None,
            })
            .unwrap()
    }

    #[test]
    fn identity_survives_close_and_versions_are_monotonic() {
        let directory = TestDirectory::new("identity");
        let path = directory.write("main.ae", "int main(){return 0;}");
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let id = open_file(&workspace, &path, "int main(){return 1;}");
        assert_eq!(
            workspace
                .change(ChangeDocument {
                    document: id,
                    text: Arc::from("int main(){return 2;}"),
                    client_version: Some(2),
                })
                .unwrap(),
            DocumentVersion(2)
        );
        workspace.close(id).unwrap();
        let reopened = workspace
            .open(OpenDocument {
                locator: DocumentLocator::file(&path).unwrap(),
                text: Arc::from("int main(){return 3;}"),
                client_version: Some(1),
                project: None,
            })
            .unwrap();
        assert_eq!(id, reopened);
        assert_eq!(workspace.document(id).unwrap().version, DocumentVersion(4));
    }

    #[test]
    fn invalid_transitions_and_regressive_versions_are_rejected() {
        let directory = TestDirectory::new("transitions");
        let path = directory.write("main.ae", "int main(){return 0;}");
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let id = open_file(&workspace, &path, "int main(){return 1;}");
        assert!(matches!(
            workspace.change(ChangeDocument {
                document: id,
                text: Arc::from("bad"),
                client_version: Some(0),
            }),
            Err(StoreError::RegressiveClientVersion { .. })
        ));
        assert!(matches!(
            workspace.open(OpenDocument {
                locator: DocumentLocator::file(&path).unwrap(),
                text: Arc::from("bad"),
                client_version: Some(2),
                project: None,
            }),
            Err(StoreError::AlreadyOpen(_))
        ));
        workspace.close(id).unwrap();
        assert!(matches!(
            workspace.change(ChangeDocument {
                document: id,
                text: Arc::from("bad"),
                client_version: Some(3),
            }),
            Err(StoreError::DocumentClosed(_))
        ));
    }

    #[test]
    fn save_verifies_disk_and_never_overwrites_it() {
        let directory = TestDirectory::new("save");
        let path = directory.write("main.ae", "disk");
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let id = open_file(&workspace, &path, "overlay");
        workspace
            .saved(SavedDocument {
                document: id,
                client_version: Some(2),
            })
            .unwrap();
        assert_eq!(fs::read_to_string(&path).unwrap(), "disk");
        assert!(matches!(
            workspace.document(id).unwrap().state,
            DocumentState::Open { dirty: true, .. }
        ));
        fs::write(&path, "overlay").unwrap();
        workspace
            .saved(SavedDocument {
                document: id,
                client_version: Some(3),
            })
            .unwrap();
        assert!(matches!(
            workspace.document(id).unwrap().state,
            DocumentState::Open { dirty: false, .. }
        ));
    }

    #[test]
    fn overlay_wins_for_entry_and_multiple_imports_then_close_restores_disk() {
        let directory = TestDirectory::new("imports");
        let entry = directory.write("main.ae", "int main(){return 0;}");
        let alpha = directory.write("alpha.ae", "package Alpha; public int value(){return 1;}");
        let beta = directory.write("beta.ae", "package Beta; public int value(){return 2;}");
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let entry_id = open_file(
            &workspace,
            &entry,
            "import Alpha; import Beta; int main(){return Alpha.value()+Beta.value();}",
        );
        let alpha_id = open_file(
            &workspace,
            &alpha,
            "package Renamed; public int value(){return 3;}",
        );
        let beta_id = open_file(
            &workspace,
            &beta,
            "package Beta; public int value(){return 4;}",
        );
        let errors = workspace.snapshot().discover(&entry, None).unwrap_err();
        assert!(errors[0].message.contains("Alpha"));
        workspace.close(alpha_id).unwrap();
        let result = workspace.snapshot().discover(&entry, None).unwrap();
        assert_eq!(result.stamp.document_versions.len(), 3);
        assert_eq!(
            result
                .sources
                .iter()
                .filter(|read| read.from_overlay)
                .count(),
            2
        );
        assert!(
            result
                .session
                .modules()
                .iter()
                .any(|module| module.info().display_name == "Alpha")
        );
        assert_eq!(
            workspace.may_publish(&result, Some(entry_id)),
            PublishDecision::Current
        );
        workspace.close(beta_id).unwrap();
    }

    #[test]
    fn imported_overlay_participates_through_a_transitive_import() {
        let directory = TestDirectory::new("transitive-overlay");
        let entry = directory.write("main.ae", "import Alpha; int main(){return Alpha.value();}");
        directory.write(
            "alpha.ae",
            "package Alpha; import Beta; public int value(){return Beta.value();}",
        );
        let beta = directory.write("beta.ae", "package Wrong; public int value(){return 1;}");
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let beta_id = open_file(
            &workspace,
            &beta,
            "package Beta; public int value(){return 2;}",
        );
        let result = workspace.snapshot().discover(&entry, None).unwrap();
        assert!(
            result
                .session
                .modules()
                .iter()
                .any(|module| module.info().display_name == "Beta")
        );
        assert!(result.sources.iter().any(|read| {
            read.document == Some((beta_id, DocumentVersion(1))) && read.from_overlay
        }));
    }

    #[test]
    fn overlay_topology_add_remove_alias_and_package_changes_rebuild_discovery() {
        let directory = TestDirectory::new("topology");
        let entry = directory.write("main.ae", "int main(){return 0;}");
        directory.write("alpha.ae", "package Alpha; public int value(){return 1;}");
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let id = open_file(
            &workspace,
            &entry,
            "import Alpha as a; int main(){return a.value();}",
        );
        let first = workspace.snapshot().discover(&entry, None).unwrap();
        assert_eq!(
            first.session.modules()[first.session.entry().0 as usize]
                .info()
                .imports[0]
                .alias
                .as_deref(),
            Some("a")
        );
        workspace
            .change(ChangeDocument {
                document: id,
                text: Arc::from("int main(){return 0;}"),
                client_version: Some(2),
            })
            .unwrap();
        let second = workspace.snapshot().discover(&entry, None).unwrap();
        assert!(
            !second
                .session
                .modules()
                .iter()
                .any(|module| module.info().display_name == "Alpha")
        );
        workspace
            .change(ChangeDocument {
                document: id,
                text: Arc::from("package Entry; int value(){return 0;}"),
                client_version: Some(3),
            })
            .unwrap();
        let third = workspace.snapshot().discover(&entry, None).unwrap();
        assert!(
            third
                .session
                .modules()
                .iter()
                .any(|module| module.info().display_name == "Entry")
        );
    }

    #[test]
    fn deleted_open_source_remains_in_snapshot_but_closed_source_is_missing() {
        let directory = TestDirectory::new("deleted");
        let entry = directory.write("main.ae", "int main(){return 0;}");
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let id = open_file(&workspace, &entry, "int main(){return 7;}");
        fs::remove_file(&entry).unwrap();
        workspace
            .filesystem_changed(FileChange {
                path: entry.clone(),
            })
            .unwrap();
        assert!(workspace.snapshot().discover(&entry, None).is_ok());
        workspace.close(id).unwrap();
        assert!(workspace.snapshot().discover(&entry, None).is_err());
    }

    #[test]
    fn snapshots_are_immutable_and_stale_results_are_deterministic() {
        let directory = TestDirectory::new("snapshot");
        let entry = directory.write("main.ae", "int main(){return 0;}");
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let id = open_file(&workspace, &entry, "int main(){return 1;}");
        let snapshot = workspace.snapshot();
        workspace
            .change(ChangeDocument {
                document: id,
                text: Arc::from("int main(){return 2;}"),
                client_version: Some(2),
            })
            .unwrap();
        let old = snapshot.discover(&entry, None).unwrap();
        assert!(
            old.session.modules()[old.session.entry().0 as usize]
                .source()
                .text
                .contains("return 1")
        );
        assert_eq!(
            workspace.may_publish(&old, Some(id)),
            PublishDecision::Stale
        );
    }

    #[test]
    fn external_source_changes_are_distinct_from_overlay_staleness() {
        let directory = TestDirectory::new("external");
        let entry = directory.write("main.ae", "import Alpha; int main(){return Alpha.value();}");
        let alpha = directory.write("alpha.ae", "package Alpha; public int value(){return 1;}");
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let id = open_file(
            &workspace,
            &entry,
            "import Alpha; int main(){return Alpha.value();}",
        );
        let result = workspace.snapshot().discover(&entry, None).unwrap();
        fs::write(alpha, "package Alpha; public int value(){return 2;}").unwrap();
        assert_eq!(
            workspace.may_publish(&result, Some(id)),
            PublishDecision::SourceChanged
        );
    }

    #[test]
    fn virtual_documents_and_toolchain_immutability_are_explicit() {
        let directory = TestDirectory::new("virtual");
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let id = workspace
            .open(OpenDocument {
                locator: DocumentLocator::virtual_document("untitled:test").unwrap(),
                text: Arc::from("int main(){return 0;}"),
                client_version: None,
                project: None,
            })
            .unwrap();
        assert!(matches!(
            workspace.document(id).unwrap().state,
            DocumentState::Open {
                disk_base: DiskBase::NotApplicable,
                ..
            }
        ));
        assert_eq!(
            DocumentLocator::virtual_document("aether-toolchain:std/Math"),
            Err(StoreError::ToolchainImmutable)
        );
    }

    #[cfg(unix)]
    #[test]
    fn symlink_aliases_share_document_identity() {
        use std::os::unix::fs::symlink;

        let directory = TestDirectory::new("symlink-identity");
        let real = directory.write("real.ae", "int main(){return 0;}");
        let alias = directory.0.join("alias.ae");
        symlink(&real, &alias).unwrap();
        let workspace = EditorWorkspace::new(&directory.0).unwrap();
        let id = open_file(&workspace, &alias, "int main(){return 1;}");
        workspace.close(id).unwrap();
        let reopened = workspace
            .open(OpenDocument {
                locator: DocumentLocator::file(&real).unwrap(),
                text: Arc::from("int main(){return 2;}"),
                client_version: Some(1),
                project: None,
            })
            .unwrap();
        assert_eq!(id, reopened);
    }
}
