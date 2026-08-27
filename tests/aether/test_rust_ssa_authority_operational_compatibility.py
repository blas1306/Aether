from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/qualify_rust_ssa_authority_requalification_operational.py"


def _qualification_module():
    spec = importlib.util.spec_from_file_location("rust_4_4a_operational", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_historical_corruption_is_intercepted_by_refinement_before_shadow() -> None:
    qualification = _qualification_module()
    client = qualification._historical_semantic_corruption_client()

    observation = qualification._failure_observation(client)

    assert client.response["ssa"]["structs"] == [
        {"name": "Mismatch", "fields": []}
    ]
    assert observation == {
        "rejected": True,
        "classification": "refinement_verifier_failure",
        "phase": "refinement_verification",
        "python_shadow_reached": False,
        "rust_requests": 1,
    }


def test_independent_canonical_mismatch_reaches_shadow_and_fails_closed() -> None:
    qualification = _qualification_module()

    observation = qualification._failure_observation(
        qualification._Client(),
        python_shadow_mutator=qualification._inject_python_shadow_canonical_mismatch,
    )

    assert observation == {
        "rejected": True,
        "classification": "semantic_mismatch",
        "phase": "canonical_comparison",
        "python_shadow_reached": True,
        "rust_requests": 1,
    }


def test_infrastructure_failure_remains_distinct_and_precedes_shadow() -> None:
    qualification = _qualification_module()

    observation = qualification._failure_observation(
        qualification._Client(error=RuntimeError("controlled"))
    )

    assert observation == {
        "rejected": True,
        "classification": "rust_infrastructure_failure",
        "phase": "transport",
        "python_shadow_reached": False,
        "rust_requests": 1,
    }


def test_operational_artifact_passes_with_explicit_compatibility_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    qualification = _qualification_module()
    revision = "compatibility-revision"
    soak = tmp_path / "soak.json"
    output = tmp_path / "operational.json"
    soak.write_text(
        json.dumps(
            {
                "qualification_revision": revision,
                "decision": "RUST_SSA_AUTHORITY_SOAK_PASS",
                "soak": {
                    "semantic_mismatches": 0,
                    "infrastructure_failures": 0,
                },
                "long_session": {"requests": 1000, "process_startups": 1},
                "concurrency": {"requests": 128, "process_startups": 1},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--revision",
            revision,
            "--soak",
            str(soak),
            "--output",
            str(output),
        ],
    )

    assert qualification.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["decision"] == "RUST_SSA_AUTHORITY_REQUALIFICATION_OPERATIONAL_PASS"
    assert report["milestone"] == "RUST-4.4A_OPERATIONAL_REQUALIFICATION_COMPATIBILITY"
    assert report["historical_contract"] == "RUST-3.6-V2"
    assert report["transport"]["fail_closed_semantic_mismatch"] == "PASS"
    assert {
        name: probe["status"]
        for name, probe in report["fail_closed_probes"].items()
    } == {
        "historical_semantic_corruption": "PASS",
        "canonical_rust_python_mismatch": "PASS",
        "infrastructure_failure": "PASS",
    }
    assert report["authority_probe"] == {
        "production_default_origin": "rust_schema_v2_import",
        "python_authority_rollback_origin": "python_general_ssa_builder",
    }
    assert report["rollback"] == {
        "configuration_only": True,
        "modes": ["PYTHON_SSA_AUTHORITY_RUST_SHADOW", "PYTHON_SSA_ONLY"],
    }
