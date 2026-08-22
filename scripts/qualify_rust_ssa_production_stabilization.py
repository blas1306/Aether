#!/usr/bin/env python3
"""Produce RUST-3.7a corpus, repeated-soak, long-session, and concurrency evidence."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from time import perf_counter
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.pipeline import IRBackend, parse_source, prepare_typed_program  # noqa: E402
from aether.ssa.dto import ssa_module_to_dto  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    SSAShadowFailure,
    canonical_ssa,
    lower_with_rust_authority,
)
from aether.typechecker import TypeChecker  # noqa: E402


DEFAULT_EXECUTABLE = ROOT / "compiler-rs/target/debug/aether-ssa-shadow"
DISCOVERY_ROOTS = ("examples", "benchmarks", "corpus", "tests", "scrap")
MINIMUM_LONG_SESSION_REQUESTS = 5_000
MINIMUM_REPEATED_ROUNDS = 3
MINIMUM_CONCURRENT_REQUESTS = 256
MAX_DIAGNOSTIC_CHARACTERS = 500
_SEMANTIC_CLASSIFICATIONS = {
    "semantic_mismatch",
    "python_shadow_failure",
    "rust_lowering_or_verifier_failure",
    "rust_verifier_failure",
    "same_input_violation",
    "canonicalization_failure",
}
_INFRASTRUCTURE_CLASSIFICATIONS = {
    "timeout",
    "rust_infrastructure_failure",
    "malformed_rust_response",
}


@dataclass(frozen=True)
class AcceptedProgram:
    path: Path
    source_sha256: str
    categories: tuple[str, ...]
    module: object


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _bounded(value: object) -> str:
    text = " ".join(str(value).split())
    if len(text) <= MAX_DIAGNOSTIC_CHARACTERS:
        return text
    return text[: MAX_DIAGNOSTIC_CHARACTERS - 3] + "..."


def discover_programs() -> list[Path]:
    """Return every repository source in the stabilization scope, deterministically."""
    return sorted(
        {
            path.resolve()
            for name in DISCOVERY_ROOTS
            for path in (ROOT / name).rglob("*.ae")
            if path.is_file()
        },
        key=_relative,
    )


def _categories(path: Path, source: str) -> tuple[str, ...]:
    relative = _relative(path).lower()
    lowered = source.lower()
    categories = {"plotting_independent", "valid_source_fixture"}
    if "benchmark" in relative:
        categories.add("benchmarks")
    if any(token in relative for token in ("numerical", "linear_algebra", "mincuad", "newton", "biseccion", "puntofijo")):
        categories.add("numerical_methods")
    if any(token in lowered for token in ("list<", "array<", "vector<", "matrix<")):
        categories.add("collections")
        categories.add("allocation_heavy")
    if "struct " in lowered:
        categories.add("structs")
    if "class " in lowered:
        categories.add("classes")
    if "interface " in lowered or "implements " in lowered:
        categories.add("interfaces")
    if "function<" in lowered or "indirect_call" in relative:
        categories.add("function_values_indirect_calls")
    if "recursion" in relative or "recursive" in relative:
        categories.add("recursive_programs")
    if "string" in lowered or "string" in relative:
        categories.add("string_heavy")
    if "exception" in relative or any(token in lowered for token in ("throw ", "catch (", "try {")):
        categories.add("exceptions")
    if "expense_tracker" in relative:
        categories.add("expense_tracker")
    # A module with several declarations is a useful production-shaped unit even
    # when it does not have a dedicated directory name.
    if len(re.findall(r"(?m)^\s*(?:[A-Za-z_][\w<>?, ]*\s+)+[A-Za-z_]\w*\s*\([^;]*\)\s*\{", source)) >= 3:
        categories.add("realistic_multi_function_modules")
    return tuple(sorted(categories))


def inventory() -> tuple[list[AcceptedProgram], list[dict[str, Any]]]:
    accepted: list[AcceptedProgram] = []
    rows: list[dict[str, Any]] = []
    for path in discover_programs():
        relative = _relative(path)
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            rows.append({"path": relative, "status": "REJECTED_BEFORE_SSA", "stage": "source_read", "reason": _bounded(exc)})
            continue
        digest = sha256(source.encode()).hexdigest()
        categories = _categories(path, source)
        try:
            parse_source(source)
        except Exception as exc:
            rows.append({"path": relative, "source_sha256": digest, "categories": list(categories), "status": "REJECTED_BEFORE_SSA", "stage": "parse", "reason": _bounded(exc), "exception": type(exc).__name__})
            continue
        try:
            typed = prepare_typed_program(source, TypeChecker(source_root=path.parent))
        except Exception as exc:
            rows.append({"path": relative, "source_sha256": digest, "categories": list(categories), "status": "REJECTED_BEFORE_SSA", "stage": "typecheck_or_module_resolution", "reason": _bounded(exc), "exception": type(exc).__name__})
            continue
        backend = IRBackend()
        try:
            initial = backend.lower(typed)
        except Exception as exc:
            rows.append({"path": relative, "source_sha256": digest, "categories": list(categories), "status": "REJECTED_BEFORE_SSA", "stage": "initial_ir_lowering", "reason": _bounded(exc), "exception": type(exc).__name__})
            continue
        try:
            backend.verify(initial)
        except Exception as exc:
            rows.append({"path": relative, "source_sha256": digest, "categories": list(categories), "status": "REJECTED_BEFORE_SSA", "stage": "initial_ir_verification", "reason": _bounded(exc), "exception": type(exc).__name__})
            continue
        accepted.append(AcceptedProgram(path, digest, categories, initial))
        rows.append({"path": relative, "source_sha256": digest, "categories": list(categories), "status": "ACCEPTED_BEFORE_SSA", "stage": "verified_initial_ir"})
    return accepted, rows


def _ssa_digest(ssa: object) -> str:
    dto = canonical_ssa(ssa_module_to_dto(ssa, schema_version=2))  # type: ignore[arg-type]
    encoded = json.dumps(dto, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _failure(path: Path, exc: BaseException) -> dict[str, str]:
    if isinstance(exc, SSAShadowFailure):
        classification = exc.report.classification
        phase = exc.report.phase
    else:
        classification = "unclassified_failure"
        phase = "qualification_harness"
    return {
        "path": _relative(path),
        "classification": classification,
        "phase": phase,
        "exception": type(exc).__name__,
        "reason": _bounded(exc),
    }


def _failure_counts(failures: list[dict[str, str]]) -> dict[str, int]:
    semantic = sum(row["classification"] in _SEMANTIC_CLASSIFICATIONS for row in failures)
    infrastructure = sum(row["classification"] in _INFRASTRUCTURE_CLASSIFICATIONS for row in failures)
    return {
        "semantic_mismatches": semantic,
        "infrastructure_failures": infrastructure,
        "unclassified_failures": len(failures) - semantic - infrastructure,
        "process_crashes_or_timeouts": sum(row["classification"] in {"timeout", "rust_infrastructure_failure"} for row in failures),
    }


def _rss_bytes(pid: int | None) -> int | None:
    if pid is None or not sys.platform.startswith("linux"):
        return None
    try:
        resident_pages = int((Path("/proc") / str(pid) / "statm").read_text(encoding="ascii").split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError):
        return None


def _run_serial(
    programs: list[AcceptedProgram],
    executable: Path,
    requests: int,
    *,
    expected: dict[str, str] | None = None,
    observe_rss: bool = False,
) -> tuple[dict[str, Any], dict[str, str]]:
    failures: list[dict[str, str]] = []
    deterministic_mismatches: list[str] = []
    observed = dict(expected or {})
    rss_samples: list[dict[str, int]] = []
    completed = 0
    started = perf_counter()
    with PersistentRustSSALoweringClient(executable, timeout_seconds=60) as client:
        for index in range(requests):
            program = programs[index % len(programs)]
            try:
                ssa, _report = lower_with_rust_authority(program.module, client)
                digest = _ssa_digest(ssa)
            except Exception as exc:
                failures.append(_failure(program.path, exc))
                break  # Fail closed: no retry and no client restart.
            key = _relative(program.path)
            previous = observed.setdefault(key, digest)
            if previous != digest:
                deterministic_mismatches.append(key)
                break
            completed += 1
            if observe_rss and (completed == 1 or completed % max(1, requests // 10) == 0 or completed == requests):
                value = _rss_bytes(client.process_id)
                if value is not None:
                    rss_samples.append({"request": completed, "rss_bytes": value})
        process_startups = client.process_start_count
        client_requests = client.request_count
    counts = _failure_counts(failures)
    if rss_samples:
        middle = rss_samples[len(rss_samples) // 2]["rss_bytes"]
        late_growth = rss_samples[-1]["rss_bytes"] - middle
        allowance = max(16 * 1024 * 1024, middle // 5)
        rss_assessment = "STABLE" if late_growth <= allowance else "UNEXPLAINED_GROWTH"
    else:
        late_growth = None
        allowance = None
        rss_assessment = "NOT_AVAILABLE_ON_THIS_PLATFORM"
    return (
        {
            "requested": requests,
            "completed": completed,
            "process_startups": process_startups,
            "client_requests": client_requests,
            **counts,
            "deterministic_output_mismatches": len(deterministic_mismatches),
            "deterministic_mismatch_paths": sorted(set(deterministic_mismatches)),
            "poisoned_client_failures": max(0, process_startups - 1),
            "failures": failures,
            "rss_samples": rss_samples,
            "rss_late_growth_bytes": late_growth,
            "rss_growth_allowance_bytes": allowance,
            "rss_assessment": rss_assessment,
            "elapsed_seconds_observational": round(perf_counter() - started, 6),
        },
        observed,
    )


def _run_concurrent(
    programs: list[AcceptedProgram], executable: Path, requests: int, workers: int, expected: dict[str, str]
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    deterministic_mismatches: list[str] = []

    def lower(program: AcceptedProgram, client: PersistentRustSSALoweringClient) -> tuple[str, str]:
        ssa, _report = lower_with_rust_authority(program.module, client)
        return _relative(program.path), _ssa_digest(ssa)

    workload = [programs[index % len(programs)] for index in range(requests)]
    started = perf_counter()
    with PersistentRustSSALoweringClient(executable, timeout_seconds=60) as client:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [(program, executor.submit(lower, program, client)) for program in workload]
            completed = 0
            first_failure_seen = False
            for program, future in futures:
                try:
                    path, digest = future.result()
                except Exception as exc:
                    failures.append(_failure(program.path, exc))
                    first_failure_seen = True
                    continue
                if first_failure_seen:
                    # Calls already submitted behind a failed call are not retries;
                    # record them so a restarted/poisoned session cannot pass.
                    failures.append({"path": _relative(program.path), "classification": "poisoned_client_failure", "phase": "concurrent_session", "exception": "PoisonedClient", "reason": "request completed after an earlier shared-client failure"})
                    continue
                if expected.get(path) != digest:
                    deterministic_mismatches.append(path)
                completed += 1
        process_startups = client.process_start_count
        client_requests = client.request_count
    counts = _failure_counts(failures)
    return {
        "requested": requests,
        "completed": completed,
        "callers": workers,
        "serialized_transport": True,
        "process_startups": process_startups,
        "client_requests": client_requests,
        **counts,
        "deterministic_output_mismatches": len(deterministic_mismatches),
        "deterministic_mismatch_paths": sorted(set(deterministic_mismatches)),
        "poisoned_client_failures": sum(row["classification"] == "poisoned_client_failure" for row in failures) + max(0, process_startups - 1),
        "failures": failures,
        "elapsed_seconds_observational": round(perf_counter() - started, 6),
    }


def _phase_passed(value: dict[str, Any], expected_requests: int) -> bool:
    return (
        value.get("requested") == value.get("completed") == expected_requests
        and value.get("client_requests") == expected_requests
        and value.get("process_startups") == 1
        and value.get("semantic_mismatches") == 0
        and value.get("infrastructure_failures") == 0
        and value.get("unclassified_failures") == 0
        and value.get("deterministic_output_mismatches") == 0
        and value.get("process_crashes_or_timeouts") == 0
        and value.get("poisoned_client_failures") == 0
        and value.get("rss_assessment") != "UNEXPLAINED_GROWTH"
    )


def generate(
    *,
    revision: str,
    executable: Path,
    rounds: int = MINIMUM_REPEATED_ROUNDS,
    long_requests: int = MINIMUM_LONG_SESSION_REQUESTS,
    concurrent_requests: int = MINIMUM_CONCURRENT_REQUESTS,
    callers: int = 16,
    inventory_fn: Callable[[], tuple[list[AcceptedProgram], list[dict[str, Any]]]] = inventory,
) -> dict[str, Any]:
    accepted, rows = inventory_fn()
    discovered = len(rows)
    rejected = discovered - len(accepted)
    category_paths: dict[str, list[str]] = {}
    for program in accepted:
        for category in program.categories:
            category_paths.setdefault(category, []).append(_relative(program.path))
    category_paths = {key: sorted(value) for key, value in sorted(category_paths.items())}

    if not accepted:
        repeated = long_session = concurrency = {"status": "BLOCKED", "reason": "no programs accepted before SSA"}
    else:
        repeated_requests = len(accepted) * rounds
        repeated, expected = _run_serial(accepted, executable, repeated_requests)
        repeated["rounds"] = rounds
        repeated["programs_per_round"] = len(accepted)
        long_session, expected = _run_serial(accepted, executable, long_requests, expected=expected, observe_rss=True)
        long_session["workload"] = "deterministic_round_robin_over_accepted_corpus"
        concurrency = _run_concurrent(accepted, executable, concurrent_requests, callers, expected)

    required_categories = {
        "benchmarks", "numerical_methods", "exceptions", "collections", "structs",
        "classes", "interfaces", "function_values_indirect_calls", "recursive_programs",
        "allocation_heavy", "string_heavy", "expense_tracker", "realistic_multi_function_modules",
    }
    category_gate = required_categories <= set(category_paths)
    repeated_expected = len(accepted) * rounds
    passed = (
        discovered > 169
        and bool(accepted)
        and category_gate
        and _phase_passed(repeated, repeated_expected)
        and _phase_passed(long_session, long_requests)
        and _phase_passed(concurrency, concurrent_requests)
    )
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.7a",
        "qualification_revision": revision,
        "decision": "RUST_SSA_PRODUCTION_STABILIZATION_OPERATIONAL_PASS" if passed else "RUST_SSA_PRODUCTION_STABILIZATION_OPERATIONAL_BLOCKED",
        "authority": {
            "repository_default": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "returned_ssa": "rust_schema_v2_import",
            "python_shadow": "synchronous_mandatory",
            "failure_policy": "fail_closed",
            "automatic_retries": False,
        },
        "corpus": {
            "discovery_roots": list(DISCOVERY_ROOTS),
            "historical_discovered": 169,
            "discovered_programs": discovered,
            "accepted_before_ssa": len(accepted),
            "rejected_before_ssa": rejected,
            "compared_per_round": repeated.get("programs_per_round", 0),
            "category_gate": "PASS" if category_gate else "BLOCKED",
            "missing_categories": sorted(required_categories - set(category_paths)),
            "accepted_category_paths": category_paths,
            "programs": rows,
        },
        "repeated_soak": repeated,
        "long_session": long_session,
        "concurrency": concurrency,
        "performance": {
            "measurement_kind": "incidental observations only; no timing gate",
            "hotspots_deferred_to": "RUST-3.7b",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--rounds", type=int, default=MINIMUM_REPEATED_ROUNDS)
    parser.add_argument("--long-requests", type=int, default=MINIMUM_LONG_SESSION_REQUESTS)
    parser.add_argument("--concurrent-requests", type=int, default=MINIMUM_CONCURRENT_REQUESTS)
    parser.add_argument("--callers", type=int, default=16)
    args = parser.parse_args()
    if args.rounds < MINIMUM_REPEATED_ROUNDS:
        parser.error(f"--rounds must be >= {MINIMUM_REPEATED_ROUNDS}")
    if args.long_requests < MINIMUM_LONG_SESSION_REQUESTS:
        parser.error(f"--long-requests must be >= {MINIMUM_LONG_SESSION_REQUESTS}")
    if args.concurrent_requests < MINIMUM_CONCURRENT_REQUESTS:
        parser.error(f"--concurrent-requests must be >= {MINIMUM_CONCURRENT_REQUESTS}")
    if args.callers < 2:
        parser.error("--callers must be >= 2")
    if args.build:
        cargo = shutil.which("cargo")
        if cargo is None:
            raise RuntimeError("cargo is required")
        subprocess.run(
            [cargo, "build", "--locked", "-p", "aether-verifier", "--bin", "aether-ssa-shadow"],
            cwd=ROOT / "compiler-rs",
            check=True,
        )
    executable = args.executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(f"Rust SSA companion not found: {executable}")
    report = generate(
        revision=args.revision,
        executable=executable,
        rounds=args.rounds,
        long_requests=args.long_requests,
        concurrent_requests=args.concurrent_requests,
        callers=args.callers,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(report["decision"])
    return 0 if report["decision"] == "RUST_SSA_PRODUCTION_STABILIZATION_OPERATIONAL_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
