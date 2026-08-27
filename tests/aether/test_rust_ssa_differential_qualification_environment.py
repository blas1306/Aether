from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
QUALIFIER_PATH = (
    ROOT / "scripts/qualify_rust_ssa_shadow_independent_production_promotion.py"
)
CHECKER_PATH = ROOT / "scripts/check_rust_ssa_differential_qualification.py"
PROMOTION_EVIDENCE = (
    ROOT / "docs/compiler/rust_ssa_shadow_independent_production_promotion.json"
)
WORKFLOW = ROOT / ".github/workflows/rust-ssa-shadow.yml"
ENVIRONMENT_VARIABLE = "AETHER_SSA_AUTHORITY_MODE"
DIFFERENTIAL_VALUE = "rust_ssa_authority_python_shadow"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


QUALIFIER = _load("rust_4_5a_qualifier", QUALIFIER_PATH)
CHECKER = _load("rust_4_5a_checker", CHECKER_PATH)


def test_default_probe_environment_is_sanitized_without_a_caller_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENVIRONMENT_VARIABLE, raising=False)
    environment = QUALIFIER._subprocess_environment(differential=False)
    assert ENVIRONMENT_VARIABLE not in environment


def test_differential_caller_cannot_contaminate_default_probe_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, DIFFERENTIAL_VALUE)
    environments = []

    def run(*_args, **kwargs):
        environments.append(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="42 passed", stderr="")

    monkeypatch.setattr(QUALIFIER.subprocess, "run", run)
    result = QUALIFIER._run_policy_tests(differential=False)

    assert result["status"] == "PASS"
    assert result["caller_authority_environment"] == DIFFERENTIAL_VALUE
    assert result["effective_authority_environment"] is None
    assert ENVIRONMENT_VARIABLE not in environments[0]


def test_differential_probe_sets_its_own_explicit_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENVIRONMENT_VARIABLE, raising=False)
    environments = []

    def run(*_args, **kwargs):
        environments.append(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="2 passed", stderr="")

    monkeypatch.setattr(QUALIFIER.subprocess, "run", run)
    result = QUALIFIER._run_policy_tests(differential=True)

    assert result["status"] == "PASS"
    assert result["effective_authority_environment"] == DIFFERENTIAL_VALUE
    assert environments[0][ENVIRONMENT_VARIABLE] == DIFFERENTIAL_VALUE


def _differential_artifact() -> dict[str, object]:
    evidence = json.loads(PROMOTION_EVIDENCE.read_text(encoding="utf-8"))
    default_tests = {"status": "PASS", "returncode": 0}
    differential_tests = {"status": "PASS", "returncode": 0}
    evidence.update(
        {
            "qualification_scope": "differential",
            "production_default_observation": {
                "status": "PASS",
                "mode": "RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED",
                "authority": "rust",
                "refinement_mandatory": True,
                "python_general_ssa_builder_executed": False,
                "canonical_comparison_executed": False,
                "environment": {"effective_value": None},
                "focused_policy_tests": default_tests,
            },
            "differential_mode_observation": {
                "status": "PASS",
                "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
                "authority": "rust",
                "refinement_mandatory": True,
                "python_general_ssa_builder_executed": True,
                "canonical_comparison_executed": True,
                "canonical_mismatch_fail_closed": True,
                "refinement_failure_fail_closed": True,
                "environment": {"effective_value": DIFFERENTIAL_VALUE},
                "focused_differential_tests": differential_tests,
            },
            "differential_qualification_complete": True,
            "decision": "RUST_SSA_DIFFERENTIAL_SHADOW_QUALIFIED",
        }
    )
    return evidence


def test_ci_gate_succeeds_only_for_expected_differential_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "qualified.json"
    path.write_text(json.dumps(_differential_artifact()), encoding="utf-8")
    record = CHECKER.build_record(path)
    assert record["passed"] is True, record["checks"]
    assert record["qualified"] is True
    monkeypatch.setattr("sys.argv", [str(CHECKER_PATH), "--evidence", str(path)])
    assert CHECKER.main() == 0


def test_ci_gate_fails_when_qualification_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = deepcopy(_differential_artifact())
    evidence["differential_mode_observation"]["status"] = "FAIL"
    evidence["differential_qualification_complete"] = False
    evidence["decision"] = "RUST_SSA_DIFFERENTIAL_SHADOW_BLOCKED"
    path = tmp_path / "blocked.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")

    record = CHECKER.build_record(path)
    assert record["qualified"] is False
    assert record["decision"] == "RUST_SSA_DIFFERENTIAL_SHADOW_BLOCKED"
    monkeypatch.setattr("sys.argv", [str(CHECKER_PATH), "--evidence", str(path)])
    assert CHECKER.main() == 1


def test_workflow_gates_decision_before_always_uploading_artifact() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    differential_job = workflow.split(
        "  rust-4-5-mandatory-differential-shadow:", 1
    )[1].split("  rust-4-5-clean-install-platform:", 1)[0]

    assert "--qualification-scope differential" in differential_job
    assert "scripts/check_rust_ssa_differential_qualification.py" in differential_job
    assert differential_job.index("Differential qualification decision gate") < (
        differential_job.index("actions/upload-artifact@v4")
    )
    assert "if: always()" in differential_job
