"""Explicit, test-only Initial IR shadow validation instrumentation.

The harness is intentionally outside the installed ``aether`` package.  It
injects one already-constructed coordinator into otherwise ordinary
``IRBackend`` constructions for the lifetime of a pytest session.  Python
verification remains authoritative because all verification still flows
through ``ShadowVerifierCoordinator``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from hashlib import sha256
import json
import math
from pathlib import Path

from aether.ir import (
    PythonShadowAccepted,
    PythonShadowRejected,
    ShadowRustAccepted,
    ShadowRustRejected,
    ShadowVerificationReport,
    ShadowVerifierCoordinator,
)
from aether.ir.rust_verifier import SubprocessRustVerifierClient
from aether.pipeline import IRBackend


_SUMMARY_SCHEMA_VERSION = 1
_TIMING_DIGITS = 9


class ValidationReportSink:
    """Collect reports and associate them with the active pytest item."""

    def __init__(self) -> None:
        self._reports: list[ShadowVerificationReport] = []
        self._report_tests: list[str | None] = []
        self._active_test: str | None = None
        self._tests_exercised: set[str] = set()

    @property
    def reports(self) -> tuple[ShadowVerificationReport, ...]:
        return tuple(self._reports)

    @property
    def tests_exercised(self) -> frozenset[str]:
        return frozenset(self._tests_exercised)

    @property
    def labeled_reports(
        self,
    ) -> tuple[tuple[ShadowVerificationReport, str | None], ...]:
        return tuple(zip(self._reports, self._report_tests))

    def set_active_test(self, nodeid: str | None) -> None:
        self._active_test = nodeid

    def emit(self, report: ShadowVerificationReport) -> None:
        self._reports.append(report)
        self._report_tests.append(self._active_test)
        if self._active_test is not None:
            self._tests_exercised.add(self._active_test)


class ShadowValidationHarness:
    """Build, inject, collect, and summarize an explicit subprocess shadow."""

    def __init__(
        self,
        *,
        executable: str | Path,
        timeout_seconds: float = 5.0,
    ) -> None:
        explicit_executable = Path(executable).resolve()
        self.sink = ValidationReportSink()
        self.client = SubprocessRustVerifierClient(
            executable=explicit_executable,
            timeout_seconds=timeout_seconds,
        )
        self.coordinator = ShadowVerifierCoordinator(
            client=self.client,
            sink=self.sink,
        )
        self.tests_collected = 0
        self.tests_completed = 0
        self.injected_backends = 0
        self.injection_enabled = True
        self._restore_backend_init: Callable[..., None] | None = None

    def install(self) -> None:
        """Inject the coordinator into new backends until ``uninstall``."""

        if self._restore_backend_init is not None:
            raise RuntimeError("shadow validation harness is already installed")
        original_init = IRBackend.__init__
        harness = self

        def validation_init(
            backend: IRBackend,
            *,
            output_writer: Callable[[str], None] | None = None,
            program_arguments: Sequence[str] = (),
            shadow_verifier: ShadowVerifierCoordinator | None = None,
        ) -> None:
            if shadow_verifier is None and harness.injection_enabled:
                shadow_verifier = harness.coordinator
                harness.injected_backends += 1
            original_init(
                backend,
                output_writer=output_writer,
                program_arguments=program_arguments,
                shadow_verifier=shadow_verifier,
            )

        self._restore_backend_init = original_init
        IRBackend.__init__ = validation_init  # type: ignore[method-assign]

    def uninstall(self) -> None:
        """Restore the exact constructor that was active before installation."""

        original_init = self._restore_backend_init
        if original_init is None:
            return
        IRBackend.__init__ = original_init  # type: ignore[method-assign]
        self._restore_backend_init = None

    @contextmanager
    def injected(self) -> Iterator[ShadowValidationHarness]:
        self.install()
        try:
            yield self
        finally:
            self.uninstall()

    def set_active_test(self, nodeid: str | None) -> None:
        self.sink.set_active_test(nodeid)

    def set_injection_enabled(self, enabled: bool) -> None:
        self.injection_enabled = enabled

    def summary(self, *, population: str) -> dict[str, object]:
        """Return a deterministically ordered, payload-free aggregate."""

        reports = self.sink.reports
        classifications = Counter(
            report.comparison.classification.value for report in reports
        )
        failure_kinds = Counter(
            report.metadata.failure_kind
            for report in reports
            if report.metadata.failure_kind is not None
        )
        stages = Counter(report.metadata.stage.value for report in reports)
        classifications_by_stage: dict[str, Counter[str]] = defaultdict(Counter)
        hashes = Counter(
            report.metadata.request_sha256
            for report in reports
            if report.metadata.request_sha256 is not None
        )
        for report in reports:
            classifications_by_stage[report.metadata.stage.value][
                report.comparison.classification.value
            ] += 1

        invariant_rows: dict[
            tuple[str, str, str | None, str | None],
            set[str],
        ] = defaultdict(set)
        invariant_observations: Counter[
            tuple[str, str, str | None, str | None]
        ] = Counter()
        for report in reports:
            if not isinstance(report.authoritative, PythonShadowRejected):
                continue
            rust_invariant = (
                report.shadow.diagnostic.invariant_id
                if isinstance(report.shadow, ShadowRustRejected)
                else None
            )
            rust_outcome = (
                "accepted"
                if isinstance(report.shadow, ShadowRustAccepted)
                else "rejected"
                if isinstance(report.shadow, ShadowRustRejected)
                else type(report.shadow).__name__
            )
            key = (
                report.authoritative.invariant_id,
                rust_outcome,
                rust_invariant,
                report.comparison.documented_rule_id,
            )
            invariant_observations[key] += 1
            if report.metadata.request_sha256 is not None:
                invariant_rows[key].add(report.metadata.request_sha256)

        accepted = sum(
            isinstance(report.authoritative, PythonShadowAccepted)
            for report in reports
        )
        rejected = len(reports) - accepted
        summary: dict[str, object] = {
            "schema_version": _SUMMARY_SCHEMA_VERSION,
            "population": population,
            "pytest": {
                "tests_collected": self.tests_collected,
                "tests_completed": self.tests_completed,
                "tests_exercising_shadow": len(self.sink.tests_exercised),
            },
            "injected_backends": self.injected_backends,
            "observations": {
                "total": len(reports),
                "python_accepted": accepted,
                "python_rejected": rejected,
                "distinct_request_hashes": len(hashes),
                "repeated_observations": sum(
                    count - 1 for count in hashes.values() if count > 1
                ),
            },
            "classifications": _sorted_counter(classifications),
            "failure_kinds": _sorted_counter(failure_kinds),
            "stages": _sorted_counter(stages),
            "classifications_by_stage": {
                stage: _sorted_counter(classifications_by_stage[stage])
                for stage in sorted(classifications_by_stage)
            },
            "request_hash_frequencies": {
                request_hash: hashes[request_hash]
                for request_hash in sorted(hashes)
            },
            "python_invariants": [
                {
                    "python_invariant": key[0],
                    "rust_outcome": key[1],
                    "rust_invariant": key[2],
                    "documented_rule": key[3],
                    "observations": invariant_observations[key],
                    "request_hashes": sorted(invariant_rows[key]),
                }
                for key in sorted(
                    invariant_observations,
                    key=lambda item: tuple(value or "" for value in item),
                )
            ],
            "non_parity_observations": _non_parity_observations(
                self.sink.labeled_reports
            ),
            "timings_seconds": {
                "serialization": _timing_summary(
                    report.metadata.serialization_duration_seconds
                    for report in reports
                ),
                "rust_invocation": _timing_summary(
                    report.metadata.rust_invocation_duration_seconds
                    for report in reports
                ),
                "total_shadow": _timing_summary(
                    report.metadata.total_shadow_duration_seconds
                    for report in reports
                ),
            },
            "privacy": _privacy_summary(reports),
        }
        return summary

    def write_summary(self, path: str | Path, *, population: str) -> None:
        """Write one stable-key-order JSON document without request payloads."""

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                self.summary(population=population),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def _sorted_counter(counter: Counter[str]) -> dict[str, int]:
    return {name: counter[name] for name in sorted(counter)}


def _timing_summary(values: Iterator[float | None]) -> dict[str, float | int]:
    samples = sorted(value for value in values if value is not None)
    if not samples:
        return {
            "count": 0,
            "median": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "maximum": 0.0,
            "total": 0.0,
        }
    return {
        "count": len(samples),
        "median": _rounded_percentile(samples, 0.50),
        "p90": _rounded_percentile(samples, 0.90),
        "p95": _rounded_percentile(samples, 0.95),
        "maximum": round(samples[-1], _TIMING_DIGITS),
        "total": round(sum(samples), _TIMING_DIGITS),
    }


def _rounded_percentile(samples: list[float], percentile: float) -> float:
    index = max(0, math.ceil(percentile * len(samples)) - 1)
    return round(samples[index], _TIMING_DIGITS)


def _privacy_summary(
    reports: tuple[ShadowVerificationReport, ...],
) -> dict[str, object]:
    snapshots = json.dumps(
        [report.semantic_snapshot() for report in reports],
        ensure_ascii=False,
        sort_keys=True,
    )
    lowered = snapshots.lower()
    forbidden_markers = {
        "canonical_request_payload": "canonical_request_payload" in lowered,
        "environment": '"environment"' in lowered,
        "home_path": "/home/" in lowered or "\\users\\" in lowered,
        "process_id": '"pid"' in lowered or '"process_id"' in lowered,
        "source_code": '"source"' in lowered,
        "temporary_path": "/tmp/" in lowered or "\\temp\\" in lowered,
    }
    semantic_sha256 = sha256(snapshots.encode("utf-8")).hexdigest()
    return {
        "forbidden_marker_hits": {
            name: hit for name, hit in sorted(forbidden_markers.items())
        },
        "semantic_snapshots_sha256": semantic_sha256,
    }


def _non_parity_observations(
    labeled_reports: tuple[
        tuple[ShadowVerificationReport, str | None],
        ...,
    ],
) -> list[dict[str, object]]:
    ordinary = {
        "match_accepted",
        "match_rejected_exact",
        "match_rejected_semantic",
        "documented_diagnostic_divergence",
        "documented_outcome_divergence",
    }
    observations = []
    for report, nodeid in labeled_reports:
        classification = report.comparison.classification.value
        if classification in ordinary:
            continue
        rust_invariant = (
            report.shadow.diagnostic.invariant_id
            if isinstance(report.shadow, ShadowRustRejected)
            else None
        )
        observations.append(
            {
                "classification": classification,
                "documented_rule": report.comparison.documented_rule_id,
                "failure_kind": report.metadata.failure_kind,
                "python_outcome": (
                    "accepted"
                    if isinstance(report.authoritative, PythonShadowAccepted)
                    else "rejected"
                ),
                "request_sha256": report.metadata.request_sha256,
                "rust_invariant": rust_invariant,
                "rust_outcome": (
                    "accepted"
                    if isinstance(report.shadow, ShadowRustAccepted)
                    else "rejected"
                    if isinstance(report.shadow, ShadowRustRejected)
                    else type(report.shadow).__name__
                ),
                "stage": report.metadata.stage.value,
                "test": nodeid,
            }
        )
    return sorted(
        observations,
        key=lambda item: (
            str(item["classification"]),
            str(item["request_sha256"] or ""),
            str(item["test"] or ""),
        ),
    )


__all__ = [
    "ShadowValidationHarness",
    "ValidationReportSink",
]
