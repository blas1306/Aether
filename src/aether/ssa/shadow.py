"""Fail-closed dual-lane SSA lowering authority coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
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

from aether.ir.dto import ir_module_to_dto
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
    # RUST-3.6-V2 production default. Rust returns the authoritative schema-v2
    # import only after the mandatory synchronous Python shadow matches.
    mode: SSALoweringAuthorityMode = SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
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
    performance: SSAPerformanceProfile | None = None


@dataclass(frozen=True)
class SSAPerformanceProfile:
    """One observational lowering sample measured with a monotonic clock."""

    mode: str
    clock: str
    phases_seconds: Mapping[str, float]
    measured_component_sum_seconds: float
    residual_unattributed_seconds: float
    total_wall_seconds: float
    rust_phase_detail: str
    rust_ssa_lowering_phases_seconds: Mapping[str, float]
    python_ssa_lowering_phases_seconds: Mapping[str, float]
    python_lifecycle_phases_seconds: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = tuple(self.phases_seconds.values()) + (
            self.measured_component_sum_seconds,
            self.residual_unattributed_seconds,
            self.total_wall_seconds,
        )
        if any(not isinstance(value, (int, float)) or value < 0 for value in values):
            raise ValueError("SSA performance timings must be non-negative numbers")
        phase_sum = sum(self.phases_seconds.values())
        phase_tolerance = max(1e-9, self.measured_component_sum_seconds * 1e-9)
        if abs(phase_sum - self.measured_component_sum_seconds) > phase_tolerance:
            raise ValueError("SSA performance measured component sum is inconsistent")
        accounted = self.measured_component_sum_seconds + self.residual_unattributed_seconds
        tolerance = max(1e-9, self.total_wall_seconds * 1e-9)
        if abs(accounted - self.total_wall_seconds) > tolerance:
            raise ValueError("SSA performance phase totals are inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "clock": self.clock,
            "phases_seconds": dict(self.phases_seconds),
            "measured_component_sum_seconds": self.measured_component_sum_seconds,
            "residual_unattributed_seconds": self.residual_unattributed_seconds,
            "total_wall_seconds": self.total_wall_seconds,
            "rust_phase_detail": self.rust_phase_detail,
            "rust_ssa_lowering_phases_seconds": dict(
                self.rust_ssa_lowering_phases_seconds
            ),
            "python_ssa_lowering_phases_seconds": dict(
                self.python_ssa_lowering_phases_seconds
            ),
            "python_lifecycle_phases_seconds": dict(
                self.python_lifecycle_phases_seconds
            ),
        }


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

    def __init__(
        self,
        executable: str | Path,
        *,
        timeout_seconds: float = 10.0,
        characterize_performance: bool = False,
    ) -> None:
        self.command = (
            (str(executable), "--persistent", "--characterize-performance")
            if characterize_performance
            else (str(executable), "--persistent")
        )
        self.timeout_seconds = timeout_seconds
        self.characterize_performance = characterize_performance
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._starts = 0
        self._requests = 0
        self._last_startup_seconds = 0.0
        self._last_response_decode_seconds = 0.0

    @property
    def process_start_count(self) -> int: return self._starts

    @property
    def request_count(self) -> int: return self._requests

    @property
    def last_startup_seconds(self) -> float:
        return self._last_startup_seconds

    @property
    def last_response_decode_seconds(self) -> float:
        return self._last_response_decode_seconds

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def lower(self, payload: bytes) -> Mapping[str, object]:
        self._last_startup_seconds = 0.0
        self._last_response_decode_seconds = 0.0
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
        decode_started = perf_counter() if self.characterize_performance else 0.0
        try:
            decoded = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.close()
            raise RuntimeError("malformed Rust SSA response") from exc
        if not isinstance(decoded, dict):
            self.close()
            raise RuntimeError("malformed Rust SSA response")
        if self.characterize_performance:
            self._last_response_decode_seconds = perf_counter() - decode_started
        return decoded

    def _start(self) -> subprocess.Popen[bytes]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        started = perf_counter() if self.characterize_performance else 0.0
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
        if self.characterize_performance:
            self._last_startup_seconds = perf_counter() - started
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
    result: dict[str, object] = {}
    for key, value in dto.items():
        if key != "functions":
            result[key] = _canonical_clone(value, {})
            continue
        functions = []
        for function in value:
            names = _canonical_names(function)
            copied = _canonical_clone(function, names)
            _sort_canonical_phi_incoming(copied)
            functions.append(copied)
        result[key] = functions
    return result


def _canonical_names(function: Mapping[str, object]) -> dict[str, str]:
    names: dict[str, str] = {}

    def bind(value: Any) -> None:
        if isinstance(value, dict) and value.get("tag") in {"value", "parameter"}:
            names.setdefault(value["name"], f"v{len(names)}")

    for parameter in function["parameters"]:
        bind(parameter)
    for block in function["blocks"]:
        for instruction in block["instructions"]:
            keys = (
                ("event",)
                if instruction["kind"] == "catch_entry"
                else ("result", "exception")
                if instruction["kind"]
                in {"invoke", "invoke_indirect", "invoke_interface"}
                else ("result",)
            )
            for key in keys:
                bind(instruction.get(key))
    return names


def _canonical_clone(value: Any, names: Mapping[str, str]) -> Any:
    """Clone one JSON-compatible tree while applying its alpha renaming."""
    if isinstance(value, dict):
        renamed = value.get("tag") in {"value", "parameter"} and value.get(
            "name"
        ) in names
        return {
            key: (
                names[child]
                if renamed and key == "name"
                else _canonical_clone(child, names)
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_canonical_clone(child, names) for child in value]
    if isinstance(value, tuple):
        return [_canonical_clone(child, names) for child in value]
    return value


def _sort_canonical_phi_incoming(function: Mapping[str, object]) -> None:
    for block in function["blocks"]:
        for instruction in block["instructions"]:
            if instruction["kind"] == "phi":
                instruction["incoming"].sort(key=lambda item: item["block"])


def _rewrite_canonical_names(value: Any, names: Mapping[str, str]) -> None:
    if isinstance(value, dict):
        if (
            value.get("tag") in {"value", "parameter"}
            and value.get("name") in names
        ):
            value["name"] = names[value["name"]]
        for child in value.values():
            _rewrite_canonical_names(child, names)
    elif isinstance(value, list):
        for child in value:
            _rewrite_canonical_names(child, names)


def _canonicalize_owned_ssa(dto: dict[str, object]) -> dict[str, object]:
    """Canonicalize a newly-created, compilation-local DTO in place."""
    for function in dto["functions"]:
        names = _canonical_names(function)
        _rewrite_canonical_names(function, names)
        _sort_canonical_phi_incoming(function)
    return dto


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


def _finish_performance_profile(
    mode: str,
    phases: dict[str, float],
    total_started: float,
    rust_phase_detail: str,
    rust_ssa_lowering_phases: Mapping[str, float] | None = None,
    python_ssa_lowering_phases: Mapping[str, float] | None = None,
    python_lifecycle_phases: Mapping[str, float] | None = None,
) -> SSAPerformanceProfile:
    total = perf_counter() - total_started
    measured = sum(phases.values())
    # Clock reads and Python coordination are intentionally left as residual.
    # A tiny negative value can arise because the nested Rust clock is rounded
    # to integer nanoseconds; retain internal consistency without inventing a
    # negative phase.
    residual = max(0.0, total - measured)
    if measured > total:
        phases["clock_domain_rounding_adjustment"] = max(
            0.0, phases.get("clock_domain_rounding_adjustment", 0.0) - (measured - total)
        )
        measured = sum(phases.values())
        total = max(total, measured)
        residual = total - measured
    return SSAPerformanceProfile(
        mode=mode,
        clock="time.perf_counter",
        phases_seconds=dict(phases),
        measured_component_sum_seconds=measured,
        residual_unattributed_seconds=residual,
        total_wall_seconds=total,
        rust_phase_detail=rust_phase_detail,
        rust_ssa_lowering_phases_seconds=dict(rust_ssa_lowering_phases or {}),
        python_ssa_lowering_phases_seconds=dict(
            python_ssa_lowering_phases or {}
        ),
        python_lifecycle_phases_seconds=dict(python_lifecycle_phases or {}),
    )


def _rust_phase_timings(
    response: Mapping[str, object],
) -> tuple[dict[str, float], dict[str, float], float] | None:
    """Decode optional diagnostic metadata without affecting compilation."""
    performance = response.get("performance")
    if not isinstance(performance, dict) or performance.get("unit") != "nanoseconds":
        return None
    raw_phases = performance.get("phases")
    raw_lowering_phases = performance.get("ssa_lowering_phases")
    raw_total = performance.get("request_compute_total")
    if (
        not isinstance(raw_phases, dict)
        or not isinstance(raw_total, int)
        or raw_total < 0
    ):
        return None
    expected = {
        "rust_input_parsing",
        "rust_lifecycle_normalization",
        "rust_ssa_lowering",
        "rust_owned_ssa_verification",
        "rust_schema_v2_materialization",
        "rust_orchestration_unattributed",
    }
    if set(raw_phases) != expected or any(
        not isinstance(value, int) or value < 0 for value in raw_phases.values()
    ):
        return None
    expected_lowering = {
        "cfg_construction",
        "reachability_and_rpo",
        "chk_idom",
        "dominator_tree",
        "dominance_frontier",
        "liveness",
        "definite_initialization",
        "phi_placement",
        "renaming",
        "remaining_lowering",
    }
    if raw_lowering_phases is not None and (
        not isinstance(raw_lowering_phases, dict)
        or set(raw_lowering_phases) != expected_lowering
        or any(
            not isinstance(value, int) or value < 0
            for value in raw_lowering_phases.values()
        )
    ):
        return None
    phases = {name: value / 1_000_000_000 for name, value in raw_phases.items()}
    lowering_phases = (
        {
            name: value / 1_000_000_000
            for name, value in raw_lowering_phases.items()
        }
        if isinstance(raw_lowering_phases, dict)
        else {}
    )
    total = raw_total / 1_000_000_000
    if sum(phases.values()) > total + 1e-9:
        return None
    if sum(lowering_phases.values()) > phases["rust_ssa_lowering"] + 1e-9:
        return None
    return phases, lowering_phases, total


def _lower_dual_lane(
    module: IRModule,
    client: RustSSALoweringClient,
    *,
    rust_authoritative: bool,
    characterize_performance: bool = False,
    execute_python_shadow: bool = True,
) -> tuple[object, SSAShadowReport]:
    """Run both qualified lanes and return only the configured authority."""
    total_started = perf_counter() if characterize_performance else 0.0
    phases: dict[str, float] = {}
    started = perf_counter() if characterize_performance else 0.0
    snapshot = ir_module_to_dto(module)
    if characterize_performance:
        phases["initial_ir_snapshot_preparation"] = perf_counter() - started
        started = perf_counter()
    payload = json.dumps(snapshot, separators=(",", ":")).encode()
    if characterize_performance:
        phases["rust_transport_serialization"] = perf_counter() - started

    python_seconds = 0.0
    rust_seconds = 0.0
    rust_phase_detail = "disabled"
    rust_ssa_lowering_phases: dict[str, float] = {}
    python_ssa_lowering_phases: dict[str, float] = {}
    python_lifecycle_phases: dict[str, float] = {}
    rust_comparison_dto: Mapping[str, object] | None = None

    def run_python() -> object:
        nonlocal python_seconds
        try:
            # ``snapshot`` was serialized from this exact verified module for
            # Rust immediately before either lane ran.  GeneralSSABuilder and
            # lifecycle expansion are non-mutating, and the fail-closed DTO
            # equality check below enforces that contract after both lanes.
            # Reuse therefore avoids a redundant JSON decode/schema import
            # while keeping both lanes tied to one logical Initial IR value.
            python_input = module
            lane_started = perf_counter()
            if characterize_performance:
                value = GeneralSSABuilder(
                    performance_timings=phases,
                    phase_timings=python_ssa_lowering_phases,
                    lifecycle_timings=python_lifecycle_phases,
                ).build(python_input)
            else:
                # Keep the production path byte-for-byte recognizable to the
                # stabilization source-contract gate.
                value = GeneralSSABuilder().build(python_input)
            # GeneralSSABuilder returns only after running this same verifier
            # over ``value``.  Nothing can mutate the SSA between that check
            # and this return, so a second identical pass was redundant.
            python_seconds = perf_counter() - lane_started
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
        nonlocal rust_seconds, rust_phase_detail, rust_comparison_dto
        nonlocal rust_ssa_lowering_phases
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
        if characterize_performance:
            detailed = _rust_phase_timings(response)
            if detailed is None:
                phases["rust_transport_and_compute_combined"] = rust_seconds
                rust_phase_detail = "combined: companion did not expose diagnostic phase metadata"
            else:
                rust_phases, rust_ssa_lowering_phases, rust_compute_total = detailed
                phases.update(rust_phases)
                startup = getattr(client, "last_startup_seconds", 0.0)
                response_decode = getattr(client, "last_response_decode_seconds", 0.0)
                startup = startup if isinstance(startup, (int, float)) else 0.0
                response_decode = response_decode if isinstance(response_decode, (int, float)) else 0.0
                phases["companion_process_startup"] = max(0.0, startup)
                phases["response_json_decode"] = max(0.0, response_decode)
                phases["request_response_transport_and_serialization"] = max(
                    0.0,
                    rust_seconds - rust_compute_total - phases["companion_process_startup"]
                    - phases["response_json_decode"],
                )
                rust_phase_detail = (
                    "separated Rust compute; final response byte serialization and IPC are combined"
                )
        if response.get("ok") is not True:
            raise SSAShadowFailure(SSAShadowReport("rust_lowering_or_verifier_failure", "rust_lane",
                                                  first_difference=str(response.get("error", "unspecified failure"))[:240],
                                                  python_seconds=python_seconds, rust_seconds=rust_seconds))
        response_ssa = response.get("ssa")
        if not isinstance(response_ssa, dict):
            raise SSAShadowFailure(SSAShadowReport("malformed_rust_response", "response_decode",
                                                  python_seconds=python_seconds, rust_seconds=rust_seconds))
        rust_comparison_dto = response_ssa
        try:
            started = perf_counter() if characterize_performance else 0.0
            value = ssa_module_from_dto(rust_comparison_dto)
            if characterize_performance:
                phases["rust_schema_v2_import"] = perf_counter() - started
        except Exception as exc:
            raise SSAShadowFailure(SSAShadowReport("malformed_rust_response", "schema_v2_import",
                                                  first_difference=str(exc)[:240], python_seconds=python_seconds,
                                                  rust_seconds=rust_seconds)) from exc
        try:
            started = perf_counter() if characterize_performance else 0.0
            SSAVerifier(value).verify()
            if characterize_performance:
                phases["imported_rust_python_verification"] = perf_counter() - started
        except Exception as exc:
            raise SSAShadowFailure(SSAShadowReport("rust_verifier_failure", "ssa_verification",
                                                  first_difference=str(exc)[:240], python_seconds=python_seconds,
                                                  rust_seconds=rust_seconds)) from exc
        return value

    if rust_authoritative:
        rust_ssa = run_rust()
        if execute_python_shadow:
            python_ssa = run_python()
        else:
            python_ssa = None
    else:
        python_ssa = run_python()
        rust_ssa = run_rust()

    started = perf_counter() if characterize_performance else 0.0
    unchanged = ir_module_to_dto(module) == snapshot
    if characterize_performance:
        phases["input_snapshot_integrity_check"] = perf_counter() - started
    if not unchanged:
        raise SSAShadowFailure(
            SSAShadowReport(
                "same_input_violation",
                "input_snapshot",
                python_seconds=python_seconds,
                rust_seconds=rust_seconds,
            )
        )

    if not execute_python_shadow:
        performance = _finish_performance_profile(
            "diagnostic_rust_authority_without_python_shadow",
            phases,
            total_started,
            rust_phase_detail,
            rust_ssa_lowering_phases,
            python_ssa_lowering_phases,
            python_lifecycle_phases,
        )
        return rust_ssa, SSAShadowReport(
            "diagnostic_rust_only",
            "diagnostic_only_not_production",
            rust_seconds=rust_seconds,
            performance=performance,
        )

    assert python_ssa is not None
    try:
        # The received schema-v2 DTO has already crossed the strict importer
        # and independent Python verifier boundaries.  Canonicalization makes
        # its own deep copy, so reusing it for this compilation cannot mutate
        # transport state or leak across requests.
        assert rust_comparison_dto is not None
        rust_dto = rust_comparison_dto
        started = perf_counter() if characterize_performance else 0.0
        python_dto = ssa_module_to_dto(python_ssa, schema_version=2)
        if characterize_performance:
            phases["python_result_dto_serialization"] = perf_counter() - started
        comparison_started = perf_counter()
        started = comparison_started
        # ``python_dto`` was just allocated for this comparison and is not
        # observable elsewhere.  Canonicalizing it in place avoids an entire
        # JSON encode/decode copy without sharing mutable state.
        python_canonical = _canonicalize_owned_ssa(python_dto)
        if characterize_performance:
            phases["python_result_canonicalization"] = perf_counter() - started
            started = perf_counter()
        rust_canonical = canonical_ssa(rust_dto)
        if characterize_performance:
            phases["rust_result_canonicalization"] = perf_counter() - started
        started = perf_counter()
        difference = _difference(python_canonical, rust_canonical)
        if characterize_performance:
            phases["canonical_comparison"] = perf_counter() - started
        compare = perf_counter() - comparison_started
    except Exception as exc:
        raise SSAShadowFailure(SSAShadowReport("canonicalization_failure", "canonicalization",
                                              first_difference=str(exc)[:240], python_seconds=python_seconds,
                                              rust_seconds=rust_seconds)) from exc
    if difference:
        path, py, rust = difference
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
    performance = (
        _finish_performance_profile(
            "rust_authority_python_shadow" if rust_authoritative else "python_authority_rust_shadow",
            phases,
            total_started,
            rust_phase_detail,
            rust_ssa_lowering_phases,
            python_ssa_lowering_phases,
            python_lifecycle_phases,
        )
        if characterize_performance
        else None
    )
    return authoritative, SSAShadowReport("match", "canonical_comparison", python_seconds=python_seconds,
                                          rust_seconds=rust_seconds, comparison_seconds=compare,
                                          performance=performance)


def lower_with_rust_shadow(
    module: IRModule,
    client: RustSSALoweringClient,
    *,
    characterize_performance: bool = False,
) -> tuple[object, SSAShadowReport]:
    """Return verified Python SSA after a synchronous verified Rust match."""
    return _lower_dual_lane(
        module,
        client,
        rust_authoritative=False,
        characterize_performance=characterize_performance,
    )


def lower_with_rust_authority(
    module: IRModule,
    client: RustSSALoweringClient,
    *,
    characterize_performance: bool = False,
) -> tuple[object, SSAShadowReport]:
    """Return imported Rust SSA only after its Python shadow matches."""
    return _lower_dual_lane(
        module,
        client,
        rust_authoritative=True,
        characterize_performance=characterize_performance,
    )


def diagnostic_lower_with_rust_authority_without_python_shadow(
    module: IRModule,
    client: RustSSALoweringClient,
) -> tuple[object, SSAShadowReport]:
    """Characterize the Rust lane without creating a production authority mode.

    This entry point is intentionally diagnostic and always instrumented.  The
    production configuration enum cannot select it, so mandatory synchronous
    Python shadowing and fail-closed behavior remain unchanged.
    """
    return _lower_dual_lane(
        module,
        client,
        rust_authoritative=True,
        characterize_performance=True,
        execute_python_shadow=False,
    )
