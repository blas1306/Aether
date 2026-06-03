from __future__ import annotations

from collections.abc import Callable
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import AetherError, AetherRuntimeError, AetherSyntaxError, AetherTypeError
from .lexer import lex
from .parser import Parser
from .result import AetherRunResult
from .runner import run_aether
from .stdlib.registry import builtin_constant_names, builtin_names
from .tokens import KEYWORDS
from .typechecker import TypeChecker


@dataclass(frozen=True)
class Diagnostic:
    message: str
    severity: str
    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class RunResult:
    success: bool
    output: str = ""
    error: str | None = None


@dataclass(frozen=True)
class CompletionItem:
    label: str
    kind: str = "text"
    detail: str | None = None


AETHER_ERRORS = (AetherSyntaxError, AetherTypeError, AetherRuntimeError)
_LOCATION_RE = re.compile(r"line (?P<line>\d+), column (?P<column>\d+)")
_ASSIGNMENT_RE = re.compile(r"\b(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:=|\+=)")
_DECLARATION_RE = re.compile(
    r"\b(?:(?:public|private)\s+)?(?:const\s+)?"
    r"(?:int|float|double|string|boolean|Matrix\s*<\s*\w+\s*>|Vector\s*<\s*\w+\s*>|[A-Z][A-Za-z0-9_]*)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b"
)
_FUNCTION_RE = re.compile(
    r"\b(?:(?:public|private)\s+)?(?:function\s+)?"
    r"(?:int|float|double|string|boolean|Matrix|Vector|[A-Z][A-Za-z0-9_]*)?(?:\s*<[^>]+>)?\s*"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\("
)
_STRUCT_RE = re.compile(r"\b(?:(?:public|private)\s+)?struct\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b")


def analyze_source(source: str, *, source_root: str | Path | None = None) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    try:
        tokens = lex(source)
    except AetherSyntaxError as exc:
        return [_diagnostic_from_error(exc, source)]
    parser = Parser(tokens)
    program, syntax_errors = parser.parse_with_recovery()
    diagnostics.extend(_diagnostic_from_error(exc, source) for exc in syntax_errors)
    type_errors = TypeChecker(source_root=source_root).check_collecting_errors(program)
    diagnostics.extend(_diagnostic_from_error(exc, source) for exc in type_errors)
    return diagnostics


def run_source(
    source: str,
    *,
    source_root: str | Path | None = None,
    plot_mode: str | None = None,
    plot_output_dir: str | Path | None = None,
    output_writer: Callable[[str], None] | None = None,
    input_reader: Callable[[], str] | None = None,
) -> RunResult:
    try:
        result: AetherRunResult = run_aether(
            source,
            source_root=source_root,
            plot_mode=plot_mode,
            plot_output_dir=plot_output_dir,
            output_writer=output_writer,
            input_reader=input_reader,
        )
    except AETHER_ERRORS as exc:
        error = exc.format() if isinstance(exc, AetherError) else f"{type(exc).__name__}: {exc}"
        return RunResult(success=False, error=error)
    return RunResult(success=True, output=result.output)


def completion_items(source: str, line: int, column: int) -> list[CompletionItem]:
    del line, column
    seen: set[str] = set()
    items: list[CompletionItem] = []

    def add(label: str, kind: str, detail: str | None = None) -> None:
        if label in seen:
            return
        seen.add(label)
        items.append(CompletionItem(label=label, kind=kind, detail=detail))

    for keyword in sorted(KEYWORDS):
        add(keyword, "keyword")
    for builtin in builtin_names():
        add(builtin, "function", "Aether builtin")
    for constant in builtin_constant_names():
        add(constant, "constant", "Aether builtin constant")
    for builtin in _imported_builtin_aliases(source):
        add(builtin, "function", "Aether imported builtin")
    for constant in _imported_builtin_constant_aliases(source):
        add(constant, "constant", "Aether imported builtin constant")
    for name in sorted(_symbol_names(source)):
        add(name, "variable", "Aether symbol")
    return items


def _diagnostic_from_error(exc: Exception, source: str = "") -> Diagnostic:
    message = exc.format() if isinstance(exc, AetherError) else f"{type(exc).__name__}: {exc}"
    line, column = _extract_location(exc)
    end_column = _diagnostic_end_column(source, line, column)
    return Diagnostic(
        message=message,
        severity="error",
        line=line,
        column=column,
        end_line=line,
        end_column=end_column,
    )


def _extract_location(exc: Exception) -> tuple[int, int]:
    line = getattr(exc, "line", None)
    column = getattr(exc, "column", None)
    if isinstance(line, int) and isinstance(column, int):
        return (max(1, line), max(1, column))
    message = str(exc)
    match = _LOCATION_RE.search(message)
    if match is None:
        return (1, 1)
    return (max(1, int(match.group("line"))), max(1, int(match.group("column"))))


def _diagnostic_end_column(source: str, line: int, column: int) -> int:
    if not source:
        return column + 1
    lines = source.splitlines()
    if line < 1 or line > len(lines):
        return column + 1
    return max(column + 1, len(lines[line - 1]) + 1)


def _symbol_names(source: str) -> set[str]:
    names: set[str] = set()
    names.update(match.group("name") for match in _ASSIGNMENT_RE.finditer(source))
    names.update(match.group("name") for match in _DECLARATION_RE.finditer(source))
    names.update(match.group("name") for match in _STRUCT_RE.finditer(source))
    for match in _FUNCTION_RE.finditer(source):
        name = match.group("name")
        if name not in KEYWORDS:
            names.add(name)
    return names


def _imported_builtin_aliases(source: str) -> set[str]:
    from .stdlib.registry import builtin_aliases_for_import, is_builtin_namespace

    aliases: set[str] = set()
    for match in re.finditer(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b", source, re.MULTILINE):
        module_name = match.group(1)
        if is_builtin_namespace(module_name):
            aliases.update(builtin_aliases_for_import(module_name))
    return aliases


def _imported_builtin_constant_aliases(source: str) -> set[str]:
    from .stdlib.registry import builtin_constant_aliases_for_import, is_builtin_namespace

    aliases: set[str] = set()
    for match in re.finditer(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b", source, re.MULTILINE):
        module_name = match.group(1)
        if is_builtin_namespace(module_name):
            aliases.update(builtin_constant_aliases_for_import(module_name))
    return aliases
