# Deprecated tooling removal audit

This report records the removal of the archived MathLab/MathTeX tree and the
deprecated Aether Qt desktop IDE. The supported tooling surface is now the
Aether CLI, shared language service/LSP, VS Code extension, and IntelliJ plugin.

## Dependency audit

The `legacy/` and `docs/legacy/` trees had no active consumer. Production and
package discovery were rooted at `src/`; pytest was rooted at `tests/`; release,
CI, example catalog, VS Code, and IntelliJ configuration did not load legacy
code or data. References in README and documentation described the tree only as
an archive. Those references were stale after removal and were replaced by the
short history note in `docs/EVOLUTION.md`.

Consequently, production imports, packaging, scripts, CI, release checks,
generated sources, and active example manifests were classified as **no
dependency**; the self-contained tests under `legacy/tests/` were part of the
archive rather than active consumers; documentation mentions were either
**historical reference only** or **stale references** updated by this change.

The Qt dependency graph was:

```text
src/main.py
  -> src/qt_app.py
     -> src/ui/                 (widgets, editor API/factory, CodeMirror adapter)
     -> src/actions/            (desktop action and menu registry)
     -> src/editor/             (Qt editor interaction/highlighting helpers)
     -> src/repl/               (desktop console adapter)
     -> src/language_runtime.py (desktop run adapter)

src/ui/codemirror_editor.py
  -> src/ui/web_editor/
     <- tools/web_editor/       (bundle-only build input)
```

The source-level entry points were `src/main.py::main`, its `launch_gui`
adapter, `src/qt_app.py::launch_qt_gui`, and `AetherStudioWindow`. There was no
Qt console-script entry point in package metadata.

`src/app_preferences.py` and `src/numeric_format.py` had only their own tests and
package declarations; neither had a supported client. `plot_backend.py` remains
part of the interpreter/stdlib and was retained, but its optional check for an
already-running PySide application was removed.

The Qt-only test set comprised `test_qt_action_registry.py`,
`test_qt_autocomplete_ux.py`, `test_qt_contextual_menus.py`,
`test_qt_syntax_highlighting.py`, `test_editor_api.py`,
`test_auto_pairs.py`, `test_bracket_matcher.py`, `test_indent_guides.py`,
`test_occurrence_highlighter.py`, `test_action_registry.py`,
`test_app_actions.py`, `test_menu_specs.py`, `test_app_preferences.py`,
`test_language_runtime.py`, and `test_repl_controller.py`.

## Protected shared tooling

The LSP imports `autocomplete_engine.py`, `command_catalog.py`, and
`document_symbols.py` directly. These neutral modules were retained, as were
`src/aether/language_service.py`, the formatter, parser, typechecker, compiler
diagnostics, CLI, and plotting backend. VS Code and IntelliJ launch the shared
LSP/CLI and do not import or bundle the embedded web editor. No compiler
semantics lived exclusively in Qt code.

## Removed areas

- Entire `legacy/` and `docs/legacy/` trees, including archived sources, tests,
  examples, documentation, and generated example artifacts.
- `src/main.py`, `src/qt_app.py`, `src/ui/`, `src/actions/`, `src/editor/`,
  `src/repl/`, `src/language_runtime.py`, `src/app_preferences.py`, and
  `src/numeric_format.py`.
- `tools/web_editor/` and the bundled assets formerly under
  `src/ui/web_editor/`.
- The Qt-only tests listed above and the global PySide pytest fixture.
- The `studio` optional dependency, PySide6, platformdirs, and obsolete Python
  module package entries.

Release verification now rejects legacy/Qt paths and Qt dependency metadata.
Current documentation and release qualification material name only CLI, LSP,
VS Code, and IntelliJ as supported tooling.

## Validation

- Focused CLI/LSP/language-service/formatter/diagnostics/plot/release tests:
  240 passed.
- Full active suite excluding the known baseline file: 4,400 passed, 4 skipped.
- Full unfiltered suite: 4,419 passed, 4 skipped, 12 failed. All 12 failures are
  the pre-existing row/column-vector expectation mismatch in
  `tests/aether/test_import_aliases.py`; the same failures reproduce from an
  unmodified `HEAD` archive.
- IntelliJ Gradle tests: successful. VS Code tests were unavailable because
  Node and npm were not installed; extension sources and manifests were not
  changed.
- Documentation, capability, example-catalog, diagnostics, compileall, CLI
  smoke, local link, and whitespace checks passed.
- The final wheel and sdist passed content verification. A clean wheel install
  passed CLI/native smoke checks and exposed the packaged LSP entry point.

## Remaining debt

Completion and symbol infrastructure is still split between
`src/aether/language_service.py` and the top-level modules used by the LSP.
Both have supported consumers and were therefore retained. Consolidating those
implementations is a separate semantic refactor; this removal did not duplicate
or rewrite compiler behavior.
