"""Benchmark the Python IR verifier against the Rust migration corpus."""

from __future__ import annotations

import argparse
import copy
import os
import platform
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import perf_counter_ns
from typing import Callable, Sequence

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
CORPUS_MANIFEST = REPOSITORY_ROOT / "tests/aether/rust_migration/manifest.yaml"
CRITICAL_DIFFERENTIAL_CASES = {
    "critical-ssa-duplicate-value": "IRV-009",
    "critical-storage-inconsistent-slot-type": "IRV-010",
    "critical-ssa-invalid-declared-type": "IRV-011",
    "critical-borrow-owning-store-without-retain": "IRV-040",
    "critical-borrow-mutation-receiver": "IRV-042",
    "critical-builtins-read-result-layout": "IRV-063",
    "critical-builtins-retain-scalar": "IRV-066",
    "critical-builtins-scalar-alias": "IRV-067",
    "critical-ssa-aggregate-compare-shape": "IRV-075",
    "critical-structs-incomplete-construction": "IRV-079",
    "critical-structs-field-read-result": "IRV-080",
    "critical-structs-field-update-value": "IRV-081",
    "critical-method-result-missing-value": "IRV-082",
}

if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from aether.ir import IRModule, IRVerificationError, IRVerifier  # noqa: E402
from aether.pipeline import IRBackend  # noqa: E402


@dataclass(frozen=True)
class CorpusEntry:
    id: str
    test: str
    accepted: bool
    parameter_case: int = 1
    verifier_invocation: int = 1
    expected_invariant: str | None = None
    expected_rust_invariant: str | None = None
    diagnostic_divergence: str | None = None
    expected_rust_outcome: str | None = None
    outcome_divergence: str | None = None
    covers: tuple[str, ...] = ()


class CorpusComparison(str, Enum):
    OUTCOME_MISMATCH = "outcome_mismatch"
    EXACT_DIAGNOSTIC_MATCH = "exact_diagnostic_match"
    DOCUMENTED_DIAGNOSTIC_DIVERGENCE = "documented_diagnostic_divergence"
    UNEXPECTED_DIAGNOSTIC_DIVERGENCE = "unexpected_diagnostic_divergence"


KNOWN_DIAGNOSTIC_DIVERGENCES = frozenset(
    {
        "first_failure_ordering",
        "representation_import_model",
        "lifecycle_dataflow_semantics",
    }
)
KNOWN_OUTCOME_DIVERGENCES: frozenset[str] = frozenset()
_INVARIANT_ID = re.compile(r"IRV-[0-9]{3}")


def compare_verifier_observations(
    entry: CorpusEntry,
    *,
    python_accepted: bool,
    python_invariant: str | None,
    rust_accepted: bool,
    rust_invariant: str | None,
) -> CorpusComparison | None:
    """Compare outcomes first, then stable first-invariant IDs for rejections."""
    if python_accepted != rust_accepted:
        return CorpusComparison.OUTCOME_MISMATCH
    if python_accepted:
        return None
    if python_invariant == rust_invariant:
        return CorpusComparison.EXACT_DIAGNOSTIC_MATCH
    if (
        entry.diagnostic_divergence is not None
        and python_invariant == entry.expected_invariant
        and rust_invariant == entry.expected_rust_invariant
    ):
        return CorpusComparison.DOCUMENTED_DIAGNOSTIC_DIVERGENCE
    return CorpusComparison.UNEXPECTED_DIAGNOSTIC_DIVERGENCE


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return parsed


