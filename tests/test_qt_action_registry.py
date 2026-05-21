from __future__ import annotations

from PySide6 import QtGui  # type: ignore

from qt_app import MathTeXQtWindow


def test_qt_app_creates_minimal_action_registry(tmp_path, monkeypatch, qapp) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()

    try:
        action_ids = [
            "file.save",
            "file.open",
            "run.current",
            "build.current",
            "repl.open_aether",
        ]

        for action_id in action_ids:
            assert window.action_registry.get(action_id).id == action_id

        assert window.action_registry.is_enabled("file.open") is True
        assert window.action_registry.is_enabled("run.current") is False
    finally:
        window.close()
        qapp.processEvents()


def _shortcut_texts(action: QtGui.QAction) -> set[str]:
    return {
        shortcut.toString(QtGui.QKeySequence.SequenceFormat.PortableText)
        for shortcut in action.shortcuts()
    }


def test_registered_menu_qactions_use_action_registry(tmp_path, monkeypatch, qapp) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()

    try:
        calls: list[str] = []
        for action_id in ("file.open", "file.save", "run.current", "build.current"):
            window.action_registry.get(action_id).callback = lambda action_id=action_id: calls.append(action_id)

        migrated_actions = {
            "interactive_open_script": ("file.open", "Open Script...", set()),
            "interactive_save_script": ("file.save", "Save", {"Ctrl+S"}),
            "interactive_run_script": ("run.current", "Run Script", {"Ctrl+Enter", "Ctrl+Return"}),
            "studio_open_mtex": ("file.open", "Open .mtex File...", set()),
            "studio_save_mtex": ("file.save", "Save", {"Ctrl+S"}),
            "studio_compile": ("build.current", "Compile", {"Ctrl+Enter", "Ctrl+Return"}),
        }

        for menu_action_id, (_action_id, label, shortcuts) in migrated_actions.items():
            action = window._menu_actions[menu_action_id]
            assert action.text() == label
            assert _shortcut_texts(action) == shortcuts

        file_open = window.action_registry.get("file.open")
        file_open.enabled = lambda: False
        window._update_menu_action_states()
        assert window._menu_actions["interactive_open_script"].isEnabled() is False

        file_open.enabled = lambda: True
        window._update_menu_action_states()
        assert window._menu_actions["interactive_open_script"].isEnabled() is True

        for menu_action_id in migrated_actions:
            window._menu_actions[menu_action_id].setEnabled(True)
            window._menu_actions[menu_action_id].trigger()

        assert calls == [
            "file.open",
            "file.save",
            "run.current",
            "file.open",
            "file.save",
            "build.current",
        ]
    finally:
        window.close()
        qapp.processEvents()
