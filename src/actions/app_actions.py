from __future__ import annotations

from typing import Any

from .action import AppAction
from .registry import ActionRegistry


def register_main_window_actions(window: Any, registry: ActionRegistry) -> None:
    registry.register(
        AppAction(
            id="file.open",
            label="Open",
            callback=window._open_current_context_file,
            enabled=window._can_open_current_context_file,
        )
    )
    registry.register(
        AppAction(
            id="file.save",
            label="Save",
            callback=window._save_current_context_file,
            shortcut="Ctrl+S",
            enabled=window._can_save_current_context_file,
        )
    )
    registry.register(
        AppAction(
            id="run.current",
            label="Run Script",
            callback=window.run_script,
            shortcut="Ctrl+Enter",
            enabled=window._can_run_current_action,
        )
    )
    registry.register(
        AppAction(
            id="build.current",
            label="Compile",
            callback=window._compile_current_mtex,
            shortcut="Ctrl+Enter",
            enabled=window._can_build_current_action,
        )
    )
    registry.register(
        AppAction(
            id="repl.open_aether",
            label="Open Aether REPL",
            callback=window._open_aether_repl,
            enabled=lambda: True,
        )
    )
