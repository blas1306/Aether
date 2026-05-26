from __future__ import annotations

from aether import AetherRuntimeError, AetherSession, AetherSyntaxError, AetherTypeError
from language_runtime import format_aether_error
from repl.events import ConsoleCapture

AETHER_REPL_ERRORS = (AetherSyntaxError, AetherTypeError, AetherRuntimeError)


class AetherReplBackend:
    def __init__(self) -> None:
        self.session = AetherSession()

    def execute_console_line(self, line: str) -> ConsoleCapture:
        stripped = line.strip()
        if not stripped:
            return ConsoleCapture()
        try:
            result = self.session.run(stripped)
        except AETHER_REPL_ERRORS as exc:
            return ConsoleCapture(stderr=format_aether_error(exc) + "\n")
        return ConsoleCapture(stdout=result.output)

    def reset_environment(self) -> None:
        self.session = AetherSession()

    def workspace_snapshot(self) -> list[dict[str, str]]:
        return self.session.workspace_snapshot()
