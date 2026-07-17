from __future__ import annotations

import pytest
from PySide6 import QtCore, QtGui

from qt_app import CodeEditor


@pytest.fixture()
def editor(qapp):
    widget = CodeEditor(enable_autocomplete=True)
    widget.set_autocomplete_document_kind("script")
    widget.set_autocomplete_workspace_provider(lambda: [])
    widget.resize(640, 320)
    widget.show()
    widget.setFocus()
    qapp.processEvents()
    yield widget
    widget.close()
    qapp.processEvents()


def _press_key(editor: CodeEditor, key: QtCore.Qt.Key) -> None:
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        key,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    editor.keyPressEvent(event)


def _press_text(editor: CodeEditor, text: str) -> None:
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        0,
        QtCore.Qt.KeyboardModifier.NoModifier,
        text,
    )
    editor.keyPressEvent(event)


def _show_completion_for_text(editor: CodeEditor, qapp, text: str) -> None:
    editor.setPlainText(text)
    qapp.processEvents()
    editor._hide_autocomplete()
    cursor = editor.textCursor()
    cursor.setPosition(len(text))
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()


def test_moving_cursor_to_complete_word_does_not_open_popup_automatically(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("function y = demo(x)")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(0)
    editor.setTextCursor(cursor)
    qapp.processEvents()

    cursor.setPosition(len("function"))
    editor.setTextCursor(cursor)
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    assert editor._autocomplete_popup.is_visible() is False
    assert editor._autocomplete_popup.current_suggestion() is None


def test_editing_existing_word_can_open_popup_again(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("function")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len("function"))
    editor.setTextCursor(cursor)
    qapp.processEvents()

    cursor = editor.textCursor()
    cursor.deletePreviousChar()
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    current = editor._autocomplete_popup.current_suggestion()
    assert current is not None
    assert current.name == "function"


def test_manual_autocomplete_invocation_still_works_on_complete_word(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("function")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len("function"))
    editor.setTextCursor(cursor)
    qapp.processEvents()

    editor._show_autocomplete_manually()
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    current = editor._autocomplete_popup.current_suggestion()
    assert current is not None
    assert current.name == "function"


def test_normal_writing_still_opens_popup_for_partial_tokens(editor: CodeEditor, qapp) -> None:
    editor.setPlainText(r"\pl")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len(r"\pl"))
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    current = editor._autocomplete_popup.current_suggestion()
    assert current is not None
    assert current.name == r"\plot()"


def test_popup_is_child_of_editor_viewport_and_opens_below_cursor(editor: CodeEditor, qapp) -> None:
    editor.setPlainText(r"\pl")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len(r"\pl"))
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()

    popup = editor._autocomplete_popup
    assert popup is not None
    assert popup.is_visible() is True
    assert popup.parentWidget() is editor.viewport()
    assert popup.isWindow() is False

    popup_rect = popup.geometry()
    viewport_rect = editor.viewport().rect()
    assert viewport_rect.contains(popup_rect)
    assert popup_rect.top() >= editor.cursorRect().bottom()


def test_editor_suggests_document_symbols_without_runtime_state(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("A = [1,2;3,4]\nA")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len("A = [1,2;3,4]\nA"))
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    current = editor._autocomplete_popup.current_suggestion()
    assert current is not None
    assert current.name == "A"
    assert current.source == "document"


def test_editor_ignores_document_symbols_defined_after_the_cursor(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("la\nlaterValue = 1")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len("la"))
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    assert editor._autocomplete_popup.is_visible() is False
    assert editor._autocomplete_popup.current_suggestion() is None


def test_enter_on_keyword_autocomplete_expands_block_immediately(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("for")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len("for"))
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    current = editor._autocomplete_popup.current_suggestion()
    assert current is not None
    assert current.name == "for"
    assert current.kind == "snippet"

    editor._accept_autocomplete_and_maybe_expand_block(current)
    qapp.processEvents()

    assert editor.toPlainText() == "for (x in iterable) {\n    \n}"
    cursor = editor.textCursor()
    assert cursor.blockNumber() == 0
    assert cursor.selectionStart() == len("for (")
    assert cursor.selectionEnd() == len("for (x")


