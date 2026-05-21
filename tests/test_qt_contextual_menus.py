from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

from qt_app import MathTeXQtWindow
from project_system import ProjectManager


class EditorApiWidgetWithoutTextCursor(QtWidgets.QWidget):  # type: ignore[misc]
    text_changed = QtCore.Signal()
    cursor_changed = QtCore.Signal()
    request_completion = QtCore.Signal()
    run_requested = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        self._text = ""
        self._modified = False
        self._selection = False

    def native_widget(self):
        return self

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text

    def get_cursor_position(self) -> int:
        return 0

    def set_cursor_position(self, pos: int) -> None:
        del pos

    def get_cursor_line_column(self) -> tuple[int, int]:
        return (1, 0)

    def go_to_line(self, line: int, column: int = 0) -> bool:
        del line, column
        return True

    def has_selection(self) -> bool:
        return self._selection

    def get_selected_text(self) -> str:
        return "selected" if self._selection else ""

    def get_selection_start_line(self) -> int | None:
        return 1 if self._selection else None

    def insert_text_at_cursor(self, text: str, cursor_offset: int = 0) -> None:
        del cursor_offset
        self._text += text

    def is_modified(self) -> bool:
        return self._modified

    def set_modified(self, value: bool) -> None:
        self._modified = value

    def connect_modification_changed(self, callback) -> None:
        del callback

    def set_diagnostics(self, diagnostics) -> None:
        del diagnostics

    def clear_diagnostics(self) -> None:
        pass

    def set_completions(self, completions) -> None:
        del completions

    def set_autocomplete_document_kind(self, document_kind: str) -> None:
        del document_kind

    def set_autocomplete_workspace_provider(self, provider) -> None:
        del provider

    def set_surface_theme(
        self,
        *,
        background: str,
        line_number_color: str = "#b0b0b0",
        current_line_color: str = "#404040",
    ) -> None:
        del background, line_number_color, current_line_color

    def focus_editor(self) -> None:
        self.setFocus()


def _menu_titles(window: MathTeXQtWindow) -> list[str]:
    return [action.text().replace("&", "") for action in window.menuBar().actions()]


def _menu_actions(window: MathTeXQtWindow, menu_title: str) -> list[str]:
    for action in window.menuBar().actions():
        if action.text().replace("&", "") != menu_title:
            continue
        menu = action.menu()
        if menu is None:
            return []
        return [entry.text() for entry in menu.actions() if not entry.isSeparator()]
    return []


def _assert_in_order(entries: list[str], expected: list[str]) -> None:
    positions = [entries.index(item) for item in expected]
    assert positions == sorted(positions)


