from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


DocumentSymbolKind = Literal["variable", "function", "module", "type"]
DocumentSymbolOrigin = Literal[
    "assignment",
    "function_definition",
    "for_loop_variable",
    "import",
    "type_alias",
    "struct",
    "class",
    "interface",
    "enum",
]

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_]\w*\Z")
_SIMPLE_ASSIGN_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*=\s*(?!=)")
_TYPE_RE = r"(?:(?:Array|List|Matrix|Vector)\s*<\s*[^>]+\s*>|[A-Za-z_]\w*)(?:\s*\[\s*\])?"
_VISIBILITY_RE = r"(?:(?:public|private)\s+)?"
_TYPED_VAR_RE = re.compile(rf"^{_VISIBILITY_RE}(?:const\s+)?(?P<type>{_TYPE_RE})\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?!=)")
_CONST_ASSIGN_RE = re.compile(rf"^{_VISIBILITY_RE}const\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?!=)")
_ALIAS_RE = re.compile(rf"^{_VISIBILITY_RE}alias\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<type>{_TYPE_RE})\s*$", re.IGNORECASE)
_STRUCT_RE = re.compile(rf"^{_VISIBILITY_RE}struct\s+(?P<name>[A-Za-z_]\w*)\s*\{{?", re.IGNORECASE)
_CLASS_RE = re.compile(rf"^{_VISIBILITY_RE}class\s+(?P<name>[A-Za-z_]\w*)\s*\{{?", re.IGNORECASE)
_INTERFACE_RE = re.compile(rf"^{_VISIBILITY_RE}interface\s+(?P<name>[A-Za-z_]\w*)\s*\{{?", re.IGNORECASE)
_ENUM_RE = re.compile(rf"^{_VISIBILITY_RE}enum\s+(?P<name>[A-Za-z_]\w*)\s*\{{?", re.IGNORECASE)
_INLINE_FUNCTION_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)\s*=\s*(?!=)")
_AETHER_FUNCTION_RE = re.compile(
    rf"^{_VISIBILITY_RE}(?:function\s+)?(?P<return_type>{_TYPE_RE})\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)\s*\{?",
    re.IGNORECASE,
)
_STRUCT_METHOD_RE = re.compile(
    rf"(?m)^[ \t]*(?:public\s+|private\s+)?(?:function\s+)?(?P<return_type>{_TYPE_RE})\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)\s*\{",
    re.IGNORECASE,
)
_INTERFACE_METHOD_RE = re.compile(
    rf"(?m)^[ \t]*(?:function\s+)?(?P<return_type>{_TYPE_RE})\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)\s*;",
    re.IGNORECASE,
)
_BLOCK_FUNCTION_RE = re.compile(
    r"^function\s+(?:(?:\[(?P<outputs>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\]|(?P<output>[A-Za-z_]\w*))\s*=\s*)?"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)\s*$",
    re.IGNORECASE,
)
_FOR_LOOP_RE = re.compile(r"^for\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<expr>[^{\n]+)", re.IGNORECASE)
_FOR_IN_RE = re.compile(r"^for\s+(?P<name>[A-Za-z_]\w*)\s+in\s+(?P<expr>[^{\n]+)", re.IGNORECASE)
_IMPORT_RE = re.compile(
    r"^import\s+(?P<module>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?:\s+as\s+(?P<alias>[A-Za-z_]\w*))?\b",
    re.IGNORECASE,
)
_FROM_IMPORT_RE = re.compile(
    r"^from\s+(?P<module>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s+import\s+"
    r"(?P<symbol>[A-Za-z_]\w*)(?:\s+as\s+(?P<alias>[A-Za-z_]\w*))?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceRange:
    start_line: int
    start_character: int
    end_line: int
    end_character: int


@dataclass(frozen=True)
class _StatementSpan:
    text: str
    start_offset: int
    end_offset: int
    statement_index: int


@dataclass(frozen=True)
class DocumentSymbol:
    name: str
    kind: DocumentSymbolKind
    origin: DocumentSymbolOrigin
    signature: str
    statement_index: int
    range: SourceRange = field(default_factory=lambda: SourceRange(0, 0, 0, 0))
    selection_range: SourceRange = field(default_factory=lambda: SourceRange(0, 0, 0, 0))
    detail: str | None = None
    type_name: str | None = None
    start_offset: int = 0
    end_offset: int = 0
    selection_start_offset: int = 0
    selection_end_offset: int = 0


def extract_document_symbols(document_text: str) -> list[DocumentSymbol]:
    symbols_by_name: dict[str, DocumentSymbol] = {}
    for symbol in extract_document_symbol_occurrences(document_text):
        symbols_by_name[symbol.name.casefold()] = symbol
    return sorted(symbols_by_name.values(), key=lambda item: item.statement_index)


def extract_document_symbol_occurrences(document_text: str) -> list[DocumentSymbol]:
    symbols: list[DocumentSymbol] = []
    line_starts = _line_start_offsets(document_text)
    for statement in _split_document_statement_spans(document_text):
        symbol = _extract_symbol_from_statement(statement, line_starts)
        if symbol is None:
            continue
        symbols.append(symbol)
        if symbol.origin in {"struct", "class"}:
            symbols.extend(_extract_struct_method_symbols(statement, line_starts))
        if symbol.origin == "interface":
            symbols.extend(_extract_interface_method_symbols(statement, line_starts))
    return sorted(symbols, key=lambda item: item.statement_index)


def symbol_at_position(document_text: str, line: int, character: int) -> DocumentSymbol | None:
    offset = _position_to_offset(document_text, _line_start_offsets(document_text), line, character)
    name = identifier_at_offset(document_text, offset)
    if name is None:
        return None
    return symbol_before_offset(document_text, name, offset)


def symbol_before_offset(document_text: str, name: str, offset: int) -> DocumentSymbol | None:
    candidates = [
        symbol
        for symbol in extract_document_symbol_occurrences(document_text)
        if symbol.name == name and symbol.selection_start_offset <= offset
    ]
    if not candidates:
        return None
    under_cursor = [
        symbol
        for symbol in candidates
        if symbol.selection_start_offset <= offset <= symbol.selection_end_offset
    ]
    return max(under_cursor or candidates, key=lambda symbol: symbol.selection_start_offset)


def symbol_visible_at_offset(document_text: str, name: str, offset: int) -> DocumentSymbol | None:
    """Resolve a document symbol using Aether's declaration-order rules.

    Variables retain point-of-declaration visibility. Module declarations and
    methods in the aggregate currently containing the cursor may be resolved
    forward.
    """
    symbol = symbol_before_offset(document_text, name, offset)
    if symbol is not None:
        return symbol

    occurrences = extract_document_symbol_occurrences(document_text)
    aggregates = [
        candidate
        for candidate in occurrences
        if candidate.origin in {"struct", "class", "interface"}
    ]
    candidates: list[DocumentSymbol] = []
    for candidate in occurrences:
        if candidate.name != name or candidate.selection_start_offset <= offset:
            continue
        if candidate.origin in {"import", "type_alias", "struct", "class", "interface", "enum"}:
            candidates.append(candidate)
            continue
        if candidate.origin != "function_definition":
            continue
        parent = next(
            (
                aggregate
                for aggregate in aggregates
                if aggregate.start_offset == candidate.start_offset
                and aggregate.end_offset == candidate.end_offset
            ),
            None,
        )
        if parent is None or parent.start_offset <= offset <= parent.end_offset:
            candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate.selection_start_offset)


