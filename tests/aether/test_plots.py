from __future__ import annotations

from pathlib import Path

import pytest

from aether import AetherRuntimeError, AetherSession, AetherTypeError, analyze_source, completion_items, run_aether


def test_import_plots_plot_vector_creates_png_in_document_mode(tmp_path: Path) -> None:
    run_aether(
        """
import Plots
plot([1; 2; 3]);
""",
        plot_mode="document",
        plot_output_dir=tmp_path,
    )

    assert len(list(tmp_path.glob("plot_*.png"))) == 1


def test_plots_supports_vector_api_and_savefig(tmp_path: Path) -> None:
    result = run_aether(
        """
import Plots
x = [1; 2; 3; 4];
y = [1; 4; 9; 16];
plot(x, y, "bo");
hold(true);
scatter(x, y);
grid("on");
title("Parabola");
xlabel("x");
ylabel("y");
legend("datos");
path = savefig("demo");
""",
        plot_mode="document",
        plot_output_dir=tmp_path,
    )

    saved = Path(result.env["path"].value)
    assert saved == tmp_path / "demo.png"
    assert saved.exists()


def test_plots_qualified_calls_work_without_import(tmp_path: Path) -> None:
    result = run_aether(
        """
Plots.plot([1; 2; 3]);
path = Plots.savefig("qualified.png");
""",
        plot_mode="document",
        plot_output_dir=tmp_path,
    )

    assert Path(result.env["path"].value).exists()


def test_unqualified_plot_requires_import() -> None:
    with pytest.raises(AetherTypeError, match="Undefined function 'plot'"):
        run_aether("plot([1; 2; 3]);", plot_mode="document")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("import Plots\nplot([1; 2], [1; 2; 3]);", "same length"),
        ("import Plots\nplot(1);", "numeric vector"),
        ("import Plots\nint[] xs = []; plot(xs);", "empty vector"),
        ("import Plots\nplot([1 2; 3 4]);", "matrix shape 2x2"),
    ],
)
def test_plots_reports_clear_data_errors(source: str, message: str) -> None:
    with pytest.raises((AetherRuntimeError, AetherTypeError), match=message):
        run_aether(source, plot_mode="document")


def test_plots_sessions_do_not_share_figure_state(tmp_path: Path) -> None:
    first = AetherSession(plot_mode="document", plot_output_dir=tmp_path / "first")
    second = AetherSession(plot_mode="document", plot_output_dir=tmp_path / "second")

    first.run('import Plots\nfigure(2); title("First"); plot([1; 2]);')
    second.run('import Plots\nplot([1; 2]);')

    assert first._interpreter.plot_backend.get_active_figure() == 2
    assert second._interpreter.plot_backend.get_active_figure() == 1
    assert first._interpreter.plot_backend.title_text == "First"
    assert second._interpreter.plot_backend.title_text == ""


def test_plots_figure_state_is_isolated_per_figure(tmp_path: Path) -> None:
    session = AetherSession(plot_mode="document", plot_output_dir=tmp_path)

    session.run(
        """
import Plots
figure(1);
grid(true);
title("F1");
plot([1; 2]);
figure(2);
plot([2; 3]);
figure(1);
"""
    )

    backend = session._interpreter.plot_backend
    assert backend.get_active_figure() == 1
    assert backend.grid is True
    assert backend.title_text == "F1"


def test_plots_completions_include_qualified_and_imported_names() -> None:
    labels = {item.label for item in completion_items("import Plots\n", 1, 1)}

    assert "Plots.plot" in labels
    assert "plot" in labels


def test_analyze_source_accepts_imported_plot_alias() -> None:
    assert analyze_source("import Plots\nplot([1; 2; 3]);") == []
