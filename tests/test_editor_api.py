from __future__ import annotations

from PySide6 import QtGui  # type: ignore

from ui.code_editor import CodeEditor


def test_code_editor_exposes_editor_api_contract(qapp) -> None:
    editor = CodeEditor()
    text_changed_count = 0
    cursor_changed_count = 0
    completion_requested = 0

    def mark_text_changed() -> None:
        nonlocal text_changed_count
        text_changed_count += 1

    def mark_cursor_changed() -> None:
        nonlocal cursor_changed_count
        cursor_changed_count += 1

    def mark_completion_requested() -> None:
        nonlocal completion_requested
        completion_requested += 1

    editor.text_changed.connect(mark_text_changed)
    editor.cursor_changed.connect(mark_cursor_changed)
    editor.request_completion.connect(mark_completion_requested)

    editor.set_text("alpha\nbeta\n")
    qapp.processEvents()

    assert editor.get_text() == "alpha\nbeta\n"
    assert editor.native_widget() is editor
    assert text_changed_count >= 1

    assert editor.go_to_line(2, 2)
    qapp.processEvents()
    assert editor.get_cursor_position() == len("alpha\nbe")
    assert editor.get_cursor_line_column() == (2, 2)
    assert cursor_changed_count >= 1

    editor.set_cursor_position(1)
    assert editor.get_cursor_position() == 1

    editor.go_to_line(2)
    editor.insert_text_at_cursor("XY", cursor_offset=-1)
    assert editor.get_text() == "alpha\nXYbeta\n"
    assert editor.get_cursor_position() == len("alpha\nX")

    cursor = editor.native_widget().textCursor()
    cursor.setPosition(0)
    cursor.setPosition(len("alpha"), QtGui.QTextCursor.MoveMode.KeepAnchor)
    editor.native_widget().setTextCursor(cursor)
    assert editor.has_selection()
    assert editor.get_selected_text() == "alpha"
    assert editor.get_selection_start_line() == 1

    modification_changes: list[bool] = []
    editor.connect_modification_changed(modification_changes.append)
    editor.set_modified(False)
    assert not editor.is_modified()
    editor.set_modified(True)
    qapp.processEvents()
    assert editor.is_modified()
    assert modification_changes[-1] is True

    editor.set_diagnostics([{"line": 1, "message": "example"}])
    editor.clear_diagnostics()
    editor.set_completions(["alpha", "beta"])
    editor.focus_editor()
    editor.request_completion.emit()

    assert completion_requested == 1

    editor.close()
