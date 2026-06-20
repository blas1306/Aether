# Aether

Aether is a programming language for numerical and general-purpose computing.
This repository contains the language implementation, the official `aether`
CLI, and the optional Aether Studio desktop interface.

The active Aether workflow is intentionally focused:

- edit `.ae` scripts
- run programs with the `aether` CLI
- run complete scripts or selections
- use a persistent Aether REPL with the `aether>` prompt
- inspect the current Aether workspace
- choose a working directory for local files

MathTeX Studio is historical code, not an active Aether runtime. Its `.mtx`,
`.mtex`, `.mtn`, project, notebook, and PDF workflows are isolated under
[`legacy/`](legacy/). See
[`docs/legacy/README.md`](docs/legacy/README.md) for the retained components
and architecture boundary.

## Aether Scripts

Create or open `.ae` files from the Aether editor and run them with `Ctrl+Enter` or the Run button.

```aether
x = 2;
y = 3;
println(x + y);
```

Use `print(...)` or `println(...)` for visible output. Expression auto-printing is not part of Aether v0 yet.

Strings support Aether interpolation with `$expr$`:

```aether
n = 4;
println("n = $n$");
println("Precio: \$10");
```

## REPL

The lower console is backed by a persistent `AetherSession`.

```text
aether> x = 10;
aether> println(x);
10
```

Restarting the REPL clears the session state. Failed commands roll back without destroying earlier committed variables.

## Aether CLI

Install the project in editable mode to make the official `aether` command
available in the active Python environment:

```bash
python3 -m pip install -e .
```

Run a program directly:

```bash
aether examples/hello.ae
```

The command uses the normal language pipeline:

```text
Lexer -> Parser -> TypeChecker -> Interpreter
```

Start a persistent session backed by `AetherSession`:

```bash
aether --repl
```

Language-development inspection tools are also available:

```bash
aether --tokens examples/hello.ae
aether --ast examples/hello.ae
```

Use `aether --help` for all current options and `aether --version` for the
language version. The primary execution form is `aether file.ae`; there is no
`aether run` command.

The optional desktop application is available through:

```bash
python3 src/main.py
```

`python3 src/main.py --cli` starts the Studio text-mode REPL. The installed
`aether` command remains the primary command-line entrypoint.

## Repository Architecture

- `src/aether/`: language core, runtime, standard library, and official CLI.
- `src/aether_lsp/`: Aether language server support.
- `src/`: active desktop application and editor integration modules.
- `tests/`: active Aether, CLI, LSP, editor, and desktop tests.
- `examples/`: `.ae` programs for the active language.
- `docs/aether/`: current language specification.
- `legacy/`: quarantined MathTeX Studio implementation, tests, examples, and
  historical documentation.

The active package configuration only discovers packages under `src/`, and
the main pytest configuration only collects `tests/`. Neither
`src/aether/` nor the `aether` CLI imports modules from `legacy/`.

## Development

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -e . --no-deps
```

Run the GUI:

```bash
python3 src/main.py
```

Run the main test suite from the project virtual environment:

```bash
PYTHONPATH=src .venv/bin/pytest
git diff --check
```

Technical language documents:

- [Aether v0 Language Specification](docs/aether/AETHER_V0_SPEC.md) describes
  the current language behavior.
- [Aether IR Initial Design](docs/aether/AETHER_IR_DESIGN.md) proposes a future
  typed intermediate representation; it is a design document, not an
  implemented feature.

## Examples

Example Aether programs are located in the [examples/](examples/) directory, organized by category:

- **structs/** - Working with structs, methods, and interface implementation
- **linear_algebra/** - Vector and matrix operations
- **nonlinear_systems/** - Solving non-linear systems of equations
- **interactive/** - Examples requiring user input (not for automation)
- **minimos_cuadrados/** - Least-squares polynomial fitting

See [examples/README.md](examples/README.md) for details on each example.
