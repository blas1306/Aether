from __future__ import annotations

from pathlib import Path
from typing import Any

from notebook_file import (
    export_notebook_to_mtex,
    load_notebook_file,
    make_notebook_block,
    new_notebook_document,
    save_notebook_file,
)
from notebook_model import NotebookBlock, NotebookDocument

from PySide6 import QtWidgets  # type: ignore


class NotebookEditorView(QtWidgets.QWidget):  # type: ignore[misc]
    def __init__(self, document: NotebookDocument | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("notebookEditorView")
        self._document = document or new_notebook_document()
        self._runner: Any | None = None
        self._editors: dict[str, QtWidgets.QPlainTextEdit] = {}
        self._outputs: dict[str, QtWidgets.QPlainTextEdit] = {}
        self._statuses: dict[str, QtWidgets.QLabel] = {}

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        toolbar = QtWidgets.QFrame(self)
        toolbar.setObjectName("notebookEditorToolbar")
        toolbar_layout = QtWidgets.QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 8, 8, 8)
        toolbar_layout.setSpacing(6)

        self.new_btn = QtWidgets.QPushButton("New")
        self.new_btn.setObjectName("notebookEditorNewButton")
        self.open_btn = QtWidgets.QPushButton("Open .mtn")
        self.open_btn.setObjectName("notebookEditorOpenButton")
        self.save_btn = QtWidgets.QPushButton("Save")
        self.save_btn.setObjectName("notebookEditorSaveButton")
        self.save_as_btn = QtWidgets.QPushButton("Save As")
        self.save_as_btn.setObjectName("notebookEditorSaveAsButton")
        self.export_mtex_btn = QtWidgets.QPushButton("Export .mtex")
        self.export_mtex_btn.setObjectName("notebookEditorExportMtexButton")
        self.add_text_btn = QtWidgets.QPushButton("Add Text Block")
        self.add_text_btn.setObjectName("notebookEditorAddTextButton")
        self.add_code_btn = QtWidgets.QPushButton("Add Code Block")
        self.add_code_btn.setObjectName("notebookEditorAddCodeButton")
        self.run_all_btn = QtWidgets.QPushButton("Run All")
        self.run_all_btn.setObjectName("notebookEditorRunAllButton")
        self.clear_outputs_btn = QtWidgets.QPushButton("Clear Outputs")
        self.clear_outputs_btn.setObjectName("notebookEditorClearOutputsButton")

        for button in (
            self.new_btn,
            self.open_btn,
            self.save_btn,
            self.save_as_btn,
            self.export_mtex_btn,
            self.add_text_btn,
            self.add_code_btn,
            self.run_all_btn,
            self.clear_outputs_btn,
        ):
            toolbar_layout.addWidget(button)
        toolbar_layout.addStretch()
        root.addWidget(toolbar)

        self._scroll = QtWidgets.QScrollArea(self)
        self._scroll.setObjectName("notebookEditorScrollArea")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._content = QtWidgets.QWidget(self._scroll)
        self._content.setObjectName("notebookEditorContent")
        self._blocks_layout = QtWidgets.QVBoxLayout(self._content)
        self._blocks_layout.setContentsMargins(12, 12, 12, 12)
        self._blocks_layout.setSpacing(10)
        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll, 1)

        self.new_btn.clicked.connect(self.new_document)
        self.open_btn.clicked.connect(self.open_document)
        self.save_btn.clicked.connect(self.save_document)
        self.save_as_btn.clicked.connect(self.save_document_as)
        self.export_mtex_btn.clicked.connect(self.export_mtex)
        self.add_text_btn.clicked.connect(self.add_text_block)
        self.add_code_btn.clicked.connect(self.add_code_block)
        self.run_all_btn.clicked.connect(self.run_all)
        self.clear_outputs_btn.clicked.connect(self.clear_outputs)

        self.setStyleSheet(self._stylesheet())
        self._rebuild_blocks()

    @property
    def document(self) -> NotebookDocument:
        self.sync_document_from_editors()
        return self._document

    def set_document(self, document: NotebookDocument) -> None:
        self._document = document
        self._runner = None
        self._rebuild_blocks()

    def new_document(self) -> None:
        document = new_notebook_document(self._document.default_language)
        document.blocks.append(make_notebook_block("code", "", document.default_language))
        self.set_document(document)

    def load_path(self, path: Path) -> None:
        self.set_document(load_notebook_file(path))

    def save_path(self, path: Path) -> None:
        self.sync_document_from_editors()
        save_notebook_file(self._document, path)

    def to_mtex(self) -> str:
        self.sync_document_from_editors()
        return export_notebook_to_mtex(self._document)

    def open_document(self) -> None:
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open Notebook",
            str(self._dialog_dir()),
            "MathTeX Notebooks (*.mtn);;All Files (*)",
        )
        if filename:
            self.load_path(Path(filename))

    def save_document(self) -> None:
        if self._document.path is None:
            self.save_document_as()
            return
        self.save_path(self._document.path)

    def save_document_as(self) -> None:
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Notebook",
            str(self._dialog_dir() / "notebook.mtn"),
            "MathTeX Notebooks (*.mtn);;All Files (*)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".mtn":
            path = path.with_suffix(".mtn")
        self.save_path(path)

    def export_mtex(self) -> None:
        initial = self._document.path.with_suffix(".mtex").name if self._document.path else "notebook.mtex"
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Notebook to .mtex",
            str(self._dialog_dir() / initial),
            "MathTeX Documents (*.mtex);;All Files (*)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".mtex":
            path = path.with_suffix(".mtex")
        path.write_text(self.to_mtex(), encoding="utf-8")

    def add_text_block(self) -> None:
        self.sync_document_from_editors()
        self._document.blocks.append(make_notebook_block("text", ""))
        self._rebuild_blocks()

    def add_code_block(self) -> None:
        self.sync_document_from_editors()
        self._document.blocks.append(make_notebook_block("code", "", self._document.default_language))
        self._rebuild_blocks()

    def run_all(self) -> None:
        self.sync_document_from_editors()
        self._runner = self._create_notebook_runner()
        for block in self._document.blocks:
            if block.kind == "code":
                self._run_block(block)

    def clear_outputs(self) -> None:
        for block in self._document.blocks:
            if block.kind != "code":
                continue
            block.outputs = []
            if block.status in {"ok", "error", "running"}:
                block.status = "idle"
            self._render_outputs(block)
            self._update_status(block)

    def sync_document_from_editors(self) -> None:
        for block in self._document.blocks:
            editor = self._editors.get(block.id)
            if editor is not None:
                block.source = editor.toPlainText()

    def _rebuild_blocks(self) -> None:
        while self._blocks_layout.count():
            item = self._blocks_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._editors.clear()
        self._outputs.clear()
        self._statuses.clear()

        if not self._document.blocks:
            empty = QtWidgets.QLabel("Notebook is empty.")
            empty.setObjectName("notebookEditorEmptyLabel")
            self._blocks_layout.addWidget(empty)
        else:
            for block in self._document.blocks:
                self._blocks_layout.addWidget(self._create_block_widget(block))
        self._blocks_layout.addStretch()

    def _create_block_widget(self, block: NotebookBlock) -> QtWidgets.QWidget:
        if block.kind == "code":
            return self._create_code_block_widget(block)
        return self._create_text_block_widget(block)

    def _create_text_block_widget(self, block: NotebookBlock) -> QtWidgets.QWidget:
        frame = self._create_block_frame()
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        header = QtWidgets.QLabel("Text")
        header.setObjectName("notebookEditorBlockHeader")
        editor = QtWidgets.QPlainTextEdit()
        editor.setObjectName("notebookEditorTextEditor")
        editor.setPlainText(block.source)
        editor.setMinimumHeight(90)
        layout.addWidget(header)
        layout.addWidget(editor)
        self._editors[block.id] = editor
        return frame

    def _create_code_block_widget(self, block: NotebookBlock) -> QtWidgets.QWidget:
        frame = self._create_block_frame()
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(block.language or self._document.default_language)
        label.setObjectName("notebookEditorBlockHeader")
        status = QtWidgets.QLabel(block.status)
        status.setObjectName("notebookEditorStatusLabel")
        run_button = QtWidgets.QPushButton("Run Block")
        run_button.setObjectName("notebookEditorRunBlockButton")
        clear_button = QtWidgets.QPushButton("Clear Output")
        clear_button.setObjectName("notebookEditorClearBlockOutputButton")
        header.addWidget(label)
        header.addWidget(status)
        header.addStretch()
        header.addWidget(run_button)
        header.addWidget(clear_button)
        layout.addLayout(header)
        self._statuses[block.id] = status

        editor = QtWidgets.QPlainTextEdit()
        editor.setObjectName("notebookEditorCodeEditor")
        editor.setPlainText(block.source)
        editor.setMinimumHeight(96)
        layout.addWidget(editor)
        self._editors[block.id] = editor

        output = QtWidgets.QPlainTextEdit()
        output.setObjectName("notebookEditorOutput")
        output.setReadOnly(True)
        output.setMinimumHeight(46)
        output.setPlaceholderText("Output")
        layout.addWidget(output)
        self._outputs[block.id] = output
        self._render_outputs(block)
        self._update_status(block)

        run_button.clicked.connect(lambda _checked=False, current=block: self._run_block(current))
        clear_button.clicked.connect(lambda _checked=False, current=block: self._clear_block_output(current))
        editor.textChanged.connect(lambda current=block: self._mark_dirty(current))
        return frame

    def _create_block_frame(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("notebookEditorBlock")
        return frame

    def _run_block(self, block: NotebookBlock) -> None:
        editor = self._editors.get(block.id)
        if editor is not None:
            block.source = editor.toPlainText()
        block.status = "running"
        self._update_status(block)
        runner = self._notebook_runner()
        runner.run_block(block)
        self._render_outputs(block)
        self._update_status(block)

    def _clear_block_output(self, block: NotebookBlock) -> None:
        block.outputs = []
        if block.status in {"ok", "error", "running"}:
            block.status = "idle"
        self._render_outputs(block)
        self._update_status(block)

    def _mark_dirty(self, block: NotebookBlock) -> None:
        editor = self._editors.get(block.id)
        if editor is not None:
            block.source = editor.toPlainText()
        if block.status != "dirty":
            block.status = "dirty"
            self._update_status(block)

    def _notebook_runner(self):
        if self._runner is None:
            self._runner = self._create_notebook_runner()
        return self._runner

    def _create_notebook_runner(self):
        from notebook_runner import NotebookRunner

        return NotebookRunner()

    def _render_outputs(self, block: NotebookBlock) -> None:
        output = self._outputs.get(block.id)
        if output is None:
            return
        if block.outputs:
            output.setPlainText("\n".join(self._format_output(kind=item.kind, text=item.text) for item in block.outputs))
        elif block.status == "ok":
            output.setPlainText("Executed successfully.")
        else:
            output.setPlainText("")

    def _update_status(self, block: NotebookBlock) -> None:
        label = self._statuses.get(block.id)
        if label is None:
            return
        label.setText(block.status)
        label.setProperty("status", block.status)
        label.style().unpolish(label)
        label.style().polish(label)

    def _format_output(self, *, kind: str, text: str) -> str:
        if kind == "variables":
            return text.rstrip()
        prefix = kind.upper() if kind else "OUTPUT"
        clean_text = text.rstrip()
        return f"{prefix}: {clean_text}" if clean_text else prefix

    def _dialog_dir(self) -> Path:
        return self._document.path.parent if self._document.path is not None else Path.cwd()

    def _stylesheet(self) -> str:
        return """
        QWidget#notebookEditorView {
            background: #202326;
            color: #e7eaee;
        }
        QWidget#notebookEditorContent {
            background: #202326;
        }
        QFrame#notebookEditorToolbar {
            background: #262c32;
            border-bottom: 1px solid #3b434c;
        }
        QFrame#notebookEditorBlock {
            background: #262c32;
            border: 1px solid #3b434c;
            border-radius: 8px;
        }
        QLabel#notebookEditorBlockHeader {
            color: #d3dae2;
            font-weight: 600;
        }
        QLabel#notebookEditorStatusLabel {
            color: #cbd3dc;
            background: #303741;
            border: 1px solid #4a5360;
            border-radius: 5px;
            padding: 2px 8px;
        }
        QLabel#notebookEditorStatusLabel[status="ok"] {
            color: #daf5d4;
            background: #234a2b;
            border-color: #5ea36b;
        }
        QLabel#notebookEditorStatusLabel[status="error"] {
            color: #ffd7d7;
            background: #5a2222;
            border-color: #d47b7b;
        }
        QLabel#notebookEditorStatusLabel[status="dirty"] {
            color: #fff2cf;
            background: #5a4217;
            border-color: #d5a84a;
        }
        QPlainTextEdit#notebookEditorTextEditor,
        QPlainTextEdit#notebookEditorCodeEditor,
        QPlainTextEdit#notebookEditorOutput {
            border: 1px solid #3a414b;
            border-radius: 6px;
            background: #15181d;
            color: #e7eaee;
            selection-background-color: #315f8f;
            font-family: Consolas, "Courier New", monospace;
            font-size: 10pt;
        }
        QPlainTextEdit#notebookEditorTextEditor {
            background: #1b1f24;
        }
        QPlainTextEdit#notebookEditorOutput {
            background: #111418;
            color: #d7dde5;
        }
        QLabel#notebookEditorEmptyLabel {
            color: #9da7b1;
            padding: 16px;
        }
        QPushButton {
            background: #315f8f;
            border: 1px solid #477bad;
            border-radius: 5px;
            color: white;
            padding: 4px 10px;
        }
        QPushButton:hover {
            background: #3b72aa;
        }
        """

