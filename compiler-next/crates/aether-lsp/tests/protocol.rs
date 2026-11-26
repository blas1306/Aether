//! End-to-end protocol tests against the real `aether-lsp` executable.

use std::fmt::Write as _;
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::{Value, json};

static NEXT_DIRECTORY: AtomicU64 = AtomicU64::new(1);

struct TestDirectory(PathBuf);

impl TestDirectory {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "aether-lsp-protocol-{}-{}",
            std::process::id(),
            NEXT_DIRECTORY.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn write(&self, relative: &str, contents: &str) -> PathBuf {
        let path = self.0.join(relative);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(&path, contents).unwrap();
        path
    }
}

impl Drop for TestDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

struct Client {
    child: Child,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
}

impl Client {
    fn start() -> Self {
        let mut child = Command::new(env!("CARGO_BIN_EXE_aether-lsp"))
            .arg("--stdio")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let input = child.stdin.take().unwrap();
        let output = BufReader::new(child.stdout.take().unwrap());
        Self {
            child,
            input,
            output,
        }
    }

    fn send(&mut self, value: &Value) {
        let payload = serde_json::to_vec(value).unwrap();
        write!(self.input, "Content-Length: {}\r\n\r\n", payload.len()).unwrap();
        self.input.write_all(&payload).unwrap();
        self.input.flush().unwrap();
    }

    fn send_raw(&mut self, payload: &[u8]) {
        write!(self.input, "Content-Length: {}\r\n\r\n", payload.len()).unwrap();
        self.input.write_all(payload).unwrap();
        self.input.flush().unwrap();
    }

    fn receive(&mut self) -> Value {
        let mut length = None;
        loop {
            let mut line = String::new();
            assert_ne!(self.output.read_line(&mut line).unwrap(), 0);
            if line == "\r\n" {
                break;
            }
            if let Some((name, value)) = line.trim_end().split_once(':') {
                if name.eq_ignore_ascii_case("Content-Length") {
                    length = Some(value.trim().parse::<usize>().unwrap());
                }
            }
        }
        let mut payload = vec![0; length.unwrap()];
        self.output.read_exact(&mut payload).unwrap();
        serde_json::from_slice(&payload).unwrap()
    }

    fn initialize(&mut self, root: &Path) {
        self.send(&json!({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"rootUri": file_uri(root), "capabilities": {}}
        }));
        let response = self.receive();
        assert_eq!(response["id"], 1);
        assert_eq!(
            response["result"]["capabilities"]["textDocumentSync"]["change"],
            1
        );
        assert_eq!(
            response["result"]["capabilities"]["documentSymbolProvider"],
            true
        );
        assert!(
            response["result"]["capabilities"]
                .get("hoverProvider")
                .is_none()
        );
        self.send(&json!({"jsonrpc": "2.0", "method": "initialized", "params": {}}));
    }

    fn diagnostics_for(&mut self, uri: &str, version: i64) -> Value {
        for _ in 0..20 {
            let message = self.receive();
            if message["method"] == "textDocument/publishDiagnostics"
                && message["params"]["uri"] == uri
                && message["params"]["version"] == version
            {
                return message;
            }
        }
        panic!("no matching diagnostics publication");
    }

    fn diagnostics_for_uri(&mut self, uri: &str) -> Value {
        for _ in 0..20 {
            let message = self.receive();
            if message["method"] == "textDocument/publishDiagnostics"
                && message["params"]["uri"] == uri
            {
                return message;
            }
        }
        panic!("no matching diagnostics publication");
    }

    fn document_symbols(&mut self, id: i64, uri: &str) -> Value {
        self.send(&json!({
            "jsonrpc": "2.0", "id": id, "method": "textDocument/documentSymbol",
            "params": {"textDocument": {"uri": uri}}
        }));
        for _ in 0..30 {
            let message = self.receive();
            if message["id"] == id {
                return message;
            }
        }
        panic!("no matching documentSymbol response");
    }

    fn shutdown(mut self) {
        self.send(&json!({"jsonrpc": "2.0", "id": 99, "method": "shutdown"}));
        loop {
            if self.receive()["id"] == 99 {
                break;
            }
        }
        self.send(&json!({"jsonrpc": "2.0", "method": "exit"}));
        drop(self.input);
        assert!(self.child.wait().unwrap().success());
    }
}

