from __future__ import annotations

from console_engine import MathRuntime
from repl import create_aether_repl, create_legacy_mathlab_repl, create_mathlab_repl


def test_aether_repl_session_persists_through_input() -> None:
    repl = create_aether_repl()

    repl.execute_line("x = 5;")
    events = repl.execute_line("println(x);")

    assert [(event.kind, event.text) for event in events] == [("stdout", "5")]


def test_aether_repl_restart_clears_variables() -> None:
    repl = create_aether_repl()

    repl.execute_line("x = 5;")
    repl.reset_environment()
    events = repl.execute_line("println(x);")

    assert any(event.kind == "error" and "Undefined variable 'x'" in event.text for event in events)


def test_aether_repl_errors_do_not_destroy_state() -> None:
    repl = create_aether_repl()

    repl.execute_line("x = 5;")
    error_events = repl.execute_line('x = "oops";')
    output_events = repl.execute_line("println(x);")

    assert any(event.kind == "error" for event in error_events)
    assert [(event.kind, event.text) for event in output_events] == [("stdout", "5")]


def test_aether_repl_workspace_updates_from_session() -> None:
    repl = create_aether_repl()

    repl.execute_line("Matrix<int> A = [1 2; 3 4];")

    assert repl.workspace_snapshot() == [
        {
            "name": "A",
            "type": "Matrix<int>",
            "shape": "2x2",
            "class": "Matrix<int>",
            "size": "2x2",
            "summary": "[1 2; 3 4]",
        }
    ]


def test_aether_repl_profile_uses_aether_prompt() -> None:
    repl = create_aether_repl()

    assert repl.profile.title == "Aether REPL"
    assert repl.prompt == "aether> "


def test_mathlab_repl_profile_keeps_legacy_console() -> None:
    repl = create_mathlab_repl(MathRuntime())

    assert repl.profile.title == "MathLab Legacy Console"
    assert repl.prompt == "mathlab> "


def test_explicit_legacy_mathlab_repl_alias_keeps_compatibility() -> None:
    repl = create_legacy_mathlab_repl(MathRuntime())

    assert repl.profile.title == "MathLab Legacy Console"
    assert repl.prompt == "mathlab> "
