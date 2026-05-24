from __future__ import annotations

from pathlib import Path

import pytest

from aether import AetherRuntimeError, AetherSession, AetherTypeError, analyze_source, completion_items, run_aether
from aether.ast import CallExpression, ExpressionStatement
from aether.lexer import lex
from aether.parser import Parser


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


def test_plots_v2_parser_accepts_bang_calls_and_keyword_arguments() -> None:
    program = Parser(lex('plot!(x, y, label="datos", color="red");')).parse()
    statement = program.statements[0]

    assert isinstance(statement, ExpressionStatement)
    call = statement.expression
    assert isinstance(call, CallExpression)
    assert call.callee == "plot!"
    assert len(call.arguments) == 2
    assert set(call.keyword_arguments) == {"label", "color"}


def test_plots_v2_keyword_styles_and_mutating_series(tmp_path: Path) -> None:
    result = run_aether(
        """
import Plots
x = [1; 2; 3; 4];
y = [1; 4; 9; 16];
plot(x, y, label="cuadrados", color="blue", linewidth=2, title="Ajuste", xlabel="x", ylabel="y");
scatter!(x, y, label="datos", marker="x", color="red");
path = savefig("styled");
""",
        plot_mode="document",
        plot_output_dir=tmp_path,
    )

    assert Path(result.env["path"].value).exists()


def test_plots_v2_plot_function_samples_expression_function(tmp_path: Path) -> None:
    result = run_aether(
        """
import Plots
f(x) = x^2 + 1;
plot(f, 0, 3, n=12, label="f", color="green");
path = savefig("function_plot");
""",
        plot_mode="document",
        plot_output_dir=tmp_path,
    )

    assert Path(result.env["path"].value).exists()


def test_plots_v2_plot_function_rejects_wrong_arity() -> None:
    with pytest.raises(AetherTypeError, match="take exactly one argument"):
        run_aether(
            """
import Plots
f(x, y) = x + y;
plot(f, 0, 1);
""",
            plot_mode="document",
        )


def test_plots_v2_unknown_keyword_is_clear() -> None:
    with pytest.raises(AetherTypeError, match="unknown keyword argument 'colour'"):
        run_aether(
            """
import Plots
plot([1; 2; 3], colour="red");
""",
            plot_mode="document",
        )


def test_plots_v2_bar_histogram_and_matrix_columns(tmp_path: Path) -> None:
    result = run_aether(
        """
import Plots
x = [1; 2; 3];
Y = [1 2; 4 5; 9 10];
plot(x, Y, label="series");
bar!(x, [2; 3; 4], color="gray", alpha=0.5);
histogram!([1; 1; 2; 3; 3; 3], bins=3, label="hist");
path = savefig("mixed");
""",
        plot_mode="document",
        plot_output_dir=tmp_path,
    )

    assert Path(result.env["path"].value).exists()


def test_lexer_keeps_not_equal_after_identifier() -> None:
    result = run_aether("x = 1; println(x != 2);")

    assert result.output == "true\n"
