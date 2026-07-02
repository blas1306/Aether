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
aether --backend=ast examples/hello.ae
```

The default command uses the production AST backend:

```text
Lexer -> Parser -> TypeChecker -> ASTBackend
```

`--backend=ast` is equivalent to the default.

An experimental IR backend is available for the current scalar function
subset:

```bash
aether --backend=ir program.ae
```

The IR backend uses:

```text
Lexer -> Parser -> TypeChecker -> IR lowering -> IR verifier -> IR interpreter
```

For now, IR file execution requires a zero-argument `main()` function. It is
not the default backend and does not support structs, classes, lists, advanced
imports, builtins such as `println`, or the full top-level scripting model yet.

Start a persistent session backed by `AetherSession`:

```bash
aether --repl
```

Language-development inspection tools are also available:

```bash
aether --tokens examples/hello.ae
aether --ast examples/hello.ae
aether --emit-ir program.ae
aether --emit-ir --opt program.ae
aether --emit-ir --opt --show-passes program.ae
aether --backend=ir --emit-ir program.ae
```

`--emit-ir` lowers and verifies the program, prints textual IR, and does not
execute it. Add `--opt` to inspect the IR after the current optimization
pipeline. The CLI runs the optimizer to a fixed point, with a default limit of
10 iterations to catch accidental non-convergence:

```text
Lexer -> Parser -> TypeChecker -> IR lowering -> IR verifier -> OptimizerPipeline -> IR verifier
```

Add `--show-passes` with `--emit-ir --opt` to print the lowered IR, the IR after
each optimizer pass in each iteration, and the final IR. This is a development
inspection tool; the default optimized IR output remains unchanged without
`--show-passes`.

Optimizer pass headers include lightweight debug statistics. For example,
`[changed, folded=2]` means the pass changed the IR and folded two operations,
while `[no changes, removed=0]` means the pass left the IR unchanged. These
metrics are only for compiler-development inspection; they are not part of the
IR semantics and do not affect execution behavior.

The current optimizer pipeline includes constant folding, block-local constant
propagation, algebraic simplification, dead code elimination, and block-local
dead store elimination. The iterative pipeline does not add new optimizations;
it reruns these existing passes until a full iteration reports no changes or
the maximum iteration count is reached. Dead Store Elimination only removes
`IRStore`
instructions whose slot is not loaded again before another same-slot store or
before a returning block ends. It does not perform global liveness, alias,
escape, interprocedural, SSA, `if`, or `while` analysis; stores that may be
observed through `jump` or `branch` successors are preserved.

Optimization is currently connected only to `--emit-ir`. `--backend=ir` still
executes the verified, unoptimized IR, and `--opt` without `--emit-ir` is
rejected. `--show-passes` also requires `--emit-ir --opt`.

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
  typed intermediate representation and documents the experimental Python IR
  backend.

## Examples

Example Aether programs are located in the [examples/](examples/) directory, organized by category:

- **structs/** - Working with structs, methods, and interface implementation
- **linear_algebra/** - Vector and matrix operations
- **nonlinear_systems/** - Solving non-linear systems of equations
- **interactive/** - Examples requiring user input (not for automation)
- **minimos_cuadrados/** - Least-squares polynomial fitting

See [examples/README.md](examples/README.md) for details on each example.
