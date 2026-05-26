from __future__ import annotations

from dataclasses import dataclass


OPEN_TO_CLOSE = {"(": ")", "[": "]", "{": "}", "<": ">"}
CLOSE_TO_OPEN = {closing: opening for opening, closing in OPEN_TO_CLOSE.items()}
BRACKETS = set(OPEN_TO_CLOSE) | set(CLOSE_TO_OPEN)


@dataclass(frozen=True)
class BracketMatch:
    anchor_pos: int
    match_pos: int | None
    is_valid: bool


def find_bracket_match(text: str, cursor_pos: int) -> BracketMatch | None:
    """Find the bracket under or immediately before the cursor.

    The matcher currently treats the document as plain text. Keeping this logic
    isolated makes it straightforward to skip strings/comments later.
    """
    if not text:
        return None

    cursor_pos = max(0, min(cursor_pos, len(text)))
    anchor_pos = _bracket_anchor_position(text, cursor_pos)
    if anchor_pos is None:
        return None

    anchor = text[anchor_pos]
    if anchor in OPEN_TO_CLOSE:
        match_pos = _find_forward_match(text, anchor_pos, OPEN_TO_CLOSE[anchor])
    else:
        match_pos = _find_backward_match(text, anchor_pos, CLOSE_TO_OPEN[anchor])

    return BracketMatch(anchor_pos=anchor_pos, match_pos=match_pos, is_valid=match_pos is not None)


def _bracket_anchor_position(text: str, cursor_pos: int) -> int | None:
    if cursor_pos > 0 and text[cursor_pos - 1] in BRACKETS:
        return cursor_pos - 1
    if cursor_pos < len(text) and text[cursor_pos] in BRACKETS:
        return cursor_pos
    return None


def _find_forward_match(text: str, anchor_pos: int, closing: str) -> int | None:
    expected_closings = [closing]
    for pos in range(anchor_pos + 1, len(text)):
        char = text[pos]
        if char in OPEN_TO_CLOSE:
            expected_closings.append(OPEN_TO_CLOSE[char])
        elif char in CLOSE_TO_OPEN:
            if not expected_closings or char != expected_closings.pop():
                return None
            if not expected_closings:
                return pos
    return None


def _find_backward_match(text: str, anchor_pos: int, opening: str) -> int | None:
    expected_openings = [opening]
    for pos in range(anchor_pos - 1, -1, -1):
        char = text[pos]
        if char in CLOSE_TO_OPEN:
            expected_openings.append(CLOSE_TO_OPEN[char])
        elif char in OPEN_TO_CLOSE:
            if not expected_openings or char != expected_openings.pop():
                return None
            if not expected_openings:
                return pos
    return None
