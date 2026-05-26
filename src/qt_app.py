
from __future__ import annotations

import sys
from pathlib import Path

from actions import ActionRegistry
from actions.app_actions import register_main_window_actions
from actions.menu_specs import INTERACTIVE_MENU_SPEC, MenuSpec
from aether.runtime_state import (
    register_plot_listener,
    set_plot_mode,
    unregister_plot_listener,
    change_working_dir,
    get_working_dir,
)
from language_runtime import LEGACY_SUFFIXES, run_source_for_file
from repl import ReplController, create_aether_repl
from ui.console_widget import ConsoleWidget as DockConsoleWidget
from ui.code_editor import (
    BRACKET_ERROR_BG,
    BRACKET_MATCH_BG,
    CodeEditor,
    EDITOR_BG,
    EDITOR_MATCH_BG,
    INDENTATION,
    OCCURRENCE_MATCH_BG,
    PUNCT_COLOR,
    STRING_COLOR,
)
from ui.editor_api import EditorAPI
from ui.editor_factory import configured_editor_kind, create_editor

try:  # pragma: no cover - depende de la instalacion del usuario
    from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
except Exception as exc:  # pragma: no cover - no hay Qt disponible
    raise ImportError("PySide6 no esta disponible") from exc

AETHER_EDITOR_BG = "#1e1e1e"
AETHER_PANEL_BG = "#252526"
AETHER_TOOLBAR_BG = "#2d2d2d"
AETHER_BORDER = "#3c3c3c"
AETHER_MUTED_TEXT = "#9da7b1"
AETHER_TEXT = "#e3e6ea"
AETHER_OUTPUT_TEXT = "#d4d4d4"
AETHER_STATUS_PALETTE = {
    "neutral": ("#d6d6d6", "#2f3a40", "#54606b"),
    "info": ("#d9ecff", "#1f3a56", "#4f8cc9"),
    "success": ("#daf5d4", "#234a2b", "#5ea36b"),
    "warning": ("#fff2cf", "#5a4217", "#d5a84a"),
    "error": ("#ffd7d7", "#5a2222", "#d47b7b"),
}
QT_AVAILABLE = True
INTERACTIVE_MENU_CONTEXT = "interactive"


def _is_editor_api(value) -> bool:
    required_methods = (
        "get_text",
        "set_text",
        "get_cursor_position",
        "set_cursor_position",
        "get_cursor_line_column",
        "go_to_line",
        "has_selection",
        "get_selected_text",
        "get_selection_start_line",
        "insert_text_at_cursor",
        "is_modified",
        "set_modified",
        "connect_modification_changed",
        "set_diagnostics",
        "clear_diagnostics",
        "set_completions",
        "set_autocomplete_document_kind",
        "set_autocomplete_workspace_provider",
        "set_surface_theme",
        "focus_editor",
    )
    return all(callable(getattr(value, method_name, None)) for method_name in required_methods)


DARK_APP_STYLESHEET = f"""
QWidget {{
    background: #181b1f;
    color: {AETHER_TEXT};
    selection-background-color: #315f8f;
    selection-color: #ffffff;
}}
QMainWindow,
QDialog,
QMessageBox,
QFileDialog {{
    background: #181b1f;
    color: {AETHER_TEXT};
}}
QMenuBar {{
    background: #20242a;
    color: {AETHER_TEXT};
    border-bottom: 1px solid #333942;
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 10px;
}}
QMenuBar::item:selected,
QMenuBar::item:pressed {{
    background: #2d333a;
}}
QMenu {{
    background: #20242a;
    color: {AETHER_TEXT};
    border: 1px solid #3a424c;
}}
QMenu::item {{
    padding: 5px 26px 5px 24px;
}}
QMenu::item:selected {{
    background: #315f8f;
    color: #ffffff;
}}
QMenu::separator {{
    height: 1px;
    background: #3a424c;
    margin: 5px 8px;
}}
QTabWidget::pane {{
    background: #181b1f;
    border: 1px solid #333942;
}}
QTabBar::tab {{
    background: #20242a;
    color: {AETHER_MUTED_TEXT};
    border: 1px solid #333942;
    padding: 7px 12px;
}}
QTabBar::tab:selected {{
    background: #262b31;
    color: {AETHER_TEXT};
}}
QTabBar::tab:hover {{
    background: #2d333a;
}}
QPushButton,
QToolButton {{
    background: #262b31;
    border: 1px solid #3a424c;
    border-radius: 6px;
    color: #d7dce1;
    padding: 4px 10px;
}}
QPushButton:hover,
QToolButton:hover {{
    background: #2d333a;
    border-color: #4b5561;
}}
QPushButton:pressed,
QToolButton:pressed {{
    background: #1f2328;
}}
QPushButton:disabled,
QToolButton:disabled {{
    color: #7c858e;
    border-color: #343a42;
    background: #20242a;
}}
QLineEdit,
QPlainTextEdit,
QTextEdit,
QComboBox,
QSpinBox,
QDoubleSpinBox {{
    background: #15181d;
    color: {AETHER_TEXT};
    border: 1px solid #3a424c;
    border-radius: 5px;
    padding: 3px 6px;
}}
QLineEdit:focus,
QPlainTextEdit:focus,
QTextEdit:focus,
QComboBox:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {{
    border-color: #4f8cc9;
}}
QComboBox QAbstractItemView,
QListView,
QListWidget,
QTreeView,
QTreeWidget,
QTableView,
QTableWidget {{
    background: #1b1f24;
    alternate-background-color: #20252b;
    color: {AETHER_TEXT};
    border: 1px solid #313740;
    selection-background-color: #315f8f;
    selection-color: #ffffff;
}}
QHeaderView::section {{
    background: #262b31;
    color: {AETHER_MUTED_TEXT};
    border: 1px solid #3a424c;
    padding: 4px 6px;
}}
QCheckBox,
QRadioButton,
QLabel {{
    background: transparent;
    color: {AETHER_TEXT};
}}
QCheckBox::indicator,
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
}}
QCheckBox::indicator:unchecked,
QRadioButton::indicator:unchecked {{
    background: #15181d;
    border: 1px solid #4a5360;
}}
QCheckBox::indicator:checked,
QRadioButton::indicator:checked {{
    background: #315f8f;
    border: 1px solid #5a93c7;
}}
QStatusBar {{
    background: #20242a;
    color: {AETHER_TEXT};
    border-top: 1px solid #333942;
}}
QToolTip {{
    background: #20242a;
    color: {AETHER_TEXT};
    border: 1px solid #4a5360;
    padding: 4px;
}}
QScrollArea,
QScrollArea > QWidget > QWidget {{
    background: #181b1f;
}}
QScrollBar:vertical,
QScrollBar:horizontal {{
    background: #181b1f;
    border: none;
    margin: 0;
}}
QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {{
    background: #3a424c;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {{
    background: #4b5561;
}}
QScrollBar::add-line,
QScrollBar::sub-line,
QScrollBar::add-page,
QScrollBar::sub-page {{
    background: transparent;
    border: none;
    width: 0;
    height: 0;
}}
QSplitter::handle {{
    background: #20242a;
}}
"""


