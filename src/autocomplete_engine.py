from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Sequence

from aether.stdlib.registry import builtin_names
from command_catalog import COMMAND_CATALOG, CommandSuggestion
from document_symbols import DocumentSymbol, extract_document_symbols


AutocompleteKind = Literal["command", "identifier", "member"]
DocumentKind = Literal["script", "mtex_document"]


@dataclass(frozen=True)
class AutocompleteMatch:
    kind: AutocompleteKind
    prefix: str
    token_start_col: int
    token_end_col: int
    qualifier: str = ""


@dataclass(frozen=True)
class AutocompleteRequest:
    line_text: str
    cursor_col: int
    document_kind: DocumentKind = "script"
    document_text: str = ""
    workspace_items: Sequence[dict[str, str]] = ()


def _is_command_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _is_identifier_start_char(char: str) -> bool:
    return char.isalpha() or char == "_"


def _is_identifier_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _keyword_entry(
    name: str,
    description: str,
    *,
    insert_text: str | None = None,
    signature: str | None = None,
    category: str = "keywords",
    priority: int = 120,
) -> CommandSuggestion:
    resolved_insert = insert_text or name
    resolved_signature = signature or resolved_insert
    return CommandSuggestion(
        name=name,
        label=name,
        insert_text=resolved_insert,
        signature=resolved_signature,
        description=description,
        category=category,
        kind="keyword",
        source="language",
        priority=priority,
        match_text=name,
    )


KEYWORD_SUGGESTIONS: tuple[CommandSuggestion, ...] = (
    _keyword_entry("for", "Start a for-in loop.", insert_text="for ", signature="for x in iterable { ... }", category="control"),
    _keyword_entry("while", "Start a while block.", insert_text="while ", signature="while condition { ... }", category="control"),
    _keyword_entry("if", "Start a conditional block.", insert_text="if ", signature="if condition { ... }", category="control"),
    _keyword_entry("else", "Add an else branch.", category="control"),
    _keyword_entry("in", "Separate a for-loop variable from its iterable.", category="control", priority=95),
    _keyword_entry("function", "Start a user function definition.", insert_text="function ", signature="function int name() { ... }", category="definitions"),
    _keyword_entry("return", "Return from the current function.", category="control"),
    _keyword_entry("true", "Boolean literal.", category="literals", priority=100),
    _keyword_entry("false", "Boolean literal.", category="literals", priority=100),
    _keyword_entry("int", "Integer type.", category="types", priority=105),
    _keyword_entry("double", "Double precision numeric type.", category="types", priority=105),
    _keyword_entry("float", "Floating point numeric type.", category="types", priority=105),
    _keyword_entry("string", "String type.", category="types", priority=105),
    _keyword_entry("boolean", "Boolean type.", category="types", priority=105),
    _keyword_entry("bool", "Boolean type alias.", insert_text="boolean", signature="boolean", category="types", priority=70),
    _keyword_entry("Matrix", "Matrix type.", category="types", priority=95),
    _keyword_entry("Vector", "Vector type.", category="types", priority=95),
)


def _snippet_entry(
    name: str,
    insert_text: str,
    cursor_col: int,
    selection_length: int,
    description: str,
    *,
    priority: int = 390,
) -> CommandSuggestion:
    return CommandSuggestion(
        name=name,
        label=name,
        insert_text=insert_text,
        signature=insert_text,
        description=description,
        category="snippets",
        kind="snippet",
        source="language",
        priority=priority,
        match_text=name,
        cursor_backtrack=len(insert_text) - cursor_col,
        cursor_selection_length=selection_length,
    )


SNIPPET_SUGGESTIONS: tuple[CommandSuggestion, ...] = (
    _snippet_entry("fn", "f(x) = expression;", len("f(x) = "), len("expression"), "Expression function snippet.", priority=430),
    _snippet_entry("for", "for x in iterable {\n    \n}", len("for "), len("x"), "For loop snippet."),
    _snippet_entry("if", "if condition {\n    \n}", len("if "), len("condition"), "If block snippet."),
    _snippet_entry("while", "while condition {\n    \n}", len("while "), len("condition"), "While loop snippet."),
    _snippet_entry("func", "int name() {\n    \n}", len("int "), len("name"), "Block function snippet."),
    _snippet_entry("ife", "if condition {\n    \n} else {\n    \n}", len("if "), len("condition"), "If/else block snippet."),
)


