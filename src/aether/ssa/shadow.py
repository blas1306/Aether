"""Python-authority/Rust-shadow SSA lowering coordination (RUST-3.3)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, unique
import json
from pathlib import Path
import queue
import subprocess
import threading
from time import perf_counter
from typing import Any, Mapping, Protocol

from aether.ir.dto import ir_module_to_dto
from aether.ir.model import IRModule

from .dto import ssa_module_from_dto, ssa_module_to_dto
from .general_builder import GeneralSSABuilder
from .verifier import SSAVerifier


@unique
class SSALoweringAuthorityMode(str, Enum):
    PYTHON_SSA_ONLY = "python_ssa_only"
    PYTHON_SSA_AUTHORITY_RUST_SHADOW = "python_ssa_authority_rust_shadow"


@unique
class SSAShadowFailurePolicy(str, Enum):
    FAIL_CLOSED = "fail_closed"
    OBSERVE = "observe"


@dataclass(frozen=True)
class SSALoweringAuthorityConfiguration:
    mode: SSALoweringAuthorityMode = SSALoweringAuthorityMode.PYTHON_SSA_ONLY
    failure_policy: SSAShadowFailurePolicy = SSAShadowFailurePolicy.FAIL_CLOSED
    protocol_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.mode, SSALoweringAuthorityMode):
            raise TypeError("mode must be an SSALoweringAuthorityMode")
        if not isinstance(self.failure_policy, SSAShadowFailurePolicy):
            raise TypeError("failure_policy must be an SSAShadowFailurePolicy")
        if self.protocol_version != 1:
            raise ValueError("only SSA shadow protocol version 1 is supported")


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

    def lower(self, payload: bytes) -> Mapping[str, object]:
        with self._lock:
            process = self._start()
            assert process.stdin is not None
            process.stdin.write(len(payload).to_bytes(4, "big") + payload)
            process.stdin.flush()
            response = self._read_frame(process)
            self._requests += 1
        try:
            decoded = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.close()
            raise RuntimeError("malformed Rust SSA response") from exc
        if not isinstance(decoded, dict):
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
            valid = value == {"product": "aether-ssa-shadow", "protocol_version": 1}
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


def lower_with_rust_shadow(module: IRModule, client: RustSSALoweringClient) -> tuple[object, SSAShadowReport]:
    """Return only Python SSA, or fail closed with a bounded structured report."""
    snapshot = ir_module_to_dto(module)
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    started = perf_counter(); python_ssa = GeneralSSABuilder().build(module); python_seconds = perf_counter() - started
    if ir_module_to_dto(module) != snapshot:
        raise SSAShadowFailure(SSAShadowReport("same_input_violation", "input_snapshot"))
    try:
        started = perf_counter(); response = client.lower(payload); rust_seconds = perf_counter() - started
    except Exception as exc:
        classification = "timeout" if isinstance(exc, TimeoutError) else "rust_infrastructure_failure"
        raise SSAShadowFailure(SSAShadowReport(classification, "transport", first_difference=str(exc)[:240],
                                              python_seconds=python_seconds)) from exc
    if response.get("ok") is not True:
        raise SSAShadowFailure(SSAShadowReport("rust_lowering_or_verifier_failure", "rust_lane",
                                              first_difference=str(response.get("error", "unspecified failure"))[:240],
                                              python_seconds=python_seconds, rust_seconds=rust_seconds))
    if not isinstance(response.get("ssa"), dict):
        raise SSAShadowFailure(SSAShadowReport("malformed_rust_response", "response_decode",
                                              python_seconds=python_seconds, rust_seconds=rust_seconds))
    try:
        rust_ssa = ssa_module_from_dto(response["ssa"])
    except Exception as exc:
        raise SSAShadowFailure(SSAShadowReport("malformed_rust_response", "schema_v2_import",
                                              first_difference=str(exc)[:240], python_seconds=python_seconds,
                                              rust_seconds=rust_seconds)) from exc
    try:
        SSAVerifier(rust_ssa).verify()
    except Exception as exc:
        raise SSAShadowFailure(SSAShadowReport("rust_verifier_failure", "ssa_verification",
                                              first_difference=str(exc)[:240], python_seconds=python_seconds,
                                              rust_seconds=rust_seconds)) from exc
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
    return python_ssa, SSAShadowReport("match", "canonical_comparison", python_seconds=python_seconds,
                                      rust_seconds=rust_seconds, comparison_seconds=compare)
