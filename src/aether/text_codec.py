from __future__ import annotations

import math

from .errors import AetherRuntimeError
from .string_value import EMPTY_STRING, MAX_STRING_LENGTH, StringValue


TEXT_BYTE_AT_BUILTIN = "text.byteAt"
TEXT_BYTE_SLICE_BUILTIN = "text.byteSlice"
TEXT_FORMAT_INT_BUILTIN = "text.formatInt"
TEXT_FORMAT_DOUBLE_BUILTIN = "text.formatDouble"
TEXT_CONCAT_FRAGMENTS_BUILTIN = "text.concatFragments"

TEXT_CODEC_BUILTINS = frozenset(
    {
        TEXT_BYTE_AT_BUILTIN,
        TEXT_BYTE_SLICE_BUILTIN,
        TEXT_FORMAT_INT_BUILTIN,
        TEXT_FORMAT_DOUBLE_BUILTIN,
        TEXT_CONCAT_FRAGMENTS_BUILTIN,
    }
)


def byte_at(value: StringValue, offset: int) -> int:
    if offset < 0 or offset >= value.byte_length:
        raise AetherRuntimeError("text.byteAt offset is outside the string")
    return value.utf8_bytes[offset]


def byte_slice(value: StringValue, start: int, length: int) -> StringValue:
    if start < 0 or length < 0 or start > value.byte_length - length:
        raise AetherRuntimeError("text.byteSlice range is outside the string")
    if length == 0:
        return EMPTY_STRING
    try:
        return StringValue.from_utf8(value.utf8_bytes[start : start + length])
    except ValueError as exc:
        raise AetherRuntimeError(
            "text.byteSlice boundaries must preserve valid UTF-8"
        ) from exc


def format_int(value: int) -> StringValue:
    return StringValue.dynamic(str(value))


def format_double(value: float) -> StringValue:
    if not math.isfinite(value):
        raise AetherRuntimeError("text.formatDouble requires a finite value")
    # IEEE-754 binary64 needs at most 17 significant decimal digits for exact
    # round-trip.  Python's format is locale independent and matches the native
    # C-locale %.17g contract used by the LLVM runtime.
    return StringValue.dynamic(format(value, ".17g"))


def concat_fragments(values: list[object]) -> StringValue:
    fragments: list[bytes] = []
    total = 0
    for value in values:
        # AST collections contain typed element wrappers; IR collections carry
        # the lowered payload directly.
        if hasattr(value, "type_name") and getattr(value, "type_name") == "string":
            value = getattr(value, "value")
        if not isinstance(value, StringValue):
            raise AetherRuntimeError(
                "text.concatFragments requires List<string>"
            )
        length = value.byte_length
        if total > MAX_STRING_LENGTH - length:
            raise AetherRuntimeError("text.concatFragments length overflow")
        total += length
        fragments.append(value.utf8_bytes)
    if total == 0:
        return EMPTY_STRING
    return StringValue.from_utf8(b"".join(fragments))
