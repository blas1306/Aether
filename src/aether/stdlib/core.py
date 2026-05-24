from __future__ import annotations

from collections.abc import Callable
from math import cos, exp, floor, log, log10, sin, sqrt, tan

from ..errors import AetherRuntimeError, AetherTypeError
from ..formatting import format_value
from ..types import (
    AetherType,
    AetherValue,
    MatrixType,
    NUMERIC_TYPES,
    TransposeVectorType,
    VectorType,
    explicit_cast,
    is_array_type,
    is_matrix_type,
    type_to_string,
)
from .registry import BuiltinDefinition, BuiltinFunction, OutputWriter, RuntimeContext, RuntimeFactory


CAST_BUILTINS = {"int", "float", "double", "string", "boolean"}


def builtin_definitions() -> list[BuiltinDefinition]:
    definitions = [
        BuiltinDefinition("print", _make_print_runtime, _print_type),
        BuiltinDefinition("println", _make_println_runtime, _print_type),
        BuiltinDefinition("length", _constant_runtime(length_builtin), _length_type, _exactly_one("length")),
        BuiltinDefinition("rows", _constant_runtime(rows_builtin), _rows_type, _exactly_one("rows")),
        BuiltinDefinition("cols", _constant_runtime(cols_builtin), _cols_type, _exactly_one("cols")),
        BuiltinDefinition("sin", _constant_runtime(math_unary_builtin("sin", sin)), _math_unary_type("sin"), _exactly_one("sin")),
        BuiltinDefinition("cos", _constant_runtime(math_unary_builtin("cos", cos)), _math_unary_type("cos"), _exactly_one("cos")),
        BuiltinDefinition("tan", _constant_runtime(math_unary_builtin("tan", tan)), _math_unary_type("tan"), _exactly_one("tan")),
        BuiltinDefinition("exp", _constant_runtime(math_unary_builtin("exp", exp)), _math_unary_type("exp"), _exactly_one("exp")),
        BuiltinDefinition("ln", _constant_runtime(ln_builtin), _math_unary_type("ln"), _exactly_one("ln")),
        BuiltinDefinition("log", _constant_runtime(log_builtin), _math_unary_type("log"), _exactly_one("log")),
        BuiltinDefinition("sqrt", _constant_runtime(sqrt_builtin), _sqrt_type, _exactly_one("sqrt")),
        BuiltinDefinition("abs", _constant_runtime(abs_builtin), _abs_type, _exactly_one("abs")),
        BuiltinDefinition("Math.mod", _constant_runtime(mod_builtin), _math_binary_type("Math.mod"), _exactly_two("Math.mod")),
    ]
    definitions.extend(
        BuiltinDefinition(
            type_name,
            _constant_runtime(cast_builtin(type_name)),
            _cast_type(type_name),
            _exactly_one(type_name),
        )
        for type_name in sorted(CAST_BUILTINS)
    )
    return definitions


def _constant_runtime(function: BuiltinFunction) -> RuntimeFactory:
    def factory(_context: RuntimeContext) -> BuiltinFunction:
        return function

    return factory


def _exactly_one(label: str):
    def validate(arg_count: int) -> None:
        if arg_count != 1:
            raise AetherTypeError(f"{label}(...) expects exactly one argument.")

    return validate


def _exactly_two(label: str):
    def validate(arg_count: int) -> None:
        if arg_count != 2:
            raise AetherTypeError(f"{label}(...) expects exactly two arguments.")

    return validate


def _make_print_builtin(write_output: OutputWriter) -> BuiltinFunction:
    def print_builtin(args: list[AetherValue]) -> AetherValue:
        if not args:
            raise AetherRuntimeError("print expects at least one argument.")
        write_output("".join(format_value(arg) for arg in args))
        return AetherValue("boolean", True)

    return print_builtin


def _make_print_runtime(context: RuntimeContext) -> BuiltinFunction:
    return _make_print_builtin(context.write_output)


def _make_println_builtin(write_output: OutputWriter) -> BuiltinFunction:
    def println_builtin(args: list[AetherValue]) -> AetherValue:
        if not args:
            raise AetherRuntimeError("println expects at least one argument.")
        write_output("".join(format_value(arg) for arg in args) + "\n")
        return AetherValue("boolean", True)

    return println_builtin


def _make_println_runtime(context: RuntimeContext) -> BuiltinFunction:
    return _make_println_builtin(context.write_output)


def cast_builtin(target_type: str) -> BuiltinFunction:
    def cast(args: list[AetherValue]) -> AetherValue:
        if len(args) != 1:
            raise AetherTypeError(f"{target_type}(...) expects exactly one argument.")
        return explicit_cast(target_type, args[0])

    return cast


def length_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError("length(...) expects exactly one argument.")
    value = args[0]
    if isinstance(value.type_name, VectorType):
        return AetherValue("int", len(value.value))
    if isinstance(value.type_name, TransposeVectorType):
        return AetherValue("int", len(value.value.value))
    if isinstance(value.type_name, MatrixType) and value.type_name.vector:
        return AetherValue("int", _vector_length(value))
    if not is_array_type(value.type_name):
        raise AetherTypeError(f"length(...) expects an array argument, got '{type_to_string(value.type_name)}'.")
    return AetherValue("int", len(value.value))


def rows_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError("rows(...) expects exactly one argument.")
    value = args[0]
    if not is_matrix_type(value.type_name):
        raise AetherTypeError(f"rows(...) expects a matrix argument, got '{type_to_string(value.type_name)}'.")
    return AetherValue("int", len(value.value))


def cols_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError("cols(...) expects exactly one argument.")
    value = args[0]
    if not is_matrix_type(value.type_name):
        raise AetherTypeError(f"cols(...) expects a matrix argument, got '{type_to_string(value.type_name)}'.")
    return AetherValue("int", len(value.value[0].value) if value.value else 0)


