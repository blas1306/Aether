from __future__ import annotations

from pathlib import Path

import app_preferences
from app_preferences import AppPreferences, AppPreferencesStore


def test_app_preferences_default_to_auto_compile_off(tmp_path) -> None:
    store = AppPreferencesStore(tmp_path / "ui_preferences.json")

    preferences = store.load()

    assert preferences.auto_compile_enabled is False


def test_app_preferences_store_persists_auto_compile_state(tmp_path) -> None:
    storage_path = tmp_path / "ui_preferences.json"
    store = AppPreferencesStore(storage_path)

    store.save(AppPreferences(auto_compile_enabled=True))
    reloaded = AppPreferencesStore(storage_path).load()

    assert storage_path.exists()
    assert reloaded.auto_compile_enabled is True


def test_default_preferences_path_uses_platformdirs(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_user_config_dir(*args, **kwargs) -> str:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return str(tmp_path / "config-home")

    monkeypatch.setattr(app_preferences, "user_config_dir", fake_user_config_dir)

    path = app_preferences.default_preferences_path()

    assert path == tmp_path / "config-home" / "ui_preferences.json"
    assert captured["args"] == ()
    assert captured["kwargs"] == {"appname": "Aether Studio", "appauthor": False}
