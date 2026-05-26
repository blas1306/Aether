# MathLab Legacy Reference Audit

## Executive Summary

This audit classifies current `MathLab`, `mathlab`, and `MATHLAB` references in `src`, `tests`, and `docs` before moving or renaming legacy files.

Current state:

- Aether is already the visible/default experience in the script tab, new script naming, notebook default language, and default REPL.
- MathLab remains valid as the `.mtx` legacy runtime and compatibility surface.
- The largest remaining migration work is internal naming in Qt helpers and REPL/runtime adapters, not user-facing behavior.
- No files should be moved yet. Keep the legacy runtime stable until `.mtx` and `.mtex` compatibility are covered by a dedicated migration plan.

The raw search commands also matched Python bytecode in `__pycache__`; those binary matches are ignored in this classification.

## A. Visible References That Should Change To Aether

These references are visible or documentation-facing and should be reviewed when polishing branding. They should not be changed blindly if they describe the `.mtx` legacy path.

- `docs/aether/AETHER_V0_SPEC.md:702`
  - Cleaned in the first post-audit pass.
  - Current wording presents `.ae` as the primary Aether script flow and `.mtx` as the MathLab Legacy Console compatibility path.
- `docs/aether/AETHER_V0_SPEC.md:729`
  - Cleaned in the first post-audit pass.
  - Current wording uses `MathLab Legacy pipeline` for the historical compatibility layer.

No current UI strings found by this audit appear to present MathLab as the primary experience. Existing visible UI strings such as `MathLab Legacy Console`, `MathLab Legacy Files (*.mtx)`, and `.mtx` guidance are classified as valid legacy references.

## B. Valid Legacy References

These references are part of the `.mtx` compatibility contract and should remain until the legacy runtime is deliberately retired.

- `src/language_runtime.py`
  - `MATHLAB_RUNTIME = FileRuntime("mathlab", "MathLab Legacy", (".mtx",))`
  - `create_session_for_language` accepts `mathlab`, `mathlab legacy`, `mtx`, `.mtx`.
  - `_run_mathlab_source(...)` executes `.mtx` through the legacy adapter.
  - `MathLab Legacy execution stopped due to an error.`
- `src/repl/repl_controller.py`
  - `MATHLAB_PROFILE`
  - `id="mathlab"`
  - `prompt="mathlab> "`
  - `MathLab Legacy Console`
  - `MathLabReplBackend`
  - `create_mathlab_repl(...)`
- `src/repl/__init__.py`
  - exports `create_mathlab_repl` for compatibility.
- `src/notebook_parser.py`
  - accepts explicit `\begin{MathLab}` blocks.
- `src/notebook_runner.py`
  - dispatches `block.language == "MathLab"` to the legacy notebook runner path.
- `src/qt_app.py`
  - imports and instantiates `create_mathlab_repl`.
  - selects `mathlab_repl` only for `MATHLAB_RUNTIME`.
  - visible strings that explicitly say `MathLab Legacy` for `.mtx`.
- Tests that protect legacy behavior:
  - `tests/test_language_runtime.py`
  - `tests/test_repl_controller.py`
  - `tests/test_notebook_parser.py`
  - `tests/test_notebook_file.py`
  - `tests/test_notebook_editor_view.py`
  - `tests/test_notebook_view.py`
  - `tests/test_notebook_runner.py`
  - `tests/test_qt_contextual_menus.py`
  - `tests/test_qt_project_context_switching.py`

## C. Internal Names To Rename Later

These names no longer necessarily mean the MathLab runtime, but they are internal implementation names. Rename them only in a focused cleanup pass, after tests are green.

First safe internal pass:

- `src/language_runtime.py` now exposes `MATHLAB_LEGACY_RUNTIME` as an additive alias of `MATHLAB_RUNTIME`.
- `src/repl/repl_controller.py` now exposes `create_legacy_mathlab_repl(...)` as an additive wrapper around `create_mathlab_repl(...)`.
- Existing names remain intact for compatibility.

- `src/qt_app.py`
  - `_apply_mathlab_stylesheet`
  - `_create_mathlab_panel`
  - `mathlab_repl` instance attribute, if the future architecture uses a more generic legacy runtime registry.
  - Qt object names such as `mathLabPanel`, `mathLabToolbarCard`, `mathLabScriptTabs`, `mathLabWorkspaceTable`, and related stylesheet selectors.
- `src/repl/repl_controller.py`
  - `MathLabReplBackend`, only if the legacy backend is later renamed as a `.mtx` backend.
- `src/language_runtime.py`
  - `_run_mathlab_source`, only if the legacy adapter becomes `_run_mtx_legacy_source`.
  - `MATHLAB_RUNTIME`, only if a future naming pass prefers `MTX_LEGACY_RUNTIME`.
- Test names that say `mathlab` while testing the legacy contract:
  - keep for now because they document the compatibility layer.
  - rename only if the implementation names change.

## Critical Files To Avoid Moving Or Deleting

Do not move, delete, or rename these until there is a dedicated legacy runtime plan:

- `src/latex_lang.py`
- `src/mtex_executor.py`
- `src/console_engine.py`
- `src/language_runtime.py`
- `src/repl/repl_controller.py`
- `src/repl/__init__.py`
- `.mtx` fixtures and examples under `ejemplos/` and tests.
- `.mtex` document pipeline files and tests.

## Safer Future Rename Targets

These are safer candidates for a later mechanical rename because they are branding or helper names, not the core runtime implementation:

- `src/qt_app.py` helper methods:
  - `_apply_mathlab_stylesheet` -> `_apply_aether_stylesheet`
  - `_create_mathlab_panel` -> `_create_aether_panel`
- Qt object names and stylesheet selectors in `src/qt_app.py`:
  - `mathLabPanel*` -> `aetherPanel*`
  - `mathLabToolbar*` -> `aetherToolbar*`
  - `mathLabScriptTabs` -> `aetherScriptTabs`
  - `mathLabWorkspaceTable` -> `aetherWorkspaceTable`
- Documentation wording in `docs/aether/AETHER_V0_SPEC.md` where it describes current UI branding.

## Recommended Next Steps

1. Keep the current legacy runtime names stable until `.mtx` and `.mtex` tests are fully runnable in the local environment.
2. Keep documentation wording consistent as `MathLab Legacy` where it refers to the compatibility layer.
3. Do a scoped Qt helper rename pass for `_apply_mathlab_stylesheet`, `_create_mathlab_panel`, and related object names.
4. Only after that, decide whether runtime identifiers should stay as `MathLab` for compatibility or move to `MtxLegacy` naming.
5. Before moving legacy files, add a migration checklist that explicitly protects `.mtx`, `.mtex`, `create_mathlab_repl`, and `\begin{MathLab}`.
