from __future__ import annotations

import pytest
from PySide6 import QtGui  # type: ignore

from ui.code_editor import CodeEditor
from ui.editor_api import EditorAPI
from ui.editor_factory import create_editor


@pytest.fixture
def editor(qapp):
    widget = CodeEditor()
    yield widget
    widget.close()


def _select_range(editor: CodeEditor, start: int, end: int) -> None:
    cursor = editor.native_widget().textCursor()
    cursor.setPosition(start)
    cursor.setPosition(end, QtGui.QTextCursor.MoveMode.KeepAnchor)
    editor.native_widget().setTextCursor(cursor)


def test_set_text_get_text_and_text_changed_signal(editor: CodeEditor, qapp) -> None:
    changes = 0

    def mark_changed() -> None:
        nonlocal changes
        changes += 1

    editor.text_changed.connect(mark_changed)
    editor.set_text("alpha\nbeta\n")
    qapp.processEvents()

    assert editor.get_text() == "alpha\nbeta\n"
    assert changes >= 1


def test_cursor_position_and_line_column_contract(editor: CodeEditor, qapp) -> None:
    cursor_changes = 0

    def mark_cursor_changed() -> None:
        nonlocal cursor_changes
        cursor_changes += 1

    editor.cursor_changed.connect(mark_cursor_changed)
    editor.set_text("alpha\nbeta\n")

    assert editor.go_to_line(2, 2)
    qapp.processEvents()
    assert editor.get_cursor_position() == len("alpha\nbe")
    assert editor.get_cursor_line_column() == (2, 2)
    assert cursor_changes >= 1

    editor.set_cursor_position(1)
    assert editor.get_cursor_position() == 1
    assert editor.get_cursor_line_column() == (1, 1)


def test_selection_contract_uses_normalized_newlines(editor: CodeEditor) -> None:
    editor.set_text("alpha\nbeta\ngamma\n")
    _select_range(editor, len("alpha\nbe"), len("alpha\nbeta\nga"))

    assert editor.has_selection()
    assert editor.get_selected_text() == "ta\nga"
    assert editor.get_selection_start_line() == 2


def test_empty_selection_contract(editor: CodeEditor) -> None:
    editor.set_text("alpha\n")
    editor.set_cursor_position(0)

    assert not editor.has_selection()
    assert editor.get_selected_text() == ""
    assert editor.get_selection_start_line() is None


def test_insert_text_at_cursor_repositions_by_offset(editor: CodeEditor) -> None:
    editor.set_text("alpha\nbeta\n")
    assert editor.go_to_line(2)

    editor.insert_text_at_cursor("XY", cursor_offset=-1)

    assert editor.get_text() == "alpha\nXYbeta\n"
    assert editor.get_cursor_position() == len("alpha\nX")
    assert editor.get_cursor_line_column() == (2, 1)


def test_modified_state_contract(editor: CodeEditor) -> None:
    editor.set_text("alpha")
    editor.set_modified(False)

    assert not editor.is_modified()

    editor.insert_text_at_cursor(" beta")

    assert editor.is_modified()
    editor.set_modified(False)
    assert not editor.is_modified()


def test_modification_changed_callback_contract(editor: CodeEditor, qapp) -> None:
    changes: list[bool] = []
    editor.connect_modification_changed(changes.append)

    editor.set_text("alpha")
    editor.set_modified(False)
    editor.insert_text_at_cursor(" beta")
    qapp.processEvents()

    assert changes[-1] is True


def test_native_widget_remains_available_as_escape_hatch(editor: CodeEditor) -> None:
    assert editor.native_widget() is editor


@pytest.mark.parametrize("kind", ["qt_plain", "experimental"])
def test_create_editor_kinds_return_basic_editor_api(kind: str, qapp) -> None:
    editor: EditorAPI = create_editor(kind)
    try:
        editor.set_text(f"{kind}\nbody\n")
        assert editor.get_text() == f"{kind}\nbody\n"
        assert editor.go_to_line(2, 1)
        assert editor.get_cursor_line_column() == (2, 1)
        editor.insert_text_at_cursor("X")
        assert editor.get_text() == f"{kind}\nbXody\n"
    finally:
        editor.native_widget().close()


def test_create_editor_unknown_kind_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="Unknown editor kind 'missing'.*qt_plain.*experimental"):
        create_editor("missing")