def _line_context(line_text: str, cursor_col: int, *, percent_comments: bool = False) -> tuple[bool, int | None]:
    in_string: str | None = None
    escaped = False
    index = 0
    limit = max(0, min(cursor_col, len(line_text)))
    while index < limit:
        char = line_text[index]
        next_char = line_text[index + 1] if index + 1 < len(line_text) else ""

        if in_string is not None:
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
            index += 1
            continue

        if char == "#" or (percent_comments and char == "%" and (index == 0 or line_text[index - 1] != "\\")):
            return False, index
        if char == "/" and next_char == "/":
            return False, index

        index += 1

    return in_string is not None, None


def is_comment_context(line_text: str, cursor_col: int, *, percent_comments: bool = False) -> bool:
    if cursor_col < 0 or cursor_col > len(line_text):
        return False
    _in_string, comment_start = _line_context(line_text, cursor_col, percent_comments=percent_comments)
    return comment_start is not None and cursor_col > comment_start


def is_string_context(line_text: str, cursor_col: int, *, percent_comments: bool = False) -> bool:
    if cursor_col < 0 or cursor_col > len(line_text):
        return False
    in_string, _comment_start = _line_context(line_text, cursor_col, percent_comments=percent_comments)
    return in_string


def detect_command_prefix(line_text: str, cursor_col: int, *, percent_comments: bool = False) -> AutocompleteMatch | None:
    if cursor_col < 0 or cursor_col > len(line_text):
        return None
    if is_comment_context(line_text, cursor_col, percent_comments=percent_comments) or is_string_context(
        line_text,
        cursor_col,
        percent_comments=percent_comments,
    ):
        return None

    start = cursor_col
    while start > 0 and _is_command_char(line_text[start - 1]):
        start -= 1

    if start == 0 or line_text[start - 1] != "\\":
        return None

    token_start = start - 1
    token_end = cursor_col
    while token_end < len(line_text) and _is_command_char(line_text[token_end]):
        token_end += 1

    return AutocompleteMatch(
        kind="command",
        prefix=line_text[token_start:cursor_col],
        token_start_col=token_start,
        token_end_col=token_end,
    )


def detect_identifier_prefix(line_text: str, cursor_col: int, *, percent_comments: bool = False) -> AutocompleteMatch | None:
    if cursor_col < 0 or cursor_col > len(line_text):
        return None
    if is_comment_context(line_text, cursor_col, percent_comments=percent_comments) or is_string_context(
        line_text,
        cursor_col,
        percent_comments=percent_comments,
    ):
        return None

    start = cursor_col
    while start > 0 and _is_identifier_char(line_text[start - 1]):
        start -= 1

    if start >= cursor_col:
        return None
    if start > 0 and line_text[start - 1] == "\\":
        return None
    if not _is_identifier_start_char(line_text[start]):
        return None

    token_end = cursor_col
    while token_end < len(line_text) and _is_identifier_char(line_text[token_end]):
        token_end += 1

    return AutocompleteMatch(
        kind="identifier",
        prefix=line_text[start:cursor_col],
        token_start_col=start,
        token_end_col=token_end,
    )


