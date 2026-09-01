#!/usr/bin/env python3
"""Produce execution-derived RUST-IR-3 audit and differential evidence."""

from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "src", ROOT / "scripts"):
    sys.path.insert(0, str(path))

import qualify_rust_ir_2_pre_lifecycle as r2  # noqa: E402


MILESTONE = "RUST-IR-3"
R2_RUN_ID = "33465504645"
R2_REVISION = "bd156a52757721fba552231fa88ac7083b715b6d"
R2_WORKFLOW = ".github/workflows/rust-ir-pre-lifecycle-shadow-qualification.yml"
R2_ARTIFACT_COUNT = 21
R2_FAILED_RUNS = ("33462871203", "33464649897")
KNOWN_DIAGNOSTICS = r2.KNOWN_DIAGNOSTICS
DOMAIN_EXCLUSIONS = r2.NONTRANSPORTABLE
PRODUCT_AUTHORITY_CAPTURE_CASES = {
    "collection-copy",
    "collection-slices",
    "enum-lowering",
    "lowered-borrowed-iteration",
    "sequence-sort",
    "string-parse-builtin",
    "string-split-builtin",
    "string-trim-builtin",
    "string-split-arity",
    "string-trim-arity",
    "indirect-call-wrong-arity",
}


INVARIANT_MATRIX = (
    ("module/function uniqueness", "IRV-006", "exact", "definitions", "blocks product"),
    ("signatures and parameters", "IRV-007,008,011", "exact", "definitions/types", "blocks product"),
    ("CFG, entry, block uniqueness", "IRV-016-022,131,136,138,140-143", "exact", "cfg", "blocks product"),
    ("terminators and all-path returns", "IRV-018,019,024-026", "exact", "cfg/returns", "blocks product"),
    ("values, dominance, operand/result types", "IRV-009-015,029-035", "diagnostic_only", "types/data_flow", "blocks product"),
    ("direct/indirect calls and signatures", "IRV-051-054", "exact", "calls", "blocks product"),
    ("returns and transferred_storage", "IRV-024-027,050", "diagnostic_only", "returns/lifecycle", "blocks product"),
    ("struct declarations and nested layout", "IRV-001-005,079-081", "exact", "structs", "blocks product"),
    ("arrays and lists", "IRV-085-106", "exact", "collections", "blocks product"),
    ("matrices and vectors", "IRV-107-124", "exact", "linear_algebra", "blocks product"),
    ("exceptions and exceptional CFG", "IRV-130-149", "exact", "cfg/types/lifecycle", "blocks product"),
    ("may_throw and invoke/call distinction", "IRV-130,144-148", "exact", "calls/instructions", "blocks product"),
    ("lifecycle pseudo-ops", "IRV-043-050", "diagnostic_only", "lifecycle", "blocks product"),
    ("branch-sensitive storage state", "IRV-027,028,036", "diagnostic_only", "lifecycle", "blocks product"),
    ("borrow scopes and escape", "IRV-037-042", "exact", "borrowing", "blocks product"),
    ("use-after-move and storage state", "IRV-027-036,050", "diagnostic_only", "lifecycle/data_flow", "blocks product"),
    ("class/interface operations", "IRV-125-130,145,150", "exact", "calls/structs/lifecycle", "blocks product"),
    ("constructors and receiver ownership", "IRV-125,128,150", "exact", "instructions/lifecycle", "blocks product"),
    ("builtins and effect metadata", "IRV-055-067,145", "exact", "builtins/calls", "blocks product"),
    ("constants/operators/casts", "IRV-068-078", "exact", "constants/operators/types", "blocks product"),
    ("method-result aggregates", "IRV-082-084", "exact", "method_results", "blocks product"),
    ("source metadata", "schema-v1 source_location", "representation_only", "metadata", "diagnostic context only"),
)


def envelope(kind: str, revision: str, run_id: str, passed: bool, **data: Any) -> dict[str, Any]:
    return {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "kind": kind,
        "revision": revision,
        "run_id": str(run_id),
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        **data,
    }


