from __future__ import annotations

from dataclasses import dataclass

OPENING_PAIRS = {
    "(": ")",
    "[": "]",
    "{": "}",
    "<": ">",
    '"': '"',
    "'": "'",
}
CLOSING_PAIRS = {closing: opening for opening, closing in OPENING_PAIRS.items()}


@dataclass(frozen=True)
class SmartEnterInsertion:
    text: str
    cursor_offset: int


def closing_for_opening(char: str) -> str | None:
    return OPENING_PAIRS.get(char)


def should_skip_closing(text: str, cursor_pos: int, char: str) -> bool:
    if char not in CLOSING_PAIRS:
        return False
    return 0 <= cursor_pos < len(text) and text[cursor_pos] == char


def empty_pair_at(text: str, cursor_pos: int) -> tuple[str, str] | None:
    if cursor_pos <= 0 or cursor_pos >= len(text):
        return None

    opening = text[cursor_pos - 1]
    closing = text[cursor_pos]
    if OPENING_PAIRS.get(opening) == closing:
        return opening, closing
    return None


def line_indentation(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def smart_enter_in_empty_braces(
    line: str,
    cursor_pos_in_line: int,
    *,
    indent_unit: str = " " * 4,
) -> SmartEnterInsertion | None:
    if cursor_pos_in_line <= 0 or cursor_pos_in_line >= len(line):
        return None
    if line[cursor_pos_in_line - 1] != "{" or line[cursor_pos_in_line] != "}":
        return None

    current_indent = line_indentation(line)
    text = f"\n{current_indent}{indent_unit}\n{current_indent}"
    cursor_offset = 1 + len(current_indent) + len(indent_unit)
    return SmartEnterInsertion(text=text, cursor_offset=cursor_offset)
