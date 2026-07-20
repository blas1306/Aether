# Aether for Visual Studio Code

This is the official **development** extension for Aether. It recognizes `.ae`
files, provides TextMate syntax highlighting, starts the shared Aether language
server, and exposes the Aether CLI through editor commands. Parsing, type
checking, formatting, diagnostics, completion, hover, and navigation remain the
responsibility of `aether-lsp` and the compiler; the extension does not
reimplement language semantics.

The extension is not published in the Visual Studio Marketplace yet. The
`aether-dev` publisher is a provisional packaging placeholder and must be
replaced with the real publisher before publication.

## Requirements

Install Aether separately and ensure both commands are available in `PATH`:

```text
aether
aether-lsp
```

For a development checkout of the main repository:

```bash
python3 -m pip install -e . --no-deps
```

If the executables are elsewhere, set their full paths in VS Code settings.
No Linux-only path is hardcoded, and paths containing spaces are passed safely
without invoking a shell.

## Commands

- `Aether: Run` executes `aether file.ae`. The CLI's native/LLVM backend is the
  default and is also the editor-title play button.
- `Aether: Check` executes `aether --check file.ae`.
- `Aether: Run with AST Backend` explicitly executes
  `aether --backend=ast file.ae`. AST is auxiliary/experimental and is never a
  silent fallback.
- `Aether: Emit IR`, `Aether: Emit SSA`, and `Aether: Emit LLVM` use the audited
  public CLI flags `--emit-ir`, `--emit-ssa`, and `--emit-llvm`.
- `Aether: Restart Language Server` restarts `aether-lsp`.
- `Aether: Show Output` reveals the `Aether` output channel.

Commands save a dirty active Aether document first. Untitled, virtual, and
non-Aether files are rejected. The working directory is the containing
workspace folder, or the file's parent directory when it is outside a
workspace.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `aether.executable` | `aether` | CLI executable name or path. |
| `aether.lsp.executable` | `aether-lsp` | LSP executable name or path. |
| `aether.defaultBackend` | `native` | Backend for `Aether: Run`: `native` or `ast`. |
| `aether.optimizationLevel` | `O0` | `O0`, `O1`, or `O2`; currently passed only to `Emit IR`, matching the CLI contract. |
| `aether.revealOutput` | `onError` | Reveal output `always`, `onError`, or `never`. |

The output channel preserves stdout, stderr, process exit codes, and launch
errors. It does not reinterpret CLI diagnostics, enable `--debug`, or turn an
internal compiler error into a syntax diagnostic.

## Development

This extension has its own Node dependency boundary. From this directory:

```bash
npm install
npm run compile
npm test
npm run package
```

Open `vscode-extension/` as the VS Code workspace and press F5 to launch an
Extension Development Host. Packaging creates `aether-vscode-0.1.0.vsix`; it
does not publish anything.

## Current limitations

- Aether and its language server must be installed externally.
- There is no debugger or custom UI.
- Programs run in the output channel, so interactive stdin is not available in
  this MVP.
- TextMate highlighting is intentionally lexical and does not replace the
  Aether parser. Although editor block-comment pairing is registered for the
  requested tooling contract, normative Aether v1 currently accepts `#` and
  `//` line comments and does not define block comments.
- The official 16×16 IntelliJ SVG is reused to render the packaged PNG icon;
  no new logo was invented.
