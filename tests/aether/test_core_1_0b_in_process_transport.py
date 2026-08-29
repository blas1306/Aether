from __future__ import annotations

import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from aether.ir.model import IRModule
from aether.pipeline import SSAPipeline
from aether.ssa.shadow import (
    RUST_CORE_TRANSPORT_ENV,
    ProductionRustSSALoweringClient,
    RustCoreTransport,
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    resolve_rust_core_transport,
)


EMPTY_SSA = {
    "schema_version": 2,
    "representation": "aether_ssa",
    "functions": [],
    "structs": [],
}


class StubClient:
    process_start_count = 0

    def __init__(
        self,
        response: dict[str, object] | None = None,
        *,
        transport_name: str = "in_process",
    ) -> None:
        self.response = response or {"ok": True, "ssa": EMPTY_SSA}
        self.transport_name = transport_name
        self.request_count = 0
        self.closed = False

    def lower(self, _payload: bytes):
        self.request_count += 1
        return self.response

    def close(self) -> None:
        self.closed = True


def selected_client(
    transport: RustCoreTransport,
    delegate: StubClient | None = None,
) -> tuple[ProductionRustSSALoweringClient, StubClient]:
    delegate = delegate or StubClient(transport_name=transport.value)
    client = ProductionRustSSALoweringClient(transport)
    client._create_client = lambda: delegate  # type: ignore[method-assign]
    return client, delegate


def test_transport_policy_default_explicit_and_invalid_fail_closed() -> None:
    assert resolve_rust_core_transport({}) is RustCoreTransport.IN_PROCESS
    assert resolve_rust_core_transport(
        {RUST_CORE_TRANSPORT_ENV: "in_process"}
    ) is RustCoreTransport.IN_PROCESS
    assert resolve_rust_core_transport(
        {RUST_CORE_TRANSPORT_ENV: "companion"}
    ) is RustCoreTransport.COMPANION
    with pytest.raises(ValueError, match="invalid AETHER_RUST_CORE_TRANSPORT"):
        resolve_rust_core_transport({RUST_CORE_TRANSPORT_ENV: "automatic"})


@pytest.mark.parametrize("transport", tuple(RustCoreTransport))
def test_requested_transport_equals_machine_readable_observation(
    transport: RustCoreTransport,
) -> None:
    client, delegate = selected_client(transport)
    assert client.observed_transport is None
    assert client.lower(b"{}") == {"ok": True, "ssa": EMPTY_SSA}
    assert client.provenance.requested_transport == transport.value
    assert client.provenance.observed_transport == transport.value
    assert delegate.request_count == 1


@pytest.mark.parametrize("requested", tuple(RustCoreTransport))
def test_adapter_transport_mismatch_fails_closed_before_execution(
    requested: RustCoreTransport,
) -> None:
    other = (
        RustCoreTransport.COMPANION
        if requested is RustCoreTransport.IN_PROCESS
        else RustCoreTransport.IN_PROCESS
    )
    delegate = StubClient(transport_name=other.value)
    client, _ = selected_client(requested, delegate)

    with pytest.raises(RuntimeError, match="transport mismatch"):
        client.lower(b"{}")

    assert delegate.closed is True
    assert delegate.request_count == 0
    assert client.observed_transport is None


def test_broken_in_process_never_discovers_or_executes_companion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    companion_calls = 0

    def broken_binding():
        raise RuntimeError("binding unavailable")

    def forbidden_companion():
        nonlocal companion_calls
        companion_calls += 1
        raise AssertionError("companion fallback")

    monkeypatch.setitem(
        sys.modules,
        "aether_compiler_core",
        SimpleNamespace(binding=broken_binding, companion_path=forbidden_companion),
    )
    client = ProductionRustSSALoweringClient(RustCoreTransport.IN_PROCESS)
    with pytest.raises(RuntimeError, match="binding unavailable"):
        client.lower(b"{}")
    assert companion_calls == 0
    assert client.requested_transport == "in_process"
    assert client.observed_transport is None


