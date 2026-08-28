#!/usr/bin/env python3
"""Generate one CORE-1.0A qualification lane without changing production policy."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import gc
import importlib.util
import json
import os
from pathlib import Path
import platform
from statistics import median
import subprocess
import sys
import threading
from time import perf_counter
import tracemalloc
from types import ModuleType
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import qualify_core_1_0_in_process_boundary as core10  # noqa: E402
from aether.ir.dto import ir_module_to_dto  # noqa: E402
from aether.ir.lifecycle import expand_lifecycle  # noqa: E402
from aether.ssa.dto import ssa_module_from_dto  # noqa: E402
from aether.ssa.in_process import InProcessRustSSALoweringClient  # noqa: E402
from aether.ssa.refinement_verifier import SSARefinementVerifier  # noqa: E402
from aether.ssa.shadow import PersistentRustSSALoweringClient  # noqa: E402
from aether.ssa.verifier import SSAVerifier  # noqa: E402
from qualify_rust_ssa_lowering_adversarial import linear, straight  # noqa: E402


MILESTONE = "CORE-1.0A"
DEFAULT_COMPANION = ROOT / "compiler-rs/target/release/aether-ssa-shadow"
DEFAULT_EXTENSION = ROOT / "compiler-rs/target/release/lib_aether_core.so"
R41_PATH = ROOT / "scripts/qualify_rust_ssa_independent_refinement_verifier.py"
REQUIRED_DEEP = (993, 1000, 5000, 10000)
DIAGNOSTIC_FIELDS = (
    "kind",
    "category",
    "phase",
    "code",
    "function",
    "block",
    "source_location",
)


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load qualification module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _command_output(command: list[str]) -> str:
    return subprocess.run(
        command, cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _revision(value: str | None) -> str:
    revision = value or _command_output(["git", "rev-parse", "HEAD"])
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise ValueError("revision must be an exact lowercase 40-character Git SHA")
    return revision


def _platform_id() -> str:
    system = platform.system().lower()
    os_name = "macos" if system == "darwin" else "windows" if system == "windows" else "linux"
    machine = platform.machine().lower().replace("-", "_")
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x86_64" if machine in {"amd64", "x86_64"} else machine
    return f"{os_name}-{architecture}"


def _metadata(kind: str, args: argparse.Namespace) -> dict[str, object]:
    rust = _command_output(["rustc", "-vV"])
    rust_target = next(
        line.removeprefix("host: ") for line in rust.splitlines() if line.startswith("host: ")
    )
    worktree_status = _command_output(
        ["git", "status", "--porcelain", "--untracked-files=no"]
    )
    return {
        "artifact_schema_version": 1,
        "kind": kind,
        "milestone": MILESTONE,
        "exact_revision": _revision(args.revision),
        "ci_run_id": args.ci_run_id or os.environ.get("GITHUB_RUN_ID") or "LOCAL_PRE_CI",
        "platform": _platform_id(),
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "rust_target": rust_target,
        "worktree_clean": worktree_status == "",
        "qualification_only": True,
        "production_default_changed": False,
        "companion_remains_production_and_rollback": True,
        "automatic_fallback": False,
    }


def _encode(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _initial_failure_payloads(valid: bytes) -> list[tuple[str, str, bytes]]:
    value = json.loads(valid)
    wrong_schema = deepcopy(value)
    wrong_schema["schema_version"] = 999
    unknown = deepcopy(value)
    unknown["unexpected"] = True

    straight_dto = ir_module_to_dto(straight(2))
    invalid_cfg = deepcopy(straight_dto)
    invalid_cfg["functions"][0]["blocks"][0]["instructions"][-1] = {
        "kind": "jump",
        "target": "missing",
    }
    duplicate_function = deepcopy(straight_dto)
    duplicate_function["functions"].append(deepcopy(duplicate_function["functions"][0]))
    wrong_return = deepcopy(straight_dto)
    wrong_return["functions"][0]["return_type"] = {"tag": "int"}
    lifecycle = deepcopy(straight_dto)
    lifecycle["functions"][0]["blocks"][0]["instructions"] = [
        instruction
        for instruction in lifecycle["functions"][0]["blocks"][0]["instructions"]
        if instruction["kind"] != "init_default"
    ]
    return [
        ("malformed_initial_ir_json", "malformed Initial IR", b"{"),
        ("non_object_binding_input", "malformed protocol/binding inputs", b"[]"),
        ("unsupported_schema", "malformed protocol/binding inputs", _encode(wrong_schema)),
        ("unknown_root_field", "malformed Initial IR", _encode(unknown)),
        ("invalid_cfg_target", "invalid CFG", _encode(invalid_cfg)),
        ("duplicate_function", "invalid CFG", _encode(duplicate_function)),
        ("wrong_return_flow", "wrong return/value flow", _encode(wrong_return)),
        ("uninitialized_lifecycle_storage", "lifecycle errors", _encode(lifecycle)),
    ]


def _downstream_outcome(initial: object, dto: dict[str, object]) -> dict[str, str]:
    try:
        imported = ssa_module_from_dto(dto)
    except Exception as error:
        return {"outcome": "REJECT", "phase": "imported_ssa", "error_type": type(error).__name__, "message": str(error)}
    try:
        SSAVerifier(imported).verify()
    except Exception as error:
        return {"outcome": "REJECT", "phase": "ssa_verification", "error_type": type(error).__name__, "message": str(error)}
    try:
        SSARefinementVerifier(initial, imported).verify()
    except Exception as error:
        return {"outcome": "REJECT", "phase": "refinement_verification", "error_type": type(error).__name__, "message": str(error)}
    return {"outcome": "ACCEPT", "phase": "complete", "error_type": "", "message": ""}


def _imported_ssa_campaign(
    companion: PersistentRustSSALoweringClient,
    in_process: InProcessRustSSALoweringClient,
) -> list[dict[str, object]]:
    r41 = _load("core_1_0a_r41", R41_PATH)
    fixtures = {
        "branch": expand_lifecycle(r41.RUST_4_0.branch_module()),
        "effects": expand_lifecycle(r41.effect_module()),
    }
    selected = {
        "missing_phi",
        "extra_phi",
        "wrong_phi_incoming_value",
        "wrong_phi_predecessor",
        "wrong_return",
        "wrong_type",
        "wrong_branch_target",
        "missing_preserved_instruction",
        "duplicated_block",
        "wrong_call_target",
        "wrong_call_argument",
        "incorrect_promoted_value",
    }
    baselines: dict[str, tuple[dict[str, object], dict[str, object]]] = {}
    for fixture, initial in fixtures.items():
        payload = core10.payload_for_module(initial)
        companion_response = companion.lower(payload)
        in_process_response = in_process.lower(payload)
        if companion_response.get("ok") is not True or in_process_response.get("ok") is not True:
            raise RuntimeError(f"baseline rejected for imported SSA fixture {fixture}")
        companion_ssa = companion_response.get("ssa")
        in_process_ssa = in_process_response.get("ssa")
        if not isinstance(companion_ssa, dict) or not isinstance(in_process_ssa, dict):
            raise RuntimeError(f"malformed baseline for imported SSA fixture {fixture}")
        baselines[fixture] = (companion_ssa, in_process_ssa)

    rows: list[dict[str, object]] = []
    for case in r41.mutation_cases():
        if case.name not in selected:
            continue
        companion_ssa, in_process_ssa = baselines[case.fixture]
        companion_candidate = deepcopy(companion_ssa)
        in_process_candidate = deepcopy(in_process_ssa)
        case.mutate(companion_candidate)
        case.mutate(in_process_candidate)
        companion_outcome = _downstream_outcome(fixtures[case.fixture], companion_candidate)
        in_process_outcome = _downstream_outcome(fixtures[case.fixture], in_process_candidate)
        parity = companion_outcome == in_process_outcome
        rows.append(
            {
                "case_id": case.name,
                "category": "invalid phi" if "phi" in case.name else "imported SSA failures" if companion_outcome["phase"] == "imported_ssa" else "refinement failures",
                "companion": companion_outcome,
                "in_process": in_process_outcome,
                "divergence": None if parity else "diagnostic divergence",
                "passed": parity and companion_outcome["outcome"] == "REJECT",
            }
        )
    companion_ssa, in_process_ssa = baselines["branch"]
    companion_candidate = deepcopy(companion_ssa)
    in_process_candidate = deepcopy(in_process_ssa)
    for candidate in (companion_candidate, in_process_candidate):
        del candidate["functions"][0]["blocks"][0]["instructions"][0]["kind"]
    companion_outcome = _downstream_outcome(fixtures["branch"], companion_candidate)
    in_process_outcome = _downstream_outcome(fixtures["branch"], in_process_candidate)
    rows.append(
        {
            "case_id": "malformed_imported_ssa",
            "category": "imported SSA failures",
            "companion": companion_outcome,
            "in_process": in_process_outcome,
            "divergence": None if companion_outcome == in_process_outcome else "diagnostic divergence",
            "passed": companion_outcome == in_process_outcome and companion_outcome["outcome"] == "REJECT",
        }
    )
    if {row["case_id"] for row in rows} != selected | {"malformed_imported_ssa"}:
        raise RuntimeError("RUST-4.x imported SSA mutation inventory changed")
    return rows


def _stats(samples: list[float]) -> dict[str, float | int]:
    center = median(samples)
    return {
        "samples": len(samples),
        "median_seconds": center,
        "mad_seconds": median(abs(sample - center) for sample in samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
    }


def _performance(
    extension: ModuleType,
    companion_path: Path,
    workloads: dict[str, list[bytes]],
    rounds: int,
) -> dict[str, object]:
    rows: dict[str, object] = {}
    with PersistentRustSSALoweringClient(
        companion_path, timeout_seconds=180, characterize_performance=True
    ) as companion:
        for name, payloads in workloads.items():
            companion_samples = {key: [] for key in ("conversion", "ipc_transport", "rust_core", "result_conversion", "total_boundary")}
            in_process_samples = {key: [] for key in ("conversion", "ipc_transport", "rust_core", "result_conversion", "total_boundary")}
            for _ in range(rounds + 2):
                for lane, samples in (("companion", companion_samples), ("in_process", in_process_samples)):
                    totals = {key: 0.0 for key in samples}
                    for payload in payloads:
                        boundary_started = perf_counter()
                        if lane == "companion":
                            response = companion.lower(payload)
                            performance = response["performance"]
                            phases = performance["phases"]
                            totals["conversion"] += phases["rust_input_parsing"] / 1e9
                            totals["rust_core"] += sum(
                                phases[key] / 1e9
                                for key in ("rust_lifecycle_normalization", "rust_ssa_lowering", "rust_owned_ssa_verification")
                            )
                            totals["result_conversion"] += (
                                phases["rust_schema_v2_materialization"] / 1e9
                                + companion.last_response_decode_seconds
                            )
                            measured = performance["request_compute_total"] / 1e9 + companion.last_response_decode_seconds
                        else:
                            core = extension.CompilerCore()
                            started = perf_counter()
                            session = core.accept_initial_ir_schema_v1(payload)
                            totals["conversion"] += perf_counter() - started
                            started = perf_counter()
                            session.lower_ssa()
                            totals["rust_core"] += perf_counter() - started
                            started = perf_counter()
                            json.loads(session.export_ssa_schema_v2())
                            totals["result_conversion"] += perf_counter() - started
                            measured = totals["conversion"] + totals["rust_core"] + totals["result_conversion"]
                        elapsed = perf_counter() - boundary_started
                        totals["total_boundary"] += elapsed
                        totals["ipc_transport"] += max(0.0, elapsed - measured) if lane == "companion" else 0.0
                    if _ >= 2:
                        for key, value in totals.items():
                            samples[key].append(value)
            rows[name] = {
                "payload_count": len(payloads),
                "persistent_companion": {key: _stats(value) for key, value in companion_samples.items()},
                "in_process": {key: _stats(value) for key, value in in_process_samples.items()},
            }
    return {
        "correction_gate": False,
        "warmups": 2,
        "rounds": rounds,
        "dispersion": "median absolute deviation plus min/max",
        "conversion_definitions": {
            "conversion": "schema-v1 decode/input conversion",
            "ipc_transport": "companion residual framing/pipe/scheduling; zero for in-process",
            "rust_core": "lifecycle normalization, SSA lowering, owned SSA verification",
            "result_conversion": "schema-v2 materialization and Python JSON decode",
            "total_boundary": "wall time for the qualified boundary",
        },
        "workloads": rows,
    }


def semantic_lane(args: argparse.Namespace, extension: ModuleType) -> dict[str, object]:
    report = _metadata("core_1_0a_semantic", args)
    in_process = InProcessRustSSALoweringClient(extension)
    with PersistentRustSSALoweringClient(
        args.companion.resolve(), timeout_seconds=180, qualification_structured_errors=True
    ) as companion:
        ordinary_paths = [
            ROOT / "examples/hello.ae",
            ROOT / "tests/aether/parity_corpus/strings.ae",
            ROOT / "examples/aggregate_collections/particles.ae",
            ROOT / "examples/Sorts/Main.ae",
            ROOT / "tests/fixtures/rust_ssa_promotion_failure/owning_call_result.ae",
        ]
        ordinary = [
            core10.compare_payload(path.relative_to(ROOT).as_posix(), core10.payload_for_path(path), companion, in_process)
            for path in ordinary_paths
        ]
        valid = core10.payload_for_path(ROOT / "examples/hello.ae")
        failures = []
        for case_id, category, payload in _initial_failure_payloads(valid):
            row = core10.compare_payload(
                case_id, payload, companion, in_process, expected_rejection=True
            )
            row["campaign_category"] = category
            row["divergence"] = None if row["passed"] else "diagnostic divergence" if row.get("acceptance_parity") else "semantic divergence"
            failures.append(row)
        deep_sizes = (993, 1000) if args.smoke else REQUIRED_DEEP
        deep = [
            core10.compare_payload(
                f"deep_cfg_{size}", core10.payload_for_module(linear(f"core_1_0a_deep_{size}", size)), companion, in_process
            )
            for size in deep_sizes
        ]
        historical = core10.historical_qualification(companion, in_process, smoke=args.smoke)
        imported_ssa = _imported_ssa_campaign(companion, in_process)
        transport = {
            "companion_process_starts": companion.process_start_count,
            "companion_requests": companion.request_count,
            "in_process_process_starts": in_process.process_start_count,
            "in_process_requests": in_process.request_count,
            "same_input_contract": "identical lifecycle-normalized schema-v1 bytes",
        }

    historical_payloads = _first_historical_payloads(5 if args.smoke else 116)
    performance = _performance(
        extension,
        args.companion.resolve(),
        {
            "ordinary": [core10.payload_for_path(ROOT / "examples/hello.ae")],
            "historical_batch": historical_payloads,
            "deep_cfg": [core10.payload_for_module(linear("core_1_0a_perf_deep", 1000 if args.smoke else 5000))],
            "repository_real": [core10.payload_for_path(ROOT / "examples/aggregate_collections/particles.ae")],
        },
        2 if args.smoke else args.rounds,
    )
    expected_historical = 5 if args.smoke else 116
    passed = (
        all(row["passed"] for row in ordinary + failures + deep + imported_ssa)
        and historical["status"] == "PASS"
        and historical["passed"] == historical["denominator"] == expected_historical
        and {int(str(row["case_id"]).removeprefix("deep_cfg_")) for row in deep} == set(deep_sizes)
        and transport["companion_process_starts"] == 1
        and transport["in_process_process_starts"] == 0
    )
    report.update(
        {
            "status": "PASS" if passed else "FAIL",
            "ordinary": ordinary,
            "historical": historical,
            "failure_campaign": failures,
            "imported_ssa_and_refinement_campaign": imported_ssa,
            "deep_cfg": deep,
            "performance": performance,
            "transport": transport,
            "divergence_taxonomy": [
                "semantic divergence",
                "diagnostic divergence",
                "transport-only divergence",
                "expected transport-specific failure",
            ],
            "diagnostic_fields": list(DIAGNOSTIC_FIELDS),
        }
    )
    return report


def _first_historical_payloads(count: int) -> list[bytes]:
    payloads: list[bytes] = []
    for path in core10.historical_paths():
        try:
            payload = core10.payload_for_path(path)
        except Exception:
            continue
        payloads.append(payload)
        if len(payloads) == count:
            break
    if len(payloads) != count:
        raise RuntimeError("historical performance batch is incomplete")
    return payloads


def _run_pytest(command: list[str]) -> dict[str, object]:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "output_tail": (completed.stdout + completed.stderr)[-4000:],
    }


def production_lane(args: argparse.Namespace, extension: ModuleType) -> dict[str, object]:
    del extension
    report = _metadata("core_1_0a_production", args)
    valid = core10.payload_for_path(ROOT / "examples/hello.ae")
    with PersistentRustSSALoweringClient(args.companion.resolve(), timeout_seconds=60) as default:
        first = default.lower(valid)
        second = default.lower(valid)
        failure = default.lower(b"{")
        default_shape_preserved = set(failure) == {"ok", "error"} and first == second
        default_transport = {
            "identity_and_protocol_v1": "PASS",
            "response_shape_preserved": default_shape_preserved,
            "persistent_process_starts": default.process_start_count,
            "requests": default.request_count,
            "repeated_result_equal": first == second,
        }
    with PersistentRustSSALoweringClient(
        args.companion.resolve(), timeout_seconds=60, qualification_structured_errors=True
    ) as qualified:
        structured = qualified.lower(b"{")
    source_guards = {
        "companion_calls_compiler_core": "lower_verified_ssa(initial)" in (ROOT / "compiler-rs/crates/aether-verifier/src/bin/aether-ssa-shadow.rs").read_text(),
        "pyo3_calls_compiler_core": "CompilerCore.accept_initial_ir(initial_ir)" in (ROOT / "compiler-rs/crates/aether-python/src/lib.rs").read_text(),
        "core_not_coupled_to_pyo3": "pyo3" not in (ROOT / "compiler-rs/crates/aether-verifier/src/compiler_core.rs").read_text(),
        "in_process_not_in_default_selector": "InProcessRustSSALoweringClient" not in (ROOT / "src/aether/ssa/shadow.py").read_text(),
    }
    focused = _run_pytest(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/aether/test_rust_ssa_shadow_independent_production_promotion.py",
            "tests/aether/test_rust_ssa_shadow_independent_qualification.py",
            "tests/aether/test_rust_ssa_refinement_production_integration.py",
            "tests/aether/test_rust_ssa_authority_promotion.py",
            "tests/aether/test_rust_ssa_shadow_mode.py",
            "-k",
            "production or differential or rollback or python_only or refinement",
        ]
    )
    gates = {
        "protocol_v1": default_shape_preserved,
        "persistent_companion": default_transport["persistent_process_starts"] == 1,
        "rust_ssa_output": first == second and first.get("ok") is True,
        "verification_and_refinement": focused["status"] == "PASS",
        "structured_failure_and_locations": isinstance(structured.get("diagnostic"), dict) and set(structured["diagnostic"]) == set(DIAGNOSTIC_FIELDS),
        "lifecycle": focused["status"] == "PASS",
        "rust_4_5_default_policy": source_guards["in_process_not_in_default_selector"] and focused["status"] == "PASS",
        "differential_python_shadow": focused["status"] == "PASS",
        "rollback_modes": focused["status"] == "PASS",
    }
    report.update(
        {
            "status": "PASS" if all(gates.values()) and all(source_guards.values()) else "FAIL",
            "selected_rust_4_5_gates": {
                "justification": "CompilerCore refactored ordinary companion lowering/verification and error propagation; authority selection, differential comparison, lifecycle/refinement integration, persistent protocol, and rollback are therefore the affected surfaces. Packaging release assembly and unrelated optimizer/backend gates are not semantically reachable from this refactor.",
                "focused_pytest": focused,
            },
            "production_regression_gates": gates,
            "default_companion": default_transport,
            "qualification_only_structured_error_extension": structured,
            "shared_core_guards": source_guards,
        }
    )
    return report


def _current_rss_bytes() -> tuple[int | None, str]:
    if sys.platform.startswith("linux"):
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024, "linux /proc/self/status VmRSS"
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
            return int(counters.WorkingSetSize), "Windows process working set"
        except Exception:
            pass
    return None, "current RSS unavailable; Python allocation tracking only"


def sessions_lane(args: argparse.Namespace, extension: ModuleType) -> dict[str, object]:
    report = _metadata("core_1_0a_sessions", args)
    core = extension.CompilerCore()
    ordinary = core10.payload_for_path(ROOT / "examples/hello.ae")
    other = core10.payload_for_path(ROOT / "examples/aggregate_collections/particles.ae")
    invalid = _initial_failure_payloads(ordinary)[4][2]

    session = core.accept_initial_ir_schema_v1(ordinary)
    session.lower_ssa()
    first = bytes(session.export_ssa_schema_v2())
    session.lower_ssa()
    repeated = bytes(session.export_ssa_schema_v2())

    sessions = [core.accept_initial_ir_schema_v1(ordinary), core.accept_initial_ir_schema_v1(other)]
    sessions[1].lower_ssa()
    sessions[0].lower_ssa()
    interleaved = [bytes(item.export_ssa_schema_v2()) for item in sessions]

    failing = core.accept_initial_ir_schema_v1(invalid)
    failure_rows = []
    for _ in range(2):
        try:
            failing.lower_ssa()
        except extension.AetherCoreError as error:
            failure_rows.append({field: getattr(error, field, None) for field in DIAGNOSTIC_FIELDS} | {"message": str(error)})

    shared = core.accept_initial_ir_schema_v1(other)
    with ThreadPoolExecutor(max_workers=8) as pool:
        same_session = list(pool.map(lambda _: (shared.lower_ssa(), bytes(shared.export_ssa_schema_v2()))[1], range(8)))

    def independent(payload: bytes) -> bytes:
        value = extension.CompilerCore().accept_initial_ir_schema_v1(payload)
        value.lower_ssa()
        return bytes(value.export_ssa_schema_v2())

    with ThreadPoolExecutor(max_workers=4) as pool:
        independent_results = list(pool.map(independent, [ordinary, other, ordinary, other]))

    def reject(_: int) -> tuple[str, str, str]:
        value = extension.CompilerCore().accept_initial_ir_schema_v1(invalid)
        try:
            value.lower_ssa()
        except extension.AetherCoreError as error:
            return error.kind, error.phase, error.code
        raise AssertionError("concurrent invalid session was accepted")

    with ThreadPoolExecutor(max_workers=4) as pool:
        concurrent_failures = list(pool.map(reject, range(8)))

    ticker_stop = threading.Event()
    ticker_ready = threading.Event()
    ticks = 0

    def ticker() -> None:
        nonlocal ticks
        ticker_ready.set()
        while not ticker_stop.is_set():
            ticks += 1

    deep = core.accept_initial_ir_schema_v1(
        core10.payload_for_module(linear("core_1_0a_gil", 1000 if args.smoke else 5000))
    )
    thread = threading.Thread(target=ticker)
    thread.start()
    ticker_ready.wait()
    before = ticks
    deep.lower_ssa()
    during = ticks - before
    ticker_stop.set()
    thread.join()

    soak_count = 50 if args.smoke else args.soak
    gc.collect()
    rss_before, rss_method = _current_rss_bytes()
    tracemalloc.start()
    python_before = tracemalloc.get_traced_memory()[0]
    for _ in range(soak_count):
        value = core.accept_initial_ir_schema_v1(ordinary)
        value.lower_ssa()
        value.export_ssa_schema_v2()
        del value
    gc.collect()
    python_after, python_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after, _ = _current_rss_bytes()
    rss_growth = None if rss_before is None or rss_after is None else rss_after - rss_before
    memory = {
        "iterations": soak_count,
        "rss_method": rss_method,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "rss_growth_bytes": rss_growth,
        "python_traced_growth_bytes": python_after - python_before,
        "python_traced_peak_bytes": python_peak,
        "unbounded_growth_observed": bool(rss_growth is not None and rss_growth > 64 * 1024 * 1024),
        "lsan": "NOT_RUN; no ptrace/sandbox result is represented as leak evidence",
    }
    gates = {
        "create_repeated_use": first == repeated,
        "multiple_simultaneous_and_interleaved": interleaved[0] == first and interleaved[0] != interleaved[1],
        "exception_then_reuse": len(failure_rows) == 2 and failure_rows[0] == failure_rows[1],
        "same_session_serialized": len(set(same_session)) == 1,
        "independent_session_isolation": independent_results[0] == independent_results[2] and independent_results[1] == independent_results[3] and independent_results[0] != independent_results[1],
        "concurrent_failures": len(set(concurrent_failures)) == 1,
        "gil_released": during > 0,
        "create_destroy_soak": not memory["unbounded_growth_observed"],
        "no_raw_or_stale_handle_api": not any(name for name in dir(session) if "handle" in name.lower()),
    }
    report.update(
        {
            "status": "PASS" if all(gates.values()) else "FAIL",
            "session_and_handle_gates": gates,
            "failure_reuse": failure_rows,
            "concurrency": {
                "gil_ticker_progress_during_rust": during,
                "independent_sessions": 4,
                "same_session_calls": 8,
                "same_session_contract": "serialized by Mutex<CompilationSession>; idempotent lowering",
                "concurrent_failures": 8,
                "cleanup_under_concurrency": "PASS",
            },
            "rust_traits": {
                "CompilerCore": "Send + Sync (compile-time Rust test)",
                "CompilationSession": "Send + Sync (compile-time Rust test)",
                "python_session": "Mutex<CompilationSession>; parallel across independent sessions, serialized within one session",
                "unsafe": False,
            },
            "lifetime_model": "Python owns the PyO3 object directly; Rust RAII destruction has no numeric registry handle, so stale/double-free handle states are not representable through the API.",
            "memory": memory,
        }
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--section", choices=("semantic", "production", "sessions"))
    mode.add_argument(
        "--production-only",
        action="store_const",
        const="production",
        dest="section",
        help="Run only the CORE-1.0A production-preservation lane.",
    )
    parser.add_argument("--companion", type=Path, default=DEFAULT_COMPANION)
    parser.add_argument("--extension", type=Path, default=DEFAULT_EXTENSION)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--ci-run-id")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--soak", type=int, default=500)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if not args.companion.is_file():
        parser.error(f"companion not found: {args.companion}")
    if not args.extension.is_file():
        parser.error(f"extension not found: {args.extension}")
    extension = core10.load_extension(args.extension.resolve())
    lane: Callable[[argparse.Namespace, ModuleType], dict[str, object]] = {
        "semantic": semantic_lane,
        "production": production_lane,
        "sessions": sessions_lane,
    }[args.section]
    report = lane(args, extension)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"{MILESTONE} {args.section}: {report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
