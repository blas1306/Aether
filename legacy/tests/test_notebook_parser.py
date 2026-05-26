from __future__ import annotations

from notebook_parser import parse_notebook_source


def test_parse_latex_only_document_as_single_latex_block() -> None:
    document = parse_notebook_source("Uno\nDos\n")

    assert len(document.blocks) == 1
    block = document.blocks[0]
    assert block.kind == "latex"
    assert block.language is None
    assert block.source == "Uno\nDos\n"
    assert block.start_line == 1
    assert block.end_line == 2


def test_parse_latex_code_latex_document() -> None:
    source = (
        "Antes\n"
        "\\begin{code}\n"
        "a = 1;\n"
        "\\end{code}\n"
        "Despues\n"
    )

    document = parse_notebook_source(source)

    assert [block.kind for block in document.blocks] == ["latex", "code", "latex"]
    assert document.blocks[0].source == "Antes\n"
    assert document.blocks[1].source == "a = 1;\n"
    assert document.blocks[2].source == "Despues\n"


def test_begin_code_uses_default_language() -> None:
    document = parse_notebook_source('\\begin{code}\nprintln("hola");\n\\end{code}\n')

    assert document.blocks[0].language == "Aether"


def test_begin_code_can_still_use_mathlab_when_default_is_legacy() -> None:
    document = parse_notebook_source("\\begin{code}\na = 1;\n\\end{code}\n", default_language="MathLab")

    assert document.blocks[0].language == "MathLab"


def test_begin_mathlab_uses_mathlab_language() -> None:
    document = parse_notebook_source("\\begin{MathLab}\na = 1;\n\\end{MathLab}\n")

    assert document.blocks[0].language == "MathLab"


def test_preserves_one_based_start_and_end_lines() -> None:
    source = (
        "L1\n"
        "L2\n"
        "\\begin{code}\n"
        "a = 1;\n"
        "b = 2;\n"
        "\\end{code}\n"
        "L7\n"
    )

    document = parse_notebook_source(source)

    assert document.blocks[0].start_line == 1
    assert document.blocks[0].end_line == 2
    assert document.blocks[1].start_line == 4
    assert document.blocks[1].end_line == 5
    assert document.blocks[2].start_line == 7
    assert document.blocks[2].end_line == 7


def test_handles_multiple_code_blocks() -> None:
    source = (
        "\\begin{code}\n"
        "a = 1;\n"
        "\\end{code}\n"
        "Entre\n"
        "\\begin{MathLab}\n"
        "b = a + 1;\n"
        "\\end{MathLab}\n"
    )

    document = parse_notebook_source(source)

    assert [block.kind for block in document.blocks] == ["code", "latex", "code"]
    assert document.blocks[0].source == "a = 1;\n"
    assert document.blocks[1].source == "Entre\n"
    assert document.blocks[2].source == "b = a + 1;\n"


def test_unclosed_code_block_returns_error_block() -> None:
    document = parse_notebook_source("Intro\n\\begin{code}\na = 1;\n")

    block = document.blocks[-1]
    assert block.kind == "code"
    assert block.status == "error"
    assert block.source == "a = 1;\n"
    assert block.outputs[0].kind == "error"
    assert "Missing \\end{code}" in block.outputs[0].text


def test_latex_with_normal_commands_is_not_modified() -> None:
    source = (
        "\\begin{document}\n"
        "\\section{Normal}\n"
        "\\begin{equation}\n"
        "x^2 + 1\n"
        "\\end{equation}\n"
        "\\end{document}\n"
    )

    document = parse_notebook_source(source)

    assert len(document.blocks) == 1
    assert document.blocks[0].kind == "latex"
    assert document.blocks[0].source == source