def forward_visible_symbols(document_text: str, offset: int) -> list[DocumentSymbol]:
    """Return module declarations after offset, excluding local variables."""
    occurrences = extract_document_symbol_occurrences(document_text)
    aggregate_spans = {
        (candidate.start_offset, candidate.end_offset)
        for candidate in occurrences
        if candidate.origin in {"struct", "class", "interface"}
    }
    result: list[DocumentSymbol] = []
    for candidate in occurrences:
        if candidate.selection_start_offset <= offset:
            continue
        if candidate.origin in {"import", "type_alias", "struct", "class", "interface", "enum"}:
            result.append(candidate)
        elif candidate.origin == "function_definition" and (
            candidate.start_offset,
            candidate.end_offset,
        ) not in aggregate_spans:
            result.append(candidate)
    return result


def identifier_at_offset(document_text: str, offset: int) -> str | None:
    if not document_text:
        return None
    offset = min(max(0, offset), len(document_text) - 1)
    if not _is_hover_identifier_char(document_text[offset]) and offset > 0:
        offset -= 1
    if not _is_hover_identifier_char(document_text[offset]):
        return None

    start = offset
    while start > 0 and _is_hover_identifier_char(document_text[start - 1]):
        start -= 1
    end = offset + 1
    while end < len(document_text) and _is_hover_identifier_char(document_text[end]):
        end += 1

    token = document_text[start:end].strip(".")
    if not token or not all(part and _IDENTIFIER_PATTERN.fullmatch(part.rstrip("!")) for part in token.split(".")):
        return None
    return token


