from __future__ import annotations

from editor.indent_guides import (
    IndentGuide,
    active_guide_column,
    calculate_indent_guides,
    guide_columns_for_line,
    visual_indent_width,
)
from qt_app import CodeEditor


def test_visual_indent_width_expands_tabs_to_tab_stops() -> None:
    assert visual_indent_width("\tfoo", tab_size=4) == 4
    assert visual_indent_width("  \tfoo", tab_size=4) == 4
    assert visual_indent_width("\t  foo", tab_size=4) == 6


def test_guide_columns_follow_visual_indentation() -> None:
    assert guide_columns_for_line("    if (x) {", indent_width=4, tab_size=4) == (0,)
    assert guide_columns_for_line("\t    println(x)", indent_width=4, tab_size=4) == (0, 4)


def test_closing_only_line_uses_its_real_indent() -> None:
    assert guide_columns_for_line("    }", indent_width=4, tab_size=4) == (0,)
    assert guide_columns_for_line("end", indent_width=4, tab_size=4) == ()


def test_calculate_indent_guides_builds_contiguous_ranges_and_active_guide() -> None:
    lines = [
        "function test() {",
        "    if (x > 0) {",
        "        while (y > 0) {",
        "            println(y);",
        "        }",
        "    }",
        "}",
    ]

    guides = calculate_indent_guides(lines, cursor_block=3, indent_width=4, tab_size=4)

    assert IndentGuide(column=0, start_block=1, end_block=5, active=False) in guides
    assert IndentGuide(column=4, start_block=2, end_block=4, active=False) in guides
    assert IndentGuide(column=8, start_block=3, end_block=3, active=True) in guides
    assert active_guide_column(lines, 3, indent_width=4, tab_size=4) == 8


def test_blank_lines_inherit_surrounding_indent_for_stability() -> None:
    lines = [
        "if (x) {",
        "    println(x)",
        "",
        "    println(x + 1)",
        "}",
    ]

    guides = calculate_indent_guides(lines, cursor_block=2, indent_width=4, tab_size=4)

    assert IndentGuide(column=0, start_block=1, end_block=3, active=True) in guides


def test_qt_editor_indent_guides_paint_stability(qapp) -> None:
    editor = CodeEditor()
    editor.setPlainText("function test() {\n    if (x) {\n        println(x)\n    }\n}\n")
    editor.resize(420, 220)
    editor.show()
    qapp.processEvents()

    image = editor.viewport().grab().toImage()

    assert not image.isNull()
    editor.close()
