from __future__ import annotations

from typing import Protocol

from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

from repl.events import ConsoleEvent

CONSOLE_OUTPUT_BG = "#1e1e1e"
CONSOLE_PANEL_TEXT = "#d4d4d4"
CONSOLE_BORDER = "#3c3c3c"
CONSOLE_ERROR = "#ff8f8f"
CONSOLE_WARNING = "#ffd27a"
CONSOLE_PROMPT = "#9cdcfe"
CONSOLE_STATUS = "#a9b3bd"
CONSOLE_INPUT_BG = "#181b1f"
CONSOLE_BUTTON_BG = "#262b31"
CONSOLE_BUTTON_BORDER = "#3a424c"
CONSOLE_BUTTON_HOVER = "#2d333a"


class ConsoleEngine(Protocol):
    prompt: str

    def execute_line(self, line: str) -> list[ConsoleEvent]:
        ...

    def clear_console(self) -> list[ConsoleEvent]:
        ...

    def reset_environment(self) -> list[ConsoleEvent]:
        ...

    def history_prev(self, current_buffer: str) -> str:
        ...

    def history_next(self) -> str:
        ...


class ConsoleInput(QtWidgets.QLineEdit):  # type: ignore[misc]
    def __init__(self, engine: ConsoleEngine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setClearButtonEnabled(False)
        self.setPlaceholderText("")
        self.setFrame(False)
        self.setToolTip("Press Enter to run the current command. Use Up/Down for history.")
        self.setStyleSheet(
            f"""
            QLineEdit {{
                background: transparent;
                color: {CONSOLE_PANEL_TEXT};
                font-family: Consolas;
                font-size: 11pt;
                border: none;
                padding: 6px 0;
                selection-background-color: #264f78;
            }}
        """
        )

    def keyPressEvent(self, event):  # noqa: N802 - Qt API
        if event.key() == QtCore.Qt.Key.Key_Up:
            self.setText(self.engine.history_prev(self.text()))
            self.setCursorPosition(len(self.text()))
            event.accept()
            return
        if event.key() == QtCore.Qt.Key.Key_Down:
            self.setText(self.engine.history_next())
            self.setCursorPosition(len(self.text()))
            event.accept()
            return
        super().keyPressEvent(event)


class ConsoleWidget(QtWidgets.QWidget):  # type: ignore[misc]
    executed = QtCore.Signal()
    restarted = QtCore.Signal()
    command_started = QtCore.Signal(str)
    command_finished = QtCore.Signal(bool)

    def __init__(
        self,
        engine: ConsoleEngine,
        parent=None,
        *,
        welcome_text: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self._welcome_text = welcome_text or (
            "Welcome to Aether Studio\n"
            "Aether interactive REPL session ready.\n"
            "Use print(...) or println(...) for output. Ctrl+L clears the transcript."
        )

        self.terminal_frame = QtWidgets.QFrame(self)
        self.terminal_frame.setObjectName("aetherConsoleRoot")
        self.terminal_frame.setStyleSheet(
            f"""
            QFrame#aetherConsoleRoot {{
                background: {CONSOLE_OUTPUT_BG};
                border: 1px solid {CONSOLE_BORDER};
                border-radius: 8px;
            }}
            QFrame#aetherConsoleInputRow {{
                background: {CONSOLE_INPUT_BG};
                border-top: 1px solid {CONSOLE_BORDER};
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
            }}
            QLabel#aetherConsolePromptLabel {{
                color: {CONSOLE_PROMPT};
                font-family: Consolas;
                font-size: 11pt;
                font-weight: 600;
                background: transparent;
            }}
            QToolButton#aetherConsoleUtilityButton {{
                background: {CONSOLE_BUTTON_BG};
                border: 1px solid {CONSOLE_BUTTON_BORDER};
                border-radius: 6px;
                color: {CONSOLE_PANEL_TEXT};
                padding: 4px 10px;
            }}
            QToolButton#aetherConsoleUtilityButton:hover {{
                background: {CONSOLE_BUTTON_HOVER};
                border-color: #4b5561;
            }}
        """
        )

        self.output = QtWidgets.QPlainTextEdit(self.terminal_frame)
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(160)
        self.output.setFrameStyle(QtWidgets.QFrame.Shape.NoFrame)
        self.output.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background: transparent;
                color: {CONSOLE_PANEL_TEXT};
                font-family: Consolas;
                font-size: 11pt;
                border: none;
                padding: 8px 10px 6px 10px;
            }}
        """
        )

        self.input_row = QtWidgets.QFrame(self.terminal_frame)
        self.input_row.setObjectName("aetherConsoleInputRow")
        self.prompt_label = QtWidgets.QLabel(self.engine.prompt.rstrip(), self.input_row)
        self.prompt_label.setObjectName("aetherConsolePromptLabel")
        self.input = ConsoleInput(engine, self.input_row)
        self.clear_btn = QtWidgets.QToolButton(self.input_row)
        self.clear_btn.setObjectName("aetherConsoleUtilityButton")
        self.clear_btn.setText("Clear")
        self.clear_btn.setToolTip("Clear the REPL transcript (Ctrl+L).")
        self.restart_btn = QtWidgets.QToolButton(self.input_row)
        self.restart_btn.setObjectName("aetherConsoleUtilityButton")
        self.restart_btn.setText("Restart REPL")
        self.restart_btn.setToolTip("Restart the current REPL session.")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        terminal_layout = QtWidgets.QVBoxLayout(self.terminal_frame)
        terminal_layout.setContentsMargins(0, 0, 0, 0)
        terminal_layout.setSpacing(0)
        terminal_layout.addWidget(self.output, 1)

        input_layout = QtWidgets.QHBoxLayout(self.input_row)
        input_layout.setContentsMargins(10, 6, 10, 6)
        input_layout.setSpacing(8)
        input_layout.addWidget(self.prompt_label)
        input_layout.addWidget(self.input, 1)
        input_layout.addWidget(self.clear_btn)
        input_layout.addWidget(self.restart_btn)
        terminal_layout.addWidget(self.input_row)
        layout.addWidget(self.terminal_frame, 1)

        self.input.returnPressed.connect(self._submit)
        self.clear_btn.clicked.connect(self.clear)
        self.restart_btn.clicked.connect(self.restart_session)
        self.clear_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+L"), self)
        self.clear_shortcut.activated.connect(self.clear)
        self.setFocusProxy(self.input)

        self.clear()

    def set_engine(self, engine: ConsoleEngine, *, welcome_text: str | None = None, clear: bool = True) -> None:
        self.engine = engine
        self.input.engine = engine
        self.prompt_label.setText(self.engine.prompt.rstrip())
        profile = getattr(engine, "profile", None)
        if welcome_text is not None:
            self._welcome_text = welcome_text
        elif profile is not None:
            self._welcome_text = profile.welcome_text
        restart_label = getattr(profile, "restart_label", "Restart REPL") if profile is not None else "Restart"
        self.restart_btn.setText(restart_label)
        self.restart_btn.setToolTip(f"{restart_label} for the current session.")
        if clear:
            self.clear()

    def clear(self) -> None:
        self.output.setPlainText("")
        self.input.clear()
        if self._welcome_text:
            self._append_raw(self._welcome_text, ensure_newline=True, kind="status")
        self.input.setFocus()

    def restart_session(self) -> None:
        events = self.engine.reset_environment()
        self.clear()
        self.render_events(events)
        self.restarted.emit()
        self.input.setFocus()

    def append_output(self, text: str, ensure_newline: bool = True, *, kind: str = "stdout") -> None:
        if not text:
            return
        self._append_raw(text, ensure_newline=ensure_newline, kind=kind)

    def render_events(self, events: list[ConsoleEvent]) -> None:
        for event in events:
            if event.kind == "clear":
                self.clear()
                continue
            if event.kind == "error":
                self.append_output(f"[Error] {event.text}", kind="error")
                continue
            if event.kind == "warning":
                self.append_output(f"[Warning] {event.text}", kind="warning")
                continue
            self.append_output(event.text, kind=event.kind)

    def submit_current_input(self) -> None:
        self._submit()

    def _submit(self) -> None:
        line = self.input.text()
        if not line.strip():
            self.input.clear()
            self.input.setFocus()
            return
        self.command_started.emit(line)
        self._append_prompt_line(line)
        self.input.clear()
        events = self.engine.execute_line(line)
        self.render_events(events)
        self.command_finished.emit(not any(event.kind == "error" for event in events))
        self.executed.emit()
        self.input.setFocus()

    def _append_prompt_line(self, line: str) -> None:
        self._append_raw(f"{self.engine.prompt}{line}", ensure_newline=True, kind="prompt")

    def _append_raw(self, text: str, *, ensure_newline: bool, kind: str) -> None:
        cursor = self.output.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        existing = self.output.toPlainText()
        if existing and not existing.endswith("\n"):
            cursor.insertText("\n", self._format_for_kind("stdout"))
        cursor.insertText(text, self._format_for_kind(kind))
        if ensure_newline and not text.endswith("\n"):
            cursor.insertText("\n", self._format_for_kind(kind))
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def _format_for_kind(self, kind: str) -> QtGui.QTextCharFormat:
        color = {
            "error": CONSOLE_ERROR,
            "warning": CONSOLE_WARNING,
            "prompt": CONSOLE_PROMPT,
            "status": CONSOLE_STATUS,
        }.get(kind, CONSOLE_PANEL_TEXT)
        fmt = QtGui.QTextCharFormat()
        fmt.setForeground(QtGui.QColor(color))
        return fmt
