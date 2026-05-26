from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


LOG_LOCATION_RE = re.compile(r"(?P<file>[A-Za-z]:[^:]+|[^:\s]+):(?P<line>\d+)")


@dataclass(frozen=True)
class LogEntry:
    level: str
    message: str
    step: int
    source: str = "stdout"
    file: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class VariableSummary:
    name: str
    value_type: str
    size: str
    summary: str


@dataclass
class ExecutionResult:
    success: bool
    source_path: Path | None = None
    pdf_path: Path | None = None
    build_dir: Path | None = None
    logs: list[LogEntry] = field(default_factory=list)
    warnings: list[LogEntry] = field(default_factory=list)
    errors: list[LogEntry] = field(default_factory=list)
    output_files: list[Path] = field(default_factory=list)
    variables: list[VariableSummary] = field(default_factory=list)


def infer_log_level(message: str, source: str = "stdout") -> str:
    lowered = (message or "").strip().lower()
    if source == "stderr":
        return "error"
    if not lowered:
        return "info"
    if lowered.startswith("warning") or " warning" in lowered:
        return "warning"
    error_prefixes = (
        "error",
        "parse error",
        "block error",
        "runtime error",
        "build error",
        "syntax error",
    )
    if lowered.startswith(error_prefixes) or "error:" in lowered or "failed" in lowered or "exception" in lowered:
        return "error"
    return "info"


def _extract_location(message: str) -> tuple[str | None, int | None]:
    match = LOG_LOCATION_RE.search(message or "")
    if not match:
        return None, None
    try:
        return match.group("file"), int(match.group("line"))
    except (TypeError, ValueError):
        return match.group("file"), None


class _StructuredLogStream:
    def __init__(self, collector: "StructuredLogCollector", source: str) -> None:
        self._collector = collector
        self._source = source

    def write(self, text: str) -> int:
        self._collector.add_text(text, source=self._source)
        return len(text)

    def flush(self) -> None:
        self._collector.flush(source=self._source)


class StructuredLogCollector:
    def __init__(self) -> None:
        self.entries: list[LogEntry] = []
        self._buffers: dict[str, str] = {}
        self._step = 0

    def stream(self, source: str) -> _StructuredLogStream:
        return _StructuredLogStream(self, source)

    def add_entry(self, message: str, level: str = "info", source: str = "app") -> None:
        clean = (message or "").strip()
        if not clean:
            return
        self._step += 1
        file, line = _extract_location(clean)
        self.entries.append(
            LogEntry(
                level=level,
                message=clean,
                step=self._step,
                source=source,
                file=file,
                line=line,
            )
        )

    def add_text(self, text: str, source: str = "stdout") -> None:
        if not text:
            return
        pending = self._buffers.get(source, "") + text
        parts = pending.splitlines(keepends=True)
        trailing = ""
        if parts and not parts[-1].endswith(("\n", "\r")):
            trailing = parts.pop()
        for raw_line in parts:
            clean = raw_line.strip()
            if not clean:
                continue
            self.add_entry(clean, level=infer_log_level(clean, source=source), source=source)
        self._buffers[source] = trailing

    def flush(self, source: str | None = None) -> None:
        if source is not None:
            pending = self._buffers.pop(source, "")
            if pending.strip():
                self.add_entry(pending.strip(), level=infer_log_level(pending, source=source), source=source)
            return
        for key in list(self._buffers.keys()):
            self.flush(source=key)

    def build_result(
        self,
        *,
        success: bool,
        source_path: Path | None,
        pdf_path: Path | None,
        build_dir: Path | None,
        output_files: list[Path],
        variables: list[VariableSummary],
    ) -> ExecutionResult:
        self.flush()
        warnings = [entry for entry in self.entries if entry.level == "warning"]
        errors = [entry for entry in self.entries if entry.level == "error"]
        return ExecutionResult(
            success=success,
            source_path=source_path,
            pdf_path=pdf_path,
            build_dir=build_dir,
            logs=list(self.entries),
            warnings=warnings,
            errors=errors,
            output_files=output_files,
            variables=variables,
        )


def variable_summaries_from_snapshot(snapshot: list[dict[str, str]]) -> list[VariableSummary]:
    summaries: list[VariableSummary] = []
    for item in snapshot:
        summaries.append(
            VariableSummary(
                name=str(item.get("name", "")),
                value_type=str(item.get("class", "")),
                size=str(item.get("size", "")),
                summary=str(item.get("summary", "")),
            )
        )
    return summaries
