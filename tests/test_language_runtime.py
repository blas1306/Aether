from __future__ import annotations

from aether import AetherSession
from language_runtime import (
    AETHER_RUNTIME,
    UNKNOWN_RUNTIME,
    create_session_for_language,
    run_source_for_file,
    runtime_for_file,
)


def test_runtime_for_aether_file_returns_aether() -> None:
    assert runtime_for_file("demo.ae") == AETHER_RUNTIME


def test_runtime_for_legacy_files_returns_unknown() -> None:
    assert runtime_for_file("legacy.mtx") == UNKNOWN_RUNTIME
    assert runtime_for_file("document.mtex") == UNKNOWN_RUNTIME
    assert runtime_for_file("notebook.mtn") == UNKNOWN_RUNTIME


def test_run_aether_source_returns_output() -> None:
    result = run_source_for_file("hello.ae", 'println("hola");')

    assert result.success
    assert result.runtime == AETHER_RUNTIME
    assert result.output == "hola\n"
    assert result.error is None


def test_run_aether_error_is_reported_without_raising() -> None:
    result = run_source_for_file("broken.ae", "println(x);")

    assert not result.success
    assert result.runtime == AETHER_RUNTIME
    assert result.error == "AetherTypeError: Undefined variable 'x'."


def test_create_session_for_language_returns_aether_session() -> None:
    assert isinstance(create_session_for_language("aether"), AetherSession)


def test_legacy_source_is_rejected_without_running_mathlab() -> None:
    result = run_source_for_file("legacy.mtx", "a = 1;")

    assert not result.success
    assert result.runtime == UNKNOWN_RUNTIME
    assert "Legacy format '.mtx' is not supported by Aether Studio" in (result.error or "")


def test_create_session_for_language_rejects_legacy_runtime() -> None:
    try:
        create_session_for_language(".mtx")
    except ValueError as exc:
        assert "No session is registered" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected .mtx session creation to be rejected")