def _load_manifest(path: Path) -> tuple[int, list[CorpusEntry]]:
    """Read the small, deliberately regular migration manifest without PyYAML."""
    schema_version: int | None = None
    accepted: bool | None = None
    current: dict[str, str] | None = None
    entries: list[CorpusEntry] = []

    def parse_covers(value: str) -> tuple[str, ...]:
        if not value.startswith("[") or not value.endswith("]"):
            raise ValueError(f"Corpus covers must be an inline list, got {value!r}")
        covers = tuple(
            item.strip() for item in value[1:-1].split(",") if item.strip()
        )
        if not covers:
            raise ValueError("Corpus covers must not be empty")
        if any(_INVARIANT_ID.fullmatch(item) is None for item in covers):
            raise ValueError(f"Corpus covers contains an invalid invariant: {value!r}")
        if len(covers) != len(set(covers)):
            raise ValueError(f"Corpus covers contains duplicates: {value!r}")
        return covers

    def finish_entry() -> None:
        nonlocal current
        if current is None:
            return
        if accepted is None:
            raise ValueError(f"Corpus entry {current.get('id', '<unknown>')} is outside a list")
        try:
            entry = CorpusEntry(
                id=current["id"],
                test=current["test"],
                accepted=accepted,
                parameter_case=int(current.get("parameter_case", "1")),
                verifier_invocation=int(current.get("verifier_invocation", "1")),
                expected_invariant=current.get("expected_invariant"),
                expected_rust_invariant=current.get("expected_rust_invariant"),
                diagnostic_divergence=current.get("diagnostic_divergence"),
                expected_rust_outcome=current.get("expected_rust_outcome"),
                outcome_divergence=current.get("outcome_divergence"),
                covers=parse_covers(current["covers"]),
            )
        except (KeyError, ValueError) as error:
            raise ValueError(f"Malformed corpus entry: {current}") from error
        if entry.parameter_case < 1 or entry.verifier_invocation < 1:
            raise ValueError(f"Corpus ordinals must be positive for {entry.id}")
        if entry.accepted and entry.expected_invariant is not None:
            raise ValueError(f"Valid corpus entry {entry.id} has a rejection expectation")
        if not entry.accepted and entry.expected_invariant is None:
            raise ValueError(f"Invalid corpus entry {entry.id} has no Python invariant")
        if (
            entry.expected_invariant is not None
            and entry.expected_invariant not in entry.covers
        ):
            raise ValueError(
                f"Invalid corpus entry {entry.id} does not cover its expected invariant"
            )
        if (entry.expected_rust_invariant is None) != (entry.diagnostic_divergence is None):
            raise ValueError(
                f"Corpus entry {entry.id} must define both Rust invariant and divergence kind"
            )
        if entry.diagnostic_divergence not in KNOWN_DIAGNOSTIC_DIVERGENCES | {None}:
            raise ValueError(
                f"Corpus entry {entry.id} has unknown diagnostic divergence "
                f"{entry.diagnostic_divergence!r}"
            )
        if (
            entry.expected_rust_invariant is not None
            and entry.expected_rust_invariant == entry.expected_invariant
        ):
            raise ValueError(f"Corpus entry {entry.id} documents an exact diagnostic as divergent")
        if (entry.expected_rust_outcome is None) != (entry.outcome_divergence is None):
            raise ValueError(
                f"Corpus entry {entry.id} must define both Rust outcome and divergence kind"
            )
        if entry.expected_rust_outcome not in {None, "accepted", "rejected"}:
            raise ValueError(
                f"Corpus entry {entry.id} has unknown Rust outcome "
                f"{entry.expected_rust_outcome!r}"
            )
        if entry.outcome_divergence not in KNOWN_OUTCOME_DIVERGENCES | {None}:
            raise ValueError(
                f"Corpus entry {entry.id} has unknown outcome divergence "
                f"{entry.outcome_divergence!r}"
            )
        if entry.expected_rust_outcome == ("accepted" if entry.accepted else "rejected"):
            raise ValueError(f"Corpus entry {entry.id} documents matching outcomes as divergent")
        entries.append(entry)
        current = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if raw_line == "valid_modules:":
            finish_entry()
            accepted = True
            continue
        if raw_line == "invalid_modules:":
            finish_entry()
            accepted = False
            continue
        if raw_line.startswith("schema_version:"):
            schema_version = int(line.split(":", 1)[1].strip())
            continue
        if raw_line.startswith("  - id:"):
            finish_entry()
            current = {"id": line.split(":", 1)[1].strip()}
            continue
        if current is not None and raw_line.startswith("    "):
            key, separator, value = line.partition(":")
            if separator and key in {
                "test",
                "parameter_case",
                "verifier_invocation",
                "expected_invariant",
                "expected_rust_invariant",
                "diagnostic_divergence",
                "expected_rust_outcome",
                "outcome_divergence",
                "covers",
            }:
                current[key] = value.strip()

    finish_entry()
    if schema_version is None:
        raise ValueError(f"Missing schema_version in {path}")
    if not entries:
        raise ValueError(f"No corpus entries found in {path}")
    ids = [entry.id for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate corpus IDs in {path}")
    return schema_version, entries


class _CorpusCollector:
    def __init__(self, entries: Sequence[CorpusEntry]) -> None:
        self.entries = entries
        self.entries_by_nodeid: dict[str, list[CorpusEntry]] = {}
        self.modules: dict[str, IRModule] = {}
        self._active_entries: Sequence[CorpusEntry] = ()
        self._verifier_invocation = 0

    def pytest_collection_modifyitems(
        self,
        config: pytest.Config,
        items: list[pytest.Item],
    ) -> None:
        items_by_test: dict[str, list[pytest.Item]] = defaultdict(list)
        for item in items:
            items_by_test[item.nodeid.split("[", 1)[0]].append(item)

        selected_nodeids: set[str] = set()
        for entry in self.entries:
            candidates = items_by_test.get(entry.test, [])
            try:
                item = candidates[entry.parameter_case - 1]
            except IndexError as error:
                raise pytest.UsageError(
                    f"Cannot resolve corpus entry {entry.id}: {entry.test} "
                    f"parameter case {entry.parameter_case}"
                ) from error
            selected_nodeids.add(item.nodeid)
            self.entries_by_nodeid.setdefault(item.nodeid, []).append(entry)

        deselected = [item for item in items if item.nodeid not in selected_nodeids]
        if deselected:
            config.hook.pytest_deselected(items=deselected)
        items[:] = [item for item in items if item.nodeid in selected_nodeids]

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(
        self,
        item: pytest.Item,
        nextitem: pytest.Item | None,
    ) -> object:
        self._active_entries = self.entries_by_nodeid.get(item.nodeid, ())
        self._verifier_invocation = 0
        yield
        self._active_entries = ()

    def record(self, module: IRModule) -> None:
        self._verifier_invocation += 1
        for entry in self._active_entries:
            if entry.verifier_invocation == self._verifier_invocation:
                self.modules[entry.id] = copy.deepcopy(module)


def _materialize_modules(entries: Sequence[CorpusEntry]) -> list[tuple[CorpusEntry, IRModule]]:
    collector = _CorpusCollector(entries)
    tests = sorted({entry.test for entry in entries})
    original_verify: Callable[[IRVerifier], IRModule] = IRVerifier.verify
    original_admit = IRBackend.admit_initial_ir

    def recording_verify(verifier: IRVerifier) -> IRModule:
        collector.record(verifier.module)
        return original_verify(verifier)

    def recording_admit(backend: IRBackend, module: IRModule) -> IRModule:
        collector.record(module)
        return original_admit(backend, module)

    IRVerifier.verify = recording_verify
    IRBackend.admit_initial_ir = recording_admit
    previous_directory = Path.cwd()
    try:
        os.chdir(REPOSITORY_ROOT)
        exit_code = pytest.main(
            ["-q", "--disable-warnings", "--tb=short", *tests],
            plugins=[collector],
        )
    finally:
        os.chdir(previous_directory)
        IRVerifier.verify = original_verify
        IRBackend.admit_initial_ir = original_admit

    if exit_code != pytest.ExitCode.OK:
        raise RuntimeError(f"Corpus materialization failed with pytest exit code {exit_code}")
    missing = [entry.id for entry in entries if entry.id not in collector.modules]
    if missing:
        raise RuntimeError(f"Corpus materialization did not capture: {', '.join(missing)}")
    return [(entry, collector.modules[entry.id]) for entry in entries]


def _verify_round(modules: Sequence[tuple[CorpusEntry, IRModule]]) -> tuple[int, int, int]:
    outcomes: list[tuple[CorpusEntry, bool]] = []
    started = perf_counter_ns()
    for entry, module in modules:
        try:
            IRVerifier(module).verify()
        except IRVerificationError:
            outcomes.append((entry, False))
        else:
            outcomes.append((entry, True))
    elapsed_ns = perf_counter_ns() - started

    mismatches = [entry.id for entry, actual in outcomes if actual != entry.accepted]
    if mismatches:
        raise RuntimeError(f"Verifier outcomes changed for: {', '.join(mismatches)}")
    accepted = sum(actual for _, actual in outcomes)
    return elapsed_ns, accepted, len(outcomes) - accepted


def _cpu_description() -> str:
    description = platform.processor().strip()
    cpuinfo = Path("/proc/cpuinfo")
    if not description and cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() in {"model name", "Hardware"}:
                description = value.strip()
                break
    return description or "unavailable"


def _format_report(
    *,
    schema_version: int,
    module_count: int,
    accepted: int,
    rejected: int,
    warmup_rounds: int,
    elapsed_rounds_ns: Sequence[int],
) -> str:
    measured_rounds = len(elapsed_rounds_ns)
    verifier_calls = module_count * measured_rounds
    total_ns = sum(elapsed_rounds_ns)
    average_ns = total_ns / verifier_calls
    throughput = verifier_calls / (total_ns / 1_000_000_000)
    round_ms = [elapsed / 1_000_000 for elapsed in elapsed_rounds_ns]
    return "\n".join(
        [
            "Python IR verifier baseline",
            f"Corpus: {CORPUS_MANIFEST.relative_to(REPOSITORY_ROOT)} (schema {schema_version})",
            f"Modules verified per round: {module_count}",
            f"Accepted: {accepted}",
            f"Rejected: {rejected}",
            f"Warm-up rounds: {warmup_rounds}",
            f"Measured rounds: {measured_rounds}",
            f"Measured verifier calls: {verifier_calls}",
            f"Total verification time: {total_ns / 1_000_000_000:.6f} s",
            f"Average time per module: {average_ns / 1_000:.3f} us",
            f"Throughput: {throughput:.2f} modules/s",
            "Per-round total: "
            f"min {min(round_ms):.3f} ms, median {statistics.median(round_ms):.3f} ms, "
            f"mean {statistics.mean(round_ms):.3f} ms, max {max(round_ms):.3f} ms",
            "Environment:",
            f"  Python: {platform.python_version()} ({platform.python_implementation()})",
            f"  OS: {platform.platform()}",
            f"  CPU: {_cpu_description()}",
            f"  Logical CPUs: {os.cpu_count() or 'unavailable'}",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rounds",
        type=_positive_int,
        default=10,
        help="number of measured full-corpus rounds (default: 10)",
    )
    parser.add_argument(
        "--warmup",
        type=_non_negative_int,
        default=1,
        help="number of untimed full-corpus warm-up rounds (default: 1)",
    )
    arguments = parser.parse_args(argv)

    schema_version, entries = _load_manifest(CORPUS_MANIFEST)
    print(f"Materializing {len(entries)} modules from the migration corpus (not timed)...")
    modules = _materialize_modules(entries)

    accepted = rejected = 0
    for _ in range(arguments.warmup):
        _, accepted, rejected = _verify_round(modules)

    elapsed_rounds_ns: list[int] = []
    for _ in range(arguments.rounds):
        elapsed_ns, accepted, rejected = _verify_round(modules)
        elapsed_rounds_ns.append(elapsed_ns)

    print()
    print(
        _format_report(
            schema_version=schema_version,
            module_count=len(modules),
            accepted=accepted,
            rejected=rejected,
            warmup_rounds=arguments.warmup,
            elapsed_rounds_ns=elapsed_rounds_ns,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
