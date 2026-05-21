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


STUDIO_MENU_SPEC: MenuSpec = {
    "File": [
        "studio_new_project",
        "studio_open_project",
        "studio_project_home",
        None,
        "studio_open_mtex",
        None,
        "studio_save_mtex",
        "studio_save_mtex_as",
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
    "Insert": [
        "studio_insert_section",
        "studio_insert_subsection",
        None,
        "studio_insert_equation",
        "studio_insert_code",
        "studio_insert_table",
        "studio_insert_figure",
        "studio_insert_mathtex",
    ],
    "View": [
        "studio_show_project_files",
        "studio_show_preview",
        None,
        "studio_go_to_code_location_in_pdf",
        "studio_go_to_pdf_location_in_code",
        None,
        "studio_show_logs",
        "studio_refresh_tree",
    ],
    "Build": [
        "studio_compile",
        "studio_toggle_auto_compile",
        None,
        "studio_show_logs",
    ],
    "Help": [
        "help_about",
        "help_studio",
    ],
}
