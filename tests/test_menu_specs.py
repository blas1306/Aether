from __future__ import annotations

from actions.menu_specs import INTERACTIVE_MENU_SPEC


def test_interactive_menu_spec_contains_expected_menus_and_entries() -> None:
    assert list(INTERACTIVE_MENU_SPEC) == ["File", "Edit", "View", "Run", "Tools", "Help"]
    assert INTERACTIVE_MENU_SPEC["File"] == [
        "interactive_new_script",
        "interactive_open_script",
        None,
        "interactive_save_script",
        "interactive_save_script_as",
        None,
        "interactive_close_script",
        None,
        "interactive_exit",
    ]
    assert INTERACTIVE_MENU_SPEC["Run"] == [
        "interactive_run_script",
        "interactive_run_selection",
        None,
        "interactive_clear_console",
    ]
