from __future__ import annotations

import pytest

from actions import ActionNotFoundError, ActionRegistry, AppAction


def test_action_registry_registers_and_runs_action() -> None:
    calls: list[str] = []
    registry = ActionRegistry()

    registry.register(AppAction(id="demo.run", label="Run", callback=lambda: calls.append("ran")))
    registry.run("demo.run")

    assert calls == ["ran"]
    assert registry.get("demo.run").label == "Run"


def test_action_registry_missing_action_has_clear_error() -> None:
    registry = ActionRegistry()

    with pytest.raises(ActionNotFoundError, match="Action not found: missing.action"):
        registry.get("missing.action")


def test_action_registry_enabled_predicate_reports_state() -> None:
    registry = ActionRegistry()
    enabled = False

    registry.register(
        AppAction(
            id="demo.guard",
            label="Guarded",
            callback=lambda: None,
            enabled=lambda: enabled,
        )
    )

    assert registry.is_enabled("demo.guard") is False

    enabled = True
    assert registry.is_enabled("demo.guard") is True
