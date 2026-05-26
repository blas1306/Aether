from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from notebook_file import new_notebook_document, save_notebook_file
from notebook_view import NotebookView
from project_system import PROJECT_METADATA_FILENAME, ProjectInfo, ProjectManager

from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

_Signal = QtCore.Signal  # type: ignore[attr-defined]


WORKSPACE_OUTER_MARGIN = 12
WORKSPACE_SECTION_SPACING = 10
WORKSPACE_ROW_SPACING = 6
WORKSPACE_PANEL_PADDING = 8
WORKSPACE_LEFT_MIN_WIDTH = 240
WORKSPACE_EDITOR_MIN_WIDTH = 420
WORKSPACE_PREVIEW_MIN_WIDTH = 420
WORKSPACE_DEFAULT_SPLITTER_WEIGHTS = (22, 38, 40)
AETHER_SCRIPT_SUFFIX = ".ae"
OPENABLE_PROJECT_SUFFIXES = {".mtex", ".mtx", ".mtn", AETHER_SCRIPT_SUFFIX}


def _format_timestamp(raw_value: str | None) -> str:
    if not raw_value:
        return "Unknown"
    try:
        timestamp = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return raw_value
    return timestamp.strftime("%Y-%m-%d %H:%M")


class ProjectHomeWidget(QtWidgets.QWidget):  # type: ignore[misc]
    new_project_requested = _Signal()
    open_project_requested = _Signal()
    project_activated = _Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(18)

        title = QtWidgets.QLabel("MTeX Studio")
        title_font = QtGui.QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel("Open a recent project or create a new workspace.")
        subtitle.setStyleSheet("color: #6f6f6f;")
        layout.addWidget(subtitle)

        buttons = QtWidgets.QHBoxLayout()
        self.new_project_btn = QtWidgets.QPushButton("New Project")
        self.open_project_btn = QtWidgets.QPushButton("Open Project")
        buttons.addWidget(self.new_project_btn)
        buttons.addWidget(self.open_project_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        recent_label = QtWidgets.QLabel("Recent Projects")
        recent_font = QtGui.QFont()
        recent_font.setPointSize(12)
        recent_font.setBold(True)
        recent_label.setFont(recent_font)
        layout.addWidget(recent_label)

        self.project_list = QtWidgets.QListWidget()
        self.project_list.setAlternatingRowColors(True)
        self.project_list.itemActivated.connect(self._emit_selected_project)
        layout.addWidget(self.project_list, 1)

        self.empty_label = QtWidgets.QLabel("No recent projects yet.")
        self.empty_label.setStyleSheet("color: #7a7a7a;")
        layout.addWidget(self.empty_label)

        self.new_project_btn.clicked.connect(self.new_project_requested.emit)
        self.open_project_btn.clicked.connect(self.open_project_requested.emit)
        self._update_empty_state()

    def set_projects(self, projects: list[ProjectInfo]) -> None:
        self.project_list.clear()
        for project in projects:
            item = QtWidgets.QListWidgetItem(project.name)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(project.path))
            item.setToolTip(str(project.path))
            item.setText(
                f"{project.name}\n{project.path}\nLast opened: {_format_timestamp(project.last_opened)}"
            )
            self.project_list.addItem(item)
        self._update_empty_state()

    def _emit_selected_project(self, item: QtWidgets.QListWidgetItem) -> None:
        project_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if project_path:
            self.project_activated.emit(str(project_path))

    def _update_empty_state(self) -> None:
        is_empty = self.project_list.count() == 0
        self.empty_label.setVisible(is_empty)
        self.project_list.setVisible(not is_empty)


