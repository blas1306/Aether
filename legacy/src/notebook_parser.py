from __future__ import annotations

import re
from pathlib import Path

from notebook_model import NotebookBlock, NotebookDocument, NotebookOutput


_BEGIN_RE = re.compile(r"^\\begin\{(?P<language>code|Aether|MathLab)\}$")


def parse_notebook_source(
    source: str,
    path: Path | None = None,
    default_language: str = "Aether",
) -> NotebookDocument:
    document = NotebookDocument(path=path, default_language=default_language)
    lines = source.splitlines(keepends=True)
    block_index = 1
    latex_lines: list[str] = []
    latex_start_line: int | None = None
    line_number = 1
    index = 0

    def next_id() -> str:
        nonlocal block_index
        block_id = f"block-{block_index}"
        block_index += 1
        return block_id

    def append_latex(end_line: int) -> None:
        nonlocal latex_lines, latex_start_line
        if not latex_lines:
            latex_start_line = None
            return
        document.blocks.append(
            NotebookBlock(
                id=next_id(),
                kind="latex",
                source="".join(latex_lines),
                language=None,
                start_line=latex_start_line or end_line,
                end_line=end_line,
            )
        )
        latex_lines = []
        latex_start_line = None

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        begin_match = _BEGIN_RE.fullmatch(stripped)
        if begin_match is None:
            if latex_start_line is None:
                latex_start_line = line_number
            latex_lines.append(line)
            index += 1
            line_number += 1
            continue

        append_latex(line_number - 1)

        raw_language = begin_match.group("language")
        language = default_language if raw_language == "code" else raw_language
        end_marker = rf"\end{{{raw_language}}}"
        code_start_line = line_number + 1
        code_lines: list[str] = []

        index += 1
        line_number += 1
        found_end = False
        while index < len(lines):
            candidate = lines[index]
            if candidate.strip() == end_marker:
                found_end = True
                break
            code_lines.append(candidate)
            index += 1
            line_number += 1

        code_end_line = max(code_start_line, line_number - 1)
        code_block = NotebookBlock(
            id=next_id(),
            kind="code",
            source="".join(code_lines),
            language=language,
            start_line=code_start_line,
            end_line=code_end_line,
            code_environment=raw_language,
        )

        if not found_end:
            code_block.status = "error"
            code_block.outputs.append(
                NotebookOutput(
                    kind="error",
                    text=f"Missing {end_marker} for notebook code block opened on line {code_start_line - 1}.",
                )
            )
            document.blocks.append(code_block)
            return document

        document.blocks.append(code_block)
        index += 1
        line_number += 1

    append_latex(line_number - 1)
    return document
