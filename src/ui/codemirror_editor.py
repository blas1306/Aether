from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from PySide6 import QtCore, QtWidgets  # type: ignore

WEB_EDITOR_INDEX = Path(__file__).with_name("web_editor") / "index.html"


class _CodeMirrorBridge(QtCore.QObject):  # type: ignore[misc]
    ready = QtCore.Signal()
    load_error = QtCore.Signal(str)
    text_changed = QtCore.Signal(str, int)
    cursor_changed = QtCore.Signal(int)

    @QtCore.Slot()
    def editorReady(self) -> None:
        self.ready.emit()

    @QtCore.Slot(str)
    def editorError(self, message: str) -> None:
        self.load_error.emit(message)

    @QtCore.Slot(str, int)
    def editorTextChanged(self, text: str, cursor_position: int) -> None:
        self.text_changed.emit(text, cursor_position)

    @QtCore.Slot(int)
    def editorCursorChanged(self, cursor_position: int) -> None:
        self.cursor_changed.emit(cursor_position)


def _load_qt_webengine():
    try:
        from PySide6 import QtWebChannel, QtWebEngineCore, QtWebEngineWidgets  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "CodeMirrorEditor requires PySide6 QtWebEngine support. "
            "Install a PySide6 build that provides QtWebEngineWidgets and QtWebChannel."
        ) from exc
    return QtWebChannel, QtWebEngineCore, QtWebEngineWidgets


