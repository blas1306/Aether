from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets  # type: ignore

from notebook_model import NotebookOutput
from notebook_view import NotebookView
from project_system import ProjectManager
from project_widgets import ProjectWorkspaceWidget


class FakeNotebookRunner:
    def __init__(self) -> None:
        self.env: dict[str, int] = {}

    def run_block(self, block):
        text = block.source.strip().rstrip(";")
        block.outputs = []
        try:
            name, expr = [part.strip() for part in text.split("=", 1)]
            if expr.isdigit():
                value = int(expr)
            elif "+" in expr:
                left, right = [part.strip() for part in expr.split("+", 1)]
                value = self.env[left] + int(right)
            else:
                value = self.env[expr]
            self.env[name] = value
            block.status = "ok"
        except Exception:
            block.status = "error"
            block.outputs = [NotebookOutput(kind="error", text=f"Fake runtime error: {text}")]
        return block


def _code_editors(view: NotebookView) -> list[QtWidgets.QPlainTextEdit]:
    return [editor for editor in view.findChildren(QtWidgets.QPlainTextEdit) if editor.objectName() == "notebookCodeEditor"]


def _output_editors(view: NotebookView) -> list[QtWidgets.QPlainTextEdit]:
    return [editor for editor in view.findChildren(QtWidgets.QPlainTextEdit) if editor.objectName() == "notebookOutput"]


def _status_labels(view: NotebookView) -> list[QtWidgets.QLabel]:
    return [label for label in view.findChildren(QtWidgets.QLabel) if label.objectName() == "notebookStatusLabel"]


def _buttons(view: NotebookView, object_name: str) -> list[QtWidgets.QPushButton]:
    return [button for button in view.findChildren(QtWidgets.QPushButton) if button.objectName() == object_name]


def test_notebook_view_to_source_preserves_code_and_explicit_mathlab(qapp) -> None:
    source = (
        "Intro\n"
        "\\begin{code}\n"
        "a = 1;\n"
        "\\end{code}\n"
        "Middle\n"
        "\\begin{MathLab}\n"
        "b = 2;\n"
        "\\end{MathLab}\n"
        "End\n"
    )
    view = NotebookView(source)
    try:
        editors = _code_editors(view)
        assert len(editors) == 2

        editors[0].setPlainText("a = 3;")
        editors[1].setPlainText("b = a + 2;")

        rebuilt = view.to_source()

        assert "Intro\n" in rebuilt
        assert "\\begin{code}\na = 3;\n\\end{code}\n" in rebuilt
        assert "\\begin{MathLab}\nb = a + 2;\n\\end{MathLab}\n" in rebuilt
        assert rebuilt.endswith("End\n")
    finally:
        view.close()
        qapp.processEvents()


def test_notebook_view_marks_code_block_dirty_when_edited(qapp) -> None:
    view = NotebookView("\\begin{code}\na = 1;\n\\end{code}\n")
    try:
        editor = _code_editors(view)[0]
        editor.setPlainText("a = 2;")
        qapp.processEvents()

        assert view.document.blocks[0].status == "dirty"
        assert _status_labels(view)[0].text() == "dirty"
    finally:
        view.close()
        qapp.processEvents()


def test_notebook_view_run_button_shows_mathlab_output(qapp) -> None:
    class FakeRunner:
        def run_block(self, block):
            block.status = "ok"
            block.outputs = [
                NotebookOutput(kind="stdout", text="x = 2"),
                NotebookOutput(kind="variables", text="Generated / Updated variables:\n- x: int, 1x1, 2"),
            ]
            return block

    view = NotebookView("\\begin{code}\nx = 2\n\\end{code}\n")
    view._runner = FakeRunner()
    try:
        run_buttons = [button for button in view.findChildren(QtWidgets.QPushButton) if button.objectName() == "notebookRunButton"]
        assert len(run_buttons) == 1

        run_buttons[0].click()
        qapp.processEvents()

        outputs = _output_editors(view)
        assert len(outputs) == 1
        output_text = outputs[0].toPlainText()
        assert "STDOUT:" in output_text
        assert "x = 2" in output_text
        assert "Generated / Updated variables:" in output_text
        assert "- x: int, 1x1, 2" in output_text
    finally:
        view.close()
        qapp.processEvents()


def test_notebook_view_clear_output_for_block(qapp) -> None:
    view = NotebookView("\\begin{code}\nx = 2\n\\end{code}\n")
    view._runner = FakeNotebookRunner()
    try:
        _buttons(view, "notebookRunButton")[0].click()
        qapp.processEvents()
        assert view.document.blocks[0].status == "ok"
        assert "Executed successfully." in _output_editors(view)[0].toPlainText()

        _buttons(view, "notebookClearBlockOutputButton")[0].click()
        qapp.processEvents()

        assert view.document.blocks[0].status == "idle"
        assert _output_editors(view)[0].toPlainText() == ""
        assert _status_labels(view)[0].text() == "idle"
    finally:
        view.close()
        qapp.processEvents()


