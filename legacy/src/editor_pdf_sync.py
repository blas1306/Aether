from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess


logger = logging.getLogger(__name__)

TRACE_ARTIFACT_VERSION = 1

_HEADING_LEVELS = {
    "chapter": 0,
    "section": 1,
    "subsection": 2,
    "subsubsection": 3,
}
_HEADING_PATTERN = re.compile(r"\\(?P<command>chapter|section|subsection|subsubsection)\*?")
_CONTROL_SEQUENCE_RE = re.compile(r"\\([A-Za-z]+)\*?|\\.")
_WHITESPACE_RE = re.compile(r"\s+")
_NUMBERLINE_RE = re.compile(r"\\numberline\s*\{[^{}]*\}")
_SYNCTEX_KEY_VALUE_RE = re.compile(r"^(?P<key>[A-Za-z]+):(?P<value>.*)$")


@dataclass(frozen=True)
class SourceLandmark:
    command: str
    title: str
    normalized_title: str
    line_number: int
    level: int
    parent_index: int | None

    @property
    def signature(self) -> tuple[int, str, str]:
        return (self.line_number, self.command, self.normalized_title)


@dataclass(frozen=True)
class PdfLandmark:
    command: str
    title: str
    normalized_title: str
    page_index: int


@dataclass(frozen=True)
class TraceMappingSpan:
    source_start_line: int | None
    source_end_line: int | None
    tex_start_line: int
    tex_end_line: int
    kind: str

    @property
    def signature(self) -> tuple[str, int | None, int | None, int, int]:
        return (
            self.kind,
            self.source_start_line,
            self.source_end_line,
            self.tex_start_line,
            self.tex_end_line,
        )

    @property
    def source_line_span(self) -> int:
        if self.source_start_line is None or self.source_end_line is None:
            return 0
        return max(0, self.source_end_line - self.source_start_line)

    def contains_source_line(self, line_number: int) -> bool:
        if self.source_start_line is None or self.source_end_line is None:
            return False
        return self.source_start_line <= line_number <= self.source_end_line

    def resolve_tex_line(self, source_line: int) -> int:
        if self.source_start_line is None or self.source_end_line is None:
            return self.tex_start_line
        if self.source_end_line <= self.source_start_line:
            return self.tex_start_line
        if self.tex_end_line <= self.tex_start_line:
            return self.tex_start_line
        source_offset = max(0, min(source_line, self.source_end_line) - self.source_start_line)
        source_span = max(1, self.source_end_line - self.source_start_line)
        tex_span = max(0, self.tex_end_line - self.tex_start_line)
        if tex_span == source_span:
            return self.tex_start_line + source_offset
        scaled_offset = round((source_offset / source_span) * tex_span)
        return min(self.tex_end_line, max(self.tex_start_line, self.tex_start_line + scaled_offset))

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "source_start_line": self.source_start_line,
            "source_end_line": self.source_end_line,
            "tex_start_line": self.tex_start_line,
            "tex_end_line": self.tex_end_line,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "TraceMappingSpan":
        return cls(
            source_start_line=payload.get("source_start_line"),
            source_end_line=payload.get("source_end_line"),
            tex_start_line=int(payload["tex_start_line"]),
            tex_end_line=int(payload["tex_end_line"]),
            kind=str(payload.get("kind", "unknown")),
        )


@dataclass(frozen=True)
class MtexTraceArtifact:
    version: int
    source_path: Path
    tex_path: Path
    pdf_path: Path
    synctex_path: Path
    synctex_enabled: bool
    spans: list[TraceMappingSpan]

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "source_path": str(self.source_path),
            "tex_path": str(self.tex_path),
            "pdf_path": str(self.pdf_path),
            "synctex_path": str(self.synctex_path),
            "synctex_enabled": self.synctex_enabled,
            "spans": [span.to_dict() for span in self.spans],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "MtexTraceArtifact":
        return cls(
            version=int(payload.get("version", 0)),
            source_path=Path(str(payload["source_path"])).expanduser().resolve(),
            tex_path=Path(str(payload["tex_path"])).expanduser().resolve(),
            pdf_path=Path(str(payload["pdf_path"])).expanduser().resolve(),
            synctex_path=Path(str(payload["synctex_path"])).expanduser().resolve(),
            synctex_enabled=bool(payload.get("synctex_enabled", False)),
            spans=[TraceMappingSpan.from_dict(item) for item in payload.get("spans", [])],
        )


