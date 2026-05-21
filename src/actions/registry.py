from __future__ import annotations

from .action import AppAction


class ActionNotFoundError(KeyError):
    """Raised when an action id is not registered."""


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, AppAction] = {}

    def register(self, action: AppAction) -> None:
        if action.id in self._actions:
            raise ValueError(f"Action already registered: {action.id}")
        self._actions[action.id] = action

    def get(self, action_id: str) -> AppAction:
        try:
            return self._actions[action_id]
        except KeyError as exc:
            raise ActionNotFoundError(f"Action not found: {action_id}") from exc

    def run(self, action_id: str) -> None:
        action = self.get(action_id)
        action.callback()

    def is_enabled(self, action_id: str) -> bool:
        action = self.get(action_id)
        if action.enabled is None:
            return True
        return bool(action.enabled())