@pytest.mark.parametrize(
    ("prefix", "key", "expected_text", "selection_start", "selection_end"),
    [
        ("fn", QtCore.Qt.Key.Key_Tab, "f(x) = expression;", len("f(x) = "), len("f(x) = expression")),
        ("for", QtCore.Qt.Key.Key_Return, "for (x in iterable) {\n    \n}", len("for ("), len("for (x")),
        ("if", QtCore.Qt.Key.Key_Tab, "if (condition) {\n    \n}", len("if ("), len("if (condition")),
        (
            "while",
            QtCore.Qt.Key.Key_Return,
            "while (condition) {\n    \n}",
            len("while ("),
            len("while (condition"),
        ),
        ("func", QtCore.Qt.Key.Key_Tab, "int name() {\n    \n}", len("int "), len("int name")),
    ],
)
def test_aether_snippets_accept_with_tab_or_enter_and_place_cursor(
    editor: CodeEditor,
    qapp,
    prefix: str,
    key: QtCore.Qt.Key,
    expected_text: str,
    selection_start: int,
    selection_end: int,
) -> None:
    _show_completion_for_text(editor, qapp, prefix)

    assert editor._autocomplete_popup is not None
    current = editor._autocomplete_popup.current_suggestion()
    assert current is not None
    assert current.name == prefix
    assert current.kind == "snippet"

    _press_key(editor, key)
    qapp.processEvents()

    assert editor.toPlainText() == expected_text
    cursor = editor.textCursor()
    assert cursor.selectionStart() == selection_start
    assert cursor.selectionEnd() == selection_end


def test_ife_snippet_inserts_else_branch(editor: CodeEditor, qapp) -> None:
    _show_completion_for_text(editor, qapp, "ife")

    _press_key(editor, QtCore.Qt.Key.Key_Return)
    qapp.processEvents()

    assert editor.toPlainText() == "if (condition) {\n    \n} else {\n    \n}"
    assert editor.textCursor().selectedText() == "condition"


@pytest.mark.parametrize(("prefix", "expected_text"), [("Mat", "Matrix<>"), ("Vec", "Vector<>")])
def test_type_autocomplete_inserts_angle_pair_with_cursor_inside(
    editor: CodeEditor,
    qapp,
    prefix: str,
    expected_text: str,
) -> None:
    _show_completion_for_text(editor, qapp, prefix)

    _press_key(editor, QtCore.Qt.Key.Key_Tab)
    qapp.processEvents()

    assert editor.toPlainText() == expected_text
    assert editor.textCursor().position() == len(expected_text) - 1


def test_type_autocomplete_does_not_duplicate_existing_angle_pair(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("Matrix<double>")
    qapp.processEvents()
    editor._hide_autocomplete()
    cursor = editor.textCursor()
    cursor.setPosition(len("Matrix"))
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._show_autocomplete_manually()
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    current = editor._autocomplete_popup.current_suggestion()
    assert current is not None
    assert current.name == "Matrix"

    _press_key(editor, QtCore.Qt.Key.Key_Tab)
    qapp.processEvents()

    assert editor.toPlainText() == "Matrix<double>"
    assert editor.textCursor().position() == len("Matrix")


def test_snippet_acceptance_keeps_auto_pairs_working(editor: CodeEditor, qapp) -> None:
    _show_completion_for_text(editor, qapp, "fn")
    _press_key(editor, QtCore.Qt.Key.Key_Tab)
    qapp.processEvents()

    cursor = editor.textCursor()
    cursor.clearSelection()
    cursor.setPosition(len(editor.toPlainText()))
    editor.setTextCursor(cursor)
    _press_text(editor, "(")
    qapp.processEvents()

    assert editor.toPlainText() == "f(x) = expression;()"
    assert editor.textCursor().position() == len("f(x) = expression;(")


def test_enter_before_existing_for_line_does_not_expand_block(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("for i = 1:3")
    qapp.processEvents()

    cursor = editor.textCursor()
    cursor.setPosition(0)
    editor.setTextCursor(cursor)
    qapp.processEvents()

    editor._handle_return()
    qapp.processEvents()

    assert editor.toPlainText() == "\nfor i = 1:3"
