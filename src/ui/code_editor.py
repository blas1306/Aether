from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from autocomplete_engine import AutocompleteMatch, AutocompleteRequest, build_autocomplete_suggestions, detect_autocomplete_match
from command_catalog import CommandSuggestion
from editor.auto_pairs import (
    closing_for_opening,
    empty_pair_at,
    should_skip_closing,
    smart_enter_in_empty_braces,
)
from editor.bracket_matcher import find_bracket_match
from editor.indent_guides import QtIndentGuideRenderer
from editor.occurrence_highlighter import find_occurrences

try:  # pragma: no cover - depende de la instalacion del usuario
    from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
except Exception as exc:  # pragma: no cover - no hay Qt disponible
    raise ImportError("PySide6 no esta disponible") from exc

EDITOR_KEYWORDS = (
    "int",
    "float",
    "double",
    "complex",
    "string",
    "boolean",
    "Exception",
    "void",
    "Matrix",
    "Vector",
    "alias",
    "struct",
    "enum",
    "const",
    "package",
    "public",
    "private",
    "for",
    "break",
    "continue",
    "try",
    "catch",
    "throw",
    "if",
    "elif",
    "else",
    "while",
    "function",
    "return",
    "null",
    "repeat",
    "until",
    "end",
    "plot",
    "sum",
    "product",
)
KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(word) for word in EDITOR_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
LOGICAL_OPERATOR_PATTERN = re.compile(r"&&|\|\|")
SCRIPT_COMMENT_PATTERN = re.compile(r"#.*|//.*")
STRING_PATTERN = re.compile(r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')")
NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")
PUNCT_PATTERN = re.compile(r"[=+\-*/%\\^<>{}\[\](),.;:|?]")
INDENTATION = " " * 4
EDITOR_BG = "#353535"
TEXT_FG = "#ffffff"
STRING_COLOR = "#c586c0"
NUMBER_COLOR = "#45b39d"
PUNCT_COLOR = "#f7dc6f"
SELECT_BG = "rgba(255, 159, 59, 110)"  # tono calido con algo de transparencia
EDITOR_MATCH_BG = "#6b7a3f"
BRACKET_MATCH_BG = EDITOR_MATCH_BG
BRACKET_ERROR_BG = "#a65353"
BRACKET_MATCH_FG = "#ffffff"
OCCURRENCE_MATCH_BG = EDITOR_MATCH_BG
FUNC_COLOR = "#3d5afe"
IMPORT_KEYWORD_COLOR = "#cc7832"
IMPORT_MODULE_COLOR = "#ce9178"
IMPORT_NAME_COLOR = "#9cdcfe"
FUNCTION_PATTERN = re.compile(r"\\[A-Za-z][A-Za-z0-9_]*")
IMPORT_PATTERN = re.compile(
    r"\bimport\b\s+(?P<module>[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)"
)
FROM_IMPORT_PATTERN = re.compile(
    r"\bfrom\b\s+(?P<module>[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\s+(?:\bimport\b(?:\s+(?P<names>[A-Za-z0-9_,\s]*))?)?"
)


class AetherSyntaxHighlighter(QtGui.QSyntaxHighlighter):  # type: ignore[misc]
    _STATE_TEXT = 0

    def __init__(self, document):
        super().__init__(document)
        assert QtGui is not None
        self._formats = {
            "keyword": self._make_format(QtGui.QColor("#a30101")),
            "comment": self._make_format(QtGui.QColor("#00aa00")),
            "string": self._make_format(QtGui.QColor(STRING_COLOR)),
            "number": self._make_format(QtGui.QColor(NUMBER_COLOR)),
            "punct": self._make_format(QtGui.QColor(PUNCT_COLOR)),
            "func": self._make_format(QtGui.QColor(FUNC_COLOR)),
            "import_kw": self._make_format(QtGui.QColor(IMPORT_KEYWORD_COLOR)),
            "import_mod": self._make_format(QtGui.QColor(IMPORT_MODULE_COLOR)),
            "import_name": self._make_format(QtGui.QColor(IMPORT_NAME_COLOR)),
        }
    def _make_format(self, color: QtGui.QColor) -> QtGui.QTextCharFormat:
        assert QtGui is not None
        fmt = QtGui.QTextCharFormat()
        fmt.setForeground(color)
        return fmt

    def set_document_kind(self, document_kind: str) -> None:
        del document_kind
        self.rehighlight()

    def _keyword_spans(self, text: str) -> list[tuple[int, int]]:
        self.setCurrentBlockState(self._STATE_TEXT)
        return [(0, len(text))]

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - API Qt
        keyword_spans = self._keyword_spans(text)
        comment_spans = self._comment_spans(text, keyword_spans)
        for match in STRING_PATTERN.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._formats["string"])
        for start, end in comment_spans:
            self.setFormat(start, end - start, self._formats["comment"])
        skip = []
        for match in STRING_PATTERN.finditer(text):
            skip.append((match.start(), match.end()))
        skip.extend(comment_spans)

        def _skipped(pos: int) -> bool:
            return any(a <= pos < b for a, b in skip)

        def _in_keyword_span(pos: int) -> bool:
            return any(start <= pos < end for start, end in keyword_spans)

        for match in KEYWORD_PATTERN.finditer(text):
            if _skipped(match.start()) or not _in_keyword_span(match.start()):
                continue
            self.setFormat(match.start(), match.end() - match.start(), self._formats["keyword"])
        for match in FUNCTION_PATTERN.finditer(text):
            if _skipped(match.start()):
                continue
            self.setFormat(match.start(), match.end() - match.start(), self._formats["func"])
        for match in NUMBER_PATTERN.finditer(text):
            if _skipped(match.start()):
                continue
            self.setFormat(match.start(), match.end() - match.start(), self._formats["number"])
        for match in PUNCT_PATTERN.finditer(text):
            if _skipped(match.start()):
                continue
            self.setFormat(match.start(), match.end() - match.start(), self._formats["punct"])
        for match in LOGICAL_OPERATOR_PATTERN.finditer(text):
            if _skipped(match.start()) or not _in_keyword_span(match.start()):
                continue
            self.setFormat(match.start(), match.end() - match.start(), self._formats["keyword"])
        for match in IMPORT_PATTERN.finditer(text):
            if _skipped(match.start()) or not _in_keyword_span(match.start()):
                continue
            import_start = match.start()
            self.setFormat(import_start, 6, self._formats["import_kw"])
            mod_start, mod_end = match.span("module")
            self.setFormat(mod_start, mod_end - mod_start, self._formats["import_mod"])
        for match in FROM_IMPORT_PATTERN.finditer(text):
            if _skipped(match.start()) or not _in_keyword_span(match.start()):
                continue
            from_start = match.start()
            self.setFormat(from_start, 4, self._formats["import_kw"])
            import_pos = text.rfind("import", match.start(), match.end())
            if import_pos != -1:
                self.setFormat(import_pos, 6, self._formats["import_kw"])
            mod_start, mod_end = match.span("module")
            self.setFormat(mod_start, mod_end - mod_start, self._formats["import_mod"])
            names_segment = match.group("names") or ""
            names_base = match.start("names") if match.start("names") != -1 else match.end()
            search_pos = 0
            for name in [n.strip() for n in names_segment.split(",") if n.strip()]:
                idx = names_segment.find(name, search_pos)
                if idx == -1:
                    continue
                name_start = names_base + idx
                if _skipped(name_start):
                    continue
                self.setFormat(name_start, len(name), self._formats["import_name"])
                search_pos = idx + len(name)

    def _comment_spans(self, text: str, code_spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
        def _in_code(pos: int) -> bool:
            return any(start <= pos < end for start, end in code_spans)

        spans: list[tuple[int, int]] = []
        for match in SCRIPT_COMMENT_PATTERN.finditer(text):
            spans.append((match.start(), match.end()))
        return spans


class LineNumberArea(QtWidgets.QWidget):  # type: ignore[misc]
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QtCore.QSize:  # noqa: D401
        return QtCore.QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):  # noqa: D401
        self._editor.line_number_area_paint_event(event)


