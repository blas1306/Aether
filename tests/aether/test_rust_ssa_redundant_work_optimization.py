from __future__ import annotations

from copy import deepcopy
import json

import pytest

import aether.ssa.shadow as shadow_module
from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.ir.model import (
    IRBasicBlock,
    IRBranch,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRJump,
    IRLoad,
    IRModule,
    IRParameter,
    IRReturn,
    IRStore,
    IRStructDefinition,
    IRValue,
)
from aether.ir.types import BoolType, IntType
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.general_builder import GeneralSSABuilder
from aether.ssa.model import SSAModule
from aether.ssa.shadow import SSAShadowFailure, canonical_ssa, lower_with_rust_authority


class ReusingClient:
    process_start_count = 1

    def __init__(self, ssa: dict[str, object]) -> None:
        self.response = {"ok": True, "ssa": ssa}
        self.payloads: list[bytes] = []
        self.request_count = 0

    def lower(self, payload: bytes):
        self.payloads.append(payload)
        self.request_count += 1
        return self.response


def _branch_module() -> IRModule:
    int_type = IntType()
    parameter = IRParameter("input", int_type)
    slot = IRValue("slot", int_type)
    zero = IRValue("0", int_type)
    condition = IRValue("1", BoolType())
    one = IRValue("2", int_type)
    two = IRValue("3", int_type)
    loaded = IRValue("4", int_type)
    return IRModule(
        [
            IRFunction(
                "choose",
                [parameter],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(zero, 0),
                            IRCompareOp(condition, "gt", parameter, zero),
                            IRBranch(condition, "then", "else"),
                        ],
                    ),
                    IRBasicBlock(
                        "then",
                        [IRConst(one, 1), IRStore(slot, one), IRJump("merge")],
                    ),
                    IRBasicBlock(
                        "else",
                        [IRConst(two, 2), IRStore(slot, two), IRJump("merge")],
                    ),
                    IRBasicBlock("merge", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )


def _legacy_shadow_dto(module: IRModule) -> dict[str, object]:
    payload = json.dumps(
        ir_module_to_dto(module), sort_keys=True, separators=(",", ":")
    ).encode()
    reconstructed = ir_module_from_dto(json.loads(payload))
    return ssa_module_to_dto(GeneralSSABuilder().build(reconstructed), schema_version=2)


def test_reused_initial_ir_and_verified_builder_output_match_legacy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _branch_module()
    before = ir_module_to_dto(module)
    expected = _legacy_shadow_dto(module)
    client = ReusingClient(deepcopy(expected))
    builder_inputs: list[IRModule] = []
    verified_object_ids: list[int] = []
    original_build = shadow_module.GeneralSSABuilder.build
    original_verify = shadow_module.SSAVerifier.verify

    def observed_build(self, value):
        builder_inputs.append(value)
        return original_build(self, value)

    def observed_verify(self):
        verified_object_ids.append(id(self.module))
        return original_verify(self)

    monkeypatch.setattr(shadow_module.GeneralSSABuilder, "build", observed_build)
    monkeypatch.setattr(shadow_module.SSAVerifier, "verify", observed_verify)

    result, report = lower_with_rust_authority(module, client)

    assert report.classification == "match"
    assert builder_inputs == [module]
    assert len(verified_object_ids) == 2
    assert len(set(verified_object_ids)) == 2
    assert canonical_ssa(ssa_module_to_dto(result, schema_version=2)) == canonical_ssa(expected)
    assert ir_module_to_dto(module) == before


def test_received_rust_dto_is_reused_once_per_compilation_without_state_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _branch_module()
    rust_dto = _legacy_shadow_dto(module)
    client = ReusingClient(rust_dto)
    response_before = deepcopy(client.response)
    serialized: list[SSAModule] = []
    original_to_dto = shadow_module.ssa_module_to_dto

    def observed_to_dto(value, *, schema_version=2):
        serialized.append(value)
        return original_to_dto(value, schema_version=schema_version)

    monkeypatch.setattr(shadow_module, "ssa_module_to_dto", observed_to_dto)

    first, first_report = lower_with_rust_authority(module, client)
    second, second_report = lower_with_rust_authority(module, client)

    assert first_report.classification == second_report.classification == "match"
    assert len(serialized) == 2  # Python result only: once in each compilation.
    assert all(value is not first and value is not second for value in serialized)
    assert client.response == response_before
    assert client.request_count == 2


def test_input_integrity_check_still_fails_closed_on_builder_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = IRModule()
    client = ReusingClient(
        {
            "schema_version": 2,
            "representation": "aether_ssa",
            "functions": [],
            "structs": [],
        }
    )

    def mutating_builder(_self, value: IRModule) -> SSAModule:
        value.structs.append(IRStructDefinition("Mutated", ()))
        return SSAModule()

    monkeypatch.setattr(shadow_module.GeneralSSABuilder, "build", mutating_builder)

    with pytest.raises(SSAShadowFailure) as caught:
        lower_with_rust_authority(module, client)

    assert caught.value.report.classification == "same_input_violation"
    assert caught.value.report.phase == "input_snapshot"
