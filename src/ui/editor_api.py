from __future__ import annotations

from typing import Any, Callable, Protocol


class EditorAPI(Protocol):
    """Common editor contract used by the application shell.

    Implementations must provide the text, cursor, selection, modification,
    insertion, diagnostics, completions, focus, and signal behavior declared
    here. The application should prefer these methods over toolkit-specific
    APIs so future adapters can replace the current Qt text widget.

    `native_widget()` is the only escape hatch. It exists for integration
    points that genuinely require a toolkit object, such as adding an editor to
    a Qt layout. App orchestration code such as `qt_app.py` should not use it
    for normal editor operations.
    """

    # Required event channels. Concrete adapters may expose Qt signals,
    # callbacks, or signal-like objects with a compatible connect/emit surface.
    text_changed: Any
    cursor_changed: Any
    request_completion: Any
    run_requested: Any

    def native_widget(self) -> Any:
        """Return the concrete UI object for toolkit-only integration.

        This is an escape hatch, not part of normal editor orchestration.
        Prefer the typed methods on this protocol for all text, cursor,
        selection, modification, and completion behavior.
        """
        ...

    def get_text(self) -> str:
        """Return the complete document text."""
        ...

    def set_text(self, text: str) -> None:
        """Replace the complete document text with `text`."""
        ...

    def get_cursor_position(self) -> int:
        """Return the absolute zero-based cursor offset in the document."""
        ...

    def set_cursor_position(self, pos: int) -> None:
        """Move the cursor to absolute zero-based document offset `pos`."""
        ...

    def get_cursor_line_column(self) -> tuple[int, int]:
        """Return the cursor as `(line, column)`.

        Lines are one-based for user-facing editor and diagnostic workflows.
        Columns are zero-based to match string offsets within a line.
        """
        ...

    def go_to_line(self, line: int, column: int = 0) -> bool:
        """Move the cursor to `line` and `column`.

        `line` is one-based and `column` is zero-based. Return `False` when
        the target line cannot be resolved.
        """
        ...

    def has_selection(self) -> bool:
        """Return whether the editor currently has a non-empty selection."""
        ...

    def get_selected_text(self) -> str:
        """Return the selected text using `\n` for line breaks."""
        ...

    def get_selection_start_line(self) -> int | None:
        """Return the one-based line where the current selection starts.

        Return `None` when there is no active selection.
        """
        ...

    def insert_text_at_cursor(self, text: str, cursor_offset: int = 0) -> None:
        """Insert `text` at the cursor and optionally reposition the cursor.

        `cursor_offset` is relative to the cursor position immediately after
        insertion. For example, `cursor_offset=-1` leaves the cursor one
        character before the inserted text's end.
        """
        ...

    def is_modified(self) -> bool:
        """Return whether the document has unsaved modifications."""
        ...

    def set_modified(self, value: bool) -> None:
        """Set the document modification state."""
        ...

    def connect_modification_changed(self, callback: Callable[[bool], None]) -> None:
        """Call `callback(changed)` when the modification state changes."""
        ...

    def set_diagnostics(self, diagnostics) -> None:
        """Replace current diagnostics shown by the editor adapter."""
        ...

    def clear_diagnostics(self) -> None:
        """Clear diagnostics shown by the editor adapter."""
        ...

    def set_completions(self, completions) -> None:
        """Replace externally supplied completion candidates."""
        ...

    def focus_editor(self) -> None:
        """Move keyboard focus into the editor surface."""
        ...
