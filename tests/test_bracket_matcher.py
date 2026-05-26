from __future__ import annotations

from PySide6 import QtGui

from editor.bracket_matcher import find_bracket_match
from qt_app import BRACKET_ERROR_BG, BRACKET_MATCH_BG, CodeEditor


def test_finds_simple_pair() -> None:
    match = find_bracket_match("(x)", 1)

    assert match is not None
    assert match.anchor_pos == 0
    assert match.match_pos == 2
    assert match.is_valid


def test_finds_angle_pair() -> None:
    text = "Matrix<double>"

    match = find_bracket_match(text, text.index("<") + 1)

    assert match is not None
    assert match.anchor_pos == text.index("<")
    assert match.match_pos == text.index(">")
    assert match.is_valid


def test_finds_nested_pair() -> None:
    text = "{ [ (x) ] }"

    inner = find_bracket_match(text, text.index("(") + 1)
    outer = find_bracket_match(text, text.index("}") + 1)

    assert inner is not None
    assert inner.anchor_pos == 4
    assert inner.match_pos == 6
    assert inner.is_valid
    assert outer is not None
    assert outer.anchor_pos == 10
    assert outer.match_pos == 0
    assert outer.is_valid


def test_detects_unmatched_bracket() -> None:
    match = find_bracket_match("(x", 1)

    assert match is not None
    assert match.anchor_pos == 0
    assert match.match_pos is None
    assert not match.is_valid


def test_detects_crossed_nested_brackets_as_unmatched() -> None:
    match = find_bracket_match("([)]", 1)

    assert match is not None
    assert match.anchor_pos == 0
    assert match.match_pos is None
    assert not match.is_valid


def test_matches_from_cursor_before_and_after_bracket() -> None:
    text = "(x)"

    before_open = find_bracket_match(text, 0)
    after_close = find_bracket_match(text, 3)

    assert before_open is not None
    assert before_open.anchor_pos == 0
    assert before_open.match_pos == 2
    assert after_close is not None
    assert after_close.anchor_pos == 2
    assert after_close.match_pos == 0


def _selection_ranges(editor: CodeEditor) -> list[tuple[int, int]]:
    ranges = []
    for selection in editor.extraSelections():
        cursor = selection.cursor
        ranges.append((cursor.selectionStart(), cursor.selectionEnd()))
    return ranges


def _selection_backgrounds(editor: CodeEditor) -> list[str]:
    return [selection.format.background().color().name() for selection in editor.extraSelections()]


def _has_current_line_selection(editor: CodeEditor) -> bool:
    return any(
        not selection.cursor.hasSelection()
        and bool(selection.format.property(QtGui.QTextFormat.Property.FullWidthSelection))
        for selection in editor.extraSelections()
    )


def test_qt_extra_selections_keep_current_line_and_matching_brackets(qapp) -> None:
    editor = CodeEditor()
    editor.setPlainText("(x)")
    cursor = editor.textCursor()
    cursor.setPosition(1)
    editor.setTextCursor(cursor)
    qapp.processEvents()

    assert _has_current_line_selection(editor)
    assert (0, 1) in _selection_ranges(editor)
    assert (2, 3) in _selection_ranges(editor)
    assert BRACKET_MATCH_BG.lower() in _selection_backgrounds(editor)

    editor.close()


def test_qt_extra_selection_marks_unmatched_bracket_without_losing_current_line(qapp) -> None:
    editor = CodeEditor()
    editor.setPlainText("(x")
    cursor = editor.textCursor()
    cursor.setPosition(1)
    editor.setTextCursor(cursor)
    qapp.processEvents()

    assert _has_current_line_selection(editor)
    assert (0, 1) in _selection_ranges(editor)
    assert BRACKET_ERROR_BG.lower() in _selection_backgrounds(editor)

    editor.close()
