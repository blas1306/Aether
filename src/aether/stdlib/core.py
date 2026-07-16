from __future__ import annotations

from collections.abc import Callable
import cmath
import math
from math import ceil, cos, exp, factorial as math_factorial, floor, log, log10, sin, sqrt, tan

from ..array_safety import checked_array_length_to_int
from ..errors import AetherRuntimeError, AetherTypeError
from ..equality import aether_values_equal
from ..formatting import format_value
from ..integer_arithmetic import INT_MAX, INT_MIN, INTEGER_OVERFLOW_MESSAGE
from ..list_safety import checked_list_index_to_int, checked_list_length_to_int
from ..process_arguments import PROCESS_ARGS_BUILTIN, PROCESS_ARGS_TYPE, process_args_snapshot
from ..scalar_math import SCALAR_MATH_CONSTANTS
from ..string_parsing import (
    DOUBLE_PARSE_RESULT_TYPE,
    INT_PARSE_RESULT_TYPE,
    PARSE_DOUBLE_BUILTIN,
    PARSE_INT_BUILTIN,
    PARSE_STATUS_TYPE,
    ParseStatus,
    parse_double_bytes,
    parse_int_bytes,
)
from ..string_value import (
    STRING_SPLIT_BUILTIN,
    STRING_TRIM_BUILTIN,
    StringValue,
    aether_string_split,
    aether_string_trim,
)
from ..text_file_io import FILE_STATUS_TYPE, FileStatus
from ..types import (
    AetherType,
    AetherValue,
    ArrayType,
    ClassType,
    InterfaceType,
    ListType,
    MatrixType,
    NUMERIC_TYPES,
    REAL_NUMERIC_TYPES,
    TransposeVectorType,
    VectorType,
    EnumIdentity,
    EnumType,
    EnumValue,
    StructInstance,
    VOID_VALUE,
    can_implicitly_convert,
    coerce_implicit,
    explicit_cast,
    is_array_type,
    is_list_type,
    shape_dimension_count,
    shape_dimensions,
    shape_vector_value,
    type_to_string,
)
from .registry import (
    BuiltinConstantDefinition,
    BuiltinDefinition,
    BuiltinFunction,
    MutationKind,
    OutputWriter,
    RuntimeContext,
    RuntimeFactory,
)


CAST_BUILTINS = {"int", "float", "double", "string", "boolean"}