def apply_dark_qt_theme(app: QtWidgets.QApplication | None = None) -> None:
    """Force Aether Studio to use a dark Qt theme regardless of the OS theme."""
    app = app or QtWidgets.QApplication.instance()
    if app is None:
        return

    if "Fusion" in QtWidgets.QStyleFactory.keys():
        app.setStyle("Fusion")

    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#181b1f"))
    palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(AETHER_TEXT))
    palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor("#15181d"))
    palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor("#20252b"))
    palette.setColor(QtGui.QPalette.ColorRole.ToolTipBase, QtGui.QColor("#20242a"))
    palette.setColor(QtGui.QPalette.ColorRole.ToolTipText, QtGui.QColor(AETHER_TEXT))
    palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(AETHER_TEXT))
    palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor("#262b31"))
    palette.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor("#d7dce1"))
    palette.setColor(QtGui.QPalette.ColorRole.BrightText, QtGui.QColor("#ffffff"))
    palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor("#315f8f"))
    palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor("#ffffff"))
    palette.setColor(
        QtGui.QPalette.ColorGroup.Disabled,
        QtGui.QPalette.ColorRole.WindowText,
        QtGui.QColor("#7c858e"),
    )
    palette.setColor(
        QtGui.QPalette.ColorGroup.Disabled,
        QtGui.QPalette.ColorRole.Text,
        QtGui.QColor("#7c858e"),
    )
    palette.setColor(
        QtGui.QPalette.ColorGroup.Disabled,
        QtGui.QPalette.ColorRole.ButtonText,
        QtGui.QColor("#7c858e"),
    )
    app.setPalette(palette)
    app.setStyleSheet(DARK_APP_STYLESHEET)