#[test]
fn document_symbols_are_hierarchical_exact_and_follow_overlays_and_disk() {
    let directory = TestDirectory::new();
    let source = directory.write(
        "main.ae",
        "// 😀\r\nstruct Box{int value;}\r\nenum Choice{One,Two}\r\nint main(){return 0;}",
    );
    let uri = file_uri(&source);
    let mut client = Client::start();
    client.initialize(&directory.0);
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": uri, "languageId": "aether", "version": 1,
            "text": "// 😀\r\nstruct Box{int value;}\r\nenum Choice{One,Two}\r\nint main(){return 0;}"
        }}
    }));

    let response = client.document_symbols(40, &uri);
    let symbols = response["result"].as_array().unwrap();
    assert_eq!(
        symbols
            .iter()
            .map(|symbol| {
                (
                    symbol["name"].as_str().unwrap(),
                    symbol["kind"].as_u64().unwrap(),
                )
            })
            .collect::<Vec<_>>(),
        [("Box", 23), ("Choice", 10), ("main", 12)]
    );
    assert_eq!(
        symbols[0]["selectionRange"],
        json!({"start":{"line":1,"character":7},"end":{"line":1,"character":10}})
    );
    assert_eq!(
        symbols[0]["range"],
        json!({"start":{"line":1,"character":0},"end":{"line":1,"character":22}})
    );
    assert_eq!(symbols[0]["children"][0]["name"], "value");
    assert_eq!(symbols[0]["children"][0]["kind"], 8);
    assert_eq!(symbols[1]["children"][0]["kind"], 22);
    assert_eq!(symbols[1]["children"][1]["name"], "Two");

    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": "\n\nint helper(){return 1;}\nint main(){return helper();}"}]
        }
    }));
    let changed = client.document_symbols(41, &uri);
    assert_eq!(changed["result"][0]["name"], "helper");
    assert_eq!(changed["result"][0]["selectionRange"]["start"]["line"], 2);
    assert_eq!(changed["result"][1]["name"], "main");

    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 3},
            "contentChanges": [{"text": "int broken( { return 0; }"}]
        }
    }));
    let invalid = client.document_symbols(42, &uri);
    assert_eq!(invalid["error"]["code"], -32803);

    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didClose",
        "params": {"textDocument": {"uri": uri}}
    }));
    let closed = client.document_symbols(43, &uri);
    assert_eq!(closed["result"][0]["name"], "Box");
    assert_eq!(closed["result"][2]["name"], "main");
    client.shutdown();
}

#[test]
fn document_symbols_recover_after_invalid_blank_line_enum_and_rapid_edits() {
    let directory = TestDirectory::new();
    let initial = "struct NewtonResultado{double raiz;double res;int iter;}\nint main(){return 0;}";
    let source = directory.write("main.ae", initial);
    let uri = file_uri(&source);
    let mut client = Client::start();
    client.initialize(&directory.0);
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": uri, "languageId": "aether", "version": 1, "text": initial
        }}
    }));

    let opened = client.document_symbols(44, &uri);
    assert_eq!(opened["result"][0]["name"], "NewtonResultado");
    assert_eq!(opened["result"][0]["children"].as_array().unwrap().len(), 3);
    assert_eq!(opened["result"][1]["name"], "main");

    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": "struct NewtonResultado{"}]
        }
    }));
    let invalid = client.document_symbols(45, &uri);
    assert_eq!(invalid["error"]["code"], -32803);

    let blank_lines =
        "\n\nstruct NewtonResultado{double raiz;double res;int iter;}\n\nint main(){return 0;}\n";
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 3},
            "contentChanges": [{"text": blank_lines}]
        }
    }));
    let after_blank_lines = client.document_symbols(46, &uri);
    assert_eq!(after_blank_lines["result"][0]["name"], "NewtonResultado");
    assert_eq!(after_blank_lines["result"][1]["name"], "main");

    let with_enum = "\n\nstruct NewtonResultado{double raiz;double res;int iter;}\n\nenum Color{Rojo,Verde,Azul}\n\nint main(){return 0;}\n";
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 4},
            "contentChanges": [{"text": with_enum}]
        }
    }));
    let after_enum = client.document_symbols(47, &uri);
    assert_eq!(after_enum["result"][1]["name"], "Color");
    assert_eq!(
        after_enum["result"][1]["children"]
            .as_array()
            .unwrap()
            .len(),
        3
    );
    assert_eq!(after_enum["result"][2]["name"], "main");

    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 5},
            "contentChanges": [{"text": "int broken("}]
        }
    }));
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 6},
            "contentChanges": [{"text": "int helper(){return 1;}\nint main(){return helper();}"}]
        }
    }));
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 7},
            "contentChanges": [{"text": with_enum}]
        }
    }));
    let after_rapid_edits = client.document_symbols(48, &uri);
    assert_eq!(after_rapid_edits["result"][0]["name"], "NewtonResultado");
    assert_eq!(after_rapid_edits["result"][1]["name"], "Color");
    assert_eq!(after_rapid_edits["result"][2]["name"], "main");
    client.shutdown();
}

