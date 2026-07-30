from __future__ import annotations

from qt_app import CodeEditor, PUNCT_COLOR, STRING_COLOR


def _block_format_colors(editor: CodeEditor, block_number: int) -> list[tuple[int, int, str]]:
    block = editor.document().findBlockByNumber(block_number)
    layout = block.layout()
    return [
        (fmt.start, fmt.length, fmt.format.foreground().color().name())
        for fmt in layout.formats()
    ]


def _has_color_at(editor: CodeEditor, block_number: int, start: int, length: int, color: str) -> bool:
    for fmt_start, fmt_length, fmt_color in _block_format_colors(editor, block_number):
        if fmt_color != color:
            continue
        fmt_end = fmt_start + fmt_length
        target_end = start + length
        if fmt_start <= start and target_end <= fmt_end:
            return True
    return False


def test_script_keywords_are_highlighted_but_not_inside_comments(qapp) -> None:
    editor = CodeEditor()
    editor.set_autocomplete_document_kind("script")
    editor.setPlainText("if x\n# if comment\n")
    qapp.processEvents()

    assert _has_color_at(editor, 0, 0, 2, "#a30101")
    assert not _has_color_at(editor, 1, 2, 2, "#a30101")

    editor.close()


def test_exception_keywords_are_highlighted(qapp) -> None:
    editor = CodeEditor()
    editor.set_autocomplete_document_kind("script")
    editor.setPlainText("try { throw error; } catch (Error error) { throw; }\n")
    qapp.processEvents()

    assert _has_color_at(editor, 0, 0, 3, "#a30101")
    assert _has_color_at(editor, 0, 6, 5, "#a30101")
    assert _has_color_at(editor, 0, 21, 5, "#a30101")
    assert _has_color_at(editor, 0, 28, 5, "#a30101")
    assert _has_color_at(editor, 0, 43, 5, "#a30101")

    editor.close()


def test_enum_keyword_is_highlighted(qapp) -> None:
    editor = CodeEditor()
    editor.set_autocomplete_document_kind("script")
    editor.setPlainText("public enum SolverStatus { Converged }\n")
    qapp.processEvents()

    assert _has_color_at(editor, 0, 0, 6, "#a30101")
    assert _has_color_at(editor, 0, 7, 4, "#a30101")

    editor.close()


def test_aether_types_are_highlighted_like_keywords(qapp) -> None:
    editor = CodeEditor()
    editor.set_autocomplete_document_kind("script")
    editor.setPlainText("int i = 0;\ndouble x = 1.0;\nMatrix<double> A = [];\n")
    qapp.processEvents()

    assert _has_color_at(editor, 0, 0, 3, "#a30101")
    assert _has_color_at(editor, 1, 0, 6, "#a30101")
    assert _has_color_at(editor, 2, 0, 6, "#a30101")
    assert _has_color_at(editor, 2, 7, 6, "#a30101")

    editor.close()


def test_editor_cursor_is_wider_for_visibility(qapp) -> None:
    editor = CodeEditor()

    assert editor.cursorWidth() == 2

    editor.close()


def test_import_statement_highlights_keyword_and_module_name(qapp) -> None:
    editor = CodeEditor()
    editor.set_autocomplete_document_kind("script")
    editor.setPlainText("import metodo\n")
    qapp.processEvents()

    assert _has_color_at(editor, 0, 0, 6, "#cc7832")
    assert _has_color_at(editor, 0, 7, 6, "#ce9178")

    editor.close()


def test_from_import_statement_highlights_dotted_module_and_imported_names(qapp) -> None:
    editor = CodeEditor()
    editor.set_autocomplete_document_kind("script")
    editor.setPlainText("from metodos.newton import blas, otraFuncion\n")
    qapp.processEvents()

    assert _has_color_at(editor, 0, 0, 4, "#cc7832")
    assert _has_color_at(editor, 0, 5, 14, "#ce9178")
    assert _has_color_at(editor, 0, 20, 6, "#cc7832")
    assert _has_color_at(editor, 0, 27, 4, "#9cdcfe")
    assert _has_color_at(editor, 0, 33, 11, "#9cdcfe")

    editor.close()


def test_punctuation_is_visible_in_aether_scripts(qapp) -> None:
    assert PUNCT_COLOR != STRING_COLOR

    script_editor = CodeEditor()
    script_editor.set_autocomplete_document_kind("script")
    script_editor.setPlainText("A = [1, (2 + 3); {4, 5}] \\ b % 2\n")
    qapp.processEvents()

    punctuation_positions = (2, 4, 6, 8, 11, 14, 15, 17, 19, 22, 23, 25, 29)
    for position in punctuation_positions:
        assert _has_color_at(script_editor, 0, position, 1, PUNCT_COLOR)

    script_editor.close()
