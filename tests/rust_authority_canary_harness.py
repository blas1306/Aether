"""Explicit, test-only Rust-authority canary instrumentation.

This module is deliberately outside the installed ``aether`` package.  A
canary exists only when pytest receives both an explicit configuration file and
an explicit verifier executable.  The ordinary test and product construction
paths never import or activate it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path

from aether.ir import (
    ShadowClassification,
    ShadowRustAccepted,
    ShadowRustInfrastructureFailure,
    ShadowRustIntegrationFailure,
    ShadowRustRejected,
    ShadowVerificationReport,
    VerifierAuthorityConfiguration,
    VerifierAuthorityEnvironment,
    VerifierAuthorityMode,
    VerifierAuthorityPipeline,
    VerifierImplementation,
)
from aether.ir.rust_verifier import SubprocessRustVerifierClient
from aether.pipeline import IRBackend


_CONFIGURATION_SCHEMA_VERSION = 1
_SUMMARY_SCHEMA_VERSION = 1
_CONFIGURATION_FIELDS = frozenset(
    {
        "schema_version",
        "authority_mode",
        "environment",
        "python_shadow",
        "comparison",
        "reporting",
        "timeout_seconds",
        "suites",
    }
)
_STARTUP_FAILURE_KINDS = frozenset(
    {
        "executable_integrity_error",
        "executable_not_found",
        "incompatible_executable",
        "invalid_executable",
        "not_executable",
        "spawn_failure",
    }
)


@dataclass(frozen=True)
class RustAuthorityCanaryConfiguration:
    """Validated, immutable test-only canary configuration."""

    timeout_seconds: float
    suites: tuple[str, ...]

    @property
    def authority_configuration(self) -> VerifierAuthorityConfiguration:
        return VerifierAuthorityConfiguration(
            VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW,
            VerifierAuthorityEnvironment.CANARY,
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "schema_version": _CONFIGURATION_SCHEMA_VERSION,
            "authority_mode": (
                VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW.value
            ),
            "environment": VerifierAuthorityEnvironment.CANARY.value,
            "python_shadow": "required",
            "comparison": "required",
            "reporting": "required",
            "timeout_seconds": self.timeout_seconds,
            "suites": list(self.suites),
        }

    @classmethod
    def load(cls, path: str | Path) -> RustAuthorityCanaryConfiguration:
        """Load an exact-schema canary file and reject ambiguous activation."""

        try:
            raw = Path(path).read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError("canary configuration cannot be read") from error
        try:
            value = json.loads(raw, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError("canary configuration is not valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("canary configuration must be a JSON object")
        if frozenset(value) != _CONFIGURATION_FIELDS:
            raise ValueError("canary configuration fields do not match schema")
        expected_literals = {
            "schema_version": _CONFIGURATION_SCHEMA_VERSION,
            "authority_mode": (
                VerifierAuthorityMode.RUST_AUTHORITY_PYTHON_SHADOW.value
            ),
            "environment": VerifierAuthorityEnvironment.CANARY.value,
            "python_shadow": "required",
            "comparison": "required",
            "reporting": "required",
        }
        for name, expected in expected_literals.items():
            if value[name] != expected:
                raise ValueError(
                    f"canary configuration requires {name}={expected!r}"
                )
        timeout = value["timeout_seconds"]
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or float(timeout) <= 0
        ):
            raise ValueError(
                "canary configuration timeout_seconds must be positive"
            )
        suites = value["suites"]
        if (
            not isinstance(suites, list)
            or not suites
            or any(not isinstance(name, str) or not name for name in suites)
            or suites != sorted(set(suites))
        ):
            raise ValueError(
                "canary configuration suites must be sorted and unique"
            )
        return cls(timeout_seconds=float(timeout), suites=tuple(suites))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


class CanaryReportSink:
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
    def labeled_reports(
        self,
    ) -> tuple[tuple[ShadowVerificationReport, str | None], ...]:
        return tuple(zip(self._reports, self._report_tests))

    @property
    def tests_exercised(self) -> frozenset[str]:
        return frozenset(self._tests_exercised)

    def set_active_test(self, nodeid: str | None) -> None:
        self._active_test = nodeid

    def emit(self, report: ShadowVerificationReport) -> None:
        if (
            report.authority_result.implementation
            is not VerifierImplementation.RUST
            or report.shadow_result.implementation
            is not VerifierImplementation.PYTHON
        ):
            raise RuntimeError("canary report did not use Rust authority")
        self._reports.append(report)
        self._report_tests.append(self._active_test)
        if self._active_test is not None:
            self._tests_exercised.add(self._active_test)


class RustAuthorityCanaryHarness:
    """Build, inject, collect, and summarize the Rust-authority canary."""

    def __init__(
        self,
        *,
        configuration: RustAuthorityCanaryConfiguration,
        executable: str | Path,
    ) -> None:
        self.configuration = configuration
        self.sink = CanaryReportSink()
        self.client = SubprocessRustVerifierClient(
            executable=Path(executable).resolve(),
            timeout_seconds=configuration.timeout_seconds,
        )
        self.pipeline = VerifierAuthorityPipeline(
            client=self.client,
            sink=self.sink,
            configuration=configuration.authority_configuration,
            strict_sink_errors=True,
        )
        self.tests_collected = 0
        self.tests_completed = 0
        self.injected_backends = 0
        self._restore_backend_init: Callable[..., None] | None = None

    def install(self) -> None:
        if self._restore_backend_init is not None:
            raise RuntimeError("Rust-authority canary is already installed")
        original_init = IRBackend.__init__
        harness = self

        def canary_init(
            backend: IRBackend,
            *,
            output_writer: Callable[[str], None] | None = None,
            program_arguments: Sequence[str] = (),
            shadow_verifier: VerifierAuthorityPipeline | None = None,
        ) -> None:
            if shadow_verifier is None:
                shadow_verifier = harness.pipeline
                harness.injected_backends += 1
            original_init(
                backend,
                output_writer=output_writer,
                program_arguments=program_arguments,
                shadow_verifier=shadow_verifier,
            )

        self._restore_backend_init = original_init
        IRBackend.__init__ = canary_init  # type: ignore[method-assign]

    def uninstall(self) -> None:
        original_init = self._restore_backend_init
        if original_init is None:
            return
        IRBackend.__init__ = original_init  # type: ignore[method-assign]
        self._restore_backend_init = None

    @contextmanager
    def injected(self) -> Iterator[RustAuthorityCanaryHarness]:
        self.install()
        try:
            yield self
        finally:
            self.uninstall()

    def set_active_test(self, nodeid: str | None) -> None:
        self.sink.set_active_test(nodeid)

    def summary(self, *, population: str) -> dict[str, object]:
        """Return a stable, timing-free operational summary."""

        reports = self.sink.reports
        classifications = Counter(
            report.comparison.classification.value for report in reports
        )
        semantic_mismatches = sum(
            classifications[classification.value]
            for classification in (
                ShadowClassification.DOCUMENTED_OUTCOME_DIVERGENCE,
                ShadowClassification.UNEXPECTED_OUTCOME_DIVERGENCE,
            )
        )
        failure_kinds = Counter(
            report.metadata.failure_kind
            for report in reports
            if report.metadata.failure_kind is not None
        )
        accepted = sum(
            isinstance(report.authoritative, ShadowRustAccepted)
            for report in reports
        )
        rejected = sum(
            isinstance(report.authoritative, ShadowRustRejected)
            for report in reports
        )
        protocol_failures = sum(
            isinstance(report.authoritative, ShadowRustInfrastructureFailure)
            for report in reports
        )
        integration_failures = sum(
            isinstance(report.authoritative, ShadowRustIntegrationFailure)
            for report in reports
        )
        request_hashes = Counter(
            report.metadata.request_sha256
            for report in reports
            if report.metadata.request_sha256 is not None
        )
        snapshots = json.dumps(
            [report.semantic_snapshot() for report in reports],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return {
            "schema_version": _SUMMARY_SCHEMA_VERSION,
            "population": population,
            "configuration": self.configuration.snapshot(),
            "pytest": {
                "tests_collected": self.tests_collected,
                "tests_completed": self.tests_completed,
                "tests_exercising_canary": len(self.sink.tests_exercised),
            },
            "injected_backends": self.injected_backends,
            "modules": {
                "total": len(reports),
                "accepted": accepted,
                "rejected": rejected,
                "unavailable": len(reports) - accepted - rejected,
                "distinct_request_hashes": len(request_hashes),
            },
            "comparisons": {
                "total": len(reports),
                "classifications": _sorted_counter(classifications),
                "semantic_mismatches": semantic_mismatches,
                "unexpected": sum(
                    count
                    for classification, count in classifications.items()
                    if classification.startswith("unexpected_")
                    or classification
                    in {
                        ShadowClassification.SHADOW_COORDINATOR_FAILURE.value,
                        ShadowClassification.SHADOW_SKIPPED.value,
                    }
                ),
            },
            "failures": {
                "timeout_count": failure_kinds["timeout"],
                "infrastructure_failures": (
                    protocol_failures + integration_failures
                ),
                "protocol_failures": protocol_failures,
                "startup_failures": sum(
                    failure_kinds[kind] for kind in _STARTUP_FAILURE_KINDS
                ),
                "integration_failures": integration_failures,
                "by_kind": _sorted_counter(failure_kinds),
            },
            "request_hash_frequencies": {
                request_hash: request_hashes[request_hash]
                for request_hash in sorted(request_hashes)
            },
            "semantic_snapshots_sha256": sha256(snapshots).hexdigest(),
        }

    def write_summary(self, path: str | Path, *, population: str) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                self.summary(population=population),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )


def _sorted_counter(counter: Counter[str]) -> dict[str, int]:
    return {name: counter[name] for name in sorted(counter)}


__all__ = [
    "CanaryReportSink",
    "RustAuthorityCanaryConfiguration",
    "RustAuthorityCanaryHarness",
]
