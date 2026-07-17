from __future__ import annotations

import pytest

from aether import AetherSession, AetherTypeError, run_aether


def test_session_persists_variable_between_runs() -> None:
    session = AetherSession()

    session.run("x = 5;")
    result = session.run("println(x);")

    assert result.output == "5\n"


def test_session_persists_function_between_runs() -> None:
    session = AetherSession()

    session.run(
        """
        int f(int x) {
            return x + 1;
        }
        """
    )
    result = session.run("println(f(4));")

    assert result.output == "5\n"


def test_function_persists_in_session_without_keyword() -> None:
    session = AetherSession()

    session.run(
        """
        double doble(double x) {
            return 2*x;
        }
        """
    )
    result = session.run("println(doble(3));")

    assert result.output == "6.0\n"


def test_session_error_does_not_destroy_previous_state() -> None:
    session = AetherSession()

    session.run("x = 5;")
    with pytest.raises(AetherTypeError):
        session.run('x = "hola";')

    result = session.run("println(x);")
    assert result.output == "5\n"


def test_session_failed_run_does_not_partially_commit_new_variable() -> None:
    session = AetherSession()

    with pytest.raises(AetherTypeError):
        session.run("y = 1; println(missing);")

    with pytest.raises(AetherTypeError, match="Undefined variable 'y'"):
        session.run("println(y);")


def test_session_block_scope_still_does_not_escape() -> None:
    session = AetherSession()

    session.run("if (true) { y = 3; }")

    with pytest.raises(AetherTypeError, match="Undefined variable 'y'"):
        session.run("println(y);")


def test_run_aether_still_uses_fresh_session() -> None:
    run_aether("x = 5;")

    with pytest.raises(AetherTypeError, match="Undefined variable 'x'"):
        run_aether("println(x);")


def test_two_sessions_are_independent() -> None:
    s1 = AetherSession()
    s2 = AetherSession()

    s1.run("x = 5;")

    with pytest.raises(AetherTypeError, match="Undefined variable 'x'"):
        s2.run("println(x);")
