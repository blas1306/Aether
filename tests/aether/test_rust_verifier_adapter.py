from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys

import pytest

from aether.ir import (
    IRModule,
    RustVerifierAccepted,
    RustVerifierExecutableNotFound,
    RustVerifierInvalidResponse,
    RustVerifierOutputLimitExceeded,
    RustVerifierPhase,
    RustVerifierProcessFailure,
    RustVerifierProtocolError,
    RustVerifierProtocolErrorKind,
    RustVerifierRejected,
    RustVerifierRequestTooLarge,
    RustVerifierSpawnFailure,
    RustVerifierTimeout,
    VerifierCategory,
    discover_rust_verifier_executable,
    verify_module_with_rust,
)


ACCEPTED_RESPONSE = {"protocol_version": 1, "status": "accepted"}
REJECTED_RESPONSE = {
    "protocol_version": 1,
    "status": "rejected",
    "diagnostic": {
        "phase": "types",
        "category": "returns",
        "invariant": "IRV-026",
        "message": "bad return",
        "context": {
            "function_index": 0,
            "function_name": "main",
            "block_index": 1,
            "block_name": "exit",
            "instruction_index": 2,
            "instruction_kind": "return",
        },
    },
}
ERROR_RESPONSE = {
    "protocol_version": 1,
    "status": "error",
    "error": {"kind": "module_import", "message": "cannot import module"},
}


def _command(source: str) -> list[str]:
    return [sys.executable, "-c", source]


def _emit(value: object, *, stderr: bytes = b"") -> list[str]:
    stdout = json.dumps(value, separators=(",", ":")).encode() + b"\n"
    return _command(
        "import os\n"
        f"os.write(1, {stdout!r})\n"
        f"os.write(2, {stderr!r})\n"
    )


def test_accepted_response_and_exact_canonical_request() -> None:
    expected = (
        b'{"module":{"functions":[],"schema_version":1,"structs":[]},'
        b'"operation":"verify","protocol_version":1}\n'
    )
    command = _command(
        "import json, os, sys\n"
        "request = sys.stdin.buffer.read()\n"
        f"expected = {expected!r}\n"
        "if request != expected:\n"
        "    os.write(2, request)\n"
        "    raise SystemExit(9)\n"
        "os.write(1, b'{\"protocol_version\":1,\"status\":\"accepted\"}\\n')\n"
    )

    module = IRModule()
    original = copy.deepcopy(module)
    first = verify_module_with_rust(module, executable=command)
    second = verify_module_with_rust(module, executable=command)

    assert first == second == RustVerifierAccepted()
    assert module == original


def test_rejected_response_preserves_all_typed_diagnostic_context() -> None:
    result = verify_module_with_rust(
        IRModule(), executable=_emit(REJECTED_RESPONSE)
    )

    assert isinstance(result, RustVerifierRejected)
    assert result.diagnostic.phase is RustVerifierPhase.TYPES
    assert result.diagnostic.category is VerifierCategory.RETURNS
    assert result.diagnostic.invariant == "IRV-026"
    assert result.diagnostic.message == "bad return"
    assert result.diagnostic.function_index == 0
    assert result.diagnostic.function_name == "main"
    assert result.diagnostic.block_index == 1
    assert result.diagnostic.block_name == "exit"
    assert result.diagnostic.instruction_index == 2
    assert result.diagnostic.instruction_kind == "return"


def test_protocol_error_is_a_result_not_an_adapter_exception() -> None:
    result = verify_module_with_rust(IRModule(), executable=_emit(ERROR_RESPONSE))

    assert result == RustVerifierProtocolError(
        RustVerifierProtocolErrorKind.MODULE_IMPORT,
        "cannot import module",
    )


def test_exit_zero_stderr_is_preserved_but_does_not_change_semantics() -> None:
    result = verify_module_with_rust(
        IRModule(),
        executable=_emit(ACCEPTED_RESPONSE, stderr=b"debug note\n"),
    )

    assert isinstance(result, RustVerifierAccepted)
    assert result.transport.stderr == b"debug note\n"


@pytest.mark.parametrize(
    ("stdout", "match"),
    [
        (b"", "empty"),
        (b"not json", "strict JSON"),
        (b"{}\n{}\n", "trailing"),
        (
            b'{"protocol_version":1,"protocol_version":1,"status":"accepted"}',
            "strict JSON",
        ),
        (b'{"protocol_version":2,"status":"accepted"}', "must be 1"),
        (b'{"protocol_version":1,"status":"future"}', "unknown"),
        (
            b'{"protocol_version":1,"status":"accepted","diagnostic":{}}',
            "fields",
        ),
        (b"\xff", "UTF-8"),
        (b'{"protocol_version":1,"status":"accepted"} extra', "trailing"),
    ],
)
def test_invalid_stdout_shapes_are_rejected(stdout: bytes, match: str) -> None:
    with pytest.raises(RustVerifierInvalidResponse, match=match):
        verify_module_with_rust(
            IRModule(),
            executable=_command(f"import os\nos.write(1, {stdout!r})\n"),
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("phase",), "future"),
        (("category",), "future"),
        (("invariant",), "IRV-26"),
        (("context", "function_index"), True),
        (("context", "block_index"), -1),
        (("context", "instruction_kind"), "future_instruction"),
        (("context", "function_name"), 3),
    ],
)
def test_invalid_diagnostic_fields_are_rejected(
    path: tuple[str, ...], value: object
) -> None:
    response = json.loads(json.dumps(REJECTED_RESPONSE))
    target = response["diagnostic"]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(RustVerifierInvalidResponse):
        verify_module_with_rust(IRModule(), executable=_emit(response))


