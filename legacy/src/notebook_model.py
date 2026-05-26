from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


NotebookBlockKind = Literal["latex", "text", "code"]

NOTEBOOK_BLOCK_STATUSES = {"idle", "running", "ok", "error", "dirty"}


@dataclass
class NotebookOutput:
    kind: str
    text: str = ""
    data: Any = None


@dataclass
class NotebookBlock:
    id: str
    kind: NotebookBlockKind
    source: str
    language: str | None
    start_line: int
    end_line: int
    status: str = "idle"
    outputs: list[NotebookOutput] = field(default_factory=list)
    code_environment: str = "code"


@dataclass
class NotebookDocument:
    path: Path | None
    default_language: str = "Aether"
    blocks: list[NotebookBlock] = field(default_factory=list)