#[test]
fn document_symbols_map_classes_interfaces_and_explicit_members_only() {
    let directory = TestDirectory::new();
    let text = "interface I{int f();}open class A:I{Buffer<int> value;public init(Buffer<int> value){this.value=value;}public open int f(){return 1;}}class B:A{Buffer<int> value2;public init(Buffer<int> value,Buffer<int> value2):base(value){this.value2=value2;}public override int f(){return 7;}}int main(){B b=B(Buffer<int>(2,1),Buffer<int>(2,2));I i=b;return i.f();}";
    let source = directory.write("main.ae", text);
    let uri = file_uri(&source);
    let mut client = Client::start();
    client.initialize(&directory.0);
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": uri, "languageId": "aether", "version": 1, "text": text
        }}
    }));
    let response = client.document_symbols(60, &uri);
    let symbols = response["result"].as_array().unwrap();
    assert_eq!(symbols[0]["name"], "I");
    assert_eq!(symbols[0]["kind"], 11);
    assert_eq!(symbols[0]["children"][0]["name"], "f");
    assert_eq!(symbols[0]["children"][0]["kind"], 6);
    assert_eq!(symbols[1]["name"], "A");
    assert_eq!(symbols[1]["kind"], 5);
    assert_eq!(
        symbols[1]["children"]
            .as_array()
            .unwrap()
            .iter()
            .map(|symbol| (
                symbol["name"].as_str().unwrap(),
                symbol["kind"].as_u64().unwrap()
            ))
            .collect::<Vec<_>>(),
        [("value", 8), ("init", 9), ("f", 6)]
    );
    assert_eq!(symbols[2]["children"][2]["name"], "f");
    assert!(
        symbols
            .iter()
            .all(|symbol| !symbol["name"].as_str().unwrap().starts_with('$'))
    );
    client.shutdown();
}