def math_unary_builtin(label: str, function: Callable[[float], float]) -> BuiltinFunction:
    def builtin(args: list[AetherValue]) -> AetherValue:
        value = _require_numeric_unary_arg(args, label)
        return AetherValue("double", function(value.value))

    return builtin


def ln_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_numeric_unary_arg(args, "ln")
    if value.value <= 0:
        raise AetherRuntimeError("ln(...) is only defined for positive real numbers.")
    return AetherValue("double", log(value.value))


def log_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_numeric_unary_arg(args, "log")
    if value.value <= 0:
        raise AetherRuntimeError("log(...) is only defined for positive real numbers.")
    return AetherValue("double", log10(value.value))


def sqrt_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_numeric_unary_arg(args, "sqrt")
    if value.value < 0:
        raise AetherRuntimeError("sqrt(...) is only defined for non-negative real numbers in Aether v0.")
    return AetherValue("double", sqrt(value.value))


def abs_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_numeric_unary_arg(args, "abs")
    return AetherValue(value.type_name, abs(value.value))


def mod_builtin(args: list[AetherValue]) -> AetherValue:
    left, right = _require_numeric_binary_args(args, "Math.mod")
    if right.value == 0:
        raise AetherRuntimeError("Math.mod(...) is undefined for divisor zero.")
    result_type = common_primitive_type([left.type_name, right.type_name], label="Math.mod")
    result = left.value - floor(left.value / right.value) * right.value
    if result_type == "int":
        result = int(result)
    else:
        result = float(result)
    return AetherValue(result_type, result)


def _require_numeric_unary_arg(args: list[AetherValue], label: str) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{label}(...) expects exactly one argument.")
    value = args[0]
    if value.type_name not in NUMERIC_TYPES:
        raise AetherTypeError(f"{label}(...) expects a numeric argument, got '{type_to_string(value.type_name)}'.")
    return value


def _require_numeric_binary_args(args: list[AetherValue], label: str) -> tuple[AetherValue, AetherValue]:
    if len(args) != 2:
        raise AetherTypeError(f"{label}(...) expects exactly two arguments.")
    left, right = args
    if left.type_name not in NUMERIC_TYPES or right.type_name not in NUMERIC_TYPES:
        raise AetherTypeError(
            f"{label}(...) expects numeric arguments, got "
            f"'{type_to_string(left.type_name)}' and '{type_to_string(right.type_name)}'."
        )
    return left, right


def _print_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return "boolean"


def _length_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError("length(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if isinstance(argument_type, MatrixType) and argument_type.vector:
        return "int"
    if isinstance(argument_type, (VectorType, TransposeVectorType)):
        return "int"
    if not is_array_type(argument_type):
        raise AetherTypeError(f"length(...) expects an array argument, got '{type_to_string(argument_type)}'.")
    return "int"


def _rows_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _matrix_dimension_type(arg_types, "rows")


def _cols_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _matrix_dimension_type(arg_types, "cols")


def _matrix_dimension_type(arg_types: list[AetherType | None], label: str) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{label}(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if not is_matrix_type(argument_type):
        raise AetherTypeError(f"{label}(...) expects a matrix argument, got '{type_to_string(argument_type)}'.")
    return "int"


def _vector_length(value: AetherValue) -> int:
    rows = value.value
    if not rows:
        return 0
    if len(rows) == 1:
        return len(rows[0].value)
    return len(rows)


def _sqrt_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _math_unary_type("sqrt")(arg_types)


def _math_unary_type(label: str):
    def infer(arg_types: list[AetherType | None]) -> AetherType | None:
        if len(arg_types) != 1:
            raise AetherTypeError(f"{label}(...) expects exactly one argument.")
        argument_type = arg_types[0]
        if argument_type is None:
            return None
        if argument_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{label}(...) expects a numeric argument, got '{type_to_string(argument_type)}'.")
        return "double"

    return infer


def _math_binary_type(label: str):
    def infer(arg_types: list[AetherType | None]) -> AetherType | None:
        if len(arg_types) != 2:
            raise AetherTypeError(f"{label}(...) expects exactly two arguments.")
        left_type, right_type = arg_types
        if left_type is None or right_type is None:
            return None
        if left_type not in NUMERIC_TYPES or right_type not in NUMERIC_TYPES:
            raise AetherTypeError(
                f"{label}(...) expects numeric arguments, got "
                f"'{type_to_string(left_type)}' and '{type_to_string(right_type)}'."
            )
        return common_primitive_type([left_type, right_type], label=label)

    return infer


def _abs_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError("abs(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if argument_type not in NUMERIC_TYPES:
        raise AetherTypeError(f"abs(...) expects a numeric argument, got '{type_to_string(argument_type)}'.")
    return argument_type


def _cast_type(target_type: str):
    def infer(arg_types: list[AetherType | None]) -> AetherType | None:
        if len(arg_types) != 1:
            raise AetherTypeError(f"{target_type}(...) expects exactly one argument.")
        return target_type

    return infer


def common_primitive_type(primitive_types: list[AetherType | None], *, label: str) -> str:
    if not all(isinstance(type_name, str) for type_name in primitive_types):
        raise AetherTypeError(f"{label}(...) expects scalar primitive homogeneous compatible elements.")
    unique_types = set(primitive_types)
    if len(unique_types) == 1:
        return primitive_types[0]
    if unique_types <= NUMERIC_TYPES:
        if "double" in unique_types:
            return "double"
        if "float" in unique_types:
            return "float"
        return "int"
    raise AetherTypeError(f"{label}(...) expects scalar primitive homogeneous compatible elements.")
