from __future__ import annotations

import pytest

from latex_lang import env_ast, reset_environment
from notebook_model import NotebookBlock
from notebook_runner import NotebookRunner


@pytest.fixture(autouse=True)
def _fresh_runtime() -> None:
    reset_environment()
    yield
    reset_environment()


def _code_block(source: str, language: str | None = "MathLab") -> NotebookBlock:
    return NotebookBlock(
        id="block-test",
        kind="code",
        source=source,
        language=language,
        start_line=1,
        end_line=max(1, len(source.splitlines())),
    )


def test_runs_simple_mathlab_assignment() -> None:
    runner = NotebookRunner()
    block = _code_block("a = 2;")

    result = runner.run_block(block)

    assert result.status == "ok"
    assert env_ast["a"] == 2


def test_runs_two_mathlab_blocks_with_shared_workspace() -> None:
    runner = NotebookRunner()

    runner.run_block(_code_block("a = 2;"))
    result = runner.run_block(_code_block("b = a + 3;"))

    assert result.status == "ok"
    assert float(env_ast["b"]) == 5.0


def test_runs_aether_blocks_with_shared_workspace() -> None:
    runner = NotebookRunner()

    runner.run_block(_code_block("x = 5;", language="Aether"))
    result = runner.run_block(_code_block("println(x);", language="Aether"))

    assert result.status == "ok"
    assert result.outputs[0].kind == "stdout"
    assert result.outputs[0].text == "5"


def test_latex_block_is_not_executed() -> None:
    runner = NotebookRunner()
    block = NotebookBlock(
        id="latex-test",
        kind="latex",
        source="a = 2;",
        language=None,
        start_line=1,
        end_line=1,
    )

    result = runner.run_block(block)

    assert result is block
    assert result.status == "idle"
    assert result.outputs == []
    assert "a" not in env_ast


def test_unsupported_language_returns_error_output() -> None:
    runner = NotebookRunner()
    block = _code_block("a = 2;", language="Python")

    result = runner.run_block(block)

    assert result.status == "error"
    assert result.outputs[0].kind == "error"
    assert result.outputs[0].text == "Unsupported notebook language"
    assert "a" not in env_ast


def test_runtime_error_is_stored_as_error_output() -> None:
    runner = NotebookRunner()
    block = _code_block("a = missing_variable")

    result = runner.run_block(block)

    assert result.status == "error"
    assert any(output.kind == "error" for output in result.outputs)


def _variables_output(block: NotebookBlock):
    matches = [output for output in block.outputs if output.kind == "variables"]
    assert len(matches) == 1
    return matches[0]


def test_variables_output_reports_created_scalar() -> None:
    runner = NotebookRunner()

    result = runner.run_block(_code_block("a = 2;"))
    output = _variables_output(result)

    assert "Generated / Updated variables:" in output.text
    assert "- a:" in output.text
    assert "2" in output.text
    assert output.data[0]["name"] == "a"
    assert output.data[0]["change"] == "new"


def test_variables_output_reports_vector_and_matrix_preview() -> None:
    runner = NotebookRunner()

    result = runner.run_block(_code_block("v = [1, 2, 3];\nA = [1, 2; 3, 4];"))
    output = _variables_output(result)

    assert "v" in output.text
    assert "A" in output.text
    assert "[1, 2, 3]" in output.text
    assert "[[1, 2]; [3, 4]]" in output.text


def test_variables_output_reports_updated_variable() -> None:
    runner = NotebookRunner()
    runner.run_block(_code_block("a = 2;"))

    result = runner.run_block(_code_block("a = 7;"))
    output = _variables_output(result)

    assert output.data[0]["name"] == "a"
    assert output.data[0]["change"] == "updated"
    assert "7" in output.text


def test_variables_output_truncates_large_matrix_preview() -> None:
    runner = NotebookRunner()
    source = "A = [1,2,3,4,5,6; 7,8,9,10,11,12; 13,14,15,16,17,18; 19,20,21,22,23,24; 25,26,27,28,29,30; 31,32,33,34,35,36];"

    result = runner.run_block(_code_block(source))
    output = _variables_output(result)

    assert "A" in output.text
    assert "6x6" in output.text
    assert "..." in output.text
    assert "36" not in output.text
