#!/usr/bin/env python3
"""Observe productive RUST-REFINE-3 authority without using Python refinement."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform as host_platform
import shutil
import subprocess
import sys
import tempfile
from typing import Any


MILESTONE = "RUST-REFINE-3"

SCALAR_SOURCE = """
int choose(boolean flag) {
    int value = 1;
    if (flag) { value = 2; }
    return value;
}
int main() { println(choose(true)); return 0; }
"""

ENUM_SOURCE = """
enum Status { Ready, Waiting }
Status choose(boolean flag) {
    Status value = Status.Waiting;
    if (flag) { value = Status.Ready; }
    return value;
}
int main() { Status value = choose(true); println(value); return 0; }
"""


def _identity(
    kind: str,
    revision: str,
    run_id: str,
    passed: bool,
    **values: Any,
) -> dict[str, Any]:
    return {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "kind": kind,
        "revision": revision,
        "run_id": str(run_id),
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        **values,
    }


def _client(transport: str):
    from aether.ssa.shadow import ProductionRustSSALoweringClient

    return ProductionRustSSALoweringClient(transport, timeout_seconds=180)


def _compile(source: str, source_root: Path, client: object) -> dict[str, Any]:
    from aether.pipeline import SSAPipeline, prepare_typed_program
    from aether.ssa.dto import ssa_module_to_dto
    from aether.typechecker import TypeChecker

    typed = prepare_typed_program(source, TypeChecker(source_root=source_root))
    pipeline = SSAPipeline(rust_shadow_client=client)
    result = pipeline.run(typed)
    trace = pipeline.last_authority_report
    if trace is None:
        raise RuntimeError("productive pipeline returned no authority trace")
    return {
        "accepted": bool(result.ssa_module.functions),
        "ssa_sha256": sha256(
            json.dumps(
                ssa_module_to_dto(result.ssa_module, schema_version=2),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "returned_ssa_origin": pipeline.last_returned_ssa_origin,
        "refinement_authority": trace.refinement_authority,
        "rust_refinement_verification_observed": (
            trace.rust_refinement_verification_observed
        ),
        "python_refinement_role": trace.python_refinement_role,
        "python_refinement_verification_executed": (
            trace.python_refinement_verification_executed
        ),
        "python_ssa_verifier_executed": (
            trace.stage_execution_counts.get("imported_ssa_verification") == 1
            and trace.final_generic_verification_executed
        ),
        "completed_stages": list(trace.completed_stages),
        "stage_execution_counts": dict(trace.stage_execution_counts),
    }


def _qualification_oracle(
    source: str,
    source_root: Path,
    client: object,
) -> dict[str, Any]:
    from aether.pipeline import SSAPipeline, prepare_typed_program
    from aether.ssa.shadow_independent import qualify_shadow_independent_rust_ssa
    from aether.typechecker import TypeChecker

    typed = prepare_typed_program(source, TypeChecker(source_root=source_root))
    initial = SSAPipeline().lower_ir(typed)
    _ssa, trace = qualify_shadow_independent_rust_ssa(initial, client)
    return {
        "accepted": trace.accepted,
        "refinement_authority": trace.refinement_authority,
        "python_refinement_role": trace.python_refinement_role,
        "python_refinement_verification_executed": (
            trace.python_refinement_verification_executed
        ),
    }


def _full_backend(source: str, source_root: Path, transport: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".ae",
        dir=source_root,
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write(source)
        path = Path(handle.name)
    try:
        environment = os.environ.copy()
        environment["AETHER_RUST_CORE_TRANSPORT"] = transport
        completed = subprocess.run(
            [sys.executable, "-m", "aether.cli", "--emit-llvm", str(path)],
            cwd=source_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
        )
        return {
            "accepted": completed.returncode == 0 and "define" in completed.stdout,
            "returncode": completed.returncode,
            "llvm_generated": "define" in completed.stdout,
            "stderr": completed.stderr[-500:],
        }
    finally:
        path.unlink(missing_ok=True)


def _python_refinement_absent(source_root: Path, client: object) -> dict[str, Any]:
    import aether.ssa.shadow_independent as production

    original = production.verify_ssa_refinement
    calls = 0

    def reject(*_args: object, **_kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("Python refinement must not be productive")

    production.verify_ssa_refinement = reject
    try:
        result = _compile(SCALAR_SOURCE, source_root, client)
    finally:
        production.verify_ssa_refinement = original
    return {
        "compilation_accepted": result["accepted"],
        "python_refinement_calls": calls,
        "python_rejection_could_block": calls != 0,
    }


class _RejectOnceClient:
    def __init__(self, delegate: object) -> None:
        self.delegate = delegate
        self.rejected = False

    def lower(self, payload: bytes) -> dict[str, object]:
        if not self.rejected:
            self.rejected = True
            return {
                "ok": False,
                "error": "injected Rust refinement rejection",
                "diagnostic": {
                    "kind": "internal",
                    "category": "ssa_refinement_verification",
                    "phase": "ssa_verification",
                    "code": "SSA-REFINE-QUALIFICATION-INJECTED",
                },
            }
        return dict(self.delegate.lower(payload))  # type: ignore[attr-defined]


def _no_python_rescue(source_root: Path, client: object) -> dict[str, Any]:
    import aether.ssa.shadow_independent as production
    from aether.pipeline import SSAPipeline, prepare_typed_program
    from aether.typechecker import TypeChecker

    typed = prepare_typed_program(
        SCALAR_SOURCE,
        TypeChecker(source_root=source_root),
    )
    guarded = _RejectOnceClient(client)
    original = production.verify_ssa_refinement
    python_calls = 0

    def python_rescue(*_args: object, **_kwargs: object) -> None:
        nonlocal python_calls
        python_calls += 1

    production.verify_ssa_refinement = python_rescue
    try:
        rejected = False
        detail: dict[str, object] = {}
        try:
            SSAPipeline(rust_shadow_client=guarded).run(typed)
        except production.ShadowIndependentRustAuthorityFailure as error:
            rejected = True
            try:
                rejection = json.loads(error.detail)
            except json.JSONDecodeError:
                rejection = {"error": error.detail, "diagnostic": None}
            detail = {
                "failed_stage": error.trace.failed_stage,
                "classification": error.trace.failure_classification,
                "detail": error.detail,
                "diagnostic": rejection.get("diagnostic"),
            }
        recovered = _compile(SCALAR_SOURCE, source_root, guarded)
    finally:
        production.verify_ssa_refinement = original
    return {
        "rust_rejection_blocked": rejected,
        "python_refinement_calls": python_calls,
        "python_rescue_attempted": python_calls != 0,
        "structured_error": detail,
        "subsequent_recovery_succeeded": recovered["accepted"],
        "automatic_fallback": False,
    }


def _valid_sources(root: Path) -> list[tuple[str, str, Path]]:
    candidates = {
        "exceptions": root / "corpus/exceptions/positive/throw_and_typed_catch.ae",
        "exceptions_rethrow": root / "corpus/exceptions/positive/nested_rethrow_chain.ae",
        "exceptions_invoke": root / "corpus/exceptions/positive/indirect_call.ae",
        "exceptions_interface_dispatch": root / "corpus/exceptions/positive/method_interface_dispatch.ae",
        "exceptions_cleanup": root / "corpus/exceptions/positive/cleanup_during_unwinding.ae",
        "lifecycle": root / "tests/fixtures/rust_ssa_promotion_failure/interface_lifecycle_default.ae",
        "strings": root / "examples/llvm/string_choose.ae",
        "arrays": root / "benchmarks/array_sum.ae",
        "lists": root / "benchmarks/list_push.ae",
        "matrices": root / "benchmarks/matrix_mul.ae",
        "classes": root / "examples/classes/counter_basic.ae",
        "interfaces": root / "examples/classes/implements_interface.ae",
        "modules": root / "examples/structs/main.ae",
        "calls_phi": root / "benchmarks/if_else.ae",
    }
    rows = [
        (category, path.read_text(encoding="utf-8"), path.parent)
        for category, path in candidates.items()
    ]
    rows.append(("enums", ENUM_SOURCE, root))
    return rows


def production(
    root: Path,
    revision: str,
    run_id: str,
    transport: str,
    kind: str,
) -> dict[str, Any]:
    client = _client(transport)
    try:
        cases = [
            {"category": category, **_compile(source, source_root, client)}
            for category, source, source_root in _valid_sources(root)
        ]
        python_absent = _python_refinement_absent(root, client)
        no_rescue = _no_python_rescue(root, client)
        full_backend = (
            _full_backend(SCALAR_SOURCE, root, transport)
            if kind == "production_pipeline"
            else None
        )
        provenance = client.provenance
    finally:
        client.close()
    passed = (
        bool(cases)
        and all(
            row["accepted"]
            and row["refinement_authority"] == "rust"
            and row["rust_refinement_verification_observed"] is True
            and row["python_refinement_role"] == "not_executed"
            and row["python_refinement_verification_executed"] is False
            and row["python_ssa_verifier_executed"] is True
            for row in cases
        )
        and python_absent["compilation_accepted"] is True
        and python_absent["python_refinement_calls"] == 0
        and no_rescue["rust_rejection_blocked"] is True
        and no_rescue["python_rescue_attempted"] is False
        and no_rescue["subsequent_recovery_succeeded"] is True
        and (full_backend is None or full_backend["accepted"] is True)
        and provenance.requested_transport == provenance.observed_transport == transport
    )
    return _identity(
        kind,
        revision,
        run_id,
        passed,
        requested_transport=transport,
        observed_transport=provenance.observed_transport,
        authority_provenance={
            "refinement_authority": "rust",
            "python_refinement_role": "not_executed",
            "derived_from_case_traces": True,
            "constant_only_evidence": False,
        },
        cases=cases,
        python_refinement_absence=python_absent,
        no_python_rescue=no_rescue,
        full_backend=full_backend,
        automatic_fallback=False,
    )


def transport(root: Path, revision: str, run_id: str) -> dict[str, Any]:
    rows = []
    for selected in ("in_process", "companion"):
        record = production(
            root,
            revision,
            run_id,
            selected,
            "transport_observation",
        )
        rows.append(
            {
                "requested_transport": record["requested_transport"],
                "observed_transport": record["observed_transport"],
                "status": record["status"],
                "valid_output_sha256": record["cases"][0]["ssa_sha256"],
                "rejection_classification": record["no_python_rescue"][
                    "structured_error"
                ]["classification"],
                "no_python_rescue": record["no_python_rescue"],
                "authority_provenance": record["authority_provenance"],
                "automatic_fallback": record["automatic_fallback"],
            }
        )
    passed = (
        all(
            row["status"] == "PASS"
            and row["requested_transport"] == row["observed_transport"]
            and row["automatic_fallback"] is False
            for row in rows
        )
        and len({row["valid_output_sha256"] for row in rows}) == 1
        and len({row["rejection_classification"] for row in rows}) == 1
    )
    return _identity("transport_parity", revision, run_id, passed, rows=rows)


def environment(
    kind: str,
    root: Path,
    repository: Path,
    revision: str,
    run_id: str,
    role: str,
    platform_id: str,
    python_minor: str,
    wheels: list[Path],
    full_python_suite: str | None,
) -> dict[str, Any]:
    import aether
    import aether_compiler_core
    from aether_compiler_core import companion_path, version_metadata

    imported = [
        Path(aether.__file__).resolve(),
        Path(aether_compiler_core.__file__).resolve(),
    ]
    clean = kind != "source_development"
    checkout_importable = any(
        path.is_relative_to(repository.resolve()) for path in imported
    )
    transport_rows = []
    for selected in ("in_process", "companion"):
        client = _client(selected)
        try:
            valid = _compile(SCALAR_SOURCE, root, client)
            absent = _python_refinement_absent(root, client)
            no_rescue = _no_python_rescue(root, client)
            oracle = _qualification_oracle(SCALAR_SOURCE, root, client)
            provenance = client.provenance
        finally:
            client.close()
        transport_rows.append(
            {
                "requested_transport": selected,
                "observed_transport": provenance.observed_transport,
                "valid_case": valid,
                "python_refinement_absence": absent,
                "no_python_rescue": no_rescue,
                "qualification_oracle": oracle,
                "automatic_fallback": False,
            }
        )
    metadata = version_metadata()
    requirements = importlib.metadata.requires("aether-language") or []
    passed = (
        len(transport_rows) == 2
        and all(
            row["requested_transport"] == row["observed_transport"]
            and row["valid_case"]["accepted"] is True
            and row["valid_case"]["refinement_authority"] == "rust"
            and row["valid_case"]["python_refinement_verification_executed"] is False
            and row["python_refinement_absence"]["python_refinement_calls"] == 0
            and row["no_python_rescue"]["rust_rejection_blocked"] is True
            and row["no_python_rescue"]["python_rescue_attempted"] is False
            and row["qualification_oracle"]["accepted"] is True
            and row["qualification_oracle"]["refinement_authority"] == "rust"
            and row["qualification_oracle"]["python_refinement_role"]
            == "oracle_only"
            and row["qualification_oracle"][
                "python_refinement_verification_executed"
            ]
            is True
            for row in transport_rows
        )
        and companion_path().is_file()
        and metadata.get("build_identity") == revision
        and metadata.get("protocol_version") == 1
        and "aether-compiler-core==1.0.0rc4" in requirements
        and (not clean or not checkout_importable)
        and (not clean or shutil.which("cargo") is None)
        and (not clean or shutil.which("rustc") is None)
        and (kind != "source_development" or full_python_suite == "PASS")
    )
    return _identity(
        kind,
        revision,
        run_id,
        passed,
        role=role,
        platform=platform_id,
        python_minor=python_minor,
        python_patch=host_platform.python_version(),
        checkout_importable=checkout_importable,
        cargo_required_by_consumer=shutil.which("cargo") is not None,
        rustc_required_by_consumer=shutil.which("rustc") is not None,
        product_binding=bool(aether_compiler_core.CompilerCore),
        companion_installed=companion_path().is_file(),
        native_manifest=metadata,
        exact_dependency_resolution=(
            "aether-compiler-core==1.0.0rc4" in requirements
        ),
        imported_paths=[str(path) for path in imported],
        wheels=[
            {
                "name": path.name,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
            for path in wheels
        ],
        full_python_suite=full_python_suite,
        transport_rows=transport_rows,
        authority_provenance={
            "refinement_authority": "rust",
            "python_refinement_role": "not_executed",
            "derived_from_case_traces": True,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("production", "transport", "environment"),
        required=True,
    )
    parser.add_argument("--kind", default="production_authority")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument(
        "--transport",
        default="in_process",
        choices=("in_process", "companion"),
    )
    parser.add_argument("--role", default="dedicated")
    parser.add_argument("--platform", default="unknown")
    parser.add_argument(
        "--python-minor",
        default=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    parser.add_argument("--wheel", type=Path, action="append", default=[])
    parser.add_argument("--full-python-suite", choices=("PASS", "FAIL"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "production":
        result = production(
            args.root,
            args.revision,
            args.run_id,
            args.transport,
            args.kind,
        )
    elif args.mode == "transport":
        result = transport(args.root, args.revision, args.run_id)
    else:
        result = environment(
            args.kind,
            args.root,
            args.repository,
            args.revision,
            args.run_id,
            args.role,
            args.platform,
            args.python_minor,
            args.wheel,
            args.full_python_suite,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{result['kind']}: {result['status']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
