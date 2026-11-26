//! Minimal native Aether language server for canonical diagnostics.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::fmt::Write as _;
use std::io::{self, BufRead, BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, mpsc};
use std::thread;

use aether_analysis::{
    AnalysisScheduler, AnalysisTarget, ChangeDocument, DiagnosticSeverity, DocumentId,
    DocumentLocator, EditorDiagnostic, EditorRange, EditorWorkspace, OpenDocument, ProjectId,
    ProjectPlan, RequestState, SavedDocument, SourceIdentity,
};
use serde_json::{Value, json};

enum Outbound {
    Message(Value),
    Stop,
}

#[derive(Clone)]
struct OpenFile {
    document: DocumentId,
    version: Option<i64>,
    path: PathBuf,
    role: DocumentRole,
}

#[derive(Clone)]
enum DocumentRole {
    /// A standalone source or the canonical entry of a validated project.
    AnalysisTarget(Option<PathBuf>),
    /// A project module is diagnosed through the canonical project entry target.
    ProjectMember(PathBuf),
    /// A manifest claimed this source, but its authoritative locked graph was unavailable.
    ProjectUnavailable(PathBuf, Arc<str>),
    /// The project boundary itself could not be represented safely.
    InternalFailure(Arc<str>),
}

enum ProjectContext {
    Ready {
        project: ProjectId,
        root: PathBuf,
        entry: bool,
    },
    Unavailable(PathBuf, String),
    Standalone,
    InternalFailure(String),
}

struct ProjectRecord {
    id: ProjectId,
    entry: PathBuf,
    generation: u64,
    plan: ProjectPlan,
    available: bool,
}

#[derive(Default)]
struct PublicationState {
    epochs: HashMap<DocumentId, u64>,
    files: HashMap<DocumentId, (String, Option<i64>)>,
    contributions: HashMap<DocumentId, BTreeMap<String, Vec<Value>>>,
}

struct Server {
    output: mpsc::Sender<Outbound>,
    workspace: Option<Arc<EditorWorkspace>>,
    scheduler: Option<AnalysisScheduler>,
    root: Option<PathBuf>,
    documents: HashMap<String, OpenFile>,
    projects: HashMap<PathBuf, ProjectRecord>,
    next_project: u64,
    publication: Arc<Mutex<PublicationState>>,
    initialized: bool,
    shutdown: bool,
}

impl Server {
    fn new(output: mpsc::Sender<Outbound>) -> Self {
        Self {
            output,
            workspace: None,
            scheduler: None,
            root: None,
            documents: HashMap::new(),
            projects: HashMap::new(),
            next_project: 1,
            publication: Arc::new(Mutex::new(PublicationState::default())),
            initialized: false,
            shutdown: false,
        }
    }

    fn send(&self, message: Value) {
        let _ = self.output.send(Outbound::Message(message));
    }

    #[allow(clippy::needless_pass_by_value)]
    fn response(&self, id: Value, result: Value) {
        self.send(json!({"jsonrpc": "2.0", "id": id, "result": result}));
    }

    #[allow(clippy::needless_pass_by_value)]
    fn error(&self, id: Value, code: i64, message: impl Into<String>) {
        self.send(json!({
            "jsonrpc": "2.0", "id": id,
            "error": {"code": code, "message": message.into()}
        }));
    }

    fn handle(&mut self, message: &Value) -> Option<i32> {
        let Some(object) = message.as_object() else {
            self.error(Value::Null, -32600, "Invalid Request");
            return None;
        };
        let method = object.get("method").and_then(Value::as_str);
        let id = object.get("id").cloned();
        match method {
            Some("initialize") => self.initialize(id.unwrap_or(Value::Null), object.get("params")),
            Some("initialized" | "$/cancelRequest") => {}
            Some("shutdown") => {
                self.shutdown = true;
                if let Some(mut scheduler) = self.scheduler.take() {
                    scheduler.shutdown();
                }
                self.response(id.unwrap_or(Value::Null), Value::Null);
            }
            Some("exit") => return Some(i32::from(!self.shutdown)),
            Some("textDocument/didOpen") if !self.shutdown => self.did_open(object.get("params")),
            Some("textDocument/didChange") if !self.shutdown => {
                self.did_change(object.get("params"));
            }
            Some("textDocument/didSave") if !self.shutdown => self.did_save(object.get("params")),
            Some("textDocument/didClose") if !self.shutdown => self.did_close(object.get("params")),
            Some(unknown) if id.is_some() => {
                self.error(
                    id.unwrap_or(Value::Null),
                    -32601,
                    format!("Method not found: {unknown}"),
                );
            }
            Some(_) => {}
            None => self.error(id.unwrap_or(Value::Null), -32600, "Invalid Request"),
        }
        None
    }