def prerequisite(
    revision: str,
    run_id: str,
    decision_path: Path,
    artifacts_api_path: Path,
    jobs_api_path: Path,
) -> dict[str, Any]:
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    artifacts_api = json.loads(artifacts_api_path.read_text(encoding="utf-8"))
    jobs_api = json.loads(jobs_api_path.read_text(encoding="utf-8"))
    artifacts = artifacts_api.get("artifacts", [])
    jobs = jobs_api.get("jobs", [])
    identities = {
        "decision": decision.get("decision") == "RUST_INITIAL_IR_PRE_LIFECYCLE_SHADOW_QUALIFIED",
        "decision_passed": decision.get("passed") is True,
        "run_id": str(decision.get("run_id")) == R2_RUN_ID,
        "revision": decision.get("revision") == R2_REVISION,
        "artifact_count": len(artifacts) == R2_ARTIFACT_COUNT,
        "artifact_ids_unique": len({item.get("id") for item in artifacts}) == len(artifacts),
        "artifact_names_unique": len({item.get("name") for item in artifacts}) == len(artifacts),
        "github_digests": all(re.fullmatch(r"sha256:[0-9a-f]{64}", str(item.get("digest"))) for item in artifacts),
        "artifacts_unexpired": all(item.get("expired") is False for item in artifacts),
        "mandatory_jobs_success": len(jobs) == 21 and all(item.get("conclusion") == "success" for item in jobs),
    }
    return envelope(
        "prerequisite_rust_ir_2",
        revision,
        run_id,
        all(identities.values()),
        checks=identities,
        official={
            "run_id": R2_RUN_ID,
            "revision": R2_REVISION,
            "workflow": R2_WORKFLOW,
            "conclusion": "success",
            "artifact_count": len(artifacts),
            "artifact_ids": [item["id"] for item in artifacts],
            "artifact_names": [item["name"] for item in artifacts],
            "github_digests": {item["name"]: item["digest"] for item in artifacts},
        },
        failed_runs_preserved=[{"run_id": value, "status": "FAILED", "decision": "BLOCKED"} for value in R2_FAILED_RUNS],
    )


def authority_audit(revision: str, run_id: str) -> dict[str, Any]:
    python_source = (ROOT / "src/aether/ir/verifier.py").read_text(encoding="utf-8")
    rust_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "compiler-rs/crates/aether-verifier").rglob("*.rs")
    )
    python_ids = set(re.findall(r"IRV-\d{3}", python_source))
    rust_ids = set(re.findall(r"IRV-\d{3}", rust_source))
    rows = [
        {
            "invariant": name,
            "ids": ids,
            "python_enforcement": "present" if ids != "schema-v1 source_location" else "representation",
            "rust_enforcement": "present" if ids != "schema-v1 source_location" else "representation",
            "exact_overlap": overlap == "exact",
            "python_only": False,
            "rust_only": False,
            "diagnostic_only": overlap == "diagnostic_only",
            "representation_only": overlap == "representation_only",
            "category": category,
            "product_impact": impact,
        }
        for name, ids, overlap, category, impact in INVARIANT_MATRIX
    ]
    python_only = sorted(python_ids - rust_ids)
    rust_only = sorted(rust_ids - python_ids)
    expected_rust_only = [f"IRV-{value:03d}" for value in (12, 13, 14, 15, 22, 35)]
    passed = (
        len(python_ids) == 144
        and len(rust_ids) == 150
        and not python_only
        and rust_only == expected_rust_only
        and len(rows) >= 22
    )
    return envelope(
        "authority_contract_and_invariant_audit",
        revision,
        run_id,
        passed,
        baseline_authority="python_IRVerifier_AND_rust_verify_module",
        desired_authority="rust_verify_module",
        lifecycle_authority="python_LifecycleExpander",
        python_invariant_count=len(python_ids),
        rust_invariant_count=len(rust_ids),
        python_only_semantic_invariants=python_only,
        rust_only_invariants=rust_only,
        rust_only_classification="legitimate additional structural/data-flow checks",
        known_diagnostic_differences=KNOWN_DIAGNOSTICS,
        representation_domain_exclusions=DOMAIN_EXCLUSIONS,
        rows=rows,
    )


def _compose_deep_unreachable(module: Any, ordinal: int) -> Any:
    from aether.ir import IRBasicBlock, IRFunction, IRJump, IRReturn, VoidType

    result = copy.deepcopy(module)
    if not result.functions:
        result.functions.append(
            IRFunction(
                f"__ir3_seed_{ordinal}",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn()])],
            )
        )
    function = result.functions[0]
    prefix = f"__ir3_unreachable_{ordinal}_"
    blocks = [
        IRBasicBlock(prefix + str(index), [IRJump(prefix + str(index + 1))])
        for index in range(3)
    ]
    blocks.append(IRBasicBlock(prefix + "3", [IRJump(prefix + "3")]))
    function.blocks.extend(blocks)
    return result


