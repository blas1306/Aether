from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.ir.lifecycle import expand_lifecycle
from aether.ir.model import IRModule, IRStructDefinition
from aether.pipeline import SSAPipeline
from aether.ssa import GeneralSSABuilder
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto
import aether.ssa.shadow as shadow
from aether.ssa.shadow import (
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    SSAShadowFailure,
    diagnostic_inject_post_rust_verification_corruption,
    lower_with_rust_authority,
    qualify_with_python_refinement_oracle,
)


ROOT = Path(__file__).resolve().parents[2]
RUST_4_0 = ROOT / "scripts/qualify_rust_ssa_independent_authority.py"
RUST_4_1 = ROOT / "scripts/qualify_rust_ssa_independent_refinement_verifier.py"
CHECKER = ROOT / "scripts/check_rust_ssa_refinement_production_integration.py"
EVIDENCE = ROOT / "docs/compiler/rust_ssa_refinement_production_integration.json"
REPORT = ROOT / "docs/compiler/RUST_SSA_REFINEMENT_PRODUCTION_INTEGRATION.md"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R40 = _load("rust_4_0_production_tests", RUST_4_0)
R41 = _load("rust_4_1_production_tests", RUST_4_1)


class StaticClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.payloads: list[dict[str, object]] = []

    @property
    def process_start_count(self) -> int:
        return 1

    @property
    def request_count(self) -> int:
        return len(self.payloads)

    def lower(self, payload: bytes) -> dict[str, object]:
        self.payloads.append(json.loads(payload))
        return deepcopy(self.response)


def _response(module: IRModule) -> dict[str, object]:
    normalized = expand_lifecycle(module)
    return {
        "ok": True,
        "ssa": ssa_module_to_dto(
            GeneralSSABuilder().build(normalized), schema_version=2
        ),
    }


def _mutator(name: str):
    case = next(case for case in R41.mutation_cases() if case.name == name)

    def mutate(ssa):
        dto = ssa_module_to_dto(ssa, schema_version=2)
        case.mutate(dto)
        return ssa_module_from_dto(dto)

    return mutate


@pytest.mark.parametrize(
    ("mutation", "fixture"),
    [
        ("missing_phi", "branch"),
        ("extra_phi", "branch"),
        ("wrong_phi_incoming_value", "branch"),
        ("wrong_return", "branch"),
        ("missing_preserved_instruction", "branch"),
        ("duplicated_preserved_instruction", "branch"),
        ("retained_unreachable_block", "branch"),
        ("wrong_branch_target", "branch"),
        ("wrong_call_target", "effects"),
        ("wrong_call_argument", "effects"),
        ("incorrect_promoted_value", "branch"),
    ],
)
def test_injected_corruption_fails_at_refinement_before_python_shadow(
    monkeypatch: pytest.MonkeyPatch, mutation: str, fixture: str
) -> None:
    module = R40.branch_module() if fixture == "branch" else R41.effect_module()
    client = StaticClient(_response(module))
    shadow_calls = 0

    def forbidden_shadow(_self, _module):
        nonlocal shadow_calls
        shadow_calls += 1
        raise AssertionError("Python shadow ran after refinement failure")

    monkeypatch.setattr(shadow.GeneralSSABuilder, "build", forbidden_shadow)
    with pytest.raises(SSAShadowFailure) as caught:
        diagnostic_inject_post_rust_verification_corruption(
            module, client, _mutator(mutation)
        )

    assert caught.value.report.classification == "python_refinement_oracle_rejection"
    assert caught.value.report.phase == "python_refinement_oracle"
    assert shadow_calls == 0