    fn initialize(&mut self, id: Value, params: Option<&Value>) {
        if self.initialized {
            self.error(id, -32600, "initialize may only be sent once");
            return;
        }
        let root = params
            .and_then(|value| value.get("rootUri"))
            .and_then(Value::as_str)
            .and_then(file_uri_to_path)
            .or_else(|| {
                params
                    .and_then(|value| value.get("rootPath"))
                    .and_then(Value::as_str)
                    .map(PathBuf::from)
            })
            .or_else(|| std::env::current_dir().ok());
        let Some(root) = root else {
            self.error(id, -32603, "could not determine workspace root");
            return;
        };
        match EditorWorkspace::new(&root) {
            Ok(workspace) => {
                let workspace = Arc::new(workspace);
                self.scheduler = Some(AnalysisScheduler::new(Arc::clone(&workspace)));
                self.workspace = Some(workspace);
                self.root = root.canonicalize().ok();
                self.initialized = true;
                self.response(
                    id,
                    json!({
                        "serverInfo": {"name": "aether-lsp", "version": env!("CARGO_PKG_VERSION")},
                        "capabilities": {
                            "positionEncoding": "utf-16",
                            "textDocumentSync": {
                                "openClose": true,
                                "change": 1,
                                "save": {"includeText": false}
                            }
                        }
                    }),
                );
            }
            Err(error) => self.error(id, -32603, format!("invalid workspace root: {error}")),
        }
    }

    fn did_open(&mut self, params: Option<&Value>) {
        let Some(document) = params.and_then(|value| value.get("textDocument")) else {
            return;
        };
        let (Some(uri), Some(text)) = (
            document.get("uri").and_then(Value::as_str),
            document.get("text").and_then(Value::as_str),
        ) else {
            return;
        };
        let version = document.get("version").and_then(Value::as_i64);
        let Some(path) = file_uri_to_path(uri) else {
            eprintln!("aether-lsp: virtual documents are not analyzable in diagnostics V1");
            return;
        };
        let context = self.project_for(&path);
        let (project, role) = match context {
            ProjectContext::Ready {
                project,
                root,
                entry,
            } => (
                Some(project),
                if entry {
                    DocumentRole::AnalysisTarget(Some(root))
                } else {
                    DocumentRole::ProjectMember(root)
                },
            ),
            ProjectContext::Unavailable(root, message) => (
                None,
                DocumentRole::ProjectUnavailable(root, Arc::from(message)),
            ),
            ProjectContext::Standalone => (None, DocumentRole::AnalysisTarget(None)),
            ProjectContext::InternalFailure(message) => {
                (None, DocumentRole::InternalFailure(Arc::from(message)))
            }
        };
        let Some(workspace) = &self.workspace else {
            return;
        };
        match workspace.open(OpenDocument {
            locator: match DocumentLocator::file(&path) {
                Ok(locator) => locator,
                Err(error) => {
                    eprintln!("aether-lsp: cannot open {uri}: {error}");
                    return;
                }
            },
            text: Arc::from(text),
            client_version: version,
            project,
        }) {
            Ok(document_id) => {
                self.documents.insert(
                    uri.to_owned(),
                    OpenFile {
                        document: document_id,
                        version,
                        path,
                        role,
                    },
                );
                let mut publication = self.publication.lock().expect("publication state poisoned");
                publication
                    .files
                    .insert(document_id, (uri.to_owned(), version));
                publication.epochs.entry(document_id).or_default();
                drop(publication);
                self.schedule_all();
            }
            Err(error) => eprintln!("aether-lsp: cannot open {uri}: {error}"),
        }
    }