def detect_member_prefix(line_text: str, cursor_col: int, *, percent_comments: bool = False) -> AutocompleteMatch | None:
    if cursor_col < 0 or cursor_col > len(line_text):
        return None
    if is_comment_context(line_text, cursor_col, percent_comments=percent_comments) or is_string_context(
        line_text,
        cursor_col,
        percent_comments=percent_comments,
    ):
        return None

    token_start = cursor_col
    while token_start > 0 and _is_identifier_char(line_text[token_start - 1]):
        token_start -= 1

    if token_start == 0 or line_text[token_start - 1] != ".":
        return None

    qualifier_end = token_start - 1
    qualifier_start = qualifier_end
    while qualifier_start > 0 and (
        _is_identifier_char(line_text[qualifier_start - 1]) or line_text[qualifier_start - 1] == "."
    ):
        qualifier_start -= 1

    qualifier = line_text[qualifier_start:qualifier_end]
    if not qualifier or any(not part or not _is_identifier_start_char(part[0]) for part in qualifier.split(".")):
        return None

    token_end = cursor_col
    while token_end < len(line_text) and _is_identifier_char(line_text[token_end]):
        token_end += 1

    return AutocompleteMatch(
        kind="member",
        prefix=line_text[token_start:cursor_col],
        token_start_col=token_start,
        token_end_col=token_end,
        qualifier=qualifier,
    )


def detect_autocomplete_match(line_text: str, cursor_col: int, *, percent_comments: bool = False) -> AutocompleteMatch | None:
    return (
        detect_command_prefix(line_text, cursor_col, percent_comments=percent_comments)
        or detect_member_prefix(line_text, cursor_col, percent_comments=percent_comments)
        or detect_identifier_prefix(line_text, cursor_col, percent_comments=percent_comments)
    )


def _match_prefix(candidate: str, prefix: str) -> bool:
    return candidate.casefold().startswith(prefix.casefold())


def _format_workspace_variable_description(item: dict[str, str]) -> str:
    value_type = str(item.get("class", "")).strip()
    size = str(item.get("size", "")).strip()
    summary = str(item.get("summary", "")).strip()
    parts = [part for part in (value_type, size) if part and part != "function"]
    lead = " ".join(parts).strip()
    if summary and summary != str(item.get("name", "")).strip():
        return f"{lead}: {summary}" if lead else summary
    return lead or "Workspace value."


def _workspace_suggestions(prefix: str, workspace_items: Sequence[dict[str, str]]) -> list[CommandSuggestion]:
    suggestions: list[CommandSuggestion] = []
    for item in workspace_items:
        name = str(item.get("name", "")).strip()
        if not name or not _match_prefix(name, prefix):
            continue
        cls = str(item.get("class", "")).strip()
        signature = str(item.get("summary", "")).strip() or name
        if cls in {"UserFunction", "function"}:
            suggestions.append(
                CommandSuggestion(
                    name=name,
                    label=name,
                    insert_text=f"{name}()",
                    signature=signature,
                    description="User function from the current workspace.",
                    category="workspace",
                    kind="function",
                    source="workspace",
                    priority=260,
                    match_text=name,
                    cursor_backtrack=1,
                )
            )
            continue
        suggestions.append(
            CommandSuggestion(
                name=name,
                label=name,
                insert_text=name,
                signature=name,
                description=_format_workspace_variable_description(item),
                category="workspace",
                kind="variable",
                source="workspace",
                priority=240,
                match_text=name,
            )
        )
    return suggestions


def _document_symbol_description(symbol: DocumentSymbol) -> str:
    if symbol.kind == "function":
        return "User function defined earlier in the current document."
    if symbol.origin == "for_loop_variable":
        return "Loop variable defined earlier in the current document."
    return "Variable defined earlier in the current document."


def _document_symbol_suggestions(prefix: str, document_text: str) -> list[CommandSuggestion]:
    suggestions: list[CommandSuggestion] = []
    for symbol in extract_document_symbols(document_text):
        if not _match_prefix(symbol.name, prefix):
            continue
        priority = 310 + symbol.statement_index if symbol.kind == "function" else 290 + symbol.statement_index
        if symbol.kind == "function":
            suggestions.append(
                CommandSuggestion(
                    name=symbol.name,
                    label=symbol.name,
                    insert_text=f"{symbol.name}()",
                    signature=symbol.signature,
                    description=_document_symbol_description(symbol),
                    category="document",
                    kind="function",
                    source="document",
                    priority=priority,
                    match_text=symbol.name,
                    cursor_backtrack=1,
                )
            )
            continue
        suggestions.append(
            CommandSuggestion(
                name=symbol.name,
                label=symbol.name,
                insert_text=symbol.name,
                signature=symbol.signature,
                description=_document_symbol_description(symbol),
                category="document",
                kind="variable",
                source="document",
                priority=priority,
                match_text=symbol.name,
            )
        )
    return suggestions


