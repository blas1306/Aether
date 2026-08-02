# Aether examples

This directory contains two deliberately separate catalogs. The machine-readable
source of truth is [`v1_examples_manifest.json`](v1_examples_manifest.json);
this README explains the policy but does not duplicate its path list.

Catalog count: **107 total = 89 V1_NATIVE + 18 AST_ONLY_EXPERIMENTAL; BROKEN = 0**.

## Official Aether 1.0 examples

Entries classified as `V1_NATIVE` belong to the normative Aether 1.0 profile.
They pass the native capability gate, verified IR and SSA lowering, LLVM
emission, and the release-gate observations declared in the manifest. Runnable
entries declare their exit code, stdout/stderr hashes, and timeout; module-only
entries declare `native_module_emission` and are compiled without execution.

Run the smallest official example with:

```bash
aether examples/hello.ae
```

The repository keeps its existing topic directories to avoid a disruptive
route migration. A file's directory is not its stability promise: only its
manifest `classification` determines whether it is official.

## Frontend and AST experiments

Entries classified as `AST_ONLY_EXPERIMENTAL` are non-normative experiments.
They exercise real parser, typechecker, AST-interpreter, plotting, input,
classes, exceptions, advanced algebra, or other surfaces outside Aether 1.0.
Each entry declares `outside_v1_features` and must be rejected by native at the
capability gate, before IR/LLVM lowering.

Use the AST backend explicitly when an entry is runnable:

```bash
aether --backend=ast examples/linear_algebra/basic_operations.ae
```

Some experimental entries have `run: false` because they are modules,
interactive programs, plotting sessions, or frontend demonstrations. The gate
still parses and typechecks them and verifies their exact native exclusion.
They may change without Aether 1.0 compatibility guarantees. See the
[frontend experiments annex](../docs/aether/AETHER_FRONTEND_EXPERIMENTS.md).

The corrected `linear_algebra/primes_advanced.ae` and
`minimos_cuadrados/MinimosCuadrados.ae` remain in this experimental group: they
now use current vector orientation and indexing, but their host algebra,
plotting, inferred globals, and function-value behavior are outside v1.

## Fixtures are not examples

Historical migration inputs and intentionally invalid programs live under
`tests/fixtures/`, never under `examples/`, and never in this manifest. The
slice-assignment experiment formerly presented as a list example is now a
structured invalid fixture. The incomplete interactive least-squares duplicate
was removed; the catalog audit records why it was not preserved as a fixture.

## Validation

Every `.ae` file recursively contained in `examples/` must appear exactly once
in the manifest; there are no exclusions inside this directory. Paths are
normalized repository-relative POSIX paths and entries are ordered
lexicographically by path. A runnable entry's condition and sole backend must
match its classification. Non-runnable entries use null exit-code and stream
observations.

Runtime hashes are SHA-256 digests of the captured stdout or stderr text after
normalizing CRLF and CR to LF, encoded as UTF-8. Paths and source-file bytes do
not participate in these observation hashes. This makes the same semantic
output portable across supported host line-ending conventions.

Fast catalog structure check:

```bash
.venv/bin/python scripts/check_examples_catalog.py --structure-only
```

Frontend, capability, IR, SSA, and LLVM gate:

```bash
.venv/bin/python scripts/check_examples_catalog.py
```

Full native observations (requires clang):

```bash
.venv/bin/python scripts/check_examples_catalog.py --run-native
```

Explicitly refresh capability codes and runtime observations with:

```bash
.venv/bin/python scripts/check_examples_catalog.py --update
```

The update command uses canonical JSON rendering and is idempotent. It refuses
to invent inventory policy or silently promote/demote an example: additions,
removals, and support-boundary changes require an intentional manifest edit
before observations can be refreshed.
