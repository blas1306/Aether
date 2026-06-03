from __future__ import annotations

from collections.abc import Callable
import cmath
from math import ceil, cos, exp, factorial as math_factorial, floor, log, log10, pi, sin, sqrt, tan

from ..errors import AetherRuntimeError, AetherTypeError
from ..formatting import format_value
from ..types import (
    AetherType,
    AetherValue,
    MatrixType,
    NUMERIC_TYPES,
    REAL_NUMERIC_TYPES,
    TransposeVectorType,
    VectorType,
    VOID_VALUE,
    explicit_cast,
    is_array_type,
    shape_dimension_count,
    shape_dimensions,
    shape_vector_value,
    type_to_string,
)
from .registry import BuiltinConstantDefinition, BuiltinDefinition, BuiltinFunction, OutputWriter, RuntimeContext, RuntimeFactory


CAST_BUILTINS = {"int", "float", "double", "string", "boolean"}


def builtin_definitions() -> list[BuiltinDefinition]:
    definitions = [
        BuiltinDefinition("print", _make_print_runtime, _print_type),
        BuiltinDefinition("println", _make_println_runtime, _print_type),
        BuiltinDefinition("input", _constant_runtime(_input_runtime), _input_type, _zero_or_one("input")),
        BuiltinDefinition("length", _constant_runtime(length_builtin), _length_type, _exactly_one("length")),
        BuiltinDefinition("size", _constant_runtime(size_builtin), _size_type, _exactly_one("size")),
        BuiltinDefinition("rows", _constant_runtime(rows_builtin), _rows_type, _exactly_one("rows")),
        BuiltinDefinition("cols", _constant_runtime(cols_builtin), _cols_type, _exactly_one("cols")),
        BuiltinDefinition("columns", _constant_runtime(cols_builtin), _columns_type, _exactly_one("columns")),
        BuiltinDefinition("sin", _constant_runtime(math_unary_builtin("sin", sin)), _math_unary_type("sin"), _exactly_one("sin")),
        BuiltinDefinition("cos", _constant_runtime(math_unary_builtin("cos", cos)), _math_unary_type("cos"), _exactly_one("cos")),
        BuiltinDefinition("tan", _constant_runtime(math_unary_builtin("tan", tan)), _math_unary_type("tan"), _exactly_one("tan")),
        BuiltinDefinition("exp", _constant_runtime(math_unary_builtin("exp", exp)), _math_unary_type("exp"), _exactly_one("exp")),
        BuiltinDefinition("ln", _constant_runtime(ln_builtin), _math_unary_type("ln"), _exactly_one("ln")),
        BuiltinDefinition("log", _constant_runtime(log_builtin), _math_unary_type("log"), _exactly_one("log")),
        BuiltinDefinition("sqrt", _constant_runtime(sqrt_builtin), _sqrt_type, _exactly_one("sqrt")),
        BuiltinDefinition("abs", _constant_runtime(abs_builtin), _abs_type, _exactly_one("abs")),
        BuiltinDefinition("complex", _constant_runtime(complex_builtin), _complex_type, _one_or_two("complex")),
        BuiltinDefinition("real", _constant_runtime(real_builtin), _real_part_type("real"), _exactly_one("real")),
        BuiltinDefinition("imag", _constant_runtime(imag_builtin), _real_part_type("imag"), _exactly_one("imag")),
        BuiltinDefinition("conj", _constant_runtime(conj_builtin), _conj_type, _exactly_one("conj")),
        BuiltinDefinition("angle", _constant_runtime(angle_builtin), _real_part_type("angle"), _exactly_one("angle")),
        BuiltinDefinition("Math.mod", _constant_runtime(mod_builtin), _math_binary_type("Math.mod"), _exactly_two("Math.mod")),
        BuiltinDefinition("Math.factorial", _constant_runtime(factorial_builtin), _factorial_type, _exactly_one("Math.factorial")),
        BuiltinDefinition("Math.floor", _constant_runtime(floor_builtin), _real_to_int_type("Math.floor"), _exactly_one("Math.floor")),
        BuiltinDefinition("Math.ceil", _constant_runtime(ceil_builtin), _real_to_int_type("Math.ceil"), _exactly_one("Math.ceil")),
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


def builtin_constant_definitions() -> list[BuiltinConstantDefinition]:
    return [
        BuiltinConstantDefinition("Math.pi", "double", pi),
    ]


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


def _one_or_two(label: str):
    def validate(arg_count: int) -> None:
        if arg_count not in {1, 2}:
            raise AetherTypeError(f"{label}(...) expects one or two arguments.")

    return validate


def _zero_or_one(label: str):
    def validate(arg_count: int) -> None:
        if arg_count not in {0, 1}:
            raise AetherTypeError(f"{label}(...) expects zero or one argument.")

    return validate


def _input_runtime(_args: list[AetherValue]) -> AetherValue:
    raise AetherRuntimeError("input() requires a typed assignment context.")


def _make_print_builtin(write_output: OutputWriter) -> BuiltinFunction:
    def print_builtin(args: list[AetherValue]) -> AetherValue:
        if not args:
            raise AetherRuntimeError("print expects at least one argument.")
        write_output("".join(format_value(arg) for arg in args))
        return AetherValue("void", VOID_VALUE)

    return print_builtin


def _make_print_runtime(context: RuntimeContext) -> BuiltinFunction:
    return _make_print_builtin(context.write_output)


def _make_println_builtin(write_output: OutputWriter) -> BuiltinFunction:
    def println_builtin(args: list[AetherValue]) -> AetherValue:
        if not args:
            raise AetherRuntimeError("println expects at least one argument.")
        write_output("".join(format_value(arg) for arg in args) + "\n")
        return AetherValue("void", VOID_VALUE)

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


def size_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError("size(...) expects exactly one argument.")
    return shape_vector_value(args[0])


def rows_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError("rows(...) expects exactly one argument.")
    value = args[0]
    dimensions = shape_dimensions(value)
    if len(dimensions) < 2:
        raise AetherTypeError(f"rows(...) expects a matrix argument, got '{type_to_string(value.type_name)}'.")
    return AetherValue("int", dimensions[0])


def cols_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError("cols(...) expects exactly one argument.")
    value = args[0]
    dimensions = shape_dimensions(value)
    if len(dimensions) < 2:
        raise AetherTypeError(f"cols(...) expects a matrix argument, got '{type_to_string(value.type_name)}'.")
    return AetherValue("int", dimensions[1])


def math_unary_builtin(label: str, function: Callable[[float], float]) -> BuiltinFunction:
    def builtin(args: list[AetherValue]) -> AetherValue:
        value = _require_real_numeric_unary_arg(args, label)
        return AetherValue("double", function(value.value))

    return builtin


def ln_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_real_numeric_unary_arg(args, "ln")
    if value.value <= 0:
        raise AetherRuntimeError("ln(...) is only defined for positive real numbers.")
    return AetherValue("double", log(value.value))


def log_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_real_numeric_unary_arg(args, "log")
    if value.value <= 0:
        raise AetherRuntimeError("log(...) is only defined for positive real numbers.")
    return AetherValue("double", log10(value.value))


def sqrt_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_numeric_unary_arg(args, "sqrt")
    if value.type_name == "complex" or value.value < 0:
        return AetherValue("complex", cmath.sqrt(value.value))
    if value.value < 0:
        raise AetherRuntimeError("sqrt(...) is only defined for non-negative real numbers in Aether v0.")
    return AetherValue("double", sqrt(value.value))


def abs_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_numeric_unary_arg(args, "abs")
    if value.type_name == "complex":
        return AetherValue("double", abs(value.value))
    return AetherValue(value.type_name, abs(value.value))


def complex_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) not in {1, 2}:
        raise AetherTypeError("complex(...) expects one or two arguments.")
    if any(arg.type_name not in NUMERIC_TYPES for arg in args):
        raise AetherTypeError("complex(...) expects numeric arguments.")
    if len(args) == 1:
        return AetherValue("complex", complex(args[0].value))
    return AetherValue("complex", complex(args[0].value) + complex(args[1].value) * 1j)