    fn did_change(&mut self, params: Option<&Value>) {
        let Some(params) = params else { return };
        let Some(document) = params.get("textDocument") else {
            return;
        };
        let Some(uri) = document.get("uri").and_then(Value::as_str) else {
            return;
        };
        let version = document.get("version").and_then(Value::as_i64);
        let Some(changes) = params.get("contentChanges").and_then(Value::as_array) else {
            return;
        };
        if changes.len() != 1 || changes[0].get("range").is_some() {
            eprintln!("aether-lsp: rejected incremental didChange while full sync is advertised");
            return;
        }
        let Some(text) = changes[0].get("text").and_then(Value::as_str) else {
            return;
        };
        let Some(open) = self.documents.get(uri).cloned() else {
            return;
        };
        let Some(workspace) = &self.workspace else {
            return;
        };
        match workspace.change(ChangeDocument {
            document: open.document,
            text: Arc::from(text),
            client_version: version,
        }) {
            Ok(_) => {
                if let Some(current) = self.documents.get_mut(uri) {
                    current.version = version.or(current.version);
                }
                if let Some(file) = self
                    .publication
                    .lock()
                    .expect("publication state poisoned")
                    .files
                    .get_mut(&open.document)
                {
                    file.1 = version.or(file.1);
                }
                self.schedule_all();
            }
            Err(error) => eprintln!("aether-lsp: rejected change for {uri}: {error}"),
        }
    }

    fn did_save(&mut self, params: Option<&Value>) {
        let Some(uri) = params
            .and_then(|value| value.get("textDocument"))
            .and_then(|value| value.get("uri"))
            .and_then(Value::as_str)
        else {
            return;
        };
        let Some(open) = self.documents.get(uri) else {
            return;
        };
        let Some(workspace) = &self.workspace else {
            return;
        };
        match workspace.saved(SavedDocument {
            document: open.document,
            client_version: open.version,
        }) {
            Ok(_) => self.schedule_all(),
            Err(error) => eprintln!("aether-lsp: save observation failed for {uri}: {error}"),
        }
    }

    fn did_close(&mut self, params: Option<&Value>) {
        let Some(uri) = params
            .and_then(|value| value.get("textDocument"))
            .and_then(|value| value.get("uri"))
            .and_then(Value::as_str)
        else {
            return;
        };
        let Some(open) = self.documents.remove(uri) else {
            return;
        };
        if let Some(workspace) = &self.workspace {
            if let Err(error) = workspace.close(open.document) {
                eprintln!("aether-lsp: close failed for {uri}: {error}");
            }
        }
        let mut publication = self.publication.lock().expect("publication state poisoned");
        *publication.epochs.entry(open.document).or_default() += 1;
        publication.files.remove(&open.document);
        let mut affected: BTreeSet<String> = publication
            .contributions
            .remove(&open.document)
            .unwrap_or_default()
            .into_keys()
            .collect();
        affected.insert(uri.to_owned());
        for values in publication.contributions.values_mut() {
            values.remove(uri);
        }
        for affected_uri in affected {
            let (diagnostics, version) = if affected_uri == uri {
                (Vec::new(), open.version)
            } else {
                let diagnostics = merged_diagnostics(&publication, &affected_uri);
                let version = publication
                    .files
                    .values()
                    .find_map(|(candidate, version)| {
                        (candidate == &affected_uri).then_some(*version)
                    })
                    .flatten();
                (diagnostics, version)
            };
            let _ = self.output.send(Outbound::Message(publish(
                &affected_uri,
                diagnostics,
                version,
            )));
        }
        drop(publication);
        self.schedule_all();
    }

    fn project_for(&mut self, path: &Path) -> ProjectContext {
        let Some(workspace_root) = self.root.as_deref() else {
            return ProjectContext::InternalFailure("workspace root is unavailable".into());
        };
        let Some(mut cursor) = path.parent() else {
            return ProjectContext::InternalFailure("document has no parent directory".into());
        };
        loop {
            if cursor.join("aether.toml").is_file() {
                let canonical = match cursor.canonicalize() {
                    Ok(path) => path,
                    Err(error) => {
                        return ProjectContext::InternalFailure(format!(
                            "could not canonicalize project root: {error}"
                        ));
                    }
                };
                if let Some(record) = self.projects.get(&canonical) {
                    return ProjectContext::Ready {
                        project: record.id,
                        root: canonical,
                        entry: same_file_or_lexical(path, &record.entry),
                    };
                }
                match ProjectPlan::load_read_only(&canonical) {
                    Ok(plan) => {
                        let id = ProjectId(self.next_project);
                        self.next_project += 1;
                        let entry = plan.source().to_path_buf();
                        if let Some(workspace) = &self.workspace {
                            workspace.set_project(id, 1, plan.clone());
                        }
                        self.projects.insert(
                            canonical.clone(),
                            ProjectRecord {
                                id,
                                entry: entry.clone(),
                                generation: 1,
                                plan,
                                available: true,
                            },
                        );
                        return ProjectContext::Ready {
                            project: id,
                            root: canonical,
                            entry: same_file_or_lexical(path, &entry),
                        };
                    }
                    Err(error) => {
                        eprintln!("aether-lsp: project is not read-only analyzable: {error}");
                        return ProjectContext::Unavailable(canonical, error);
                    }
                }
            }
            if cursor == workspace_root {
                break;
            }
            let Some(parent) = cursor.parent() else {
                break;
            };
            cursor = parent;
        }
        ProjectContext::Standalone
    }

