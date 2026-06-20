# Legacy MathTeX/MTeX Code

This folder isolates the historical MathTeX Studio/MTeX implementation from
the active Aether product.

Contents:

- `src/`: old `.mtx`, `.mtex`, notebook, PDF, SyncTeX, project, parser, and
  diagnostic modules.
- `tests/`: tests that exercised those legacy modules before isolation.
- `examples/`: old `.mtx`, `.mtex`, and project examples.
- `docs/`: historical notes and legacy user documentation.

The active application and test suite live in `src/`, `tests/`, and
`docs/aether/`. Aether Studio currently supports `.ae` files only.

See [`docs/legacy/README.md`](../docs/legacy/README.md) for the canonical
inventory, architecture boundary, and maintenance policy for this directory.
