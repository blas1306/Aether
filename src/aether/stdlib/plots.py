from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from plot_backend import PlotBackendError

from ..errors import AetherRuntimeError, AetherTypeError
from ..types import AetherType, AetherValue, ArrayType, MatrixType, NUMERIC_TYPES, VectorType, type_to_string
from .registry import BuiltinDefinition, BuiltinFunction, RuntimeContext, RuntimeFactory


PLOT_NAME = "Plots.plot"
PLOT_BANG_NAME = "Plots.plot!"
SCATTER_NAME = "Plots.scatter"
SCATTER_BANG_NAME = "Plots.scatter!"
BAR_NAME = "Plots.bar"
BAR_BANG_NAME = "Plots.bar!"
HISTOGRAM_NAME = "Plots.histogram"
HISTOGRAM_BANG_NAME = "Plots.histogram!"
FIGURE_NAME = "Plots.figure"
HOLD_NAME = "Plots.hold"
GRID_NAME = "Plots.grid"
TITLE_NAME = "Plots.title"
XLABEL_NAME = "Plots.xlabel"
YLABEL_NAME = "Plots.ylabel"
LEGEND_NAME = "Plots.legend"
SAVEFIG_NAME = "Plots.savefig"

_KWARGS_TYPE = "__kwargs__"
_FUNCTION_TYPE = "function"

_STYLE_KEYWORDS = {"label", "color", "marker", "linestyle", "linewidth", "alpha"}
_AXES_KEYWORDS = {"title", "xlabel", "ylabel", "legend"}
_PLOT_KEYWORDS = _STYLE_KEYWORDS | _AXES_KEYWORDS | {"n"}
_SCATTER_KEYWORDS = _STYLE_KEYWORDS | _AXES_KEYWORDS
_BAR_KEYWORDS = _STYLE_KEYWORDS | _AXES_KEYWORDS
_HISTOGRAM_KEYWORDS = _STYLE_KEYWORDS | _AXES_KEYWORDS | {"bins"}


@dataclass(frozen=True)
class _PlotOptions:
    style: dict[str, Any]
    title: str | None = None
    xlabel: str | None = None
    ylabel: str | None = None
    legend: str | bool | None = None
    n: int | None = None
    bins: int | None = None


