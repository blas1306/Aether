from __future__ import annotations

from collections.abc import Callable
from typing import Any

from plot_backend import PlotBackendError

from ..errors import AetherRuntimeError, AetherTypeError
from ..types import AetherType, AetherValue, ArrayType, MatrixType, NUMERIC_TYPES, type_to_string
from .registry import BuiltinDefinition, BuiltinFunction, RuntimeContext, RuntimeFactory


PLOT_NAME = "Plots.plot"
SCATTER_NAME = "Plots.scatter"
FIGURE_NAME = "Plots.figure"
HOLD_NAME = "Plots.hold"
GRID_NAME = "Plots.grid"
TITLE_NAME = "Plots.title"
XLABEL_NAME = "Plots.xlabel"
YLABEL_NAME = "Plots.ylabel"
LEGEND_NAME = "Plots.legend"
SAVEFIG_NAME = "Plots.savefig"


def builtin_definitions() -> list[BuiltinDefinition]:
    return [
        BuiltinDefinition(PLOT_NAME, _plot_runtime("plot"), _plot_type, _arity_between(PLOT_NAME, 1, 3)),
        BuiltinDefinition(SCATTER_NAME, _plot_runtime("scatter"), _scatter_type, _arity_between(SCATTER_NAME, 1, 2)),
        BuiltinDefinition(FIGURE_NAME, _plot_runtime("figure"), _figure_type, _exactly_one(FIGURE_NAME)),
        BuiltinDefinition(HOLD_NAME, _plot_runtime("hold"), _on_off_type(HOLD_NAME), _exactly_one(HOLD_NAME)),
        BuiltinDefinition(GRID_NAME, _plot_runtime("grid"), _on_off_type(GRID_NAME), _exactly_one(GRID_NAME)),
        BuiltinDefinition(TITLE_NAME, _plot_runtime("title"), _text_type(TITLE_NAME), _exactly_one(TITLE_NAME)),
        BuiltinDefinition(XLABEL_NAME, _plot_runtime("xlabel"), _text_type(XLABEL_NAME), _exactly_one(XLABEL_NAME)),
        BuiltinDefinition(YLABEL_NAME, _plot_runtime("ylabel"), _text_type(YLABEL_NAME), _exactly_one(YLABEL_NAME)),
        BuiltinDefinition(LEGEND_NAME, _plot_runtime("legend"), _legend_type),
        BuiltinDefinition(SAVEFIG_NAME, _plot_runtime("savefig"), _savefig_type, _exactly_one(SAVEFIG_NAME)),
    ]


def _plot_runtime(command: str) -> RuntimeFactory:
    def factory(context: RuntimeContext) -> BuiltinFunction:
        def builtin(args: list[AetherValue]) -> AetherValue:
            backend = context.plot_backend
            if backend is None:
                raise AetherRuntimeError("Plots backend is not available in this Aether session.")
            try:
                if command == "plot":
                    _validate_plot_runtime_args(PLOT_NAME, args)
                    backend.plot(*_plot_python_args(args))
                    return AetherValue("boolean", True)
                if command == "scatter":
                    _validate_scatter_runtime_args(args)
                    backend.scatter(*[_numeric_vector(arg, "x" if index == 0 and len(args) == 2 else "y") for index, arg in enumerate(args)])
                    return AetherValue("boolean", True)
                if command == "figure":
                    _require_count(FIGURE_NAME, args, 1)
                    _require_type(args[0], "int", FIGURE_NAME)
                    backend.set_figure(args[0].value)
                    return AetherValue("boolean", True)
                if command == "hold":
                    _require_count(HOLD_NAME, args, 1)
                    backend.set_hold(_on_off_value(args[0], HOLD_NAME))
                    return AetherValue("boolean", True)
                if command == "grid":
                    _require_count(GRID_NAME, args, 1)
                    backend.set_grid(_on_off_value(args[0], GRID_NAME))
                    return AetherValue("boolean", True)
                if command == "title":
                    backend.title(_single_string(args, TITLE_NAME))
                    return AetherValue("boolean", True)
                if command == "xlabel":
                    backend.xlabel(_single_string(args, XLABEL_NAME))
                    return AetherValue("boolean", True)
                if command == "ylabel":
                    backend.ylabel(_single_string(args, YLABEL_NAME))
                    return AetherValue("boolean", True)
                if command == "legend":
                    backend.legend(*[_require_string_value(arg, LEGEND_NAME) for arg in args])
                    return AetherValue("boolean", True)
                if command == "savefig":
                    path = backend.savefig(_single_string(args, SAVEFIG_NAME))
                    return AetherValue("string", path)
            except PlotBackendError as exc:
                raise AetherRuntimeError(str(exc)) from exc
            raise AetherRuntimeError(f"Unsupported Plots command '{command}'.")

        return builtin

    return factory


