from __future__ import annotations

from ..errors import AetherTypeError
from ..string_value import StringValue
from ..text_codec import (
    TEXT_BYTE_AT_BUILTIN,
    TEXT_BYTE_SLICE_BUILTIN,
    TEXT_CONCAT_FRAGMENTS_BUILTIN,
    TEXT_FORMAT_DOUBLE_BUILTIN,
    TEXT_FORMAT_INT_BUILTIN,
    byte_at,
    byte_slice,
    concat_fragments,
    format_double,
    format_int,
)
from ..types import AetherType, AetherValue, ListType, type_to_string
from .registry import BuiltinDefinition, BuiltinFunction, RuntimeContext


def builtin_definitions() -> list[BuiltinDefinition]:
    return [
        BuiltinDefinition(TEXT_BYTE_AT_BUILTIN, _constant(_byte_at), _byte_at_type, _arity(TEXT_BYTE_AT_BUILTIN, 2)),
        BuiltinDefinition(TEXT_BYTE_SLICE_BUILTIN, _constant(_byte_slice), _byte_slice_type, _arity(TEXT_BYTE_SLICE_BUILTIN, 3)),
        BuiltinDefinition(TEXT_FORMAT_INT_BUILTIN, _constant(_format_int), _format_int_type, _arity(TEXT_FORMAT_INT_BUILTIN, 1)),
        BuiltinDefinition(TEXT_FORMAT_DOUBLE_BUILTIN, _constant(_format_double), _format_double_type, _arity(TEXT_FORMAT_DOUBLE_BUILTIN, 1)),
        BuiltinDefinition(TEXT_CONCAT_FRAGMENTS_BUILTIN, _constant(_concat_fragments), _concat_type, _arity(TEXT_CONCAT_FRAGMENTS_BUILTIN, 1)),
    ]


def _constant(function: BuiltinFunction):
    def factory(_context: RuntimeContext) -> BuiltinFunction:
        return function

    return factory


def _arity(label: str, expected: int):
    def validate(actual: int) -> None:
        if actual != expected:
            raise AetherTypeError(f"{label}(...) expects exactly {expected} arguments.")

    return validate


def _expect(arg_types: list[AetherType | None], expected: tuple[AetherType, ...], label: str) -> None:
    if len(arg_types) != len(expected):
        raise AetherTypeError(f"{label}(...) expects exactly {len(expected)} arguments.")
    for index, (actual, wanted) in enumerate(zip(arg_types, expected), start=1):
        if actual is not None and actual != wanted:
            raise AetherTypeError(
                f"{label}(...) argument {index} must be '{type_to_string(wanted)}', "
                f"got '{type_to_string(actual)}'."
            )


def _byte_at_type(arg_types: list[AetherType | None]) -> AetherType:
    _expect(arg_types, ("string", "int"), TEXT_BYTE_AT_BUILTIN)
    return "int"


def _byte_slice_type(arg_types: list[AetherType | None]) -> AetherType:
    _expect(arg_types, ("string", "int", "int"), TEXT_BYTE_SLICE_BUILTIN)
    return "string"


def _format_int_type(arg_types: list[AetherType | None]) -> AetherType:
    _expect(arg_types, ("int",), TEXT_FORMAT_INT_BUILTIN)
    return "string"


def _format_double_type(arg_types: list[AetherType | None]) -> AetherType:
    _expect(arg_types, ("double",), TEXT_FORMAT_DOUBLE_BUILTIN)
    return "string"


def _concat_type(arg_types: list[AetherType | None]) -> AetherType:
    _expect(arg_types, (ListType("string"),), TEXT_CONCAT_FRAGMENTS_BUILTIN)
    return "string"


def _string(value: AetherValue, label: str) -> StringValue:
    if value.type_name != "string" or not isinstance(value.value, StringValue):
        raise AetherTypeError(f"{label}(...) requires a string argument.")
    return value.value


def _byte_at(args: list[AetherValue]) -> AetherValue:
    return AetherValue("int", byte_at(_string(args[0], TEXT_BYTE_AT_BUILTIN), int(args[1].value)))


def _byte_slice(args: list[AetherValue]) -> AetherValue:
    return AetherValue(
        "string",
        byte_slice(
            _string(args[0], TEXT_BYTE_SLICE_BUILTIN),
            int(args[1].value),
            int(args[2].value),
        ),
    )


def _format_int(args: list[AetherValue]) -> AetherValue:
    return AetherValue("string", format_int(int(args[0].value)))


def _format_double(args: list[AetherValue]) -> AetherValue:
    return AetherValue("string", format_double(float(args[0].value)))


def _concat_fragments(args: list[AetherValue]) -> AetherValue:
    return AetherValue("string", concat_fragments(args[0].value))