class CodeMirrorEditor(QtWidgets.QWidget):  # type: ignore[misc]
    """Experimental EditorAPI adapter backed by CodeMirror 6 in QWebEngineView."""

    text_changed = QtCore.Signal()
    cursor_changed = QtCore.Signal()
    request_completion = QtCore.Signal()
    run_requested = QtCore.Signal()
    _modification_changed = QtCore.Signal(bool)

    def __init__(self, parent=None, *, enable_autocomplete: bool = False) -> None:
        super().__init__(parent)
        del enable_autocomplete
        QtWebChannel, QtWebEngineCore, QtWebEngineWidgets = _load_qt_webengine()

        self._text = ""
        self._cursor_position = 0
        self._modified = False
        self._page_ready = False
        self._pending_text: str | None = ""
        self._load_error: str | None = None
        self._diagnostics = []
        self._external_completions = []
        self._autocomplete_document_kind = "script"
        self._autocomplete_workspace_provider: Callable[[], list[dict[str, str]]] | None = None

        self._view = QtWebEngineWidgets.QWebEngineView(self)
        self._bridge = _CodeMirrorBridge(self)
        self._channel = QtWebChannel.QWebChannel(self._view.page())
        self._channel.registerObject("codeMirrorBridge", self._bridge)
        self._view.page().setWebChannel(self._channel)
        self._allow_local_file_access(QtWebEngineCore)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._view)

        self._bridge.ready.connect(self._on_editor_ready)
        self._bridge.load_error.connect(self._on_editor_load_error)
        self._bridge.text_changed.connect(self._on_js_text_changed)
        self._bridge.cursor_changed.connect(self._on_js_cursor_changed)
        self._view.loadFinished.connect(self._on_page_load_finished)

        self._load_local_editor()

    def native_widget(self) -> QtWidgets.QWidget:
        return self

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = str(text)
        self._cursor_position = min(self._cursor_position, len(self._text))
        self._pending_text = self._text
        if self._page_ready:
            self._set_js_text(self._text)
        self.text_changed.emit()

    def get_cursor_position(self) -> int:
        return self._cursor_position

    def set_cursor_position(self, pos: int) -> None:
        self._cursor_position = max(0, min(int(pos), len(self._text)))
        if self._page_ready:
            self._run_editor_js(f"window.codeMirrorAdapter.setCursorPosition({self._cursor_position});")
        self.cursor_changed.emit()

    def get_cursor_line_column(self) -> tuple[int, int]:
        position = max(0, min(self._cursor_position, len(self._text)))
        line = self._text.count("\n", 0, position) + 1
        line_start = self._text.rfind("\n", 0, position) + 1
        return line, position - line_start

    def go_to_line(self, line: int, column: int = 0) -> bool:
        offset = self._offset_for_line_column(line, column)
        if offset is None:
            return False
        self._cursor_position = offset
        if self._page_ready:
            self._run_editor_js(
                f"window.codeMirrorAdapter.goToLine({int(line)}, {max(0, int(column))});"
            )
        self.cursor_changed.emit()
        return True

    def has_selection(self) -> bool:
        return False

    def get_selected_text(self) -> str:
        return ""

    def get_selection_start_line(self) -> int | None:
        return None

    def insert_text_at_cursor(self, text: str, cursor_offset: int = 0) -> None:
        position = max(0, min(self._cursor_position, len(self._text)))
        inserted = str(text)
        self.set_text(self._text[:position] + inserted + self._text[position:])
        self.set_cursor_position(position + len(inserted) + int(cursor_offset))
        self.set_modified(True)

    def is_modified(self) -> bool:
        return self._modified

    def set_modified(self, value: bool) -> None:
        changed = self._modified != bool(value)
        self._modified = bool(value)
        if changed:
            self._modification_changed.emit(self._modified)

    def connect_modification_changed(self, callback: Callable[[bool], None]) -> None:
        self._modification_changed.connect(callback)

    def set_diagnostics(self, diagnostics) -> None:
        self._diagnostics = list(diagnostics or [])

    def clear_diagnostics(self) -> None:
        self._diagnostics = []

    def set_completions(self, completions) -> None:
        self._external_completions = list(completions or [])

    def set_autocomplete_document_kind(self, document_kind: str) -> None:
        self._autocomplete_document_kind = str(document_kind or "script")

    def set_autocomplete_workspace_provider(
        self,
        provider: Callable[[], list[dict[str, str]]] | None,
    ) -> None:
        self._autocomplete_workspace_provider = provider

    def set_surface_theme(
        self,
        *,
        background: str,
        line_number_color: str = "#b0b0b0",
        current_line_color: str = "#404040",
    ) -> None:
        del background, line_number_color, current_line_color

    def focus_editor(self) -> None:
        self._view.setFocus()
        if self._page_ready:
            self._run_editor_js("window.codeMirrorAdapter.focusEditor();")

    def web_load_error(self) -> str | None:
        return self._load_error

    def _on_editor_ready(self) -> None:
        self._page_ready = True
        if self._pending_text is not None:
            self._set_js_text(self._pending_text)
            self._pending_text = None

    def _on_editor_load_error(self, message: str) -> None:
        self._load_error = message

    def _on_js_text_changed(self, text: str, cursor_position: int) -> None:
        self._text = text
        self._cursor_position = max(0, min(int(cursor_position), len(self._text)))
        self.set_modified(True)
        self.text_changed.emit()

    def _on_js_cursor_changed(self, cursor_position: int) -> None:
        self._cursor_position = max(0, min(int(cursor_position), len(self._text)))
        self.cursor_changed.emit()

    def _set_js_text(self, text: str) -> None:
        payload = json.dumps(str(text))
        self._run_editor_js(f"window.codeMirrorAdapter.setText({payload});")

    def _run_editor_js(self, expression: str) -> None:
        self._view.page().runJavaScript(expression)

    def _allow_local_file_access(self, QtWebEngineCore) -> None:
        settings = self._view.page().settings()
        web_attribute = QtWebEngineCore.QWebEngineSettings.WebAttribute
        settings.setAttribute(web_attribute.LocalContentCanAccessFileUrls, True)

    def _load_local_editor(self) -> None:
        if not WEB_EDITOR_INDEX.exists():
            self._load_error = f"CodeMirror web editor asset not found: {WEB_EDITOR_INDEX}"
            self._view.setHtml(self._missing_asset_html(self._load_error))
            return
        self._view.load(QtCore.QUrl.fromLocalFile(str(WEB_EDITOR_INDEX)))

    def _on_page_load_finished(self, ok: bool) -> None:
        if not ok and self._load_error is None:
            self._load_error = f"CodeMirror web editor failed to load: {WEB_EDITOR_INDEX}"

    def _missing_asset_html(self, message: str) -> str:
        escaped = (
            message.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        return (
            "<!doctype html><html><body style=\"margin:0;padding:16px;"
            "background:#1e1e1e;color:#ffd7d7;font:13px monospace;\">"
            f"{escaped}</body></html>"
        )

    def _offset_for_line_column(self, line: int, column: int) -> int | None:
        target_line = int(line)
        if target_line < 1:
            target_line = 1
        line_starts = [0]
        line_starts.extend(index + 1 for index, char in enumerate(self._text) if char == "\n")
        if target_line > len(line_starts):
            return None
        start = line_starts[target_line - 1]
        newline_index = self._text.find("\n", start)
        end = len(self._text) if newline_index < 0 else newline_index
        return start + min(max(0, int(column)), end - start)