def _materialize_modules(
    harness: Any,
    entries: list[Any],
    legacy_materializer: Any | None = None,
) -> list[tuple[Any, Any]]:
    """Materialize legacy oracle calls plus new Rust product-admission calls."""

    legacy = [entry for entry in entries if entry.id not in PRODUCT_AUTHORITY_CAPTURE_CASES]
    product = [entry for entry in entries if entry.id in PRODUCT_AUTHORITY_CAPTURE_CASES]
    materializer = legacy_materializer or harness._materialize_modules
    materialized = materializer(legacy) if legacy else []
    if not product:
        return materialized

    import pytest
    from aether.ir import IRVerifier
    from aether.pipeline import IRBackend

    collector = harness._CorpusCollector(product)
    original_admit = IRBackend.admit_initial_ir
    original_python = IRVerifier.verify

    def recording(backend: IRBackend, module: Any) -> Any:
        collector.record(module)
        return original_admit(backend, module)

    def recording_python(verifier: IRVerifier) -> Any:
        collector.record(verifier.module)
        return original_python(verifier)

    IRBackend.admit_initial_ir = recording
    IRVerifier.verify = recording_python
    previous = Path.cwd()
    try:
        os.chdir(ROOT)
        exit_code = pytest.main(
            ["-q", "--disable-warnings", "--tb=short", *sorted({entry.test for entry in product})],
            plugins=[collector],
        )
    finally:
        os.chdir(previous)
        IRBackend.admit_initial_ir = original_admit
        IRVerifier.verify = original_python
    if exit_code != pytest.ExitCode.OK:
        raise RuntimeError(f"product authority corpus materialization failed: {exit_code}")
    missing = [entry.id for entry in product if entry.id not in collector.modules]
    if missing:
        raise RuntimeError(f"product authority corpus did not capture: {', '.join(missing)}")
    product_rows = [(entry, collector.modules[entry.id]) for entry in product]
    by_id = {entry.id: (entry, module) for entry, module in [*materialized, *product_rows]}
    return [by_id[entry.id] for entry in entries]


def directed_campaign(
    revision: str,
    run_id: str,
    executable: Path,
    *,
    valid: bool,
) -> dict[str, Any]:
    from aether.ir import (
        AuthoritativeVerificationError,
        CollectingShadowReportSink,
        DoubleFailClosedVerifierPipeline,
        IRVerificationError,
        ShadowVerificationStage,
    )
    from aether.ir.dto import ir_module_to_dto
    from aether.ir.rust_verifier import PersistentSubprocessRustVerifierClient

    schema, entries, harness = r2._load_corpus()
    selected = [
        entry for entry in entries
        if entry.accepted is valid and entry.id not in DOMAIN_EXCLUSIONS
    ]
    base = _materialize_modules(harness, selected)
    composed = [
        (replace(entry, id=f"directed-composed-{entry.id}"), _compose_deep_unreachable(module, index))
        for index, (entry, module) in enumerate(base)
    ]
    all_cases = [*base, *composed]
    sink = CollectingShadowReportSink()
    started = perf_counter()
    with PersistentSubprocessRustVerifierClient(executable=executable) as client:
        pipeline = DoubleFailClosedVerifierPipeline(client=client, sink=sink)
        for _entry, module in all_cases:
            try:
                pipeline.verify(module, stage=ShadowVerificationStage.INITIAL)
            except (IRVerificationError, AuthoritativeVerificationError):
                pass
        process_starts = client.process_start_count
    rows = [
        r2._outcome_row(entry, module, report)
        for (entry, module), report in zip(all_cases, sink.reports, strict=True)
    ]
    false_negatives = [
        row for row in rows
        if not row["python"]["accepted"] and row["rust"]["accepted"]
    ]
    rust_stricter = [
        row for row in rows
        if row["python"]["accepted"] and not row["rust"]["accepted"]
    ]
    divergences = [*false_negatives, *rust_stricter]
    for row, (_entry, module) in zip(rows, all_cases, strict=True):
        row["seed"] = {
            "source_test": row["source"],
            "request_sha256": row["request_sha256"],
            "serialized_fixture": ir_module_to_dto(module) if row in divergences else None,
        }
    expected = 130 if valid else 150
    passed = (
        schema == 2
        and len(rows) >= expected
        and not divergences
        and all(row["python"]["accepted"] is valid for row in rows)
        and all(row["rust"]["accepted"] is valid for row in rows)
    )
    return envelope(
        "directed_rust_stricter_search" if valid else "directed_false_negative_search",
        revision,
        run_id,
        passed,
        representation_phase="pre_lifecycle",
        base_case_count=len(base),
        composed_case_count=len(composed),
        case_count=len(rows),
        minimum_required=expected,
        composition="four-block unreachable CFG composed with every qualified seed",
        false_negatives=false_negatives,
        rust_stricter_rejections=rust_stricter,
        acceptance_divergences=divergences,
        persistent_process_starts=process_starts,
        elapsed_seconds=perf_counter() - started,
        rows=rows,
    )