def test_timeout_terminates_process_and_keeps_bounded_partial_output() -> None:
    command = _command(
        "import os, time\n"
        "os.write(1, b'partial')\n"
        "os.write(2, b'note')\n"
        "time.sleep(30)\n"
    )

    with pytest.raises(RustVerifierTimeout) as raised:
        verify_module_with_rust(
            IRModule(), executable=command, timeout_seconds=0.1
        )

    assert raised.value.stdout_excerpt == b"partial"
    assert raised.value.stderr_excerpt == b"note"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_output_limits_terminate_chatty_processes(stream: str) -> None:
    descriptor = 1 if stream == "stdout" else 2
    command = _command(
        "import os\n"
        f"os.write({descriptor}, b'x' * 10000)\n"
        "os.write(1, b'{\"protocol_version\":1,\"status\":\"accepted\"}\\n')\n"
    )

    with pytest.raises(RustVerifierOutputLimitExceeded) as raised:
        verify_module_with_rust(
            IRModule(),
            executable=command,
            stdout_limit_bytes=100 if stream == "stdout" else 1024,
            stderr_limit_bytes=100 if stream == "stderr" else 1024,
        )

    assert raised.value.stream == stream
    assert raised.value.limit_bytes == 100
    assert raised.value.excerpt == b"x" * 100


def test_request_limit_is_enforced_before_spawn() -> None:
    with pytest.raises(RustVerifierRequestTooLarge):
        verify_module_with_rust(
            IRModule(),
            executable=["definitely-not-run"],
            request_limit_bytes=1,
        )


def test_nonzero_exit_never_trusts_json_stdout() -> None:
    command = _command(
        "import os\n"
        "os.write(1, b'{\"protocol_version\":1,\"status\":\"accepted\"}\\n')\n"
        "os.write(2, b'failed')\n"
        "raise SystemExit(7)\n"
    )

    with pytest.raises(RustVerifierProcessFailure) as raised:
        verify_module_with_rust(IRModule(), executable=command)

    assert raised.value.returncode == 7
    assert b'"accepted"' in raised.value.stdout_excerpt
    assert raised.value.stderr_excerpt == b"failed"


def test_missing_executable_and_other_spawn_failures_are_distinct(
    tmp_path: Path,
) -> None:
    with pytest.raises(RustVerifierExecutableNotFound):
        verify_module_with_rust(
            IRModule(), executable=tmp_path / "does-not-exist"
        )

    with pytest.raises(RustVerifierSpawnFailure):
        verify_module_with_rust(IRModule(), executable=tmp_path)


@pytest.mark.parametrize("timeout", [True, 0, -1, float("inf"), float("nan")])
def test_timeout_must_be_a_finite_positive_real(timeout: object) -> None:
    expected = TypeError if timeout is True else ValueError
    with pytest.raises(expected):
        verify_module_with_rust(
            IRModule(),
            executable=_emit(ACCEPTED_RESPONSE),
            timeout_seconds=timeout,  # type: ignore[arg-type]
        )


def test_discovery_precedence_is_explicit_then_path_then_requested_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit = tmp_path / "explicit"
    explicit.write_bytes(b"")
    explicit.chmod(0o755)
    assert discover_rust_verifier_executable(executable=explicit) == explicit

    path_directory = tmp_path / "path"
    path_directory.mkdir()
    path_executable = path_directory / "aether-ir-verifier"
    path_executable.write_bytes(b"")
    path_executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(path_directory))
    assert discover_rust_verifier_executable() == path_executable

    repository_executable = (
        tmp_path
        / "repository"
        / "compiler-rs"
        / "target"
        / "debug"
        / "aether-ir-verifier"
    )
    repository_executable.parent.mkdir(parents=True)
    repository_executable.write_bytes(b"")
    repository_executable.chmod(0o755)
    assert (
        discover_rust_verifier_executable(
            search_path=False,
            repository_root=tmp_path / "repository",
        )
        == repository_executable
    )


def test_discovery_failure_does_not_depend_on_current_working_directory(
    tmp_path: Path,
) -> None:
    original = Path.cwd()
    try:
        os.chdir(tmp_path)
        with pytest.raises(RustVerifierExecutableNotFound):
            discover_rust_verifier_executable(search_path=False)
    finally:
        os.chdir(original)