@dataclass(frozen=True)
class EditorAutocompleteContext:
    block_position: int
    token: AutocompleteMatch


class QtAutocompletePopup(QtWidgets.QFrame):  # type: ignore[misc]
    def __init__(self, parent, *, on_accept) -> None:
        super().__init__(parent)
        self._on_accept = on_accept
        self._suggestions: list[CommandSuggestion] = []
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)
        self.setStyleSheet(
            """
            QFrame {
                background: #2c2f33;
                border: 1px solid #5a6472;
                border-radius: 4px;
            }
            QListWidget {
                background: transparent;
                border: none;
                color: #f4f4f4;
                font-family: Consolas;
                font-size: 10pt;
                outline: none;
            }
            QListWidget::item {
                padding: 4px 8px;
            }
            QListWidget::item:selected {
                background: #5a6472;
                color: #ffffff;
            }
        """
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._list = QtWidgets.QListWidget(self)
        self._list.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setMouseTracking(True)
        self._list.itemClicked.connect(lambda _item: self.accept_current())
        self._list.itemDoubleClicked.connect(lambda _item: self.accept_current())
        layout.addWidget(self._list)

    def is_visible(self) -> bool:
        return self.isVisible()

    def show_suggestions(self, editor: "CodeEditor", suggestions: list[CommandSuggestion]) -> None:
        self._suggestions = list(suggestions)
        if not self._suggestions:
            self.hide_popup()
            return

        self._list.clear()
        for suggestion in self._suggestions:
            label = suggestion.label or suggestion.name
            item = QtWidgets.QListWidgetItem(f"{label}  {suggestion.description}")
            tooltip_lines = [label]
            if suggestion.signature and suggestion.signature != label:
                tooltip_lines.append(suggestion.signature)
            if suggestion.category:
                tooltip_lines.append(f"Category: {suggestion.category}")
            if suggestion.description:
                tooltip_lines.append(suggestion.description)
            item.setToolTip("\n".join(tooltip_lines))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, suggestion)
            self._list.addItem(item)

        self._list.setCurrentRow(0)
        self._position_for_editor(editor)
        self.show()
        self.raise_()

    def hide_popup(self) -> None:
        self._suggestions = []
        self.hide()

    def move_selection(self, delta: int) -> bool:
        if not self.isVisible() or not self._suggestions:
            return False
        current_row = max(0, self._list.currentRow())
        next_row = max(0, min(self._list.count() - 1, current_row + delta))
        self._list.setCurrentRow(next_row)
        item = self._list.item(next_row)
        if item is not None:
            self._list.scrollToItem(item)
        return True

    def current_suggestion(self) -> CommandSuggestion | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(QtCore.Qt.ItemDataRole.UserRole)

    def accept_current(self) -> bool:
        suggestion = self.current_suggestion()
        if suggestion is None:
            return False
        self._on_accept(suggestion)
        return True

    def reposition(self, editor: "CodeEditor") -> None:
        if self.isVisible():
            self._position_for_editor(editor)

    def _position_for_editor(self, editor: "CodeEditor") -> None:
        viewport_rect = editor.viewport().rect()
        row_height = max(22, self._list.sizeHintForRow(0))
        visible_rows = min(max(1, self._list.count()), 8)
        frame = self.frameWidth() * 2
        scrollbar_width = self._list.verticalScrollBar().sizeHint().width()
        width = min(560, max(280, int(viewport_rect.width() * 0.55)))
        width = min(width, max(1, viewport_rect.width()))
        needs_scroll = self._list.count() > visible_rows
        height = row_height * visible_rows + frame + 4
        if needs_scroll:
            width += scrollbar_width
            width = min(width, max(1, viewport_rect.width()))

        max_height = max(1, viewport_rect.height() - 8)
        if height > max_height:
            height = max_height
        self.resize(width, height)

        rect = editor.cursorRect()
        below_y = rect.bottom() + 4
        above_y = rect.top() - height - 4
        space_below = viewport_rect.height() - below_y
        space_above = rect.top() - 4
        if height > space_below and space_above > space_below:
            y = max(0, above_y)
        else:
            y = min(max(0, below_y), max(0, viewport_rect.height() - height))

        x = min(max(0, rect.left()), max(0, viewport_rect.width() - width))
        self.move(QtCore.QPoint(x, y))