#[test]
fn document_symbol_requests_are_cancellable_and_stale_results_are_errors() {
    let directory = TestDirectory::new();
    let mut large = String::new();
    for index in 0..4_000 {
        writeln!(large, "int f{index}(){{return {index};}}").unwrap();
    }
    large.push_str("int main(){return 0;}");
    let source = directory.write("main.ae", &large);
    let uri = file_uri(&source);
    let mut client = Client::start();
    client.initialize(&directory.0);
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": uri, "languageId": "aether", "version": 1, "text": large
        }}
    }));
    client.send(&json!({
        "jsonrpc": "2.0", "id": 70, "method": "textDocument/documentSymbol",
        "params": {"textDocument": {"uri": uri}}
    }));
    client.send(&json!({
        "jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 70}
    }));
    loop {
        let message = client.receive();
        if message["id"] == 70 {
            assert_eq!(message["error"]["code"], -32800);
            break;
        }
    }

    client.send(&json!({
        "jsonrpc": "2.0", "id": 71, "method": "textDocument/documentSymbol",
        "params": {"textDocument": {"uri": uri}}
    }));
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": "int main(){return 0;}"}]
        }
    }));
    loop {
        let message = client.receive();
        if message["id"] == 71 {
            assert_eq!(message["error"]["code"], -32801);
            break;
        }
    }
    let current = client.document_symbols(72, &uri);
    assert_eq!(current["result"].as_array().unwrap().len(), 1);
    assert_eq!(current["result"][0]["name"], "main");

    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 3},
            "contentChanges": [{"text": large}]
        }
    }));
    client.send(&json!({
        "jsonrpc": "2.0", "id": 73, "method": "textDocument/documentSymbol",
        "params": {"textDocument": {"uri": uri}}
    }));
    client.send(&json!({"jsonrpc": "2.0", "id": 99, "method": "shutdown"}));
    let mut cancelled = false;
    let mut shutdown = false;
    while !cancelled || !shutdown {
        let message = client.receive();
        if message["id"] == 73 {
            assert_eq!(message["error"]["code"], -32800);
            cancelled = true;
        } else if message["id"] == 99 {
            assert!(message["result"].is_null());
            shutdown = true;
        }
    }
    client.send(&json!({"jsonrpc": "2.0", "method": "exit"}));
    drop(client.input);
    assert!(client.child.wait().unwrap().success());
}

#[test]
fn cancelling_an_older_document_symbol_request_does_not_cancel_its_successor() {
    let directory = TestDirectory::new();
    let mut large = String::new();
    for index in 0..4_000 {
        writeln!(large, "int f{index}(){{return {index};}}").unwrap();
    }
    large.push_str("int main(){return 0;}");
    let source = directory.write("main.ae", &large);
    let uri = file_uri(&source);
    let mut client = Client::start();
    client.initialize(&directory.0);
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": uri, "languageId": "aether", "version": 1, "text": large
        }}
    }));
    client.send(&json!({
        "jsonrpc": "2.0", "id": 80, "method": "textDocument/documentSymbol",
        "params": {"textDocument": {"uri": uri}}
    }));
    client.send(&json!({
        "jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 80}
    }));
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": "enum Color{Rojo,Verde,Azul}\nint main(){return 0;}"}]
        }
    }));
    client.send(&json!({
        "jsonrpc": "2.0", "id": 81, "method": "textDocument/documentSymbol",
        "params": {"textDocument": {"uri": uri}}
    }));

    let mut cancelled = false;
    let mut succeeded = false;
    while !cancelled || !succeeded {
        let message = client.receive();
        if message["id"] == 80 {
            assert_eq!(message["error"]["code"], -32800);
            cancelled = true;
        } else if message["id"] == 81 {
            let symbols = message["result"]
                .as_array()
                .unwrap_or_else(|| panic!("successor response was not successful: {message}"));
            assert_eq!(symbols.len(), 2);
            assert_eq!(message["result"][0]["name"], "Color");
            assert_eq!(message["result"][1]["name"], "main");
            succeeded = true;
        }
    }
    client.shutdown();
}

fn file_uri(path: &Path) -> String {
    format!("file://{}", path.display()).replace(' ', "%20")
}