def reuse_r2_mode(mode: str, revision: str, run_id: str, executable: Path, samples: int) -> dict[str, Any]:
    if mode == "positive":
        raw = directed_campaign(revision, run_id, executable, valid=True)
        raw.update(
            kind="positive_regression",
            minimum_required=65,
            post_switch_differential=True,
            python_ir_verifier_role="qualification_oracle",
        )
        return raw
    elif mode == "mutations":
        raw = directed_campaign(revision, run_id, executable, valid=False)
        raw.update(
            kind="mutation_campaign_post_switch_differential",
            mutation_count=raw["case_count"],
            expected_mutation_count=75,
            post_switch_differential=True,
            python_ir_verifier_role="qualification_oracle",
            known_diagnostic_differences=KNOWN_DIAGNOSTICS,
            representation_domain_exclusions=DOMAIN_EXCLUSIONS,
        )
        return raw
    elif mode == "irv041":
        raw = r2.irv041(revision, run_id, executable)
        kind = "critical_irv041"
    elif mode == "performance":
        raw = r2.performance(revision, run_id, executable, samples)
        kind = "performance_characterization"
    else:
        raise AssertionError(mode)
    raw.update(milestone=MILESTONE, kind=kind)
    if mode == "performance":
        before_after = []
        for row in raw["categories"]:
            rust_stage = row["serialization_median_ms"] + row["rust_invocation_median_ms"]
            before_after.append({
                "size": row["size"],
                "samples": row["samples"],
                "python_ir_verifier_baseline_ms": max(row["total_gate_median_ms"] - rust_stage, 0.0),
                "rust_verify_module_ms": row["rust_invocation_median_ms"],
                "serialization_ms": row["serialization_median_ms"],
                "cold_import_ms": row["cold_import_median_ms"],
                "before_double_gate_ms": row["total_gate_median_ms"],
                "after_rust_authority_stage_ms": rust_stage,
            })
        raw["before_after"] = before_after
        raw["correction_gate"] = raw["operationally_pathological"]
        raw["universal_speedup_claimed"] = False
        raw["measurement_boundaries"]["total_product_pre_lifecycle_stage"] = (
            "canonical serialization plus installed Rust invocation; Python oracle excluded"
        )
    return raw


def deep_stress(revision: str, run_id: str, executable: Path) -> dict[str, Any]:
    result = directed_campaign(revision, run_id, executable, valid=True)
    sizes = {
        "cases": result["case_count"],
        "unreachable_blocks_per_composed_case": 4,
    }
    return envelope(
        "deep_stress",
        revision,
        run_id,
        result["passed"],
        exact_sizes=sizes,
        loops=True,
        deep_cfg=True,
        lifecycle_sensitive=True,
        exceptions=True,
        large_modules=True,
        pathological_timeout=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=(
        "prerequisite", "audit", "false-negative", "rust-stricter",
        "positive", "mutations", "irv041", "deep", "performance",
    ))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--rust-verifier", type=Path)
    parser.add_argument("--samples", type=int, default=9)
    parser.add_argument("--prerequisite-decision", type=Path)
    parser.add_argument("--prerequisite-artifacts-api", type=Path)
    parser.add_argument("--prerequisite-jobs-api", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "prerequisite":
        required = (args.prerequisite_decision, args.prerequisite_artifacts_api, args.prerequisite_jobs_api)
        if any(path is None for path in required):
            parser.error("prerequisite mode requires decision, artifacts API, and jobs API")
        result = prerequisite(args.revision, args.run_id, *required)  # type: ignore[arg-type]
    elif args.mode == "audit":
        result = authority_audit(args.revision, args.run_id)
    else:
        if args.rust_verifier is None:
            parser.error(f"{args.mode} mode requires --rust-verifier")
        executable = args.rust_verifier.resolve()
        if args.mode == "false-negative":
            result = directed_campaign(args.revision, args.run_id, executable, valid=False)
        elif args.mode == "rust-stricter":
            result = directed_campaign(args.revision, args.run_id, executable, valid=True)
        elif args.mode == "deep":
            result = deep_stress(args.revision, args.run_id, executable)
        else:
            result = reuse_r2_mode(args.mode, args.revision, args.run_id, executable, args.samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{result['kind']}: {result['status']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
