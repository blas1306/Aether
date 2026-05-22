from __future__ import annotations

from actions import ActionRegistry
from actions.app_actions import register_main_window_actions


class FakeMainWindow:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.can_open = True
        self.can_save = False
        self.can_run = True
        self.can_build = False

    def _open_current_context_file(self) -> None:
        self.calls.append("file.open")

    def _save_current_context_file(self) -> None:
        self.calls.append("file.save")

    def run_script(self) -> None:
        self.calls.append("run.current")

    def _open_aether_repl(self) -> None:
        self.calls.append("repl.open_aether")

    def _can_open_current_context_file(self) -> bool:
        return self.can_open

    def _can_save_current_context_file(self) -> bool:
        return self.can_save

    def _can_run_current_action(self) -> bool:
        return self.can_run


def test_register_main_window_actions_registers_expected_action_contracts() -> None:
    window = FakeMainWindow()
    registry = ActionRegistry()

    register_main_window_actions(window, registry)

    expected = {
        "file.open": ("Open", None, True),
        "file.save": ("Save", "Ctrl+S", False),
        "run.current": ("Run Script", "Ctrl+Enter", True),
        "repl.open_aether": ("Open Aether REPL", None, True),
    }

    for action_id, (label, shortcut, enabled) in expected.items():
        action = registry.get(action_id)
        assert action.id == action_id
        assert action.label == label
        assert action.shortcut == shortcut
        assert registry.is_enabled(action_id) is enabled


def test_register_main_window_actions_uses_window_callbacks() -> None:
    window = FakeMainWindow()
    registry = ActionRegistry()

    register_main_window_actions(window, registry)
    for action_id in (
        "file.open",
        "file.save",
        "run.current",
        "repl.open_aether",
    ):
        registry.run(action_id)

    assert window.calls == [
        "file.open",
        "file.save",
        "run.current",
        "repl.open_aether",
    ]