#[test]
#[allow(clippy::too_many_lines)]
fn real_stdio_server_handles_lifecycle_overlays_utf16_and_recovery() {
    let directory = TestDirectory::new();
    let source = directory.0.join("main.ae");
    fs::write(&source, "int main(){return 0;}").unwrap();
    let uri = file_uri(&source);
    let mut client = Client::start();
    client.initialize(&directory.0);

    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": uri, "languageId": "aether", "version": 1,
            "text": "int main(){return 0;}"
        }}
    }));
    assert_eq!(
        client.diagnostics_for(&uri, 1)["params"]["diagnostics"],
        json!([])
    );

    let invalid = "int main(){println(\"😀\"); @ return 0;}";
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": invalid}]
        }
    }));
    let diagnostics = client.diagnostics_for(&uri, 2);
    let items = diagnostics["params"]["diagnostics"].as_array().unwrap();
    assert!(!items.is_empty());
    let byte = invalid.find('@').unwrap();
    let expected_utf16 = invalid[..byte].encode_utf16().count() as u64;
    assert_eq!(
        items[0]["range"]["start"]["character"].as_u64(),
        Some(expected_utf16)
    );

    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 3},
            "contentChanges": [{"text": "int main( { return 0; }"}]
        }
    }));
    assert!(
        !client.diagnostics_for(&uri, 3)["params"]["diagnostics"]
            .as_array()
            .unwrap()
            .is_empty()
    );

    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 4},
            "contentChanges": [{"text": "int main(){return unknown_name;}"}]
        }
    }));
    assert!(
        !client.diagnostics_for(&uri, 4)["params"]["diagnostics"]
            .as_array()
            .unwrap()
            .is_empty()
    );

    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 5},
            "contentChanges": [{"text": "struct S{Buffer<int> b;}int main(){S a=S(Buffer<int>(1,0));S c=a;return a.b[0];}"}]
        }
    }));
    let ownership = client.diagnostics_for(&uri, 5);
    assert!(
        ownership["params"]["diagnostics"]
            .as_array()
            .unwrap()
            .iter()
            .any(|diagnostic| diagnostic["code"] == "E0291")
    );

    // Two immediate full replacements exercise cancellation and stale-result suppression. Only
    // the current client version is accepted as the terminal observation.
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 6},
            "contentChanges": [{"text": "int main( { return 0; }"}]
        }
    }));
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 7},
            "contentChanges": [{"text": "int main(){return 0;}"}]
        }
    }));
    assert_eq!(
        client.diagnostics_for(&uri, 7)["params"]["diagnostics"],
        json!([])
    );

    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didSave",
        "params": {"textDocument": {"uri": uri}}
    }));
    assert_eq!(
        client.diagnostics_for(&uri, 7)["params"]["diagnostics"],
        json!([])
    );

    client.send(&json!({"jsonrpc": "2.0", "id": 7, "method": "aether/unknown"}));
    let unknown = client.receive();
    assert_eq!(unknown["id"], 7);
    assert_eq!(unknown["error"]["code"], -32601);

    client.send_raw(b"{");
    assert_eq!(client.receive()["error"]["code"], -32700);

    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didClose",
        "params": {"textDocument": {"uri": uri}}
    }));
    assert_eq!(
        client.diagnostics_for(&uri, 7)["params"]["diagnostics"],
        json!([])
    );
    client.shutdown();
}

#[test]
fn imported_unsaved_overlay_is_published_on_imported_uri() {
    let directory = TestDirectory::new();
    let main = directory.0.join("main.ae");
    let alpha = directory.0.join("alpha.ae");
    fs::write(&main, "import Alpha; int main(){return Alpha.value();}").unwrap();
    fs::write(&alpha, "package Alpha; public int value(){return 1;}").unwrap();
    let main_uri = file_uri(&main);
    let alpha_uri = file_uri(&alpha);
    let mut client = Client::start();
    client.initialize(&directory.0);
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": main_uri, "languageId": "aether", "version": 1,
            "text": "import Alpha; int main(){return Alpha.value();}"
        }}
    }));
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": alpha_uri, "languageId": "aether", "version": 8,
            "text": "package Alpha; public int value( { return 1; }"
        }}
    }));
    let diagnostics = client.diagnostics_for(&alpha_uri, 8);
    assert!(
        !diagnostics["params"]["diagnostics"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    client.shutdown();
}

#[test]
fn project_without_usable_lock_fails_closed_instead_of_using_standalone_rules() {
    for lock in [None, Some("this is not a lock")] {
        let directory = TestDirectory::new();
        directory.write(
            "aether.toml",
            "[package]\nname='app'\nversion='0.1.0'\n[application]\nentry='src/main.ae'\n",
        );
        let main = directory.write("src/main.ae", "int main(){return unknown_name;}");
        if let Some(lock) = lock {
            directory.write("aether.lock", lock);
        }
        let uri = file_uri(&main);
        let mut client = Client::start();
        client.initialize(&directory.0);
        client.send(&json!({
            "jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
                "uri": uri, "languageId": "aether", "version": 1,
                "text": "int main(){return unknown_name;}"
            }}
        }));
        let diagnostics = client.diagnostics_for(&uri, 1);
        let items = diagnostics["params"]["diagnostics"].as_array().unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0]["code"], "aether.project-unavailable");
        assert_eq!(items[0]["source"], "aether-project");
        assert!(items.iter().all(|item| item["code"] != "E0202"));
        let symbols = client.document_symbols(10, &uri);
        assert_eq!(symbols["error"]["code"], -32803);
        client.shutdown();
    }
}

