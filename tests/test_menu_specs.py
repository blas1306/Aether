from __future__ import annotations

from actions.menu_specs import INTERACTIVE_MENU_SPEC, STUDIO_MENU_SPEC


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


def test_studio_menu_spec_contains_expected_menus_and_entries() -> None:
    assert list(STUDIO_MENU_SPEC) == ["File", "Edit", "Insert", "View", "Build", "Help"]
    assert STUDIO_MENU_SPEC["File"] == [
        "studio_new_project",
        "studio_open_project",
        "studio_project_home",
        None,
        "studio_open_mtex",
        None,
        "studio_save_mtex",
        "studio_save_mtex_as",
    ]
    assert STUDIO_MENU_SPEC["Build"] == [
        "studio_compile",
        "studio_toggle_auto_compile",
        None,
        "studio_show_logs",
    ]
