from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import math
import re

from .integer_arithmetic import INT_MAX, INT_MIN


PARSE_STATUS_TYPE = "ParseStatus"
INT_PARSE_RESULT_TYPE = "IntParseResult"
DOUBLE_PARSE_RESULT_TYPE = "DoubleParseResult"
PARSE_INT_BUILTIN = "parseInt"
PARSE_DOUBLE_BUILTIN = "parseDouble"
PARSE_BUILTINS = frozenset({PARSE_INT_BUILTIN, PARSE_DOUBLE_BUILTIN})


class ParseStatus(IntEnum):
    Success = 0
    Empty = 1
    InvalidFormat = 2
    OutOfRange = 3


PARSE_STATUS_VARIANTS = tuple(status.name for status in ParseStatus)
BUILTIN_PARSE_TYPES = frozenset(
    {PARSE_STATUS_TYPE, INT_PARSE_RESULT_TYPE, DOUBLE_PARSE_RESULT_TYPE}
)


@dataclass(frozen=True)
class ParsedNumber:
    value: int | float
    status: ParseStatus


# sign? ((digit+ ('.' digit*)?) | ('.' digit+)) ([eE] sign? digit+)?
# Matching bytes (rather than decoded text) makes ASCII-only acceptance and
# embedded-NUL rejection explicit and length-aware.
_DOUBLE_GRAMMAR = re.compile(
    rb"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?\Z"
)


def parse_int_bytes(data: bytes) -> ParsedNumber:
    """Parse strict decimal i32 syntax without an overflowing accumulator."""

    if not data:
        return ParsedNumber(0, ParseStatus.Empty)

    index = 0
    negative = False
    if data[0] in (ord("+"), ord("-")):
        negative = data[0] == ord("-")
        index = 1
    if index == len(data):
        return ParsedNumber(0, ParseStatus.InvalidFormat)

    # The negative limit has magnitude 2^31, one larger than INT_MAX.
    magnitude_limit = -INT_MIN if negative else INT_MAX
    magnitude = 0
    out_of_range = False
    for byte in data[index:]:
        if byte < ord("0") or byte > ord("9"):
            return ParsedNumber(0, ParseStatus.InvalidFormat)
        digit = byte - ord("0")
        if not out_of_range:
            if magnitude > (magnitude_limit - digit) // 10:
                out_of_range = True
            else:
                magnitude = magnitude * 10 + digit

    if out_of_range:
        return ParsedNumber(0, ParseStatus.OutOfRange)

    return ParsedNumber(-magnitude if negative else magnitude, ParseStatus.Success)


def parse_double_bytes(data: bytes) -> ParsedNumber:
    """Parse the documented locale-independent decimal double grammar.

    Python's decimal-to-binary conversion is used only after the byte grammar
    has been fully normalized here. Python accepts no extra spellings through
    this path: whitespace, underscores, non-ASCII, NUL, NaN and infinity have
    already been rejected. Overflow is normalized to OutOfRange; IEEE-754
    underflow (including signed zero) is a successful parse.
    """

    if not data:
        return ParsedNumber(0.0, ParseStatus.Empty)
    if _DOUBLE_GRAMMAR.fullmatch(data) is None:
        return ParsedNumber(0.0, ParseStatus.InvalidFormat)

    try:
        value = float(data.decode("ascii"))
    except (OverflowError, ValueError):
        return ParsedNumber(0.0, ParseStatus.OutOfRange)
    if math.isinf(value):
        return ParsedNumber(0.0, ParseStatus.OutOfRange)
    return ParsedNumber(value, ParseStatus.Success)