def builtin_definitions() -> list[BuiltinDefinition]:
    definitions = [
        BuiltinDefinition("print", _make_print_runtime, _print_type),
        BuiltinDefinition("println", _make_println_runtime, _print_type),
        BuiltinDefinition(
            PROCESS_ARGS_BUILTIN,
            _make_process_args_runtime,
            _process_args_type,
            _exactly_zero(PROCESS_ARGS_BUILTIN),
        ),
        BuiltinDefinition("input", _constant_runtime(_input_runtime), _input_type, _zero_or_one("input")),
        BuiltinDefinition("length", _constant_runtime(length_builtin), _length_type, _exactly_one("length")),
        BuiltinDefinition("is_empty", _constant_runtime(is_empty_builtin), _is_empty_type, _exactly_one("is_empty")),
        BuiltinDefinition("copy", _constant_runtime(copy_builtin), _copy_type, _exactly_one("copy")),
        BuiltinDefinition("push", _constant_runtime(push_builtin), _push_type, _exactly_two("push"), MutationKind.STRUCTURAL),
        BuiltinDefinition("pop", _constant_runtime(pop_builtin), _pop_type, _exactly_one("pop"), MutationKind.STRUCTURAL),
        BuiltinDefinition("insert", _constant_runtime(insert_builtin), _insert_type, _exactly_three("insert"), MutationKind.STRUCTURAL),
        BuiltinDefinition("remove_at", _constant_runtime(remove_at_builtin), _remove_at_type, _exactly_two("remove_at"), MutationKind.STRUCTURAL),
        BuiltinDefinition("contains", _constant_runtime(contains_builtin), _contains_type, _exactly_two("contains")),
        BuiltinDefinition("index_of", _constant_runtime(index_of_builtin), _index_of_type, _exactly_two("index_of")),
        BuiltinDefinition("clear", _constant_runtime(clear_builtin), _clear_type, _exactly_one("clear"), MutationKind.STRUCTURAL),
        BuiltinDefinition("reverse", _constant_runtime(reverse_builtin), _reverse_type, _exactly_one("reverse"), MutationKind.ELEMENT),
        BuiltinDefinition("sort", _constant_runtime(sort_builtin), _sort_type, _exactly_one("sort"), MutationKind.ELEMENT),
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
        BuiltinDefinition(PARSE_INT_BUILTIN, _constant_runtime(_parse_int_runtime), _parse_int_type, _exactly_one(PARSE_INT_BUILTIN)),
        BuiltinDefinition(PARSE_DOUBLE_BUILTIN, _constant_runtime(_parse_double_runtime), _parse_double_type, _exactly_one(PARSE_DOUBLE_BUILTIN)),
        BuiltinDefinition(
            STRING_TRIM_BUILTIN,
            _constant_runtime(_string_trim_runtime),
            _string_trim_type,
            _exactly_one("string.trim"),
        ),
        BuiltinDefinition(
            STRING_SPLIT_BUILTIN,
            _constant_runtime(_string_split_runtime),
            _string_split_type,
            _exactly_two("string.split"),
        ),
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
    pi_type, pi_value = SCALAR_MATH_CONSTANTS["Math.pi"]
    constants = [
        BuiltinConstantDefinition("Math.pi", pi_type, pi_value),
    ]
    status_type = EnumType(PARSE_STATUS_TYPE, EnumIdentity("__builtin__", PARSE_STATUS_TYPE))
    constants.extend(
        BuiltinConstantDefinition(
            f"{PARSE_STATUS_TYPE}.{status.name}",
            status_type,
            EnumValue(
                PARSE_STATUS_TYPE,
                status.name,
                status_type.identity,
                int(status),
                int(status),
            ),
        )
        for status in ParseStatus
    )
    file_status_type = EnumType(
        FILE_STATUS_TYPE, EnumIdentity("__builtin__", FILE_STATUS_TYPE)
    )
    constants.extend(
        BuiltinConstantDefinition(
            f"{FILE_STATUS_TYPE}.{status.name}",
            file_status_type,
            EnumValue(
                FILE_STATUS_TYPE,
                status.name,
                file_status_type.identity,
                int(status),
                int(status),
            ),
        )
        for status in FileStatus
    )
    return constants


def _parse_result(type_name: str, value_type: str, value: int | float, status: ParseStatus) -> AetherValue:
    status_type = EnumType(PARSE_STATUS_TYPE, EnumIdentity("__builtin__", PARSE_STATUS_TYPE))
    status_value = EnumValue(
        PARSE_STATUS_TYPE,
        status.name,
        status_type.identity,
        int(status),
        int(status),
    )
    return AetherValue(
        type_name,
        StructInstance(
            type_name,
            {
                "value": AetherValue(value_type, value),
                "status": AetherValue(status_type, status_value),
            },
            ("value", "status"),
        ),
    )


def _parse_int_runtime(args: list[AetherValue]) -> AetherValue:
    parsed = parse_int_bytes(_parse_string_bytes(args, PARSE_INT_BUILTIN))
    return _parse_result(INT_PARSE_RESULT_TYPE, "int", int(parsed.value), parsed.status)


def _parse_double_runtime(args: list[AetherValue]) -> AetherValue:
    parsed = parse_double_bytes(_parse_string_bytes(args, PARSE_DOUBLE_BUILTIN))
    return _parse_result(DOUBLE_PARSE_RESULT_TYPE, "double", float(parsed.value), parsed.status)


def _string_trim_runtime(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1 or args[0].type_name != "string" or not isinstance(args[0].value, StringValue):
        actual = "no receiver" if not args else type_to_string(args[0].type_name)
        raise AetherTypeError(f"string.trim() requires a string receiver, got '{actual}'.")
    return AetherValue("string", aether_string_trim(args[0].value))


def _string_trim_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError("string.trim() expects zero arguments.")
    if arg_types[0] is not None and arg_types[0] != "string":
        raise AetherTypeError(
            f"string.trim() requires a string receiver, got '{type_to_string(arg_types[0])}'."
        )
    return "string"


def _string_split_runtime(args: list[AetherValue]) -> AetherValue:
    if (
        len(args) != 2
        or args[0].type_name != "string"
        or args[1].type_name != "string"
        or not isinstance(args[0].value, StringValue)
        or not isinstance(args[1].value, StringValue)
    ):
        raise AetherTypeError("string.split(...) requires string receiver and separator.")
    return AetherValue(
        ArrayType("string"),
        aether_string_split(args[0].value, args[1].value, wrap_values=True),
    )


def _string_split_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 2:
        raise AetherTypeError("string.split(...) expects exactly one argument.")
    if arg_types[0] is not None and arg_types[0] != "string":
        raise AetherTypeError("string.split(...) requires a string receiver.")
    if arg_types[1] is not None and arg_types[1] != "string":
        raise AetherTypeError(
            f"string.split(...) expects a string separator, got '{type_to_string(arg_types[1])}'."
        )
    return ArrayType("string")


def _parse_string_bytes(args: list[AetherValue], label: str) -> bytes:
    if len(args) != 1 or args[0].type_name != "string" or not isinstance(args[0].value, StringValue):
        actual = "no argument" if not args else type_to_string(args[0].type_name)
        raise AetherTypeError(f"{label}(...) expects one string argument, got '{actual}'.")
    return args[0].value.utf8_bytes


def _parse_int_type(arg_types: list[AetherType | None]) -> AetherType | None:
    _parse_argument_type(arg_types, PARSE_INT_BUILTIN)
    return INT_PARSE_RESULT_TYPE


def _parse_double_type(arg_types: list[AetherType | None]) -> AetherType | None:
    _parse_argument_type(arg_types, PARSE_DOUBLE_BUILTIN)
    return DOUBLE_PARSE_RESULT_TYPE


def _parse_argument_type(arg_types: list[AetherType | None], label: str) -> None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{label}(...) expects exactly one argument.")
    if arg_types[0] is not None and arg_types[0] != "string":
        raise AetherTypeError(
            f"{label}(...) expects a string argument, got '{type_to_string(arg_types[0])}'."
        )


def _constant_runtime(function: BuiltinFunction) -> RuntimeFactory:
    def factory(_context: RuntimeContext) -> BuiltinFunction:
        return function

    return factory


def _make_process_args_runtime(context: RuntimeContext) -> BuiltinFunction:
    def process_args_runtime(_args: list[AetherValue]) -> AetherValue:
        return process_args_snapshot(context.program_arguments)

    return process_args_runtime


def _process_args_type(arg_types: list[AetherType | None]) -> AetherType:
    if arg_types:
        raise AetherTypeError("System.args() expects zero arguments.")
    return PROCESS_ARGS_TYPE


def _exactly_zero(label: str):
    def validate(arg_count: int) -> None:
        if arg_count != 0:
            raise AetherTypeError(f"{label}() expects zero arguments.")

    return validate


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


def _exactly_three(label: str):
    def validate(arg_count: int) -> None:
        if arg_count != 3:
            raise AetherTypeError(f"{label}(...) expects exactly three arguments.")

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
    if not is_array_type(value.type_name) and not is_list_type(value.type_name):
        raise AetherTypeError(f"length(...) expects a List, Array, or Vector argument, got '{type_to_string(value.type_name)}'.")
    length = len(value.value)
    if is_list_type(value.type_name) or is_array_type(value.type_name):
        try:
            length = (
                checked_list_length_to_int(length)
                if is_list_type(value.type_name)
                else checked_array_length_to_int(length)
            )
        except OverflowError as error:
            raise AetherRuntimeError(str(error)) from error
    return AetherValue("int", length)


def is_empty_builtin(args: list[AetherValue]) -> AetherValue:
    xs = _require_list_arg(args, "is_empty")
    return AetherValue("boolean", len(xs.value) == 0)


def copy_builtin(args: list[AetherValue]) -> AetherValue:
    xs = _require_list_or_array_arg(args, "copy")
    from ..collection_value import CollectionObject

    if isinstance(xs.value, CollectionObject):
        return AetherValue(xs.type_name, xs.value.logical_copy())
    # Compatibility for legacy host-created values.  Source-language
    # collections use CollectionObject after the RC migration.
    return AetherValue(
        xs.type_name,
        CollectionObject(
            "Array" if isinstance(xs.type_name, ArrayType) else "List",
            xs.type_name.element_type,
            xs.value,
        ),
    )


def push_builtin(args: list[AetherValue]) -> AetherValue:
    xs = _require_list_arg(args, "push")
    value = _coerce_list_element_arg(xs, args[1], "push")
    xs.value.append(value)
    return AetherValue("void", VOID_VALUE)


def pop_builtin(args: list[AetherValue]) -> AetherValue:
    xs = _require_list_arg(args, "pop")
    if not xs.value:
        raise AetherRuntimeError("pop() cannot be used on an empty List")
    return xs.value.pop()


def insert_builtin(args: list[AetherValue]) -> AetherValue:
    xs = _require_list_arg(args, "insert")
    index = _require_int_arg(args[1], "insert() index")
    length = len(xs.value)
    if index < 0 or index > length:
        raise AetherRuntimeError(
            f"insert() index must be between 0 and length(xs); got {index} for List of length {length}"
        )
    value = _coerce_list_element_arg(xs, args[2], "insert")
    xs.value.insert(index, value)
    return AetherValue("void", VOID_VALUE)


def remove_at_builtin(args: list[AetherValue]) -> AetherValue:
    xs = _require_list_arg(args, "remove_at")
    index = _require_int_arg(args[1], "remove_at() index")
    length = len(xs.value)
    if index < 0 or index >= length:
        raise AetherRuntimeError(f"remove_at() index {index} out of bounds for List of length {length}")
    return xs.value.pop(index)


def contains_builtin(args: list[AetherValue]) -> AetherValue:
    xs = _require_list_arg(args, "contains")
    value = _coerce_list_element_arg(xs, args[1], "contains")
    return AetherValue("boolean", _list_index_of(xs, value) >= 0)


def index_of_builtin(args: list[AetherValue]) -> AetherValue:
    xs = _require_list_arg(args, "index_of")
    value = _coerce_list_element_arg(xs, args[1], "index_of")
    try:
        index = checked_list_index_to_int(_list_index_of(xs, value))
    except OverflowError as error:
        raise AetherRuntimeError(str(error)) from error
    return AetherValue("int", index)


def _list_index_of(xs: AetherValue, value: AetherValue) -> int:
    for index, element in enumerate(xs.value):
        if aether_values_equal(element, value):
            return index
    return -1


def clear_builtin(args: list[AetherValue]) -> AetherValue:
    xs = _require_list_arg(args, "clear")
    xs.value.clear()
    return AetherValue("void", VOID_VALUE)


def reverse_builtin(args: list[AetherValue]) -> AetherValue:
    xs = _require_list_arg(args, "reverse")
    xs.value.reverse()
    return AetherValue("void", VOID_VALUE)


def sort_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError("sort(...) expects exactly one argument.")
    xs = args[0]
    _require_sortable_sequence_type(xs.type_name, "sort")
    if not isinstance(xs.value, list):
        raise AetherTypeError(
            f"sort(...) expects a List or Array argument, got '{type_to_string(xs.type_name)}'."
        )
    element_type = xs.type_name.element_type
    if element_type == "double":
        # Python's sort is stable.  The tuple supplies the specified total order:
        # non-NaNs numerically first, then all NaNs as one equivalent group.
        xs.value.sort(key=lambda element: (math.isnan(element.value), 0.0 if math.isnan(element.value) else element.value))
    elif element_type == "string":
        xs.value.sort(key=lambda element: element.value.encode("utf-8"))
    else:
        xs.value.sort(key=lambda element: element.value)
    return AetherValue("void", VOID_VALUE)


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
        try:
            result = function(value.value)
        except ValueError:
            # C libm/LLVM return NaN for invalid real domains.  Python's math
            # module raises instead, so normalize the AST implementation here.
            result = float("nan")
        except OverflowError:
            result = math.copysign(float("inf"), value.value)
        return AetherValue("double", result)

    return builtin


def ln_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_real_numeric_unary_arg(args, "ln")
    if value.value == 0:
        return AetherValue("double", float("-inf"))
    if value.value < 0:
        return AetherValue("double", float("nan"))
    return AetherValue("double", log(value.value))


def log_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_real_numeric_unary_arg(args, "log")
    if value.value == 0:
        return AetherValue("double", float("-inf"))
    if value.value < 0:
        return AetherValue("double", float("nan"))
    return AetherValue("double", log10(value.value))


def sqrt_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_numeric_unary_arg(args, "sqrt")
    if value.type_name == "complex" or value.value < 0:
        return AetherValue("complex", cmath.sqrt(value.value))
    return AetherValue("double", sqrt(value.value))


def abs_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_numeric_unary_arg(args, "abs")
    if value.type_name == "complex":
        return AetherValue("double", abs(value.value))
    if value.type_name == "int" and value.value == INT_MIN:
        raise AetherRuntimeError(INTEGER_OVERFLOW_MESSAGE)
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
        quotient = left.value / right.value
        result = (
            float("nan")
            if not math.isfinite(quotient)
            else left.value - floor(quotient) * right.value
        )
    if result_type == "int":
        result = int(result)
    else:
        result = float(result)
    return AetherValue(result_type, result)


def factorial_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_int_unary_arg(args, "Math.factorial")
    if value.value < 0:
        raise AetherRuntimeError("Math.factorial(...) requires a non-negative integer.")
    result = math_factorial(value.value)
    if result > INT_MAX:
        raise AetherRuntimeError(INTEGER_OVERFLOW_MESSAGE)
    return AetherValue("int", result)


def floor_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_real_numeric_unary_arg(args, "Math.floor")
    try:
        result = floor(value.value)
    except (OverflowError, ValueError) as exc:
        raise AetherRuntimeError("Math.floor(...) cannot convert NaN or infinity to int.") from exc
    if result < INT_MIN or result > INT_MAX:
        raise AetherRuntimeError("Math.floor(...) cannot convert NaN or infinity to int.")
    return AetherValue("int", result)


def ceil_builtin(args: list[AetherValue]) -> AetherValue:
    value = _require_real_numeric_unary_arg(args, "Math.ceil")
    try:
        result = ceil(value.value)
    except (OverflowError, ValueError) as exc:
        raise AetherRuntimeError("Math.ceil(...) cannot convert NaN or infinity to int.") from exc
    if result < INT_MIN or result > INT_MAX:
        raise AetherRuntimeError("Math.ceil(...) cannot convert NaN or infinity to int.")
    return AetherValue("int", result)


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


def _require_list_arg(args: list[AetherValue], label: str) -> AetherValue:
    if not args:
        raise AetherTypeError(f"{label}(...) expects a List argument.")
    value = args[0]
    if not isinstance(value.type_name, ListType):
        raise AetherTypeError(f"{label}(...) expects a List argument, got '{type_to_string(value.type_name)}'.")
    return value


def _require_list_or_array_arg(args: list[AetherValue], label: str) -> AetherValue:
    if not args:
        raise AetherTypeError(f"{label}(...) expects a List or Array argument.")
    value = args[0]
    if not isinstance(value.type_name, (ListType, ArrayType)):
        raise AetherTypeError(f"{label}(...) expects a List or Array argument, got '{type_to_string(value.type_name)}'.")
    return value


def _require_int_arg(value: AetherValue, label: str) -> int:
    if value.type_name != "int":
        raise AetherTypeError(f"{label} must be int, got '{type_to_string(value.type_name)}'.")
    return value.value


def _coerce_list_element_arg(xs: AetherValue, value: AetherValue, label: str) -> AetherValue:
    if not isinstance(xs.type_name, ListType):
        raise AetherTypeError(f"{label}(...) expects a List argument, got '{type_to_string(xs.type_name)}'.")
    try:
        return coerce_implicit(value, xs.type_name.element_type)
    except AetherTypeError as exc:
        raise AetherTypeError(
            f"{label}(...) value of type '{type_to_string(value.type_name)}' is not assignable to "
            f"'{type_to_string(xs.type_name.element_type)}'."
        ) from exc


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
    if not is_array_type(argument_type) and not is_list_type(argument_type):
        raise AetherTypeError(f"length(...) expects a List, Array, or Vector argument, got '{type_to_string(argument_type)}'.")
    return "int"


def _is_empty_type(arg_types: list[AetherType | None]) -> AetherType | None:
    _require_list_type_args(arg_types, "is_empty", 1)
    return "boolean"


def _push_type(arg_types: list[AetherType | None]) -> AetherType | None:
    list_type = _require_list_type_args(arg_types, "push", 2)
    if list_type is None:
        return None
    _require_assignable_to_list_element(arg_types[1], list_type, "push")
    return "void"


def _pop_type(arg_types: list[AetherType | None]) -> AetherType | None:
    list_type = _require_list_type_args(arg_types, "pop", 1)
    if list_type is None:
        return None
    return list_type.element_type


def _insert_type(arg_types: list[AetherType | None]) -> AetherType | None:
    list_type = _require_list_type_args(arg_types, "insert", 3)
    if list_type is None:
        return None
    _require_int_type(arg_types[1], "insert() index")
    _require_assignable_to_list_element(arg_types[2], list_type, "insert")
    return "void"


def _remove_at_type(arg_types: list[AetherType | None]) -> AetherType | None:
    list_type = _require_list_type_args(arg_types, "remove_at", 2)
    if list_type is None:
        return None
    _require_int_type(arg_types[1], "remove_at() index")
    return list_type.element_type


def _contains_type(arg_types: list[AetherType | None]) -> AetherType | None:
    list_type = _require_list_type_args(arg_types, "contains", 2)
    if list_type is None:
        return None
    _require_assignable_to_list_element(arg_types[1], list_type, "contains")
    return "boolean"


def _index_of_type(arg_types: list[AetherType | None]) -> AetherType | None:
    list_type = _require_list_type_args(arg_types, "index_of", 2)
    if list_type is None:
        return None
    _require_assignable_to_list_element(arg_types[1], list_type, "index_of")
    return "int"


def _clear_type(arg_types: list[AetherType | None]) -> AetherType | None:
    _require_list_type_args(arg_types, "clear", 1)
    return "void"


def _copy_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _require_list_or_array_type_args(arg_types, "copy", 1)


def _reverse_type(arg_types: list[AetherType | None]) -> AetherType | None:
    _require_list_type_args(arg_types, "reverse", 1)
    return "void"


def _sort_type(arg_types: list[AetherType | None]) -> AetherType | None:
    sequence_type = _require_list_or_array_type_args(arg_types, "sort", 1)
    if sequence_type is None:
        return None
    _require_sortable_sequence_type(sequence_type, "sort")
    return "void"


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


def _require_list_type_args(arg_types: list[AetherType | None], label: str, count: int) -> ListType | None:
    if len(arg_types) != count:
        raise AetherTypeError(f"{label}(...) expects exactly {_argument_count_word(count)} arguments.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if not isinstance(argument_type, ListType):
        raise AetherTypeError(f"{label}(...) expects a List argument, got '{type_to_string(argument_type)}'.")
    return argument_type


def _require_list_or_array_type_args(arg_types: list[AetherType | None], label: str, count: int) -> ListType | ArrayType | None:
    if len(arg_types) != count:
        raise AetherTypeError(f"{label}(...) expects exactly {_argument_count_word(count)} arguments.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if not isinstance(argument_type, (ListType, ArrayType)):
        raise AetherTypeError(f"{label}(...) expects a List or Array argument, got '{type_to_string(argument_type)}'.")
    return argument_type


def _require_int_type(type_name: AetherType | None, label: str) -> None:
    if type_name is not None and type_name != "int":
        raise AetherTypeError(f"{label} must be int, got '{type_to_string(type_name)}'.")


def _require_assignable_to_list_element(type_name: AetherType | None, list_type: ListType, label: str) -> None:
    if type_name is None:
        return
    if not can_implicitly_convert(type_name, list_type.element_type):
        raise AetherTypeError(
            f"{label}(...) value of type '{type_to_string(type_name)}' is not assignable to "
            f"'{type_to_string(list_type.element_type)}'."
        )


def _require_sortable_sequence_type(type_name: AetherType, label: str) -> None:
    if not isinstance(type_name, (ListType, ArrayType)):
        raise AetherTypeError(f"{label}(...) expects a List or Array argument, got '{type_to_string(type_name)}'.")
    if type_name.element_type not in {"int", "double", "string"}:
        raise AetherTypeError(
            f"{label}(...) only supports sequences of int, double, or string; "
            f"got '{type_to_string(type_name)}'."
        )


def _argument_count_word(count: int) -> str:
    return {1: "one", 2: "two", 3: "three"}.get(count, str(count))


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
