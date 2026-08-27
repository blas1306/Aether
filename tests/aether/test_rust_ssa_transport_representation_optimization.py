from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import threading

import pytest

import aether.ssa.shadow as shadow_module
from aether.ir.model import (
    IRBasicBlock,
    IRFunction,
    IRModule,
    IRParameter,
    IRReturn,
    IRStructDefinition,
)
from aether.ir.types import IntType
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.general_builder import GeneralSSABuilder
from aether.ssa.shadow import SSAShadowFailure, canonical_ssa, lower_with_rust_authority


ROOT = Path(__file__).resolve().parents[2]


class SharedResponseClient:
    process_start_count = 1

    def __init__(self, responses: dict[str, object] | list[dict[str, object]]) -> None:
        self.responses = responses if isinstance(responses, list) else [responses]
        self.request_count = 0
        self._lock = threading.Lock()

    def lower(self, _payload: bytes):
        with self._lock:
            index = min(self.request_count, len(self.responses) - 1)
            self.request_count += 1
            return self.responses[index]


def _module() -> IRModule:
    integer = IntType()
    parameter = IRParameter("original_parameter", integer)
    return IRModule(
        [
            IRFunction(
                "identity",
                [parameter],
                integer,
                [IRBasicBlock("entry", [IRReturn(parameter)])],
            )
        ],
        [IRStructDefinition("Nested", ())],
    )


def _response(module: IRModule | None = None) -> dict[str, object]:
    value = GeneralSSABuilder().build(module or _module())
    return {"ok": True, "ssa": ssa_module_to_dto(value, schema_version=2)}


def _legacy_canonical(dto: dict[str, object]) -> dict[str, object]:
    result = json.loads(json.dumps(dto))
    for function in result["functions"]:
        names: dict[str, str] = {}

        def bind(value):
            if isinstance(value, dict) and value.get("tag") in {"value", "parameter"}:
                names.setdefault(value["name"], f"v{len(names)}")

        for parameter in function["parameters"]:
            bind(parameter)
        for block in function["blocks"]:
            for instruction in block["instructions"]:
                keys = (
                    ("event",)
                    if instruction["kind"] == "catch_entry"
                    else ("result", "exception")
                    if instruction["kind"]
                    in {"invoke", "invoke_indirect", "invoke_interface"}
                    else ("result",)
                )
                for key in keys:
                    bind(instruction.get(key))

        def rewrite(value):
            if isinstance(value, dict):
                if (
                    value.get("tag") in {"value", "parameter"}
                    and value.get("name") in names
                ):
                    value["name"] = names[value["name"]]
                for child in value.values():
                    rewrite(child)
            elif isinstance(value, list):
                for child in value:
                    rewrite(child)

        rewrite(function)
        for block in function["blocks"]:
            for instruction in block["instructions"]:
                if instruction["kind"] == "phi":
                    instruction["incoming"].sort(key=lambda item: item["block"])
    return result


def test_fused_canonical_clone_is_legacy_equivalent_and_isolated() -> None:
    dto = _response()["ssa"]
    before = deepcopy(dto)

    optimized = canonical_ssa(dto)

    assert optimized == _legacy_canonical(dto)
    assert dto == before
    optimized["structs"].append({"name": "Mutation", "fields": []})
    optimized["functions"][0]["parameters"][0]["name"] = "mutated"
    assert dto == before


def test_owned_python_dto_canonicalization_is_legacy_equivalent() -> None:
    dto = deepcopy(_response()["ssa"])
    expected = _legacy_canonical(dto)

    returned = shadow_module._canonicalize_owned_ssa(dto)

    assert returned is dto
    assert returned == expected


def test_mutating_both_lane_results_cannot_contaminate_next_compilation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    response = _response(module)
    response_before = deepcopy(response)
    client = SharedResponseClient(response)
    python_results = []
    original_build = shadow_module.GeneralSSABuilder.build

    def capture_build(self, value):
        result = original_build(self, value)
        python_results.append(result)
        return result

    monkeypatch.setattr(shadow_module.GeneralSSABuilder, "build", capture_build)
    imported, first_report = lower_with_rust_authority(module, client)
    imported.structs.append(IRStructDefinition("ImportedMutation", ()))
    python_results[0].structs.append(IRStructDefinition("ShadowMutation", ()))

    second, second_report = lower_with_rust_authority(module, client)

    assert first_report.classification == second_report.classification == "match"
    assert [definition.name for definition in second.structs] == ["Nested"]
    assert [definition.name for definition in python_results[1].structs] == ["Nested"]
    assert response == response_before


def test_failed_then_successful_compilation_does_not_retain_dto_mutation() -> None:
    module = _module()
    valid = _response(module)
    mismatching = deepcopy(valid)
    mismatching["ssa"]["structs"].append({"name": "Mismatch", "fields": []})
    mismatch_before = deepcopy(mismatching)
    client = SharedResponseClient([mismatching, valid])

    with pytest.raises(SSAShadowFailure, match="refinement_verifier_failure"):
        lower_with_rust_authority(module, client)
    result, report = lower_with_rust_authority(module, client)

    assert report.classification == "match"
    assert [definition.name for definition in result.structs] == ["Nested"]
    assert mismatching == mismatch_before


def test_concurrent_callers_share_no_canonical_or_imported_state() -> None:
    module = _module()
    response = _response(module)
    response_before = deepcopy(response)
    client = SharedResponseClient(response)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _index: lower_with_rust_authority(module, client), range(32)
            )
        )

    assert all(report.classification == "match" for _value, report in results)
    assert len({id(value) for value, _report in results}) == 32
    assert response == response_before
    assert client.request_count == 32


def test_companion_serializes_typed_schema_v2_without_json_value_tree() -> None:
    source = (
        ROOT
        / "compiler-rs/crates/aether-verifier/src/bin/aether-ssa-shadow.rs"
    ).read_text(encoding="utf-8")

    assert "ssa: aether_ir::wire::SSAModuleV2DTO" in source
    assert "serde_json::to_value(owned.to_schema_v2())" not in source
    assert "ssa: owned.to_schema_v2()" in source
