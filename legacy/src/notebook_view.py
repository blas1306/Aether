from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from notebook_model import NotebookBlock, NotebookDocument
from notebook_parser import parse_notebook_source

from PySide6 import QtWidgets  # type: ignore


class NotebookView(QtWidgets.QWidget):  # type: ignore[misc]
    def __init__(self, source: str = "", path: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("notebookView")
        self._document = NotebookDocument(path=path)
        self._runner: Any | None = None
        self._source_provider: Callable[[], str] | None = None
        self._path_provider: Callable[[], Path | None] | None = None
        self._code_editors: dict[str, QtWidgets.QPlainTextEdit] = {}
        self._output_editors: dict[str, QtWidgets.QPlainTextEdit] = {}
        self._status_labels: dict[str, QtWidgets.QLabel] = {}
        self._last_source = source

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        toolbar = QtWidgets.QFrame(self)
        toolbar.setObjectName("notebookToolbar")
        toolbar_layout = QtWidgets.QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 8, 8, 8)
        toolbar_layout.setSpacing(6)
        self.run_all_btn = QtWidgets.QPushButton("Run All")
        self.run_all_btn.setObjectName("notebookRunAllButton")
        self.clear_outputs_btn = QtWidgets.QPushButton("Clear Outputs")
        self.clear_outputs_btn.setObjectName("notebookClearOutputsButton")
        self.reload_source_btn = QtWidgets.QPushButton("Reload from Source")
        self.reload_source_btn.setObjectName("notebookReloadSourceButton")
        toolbar_layout.addWidget(self.run_all_btn)
        toolbar_layout.addWidget(self.clear_outputs_btn)
        toolbar_layout.addWidget(self.reload_source_btn)
        toolbar_layout.addStretch()
        root.addWidget(toolbar)

        self._scroll = QtWidgets.QScrollArea(self)
        self._scroll.setObjectName("notebookScrollArea")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)

        self._content = QtWidgets.QWidget(self._scroll)
        self._content.setObjectName("notebookContent")
        self._blocks_layout = QtWidgets.QVBoxLayout(self._content)
        self._blocks_layout.setContentsMargins(12, 12, 12, 12)
        self._blocks_layout.setSpacing(10)
        self._blocks_layout.addStretch()

        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll, 1)
        self.run_all_btn.clicked.connect(self.run_all)
        self.clear_outputs_btn.clicked.connect(self.clear_outputs)
        self.reload_source_btn.clicked.connect(self.reload_from_source)
        self.setStyleSheet(self._stylesheet())
        self.set_source(source, path=path)

    def set_source_provider(
        self,
        source_provider: Callable[[], str] | None,
        path_provider: Callable[[], Path | None] | None = None,
    ) -> None:
        self._source_provider = source_provider
        self._path_provider = path_provider

    def set_source(self, source: str, path: Path | None = None) -> None:
        self._last_source = source
        self._document = parse_notebook_source(source, path=path)
        self._runner = None
        self._rebuild_blocks()

    def reload_from_source(self) -> None:
        source = self._source_provider() if self._source_provider is not None else self._last_source
        path = self._path_provider() if self._path_provider is not None else self._document.path
        self.set_source(source, path=path)

    def to_source(self) -> str:
        parts: list[str] = []
        for block in self._document.blocks:
            if block.kind == "latex":
                parts.append(block.source)
                continue

            self._sync_block_source_from_editor(block)
            environment = block.code_environment or "code"
            parts.append(f"\\begin{{{environment}}}\n")
            parts.append(block.source)
            if block.source and not block.source.endswith("\n"):
                parts.append("\n")
            parts.append(f"\\end{{{environment}}}\n")
        return "".join(parts)

    @property
    def document(self) -> NotebookDocument:
        return self._document

    def _rebuild_blocks(self) -> None:
        while self._blocks_layout.count():
            item = self._blocks_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._code_editors.clear()
        self._output_editors.clear()
        self._status_labels.clear()

        if not self._document.blocks:
            empty_label = QtWidgets.QLabel("Notebook is empty.")
            empty_label.setObjectName("notebookEmptyLabel")
            self._blocks_layout.addWidget(empty_label)
        else:
            for block in self._document.blocks:
                self._blocks_layout.addWidget(self._create_block_widget(block))
        self._blocks_layout.addStretch()

    def _create_block_widget(self, block: NotebookBlock) -> QtWidgets.QWidget:
        if block.kind == "code":
            return self._create_code_block_widget(block)
        return self._create_latex_block_widget(block)

    def _create_latex_block_widget(self, block: NotebookBlock) -> QtWidgets.QWidget:
        editor = QtWidgets.QPlainTextEdit()
        editor.setObjectName("notebookLatexBlock")
        editor.setReadOnly(True)
        editor.setPlainText(block.source)
        editor.setMinimumHeight(72)
        editor.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum)
        return editor

    def _create_code_block_widget(self, block: NotebookBlock) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setObjectName("notebookCodeBlock")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(f"{block.language or 'Unknown'} | lines {block.start_line}-{block.end_line}")
        label.setObjectName("notebookCodeHeader")
        status_label = QtWidgets.QLabel(block.status)
        status_label.setObjectName("notebookStatusLabel")
        run_button = QtWidgets.QPushButton("Run")
        run_button.setObjectName("notebookRunButton")
        run_button.setToolTip("Run this notebook block")
        clear_button = QtWidgets.QPushButton("Clear Output")
        clear_button.setObjectName("notebookClearBlockOutputButton")
        clear_button.setToolTip("Clear this block output")
        header.addWidget(label)
        header.addWidget(status_label)
        header.addStretch()
        header.addWidget(run_button)
        header.addWidget(clear_button)
        layout.addLayout(header)
        self._status_labels[block.id] = status_label

        editor = QtWidgets.QPlainTextEdit()
        editor.setObjectName("notebookCodeEditor")
        editor.setPlainText(block.source)
        editor.setMinimumHeight(96)
        editor.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(editor)
        self._code_editors[block.id] = editor

        output = QtWidgets.QPlainTextEdit()
        output.setObjectName("notebookOutput")
        output.setReadOnly(True)
        output.setMaximumBlockCount(1000)
        output.setMinimumHeight(46)
        output.setPlaceholderText("Output")
        layout.addWidget(output)
        self._output_editors[block.id] = output
        self._render_outputs(block)
        self._update_status_label(block)

        run_button.clicked.connect(lambda _checked=False, current=block: self._run_block(current))
        clear_button.clicked.connect(lambda _checked=False, current=block: self.clear_block_output(current))
        editor.textChanged.connect(lambda current=block: self._mark_block_dirty(current))
        return frame

    def run_all(self) -> None:
        self._runner = self._create_notebook_runner()
        for block in self._document.blocks:
            if block.kind != "code":
                continue
            self._run_block(block)

    def clear_outputs(self) -> None:
        for block in self._document.blocks:
            if block.kind != "code":
                continue
            self.clear_block_output(block)

    def clear_block_output(self, block: NotebookBlock) -> None:
        block.outputs = []
        if block.status in {"ok", "error", "running"}:
            block.status = "idle"
        self._render_outputs(block)
        self._update_status_label(block)

    def _run_block(self, block: NotebookBlock) -> None:
        self._sync_block_source_from_editor(block)
        block.status = "running"
        self._update_status_label(block)
        runner = self._notebook_runner()
        runner.run_block(block)
        self._render_outputs(block)
        self._update_status_label(block)

    def _mark_block_dirty(self, block: NotebookBlock) -> None:
        editor = self._code_editors.get(block.id)
        if editor is not None:
            block.source = editor.toPlainText()
        if block.status != "dirty":
            block.status = "dirty"
            self._update_status_label(block)

    def _sync_block_source_from_editor(self, block: NotebookBlock) -> None:
        editor = self._code_editors.get(block.id)
        if editor is not None:
            block.source = editor.toPlainText()

    def _notebook_runner(self):
        if self._runner is None:
            self._runner = self._create_notebook_runner()
        return self._runner

    def _create_notebook_runner(self):
        from notebook_runner import NotebookRunner

        return NotebookRunner()

    def _render_outputs(self, block: NotebookBlock) -> None:
        output = self._output_editors.get(block.id)
        if output is None:
            return
        if block.outputs:
            output.setPlainText("\n".join(self._format_output(kind=item.kind, text=item.text) for item in block.outputs))
            return
        if block.status == "ok":
            output.setPlainText("Executed successfully.")
        elif block.status == "error":
            output.setPlainText("Error.")
        else:
            output.setPlainText("")

    def _update_status_label(self, block: NotebookBlock) -> None:
        label = self._status_labels.get(block.id)
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

    def _stylesheet(self) -> str:
        return """
        QWidget#notebookView {
            background: #1f2329;
            color: #e7eaee;
        }
        QWidget#notebookContent {
            background: #1f2329;
        }
        QFrame#notebookToolbar {
            background: #242a31;
            border-bottom: 1px solid #3a414b;
        }
        QPlainTextEdit#notebookLatexBlock,
        QPlainTextEdit#notebookCodeEditor,
        QPlainTextEdit#notebookOutput {
            border: 1px solid #3a414b;
            border-radius: 6px;
            background: #15181d;
            color: #e7eaee;
            selection-background-color: #315f8f;
            font-family: Consolas, "Courier New", monospace;
            font-size: 10pt;
        }
        QPlainTextEdit#notebookLatexBlock {
            background: #242a31;
        }
        QPlainTextEdit#notebookOutput {
            background: #111418;
            color: #d7dde5;
        }
        QFrame#notebookCodeBlock {
            background: #242a31;
            border: 1px solid #3a414b;
            border-radius: 8px;
        }
        QLabel#notebookCodeHeader {
            color: #cbd3dc;
            font-weight: 600;
        }
        QLabel#notebookStatusLabel {
            color: #cbd3dc;
            background: #303741;
            border: 1px solid #4a5360;
            border-radius: 5px;
            padding: 2px 8px;
        }
        QLabel#notebookStatusLabel[status="ok"] {
            color: #daf5d4;
            background: #234a2b;
            border-color: #5ea36b;
        }
        QLabel#notebookStatusLabel[status="error"] {
            color: #ffd7d7;
            background: #5a2222;
            border-color: #d47b7b;
        }
        QLabel#notebookStatusLabel[status="dirty"] {
            color: #fff2cf;
            background: #5a4217;
            border-color: #d5a84a;
        }
        QLabel#notebookStatusLabel[status="running"] {
            color: #d9ecff;
            background: #1f3a56;
            border-color: #4f8cc9;
        }
        QLabel#notebookEmptyLabel {
            color: #9da7b1;
            padding: 16px;
        }
        QPushButton#notebookRunButton,
        QPushButton#notebookRunAllButton,
        QPushButton#notebookClearOutputsButton,
        QPushButton#notebookReloadSourceButton,
        QPushButton#notebookClearBlockOutputButton {
            background: #315f8f;
            border: 1px solid #477bad;
            border-radius: 5px;
            color: white;
            padding: 4px 12px;
        }
        QPushButton#notebookRunButton:hover,
        QPushButton#notebookRunAllButton:hover,
        QPushButton#notebookClearOutputsButton:hover,
        QPushButton#notebookReloadSourceButton:hover,
        QPushButton#notebookClearBlockOutputButton:hover {
            background: #3b72aa;
        }
        """
