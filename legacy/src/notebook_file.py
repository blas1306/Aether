from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from notebook_model import NotebookBlock, NotebookDocument


NOTEBOOK_FILE_TYPE = "mathtex-notebook"
NOTEBOOK_FILE_VERSION = 1


def new_notebook_document(default_language: str = "Aether") -> NotebookDocument:
    return NotebookDocument(path=None, default_language=default_language, blocks=[])


def load_notebook_file(path: Path) -> NotebookDocument:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Notebook file must contain a JSON object.")
    if raw.get("type") != NOTEBOOK_FILE_TYPE:
        raise ValueError("Unsupported notebook file type.")
    if raw.get("version") != NOTEBOOK_FILE_VERSION:
        raise ValueError(f"Unsupported notebook file version: {raw.get('version')!r}.")

    default_language = _string_or_default(raw.get("default_language"), "Aether")
    blocks_raw = raw.get("blocks", [])
    if not isinstance(blocks_raw, list):
        raise ValueError("Notebook blocks must be a list.")

    document = NotebookDocument(path=path, default_language=default_language)
    for index, item in enumerate(blocks_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Notebook block {index} must be an object.")
        document.blocks.append(_block_from_json(item, index=index, default_language=default_language))
    return document


def save_notebook_file(document: NotebookDocument, path: Path) -> None:
    payload = {
        "type": NOTEBOOK_FILE_TYPE,
        "version": NOTEBOOK_FILE_VERSION,
        "default_language": document.default_language,
        "blocks": [_block_to_json(block, default_language=document.default_language) for block in document.blocks],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    document.path = path


def export_notebook_to_mtex(document: NotebookDocument) -> str:
    parts: list[str] = []
    for block in document.blocks:
        if block.kind in {"text", "latex"}:
            parts.append(block.source)
            if block.source and not block.source.endswith("\n"):
                parts.append("\n")
            continue

        if block.kind != "code":
            continue

        language = block.language or document.default_language
        environment = "code" if language == document.default_language else language
        parts.append(f"\\begin{{{environment}}}\n")
        parts.append(block.source)
        if block.source and not block.source.endswith("\n"):
            parts.append("\n")
        parts.append(f"\\end{{{environment}}}\n")
    return "".join(parts)


def make_notebook_block(kind: str, source: str = "", language: str | None = None) -> NotebookBlock:
    if kind not in {"text", "code"}:
        raise ValueError(f"Unsupported notebook block kind: {kind!r}.")
    return NotebookBlock(
        id=f"block-{uuid4().hex}",
        kind=kind,
        source=source,
        language=language if kind == "code" else None,
        start_line=1,
        end_line=max(1, len(source.splitlines())),
    )


def _block_from_json(item: dict, *, index: int, default_language: str) -> NotebookBlock:
    kind = item.get("kind")
    if kind not in {"text", "code"}:
        raise ValueError(f"Unsupported notebook block kind at index {index}: {kind!r}.")

    source = _string_or_default(item.get("source"), "")
    language = _string_or_default(item.get("language"), default_language) if kind == "code" else None
    return NotebookBlock(
        id=_string_or_default(item.get("id"), f"block-{uuid4().hex}"),
        kind=kind,
        source=source,
        language=language,
        start_line=1,
        end_line=max(1, len(source.splitlines())),
    )


def _block_to_json(block: NotebookBlock, *, default_language: str) -> dict[str, str]:
    payload = {
        "id": block.id,
        "kind": "text" if block.kind == "latex" else block.kind,
        "source": block.source,
    }
    if block.kind == "code":
        payload["language"] = block.language or default_language
    return payload


def _string_or_default(value: object, default: str) -> str:
    return value if isinstance(value, str) else default
