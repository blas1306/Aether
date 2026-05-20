from __future__ import annotations

from typing import Any, Protocol


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

    def go_to_line(self, line: int, column: int = 0) -> bool:
        ...

    def set_diagnostics(self, diagnostics) -> None:
        ...

    def clear_diagnostics(self) -> None:
        ...

    def set_completions(self, completions) -> None:
        ...

    def focus_editor(self) -> None:
        ...
