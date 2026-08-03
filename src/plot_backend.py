from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

import numpy as np

plt = None
FigureCanvasAgg = None
Figure = None


def _ensure_matplotlib(*, prefer_interactive: bool = False) -> None:
    global plt, FigureCanvasAgg, Figure
    if plt is not None and FigureCanvasAgg is not None and Figure is not None:
        if prefer_interactive and _is_noninteractive_backend(str(plt.get_backend()).lower()):
            try:
                plt.switch_backend("qtagg")
            except Exception:
                pass
        return
    import matplotlib

    backend = str(matplotlib.get_backend()).lower()
    if prefer_interactive and _is_noninteractive_backend(backend):
        try:
            matplotlib.use("qtagg", force=True)
        except Exception:
            pass
    elif "tk" in backend:
        matplotlib.use("qtagg", force=True)
    import matplotlib.pyplot as _plt
    from matplotlib.backends.backend_agg import FigureCanvasAgg as _FigureCanvasAgg
    from matplotlib.figure import Figure as _Figure

    plt = _plt
    FigureCanvasAgg = _FigureCanvasAgg
    Figure = _Figure


def _is_noninteractive_backend(backend: str) -> bool:
    return backend in {"agg", "cairo", "pdf", "pgf", "ps", "svg", "template"} or backend.endswith("agg")


class PlotBackendError(ValueError):
    """Base class for plot backend validation errors."""


class PlotDataError(PlotBackendError):
    """Raised when the plot data is invalid."""


class PlotFormatError(PlotBackendError):
    """Raised when a fmt/linespec string is invalid."""


