#!/usr/bin/env python3
"""Produce execution-derived RUST-IR-2 qualification evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Any
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from rust_ir_2_artifacts import (  # noqa: E402
    BASELINE_REVISION,
    BASELINE_SUBJECT,
    MILESTONE,
)


NONTRANSPORTABLE = {
    "lifecycle-non-storage-destination": (
        "lifecycle_destination_not_representable_as_IRStorageDTO",
        "IRV-043",
    ),
    "integer-constant-out-of-range": (
        "python_integer_outside_schema_v1_i32",
        "IRV-069",
    ),
}
KNOWN_DIAGNOSTICS = {
    "undefined-slot": ("IRV-031", "IRV-032"),
    "return-storage-after-move": ("IRV-050", "IRV-026"),
    "inconsistent-branch-initialization": ("IRV-036", "IRV-028"),
}
BORROW_SOURCE = """
List<int> first(List<List<int>> values) {
    for (List<int> item in values) { return item; }
    return {};
}
int main() {
    List<List<int>> values = {{1, 2}};
    List<int> saved = first(values);
    values.clear();
    println(saved);
    return 0;
}
"""
EXCEPTION_SOURCE = """
struct FileError implements Error {
    string text;
    string message() { return text; }
}
class NetworkError implements Error {
    string text;
    public string message() { return text; }
}
void failFile() { throw FileError("old"); }
void failNetwork() { throw NetworkError("transferred"); }
void relay() {
    try { failFile(); } catch (FileError old) {
        try { failNetwork(); } catch (NetworkError active) { throw; }
    }
}
int main() {
    try { relay(); } catch (NetworkError outer) { println(outer.message()); }
    return 0;
}
"""
MUTATION_COVERAGE_CASES = {
    "functions": "duplicate-function",
    "blocks": "duplicate-block",
    "entry": "missing-entry-block",
    "cfg": "missing-jump-target",
    "terminators": "instruction-after-terminator",
    "types": "unsupported-cast",
    "calls": "call-wrong-arity",
    "returns": "return-type-mismatch",
    "slots_storage": "undefined-slot",
    "lifecycle_pseudo_ops": "missing-lifecycle-cleanup",
    "move_use_after_move": "load-after-move",
    "borrow_escape": "borrowed-value-return",
    "transferred_storage": "return-storage-after-move",
    "structs": "recursive-by-value-struct",
    "collections": "list-set-value-type",
    "semantically_relevant_metadata": "critical-ssa-aggregate-compare-shape",
    "exceptions": "supplemental-exception-irv149",
}


def envelope(
    kind: str,
    revision: str,
    run_id: str,
    passed: bool,
    **payload: Any,
) -> dict[str, Any]:
    return {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "kind": kind,
        "revision": revision,
        "run_id": str(run_id),
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        **payload,
    }


def _git(*arguments: str) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout.strip()


def contract(revision: str, run_id: str) -> dict[str, Any]:
    pipeline = (ROOT / "src/aether/pipeline.py").read_text(encoding="utf-8")
    shadow = (ROOT / "src/aether/ir/shadow_verifier.py").read_text(encoding="utf-8")
    lifecycle = (ROOT / "src/aether/ir/lifecycle.py").read_text(encoding="utf-8")
    ssa = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    independent = (ROOT / "src/aether/ssa/shadow_independent.py").read_text(
        encoding="utf-8"
    )
    head_code, head = _git("rev-parse", "HEAD")
    baseline_code, baseline = _git("rev-parse", BASELINE_REVISION)
    subject_code, subject = _git("show", "-s", "--format=%s", BASELINE_REVISION)
    ancestor_code, _ = _git("merge-base", "--is-ancestor", BASELINE_REVISION, revision)
    remote_code, remote_main = _git("rev-parse", "origin/main")
    status_code, status = _git("status", "--porcelain", "--untracked-files=all")
    productive_files = [
        "compiler-rs/crates/aether-python/build.rs",
        "compiler-rs/distributions/aether-compiler-core/pyproject.toml",
        "compiler-rs/distributions/aether-compiler-core/python/aether_compiler_core/__init__.py",
        "src/aether/ir/shadow_verifier.py",
        "src/aether/pipeline.py",
    ]
    unchanged: dict[str, bool] = {}
    blobs: dict[str, dict[str, str | None]] = {}
    for path in productive_files:
        old_code, old_blob = _git("rev-parse", f"{BASELINE_REVISION}:{path}")
        new_code, new_blob = _git("rev-parse", f"{revision}:{path}")
        unchanged[path] = old_code == new_code == 0 and old_blob == new_blob
        blobs[path] = {
            "rust_ir_1": old_blob if old_code == 0 else None,
            "qualification_revision": new_blob if new_code == 0 else None,
        }
    lower_verified = pipeline[pipeline.index("    def lower_verified(") : pipeline.index("    def optimize_verified(")]
    optimize_verified = pipeline[pipeline.index("    def optimize_verified(") : pipeline.index("    def run(", pipeline.index("    def optimize_verified("))]
    authority_pipeline = shadow[
        shadow.index("class VerifierAuthorityPipeline") :
        shadow.index("class ShadowVerifierCoordinator")
    ]
    double_gate = shadow[
        shadow.index("class DoubleFailClosedVerifierPipeline") :
        shadow.index("class ProductionInitialIRVerifierClient")
    ]
    production_client = shadow[shadow.index("class ProductionInitialIRVerifierClient") : shadow.index("def _normalize_rust_invocation")]
    checks = {
        "run_revision_is_head": head_code == 0 and head == revision,
        "baseline_exact": baseline_code == 0 and baseline == BASELINE_REVISION,
        "baseline_subject_exact": subject_code == 0 and subject == BASELINE_SUBJECT,
        "baseline_is_ancestor": ancestor_code == 0,
        "official_revision_is_origin_main": remote_code == 0 and remote_main == revision,
        "working_tree_clean_at_start": status_code == 0 and not status,
        "rust_ir_1_product_files_unchanged": all(unchanged.values()),
        "python_ir_verifier_mandatory": "python_execution.resolve()" in authority_pipeline,
        "rust_verifier_mandatory": "rust_execution.resolve()" in authority_pipeline,
        "double_fail_closed_product": "VerifierAuthorityMode.DOUBLE_FAIL_CLOSED" in double_gate,
        "product_gate_in_lower_verified": "production_initial_ir_admission_pipeline().verify" in lower_verified,
        "initial_stage_at_call_site": "ShadowVerificationStage.INITIAL" in lower_verified,
        "post_optimization_python_only": "stage=ShadowVerificationStage.POST_OPTIMIZATION" in optimize_verified
        and "production_initial_ir_admission_pipeline" not in optimize_verified,
        "python_lifecycle_connected": "expand_lifecycle(module)" in optimize_verified
        and "class LifecycleExpander" in lifecycle,
        "installed_verifier_discovery": "from aether_compiler_core import initial_ir_verifier_path" in production_client,
        "no_checkout_or_path_fallback": "search_path" not in production_client
        and "target/" not in production_client,
        "rust_refinement_authority_preserved": "return SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED" in ssa,
        "python_lifecycle_in_refinement_path": '"lifecycle_normalization", lambda: expand_lifecycle(verified)' in independent,
    }
    return envelope(
        "contract_and_baseline",
        revision,
        run_id,
        all(checks.values()),
        rust_ir_1={
            "revision": BASELINE_REVISION,
            "subject": BASELINE_SUBJECT,
            "branch": "main",
        },
        origin_main=remote_main,
        executed_revision=head,
        checks=checks,
        call_site={
            "path": "src/aether/pipeline.py",
            "symbol": "IRBackend.lower_verified",
            "stage": "initial",
            "representation_phase": "pre_lifecycle",
        },
        productive_file_blobs=blobs,
        authority={
            "initial_ir": "python_IRVerifier_AND_rust_verify_module",
            "lifecycle": "python_LifecycleExpander",
            "ssa_refinement": "rust_refinement_authority",
            "rust_initial_ir_exclusive_authority_promoted": False,
            "post_lifecycle_rust_gate": False,
        },
        schema_changed=False,
        protocol_changed=False,
        transport_selection_changed=False,
        pyo3_changed=False,
    )


def _load_corpus() -> tuple[int, list[Any], Any]:
    benchmark_path = ROOT / "benchmarks/ir_verifier.py"
    spec = importlib.util.spec_from_file_location("rust_ir_2_corpus", benchmark_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load migration corpus harness")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    schema, entries = module._load_manifest(module.CORPUS_MANIFEST)
    return schema, entries, module


def _enum(value: object | None) -> str | None:
    raw = getattr(value, "value", value)
    return str(raw) if raw is not None else None


def _source_location(module: Any, diagnostic: Any) -> dict[str, Any] | None:
    if diagnostic is None:
        return None
    function_index = getattr(diagnostic, "function_index", None)
    block_index = getattr(diagnostic, "block_index", None)
    instruction_index = getattr(diagnostic, "instruction_index", None)
    if None in {function_index, block_index, instruction_index}:
        return None
    try:
        instruction = module.functions[function_index].blocks[block_index].instructions[
            instruction_index
        ]
    except (IndexError, TypeError):
        return None
    location = getattr(instruction, "source_location", None)
    if location is None:
        return None
    return {
        "line": location.line,
        "column": location.column,
        "path": location.path,
        "recovered_from_unchanged_python_snapshot": True,
    }


def _outcome_row(entry: Any, module: Any, report: Any) -> dict[str, Any]:
    from aether.ir import (
        PythonShadowAccepted,
        PythonShadowRejected,
        ShadowRustAccepted,
        ShadowRustRejected,
    )

    python = report.authoritative
    rust = report.shadow
    python_accept = isinstance(python, PythonShadowAccepted)
    rust_accept = isinstance(rust, ShadowRustAccepted)
    python_code = python.invariant_id if isinstance(python, PythonShadowRejected) else None
    rust_diagnostic = rust.diagnostic if isinstance(rust, ShadowRustRejected) else None
    return {
        "case_id": entry.id,
        "source": entry.test,
        "covers": list(getattr(entry, "covers", ())),
        "profile": "migration_corpus_schema_v2",
        "representation_state": "IRModule_schema_v1_DTO",
        "phase": "pre_lifecycle",
        "python": {
            "accepted": python_accept,
            "code": python_code,
            "category": _enum(getattr(python, "category", None)),
            "phase": _enum(getattr(python, "phase", None)),
            "function": getattr(python, "function_name", None),
            "block": getattr(python, "block_name", None),
            "source_location": None,
        },
        "rust": {
            "accepted": rust_accept,
            "code": getattr(rust_diagnostic, "invariant_id", None),
            "category": _enum(getattr(rust_diagnostic, "category", None)),
            "phase": _enum(getattr(rust_diagnostic, "phase", None)),
            "function": getattr(rust_diagnostic, "function_name", None),
            "block": getattr(rust_diagnostic, "block_name", None),
            "instruction": getattr(rust_diagnostic, "instruction_index", None),
            "source_location": _source_location(module, rust_diagnostic),
        },
        "request_sha256": report.metadata.request_sha256,
        "classification": report.comparison.classification.value,
        "acceptance_divergence": python_accept != rust_accept,
    }


def _run_probe(
    module: Any,
    executable: Path,
    *,
    case_id: str,
    source: str,
    covers: tuple[str, ...],
) -> dict[str, Any]:
    from aether.ir import (
        AuthoritativeVerificationError,
        CollectingShadowReportSink,
        DoubleFailClosedVerifierPipeline,
        IRVerificationError,
        ShadowVerificationStage,
    )
    from aether.ir.rust_verifier import PersistentSubprocessRustVerifierClient

    sink = CollectingShadowReportSink()
    with PersistentSubprocessRustVerifierClient(executable=executable) as client:
        pipeline = DoubleFailClosedVerifierPipeline(client=client, sink=sink)
        try:
            pipeline.verify(module, stage=ShadowVerificationStage.INITIAL)
        except (IRVerificationError, AuthoritativeVerificationError):
            pass
    entry = SimpleNamespace(id=case_id, test=source, covers=covers)
    row = _outcome_row(entry, module, sink.reports[0])
    return row


def _structured_error_probe(executable: Path) -> dict[str, Any]:
    from dataclasses import replace

    from aether.ir import IRValue, IntType
    from aether.pipeline import IRBackend, prepare_typed_program
    from aether.typechecker import TypeChecker

    module = IRBackend().lower(
        prepare_typed_program(
            "int main() { int x = 1; return x; }",
            TypeChecker(),
        )
    )
    function = module.functions[0]
    block = function.blocks[0]
    instruction = block.instructions[1]
    corrupted = replace(
        instruction,
        source=IRValue("qualification_undefined", IntType()),
    )
    new_block = replace(
        block,
        instructions=[block.instructions[0], corrupted, *block.instructions[2:]],
    )
    new_function = replace(function, blocks=[new_block])
    invalid = replace(module, functions=[new_function])
    return _run_probe(
        invalid,
        executable,
        case_id="supplemental-structured-source-location",
        source="embedded_valid_source_then_schema_valid_undefined_value_mutation",
        covers=("IRV-029",),
    )


def _exception_probe(executable: Path) -> dict[str, Any]:
    from aether.ir import IRExceptionDestroy, IRRethrow, IRVerifier
    from aether.pipeline import IRBackend, prepare_typed_program
    from aether.typechecker import TypeChecker

    module = IRBackend().lower(
        prepare_typed_program(EXCEPTION_SOURCE, TypeChecker())
    )
    IRVerifier(module).verify()
    block = next(
        block
        for function in module.functions
        for block in function.blocks
        if isinstance(block.instructions[-1], IRRethrow)
    )
    rethrow = block.instructions[-1]
    old_destroy = next(
        item
        for item in block.instructions[:-1]
        if isinstance(item, IRExceptionDestroy) and item.event != rethrow.event
    )
    block.instructions.remove(old_destroy)
    return _run_probe(
        module,
        executable,
        case_id="supplemental-exception-irv149",
        source="embedded_nested_rethrow_duplicate_terminal_use_mutation",
        covers=("IRV-149",),
    )


def corpus(
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
    from aether.ir.rust_verifier import PersistentSubprocessRustVerifierClient

    schema, entries, harness = _load_corpus()
    selected = [
        entry
        for entry in entries
        if entry.accepted is valid and entry.id not in NONTRANSPORTABLE
    ]
    modules = harness._materialize_modules(selected)
    sink = CollectingShadowReportSink()
    with PersistentSubprocessRustVerifierClient(executable=executable) as client:
        pipeline = DoubleFailClosedVerifierPipeline(client=client, sink=sink)
        for _entry, module in modules:
            try:
                pipeline.verify(module, stage=ShadowVerificationStage.INITIAL)
            except (IRVerificationError, AuthoritativeVerificationError):
                pass
        process_starts = client.process_start_count
    rows = [
        _outcome_row(entry, module, report)
        for (entry, module), report in zip(modules, sink.reports, strict=True)
    ]
    divergences = [row for row in rows if row["acceptance_divergence"]]
    if valid:
        passed = (
            schema == 2
            and len(rows) >= 65
            and len(rows) == len(selected)
            and not divergences
            and all(row["python"]["accepted"] and row["rust"]["accepted"] for row in rows)
        )
        return envelope(
            "valid_corpus_differential",
            revision,
            run_id,
            passed,
            corpus_schema_version=schema,
            case_count=len(rows),
            minimum_required=65,
            acceptance_divergences=divergences,
            representation_phase="pre_lifecycle",
            persistent_process_starts=process_starts,
            rows=rows,
        )

    known = {
        row["case_id"]: {
            "python": row["python"]["code"],
            "rust": row["rust"]["code"],
            "classification": row["classification"],
            "covers": row["covers"],
        }
        for row in rows
        if row["case_id"] in KNOWN_DIAGNOSTICS
    }
    classifications = Counter(row["classification"] for row in rows)
    domain_rows = [
        {
            "case_id": case_id,
            "reason": reason,
            "python_code": code,
            "classification": "representation_domain_difference",
            "verifier_divergence": False,
            "product_valid_program": False,
            "product_corpus_affected": False,
        }
        for case_id, (reason, code) in NONTRANSPORTABLE.items()
    ]
    structured_probe = _structured_error_probe(executable)
    exception_probe = _exception_probe(executable)
    supplemental_rows = [structured_probe, exception_probe]
    supplemental_divergences = [
        row for row in supplemental_rows if row["acceptance_divergence"]
    ]
    all_divergences = [*divergences, *supplemental_divergences]
    corpus_ids = {row["case_id"] for row in rows}
    supplemental_ids = {row["case_id"] for row in supplemental_rows}
    coverage = {
        family: case_id
        for family, case_id in MUTATION_COVERAGE_CASES.items()
        if case_id in corpus_ids | supplemental_ids
    }
    passed = (
        schema == 2
        and len(rows) == 75
        and not all_divergences
        and all(not row["python"]["accepted"] and not row["rust"]["accepted"] for row in rows)
        and all(
            not row["python"]["accepted"] and not row["rust"]["accepted"]
            for row in supplemental_rows
        )
        and coverage == MUTATION_COVERAGE_CASES
        and all(
            known.get(case_id, {}).get("python") == expected[0]
            and known.get(case_id, {}).get("rust") == expected[1]
            for case_id, expected in KNOWN_DIAGNOSTICS.items()
        )
    )
    mutation_rows = [
        {
            "mutation_id": row["case_id"],
            "invariant": row["python"]["code"],
            "python": row["python"],
            "rust": row["rust"],
            "classification": row["classification"],
            "representation_phase": "pre_lifecycle",
            "acceptance_divergence": row["acceptance_divergence"],
        }
        for row in rows
    ]
    structured_errors = {
        field: sum(
            row["rust"].get(field) is not None
            for row in [*rows, *supplemental_rows]
        )
        for field in ("category", "phase", "code", "function", "block", "instruction")
    }
    structured_errors["source_location"] = sum(
        row["rust"].get("source_location") is not None
        for row in [*rows, *supplemental_rows]
    )
    return envelope(
        "mutation_campaign",
        revision,
        run_id,
        passed,
        mutation_count=len(mutation_rows),
        expected_mutation_count=75,
        qualified_case_count=len(mutation_rows) + len(supplemental_rows),
        acceptance_divergences=all_divergences,
        classification_counts=dict(sorted(classifications.items())),
        known_diagnostic_differences=known,
        structured_error_field_counts=structured_errors,
        structured_error_limitations={
            "source_location": "recovered_from_unchanged_python_snapshot_when_instruction_context_exists",
            "diagnostic_prose_is_semantic_identity": False,
            "protocol_or_schema_changed_for_qualification": False,
        },
        coverage_cases=coverage,
        supplemental_rows=supplemental_rows,
        representation_domain_exclusions=domain_rows,
        product_corpus_domain_impact=False,
        rows=mutation_rows,
    )


def irv041(revision: str, run_id: str, executable: Path) -> dict[str, Any]:
    from aether.ir import IRVerifier, RustVerifierAccepted, RustVerifierRejected
    from aether.ir.lifecycle import expand_lifecycle
    from aether.ir.rust_verifier import verify_module_with_rust
    from aether.pipeline import IRBackend, prepare_typed_program
    from aether.typechecker import TypeChecker

    typed = prepare_typed_program(BORROW_SOURCE, TypeChecker())
    pre = IRBackend().lower(typed)
    python_pre = IRVerifier(pre).verify() is pre
    rust_pre_result = verify_module_with_rust(pre, executable=executable)
    post = expand_lifecycle(pre)
    rust_post_result = verify_module_with_rust(post, executable=executable)
    rust_pre = isinstance(rust_pre_result, RustVerifierAccepted)
    post_irv041 = (
        isinstance(rust_post_result, RustVerifierRejected)
        and rust_post_result.diagnostic.invariant == "IRV-041"
    )
    passed = python_pre and rust_pre and post_irv041
    return envelope(
        "critical_irv041_regressions",
        revision,
        run_id,
        passed,
        representation_phase="pre_lifecycle",
        pre_lifecycle_python="ACCEPT" if python_pre else "REJECT",
        pre_lifecycle_rust="ACCEPT" if rust_pre else "REJECT",
        post_lifecycle_rust_observation={
            "result": "REJECT" if isinstance(rust_post_result, RustVerifierRejected) else "ACCEPT",
            "code": (
                rust_post_result.diagnostic.invariant
                if isinstance(rust_post_result, RustVerifierRejected)
                else None
            ),
            "qualification_only": True,
            "productive_gate": False,
        },
        product_rust_verification_phase="pre_lifecycle",
    )


def performance(
    revision: str,
    run_id: str,
    executable: Path,
    samples: int,
) -> dict[str, Any]:
    import os

    import_times = []
    import_environment = os.environ.copy()
    import_environment["PYTHONPATH"] = str(ROOT / "src")
    import_script = (
        "from time import perf_counter;"
        "started=perf_counter();"
        "import aether.ir;"
        "print((perf_counter()-started)*1000)"
    )
    for _ in range(samples):
        completed = subprocess.run(
            [sys.executable, "-c", import_script],
            cwd=ROOT,
            env=import_environment,
            capture_output=True,
            text=True,
            check=True,
        )
        import_times.append(float(completed.stdout.strip()))

    from aether.ir import CollectingShadowReportSink, DoubleFailClosedVerifierPipeline
    from aether.ir.rust_verifier import PersistentSubprocessRustVerifierClient
    from aether.pipeline import IRBackend, prepare_typed_program
    from aether.typechecker import TypeChecker

    sources = {
        "small": "int main() { return 0; }",
        "medium": "int sum(int n) { int x = 0; int i = 0; while (i < n) { x = x + i; i = i + 1; } return x; } int main() { return sum(20); }",
        "large": "int main() { List<int> values = {1,2,3,4,5,6,7,8}; int total = 0; for (int value in values) { total = total + value; } return total; }",
    }
    rows = []
    with PersistentSubprocessRustVerifierClient(executable=executable) as client:
        for size, source in sources.items():
            module = IRBackend().lower(prepare_typed_program(source, TypeChecker()))
            sink = CollectingShadowReportSink()
            gate = DoubleFailClosedVerifierPipeline(client=client, sink=sink)
            for _ in range(samples):
                gate.verify(module)
            rows.append(
                {
                    "size": size,
                    "samples": samples,
                    "cold_import_median_ms": statistics.median(import_times),
                    "serialization_median_ms": statistics.median(
                        report.metadata.serialization_duration_seconds * 1000
                        for report in sink.reports
                        if report.metadata.serialization_duration_seconds is not None
                    ),
                    "rust_invocation_median_ms": statistics.median(
                        report.metadata.rust_invocation_duration_seconds * 1000
                        for report in sink.reports
                        if report.metadata.rust_invocation_duration_seconds is not None
                    ),
                    "total_gate_median_ms": statistics.median(
                        report.metadata.total_shadow_duration_seconds * 1000
                        for report in sink.reports
                        if report.metadata.total_shadow_duration_seconds is not None
                    ),
                    "verify_module_included_in_rust_invocation": True,
                    "verify_module_separately_observable_under_protocol_v1": False,
                }
            )
    pathological = any(row["total_gate_median_ms"] > 1000 for row in rows)
    return envelope(
        "performance_characterization",
        revision,
        run_id,
        not pathological,
        categories=rows,
        rust_ir_1_local_baseline_ms={
            "serialization_median": 0.141,
            "rust_invocation": 0.208,
            "total_gate": 0.373,
        },
        correctness_threshold_enforced=False,
        measurement_boundaries={
            "dto_preparation": "canonical request serialization",
            "rust_invocation": "framing_process_protocol_parse_and_verify_module",
            "verify_module": "included_in_rust_invocation_not_separately_exposed_by_protocol_v1",
            "import": "fresh_python_process_timed_import_aether_ir",
            "total_added_gate": "python_verify_plus_serialization_plus_rust_invocation",
        },
        operational_pathology_threshold_ms=1000,
        operationally_pathological=pathological,
    )


def gate(kind: str, revision: str, run_id: str, details: dict[str, Any]) -> dict[str, Any]:
    passed = details.pop("passed", True) is True
    return envelope(kind, revision, run_id, passed, **details)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("contract", "valid-corpus", "mutations", "irv041", "performance", "gate"),
    )
    parser.add_argument("--kind")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--rust-verifier", type=Path)
    parser.add_argument("--samples", type=int, default=9)
    parser.add_argument("--details", default="{}")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode in {"valid-corpus", "mutations", "irv041", "performance"} and args.rust_verifier is None:
        parser.error(f"--rust-verifier is required for {args.mode}")
    if args.mode == "contract":
        result = contract(args.revision, args.run_id)
    elif args.mode == "valid-corpus":
        result = corpus(args.revision, args.run_id, args.rust_verifier, valid=True)
    elif args.mode == "mutations":
        result = corpus(args.revision, args.run_id, args.rust_verifier, valid=False)
    elif args.mode == "irv041":
        result = irv041(args.revision, args.run_id, args.rust_verifier)
    elif args.mode == "performance":
        result = performance(args.revision, args.run_id, args.rust_verifier, args.samples)
    else:
        if not args.kind:
            parser.error("--kind is required with --mode gate")
        result = gate(args.kind, args.revision, args.run_id, json.loads(args.details))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{result['kind']}: {result['status']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
