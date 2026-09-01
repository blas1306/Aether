import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs/architecture/implementation_language_ownership.json"


def test_ownership_registry_has_one_legal_authority_per_responsibility() -> None:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    languages = set(data["languages"])
    phases = set(data["migration_phases"])
    components = data["components"]

    names = [entry["component"] for entry in components]
    assert len(names) == len(set(names))
    assert data["principle"] == "one_canonical_implementation_per_responsibility"

    for entry in components:
        required = {
            "component", "current_authority", "target_authority",
            "migration_phase", "allowed_shadows", "boundary",
        }
        assert required <= set(entry)
        assert set(entry) <= required | {
            "semantic_parity_status",
            "operational_readiness_status",
            "companion_packaging_model",
            "next_promotion",
        }
        if entry["component"] not in {
            "initial_ir_verification",
            "ssa_construction",
            "ssa_verification",
        }:
            assert set(entry) == required
        assert entry["current_authority"] in languages
        assert entry["target_authority"] in languages
        assert entry["migration_phase"] in phases
        assert len(entry["allowed_shadows"]) == len(set(entry["allowed_shadows"]))
        assert all(shadow in languages for shadow in entry["allowed_shadows"])
        assert entry["current_authority"] not in entry["allowed_shadows"]

    initial_verifier = next(
        entry for entry in components
        if entry["component"] == "initial_ir_verification"
    )
    assert initial_verifier["current_authority"] == "python"
    assert initial_verifier["migration_phase"] == "RP2"
    assert initial_verifier["allowed_shadows"] == ["rust"]
    assert (
        initial_verifier["next_promotion"]
        == "RUST_IR_2_PRE_LIFECYCLE_SHADOW_QUALIFICATION"
    )
    assert (
        initial_verifier["semantic_parity_status"]
        == "pre_lifecycle_acceptance_parity"
    )
    assert (
        initial_verifier["operational_readiness_status"]
        == "double_fail_closed_shadow_integrated"
    )
    assert (
        initial_verifier["companion_packaging_model"]
        == "native_compiler_core_wheel"
    )

    for component in ("ssa_construction", "ssa_verification"):
        ssa = next(entry for entry in components if entry["component"] == component)
        assert ssa["current_authority"] == "python"
        assert ssa["migration_phase"] == "RP2"
        assert ssa["allowed_shadows"] == ["rust"]
        assert ssa["operational_readiness_status"] == "promotion_failed_rust_3_6"


def test_only_migrations_may_have_shadows() -> None:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for entry in data["components"]:
        if entry["allowed_shadows"]:
            assert entry["migration_phase"] not in {"stable", "RP0"}
