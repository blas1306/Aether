#!/usr/bin/env python3
"""Repeat the verifier operational suites and emit deterministic soak statistics."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ir.rust_verifier import select_rust_verifier_executable  # noqa: E402


SUITES = {
    "migration_corpus": (
        "tests/aether/test_rust_verifier_adapter_integration.py",
    ),
    "differential_corpus": (
        "tests/aether/test_shadow_verifier_integration.py",
    ),
    "compiler_examples": ("tests/test_example_smoke.py",),
    "benchmark_suite": ("tests/aether/test_benchmark.py",),
}


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _stable_projection(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in summary.items()
        if key not in {"timings_seconds", "population"}
    }


def run_soak(
    executable: Path,
    *,
    iterations: int,
    suite_timeout_seconds: float,
) -> dict[str, object]:
    selection = select_rust_verifier_executable(executable)
    classifications: Counter[str] = Counter()
    failure_kinds: Counter[str] = Counter()
    fingerprints: dict[str, list[str]] = defaultdict(list)
    pytest_executions = 0
    verifier_observations = 0
    corpus_snapshot_observations = 0
    process_failures = 0
    timeout_count = 0
    suite_runs = 0

    with tempfile.TemporaryDirectory(prefix="aether-verifier-soak-") as temporary:
        temporary_root = Path(temporary)
        for iteration in range(iterations):
            suite_runs += 1
            snapshot_path = temporary_root / f"{iteration}-corpus-snapshot.json"
            snapshot_command = [
                sys.executable,
                str(ROOT / "scripts" / "rust_verifier_platform_snapshot.py"),
                "--executable",
                str(selection.path),
                "--output",
                str(snapshot_path),
            ]
            try:
                snapshot_completed = subprocess.run(
                    snapshot_command,
                    cwd=ROOT,
                    check=False,
                    timeout=suite_timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                timeout_count += 1
            else:
                if snapshot_completed.returncode != 0:
                    process_failures += 1
                elif snapshot_path.is_file():
                    snapshot = json.loads(
                        snapshot_path.read_text(encoding="utf-8")
                    )
                    statistics = snapshot["statistics"]
                    corpus_snapshot_observations += int(
                        statistics["transportable_cases"]
                    )
                    classifications.update(statistics["classifications"])
                    fingerprints["operational_corpus_snapshot"].append(
                        sha256(snapshot_path.read_bytes()).hexdigest()
                    )
            for suite_name, test_paths in SUITES.items():
                suite_runs += 1
                summary_path = temporary_root / f"{iteration}-{suite_name}.json"
                command = [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    *test_paths,
                    "--shadow-validation-executable",
                    str(selection.path),
                    "--shadow-validation-output",
                    str(summary_path),
                ]
                try:
                    completed = subprocess.run(
                        command,
                        cwd=ROOT,
                        check=False,
                        timeout=suite_timeout_seconds,
                    )
                except subprocess.TimeoutExpired:
                    timeout_count += 1
                    continue
                if completed.returncode != 0:
                    process_failures += 1
                if not summary_path.is_file():
                    continue
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                pytest_executions += int(summary["pytest"]["tests_completed"])
                verifier_observations += int(summary["observations"]["total"])
                classifications.update(summary["classifications"])
                failure_kinds.update(summary["failure_kinds"])
                encoded = json.dumps(
                    _stable_projection(summary),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
                fingerprints[suite_name].append(sha256(encoded).hexdigest())

    deterministic = all(
        len(set(suite_fingerprints)) == 1
        for suite_fingerprints in fingerprints.values()
    ) and set(fingerprints) == set(SUITES) | {"operational_corpus_snapshot"}
    return {
        "schema_version": 1,
        "host": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "executable": {
            "version": selection.identity.version,
            "sha256": selection.sha256,
            "protocol_versions": list(selection.identity.protocol_versions),
            "ir_schema_versions": list(selection.identity.ir_schema_versions),
            "capabilities": list(selection.identity.capabilities),
        },
        "configuration": {
            "iterations": iterations,
            "suite_timeout_seconds": suite_timeout_seconds,
            "suites": sorted(SUITES),
        },
        "execution_counts": {
            "suite_runs": suite_runs,
            "pytest_tests_completed": pytest_executions,
            "verifier_observations": verifier_observations,
            "corpus_snapshot_observations": corpus_snapshot_observations,
        },
        "failure_counts": {
            "suite_process_failures": process_failures,
            "suite_timeouts": timeout_count,
            "verifier_failure_kinds": {
                key: failure_kinds[key] for key in sorted(failure_kinds)
            },
        },
        "comparison_statistics": {
            key: classifications[key] for key in sorted(classifications)
        },
        "determinism": {
            "confirmed": deterministic,
            "suite_fingerprints": {
                key: values for key, values in sorted(fingerprints.items())
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument(
        "--iterations",
        type=_positive_integer,
        default=3,
    )
    parser.add_argument("--suite-timeout", type=float, default=1800.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_soak(
        args.executable,
        iterations=args.iterations,
        suite_timeout_seconds=args.suite_timeout,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(args.output)
    failures = report["failure_counts"]
    assert isinstance(failures, dict)
    deterministic = report["determinism"]
    assert isinstance(deterministic, dict)
    return (
        0
        if failures["suite_process_failures"] == 0
        and failures["suite_timeouts"] == 0
        and not failures["verifier_failure_kinds"]
        and deterministic["confirmed"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