@dataclass(frozen=True)
class SyncTexForwardRecord:
    page_index: int
    x: float
    y: float
    h: float
    v: float
    width: float
    height: float
    output_path: Path | None = None


@dataclass(frozen=True)
class ResolvedSyncTarget:
    page_index: int
    landmark: SourceLandmark | None = None
    strategy: str = "landmark"
    tex_line: int | None = None
    trace_span: TraceMappingSpan | None = None
    sync_record: SyncTexForwardRecord | None = None


@dataclass(frozen=True)
class ResolvedSourceTarget:
    line_number: int
    page_index: int
    landmark: SourceLandmark
    strategy: str = "landmark"


def _strip_line_comment(text: str) -> str:
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "%":
            return text[:index]
    return text


def _parse_braced_group(text: str, start_index: int) -> tuple[str, int] | None:
    if start_index >= len(text) or text[start_index] != "{":
        return None
    depth = 0
    chars: list[str] = []
    index = start_index
    while index < len(text):
        char = text[index]
        if char == "{":
            if depth > 0:
                chars.append(char)
            depth += 1
            index += 1
            continue
        if char == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                return ("".join(chars), index + 1)
            chars.append(char)
            index += 1
            continue
        if char == "\\" and index + 1 < len(text):
            chars.append(char)
            chars.append(text[index + 1])
            index += 2
            continue
        chars.append(char)
        index += 1
    return None


def _skip_optional_bracket_group(text: str, start_index: int) -> int:
    index = start_index
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] != "[":
        return index
    depth = 0
    while index < len(text):
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return start_index


def _normalize_title(title: str) -> str:
    cleaned = _NUMBERLINE_RE.sub(" ", title)
    cleaned = _CONTROL_SEQUENCE_RE.sub(lambda match: f" {match.group(1) or ' '} ", cleaned)
    cleaned = cleaned.replace("{", " ").replace("}", " ").replace("~", " ")
    return _WHITESPACE_RE.sub(" ", cleaned).strip().lower()


def extract_source_landmarks(text: str) -> list[SourceLandmark]:
    landmarks: list[SourceLandmark] = []
    active_by_level: dict[int, int] = {}

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_line_comment(raw_line)
        match = _HEADING_PATTERN.search(line)
        if match is None:
            continue
        command = match.group("command")
        level = _HEADING_LEVELS[command]
        index = _skip_optional_bracket_group(line, match.end())
        while index < len(line) and line[index].isspace():
            index += 1
        title_group = _parse_braced_group(line, index)
        if title_group is None:
            continue
        title, _end_index = title_group
        normalized_title = _normalize_title(title)
        parent_index = None
        for parent_level in range(level - 1, -1, -1):
            if parent_level in active_by_level:
                parent_index = active_by_level[parent_level]
                break
        landmarks.append(
            SourceLandmark(
                command=command,
                title=title.strip(),
                normalized_title=normalized_title,
                line_number=line_number,
                level=level,
                parent_index=parent_index,
            )
        )
        active_by_level[level] = len(landmarks) - 1
        for stale_level in tuple(key for key in active_by_level if key > level):
            active_by_level.pop(stale_level, None)

    return landmarks