def real_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_numeric_unary_arg(args, "real")
    return AetherValue("double", float(complex(value.value).real))


def imag_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_numeric_unary_arg(args, "imag")
    return AetherValue("double", float(complex(value.value).imag))


def conj_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_numeric_unary_arg(args, "conj")
    if value.type_name == "complex":
        return AetherValue("complex", complex(value.value).conjugate())
    return value


def angle_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_numeric_unary_arg(args, "angle")
    return AetherValue("double", float(cmath.phase(complex(value.value))))


def mod_builtin(args: list[AetherValue]) -> AetherValue:
    left, right = _require_real_numeric_binary_args(args, "Math.mod")
    if right.value == 0:
        raise AetherRuntimeError("Math.mod(...) is undefined for divisor zero.")
    result_type = common_primitive_type([left.type_name, right.type_name], label="Math.mod")
    if left.type_name == "int" and right.type_name == "int":
        result = left.value % right.value
    else:
        result = left.value - floor(left.value / right.value) * right.value
    if result_type == "int":
        result = int(result)
    else:
        result = float(result)
    return AetherValue(result_type, result)


def factorial_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_int_unary_arg(args, "Math.factorial")
    if value.value < 0:
        raise AetherRuntimeError("Math.factorial(...) requires a non-negative integer.")
    return AetherValue("int", math_factorial(value.value))


def floor_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_real_numeric_unary_arg(args, "Math.floor")
    return AetherValue("int", floor(value.value))


def ceil_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_real_numeric_unary_arg(args, "Math.ceil")
    return AetherValue("int", ceil(value.value))


def _require_numeric_unary_arg(args: list[AetherValue], label: str) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError(f"{label}(...) expects exactly one argument.")
    value = args[0]
    if value.type_name not in NUMERIC_TYPES:
        raise AetherTypeError(f"{label}(...) expects a numeric argument, got '{type_to_string(value.type_name)}'.")
    return value


