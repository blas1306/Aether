from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from command_catalog import COMMAND_CATALOG
from latex_lang import (
    env_ast,
    ejecutar_linea,
    get_document_output_dir,
    reset_environment,
    set_document_output_dir,
    set_plot_mode,
)


def _run(line: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ejecutar_linea(line)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _fresh_runtime():
    previous_output_dir = get_document_output_dir()
    set_plot_mode("interactive")
    reset_environment()
    yield
    set_document_output_dir(previous_output_dir)
    set_plot_mode("interactive")
    reset_environment()


def test_catalog_entries_have_unique_names_and_nonempty_core_metadata():
    names = [entry.name for entry in COMMAND_CATALOG]

    assert len(names) == len(set(names))

    for entry in COMMAND_CATALOG:
        assert entry.name.strip()
        assert entry.insert_text.strip()
        assert entry.signature.strip()
        assert entry.category.strip()
        assert entry.description.strip()


def test_catalog_commands_match_real_supported_surface_for_sample_set(tmp_path: Path):
    _run("A = [4 3; 6 3];")
    _run(r"[L, U] = \LU(A);")
    assert env_ast["L"].tolist() == [[1, 0], [pytest.approx(1.5), 1]]
    assert env_ast["U"].tolist() == [[4, 3], [0, pytest.approx(-1.5)]]

    _run(r"root = \NR(x^2 - 2, 1);")
    assert float(env_ast["root"]) == pytest.approx(2**0.5, rel=1e-9)

    _run(r"mn = \min([3,1,2]);")
    _run(r"mx = \max([3,1,2]);")
    assert float(env_ast["mn"]) == pytest.approx(1.0)
    assert float(env_ast["mx"]) == pytest.approx(3.0)

    _run(r"\ode(y'(x)=y(x), y(0)=1, x=0..1, n=8);")
    assert "y_num" in env_ast
    assert callable(env_ast["y_num"])

    set_plot_mode("document")
    set_document_output_dir(tmp_path)
    _run(r'\plot([0,1],[0,1], name="catalog_plot");')
    assert env_ast["last_plot"] == "catalog_plot.png"
    assert env_ast["_plot_files"]["catalog_plot"] == "catalog_plot.png"
    assert (tmp_path / "catalog_plot.png").exists()

    _run("t = [3,1,2];")
    _run(r"[sorted_t, idx] = \sort(t);")
    assert env_ast["sorted_t"].tolist() == [[1, 2, 3]]
    assert env_ast["idx"].tolist() == [[2, 3, 1]]

    _run("catalog_marker = 1;")
    vars_output = _run(r"\vars")
    assert "catalog_marker" in vars_output


def test_diag_and_Diag_catalog_descriptions_match_runtime_behavior():
    descriptions = {entry.name: entry.description for entry in COMMAND_CATALOG}

    assert descriptions[r"\diag()"] == "Extract the diagonal of a matrix."
    assert descriptions[r"\Diag()"] == "Build a diagonal matrix."
    assert descriptions[r"\format()"] == "Set the global numeric display format."
    assert descriptions[r"\run"] == "Run a .mtx script file."
