from __future__ import annotations

from typing import Any, Callable, Protocol


class EditorAPI(Protocol):
    text_changed: Any
    cursor_changed: Any
    request_completion: Any
    run_requested: Any

    def native_widget(self) -> Any:
        ...

    def get_text(self) -> str:
        ...

    def set_text(self, text: str) -> None:
        ...

    def get_cursor_position(self) -> int:
        ...

    def set_cursor_position(self, pos: int) -> None:
        ...

    def get_cursor_line_column(self) -> tuple[int, int]:
        ...

    def go_to_line(self, line: int, column: int = 0) -> bool:
        ...

    def has_selection(self) -> bool:
        ...

    def get_selected_text(self) -> str:
        ...

    def get_selection_start_line(self) -> int | None:
        ...

    def insert_text_at_cursor(self, text: str, cursor_offset: int = 0) -> None:
        ...

    def is_modified(self) -> bool:
        ...

    def set_modified(self, value: bool) -> None:
        ...

    def connect_modification_changed(self, callback: Callable[[bool], None]) -> None:
        ...

    def set_diagnostics(self, diagnostics) -> None:
        ...

    def clear_diagnostics(self) -> None:
        ...

    def set_completions(self, completions) -> None:
        ...

    def focus_editor(self) -> None:
        ...
