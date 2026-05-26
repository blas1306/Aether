from __future__ import annotations

from console_engine import ConsoleEngine, ConsoleEvent, MathRuntime
from latex_lang import env_ast


def setup_function() -> None:
    MathRuntime().reset_environment()


def teardown_function() -> None:
    MathRuntime().reset_environment()


def test_execute_line_returns_stdout_event_for_simple_assignment() -> None:
    engine = ConsoleEngine(MathRuntime())

    events = engine.execute_line("x = 2")

    assert len(events) == 1
    assert events[0].kind == "stdout"
    assert "x = 2" in events[0].text


def test_execute_line_returns_error_event_on_runtime_failure() -> None:
    engine = ConsoleEngine(MathRuntime())

    events = engine.execute_line("x = y")

    assert any(event.kind == "error" for event in events)


def test_history_prev_and_next_round_trip() -> None:
    engine = ConsoleEngine(MathRuntime())
    engine.execute_line("x = 1")
    engine.execute_line("y = 2")

    assert engine.history_prev("draft") == "y = 2"
    assert engine.history_prev("ignored") == "x = 1"
    assert engine.history_next() == "y = 2"
    assert engine.history_next() == "draft"


def test_reset_environment_clears_shared_runtime_state() -> None:
    engine = ConsoleEngine(MathRuntime())
    engine.execute_line("x = 9")
    assert "x" in env_ast

    events = engine.reset_environment()

    assert events[0].kind == "status"
    assert "x" not in env_ast


def test_clear_console_returns_clear_event() -> None:
    engine = ConsoleEngine(MathRuntime())

    events = engine.clear_console()

    assert events == [ConsoleEvent(kind="clear", text="")]