def _extract_symbol_from_statement(statement_span: _StatementSpan, line_starts: list[int]) -> DocumentSymbol | None:
    statement = statement_span.text.strip()
    if not statement:
        return None
    leading_ws = len(statement_span.text) - len(statement_span.text.lstrip())
    return (
        _extract_import_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_alias_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_struct_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_class_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_interface_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_enum_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_aether_function_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_block_function_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_inline_function_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_for_loop_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_for_in_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_typed_var_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_const_assignment_symbol(statement, statement_span, leading_ws, line_starts)
        or _extract_assignment_symbol(statement, statement_span, leading_ws, line_starts)
    )


def _extract_alias_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _ALIAS_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    type_name = _normalize_type_name(match.group("type"))
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="type",
        origin="type_alias",
        signature=name,
        detail=f"alias {name} = {type_name}",
        type_name=type_name,
    )


def _extract_struct_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _STRUCT_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="type",
        origin="struct",
        signature=name,
        detail=f"struct {name}",
        type_name=name,
    )


def _extract_class_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _CLASS_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="type",
        origin="class",
        signature=name,
        detail=f"class {name}",
        type_name=name,
    )


def _extract_interface_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _INTERFACE_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="type",
        origin="interface",
        signature=name,
        detail=f"interface {name}",
        type_name=name,
    )


def _extract_struct_method_symbols(statement_span: _StatementSpan, line_starts: list[int]) -> list[DocumentSymbol]:
    symbols: list[DocumentSymbol] = []
    for match in _STRUCT_METHOD_RE.finditer(statement_span.text):
        prefix = statement_span.text[: match.start()]
        if "{" not in prefix:
            continue
        name = match.group("name")
        parsed_params = _parse_aether_parameters(match.group("params"))
        if parsed_params is None:
            continue
        param_names, param_details = parsed_params
        return_type = _normalize_type_name(match.group("return_type"))
        signature = _build_function_signature(name, param_names)
        detail = f"{return_type} {_build_function_signature(name, param_details)}"
        symbols.append(
            _document_symbol(
                statement_span,
                line_starts,
                name_start=match.start("name"),
                name_end=match.end("name"),
                name=name,
                kind="function",
                origin="function_definition",
                signature=signature,
                detail=detail,
                type_name=return_type,
            )
        )
    return symbols


def _extract_interface_method_symbols(statement_span: _StatementSpan, line_starts: list[int]) -> list[DocumentSymbol]:
    symbols: list[DocumentSymbol] = []
    for match in _INTERFACE_METHOD_RE.finditer(statement_span.text):
        prefix = statement_span.text[: match.start()]
        if "{" not in prefix:
            continue
        name = match.group("name")
        parsed_params = _parse_aether_parameters(match.group("params"))
        if parsed_params is None:
            continue
        param_names, param_details = parsed_params
        return_type = _normalize_type_name(match.group("return_type"))
        signature = _build_function_signature(name, param_names)
        detail = f"{return_type} {_build_function_signature(name, param_details)}"
        symbols.append(
            _document_symbol(
                statement_span,
                line_starts,
                name_start=match.start("name"),
                name_end=match.end("name"),
                name=name,
                kind="function",
                origin="function_definition",
                signature=signature,
                detail=detail,
                type_name=return_type,
            )
        )
    return symbols


def _extract_enum_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _ENUM_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="type",
        origin="enum",
        signature=name,
        detail=f"enum {name}",
        type_name=name,
    )


