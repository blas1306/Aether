from __future__ import annotations

import json
from pathlib import Path

import pytest

from notebook_file import (
    export_notebook_to_mtex,
    load_notebook_file,
    make_notebook_block,
    new_notebook_document,
    save_notebook_file,
)
from notebook_parser import parse_notebook_source


def test_new_notebook_document_defaults_to_aether() -> None:
    document = new_notebook_document()

    assert document.path is None
    assert document.default_language == "Aether"
    assert document.blocks == []


def test_save_and_load_mtn_preserves_text_and_code_blocks(tmp_path: Path) -> None:
    document = new_notebook_document()
    document.blocks.append(make_notebook_block("text", "Intro LaTeX\n"))
    document.blocks.append(make_notebook_block("code", "a = 1;\n", "MathLab"))
    path = tmp_path / "demo.mtn"

    save_notebook_file(document, path)
    loaded = load_notebook_file(path)

    assert loaded.path == path
    assert loaded.default_language == "Aether"
    assert [block.kind for block in loaded.blocks] == ["text", "code"]
    assert [block.source for block in loaded.blocks] == ["Intro LaTeX\n", "a = 1;\n"]
    assert loaded.blocks[1].language == "MathLab"


def test_save_mtn_uses_versioned_json_format(tmp_path: Path) -> None:
    document = new_notebook_document()
    document.blocks.append(make_notebook_block("text", "Hello"))
    path = tmp_path / "versioned.mtn"

    save_notebook_file(document, path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["type"] == "mathtex-notebook"
    assert payload["version"] == 1
    assert payload["blocks"][0]["kind"] == "text"


def test_export_notebook_to_mtex_uses_latex_text_and_code_environments() -> None:
    document = new_notebook_document()
    document.blocks.append(make_notebook_block("text", "\\section{Intro}\n"))
    document.blocks.append(make_notebook_block("code", 'println("hola");', "Aether"))

    assert export_notebook_to_mtex(document) == '\\section{Intro}\n\\begin{code}\nprintln("hola");\n\\end{code}\n'


def test_export_notebook_to_mtex_preserves_explicit_mathlab_legacy_blocks() -> None:
    document = new_notebook_document()
    document.blocks.append(make_notebook_block("code", "a = 1;", "MathLab"))

    assert export_notebook_to_mtex(document) == "\\begin{MathLab}\na = 1;\n\\end{MathLab}\n"


def test_load_rejects_unknown_notebook_version(tmp_path: Path) -> None:
    path = tmp_path / "future.mtn"
    path.write_text(
        json.dumps({"type": "mathtex-notebook", "version": 99, "blocks": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported notebook file version"):
        load_notebook_file(path)


def test_mtex_notebook_parser_still_parses_latex_and_code() -> None:
    document = parse_notebook_source("Intro\n\\begin{code}\na = 1;\n\\end{code}\n")

    assert [block.kind for block in document.blocks] == ["latex", "code"]
    assert document.blocks[0].source == "Intro\n"
    assert document.blocks[1].source == "a = 1;\n"
