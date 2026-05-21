from __future__ import annotations

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
