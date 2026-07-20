# Aether IntelliJ Plugin

Official IntelliJ support for Aether. The plugin follows the same command-line
contract as the VS Code extension: the native compiler is the normal execution
path, while the AST interpreter is available only when explicitly selected.

The plugin is versioned from Aether's canonical version source and is packaged
separately from the Python wheel.

## Requirements and executable discovery

Install Aether so that both official entry points are available:

```text
aether
aether-lsp
```

Run and compiler actions use `aether`; language features use
`aether-lsp --stdio`. Neither path invokes `python -m` or
`aether_lsp.run_file`.

Each executable is resolved independently in this order:

1. the value configured in **Settings > Tools > Aether**;
2. `.venv/bin/aether` or `.venv/bin/aether-lsp` in the project on Linux/macOS,
   and the corresponding `.venv/Scripts/*.exe`/wrapper on Windows;
3. `aether` or `aether-lsp` from `PATH`.

Configured values may be command names, absolute paths, or paths relative to
the project. They must identify only an executable: shell fragments and
embedded arguments are not accepted. Leave a field empty to enable `.venv`
detection followed by `PATH` lookup.

## Running and compiler actions

- **Run Aether File** runs `aether file.ae` with the native backend.
- **Run Aether File with AST Backend** runs
  `aether --backend=ast file.ae` explicitly.
- **Check Aether File** uses `aether --check`.
- **Emit Aether IR**, **Emit Aether SSA**, and **Emit Aether LLVM** use the
  corresponding `--emit-ir`, `--emit-ssa`, and `--emit-llvm` options.
- **Restart Aether Language Server** asks IntelliJ's public LSP manager to stop
  and restart this plugin's server when needed.

Secondary commands are grouped in the **Aether** submenu. The gutter's green
run icon and the top-level **Run Aether File** action always select native; no
automatic native-to-AST fallback is performed.

Commands run in IntelliJ's standard Run console. Arguments are passed directly
to `GeneralCommandLine`, never through a shell, so paths containing spaces are
safe and stdin remains available. A file uses its containing module/content
root as the working directory when IntelliJ can identify one, then its project
root, and finally the file's parent directory. The CLI's stdout, stderr, and
exit status are preserved, including status 1 (source error), 2 (usage), 3
(toolchain), 70 (internal compiler error), and 130 (interruption).

## Settings and run configurations

**Settings > Tools > Aether** provides:

- **Aether executable**;
- **Aether language server executable**;
- **Default backend** (`Native` initially, or `AST`).

The default-backend preference is used when IntelliJ creates a new run
configuration through its generic configuration producer or template. Each run
configuration persists its own file and backend afterward, so changing the
global preference does not rewrite saved configurations. Older configurations
without a backend load as native. The historical `pythonPath` setting is still
accepted during deserialization but is ignored.

The explicit **Run Aether File** and gutter actions remain native regardless of
the preference; **Run Aether File with AST Backend** always remains AST.

## Language support

The plugin provides the `.ae` file type, basic syntax highlighting, New Aether
File, typing helpers, and IntelliJ LSP integration for diagnostics, completion,
hover, outline, and formatting. The server transport is stdout, so the plugin
does not add logging to it.

## Development

From the repository root:

```bash
./gradlew :tools:intellij-aether:test
./gradlew :tools:intellij-aether:check
./gradlew :tools:intellij-aether:buildPlugin
./gradlew :tools:intellij-aether:runIde
```

`runIde` opens a sandbox IDE for manual checks. Install Aether in the sandbox
environment or point the two executable settings at a suitable installation.

## Limitations

The plugin does not install Aether or manage virtual environments. If no
project `.venv` entry point exists, IntelliJ must inherit a `PATH` containing
the commands or the executable paths must be configured. Historical consumers
may still use `src/aether_lsp/run_file.py`, but this plugin no longer depends on
that compatibility module.