def _parse_contentsline_entry(entry_text: str) -> PdfLandmark | None:
    entry = entry_text.strip()
    if not entry.startswith(r"\contentsline"):
        return None
    index = len(r"\contentsline")
    groups: list[str] = []
    for _ in range(4):
        while index < len(entry) and entry[index].isspace():
            index += 1
        if index >= len(entry) or entry[index] != "{":
            break
        parsed = _parse_braced_group(entry, index)
        if parsed is None:
            break
        value, index = parsed
        groups.append(value)

    if len(groups) < 3:
        return None

    command = groups[0].strip()
    if command not in _HEADING_LEVELS:
        return None

    normalized_title = _normalize_title(groups[1])
    if not normalized_title:
        return None

    try:
        page_number = int(groups[2].strip())
    except ValueError:
        return None

    return PdfLandmark(
        command=command,
        title=groups[1].strip(),
        normalized_title=normalized_title,
        page_index=max(0, page_number - 1),
    )


def parse_toc_landmarks(text: str) -> list[PdfLandmark]:
    landmarks: list[PdfLandmark] = []
    for raw_line in text.splitlines():
        parsed = _parse_contentsline_entry(raw_line)
        if parsed is not None:
            landmarks.append(parsed)
    return landmarks


def parse_aux_landmarks(text: str) -> list[PdfLandmark]:
    landmarks: list[PdfLandmark] = []
    prefix = r"\@writefile{toc}"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        index = len(prefix)
        while index < len(line) and line[index].isspace():
            index += 1
        if index >= len(line) or line[index] != "{":
            continue
        parsed = _parse_braced_group(line, index)
        if parsed is None:
            continue
        entry_text, _end_index = parsed
        parsed_entry = _parse_contentsline_entry(entry_text)
        if parsed_entry is not None:
            landmarks.append(parsed_entry)
    return landmarks


