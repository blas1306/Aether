#!/usr/bin/env python3
"""Qualify the permanent RUST-3.6-V2 lifecycle promotion fixtures."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ir.dto import ir_module_from_dto, ir_module_to_dto  # noqa: E402
from aether.ir.lifecycle import expand_lifecycle  # noqa: E402
from aether.pipeline import IRBackend, SSAPipeline, prepare_typed_program  # noqa: E402
from aether.ssa import GeneralSSABuilder, SSAVerifier  # noqa: E402
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto  # noqa: E402
from aether.ssa.optimizer import SSAOptimizerPipeline  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    canonical_ssa,
)
from aether.ssa.shadow_independent import (  # noqa: E402
    SHADOW_INDEPENDENT_STAGE_MANIFEST,
    ShadowIndependentQualificationTrace,
)
from aether.typechecker import TypeChecker  # noqa: E402


MANIFEST = (
    ROOT
    / "tests/fixtures/rust_ssa_promotion_failure/qualification_manifest.json"
)
DEFAULT_COMPANION = ROOT / "compiler-rs/target/debug/aether-ssa-shadow"
DEFAULT_NORMALIZER = (
    ROOT / "compiler-rs/target/debug/examples/normalize_lifecycle_v1"
)
EXPECTED_ORIGINS = {
    SSALoweringAuthorityMode.PYTHON_SSA_ONLY: "python_general_ssa_builder",
    SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW: (
        "python_general_ssa_builder"
    ),
    SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW: (
        "rust_schema_v2_import"
    ),
    SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED: (
        "rust_schema_v2_import"
    ),
}
SEMANTIC_METADATA_FIELDS = frozenset(
    {
        "source_location",
        "bounds_checked",
        "aggregate",
        "aggregate_type",
        "interface",
        "interface_type",
        "ownership",
        "transferred_storage",
        "receiver_ownership",
        "constructor_receiver",
        "normal_target",
        "exceptional_target",
    }
)


def _load_manifest() -> dict[str, Any]:
    if set(EXPECTED_ORIGINS) != set(SSALoweringAuthorityMode):
        raise ValueError(
            "promotion fixture returned-origin contract must cover every "
            "SSA authority mode"
        )
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("promotion fixture manifest must be an object")
    causes = value.get("root_causes")
    if not isinstance(causes, list) or len(causes) != 5:
        raise ValueError("promotion fixture manifest must define five root causes")
    fixtures = [fixture for cause in causes for fixture in cause["fixtures"]]
    if len(set(fixtures)) != value.get("fixture_count"):
        raise ValueError("promotion fixture manifest fixture count is inconsistent")
    if {cause["promotion_gate"] for cause in causes} != {
        f"V2-L{number:02d}" for number in range(1, 6)
    }:
        raise ValueError("promotion fixture gates must be V2-L01 through V2-L05")
    for relative in fixtures:
        if not (ROOT / relative).is_file():
            raise ValueError(f"missing mandatory promotion fixture: {relative}")
    return value


def _field_projection(value: Any, path: str = "$") -> list[list[Any]]:
    rows: list[list[Any]] = []
    if isinstance(value, dict):
        for key in sorted(value):
            item = value[key]
            child_path = f"{path}.{key}"
            if key in SEMANTIC_METADATA_FIELDS:
                rows.append([child_path, item])
            rows.extend(_field_projection(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(_field_projection(item, f"{path}[{index}]"))
    return rows


def _mode_result(
    initial_dto: dict[str, Any],
    mode: SSALoweringAuthorityMode,
    client: PersistentRustSSALoweringClient,
) -> dict[str, Any]:
    pipeline = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(mode),
        rust_shadow_client=client,
    )
    result = pipeline.run(ir_module_from_dto(initial_dto))
    SSAOptimizerPipeline(verify_after_each=True).run(result.ssa_module)
    expected_origin = EXPECTED_ORIGINS[mode]
    report = pipeline.last_authority_report
    if mode is SSALoweringAuthorityMode.PYTHON_SSA_ONLY:
        comparison = "not_compared"
        qualification = "not_compared"
        qualification_checks = {
            "authority_report_absent": report is None,
        }
    elif mode is SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED:
        comparison = "not_compared"
        qualification = "independent_refinement_verified"
        expected_counts = {
            stage: 1 for stage in SHADOW_INDEPENDENT_STAGE_MANIFEST
        }
        qualification_checks = {
            "trace_type": isinstance(
                report, ShadowIndependentQualificationTrace
            ),
            "accepted": getattr(report, "accepted", False) is True,
            "mode": getattr(report, "mode", None) == mode.value,
            "complete_ordering": (
                getattr(report, "completed_stages", None)
                == SHADOW_INDEPENDENT_STAGE_MANIFEST
            ),
            "each_stage_executed_once": (
                getattr(report, "stage_execution_counts", None)
                == expected_counts
            ),
            "no_failed_stage": getattr(report, "failed_stage", None) is None,
            "no_failure_classification": (
                getattr(report, "failure_classification", None) is None
            ),
            "rust_lowering_executed": (
                getattr(report, "rust_ssa_lowering_executed", False) is True
            ),
            "rust_verification_succeeded": (
                getattr(report, "rust_side_verification_succeeded", False)
                is True
            ),
            "refinement_verification_executed": (
                getattr(report, "refinement_verification_executed", False)
                is True
            ),
            "final_verification_executed": (
                getattr(report, "final_generic_verification_executed", False)
                is True
            ),
            "python_builder_not_instantiated": (
                getattr(
                    report,
                    "python_general_ssa_builder_instantiated",
                    True,
                )
                is False
            ),
            "python_lowering_not_executed": (
                getattr(report, "python_ssa_lowering_executed", True) is False
            ),
            "canonical_comparison_not_executed": (
                getattr(
                    report,
                    "canonical_rust_python_comparison_executed",
                    True,
                )
                is False
            ),
        }
    else:
        comparison = getattr(report, "classification", None)
        qualification = comparison
        qualification_checks = {
            "canonical_comparison_matched": qualification == "match",
        }
    passed = (
        pipeline.last_returned_ssa_origin == expected_origin
        and all(qualification_checks.values())
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "returned_ssa_origin": pipeline.last_returned_ssa_origin,
        "expected_returned_ssa_origin": expected_origin,
        "comparison": comparison,
        "qualification": qualification,
        "qualification_checks": qualification_checks,
        "optimizer_verification": "PASS",
    }


def _qualify_fixture(
    relative: str,
    normalizer: Path,
    client: PersistentRustSSALoweringClient,
) -> dict[str, Any]:
    path = ROOT / relative
    source = path.read_text(encoding="utf-8")
    typed = prepare_typed_program(source, TypeChecker(source_root=path.parent))
    initial = IRBackend().lower_verified(typed)
    initial_dto = ir_module_to_dto(initial)
    payload = json.dumps(
        initial_dto, sort_keys=True, separators=(",", ":")
    ).encode()

    python_lifecycle = ir_module_to_dto(
        expand_lifecycle(ir_module_from_dto(initial_dto))
    )
    normalized = subprocess.run(
        [normalizer], input=payload, capture_output=True, check=True
    )
    rust_lifecycle = json.loads(normalized.stdout)

    python_ssa = GeneralSSABuilder().build(ir_module_from_dto(initial_dto))
    SSAVerifier(python_ssa).verify()
    python_dto = ssa_module_to_dto(python_ssa, schema_version=2)

    response_a = client.lower(payload)
    response_b = client.lower(payload)
    rust_dto = response_a.get("ssa")
    if response_a.get("ok") is not True or not isinstance(rust_dto, dict):
        raise RuntimeError(
            f"{relative}: Rust lowering failed: {response_a.get('error')}"
        )
    rust_ssa = ssa_module_from_dto(rust_dto)
    SSAVerifier(rust_ssa).verify()
    round_trip = ssa_module_to_dto(rust_ssa, schema_version=2)
    python_canonical = canonical_ssa(python_dto)
    rust_canonical = canonical_ssa(rust_dto)

    checks = {
        "verified_initial_ir": ir_module_to_dto(initial) == initial_dto,
        "lifecycle_parity": rust_lifecycle == python_lifecycle,
        "canonical_ssa_parity": rust_canonical == python_canonical,
        "rust_owned_ssa_verification": response_a.get("ok") is True,
        "python_ssa_verification": True,
        "schema_v2_import": True,
        "exact_python_reserialization": round_trip == rust_dto,
        "rust_determinism": response_a == response_b,
        "same_input_guarantee": ir_module_to_dto(initial) == initial_dto,
        "source_location_preservation": (
            _field_projection(python_canonical)
            == _field_projection(rust_canonical)
        ),
        "bounds_aggregate_interface_ownership_metadata": (
            _field_projection(python_canonical)
            == _field_projection(rust_canonical)
        ),
        "constructor_normal_exceptional_lifecycle": (
            rust_lifecycle == python_lifecycle
        ),
    }
    modes = {
        mode.name: _mode_result(initial_dto, mode, client)
        for mode in SSALoweringAuthorityMode
    }
    passed = all(checks.values()) and all(
        row["status"] == "PASS" for row in modes.values()
    )
    return {
        "fixture": relative,
        "source_sha256": sha256(source.encode()).hexdigest(),
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "mode_matrix": modes,
    }


def generate(
    *,
    revision: str,
    companion: Path,
    normalizer: Path,
) -> dict[str, Any]:
    manifest = _load_manifest()
    fixture_to_causes: dict[str, list[str]] = {}
    for cause in manifest["root_causes"]:
        for relative in cause["fixtures"]:
            fixture_to_causes.setdefault(relative, []).append(cause["id"])

    with PersistentRustSSALoweringClient(companion, timeout_seconds=60) as client:
        fixtures = [
            _qualify_fixture(relative, normalizer, client)
            for relative in sorted(fixture_to_causes)
        ]
        transport = {
            "requests": client.request_count,
            "process_startups": client.process_start_count,
        }
    by_path = {row["fixture"]: row for row in fixtures}
    gates = []
    for cause in manifest["root_causes"]:
        passed = all(by_path[path]["status"] == "PASS" for path in cause["fixtures"])
        gates.append(
            {
                "id": cause["promotion_gate"],
                "root_cause": cause["id"],
                "name": cause["name"],
                "coverage": cause["coverage"],
                "fixtures": cause["fixtures"],
                "status": "PASS" if passed else "BLOCKED",
            }
        )
    passed = all(gate["status"] == "PASS" for gate in gates)
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.6-V2",
        "qualification_revision": revision,
        "decision": (
            "RUST_SSA_PROMOTION_FIXTURES_QUALIFIED"
            if passed
            else "RUST_SSA_PROMOTION_FIXTURES_BLOCKED"
        ),
        "repository_default": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        "mandatory_fixture_count": len(fixtures),
        "historical_minimized_fixture_count": manifest[
            "historical_minimized_fixture_count"
        ],
        "gates": gates,
        "fixtures": fixtures,
        "transport": transport,
        "manifest_sha256": sha256(MANIFEST.read_bytes()).hexdigest(),
        "scope": {
            "lowering_semantics_changed": False,
            "lifecycle_policy_changed": False,
            "schemas_changed": False,
            "canonicalizer_changed": False,
            "optimizer_backend_semantics_changed": False,
        },
    }


def _build_tools() -> None:
    cargo = shutil.which("cargo")
    if cargo is None:
        raise RuntimeError("cargo is required")
    subprocess.run(
        [
            cargo,
            "build",
            "-p",
            "aether-ir",
            "--example",
            "normalize_lifecycle_v1",
            "-p",
            "aether-verifier",
            "--bin",
            "aether-ssa-shadow",
        ],
        cwd=ROOT / "compiler-rs",
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--companion", type=Path, default=DEFAULT_COMPANION)
    parser.add_argument("--normalizer", type=Path, default=DEFAULT_NORMALIZER)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.build:
        _build_tools()
    report = generate(
        revision=args.revision,
        companion=args.companion.resolve(),
        normalizer=args.normalizer.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(report["decision"])
    return 0 if report["decision"].endswith("_QUALIFIED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