def test_broken_companion_never_imports_or_executes_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding_calls = 0

    def forbidden_binding():
        nonlocal binding_calls
        binding_calls += 1
        raise AssertionError("in-process fallback")

    def missing_companion():
        raise FileNotFoundError("companion unavailable")

    monkeypatch.setitem(
        sys.modules,
        "aether_compiler_core",
        SimpleNamespace(binding=forbidden_binding, companion_path=missing_companion),
    )
    client = ProductionRustSSALoweringClient(RustCoreTransport.COMPANION)
    with pytest.raises(FileNotFoundError, match="companion unavailable"):
        client.lower(b"{}")
    assert binding_calls == 0
    assert client.requested_transport == "companion"
    assert client.observed_transport is None


def test_missing_productive_package_fails_closed_without_other_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "aether_compiler_core", None)
    for transport in RustCoreTransport:
        with pytest.raises(RuntimeError, match="aether-compiler-core is required"):
            ProductionRustSSALoweringClient(transport).lower(b"{}")


@pytest.mark.parametrize("transport", tuple(RustCoreTransport))
def test_handled_failure_reuses_same_transport_without_hidden_switch(
    transport: RustCoreTransport,
) -> None:
    failure = {
        "ok": False,
        "error": "representative CompilerCore rejection",
        "diagnostic": {"code": "CORE-TEST-001"},
    }
    client, delegate = selected_client(
        transport,
        StubClient(failure, transport_name=transport.value),
    )
    assert client.lower(b"bad") == failure
    assert client.lower(b"bad-again") == failure
    assert delegate.request_count == 2
    assert client.provenance.requested_transport == transport.value
    assert client.provenance.observed_transport == transport.value


@pytest.mark.parametrize("transport", tuple(RustCoreTransport))
@pytest.mark.parametrize(
    "authority",
    (
        SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED,
        SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW,
        SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW,
    ),
)
def test_authority_and_transport_are_orthogonal(
    transport: RustCoreTransport,
    authority: SSALoweringAuthorityMode,
) -> None:
    client, delegate = selected_client(transport)
    result = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(authority),
        rust_shadow_client=client,
    ).run(IRModule())
    assert result.ssa_module.functions == []
    assert delegate.request_count == 1
    assert client.provenance.requested_transport == transport.value
    assert client.provenance.observed_transport == transport.value


def test_python_only_does_not_resolve_or_require_rust_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RUST_CORE_TRANSPORT_ENV, "invalid-but-unused")
    result = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.PYTHON_SSA_ONLY
        )
    ).run(IRModule())
    assert result.ssa_module.functions == []


def test_one_productive_client_is_reused_concurrently() -> None:
    client, delegate = selected_client(RustCoreTransport.IN_PROCESS)
    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(client.lower, [b"{}"] * 64))
    assert all(response == {"ok": True, "ssa": EMPTY_SSA} for response in responses)
    assert delegate.request_count == 64
    assert client.provenance.requested_transport == "in_process"
    assert client.provenance.observed_transport == "in_process"


def test_default_guard_is_in_process_and_companion_remains_selectable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RUST_CORE_TRANSPORT_ENV, raising=False)
    assert ProductionRustSSALoweringClient().requested_transport == "in_process"
    monkeypatch.setenv(RUST_CORE_TRANSPORT_ENV, "companion")
    assert ProductionRustSSALoweringClient().requested_transport == "companion"


def test_production_source_has_no_qualification_package_or_fallback() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "src/aether/ssa/shadow.py"
    ).read_text(encoding="utf-8")
    production = source[
        source.index("class ProductionRustSSALoweringClient") :
        source.index("_PRODUCTION_RUST_SSA_CLIENTS")
    ]
    assert "aether-core-qualification" not in production
    assert "aether_compiler_core import binding" in production
    assert "aether_compiler_core import companion_path" in production
    assert "except" not in production.split("def lower", 1)[1].split("def close", 1)[0]


def test_aggregate_blocks_missing_machine_readable_evidence(tmp_path) -> None:
    from pathlib import Path

    checker_path = (
        Path(__file__).resolve().parents[2]
        / "scripts/check_core_1_0b_in_process_transport.py"
    )
    spec = importlib.util.spec_from_file_location("core_1_0b_checker", checker_path)
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    aggregate, errors = checker.check(tmp_path)
    assert aggregate["decision"] == checker.BLOCKED
    assert aggregate["packaged_clean_consumer"] is False
    assert errors
    assert checker._performance_complete({"workloads": {}}) is False
    assert checker._performance_complete({"workloads": "malformed"}) is False
    assert checker._packaged_consumer_complete([], "0" * 40) is False