def test_notebook_view_run_all_shares_workspace_between_blocks(qapp) -> None:
    source = (
        "\\begin{code}\n"
        "a = 2;\n"
        "\\end{code}\n"
        "\\begin{code}\n"
        "b = a + 3;\n"
        "\\end{code}\n"
    )
    view = NotebookView(source)
    fake_runner = FakeNotebookRunner()
    view._create_notebook_runner = lambda: fake_runner
    try:
        view.run_all_btn.click()
        qapp.processEvents()

        assert [block.status for block in view.document.blocks] == ["ok", "ok"]
        assert fake_runner.env["b"] == 5
        assert [label.text() for label in _status_labels(view)] == ["ok", "ok"]
    finally:
        view.close()
        qapp.processEvents()


def test_notebook_view_run_all_continues_after_error(qapp) -> None:
    source = (
        "\\begin{code}\n"
        "a = 2;\n"
        "\\end{code}\n"
        "\\begin{code}\n"
        "b = missing + 3;\n"
        "\\end{code}\n"
        "\\begin{code}\n"
        "c = 4;\n"
        "\\end{code}\n"
    )
    view = NotebookView(source)
    view._create_notebook_runner = FakeNotebookRunner
    try:
        view.run_all_btn.click()
        qapp.processEvents()

        assert [block.status for block in view.document.blocks] == ["ok", "error", "ok"]
        assert "ERROR:" in _output_editors(view)[1].toPlainText()
        assert [label.text() for label in _status_labels(view)] == ["ok", "error", "ok"]
    finally:
        view.close()
        qapp.processEvents()


def test_notebook_view_clear_outputs_all_blocks(qapp) -> None:
    view = NotebookView("\\begin{code}\na = 2;\n\\end{code}\n\\begin{code}\nb = missing;\n\\end{code}\n")
    view._create_notebook_runner = FakeNotebookRunner
    try:
        view.run_all()
        assert [block.status for block in view.document.blocks] == ["ok", "error"]

        view.clear_outputs_btn.click()
        qapp.processEvents()

        assert [block.status for block in view.document.blocks] == ["idle", "idle"]
        assert [output.toPlainText() for output in _output_editors(view)] == ["", ""]
    finally:
        view.close()
        qapp.processEvents()


def test_project_workspace_exposes_notebook_tab_and_syncs_to_source(tmp_path: Path, qapp) -> None:
    manager = ProjectManager()
    project = manager.create_project("NotebookWorkspaceProject", tmp_path)
    widget = ProjectWorkspaceWidget(
        editor_factory=QtWidgets.QPlainTextEdit,
        preview_factory=QtWidgets.QLabel,
        preview_message="Preview",
        project_manager=manager,
    )
    try:
        widget.set_project(project)
        widget.editor_widget.setPlainText("\\begin{code}\na = 1;\n\\end{code}\n")

        assert widget.content_tabs.tabText(0) == "Source"
        assert widget.content_tabs.tabText(1) == "Notebook"

        widget.content_tabs.setCurrentWidget(widget.notebook_view)
        qapp.processEvents()
        _code_editors(widget.notebook_view)[0].setPlainText("a = 4;")

        widget.sync_notebook_to_editor_if_active()

        assert "\\begin{code}\na = 4;\n\\end{code}\n" in widget.editor_widget.toPlainText()
    finally:
        widget.close()
        qapp.processEvents()


def test_project_workspace_reloads_notebook_from_source_when_tab_is_selected(tmp_path: Path, qapp) -> None:
    manager = ProjectManager()
    project = manager.create_project("NotebookReloadProject", tmp_path)
    widget = ProjectWorkspaceWidget(
        editor_factory=QtWidgets.QPlainTextEdit,
        preview_factory=QtWidgets.QLabel,
        preview_message="Preview",
        project_manager=manager,
    )
    try:
        widget.set_project(project)
        widget.editor_widget.setPlainText("\\begin{code}\na = 1;\n\\end{code}\n")
        widget.content_tabs.setCurrentWidget(widget.notebook_view)
        qapp.processEvents()
        assert _code_editors(widget.notebook_view)[0].toPlainText() == "a = 1;\n"

        widget.content_tabs.setCurrentWidget(widget.editor_widget)
        widget.editor_widget.setPlainText("\\begin{code}\na = 9;\n\\end{code}\n")
        widget.content_tabs.setCurrentWidget(widget.notebook_view)
        qapp.processEvents()

        assert _code_editors(widget.notebook_view)[0].toPlainText() == "a = 9;\n"
    finally:
        widget.close()
        qapp.processEvents()