class AetherStudioWindow(QtWidgets.QMainWindow):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        apply_dark_qt_theme()
        set_plot_mode("interactive")
        self.setWindowTitle("Aether Studio")
        self.resize(1200, 720)
        self.aether_repl = create_aether_repl()
        self.console_engine: ReplController = self.aether_repl
        self._plot_listener_registered = False
        self._plot_windows: list[QtWidgets.QMainWindow] = []
        self._untitled_counter = 1
        self.editor_kind = configured_editor_kind()
        self.script_docs: list[dict] = []
        self.console_dock: QtWidgets.QDockWidget | None = None
        self.console_panel_title_label: QtWidgets.QLabel | None = None
        self.console_panel_subtitle_label: QtWidgets.QLabel | None = None
        self.console_toggle_btn: QtWidgets.QPushButton | None = None
        self.console_restore_btn: QtWidgets.QPushButton | None = None
        self.runtime_status_label: QtWidgets.QLabel | None = None
        self.central_tabs: QtWidgets.QTabWidget | None = None
        self.dir_combo: QtWidgets.QComboBox | None = None
        self.workspace_dock: QtWidgets.QDockWidget | None = None
        self.workspace_table: QtWidgets.QTableWidget | None = None
        self.action_registry = ActionRegistry()
        self._app_actions_initialized = False
        self._menu_actions: dict[str, QtGui.QAction] = {}
        self._register_plot_listener()
        self._build_ui()
        self._apply_aether_stylesheet()
        self._set_runtime_status("Ready", tone="neutral", message="Ready")
        self.console_widget.clear()
        self._build_console_dock()
        self._build_workspace_dock()
        self._sync_console_for_active_tab()

    # ----- UI -------------------------------------------------------------
    def _build_ui(self) -> None:
        self.central_tabs = None
        self.setCentralWidget(self._build_script_tab())
        self._init_restore_buttons()

        self.console_widget = DockConsoleWidget(
            self.console_engine,
            self,
            welcome_text=self.console_engine.profile.welcome_text,
        )
        self.console_widget.command_started.connect(self._on_console_command_started)
        self.console_widget.command_finished.connect(self._on_console_command_finished)
        self.console_widget.executed.connect(self.refresh_workspace_view)
        self.console_widget.restarted.connect(self.refresh_workspace_view)
        self._initialize_menu_actions()
        self._refresh_menu_bar_for_active_context()

    def _init_restore_buttons(self) -> None:
        status = self.statusBar()
        status.setSizeGripEnabled(False)
        self.runtime_status_label = QtWidgets.QLabel("Ready")
        self.runtime_status_label.setMinimumWidth(92)
        self.runtime_status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        status.addPermanentWidget(self.runtime_status_label)
        self._set_runtime_status("Ready", tone="neutral", message="Ready")
        self.console_restore_btn = QtWidgets.QPushButton("Restore Console to Panel")
        self.console_restore_btn.setObjectName("aetherStatusButton")
        if self.console_restore_btn is not None:
            self.console_restore_btn.setVisible(False)
            self.console_restore_btn.clicked.connect(self._restore_console_dock)
            status.addPermanentWidget(self.console_restore_btn)

    def _apply_aether_stylesheet(self) -> None:
        self.setStyleSheet(
            f"""
            QStatusBar {{
                background: #20242a;
                color: {AETHER_TEXT};
                border-top: 1px solid #333942;
            }}
            QStatusBar::item {{
                border: none;
            }}
            QPushButton#aetherStatusButton {{
                background: #262b31;
                border: 1px solid #3a424c;
                border-radius: 6px;
                color: #d7dce1;
                padding: 4px 10px;
            }}
            QPushButton#aetherStatusButton:hover {{
                background: #2d333a;
                border-color: #4b5561;
            }}
            QFrame#aetherToolbarCard {{
                background: {AETHER_TOOLBAR_BG};
                border: 1px solid {AETHER_BORDER};
                border-radius: 10px;
            }}
            QFrame#aetherPanel,
            QFrame#aetherPanelMuted,
            QFrame#aetherPanelPrimary {{
                background: {AETHER_PANEL_BG};
                border-radius: 10px;
            }}
            QFrame#aetherPanel {{
                border: 1px solid {AETHER_BORDER};
            }}
            QFrame#aetherPanelMuted {{
                border: 1px solid #44484f;
            }}
            QFrame#aetherPanelPrimary {{
                border: 1px solid #4a4f58;
            }}
            QLabel#aetherPanelTitle {{
                color: {AETHER_TEXT};
                background: transparent;
                border: none;
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#aetherPanelSubtitle {{
                color: {AETHER_MUTED_TEXT};
                background: transparent;
                border: none;
                font-size: 11px;
            }}
            QLabel#aetherToolbarTitle {{
                color: {AETHER_TEXT};
                background: transparent;
                border: none;
                font-size: 14px;
                font-weight: 600;
            }}
            QLabel#aetherToolbarSubtitle {{
                color: {AETHER_MUTED_TEXT};
                background: transparent;
                border: none;
                font-size: 11px;
            }}
            QToolButton#aetherToolbarIconButton,
            QToolButton#aetherToolbarUtilityButton,
            QFrame#aetherPanel QPushButton,
            QFrame#aetherPanelMuted QPushButton,
            QFrame#aetherPanelPrimary QPushButton {{
                background: #262b31;
                border: 1px solid #3a424c;
                border-radius: 6px;
                color: #d7dce1;
            }}
            QToolButton#aetherToolbarIconButton:hover,
            QToolButton#aetherToolbarUtilityButton:hover,
            QFrame#aetherPanel QPushButton:hover,
            QFrame#aetherPanelMuted QPushButton:hover,
            QFrame#aetherPanelPrimary QPushButton:hover {{
                background: #2d333a;
                border-color: #4b5561;
            }}
            QToolButton#aetherToolbarUtilityButton {{
                padding: 3px 6px;
            }}
            QTabWidget#aetherScriptTabs::pane {{
                background: #20252a;
                border: 1px solid {AETHER_BORDER};
                border-radius: 10px;
                top: -1px;
            }}
            QTabWidget#aetherScriptTabs QTabBar::tab {{
                background: #262b31;
                color: {AETHER_MUTED_TEXT};
                border: 1px solid {AETHER_BORDER};
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 7px 12px;
                margin-right: 3px;
            }}
            QTabWidget#aetherScriptTabs QTabBar::tab:selected {{
                background: {AETHER_EDITOR_BG};
                color: {AETHER_TEXT};
            }}
            QDockWidget#ConsoleDock::title,
            QDockWidget#workspaceDock::title {{
                background: #20242a;
                color: {AETHER_TEXT};
                border: 1px solid #333942;
                padding: 4px 8px;
            }}
            QTableWidget#aetherWorkspaceTable {{
                background: #1b1f24;
                alternate-background-color: #20252b;
                color: {AETHER_TEXT};
                border: 1px solid #313740;
                border-radius: 7px;
                gridline-color: #313740;
                padding: 4px;
            }}
            QTableWidget#aetherWorkspaceTable::item {{
                padding: 4px 2px;
            }}
            QTableWidget#aetherWorkspaceTable QHeaderView::section {{
                background: #262b31;
                color: {AETHER_MUTED_TEXT};
                border: 1px solid #3a424c;
                padding: 4px 6px;
            }}
            QWidget#aetherPlotRoot {{
                background: #181b1f;
            }}
        """
        )

    def _create_aether_panel(
        self,
        title: str,
        subtitle: str,
        content: QtWidgets.QWidget,
        *,
        variant: str = "default",
    ) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName(
            {
                "muted": "aetherPanelMuted",
                "primary": "aetherPanelPrimary",
            }.get(variant, "aetherPanel")
        )
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        header = QtWidgets.QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("aetherPanelTitle")
        subtitle_label = QtWidgets.QLabel(subtitle)
        subtitle_label.setObjectName("aetherPanelSubtitle")
        header.addWidget(title_label)
        header.addWidget(subtitle_label)
        layout.addLayout(header)
        layout.addWidget(content, 1)
        return frame

    def _set_runtime_status(self, state: str, *, tone: str = "neutral", message: str | None = None) -> None:
        fg, bg, border = AETHER_STATUS_PALETTE.get(tone, AETHER_STATUS_PALETTE["neutral"])
        if self.runtime_status_label is not None:
            self.runtime_status_label.setText(state)
            self.runtime_status_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {fg};
                    background: {bg};
                    border: 1px solid {border};
                    border-radius: 11px;
                    padding: 3px 10px;
                    font-weight: 600;
                }}
            """
            )
        self.statusBar().showMessage(message or state)

    def _on_console_command_started(self, _command: str) -> None:
        self._set_runtime_status("Running", tone="info", message="Running Aether input...")

    def _on_console_command_finished(self, success: bool) -> None:
        if success:
            self._set_runtime_status("Done", tone="success", message="Command completed.")
            return
        self._set_runtime_status("Error", tone="error", message="Command completed with errors.")

    def _theme_icon(
        self,
        names: tuple[str, ...],
        fallback: QtWidgets.QStyle.StandardPixmap | None = None,
    ) -> QtGui.QIcon:
        for name in names:
            icon = QtGui.QIcon.fromTheme(name)
            if not icon.isNull():
                return icon
        if fallback is not None:
            return self.style().standardIcon(fallback)
        return QtGui.QIcon()

    def _ibeam_icon(self, size: int = 12) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        pen = QtGui.QPen(QtGui.QColor("#f2f2f2"))
        pen.setWidth(2)
        painter.setPen(pen)
        center_x = size // 2
        top = 2
        bottom = size - 3
        painter.drawLine(center_x, top, center_x, bottom)
        painter.drawLine(center_x - 3, top, center_x + 3, top)
        painter.drawLine(center_x - 3, bottom, center_x + 3, bottom)
        painter.end()
        return QtGui.QIcon(pixmap)

    def _compose_icon(
        self,
        base_icon: QtGui.QIcon,
        overlay_icon: QtGui.QIcon,
        size: int = 20,
    ) -> QtGui.QIcon:
        if base_icon.isNull():
            return overlay_icon
        base = base_icon.pixmap(size, size)
        if base.isNull():
            return base_icon
        overlay_size = max(10, int(size * 0.5))
        overlay = overlay_icon.pixmap(overlay_size, overlay_size)
        if overlay.isNull():
            return base_icon
        painter = QtGui.QPainter(base)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        x = size - overlay.width() - 1
        y = size - overlay.height() - 1
        painter.fillRect(x - 1, y - 1, overlay.width() + 2, overlay.height() + 2, QtGui.QColor(30, 30, 30, 220))
        painter.drawPixmap(x, y, overlay)
        painter.end()
        return QtGui.QIcon(base)

    def _make_script_icon_button(self, icon: QtGui.QIcon, tooltip: str) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton()
        button.setObjectName("aetherToolbarIconButton")
        button.setAutoRaise(False)
        button.setText("")
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setIcon(icon)
        button.setIconSize(QtCore.QSize(18, 18))
        button.setFixedSize(30, 28)
        return button

    def _initialize_menu_actions(self) -> None:
        if self._menu_actions:
            return
        self._initialize_app_actions()
        self._menu_actions = {
            "interactive_new_script": self._make_menu_action("New Script", self._new_script_file),
            "interactive_open_script": self._make_registered_qaction("file.open", "Open Script..."),
            "interactive_save_script": self._make_registered_qaction("file.save", "Save"),
            "interactive_save_script_as": self._make_menu_action("Save As...", self._save_script_file_as, shortcut="Ctrl+Shift+S"),
            "interactive_close_script": self._make_menu_action("Close Script", self._close_current_script),
            "interactive_exit": self._make_menu_action("Exit", self.close),
            "interactive_show_console": self._make_menu_action("Show/Focus Console", self._show_console),
            "interactive_show_workspace": self._make_menu_action("Show/Focus Workspace", self._show_workspace_panel),
            "interactive_restore_console": self._make_menu_action("Restore Console to Panel", self._restore_console_dock),
            "interactive_reset_layout": self._make_menu_action("Reset Panel Layout", self._reset_interactive_panel_layout),
            "interactive_run_script": self._make_registered_qaction(
                "run.current",
                "Run Script",
                shortcut_aliases=("Ctrl+Return",),
            ),
            "interactive_run_selection": self._make_menu_action("Run Selection", self.run_selection),
            "interactive_clear_console": self._make_menu_action("Clear Console", self._clear_console_output),
            "interactive_choose_directory": self._make_menu_action("Choose Working Directory...", self._select_directory),
            "interactive_parent_directory": self._make_menu_action("Go to Parent Directory", self._go_parent_directory),
            "edit_undo": self._make_menu_action("Undo", lambda: self._invoke_context_editor("undo"), shortcut=QtGui.QKeySequence.StandardKey.Undo),
            "edit_redo": self._make_menu_action("Redo", lambda: self._invoke_context_editor("redo"), shortcut=QtGui.QKeySequence.StandardKey.Redo),
            "edit_cut": self._make_menu_action("Cut", lambda: self._invoke_context_editor("cut"), shortcut=QtGui.QKeySequence.StandardKey.Cut),
            "edit_copy": self._make_menu_action("Copy", lambda: self._invoke_context_editor("copy"), shortcut=QtGui.QKeySequence.StandardKey.Copy),
            "edit_paste": self._make_menu_action("Paste", lambda: self._invoke_context_editor("paste"), shortcut=QtGui.QKeySequence.StandardKey.Paste),
            "edit_select_all": self._make_menu_action(
                "Select All",
                lambda: self._invoke_context_editor("selectAll"),
                shortcut=QtGui.QKeySequence.StandardKey.SelectAll,
            ),
            "help_about": self._make_menu_action("About Aether Studio", self._show_about_dialog),
            "help_interactive": self._make_menu_action("Aether Help", self._show_interactive_help),
        }

    def _initialize_app_actions(self) -> None:
        if self._app_actions_initialized:
            return
        register_main_window_actions(self, self.action_registry)
        self._app_actions_initialized = True

    def _run_action(self, action_id: str) -> None:
        self.action_registry.run(action_id)
        self._update_menu_action_states()

    def _can_open_current_context_file(self) -> bool:
        return True

    def _open_current_context_file(self) -> None:
        self._open_script_file()

    def _can_save_current_context_file(self) -> bool:
        return hasattr(self, "script_tab_widget") and self._current_script_doc() is not None

    def _save_current_context_file(self) -> None:
        self._save_script_file()

    def _can_run_current_action(self) -> bool:
        return (
            self._current_menu_context() == INTERACTIVE_MENU_CONTEXT
            and hasattr(self, "script_tab_widget")
            and self._current_script_doc() is not None
        )

    def _open_aether_repl(self) -> None:
        changed = self.console_engine is not self.aether_repl
        self.console_engine = self.aether_repl
        if hasattr(self, "console_widget") and self.console_widget is not None:
            self.console_widget.set_engine(self.aether_repl, clear=changed)
        self._apply_repl_panel_profile()
        self._show_console()

    def _make_menu_action(
        self,
        text: str,
        slot,
        *,
        shortcut: str | QtGui.QKeySequence.StandardKey | list[str] | tuple[str, ...] | None = None,
        checkable: bool = False,
    ) -> QtGui.QAction:
        action = QtGui.QAction(text, self)
        if shortcut is not None:
            if isinstance(shortcut, (list, tuple)):
                action.setShortcuts([QtGui.QKeySequence(value) for value in shortcut])
            elif isinstance(shortcut, str):
                action.setShortcut(QtGui.QKeySequence(shortcut))
            else:
                action.setShortcuts(shortcut)
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        return action

    def _make_registered_qaction(
        self,
        action_id: str,
        text: str | None = None,
        *,
        shortcut_aliases: tuple[str, ...] = (),
    ) -> QtGui.QAction:
        app_action = self.action_registry.get(action_id)
        action = QtGui.QAction(text or app_action.label, self)
        shortcuts = []
        if app_action.shortcut:
            shortcuts.append(QtGui.QKeySequence(app_action.shortcut))
        shortcuts.extend(QtGui.QKeySequence(value) for value in shortcut_aliases)
        if shortcuts:
            action.setShortcuts(shortcuts)
        action.triggered.connect(lambda _checked=False, action_id=action_id: self._run_action(action_id))
        action.setEnabled(self.action_registry.is_enabled(action_id))
        return action

    def _sync_registered_qaction_enabled(
        self,
        menu_action_id: str,
        app_action_id: str,
        context_enabled: bool = True,
    ) -> None:
        self._menu_actions[menu_action_id].setEnabled(
            context_enabled and self.action_registry.is_enabled(app_action_id)
        )

    def _current_menu_context(self) -> str:
        return INTERACTIVE_MENU_CONTEXT

    def _set_active_main_tab(self, index: int) -> None:
        self._handle_active_context_changed()

    def _handle_active_context_changed(self) -> None:
        self._sync_repl_for_active_script()
        self._sync_console_for_active_tab()
        self._refresh_menu_bar_for_active_context()

    def _handle_script_tab_changed(self) -> None:
        self._sync_repl_for_active_script()
        self._refresh_menu_bar_for_active_context()

    def _current_repl_controller(self) -> ReplController:
        return self.aether_repl

    def _sync_repl_for_active_script(self) -> None:
        target = self._current_repl_controller()
        changed = target is not self.console_engine
        self.console_engine = target
        if hasattr(self, "console_widget") and self.console_widget is not None:
            self.console_widget.set_engine(target, clear=changed)
        self._apply_repl_panel_profile()
        self.refresh_workspace_view()

    def _apply_repl_panel_profile(self) -> None:
        profile = self.console_engine.profile
        if self.console_dock is not None:
            self.console_dock.setWindowTitle(profile.title)
        if self.console_panel_title_label is not None:
            self.console_panel_title_label.setText(profile.title)
        if self.console_panel_subtitle_label is not None:
            self.console_panel_subtitle_label.setText(profile.subtitle)

    def _refresh_menu_bar_for_active_context(self) -> None:
        if not self._menu_actions:
            return
        self._update_menu_action_states()
        menu_bar = self.menuBar()
        menu_bar.clear()
        self._build_interactive_menus(menu_bar)

    def _build_interactive_menus(self, menu_bar: QtWidgets.QMenuBar) -> None:
        built_menus = self._build_menus_from_spec(menu_bar, INTERACTIVE_MENU_SPEC)
        view_menu = built_menus.get("View")
        if view_menu is not None and self.console_dock is not None:
            view_menu.addSeparator()
            toggle_action = self.console_dock.toggleViewAction()
            toggle_action.setText("Console")
            view_menu.addAction(toggle_action)

    def _build_menus_from_spec(
        self,
        menu_bar: QtWidgets.QMenuBar,
        spec: MenuSpec,
    ) -> dict[str, QtWidgets.QMenu]:
        return {
            title: self._add_menu(menu_bar, title, entries)
            for title, entries in spec.items()
        }

    def _add_menu(self, menu_bar: QtWidgets.QMenuBar, title: str, entries: list[str | None]) -> QtWidgets.QMenu:
        menu = menu_bar.addMenu(title)
        menu.aboutToShow.connect(self._update_menu_action_states)
        for entry in entries:
            if entry is None:
                menu.addSeparator()
                continue
            action = self._menu_actions.get(entry)
            if action is not None:
                menu.addAction(action)
        return menu

    def _update_menu_action_states(self) -> None:
        actions = self._menu_actions
        if not actions:
            return

        interactive_context_active = True
        script_doc = self._current_script_doc() if hasattr(self, "script_tab_widget") else None
        has_script_doc = script_doc is not None
        script_editor = self._active_script_editor()
        context_editor = self._context_editor()
        has_editor = context_editor is not None

        for key in ("edit_undo", "edit_redo", "edit_cut", "edit_copy", "edit_paste", "edit_select_all"):
            actions[key].setEnabled(has_editor)

        actions["interactive_new_script"].setEnabled(interactive_context_active)
        self._sync_registered_qaction_enabled("interactive_open_script", "file.open", interactive_context_active)
        self._sync_registered_qaction_enabled("interactive_save_script", "file.save", interactive_context_active)
        actions["interactive_save_script_as"].setEnabled(interactive_context_active and has_script_doc)
        actions["interactive_close_script"].setEnabled(interactive_context_active and has_script_doc)
        self._sync_registered_qaction_enabled("interactive_run_script", "run.current", interactive_context_active)
        actions["interactive_run_selection"].setEnabled(
            interactive_context_active and script_editor is not None and script_editor.has_selection()
        )
        actions["interactive_show_console"].setEnabled(interactive_context_active and self.console_dock is not None)
        actions["interactive_show_workspace"].setEnabled(interactive_context_active and self.workspace_dock is not None)
        actions["interactive_restore_console"].setEnabled(
            interactive_context_active and self.console_dock is not None and self.console_dock.isFloating()
        )
        actions["interactive_reset_layout"].setEnabled(
            interactive_context_active and (self.console_dock is not None or self.workspace_dock is not None)
        )
        actions["interactive_clear_console"].setEnabled(interactive_context_active)
        actions["interactive_choose_directory"].setEnabled(interactive_context_active)
        actions["interactive_parent_directory"].setEnabled(interactive_context_active)

    def _build_script_tab(self) -> QtWidgets.QWidget:
        root = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        toolbar_card = QtWidgets.QFrame()
        toolbar_card.setObjectName("aetherToolbarCard")
        toolbar_layout = QtWidgets.QVBoxLayout(toolbar_card)
        toolbar_layout.setContentsMargins(10, 10, 10, 10)
        toolbar_layout.setSpacing(8)

        toolbar_header = QtWidgets.QVBoxLayout()
        toolbar_header.setContentsMargins(0, 0, 0, 0)
        toolbar_header.setSpacing(2)
        toolbar_title = QtWidgets.QLabel("Aether")
        toolbar_title.setObjectName("aetherToolbarTitle")
        toolbar_subtitle = QtWidgets.QLabel("Working directory and execution shortcuts")
        toolbar_subtitle.setObjectName("aetherToolbarSubtitle")
        toolbar_header.addWidget(toolbar_title)
        toolbar_header.addWidget(toolbar_subtitle)
        toolbar_layout.addLayout(toolbar_header)

        directory_row = QtWidgets.QHBoxLayout()
        directory_row.setSpacing(6)
        directory_label = QtWidgets.QLabel("Working Directory:")
        directory_label.setStyleSheet(f"color: {AETHER_MUTED_TEXT};")
        directory_row.addWidget(directory_label)

        self.dir_combo = QtWidgets.QComboBox()
        self.dir_combo.setEditable(True)
        self.dir_combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.dir_combo.setMinimumWidth(320)
        self.dir_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.dir_combo.setStyleSheet(
            f"""
            QComboBox {{
                background: #262b31;
                color: {AETHER_TEXT};
                border: 1px solid #3a424c;
                border-radius: 4px;
                padding: 3px 8px;
            }}
            QComboBox:focus {{
                border: 1px solid #4f8cc9;
            }}
            QComboBox QAbstractItemView {{
                background: #1f2328;
                color: {AETHER_TEXT};
                selection-background-color: #2d333a;
            }}
        """
        )
        self.dir_combo.activated.connect(lambda _idx: self._apply_working_dir_from_text(self.dir_combo.currentText()))
        line_edit = self.dir_combo.lineEdit()
        if line_edit is not None:
            line_edit.returnPressed.connect(lambda: self._apply_working_dir_from_text(line_edit.text()))
        directory_row.addWidget(self.dir_combo, 1)

        style = self.style()
        up_btn = QtWidgets.QToolButton()
        up_btn.setObjectName("aetherToolbarUtilityButton")
        up_btn.setToolTip("Go up one level")
        up_btn.setAutoRaise(True)
        up_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowUp))
        up_btn.clicked.connect(self._go_parent_directory)
        directory_row.addWidget(up_btn)

        browse_btn = QtWidgets.QToolButton()
        browse_btn.setObjectName("aetherToolbarUtilityButton")
        browse_btn.setToolTip("Choose directory")
        browse_btn.setAutoRaise(True)
        browse_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirClosedIcon))
        browse_btn.clicked.connect(self._select_directory)
        directory_row.addWidget(browse_btn)
        toolbar_layout.addLayout(directory_row)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(6)
        new_icon = self._theme_icon(
            ("document-new-symbolic",),
            QtWidgets.QStyle.StandardPixmap.SP_FileIcon,
        )
        open_icon = self._theme_icon(
            ("folder-documents-symbolic", "document-open-symbolic"),
            QtWidgets.QStyle.StandardPixmap.SP_DirOpenIcon,
        )
        save_icon = self._theme_icon(
            ("document-save-symbolic", "media-floppy-symbolic"),
            QtWidgets.QStyle.StandardPixmap.SP_DialogSaveButton,
        )
        save_as_icon = self._theme_icon(
            ("document-save-as-symbolic",),
            QtWidgets.QStyle.StandardPixmap.SP_DialogSaveButton,
        )
        run_all_icon = self._theme_icon(
            ("media-playback-start-symbolic",),
            QtWidgets.QStyle.StandardPixmap.SP_MediaPlay,
        )
        cursor_icon = self._theme_icon(("insert-text-symbolic",))
        if cursor_icon.isNull():
            cursor_icon = self._ibeam_icon()
        run_sel_icon = self._compose_icon(run_all_icon, cursor_icon)

        new_btn = self._make_script_icon_button(new_icon, "New File")
        open_btn = self._make_script_icon_button(open_icon, "Open .ae")
        save_btn = self._make_script_icon_button(save_icon, "Save")
        save_as_btn = self._make_script_icon_button(save_as_icon, "Save As...")
        run_all = self._make_script_icon_button(run_all_icon, "Run All (Ctrl+Enter)")
        run_sel = self._make_script_icon_button(run_sel_icon, "Run Selection")
        buttons.addWidget(new_btn)
        buttons.addWidget(open_btn)
        buttons.addWidget(save_btn)
        buttons.addWidget(save_as_btn)
        buttons.addWidget(run_all)
        buttons.addWidget(run_sel)
        buttons.addStretch()
        toolbar_layout.addLayout(buttons)
        layout.addWidget(toolbar_card)

        self.script_tab_widget = QtWidgets.QTabWidget()
        self.script_tab_widget.setObjectName("aetherScriptTabs")
        self.script_tab_widget.setTabsClosable(True)
        self.script_tab_widget.tabCloseRequested.connect(self._request_close_script_tab)
        self.script_tab_widget.currentChanged.connect(lambda _idx: self._handle_script_tab_changed())
        editor_panel = self._create_aether_panel(
            "Editor",
            "Edit and run the active .ae script",
            self.script_tab_widget,
            variant="primary",
        )
        layout.addWidget(editor_panel, 1)

        run_all.clicked.connect(lambda _checked=False: self._run_action("run.current"))
        run_sel.clicked.connect(self.run_selection)
        new_btn.clicked.connect(lambda: self._new_script_file())
        open_btn.clicked.connect(lambda _checked=False: self._run_action("file.open"))
        save_btn.clicked.connect(lambda _checked=False: self._run_action("file.save"))
        save_as_btn.clicked.connect(self._save_script_file_as)

        # No se crea archivo vacio al iniciar; el usuario abre o crea manualmente.
        self._sync_working_dir_controls()
        return root

    def _apply_working_dir(self, path: Path) -> None:
        target = path.expanduser()
        if change_working_dir(target):
            self._sync_working_dir_controls()

    def _apply_working_dir_from_text(self, raw_text: str) -> None:
        text = (raw_text or "").strip()
        if not text:
            return
        self._apply_working_dir(Path(text))

    def _go_parent_directory(self) -> None:
        current = get_working_dir()
        parent = current.parent
        if parent != current:
            self._apply_working_dir(parent)

    def _sync_working_dir_controls(self) -> None:
        combo = self.dir_combo
        if combo is None:
            return
        current = str(get_working_dir())
        combo.blockSignals(True)
        if combo.findText(current) == -1:
            combo.insertItem(0, current)
        combo.setCurrentText(current)
        while combo.count() > 15:
            combo.removeItem(combo.count() - 1)
        combo.blockSignals(False)

    def _select_directory(self) -> None:
        current = str(get_working_dir())
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose Working Directory", current)
        if not directory:
            return
        self._apply_working_dir(Path(directory))

    # ----- Consola --------------------------------------------------------
    def append_output(self, text: str, ensure_newline: bool = True) -> None:
        self.console_widget.append_output(text, ensure_newline=ensure_newline)

    def _remove_trailing_prompt(self) -> None:
        return

    def _append_prompt(self) -> None:
        return

    def _script_banner_name(self, doc: dict) -> str:
        path = doc.get("path")
        if path is not None:
            try:
                return Path(path).name
            except Exception:
                pass
        name = str(doc.get("name") or "").strip()
        return name or "untitled.ae"

    def _build_console_dock(self) -> None:
        profile = self.console_engine.profile
        dock = QtWidgets.QDockWidget(profile.title, self)
        panel = self._create_aether_panel(
            profile.title,
            profile.subtitle,
            self.console_widget,
            variant="muted",
        )
        self.console_panel_title_label = panel.findChild(QtWidgets.QLabel, "aetherPanelTitle")
        self.console_panel_subtitle_label = panel.findChild(QtWidgets.QLabel, "aetherPanelSubtitle")
        dock.setWidget(panel)
        dock.setObjectName("ConsoleDock")
        dock.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.BottomDockWidgetArea
            | QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
            | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.topLevelChanged.connect(lambda _f: self._on_console_dock_state_changed())
        dock.visibilityChanged.connect(lambda _v: self._on_console_dock_state_changed())
        self.console_dock = dock
        self._on_console_dock_state_changed()

    def _show_console(self) -> None:
        self._restore_console_dock()

    def _toggle_console_dock(self) -> None:
        dock = self.console_dock
        if dock is None:
            return
        target_state = not dock.isFloating()
        dock.setFloating(target_state)
        dock.show()
        self._on_console_dock_state_changed()

    def _restore_console_dock(self) -> None:
        dock = self.console_dock
        if dock is None:
            return
        dock.setFloating(False)
        dock.show()
        dock.raise_()
        self._on_console_dock_state_changed()

    def _on_console_dock_state_changed(self) -> None:
        dock = self.console_dock
        floating = dock.isFloating() if dock else False
        visible = dock.isVisible() if dock else False
        need_restore = floating or not visible
        if self.console_restore_btn:
            self.console_restore_btn.setVisible(need_restore)
        if self.console_toggle_btn:
            self.console_toggle_btn.setText("Dock" if floating else "Undock")
        if dock and not visible:
            dock.show()
        if dock:
            dock.activateWindow()
        try:
            self.console_widget.input.setFocus()
        except Exception:
            pass

    def _sync_console_for_active_tab(self) -> None:
        dock = self.console_dock
        if dock is not None:
            dock.show()
            self._on_console_dock_state_changed()
        if self.workspace_dock is not None:
            self.workspace_dock.show()

    def _show_workspace_panel(self) -> None:
        if self.workspace_dock is None:
            return
        self.workspace_dock.show()
        self.workspace_dock.raise_()
        if self.workspace_table is not None:
            self.workspace_table.setFocus()

    def _reset_interactive_panel_layout(self) -> None:
        docks: list[QtWidgets.QDockWidget] = []
        if self.console_dock is not None:
            self.console_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.console_dock)
            self.console_dock.show()
            docks.append(self.console_dock)
        if self.workspace_dock is not None:
            self.workspace_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.workspace_dock)
            self.workspace_dock.show()
            docks.append(self.workspace_dock)
        if self.console_dock is not None and self.workspace_dock is not None:
            self.splitDockWidget(self.console_dock, self.workspace_dock, QtCore.Qt.Orientation.Horizontal)
            self.resizeDocks([self.console_dock, self.workspace_dock], [830, 330], QtCore.Qt.Orientation.Horizontal)
        if docks:
            self._on_console_dock_state_changed()

    def _active_script_editor(self) -> EditorAPI | None:
        doc = self._current_script_doc()
        if not doc:
            return None
        widget = doc.get("widget")
        return widget if _is_editor_api(widget) else None

    def _context_editor(self) -> EditorAPI | None:
        return self._active_script_editor()

    def _invoke_context_editor(self, method_name: str) -> None:
        editor = self._context_editor()
        if editor is None:
            return
        handler = getattr(editor, method_name, None)
        if callable(handler):
            handler()
            editor.focus_editor()

    # ----- Workspace ------------------------------------------------------
    def _build_workspace_dock(self) -> None:
        dock = QtWidgets.QDockWidget("Workspace", self)
        dock.setObjectName("workspaceDock")
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        table = QtWidgets.QTableWidget()
        table.setObjectName("aetherWorkspaceTable")
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Name", "Type", "Shape", "Summary"])
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        self._apply_workspace_column_layout(table)
        dock.setWidget(
            self._create_aether_panel(
                "Workspace",
                "Variables and values from the current session",
                table,
            )
        )
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        if self.console_dock is not None:
            self.splitDockWidget(self.console_dock, dock, QtCore.Qt.Orientation.Horizontal)
            self.resizeDocks([self.console_dock, dock], [830, 330], QtCore.Qt.Orientation.Horizontal)
        self.workspace_dock = dock
        self.workspace_table = table

    def _apply_workspace_column_layout(self, table: QtWidgets.QTableWidget) -> None:
        header = table.horizontalHeader()
        for col in range(4):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        table.setColumnWidth(0, 110)
        table.setColumnWidth(1, 90)
        table.setColumnWidth(2, 90)
        table.setColumnWidth(3, 110)

    def refresh_workspace_view(self) -> None:
        try:
            items = self._current_workspace_snapshot()
        except Exception:
            items = []
        table = self.workspace_table
        if table is not None:
            table.setSortingEnabled(False)
            table.clearContents()
            table.setRowCount(len(items))
            for row_idx, info in enumerate(items):
                row_values = [
                    info.get("name", ""),
                    info.get("type") or info.get("class", ""),
                    info.get("shape") or info.get("size", ""),
                    info.get("summary", ""),
                ]
                for col_idx, value in enumerate(row_values):
                    item = QtWidgets.QTableWidgetItem(str(value))
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                    table.setItem(row_idx, col_idx, item)
            table.setSortingEnabled(True)
            self._apply_workspace_column_layout(table)

    def _current_workspace_snapshot(self) -> list[dict[str, str]]:
        return self.console_engine.workspace_snapshot()

    # ----- Script docs ----------------------------------------------------
    def _new_script_file(self, initial: bool = False) -> None:
        name = f"untitled_{self._untitled_counter}.ae"
        self._untitled_counter += 1
        self._create_script_document(name=name, path=None, content="", announce=not initial)

    def _create_script_document(self, name: str, path: Path | None, content: str, announce: bool) -> None:
        editor = create_editor(self.editor_kind, enable_autocomplete=True)
        editor.set_autocomplete_document_kind("script")
        editor.set_autocomplete_workspace_provider(self._current_workspace_snapshot)
        editor.set_surface_theme(
            background=AETHER_EDITOR_BG,
            line_number_color="#858585",
            current_line_color="#2b3036",
        )
        editor.set_text(content)
        editor.text_changed.connect(lambda e=editor: self._mark_script_dirty(e))
        idx = self.script_tab_widget.addTab(editor, name)
        self.script_tab_widget.setCurrentIndex(idx)
        doc = {"widget": editor, "path": path, "name": name, "dirty": False, "tab_index": idx}
        self.script_docs.append(doc)
        self._update_script_tab_title(doc)
        self._sync_repl_for_active_script()
        self._refresh_menu_bar_for_active_context()

    def _current_script_doc(self):
        idx = self.script_tab_widget.currentIndex()
        if idx < 0:
            return None
        widget = self.script_tab_widget.widget(idx)
        for doc in self.script_docs:
            if doc["widget"] is widget:
                return doc
        return None

    def _update_script_tab_title(self, doc: dict) -> None:
        widget = doc.get("widget")
        if widget is None:
            return
        name = doc.get("name") or "untitled.ae"
        title = f"*{name}" if doc.get("dirty") else name
        idx = self.script_tab_widget.indexOf(widget)
        if idx >= 0:
            self.script_tab_widget.setTabText(idx, title)

    def _mark_script_dirty(self, widget: EditorAPI) -> None:
        doc = next((d for d in self.script_docs if d["widget"] is widget), None)
        if not doc:
            return
        doc["dirty"] = True
        self._update_script_tab_title(doc)

    def _request_close_script_tab(self, index: int) -> None:
        widget = self.script_tab_widget.widget(index)
        doc = next((d for d in self.script_docs if d["widget"] is widget), None)
        if not doc:
            self.script_tab_widget.removeTab(index)
            return
        if doc.get("dirty"):
            choice = self._ask_close_confirmation(doc)
            if choice == "cancel":
                return
            if choice == "save" and not self._save_script_document(doc):
                return
        self._remove_script_doc(doc)

    def _remove_script_doc(self, doc: dict) -> None:
        widget = doc.get("widget")
        if widget:
            idx = self.script_tab_widget.indexOf(widget)
            if idx >= 0:
                self.script_tab_widget.removeTab(idx)
        if doc in self.script_docs:
            self.script_docs.remove(doc)

        self._sync_repl_for_active_script()
        self._refresh_menu_bar_for_active_context()

    def _close_current_script(self) -> None:
        if not hasattr(self, "script_tab_widget"):
            return
        index = self.script_tab_widget.currentIndex()
        if index >= 0:
            self._request_close_script_tab(index)
    def _ask_close_confirmation(self, doc: dict) -> str:
        path = doc.get("path")
        location = str(path) if path else doc.get("name", "unsaved file")
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle("Close File")
        dialog.setText(
            f"The file {location} is about to close with unsaved changes.\n"
            "Do you want to cancel, save, or discard those changes?"
        )
        dialog.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Save
            | QtWidgets.QMessageBox.StandardButton.Discard
            | QtWidgets.QMessageBox.StandardButton.Cancel
        )
        dialog.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Save)
        result = dialog.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Save:
            return "save"
        if result == QtWidgets.QMessageBox.StandardButton.Discard:
            return "discard"
        return "cancel"

    def _prompt_script_destination(self, doc=None):
        initial = "new_script.ae"
        if doc and doc.get("path"):
            try:
                initial = Path(doc["path"]).name
            except Exception:
                initial = str(doc["path"])
        elif doc and doc.get("name"):
            initial = doc.get("name")
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Script",
            str(get_working_dir() / initial),
            "Aether Files (*.ae);;All Files (*)",
        )
        if not filename:
            return None
        path = Path(filename)
        if path.suffix.lower() != ".ae":
            path = path.with_suffix(".ae")
        return path

    def _write_script_document(self, doc: dict, path: Path) -> None:
        widget: EditorAPI | None = doc.get("widget")
        if not widget:
            return
        content = widget.get_text()
        path.write_text(content, encoding="utf-8")

    def _persist_script_document(self, doc: dict, path: Path) -> bool:
        if self._is_legacy_file_path(path):
            self._show_legacy_file_message(path)
            return False
        if path.suffix.lower() != ".ae":
            path = path.with_suffix(".ae")
        try:
            self._write_script_document(doc, path)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Aether Studio", f"Could not save the file.\n{exc}")
            return False
        doc["path"] = path
        doc["name"] = path.name
        doc["dirty"] = False
        self._update_script_tab_title(doc)
        self._sync_repl_for_active_script()
        return True

    def _save_script_document(self, doc) -> bool:
        if not doc:
            return False
        destination = doc.get("path")
        if destination:
            return self._persist_script_document(doc, Path(destination))
        dest = self._prompt_script_destination(doc)
        if not dest:
            return False
        return self._persist_script_document(doc, dest)

    def _save_script_file(self) -> bool:
        doc = self._current_script_doc()
        if not doc:
            return False
        if doc.get("path") is None:
            return self._save_script_file_as() is not None
        return self._persist_script_document(doc, Path(doc["path"]))

    def _save_script_file_as(self):
        doc = self._current_script_doc()
        if not doc:
            return None
        destination = self._prompt_script_destination(doc)
        if not destination:
            return None
        if self._persist_script_document(doc, destination):
            return destination
        return None

    def _find_script_doc_by_path(self, path: Path):
        target = None
        try:
            target = Path(path).resolve()
        except Exception:
            target = None
        for doc in self.script_docs:
            existing = doc.get("path")
            if not existing:
                continue
            try:
                if Path(existing).resolve() == target:
                    return doc
            except Exception:
                continue
        return None

    def _open_script_file(self, path: Path | str | None = None) -> None:
        # The clicked signal from Qt can pass a boolean "checked" flag; normalize that away.
        if isinstance(path, bool):
            path = None
        if isinstance(path, str):
            path = Path(path)
        if path is None:
            filename, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Open Script File",
                str(get_working_dir()),
                "Aether Files (*.ae);;All Files (*)",
            )
            if not filename:
                return
            path = Path(filename)
        if self._is_legacy_file_path(path):
            self._show_legacy_file_message(path)
            return
        if path.suffix.lower() != ".ae":
            QtWidgets.QMessageBox.information(
                self,
                "Aether Studio",
                "Aether Studio opens and runs .ae scripts only.",
            )
            return
        existing_doc = self._find_script_doc_by_path(path)
        if existing_doc:
            widget = existing_doc.get("widget")
            if widget:
                idx = self.script_tab_widget.indexOf(widget)
                if idx >= 0:
                    self.script_tab_widget.setCurrentIndex(idx)
            self._set_active_main_tab(0)
            self.append_output(f"[Script] {path.name} was already open. Tab activated.")
            return
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Aether Studio", f"Could not open the file.\n{exc}")
            return
        self._create_script_document(name=path.name, path=path, content=content, announce=False)
        self._set_active_main_tab(0)

    def _is_legacy_file_path(self, path: Path) -> bool:
        return path.suffix.lower() in LEGACY_SUFFIXES

    def _show_legacy_file_message(self, path: Path) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "Aether Studio",
            (
                f"{path.name} uses a legacy format ({path.suffix}).\n"
                "Aether Studio now supports .ae scripts only. Use or convert this file to .ae."
            ),
        )

    def _clear_console_output(self) -> None:
        if hasattr(self, "console_widget") and self.console_widget is not None:
            self.console_widget.clear()

    def _show_about_dialog(self) -> None:
        QtWidgets.QMessageBox.about(
            self,
            "About Aether Studio",
            (
                "Aether Studio is focused on the Aether workflow:\n\n"
                "- .ae scripts in the editor.\n"
                "- Aether REPL and workspace inspection.\n"
                "- Working directory controls for local script workflows."
            ),
        )

    def _show_interactive_help(self) -> None:
        if self._open_documentation_file("docs/aether/AETHER_V0_SPEC.md"):
            self.append_output("[Help] Opened the Aether guide.")
            return
        QtWidgets.QMessageBox.information(
            self,
            "Aether Help",
            "The guide file could not be opened. Aether Studio supports .ae scripts and the Aether REPL.",
        )

    def _open_documentation_file(self, relative_path: str) -> bool:
        doc_path = Path(__file__).resolve().parents[1] / relative_path
        if not doc_path.exists():
            return False
        return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(doc_path)))

    def _update_window_title(self) -> None:
        self.setWindowTitle("Aether Studio")

    # ----- Ejecucion ------------------------------------------------------
    def _execute_line(self, line: str, echo: bool = True) -> bool:
        stripped = line.strip()
        if not stripped:
            return True
        events = self.console_engine.execute_line(stripped)
        if echo:
            self.append_output(f"{self.console_engine.prompt}{stripped}")
        if hasattr(self, "console_widget") and self.console_widget is not None:
            self.console_widget.render_events(events)
        self.refresh_workspace_view()
        return not any(event.kind == "error" for event in events)

    def run_command(self) -> None:
        self.console_widget.submit_current_input()
        self.console_widget.input.setFocus()

    def run_script(self) -> None:
        doc = self._current_script_doc()
        if not doc:
            self.append_output("There is no active editor to run.")
            return
        widget: EditorAPI = doc["widget"]
        contenido = widget.get_text()
        if not self._script_doc_is_aether_supported(doc):
            return
        self._run_aether_script(doc, contenido)

    def _run_aether_script(self, doc: dict, source: str) -> None:
        if not source.strip():
            self.append_output("There is no code to run.")
            return
        script_name = self._script_banner_name(doc)
        self._set_runtime_status("Running", tone="info", message=f"Running {script_name} with Aether...")
        self.append_output(f">> {script_name}")
        result = run_source_for_file(doc.get("path") or doc.get("name"), source)
        if result.output:
            self.append_output(result.output, ensure_newline=False)
        if result.success:
            if not result.output:
                self.append_output("Aether program executed successfully.")
            self._set_runtime_status("Done", tone="success", message=f"{script_name} finished.")
            return
        self.append_output(result.error or "Aether execution failed.")
        self._set_runtime_status("Error", tone="error", message=f"{script_name} stopped due to an error.")

    def run_selection(self) -> None:
        doc = self._current_script_doc()
        if not doc:
            self.append_output("There is no active editor to run.")
            return
        widget_api: EditorAPI = doc["widget"]
        if not widget_api.has_selection():
            self.append_output("Select a block in the editor to run only that part.")
            return
        seleccion = widget_api.get_selected_text()
        if not self._script_doc_is_aether_supported(doc):
            return
        self._run_aether_selection(doc, seleccion)

    def _script_doc_is_aether_supported(self, doc: dict) -> bool:
        location = doc.get("path") or doc.get("name")
        if location:
            suffix = Path(str(location)).suffix.lower()
            if suffix in LEGACY_SUFFIXES:
                self._show_legacy_file_message(Path(str(location)))
                self._set_runtime_status("Error", tone="error", message="Legacy file format is not supported.")
                return False
            if suffix and suffix != ".ae":
                QtWidgets.QMessageBox.information(
                    self,
                    "Aether Studio",
                    "Aether Studio runs .ae scripts only.",
                )
                self._set_runtime_status("Error", tone="error", message="Unsupported script format.")
                return False
        return True

    def _run_aether_selection(self, doc: dict, source: str) -> None:
        if not source.strip():
            self.append_output("The selection is empty.")
            return
        script_name = self._script_banner_name(doc)
        self._set_runtime_status("Running", tone="info", message=f"Running Aether selection from {script_name}...")
        self.append_output("[Running selection]")
        self.append_output(f">> {script_name}")
        result = run_source_for_file(doc.get("path") or doc.get("name"), source)
        if result.output:
            self.append_output(result.output, ensure_newline=False)
        if result.success:
            if not result.output:
                self.append_output("Aether program executed successfully.")
            self.append_output("[Selection finished]\n")
            self._set_runtime_status("Done", tone="success", message=f"Selection from {script_name} finished.")
            return
        self.append_output(result.error or "Aether execution failed.")
        self._set_runtime_status("Error", tone="error", message=f"Selection from {script_name} stopped due to an error.")

    # ----- Plot listener --------------------------------------------------
    def _register_plot_listener(self) -> None:
        if self._plot_listener_registered:
            return
        try:
            register_plot_listener(self._handle_plot_generated)
            self._plot_listener_registered = True
        except Exception:
            self._plot_listener_registered = False

    def _unregister_plot_listener(self) -> None:
        if not self._plot_listener_registered:
            return
        try:
            unregister_plot_listener(self._handle_plot_generated)
        except Exception:
            pass
        finally:
            self._plot_listener_registered = False

    def _handle_plot_generated(self, filepath: str, plot_name: str | None) -> None:
        path = Path(filepath)
        if not path.exists():
            return
        pixmap = QtGui.QPixmap(str(path))
        caption = plot_name or path.stem
        if pixmap.isNull():
            self.append_output(f"[Grafico: {caption}] {filepath}")
            return
        window = QtWidgets.QMainWindow(self)
        window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.setWindowTitle(f"Figura - {caption}")
        window.resize(960, 700)

        scroll = QtWidgets.QScrollArea(window)
        scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        label = QtWidgets.QLabel()
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(pixmap)
        layout.addWidget(label)

        scroll.setWidget(container)
        plot_root = QtWidgets.QWidget()
        plot_root.setObjectName("aetherPlotRoot")
        plot_layout = QtWidgets.QVBoxLayout(plot_root)
        plot_layout.setContentsMargins(10, 10, 10, 10)
        plot_layout.setSpacing(0)
        plot_layout.addWidget(
            self._create_aether_panel(
                "Plots",
                "Generated figures from the current session",
                scroll,
            )
        )
        window.setCentralWidget(plot_root)
        window.show()
        window.raise_()
        window.activateWindow()

        self._plot_windows.append(window)
        window.destroyed.connect(lambda *_: self._plot_windows.remove(window) if window in self._plot_windows else None)

    # ----- Eventos --------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        self._unregister_plot_listener()
        for win in list(self._plot_windows):
            try:
                win.close()
            except Exception:
                pass
        self._plot_windows = []
        super().closeEvent(event)


def launch_qt_gui() -> bool:
    """Try to open the Qt interface. Return False if it is not possible."""
    if not QT_AVAILABLE:
        return False
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    apply_dark_qt_theme(app)
    window = AetherStudioWindow()
    window.show()
    try:
        app.exec()
    except KeyboardInterrupt:
        return False
    except Exception:
        return False
    return True