def test_menu_bar_switches_between_interactive_and_studio(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()

    try:
        qapp.processEvents()

        assert _menu_titles(window) == ["File", "Edit", "View", "Run", "Tools", "Help"]
        _assert_in_order(
            _menu_actions(window, "File"),
            ["New Script", "Open Script...", "Save"],
        )

        assert _menu_actions(window, "Run") == [
            "Run Script",
            "Run Selection",
            "Clear Console",
        ]

        assert window.central_tabs is not None
        window.central_tabs.setCurrentIndex(1)
        qapp.processEvents()

        assert _menu_titles(window) == ["File", "Edit", "Insert", "View", "Build", "Help"]
        _assert_in_order(
            _menu_actions(window, "File"),
            ["New Project", "Open Project...", "Open .mtex File..."],
        )
        assert _menu_actions(window, "Build") == [
            "Compile",
            "Toggle Auto Compile",
            "Show Logs & Output Files",
        ]
    finally:
        window.close()
        qapp.processEvents()


def test_aether_ui_object_names_replace_mathlab_visual_names(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()

    try:
        qapp.processEvents()
        object_names = {widget.objectName() for widget in window.findChildren(QtWidgets.QWidget)}

        renamed_object_names = [
            "aetherStatusButton",
            "aetherToolbarCard",
            "aetherPanel",
            "aetherPanelMuted",
            "aetherPanelPrimary",
            "aetherPanelTitle",
            "aetherPanelSubtitle",
            "aetherToolbarTitle",
            "aetherToolbarSubtitle",
            "aetherToolbarIconButton",
            "aetherToolbarUtilityButton",
            "aetherScriptTabs",
            "aetherWorkspaceTable",
        ]
        for object_name in renamed_object_names:
            assert object_name in object_names
            assert object_name.replace("aether", "mathLab", 1) not in object_names

        plot_path = tmp_path / "plot.png"
        pixmap = QtGui.QPixmap(2, 2)
        pixmap.fill(QtGui.QColor("#ffffff"))
        assert pixmap.save(str(plot_path))
        window._handle_plot_generated(str(plot_path), "demo")
        qapp.processEvents()

        plot_root_names = {
            plot_window.centralWidget().objectName()
            for plot_window in window._plot_windows
            if plot_window.centralWidget() is not None
        }
        assert "aetherPlotRoot" in plot_root_names
        assert "aetherPlotRoot".replace("aether", "mathLab", 1) not in plot_root_names
    finally:
        for plot_window in list(window._plot_windows):
            plot_window.close()
        window.close()
        qapp.processEvents()


def test_codemirror_script_tabs_update_menu_without_qplaintextedit_api(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    created_kinds: list[str] = []

    def fake_create_editor(kind: str, parent=None, *, enable_autocomplete: bool = False):
        del parent, enable_autocomplete
        created_kinds.append(kind)
        return EditorApiWidgetWithoutTextCursor()

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("AETHER_EDITOR_KIND", "codemirror")
    monkeypatch.setattr("qt_app.create_editor", fake_create_editor)

    window = MathTeXQtWindow()

    try:
        assert window.editor_kind == "codemirror"
        window._new_script_file()
        window._new_script_file()
        qapp.processEvents()

        assert window.script_tab_widget.count() == 2
        assert created_kinds[-2:] == ["codemirror", "codemirror"]

        window.script_tab_widget.setCurrentIndex(0)
        window._update_menu_action_states()
        window.script_tab_widget.setCurrentIndex(1)
        window._update_menu_action_states()

        run_selection = window._menu_actions["interactive_run_selection"]
        assert not run_selection.isEnabled()
    finally:
        window.close()
        qapp.processEvents()


def test_main_tab_uses_aether_name_and_editor_runs_show_script_banner(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()
    script_path = tmp_path / "demo_script.mtx"
    script_path.write_text("x = 1;\ny = 2;\n", encoding="utf-8")

    try:
        assert window.central_tabs is not None
        assert window.central_tabs.tabText(0) == "Aether"

        window._open_mtex_in_script(script_path)
        qapp.processEvents()
        assert window.console_widget is not None
        window.console_widget.clear()

        window.run_script()
        qapp.processEvents()
        run_all_output = window.console_widget.output.toPlainText()
        assert ">> demo_script.mtx" in run_all_output
        assert "[Running script]" not in run_all_output
        assert "[Script finished]" not in run_all_output

        window.console_widget.clear()
        assert window.script_docs
        editor = window.script_docs[0]["widget"]
        editor.setFocus()
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(len("x = 1;"), QtGui.QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)

        window.run_selection()
        qapp.processEvents()
        run_selection_output = window.console_widget.output.toPlainText()
        assert ">> demo_script.mtx" in run_selection_output
    finally:
        window.close()
        qapp.processEvents()


def test_console_defaults_to_aether_repl_when_no_file_is_open(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()

    try:
        assert window.windowTitle() == "Aether Studio"
        assert window.console_widget is not None
        console_text = window.console_widget.output.toPlainText()
        assert "Welcome to Aether Studio" in console_text
        assert "Aether interactive REPL session ready." in console_text
        assert "Use print(...) or println(...) for output." in console_text
        assert window.console_widget.prompt_label.text() == "aether>"
        assert window.console_widget.input.placeholderText() == ""
    finally:
        window.close()
        qapp.processEvents()


def test_active_script_extension_selects_repl_panel(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()
    ae_path = tmp_path / "scratch.ae"
    mtx_path = tmp_path / "legacy.mtx"
    ae_path.write_text("x = 5;\n", encoding="utf-8")
    mtx_path.write_text("x = 5;\n", encoding="utf-8")

    try:
        window._open_mtex_in_script(ae_path)
        qapp.processEvents()
        assert window.console_dock is not None
        assert window.console_dock.windowTitle() == "Aether REPL"
        assert window.console_widget.prompt_label.text() == "aether>"

        window._open_mtex_in_script(mtx_path)
        qapp.processEvents()
        assert window.console_dock.windowTitle() == "MathLab Legacy Console"
        assert window.console_widget.prompt_label.text() == "mathlab>"
        assert "MathLab Legacy console ready for .mtx files." in window.console_widget.output.toPlainText()
    finally:
        window.close()
        qapp.processEvents()


def test_studio_insert_menu_inserts_mathtex_block(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()
    manager = ProjectManager()
    project = manager.create_project("MenuProject", tmp_path)

    try:
        window._open_project(project)
        assert window.central_tabs is not None
        window.central_tabs.setCurrentIndex(1)
        qapp.processEvents()

        assert window.mtex_editor is not None
        window.mtex_editor.setPlainText("")
        window.mtex_editor.moveCursor(QtGui.QTextCursor.MoveOperation.End)

        insert_entries = _menu_actions(window, "Insert")
        assert "MathTeX Block" in insert_entries

        action = window._menu_actions["studio_insert_mathtex"]
        action.trigger()
        qapp.processEvents()

        text = window.mtex_editor.toPlainText()
        assert "\\begin{code}" in text
        assert "\\end{code}" in text
    finally:
        if window.mtex_editor is not None:
            window.mtex_editor.document().setModified(False)
        window._reset_auto_compile_runtime()
        window.current_project = None
        window.current_mtex_path = None
        window.close()
        qapp.processEvents()
