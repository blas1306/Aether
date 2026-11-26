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
    projects: HashMap<PathBuf, (ProjectId, PathBuf)>,
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
        let project = self.project_for(&path);
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
                let diagnostics = publication
                    .contributions
                    .values()
                    .filter_map(|items| items.get(&affected_uri))
                    .flatten()
                    .cloned()
                    .collect();
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

    fn project_for(&mut self, path: &Path) -> Option<ProjectId> {
        let workspace_root = self.root.as_deref()?;
        let mut cursor = path.parent()?;
        loop {
            if cursor.join("aether.toml").is_file() {
                let canonical = cursor.canonicalize().ok()?;
                if let Some((id, entry)) = self.projects.get(&canonical) {
                    return path
                        .canonicalize()
                        .ok()
                        .filter(|candidate| candidate == entry)
                        .map(|_| *id);
                }
                match ProjectPlan::load_read_only(&canonical) {
                    Ok(plan) => {
                        let id = ProjectId(self.next_project);
                        self.next_project += 1;
                        let entry = plan.source().to_path_buf();
                        if let Some(workspace) = &self.workspace {
                            workspace.set_project(id, 1, plan);
                        }
                        self.projects.insert(canonical, (id, entry.clone()));
                        return path
                            .canonicalize()
                            .ok()
                            .filter(|candidate| candidate == &entry)
                            .map(|_| id);
                    }
                    Err(error) => {
                        eprintln!("aether-lsp: project is not read-only analyzable: {error}");
                        return None;
                    }
                }
            }
            if cursor == workspace_root {
                break;
            }
            cursor = cursor.parent()?;
        }
        None
    }

    fn schedule_all(&mut self) {
        let targets: Vec<DocumentId> = self.documents.values().map(|file| file.document).collect();
        for target in targets {
            self.schedule(target);
        }
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
            for uri in affected {
                let diagnostics = state
                    .contributions
                    .values()
                    .filter_map(|items| items.get(&uri))
                    .flatten()
                    .cloned()
                    .collect();
                let version = state
                    .files
                    .values()
                    .find_map(|(candidate, version)| (candidate == &uri).then_some(*version))
                    .flatten();
                // Validation and queue insertion share the same lock. A later edit/close must
                // therefore enqueue its newer publication after this one.
                let _ = output.send(Outbound::Message(publish(&uri, diagnostics, version)));
            }
        });
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
}