class PlotBackend:
    """Minimal state for Octave/MATLAB-style 2D plots."""

    _VALID_LINESTYLES = ("--", "-.", "-", ":")
    _VALID_MARKERS = {"o", "x", "."}
    _VALID_COLORS = {"r", "g", "b", "k"}
    _VALID_LEGEND_LOCATIONS = {
        "best",
        "upper right",
        "upper left",
        "lower left",
        "lower right",
        "right",
        "center left",
        "center right",
        "lower center",
        "upper center",
        "center",
    }
    _OCTAVE_LOCATION_ALIASES = {
        "northeast": "upper right",
        "northwest": "upper left",
        "southeast": "lower right",
        "southwest": "lower left",
        "north": "upper center",
        "south": "lower center",
        "east": "center right",
        "west": "center left",
    }

    def __init__(
        self,
        plot_mode: str = "interactive",
        output_dir: str | Path = ".",
        on_image: Callable[[str | bytes], None] | None = None,
    ) -> None:
        self.current_figure: Figure | None = None
        self.current_axes = None
        self.hold = False
        self.grid = False
        self.title_text = ""
        self.xlabel_text = ""
        self.ylabel_text = ""
        self.legend_visible = False
        self.legend_labels: list[str] | None = None
        self.legend_location = "best"
        self.plot_mode = "interactive"
        self.output_dir = Path(".")
        self._last_document_target: Path | None = None
        self._figure_states: dict[int, dict[str, Any]] = {}
        self._active_figure_id = 1
        self.on_image = on_image
        self._interactive_show_requested = False
        self._figure_states[1] = self._new_state()
        self._load_state(1)
        self.set_mode(plot_mode)
        self.set_output_dir(output_dir)

    def set_mode(self, mode: str) -> None:
        self.plot_mode = "document" if str(mode).strip().lower() == "document" else "interactive"

    def set_output_dir(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)

    def reset(self) -> None:
        self._figure_states.clear()
        self._active_figure_id = 1
        self._interactive_show_requested = False
        self._figure_states[1] = self._new_state()
        self._load_state(1)

    def get_active_figure(self) -> int:
        return self._active_figure_id

    def set_figure(self, figure_id: Any) -> int:
        fig_num = self._coerce_figure_id(figure_id)
        self._save_active_state()
        self._active_figure_id = fig_num
        if fig_num not in self._figure_states:
            self._figure_states[fig_num] = self._new_state()
        self._load_state(fig_num)
        if self.plot_mode == "interactive" and self.current_figure is not None:
            _ensure_matplotlib()
            fig_number = getattr(self.current_figure, "number", None)
            if fig_number is not None and plt.fignum_exists(fig_number):
                try:
                    plt.figure(fig_number)
                except Exception:
                    pass
        return fig_num

    def title(self, text: Any) -> None:
        self.title_text = str(text)
        if self.current_axes is not None:
            self.current_axes.set_title(self.title_text)
            self._redraw_interactive()
            self._persist_document_if_needed()

    def xlabel(self, text: Any) -> None:
        self.xlabel_text = str(text)
        if self.current_axes is not None:
            self.current_axes.set_xlabel(self.xlabel_text)
            self._redraw_interactive()
            self._persist_document_if_needed()

    def ylabel(self, text: Any) -> None:
        self.ylabel_text = str(text)
        if self.current_axes is not None:
            self.current_axes.set_ylabel(self.ylabel_text)
            self._redraw_interactive()
            self._persist_document_if_needed()

    def set_grid(self, value: Any) -> None:
        self.grid = self._to_on_off(value, "grid")
        if self.current_axes is not None:
            self.current_axes.grid(self.grid)
            self._redraw_interactive()
            self._persist_document_if_needed()

    def set_hold(self, value: Any) -> None:
        self.hold = self._to_on_off(value, "hold")

    def legend(self, *args: Any) -> None:
        axes = self.current_axes
        if axes is None:
            raise PlotBackendError("There is no active plot to apply legend to.")

        lines = list(axes.get_lines())
        if not args:
            self.legend_visible = True
            self.legend_labels = None
            self._apply_legend_state()
            self._redraw_interactive()
            self._persist_document_if_needed()
            return

        parsed = [self._coerce_legend_text(a) for a in args]
        if len(parsed) == 1 and parsed[0].lower() in {"on", "off", "show", "hide", "toggle"}:
            cmd = parsed[0].lower()
            if cmd in {"on", "show"}:
                self.legend_visible = True
            elif cmd in {"off", "hide"}:
                self.legend_visible = False
            else:
                self.legend_visible = not self.legend_visible
            self._apply_legend_state()
            self._redraw_interactive()
            self._persist_document_if_needed()
            return

        labels, location = self._parse_legend_labels_and_location(parsed)
        if location is not None:
            self.legend_location = location

        if labels is not None:
            if not lines:
                raise PlotBackendError("There are no series to label in legend.")
            if len(labels) > len(lines):
                raise PlotBackendError(
                    f"legend received {len(labels)} label(s), but there are {len(lines)} series."
                )
            self.legend_labels = labels
            for line, label in zip(lines, labels):
                line.set_label(label)

        self.legend_visible = True
        self._apply_legend_state()
        self._redraw_interactive()
        self._persist_document_if_needed()

    def plot(
        self,
        *args: Any,
        output_name: str | None = None,
        append: bool = False,
        style: dict[str, Any] | None = None,
    ) -> str | bytes | None:
        x_vals: np.ndarray
        y_vals: np.ndarray
        fmt: str | None = None

        if len(args) == 1:
            y_vals = self._to_vector(args[0], "y")
            x_vals = np.arange(1, len(y_vals) + 1, dtype=float)
        elif len(args) == 2:
            if isinstance(args[1], str):
                y_vals = self._to_vector(args[0], "y")
                x_vals = np.arange(1, len(y_vals) + 1, dtype=float)
                fmt = args[1]
            else:
                x_vals = self._to_vector(args[0], "x")
                y_vals = self._to_vector(args[1], "y")
        elif len(args) == 3:
            x_vals = self._to_vector(args[0], "x")
            y_vals = self._to_vector(args[1], "y")
            if not isinstance(args[2], str):
                raise PlotFormatError("plot(x, y, fmt): fmt must be a string.")
            fmt = args[2]
        else:
            raise PlotDataError("plot accepts: plot(y), plot(x, y), plot(x, y, fmt).")

        if len(x_vals) != len(y_vals):
            raise PlotDataError(f"x and y must have the same length (x={len(x_vals)}, y={len(y_vals)}).")
        if len(x_vals) == 0:
            raise PlotDataError("x and y cannot be empty.")

        axes = self._ensure_axes()
        if not self.hold and not append:
            axes.cla()

        plot_kwargs = self._parse_fmt(fmt) if fmt is not None else {}
        if style:
            plot_kwargs.update(style)
        axes.plot(x_vals, y_vals, **plot_kwargs)
        if plot_kwargs.get("label"):
            self.legend_visible = True

        self._apply_axes_state()
        return self._render(output_name=output_name)

    def scatter(
        self,
        *args: Any,
        output_name: str | None = None,
        append: bool = False,
        style: dict[str, Any] | None = None,
    ) -> str | bytes | None:
        if len(args) == 1:
            y_vals = self._to_vector(args[0], "y")
            x_vals = np.arange(1, len(y_vals) + 1, dtype=float)
        elif len(args) == 2:
            x_vals = self._to_vector(args[0], "x")
            y_vals = self._to_vector(args[1], "y")
        else:
            raise PlotDataError("scatter accepts: scatter(y), scatter(x, y).")

        if len(x_vals) != len(y_vals):
            raise PlotDataError(f"x and y must have the same length (x={len(x_vals)}, y={len(y_vals)}).")
        if len(x_vals) == 0:
            raise PlotDataError("x and y cannot be empty.")

        axes = self._ensure_axes()
        if not self.hold and not append:
            axes.cla()

        scatter_kwargs = dict(style or {})
        axes.scatter(x_vals, y_vals, **scatter_kwargs)
        if scatter_kwargs.get("label"):
            self.legend_visible = True
            axes.legend(loc=self.legend_location)
        self._apply_axes_state()
        return self._render(output_name=output_name)

    def bar(
        self,
        *args: Any,
        output_name: str | None = None,
        append: bool = False,
        style: dict[str, Any] | None = None,
    ) -> str | bytes | None:
        if len(args) == 1:
            y_vals = self._to_vector(args[0], "y")
            x_vals = np.arange(1, len(y_vals) + 1, dtype=float)
        elif len(args) == 2:
            x_vals = self._to_vector(args[0], "x")
            y_vals = self._to_vector(args[1], "y")
        else:
            raise PlotDataError("bar accepts: bar(y), bar(x, y).")
        if len(x_vals) != len(y_vals):
            raise PlotDataError(f"x and y must have the same length (x={len(x_vals)}, y={len(y_vals)}).")
        if len(x_vals) == 0:
            raise PlotDataError("x and y cannot be empty.")

        axes = self._ensure_axes()
        if not self.hold and not append:
            axes.cla()
        bar_kwargs = dict(style or {})
        axes.bar(x_vals, y_vals, **bar_kwargs)
        if bar_kwargs.get("label"):
            self.legend_visible = True
            axes.legend(loc=self.legend_location)
        self._apply_axes_state()
        return self._render(output_name=output_name)

    def histogram(
        self,
        values: Any,
        *,
        bins: int | None = None,
        output_name: str | None = None,
        append: bool = False,
        style: dict[str, Any] | None = None,
    ) -> str | bytes | None:
        y_vals = self._to_vector(values, "y")
        if len(y_vals) == 0:
            raise PlotDataError("y cannot be empty.")

        axes = self._ensure_axes()
        if not self.hold and not append:
            axes.cla()
        hist_kwargs = dict(style or {})
        if bins is not None:
            hist_kwargs["bins"] = bins
        axes.hist(y_vals, **hist_kwargs)
        if hist_kwargs.get("label"):
            self.legend_visible = True
            axes.legend(loc=self.legend_location)
        self._apply_axes_state()
        return self._render(output_name=output_name)

    def savefig(self, output_name: str) -> str:
        if self.current_figure is None:
            raise PlotBackendError("There is no active figure to save.")
        target = self._build_savefig_path(output_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.current_figure.savefig(target, format="png", bbox_inches="tight")
        self._last_document_target = target
        return str(target)

    def _ensure_axes(self):
        if self.plot_mode == "interactive":
            _ensure_matplotlib(prefer_interactive=True)
            needs_new = (
                self.current_figure is None
                or self.current_axes is None
                or not hasattr(self.current_figure, "number")
                or not plt.fignum_exists(self.current_figure.number)
            )
            if needs_new:
                fig = plt.figure(self._active_figure_id)
                ax = fig.axes[0] if fig.axes else fig.add_subplot(111)
                self.current_figure = fig
                self.current_axes = ax
            return self.current_axes

        if self.current_figure is None or self.current_axes is None:
            _ensure_matplotlib()
            fig = Figure()
            FigureCanvasAgg(fig)
            self.current_figure = fig
            self.current_axes = fig.add_subplot(111)
        return self.current_axes

    def _apply_axes_state(self) -> None:
        if self.current_axes is None:
            return
        self.current_axes.grid(self.grid)
        if self.title_text:
            self.current_axes.set_title(self.title_text)
        if self.xlabel_text:
            self.current_axes.set_xlabel(self.xlabel_text)
        if self.ylabel_text:
            self.current_axes.set_ylabel(self.ylabel_text)
        self._apply_legend_state()

    def _apply_legend_state(self) -> None:
        if self.current_axes is None:
            return
        axes = self.current_axes
        lines = list(axes.get_lines())
        handles, auto_labels = axes.get_legend_handles_labels()
        if not lines and not handles:
            existing = axes.get_legend()
            if existing is not None:
                existing.remove()
            return

        if not self.legend_visible:
            existing = axes.get_legend()
            if existing is not None:
                existing.remove()
            return

        if self.legend_labels and lines:
            for idx, line in enumerate(lines):
                if idx < len(self.legend_labels):
                    line.set_label(self.legend_labels[idx])
                elif line.get_label().startswith("_"):
                    line.set_label(f"data{idx + 1}")
        else:
            for idx, line in enumerate(lines, start=1):
                if line.get_label().startswith("_"):
                    line.set_label(f"data{idx}")

        handles, auto_labels = axes.get_legend_handles_labels()
        if handles:
            axes.legend(loc=self.legend_location)

    def _render(self, output_name: str | None = None) -> str | bytes | None:
        if self.current_figure is None:
            raise PlotBackendError("There is no active figure to render.")

        if self.plot_mode == "document":
            target = self._build_document_path(output_name)
            target.parent.mkdir(parents=True, exist_ok=True)
            self.current_figure.savefig(target, format="png", bbox_inches="tight")
            self._last_document_target = target
            return str(target)

        if hasattr(self.current_figure, "number"):
            _ensure_matplotlib()
            plt.figure(self.current_figure.number)
        self._show_interactive()
        return None

    def _show_interactive(self) -> None:
        _ensure_matplotlib(prefer_interactive=True)
        plt.show(block=False)
        self._interactive_show_requested = True
        plt.pause(0.001)

    def wait_for_interactive_plots(self) -> None:
        if self.plot_mode != "interactive" or not self._interactive_show_requested:
            return
        _ensure_matplotlib(prefer_interactive=True)
        self._interactive_show_requested = False
        plt.show(block=True)

    def _redraw_interactive(self) -> None:
        if self.plot_mode != "interactive":
            return
        fig = self.current_figure
        if fig is None:
            return
        _ensure_matplotlib()
        canvas = getattr(fig, "canvas", None)
        if canvas is None:
            return
        try:
            canvas.draw_idle()
        except Exception:
            try:
                canvas.draw()
            except Exception:
                return
        try:
            canvas.flush_events()
        except Exception:
            pass
        try:
            plt.pause(0.001)
        except Exception:
            pass

    def _persist_document_if_needed(self) -> None:
        if self.plot_mode != "document":
            return
        if self.current_figure is None or self._last_document_target is None:
            return
        target = self._last_document_target
        target.parent.mkdir(parents=True, exist_ok=True)
        self.current_figure.savefig(target, format="png", bbox_inches="tight")

    def _build_document_path(self, output_name: str | None) -> Path:
        if output_name:
            name = Path(output_name).name
            if not name.lower().endswith(".png"):
                name = f"{name}.png"
            return self.output_dir / name
        unique = f"plot_{uuid.uuid4().hex[:10]}.png"
        return self.output_dir / unique

    def _build_savefig_path(self, output_name: str) -> Path:
        name = str(output_name).strip()
        if not name:
            raise PlotBackendError("savefig(path): path cannot be empty.")
        target = Path(name)
        if target.suffix.lower() != ".png":
            target = target.with_suffix(".png")
        if not target.is_absolute():
            target = self.output_dir / target
        return target

    def _coerce_legend_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value.strip().strip("\"'")
        return str(value).strip().strip("\"'")

    def _parse_legend_labels_and_location(self, parsed_tokens: list[str]) -> tuple[list[str] | None, str | None]:
        labels = list(parsed_tokens)
        location: str | None = None

        if len(labels) >= 2 and labels[-2].lower() == "location":
            location = self._normalize_legend_location(labels[-1])
            labels = labels[:-2]
        elif len(labels) == 1 and self._looks_like_location(labels[0]):
            location = self._normalize_legend_location(labels[0])
            labels = []

        if not labels:
            return None, location

        return [str(label) for label in labels], location

    def _looks_like_location(self, token: str) -> bool:
        normalized = " ".join(token.replace("-", " ").replace("_", " ").lower().split())
        if normalized in self._VALID_LEGEND_LOCATIONS:
            return True
        return normalized in self._OCTAVE_LOCATION_ALIASES

    def _normalize_legend_location(self, token: str) -> str:
        normalized = " ".join(token.replace("-", " ").replace("_", " ").lower().split())
        if normalized in self._OCTAVE_LOCATION_ALIASES:
            return self._OCTAVE_LOCATION_ALIASES[normalized]
        if normalized in self._VALID_LEGEND_LOCATIONS:
            return normalized
        raise PlotBackendError(
            f"invalid legend location '{token}'. "
            "Use, for example: best, northeast, northwest, southeast, southwest."
        )

    def _to_vector(self, value: Any, label: str) -> np.ndarray:
        if isinstance(value, (str, bytes)):
            raise PlotDataError(f"{label} must be a numeric vector, not text.")

        try:
            array = np.asarray(value, dtype=float)
        except Exception as exc:
            raise PlotDataError(f"{label} is not a valid numeric vector: {exc}") from exc

        if array.ndim == 0:
            raise PlotDataError(f"{label} must be a vector, not a scalar.")

        if array.ndim == 2:
            if 1 in array.shape:
                array = array.reshape(-1)
            else:
                raise PlotDataError(f"{label} must be a 1D vector (got shape {array.shape}).")
        elif array.ndim > 2:
            raise PlotDataError(f"{label} must be a 1D vector (got {array.ndim} dimensions).")

        return array.reshape(-1)

    def _parse_fmt(self, fmt: str) -> dict[str, Any]:
        token = fmt.strip()
        if not token:
            return {}

        linestyle: str | None = None
        marker: str | None = None
        color: str | None = None

        i = 0
        while i < len(token):
            if token[i].isspace():
                i += 1
                continue

            two = token[i : i + 2]
            if two in {"--", "-."}:
                if linestyle is not None:
                    raise PlotFormatError(f"invalid fmt '{fmt}': multiple line styles.")
                linestyle = two
                i += 2
                continue

            ch = token[i]
            if ch in {"-", ":"}:
                if linestyle is not None:
                    raise PlotFormatError(f"invalid fmt '{fmt}': multiple line styles.")
                linestyle = ch
                i += 1
                continue
            if ch in self._VALID_MARKERS:
                if marker is not None:
                    raise PlotFormatError(f"invalid fmt '{fmt}': multiple markers.")
                marker = ch
                i += 1
                continue
            if ch in self._VALID_COLORS:
                if color is not None:
                    raise PlotFormatError(f"invalid fmt '{fmt}': multiple colors.")
                color = ch
                i += 1
                continue
            raise PlotFormatError(
                f"invalid fmt '{fmt}': unsupported token '{ch}'. "
                "Supported: linestyles - -- : -., markers o x ., colors r g b k."
            )

        kwargs: dict[str, Any] = {}
        if color is not None:
            kwargs["color"] = color
        if marker is not None:
            kwargs["marker"] = marker
        if linestyle is not None:
            kwargs["linestyle"] = linestyle
        elif marker is not None:
            kwargs["linestyle"] = "None"

        return kwargs

    @staticmethod
    def _to_on_off(value: Any, label: str) -> bool:
        if isinstance(value, bool):
            return value
        token = str(value).strip().strip("\"'").lower()
        if token == "on":
            return True
        if token == "off":
            return False
        raise PlotBackendError(f"{label} expects 'on' or 'off'.")

    def _new_state(self) -> dict[str, Any]:
        return {
            "current_figure": None,
            "current_axes": None,
            "hold": False,
            "grid": False,
            "title_text": "",
            "xlabel_text": "",
            "ylabel_text": "",
            "legend_visible": False,
            "legend_labels": None,
            "legend_location": "best",
            "_last_document_target": None,
        }

    def _capture_state(self) -> dict[str, Any]:
        return {
            "current_figure": self.current_figure,
            "current_axes": self.current_axes,
            "hold": self.hold,
            "grid": self.grid,
            "title_text": self.title_text,
            "xlabel_text": self.xlabel_text,
            "ylabel_text": self.ylabel_text,
            "legend_visible": self.legend_visible,
            "legend_labels": None if self.legend_labels is None else list(self.legend_labels),
            "legend_location": self.legend_location,
            "_last_document_target": self._last_document_target,
        }

    def _save_active_state(self) -> None:
        self._figure_states[self._active_figure_id] = self._capture_state()

    def _load_state(self, fig_num: int) -> None:
        state = self._figure_states.get(fig_num)
        if state is None:
            state = self._new_state()
            self._figure_states[fig_num] = state
        self.current_figure = state["current_figure"]
        self.current_axes = state["current_axes"]
        self.hold = bool(state["hold"])
        self.grid = bool(state["grid"])
        self.title_text = str(state["title_text"])
        self.xlabel_text = str(state["xlabel_text"])
        self.ylabel_text = str(state["ylabel_text"])
        self.legend_visible = bool(state["legend_visible"])
        labels = state["legend_labels"]
        self.legend_labels = list(labels) if isinstance(labels, list) else None
        self.legend_location = str(state["legend_location"])
        self._last_document_target = state["_last_document_target"]

    @staticmethod
    def _coerce_figure_id(value: Any) -> int:
        if isinstance(value, bool):
            raise PlotBackendError("figure(n): n must be a positive integer.")
        if isinstance(value, str):
            token = value.strip().strip("\"'")
            if not token:
                raise PlotBackendError("figure(n): n must be a positive integer.")
            try:
                num_f = float(token)
            except Exception as exc:
                raise PlotBackendError("figure(n): n must be a positive integer.") from exc
        else:
            try:
                num_f = float(value)
            except Exception as exc:
                raise PlotBackendError("figure(n): n must be a positive integer.") from exc
        num_i = int(num_f)
        if abs(num_f - num_i) > 1e-12 or num_i <= 0:
            raise PlotBackendError("figure(n): n must be a positive integer.")
        return num_i