def _require_int_unary_arg(args: list[AetherValue], label: str) -> AetherValue:
    value = _require_numeric_unary_arg(args, label)
    if value.type_name != "int":
        raise AetherTypeError(f"{label}(...) expects an int argument, got '{type_to_string(value.type_name)}'.")
    return value


def _require_real_numeric_unary_arg(args: list[AetherValue], label: str) -> AetherValue:
    value = _require_numeric_unary_arg(args, label)
    if value.type_name not in REAL_NUMERIC_TYPES:
        raise AetherTypeError(f"{label}(...) expects a real numeric argument, got '{type_to_string(value.type_name)}'.")
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


def _require_real_numeric_binary_args(args: list[AetherValue], label: str) -> tuple[AetherValue, AetherValue]:
    left, right = _require_numeric_binary_args(args, label)
    if left.type_name not in REAL_NUMERIC_TYPES or right.type_name not in REAL_NUMERIC_TYPES:
        raise AetherTypeError(
            f"{label}(...) expects real numeric arguments, got "
            f"'{type_to_string(left.type_name)}' and '{type_to_string(right.type_name)}'."
        )
    return left, right


def _print_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return "void"


def _input_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) not in {0, 1}:
        raise AetherTypeError("input(...) expects zero or one argument.")
    if arg_types and arg_types[0] is not None and arg_types[0] != "string":
        raise AetherTypeError(f"input(...) prompt must be string, got '{type_to_string(arg_types[0])}'.")
    return None


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


def _size_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError("size(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return VectorType("int")
    return VectorType("int", shape_dimension_count(argument_type))


def _rows_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _matrix_dimension_type(arg_types, "rows")


def _cols_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _matrix_dimension_type(arg_types, "cols")


def _columns_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _matrix_dimension_type(arg_types, "columns")


def _matrix_dimension_type(arg_types: list[AetherType | None], label: str) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{label}(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if shape_dimension_count(argument_type) < 2:
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
    if len(arg_types) != 1:
        raise AetherTypeError("sqrt(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if argument_type not in NUMERIC_TYPES:
        raise AetherTypeError(f"sqrt(...) expects a numeric argument, got '{type_to_string(argument_type)}'.")
    return "complex" if argument_type == "complex" else "double"


def _math_unary_type(label: str):
    def infer(arg_types: list[AetherType | None]) -> AetherType | None:
        if len(arg_types) != 1:
            raise AetherTypeError(f"{label}(...) expects exactly one argument.")
        argument_type = arg_types[0]
        if argument_type is None:
            return None
        if argument_type not in REAL_NUMERIC_TYPES:
            raise AetherTypeError(f"{label}(...) expects a real numeric argument, got '{type_to_string(argument_type)}'.")
        return "double"

    return infer


def _math_binary_type(label: str):
    def infer(arg_types: list[AetherType | None]) -> AetherType | None:
        if len(arg_types) != 2:
            raise AetherTypeError(f"{label}(...) expects exactly two arguments.")
        left_type, right_type = arg_types
        if left_type is None or right_type is None:
            return None
        if left_type not in REAL_NUMERIC_TYPES or right_type not in REAL_NUMERIC_TYPES:
            raise AetherTypeError(
                f"{label}(...) expects real numeric arguments, got "
                f"'{type_to_string(left_type)}' and '{type_to_string(right_type)}'."
            )
        return common_primitive_type([left_type, right_type], label=label)

    return infer


def _factorial_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError("Math.factorial(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if argument_type != "int":
        raise AetherTypeError(f"Math.factorial(...) expects an int argument, got '{type_to_string(argument_type)}'.")
    return "int"


def _real_to_int_type(label: str):
    def infer(arg_types: list[AetherType | None]) -> AetherType | None:
        if len(arg_types) != 1:
            raise AetherTypeError(f"{label}(...) expects exactly one argument.")
        argument_type = arg_types[0]
        if argument_type is None:
            return None
        if argument_type not in REAL_NUMERIC_TYPES:
            raise AetherTypeError(f"{label}(...) expects a real numeric argument, got '{type_to_string(argument_type)}'.")
        return "int"

    return infer


def _abs_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError("abs(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if argument_type not in NUMERIC_TYPES:
        raise AetherTypeError(f"abs(...) expects a numeric argument, got '{type_to_string(argument_type)}'.")
    return "double" if argument_type == "complex" else argument_type


def _complex_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) not in {1, 2}:
        raise AetherTypeError("complex(...) expects one or two arguments.")
    for argument_type in arg_types:
        if argument_type is not None and argument_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"complex(...) expects numeric arguments, got '{type_to_string(argument_type)}'.")
    return "complex"


def _real_part_type(label: str):
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


def _conj_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError("conj(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if argument_type not in NUMERIC_TYPES:
        raise AetherTypeError(f"conj(...) expects a numeric argument, got '{type_to_string(argument_type)}'.")
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
        if "complex" in unique_types:
            return "complex"
        if "double" in unique_types:
            return "double"
        if "float" in unique_types:
            return "float"
        return "int"
    raise AetherTypeError(f"{label}(...) expects scalar primitive homogeneous compatible elements.")
