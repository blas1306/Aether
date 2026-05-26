from __future__ import annotations

from typing import Any

import numpy as np
import sympy as sp
from sympy.matrices import MatrixBase

from aether import AetherRuntimeError, AetherSession, AetherSyntaxError, AetherTypeError
from console_engine import MathRuntime, capture_to_events
from language_runtime import format_aether_error
from latex_lang import iter_workspace_items
from notebook_model import NotebookBlock, NotebookOutput


_PREVIEW_MAX_ROWS = 5
_PREVIEW_MAX_COLS = 5
_PREVIEW_MAX_TEXT = 80
AETHER_NOTEBOOK_ERRORS = (AetherSyntaxError, AetherTypeError, AetherRuntimeError)


class NotebookRunner:
    def __init__(self, runtime: MathRuntime | None = None) -> None:
        self.runtime = runtime or MathRuntime()
        self.runtime.reset_environment()
        self.aether_session = AetherSession()

    def run_block(self, block: NotebookBlock) -> NotebookBlock:
        if block.kind != "code":
            return block

        block.status = "running"
        block.outputs = []

        if block.language == "Aether":
            return self._run_aether_block(block)
        if block.language != "MathLab":
            block.status = "error"
            block.outputs.append(NotebookOutput(kind="error", text="Unsupported notebook language"))
            return block

        before = _snapshot_by_name(self.runtime.workspace_snapshot())

        try:
            statements = self.runtime.split_console_input(block.source)
        except Exception as exc:
            block.status = "error"
            block.outputs.append(NotebookOutput(kind="error", text=str(exc)))
            return block

        has_error = False
        for statement in statements:
            capture = self.runtime.execute_console_line(statement)
            for event in capture_to_events(capture):
                block.outputs.append(NotebookOutput(kind=event.kind, text=event.text))
                if event.kind == "error":
                    has_error = True

        variable_changes = _workspace_variable_changes(before, self.runtime.workspace_snapshot(), self.runtime.env)
        if variable_changes:
            block.outputs.append(
                NotebookOutput(
                    kind="variables",
                    text=_format_variable_changes(variable_changes),
                    data=variable_changes,
                )
            )

        block.status = "error" if has_error else "ok"
        return block

    def _run_aether_block(self, block: NotebookBlock) -> NotebookBlock:
        before = _snapshot_by_name(self.aether_session.workspace_snapshot())
        try:
            result = self.aether_session.run(block.source)
        except AETHER_NOTEBOOK_ERRORS as exc:
            block.status = "error"
            block.outputs.append(NotebookOutput(kind="error", text=format_aether_error(exc)))
            return block

        if result.output:
            block.outputs.append(NotebookOutput(kind="stdout", text=result.output.rstrip("\n")))

        variable_changes = _workspace_variable_changes(before, self.aether_session.workspace_snapshot(), {})
        if variable_changes:
            block.outputs.append(
                NotebookOutput(
                    kind="variables",
                    text=_format_variable_changes(variable_changes),
                    data=variable_changes,
                )
            )

        block.status = "ok"
        return block


def _snapshot_by_name(snapshot: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {item.get("name", ""): dict(item) for item in snapshot if item.get("name")}


def _workspace_variable_changes(
    before: dict[str, dict[str, str]],
    after_snapshot: list[dict[str, str]],
    env: dict[str, Any],
) -> list[dict[str, str]]:
    values = dict(iter_workspace_items(env))
    changes: list[dict[str, str]] = []
    for item in after_snapshot:
        name = item.get("name", "")
        if not name:
            continue
        previous = before.get(name)
        if previous is not None and previous == item:
            continue
        value = values.get(name)
        change = dict(item)
        change["change"] = "updated" if previous is not None else "new"
        change["preview"] = _preview_value(value, fallback=item.get("summary", ""))
        changes.append(change)
    return changes


def _format_variable_changes(changes: list[dict[str, str]]) -> str:
    lines = ["Generated / Updated variables:"]
    for item in changes:
        cls = item.get("class", "")
        size = item.get("size", "")
        preview = item.get("preview", "")
        details = ", ".join(part for part in (cls, size) if part and part != "-")
        suffix = f": {details}" if details else ":"
        if preview:
            suffix = f"{suffix}, {preview}"
        lines.append(f"- {item.get('name', '')}{suffix}")
    return "\n".join(lines)


def _preview_value(value: Any, fallback: str = "") -> str:
    try:
        if isinstance(value, MatrixBase):
            return _preview_matrix(value.rows, value.cols, lambda row, col: value[row, col])
        if isinstance(value, np.ndarray):
            return _preview_array(value)
        if isinstance(value, (list, tuple)):
            return _preview_sequence(value)
        return _truncate_preview(str(value if value is not None else fallback))
    except Exception:
        return _truncate_preview(fallback)


def _preview_array(value: np.ndarray) -> str:
    if value.ndim == 0:
        return _truncate_preview(str(value.item()))
    if value.ndim == 1:
        return _preview_sequence(value.tolist())
    rows, cols = value.shape[0], value.shape[1]
    return _preview_matrix(rows, cols, lambda row, col: value[row, col])


def _preview_sequence(value: list[Any] | tuple[Any, ...]) -> str:
    if value and all(isinstance(row, (list, tuple, np.ndarray)) for row in value):
        rows = len(value)
        cols = max((len(row) for row in value), default=0)
        return _preview_matrix(rows, cols, lambda row, col: value[row][col] if col < len(value[row]) else "")
    shown = [_preview_cell(item) for item in value[:_PREVIEW_MAX_COLS]]
    if len(value) > _PREVIEW_MAX_COLS:
        shown.append("...")
    return "[" + ", ".join(shown) + "]"


def _preview_matrix(rows: int, cols: int, cell_at) -> str:
    rendered_rows: list[str] = []
    for row in range(min(rows, _PREVIEW_MAX_ROWS)):
        rendered_cells = [_preview_cell(cell_at(row, col)) for col in range(min(cols, _PREVIEW_MAX_COLS))]
        if cols > _PREVIEW_MAX_COLS:
            rendered_cells.append("...")
        rendered_rows.append("[" + ", ".join(rendered_cells) + "]")
    if rows > _PREVIEW_MAX_ROWS:
        rendered_rows.append("...")
    return "[" + "; ".join(rendered_rows) + "]"


def _preview_cell(value: Any) -> str:
    if isinstance(value, sp.Basic):
        text = str(value)
    else:
        text = str(value)
    return _truncate_preview(text, max_len=24)


def _truncate_preview(text: str, max_len: int = _PREVIEW_MAX_TEXT) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 3] + "..."
