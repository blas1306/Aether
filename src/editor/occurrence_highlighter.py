from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Occurrence:
    start: int
    end: int


@dataclass(frozen=True)
class Identifier:
    text: str
    start: int
    end: int


KEYWORDS = {
    "and",
    "bool",
    "break",
    "class",
    "continue",
    "alias",
    "const",
    "double",
    "elif",
    "else",
    "end",
    "false",
    "float",
    "for",
    "function",
    "if",
    "in",
    "int",
    "null",
    "or",
    "package",
    "private",
    "public",
    "struct",
    "interface",
    "implements",
    "enum",
    "repeat",
    "return",
    "true",
    "until",
    "while",
}


def identifier_at(text: str, cursor_pos: int) -> tuple[str, int, int] | None:
    """Return the identifier under the cursor."""
    if not text:
        return None

    cursor_pos = max(0, min(cursor_pos, len(text)))
    for identifier in _scan_identifiers(text):
        if identifier.start <= cursor_pos < identifier.end:
            return identifier.text, identifier.start, identifier.end
    return None


def find_occurrences(text: str, cursor_pos: int) -> list[Occurrence]:
    target = identifier_at(text, cursor_pos)
    if target is None:
        return []

    target_text, _start, _end = target
    if _is_keyword(target_text):
        return []

    return [
        Occurrence(identifier.start, identifier.end)
        for identifier in _scan_identifiers(text)
        if identifier.text == target_text
    ]


def _scan_identifiers(text: str) -> list[Identifier]:
    identifiers: list[Identifier] = []
    pos = 0
    while pos < len(text):
        if _is_identifier_start(text[pos]):
            start = pos
            pos += 1
            while pos < len(text) and _is_identifier_part(text[pos]):
                pos += 1
            identifiers.append(Identifier(text[start:pos], start, pos))
            continue

        if _is_backslash_command_start(text, pos):
            start = pos
            pos += 2
            while pos < len(text) and _is_identifier_part(text[pos]):
                pos += 1
            identifiers.append(Identifier(text[start:pos], start, pos))
            continue

        pos += 1
    return identifiers


def _is_backslash_command_start(text: str, pos: int) -> bool:
    return text[pos] == "\\" and pos + 1 < len(text) and text[pos + 1].isalpha()


def _is_identifier_start(char: str) -> bool:
    return char.isalpha() or char == "_"


def _is_identifier_part(char: str) -> bool:
    return char.isalnum() or char == "_"


def _is_keyword(identifier: str) -> bool:
    return not identifier.startswith("\\") and identifier.lower() in KEYWORDS
