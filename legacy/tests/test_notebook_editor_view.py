from __future__ import annotations

from PySide6 import QtWidgets  # type: ignore

from notebook_editor_view import NotebookEditorView
from notebook_file import make_notebook_block, new_notebook_document
from notebook_model import NotebookOutput


class FakeNotebookRunner:
    def run_block(self, block):
        block.status = "ok"
        block.outputs = [NotebookOutput(kind="stdout", text="ran")]
        return block


def _text_editors(view: NotebookEditorView) -> list[QtWidgets.QPlainTextEdit]:
    return [editor for editor in view.findChildren(QtWidgets.QPlainTextEdit) if editor.objectName() == "notebookEditorTextEditor"]


def _code_editors(view: NotebookEditorView) -> list[QtWidgets.QPlainTextEdit]:
    return [editor for editor in view.findChildren(QtWidgets.QPlainTextEdit) if editor.objectName() == "notebookEditorCodeEditor"]


def _buttons(view: NotebookEditorView, object_name: str) -> list[QtWidgets.QPushButton]:
    return [button for button in view.findChildren(QtWidgets.QPushButton) if button.objectName() == object_name]


def test_notebook_editor_adds_directly_editable_text_and_code_blocks(qapp) -> None:
    view = NotebookEditorView()
    try:
        _buttons(view, "notebookEditorAddTextButton")[0].click()
        _buttons(view, "notebookEditorAddCodeButton")[0].click()
        qapp.processEvents()

        _text_editors(view)[0].setPlainText("Editable text")
        _code_editors(view)[0].setPlainText("a = 2;")

        assert [block.kind for block in view.document.blocks] == ["text", "code"]
        assert [block.source for block in view.document.blocks] == ["Editable text", "a = 2;"]
    finally:
        view.close()
        qapp.processEvents()


def test_notebook_editor_new_button_creates_editable_notebook(qapp) -> None:
    document = new_notebook_document()
    document.blocks.append(make_notebook_block("text", "Old content"))
    view = NotebookEditorView(document)
    try:
        _buttons(view, "notebookEditorNewButton")[0].click()
        qapp.processEvents()

        assert view.document.path is None
        assert [block.kind for block in view.document.blocks] == ["code"]
        assert len(_code_editors(view)) == 1
    finally:
        view.close()
        qapp.processEvents()


def test_notebook_editor_runs_code_block_and_exports_to_mtex(qapp) -> None:
    document = new_notebook_document()
    document.blocks.append(make_notebook_block("text", "Intro\n"))
    document.blocks.append(make_notebook_block("code", "a = 1;", "MathLab"))
    view = NotebookEditorView(document)
    view._create_notebook_runner = FakeNotebookRunner
    try:
        _buttons(view, "notebookEditorRunBlockButton")[0].click()
        qapp.processEvents()

        outputs = [editor for editor in view.findChildren(QtWidgets.QPlainTextEdit) if editor.objectName() == "notebookEditorOutput"]
        assert "STDOUT: ran" in outputs[0].toPlainText()
        assert view.document.blocks[1].status == "ok"
        assert view.to_mtex() == "Intro\n\\begin{MathLab}\na = 1;\n\\end{MathLab}\n"
    finally:
        view.close()
        qapp.processEvents()
