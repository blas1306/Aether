from __future__ import annotations

from pathlib import Path

from execution_results import ExecutionResult

from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore


class LogsOutputWidget(QtWidgets.QDialog):  # type: ignore[misc]
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Logs & Output Files")
        self.resize(980, 640)
        self.setModal(False)
        self._execution_result: ExecutionResult | None = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.summary_label = QtWidgets.QLabel("Compile a project file to inspect logs, output files, and variables.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #d6d6d6;")
        root.addWidget(self.summary_label)

        self.tabs = QtWidgets.QTabWidget()
        root.addWidget(self.tabs, 1)

        self.logs_table = QtWidgets.QTableWidget()
        self.logs_table.setColumnCount(5)
        self.logs_table.setHorizontalHeaderLabels(["Step", "Level", "Source", "Location", "Message"])
        self.logs_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.logs_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.logs_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.logs_table.verticalHeader().setVisible(False)
        self.logs_table.setAlternatingRowColors(True)
        self.tabs.addTab(self.logs_table, "Logs")

        files_page = QtWidgets.QWidget()
        files_layout = QtWidgets.QVBoxLayout(files_page)
        files_layout.setContentsMargins(0, 0, 0, 0)
        self.files_tree = QtWidgets.QTreeWidget()
        self.files_tree.setHeaderLabels(["Name", "Type", "Path"])
        self.files_tree.setAlternatingRowColors(True)
        self.files_tree.itemDoubleClicked.connect(self._open_selected_file)
        files_layout.addWidget(self.files_tree, 1)
        file_buttons = QtWidgets.QHBoxLayout()
        self.open_file_btn = QtWidgets.QPushButton("Open")
        self.reveal_file_btn = QtWidgets.QPushButton("Reveal Folder")
        file_buttons.addStretch()
        file_buttons.addWidget(self.open_file_btn)
        file_buttons.addWidget(self.reveal_file_btn)
        files_layout.addLayout(file_buttons)
        self.open_file_btn.clicked.connect(self._open_selected_file)
        self.reveal_file_btn.clicked.connect(self._reveal_selected_file)
        self.tabs.addTab(files_page, "Output Files")

        self.variables_table = QtWidgets.QTableWidget()
        self.variables_table.setColumnCount(4)
        self.variables_table.setHorizontalHeaderLabels(["Name", "Type", "Size", "Summary"])
        self.variables_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.variables_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.variables_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.variables_table.verticalHeader().setVisible(False)
        self.variables_table.setAlternatingRowColors(True)
        self.tabs.addTab(self.variables_table, "Variables")

        self._apply_header_modes()
        self.clear_result()

    def _apply_header_modes(self) -> None:
        logs_header = self.logs_table.horizontalHeader()
        logs_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        logs_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        logs_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        logs_header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        logs_header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Stretch)

        files_header = self.files_tree.header()
        files_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        files_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        files_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)

        vars_header = self.variables_table.horizontalHeader()
        vars_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        vars_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        vars_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        vars_header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)

    def clear_result(self, message: str | None = None) -> None:
        self._execution_result = None
        self.summary_label.setText(message or "Compile a project file to inspect logs, output files, and variables.")
        self.logs_table.clearContents()
        self.logs_table.setRowCount(0)
        self.files_tree.clear()
        self.variables_table.clearContents()
        self.variables_table.setRowCount(0)
        self.open_file_btn.setEnabled(False)
        self.reveal_file_btn.setEnabled(False)

    def set_execution_result(self, result: ExecutionResult) -> None:
        self._execution_result = result
        status = "Succeeded" if result.success else "Failed"
        output_count = len(result.output_files)
        variable_count = len(result.variables)
        log_count = len(result.logs)
        pdf_text = str(result.pdf_path) if result.pdf_path else "No PDF"
        self.summary_label.setText(
            f"{status}. PDF: {pdf_text} | Logs: {log_count} | Output Files: {output_count} | Variables: {variable_count}"
        )
        self._populate_logs(result)
        self._populate_files(result)
        self._populate_variables(result)
        self.open_file_btn.setEnabled(bool(result.output_files))
        self.reveal_file_btn.setEnabled(bool(result.output_files))

    def _populate_logs(self, result: ExecutionResult) -> None:
        self.logs_table.clearContents()
        self.logs_table.setRowCount(len(result.logs))
        for row, entry in enumerate(result.logs):
            location = ""
            if entry.file:
                location = f"{entry.file}:{entry.line}" if entry.line is not None else entry.file
            values = [str(entry.step), entry.level, entry.source, location, entry.message]
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if column == 1:
                    color = self._level_color(entry.level)
                    item.setForeground(QtGui.QBrush(color))
                self.logs_table.setItem(row, column, item)

    def _populate_files(self, result: ExecutionResult) -> None:
        self.files_tree.clear()
        for path in result.output_files:
            item = QtWidgets.QTreeWidgetItem(
                [
                    path.name,
                    path.suffix.lower().lstrip(".") or "file",
                    str(path),
                ]
            )
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, str(path))
            self.files_tree.addTopLevelItem(item)

    def _populate_variables(self, result: ExecutionResult) -> None:
        self.variables_table.clearContents()
        self.variables_table.setRowCount(len(result.variables))
        for row, variable in enumerate(result.variables):
            values = [variable.name, variable.value_type, variable.size, variable.summary]
            for column, value in enumerate(values):
                self.variables_table.setItem(row, column, QtWidgets.QTableWidgetItem(value))

    def _selected_output_path(self) -> Path | None:
        item = self.files_tree.currentItem()
        if item is None:
            if self.files_tree.topLevelItemCount() == 0:
                return None
            item = self.files_tree.topLevelItem(0)
            self.files_tree.setCurrentItem(item)
        raw = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not raw:
            return None
        return Path(str(raw))

    def _open_selected_file(self, *_args) -> None:
        path = self._selected_output_path()
        if path is None or not path.exists():
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _reveal_selected_file(self) -> None:
        path = self._selected_output_path()
        if path is None:
            return
        target = path.parent if path.exists() else path
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(target)))

    def _level_color(self, level: str) -> QtGui.QColor:
        if level == "error":
            return QtGui.QColor("#ff8a80")
        if level == "warning":
            return QtGui.QColor("#ffd180")
        return QtGui.QColor("#e0e0e0")