def test_rust_refinement_and_python_share_one_normalized_input_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = R40.branch_module()
    client = StaticClient(_response(module))
    observed: dict[str, object] = {}
    original_refinement = shadow.verify_ssa_refinement
    original_build = shadow.GeneralSSABuilder.build

    def capture_refinement(initial, ssa):
        observed["refinement"] = initial
        return original_refinement(initial, ssa)

    def capture_shadow(self, initial):
        observed["shadow"] = initial
        return original_build(self, initial)

    monkeypatch.setattr(shadow, "verify_ssa_refinement", capture_refinement)
    monkeypatch.setattr(shadow.GeneralSSABuilder, "build", capture_shadow)
    qualify_with_python_refinement_oracle(module, client)

    assert observed["refinement"] is observed["shadow"]
    assert client.payloads == [ir_module_to_dto(observed["refinement"])]


def test_mutation_between_rust_and_refinement_fails_same_input() -> None:
    module = expand_lifecycle(R40.branch_module())
    response = _response(module)

    class MutatingClient(StaticClient):
        def lower(self, payload: bytes) -> dict[str, object]:
            value = super().lower(payload)
            module.structs.append(IRStructDefinition("Injected", ()))
            return value

    with pytest.raises(SSAShadowFailure) as caught:
        lower_with_rust_authority(module, MutatingClient(response))

    assert caught.value.report.classification == "same_input_violation"
    assert caught.value.report.phase == "before_refinement_verification"


def test_mutation_between_refinement_and_python_fails_same_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = expand_lifecycle(R40.branch_module())
    original = shadow.verify_ssa_refinement

    def mutating_refinement(initial, ssa):
        result = original(initial, ssa)
        initial.structs.append(IRStructDefinition("Injected", ()))
        return result

    monkeypatch.setattr(shadow, "verify_ssa_refinement", mutating_refinement)
    with pytest.raises(SSAShadowFailure) as caught:
        qualify_with_python_refinement_oracle(
            module, StaticClient(_response(module))
        )

    assert caught.value.report.classification == "same_input_violation"
    assert caught.value.report.phase == "before_python_shadow"


def test_stale_or_reconstructed_different_ir_is_rejected_before_shadow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = expand_lifecycle(R40.branch_module())
    different_dto = ir_module_to_dto(current)
    different_dto["functions"][0]["name"] = "stale_compilation"
    different = ir_module_from_dto(different_dto)
    stale_response = _response(different)
    called = False

    def forbidden(_self, _module):
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(shadow.GeneralSSABuilder, "build", forbidden)
    with pytest.raises(SSAShadowFailure) as caught:
        qualify_with_python_refinement_oracle(
            current, StaticClient(stale_response)
        )

    assert caught.value.report.classification == "python_refinement_oracle_rejection"
    assert called is False


def test_injection_state_does_not_leak_to_next_compilation() -> None:
    module = R40.branch_module()
    client = StaticClient(_response(module))
    with pytest.raises(SSAShadowFailure, match="python_refinement_oracle_rejection"):
        diagnostic_inject_post_rust_verification_corruption(
            module, client, _mutator("wrong_return")
        )

    returned, report = lower_with_rust_authority(module, client)
    assert report.classification == "match"
    assert ssa_module_to_dto(returned, schema_version=2) == client.response["ssa"]


def test_refinement_runs_only_in_explicit_qualification_oracle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = shadow.verify_ssa_refinement
    import aether.ssa.shadow_independent as shadow_independent

    def capture(initial, ssa):
        nonlocal calls
        calls += 1
        return original(initial, ssa)

    monkeypatch.setattr(shadow, "verify_ssa_refinement", capture)
    monkeypatch.setattr(shadow_independent, "verify_ssa_refinement", capture)
    module = IRModule()
    response = _response(module)

    rust_authority = SSAPipeline(rust_shadow_client=StaticClient(response))
    rust_authority.run(module)
    assert calls == 0

    differential = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
        ),
        rust_shadow_client=StaticClient(response),
    )
    differential.run(module)
    assert calls == 0

    python_authority = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW
        ),
        rust_shadow_client=StaticClient(response),
    )
    python_authority.run(module)
    python_only = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.PYTHON_SSA_ONLY
        )
    )
    python_only.run(module)
    assert calls == 0

    qualify_with_python_refinement_oracle(module, StaticClient(response))
    assert calls == 1