    fn schedule_all(&mut self) {
        self.refresh_projects();
        let targets: Vec<(DocumentId, DocumentRole)> = self
            .documents
            .values()
            .map(|file| (file.document, file.role.clone()))
            .collect();
        for (target, role) in targets {
            match role {
                DocumentRole::AnalysisTarget(_) => self.schedule(target),
                DocumentRole::ProjectMember(_) => self.publish_empty_contribution(target),
                DocumentRole::ProjectUnavailable(_, message) => self.publish_context_diagnostic(
                    target,
                    "aether.project-unavailable",
                    &format!("Aether project is unavailable: {message}"),
                ),
                DocumentRole::InternalFailure(message) => self.publish_context_diagnostic(
                    target,
                    "aether.project-internal-failure",
                    &format!("Aether project context failed internally: {message}"),
                ),
            }
        }
    }

    fn refresh_projects(&mut self) {
        let roots: BTreeSet<PathBuf> = self
            .documents
            .values()
            .filter_map(|file| role_project_root(&file.role).cloned())
            .collect();
        for root in roots {
            match ProjectPlan::load_read_only(&root) {
                Ok(plan) => {
                    let entry = plan.source().to_path_buf();
                    let (id, generation, changed) =
                        if let Some(record) = self.projects.get_mut(&root) {
                            let changed = !record.available || record.plan != plan;
                            if changed {
                                record.generation += 1;
                                record.entry.clone_from(&entry);
                                record.plan = plan.clone();
                                record.available = true;
                            }
                            (record.id, record.generation, changed)
                        } else {
                            let id = ProjectId(self.next_project);
                            self.next_project += 1;
                            self.projects.insert(
                                root.clone(),
                                ProjectRecord {
                                    id,
                                    entry: entry.clone(),
                                    generation: 1,
                                    plan: plan.clone(),
                                    available: true,
                                },
                            );
                            (id, 1, true)
                        };
                    if changed {
                        if let Some(workspace) = &self.workspace {
                            workspace.set_project(id, generation, plan);
                        }
                    }
                    for file in self.documents.values_mut().filter(|file| {
                        role_project_root(&file.role).is_some_and(|candidate| candidate == &root)
                    }) {
                        file.role = if same_file_or_lexical(&file.path, &entry) {
                            DocumentRole::AnalysisTarget(Some(root.clone()))
                        } else {
                            DocumentRole::ProjectMember(root.clone())
                        };
                        if let Some(workspace) = &self.workspace {
                            let _ = workspace.set_document_project(file.document, Some(id));
                        }
                    }
                }
                Err(error) => {
                    if let Some(record) = self.projects.get_mut(&root) {
                        if record.available {
                            record.available = false;
                            record.generation += 1;
                            if let Some(workspace) = &self.workspace {
                                workspace.set_project_generation(record.id, record.generation);
                            }
                        }
                    }
                    let message: Arc<str> = Arc::from(error);
                    for file in self.documents.values_mut().filter(|file| {
                        role_project_root(&file.role).is_some_and(|candidate| candidate == &root)
                    }) {
                        file.role = DocumentRole::ProjectUnavailable(root.clone(), message.clone());
                        if let Some(workspace) = &self.workspace {
                            let _ = workspace.set_document_project(file.document, None);
                        }
                    }
                }
            }
        }
    }

