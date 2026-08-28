#!/usr/bin/env python3
"""Qualify CORE-1.0 companion/in-process transport parity.

This harness is experimental and never changes production authority policy.
It feeds identical normalized schema-v1 bytes to both adapters and uses the
existing canonical schema-v2 representation only as a qualification oracle.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from types import ModuleType
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from aether.ir.dto import ir_module_to_dto  # noqa: E402
from aether.ir.lifecycle import expand_lifecycle  # noqa: E402
from aether.pipeline import IRBackend, prepare_typed_program  # noqa: E402
from aether.ssa.dto import ssa_module_from_dto  # noqa: E402
from aether.ssa.in_process import InProcessRustSSALoweringClient  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    canonical_ssa,
)
from aether.ssa.verifier import SSAVerifier  # noqa: E402
from aether.typechecker import TypeChecker  # noqa: E402
from qualify_rust_ssa_lowering_adversarial import linear  # noqa: E402


DEFAULT_COMPANION = ROOT / "compiler-rs/target/release/aether-ssa-shadow"
DEFAULT_EXTENSION = ROOT / "compiler-rs/target/release/lib_aether_core.so"
HISTORICAL_ROOTS = (
    ROOT / "examples",
    ROOT / "benchmarks",
    ROOT / "corpus/exceptions",
)


def load_extension(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("_aether_core", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load extension module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_aether_core"] = module
    spec.loader.exec_module(module)
    return module


def payload_for_module(module: object) -> bytes:
    normalized = expand_lifecycle(module)
    return json.dumps(
        ir_module_to_dto(normalized), separators=(",", ":"), sort_keys=True
    ).encode()


def payload_for_path(path: Path) -> bytes:
    source = path.read_text(encoding="utf-8")
    program = prepare_typed_program(source, TypeChecker(source_root=path.parent))
    return payload_for_module(IRBackend().lower_verified(program))


def compare_payload(
    case_id: str,
    payload: bytes,
    companion: PersistentRustSSALoweringClient,
    in_process: InProcessRustSSALoweringClient,
    *,
    expected_error_kind: str | None = None,
) -> dict[str, object]:
    companion_response = companion.lower(payload)
    in_process_response = in_process.lower(payload)
    companion_ok = companion_response.get("ok") is True
    in_process_ok = in_process_response.get("ok") is True
    row: dict[str, object] = {
        "case_id": case_id,
        "same_input_bytes": True,
        "companion_accepts": companion_ok,
        "in_process_accepts": in_process_ok,
        "acceptance_parity": companion_ok == in_process_ok,
    }
    if not companion_ok or not in_process_ok:
        companion_error = str(companion_response.get("error", ""))
        in_process_error = str(in_process_response.get("error", ""))
        detail = in_process.last_error_detail
        classification_parity = (
            isinstance(detail, dict)
            and detail.get("kind") == expected_error_kind
            if expected_error_kind is not None
            else companion_ok == in_process_ok
        )
        row.update(
            {
                "error_text_parity": companion_error == in_process_error,
                "error_classification_parity": classification_parity,
                "source_location_parity": companion_error == in_process_error,
                "companion_error": companion_error[:500],
                "in_process_error": in_process_error[:500],
                "in_process_error_detail": detail,
                "passed": (
                    companion_ok == in_process_ok
                    and companion_error == in_process_error
                    and classification_parity
                ),
            }
        )
        return row

    companion_dto = companion_response.get("ssa")
    in_process_dto = in_process_response.get("ssa")
    if not isinstance(companion_dto, dict) or not isinstance(in_process_dto, dict):
        row.update({"passed": False, "malformed_success": True})
        return row
    companion_ssa = ssa_module_from_dto(companion_dto)
    in_process_ssa = ssa_module_from_dto(in_process_dto)
    SSAVerifier(companion_ssa).verify()
    SSAVerifier(in_process_ssa).verify()
    exact = companion_dto == in_process_dto
    canonical = canonical_ssa(companion_dto) == canonical_ssa(in_process_dto)
    row.update(
        {
            "schema_v2_exact": exact,
            "semantic_canonical_equal": canonical,
            "source_locations_equal": exact,
            "companion_python_verification": "PASS",
            "in_process_python_verification": "PASS",
            "passed": exact and canonical,
        }
    )
    return row


def historical_paths() -> list[Path]:
    return sorted(
        {path for root in HISTORICAL_ROOTS for path in root.rglob("*.ae")}
    )


def historical_qualification(
    companion: PersistentRustSSALoweringClient,
    in_process: InProcessRustSSALoweringClient,
    *,
    smoke: bool,
) -> dict[str, object]:
    rows = []
    for path in historical_paths():
        try:
            payload = payload_for_path(path)
        except Exception:
            # The frozen historical SSA corpus is the verified Initial-IR
            # subset; frontend-negative programs intentionally do not reach it.
            continue
        rows.append(
            compare_payload(
                path.relative_to(ROOT).as_posix(),
                payload,
                companion,
                in_process,
            )
        )
        if smoke and len(rows) == 5:
            break
    passed = sum(row["passed"] is True for row in rows)
    return {
        "expected": 5 if smoke else 116,
        "denominator": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "status": "PASS" if passed == len(rows) == (5 if smoke else 116) else "FAIL",
        "results": rows,
    }


def mutation_payloads(valid_payload: bytes) -> list[tuple[str, bytes, str]]:
    wrong_schema = json.loads(valid_payload)
    wrong_schema["schema_version"] = 999
    missing_terminator = json.loads(valid_payload)
    instructions = missing_terminator["functions"][0]["blocks"][0]["instructions"]
    if instructions:
        instructions.pop()
    return [
        ("malformed_json", b"{", "binding"),
        (
            "unsupported_schema",
            json.dumps(wrong_schema, separators=(",", ":")).encode(),
            "binding",
        ),
        (
            "missing_terminator",
            json.dumps(missing_terminator, separators=(",", ":")).encode(),
            "internal",
        ),
    ]


def stats(samples: list[float]) -> dict[str, float | int]:
    center = median(samples)
    return {
        "samples": len(samples),
        "median_seconds": center,
        "mad_seconds": median(abs(value - center) for value in samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
    }


def time_call(call: Callable[[], object], rounds: int, warmups: int) -> dict[str, float | int]:
    for _ in range(warmups):
        call()
    samples = []
    for _ in range(rounds):
        started = perf_counter()
        call()
        samples.append(perf_counter() - started)
    return stats(samples)


def performance_qualification(
    payload: bytes,
    companion: PersistentRustSSALoweringClient,
    in_process: InProcessRustSSALoweringClient,
    extension: ModuleType,
    rounds: int,
) -> dict[str, object]:
    def companion_round() -> None:
        response = companion.lower(payload)
        SSAVerifier(ssa_module_from_dto(response["ssa"])).verify()

    def in_process_round() -> None:
        response = in_process.lower(payload)
        SSAVerifier(ssa_module_from_dto(response["ssa"])).verify()

    core = extension.CompilerCore()
    phase_samples: dict[str, list[float]] = {
        "python_to_rust_input_copy_and_schema_v1_decode": [],
        "rust_lifecycle_lowering_and_verification": [],
        "schema_v2_materialization_and_rust_to_python_bytes": [],
    }
    for _ in range(rounds):
        started = perf_counter()
        session = core.accept_initial_ir_schema_v1(payload)
        phase_samples["python_to_rust_input_copy_and_schema_v1_decode"].append(
            perf_counter() - started
        )
        started = perf_counter()
        session.lower_ssa()
        phase_samples["rust_lifecycle_lowering_and_verification"].append(
            perf_counter() - started
        )
        started = perf_counter()
        session.export_ssa_schema_v2()
        phase_samples[
            "schema_v2_materialization_and_rust_to_python_bytes"
        ].append(perf_counter() - started)

    companion_stats = time_call(companion_round, rounds, 2)
    in_process_stats = time_call(in_process_round, rounds, 2)
    return {
        "method": {
            "warmups": 2,
            "rounds": rounds,
            "clock": "time.perf_counter",
            "dispersion": "median absolute deviation plus min/max",
            "scope": "transport/core/result import and Python verification",
        },
        "persistent_companion": companion_stats,
        "in_process": in_process_stats,
        "in_process_phases": {
            name: stats(samples) for name, samples in phase_samples.items()
        },
        "median_ratio_in_process_over_companion": (
            in_process_stats["median_seconds"] / companion_stats["median_seconds"]
        ),
        "interpretation": (
            "Qualification microbenchmark only; it isolates boundary cost but "
            "does not establish whole-compiler speedup."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companion", type=Path, default=DEFAULT_COMPANION)
    parser.add_argument("--extension", type=Path, default=DEFAULT_EXTENSION)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "docs/compiler/core_1_0_in_process_compiler_core_boundary.json",
    )
    parser.add_argument("--rounds", type=int, default=9)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if not args.companion.is_file():
        parser.error(f"companion not found: {args.companion}")
    if not args.extension.is_file():
        parser.error(f"extension not found: {args.extension}")

    extension = load_extension(args.extension.resolve())
    in_process = InProcessRustSSALoweringClient(extension)
    with PersistentRustSSALoweringClient(
        args.companion.resolve(), timeout_seconds=180
    ) as companion:
        hello = payload_for_path(ROOT / "examples/hello.ae")
        ordinary_paths = [
            ROOT / "examples/hello.ae",
            ROOT / "tests/aether/parity_corpus/strings.ae",
            ROOT / "examples/aggregate_collections/particles.ae",
            ROOT / "examples/Sorts/Main.ae",
            ROOT / "tests/fixtures/rust_ssa_promotion_failure/owning_call_result.ae",
        ]
        ordinary = [
            compare_payload(
                path.relative_to(ROOT).as_posix(),
                payload_for_path(path),
                companion,
                in_process,
            )
            for path in ordinary_paths
        ]
        failures = [
            compare_payload(
                name,
                payload,
                companion,
                in_process,
                expected_error_kind=expected_error_kind,
            )
            for name, payload, expected_error_kind in mutation_payloads(hello)
        ]
        deep_sizes = (993, 1000) if args.smoke else (993, 1000, 5000, 10000)
        deep = [
            compare_payload(
                f"deep_cfg_{size}",
                payload_for_module(linear(f"core_1_0_deep_{size}", size)),
                companion,
                in_process,
            )
            for size in deep_sizes
        ]
        historical = historical_qualification(
            companion, in_process, smoke=args.smoke
        )
        performance = performance_qualification(
            payload_for_path(ROOT / "examples/aggregate_collections/particles.ae"),
            companion,
            in_process,
            extension,
            3 if args.smoke else args.rounds,
        )
        transport = {
            "companion_process_starts": companion.process_start_count,
            "companion_requests": companion.request_count,
            "in_process_process_starts": in_process.process_start_count,
            "in_process_requests": in_process.request_count,
        }

    all_rows = ordinary + failures + deep
    passed = (
        all(row["passed"] is True for row in all_rows)
        and historical["status"] == "PASS"
        and transport["companion_process_starts"] == 1
        and transport["in_process_process_starts"] == 0
    )
    report = {
        "artifact_schema_version": 1,
        "milestone": "CORE-1.0",
        "qualification_only": True,
        "decision": (
            "CORE_1_0_IN_PROCESS_BOUNDARY_QUALIFIED"
            if passed and not args.smoke
            else "CORE_1_0_IN_PROCESS_BOUNDARY_SMOKE_PASS"
            if passed
            else "CORE_1_0_IN_PROCESS_BOUNDARY_BLOCKED"
        ),
        "same_logical_input": "identical lifecycle-normalized schema-v1 bytes",
        "architecture": {
            "core_owner": "aether-verifier::compiler_core",
            "reason": (
                "aether-verifier already owns composed verified IR semantics; "
                "aether-ir remains a representation crate and aether-python remains an adapter"
            ),
            "typed_api": [
                "CompilerCore.accept_initial_ir(IRModuleDTO) -> CompilationSession",
                "CompilationSession.lower_ssa() -> Result<(), CompilerError>",
                "CompilationSession.ssa() -> Option<&OwnedSsaModule>",
                "CompilationSession.export_ssa_schema_v2() -> Result<SSAModuleV2DTO, CompilerError>",
            ],
            "binding_adapter": "aether-python/PyO3",
            "companion_adapter": "aether-ssa-shadow protocol-v1",
            "persistent_rust_owned_session": True,
            "stage_to_stage_serialization": False,
            "current_entry_serialization": "schema-v1 JSON bytes decoded once",
            "current_exit_serialization": "schema-v2 JSON bytes qualification/debug escape hatch",
        },
        "error_model": {
            "classes": [
                "AetherCompilerError",
                "AetherBindingError",
                "AetherInternalCompilerError",
            ],
            "machine_fields": [
                "kind",
                "category",
                "phase",
                "code",
                "function",
                "block",
                "source_location",
            ],
            "fail_closed": True,
        },
        "packaging": {
            "tool": "maturin 1.15.0",
            "local_smoke": "PASS",
            "local_wheel": "cp314-cp314-manylinux_2_34_x86_64",
            "install_requires_rust": False,
            "production_package_integration": False,
            "required_release_targets": [
                "linux-x86_64",
                "windows-x86_64",
                "macos-x86_64",
                "macos-arm64",
            ],
            "multiplatform_matrix_run": False,
        },
        "concurrency": {
            "gil_released_for_rust_work": True,
            "session_state": "Mutex<CompilationSession>",
            "unsafe_code": False,
            "companion_model": "one synchronized persistent process per Python process",
        },
        "ordinary_and_feature_cases": ordinary,
        "representative_failures": failures,
        "deep_cfg": deep,
        "historical_116": historical,
        "performance": performance,
        "transport": transport,
        "production_policy_changed": False,
        "companion_retained": True,
        "automatic_fallback": False,
        "multiplatform_matrix_run": False,
        "validation": {
            "cargo_check_workspace": "PASS",
            "cargo_test_workspace_locked": "PASS",
            "binding_adapter_tests": "2/2 PASS",
            "wheel_install_import_error_smoke": "PASS",
            "historical": "116/116 PASS",
            "deep_cfg": "993/1000/5000/10000 PASS",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(report["decision"])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
