from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


DocumentSymbolKind = Literal["variable", "function"]
DocumentSymbolOrigin = Literal["assignment", "function_definition", "for_loop_variable"]

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_]\w*\Z")
_SIMPLE_ASSIGN_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*=\s*(?!=)")
_TYPED_VAR_RE = re.compile(r"^(?P<type>[A-Za-z_]\w*(?:\s*\[\s*\])?)\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?!=)")
_INLINE_FUNCTION_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)\s*=\s*(?!=)")
_AETHER_FUNCTION_RE = re.compile(
    r"^(?:function\s+)?(?P<return_type>[A-Za-z_]\w*(?:\s*\[\s*\])?)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)\s*\{?",
    re.IGNORECASE,
)
_BLOCK_FUNCTION_RE = re.compile(
    r"^function\s+(?:(?:\[(?P<outputs>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\]|(?P<output>[A-Za-z_]\w*))\s*=\s*)?"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)\s*$",
    re.IGNORECASE,
)
_FOR_LOOP_RE = re.compile(r"^for\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<expr>.+)$", re.IGNORECASE)
_FOR_IN_RE = re.compile(r"^for\s+(?P<name>[A-Za-z_]\w*)\s+in\s+(?P<expr>.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class DocumentSymbol:
    name: str
    kind: DocumentSymbolKind
    origin: DocumentSymbolOrigin
    signature: str
    statement_index: int


def extract_document_symbols(document_text: str) -> list[DocumentSymbol]:
    symbols_by_name: dict[str, DocumentSymbol] = {}
    for statement_index, statement in enumerate(_split_document_statements(document_text)):
        symbol = _extract_symbol_from_statement(statement.strip(), statement_index)
        if symbol is None:
            continue
        symbols_by_name[symbol.name.casefold()] = symbol
    return sorted(symbols_by_name.values(), key=lambda item: item.statement_index)


def _extract_symbol_from_statement(statement: str, statement_index: int) -> DocumentSymbol | None:
    if not statement:
        return None
    return (
        _extract_aether_function_symbol(statement, statement_index)
        or _extract_block_function_symbol(statement, statement_index)
        or _extract_inline_function_symbol(statement, statement_index)
        or _extract_for_loop_symbol(statement, statement_index)
        or _extract_for_in_symbol(statement, statement_index)
        or _extract_typed_var_symbol(statement, statement_index)
        or _extract_assignment_symbol(statement, statement_index)
    )


def _extract_assignment_symbol(statement: str, statement_index: int) -> DocumentSymbol | None:
    match = _SIMPLE_ASSIGN_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    return DocumentSymbol(
        name=name,
        kind="variable",
        origin="assignment",
        signature=name,
        statement_index=statement_index,
    )


def _extract_typed_var_symbol(statement: str, statement_index: int) -> DocumentSymbol | None:
    match = _TYPED_VAR_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    return DocumentSymbol(
        name=name,
        kind="variable",
        origin="assignment",
        signature=name,
        statement_index=statement_index,
    )


def _extract_inline_function_symbol(statement: str, statement_index: int) -> DocumentSymbol | None:
    match = _INLINE_FUNCTION_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    if len(name) == 1 and name.isupper():
        return None
    params = _parse_identifier_list(match.group("params"))
    if params is None:
        return None
    return DocumentSymbol(
        name=name,
        kind="function",
        origin="function_definition",
        signature=_build_function_signature(name, params),
        statement_index=statement_index,
    )


def _extract_aether_function_symbol(statement: str, statement_index: int) -> DocumentSymbol | None:
    match = _AETHER_FUNCTION_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    params = _parse_aether_parameter_list(match.group("params"))
    if params is None:
        return None
    return DocumentSymbol(
        name=name,
        kind="function",
        origin="function_definition",
        signature=_build_function_signature(name, params),
        statement_index=statement_index,
    )


def _extract_block_function_symbol(statement: str, statement_index: int) -> DocumentSymbol | None:
    match = _BLOCK_FUNCTION_RE.match(statement)
    if match is None:
        return None
    params = _parse_identifier_list(match.group("params"))
    if params is None:
        return None
    name = match.group("name")
    return DocumentSymbol(
        name=name,
        kind="function",
        origin="function_definition",
        signature=_build_function_signature(name, params),
        statement_index=statement_index,
    )


def _extract_for_loop_symbol(statement: str, statement_index: int) -> DocumentSymbol | None:
    match = _FOR_LOOP_RE.match(statement)
    if match is None:
        return None
    return DocumentSymbol(
        name=match.group("name"),
        kind="variable",
        origin="for_loop_variable",
        signature=match.group("name"),
        statement_index=statement_index,
    )


def _extract_for_in_symbol(statement: str, statement_index: int) -> DocumentSymbol | None:
    match = _FOR_IN_RE.match(statement)
    if match is None:
        return None
    return DocumentSymbol(
        name=match.group("name"),
        kind="variable",
        origin="for_loop_variable",
        signature=match.group("name"),
        statement_index=statement_index,
    )


def _parse_identifier_list(raw_text: str) -> list[str] | None:
    text = raw_text.strip()
    if not text:
        return []
    parts = [part.strip() for part in text.split(",")]
    if not parts or any(not part or _IDENTIFIER_PATTERN.fullmatch(part) is None for part in parts):
        return None
    return parts


def _parse_aether_parameter_list(raw_text: str) -> list[str] | None:
    text = raw_text.strip()
    if not text:
        return []
    params: list[str] = []
    for part in text.split(","):
        tokens = part.strip().split()
        if not tokens:
            return None
        name = tokens[-1]
        if _IDENTIFIER_PATTERN.fullmatch(name) is None:
            return None
        params.append(name)
    return params


def _build_function_signature(name: str, params: list[str]) -> str:
    if not params:
        return f"{name}()"
    return f"{name}({', '.join(params)})"


def _split_document_statements(document_text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    depth = 0
    in_string: str | None = None
    escaped = False
    index = 0

    def flush_current() -> None:
        statement = "".join(current).strip()
        if statement:
            statements.append(statement)
        current.clear()

    while index < len(document_text):
        char = document_text[index]

        if in_string is not None:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            index += 1
            continue

        if char in {'"', "'"}:
            in_string = char
            current.append(char)
            index += 1
            continue

        next_char = document_text[index + 1] if index + 1 < len(document_text) else ""
        if char == "#" or (char == "/" and next_char == "/"):
            while index < len(document_text) and document_text[index] != "\n":
                index += 1
            continue

        if char in "([{":
            depth += 1
            current.append(char)
            index += 1
            continue

        if char in ")]}":
            depth = max(0, depth - 1)
            current.append(char)
            index += 1
            continue

        if depth == 0 and char in ";\n":
            flush_current()
            index += 1
            continue

        current.append(char)
        index += 1

    flush_current()
    return statements