    fn publish_context_diagnostic(&self, target: DocumentId, code: &str, message: &str) {
        let mut state = self.publication.lock().expect("publication state poisoned");
        let Some((uri, _)) = state.files.get(&target).cloned() else {
            return;
        };
        *state.epochs.entry(target).or_default() += 1;
        let diagnostic = json!({
            "range": default_range(),
            "severity": 1,
            "code": code,
            "source": "aether-project",
            "message": message,
        });
        let previous: BTreeSet<String> = state
            .contributions
            .insert(target, BTreeMap::from([(uri.clone(), vec![diagnostic])]))
            .unwrap_or_default()
            .into_keys()
            .collect();
        let affected: BTreeSet<String> = previous.into_iter().chain([uri]).collect();
        enqueue_publications(&state, &self.output, affected);
    }

    fn publish_empty_contribution(&self, target: DocumentId) {
        let mut state = self.publication.lock().expect("publication state poisoned");
        let Some((uri, _)) = state.files.get(&target).cloned() else {
            return;
        };
        *state.epochs.entry(target).or_default() += 1;
        let previous: BTreeSet<String> = state
            .contributions
            .insert(target, BTreeMap::from([(uri.clone(), Vec::new())]))
            .unwrap_or_default()
            .into_keys()
            .collect();
        let affected: BTreeSet<String> = previous.into_iter().chain([uri]).collect();
        enqueue_publications(&state, &self.output, affected);
    }

    fn schedule(&mut self, target: DocumentId) {
        let Some(scheduler) = &self.scheduler else {
            return;
        };
        let handle = match scheduler.request(AnalysisTarget::Document(target)) {
            Ok(handle) => handle,
            Err(error) => {
                eprintln!("aether-lsp: cannot schedule analysis: {error}");
                return;
            }
        };
        let epoch = {
            let mut state = self.publication.lock().expect("publication state poisoned");
            let epoch = state.epochs.entry(target).or_default();
            *epoch += 1;
            *epoch
        };
        let publication = Arc::clone(&self.publication);
        let output = self.output.clone();
        thread::spawn(move || {
            let Ok(completion) = handle.wait() else {
                return;
            };
            if completion.state != RequestState::Published {
                return;
            }
            let Some(result) = completion.result else {
                return;
            };
            let mut state = publication.lock().expect("publication state poisoned");
            if state.epochs.get(&target).copied() != Some(epoch)
                || !state.files.contains_key(&target)
            {
                return;
            }
            let mut next: BTreeMap<String, Vec<Value>> = BTreeMap::new();
            if let Some((uri, _)) = state.files.get(&target) {
                next.insert(uri.clone(), Vec::new());
            }
            for diagnostic in &result.diagnostics {
                let Some(uri) = diagnostic_uri(diagnostic, &state.files) else {
                    continue;
                };
                next.entry(uri)
                    .or_default()
                    .push(lsp_diagnostic(diagnostic, &state.files));
            }
            let previous: BTreeSet<String> = state
                .contributions
                .insert(target, next.clone())
                .unwrap_or_default()
                .into_keys()
                .collect();
            let affected: BTreeSet<String> = previous.into_iter().chain(next.into_keys()).collect();
            // Validation and queue insertion share the same lock. A later edit/close must
            // therefore enqueue its newer publication after this one.
            enqueue_publications(&state, &output, affected);
        });
    }
}

fn same_file_or_lexical(path: &Path, expected: &Path) -> bool {
    path.canonicalize()
        .map_or_else(|_| path == expected, |candidate| candidate == expected)
}

fn role_project_root(role: &DocumentRole) -> Option<&PathBuf> {
    match role {
        DocumentRole::AnalysisTarget(Some(root))
        | DocumentRole::ProjectMember(root)
        | DocumentRole::ProjectUnavailable(root, _) => Some(root),
        DocumentRole::AnalysisTarget(None) | DocumentRole::InternalFailure(_) => None,
    }
}

fn merged_diagnostics(state: &PublicationState, uri: &str) -> Vec<Value> {
    let mut unique = BTreeMap::new();
    for diagnostic in state
        .contributions
        .values()
        .filter_map(|items| items.get(uri))
        .flatten()
    {
        // The complete protocol value is the publication-local semantic identity. This includes
        // range, severity, code, source, message and related locations, rather than collapsing
        // distinct diagnostics merely because their code and range happen to match.
        let identity = serde_json::to_string(diagnostic).expect("diagnostic JSON is serializable");
        unique.entry(identity).or_insert_with(|| diagnostic.clone());
    }
    unique.into_values().collect()
}

