# Aether Studio

Aether Studio is a focused desktop environment for the Aether language.

The current workflow is intentionally small:

- edit `.ae` scripts
- run complete scripts or selections
- use a persistent Aether REPL with the `aether>` prompt
- inspect the current Aether workspace
- choose a working directory for local files

Legacy MathTeX, MTeX, `.mtex`, `.mtx`, `.mtn`, project, notebook, and PDF workflows are no longer part of the active application surface. The old modules may still exist in the repository while the codebase is cleaned up, but the product entrypoints now target Aether only.

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

## CLI

The text-mode CLI is also Aether-only:

```bash
python3 src/main.py --cli
```

It starts the same `aether>` workflow without opening the Qt interface.

## Development

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run the GUI:

```bash
python3 src/main.py
```

Run focused tests from the project virtual environment:

```bash
.venv/bin/python -m pytest -q tests/aether tests/test_aether_lsp_server.py tests/test_repl_controller.py
```

See [docs/aether/AETHER_V0_SPEC.md](docs/aether/AETHER_V0_SPEC.md) for the current language specification.

## Examples

Example Aether programs are located in the [examples/](examples/) directory, organized by category:

- **structs/** - Working with structs, methods, and interface implementation
- **linear_algebra/** - Vector and matrix operations
- **nonlinear_systems/** - Solving non-linear systems of equations
- **interactive/** - Examples requiring user input (not for automation)
- **minimos_cuadrados/** - Least-squares polynomial fitting

See [examples/README.md](examples/README.md) for details on each example.
