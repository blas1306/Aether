from __future__ import annotations

MenuEntry = str | None
MenuSpec = dict[str, list[MenuEntry]]


INTERACTIVE_MENU_SPEC: MenuSpec = {
    "File": [
        "interactive_new_script",
        "interactive_open_script",
        None,
        "interactive_save_script",
        "interactive_save_script_as",
        None,
        "interactive_close_script",
        None,
        "interactive_exit",
    ],
    "Edit": [
        "edit_undo",
        "edit_redo",
        None,
        "edit_cut",
        "edit_copy",
        "edit_paste",
        None,
        "edit_select_all",
    ],
    "View": [
        "interactive_show_console",
        "interactive_show_workspace",
        "interactive_restore_console",
        None,
        "interactive_reset_layout",
    ],
    "Run": [
        "interactive_run_script",
        "interactive_run_selection",
        None,
        "interactive_clear_console",
    ],
    "Tools": [
        "interactive_choose_directory",
        "interactive_parent_directory",
    ],
    "Help": [
        "help_about",
        "help_interactive",
    ],
}