fn enqueue_publications(
    state: &PublicationState,
    output: &mpsc::Sender<Outbound>,
    affected: BTreeSet<String>,
) {
    for uri in affected {
        let diagnostics = merged_diagnostics(state, &uri);
        let version = state
            .files
            .values()
            .find_map(|(candidate, version)| (candidate == &uri).then_some(*version))
            .flatten();
        let _ = output.send(Outbound::Message(publish(&uri, diagnostics, version)));
    }
}

fn diagnostic_uri(
    diagnostic: &EditorDiagnostic,
    files: &HashMap<DocumentId, (String, Option<i64>)>,
) -> Option<String> {
    match diagnostic.source.as_ref()? {
        SourceIdentity::Document(document) => files.get(document).map(|item| item.0.clone()),
        SourceIdentity::Disk(path) => Some(path_to_file_uri(path)),
        SourceIdentity::Toolchain(_) => None,
    }
}

fn lsp_diagnostic(
    diagnostic: &EditorDiagnostic,
    files: &HashMap<DocumentId, (String, Option<i64>)>,
) -> Value {
    let related: Vec<Value> = diagnostic.related.iter().filter_map(|item| {
        let uri = match &item.source {
            SourceIdentity::Document(document) => files.get(document).map(|value| value.0.clone()),
            SourceIdentity::Disk(path) => Some(path_to_file_uri(path)),
            SourceIdentity::Toolchain(_) => None,
        }?;
        Some(json!({"location": {"uri": uri, "range": lsp_range(item.range)}, "message": item.message.as_ref()}))
    }).collect();
    let mut value = json!({
        "range": diagnostic.range.map_or_else(default_range, lsp_range),
        "severity": match diagnostic.severity {
            DiagnosticSeverity::Error => 1,
            DiagnosticSeverity::Warning => 2,
            DiagnosticSeverity::Information => 3,
            DiagnosticSeverity::Hint => 4,
        },
        "code": diagnostic.code.as_ref(),
        "source": "aether",
        "message": diagnostic.message.as_ref(),
    });
    if !related.is_empty() {
        value["relatedInformation"] = Value::Array(related);
    }
    value
}

fn lsp_range(range: EditorRange) -> Value {
    json!({
        "start": {"line": range.start.line, "character": range.start.character},
        "end": {"line": range.end.line, "character": range.end.character}
    })
}