class CodeEditor(QtWidgets.QPlainTextEdit):  # type: ignore[misc]
    text_changed = QtCore.Signal()
    cursor_changed = QtCore.Signal()
    request_completion = QtCore.Signal()
    run_requested = QtCore.Signal()

    def __init__(self, parent=None, *, enable_autocomplete: bool = False) -> None:
        super().__init__(parent)
        self._autocomplete_enabled = enable_autocomplete
        self._autocomplete_popup = (
            QtAutocompletePopup(self.viewport(), on_accept=self._accept_autocomplete_suggestion)
            if enable_autocomplete
            else None
        )
        self._autocomplete_suspended = False
        self._autocomplete_document_kind = "script"
        self._autocomplete_workspace_provider: Callable[[], list[dict[str, str]]] | None = None
        self._autocomplete_ignored_cursor_hides = 0
        self._diagnostics = []
        self._external_completions = []
        self._surface_bg = EDITOR_BG
        self._line_number_fg = "#b0b0b0"
        self._current_line_bg = "#404040"
        self.setTabChangesFocus(False)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.setCursorWidth(2)
        self.setFont(QtGui.QFont("Consolas", 11))
        self._configure_tab_stops()
        self._apply_surface_palette()
        self.setStyleSheet(
            f"""
            QPlainTextEdit {{
                selection-background-color: {SELECT_BG};
                selection-color: {TEXT_FG};
            }}
        """
        )
        self.highlighter = AetherSyntaxHighlighter(self.document())
        self._indent_guide_renderer = QtIndentGuideRenderer(self, indent_width=len(INDENTATION))
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.textChanged.connect(self.text_changed.emit)
        self.cursorPositionChanged.connect(self.cursor_changed.emit)
        self.cursorPositionChanged.connect(self.update_extra_selections)
        self.textChanged.connect(self.update_extra_selections)
        self.cursorPositionChanged.connect(self._update_indent_guides)
        self.textChanged.connect(self._update_indent_guides)
        if self._autocomplete_enabled:
            self.textChanged.connect(self._on_text_autocomplete_trigger)
            self.cursorPositionChanged.connect(self._on_cursor_autocomplete_trigger)
            self.updateRequest.connect(lambda _rect, _dy: self._reposition_autocomplete())
            self.verticalScrollBar().valueChanged.connect(lambda _value: self._reposition_autocomplete())
            self.horizontalScrollBar().valueChanged.connect(lambda _value: self._reposition_autocomplete())
        self.update_line_number_area_width(0)
        self.update_extra_selections()

    def native_widget(self) -> QtWidgets.QPlainTextEdit:
        return self

    def get_text(self) -> str:
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        self.setPlainText(text)

    def get_cursor_position(self) -> int:
        return self.textCursor().position()

    def set_cursor_position(self, pos: int) -> None:
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(int(pos), len(self.toPlainText()))))
        self.setTextCursor(cursor)

    def get_cursor_line_column(self) -> tuple[int, int]:
        cursor = self.textCursor()
        return cursor.blockNumber() + 1, cursor.positionInBlock()

    def go_to_line(self, line: int, column: int = 0) -> bool:
        block = self.document().findBlockByNumber(max(0, int(line) - 1))
        if not block.isValid():
            return False
        position = block.position() + max(0, min(int(column), max(0, block.length() - 1)))
        self.set_cursor_position(position)
        self.centerCursor()
        self.ensureCursorVisible()
        return True

    def has_selection(self) -> bool:
        return self.textCursor().hasSelection()

    def get_selected_text(self) -> str:
        return self.textCursor().selectedText().replace("\u2029", "\n")

    def get_selection_start_line(self) -> int | None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return None
        selection_start = min(cursor.selectionStart(), cursor.selectionEnd())
        return self.document().findBlock(selection_start).blockNumber() + 1

    def insert_text_at_cursor(self, text: str, cursor_offset: int = 0) -> None:
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.insertText(text)
        if cursor_offset:
            position = max(0, min(cursor.position() + int(cursor_offset), len(self.toPlainText())))
            cursor.setPosition(position)
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    def is_modified(self) -> bool:
        return self.document().isModified()

    def set_modified(self, value: bool) -> None:
        self.document().setModified(value)

    def connect_modification_changed(self, callback: Callable[[bool], None]) -> None:
        self.modificationChanged.connect(callback)

    def set_diagnostics(self, diagnostics) -> None:
        self._diagnostics = list(diagnostics or [])

    def clear_diagnostics(self) -> None:
        self._diagnostics = []

    def set_completions(self, completions) -> None:
        self._external_completions = list(completions or [])

    def focus_editor(self) -> None:
        self.setFocus()

    def _configure_tab_stops(self) -> None:
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * len(INDENTATION))

    def _apply_surface_palette(self) -> None:
        palette = self.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(self._surface_bg))
        palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(TEXT_FG))
        self.setPalette(palette)

    def set_surface_theme(
        self,
        *,
        background: str,
        line_number_color: str = "#b0b0b0",
        current_line_color: str = "#404040",
    ) -> None:
        self._surface_bg = background
        self._line_number_fg = line_number_color
        self._current_line_bg = current_line_color
        self._apply_surface_palette()
        self.line_number_area.update()
        self.update_extra_selections()
        self.viewport().update()

    def _update_indent_guides(self) -> None:
        self.viewport().update()

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        space = 10 + self.fontMetrics().horizontalAdvance("9") * digits
        return space

    def update_line_number_area_width(self, _new_block_count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QtCore.QRect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))
        self._reposition_autocomplete()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        self._indent_guide_renderer.paint(event)

    def line_number_area_paint_event(self, event) -> None:
        painter = QtGui.QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QtGui.QColor(self._surface_bg))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(QtGui.QColor(self._line_number_fg))
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    QtCore.Qt.AlignmentFlag.AlignRight,
                    number,
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self) -> None:
        self.update_extra_selections()

    def update_extra_selections(self) -> None:
        if self.isReadOnly():
            return
        selections = [self._current_line_selection()]
        selections.extend(self._occurrence_selections())
        selections.extend(self._bracket_match_selections())
        self.setExtraSelections(selections)

    def _current_line_selection(self):
        selection = QtWidgets.QTextEdit.ExtraSelection()
        line_color = QtGui.QColor(self._current_line_bg)
        line_color.setAlpha(80)
        selection.format.setBackground(line_color)  # type: ignore[attr-defined]
        selection.format.setProperty(QtGui.QTextFormat.Property.FullWidthSelection, True)  # type: ignore[attr-defined]
        selection.cursor = self.textCursor()  # type: ignore[attr-defined]
        selection.cursor.clearSelection()  # type: ignore[attr-defined]
        return selection

    def _bracket_match_selections(self) -> list:
        match = find_bracket_match(self.toPlainText(), self.textCursor().position())
        if match is None:
            return []

        color = BRACKET_MATCH_BG if match.is_valid else BRACKET_ERROR_BG
        positions = [match.anchor_pos]
        if match.match_pos is not None:
            positions.append(match.match_pos)
        return [self._single_character_selection(pos, color) for pos in positions]

    def _occurrence_selections(self) -> list:
        occurrences = find_occurrences(self.toPlainText(), self.textCursor().position())
        return [
            self._range_selection(occurrence.start, occurrence.end, OCCURRENCE_MATCH_BG, alpha=70)
            for occurrence in occurrences
        ]

    def _single_character_selection(self, pos: int, background: str):
        return self._range_selection(pos, pos + 1, background, foreground=BRACKET_MATCH_FG)

    def _range_selection(
        self,
        start: int,
        end: int,
        background: str,
        *,
        foreground: str | None = None,
        alpha: int | None = None,
    ):
        selection = QtWidgets.QTextEdit.ExtraSelection()
        color = QtGui.QColor(background)
        if alpha is not None:
            color.setAlpha(alpha)
        selection.format.setBackground(color)  # type: ignore[attr-defined]
        if foreground is not None:
            selection.format.setForeground(QtGui.QColor(foreground))  # type: ignore[attr-defined]
        cursor = self.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QtGui.QTextCursor.MoveMode.KeepAnchor)
        selection.cursor = cursor  # type: ignore[attr-defined]
        return selection

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        modifiers = event.modifiers()
        if self._autocomplete_enabled and self._key_event_may_edit_text(event):
            self._autocomplete_ignored_cursor_hides = max(self._autocomplete_ignored_cursor_hides, 2)
        if (
            self._autocomplete_enabled
            and key == QtCore.Qt.Key.Key_Space
            and modifiers & QtCore.Qt.KeyboardModifier.ControlModifier
        ):
            self._show_autocomplete_manually()
            return
        if self._autocomplete_enabled and self._handle_autocomplete_key(event):
            return
        if key in (QtCore.Qt.Key.Key_Tab, QtCore.Qt.Key.Key_Backtab):
            if key == QtCore.Qt.Key.Key_Tab and modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier:
                self._unindent_selection()
                return
            if key == QtCore.Qt.Key.Key_Backtab:
                self._unindent_selection()
                return
            self._indent_selection()
            return
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self._handle_return()
            self._hide_autocomplete()
            return
        if key == QtCore.Qt.Key.Key_Backspace:
            cursor = self.textCursor()
            if cursor.hasSelection():
                super().keyPressEvent(event)
                return
            if self._backspace_empty_pair(cursor):
                return
            if self._backspace_indentation(cursor):
                return
        if self._handle_auto_pair_key(event):
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self._on_cursor_autocomplete_trigger()

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self._hide_autocomplete()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._hide_autocomplete()
        super().hideEvent(event)

    def _backspace_indentation(self, cursor: QtGui.QTextCursor) -> bool:
        position_in_block = cursor.positionInBlock()
        block_text = cursor.block().text()
        if position_in_block == 0:
            return False
        if block_text[:position_in_block].endswith(INDENTATION):
            cursor.beginEditBlock()
            for _ in range(len(INDENTATION)):
                cursor.deletePreviousChar()
            cursor.endEditBlock()
            return True
        return False

    def _backspace_empty_pair(self, cursor: QtGui.QTextCursor) -> bool:
        if empty_pair_at(self.toPlainText(), cursor.position()) is None:
            return False

        cursor.beginEditBlock()
        cursor.deletePreviousChar()
        cursor.deleteChar()
        cursor.endEditBlock()
        return True

    def _handle_auto_pair_key(self, event) -> bool:
        text = event.text()
        if not text or len(text) != 1:
            return False

        modifiers = event.modifiers()
        blocked_modifiers = (
            QtCore.Qt.KeyboardModifier.ControlModifier
            | QtCore.Qt.KeyboardModifier.AltModifier
            | QtCore.Qt.KeyboardModifier.MetaModifier
        )
        if modifiers & blocked_modifiers:
            return False

        cursor = self.textCursor()
        if cursor.hasSelection():
            return False

        if should_skip_closing(self.toPlainText(), cursor.position(), text):
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.NextCharacter)
            self.setTextCursor(cursor)
            return True

        closing = closing_for_opening(text)
        if closing is None:
            return False

        cursor.beginEditBlock()
        cursor.insertText(f"{text}{closing}")
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.PreviousCharacter)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        return True

    def _handle_return(self) -> None:
        cursor = self.textCursor()
        block_text = cursor.block().text()
        position_in_block = cursor.positionInBlock()
        if not cursor.hasSelection():
            smart_enter = smart_enter_in_empty_braces(
                block_text,
                position_in_block,
                indent_unit=INDENTATION,
            )
            if smart_enter is not None:
                start = cursor.position()
                cursor.beginEditBlock()
                cursor.insertText(smart_enter.text)
                cursor.setPosition(start + smart_enter.cursor_offset)
                cursor.endEditBlock()
                self.setTextCursor(cursor)
                return

        leading_spaces = len(block_text) - len(block_text.lstrip(" "))
        current_indent = block_text[:leading_spaces]
        opens_block = self._line_opens_block(block_text)
        block_keyword = re.match(r"\s*(for|while|if|function|repeat)\b", block_text, re.IGNORECASE)
        at_line_end = position_in_block == len(block_text)
        should_expand_block = bool(opens_block and block_keyword and at_line_end)
        cursor.beginEditBlock()
        if should_expand_block:
            cursor.insertText(f"\n{current_indent}{INDENTATION}\n{current_indent}end")
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.PreviousBlock)
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.EndOfBlock)
        else:
            extra = INDENTATION if opens_block and at_line_end else ""
            cursor.insertText(f"\n{current_indent}{extra}")
        cursor.endEditBlock()
        if should_expand_block:
            self.setTextCursor(cursor)

    def _indent_selection(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            start = min(cursor.selectionStart(), cursor.selectionEnd())
            end = max(cursor.selectionStart(), cursor.selectionEnd())
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.StartOfBlock)
            while cursor.position() <= end:
                cursor.insertText(INDENTATION)
                end += len(INDENTATION)
                if not cursor.movePosition(QtGui.QTextCursor.MoveOperation.NextBlock):
                    break
            cursor.endEditBlock()
        else:
            cursor.insertText(INDENTATION)

    def _unindent_selection(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            start = min(cursor.selectionStart(), cursor.selectionEnd())
            end = max(cursor.selectionStart(), cursor.selectionEnd())
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.StartOfBlock)
            while cursor.position() <= end:
                block_text = cursor.block().text()
                if block_text.startswith(" "):
                    remove = min(len(block_text) - len(block_text.lstrip(" ")), len(INDENTATION))
                    for _ in range(remove):
                        cursor.deleteChar()
                    end -= remove
                if not cursor.movePosition(QtGui.QTextCursor.MoveOperation.NextBlock):
                    break
            cursor.endEditBlock()
        else:
            block_text = cursor.block().text()
            remove = min(len(block_text) - len(block_text.lstrip(" ")), len(INDENTATION))
            if remove:
                cursor.beginEditBlock()
                for _ in range(remove):
                    cursor.deletePreviousChar()
                cursor.endEditBlock()

    def _line_opens_block(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if stripped.endswith(":"):
            return True
        lowered = stripped.lower()
        starters = ("for", "if", "elif", "else", "while", "function", "repeat", "until")
        return any(lowered.startswith(f"{w} ") or lowered == w for w in starters)

    def _handle_autocomplete_key(self, event) -> bool:
        popup = self._autocomplete_popup
        if popup is None or not popup.is_visible():
            return False

        key = event.key()
        modifiers = event.modifiers()
        blocked_modifiers = (
            QtCore.Qt.KeyboardModifier.ControlModifier
            | QtCore.Qt.KeyboardModifier.AltModifier
            | QtCore.Qt.KeyboardModifier.MetaModifier
        )
        if modifiers & blocked_modifiers:
            return False

        if key == QtCore.Qt.Key.Key_Up:
            popup.move_selection(-1)
            return True
        if key == QtCore.Qt.Key.Key_Down:
            popup.move_selection(1)
            return True
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter, QtCore.Qt.Key.Key_Tab):
            suggestion = popup.current_suggestion()
            if suggestion is None:
                return False
            self._accept_autocomplete_and_maybe_expand_block(suggestion)
            return True
        if key == QtCore.Qt.Key.Key_Escape:
            self._hide_autocomplete()
            return True
        return False

    def _key_event_may_edit_text(self, event) -> bool:
        key = event.key()
        modifiers = event.modifiers()
        blocked_modifiers = (
            QtCore.Qt.KeyboardModifier.ControlModifier
            | QtCore.Qt.KeyboardModifier.AltModifier
            | QtCore.Qt.KeyboardModifier.MetaModifier
        )
        if modifiers & blocked_modifiers:
            return False
        if key in (
            QtCore.Qt.Key.Key_Backspace,
            QtCore.Qt.Key.Key_Delete,
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
            QtCore.Qt.Key.Key_Tab,
            QtCore.Qt.Key.Key_Backtab,
        ):
            return True
        return bool(event.text())

    def _on_cursor_autocomplete_trigger(self) -> None:
        if not self._autocomplete_enabled or self._autocomplete_suspended:
            return
        if self._autocomplete_ignored_cursor_hides > 0:
            self._autocomplete_ignored_cursor_hides -= 1
            return
        if self._autocomplete_popup is not None and self._autocomplete_popup.is_visible():
            self._hide_autocomplete()

    def _on_text_autocomplete_trigger(self) -> None:
        self._refresh_autocomplete(trigger="text")

    def _show_autocomplete_manually(self) -> None:
        self.request_completion.emit()
        self._refresh_autocomplete(trigger="manual")

    def _refresh_autocomplete(self, trigger: str = "text") -> None:
        if not self._autocomplete_enabled or self._autocomplete_suspended:
            return
        popup = self._autocomplete_popup
        if popup is None:
            return

        if trigger == "cursor" and not popup.is_visible():
            return

        context = self._current_autocomplete_context()
        if context is None:
            self._hide_autocomplete()
            return

        cursor = self.textCursor()
        workspace_items = self._autocomplete_workspace_provider() if self._autocomplete_workspace_provider else []
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text=cursor.block().text(),
                cursor_col=cursor.positionInBlock(),
                document_kind=self._autocomplete_document_kind,
                document_text=self.toPlainText()[: cursor.position()],
                workspace_items=workspace_items,
            )
        )
        if not suggestions:
            self._hide_autocomplete()
            return

        popup.show_suggestions(self, suggestions)

    def set_autocomplete_document_kind(self, document_kind: str) -> None:
        self._autocomplete_document_kind = "script"
        self.highlighter.set_document_kind(document_kind)

    def set_autocomplete_workspace_provider(
        self,
        provider: Callable[[], list[dict[str, str]]] | None,
    ) -> None:
        self._autocomplete_workspace_provider = provider

    def _reposition_autocomplete(self) -> None:
        popup = self._autocomplete_popup
        if popup is not None and popup.is_visible():
            popup.reposition(self)

    def _hide_autocomplete(self) -> None:
        popup = self._autocomplete_popup
        if popup is not None:
            popup.hide_popup()

    def _current_autocomplete_context(self) -> EditorAutocompleteContext | None:
        cursor = self.textCursor()
        block = cursor.block()
        if not block.isValid():
            return None

        token = detect_autocomplete_match(block.text(), cursor.positionInBlock())
        if token is None:
            return None

        return EditorAutocompleteContext(
            block_position=block.position(),
            token=token,
        )

    def _accept_autocomplete_suggestion(self, suggestion: CommandSuggestion) -> None:
        context = self._current_autocomplete_context()
        if context is None:
            self._hide_autocomplete()
            return

        cursor = self.textCursor()
        start = context.block_position + context.token.token_start_col
        end = context.block_position + context.token.token_end_col
        suffix_text = cursor.block().text()[context.token.token_end_col :]
        insert_text = suggestion.insert_text
        cursor_backtrack = suggestion.cursor_backtrack
        if insert_text.endswith("()") and suffix_text.lstrip().startswith("("):
            insert_text = suggestion.name
            cursor_backtrack = None
        if insert_text.endswith("<>") and suffix_text.lstrip().startswith("<"):
            insert_text = suggestion.name
            cursor_backtrack = None

        self._autocomplete_suspended = True
        try:
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.setPosition(end, QtGui.QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertText(insert_text)
            final_position = start + len(insert_text)
            if cursor_backtrack:
                final_position -= cursor_backtrack
            cursor.setPosition(final_position)
            if suggestion.cursor_selection_length:
                cursor.setPosition(
                    final_position + suggestion.cursor_selection_length,
                    QtGui.QTextCursor.MoveMode.KeepAnchor,
                )
            cursor.endEditBlock()
            self.setTextCursor(cursor)
        finally:
            self._autocomplete_suspended = False
            self._hide_autocomplete()

    def _accept_autocomplete_and_maybe_expand_block(self, suggestion: CommandSuggestion) -> None:
        self._accept_autocomplete_suggestion(suggestion)
        if suggestion.kind != "keyword":
            return
        block_text = self.textCursor().block().text()
        if self._line_opens_block(block_text):
            self._handle_return()
