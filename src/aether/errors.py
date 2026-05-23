from __future__ import annotations


class AetherError(Exception):
    """Base class for Aether language errors."""


class AetherSyntaxError(AetherError):
    """Raised when Aether source cannot be parsed."""


class AetherTypeError(AetherError):
    """Raised when Aether type rules are violated."""

    def __init__(self, message: str, *, line: int | None = None, column: int | None = None) -> None:
        super().__init__(message)
        self.line = line
        self.column = column


class AetherRuntimeError(AetherError):
    """Raised when Aether execution fails at runtime."""
