from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path


_WORKING_DIR = Path.cwd().resolve()
_PLOT_MODE = "interactive"
_PLOT_LISTENERS: list[Callable[[str, str | None], None]] = []


def change_working_dir(path: str | Path) -> bool:
    global _WORKING_DIR
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError as exc:
        print(f"Error resolving path: {exc}")
        return False
    if not resolved.exists() or not resolved.is_dir():
        print(f"Directory does not exist: {resolved}")
        return False
    try:
        os.chdir(resolved)
    except OSError as exc:
        print(f"Could not change to directory {resolved}: {exc}")
        return False
    _WORKING_DIR = resolved
    return True


def get_working_dir() -> Path:
    return _WORKING_DIR


def set_plot_mode(mode: str) -> None:
    global _PLOT_MODE
    _PLOT_MODE = "document" if str(mode).strip().lower() == "document" else "interactive"


def get_plot_mode() -> str:
    return _PLOT_MODE


def register_plot_listener(callback: Callable[[str, str | None], None]) -> None:
    if callback and callback not in _PLOT_LISTENERS:
        _PLOT_LISTENERS.append(callback)


def unregister_plot_listener(callback: Callable[[str, str | None], None]) -> None:
    if callback in _PLOT_LISTENERS:
        _PLOT_LISTENERS.remove(callback)


def notify_plot_generated(filepath: str, plot_name: str | None = None) -> None:
    for callback in list(_PLOT_LISTENERS):
        try:
            callback(filepath, plot_name)
        except Exception:
            continue
