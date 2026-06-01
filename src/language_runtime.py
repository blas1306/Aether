from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aether import AetherRuntimeError, AetherSession, AetherSyntaxError, AetherTypeError, run_aether


@dataclass(frozen=True)
class FileRuntime:
    id: str
    display_name: str
    suffixes: tuple[str, ...]


@dataclass(frozen=True)
class SourceRunResult:
    runtime: FileRuntime
    success: bool
    output: str = ""
    error: str | None = None


AETHER_RUNTIME = FileRuntime("aether", "Aether", (".ae",))
UNKNOWN_RUNTIME = FileRuntime("unknown", "Current editor", ())
LEGACY_SUFFIXES = {".mtx", ".mtex", ".mtn"}

AETHER_ERRORS = (AetherSyntaxError, AetherTypeError, AetherRuntimeError)


def runtime_for_file(path: str | Path | None) -> FileRuntime:
    suffix = _suffix_for_path(path)
    if suffix in AETHER_RUNTIME.suffixes:
        return AETHER_RUNTIME
    return UNKNOWN_RUNTIME


def create_session_for_language(language: str) -> AetherSession:
    """Create an interactive session for Aether."""
    key = (language or "").strip().lower()
    if key in {"aether", "ae", ".ae"}:
        return AetherSession()
    raise ValueError(f"No session is registered for language '{language}'.")


def run_source_for_file(
    path: str | Path | None,
    source: str,
    *,
    math_runtime: object | None = None,
) -> SourceRunResult:
    runtime = runtime_for_file(path)
    if runtime == AETHER_RUNTIME:
        return _run_aether_source(source, path=path)
    suffix = _suffix_for_path(path)
    if suffix in LEGACY_SUFFIXES:
        return SourceRunResult(
            runtime=runtime,
            success=False,
            error=(
                f"Legacy format '{suffix}' is not supported by Aether Studio. "
                "Use or convert the file to .ae."
            ),
        )
    return SourceRunResult(
        runtime=runtime,
        success=False,
        error=f"No runtime is registered for {_display_path(path)}.",
    )


def format_aether_error(exc: AetherSyntaxError | AetherTypeError | AetherRuntimeError) -> str:
    return f"{type(exc).__name__}: {getattr(exc, 'message', str(exc))}"


def _run_aether_source(source: str, *, path: str | Path | None = None) -> SourceRunResult:
    try:
        source_root = Path(path).parent if path is not None else None
        result = run_aether(source, source_root=source_root)
    except AETHER_ERRORS as exc:
        return SourceRunResult(runtime=AETHER_RUNTIME, success=False, error=format_aether_error(exc))
    return SourceRunResult(runtime=AETHER_RUNTIME, success=True, output=result.output)


def _suffix_for_path(path: str | Path | None) -> str:
    if path is None:
        return ""
    return Path(str(path)).suffix.lower()


def _display_path(path: str | Path | None) -> str:
    if path is None:
        return "the current file"
    name = Path(str(path)).name
    return name or str(path)