def _plot_python_args(args: list[AetherValue]) -> list[Any]:
    if len(args) == 1:
        return [_numeric_vector(args[0], "y")]
    if len(args) == 2 and args[1].type_name == "string":
        return [_numeric_vector(args[0], "y"), args[1].value]
    if len(args) == 2:
        return [_numeric_vector(args[0], "x"), _numeric_vector(args[1], "y")]
    return [_numeric_vector(args[0], "x"), _numeric_vector(args[1], "y"), _require_string_value(args[2], PLOT_NAME)]


def _validate_plot_runtime_args(label: str, args: list[AetherValue]) -> None:
    if len(args) not in {1, 2, 3}:
        raise AetherTypeError(f"{label}(...) expects 1 to 3 arguments.")
    if len(args) == 1:
        _numeric_vector(args[0], "y")
        return
    if len(args) == 2:
        _numeric_vector(args[0], "y" if args[1].type_name == "string" else "x")
        if args[1].type_name != "string":
            _numeric_vector(args[1], "y")
        return
    _numeric_vector(args[0], "x")
    _numeric_vector(args[1], "y")
    _require_string_value(args[2], label)


def _validate_scatter_runtime_args(args: list[AetherValue]) -> None:
    if len(args) not in {1, 2}:
        raise AetherTypeError(f"{SCATTER_NAME}(...) expects 1 or 2 arguments.")
    if len(args) == 1:
        _numeric_vector(args[0], "y")
        return
    _numeric_vector(args[0], "x")
    _numeric_vector(args[1], "y")


def _numeric_vector(value: AetherValue, label: str) -> list[float]:
    type_name = value.type_name
    if isinstance(type_name, ArrayType):
        if type_name.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{label} must be a numeric vector, got '{type_to_string(type_name)}'.")
        elements = value.value
    elif isinstance(type_name, MatrixType):
        if type_name.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{label} must be a numeric vector, got '{type_to_string(type_name)}'.")
        elements = _matrix_vector_elements(value, label)
    else:
        raise AetherTypeError(f"{label} must be a numeric vector, got '{type_to_string(type_name)}'.")
    if not elements:
        raise AetherTypeError(f"{label} cannot be an empty vector.")
    return [float(element.value) for element in elements]


def _matrix_vector_elements(value: AetherValue, label: str) -> list[AetherValue]:
    rows = value.value
    if not rows:
        return []
    row_count = len(rows)
    col_count = len(rows[0].value)
    if value.type_name.vector or row_count == 1:
        return list(rows[0].value) if row_count == 1 else [row.value[0] for row in rows]
    if col_count == 1:
        return [row.value[0] for row in rows]
    raise AetherTypeError(f"{label} must be a numeric vector, got matrix shape {row_count}x{col_count}.")


def _on_off_value(value: AetherValue, label: str) -> bool | str:
    if value.type_name == "boolean":
        return bool(value.value)
    if value.type_name == "string":
        return str(value.value)
    raise AetherTypeError(f"{label}(...) expects a boolean or string argument.")


def _single_string(args: list[AetherValue], label: str) -> str:
    _require_count(label, args, 1)
    return _require_string_value(args[0], label)


def _require_string_value(value: AetherValue, label: str) -> str:
    _require_type(value, "string", label)
    return str(value.value)


def _require_type(value: AetherValue, expected: str, label: str) -> None:
    if value.type_name != expected:
        raise AetherTypeError(f"{label}(...) expects '{expected}', got '{type_to_string(value.type_name)}'.")


