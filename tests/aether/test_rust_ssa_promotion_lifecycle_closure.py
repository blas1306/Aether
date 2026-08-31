from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Iterator

import pytest

from aether.ir.dto import ir_module_to_dto
from aether.ir.lifecycle import expand_lifecycle
from aether.pipeline import IRBackend, SSAPipeline, prepare_typed_program
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.ssa.shadow import (
    PersistentRustSSALoweringClient,
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
)
from aether.ssa.shadow_independent import (
    SHADOW_INDEPENDENT_STAGE_MANIFEST,
    ShadowIndependentQualificationTrace,
)
from aether.typechecker import TypeChecker


ROOT = Path(__file__).resolve().parents[2]
AUDIT = json.loads(
    (
        ROOT / "docs/compiler/rust_ssa_promotion_failure_root_cause_audit.json"
    ).read_text(encoding="utf-8")
)
FIXTURES = tuple(
    ROOT / relative
    for relative in sorted(
        {
            relative
            for cause in AUDIT["root_causes"]
            if cause["id"] != "RC6"
            for relative in cause["minimized_reproducers"]
        }
    )
)


@pytest.fixture(scope="module")
def rust_lifecycle_tools() -> Iterator[
    tuple[Path, PersistentRustSSALoweringClient]
]:
    cargo = shutil.which("cargo")
    if cargo is None:
        pytest.skip("cargo is required")
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
    normalizer = ROOT / "compiler-rs/target/debug/examples/normalize_lifecycle_v1"
    companion = ROOT / "compiler-rs/target/debug/aether-ssa-shadow"
    with PersistentRustSSALoweringClient(companion) as client:
        yield normalizer, client


@pytest.mark.parametrize("source_path", FIXTURES, ids=lambda path: path.stem)
def test_classified_lifecycle_reproducers_match_at_boundary_b_and_in_all_modes(
    source_path: Path,
    rust_lifecycle_tools: tuple[Path, PersistentRustSSALoweringClient],
) -> None:
    normalizer, client = rust_lifecycle_tools
    typed = prepare_typed_program(
        source_path.read_text(encoding="utf-8"),
        TypeChecker(source_root=source_path.parent),
    )
    initial = IRBackend().lower_verified(typed)
    initial_dto = ir_module_to_dto(initial)
    rust_normalized = subprocess.run(
        [normalizer],
        input=json.dumps(initial_dto, sort_keys=True, separators=(",", ":")).encode(),
        capture_output=True,
        check=True,
    )
    assert json.loads(rust_normalized.stdout) == ir_module_to_dto(
        expand_lifecycle(initial)
    )

    expected_origins = {
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
    assert set(expected_origins) == set(SSALoweringAuthorityMode)
    for mode, expected_origin in expected_origins.items():
        pipeline = SSAPipeline(
            authority_configuration=SSALoweringAuthorityConfiguration(mode),
            rust_shadow_client=client,
        )
        result = pipeline.run(initial)
        SSAOptimizerPipeline(verify_after_each=True).run(result.ssa_module)
        assert pipeline.last_returned_ssa_origin == expected_origin
        if mode is SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED:
            trace = pipeline.last_authority_report
            assert isinstance(trace, ShadowIndependentQualificationTrace)
            assert trace.accepted is True
            assert trace.mode == mode.value
            assert trace.completed_stages == tuple(
                stage
                for stage in SHADOW_INDEPENDENT_STAGE_MANIFEST
                if stage
                not in {
                    "python_refinement_oracle",
                    "same_input_integrity_after_oracle",
                }
            )
            assert trace.stage_execution_counts == {
                stage: (
                    0
                    if stage
                    in {
                        "python_refinement_oracle",
                        "same_input_integrity_after_oracle",
                    }
                    else 1
                )
                for stage in SHADOW_INDEPENDENT_STAGE_MANIFEST
            }
            assert trace.refinement_authority == "rust"
            assert trace.rust_refinement_verification_observed is True
            assert trace.python_refinement_role == "not_executed"
            assert trace.refinement_verification_executed is False
            assert trace.final_generic_verification_executed is True
            assert trace.python_general_ssa_builder_instantiated is False
            assert trace.python_ssa_lowering_executed is False
            assert trace.canonical_rust_python_comparison_executed is False
        elif mode is not SSALoweringAuthorityMode.PYTHON_SSA_ONLY:
            assert pipeline.last_authority_report.classification == "match"


def test_closure_reproducers_are_in_the_permanent_shadow_soak_inventory() -> None:
    assert len(FIXTURES) == 7
    soak_source = (ROOT / "scripts/qualify_rust_ssa_shadow_operational.py").read_text(
        encoding="utf-8"
    )
    assert 'ROOT / "tests"' in soak_source
