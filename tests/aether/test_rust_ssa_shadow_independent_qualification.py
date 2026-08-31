from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
from typing import Mapping

import pytest

from aether.ir.dto import ir_module_to_dto
from aether.ssa import GeneralSSABuilder
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.shadow import (
    SSALoweringAuthorityMode,
    canonical_ssa,
    lower_with_rust_authority,
)
from aether.ssa.shadow_independent import (
    SHADOW_INDEPENDENT_STAGE_MANIFEST,
    ShadowIndependentQualificationFailure,
    _QualificationHooks,
    qualify_shadow_independent_rust_ssa,
)


ROOT = Path(__file__).resolve().parents[2]
R43_PATH = ROOT / "scripts/qualify_rust_ssa_shadow_redundancy.py"
CHECKER_PATH = ROOT / "scripts/check_rust_ssa_shadow_independent.py"
EVIDENCE = (
    ROOT
    / "docs/compiler/rust_ssa_shadow_independent_production_qualification.json"
)
REPORT = (
    ROOT
    / "docs/compiler/RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_QUALIFICATION.md"
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R43 = _load("rust_4_3_for_r44", R43_PATH)
CHECKER = _load("rust_4_4_checker_tests", CHECKER_PATH)


class StaticClient:
    def __init__(self, response: object):
        self.response = response
        self.payloads: list[bytes] = []

    def lower(self, payload: bytes) -> Mapping[str, object]:
        self.payloads.append(payload)
        if isinstance(self.response, BaseException):
            raise self.response
        return deepcopy(self.response)  # type: ignore[return-value]


def _module():
    return R43.fixtures()["diamond"]


def _response(module=None) -> dict[str, object]:
    initial = module or _module()
    return {
        "ok": True,
        "ssa": ssa_module_to_dto(
            GeneralSSABuilder().build(initial), schema_version=2
        ),
    }


def _failure(client, *, module=None, hooks=None):
    with pytest.raises(ShadowIndependentQualificationFailure) as caught:
        qualify_shadow_independent_rust_ssa(
            module or _module(), client, _hooks=hooks
        )
    assert caught.value.trace.accepted is False
    return caught.value.trace


def test_success_trace_proves_shadow_independent_stage_manifest(monkeypatch) -> None:
    response = _response()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Python GeneralSSABuilder was instantiated or run")

    monkeypatch.setattr(GeneralSSABuilder, "__init__", forbidden)
    monkeypatch.setattr(GeneralSSABuilder, "build", forbidden)
    ssa, trace = qualify_shadow_independent_rust_ssa(
        _module(), StaticClient(response)
    )

    assert ssa_module_to_dto(ssa, schema_version=2) == response["ssa"]
    assert trace.accepted is True
    assert trace.completed_stages == SHADOW_INDEPENDENT_STAGE_MANIFEST
    assert set(trace.stage_execution_counts.values()) == {1}
    assert trace.rust_ssa_lowering_executed is True
    assert trace.rust_side_verification_succeeded is True
    assert trace.refinement_verification_executed is True
    assert trace.final_generic_verification_executed is True
    assert trace.python_general_ssa_builder_instantiated is False
    assert trace.python_ssa_lowering_executed is False
    assert trace.canonical_rust_python_comparison_executed is False


def test_production_a_and_qualification_b_return_same_authoritative_rust_ssa() -> None:
    response = _response()
    production, production_report = lower_with_rust_authority(
        _module(), StaticClient(response)
    )
    qualified, qualification_trace = qualify_shadow_independent_rust_ssa(
        _module(), StaticClient(response)
    )

    assert production_report.classification == "match"
    assert qualification_trace.accepted is True
    assert canonical_ssa(ssa_module_to_dto(production, schema_version=2)) == canonical_ssa(
        ssa_module_to_dto(qualified, schema_version=2)
    )


@pytest.mark.parametrize("order", [("A", "B"), ("B", "A"), ("A", "A"), ("B", "B")])
def test_run_order_has_no_mode_or_request_state(order) -> None:
    client = StaticClient(_response())
    outputs = []
    for mode in order:
        if mode == "A":
            ssa, report = lower_with_rust_authority(_module(), client)
            assert report.classification == "match"
        else:
            ssa, trace = qualify_shadow_independent_rust_ssa(_module(), client)
            assert trace.accepted is True
        outputs.append(canonical_ssa(ssa_module_to_dto(ssa, schema_version=2)))
    assert outputs[0] == outputs[1]
    assert len(client.payloads) == 2


def test_rust_4_4_qualification_api_is_preserved_after_production_promotion() -> None:
    assert {mode.value for mode in SSALoweringAuthorityMode} == {
        "python_ssa_only",
        "python_ssa_authority_rust_shadow",
        "rust_ssa_authority_python_shadow",
        "rust_ssa_authority_refinement_verified",
    }
    assert all(
        mode.value != "qualification_only_shadow_independent"
        for mode in SSALoweringAuthorityMode
    )


@pytest.mark.parametrize(
    ("response", "stage", "classification"),
    [
        (RuntimeError("companion stopped"), "rust_ssa_lowering_and_verification", "rust_lowering_or_verifier_failure"),
        ([], "rust_ssa_lowering_and_verification", "rust_lowering_or_verifier_failure"),
        ({"ok": False, "error": "Rust verification failed"}, "rust_ssa_lowering_and_verification", "rust_lowering_or_verifier_failure"),
        ({"ok": True, "ssa": {}}, "schema_v2_import", "schema_v2_import_failure"),
    ],
)
def test_companion_transport_response_and_import_fail_closed(
    response, stage, classification
) -> None:
    trace = _failure(StaticClient(response))
    assert trace.failed_stage == stage
    assert trace.failure_classification == classification
    assert trace.final_generic_verification_executed is False


def test_imported_ssa_verification_failure_is_closed() -> None:
    response = _response()
    response["ssa"]["functions"][0]["blocks"][0]["instructions"].pop()  # type: ignore[index]
    trace = _failure(StaticClient(response))
    assert trace.failed_stage == "imported_ssa_verification"
    assert trace.failure_classification == "imported_ssa_verifier_failure"


def test_input_integrity_failure_precedes_refinement() -> None:
    def mutate_normalized(initial):
        initial.functions.append(initial.functions[0])

    trace = _failure(
        StaticClient(_response()),
        hooks=_QualificationHooks(after_normalization=mutate_normalized),
    )
    assert trace.failed_stage == "same_input_integrity_before_acceptance"
    assert trace.refinement_verification_executed is False


def test_refinement_failure_is_closed_without_python_fallback(monkeypatch) -> None:
    def reject(*_args):
        raise RuntimeError("injected refinement failure")

    monkeypatch.setattr(
        "aether.ssa.shadow_independent.verify_ssa_refinement", reject
    )
    trace = _failure(StaticClient(_response()))
    assert trace.failed_stage == "python_refinement_oracle"
    assert trace.failure_classification == "python_refinement_oracle_rejection"
    assert trace.python_ssa_lowering_executed is False


def test_final_generic_verification_failure_is_closed() -> None:
    def corrupt_after_refinement(ssa):
        ssa.functions[0].blocks[0].instructions.pop()

    trace = _failure(
        StaticClient(_response()),
        hooks=_QualificationHooks(after_refinement=corrupt_after_refinement),
    )
    assert trace.failed_stage == "final_generic_verification"
    assert trace.final_generic_verification_executed is True
    assert trace.failure_classification == "final_generic_verifier_failure"


@pytest.mark.parametrize(
    "expected", ([True, False, True], [False, True, False])
)
def test_valid_invalid_transitions_have_no_stale_acceptance(expected) -> None:
    good = _response()
    bad = deepcopy(good)
    bad["ssa"]["functions"][0]["blocks"][0]["instructions"].pop()  # type: ignore[index]
    clients = [StaticClient(good if valid else bad) for valid in expected]
    accepted = []
    for client in clients:
        try:
            qualify_shadow_independent_rust_ssa(_module(), client)
            accepted.append(True)
        except ShadowIndependentQualificationFailure:
            accepted.append(False)
    assert accepted == list(expected)
    assert all(len(client.payloads) == 1 for client in clients)


def test_qualification_payload_is_the_once_normalized_initial_ir() -> None:
    client = StaticClient(_response())
    qualify_shadow_independent_rust_ssa(_module(), client)
    assert len(client.payloads) == 1
    assert client.payloads[0]
    assert ir_module_to_dto(_module())["schema_version"] == 1


def test_qualification_module_has_no_builder_or_canonical_oracle_dependency() -> None:
    source = (ROOT / "src/aether/ssa/shadow_independent.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "GeneralSSABuilder",
        "canonical_ssa",
        "SSARenamer",
        "PhiPlacement",
        "DominanceFrontier",
        "aether.ssa.builder",
        "aether.ssa.renaming",
    )
    # The builder name occurs only in prose/trace field names; imports and
    # executable calls are what the qualification dependency audit forbids.
    executable_source = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith('"')
    )
    assert "from .general_builder import" not in source
    assert "import GeneralSSABuilder" not in source
    assert "canonical_ssa(" not in executable_source
    assert all(f"import {name}" not in source for name in forbidden[2:])