def _builtin_suggestions(prefix: str) -> list[CommandSuggestion]:
    suggestions: list[CommandSuggestion] = []
    keyword_names = {item.name for item in KEYWORD_SUGGESTIONS}
    for name in builtin_names():
        if "." in name or name in keyword_names or not _match_prefix(name, prefix):
            continue
        suggestions.append(
            CommandSuggestion(
                name=name,
                label=name,
                insert_text=f"{name}()",
                signature=f"{name}(...)",
                description="Aether builtin.",
                category="builtins",
                kind="function",
                source="stdlib",
                priority=230,
                match_text=name,
                cursor_backtrack=1,
            )
        )
    
    # Also include package functions whose short names match the prefix
    for name in builtin_names():
        if "." not in name or name in keyword_names:
            continue
        # Extract the short name (part after the last dot)
        short_name = name.rsplit(".", 1)[-1]
        if not _match_prefix(short_name, prefix):
            continue
        suggestions.append(
            CommandSuggestion(
                name=short_name,
                label=short_name,
                insert_text=f"{short_name}()",
                signature=f"{name}(...)",
                description="Aether stdlib function.",
                category="stdlib",
                kind="function",
                source="stdlib",
                priority=240,
                match_text=short_name,
                cursor_backtrack=1,
            )
        )
    return suggestions


def _stdlib_member_suggestions(qualifier: str, prefix: str) -> list[CommandSuggestion]:
    children: dict[str, str] = {}
    function_names: list[str] = []
    qualifier_prefix = f"{qualifier}."

    for name in builtin_names():
        if not name.startswith(qualifier_prefix):
            continue
        remainder = name[len(qualifier_prefix) :]
        head, _dot, tail = remainder.partition(".")
        if tail:
            children[head] = f"{qualifier_prefix}{head}"
        elif head:
            function_names.append(head)

    suggestions: list[CommandSuggestion] = []
    for child in sorted(children):
        if not _match_prefix(child, prefix):
            continue
        suggestions.append(
            CommandSuggestion(
                name=child,
                label=child,
                insert_text=child,
                signature=children[child],
                description="Aether namespace.",
                category="modules",
                kind="module",
                source="stdlib",
                priority=460,
                match_text=child,
            )
        )

    for function_name in sorted(function_names):
        if not _match_prefix(function_name, prefix):
            continue
        suggestions.append(
            CommandSuggestion(
                name=function_name,
                label=function_name,
                insert_text=f"{function_name}()",
                signature=f"{qualifier_prefix}{function_name}(...)",
                description="Aether stdlib function.",
                category="stdlib",
                kind="function",
                source="stdlib",
                priority=410,
                match_text=function_name,
                cursor_backtrack=1,
            )
        )
    return suggestions


def _keyword_suggestions(prefix: str) -> list[CommandSuggestion]:
    return [item for item in KEYWORD_SUGGESTIONS if _match_prefix(item.match_text or item.name, prefix)]


def _snippet_suggestions(prefix: str) -> list[CommandSuggestion]:
    return [item for item in SNIPPET_SUGGESTIONS if (item.match_text or item.name).casefold() == prefix.casefold()]


def _next_non_space_char(line_text: str, cursor_col: int) -> str | None:
    idx = cursor_col
    while idx < len(line_text) and line_text[idx].isspace():
        idx += 1
    if idx >= len(line_text):
        return None
    return line_text[idx]


def _looks_like_code_line(line_text: str) -> bool:
    stripped = line_text.strip()
    if not stripped:
        return False
    if stripped.startswith("\\"):
        return False
    if "=" in stripped:
        return True
    starters = ("for", "while", "if", "elif", "else", "function", "repeat", "until", "return", "from", "import")
    return any(stripped.lower().startswith(f"{name} ") or stripped.lower() == name for name in starters)


