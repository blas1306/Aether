from __future__ import annotations


class AetherError(Exception):
    """Base class for Aether language errors."""

    def __init__(
        self,
        message: str,
        *,
        line: int | None = None,
        column: int | None = None,
        hint: str | None = None,
        kind: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column
        self.hint = hint
        self.kind = kind

    @property
    def has_location(self) -> bool:
        return isinstance(self.line, int) or isinstance(self.column, int)

    @property
    def has_details(self) -> bool:
        return self.has_location or self.hint is not None or self.kind is not None

    def with_location(self, line: int | None, column: int | None) -> "AetherError":
        if self.has_location:
            return self
        return type(self)(self.message, line=line, column=column, hint=self.hint, kind=self.kind)

    def format(self) -> str:
        header = type(self).__name__
        if isinstance(self.line, int) and isinstance(self.column, int):
            header += f" at line {self.line}, column {self.column}"
        elif isinstance(self.line, int):
            header += f" at line {self.line}"
        elif isinstance(self.column, int):
            header += f" at column {self.column}"
        if self.kind:
            header += f" [{self.kind}]"
        lines = [f"{header}:", f"  {self.message}"]
        if self.hint:
            lines.append(f"  Hint: {self.hint}")
        return "\n".join(lines)

    def __str__(self) -> str:
        if self.has_details:
            return self.format()
        return self.message


class AetherSyntaxError(AetherError):
    """Raised when Aether source cannot be parsed."""


class AetherTypeError(AetherError):
    """Raised when Aether type rules are violated."""


class AetherRuntimeError(AetherError):
    """Raised when Aether execution fails at runtime."""


class AetherInputError(AetherRuntimeError):
    """Raised when user input cannot be read or converted."""


IR_BACKEND_SUPPORTED_SUBSET = (
    "Supported IR backend subset:\n"
    "- functions\n"
    "- local variables\n"
    "- int/bool/string literals\n"
    "- arithmetic\n"
    "- comparisons\n"
    "- if/else\n"
    "- while\n"
    "- simple user-defined function calls"
)


class IRBackendUnsupportedFeatureError(AetherError):
    """Raised when the experimental IR backend cannot lower a language feature."""

    def __init__(
        self,
        message: str,
        *,
        line: int | None = None,
        column: int | None = None,
        hint: str | None = None,
        kind: str | None = None,
    ) -> None:
        super().__init__(
            message,
            line=line,
            column=column,
            hint=hint or IR_BACKEND_SUPPORTED_SUBSET,
            kind=kind,
        )
