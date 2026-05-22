from __future__ import annotations

import sys

STARTUP_IMPORT_ERROR: ModuleNotFoundError | None = None
AetherSession = None
AETHER_ERRORS: tuple[type[Exception], ...] = ()
format_aether_error = None

try:
    from aether import AetherRuntimeError, AetherSession, AetherSyntaxError, AetherTypeError
    from language_runtime import format_aether_error

    AETHER_ERRORS = (AetherSyntaxError, AetherTypeError, AetherRuntimeError)
except ModuleNotFoundError as exc:
    STARTUP_IMPORT_ERROR = exc

QT_IMPORT_ERROR: Exception | None = None

try:  # pragma: no cover - depende de la instalacion del usuario
    from qt_app import QT_AVAILABLE, launch_qt_gui
except Exception as exc:  # pragma: no cover - fallback CLI
    QT_AVAILABLE = False
    launch_qt_gui = None
    QT_IMPORT_ERROR = exc


def run_cli() -> None:
    """Run the Aether text-mode REPL."""
    if STARTUP_IMPORT_ERROR is not None or AetherSession is None or format_aether_error is None:
        _print_missing_dependency_help()
        return

    session = AetherSession()

    print("Welcome to Aether Studio CLI")
    print("Type '\\exit', or '\\quit' to leave.\n")

    while True:
        try:
            raw_input = input("aether> ")
        except EOFError:
            print("Goodbye!")
            break
        except KeyboardInterrupt:
            print()
            continue

        if raw_input.strip().lower() in {"\\exit", "\\quit"}:
            print("Goodbye!")
            break

        if not raw_input.strip():
            continue

        try:
            result = session.run(raw_input)
        except AETHER_ERRORS as exc:
            print(format_aether_error(exc))
            continue

        if result.output:
            print(result.output, end="" if result.output.endswith("\n") else "\n")


def repl() -> None:
    run_cli()


def launch_gui() -> bool:
    """Launch the PySide6 GUI when it is available."""
    if not QT_AVAILABLE or launch_qt_gui is None:
        return False
    return bool(launch_qt_gui())


def _qt_error_message() -> str:
    if QT_IMPORT_ERROR is None:
        return ""
    name = QT_IMPORT_ERROR.__class__.__name__
    detail = str(QT_IMPORT_ERROR).strip()
    return f"{name}: {detail}" if detail else name


def _print_missing_dependency_help() -> None:
    print("Could not start Aether Studio because a required Python dependency is missing.")
    print(f"Python executable: {sys.executable}")
    if STARTUP_IMPORT_ERROR is not None:
        missing = getattr(STARTUP_IMPORT_ERROR, "name", None)
        if missing:
            print(f"Missing module: {missing}")
    print("Install the project dependencies with:")
    print(f"  \"{sys.executable}\" -m pip install -r requirements.txt")


def main() -> None:
    if STARTUP_IMPORT_ERROR is not None:
        _print_missing_dependency_help()
        return

    args = {arg.lower() for arg in sys.argv[1:]}

    if {"--cli", "--no-gui"} & args:
        run_cli()
        return

    if "--tk" in args:
        print("The Tkinter interface was removed. Starting the PySide6 interface instead.\n")

    if launch_gui():
        return

    print("Could not start the PySide6 interface.")
    qt_error = _qt_error_message()
    if qt_error:
        print(f"Qt import error: {qt_error}")
    print("Use '--cli' to force text mode.\n")
    run_cli()


if __name__ == "__main__":
    main()