def _score_suggestion(
    suggestion: CommandSuggestion,
    match: AutocompleteMatch,
    *,
    line_text: str,
    document_kind: DocumentKind,
) -> tuple[int, int, int, str]:
    candidate = suggestion.match_text or suggestion.label or suggestion.name
    prefix = match.prefix
    candidate_cf = candidate.casefold()
    prefix_cf = prefix.casefold()
    score = suggestion.priority

    if candidate_cf == prefix_cf:
        score += 220
    elif candidate_cf.startswith(prefix_cf):
        score += 120

    if candidate.startswith(prefix):
        score += 35

    if match.kind == "command":
        if suggestion.kind == "command":
            score += 150
    else:
        if suggestion.kind == "function":
            score += 90
        elif suggestion.kind == "variable":
            score += 70
        elif suggestion.kind == "snippet":
            score += 65
        elif suggestion.kind == "module":
            score += 55
        elif suggestion.kind == "keyword":
            score += 35

    next_char = _next_non_space_char(line_text, match.token_end_col)
    if next_char == "(":
        if suggestion.kind == "function":
            score += 75
        elif suggestion.kind == "variable":
            score -= 40

    if document_kind == "mtex_document" and suggestion.kind == "keyword":
        score -= 25

    exact_case_bias = 1 if candidate.startswith(prefix) else 0
    length_bias = -len(candidate)
    return (score, exact_case_bias, length_bias, candidate.casefold())


def _dedupe_suggestions(
    suggestions: Sequence[CommandSuggestion],
    match: AutocompleteMatch,
    *,
    line_text: str,
    document_kind: DocumentKind,
) -> list[CommandSuggestion]:
    ranked: dict[str, tuple[tuple[int, int, int, str], CommandSuggestion]] = {}
    for suggestion in suggestions:
        key = (suggestion.label or suggestion.name).casefold()
        score = _score_suggestion(suggestion, match, line_text=line_text, document_kind=document_kind)
        current = ranked.get(key)
        if current is None or score > current[0]:
            ranked[key] = (score, suggestion)
    ordered = sorted(ranked.values(), key=lambda item: item[0], reverse=True)
    return [suggestion for _score, suggestion in ordered]


def build_autocomplete_suggestions(
    request: AutocompleteRequest,
    *,
    catalog: Sequence[CommandSuggestion] = COMMAND_CATALOG,
) -> list[CommandSuggestion]:
    percent_comments = request.document_kind == "mtex_document" and not _looks_like_code_line(request.line_text)
    match = detect_autocomplete_match(request.line_text, request.cursor_col, percent_comments=percent_comments)
    if match is None:
        return []

    if match.kind == "command":
        raw = [item for item in catalog if _match_prefix(item.match_text or item.name, match.prefix)]
        return _dedupe_suggestions(raw, match, line_text=request.line_text, document_kind=request.document_kind)

    if match.kind == "member":
        raw = _stdlib_member_suggestions(match.qualifier, match.prefix)
        return _dedupe_suggestions(raw, match, line_text=request.line_text, document_kind=request.document_kind)

    should_suggest_identifiers = request.document_kind == "script" or _looks_like_code_line(request.line_text)
    raw: list[CommandSuggestion] = []
    if should_suggest_identifiers and request.document_text:
        raw.extend(_document_symbol_suggestions(match.prefix, request.document_text))
    raw.extend(_workspace_suggestions(match.prefix, request.workspace_items))
    if should_suggest_identifiers:
        raw.extend(_snippet_suggestions(match.prefix))
        raw.extend(_builtin_suggestions(match.prefix))
        raw.extend(_keyword_suggestions(match.prefix))
    return _dedupe_suggestions(raw, match, line_text=request.line_text, document_kind=request.document_kind)


def filter_command_suggestions(
    prefix: str,
    suggestions: Sequence[CommandSuggestion] = COMMAND_CATALOG,
) -> list[CommandSuggestion]:
    request = AutocompleteRequest(line_text=prefix, cursor_col=len(prefix))
    return build_autocomplete_suggestions(request, catalog=suggestions)