class ProjectCreationDialog(QtWidgets.QDialog):  # type: ignore[misc]
    def __init__(self, default_base_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.resize(520, 150)

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("Project name")
        form.addRow("Name", self.name_input)

        location_row = QtWidgets.QHBoxLayout()
        self.location_input = QtWidgets.QLineEdit(str(default_base_dir))
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_for_location)
        location_row.addWidget(self.location_input, 1)
        location_row.addWidget(browse_btn)
        form.addRow("Location", location_row)
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.name_input.setFocus()

    def project_name(self) -> str:
        return self.name_input.text().strip()

    def base_dir(self) -> Path:
        return Path(self.location_input.text().strip()).expanduser()

    def _browse_for_location(self) -> None:
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose Project Location",
            self.location_input.text().strip() or str(Path.home()),
        )
        if selected:
            self.location_input.setText(selected)

    def _validate_and_accept(self) -> None:
        name = self.project_name()
        if not name:
            QtWidgets.QMessageBox.warning(self, "New Project", "Project name cannot be empty.")
            return
        if any(char in '<>:"/\\|?*' for char in name):
            QtWidgets.QMessageBox.warning(self, "New Project", "Project name contains invalid characters.")
            return
        if not self.location_input.text().strip():
            QtWidgets.QMessageBox.warning(self, "New Project", "Choose a location for the project.")
            return
        self.accept()


