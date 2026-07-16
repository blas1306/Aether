from __future__ import annotations

from ..errors import AetherTypeError
from ..string_value import StringValue
from ..text_file_io import (
    APPEND_TEXT_BUILTIN,
    FILE_READ_RESULT_TYPE,
    FILE_STATUS_TYPE,
    READ_TEXT_BUILTIN,
    WRITE_TEXT_ATOMIC_BUILTIN,
    WRITE_TEXT_BUILTIN,
    FileStatus,
    append_text,
    read_text,
    write_text,
    write_text_atomic,
)
from ..types import (
    AetherType,
    AetherValue,
    EnumIdentity,
    EnumType,
    EnumValue,
    StructInstance,
    type_to_string,
)
from .registry import BuiltinDefinition, BuiltinFunction, RuntimeContext


def builtin_definitions() -> list[BuiltinDefinition]:
    return [
        BuiltinDefinition(READ_TEXT_BUILTIN, _constant(_read_runtime), _read_type, _arity(READ_TEXT_BUILTIN, 1)),
        BuiltinDefinition(WRITE_TEXT_BUILTIN, _constant(_write_runtime), _write_type, _arity(WRITE_TEXT_BUILTIN, 2)),
        BuiltinDefinition(
            WRITE_TEXT_ATOMIC_BUILTIN,
            _constant(_write_atomic_runtime),
            _write_atomic_type,
            _arity(WRITE_TEXT_ATOMIC_BUILTIN, 2),
        ),
        BuiltinDefinition(APPEND_TEXT_BUILTIN, _constant(_append_runtime), _write_type, _arity(APPEND_TEXT_BUILTIN, 2)),
    ]


def _constant(function: BuiltinFunction):
    def factory(_context: RuntimeContext) -> BuiltinFunction:
        return function

    return factory


def _arity(label: str, expected: int):
    def validate(actual: int) -> None:
        if actual != expected:
            raise AetherTypeError(
                f"{label}(...) expects exactly {expected} argument"
                f"{'s' if expected != 1 else ''}."
            )

    return validate


def _require_string_types(
    arg_types: list[AetherType | None], label: str, expected: int
) -> None:
    if len(arg_types) != expected:
        raise AetherTypeError(f"{label}(...) expects exactly {expected} arguments.")
    for index, type_name in enumerate(arg_types, start=1):
        if type_name is not None and type_name != "string":
            raise AetherTypeError(
                f"{label}(...) argument {index} must be string, got "
                f"'{type_to_string(type_name)}'."
            )


def _read_type(arg_types: list[AetherType | None]) -> AetherType:
    _require_string_types(arg_types, READ_TEXT_BUILTIN, 1)
    return FILE_READ_RESULT_TYPE


def _write_type(arg_types: list[AetherType | None]) -> AetherType:
    label = WRITE_TEXT_BUILTIN if len(arg_types) != 2 else "text-file write"
    _require_string_types(arg_types, label, 2)
    return EnumType(FILE_STATUS_TYPE, EnumIdentity("__builtin__", FILE_STATUS_TYPE))


def _write_atomic_type(arg_types: list[AetherType | None]) -> AetherType:
    _require_string_types(arg_types, WRITE_TEXT_ATOMIC_BUILTIN, 2)
    return EnumType(FILE_STATUS_TYPE, EnumIdentity("__builtin__", FILE_STATUS_TYPE))


def _require_strings(args: list[AetherValue], label: str, expected: int) -> list[StringValue]:
    if len(args) != expected or any(
        argument.type_name != "string" or not isinstance(argument.value, StringValue)
        for argument in args
    ):
        raise AetherTypeError(f"{label}(...) expects {expected} string argument(s).")
    return [argument.value for argument in args]


def _status_value(status: FileStatus) -> AetherValue:
    type_name = EnumType(FILE_STATUS_TYPE, EnumIdentity("__builtin__", FILE_STATUS_TYPE))
    return AetherValue(
        type_name,
        EnumValue(
            FILE_STATUS_TYPE,
            status.name,
            type_name.identity,
            int(status),
            int(status),
        ),
    )


def _read_runtime(args: list[AetherValue]) -> AetherValue:
    path = _require_strings(args, READ_TEXT_BUILTIN, 1)[0]
    result = read_text(path)
    return AetherValue(
        FILE_READ_RESULT_TYPE,
        StructInstance(
            FILE_READ_RESULT_TYPE,
            {
                "content": AetherValue("string", result.content),
                "status": _status_value(result.status),
            },
            ("content", "status"),
        ),
    )


def _write_runtime(args: list[AetherValue]) -> AetherValue:
    path, content = _require_strings(args, WRITE_TEXT_BUILTIN, 2)
    return _status_value(write_text(path, content))


def _append_runtime(args: list[AetherValue]) -> AetherValue:
    path, content = _require_strings(args, APPEND_TEXT_BUILTIN, 2)
    return _status_value(append_text(path, content))


def _write_atomic_runtime(args: list[AetherValue]) -> AetherValue:
    path, content = _require_strings(args, WRITE_TEXT_ATOMIC_BUILTIN, 2)
    return _status_value(write_text_atomic(path, content))
