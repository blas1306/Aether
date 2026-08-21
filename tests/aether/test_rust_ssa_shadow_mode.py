from __future__ import annotations

import json

import pytest

from aether.ir.model import IRModule
from aether.pipeline import SSAPipeline
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.shadow import (
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    SSAShadowFailure,
    lower_with_rust_shadow,
)


class StubClient:
    process_start_count = 1

    def __init__(self, response):
        self.response = response
        self.request_count = 0
        self.payloads = []

    def lower(self, payload: bytes):
        self.request_count += 1
        self.payloads.append(payload)
        return self.response


def empty_response():
    return {"ok": True, "ssa": {"schema_version": 2, "representation": "aether_ssa", "functions": [], "structs": []}}


def test_python_only_is_default_and_never_requires_rust() -> None:
    result = SSAPipeline().run(IRModule()).ssa_module
    assert ssa_module_to_dto(result) == empty_response()["ssa"]


def test_shadow_returns_python_authority_and_uses_one_exact_snapshot() -> None:
    module = IRModule()
    client = StubClient(empty_response())
    expected_snapshot = json.dumps(
        __import__("aether.ir.dto", fromlist=["ir_module_to_dto"]).ir_module_to_dto(module),
        sort_keys=True, separators=(",", ":"),
    ).encode()
    result, report = lower_with_rust_shadow(module, client)
    assert report.classification == "match"
    assert client.payloads == [expected_snapshot]
    assert result is not client.response["ssa"]


def test_mismatch_and_infrastructure_fail_closed_with_structured_report() -> None:
    malformed = StubClient({"ok": True, "ssa": {"wrong": True}})
    with pytest.raises(SSAShadowFailure) as caught:
        lower_with_rust_shadow(IRModule(), malformed)
    assert caught.value.report.classification == "malformed_rust_response"
    assert len(str(caught.value)) < 1000

    mismatch = StubClient({"ok": True, "ssa": {
        "schema_version": 2, "representation": "aether_ssa", "functions": [],
        "structs": [{"name": "Unexpected", "fields": []}],
    }})
    with pytest.raises(SSAShadowFailure) as semantic:
        lower_with_rust_shadow(IRModule(), mismatch)
    assert semantic.value.report.classification == "semantic_mismatch"
    assert semantic.value.report.first_difference == "$.structs"


def test_pipeline_shadow_selection_is_explicit() -> None:
    client = StubClient(empty_response())
    configuration = SSALoweringAuthorityConfiguration(
        SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW
    )
    result = SSAPipeline(authority_configuration=configuration, rust_shadow_client=client).run(IRModule())
    assert result.ssa_module.functions == []
    assert client.request_count == 1