def builtin_definitions() -> list[BuiltinDefinition]:
    return [
        BuiltinDefinition(PLOT_NAME, _plot_runtime("plot"), _plot_type, _arity_between(PLOT_NAME, 1, 3)),
        BuiltinDefinition(PLOT_BANG_NAME, _plot_runtime("plot!"), _plot_type, _arity_between(PLOT_BANG_NAME, 1, 3)),
        BuiltinDefinition(SCATTER_NAME, _plot_runtime("scatter"), _scatter_type, _arity_between(SCATTER_NAME, 1, 2)),
        BuiltinDefinition(SCATTER_BANG_NAME, _plot_runtime("scatter!"), _scatter_type, _arity_between(SCATTER_BANG_NAME, 1, 2)),
        BuiltinDefinition(BAR_NAME, _plot_runtime("bar"), _bar_type, _arity_between(BAR_NAME, 1, 2)),
        BuiltinDefinition(BAR_BANG_NAME, _plot_runtime("bar!"), _bar_type, _arity_between(BAR_BANG_NAME, 1, 2)),
        BuiltinDefinition(HISTOGRAM_NAME, _plot_runtime("histogram"), _histogram_type, _exactly_one(HISTOGRAM_NAME)),
        BuiltinDefinition(HISTOGRAM_BANG_NAME, _plot_runtime("histogram!"), _histogram_type, _exactly_one(HISTOGRAM_BANG_NAME)),
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
        def builtin(raw_args: list[AetherValue]) -> AetherValue:
            backend = context.plot_backend
            if backend is None:
                raise AetherRuntimeError("Plots backend is not available in this Aether session.")
            args, kwargs = _split_keyword_args(raw_args)
            try:
                if command in {"plot", "plot!"}:
                    options = _plot_options(kwargs, _PLOT_KEYWORDS)
                    _run_plot(backend, args, options, append=command.endswith("!"))
                    return AetherValue("boolean", True)
                if command in {"scatter", "scatter!"}:
                    options = _plot_options(kwargs, _SCATTER_KEYWORDS)
                    backend.scatter(*_vector_args(args, SCATTER_NAME), append=command.endswith("!"), style=_style_for("scatter", options))
                    _apply_axes_options(backend, options)
                    return AetherValue("boolean", True)
                if command in {"bar", "bar!"}:
                    options = _plot_options(kwargs, _BAR_KEYWORDS)
                    backend.bar(*_vector_args(args, BAR_NAME), append=command.endswith("!"), style=_style_for("bar", options))
                    _apply_axes_options(backend, options)
                    return AetherValue("boolean", True)
                if command in {"histogram", "histogram!"}:
                    options = _plot_options(kwargs, _HISTOGRAM_KEYWORDS)
                    _require_count(HISTOGRAM_NAME, args, 1)
                    backend.histogram(
                        _numeric_vector(args[0], "y"),
                        bins=options.bins,
                        append=command.endswith("!"),
                        style=_style_for("histogram", options),
                    )
                    _apply_axes_options(backend, options)
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


def _run_plot(backend: Any, args: list[AetherValue], options: _PlotOptions, *, append: bool) -> None:
    if len(args) == 3 and args[0].type_name == _FUNCTION_TYPE:
        x_vals, y_vals = _sample_function(args[0], args[1], args[2], options.n or 400)
        backend.plot(x_vals, y_vals, append=append, style=_style_for("plot", options))
        _apply_axes_options(backend, options)
        return

    if len(args) == 2 and isinstance(args[1].type_name, MatrixType) and not _is_vector_matrix(args[1]):
        x_vals = _numeric_vector(args[0], "x")
        columns = _numeric_matrix_columns(args[1], "y")
        for index, y_vals in enumerate(columns):
            if len(x_vals) != len(y_vals):
                raise AetherTypeError(f"x and y must have the same length (x={len(x_vals)}, y={len(y_vals)}).")
            backend.plot(x_vals, y_vals, append=append or index > 0, style=_style_for("plot", options))
        _apply_axes_options(backend, options)
        return

    backend.plot(*_plot_python_args(args), append=append, style=_style_for("plot", options))
    _apply_axes_options(backend, options)


def _plot_python_args(args: list[AetherValue]) -> list[Any]:
    if len(args) == 1:
        return [_numeric_vector(args[0], "y")]
    if len(args) == 2 and args[1].type_name == "string":
        return [_numeric_vector(args[0], "y"), args[1].value]
    if len(args) == 2:
        return [_numeric_vector(args[0], "x"), _numeric_vector(args[1], "y")]
    if len(args) == 3:
        return [_numeric_vector(args[0], "x"), _numeric_vector(args[1], "y"), _require_string_value(args[2], PLOT_NAME)]
    raise AetherTypeError(f"{PLOT_NAME}(...) expects 1 to 3 positional arguments.")


def _vector_args(args: list[AetherValue], label: str) -> list[Any]:
    if len(args) == 1:
        return [_numeric_vector(args[0], "y")]
    if len(args) == 2:
        return [_numeric_vector(args[0], "x"), _numeric_vector(args[1], "y")]
    raise AetherTypeError(f"{label}(...) expects 1 or 2 positional arguments.")


def _split_keyword_args(args: list[AetherValue]) -> tuple[list[AetherValue], dict[str, AetherValue]]:
    if args and args[-1].type_name == _KWARGS_TYPE:
        return args[:-1], dict(args[-1].value)
    return args, {}


def _plot_options(kwargs: dict[str, AetherValue], allowed: set[str]) -> _PlotOptions:
    for name in kwargs:
        if name not in allowed:
            raise AetherTypeError(f"Plots got unknown keyword argument '{name}'.")
    style = {name: _style_value(name, kwargs[name]) for name in _STYLE_KEYWORDS if name in kwargs}
    return _PlotOptions(
        style=style,
        title=_optional_string(kwargs, "title"),
        xlabel=_optional_string(kwargs, "xlabel"),
        ylabel=_optional_string(kwargs, "ylabel"),
        legend=_optional_string_or_boolean(kwargs, "legend"),
        n=_optional_positive_int(kwargs, "n"),
        bins=_optional_positive_int(kwargs, "bins"),
    )


def _style_for(command: str, options: _PlotOptions) -> dict[str, Any]:
    style = dict(options.style)
    if command in {"scatter", "bar", "histogram"}:
        style.pop("linestyle", None)
    if command in {"bar", "histogram"}:
        style.pop("marker", None)
        style.pop("linewidth", None)
    return style


def _apply_axes_options(backend: Any, options: _PlotOptions) -> None:
    if options.title is not None:
        backend.title(options.title)
    if options.xlabel is not None:
        backend.xlabel(options.xlabel)
    if options.ylabel is not None:
        backend.ylabel(options.ylabel)
    if options.legend is not None:
        if isinstance(options.legend, bool):
            backend.legend("on" if options.legend else "off")
        else:
            backend.legend(options.legend)


def _sample_function(function_value: AetherValue, start: AetherValue, end: AetherValue, samples: int) -> tuple[list[float], list[float]]:
    if function_value.type_name != _FUNCTION_TYPE:
        raise AetherTypeError("plot(f, a, b) expects a function as first argument.")
    if samples < 2:
        raise AetherTypeError("Keyword argument 'n' must be at least 2.")
    a = _numeric_scalar(start, "a")
    b = _numeric_scalar(end, "b")
    if samples == 1:
        x_vals = [a]
    else:
        step = (b - a) / (samples - 1)
        x_vals = [a + step * index for index in range(samples)]
    y_vals: list[float] = []
    function_ref = function_value.value
    if getattr(function_ref, "arity", None) != 1:
        name = getattr(function_ref, "name", "function")
        raise AetherTypeError(f"plot(f, a, b) expects function '{name}' to take exactly one argument.")
    for x in x_vals:
        result = function_ref.call([AetherValue("double", float(x))])
        y_vals.append(_numeric_scalar(result, "f(x)"))
    return x_vals, y_vals


def _numeric_scalar(value: AetherValue, label: str) -> float:
    if value.type_name not in NUMERIC_TYPES:
        raise AetherTypeError(f"{label} must be numeric, got '{type_to_string(value.type_name)}'.")
    return float(value.value)


def _numeric_vector(value: AetherValue, label: str) -> list[float]:
    type_name = value.type_name
    if isinstance(type_name, ArrayType):
        if type_name.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{label} must be a numeric vector, got '{type_to_string(type_name)}'.")
        elements = value.value
    elif isinstance(type_name, VectorType):
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


def _numeric_matrix_columns(value: AetherValue, label: str) -> list[list[float]]:
    type_name = value.type_name
    if not isinstance(type_name, MatrixType):
        raise AetherTypeError(f"{label} must be a numeric matrix, got '{type_to_string(type_name)}'.")
    if type_name.element_type not in NUMERIC_TYPES:
        raise AetherTypeError(f"{label} must be a numeric matrix, got '{type_to_string(type_name)}'.")
    rows = value.value
    if not rows:
        raise AetherTypeError(f"{label} cannot be an empty matrix.")
    column_count = len(rows[0].value)
    return [[float(row.value[column_index].value) for row in rows] for column_index in range(column_count)]


def _matrix_vector_elements(value: AetherValue, label: str) -> list[AetherValue]:
    rows = value.value
    if not rows:
        return []
    row_count = len(rows)
    col_count = len(rows[0].value)
    if _is_vector_matrix(value):
        return list(rows[0].value) if row_count == 1 else [row.value[0] for row in rows]
    raise AetherTypeError(f"{label} must be a numeric vector, got matrix shape {row_count}x{col_count}.")


def _is_vector_matrix(value: AetherValue) -> bool:
    if not isinstance(value.type_name, MatrixType):
        return False
    rows = value.value
    if not rows:
        return True
    return value.type_name.vector or len(rows) == 1 or len(rows[0].value) == 1


def _style_value(name: str, value: AetherValue) -> Any:
    if name in {"label", "color", "marker", "linestyle"}:
        return _require_string_value(value, f"keyword '{name}'")
    if name in {"linewidth", "alpha"}:
        return _numeric_scalar(value, f"keyword '{name}'")
    raise AetherTypeError(f"Unknown style keyword '{name}'.")


def _optional_string(kwargs: dict[str, AetherValue], name: str) -> str | None:
    if name not in kwargs:
        return None
    return _require_string_value(kwargs[name], f"keyword '{name}'")


def _optional_string_or_boolean(kwargs: dict[str, AetherValue], name: str) -> str | bool | None:
    if name not in kwargs:
        return None
    value = kwargs[name]
    if value.type_name == "boolean":
        return bool(value.value)
    return _require_string_value(value, f"keyword '{name}'")


def _optional_positive_int(kwargs: dict[str, AetherValue], name: str) -> int | None:
    if name not in kwargs:
        return None
    value = kwargs[name]
    if value.type_name != "int":
        raise AetherTypeError(f"Keyword argument '{name}' expects 'int', got '{type_to_string(value.type_name)}'.")
    result = int(value.value)
    if result <= 0:
        raise AetherTypeError(f"Keyword argument '{name}' must be positive.")
    return result


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
    if len(arg_types) == 3 and arg_types[0] == _FUNCTION_TYPE:
        _require_numeric_scalar_type(arg_types[1], "a")
        _require_numeric_scalar_type(arg_types[2], "b")
        return "boolean"
    if len(arg_types) == 1:
        _require_numeric_vector_type(arg_types[0], "y")
    elif len(arg_types) == 2 and arg_types[1] == "string":
        _require_numeric_vector_type(arg_types[0], "y")
    elif len(arg_types) == 2:
        _require_numeric_vector_type(arg_types[0], "x")
        _require_numeric_vector_or_matrix_type(arg_types[1], "y")
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


def _bar_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _scatter_type(arg_types)


def _histogram_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{HISTOGRAM_NAME}(...) expects exactly one argument.")
    _require_numeric_vector_type(arg_types[0], "y")
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


def _require_numeric_scalar_type(type_name: AetherType | None, label: str) -> None:
    if type_name is None:
        return
    if type_name not in NUMERIC_TYPES:
        raise AetherTypeError(f"{label} must be numeric, got '{type_to_string(type_name)}'.")


def _require_numeric_vector_type(type_name: AetherType | None, label: str) -> None:
    if type_name is None:
        return
    if isinstance(type_name, ArrayType):
        if type_name.element_type not in NUMERIC_TYPES:
            raise AetherTypeError(f"{label} must be a numeric vector, got '{type_to_string(type_name)}'.")
        return
    if isinstance(type_name, VectorType):
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


def _require_numeric_vector_or_matrix_type(type_name: AetherType | None, label: str) -> None:
    if isinstance(type_name, MatrixType) and type_name.element_type in NUMERIC_TYPES:
        return
    _require_numeric_vector_type(type_name, label)


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