#[test]
fn valid_locked_project_uses_canonical_project_analysis() {
    let directory = TestDirectory::new();
    let lock = "lock-version = 1\nroot = 'root:app@0.1.0'\n\n[[package]]\nid = 'root:app@0.1.0'\nname = 'app'\nversion = '0.1.0'\nsource = 'root'\n";
    directory.write(
        "aether.toml",
        "[package]\nname='app'\nversion='0.1.0'\n[application]\nentry='src/main.ae'\n",
    );
    directory.write("aether.lock", lock);
    let main = directory.write("src/main.ae", "int main(){return unknown_name;}");
    let uri = file_uri(&main);
    let mut client = Client::start();
    client.initialize(&directory.0);
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": uri, "languageId": "aether", "version": 3,
            "text": "int main(){return unknown_name;}"
        }}
    }));
    let diagnostics = client.diagnostics_for(&uri, 3);
    assert!(
        diagnostics["params"]["diagnostics"]
            .as_array()
            .unwrap()
            .iter()
            .any(|item| item["code"] == "E0202")
    );

    fs::remove_file(directory.0.join("aether.lock")).unwrap();
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 4},
            "contentChanges": [{"text": "int main(){return 0;}"}]
        }
    }));
    let unavailable = client.diagnostics_for(&uri, 4);
    assert_eq!(
        unavailable["params"]["diagnostics"][0]["code"],
        "aether.project-unavailable"
    );

    directory.write("aether.lock", lock);
    client.send(&json!({
        "jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 5},
            "contentChanges": [{"text": "int main(){return 0;}"}]
        }
    }));
    assert_eq!(
        client.diagnostics_for(&uri, 5)["params"]["diagnostics"],
        json!([])
    );
    client.shutdown();
}

#[test]
fn identical_shared_diagnostics_are_deduplicated_across_targets() {
    let directory = TestDirectory::new();
    let first = directory.write(
        "first.ae",
        "import Alpha; int main(){return Alpha.value();}",
    );
    let second = directory.write(
        "second.ae",
        "import Alpha; int other(){return Alpha.value();}",
    );
    let alpha = directory.write("alpha.ae", "package Alpha; public int value( { return 1; }");
    let first_uri = file_uri(&first);
    let second_uri = file_uri(&second);
    let alpha_uri = file_uri(&alpha);
    let mut client = Client::start();
    client.initialize(&directory.0);

    for (uri, version, text) in [
        (
            &first_uri,
            1,
            "import Alpha; int main(){return Alpha.value();}",
        ),
        (
            &second_uri,
            2,
            "import Alpha; int other(){return Alpha.value();}",
        ),
    ] {
        client.send(&json!({
            "jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
                "uri": uri, "languageId": "aether", "version": version, "text": text
            }}
        }));
        if version == 1 {
            assert!(
                !client.diagnostics_for_uri(&alpha_uri)["params"]["diagnostics"]
                    .as_array()
                    .unwrap()
                    .is_empty()
            );
        }
    }

    // Publications for one completed target are enqueued in URI order. Observing second.ae
    // therefore means the immediately preceding Alpha publication contains both contributions.
    let mut last_alpha = None;
    loop {
        let message = client.receive();
        if message["method"] != "textDocument/publishDiagnostics" {
            continue;
        }
        if message["params"]["uri"] == alpha_uri {
            last_alpha = Some(message);
        } else if message["params"]["uri"] == second_uri {
            break;
        }
    }
    let last_alpha = last_alpha.unwrap();
    let items = last_alpha["params"]["diagnostics"].as_array().unwrap();
    assert_eq!(items.len(), 1, "identical target contributions must merge");
    client.shutdown();
}
