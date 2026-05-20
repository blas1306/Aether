from __future__ import annotations

import sys

STARTUP_IMPORT_ERROR: ModuleNotFoundError | None = None
ConsoleEngine = None
MathRuntime = None

try:
    from console_engine import ConsoleEngine, MathRuntime
except ModuleNotFoundError as exc:
    STARTUP_IMPORT_ERROR = exc

QT_IMPORT_ERROR: Exception | None = None

try:  # pragma: no cover - depende de la instalacion del usuario
    from qt_app import QT_AVAILABLE, launch_qt_gui
except Exception as exc:  # pragma: no cover - fallback CLI
    QT_AVAILABLE = False
    launch_qt_gui = None
    QT_IMPORT_ERROR = exc


def render_cli_event(event) -> None:
    if event.kind == "clear":
        return
    print(event.text)


def run_cli() -> None:
    """Traditional REPL kept for compatibility with the previous workflow."""
    if STARTUP_IMPORT_ERROR is not None or ConsoleEngine is None or MathRuntime is None:
        _print_missing_dependency_help()
        return

    runtime = MathRuntime()
    engine = ConsoleEngine(runtime)

    print("Welcome to MathTeX CLI")
    print("Type '\\exit', or '\\quit' to leave.\n")

    while True:
        try:
            raw_input = input(engine.prompt)
        except EOFError:
            print("Goodbye!")
            break
        except KeyboardInterrupt:
            print()
            continue

        if raw_input.strip().lower() in {"\\exit", "\\quit"}:
            print("Goodbye!")
            break

        events = engine.execute_line(raw_input)
        for event in events:
            render_cli_event(event)


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
