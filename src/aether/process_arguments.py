from __future__ import annotations

from collections.abc import Sequence

from .collection_value import CollectionObject, destroy_value
from .errors import AetherRuntimeError
from .string_value import StringValue
from .types import AetherValue, ArrayType


PROCESS_ARGS_BUILTIN = "System.args"
PROCESS_ARGS_TYPE = ArrayType("string")


def normalize_program_arguments(arguments: Sequence[str] | None) -> tuple[bytes, ...]:
    """Validate the host boundary and retain an immutable UTF-8 process snapshot."""

    normalized: list[bytes] = []
    for index, argument in enumerate(arguments or ()):
        if not isinstance(argument, str):
            raise TypeError("Aether program arguments must be strings")
        if "\x00" in argument:
            raise AetherRuntimeError(
                f"Aether startup error: process argument {index} contains NUL."
            )
        try:
            normalized.append(argument.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as exc:
            raise AetherRuntimeError(
                f"Aether startup error: process argument {index} is not valid UTF-8."
            ) from exc
    return tuple(normalized)


def process_args_snapshot(arguments: Sequence[bytes]) -> AetherValue:
    """Return a new owning Array<string> snapshot for one System.args() call."""

    elements = [
        AetherValue("string", StringValue.from_utf8(argument))
        for argument in arguments
    ]
    try:
        snapshot = CollectionObject("Array", "string", elements)
    finally:
        # CollectionObject copy-in retained each dynamic string. Drop the
        # temporary construction owners so the new Array owns exactly one.
        for element in reversed(elements):
            destroy_value(element)
    return AetherValue(PROCESS_ARGS_TYPE, snapshot)


def process_args_ir_snapshot(arguments: Sequence[bytes]) -> CollectionObject:
    """Raw-value equivalent used by the executable IR interpreter."""

    elements = [StringValue.from_utf8(argument) for argument in arguments]
    try:
        return CollectionObject("Array", "string", elements)
    finally:
        for element in reversed(elements):
            destroy_value(element)
