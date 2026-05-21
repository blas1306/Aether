from __future__ import annotations

import os
import warnings
from collections.abc import Mapping
from typing import Literal, cast

from ui.code_editor import CodeEditor
from ui.editor_api import EditorAPI

EditorKind = Literal["qt_plain", "experimental", "codemirror"]

DEFAULT_EDITOR_KIND: EditorKind = "qt_plain"
SUPPORTED_EDITOR_KINDS: tuple[str, ...] = ("qt_plain", "experimental", "codemirror")
AETHER_EDITOR_KIND_ENV = "AETHER_EDITOR_KIND"


def configured_editor_kind(environ: Mapping[str, str] | None = None) -> EditorKind:
    """Resolve the editor implementation selected for this process."""
    source = os.environ if environ is None else environ
    raw_kind = source.get(AETHER_EDITOR_KIND_ENV)
    if raw_kind is None:
        return DEFAULT_EDITOR_KIND

    kind = raw_kind.strip()
    if kind in SUPPORTED_EDITOR_KINDS:
        return cast(EditorKind, kind)

    supported = ", ".join(SUPPORTED_EDITOR_KINDS)
    warnings.warn(
        f"Invalid {AETHER_EDITOR_KIND_ENV}={raw_kind!r}. "
        f"Supported kinds: {supported}. Falling back to {DEFAULT_EDITOR_KIND!r}.",
        RuntimeWarning,
        stacklevel=2,
    )
    return DEFAULT_EDITOR_KIND


def create_editor(
    kind: str = DEFAULT_EDITOR_KIND,
    parent=None,
    *,
    enable_autocomplete: bool = False,
) -> EditorAPI:
    """Create an editor adapter for the requested implementation kind.

    `experimental` intentionally reuses `CodeEditor` for now. `codemirror` is
    a prototype web-editor adapter and is not the default implementation.
    """
    if kind == "qt_plain":
        return CodeEditor(parent=parent, enable_autocomplete=enable_autocomplete)
    if kind == "experimental":
        return CodeEditor(parent=parent, enable_autocomplete=enable_autocomplete)
    if kind == "codemirror":
        from ui.codemirror_editor import CodeMirrorEditor

        return CodeMirrorEditor(parent=parent, enable_autocomplete=enable_autocomplete)
    supported = ", ".join(SUPPORTED_EDITOR_KINDS)
    raise ValueError(f"Unknown editor kind '{kind}'. Supported kinds: {supported}.")
