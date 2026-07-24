"""Opt-in subprocess adapter for the standalone Rust Initial IR verifier.

This module is deliberately not imported by the compiler pipeline.  It keeps
canonical request construction, bounded subprocess transport, and strict
protocol decoding as separate operations.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from time import monotonic
from typing import NoReturn, TypeAlias

from .dto import IR_INSTRUCTION_DTO_REGISTRY
from .model import IRModule
from .rust_verifier_client import (
    RUST_VERIFIER_PROTOCOL_VERSION,
    CanonicalRustVerifierRequest,
    RustVerifierAcceptedOutcome,
    RustVerifierAdapterError,
    RustVerifierClientKind,
    RustVerifierInfrastructureFailure,
    RustVerifierInfrastructureFailureKind,
    RustVerifierIntegrationError,
    RustVerifierInvocation,
    RustVerifierInvocationMetadata,
    RustVerifierInvocationTransportMetadata,
    RustVerifierNormalizedDiagnostic,
    RustVerifierPhase,
    RustVerifierRejectedOutcome,
    RustVerifierRequestConstructionError,
    build_canonical_rust_verifier_request,
)
from .verification_result import VerifierCategory


DEFAULT_RUST_VERIFIER_TIMEOUT_SECONDS = 5.0
DEFAULT_RUST_VERIFIER_REQUEST_LIMIT_BYTES = 16 * 1024 * 1024
DEFAULT_RUST_VERIFIER_STDOUT_LIMIT_BYTES = 1024 * 1024
DEFAULT_RUST_VERIFIER_STDERR_LIMIT_BYTES = 256 * 1024

_READ_CHUNK_BYTES = 64 * 1024
_WAIT_SLICE_SECONDS = 0.05
_TERMINATE_GRACE_SECONDS = 1.0
_EXECUTABLE_BASENAME = "aether-ir-verifier"
_INVARIANT_PATTERN = re.compile(r"IRV-[0-9]{3}")
_KNOWN_INSTRUCTION_KINDS = frozenset(
    entry.tag for entry in IR_INSTRUCTION_DTO_REGISTRY
)

RustVerifierCommand: TypeAlias = (
    str | os.PathLike[str] | Sequence[str | os.PathLike[str]]
)


class RustVerifierProtocolErrorKind(str, Enum):
    """Stable infrastructure-error spellings emitted by protocol v1."""

    EMPTY_INPUT = "empty_input"
    MALFORMED_JSON = "malformed_json"
    REQUEST_SCHEMA = "request_schema"
    UNSUPPORTED_PROTOCOL_VERSION = "unsupported_protocol_version"
    UNSUPPORTED_IR_SCHEMA_VERSION = "unsupported_ir_schema_version"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    MODULE_SCHEMA = "module_schema"
    MODULE_IMPORT = "module_import"
    NORMALIZATION = "normalization"
    INPUT_IO = "input_io"
    INTERNAL = "internal"


@dataclass(frozen=True)
class RustVerifierTransportMetadata:
    """Non-semantic process metadata retained for diagnostics."""

    stderr: bytes = b""


@dataclass(frozen=True)
class RustVerifierDiagnostic:
    """One typed semantic rejection from the Rust verifier."""

    phase: RustVerifierPhase
    category: VerifierCategory
    invariant: str
    message: str
    function_index: int | None
    function_name: str | None
    block_index: int | None
    block_name: str | None
    instruction_index: int | None
    instruction_kind: str | None


@dataclass(frozen=True)
class RustVerifierAccepted:
    """A successful semantic verification."""

    transport: RustVerifierTransportMetadata = field(
        default_factory=RustVerifierTransportMetadata
    )


@dataclass(frozen=True)
class RustVerifierRejected:
    """A trustworthy semantic rejection."""

    diagnostic: RustVerifierDiagnostic
    transport: RustVerifierTransportMetadata = field(
        default_factory=RustVerifierTransportMetadata
    )


@dataclass(frozen=True)
class RustVerifierProtocolError:
    """A valid protocol-level error response from the Rust executable."""

    kind: RustVerifierProtocolErrorKind
    message: str
    transport: RustVerifierTransportMetadata = field(
        default_factory=RustVerifierTransportMetadata
    )


RustVerifierResult: TypeAlias = (
    RustVerifierAccepted | RustVerifierRejected | RustVerifierProtocolError
)


class RustVerifierExecutableNotFound(RustVerifierAdapterError):
    """Raised when the configured executable cannot be found."""


class RustVerifierSpawnFailure(RustVerifierAdapterError):
    """Raised when the operating system refuses to start the process."""


class RustVerifierTimeout(RustVerifierAdapterError):
    """Raised when the verifier does not finish within the configured timeout."""

    def __init__(
        self,
        timeout_seconds: float,
        *,
        stdout_excerpt: bytes,
        stderr_excerpt: bytes,
    ) -> None:
        super().__init__(
            f"Rust verifier exceeded the {timeout_seconds:g} second timeout"
        )
        self.timeout_seconds = timeout_seconds
        self.stdout_excerpt = stdout_excerpt
        self.stderr_excerpt = stderr_excerpt


class RustVerifierOutputLimitExceeded(RustVerifierAdapterError):
    """Raised when stdout or stderr exceeds its configured byte limit."""

    def __init__(self, stream: str, limit_bytes: int, *, excerpt: bytes) -> None:
        super().__init__(
            f"Rust verifier {stream} exceeded the {limit_bytes} byte limit"
        )
        self.stream = stream
        self.limit_bytes = limit_bytes
        self.excerpt = excerpt


class RustVerifierRequestTooLarge(RustVerifierAdapterError):
    """Raised before spawning when the encoded request is too large."""

    def __init__(self, size_bytes: int, limit_bytes: int) -> None:
        super().__init__(
            f"Rust verifier request is {size_bytes} bytes; limit is {limit_bytes}"
        )
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes


class RustVerifierProcessFailure(RustVerifierAdapterError):
    """Raised for a nonzero exit, whose stdout is never trusted."""

    def __init__(
        self,
        returncode: int,
        *,
        stdout_excerpt: bytes,
        stderr_excerpt: bytes,
    ) -> None:
        super().__init__(f"Rust verifier process exited with status {returncode}")
        self.returncode = returncode
        self.stdout_excerpt = stdout_excerpt
        self.stderr_excerpt = stderr_excerpt


class RustVerifierInvalidResponse(RustVerifierAdapterError):
    """Raised when exit-zero stdout is not exactly one protocol-v1 response."""


@dataclass(frozen=True)
class SubprocessRustVerifierInvocationMetadata(
    RustVerifierInvocationTransportMetadata
):
    """Process-only details nested under neutral invocation metadata."""

    stderr: bytes
    exit_code: int
    protocol_error_kind: RustVerifierProtocolErrorKind | None = None


@dataclass
class _CapturedStream:
    limit_bytes: int
    data: bytearray = field(default_factory=bytearray)
    exceeded: bool = False


@dataclass(frozen=True)
class _ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class _DuplicateJSONKey(ValueError):
    pass


_PROTOCOL_ERROR_TO_INFRASTRUCTURE_KIND = {
    RustVerifierProtocolErrorKind.EMPTY_INPUT: (
        RustVerifierInfrastructureFailureKind.INVALID_REQUEST
    ),
    RustVerifierProtocolErrorKind.MALFORMED_JSON: (
        RustVerifierInfrastructureFailureKind.INVALID_REQUEST
    ),
    RustVerifierProtocolErrorKind.REQUEST_SCHEMA: (
        RustVerifierInfrastructureFailureKind.INVALID_REQUEST
    ),
    RustVerifierProtocolErrorKind.UNSUPPORTED_PROTOCOL_VERSION: (
        RustVerifierInfrastructureFailureKind.INCOMPATIBLE_VERSION
    ),
    RustVerifierProtocolErrorKind.UNSUPPORTED_IR_SCHEMA_VERSION: (
        RustVerifierInfrastructureFailureKind.INCOMPATIBLE_VERSION
    ),
    RustVerifierProtocolErrorKind.UNSUPPORTED_OPERATION: (
        RustVerifierInfrastructureFailureKind.UNSUPPORTED_OPERATION
    ),
    RustVerifierProtocolErrorKind.MODULE_SCHEMA: (
        RustVerifierInfrastructureFailureKind.INVALID_MODULE
    ),
    RustVerifierProtocolErrorKind.MODULE_IMPORT: (
        RustVerifierInfrastructureFailureKind.INVALID_MODULE
    ),
    RustVerifierProtocolErrorKind.NORMALIZATION: (
        RustVerifierInfrastructureFailureKind.INVALID_MODULE
    ),
    RustVerifierProtocolErrorKind.INPUT_IO: (
        RustVerifierInfrastructureFailureKind.INPUT_IO
    ),
    RustVerifierProtocolErrorKind.INTERNAL: (
        RustVerifierInfrastructureFailureKind.INTERNAL
    ),
}


class SubprocessRustVerifierClient:
    """Bounded protocol-v1 subprocess implementation of the neutral client."""

    def __init__(
        self,
        *,
        executable: RustVerifierCommand,
        timeout_seconds: float = DEFAULT_RUST_VERIFIER_TIMEOUT_SECONDS,
        request_limit_bytes: int = DEFAULT_RUST_VERIFIER_REQUEST_LIMIT_BYTES,
        stdout_limit_bytes: int = DEFAULT_RUST_VERIFIER_STDOUT_LIMIT_BYTES,
        stderr_limit_bytes: int = DEFAULT_RUST_VERIFIER_STDERR_LIMIT_BYTES,
    ) -> None:
        self._command = _normalize_command(executable)
        self._timeout_seconds = _validate_timeout(timeout_seconds)
        self._request_limit_bytes = _validate_byte_limit(
            request_limit_bytes,
            "request_limit_bytes",
        )
        self._stdout_limit_bytes = _validate_byte_limit(
            stdout_limit_bytes,
            "stdout_limit_bytes",
        )
        self._stderr_limit_bytes = _validate_byte_limit(
            stderr_limit_bytes,
            "stderr_limit_bytes",
        )

    def verify(
        self,
        request: CanonicalRustVerifierRequest,
    ) -> RustVerifierInvocation:
        """Invoke the configured process using an already encoded request."""

        if not isinstance(request, CanonicalRustVerifierRequest):
            raise TypeError("request must be a CanonicalRustVerifierRequest")
        if len(request.payload) > self._request_limit_bytes:
            raise RustVerifierRequestTooLarge(
                len(request.payload),
                self._request_limit_bytes,
            )

        started_at = monotonic()
        process_result = _run_bounded_process(
            self._command,
            request.payload,
            timeout_seconds=self._timeout_seconds,
            stdout_limit_bytes=self._stdout_limit_bytes,
            stderr_limit_bytes=self._stderr_limit_bytes,
        )
        if process_result.returncode != 0:
            raise RustVerifierProcessFailure(
                process_result.returncode,
                stdout_excerpt=process_result.stdout,
                stderr_excerpt=process_result.stderr,
            )
        wire_result = _decode_response(
            process_result.stdout,
            transport=RustVerifierTransportMetadata(
                stderr=process_result.stderr,
            ),
        )
        duration_seconds = monotonic() - started_at
        protocol_error_kind = (
            wire_result.kind
            if isinstance(wire_result, RustVerifierProtocolError)
            else None
        )
        metadata = RustVerifierInvocationMetadata(
            client_kind=RustVerifierClientKind.SUBPROCESS,
            duration_seconds=duration_seconds,
            protocol_version=request.protocol_version,
            ir_schema_version=request.ir_schema_version,
            transport_metadata=SubprocessRustVerifierInvocationMetadata(
                stderr=process_result.stderr,
                exit_code=process_result.returncode,
                protocol_error_kind=protocol_error_kind,
            ),
        )
        return RustVerifierInvocation(
            outcome=_translate_protocol_result(wire_result),
            metadata=metadata,
        )


def verify_module_with_rust(
    module: IRModule,
    *,
    executable: RustVerifierCommand,
    timeout_seconds: float = DEFAULT_RUST_VERIFIER_TIMEOUT_SECONDS,
    request_limit_bytes: int = DEFAULT_RUST_VERIFIER_REQUEST_LIMIT_BYTES,
    stdout_limit_bytes: int = DEFAULT_RUST_VERIFIER_STDOUT_LIMIT_BYTES,
    stderr_limit_bytes: int = DEFAULT_RUST_VERIFIER_STDERR_LIMIT_BYTES,
) -> RustVerifierResult:
    """Verify ``module`` through one explicitly selected Rust subprocess.

    Stderr is retained as transport metadata when the process exits zero and
    stdout contains a valid response; it never affects semantic classification.

    This compatibility API delegates to :class:`SubprocessRustVerifierClient`
    and translates its neutral invocation back to the Phase 4.2B wire result.
    """

    client = SubprocessRustVerifierClient(
        executable=executable,
        timeout_seconds=timeout_seconds,
        request_limit_bytes=request_limit_bytes,
        stdout_limit_bytes=stdout_limit_bytes,
        stderr_limit_bytes=stderr_limit_bytes,
    )
    invocation = client.verify(build_canonical_rust_verifier_request(module))
    return _legacy_result_from_invocation(invocation)


def discover_rust_verifier_executable(
    *,
    executable: str | os.PathLike[str] | None = None,
    search_path: bool = True,
    repository_root: str | os.PathLike[str] | None = None,
    build_profile: str = "debug",
) -> Path:
    """Resolve a development executable with deterministic opt-in precedence.

    Precedence is an explicit path, then ``PATH`` when ``search_path`` is true,
    then ``repository_root/compiler-rs/target/<profile>`` when a repository
    root is supplied.  No environment variable or current working directory is
    consulted implicitly.
    """

    if executable is not None:
        return _require_executable_path(Path(executable))

    executable_name = (
        f"{_EXECUTABLE_BASENAME}.exe"
        if os.name == "nt"
        else _EXECUTABLE_BASENAME
    )
    if search_path:
        discovered = shutil.which(executable_name)
        if discovered is not None:
            return Path(discovered).resolve()

    if repository_root is not None:
        if build_profile not in {"debug", "release"}:
            raise ValueError("build_profile must be 'debug' or 'release'")
        candidate = (
            Path(repository_root)
            / "compiler-rs"
            / "target"
            / build_profile
            / executable_name
        )
        return _require_executable_path(candidate)

    raise RustVerifierExecutableNotFound(
        "Rust verifier executable was not found using the requested discovery sources"
    )


def _require_executable_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise RustVerifierExecutableNotFound(
            "Configured Rust verifier executable does not exist or is not executable"
        )
    return resolved


def _encode_request(module: IRModule) -> bytes:
    """Compatibility wrapper around the single canonical request builder."""

    return build_canonical_rust_verifier_request(module).payload


def _translate_protocol_result(
    result: RustVerifierResult,
) -> (
    RustVerifierAcceptedOutcome
    | RustVerifierRejectedOutcome
    | RustVerifierInfrastructureFailure
):
    if isinstance(result, RustVerifierAccepted):
        return RustVerifierAcceptedOutcome()
    if isinstance(result, RustVerifierRejected):
        diagnostic = result.diagnostic
        return RustVerifierRejectedOutcome(
            RustVerifierNormalizedDiagnostic(
                invariant_id=diagnostic.invariant,
                phase=diagnostic.phase,
                category=diagnostic.category,
                message=diagnostic.message,
                function_index=diagnostic.function_index,
                function_name=diagnostic.function_name,
                block_index=diagnostic.block_index,
                block_name=diagnostic.block_name,
                instruction_index=diagnostic.instruction_index,
                instruction_kind=diagnostic.instruction_kind,
            )
        )
    return RustVerifierInfrastructureFailure(
        kind=_PROTOCOL_ERROR_TO_INFRASTRUCTURE_KIND[result.kind],
        message=result.message,
    )


def _legacy_result_from_invocation(
    invocation: RustVerifierInvocation,
) -> RustVerifierResult:
    transport_metadata = invocation.metadata.transport_metadata
    if not isinstance(
        transport_metadata,
        SubprocessRustVerifierInvocationMetadata,
    ):
        raise TypeError("invocation does not contain subprocess metadata")
    transport = RustVerifierTransportMetadata(stderr=transport_metadata.stderr)
    outcome = invocation.outcome
    if isinstance(outcome, RustVerifierAcceptedOutcome):
        return RustVerifierAccepted(transport)
    if isinstance(outcome, RustVerifierRejectedOutcome):
        diagnostic = outcome.diagnostic
        return RustVerifierRejected(
            RustVerifierDiagnostic(
                phase=diagnostic.phase,
                category=diagnostic.category,
                invariant=diagnostic.invariant_id,
                message=diagnostic.message,
                function_index=diagnostic.function_index,
                function_name=diagnostic.function_name,
                block_index=diagnostic.block_index,
                block_name=diagnostic.block_name,
                instruction_index=diagnostic.instruction_index,
                instruction_kind=diagnostic.instruction_kind,
            ),
            transport,
        )
    if transport_metadata.protocol_error_kind is None:
        raise TypeError(
            "subprocess infrastructure failure lacks a protocol error kind"
        )
    return RustVerifierProtocolError(
        kind=transport_metadata.protocol_error_kind,
        message=outcome.message,
        transport=transport,
    )


def _normalize_command(executable: RustVerifierCommand) -> tuple[str, ...]:
    if isinstance(executable, (str, os.PathLike)):
        raw_command: Sequence[str | os.PathLike[str]] = (executable,)
    elif isinstance(executable, Sequence):
        raw_command = executable
    else:
        raise TypeError("executable must be a path, string, or command sequence")

    if not raw_command:
        raise ValueError("executable command must not be empty")
    command: list[str] = []
    for argument in raw_command:
        if not isinstance(argument, (str, os.PathLike)):
            raise TypeError("executable command arguments must be strings or paths")
        normalized = os.fspath(argument)
        if not normalized:
            raise ValueError("executable command arguments must not be empty")
        command.append(normalized)
    return tuple(command)


def _validate_timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("timeout_seconds must be a real number")
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    return timeout


def _validate_byte_limit(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _run_bounded_process(
    command: tuple[str, ...],
    request: bytes,
    *,
    timeout_seconds: float,
    stdout_limit_bytes: int,
    stderr_limit_bytes: int,
) -> _ProcessResult:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except FileNotFoundError:
        raise RustVerifierExecutableNotFound(
            "Configured Rust verifier executable was not found"
        ) from None
    except OSError as error:
        raise RustVerifierSpawnFailure(
            f"Could not start Rust verifier process ({error.__class__.__name__})"
        ) from None

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stdout = _CapturedStream(stdout_limit_bytes)
    stderr = _CapturedStream(stderr_limit_bytes)
    limit_event = threading.Event()

    writer = threading.Thread(
        target=_write_request,
        args=(process.stdin, request),
        name="aether-rust-verifier-stdin",
        daemon=True,
    )
    stdout_reader = threading.Thread(
        target=_read_bounded_stream,
        args=(process.stdout, stdout, limit_event, process),
        name="aether-rust-verifier-stdout",
        daemon=True,
    )
    stderr_reader = threading.Thread(
        target=_read_bounded_stream,
        args=(process.stderr, stderr, limit_event, process),
        name="aether-rust-verifier-stderr",
        daemon=True,
    )
    for thread in (writer, stdout_reader, stderr_reader):
        thread.start()

    deadline = monotonic() + timeout_seconds
    timed_out = False
    while process.poll() is None:
        if limit_event.is_set():
            _terminate_and_reap(process)
            break
        remaining = deadline - monotonic()
        if remaining <= 0:
            timed_out = True
            _terminate_and_reap(process)
            break
        try:
            process.wait(timeout=min(_WAIT_SLICE_SECONDS, remaining))
        except subprocess.TimeoutExpired:
            continue

    if process.poll() is None:
        _terminate_and_reap(process)
    for thread in (writer, stdout_reader, stderr_reader):
        thread.join(timeout=_TERMINATE_GRACE_SECONDS)

    captured_stdout = bytes(stdout.data)
    captured_stderr = bytes(stderr.data)
    if stdout.exceeded:
        raise RustVerifierOutputLimitExceeded(
            "stdout", stdout.limit_bytes, excerpt=captured_stdout
        )
    if stderr.exceeded:
        raise RustVerifierOutputLimitExceeded(
            "stderr", stderr.limit_bytes, excerpt=captured_stderr
        )
    if timed_out:
        raise RustVerifierTimeout(
            timeout_seconds,
            stdout_excerpt=captured_stdout,
            stderr_excerpt=captured_stderr,
        )
    return _ProcessResult(
        returncode=process.returncode,
        stdout=captured_stdout,
        stderr=captured_stderr,
    )


def _write_request(stream: object, request: bytes) -> None:
    try:
        stream.write(request)  # type: ignore[attr-defined]
        stream.flush()  # type: ignore[attr-defined]
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            stream.close()  # type: ignore[attr-defined]
        except OSError:
            pass


def _read_bounded_stream(
    stream: object,
    capture: _CapturedStream,
    limit_event: threading.Event,
    process: subprocess.Popen[bytes],
) -> None:
    try:
        while True:
            remaining = capture.limit_bytes - len(capture.data)
            chunk = stream.read(min(_READ_CHUNK_BYTES, remaining + 1))  # type: ignore[attr-defined]
            if not chunk:
                return
            if len(chunk) > remaining:
                capture.data.extend(chunk[:remaining])
                capture.exceeded = True
                limit_event.set()
                try:
                    process.terminate()
                except OSError:
                    pass
                return
            capture.data.extend(chunk)
    except OSError:
        return
    finally:
        try:
            stream.close()  # type: ignore[attr-defined]
        except OSError:
            pass


def _terminate_and_reap(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        process.kill()
    except OSError:
        pass
    process.wait()


def _decode_response(
    data: bytes,
    *,
    transport: RustVerifierTransportMetadata,
) -> RustVerifierResult:
    value = _decode_one_json_value(data)
    response = _expect_mapping(value, "response")
    version = response.get("protocol_version")
    if type(version) is not int:
        _invalid("response.protocol_version must be an integer")
    if version != RUST_VERIFIER_PROTOCOL_VERSION:
        _invalid(
            f"response.protocol_version must be {RUST_VERIFIER_PROTOCOL_VERSION}"
        )
    status = response.get("status")
    if type(status) is not str:
        _invalid("response.status must be a string")

    if status == "accepted":
        _expect_fields(response, {"protocol_version", "status"}, "accepted response")
        return RustVerifierAccepted(transport)
    if status == "rejected":
        _expect_fields(
            response,
            {"protocol_version", "status", "diagnostic"},
            "rejected response",
        )
        return RustVerifierRejected(
            _decode_diagnostic(response["diagnostic"]),
            transport,
        )
    if status == "error":
        _expect_fields(
            response,
            {"protocol_version", "status", "error"},
            "error response",
        )
        error = _expect_mapping(response["error"], "response.error")
        _expect_fields(error, {"kind", "message"}, "response.error")
        kind = _expect_enum(
            error["kind"], RustVerifierProtocolErrorKind, "response.error.kind"
        )
        message = _expect_string(error["message"], "response.error.message")
        return RustVerifierProtocolError(kind, message, transport)
    _invalid(f"response.status has unknown value {status!r}")


def _decode_one_json_value(data: bytes) -> object:
    if not data:
        _invalid("stdout is empty")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _invalid("stdout is not valid UTF-8")

    decoder = json.JSONDecoder(
        object_pairs_hook=_object_without_duplicates,
        parse_constant=_reject_json_constant,
    )
    start = len(text) - len(text.lstrip())
    try:
        value, end = decoder.raw_decode(text, start)
    except (_DuplicateJSONKey, ValueError, json.JSONDecodeError):
        _invalid("stdout is not one valid strict JSON value")
    if text[end:].strip():
        _invalid("stdout contains trailing text or an additional JSON value")
    return value


def _object_without_duplicates(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"non-standard JSON constant {value}")


def _decode_diagnostic(value: object) -> RustVerifierDiagnostic:
    diagnostic = _expect_mapping(value, "response.diagnostic")
    _expect_fields(
        diagnostic,
        {"phase", "category", "invariant", "message", "context"},
        "response.diagnostic",
    )
    phase = _expect_enum(
        diagnostic["phase"], RustVerifierPhase, "response.diagnostic.phase"
    )
    category = _expect_enum(
        diagnostic["category"],
        VerifierCategory,
        "response.diagnostic.category",
    )
    invariant = _expect_string(
        diagnostic["invariant"], "response.diagnostic.invariant"
    )
    if _INVARIANT_PATTERN.fullmatch(invariant) is None:
        _invalid("response.diagnostic.invariant must have the form IRV-NNN")
    message = _expect_string(
        diagnostic["message"], "response.diagnostic.message"
    )
    context = _expect_mapping(
        diagnostic["context"], "response.diagnostic.context"
    )
    _expect_fields(
        context,
        {
            "function_index",
            "function_name",
            "block_index",
            "block_name",
            "instruction_index",
            "instruction_kind",
        },
        "response.diagnostic.context",
    )
    instruction_kind = _expect_optional_string(
        context["instruction_kind"],
        "response.diagnostic.context.instruction_kind",
    )
    if (
        instruction_kind is not None
        and instruction_kind not in _KNOWN_INSTRUCTION_KINDS
    ):
        _invalid(
            "response.diagnostic.context.instruction_kind has an unknown value"
        )
    return RustVerifierDiagnostic(
        phase=phase,
        category=category,
        invariant=invariant,
        message=message,
        function_index=_expect_optional_index(
            context["function_index"],
            "response.diagnostic.context.function_index",
        ),
        function_name=_expect_optional_string(
            context["function_name"],
            "response.diagnostic.context.function_name",
        ),
        block_index=_expect_optional_index(
            context["block_index"],
            "response.diagnostic.context.block_index",
        ),
        block_name=_expect_optional_string(
            context["block_name"],
            "response.diagnostic.context.block_name",
        ),
        instruction_index=_expect_optional_index(
            context["instruction_index"],
            "response.diagnostic.context.instruction_index",
        ),
        instruction_kind=instruction_kind,
    )


def _expect_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        _invalid(f"{label} must be an object")
    return value


def _expect_fields(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        _invalid(f"{label} has missing or unexpected fields")


def _expect_string(value: object, label: str) -> str:
    if type(value) is not str:
        _invalid(f"{label} must be a string")
    return value


def _expect_optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _expect_string(value, label)


def _expect_optional_index(value: object, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        _invalid(f"{label} must be null or a non-negative integer")
    return value


def _expect_enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    spelling = _expect_string(value, label)
    try:
        return enum_type(spelling)
    except ValueError:
        _invalid(f"{label} has an unknown value")


def _invalid(message: str) -> NoReturn:
    raise RustVerifierInvalidResponse(message)


__all__ = [
    "DEFAULT_RUST_VERIFIER_REQUEST_LIMIT_BYTES",
    "DEFAULT_RUST_VERIFIER_STDERR_LIMIT_BYTES",
    "DEFAULT_RUST_VERIFIER_STDOUT_LIMIT_BYTES",
    "DEFAULT_RUST_VERIFIER_TIMEOUT_SECONDS",
    "RUST_VERIFIER_PROTOCOL_VERSION",
    "SubprocessRustVerifierClient",
    "SubprocessRustVerifierInvocationMetadata",
    "RustVerifierAccepted",
    "RustVerifierAdapterError",
    "RustVerifierCommand",
    "RustVerifierDiagnostic",
    "RustVerifierExecutableNotFound",
    "RustVerifierIntegrationError",
    "RustVerifierInvalidResponse",
    "RustVerifierOutputLimitExceeded",
    "RustVerifierPhase",
    "RustVerifierProcessFailure",
    "RustVerifierProtocolError",
    "RustVerifierProtocolErrorKind",
    "RustVerifierRejected",
    "RustVerifierRequestConstructionError",
    "RustVerifierRequestTooLarge",
    "RustVerifierResult",
    "RustVerifierSpawnFailure",
    "RustVerifierTimeout",
    "RustVerifierTransportMetadata",
    "discover_rust_verifier_executable",
    "verify_module_with_rust",
]