class ProjectWorkspaceWidget(QtWidgets.QWidget):  # type: ignore[misc]
    home_requested = _Signal()
    save_requested = _Signal()
    save_as_requested = _Signal()
    compile_requested = _Signal()
    logs_output_requested = _Signal()
    file_open_requested = _Signal(str)

    def __init__(
        self,
        editor_factory: Callable[[], QtWidgets.QWidget],
        preview_factory: Callable[[], QtWidgets.QWidget],
        preview_message: str,
        project_manager: ProjectManager | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("projectWorkspaceRoot")
        self._project: ProjectInfo | None = None
        self._preview_message = preview_message
        self._project_manager = project_manager or ProjectManager()
        self._workspace_splitter: QtWidgets.QSplitter | None = None
        self._splitter_defaults_applied = False
        self._sync_actions: list[QtGui.QAction] = []
        self._syncing_notebook_source = False
        self.setStyleSheet(self._workspace_stylesheet())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(
            WORKSPACE_OUTER_MARGIN,
            WORKSPACE_OUTER_MARGIN,
            WORKSPACE_OUTER_MARGIN,
            WORKSPACE_OUTER_MARGIN,
        )
        layout.setSpacing(WORKSPACE_SECTION_SPACING)

        header_frame = QtWidgets.QFrame()
        header_frame.setObjectName("workspaceHeaderCard")
        header_layout = QtWidgets.QVBoxLayout(header_frame)
        header_layout.setContentsMargins(10, 10, 10, 10)
        header_layout.setSpacing(WORKSPACE_SECTION_SPACING)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(WORKSPACE_SECTION_SPACING)
        self.home_btn = QtWidgets.QPushButton("Project Home")
        self.project_name_label = QtWidgets.QLabel("No project open")
        self.project_name_label.setObjectName("projectNameLabel")
        title_font = QtGui.QFont()
        title_font.setPointSize(15)
        title_font.setBold(True)
        self.project_name_label.setFont(title_font)
        project_identity = QtWidgets.QVBoxLayout()
        project_identity.setContentsMargins(0, 0, 0, 0)
        project_identity.setSpacing(2)
        self.project_path_label = QtWidgets.QLabel("")
        self.project_path_label.setObjectName("projectPathLabel")
        self.project_path_label.setWordWrap(True)
        header.addWidget(self.home_btn)
        project_identity.addWidget(self.project_name_label)
        project_identity.addWidget(self.project_path_label)
        header.addLayout(project_identity, 1)
        header_layout.addLayout(header)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(WORKSPACE_ROW_SPACING)
        self.save_btn = QtWidgets.QPushButton("Save")
        self.save_as_btn = QtWidgets.QPushButton("Save As...")
        self.compile_btn = QtWidgets.QPushButton("Compile")
        self.auto_compile_checkbox = QtWidgets.QCheckBox("Auto compile")
        self.auto_compile_checkbox.setChecked(False)
        self.auto_compile_checkbox.setToolTip("Automatically compile the active .mtex document after a short pause.")
        self.logs_output_btn = QtWidgets.QPushButton("Logs & Output Files")
        self.sync_menu_btn = QtWidgets.QToolButton()
        self.sync_menu_btn.setObjectName("workspaceSyncButton")
        self.sync_menu_btn.setText("Sync")
        self.sync_menu_btn.setToolTip("Jump between the editor and the compiled PDF")
        self.sync_menu_btn.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.sync_menu_btn.setEnabled(False)
        self.build_status_label = QtWidgets.QLabel()
        self.build_status_label.setMinimumWidth(240)
        self.build_status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.build_status_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.MinimumExpanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.file_meta_label = QtWidgets.QLabel("Active file")
        self.file_meta_label.setObjectName("toolbarMetaLabel")
        self.file_label = QtWidgets.QLabel("No file open")
        self.file_label.setObjectName("activeFileValue")
        self.file_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        toolbar.addWidget(self.save_btn)
        toolbar.addWidget(self.save_as_btn)
        toolbar.addWidget(self.compile_btn)
        toolbar.addWidget(self.auto_compile_checkbox)
        toolbar.addWidget(self.logs_output_btn)
        toolbar.addWidget(self.sync_menu_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.build_status_label)
        toolbar.addWidget(self.file_meta_label)
        toolbar.addWidget(self.file_label)
        header_layout.addLayout(toolbar)
        layout.addWidget(header_frame)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        self._workspace_splitter = splitter

        left_panel, left_layout, _tree_header = self._create_panel_frame(
            "Project Files",
            "Browse and manage project assets",
            variant="muted",
        )
        left_panel.setMinimumWidth(WORKSPACE_LEFT_MIN_WIDTH)
        tree_actions = QtWidgets.QHBoxLayout()
        tree_actions.setContentsMargins(0, 0, 0, 0)
        tree_actions.setSpacing(WORKSPACE_ROW_SPACING)
        self.new_file_btn = self._make_tree_action_button("New File", "Create a .mtex, .mtx, .ae, or .mtn file")
        self.new_folder_btn = self._make_tree_action_button("New Folder", "Create a folder in the selected folder")
        self.upload_btn = self._make_tree_action_button("Upload", "Copy files into the selected folder")
        self.refresh_tree_btn = self._make_tree_action_button("Refresh", "Refresh the project file tree")
        tree_actions.addWidget(self.new_file_btn)
        tree_actions.addWidget(self.new_folder_btn)
        tree_actions.addWidget(self.upload_btn)
        tree_actions.addWidget(self.refresh_tree_btn)
        tree_actions.addStretch()
        left_layout.addLayout(tree_actions)
        self.file_tree = QtWidgets.QTreeWidget()
        self.file_tree.setObjectName("projectFileTree")
        self.file_tree.setAlternatingRowColors(True)
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setIndentation(18)
        self.file_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.file_tree.itemExpanded.connect(self._on_item_expanded)
        self.file_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        left_layout.addWidget(self.file_tree, 1)
        splitter.addWidget(left_panel)

        self.editor_widget = editor_factory()
        if isinstance(self.editor_widget, QtWidgets.QPlainTextEdit):
            self.editor_widget.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
            self.editor_widget.setObjectName("workspaceMtexEditor")
        self.notebook_view = NotebookView(parent=self)
        self.notebook_view.set_source_provider(
            lambda: self.editor_widget.toPlainText() if isinstance(self.editor_widget, QtWidgets.QPlainTextEdit) else "",
            self._current_file_path,
        )
        self.content_tabs = QtWidgets.QTabWidget()
        self.content_tabs.setObjectName("workspaceContentTabs")
        self.content_tabs.addTab(self.editor_widget, "Source")
        self.content_tabs.addTab(self.notebook_view, "Notebook")
        self.content_tabs.currentChanged.connect(self._handle_content_tab_changed)
        editor_panel, editor_layout, _editor_header = self._create_panel_frame(
            "MathTeX Content (.mtex)",
            "Compose and edit the active document",
            variant="primary",
        )
        editor_panel.setMinimumWidth(WORKSPACE_EDITOR_MIN_WIDTH)
        editor_layout.addWidget(self.content_tabs, 1)
        splitter.addWidget(editor_panel)

        self.preview_widget = preview_factory()
        preview_panel, preview_layout, _preview_header = self._create_panel_frame(
            "PDF Preview",
            "Review the compiled output",
        )
        preview_panel.setMinimumWidth(WORKSPACE_PREVIEW_MIN_WIDTH)
        preview_layout.addWidget(self.preview_widget, 1)
        splitter.addWidget(preview_panel)

        splitter.setStretchFactor(0, WORKSPACE_DEFAULT_SPLITTER_WEIGHTS[0])
        splitter.setStretchFactor(1, WORKSPACE_DEFAULT_SPLITTER_WEIGHTS[1])
        splitter.setStretchFactor(2, WORKSPACE_DEFAULT_SPLITTER_WEIGHTS[2])
        layout.addWidget(splitter, 1)

        self.home_btn.clicked.connect(self.home_requested.emit)
        self.save_btn.clicked.connect(self.save_requested.emit)
        self.save_as_btn.clicked.connect(self.save_as_requested.emit)
        self.compile_btn.clicked.connect(self.compile_requested.emit)
        self.logs_output_btn.clicked.connect(self.logs_output_requested.emit)
        self.new_file_btn.clicked.connect(self._create_new_file)
        self.new_folder_btn.clicked.connect(self._create_new_folder)
        self.upload_btn.clicked.connect(self._upload_files)
        self.refresh_tree_btn.clicked.connect(lambda _checked=False: self.refresh_file_tree())

        self.clear_workspace()

    @property
    def project(self) -> ProjectInfo | None:
        return self._project

    def set_project(self, project: ProjectInfo | None) -> None:
        self._project = project
        if project is None:
            self.clear_workspace()
            return
        self.project_name_label.setText(project.name)
        self.project_path_label.setText(str(project.path))
        self.project_path_label.setToolTip(str(project.path))
        self.refresh_file_tree(selected_path=project.path)

    def clear_workspace(self) -> None:
        self._project = None
        self.file_tree.clear()
        self.project_name_label.setText("No project open")
        self.project_path_label.setText("")
        self.project_path_label.setToolTip("")
        self.file_label.setText("No file open")
        self.set_build_status("Build: Ready")
        if isinstance(self.editor_widget, QtWidgets.QPlainTextEdit):
            self.editor_widget.setPlainText("")
            self.editor_widget.document().setModified(False)
        self.set_notebook_source("")
        preview = getattr(self.preview_widget, "set_message", None)
        if callable(preview):
            preview(self._preview_message)
        self._update_tree_actions_enabled()
        self._update_sync_menu_button_state()

    def set_sync_actions(
        self,
        *,
        forward_action: QtGui.QAction | None,
        inverse_action: QtGui.QAction | None,
    ) -> None:
        for action in self._sync_actions:
            try:
                action.changed.disconnect(self._update_sync_menu_button_state)
            except Exception:
                pass

        self._sync_actions = [action for action in (forward_action, inverse_action) if action is not None]
        menu = QtWidgets.QMenu(self.sync_menu_btn)
        for action in self._sync_actions:
            menu.addAction(action)
            action.changed.connect(self._update_sync_menu_button_state)
        self.sync_menu_btn.setMenu(menu)
        self._update_sync_menu_button_state()

    def refresh_file_tree(self, selected_path: str | Path | None = None) -> None:
        current_selection = self._current_tree_path()
        expanded_paths = self._expanded_tree_paths()
        self.file_tree.clear()
        self._update_tree_actions_enabled()
        if self._project is None:
            return
        root_path = self._project.path
        root_item = QtWidgets.QTreeWidgetItem([root_path.name or str(root_path)])
        root_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, str(root_path))
        self.file_tree.addTopLevelItem(root_item)
        root_item.setExpanded(True)
        self._populate_children(root_item, root_path)
        for expanded_path in expanded_paths:
            if expanded_path == root_path:
                continue
            self._expand_to_path(expanded_path)
        target_path = Path(selected_path) if selected_path is not None else current_selection
        if target_path is not None:
            self._select_tree_path(target_path)
        else:
            self.file_tree.setCurrentItem(root_item)

    def set_current_file_label(self, filename: str) -> None:
        self.file_label.setText(filename)

    def set_notebook_source(self, source: str, path: Path | None = None) -> None:
        self._syncing_notebook_source = True
        try:
            self.notebook_view.set_source(source, path=path)
        finally:
            self._syncing_notebook_source = False

    def sync_notebook_to_editor_if_active(self) -> None:
        if self.content_tabs.currentWidget() is not self.notebook_view:
            return
        self._sync_notebook_to_editor()

    def _handle_content_tab_changed(self, index: int) -> None:
        if self._syncing_notebook_source:
            return
        current_widget = self.content_tabs.widget(index)
        if current_widget is self.notebook_view:
            source = self.editor_widget.toPlainText() if isinstance(self.editor_widget, QtWidgets.QPlainTextEdit) else ""
            self.notebook_view.set_source(source, path=self._current_file_path())
            return
        self._sync_notebook_to_editor()

    def _sync_notebook_to_editor(self) -> None:
        if not isinstance(self.editor_widget, QtWidgets.QPlainTextEdit):
            return
        source = self.notebook_view.to_source()
        if source == self.editor_widget.toPlainText():
            return
        self.editor_widget.setPlainText(source)

    def _current_file_path(self) -> Path | None:
        text = self.file_label.text().strip()
        if not text or text == "No file open" or self._project is None:
            return None
        return self._project.path / text.lstrip("*")

    def set_build_status(self, text: str, tone: str = "neutral") -> None:
        palette = {
            "neutral": ("#d6d6d6", "#2f3a40", "#54606b"),
            "info": ("#d9ecff", "#1f3a56", "#4f8cc9"),
            "success": ("#daf5d4", "#234a2b", "#5ea36b"),
            "warning": ("#fff2cf", "#5a4217", "#d5a84a"),
            "error": ("#ffd7d7", "#5a2222", "#d47b7b"),
        }
        fg, bg, border = palette.get(tone, palette["neutral"])
        self.build_status_label.setText(text)
        self.build_status_label.setStyleSheet(
            f"""
            QLabel {{
                color: {fg};
                background: {bg};
                border: 1px solid {border};
                border-radius: 11px;
                padding: 3px 10px;
            }}
        """
        )

    def _workspace_stylesheet(self) -> str:
        return """
        QWidget#projectWorkspaceRoot {
            background: #181b1f;
        }
        QFrame#workspaceHeaderCard {
            background: #20242a;
            border: 1px solid #333942;
            border-radius: 10px;
        }
        QFrame#workspacePanelMuted {
            background: #20252a;
            border: 1px solid #313740;
            border-radius: 10px;
        }
        QFrame#workspacePanel {
            background: #22272d;
            border: 1px solid #363c45;
            border-radius: 10px;
        }
        QFrame#workspacePanelPrimary {
            background: #252b32;
            border: 1px solid #424b56;
            border-radius: 10px;
        }
        QLabel#projectNameLabel {
            color: #f1f3f5;
            background: transparent;
            border: none;
        }
        QLabel#projectPathLabel {
            color: #89939d;
            background: transparent;
            border: none;
            font-size: 11px;
        }
        QLabel#panelTitle {
            color: #f1f3f5;
            background: transparent;
            border: none;
            font-size: 13px;
            font-weight: 600;
        }
        QLabel#panelSubtitle {
            color: #86909a;
            background: transparent;
            border: none;
            font-size: 11px;
        }
        QLabel#toolbarMetaLabel {
            color: #86909a;
            background: transparent;
            border: none;
            font-size: 11px;
        }
        QLabel#activeFileValue {
            color: #edf1f5;
            background: transparent;
            border: none;
            font-weight: 600;
        }
        QToolButton#treeActionButton {
            background: #262b31;
            border: 1px solid #3a424c;
            border-radius: 6px;
            color: #d7dce1;
            padding: 2px 8px;
            min-height: 22px;
        }
        QToolButton#treeActionButton:hover {
            background: #2d333a;
            border-color: #4b5561;
        }
        QToolButton#treeActionButton:disabled {
            color: #7c858e;
            border-color: #343a42;
        }
        QToolButton#workspaceSyncButton {
            background: #262b31;
            border: 1px solid #3a424c;
            border-radius: 6px;
            color: #d7dce1;
            padding: 3px 10px;
            min-height: 24px;
        }
        QToolButton#workspaceSyncButton:hover {
            background: #2d333a;
            border-color: #4b5561;
        }
        QToolButton#workspaceSyncButton:disabled {
            color: #7c858e;
            border-color: #343a42;
        }
        QTreeWidget#projectFileTree {
            background: #1b1f24;
            alternate-background-color: #20252b;
            border: 1px solid #313740;
            border-radius: 7px;
            color: #e3e6ea;
            padding: 4px;
        }
        QTreeWidget#projectFileTree::item {
            padding: 4px 2px;
        }
        QPlainTextEdit#workspaceMtexEditor {
            background: #1d2228;
            border: 1px solid #414955;
            border-radius: 7px;
            padding: 8px 10px;
        }
        QSplitter::handle {
            background: transparent;
        }
        QSplitter::handle:horizontal {
            width: 10px;
        }
        """

    def _create_panel_frame(
        self,
        title: str,
        subtitle: str,
        *,
        variant: str = "default",
    ) -> tuple[QtWidgets.QFrame, QtWidgets.QVBoxLayout, QtWidgets.QHBoxLayout]:
        frame = QtWidgets.QFrame()
        object_name = {
            "muted": "workspacePanelMuted",
            "primary": "workspacePanelPrimary",
        }.get(variant, "workspacePanel")
        frame.setObjectName(object_name)
        container_layout = QtWidgets.QVBoxLayout(frame)
        container_layout.setContentsMargins(
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
        )
        container_layout.setSpacing(WORKSPACE_SECTION_SPACING)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(WORKSPACE_SECTION_SPACING)
        title_layout = QtWidgets.QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)
        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("panelTitle")
        subtitle_label = QtWidgets.QLabel(subtitle)
        subtitle_label.setObjectName("panelSubtitle")
        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)
        header.addLayout(title_layout, 1)

        header_actions = QtWidgets.QHBoxLayout()
        header_actions.setContentsMargins(0, 0, 0, 0)
        header_actions.setSpacing(WORKSPACE_ROW_SPACING)
        header.addLayout(header_actions)
        container_layout.addLayout(header)

        body_layout = QtWidgets.QVBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(WORKSPACE_SECTION_SPACING)
        container_layout.addLayout(body_layout, 1)
        return frame, body_layout, header_actions

    def _splitter_default_sizes(self, total_width: int) -> list[int]:
        minimums = [
            WORKSPACE_LEFT_MIN_WIDTH,
            WORKSPACE_EDITOR_MIN_WIDTH,
            WORKSPACE_PREVIEW_MIN_WIDTH,
        ]
        weights = list(WORKSPACE_DEFAULT_SPLITTER_WEIGHTS)
        base_width = max(total_width, sum(minimums))
        sizes = [max(int(base_width * weight / sum(weights)), minimum) for weight, minimum in zip(weights, minimums)]
        overflow = sum(sizes) - base_width
        if overflow > 0:
            for index in sorted(range(len(sizes)), key=lambda i: sizes[i] - minimums[i], reverse=True):
                reducible = max(0, sizes[index] - minimums[index])
                if reducible <= 0:
                    continue
                shrink = min(reducible, overflow)
                sizes[index] -= shrink
                overflow -= shrink
                if overflow <= 0:
                    break
        leftover = max(0, total_width - sum(sizes))
        if leftover > 0:
            preview_bonus = max(1, int(leftover * 0.55))
            sizes[2] += preview_bonus
            sizes[1] += leftover - preview_bonus
        return sizes

    def _apply_default_splitter_sizes(self) -> None:
        if self._splitter_defaults_applied or self._workspace_splitter is None:
            return
        total_width = self._workspace_splitter.size().width()
        if total_width <= 0:
            return
        self._workspace_splitter.setSizes(self._splitter_default_sizes(total_width))
        self._splitter_defaults_applied = True

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._apply_default_splitter_sizes)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._splitter_defaults_applied and self.isVisible():
            self._apply_default_splitter_sizes()

    def _populate_children(self, item: QtWidgets.QTreeWidgetItem, path: Path) -> None:
        try:
            entries = sorted(
                (entry for entry in path.iterdir() if self._should_show_entry(entry)),
                key=lambda entry: (not entry.is_dir(), entry.name.lower()),
            )
        except OSError:
            return
        while item.childCount():
            item.takeChild(0)
        for entry in entries:
            child = QtWidgets.QTreeWidgetItem([entry.name])
            child.setData(0, QtCore.Qt.ItemDataRole.UserRole, str(entry))
            item.addChild(child)
            if entry.is_dir():
                placeholder = QtWidgets.QTreeWidgetItem(["(loading)"])
                placeholder.setData(0, QtCore.Qt.ItemDataRole.UserRole, "__placeholder__")
                child.addChild(placeholder)

    def _should_show_entry(self, entry: Path) -> bool:
        return entry.name != PROJECT_METADATA_FILENAME

    def _on_item_expanded(self, item: QtWidgets.QTreeWidgetItem) -> None:
        path_value = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not path_value:
            return
        path = Path(path_value)
        if path.is_dir():
            self._populate_children(item, path)

    def _on_item_double_clicked(self, item: QtWidgets.QTreeWidgetItem, _column: int) -> None:
        path_value = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not path_value:
            return
        path = Path(path_value)
        if path.is_dir():
            item.setExpanded(not item.isExpanded())
            if item.isExpanded():
                self._populate_children(item, path)
            return
        if path.suffix.lower() in OPENABLE_PROJECT_SUFFIXES:
            self.file_open_requested.emit(str(path))

    def _make_tree_action_button(self, text: str, tooltip: str) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton()
        button.setObjectName("treeActionButton")
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAutoRaise(False)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        return button

    def _update_tree_actions_enabled(self) -> None:
        enabled = self._project is not None
        for button in (self.new_file_btn, self.new_folder_btn, self.upload_btn, self.refresh_tree_btn):
            button.setEnabled(enabled)

    def _update_sync_menu_button_state(self) -> None:
        has_actions = bool(self._sync_actions)
        any_enabled = any(action.isEnabled() for action in self._sync_actions)
        self.sync_menu_btn.setEnabled(has_actions and any_enabled)

    def _current_tree_path(self) -> Path | None:
        item = self.file_tree.currentItem()
        if item is None:
            return None
        return self._item_path(item)

    def _expanded_tree_paths(self) -> set[Path]:
        expanded_paths: set[Path] = set()
        for index in range(self.file_tree.topLevelItemCount()):
            self._collect_expanded_paths(self.file_tree.topLevelItem(index), expanded_paths)
        return expanded_paths

    def _collect_expanded_paths(
        self,
        item: QtWidgets.QTreeWidgetItem,
        expanded_paths: set[Path],
    ) -> None:
        path = self._item_path(item)
        if path is not None and item.isExpanded():
            expanded_paths.add(path)
        for child_index in range(item.childCount()):
            self._collect_expanded_paths(item.child(child_index), expanded_paths)

    def _item_path(self, item: QtWidgets.QTreeWidgetItem) -> Path | None:
        path_value = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not path_value or path_value == "__placeholder__":
            return None
        return Path(path_value)

    def _expand_to_path(self, target_path: Path) -> QtWidgets.QTreeWidgetItem | None:
        if self.file_tree.topLevelItemCount() == 0 or self._project is None:
            return None
        root_item = self.file_tree.topLevelItem(0)
        root_path = self._item_path(root_item)
        if root_path is None:
            return None
        try:
            relative_parts = target_path.resolve().relative_to(root_path.resolve()).parts
        except ValueError:
            return None
        current_item = root_item
        current_path = root_path
        for part in relative_parts:
            self._populate_children(current_item, current_path)
            next_item = None
            next_path: Path | None = None
            for child_index in range(current_item.childCount()):
                child = current_item.child(child_index)
                child_path = self._item_path(child)
                if child_path is not None and child_path.name == part:
                    next_item = child
                    next_path = child_path
                    break
            if next_item is None:
                return None
            current_item = next_item
            if next_path is None:
                return None
            current_path = next_path
            if current_path.is_dir():
                current_item.setExpanded(True)
        return current_item

    def _select_tree_path(self, target_path: Path) -> None:
        item = self._expand_to_path(target_path)
        if item is None:
            return
        self.file_tree.setCurrentItem(item)
        self.file_tree.scrollToItem(item)

    def _prompt_for_entry_name(self, title: str, label: str, default_value: str) -> str | None:
        name, accepted = QtWidgets.QInputDialog.getText(self, title, label, text=default_value)
        if not accepted:
            return None
        return name

    def _selected_project_entry(self) -> Path | None:
        return self._current_tree_path()

    def _create_new_file(self) -> None:
        if self._project is None:
            return
        name = self._prompt_for_entry_name("New File", "File name (.mtex, .mtx, .ae, .mtn)", "untitled.mtex")
        if name is None:
            return
        try:
            created_path = self._project_manager.create_project_file(
                self._project.path,
                self._selected_project_entry(),
                name,
            )
            if created_path.suffix.lower() == ".mtn":
                save_notebook_file(new_notebook_document(), created_path)
        except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "New File", str(exc))
            return
        self.refresh_file_tree(selected_path=created_path)
        if created_path.suffix.lower() in OPENABLE_PROJECT_SUFFIXES:
            self.file_open_requested.emit(str(created_path))

    def _create_new_folder(self) -> None:
        if self._project is None:
            return
        name = self._prompt_for_entry_name("New Folder", "Folder name", "untitled-folder")
        if name is None:
            return
        try:
            created_path = self._project_manager.create_project_folder(
                self._project.path,
                self._selected_project_entry(),
                name,
            )
        except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "New Folder", str(exc))
            return
        self.refresh_file_tree(selected_path=created_path)

    def _upload_files(self) -> None:
        if self._project is None:
            return
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Upload Files",
            str(self._project.path),
            "All Files (*)",
        )
        if not filenames:
            return
        selected_entry = self._selected_project_entry()
        try:
            target_directory = self._project_manager.resolve_target_directory(self._project.path, selected_entry)
            result = self._project_manager.upload_files(
                self._project.path,
                selected_entry,
                filenames,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "Upload Files", str(exc))
            return
        self.refresh_file_tree(selected_path=target_directory)
        if result.skipped_existing:
            skipped_names = "\n".join(path.name for path in result.skipped_existing)
            QtWidgets.QMessageBox.warning(
                self,
                "Upload Files",
                f"These files already exist and were skipped:\n{skipped_names}",
            )