def test_aggregate_requires_both_exact_packaged_consumer_observations() -> None:
    from pathlib import Path

    checker_path = (
        Path(__file__).resolve().parents[2]
        / "scripts/check_core_1_0b_in_process_transport.py"
    )
    spec = importlib.util.spec_from_file_location("core_1_0b_checker", checker_path)
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    revision = "a" * 40

    def record(transport: str) -> dict[str, object]:
        return {
            "status": "PASS",
            "exact_revision": revision,
            "ci_run_id": "123",
            "expected_transport": transport,
            "default_selection": transport == "in_process",
            "requested_transport": transport,
            "observed_transport": transport,
            "language_version": "1.0.0rc4",
            "native_version": "1.0.0rc4",
            "exact_native_dependency": True,
            "native_build_identity": revision,
            "outside_source_checkout": True,
            "cargo_available": False,
            "rustc_available": False,
            "handled_failure_recovery": True,
            "process_start_count": 1 if transport == "companion" else 0,
            "request_count": 3,
            "pyo3_binding_calls": 0,
        }

    records = [record("in_process"), record("companion")]
    assert checker._packaged_consumer_complete(records, revision) is True
    records[1]["observed_transport"] = "in_process"
    assert checker._packaged_consumer_complete(records, revision) is False


def test_dedicated_workflow_has_promotion_and_matrix_guards() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    workflow = root / ".github/workflows/core-in-process-promotion.yml"
    text = workflow.read_text(encoding="utf-8")
    for job in (
        "production-default-in-process:",
        "explicit-companion-rollback:",
        "transport-parity:",
        "differential-both-transports:",
        "production-pipeline:",
        "no-fallback:",
        "sessions-concurrency:",
        "affected-rust-4-5:",
        "packaging-regression:",
        "platform-matrix:",
        "python-compatibility:",
        "aggregate-fail-closed:",
    ):
        assert job in text
    for platform_id in (
        "linux-x86_64",
        "windows-x86_64",
        "macos-x86_64",
        "macos-arm64",
    ):
        assert platform_id in text
    assert 'python: ["3.11", "3.12", "3.13", "3.14"]' in text
    assert "tests/aether/test_rust_ssa_shadow_independent.py" not in text
    assert (
        "tests/aether/test_rust_ssa_shadow_independent_production_promotion.py"
        in text
    )
    assert "tests/aether/test_rust_ssa_shadow_independent_qualification.py" in text
    assert "--ci-closure" in text
    assert "--require-promoted" in text
    assert "name: packaged-clean-consumer" in text
    assert "core_1_0b_packaged_consumer_probe.py" in text
    assert "--expected-transport in_process --expect-default" in text
    assert "--expected-transport companion" in text
    assert "core-1-0b-packaged-consumer" in text


def test_qualification_evidence_records_resolved_previous_blocker() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    qualifier = (
        root / "scripts/qualify_core_1_0b_in_process_transport.py"
    ).read_text(encoding="utf-8")
    checker = (
        root / "scripts/check_core_1_0b_in_process_transport.py"
    ).read_text(encoding="utf-8")
    evidence = json.loads(
        (
            root
            / "docs/compiler/core_1_0b_in_process_production_transport_promotion.json"
        ).read_text(encoding="utf-8")
    )
    assert '"previous_blocker": "resolved_by_CORE_PKG_1"' in qualifier
    assert 'lane.get("previous_blocker") == "resolved_by_CORE_PKG_1"' in checker
    assert evidence["resumed_promotion"]["previous_blocker"] == (
        "resolved_by_CORE_PKG_1"
    )


def test_functional_qualification_characterizes_all_required_workloads() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "scripts/qualify_core_1_0b_in_process_transport.py"
    ).read_text(encoding="utf-8")
    for workload in (
        '"ordinary"',
        '"historical_116"',
        '"deep_cfg_1000"',
        '"real_ae_expense_tracker"',
    ):
        assert workload in source
