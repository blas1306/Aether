from __future__ import annotations

from collections.abc import Callable
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import AetherError, AetherRuntimeError, AetherSyntaxError, AetherTypeError
from .lexer import lex
from .parser import Parser
from . import ast
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
    r"(?:int|float|double|string|boolean|Array\s*<[^>]+>|List\s*<[^>]+>|Matrix\s*<[^>]+>|Vector\s*<[^>]+>|[A-Z][A-Za-z0-9_]*)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b"
)
_TYPED_DECLARATION_RE = re.compile(
    r"\b(?:(?:public|private)\s+)?(?:const\s+)?"
    r"(?P<type>int|float|double|string|boolean|Array\s*<[^>]+>|List\s*<[^>]+>|Matrix\s*<[^>]+>|Vector\s*<[^>]+>|[A-Z][A-Za-z0-9_]*)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b"
)
_FUNCTION_RE = re.compile(
    r"\b(?:(?:public|private)\s+)?(?:function\s+)?"
    r"(?:int|float|double|string|boolean|Array|List|Matrix|Vector|[A-Z][A-Za-z0-9_]*)?(?:\s*<[^>]+>)?\s*"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\("
)
_STRUCT_RE = re.compile(r"\b(?:(?:public|private)\s+)?struct\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b")
_INTERFACE_RE = re.compile(
    r"\b(?:(?:public|private)\s+)?interface\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{(?P<body>.*?)\}",
    re.DOTALL,
)
_ENUM_RE = re.compile(
    r"\b(?:(?:public|private)\s+)?enum\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{(?P<body>.*?)\}",
    re.DOTALL,
)
_NATIVE_TYPE_MEMBERS: dict[str, tuple[tuple[str, str], ...]] = {
    "List": (("length", "property"), ("copy", "method"), ("reverse", "method"), ("sort", "method")),
    "Array": (("length", "property"), ("copy", "method")),
    "Matrix": (("rows", "property"), ("columns", "property"), ("transpose", "method")),
    "Vector": (("length", "property"), ("norm", "method")),
}


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
    seen: set[str] = set()
    items: list[CompletionItem] = []

    def add(label: str, kind: str, detail: str | None = None) -> None:
        if label in seen:
            return
        seen.add(label)
        items.append(CompletionItem(label=label, kind=kind, detail=detail))

    enum_context = _enum_member_context(source, line, column)
    if enum_context is not None:
        enum_name, variants = enum_context
        for variant in variants:
            add(variant, "enum", enum_name)
        return items

    native_context = _native_member_context(source, line, column)
    if native_context is not None:
        type_family, members = native_context
        for member, kind in members:
            add(member, kind, type_family)
        return items

    struct_context = _struct_member_context(source, line, column)
    if struct_context is not None:
        struct_name, members = struct_context
        for member, kind in members:
            add(member, kind, struct_name)
        return items

    interface_context = _interface_member_context(source, line, column)
    if interface_context is not None:
        interface_name, members = interface_context
        for member, kind in members:
            add(member, kind, interface_name)
        return items

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
    names.update(match.group("name") for match in _INTERFACE_RE.finditer(source))
    names.update(match.group("name") for match in _ENUM_RE.finditer(source))
    for match in _FUNCTION_RE.finditer(source):
        name = match.group("name")
        if name not in KEYWORDS:
            names.add(name)
    return names


def _native_member_context(source: str, line: int, column: int) -> tuple[str, tuple[tuple[str, str], ...]] | None:
    prefix = _source_prefix(source, line, column)
    match = re.search(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\.\s*[A-Za-z_][A-Za-z0-9_]*$", prefix)
    if match is None:
        match = re.search(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\.\s*$", prefix)
    if match is None:
        return None
    variable_name = match.group("name")
    type_name = _declared_variable_types(prefix).get(variable_name)
    if type_name is None:
        return None
    type_family = _native_type_family(type_name)
    if type_family is None:
        return None
    return type_family, _NATIVE_TYPE_MEMBERS[type_family]


def _struct_member_context(source: str, line: int, column: int) -> tuple[str, tuple[tuple[str, str], ...]] | None:
    prefix = _source_prefix(source, line, column)
    match = re.search(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\.\s*[A-Za-z_][A-Za-z0-9_]*$", prefix)
    if match is None:
        match = re.search(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\.\s*$", prefix)
    if match is None:
        return None
    variable_name = match.group("name")
    type_name = _declared_variable_types(prefix).get(variable_name)
    if type_name is None:
        return None
    compact_type = re.sub(r"\s+", "", type_name)
    members = _struct_members(source).get(compact_type)
    if members is None:
        return None
    return compact_type, members


def _interface_member_context(source: str, line: int, column: int) -> tuple[str, tuple[tuple[str, str], ...]] | None:
    prefix = _source_prefix(source, line, column)
    match = re.search(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\.\s*[A-Za-z_][A-Za-z0-9_]*$", prefix)
    if match is None:
        match = re.search(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\.\s*$", prefix)
    if match is None:
        return None
    variable_name = match.group("name")
    type_name = _declared_variable_types(prefix).get(variable_name)
    if type_name is None:
        return None
    compact_type = re.sub(r"\s+", "", type_name)
    members = _interface_members(source).get(compact_type)
    if members is None:
        return None
    return compact_type, members


def _struct_members(source: str) -> dict[str, tuple[tuple[str, str], ...]]:
    try:
        program, _errors = Parser(lex(source)).parse_with_recovery()
    except AetherSyntaxError:
        return {}
    structs: dict[str, tuple[tuple[str, str], ...]] = {}
    for statement in program.statements:
        if not isinstance(statement, ast.StructDeclaration):
            continue
        members: list[tuple[str, str]] = []
        members.extend((field.name, "property") for field in statement.fields)
        members.extend((method.name, "method") for method in statement.methods)
        structs[statement.name] = tuple(members)
    return structs


def _interface_members(source: str) -> dict[str, tuple[tuple[str, str], ...]]:
    try:
        program, _errors = Parser(lex(source)).parse_with_recovery()
    except AetherSyntaxError:
        return {}
    interfaces: dict[str, tuple[tuple[str, str], ...]] = {}
    for statement in program.statements:
        if not isinstance(statement, ast.InterfaceDeclaration):
            continue
        interfaces[statement.name] = tuple((method.name, "method") for method in statement.methods)
    return interfaces


def _declared_variable_types(source: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for match in _TYPED_DECLARATION_RE.finditer(source):
        declarations[match.group("name")] = match.group("type")
    return declarations


def _native_type_family(type_name: str) -> str | None:
    compact = re.sub(r"\s+", "", type_name)
    for family in _NATIVE_TYPE_MEMBERS:
        if compact == family or compact.startswith(f"{family}<"):
            return family
    return None


def _imported_builtin_aliases(source: str) -> set[str]:
    from .stdlib.registry import builtin_aliases_for_import, is_builtin_namespace

    aliases: set[str] = set()
    for match in re.finditer(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b", source, re.MULTILINE):
        module_name = match.group(1)
        if is_builtin_namespace(module_name):
            aliases.update(builtin_aliases_for_import(module_name))
    return aliases


def _enum_member_context(source: str, line: int, column: int) -> tuple[str, list[str]] | None:
    prefix = _source_prefix(source, line, column)
    match = re.search(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\.\s*$", prefix)
    if match is None:
        return None
    enum_name = match.group("name")
    variants = _enum_variants(source).get(enum_name)
    if variants is None:
        return None
    return enum_name, variants


def _source_prefix(source: str, line: int, column: int) -> str:
    lines = source.splitlines(keepends=True)
    if not lines:
        return ""
    line_index = max(0, min(line - 1, len(lines) - 1))
    offset = sum(len(text) for text in lines[:line_index])
    offset += max(0, min(column - 1, len(lines[line_index])))
    return source[:offset]


def _enum_variants(source: str) -> dict[str, list[str]]:
    enums: dict[str, list[str]] = {}
    for match in _ENUM_RE.finditer(source):
        body = re.sub(r"//.*|#.*", "", match.group("body"))
        variants = [
            variant
            for variant in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", body)
            if variant not in KEYWORDS
        ]
        enums[match.group("name")] = variants
    return enums


def _imported_builtin_constant_aliases(source: str) -> set[str]:
    from .stdlib.registry import builtin_constant_aliases_for_import, is_builtin_namespace

    aliases: set[str] = set()
    for match in re.finditer(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b", source, re.MULTILINE):
        module_name = match.group(1)
        if is_builtin_namespace(module_name):
            aliases.update(builtin_constant_aliases_for_import(module_name))
    return aliases
