from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir


APP_PREFERENCES_FILENAME = "ui_preferences.json"
APP_PREFERENCES_VERSION = 1
APP_STORAGE_NAME = "Aether Studio"


def default_preferences_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_STORAGE_NAME / APP_PREFERENCES_FILENAME
    base_dir = Path(user_config_dir(appname=APP_STORAGE_NAME, appauthor=False))
    return base_dir / APP_PREFERENCES_FILENAME


@dataclass(frozen=True)
class AppPreferences:
    auto_compile_enabled: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "version": APP_PREFERENCES_VERSION,
            "auto_compile_enabled": self.auto_compile_enabled,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object] | None) -> "AppPreferences":
        if not isinstance(payload, dict):
            return cls()
        return cls(auto_compile_enabled=bool(payload.get("auto_compile_enabled", False)))


class AppPreferencesStore:
    def __init__(self, storage_path: Path | None = None) -> None:
        self.storage_path = storage_path or default_preferences_path()

    def load(self) -> AppPreferences:
        if not self.storage_path.exists():
            return AppPreferences()
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppPreferences()
        return AppPreferences.from_dict(payload)

    def save(self, preferences: AppPreferences) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(preferences.to_dict(), indent=2), encoding="utf-8")
