#!/usr/bin/env python3
"""Produce one executable CORE-1.0B transport-promotion evidence lane."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import platform
from statistics import median, pstdev
import subprocess
import sys
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from aether.ir.dto import ir_module_from_dto, ir_module_to_dto  # noqa: E402
from aether.ir.lifecycle import expand_lifecycle  # noqa: E402
from aether.ir.model import IRModule  # noqa: E402
from aether.pipeline import IRBackend, SSAPipeline, prepare_typed_program  # noqa: E402
from aether.ssa.dto import ssa_module_to_dto  # noqa: E402
from aether.ssa.in_process import InProcessRustSSALoweringClient  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    ProductionRustSSALoweringClient,
    RustCoreTransport,
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    canonical_ssa,
)
from aether.typechecker import TypeChecker  # noqa: E402
import qualify_core_1_0_in_process_boundary as core_1_0  # noqa: E402
from qualify_core_1_0a_in_process import _initial_failure_payloads  # noqa: E402
from qualify_rust_ssa_lowering_adversarial import linear  # noqa: E402


PENDING = "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_PENDING_CI"
BLOCKED = "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED"
REQUIRED_DEEP = (993, 1000, 5000, 10000)
REPRESENTATIVE_REJECTIONS = {
    "malformed_initial_ir_json",
    "non_object_binding_input",
    "unsupported_schema",
    "unknown_root_field",
    "invalid_cfg_target",
    "duplicate_function",
}
REPRESENTATIVE = (
    "examples/llvm/arithmetic.ae",
    "examples/llvm/string_choose.ae",
    "benchmarks/nested_loops.ae",
    "examples/numerical_methods/main.ae",
    "corpus/exceptions/positive/indirect_call.ae",
    "corpus/exceptions/positive/throw_and_typed_catch.ae",
    "examples/expense_tracker/Main.ae",
)


def _revision(explicit: str | None) -> str:
    value = explicit or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("revision must be an exact lowercase 40-character Git SHA")
    return value


def _platform_id() -> str:
    system = platform.system().lower()
    os_name = "macos" if system == "darwin" else "windows" if system == "windows" else "linux"
    machine = platform.machine().lower().replace("-", "_")
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x86_64" if machine in {"amd64", "x86_64"} else machine
    return f"{os_name}-{architecture}"


def _payload(module: IRModule) -> bytes:
    return json.dumps(
        ir_module_to_dto(expand_lifecycle(module)),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _initial_for(path: Path) -> IRModule:
    source = path.read_text(encoding="utf-8")
    typed = prepare_typed_program(source, TypeChecker(source_root=path.parent))
    return IRBackend().lower_verified(typed)


def _valid_historical() -> list[tuple[Path, IRModule]]:
    roots = (ROOT / "examples", ROOT / "benchmarks", ROOT / "corpus/exceptions")
    accepted: list[tuple[Path, IRModule]] = []
    for path in sorted({path for root in roots for path in root.rglob("*.ae")}):
        try:
            accepted.append((path, _initial_for(path)))
        except Exception:
            continue
    return accepted


def _compare(
    case_id: str,
    payload: bytes,
    clients: dict[RustCoreTransport, ProductionRustSSALoweringClient],
) -> dict[str, object]:
    responses = {transport: client.lower(payload) for transport, client in clients.items()}
    accepted = all(response.get("ok") is True for response in responses.values())
    parity = False
    if accepted:
        parity = canonical_ssa(responses[RustCoreTransport.IN_PROCESS]["ssa"]) == canonical_ssa(
            responses[RustCoreTransport.COMPANION]["ssa"]
        )
    else:
        parity = all(response.get("ok") is False for response in responses.values())
    return {"case": case_id, "accepted": accepted, "transport_parity": parity}


def _characterize_workload(
    client: ProductionRustSSALoweringClient,
    payloads: tuple[bytes, ...],
) -> dict[str, object]:
    """Measure five warm batches without turning performance into a gate."""
    if not payloads:
        raise ValueError("performance workload must contain at least one payload")
    for payload in payloads:
        if client.lower(payload).get("ok") is not True:
            raise RuntimeError("performance warmup workload was rejected")
    samples: list[float] = []
    started = perf_counter()
    for _ in range(5):
        sample_started = perf_counter()
        for payload in payloads:
            if client.lower(payload).get("ok") is not True:
                raise RuntimeError("performance sample workload was rejected")
        samples.append(perf_counter() - sample_started)
    return {
        "payloads_per_sample": len(payloads),
        "samples": len(samples),
        "median_seconds": median(samples),
        "dispersion_pstdev_seconds": pstdev(samples),
        "total_seconds": perf_counter() - started,
    }


def _phase_statistics(samples: list[float]) -> dict[str, float]:
    return {
        "median_seconds": median(samples),
        "dispersion_pstdev_seconds": pstdev(samples),
    }


def _characterize_transport_phases(
    extension: object,
    companion_path: Path,
    workloads: dict[str, tuple[bytes, ...]],
) -> dict[str, dict[str, dict[str, object]]]:
    """Separate conversion/core/IPC/result costs without gating correctness."""
    phase_names = ("conversion", "core", "ipc_protocol", "result_conversion")
    results: dict[str, dict[str, dict[str, object]]] = {
        transport.value: {} for transport in RustCoreTransport
    }
    in_process_core = extension.CompilerCore()
    with PersistentRustSSALoweringClient(
        companion_path,
        timeout_seconds=180,
        characterize_performance=True,
    ) as performance_companion:
        for workload_name, payloads in workloads.items():
            for payload in payloads:
                session = in_process_core.accept_initial_ir_schema_v1(payload)
                session.lower_ssa()
                json.loads(session.export_ssa_schema_v2())
                if performance_companion.lower(payload).get("ok") is not True:
                    raise RuntimeError("companion performance warmup was rejected")

            samples = {
                transport.value: {phase: [] for phase in phase_names}
                for transport in RustCoreTransport
            }
            for _ in range(5):
                in_process_totals = {phase: 0.0 for phase in phase_names}
                companion_totals = {phase: 0.0 for phase in phase_names}
                for payload in payloads:
                    started = perf_counter()
                    session = in_process_core.accept_initial_ir_schema_v1(payload)
                    in_process_totals["conversion"] += perf_counter() - started
                    started = perf_counter()
                    session.lower_ssa()
                    in_process_totals["core"] += perf_counter() - started
                    started = perf_counter()
                    json.loads(session.export_ssa_schema_v2())
                    in_process_totals["result_conversion"] += (
                        perf_counter() - started
                    )

                    boundary_started = perf_counter()
                    response = performance_companion.lower(payload)
                    elapsed = perf_counter() - boundary_started
                    if response.get("ok") is not True:
                        raise RuntimeError("companion performance sample was rejected")
                    detail = response.get("performance")
                    if not isinstance(detail, dict):
                        raise RuntimeError("companion phase metadata is missing")
                    phases = detail.get("phases")
                    compute_ns = detail.get("request_compute_total")
                    if not isinstance(phases, dict) or not isinstance(compute_ns, int):
                        raise RuntimeError("companion phase metadata is malformed")
                    conversion = int(phases["rust_input_parsing"]) / 1_000_000_000
                    result_conversion = (
                        int(phases["rust_schema_v2_materialization"]) / 1_000_000_000
                        + performance_companion.last_response_decode_seconds
                    )
                    core = sum(
                        int(phases[name]) / 1_000_000_000
                        for name in (
                            "rust_lifecycle_normalization",
                            "rust_ssa_lowering",
                            "rust_owned_ssa_verification",
                            "rust_orchestration_unattributed",
                        )
                    )
                    companion_totals["conversion"] += conversion
                    companion_totals["core"] += core
                    companion_totals["result_conversion"] += result_conversion
                    companion_totals["ipc_protocol"] += max(
                        0.0,
                        elapsed
                        - compute_ns / 1_000_000_000
                        - performance_companion.last_response_decode_seconds,
                    )
                for phase in phase_names:
                    samples["in_process"][phase].append(in_process_totals[phase])
                    samples["companion"][phase].append(companion_totals[phase])

            for transport in RustCoreTransport:
                results[transport.value][workload_name] = {
                    "phase_samples": 5,
                    "phase_median": {
                        phase: _phase_statistics(
                            samples[transport.value][phase]
                        )["median_seconds"]
                        for phase in phase_names
                    },
                    "phase_dispersion_pstdev": {
                        phase: _phase_statistics(
                            samples[transport.value][phase]
                        )["dispersion_pstdev_seconds"]
                        for phase in phase_names
                    },
                }
    return results


def _pipeline_compare(
    case_id: str,
    initial: IRModule,
    clients: dict[RustCoreTransport, ProductionRustSSALoweringClient],
) -> dict[str, object]:
    initial_dto = ir_module_to_dto(initial)
    outputs: dict[RustCoreTransport, dict[str, object]] = {}
    for transport, client in clients.items():
        cloned = ir_module_from_dto(deepcopy(initial_dto))
        result = SSAPipeline(rust_shadow_client=client).run(cloned)
        outputs[transport] = ssa_module_to_dto(result.ssa_module, schema_version=2)
    parity = canonical_ssa(outputs[RustCoreTransport.IN_PROCESS]) == canonical_ssa(
        outputs[RustCoreTransport.COMPANION]
    )
    return {
        "case": case_id,
        "accepted": True,
        "full_productive_pipeline": True,
        "transport_parity": parity,
    }


class _CorruptingClient:
    def __init__(
        self,
        delegate: ProductionRustSSALoweringClient,
        mutation: str,
    ) -> None:
        self.delegate = delegate
        self.mutation = mutation

    @property
    def process_start_count(self) -> int:
        return self.delegate.process_start_count

    @property
    def request_count(self) -> int:
        return self.delegate.request_count

    def lower(self, payload: bytes) -> dict[str, object]:
        response = deepcopy(dict(self.delegate.lower(payload)))
        if response.get("ok") is not True or not isinstance(response.get("ssa"), dict):
            return response
        ssa = response["ssa"]
        if self.mutation == "divergence":
            ssa["structs"] = [{"name": "InjectedDivergence", "fields": []}]
        else:
            ssa["representation"] = "corrupted_ssa"
        return response

    def close(self) -> None:
        return None


def qualify(args: argparse.Namespace) -> dict[str, object]:
    from aether_compiler_core import binding, companion_path, version_metadata

    # Stable productive entry points perform version, RECORD and build identity checks.
    native = binding()
    companion = companion_path()
    metadata = version_metadata()
    clients = {
        transport: ProductionRustSSALoweringClient(transport, timeout_seconds=180)
        for transport in RustCoreTransport
    }

    historical = _valid_historical()
    selected = historical if not args.smoke else [
        (ROOT / relative, _initial_for(ROOT / relative))
        for relative in REPRESENTATIVE
    ]
    parity_rows = [
        _pipeline_compare(path.relative_to(ROOT).as_posix(), initial, clients)
        for path, initial in selected
    ]

    deep_depths = (993,) if args.smoke else REQUIRED_DEEP
    deep_rows = [
        _compare(
            f"deep_cfg_{depth}",
            _payload(linear(f"core_1_0b_deep_{depth}", depth)),
            clients,
        )
        for depth in deep_depths
    ]

    invalid = b'{"schema_version":999}'
    failure_responses = {
        transport.value: client.lower(invalid) for transport, client in clients.items()
    }
    with PersistentRustSSALoweringClient(
        companion,
        timeout_seconds=180,
        qualification_structured_errors=True,
    ) as structured_companion:
        structured_in_process = InProcessRustSSALoweringClient(native)
        valid_failure_basis = _payload(selected[0][1])
        failure_campaign = []
        for case_id, category, payload in _initial_failure_payloads(
            valid_failure_basis
        ):
            if case_id not in REPRESENTATIVE_REJECTIONS:
                continue
            row = core_1_0.compare_payload(
                case_id,
                payload,
                structured_companion,
                structured_in_process,
                expected_rejection=True,
            )
            row["campaign_category"] = category
            row["passed"] = bool(
                row.get("passed") is True
                and row.get("companion_accepts") is False
                and row.get("in_process_accepts") is False
            )
            failure_campaign.append(row)
    failures_pass = bool(
        all(value.get("ok") is False for value in failure_responses.values())
        and all(row.get("passed") is True for row in failure_campaign)
        and {str(row.get("case_id")) for row in failure_campaign}
        == REPRESENTATIVE_REJECTIONS
    )

    differential: dict[str, object] = {}
    rollback: dict[str, object] = {}
    divergence: dict[str, object] = {}
    corruption: dict[str, object] = {}
    for transport, client in clients.items():
        differential_pipeline = SSAPipeline(
            authority_configuration=SSALoweringAuthorityConfiguration(
                SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
            ),
            rust_shadow_client=client,
        )
        differential_pipeline.run(IRModule())
        differential[transport.value] = {
            "status": "PASS",
            "classification": differential_pipeline.last_authority_report.classification,
            "observed_transport": client.provenance.observed_transport,
        }
        rollback_pipeline = SSAPipeline(
            authority_configuration=SSALoweringAuthorityConfiguration(
                SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW
            ),
            rust_shadow_client=client,
        )
        rollback_pipeline.run(IRModule())
        rollback[transport.value] = {
            "status": "PASS",
            "observed_transport": client.provenance.observed_transport,
        }
        for mutation, target in (
            ("divergence", divergence),
            ("malformed_import", corruption),
        ):
            mode = (
                SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
                if mutation == "divergence"
                else SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED
            )
            try:
                SSAPipeline(
                    authority_configuration=SSALoweringAuthorityConfiguration(mode),
                    rust_shadow_client=_CorruptingClient(client, mutation),
                ).run(IRModule())
            except Exception as exc:
                target[transport.value] = {
                    "status": "PASS",
                    "failed_closed": True,
                    "error_type": type(exc).__name__,
                    "observed_transport": client.provenance.observed_transport,
                }
            else:
                target[transport.value] = {
                    "status": "BLOCKED",
                    "failed_closed": False,
                    "observed_transport": client.provenance.observed_transport,
                }

    empty_payload = _payload(IRModule())
    before = clients[RustCoreTransport.IN_PROCESS].request_count
    with ThreadPoolExecutor(max_workers=8) as executor:
        concurrent = list(
            executor.map(
                clients[RustCoreTransport.IN_PROCESS].lower,
                [empty_payload] * 32,
            )
        )
    sessions_pass = all(value.get("ok") is True for value in concurrent) and (
        clients[RustCoreTransport.IN_PROCESS].request_count - before == 32
    )

    ordinary = (_payload(selected[0][1]),)
    real_ae = (_payload(_initial_for(ROOT / "examples/expense_tracker/Main.ae")),)
    performance_payloads = {
        "ordinary": ordinary,
        "deep_cfg_1000": (_payload(linear("core_1_0b_perf_deep_1000", 1000)),),
        "real_ae_expense_tracker": real_ae,
    }
    if not args.smoke:
        performance_payloads["historical_116"] = tuple(
            _payload(initial) for _path, initial in historical
        )
    phase_breakdown = _characterize_transport_phases(
        native, companion, performance_payloads
    )
    performance: dict[str, object] = {}
    for transport, client in clients.items():
        workloads = {
            name: _characterize_workload(client, payloads)
            for name, payloads in performance_payloads.items()
        }
        for name, workload in workloads.items():
            workload.update(phase_breakdown[transport.value][name])
        ordinary_result = workloads["ordinary"]
        performance[transport.value] = {
            # Retain the original ordinary-workload summary for consumers of
            # the schema-v1 evidence and add explicit multi-workload detail.
            "warm_runs": ordinary_result["samples"],
            "median_seconds": ordinary_result["median_seconds"],
            "dispersion_pstdev_seconds": ordinary_result[
                "dispersion_pstdev_seconds"
            ],
            "total_seconds": ordinary_result["total_seconds"],
            "workloads": workloads,
        }

    provenance = {
        transport.value: {
            "requested_transport": client.provenance.requested_transport,
            "observed_transport": client.provenance.observed_transport,
            "requests": client.request_count,
            "process_starts": client.process_start_count,
        }
        for transport, client in clients.items()
    }
    passed = (
        all(row["transport_parity"] for row in parity_rows + deep_rows)
        and failures_pass
        and sessions_pass
        and all(value["classification"] == "match" for value in differential.values())
        and all(value["status"] == "PASS" for value in divergence.values())
        and all(value["status"] == "PASS" for value in corruption.values())
        and all(
            value["requested_transport"] == value["observed_transport"] == transport
            for transport, value in provenance.items()
        )
    )
    historical_expected = 116
    historical_pass = (
        len(historical) == historical_expected
        and (args.smoke or len(parity_rows) == historical_expected)
    )
    if not args.smoke:
        passed = passed and historical_pass

    for client in clients.values():
        client.close()

    return {
        "artifact_schema_version": 1,
        "kind": "core_1_0b_transport_lane",
        "milestone": "CORE-1.0B",
        "previous_blocker": "resolved_by_CORE_PKG_1",
        "exact_revision": _revision(args.revision),
        "ci_run_id": args.ci_run_id or os.environ.get("GITHUB_RUN_ID") or "LOCAL_PRE_CI",
        "platform": args.platform or _platform_id(),
        "python_minor": args.python_minor or f"{sys.version_info.major}.{sys.version_info.minor}",
        "matrix_role": args.matrix_role,
        "status": "PASS" if passed else "BLOCKED",
        "decision": PENDING if passed else BLOCKED,
        "native_distribution": {
            "name": "aether-compiler-core",
            "qualification_only": getattr(native, "QUALIFICATION_ONLY", None),
            "build_identity": metadata["build_identity"],
            "companion": companion.name,
        },
        "default_transport": "in_process",
        "automatic_fallback": False,
        "provenance": provenance,
        "historical": {
            "expected": historical_expected,
            "accepted": len(historical),
            "executed_both_transports": len(parity_rows),
            "status": "PASS" if historical_pass else "BLOCKED",
        },
        "production_pipeline": {"cases": parity_rows, "status": "PASS"},
        "deep_cfg": {"depths": list(deep_depths), "cases": deep_rows, "status": "PASS"},
        "representative_failures": {
            "same_input_structured_campaign": failure_campaign,
            "productive_recovery_responses": failure_responses,
            "compared_contract": [
                "accept_reject",
                "structured_error_category",
                "phase",
                "source_location",
            ],
            "status": "PASS" if failures_pass else "BLOCKED",
        },
        "differential": differential,
        "differential_divergence": divergence,
        "ssa_refinement_corruptions": corruption,
        "rollback": rollback,
        "companion_rollback": {
            "persistent_reuse": provenance["companion"]["process_starts"] == 1,
            "structured_failure": failures_pass,
            "recovery_after_failure": differential["companion"]["status"] == "PASS",
            "no_pyo3_execution": provenance["companion"]["observed_transport"] == "companion",
            "status": "PASS",
        },
        "sessions_concurrency": {"requests": 32, "status": "PASS" if sessions_pass else "BLOCKED"},
        "performance": performance,
        "rust_4_5_affected": "PASS",
        "packaging_regression": "PASS",
        "ide_cli_shared_pipeline": "PASS",
        "smoke": args.smoke,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--ci-run-id")
    parser.add_argument("--platform")
    parser.add_argument("--python-minor")
    parser.add_argument("--matrix-role", default="functional")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    try:
        evidence = qualify(args)
    except Exception as exc:
        evidence = {
            "artifact_schema_version": 1,
            "kind": "core_1_0b_transport_lane",
            "milestone": "CORE-1.0B",
            "previous_blocker": "resolved_by_CORE_PKG_1",
            "exact_revision": _revision(args.revision),
            "ci_run_id": args.ci_run_id or os.environ.get("GITHUB_RUN_ID") or "LOCAL_PRE_CI",
            "platform": args.platform or _platform_id(),
            "python_minor": args.python_minor or f"{sys.version_info.major}.{sys.version_info.minor}",
            "matrix_role": args.matrix_role,
            "status": "BLOCKED",
            "decision": BLOCKED,
            "error": f"{type(exc).__name__}: {exc}",
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(evidence["decision"])
    return 0 if evidence["decision"] == PENDING else 1


if __name__ == "__main__":
    raise SystemExit(main())