def load_compiled_pdf_landmarks(
    toc_path: str | Path | None,
    aux_path: str | Path | None = None,
) -> list[PdfLandmark]:
    for candidate, parser in (
        (toc_path, parse_toc_landmarks),
        (aux_path, parse_aux_landmarks),
    ):
        if candidate is None:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            return parser(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return []


def write_trace_artifact(trace_path: str | Path, artifact: MtexTraceArtifact) -> None:
    path = Path(trace_path).expanduser().resolve()
    path.write_text(json.dumps(artifact.to_dict(), indent=2), encoding="utf-8")


def load_trace_artifact(trace_path: str | Path | None) -> MtexTraceArtifact | None:
    if trace_path is None:
        return None
    path = Path(trace_path).expanduser().resolve()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.debug("Could not read trace artifact: %s", path, exc_info=True)
        return None
    try:
        artifact = MtexTraceArtifact.from_dict(payload)
    except Exception:
        logger.debug("Trace artifact had an unexpected schema: %s", path, exc_info=True)
        return None
    if artifact.version != TRACE_ARTIFACT_VERSION:
        logger.debug("Ignoring unsupported trace artifact version %s from %s", artifact.version, path)
        return None
    return artifact


class SourceTraceMap:
    def __init__(self, artifact: MtexTraceArtifact | None = None) -> None:
        self._artifact = artifact
        self._spans = artifact.spans if artifact is not None else []
        self._source_starts = [
            span.source_start_line
            for span in self._spans
            if span.source_start_line is not None and span.source_end_line is not None
        ]

    @property
    def artifact(self) -> MtexTraceArtifact | None:
        return self._artifact

    def clear(self) -> None:
        self._artifact = None
        self._spans = []
        self._source_starts = []

    def update(self, artifact: MtexTraceArtifact | None) -> None:
        self.__init__(artifact)

    def resolve_span_for_source_line(self, line_number: int) -> TraceMappingSpan | None:
        matches = [
            span
            for span in self._spans
            if span.contains_source_line(line_number)
        ]
        if not matches:
            return None
        return min(
            matches,
            key=lambda span: (
                span.source_line_span if span.source_line_span > 0 else 0,
                span.tex_start_line,
            ),
        )

    def resolve_tex_line_for_source_line(self, line_number: int) -> tuple[int, TraceMappingSpan] | None:
        span = self.resolve_span_for_source_line(line_number)
        if span is None:
            return None
        return (span.resolve_tex_line(line_number), span)


def parse_synctex_view_output(text: str) -> list[SyncTexForwardRecord]:
    records: list[SyncTexForwardRecord] = []
    if "SyncTeX result begin" not in text:
        return records

    current: dict[str, str] = {}
    inside_results = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "SyncTeX result begin":
            inside_results = True
            current = {}
            continue
        if line == "SyncTeX result end":
            break
        if not inside_results or not line:
            continue
        match = _SYNCTEX_KEY_VALUE_RE.match(line)
        if match is None:
            continue
        key = match.group("key")
        value = match.group("value").strip()
        if key == "Output" and "Page" in current:
            records.extend(_build_synctex_records_from_payload(current))
            current = {}
        current[key] = value

    if current:
        records.extend(_build_synctex_records_from_payload(current))
    return records


def _build_synctex_records_from_payload(payload: dict[str, str]) -> list[SyncTexForwardRecord]:
    if "Page" not in payload:
        return []
    try:
        page_number = int(payload["Page"])
        return [
            SyncTexForwardRecord(
                page_index=max(0, page_number - 1),
                x=float(payload.get("x", "0")),
                y=float(payload.get("y", "0")),
                h=float(payload.get("h", payload.get("x", "0"))),
                v=float(payload.get("v", payload.get("y", "0"))),
                width=float(payload.get("W", "0")),
                height=float(payload.get("H", "0")),
                output_path=Path(payload["Output"]).expanduser().resolve() if payload.get("Output") else None,
            )
        ]
    except ValueError:
        logger.debug("Could not parse SyncTeX payload: %s", payload, exc_info=True)
        return []


def query_synctex_forward(
    *,
    tex_path: str | Path,
    pdf_path: str | Path,
    line_number: int,
    column_number: int = 1,
    synctex_dir: str | Path | None = None,
) -> list[SyncTexForwardRecord]:
    synctex_binary = shutil.which("synctex")
    if synctex_binary is None:
        logger.debug("SyncTeX CLI is not available on PATH.")
        return []

    resolved_tex = Path(tex_path).expanduser().resolve()
    resolved_pdf = Path(pdf_path).expanduser().resolve()
    if not resolved_pdf.exists():
        logger.debug("Cannot query SyncTeX without a PDF: %s", resolved_pdf)
        return []

    command = [
        synctex_binary,
        "view",
        "-i",
        f"{max(1, int(line_number))}:{max(0, int(column_number))}:{resolved_tex}",
        "-o",
        str(resolved_pdf),
    ]
    if synctex_dir is not None:
        resolved_dir = Path(synctex_dir).expanduser().resolve()
        command.extend(["-d", str(resolved_dir)])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        logger.debug("SyncTeX invocation failed for %s", resolved_tex, exc_info=True)
        return []

    output_text = "\n".join(part for part in (result.stdout, result.stderr) if part)
    records = parse_synctex_view_output(output_text)
    if not records:
        logger.debug(
            "SyncTeX did not return a forward target for %s:%s. Raw output: %s",
            resolved_tex,
            line_number,
            output_text.strip(),
        )
    return records


class EditorPdfSyncMap:
    """Stage-2 forward sync resolver with trace+SyncTeX first and landmark fallback second."""

    def __init__(self) -> None:
        self._source_landmarks: list[SourceLandmark] = []
        self._line_numbers: list[int] = []
        self._pdf_landmarks: list[PdfLandmark] = []
        self._page_by_source_index: dict[int, int] = {}
        self._trace_map = SourceTraceMap()

    def clear(self) -> None:
        self._source_landmarks = []
        self._line_numbers = []
        self._pdf_landmarks = []
        self._page_by_source_index = {}
        self._trace_map.clear()

    def update_source(self, text: str) -> None:
        self._source_landmarks = extract_source_landmarks(text)
        self._line_numbers = [landmark.line_number for landmark in self._source_landmarks]
        self._rebuild_page_map()

    def update_compiled_landmarks(
        self,
        *,
        toc_path: str | Path | None,
        aux_path: str | Path | None = None,
    ) -> None:
        self._pdf_landmarks = load_compiled_pdf_landmarks(toc_path, aux_path)
        self._rebuild_page_map()

    def update_trace_artifact(self, trace_path: str | Path | None) -> None:
        self._trace_map.update(load_trace_artifact(trace_path))

    def current_landmark_for_line(self, line_number: int) -> SourceLandmark | None:
        if not self._line_numbers:
            return None
        index = bisect_right(self._line_numbers, max(1, line_number)) - 1
        if index < 0:
            return None
        return self._source_landmarks[index]

    def current_sync_signature_for_line(self, line_number: int) -> tuple | None:
        trace_match = self._trace_map.resolve_tex_line_for_source_line(line_number)
        if trace_match is not None:
            _tex_line, span = trace_match
            return ("trace",) + span.signature
        landmark = self.current_landmark_for_line(line_number)
        if landmark is not None:
            return ("landmark",) + landmark.signature
        return None

    def resolve_target_for_line(self, line_number: int) -> ResolvedSyncTarget | None:
        line_number = max(1, int(line_number))
        landmark = self.current_landmark_for_line(line_number)

        trace_match = self._trace_map.resolve_tex_line_for_source_line(line_number)
        artifact = self._trace_map.artifact
        if trace_match is not None and artifact is not None and artifact.synctex_enabled:
            tex_line, span = trace_match
            records = query_synctex_forward(
                tex_path=artifact.tex_path,
                pdf_path=artifact.pdf_path,
                synctex_dir=artifact.synctex_path.parent,
                line_number=tex_line,
                column_number=1,
            )
            if records:
                logger.debug(
                    "Forward sync resolved source line %s to tex line %s and PDF page %s via SyncTeX.",
                    line_number,
                    tex_line,
                    records[0].page_index + 1,
                )
                return ResolvedSyncTarget(
                    page_index=records[0].page_index,
                    landmark=landmark,
                    strategy="synctex",
                    tex_line=tex_line,
                    trace_span=span,
                    sync_record=records[0],
                )
            logger.debug(
                "Forward sync had trace data for source line %s -> tex line %s, but SyncTeX returned no result.",
                line_number,
                tex_line,
            )

        if not self._line_numbers:
            return None
        index = bisect_right(self._line_numbers, line_number) - 1
        if index < 0:
            return None
        while index is not None and index >= 0:
            page_index = self._page_by_source_index.get(index)
            if page_index is not None:
                return ResolvedSyncTarget(
                    page_index=page_index,
                    landmark=self._source_landmarks[index],
                    strategy="landmark",
                )
            index = self._source_landmarks[index].parent_index
        return None

    def resolve_source_target_for_page(self, page_index: int) -> ResolvedSourceTarget | None:
        if not self._source_landmarks or not self._page_by_source_index:
            return None

        resolved_page = max(0, int(page_index))
        candidates = [
            (source_index, mapped_page)
            for source_index, mapped_page in self._page_by_source_index.items()
            if mapped_page <= resolved_page
        ]
        if not candidates:
            return None

        source_index, matched_page = max(
            candidates,
            key=lambda item: (
                item[1],
                self._source_landmarks[item[0]].line_number,
            ),
        )
        landmark = self._source_landmarks[source_index]
        return ResolvedSourceTarget(
            line_number=landmark.line_number,
            page_index=matched_page,
            landmark=landmark,
            strategy="landmark",
        )

    def _rebuild_page_map(self) -> None:
        page_by_source_index: dict[int, int] = {}
        pdf_index = 0
        for source_index, source_landmark in enumerate(self._source_landmarks):
            matched_page = None
            for candidate_index in range(pdf_index, len(self._pdf_landmarks)):
                pdf_landmark = self._pdf_landmarks[candidate_index]
                if pdf_landmark.command != source_landmark.command:
                    continue
                if pdf_landmark.normalized_title != source_landmark.normalized_title:
                    continue
                matched_page = pdf_landmark.page_index
                pdf_index = candidate_index + 1
                break
            if matched_page is not None:
                page_by_source_index[source_index] = matched_page
        self._page_by_source_index = page_by_source_index
