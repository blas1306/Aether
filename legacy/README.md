# Legacy MathTeX/MTeX Code

This folder isolates the historical MathTeX Studio/MTeX implementation from
the active Aether Studio surface.

Contents:

- `src/`: old `.mtx`, `.mtex`, notebook, PDF, SyncTeX, project, parser, and
  diagnostic modules.
- `tests/`: tests that exercised those legacy modules before isolation.
- `examples/`: old `.mtx`, `.mtex`, and project examples.
- `docs/`: historical notes and legacy user documentation.

The active application and test suite live in `src/`, `tests/`, and
`docs/aether/`. Aether Studio currently supports `.ae` files only.
