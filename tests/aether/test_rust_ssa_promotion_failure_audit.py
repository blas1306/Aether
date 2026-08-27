from __future__ import annotations

import json
from pathlib import Path

from aether.ssa.shadow import (
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
)


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = (
    ROOT / "docs/compiler/rust_ssa_promotion_failure_root_cause_audit.json"
)
HISTORICAL = ROOT / "docs/compiler/rust_ssa_authority_promotion.json"


def test_failure_audit_accounts_for_every_historical_symptom() -> None:
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    inventory = report["failure_inventory"]
    clusters = report["root_causes"]

    assert report["decision"] == "RUST_SSA_PROMOTION_FAILURES_CLASSIFIED"
    assert report["historical_failure_total"] == 42
    assert report["reproduced_total"] == 42
    assert len(inventory) == 42
    assert len({row["node_id"] for row in inventory}) == 42
    assert sum(cluster["affected_tests"] for cluster in clusters) == 42
    assert {row["root_cause"] for row in inventory} == {
        cluster["id"] for cluster in clusters
    }


def test_failed_promotion_history_is_preserved_after_v2_default_switch() -> None:
    assert (
        SSALoweringAuthorityConfiguration().mode
        is SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED
    )
    assert (
        SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
        in SSALoweringAuthorityMode
    )
    historical = json.loads(HISTORICAL.read_text(encoding="utf-8"))
    assert historical["decision"] == "RUST_SSA_AUTHORITY_PROMOTION_FAILED"
    assert historical["authority"]["production_configuration"] == (
        "RUST_SSA_AUTHORITY_PYTHON_SHADOW"
    )


def test_each_ssa_root_cause_has_a_minimized_source_reproducer() -> None:
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    for cluster in report["root_causes"]:
        for relative in cluster["minimized_reproducers"]:
            assert (ROOT / relative).is_file()