def test_permanent_checker_recomputes_committed_raw_evidence() -> None:
    record = CHECKER.build_record(EVIDENCE, REPORT)
    assert record["passed"] is True, record["checks"]
    assert record["recomputed"]["semantic_complete"] is True
    assert record["recomputed"]["PRODUCTION_SHADOW_DEPENDENCY_ids"] == []
    assert record["recomputed"]["accepted_by_both_invalid_ids"] == []


def test_checker_does_not_force_zero_dependency_count(tmp_path) -> None:
    import json

    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence["mutation_results"][0][
        "classification"
    ] = "PRODUCTION_SHADOW_DEPENDENCY"
    evidence["mutation_results"][0]["production_a_accepts"] = False
    evidence["mutation_results"][0]["qualification_b_accepts"] = True
    evidence["mutation_results"][0]["current_production_rejects"] = True
    evidence["mutation_results"][0]["shadow_independent_rejects"] = False
    evidence["mutation_results"][0]["decisions_agree"] = False
    evidence["mutation_classification_totals"] = dict(
        __import__("collections").Counter(
            row["classification"] for row in evidence["mutation_results"]
        )
    )
    evidence["PRODUCTION_SHADOW_DEPENDENCY_count"] = 1
    evidence["PRODUCTION_SHADOW_DEPENDENCY_ids"] = [
        evidence["mutation_results"][0]["mutation_id"]
    ]
    evidence["local_semantic_qualification_complete"] = False
    evidence["decision"] = "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_BLOCKED"
    path = tmp_path / "blocked.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    report = tmp_path / "blocked.md"
    report.write_text(
        REPORT.read_text(encoding="utf-8").replace(
            "RUST_SSA_SHADOW_INDEPENDENT_QUALIFICATION_INCOMPLETE",
            "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_BLOCKED",
        ),
        encoding="utf-8",
    )

    record = CHECKER.build_record(path, report)
    assert record["passed"] is True, record["checks"]
    assert record["decision"] == "RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_BLOCKED"