def _require_count(label: str, args: list[AetherValue], expected: int) -> None:
    if len(args) != expected:
        raise AetherTypeError(f"{label}(...) expects exactly {expected} argument(s).")


def _plot_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) not in {1, 2, 3}:
        raise AetherTypeError(f"{PLOT_NAME}(...) expects 1 to 3 arguments.")
    if len(arg_types) == 1:
        _require_numeric_vector_type(arg_types[0], "y")
    elif len(arg_types) == 2 and arg_types[1] == "string":
        _require_numeric_vector_type(arg_types[0], "y")
    elif len(arg_types) == 2:
        _require_numeric_vector_type(arg_types[0], "x")
        _require_numeric_vector_type(arg_types[1], "y")
    else:
        _require_numeric_vector_type(arg_types[0], "x")
        _require_numeric_vector_type(arg_types[1], "y")
        _require_argument_type(arg_types[2], "string", PLOT_NAME)
    return "boolean"


def _scatter_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) not in {1, 2}:
        raise AetherTypeError(f"{SCATTER_NAME}(...) expects 1 or 2 arguments.")
    if len(arg_types) == 1:
        _require_numeric_vector_type(arg_types[0], "y")
    else:
        _require_numeric_vector_type(arg_types[0], "x")
        _require_numeric_vector_type(arg_types[1], "y")
    return "boolean"


def _figure_type(arg_types: list[AetherType | None]) -> AetherType | None:
    _require_argument_type(arg_types[0] if arg_types else None, "int", FIGURE_NAME)
    return "boolean"


def _on_off_type(label: str) -> Callable[[list[AetherType | None]], AetherType | None]:
    def infer(arg_types: list[AetherType | None]) -> AetherType | None:
        if len(arg_types) != 1:
            raise AetherTypeError(f"{label}(...) expects exactly one argument.")
        argument_type = arg_types[0]
        if argument_type is None:
            return None
        if argument_type not in {"boolean", "string"}:
            raise AetherTypeError(f"{label}(...) expects a boolean or string argument.")
        return "boolean"

    return infer


def _text_type(label: str) -> Callable[[list[AetherType | None]], AetherType | None]:
    def infer(arg_types: list[AetherType | None]) -> AetherType | None:
        if len(arg_types) != 1:
            raise AetherTypeError(f"{label}(...) expects exactly one argument.")
        _require_argument_type(arg_types[0], "string", label)
        return "boolean"

    return infer


def _legend_type(arg_types: list[AetherType | None]) -> AetherType | None:
    for argument_type in arg_types:
        _require_argument_type(argument_type, "string", LEGEND_NAME)
    return "boolean"


def _savefig_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{SAVEFIG_NAME}(...) expects exactly one argument.")
    _require_argument_type(arg_types[0], "string", SAVEFIG_NAME)
    return "string"


def _require_numeric_vector_type(type_name: AetherType | None, label: str) -> None:
    if type_name is None:
        return
    if isinstance(type_name, ArrayType):
        if type_name.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{label} must be a numeric vector, got '{type_to_string(type_name)}'.")
        return
    if isinstance(type_name, MatrixType):
        if type_name.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{label} must be a numeric vector, got '{type_to_string(type_name)}'.")
        if type_name.rows is not None and type_name.cols is not None and type_name.rows > 1 and type_name.cols > 1:
            raise AetherTypeError(f"{label} must be a numeric vector, got matrix shape {type_name.rows}x{type_name.cols}.")
        return
    raise AetherTypeError(f"{label} must be a numeric vector, got '{type_to_string(type_name)}'.")


def _require_argument_type(type_name: AetherType | None, expected: str, label: str) -> None:
    if type_name is None:
        return
    if type_name != expected:
        raise AetherTypeError(f"{label}(...) expects '{expected}', got '{type_to_string(type_name)}'.")


def _exactly_one(label: str):
    def validate(arg_count: int) -> None:
        if arg_count != 1:
            raise AetherTypeError(f"{label}(...) expects exactly one argument.")

    return validate


def _arity_between(label: str, minimum: int, maximum: int):
    def validate(arg_count: int) -> None:
        if arg_count < minimum or arg_count > maximum:
            raise AetherTypeError(f"{label}(...) expects {minimum} to {maximum} arguments.")

    return validate
