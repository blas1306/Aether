from __future__ import annotations

from PySide6 import QtGui

from editor.occurrence_highlighter import find_occurrences, identifier_at
from qt_app import BRACKET_MATCH_BG, OCCURRENCE_MATCH_BG, CodeEditor


def _ranges(text: str, cursor_pos: int) -> list[tuple[int, int]]:
    return [(occurrence.start, occurrence.end) for occurrence in find_occurrences(text, cursor_pos)]


def test_i_in_for_highlights_exact_occurrences() -> None:
    text = "for i = 1:3\n    suma = suma + i\nend\n"

    assert _ranges(text, text.index("i")) == [(4, 5), (30, 31)]


def test_i_does_not_highlight_substrings() -> None:
    text = "int = 1\nprint(i)\nmatrix = i\n"

    assert _ranges(text, text.index("i)")) == [(14, 15), (26, 27)]


def test_suma_highlights_assignment_and_uses() -> None:
    text = "suma = 0\nsuma = suma + 1\n"

    assert _ranges(text, 1) == [(0, 4), (9, 13), (16, 20)]


def test_identifier_at_detects_cursor_in_middle_of_resultado2() -> None:
    text = "resultado2 = resultado2 + 1\n"

    assert identifier_at(text, text.index("tado")) == ("resultado2", 0, 10)


def test_cursor_at_end_of_identifier_does_not_highlight_while_typing() -> None:
    text = "suma = suma + 1\n"

    assert find_occurrences(text, 4) == []


def test_cursor_outside_identifier_returns_no_occurrences() -> None:
    assert find_occurrences("suma = 1\n", 5) == []


def test_keywords_do_not_highlight() -> None:
    text = "int x\nif x\nfor i\nwhile x\ndouble y\n"

    assert find_occurrences(text, text.index("int")) == []
    assert find_occurrences(text, text.index("if")) == []
    assert find_occurrences(text, text.index("for")) == []
    assert find_occurrences(text, text.index("while")) == []
    assert find_occurrences(text, text.index("double")) == []


def test_and_or_do_not_highlight_as_keywords() -> None:
    text = "and x\nor y\n"

    assert find_occurrences(text, text.index("and")) == []
    assert find_occurrences(text, text.index("or")) == []


def test_backslash_command_occurrences_are_supported() -> None:
    text = "\\alpha = \\alpha + beta\n"

    assert _ranges(text, 3) == [(0, 6), (9, 15)]


def _selection_ranges(editor: CodeEditor) -> list[tuple[int, int]]:
    return [
        (selection.cursor.selectionStart(), selection.cursor.selectionEnd())
        for selection in editor.extraSelections()
    ]


def _selection_backgrounds(editor: CodeEditor) -> list[str]:
    return [selection.format.background().color().name() for selection in editor.extraSelections()]


def _has_current_line_selection(editor: CodeEditor) -> bool:
    return any(
        not selection.cursor.hasSelection()
        and bool(selection.format.property(QtGui.QTextFormat.Property.FullWidthSelection))
        for selection in editor.extraSelections()
    )


def test_qt_extra_selections_keep_line_brackets_and_occurrences(qapp) -> None:
    editor = CodeEditor()
    editor.setPlainText("(suma + suma)\n")
    cursor = editor.textCursor()
    cursor.setPosition(1)
    editor.setTextCursor(cursor)
    qapp.processEvents()

    ranges = _selection_ranges(editor)
    backgrounds = _selection_backgrounds(editor)
    assert _has_current_line_selection(editor)
    assert (1, 5) in ranges
    assert (8, 12) in ranges
    assert (0, 1) in ranges
    assert (12, 13) in ranges
    assert OCCURRENCE_MATCH_BG.lower() in backgrounds
    assert BRACKET_MATCH_BG.lower() in backgrounds

    editor.close()