fn default_range() -> Value {
    json!({"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}})
}

#[allow(clippy::needless_pass_by_value)]
fn publish(uri: &str, diagnostics: Vec<Value>, version: Option<i64>) -> Value {
    let mut params = json!({"uri": uri, "diagnostics": diagnostics});
    if let Some(version) = version {
        params["version"] = json!(version);
    }
    json!({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": params})
}

#[allow(clippy::needless_pass_by_value)]
fn writer_loop<W: Write>(writer: W, receiver: mpsc::Receiver<Outbound>) {
    let mut writer = BufWriter::new(writer);
    while let Ok(outbound) = receiver.recv() {
        match outbound {
            Outbound::Message(message) => {
                let Ok(payload) = serde_json::to_vec(&message) else {
                    continue;
                };
                if write!(writer, "Content-Length: {}\r\n\r\n", payload.len()).is_err()
                    || writer.write_all(&payload).is_err()
                    || writer.flush().is_err()
                {
                    break;
                }
            }
            Outbound::Stop => break,
        }
    }
}

fn read_message<R: BufRead>(reader: &mut R) -> io::Result<Option<Result<Value, String>>> {
    let mut content_length = None;
    let mut malformed = false;
    loop {
        let mut line = String::new();
        let count = reader.read_line(&mut line)?;
        if count == 0 {
            return Ok(None);
        }
        if line == "\r\n" || line == "\n" {
            break;
        }
        let Some((name, value)) = line.trim_end().split_once(':') else {
            malformed = true;
            continue;
        };
        if name.eq_ignore_ascii_case("Content-Length") {
            content_length = value.trim().parse::<usize>().ok();
        }
    }
    let Some(length) = content_length else {
        return Ok(Some(Err("missing Content-Length".into())));
    };
    let mut payload = vec![0; length];
    reader.read_exact(&mut payload)?;
    if malformed {
        return Ok(Some(Err("malformed header".into())));
    }
    Ok(Some(
        serde_json::from_slice(&payload).map_err(|error| error.to_string()),
    ))
}

fn run<R: Read, W: Write + Send + 'static>(reader: R, writer: W) -> i32 {
    let (sender, receiver) = mpsc::channel();
    let writer = thread::spawn(move || writer_loop(writer, receiver));
    let mut server = Server::new(sender.clone());
    let mut reader = BufReader::new(reader);
    let code = loop {
        match read_message(&mut reader) {
            Ok(Some(Ok(message))) => {
                if let Some(code) = server.handle(&message) {
                    break code;
                }
            }
            Ok(Some(Err(error))) => {
                server.error(Value::Null, -32700, format!("Parse error: {error}"));
            }
            Ok(None) => break 0,
            Err(error) => {
                eprintln!("aether-lsp: input error: {error}");
                break 1;
            }
        }
    };
    if let Some(mut scheduler) = server.scheduler.take() {
        scheduler.shutdown();
    }
    let _ = sender.send(Outbound::Stop);
    drop(server);
    drop(sender);
    let _ = writer.join();
    code
}

/// Runs the server over process standard input/output.
#[must_use]
pub fn serve_stdio() -> i32 {
    run(io::stdin(), io::stdout())
}

fn file_uri_to_path(uri: &str) -> Option<PathBuf> {
    let encoded = uri.strip_prefix("file://")?;
    let bytes = encoded.as_bytes();
    let mut decoded = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' && index + 2 < bytes.len() {
            let hex = std::str::from_utf8(&bytes[index + 1..index + 3]).ok()?;
            decoded.push(u8::from_str_radix(hex, 16).ok()?);
            index += 3;
        } else {
            decoded.push(bytes[index]);
            index += 1;
        }
    }
    String::from_utf8(decoded).ok().map(PathBuf::from)
}

fn path_to_file_uri(path: &Path) -> String {
    let mut result = String::from("file://");
    for byte in path.to_string_lossy().bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'/' | b'-' | b'_' | b'.' | b'~') {
            result.push(char::from(byte));
        } else {
            let _ = write!(&mut result, "%{byte:02X}");
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    struct FailingWriter;

    impl Write for FailingWriter {
        fn write(&mut self, _buffer: &[u8]) -> io::Result<usize> {
            Err(io::Error::new(io::ErrorKind::BrokenPipe, "disconnected"))
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    #[test]
    fn uri_round_trip_handles_unicode_and_spaces() {
        let path = Path::new("/tmp/á ether/main.ae");
        assert_eq!(
            file_uri_to_path(&path_to_file_uri(path)).as_deref(),
            Some(path)
        );
    }

    #[test]
    fn framing_reads_consecutive_messages() {
        let first = br#"{"jsonrpc":"2.0","method":"initialized"}"#;
        let second = br#"{"jsonrpc":"2.0","method":"exit"}"#;
        let input = format!(
            "Content-Length: {}\r\n\r\n{}Content-Length: {}\r\n\r\n{}",
            first.len(),
            String::from_utf8_lossy(first),
            second.len(),
            String::from_utf8_lossy(second)
        );
        let mut reader = BufReader::new(input.as_bytes());
        assert!(read_message(&mut reader).unwrap().unwrap().is_ok());
        assert!(read_message(&mut reader).unwrap().unwrap().is_ok());
    }

    #[test]
    fn diagnostic_union_deduplicates_exact_values_but_preserves_distinct_messages() {
        let common = json!({"range": default_range(), "code": "E1", "message": "first"});
        let distinct = json!({"range": default_range(), "code": "E1", "message": "second"});
        let state = PublicationState {
            contributions: HashMap::from([
                (
                    DocumentId(1),
                    BTreeMap::from([("file:///x.ae".into(), vec![common.clone()])]),
                ),
                (
                    DocumentId(2),
                    BTreeMap::from([("file:///x.ae".into(), vec![common, distinct])]),
                ),
            ]),
            ..PublicationState::default()
        };
        let merged = merged_diagnostics(&state, "file:///x.ae");
        assert_eq!(merged.len(), 2);
        assert_ne!(merged[0]["message"], merged[1]["message"]);
    }

    #[test]
    fn writer_disconnect_terminates_without_panicking() {
        let (sender, receiver) = mpsc::channel();
        sender
            .send(Outbound::Message(json!({"jsonrpc": "2.0"})))
            .unwrap();
        drop(sender);
        writer_loop(FailingWriter, receiver);
    }
}
