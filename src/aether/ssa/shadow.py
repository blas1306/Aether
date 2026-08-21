"""Fail-closed dual-lane SSA lowering authority coordination."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, unique
import atexit
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
from hashlib import sha256
from time import perf_counter
from typing import Any, Mapping, Protocol

from aether.ir.dto import IR_SCHEMA_VERSION

from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.ir.model import IRModule

from .dto import ssa_module_from_dto, ssa_module_to_dto
from .general_builder import GeneralSSABuilder
from .verifier import SSAVerifier


SSA_SHADOW_PROTOCOL_VERSION = 1
SSA_SHADOW_SCHEMA_VERSION = 2
SSA_SHADOW_PRODUCT_VERSION = "0.1.0"
SSA_SHADOW_PACKAGE_MANIFEST_SCHEMA_VERSION = 1
SSA_SHADOW_CAPABILITIES = ("lower_verified_ssa_shadow",)
_SSA_SHADOW_BASENAME = "aether-ssa-shadow"
RUST_SSA_QUALIFICATION_EXECUTABLE_ENV = (
    "AETHER_INTERNAL_RUST_SSA_QUALIFICATION_EXECUTABLE"
)

_SSA_SHADOW_PLATFORMS = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "windows-x86_64": "x86_64-pc-windows-msvc",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
}


@unique
class SSALoweringAuthorityMode(str, Enum):
    PYTHON_SSA_ONLY = "python_ssa_only"
    PYTHON_SSA_AUTHORITY_RUST_SHADOW = "python_ssa_authority_rust_shadow"
    RUST_SSA_AUTHORITY_PYTHON_SHADOW = "rust_ssa_authority_python_shadow"


@unique
class SSAShadowFailurePolicy(str, Enum):
    FAIL_CLOSED = "fail_closed"
    OBSERVE = "observe"


@dataclass(frozen=True)
class SSALoweringAuthorityConfiguration:
    # RUST-3.6a safe default after the failed authority promotion.  Rust
    # authority remains an explicit, fail-closed qualification selection.
    mode: SSALoweringAuthorityMode = SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW
    failure_policy: SSAShadowFailurePolicy = SSAShadowFailurePolicy.FAIL_CLOSED
    protocol_version: int = SSA_SHADOW_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.mode, SSALoweringAuthorityMode):
            raise TypeError("mode must be an SSALoweringAuthorityMode")
        if not isinstance(self.failure_policy, SSAShadowFailurePolicy):
            raise TypeError("failure_policy must be an SSAShadowFailurePolicy")
        if self.protocol_version != SSA_SHADOW_PROTOCOL_VERSION:
            raise ValueError("only SSA shadow protocol version 1 is supported")
        if (
            self.mode is SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
            and self.failure_policy is not SSAShadowFailurePolicy.FAIL_CLOSED
        ):
            raise ValueError("Rust SSA authority requires fail-closed semantics")


@dataclass(frozen=True)
class SSAShadowReport:
    classification: str
    phase: str
    function: str | None = None
    block: str | None = None
    first_difference: str | None = None
    python_fragment: str | None = None
    rust_fragment: str | None = None
    source_location: object | None = None
    python_seconds: float = 0.0
    rust_seconds: float = 0.0
    comparison_seconds: float = 0.0


class SSAShadowFailure(RuntimeError):
    def __init__(self, report: SSAShadowReport):
        self.report = report
        super().__init__(json.dumps(report.__dict__, sort_keys=True, default=str))


class RustSSALoweringClient(Protocol):
    @property
    def process_start_count(self) -> int: ...
    @property
    def request_count(self) -> int: ...
    def lower(self, payload: bytes) -> Mapping[str, object]: ...


class PersistentRustSSALoweringClient:
    """Synchronized length-framed companion; one process serves many requests."""

    def __init__(self, executable: str | Path, *, timeout_seconds: float = 10.0) -> None:
        self.command = (str(executable), "--persistent")
        self.timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._starts = 0
        self._requests = 0

    @property
    def process_start_count(self) -> int: return self._starts

    @property
    def request_count(self) -> int: return self._requests

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def lower(self, payload: bytes) -> Mapping[str, object]:
        with self._lock:
            process = self._start()
            assert process.stdin is not None
            try:
                process.stdin.write(len(payload).to_bytes(4, "big") + payload)
                process.stdin.flush()
                response = self._read_frame(process)
                self._requests += 1
            except Exception:
                self.close()
                raise
        try:
            decoded = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.close()
            raise RuntimeError("malformed Rust SSA response") from exc
        if not isinstance(decoded, dict):
            self.close()
            raise RuntimeError("malformed Rust SSA response")
        return decoded

    def _start(self) -> subprocess.Popen[bytes]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        try:
            self._process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE, shell=False)
        except OSError as exc:
            raise RuntimeError("Rust SSA companion startup failure") from exc
        self._starts += 1
        identity = self._read_frame(self._process)
        try:
            value = json.loads(identity)
            valid = value == {
                "product": _SSA_SHADOW_BASENAME,
                "product_version": SSA_SHADOW_PRODUCT_VERSION,
                "protocol_version": SSA_SHADOW_PROTOCOL_VERSION,
                "input_schema_version": IR_SCHEMA_VERSION,
                "output_schema_version": SSA_SHADOW_SCHEMA_VERSION,
            }
        except (UnicodeDecodeError, json.JSONDecodeError):
            valid = False
        if not valid:
            self.close()
            raise RuntimeError("incompatible Rust SSA companion identity")
        return self._process

    def _read_frame(self, process: subprocess.Popen[bytes]) -> bytes:
        assert process.stdout is not None
        result: queue.Queue[bytes | BaseException] = queue.Queue(maxsize=1)
        def read() -> None:
            try:
                header = process.stdout.read(4)
                if len(header) != 4: raise EOFError("truncated frame header")
                length = int.from_bytes(header, "big")
                if length > 64 * 1024 * 1024: raise ValueError("response exceeds limit")
                body = process.stdout.read(length)
                if len(body) != length: raise EOFError("truncated frame")
                result.put(body)
            except BaseException as exc: result.put(exc)
        threading.Thread(target=read, daemon=True).start()
        try: value = result.get(timeout=self.timeout_seconds)
        except queue.Empty:
            self.close()
            raise TimeoutError("Rust SSA shadow request timed out") from None
        if isinstance(value, BaseException):
            self.close()
            raise RuntimeError("Rust SSA companion transport failure") from value
        return value

    def close(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            process.terminate()
            try: process.wait(timeout=1)
            except subprocess.TimeoutExpired: process.kill(); process.wait()

    def __enter__(self) -> PersistentRustSSALoweringClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class ProductionRustSSALoweringClient:
    """Lazily use the strictly packaged production companion.

    The package is selected only from the canonical installation prefix.  No
    PATH, checkout, Cargo target-directory, or debug-binary fallback exists.
    """

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._client: PersistentRustSSALoweringClient | None = None
        self._lock = threading.Lock()

    @staticmethod
    def package_directory() -> Path:
        return Path(sys.prefix) / "libexec" / "aether" / "ssa-shadow"

    @property
    def process_start_count(self) -> int:
        return self._client.process_start_count if self._client is not None else 0

    @property
    def request_count(self) -> int:
        return self._client.request_count if self._client is not None else 0

    def lower(self, payload: bytes) -> Mapping[str, object]:
        with self._lock:
            if self._client is None:
                executable = discover_packaged_rust_ssa_shadow(self.package_directory())
                self._client = PersistentRustSSALoweringClient(
                    executable,
                    timeout_seconds=self.timeout_seconds,
                )
            client = self._client
        return client.lower(payload)

    def close(self) -> None:
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            client.close()


_PRODUCTION_RUST_SSA_CLIENT = ProductionRustSSALoweringClient()
atexit.register(_PRODUCTION_RUST_SSA_CLIENT.close)

_QUALIFICATION_RUST_SSA_CLIENTS: dict[Path, PersistentRustSSALoweringClient] = {}
_QUALIFICATION_RUST_SSA_CLIENTS_LOCK = threading.Lock()


def _close_qualification_rust_ssa_clients() -> None:
    with _QUALIFICATION_RUST_SSA_CLIENTS_LOCK:
        clients = tuple(_QUALIFICATION_RUST_SSA_CLIENTS.values())
        _QUALIFICATION_RUST_SSA_CLIENTS.clear()
    for client in clients:
        client.close()


atexit.register(_close_qualification_rust_ssa_clients)


def production_rust_ssa_lowering_client() -> ProductionRustSSALoweringClient:
    """Return the process-wide persistent production companion client."""
    return _PRODUCTION_RUST_SSA_CLIENT


def default_rust_ssa_lowering_client() -> RustSSALoweringClient:
    """Select the production client unless a test qualification propagated one.

    The internal environment override is installed only by the pytest
    qualification harness.  It is deliberately an exact absolute executable,
    not a production discovery path or fallback.
    """
    raw_executable = os.environ.get(RUST_SSA_QUALIFICATION_EXECUTABLE_ENV)
    if raw_executable is None:
        return production_rust_ssa_lowering_client()
    executable = Path(raw_executable)
    if not executable.is_absolute():
        raise RuntimeError(
            "Rust SSA qualification executable must be an absolute path"
        )
    with _QUALIFICATION_RUST_SSA_CLIENTS_LOCK:
        client = _QUALIFICATION_RUST_SSA_CLIENTS.get(executable)
        if client is None:
            client = PersistentRustSSALoweringClient(executable)
            _QUALIFICATION_RUST_SSA_CLIENTS[executable] = client
        return client


def canonical_rust_ssa_shadow_platform_id(
    os_name: str | None = None, architecture: str | None = None,
) -> str:
    """Return the canonical ID used by native companion artifacts."""
    import platform
    import sys
    raw_os = (os_name or sys.platform).lower()
    public_os = "windows" if raw_os.startswith(("win", "mingw")) else "macos" if raw_os in {"darwin", "macos"} else "linux" if raw_os.startswith("linux") else raw_os
    aliases = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}
    try:
        public_architecture = aliases[(architecture or platform.machine()).lower().replace("-", "_")]
    except KeyError:
        raise RuntimeError("unsupported Rust SSA companion architecture") from None
    platform_id = f"{public_os}-{public_architecture}"
    if platform_id not in _SSA_SHADOW_PLATFORMS:
        raise RuntimeError(f"unsupported Rust SSA companion platform: {platform_id}")
    return platform_id


def rust_ssa_shadow_artifact_name(platform_id: str) -> str:
    if platform_id not in _SSA_SHADOW_PLATFORMS:
        raise ValueError(f"unsupported Rust SSA companion platform: {platform_id}")
    extension = "zip" if platform_id.startswith("windows-") else "tar.gz"
    return f"{_SSA_SHADOW_BASENAME}-{SSA_SHADOW_PRODUCT_VERSION}-{platform_id}.{extension}"


def rust_ssa_shadow_package_manifest(
    executable: str | os.PathLike[str], *, platform_id: str | None = None,
) -> dict[str, object]:
    """Create the canonical manifest for one inspected release companion."""
    path = Path(executable).resolve()
    if not path.is_file():
        raise FileNotFoundError("Rust SSA companion executable was not found")
    expected_platform = platform_id or canonical_rust_ssa_shadow_platform_id()
    expected_name = _SSA_SHADOW_BASENAME + (".exe" if expected_platform.startswith("windows-") else "")
    if path.name != expected_name:
        raise ValueError(f"expected canonical executable name {expected_name}")
    with PersistentRustSSALoweringClient(path) as client:
        client._start()
    digest = sha256(path.read_bytes()).hexdigest()
    return {
        "manifest_schema_version": SSA_SHADOW_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "product": _SSA_SHADOW_BASENAME,
        "product_version": SSA_SHADOW_PRODUCT_VERSION,
        "protocol_version": SSA_SHADOW_PROTOCOL_VERSION,
        "supported_input_schema_versions": [IR_SCHEMA_VERSION],
        "supported_output_schema_versions": [SSA_SHADOW_SCHEMA_VERSION],
        "capabilities": list(SSA_SHADOW_CAPABILITIES),
        "platform": expected_platform,
        "architecture": expected_platform.rsplit("-", 1)[1],
        "binary": expected_name,
        "build_profile": "release",
        "sha256": digest,
        "identity": {
            "product": _SSA_SHADOW_BASENAME,
            "product_version": SSA_SHADOW_PRODUCT_VERSION,
            "protocol_version": SSA_SHADOW_PROTOCOL_VERSION,
            "input_schema_version": IR_SCHEMA_VERSION,
            "output_schema_version": SSA_SHADOW_SCHEMA_VERSION,
        },
    }


def discover_packaged_rust_ssa_shadow(
    package_directory: str | os.PathLike[str], *, expected_platform: str | None = None,
) -> Path:
    """Validate and resolve a companion package without PATH/checkout fallback."""
    directory = Path(package_directory).expanduser().resolve()
    try:
        raw = (directory / "manifest.json").read_bytes()
    except FileNotFoundError:
        raise FileNotFoundError("packaged Rust SSA companion manifest was not found") from None
    if len(raw) > 64 * 1024:
        raise RuntimeError("Rust SSA companion manifest exceeds 65536 bytes")
    try:
        manifest = json.loads(raw)
        required = {"manifest_schema_version", "product", "product_version", "protocol_version",
                    "supported_input_schema_versions", "supported_output_schema_versions", "capabilities",
                    "platform", "architecture", "binary", "build_profile", "sha256", "identity"}
        if not isinstance(manifest, dict) or set(manifest) != required:
            raise ValueError("fields")
        platform_id = expected_platform or canonical_rust_ssa_shadow_platform_id()
        expected_name = _SSA_SHADOW_BASENAME + (".exe" if platform_id.startswith("windows-") else "")
        expected_identity = {"product": _SSA_SHADOW_BASENAME, "product_version": SSA_SHADOW_PRODUCT_VERSION,
                             "protocol_version": SSA_SHADOW_PROTOCOL_VERSION, "input_schema_version": IR_SCHEMA_VERSION,
                             "output_schema_version": SSA_SHADOW_SCHEMA_VERSION}
        valid = (manifest["manifest_schema_version"] == SSA_SHADOW_PACKAGE_MANIFEST_SCHEMA_VERSION
                 and manifest["product"] == _SSA_SHADOW_BASENAME
                 and manifest["product_version"] == SSA_SHADOW_PRODUCT_VERSION
                 and manifest["protocol_version"] == SSA_SHADOW_PROTOCOL_VERSION
                 and manifest["supported_input_schema_versions"] == [IR_SCHEMA_VERSION]
                 and manifest["supported_output_schema_versions"] == [SSA_SHADOW_SCHEMA_VERSION]
                 and manifest["capabilities"] == list(SSA_SHADOW_CAPABILITIES)
                 and manifest["platform"] == platform_id and manifest["binary"] == expected_name
                 and manifest["build_profile"] == "release" and manifest["identity"] == expected_identity
                 and isinstance(manifest["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"]))
        if not valid:
            raise ValueError("contract")
    except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        raise RuntimeError("Rust SSA companion package manifest is invalid") from exc
    path = directory / str(manifest["binary"])
    if not path.is_file():
        raise FileNotFoundError("packaged Rust SSA companion was not found")
    if sha256(path.read_bytes()).hexdigest() != manifest["sha256"]:
        raise RuntimeError("Rust SSA companion checksum mismatch")
    if not platform_id.startswith("windows-") and not os.access(path, os.X_OK):
        raise PermissionError("packaged Rust SSA companion is not executable")
    # Runtime identity is checked again by PersistentRustSSALoweringClient at use.
    return path


def canonical_ssa(dto: Mapping[str, object]) -> dict[str, object]:
    """Qualified alpha-normalization retaining every schema-v2 semantic field."""
    result = json.loads(json.dumps(dto))
    for function in result["functions"]:
        names: dict[str, str] = {}
        def bind(value: Any) -> None:
            if isinstance(value, dict) and value.get("tag") in {"value", "parameter"}:
                names.setdefault(value["name"], f"v{len(names)}")
        for parameter in function["parameters"]: bind(parameter)
        for block in function["blocks"]:
            for instruction in block["instructions"]:
                keys = (("event",) if instruction["kind"] == "catch_entry" else
                        ("result", "exception") if instruction["kind"] in {"invoke", "invoke_indirect", "invoke_interface"}
                        else ("result",))
                for key in keys: bind(instruction.get(key))
        def rewrite(value: Any) -> None:
            if isinstance(value, dict):
                if value.get("tag") in {"value", "parameter"} and value.get("name") in names:
                    value["name"] = names[value["name"]]
                for child in value.values(): rewrite(child)
            elif isinstance(value, list):
                for child in value: rewrite(child)
        rewrite(function)
        for block in function["blocks"]:
            for instruction in block["instructions"]:
                if instruction["kind"] == "phi": instruction["incoming"].sort(key=lambda item: item["block"])
    return result


def _difference(left: Any, right: Any, path: str = "$") -> tuple[str, Any, Any] | None:
    if type(left) is not type(right): return (path, left, right)
    if isinstance(left, dict):
        if left.keys() != right.keys(): return (path, sorted(left), sorted(right))
        for key in left:
            found = _difference(left[key], right[key], f"{path}.{key}")
            if found: return found
    elif isinstance(left, list):
        if len(left) != len(right): return (path, f"length={len(left)}", f"length={len(right)}")
        for index, pair in enumerate(zip(left, right)):
            found = _difference(*pair, f"{path}[{index}]")
            if found: return found
    elif left != right: return (path, left, right)
    return None


def _lower_dual_lane(
    module: IRModule,
    client: RustSSALoweringClient,
    *,
    rust_authoritative: bool,
) -> tuple[object, SSAShadowReport]:
    """Run both qualified lanes and return only the configured authority."""
    snapshot = ir_module_to_dto(module)
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()

    python_seconds = 0.0
    rust_seconds = 0.0

    def run_python() -> object:
        nonlocal python_seconds
        try:
            # Both lanes consume representations derived from these exact
            # bytes.  The frontend and Initial IR lowering never run twice.
            python_input = ir_module_from_dto(json.loads(payload))
            started = perf_counter()
            value = GeneralSSABuilder().build(python_input)
            SSAVerifier(value).verify()
            python_seconds = perf_counter() - started
            return value
        except Exception as exc:
            role = "shadow" if rust_authoritative else "authority"
            raise SSAShadowFailure(
                SSAShadowReport(
                    f"python_{role}_failure",
                    "python_lane",
                    first_difference=str(exc)[:240],
                    python_seconds=python_seconds,
                    rust_seconds=rust_seconds,
                )
            ) from exc

    def run_rust() -> object:
        nonlocal rust_seconds
        try:
            started = perf_counter()
            response = client.lower(payload)
            rust_seconds = perf_counter() - started
        except Exception as exc:
            classification = "timeout" if isinstance(exc, TimeoutError) else "rust_infrastructure_failure"
            raise SSAShadowFailure(
                SSAShadowReport(
                    classification,
                    "transport",
                    first_difference=str(exc)[:240],
                    python_seconds=python_seconds,
                )
            ) from exc
        if response.get("ok") is not True:
            raise SSAShadowFailure(SSAShadowReport("rust_lowering_or_verifier_failure", "rust_lane",
                                                  first_difference=str(response.get("error", "unspecified failure"))[:240],
                                                  python_seconds=python_seconds, rust_seconds=rust_seconds))
        if not isinstance(response.get("ssa"), dict):
            raise SSAShadowFailure(SSAShadowReport("malformed_rust_response", "response_decode",
                                                  python_seconds=python_seconds, rust_seconds=rust_seconds))
        try:
            value = ssa_module_from_dto(response["ssa"])
        except Exception as exc:
            raise SSAShadowFailure(SSAShadowReport("malformed_rust_response", "schema_v2_import",
                                                  first_difference=str(exc)[:240], python_seconds=python_seconds,
                                                  rust_seconds=rust_seconds)) from exc
        try:
            SSAVerifier(value).verify()
        except Exception as exc:
            raise SSAShadowFailure(SSAShadowReport("rust_verifier_failure", "ssa_verification",
                                                  first_difference=str(exc)[:240], python_seconds=python_seconds,
                                                  rust_seconds=rust_seconds)) from exc
        return value

    if rust_authoritative:
        rust_ssa = run_rust()
        python_ssa = run_python()
    else:
        python_ssa = run_python()
        rust_ssa = run_rust()
    if ir_module_to_dto(module) != snapshot:
        raise SSAShadowFailure(
            SSAShadowReport(
                "same_input_violation",
                "input_snapshot",
                python_seconds=python_seconds,
                rust_seconds=rust_seconds,
            )
        )
    try:
        rust_dto = ssa_module_to_dto(rust_ssa, schema_version=2)
        python_dto = ssa_module_to_dto(python_ssa, schema_version=2)
        started = perf_counter(); python_canonical = canonical_ssa(python_dto); rust_canonical = canonical_ssa(rust_dto)
        difference = _difference(python_canonical, rust_canonical); compare = perf_counter() - started
    except Exception as exc:
        raise SSAShadowFailure(SSAShadowReport("canonicalization_failure", "canonicalization",
                                              first_difference=str(exc)[:240], python_seconds=python_seconds,
                                              rust_seconds=rust_seconds)) from exc
    if difference:
        path, py, rust = difference
        import re
        function_match = re.search(r"functions\[(\d+)\]", path)
        block_match = re.search(r"blocks\[(\d+)\]", path)
        function_index = int(function_match.group(1)) if function_match else None
        block_index = int(block_match.group(1)) if block_match else None
        function_value = python_canonical["functions"][function_index] if function_index is not None else None
        block_value = function_value["blocks"][block_index] if function_value is not None and block_index is not None else None
        function = function_value.get("name") if isinstance(function_value, dict) else None
        block = block_value.get("name") if isinstance(block_value, dict) else None
        location_match = re.search(r"instructions\[(\d+)\]", path)
        location = None
        if isinstance(block_value, dict) and location_match:
            instruction = block_value["instructions"][int(location_match.group(1))]
            location = instruction.get("source_location") if isinstance(instruction, dict) else None
        raise SSAShadowFailure(SSAShadowReport("semantic_mismatch", "canonical_comparison", function, block,
                                              path, repr(py)[:240], repr(rust)[:240], location,
                                              python_seconds=python_seconds, rust_seconds=rust_seconds,
                                              comparison_seconds=compare))
    authoritative = rust_ssa if rust_authoritative else python_ssa
    return authoritative, SSAShadowReport("match", "canonical_comparison", python_seconds=python_seconds,
                                          rust_seconds=rust_seconds, comparison_seconds=compare)


def lower_with_rust_shadow(
    module: IRModule,
    client: RustSSALoweringClient,
) -> tuple[object, SSAShadowReport]:
    """Return verified Python SSA after a synchronous verified Rust match."""
    return _lower_dual_lane(module, client, rust_authoritative=False)


def lower_with_rust_authority(
    module: IRModule,
    client: RustSSALoweringClient,
) -> tuple[object, SSAShadowReport]:
    """Return imported Rust SSA only after its Python shadow matches."""
    return _lower_dual_lane(module, client, rust_authoritative=True)