def test_ordinary_return_shape_and_protocol_are_unchanged() -> None:
    module = IRModule()
    response = {
        "ok": True,
        "ssa": {
            "schema_version": 2,
            "representation": "aether_ssa",
            "functions": [],
            "structs": [],
        },
    }
    expected_response = deepcopy(response)
    returned, report = lower_with_rust_authority(module, StaticClient(response))

    assert response == expected_response
    assert set(report.__dict__) == {
        "classification",
        "phase",
        "function",
        "block",
        "first_difference",
        "python_fragment",
        "rust_fragment",
        "source_location",
        "python_seconds",
        "rust_seconds",
        "comparison_seconds",
        "performance",
    }
    assert report.classification == "match"
    assert ssa_module_to_dto(returned, schema_version=2) == response["ssa"]


def test_qualification_oracle_boundaries_execute_in_fail_closed_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = IRModule()
    client = StaticClient(_response(module))
    events: list[str] = []
    original_lower = client.lower
    original_import = shadow.ssa_module_from_dto
    original_verify = shadow.SSAVerifier.verify
    original_refinement = shadow.verify_ssa_refinement
    original_build = shadow.GeneralSSABuilder.build
    original_difference = shadow._difference

    def lower(payload):
        events.append("rust_lowering")
        return original_lower(payload)

    def import_ssa(dto):
        events.append("schema_v2_import")
        return original_import(dto)

    def verify(self):
        events.append("ssa_verification")
        return original_verify(self)

    def refinement(initial, ssa):
        events.append("refinement")
        return original_refinement(initial, ssa)

    def python_shadow(self, initial):
        events.append("python_shadow")
        return original_build(self, initial)

    def compare(left, right, path="$"):
        if path == "$":
            events.append("canonical_comparison")
        return original_difference(left, right, path)

    client.lower = lower  # type: ignore[method-assign]
    monkeypatch.setattr(shadow, "ssa_module_from_dto", import_ssa)
    monkeypatch.setattr(shadow.SSAVerifier, "verify", verify)
    monkeypatch.setattr(shadow, "verify_ssa_refinement", refinement)
    monkeypatch.setattr(shadow.GeneralSSABuilder, "build", python_shadow)
    monkeypatch.setattr(shadow, "_difference", compare)

    qualify_with_python_refinement_oracle(module, client)

    first_ssa_verification = events.index("ssa_verification")
    assert events.index("rust_lowering") < events.index("schema_v2_import")
    assert events.index("schema_v2_import") < first_ssa_verification
    assert first_ssa_verification < events.index("refinement")
    assert events.index("refinement") < events.index("python_shadow")
    assert events.index("python_shadow") < events.index("canonical_comparison")


def test_checked_in_rust_4_2_evidence_remains_historical_after_promotion() -> None:
    checker = _load("rust_4_2_checker_tests", CHECKER)
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    record = checker.build_record(EVIDENCE, REPORT)
    assert evidence["decision"] == (
        "RUST_SSA_REFINEMENT_PRODUCTION_INTEGRATION_QUALIFIED"
    )
    assert record["checks"]["identity"] is True
    assert record["checks"]["production_fail_closed"] is False


def test_checker_rejects_claim_that_python_shadow_is_optional(tmp_path: Path) -> None:
    checker = _load("rust_4_2_checker_negative", CHECKER)
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence["production_invariants"]["python_shadow"] = "optional"
    corrupt = tmp_path / "evidence.json"
    corrupt.write_text(json.dumps(evidence), encoding="utf-8")
    record = checker.build_record(corrupt, REPORT)
    assert record["passed"] is False
    assert record["checks"]["production_fail_closed"] is False
