from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QUALIFIER = ROOT / "scripts/qualify_rust_refine_1_shadow.py"


def _load_qualifier():
    spec = importlib.util.spec_from_file_location(
        "rust_refine_1_shadow_qualification", QUALIFIER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mutation_campaign_has_no_semantic_or_acceptance_divergence() -> None:
    report = _load_qualifier().qualify(include_historical=False)

    assert report["status"] == "PASS"
    assert report["mutation_rows"] >= 36
    assert report["semantic_divergences"] == []
    assert report["rejected_by_both"] >= 33


def test_known_input_domain_divergence_is_explicit_and_fail_closed() -> None:
    report = _load_qualifier().qualify(include_historical=False)
    divergences = report["divergences"]

    assert [row["case"] for row in divergences] == ["missing_reachable_block"]
    assert divergences[0]["classification"] == "input_domain_divergence"
    assert divergences[0]["rust"]["accepted"] is False
    assert divergences[0]["python"]["accepted"] is False


def test_compilation_session_orders_both_rust_verifiers_before_export() -> None:
    source = (
        ROOT / "compiler-rs/crates/aether-verifier/src/compiler_core.rs"
    ).read_text(encoding="utf-8")

    lowering = source.index("lower_normalized_ir_to_ssa_v1(&normalized)")
    owned = source.index("verify_owned_ssa(&ssa)")
    refinement = source.index("verify_owned_ssa_refinement(&normalized, &ssa)")
    publish = source.index("self.ssa = Some(ssa)")
    assert lowering < owned < refinement < publish


def test_python_refinement_authority_remains_productive_after_schema_v2_import() -> None:
    source = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")

    imported = source.index("ssa_module_from_dto(rust_comparison_dto)")
    python_refinement = source.index(
        "verify_ssa_refinement(normalized_module, rust_ssa)"
    )
    assert imported < python_refinement