def _extract_assignment_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _SIMPLE_ASSIGN_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="variable",
        origin="assignment",
        signature=name,
    )


def _extract_typed_var_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _TYPED_VAR_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    type_name = _normalize_type_name(match.group("type"))
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="variable",
        origin="assignment",
        signature=name,
        detail=f"{type_name} {name}",
        type_name=type_name,
    )


def _extract_const_assignment_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _CONST_ASSIGN_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="variable",
        origin="assignment",
        signature=name,
    )


def _extract_inline_function_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _INLINE_FUNCTION_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    if len(name) == 1 and name.isupper():
        return None
    params = _parse_identifier_list(match.group("params"))
    if params is None:
        return None
    signature = _build_function_signature(name, params)
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="function",
        origin="function_definition",
        signature=signature,
        detail=signature,
    )


def _extract_aether_function_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _AETHER_FUNCTION_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    parsed_params = _parse_aether_parameters(match.group("params"))
    if parsed_params is None:
        return None
    param_names, param_details = parsed_params
    return_type = _normalize_type_name(match.group("return_type"))
    signature = _build_function_signature(name, param_names)
    detail = f"{return_type} {_build_function_signature(name, param_details)}"
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="function",
        origin="function_definition",
        signature=signature,
        detail=detail,
        type_name=return_type,
    )


def _extract_block_function_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _BLOCK_FUNCTION_RE.match(statement)
    if match is None:
        return None
    params = _parse_identifier_list(match.group("params"))
    if params is None:
        return None
    name = match.group("name")
    signature = _build_function_signature(name, params)
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="function",
        origin="function_definition",
        signature=signature,
        detail=signature,
    )


def _extract_for_loop_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _FOR_LOOP_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="variable",
        origin="for_loop_variable",
        signature=name,
        detail=f"loop variable {name}",
    )


def _extract_for_in_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _FOR_IN_RE.match(statement)
    if match is None:
        return None
    name = match.group("name")
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start("name"),
        name_end=leading_ws + match.end("name"),
        name=name,
        kind="variable",
        origin="for_loop_variable",
        signature=name,
        detail=f"loop variable {name}",
    )


def _extract_import_symbol(
    statement: str,
    statement_span: _StatementSpan,
    leading_ws: int,
    line_starts: list[int],
) -> DocumentSymbol | None:
    match = _IMPORT_RE.match(statement)
    from_import = _FROM_IMPORT_RE.match(statement)
    match = match or from_import
    if match is None:
        return None
    if from_import is not None:
        name_group = "alias" if from_import.group("alias") is not None else "symbol"
        name = from_import.group(name_group)
        detail = f"from {from_import.group('module')} import {from_import.group('symbol')}"
        if from_import.group("alias") is not None:
            detail += f" as {name}"
    else:
        name_group = "alias" if match.group("alias") is not None else "module"
        name = match.group(name_group)
        detail = f"import {match.group('module')}"
        if match.group("alias") is not None:
            detail += f" as {name}"
    return _document_symbol(
        statement_span,
        line_starts,
        name_start=leading_ws + match.start(name_group),
        name_end=leading_ws + match.end(name_group),
        name=name,
        kind="module",
        origin="import",
        signature=detail,
        detail=detail,
    )


def _parse_identifier_list(raw_text: str) -> list[str] | None:
    text = raw_text.strip()
    if not text:
        return []
    parts = [part.strip() for part in text.split(",")]
    if not parts or any(not part or _IDENTIFIER_PATTERN.fullmatch(part) is None for part in parts):
        return None
    return parts


def _parse_aether_parameters(raw_text: str) -> tuple[list[str], list[str]] | None:
    text = raw_text.strip()
    if not text:
        return [], []
    names: list[str] = []
    details: list[str] = []
    for part in text.split(","):
        stripped = part.strip()
        if not stripped:
            return None
        name_match = re.search(r"([A-Za-z_]\w*)\s*\Z", stripped)
        if name_match is None:
            return None
        name = name_match.group(1)
        if _IDENTIFIER_PATTERN.fullmatch(name) is None:
            return None
        type_text = _normalize_type_name(stripped[: name_match.start(1)].strip())
        names.append(name)
        details.append(f"{type_text} {name}".strip())
    return names, details


