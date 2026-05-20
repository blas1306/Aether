from __future__ import annotations

from typing import Literal

from ui.code_editor import CodeEditor
from ui.editor_api import EditorAPI

EditorKind = Literal["qt_plain", "experimental", "codemirror"]

DEFAULT_EDITOR_KIND: EditorKind = "qt_plain"
SUPPORTED_EDITOR_KINDS: tuple[str, ...] = ("qt_plain", "experimental", "codemirror")


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
