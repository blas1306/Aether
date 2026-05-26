from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from typing import List, Literal

from latex_lang import env_ast, ejecutar_linea, reset_environment as reset_runtime_environment, workspace_snapshot
from mtex_executor import split_code_statements


@dataclass(frozen=True)
class ConsoleEvent:
    kind: Literal["stdout", "error", "warning", "clear", "status"]
    text: str


@dataclass(frozen=True)
class ConsoleCapture:
    stdout: str = ""
    stderr: str = ""
    cleared: bool = False


class MathRuntime:
    """Thin adapter over the existing module-level MathTeX runtime."""

    def __init__(self) -> None:
        self.env = env_ast

    def split_console_input(self, text: str) -> list[str]:
        return split_code_statements(text)

    def execute_console_line(self, line: str) -> ConsoleCapture:
        stripped = line.strip()
        if not stripped:
            return ConsoleCapture()
        if stripped.lower() == r"\clean":
            return ConsoleCapture(cleared=True)

        out_buffer = io.StringIO()
        err_buffer = io.StringIO()
        try:
            with redirect_stdout(out_buffer), redirect_stderr(err_buffer):
                ejecutar_linea(stripped)
        except Exception as exc:  # pragma: no cover - defensive fallback
            err_buffer.write(f"Unexpected error: {exc}\n")
        return ConsoleCapture(stdout=out_buffer.getvalue(), stderr=err_buffer.getvalue())

    def reset_environment(self) -> None:
        reset_runtime_environment()

    def workspace_snapshot(self) -> list[dict[str, str]]:
        return workspace_snapshot()


def capture_to_events(capture: ConsoleCapture) -> List[ConsoleEvent]:
    events: list[ConsoleEvent] = []
    if capture.cleared:
        events.append(ConsoleEvent(kind="clear", text=""))
    stdout_text = capture.stdout.rstrip("\n")
    stderr_text = capture.stderr.rstrip("\n")
    if stdout_text:
        events.append(ConsoleEvent(kind=_classify_output(stdout_text), text=stdout_text))
    if stderr_text:
        events.append(ConsoleEvent(kind="error", text=stderr_text))
    return events


def _classify_output(text: str) -> Literal["stdout", "error", "warning"]:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith("warning") or "warning:" in lowered:
            return "warning"
        if _looks_like_error(stripped):
            return "error"
    return "stdout"


def _looks_like_error(text: str) -> bool:
    if not text:
        return False
    if "=" in text and text.lstrip()[:1].isalpha():
        left = text.split("=", 1)[0].strip()
        if left.replace("_", "").isalnum():
            return False
    lowered = text.lower()
    error_prefixes = (
        "error",
        "parse error",
        "block error",
        "runtime error",
        "build error",
        "syntax error",
        "usage",
        "invalid",
    )
    return any(lowered.startswith(prefix) for prefix in error_prefixes) or "error:" in lowered


class ConsoleEngine:
    def __init__(self, runtime, prompt: str = "MathTeX> "):
        self.runtime = runtime
        self.prompt = prompt
        self.history: list[str] = []
        self.history_index: int | None = None
        self._draft_buffer: str = ""

    def execute_line(self, line: str) -> List[ConsoleEvent]:
        stripped = line.strip()
        if not stripped:
            return []

        self.history.append(stripped)
        self.history_index = None
        self._draft_buffer = ""

        statements = self._split_input(stripped)
        events: list[ConsoleEvent] = []
        for statement in statements:
            capture = self.runtime.execute_console_line(statement)
            events.extend(capture_to_events(capture))
        return events

    def clear_console(self) -> List[ConsoleEvent]:
        return [ConsoleEvent(kind="clear", text="")]

    def reset_environment(self) -> List[ConsoleEvent]:
        self.runtime.reset_environment()
        return [ConsoleEvent(kind="status", text="Environment reset")]

    def history_prev(self, current_buffer: str) -> str:
        if not self.history:
            return current_buffer
        if self.history_index is None:
            self._draft_buffer = current_buffer
            self.history_index = len(self.history) - 1
        else:
            self.history_index = max(0, self.history_index - 1)
        return self.history[self.history_index]

    def history_next(self) -> str:
        if self.history_index is None:
            return self._draft_buffer
        next_index = self.history_index + 1
        if next_index >= len(self.history):
            self.history_index = None
            draft = self._draft_buffer
            self._draft_buffer = ""
            return draft
        self.history_index = next_index
        return self.history[self.history_index]

    def _split_input(self, text: str) -> list[str]:
        try:
            statements = self.runtime.split_console_input(text)
        except Exception:
            return [text]
        return [statement.strip() for statement in statements if statement.strip()]
