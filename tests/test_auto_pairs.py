from __future__ import annotations

from PySide6 import QtCore, QtGui

from editor.auto_pairs import (
    closing_for_opening,
    empty_pair_at,
    should_skip_closing,
    smart_enter_in_empty_braces,
)
from qt_app import CodeEditor


def _press_text(editor: CodeEditor, text: str) -> None:
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        0,
        QtCore.Qt.KeyboardModifier.NoModifier,
        text,
    )
    editor.keyPressEvent(event)


def _press_key(editor: CodeEditor, key: QtCore.Qt.Key) -> None:
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        key,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    editor.keyPressEvent(event)


def _set_cursor(editor: CodeEditor, position: int) -> None:
    cursor = editor.textCursor()
    cursor.setPosition(position)
    editor.setTextCursor(cursor)


def test_auto_pair_helpers_cover_supported_pairs() -> None:
    assert closing_for_opening("(") == ")"
    assert closing_for_opening("[") == "]"
    assert closing_for_opening("{") == "}"
    assert closing_for_opening("<") == ">"
    assert closing_for_opening('"') == '"'
    assert closing_for_opening("'") == "'"


def test_empty_pair_and_skip_over_helpers() -> None:
    assert empty_pair_at("{ }", 1) is None
    assert empty_pair_at("{}", 1) == ("{", "}")
    assert empty_pair_at("<>", 1) == ("<", ">")
    assert should_skip_closing("print()", len("print("), ")")
    assert should_skip_closing("{}", 1, "}")
    assert should_skip_closing("<>", 1, ">")


def test_smart_enter_helper_indents_nested_empty_braces() -> None:
    insertion = smart_enter_in_empty_braces("    for (y in v) {}", len("    for (y in v) {"))

    assert insertion is not None
    assert insertion.text == "\n        \n    "
    assert insertion.cursor_offset == len("\n        ")


def test_typing_parenthesis_produces_pair_with_cursor_in_middle(qapp) -> None:
    editor = CodeEditor()

    _press_text(editor, "(")

    assert editor.toPlainText() == "()"
    assert editor.textCursor().position() == 1


def test_typing_brace_produces_pair_with_cursor_in_middle(qapp) -> None:
    editor = CodeEditor()

    _press_text(editor, "{")

    assert editor.toPlainText() == "{}"
    assert editor.textCursor().position() == 1


def test_typing_less_than_produces_pair_with_cursor_in_middle(qapp) -> None:
    editor = CodeEditor()

    _press_text(editor, "<")

    assert editor.toPlainText() == "<>"
    assert editor.textCursor().position() == 1


def test_skip_over_closing_parenthesis(qapp) -> None:
    editor = CodeEditor()
    editor.setPlainText("print()")
    _set_cursor(editor, len("print("))

    _press_text(editor, ")")

    assert editor.toPlainText() == "print()"
    assert editor.textCursor().position() == len("print()")


def test_skip_over_closing_brace(qapp) -> None:
    editor = CodeEditor()
    editor.setPlainText("{}")
    _set_cursor(editor, 1)

    _press_text(editor, "}")

    assert editor.toPlainText() == "{}"
    assert editor.textCursor().position() == 2


def test_skip_over_greater_than(qapp) -> None:
    editor = CodeEditor()
    editor.setPlainText("<>")
    _set_cursor(editor, 1)

    _press_text(editor, ">")

    assert editor.toPlainText() == "<>"
    assert editor.textCursor().position() == 2


def test_backspace_between_empty_braces_removes_both(qapp) -> None:
    editor = CodeEditor()
    editor.setPlainText("{}")
    _set_cursor(editor, 1)

    _press_key(editor, QtCore.Qt.Key.Key_Backspace)

    assert editor.toPlainText() == ""
    assert editor.textCursor().position() == 0


def test_enter_between_empty_braces_creates_indented_block(qapp) -> None:
    editor = CodeEditor()
    editor.setPlainText("for (x in v) {}")
    _set_cursor(editor, len("for (x in v) {"))

    _press_key(editor, QtCore.Qt.Key.Key_Return)

    assert editor.toPlainText() == "for (x in v) {\n    \n}"
    assert editor.textCursor().position() == len("for (x in v) {\n    ")


def test_enter_between_nested_empty_braces_preserves_current_indent(qapp) -> None:
    editor = CodeEditor()
    text = "if (x) {\n    for (y in v) {}\n}"
    editor.setPlainText(text)
    _set_cursor(editor, text.index("{}") + 1)

    _press_key(editor, QtCore.Qt.Key.Key_Return)

    assert editor.toPlainText() == "if (x) {\n    for (y in v) {\n        \n    }\n}"
    assert editor.textCursor().position() == len("if (x) {\n    for (y in v) {\n        ")
