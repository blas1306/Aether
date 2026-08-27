#!/usr/bin/env python3
"""Requalify the RUST-3.6-V2 operational contract after RUST-4.4."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Callable
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ir.model import IRModule, IRStructDefinition  # noqa: E402
from aether.pipeline import SSAPipeline  # noqa: E402
from aether.ssa.dto import ssa_module_to_dto  # noqa: E402
from aether.ssa.general_builder import GeneralSSABuilder  # noqa: E402
from aether.ssa.model import SSAModule  # noqa: E402
from aether.ssa.verifier import SSAVerifier  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    SSAShadowFailure,
)


class _Client:
    process_start_count = 1

    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.request_count = 0
        self.payloads: list[bytes] = []

    def lower(self, payload: bytes):
        self.request_count += 1
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        return {
            "ok": True,
            "ssa": {
                "schema_version": 2,
                "representation": "aether_ssa",
                "functions": [],
                "structs": [],
            },
        }


def _failure_observation(
    client: _Client,
    *,
    python_shadow_mutator: Callable[[SSAModule], None] | None = None,
) -> dict[str, object]:
    """Observe a production authority failure without changing its policy.

    The optional mutator is qualification-only fault injection around the
    mandatory Python builder.  It lets this historical gate exercise the
    canonical comparison independently now that refinement intercepts its
    original Rust-response corruption.
    """

    python_shadow_calls = 0
    original_build = GeneralSSABuilder.build

    def build_python_shadow(
        builder: GeneralSSABuilder, module: IRModule
    ) -> SSAModule:
        nonlocal python_shadow_calls
        python_shadow_calls += 1
        value = original_build(builder, module)
        if python_shadow_mutator is not None:
            python_shadow_mutator(value)
        return value

    with patch.object(GeneralSSABuilder, "build", build_python_shadow):
        try:
            SSAPipeline(rust_shadow_client=client).run(IRModule())
        except SSAShadowFailure as exc:
            return {
                "rejected": True,
                "classification": exc.report.classification,
                "phase": exc.report.phase,
                "python_shadow_reached": python_shadow_calls == 1,
                "rust_requests": client.request_count,
            }
    return {
        "rejected": False,
        "classification": None,
        "phase": None,
        "python_shadow_reached": python_shadow_calls == 1,
        "rust_requests": client.request_count,
    }


def _historical_semantic_corruption_client() -> _Client:
    return _Client(
        {
            "ok": True,
            "ssa": {
                "schema_version": 2,
                "representation": "aether_ssa",
                "functions": [],
                "structs": [{"name": "Mismatch", "fields": []}],
            },
        }
    )


def _inject_python_shadow_canonical_mismatch(value: SSAModule) -> None:
    # The builder has already produced and verified a valid SSA module.  This
    # qualification-only mutation models a divergent shadow artifact that is
    # still structurally valid, so the production canonical boundary itself
    # must reject it.  No hook or alternate policy is installed in production.
    value.structs.append(IRStructDefinition("CanonicalMismatch", ()))
    SSAVerifier(value).verify()


def _matches_failure(
    observation: dict[str, object],
    *,
    classification: str,
    phase: str,
    python_shadow_reached: bool,
) -> bool:
    return observation == {
        "rejected": True,
        "classification": classification,
        "phase": phase,
        "python_shadow_reached": python_shadow_reached,
        "rust_requests": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--soak", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    soak = json.loads(args.soak.read_text(encoding="utf-8"))
    soak_data = soak.get("soak", {})
    long_session = soak.get("long_session", {})
    concurrency = soak.get("concurrency", {})

    matching = _Client()
    production_default = SSAPipeline(rust_shadow_client=matching)
    default_ssa = production_default.run(IRModule()).ssa_module
    python_only = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.PYTHON_SSA_ONLY
        )
    ).run(IRModule()).ssa_module
    python_authority_client = _Client()
    python_authority = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW
        ),
        rust_shadow_client=python_authority_client,
    )
    python_authority_ssa = python_authority.run(IRModule()).ssa_module
    same_input = (
        len(matching.payloads) == len(python_authority_client.payloads) == 1
        and matching.payloads[0] == python_authority_client.payloads[0]
    )
    historical_mismatch = _historical_semantic_corruption_client()
    historical_observation = _failure_observation(historical_mismatch)
    historical_corruption_applied = (
        historical_mismatch.response["ssa"]["structs"]
        == [{"name": "Mismatch", "fields": []}]
    )
    historical_fail_closed = historical_corruption_applied and _matches_failure(
        historical_observation,
        classification="refinement_verifier_failure",
        phase="refinement_verification",
        python_shadow_reached=False,
    )
    canonical_observation = _failure_observation(
        _Client(),
        python_shadow_mutator=_inject_python_shadow_canonical_mismatch,
    )
    canonical_fail_closed = _matches_failure(
        canonical_observation,
        classification="semantic_mismatch",
        phase="canonical_comparison",
        python_shadow_reached=True,
    )
    infrastructure_observation = _failure_observation(
        _Client(error=RuntimeError("controlled"))
    )
    infrastructure_fail_closed = _matches_failure(
        infrastructure_observation,
        classification="rust_infrastructure_failure",
        phase="transport",
        python_shadow_reached=False,
    )
    workflow = (ROOT / ".github/workflows/rust-ssa-shadow.yml").read_text(
        encoding="utf-8"
    )
    packaging_ok = all(
        (ROOT / relative).is_file()
        for relative in (
            "scripts/package_rust_ssa_shadow.py",
            "scripts/qualify_rust_ssa_authority_platform.py",
            "src/aether/ssa/authority_probe.py",
        )
    )
    ci_ok = all(
        token in workflow
        for token in (
            "promotion-fixtures",
            "historical-116",
            "adversarial",
            "deep-cfg",
            "full-suite-rust-default",
            "require-promoted",
        )
    )
    transport = {
        "persistent": (
            "PASS"
            if long_session.get("process_startups") == 1
            and concurrency.get("process_startups") == 1
            else "BLOCKED"
        ),
        "same_input": "PASS" if same_input else "BLOCKED",
        "fail_closed_semantic_mismatch": (
            "PASS"
            if historical_fail_closed and canonical_fail_closed
            else "BLOCKED"
        ),
        "fail_closed_infrastructure": (
            "PASS" if infrastructure_fail_closed else "BLOCKED"
        ),
        "long_session": (
            f"{long_session.get('requests')} requests / "
            f"{long_session.get('process_startups')} process"
        ),
        "concurrency": (
            f"{concurrency.get('requests')} requests / "
            f"{concurrency.get('process_startups')} process"
        ),
    }
    rollback_equal = (
        ssa_module_to_dto(default_ssa, schema_version=2)
        == ssa_module_to_dto(python_authority_ssa, schema_version=2)
        == ssa_module_to_dto(python_only, schema_version=2)
    )
    passed = (
        soak.get("qualification_revision") == args.revision
        and soak.get("decision") == "RUST_SSA_AUTHORITY_SOAK_PASS"
        and soak_data.get("semantic_mismatches") == 0
        and soak_data.get("infrastructure_failures") == 0
        and set(transport.values())
        == {
            "PASS",
            "1000 requests / 1 process",
            "128 requests / 1 process",
        }
        and rollback_equal
        and production_default.last_returned_ssa_origin == "rust_schema_v2_import"
        and python_authority.last_returned_ssa_origin == "python_general_ssa_builder"
        and packaging_ok
        and ci_ok
    )
    report = {
        "artifact_schema_version": 1,
        "milestone": "RUST-4.4A_OPERATIONAL_REQUALIFICATION_COMPATIBILITY",
        "historical_contract": "RUST-3.6-V2",
        "qualification_revision": args.revision,
        "decision": (
            "RUST_SSA_AUTHORITY_REQUALIFICATION_OPERATIONAL_PASS"
            if passed
            else "RUST_SSA_AUTHORITY_REQUALIFICATION_OPERATIONAL_BLOCKED"
        ),
        "transport": transport,
        "fail_closed_probes": {
            "historical_semantic_corruption": {
                "injection": "unexpected_struct_definition",
                "injection_applied": historical_corruption_applied,
                "expected_classification": "refinement_verifier_failure",
                "expected_phase": "refinement_verification",
                **historical_observation,
                "status": "PASS" if historical_fail_closed else "BLOCKED",
            },
            "canonical_rust_python_mismatch": {
                "injection": "qualification_only_verified_python_shadow_divergence",
                "expected_classification": "semantic_mismatch",
                "expected_phase": "canonical_comparison",
                **canonical_observation,
                "status": "PASS" if canonical_fail_closed else "BLOCKED",
            },
            "infrastructure_failure": {
                "injection": "controlled_transport_exception",
                "expected_classification": "rust_infrastructure_failure",
                "expected_phase": "transport",
                **infrastructure_observation,
                "status": "PASS" if infrastructure_fail_closed else "BLOCKED",
            },
        },
        "rollback": {
            "configuration_only": rollback_equal,
            "modes": [
                "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
                "PYTHON_SSA_ONLY",
            ],
        },
        "authority_probe": {
            "production_default_origin": production_default.last_returned_ssa_origin,
            "python_authority_rollback_origin": python_authority.last_returned_ssa_origin,
        },
        "packaging_and_discovery": "PASS" if packaging_ok else "BLOCKED",
        "ci_integration": "PASS" if ci_ok else "BLOCKED",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(report["decision"])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
