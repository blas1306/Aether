# Legacy MathTeX Studio

MathTeX Studio is retained for historical reference and is not part of the
active Aether product.

## What remains

All known MathTeX/MTeX-specific components are isolated under `legacy/`:

- `legacy/src/`: the MathTeX parser/runtime, `.mtx` and `.mtex` execution,
  notebooks, projects, PDF preview, SyncTeX, and related UI modules.
- `legacy/tests/`: the historical tests for those components.
- `legacy/examples/`: `.mtx`, `.mtex`, `.mtn`, and project examples.
- `legacy/docs/`: historical audits and user notes.

These files are intentionally kept in place. They may still be useful for
archaeology, migration work, or selectively recovering ideas, but they are
not maintained as part of Aether's supported behavior.

## Architecture boundary

The active product is:

- the Aether language core and CLI in `src/aether/`;
- the Aether LSP in `src/aether_lsp/`;
- the Aether Studio desktop/editor modules directly under `src/`;
- the main suite in `tests/`;
- `.ae` examples in `examples/`;
- current language documentation in `docs/aether/`.

The boundary is enforced by repository layout and configuration:

- packaging discovers code from `src/`, not `legacy/src/`;
- the `aether` entrypoint resolves to `aether.cli:main`;
- pytest collects `tests/`, not `legacy/tests/`;
- active Aether code and tests do not import legacy MathTeX modules.

Legacy formats (`.mtx`, `.mtex`, and `.mtn`) are not supported by the active
Aether CLI or Studio workflow.

## Maintenance rule

New Aether behavior, tests, examples, and documentation must not be added
under `legacy/`. Avoid moving or deleting legacy files unless a separate,
explicit migration or removal task verifies their historical value and any
remaining imports.
