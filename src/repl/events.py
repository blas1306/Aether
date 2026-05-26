from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ConsoleEvent:
    kind: Literal["stdout", "error", "warning", "clear", "status"]
    text: str


@dataclass(frozen=True)
class ConsoleCapture:
    stdout: str = ""
    stderr: str = ""
    cleared: bool = False


def capture_to_events(capture: ConsoleCapture) -> list[ConsoleEvent]:
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