def _build_function_signature(name: str, params: list[str]) -> str:
    if not params:
        return f"{name}()"
    return f"{name}({', '.join(params)})"


def _document_symbol(
    statement_span: _StatementSpan,
    line_starts: list[int],
    *,
    name_start: int,
    name_end: int,
    name: str,
    kind: DocumentSymbolKind,
    origin: DocumentSymbolOrigin,
    signature: str,
    detail: str | None = None,
    type_name: str | None = None,
) -> DocumentSymbol:
    start_offset = statement_span.start_offset
    end_offset = statement_span.end_offset
    selection_start = statement_span.start_offset + name_start
    selection_end = statement_span.start_offset + name_end
    return DocumentSymbol(
        name=name,
        kind=kind,
        origin=origin,
        signature=signature,
        statement_index=statement_span.statement_index,
        range=_range_for_offsets(line_starts, start_offset, end_offset),
        selection_range=_range_for_offsets(line_starts, selection_start, selection_end),
        detail=detail,
        type_name=type_name,
        start_offset=start_offset,
        end_offset=end_offset,
        selection_start_offset=selection_start,
        selection_end_offset=selection_end,
    )


def _normalize_type_name(raw_text: str) -> str:
    return re.sub(r"\s+", "", raw_text)


def _range_for_offsets(line_starts: list[int], start_offset: int, end_offset: int) -> SourceRange:
    start_line, start_character = _offset_to_position(line_starts, start_offset)
    end_line, end_character = _offset_to_position(line_starts, max(start_offset, end_offset))
    return SourceRange(start_line, start_character, end_line, end_character)


def _line_start_offsets(source: str) -> list[int]:
    starts = [0]
    for idx, char in enumerate(source):
        if char == "\n":
            starts.append(idx + 1)
    return starts


def _position_to_offset(source: str, line_starts: list[int], line: int, character: int) -> int:
    if not source:
        return 0
    line_idx = min(max(0, line), len(line_starts) - 1)
    line_start = line_starts[line_idx]
    line_end = source.find("\n", line_start)
    if line_end < 0:
        line_end = len(source)
    return min(line_start + max(0, character), line_end)


def _offset_to_position(line_starts: list[int], offset: int) -> tuple[int, int]:
    line_idx = 0
    for index, line_start in enumerate(line_starts):
        if line_start > offset:
            break
        line_idx = index
    return line_idx, max(0, offset - line_starts[line_idx])


def _is_hover_identifier_char(char: str) -> bool:
    return char.isalnum() or char in "_.!"


def _split_document_statements(document_text: str) -> list[str]:
    return [span.text.strip() for span in _split_document_statement_spans(document_text)]


def _split_document_statement_spans(document_text: str) -> list[_StatementSpan]:
    spans: list[_StatementSpan] = []
    current: list[str] = []
    current_start: list[int | None] = [None]
    depth = 0
    in_string: str | None = None
    escaped = False
    index = 0

    def flush_current() -> None:
        raw_statement = "".join(current)
        statement = raw_statement.strip()
        if statement:
            trailing_ws = len(raw_statement) - len(raw_statement.rstrip())
            start_offset = current_start[0] or 0
            end_offset = index - trailing_ws
            spans.append(_StatementSpan(statement, start_offset, end_offset, len(spans)))
        current.clear()
        current_start[0] = None

    def append_char(char: str) -> None:
        if current_start[0] is None and not char.isspace():
            current_start[0] = index
        current.append(char)

    while index < len(document_text):
        char = document_text[index]

        if in_string is not None:
            append_char(char)
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
            append_char(char)
            index += 1
            continue

        next_char = document_text[index + 1] if index + 1 < len(document_text) else ""
        if char == "#" or (char == "/" and next_char == "/"):
            while index < len(document_text) and document_text[index] != "\n":
                index += 1
            continue

        if char in "([{":
            depth += 1
            append_char(char)
            index += 1
            continue

        if char in ")]}":
            depth = max(0, depth - 1)
            append_char(char)
            index += 1
            continue

        if depth == 0 and char in ";\n":
            flush_current()
            index += 1
            continue

        append_char(char)
        index += 1

    flush_current()
    return spans
