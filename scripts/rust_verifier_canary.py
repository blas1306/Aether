#!/usr/bin/env python3
"""Run the explicit Rust-authority canary suites and aggregate their reports."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from rust_authority_canary_harness import (  # noqa: E402
    RustAuthorityCanaryConfiguration,
)


CANARY_SUITES: dict[str, tuple[str, ...]] = {
    "benchmark_suite": ("tests/aether/test_benchmark.py",),
    "compiler_examples": (
        "tests/test_example_smoke.py",
        "tests/aether/test_rust_authority_canary.py::"
        "test_canary_compiler_examples_use_real_rust_authority",
    ),
    "differential_corpus": (
        "tests/aether/test_shadow_verifier_integration.py",
        "tests/aether/test_rust_authority_canary.py::"
        "test_canary_differential_corpus_uses_real_rust_authority",
    ),
    "migration_corpus": (
        "tests/aether/test_rust_verifier_adapter_integration.py",
        "tests/aether/test_rust_authority_canary.py::"
        "test_canary_migration_corpus_uses_real_rust_authority",
    ),
}


def run_canary(
    *,
    configuration_path: Path,
    executable: Path,
    output_directory: Path,
) -> tuple[int, dict[str, object]]:
    configuration = RustAuthorityCanaryConfiguration.load(
        configuration_path
    )
    if set(configuration.suites) != set(CANARY_SUITES):
        raise ValueError(
            "configured canary suites do not match the required suite set"
        )
    output_directory.mkdir(parents=True, exist_ok=True)
    suite_exit_codes: dict[str, int] = {}
    suite_summaries: dict[str, dict[str, object]] = {}

    for suite_name in configuration.suites:
        summary_path = output_directory / f"{suite_name}.json"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *CANARY_SUITES[suite_name],
            "--rust-authority-canary-config",
            str(configuration_path),
            "--rust-authority-canary-executable",
            str(executable),
            "--rust-authority-canary-output",
            str(summary_path),
            "--rust-authority-canary-population",
            suite_name,
        ]
        completed = subprocess.run(command, cwd=ROOT, check=False)
        suite_exit_codes[suite_name] = completed.returncode
        if summary_path.is_file():
            value = json.loads(summary_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError(f"{suite_name} summary is not an object")
            suite_summaries[suite_name] = value

    aggregate = _aggregate(
        configuration=configuration,
        suite_exit_codes=suite_exit_codes,
        suite_summaries=suite_summaries,
    )
    aggregate_path = output_directory / "canary-summary.json"
    aggregate_path.write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    successful = aggregate["successful"]
    assert isinstance(successful, bool)
    return (0 if successful else 1), aggregate


def _aggregate(
    *,
    configuration: RustAuthorityCanaryConfiguration,
    suite_exit_codes: dict[str, int],
    suite_summaries: dict[str, dict[str, object]],
) -> dict[str, object]:
    classifications: Counter[str] = Counter()
    failure_kinds: Counter[str] = Counter()
    modules = Counter()
    comparisons_total = 0
    semantic_mismatches = 0
    unexpected_comparisons = 0
    timeouts = 0
    infrastructure_failures = 0
    protocol_failures = 0
    startup_failures = 0
    integration_failures = 0

    for summary in suite_summaries.values():
        module_counts = summary["modules"]
        comparison_counts = summary["comparisons"]
        failures = summary["failures"]
        assert isinstance(module_counts, dict)
        assert isinstance(comparison_counts, dict)
        assert isinstance(failures, dict)
        for name in ("total", "accepted", "rejected", "unavailable"):
            modules[name] += int(module_counts[name])
        comparisons_total += int(comparison_counts["total"])
        semantic_mismatches += int(
            comparison_counts["semantic_mismatches"]
        )
        unexpected_comparisons += int(comparison_counts["unexpected"])
        by_classification = comparison_counts["classifications"]
        by_kind = failures["by_kind"]
        assert isinstance(by_classification, dict)
        assert isinstance(by_kind, dict)
        classifications.update(
            {str(name): int(count) for name, count in by_classification.items()}
        )
        failure_kinds.update(
            {str(name): int(count) for name, count in by_kind.items()}
        )
        timeouts += int(failures["timeout_count"])
        infrastructure_failures += int(
            failures["infrastructure_failures"]
        )
        protocol_failures += int(failures["protocol_failures"])
        startup_failures += int(failures["startup_failures"])
        integration_failures += int(failures["integration_failures"])

    complete = set(suite_summaries) == set(configuration.suites)
    successful = (
        complete
        and all(code == 0 for code in suite_exit_codes.values())
        and semantic_mismatches == 0
        and unexpected_comparisons == 0
        and infrastructure_failures == 0
    )
    return {
        "schema_version": 1,
        "configuration": configuration.snapshot(),
        "suites": {
            name: {
                "exit_code": suite_exit_codes[name],
                "summary_written": name in suite_summaries,
            }
            for name in sorted(suite_exit_codes)
        },
        "modules": {
            name: modules[name]
            for name in ("total", "accepted", "rejected", "unavailable")
        },
        "comparisons": {
            "total": comparisons_total,
            "semantic_mismatches": semantic_mismatches,
            "unexpected": unexpected_comparisons,
            "classifications": {
                name: classifications[name]
                for name in sorted(classifications)
            },
        },
        "failures": {
            "timeout_count": timeouts,
            "infrastructure_failures": infrastructure_failures,
            "protocol_failures": protocol_failures,
            "startup_failures": startup_failures,
            "integration_failures": integration_failures,
            "by_kind": {
                name: failure_kinds[name] for name in sorted(failure_kinds)
            },
        },
        "complete": complete,
        "successful": successful,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    exit_code, _aggregate_summary = run_canary(
        configuration_path=args.config.resolve(),
        executable=args.executable.resolve(),
        output_directory=args.output_directory.resolve(),
    )
    print(args.output_directory.resolve() / "canary-summary.json")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
