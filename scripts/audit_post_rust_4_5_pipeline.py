#!/usr/bin/env python3
"""Qualification-only timing audit for the post-RUST-4.5 compiler pipeline.

This script does not alter compiler behavior.  It times public/internal boundaries
from a caller-side harness, uses the existing release SSA companion through the
qualification injection seam, and writes one observational JSON record.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter
from typing import Any, Callable, Iterator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKLOADS = (
    "examples/hello.ae",
    "examples/ir/sumTo.ae",
    "tests/aether/parity_corpus/strings.ae",
    "examples/aggregate_collections/particles.ae",
    "examples/Sorts/Main.ae",
    "examples/numerical_methods/main.ae",
    "examples/expense_tracker/Main.ae",
)


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    median = statistics.median(ordered)
    deviations = [abs(value - median) for value in ordered]
    return {
        "median": median,
        "mad": statistics.median(deviations),
        "minimum": ordered[0],
        "maximum": ordered[-1],
    }


class Timings:
    def __init__(self) -> None:
        self.seconds: Counter[str] = Counter()
        self.calls: Counter[str] = Counter()

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            self.seconds[name] += perf_counter() - started
            self.calls[name] += 1

    def wrap(self, owner: object, attribute: str, name: str) -> Callable[[], None]:
        original = getattr(owner, attribute)

        def measured(*args: object, **kwargs: object) -> object:
            with self.phase(name):
                return original(*args, **kwargs)

        setattr(owner, attribute, measured)

        def restore() -> None:
            setattr(owner, attribute, original)

        return restore


def _prepare_typed_program(path: Path, source: str, timings: Timings) -> object:
    from aether.entry_point import normalize_entry_point
    from aether.modules import build_checked_program, with_root_program
    from aether.parser import Parser
    from aether.pipeline import TypedProgram, tokenize_source
    from aether.typechecker import TypeChecker

    with timings.phase("root_lexer"):
        tokens = tokenize_source(source)
    with timings.phase("root_parser_ast"):
        program = Parser(tokens).parse()
    checker = TypeChecker(source_root=path.parent, entry_path=path)
    with timings.phase("semantic_typecheck_module_loading_inclusive"):
        checker.check(program)
    with timings.phase("checked_program_symbol_materialization"):
        checked = build_checked_program(program, checker)
    with timings.phase("entry_point_normalization"):
        normalized = normalize_entry_point(program, checker)
    return TypedProgram(
        normalized,
        checker,
        with_root_program(checked, normalized),
    )


def _one_warm_build(
    path: Path,
    output_path: Path,
    client: object,
) -> dict[str, object]:
    from aether.backend.llvm import LLVMBuilder
    from aether.backend.llvm.native_boundary import NativeBoundaryVerifier
    from aether.backend.llvm.printer import LLVMPrinter
    from aether.ir.lowering import IRLowerer
    from aether.ir.verifier import IRVerifier
    from aether.ssa import dto as ssa_dto
    from aether.ssa import shadow as ssa_shadow
    from aether.ssa import shadow_independent
    from aether.ssa.verifier import SSAVerifier

    timings = Timings()
    restorers: list[Callable[[], None]] = []
    trace_holder: dict[str, object] = {}

    restorers.append(timings.wrap(IRLowerer, "lower_checked_program", "initial_ir_construction"))
    restorers.append(timings.wrap(IRVerifier, "verify", "python_initial_ir_verification"))
    restorers.append(timings.wrap(SSAVerifier, "verify", "python_ssa_verification"))
    restorers.append(timings.wrap(NativeBoundaryVerifier, "verify", "python_native_boundary_verification"))
    restorers.append(timings.wrap(LLVMPrinter, "print_module", "python_llvm_text_emission"))
    original_schema_v2_import_alias = shadow_independent.ssa_module_from_dto
    restorers.append(timings.wrap(ssa_dto, "ssa_module_from_dto", "python_schema_v2_import"))
    restorers.append(timings.wrap(shadow_independent, "ir_module_to_dto", "python_ir_schema_v1_materialization_and_integrity"))
    restorers.append(timings.wrap(shadow_independent, "expand_lifecycle", "python_lifecycle_normalization"))
    restorers.append(timings.wrap(shadow_independent, "verify_ssa_refinement", "python_refinement_verification"))

    original_client_factory = ssa_shadow.default_rust_ssa_lowering_client
    ssa_shadow.default_rust_ssa_lowering_client = lambda: client
    restorers.append(
        lambda: setattr(
            ssa_shadow,
            "default_rust_ssa_lowering_client",
            original_client_factory,
        )
    )

    original_lower = shadow_independent.lower_with_shadow_independent_rust_authority

    def capture_trace(module: object, selected_client: object) -> object:
        result, trace = original_lower(module, selected_client)
        trace_holder["trace"] = trace
        return result, trace

    shadow_independent.lower_with_shadow_independent_rust_authority = capture_trace
    restorers.append(
        lambda: setattr(
            shadow_independent,
            "lower_with_shadow_independent_rust_authority",
            original_lower,
        )
    )

    # shadow_independent imported this name directly; point its alias at the
    # measured wrapper installed above.
    shadow_independent.ssa_module_from_dto = ssa_dto.ssa_module_from_dto
    restorers.append(
        lambda: setattr(
            shadow_independent,
            "ssa_module_from_dto",
            original_schema_v2_import_alias,
        )
    )

    source_started = perf_counter()
    source = path.read_text(encoding="utf-8")
    timings.seconds["source_loading"] += perf_counter() - source_started
    timings.calls["source_loading"] += 1

    total_started = perf_counter()
    try:
        typed = _prepare_typed_program(path, source, timings)
        builder = LLVMBuilder(optimization_profile="O0")
        original_run_clang = builder._run_clang

        def measured_clang(*args: object, **kwargs: object) -> object:
            with timings.phase("external_clang_link"):
                return original_run_clang(*args, **kwargs)

        builder._run_clang = measured_clang  # type: ignore[method-assign]
        builder.build(typed, output_path=output_path, keep_llvm=False)
    finally:
        total = perf_counter() - total_started
        for restore in reversed(restorers):
            restore()

    trace = trace_holder.get("trace")
    trace_dict = trace.to_dict() if trace is not None else None  # type: ignore[union-attr]
    last_response = getattr(client, "last_response", None)
    return {
        "total_without_source_loading_seconds": total,
        "total_with_source_loading_seconds": total + timings.seconds["source_loading"],
        "phase_seconds": dict(timings.seconds),
        "phase_calls": dict(timings.calls),
        "rust_authority_trace": trace_dict,
        "rust_response_performance": (
            last_response.get("performance")
            if isinstance(last_response, dict)
            else None
        ),
    }


class RecordingClient:
    def __init__(self, delegate: object) -> None:
        self.delegate = delegate
        self.last_response: dict[str, object] | None = None

    def lower(self, payload: bytes) -> dict[str, object]:
        response = self.delegate.lower(payload)  # type: ignore[attr-defined]
        self.last_response = dict(response)
        return self.last_response


def _cold_samples(
    path: Path,
    companion: Path,
    rounds: int,
    warmups: int,
    temporary: Path,
) -> list[float]:
    values: list[float] = []
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["AETHER_INTERNAL_RUST_SSA_QUALIFICATION_EXECUTABLE"] = str(companion)
    for index in range(rounds + warmups):
        output = temporary / f"cold-{path.stem}-{index}"
        command = [
            sys.executable,
            "-m",
            "aether",
            "build",
            str(path),
            "-o",
            str(output),
        ]
        started = perf_counter()
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        elapsed = perf_counter() - started
        if completed.returncode != 0:
            raise RuntimeError(f"cold build failed for {path}: {completed.stderr}")
        if index >= warmups:
            values.append(elapsed)
    return values


def _process_baseline(command: list[str], rounds: int, warmups: int) -> list[float]:
    values: list[float] = []
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    for index in range(rounds + warmups):
        started = perf_counter()
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        elapsed = perf_counter() - started
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.decode(errors="replace"))
        if index >= warmups:
            values.append(elapsed)
    return values


def _aggregate_warm(samples: list[dict[str, object]]) -> dict[str, object]:
    phase_names = sorted(
        {
            name
            for sample in samples
            for name in sample["phase_seconds"]  # type: ignore[union-attr]
        }
    )
    trace_stage_names = sorted(
        {
            name
            for sample in samples
            for name in sample["rust_authority_trace"]["stage_seconds"]  # type: ignore[index]
        }
    )
    rust_phase_names = sorted(
        {
            name
            for sample in samples
            for name in sample["rust_response_performance"]["phases"]  # type: ignore[index]
        }
    )
    return {
        "total": _summary(
            [float(sample["total_with_source_loading_seconds"]) for sample in samples]
        ),
        "phases": {
            name: _summary(
                [
                    float(sample["phase_seconds"].get(name, 0.0))  # type: ignore[union-attr]
                    for sample in samples
                ]
            )
            for name in phase_names
        },
        "phase_calls": samples[-1]["phase_calls"],
        "rust_authority_trace_stages": {
            name: _summary(
                [
                    float(sample["rust_authority_trace"]["stage_seconds"][name])  # type: ignore[index]
                    for sample in samples
                ]
            )
            for name in trace_stage_names
        },
        "rust_internal_phases": {
            name: _summary(
                [
                    float(sample["rust_response_performance"]["phases"][name])  # type: ignore[index]
                    / 1_000_000_000
                    for sample in samples
                ]
            )
            for name in rust_phase_names
        },
        "last_rust_authority_trace": samples[-1]["rust_authority_trace"],
        "last_rust_response_performance": samples[-1]["rust_response_performance"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companion", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("workloads", nargs="*", default=DEFAULT_WORKLOADS)
    args = parser.parse_args()

    companion = args.companion.resolve()
    if not companion.is_file():
        parser.error(f"companion not found: {companion}")
    workloads = [(ROOT / item).resolve() for item in args.workloads]

    from aether.ssa.shadow import PersistentRustSSALoweringClient

    delegate = PersistentRustSSALoweringClient(
        companion,
        characterize_performance=True,
    )
    client = RecordingClient(delegate)
    records: list[dict[str, object]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="aether-post-rust-4-5-audit-") as raw:
            temporary = Path(raw)
            for path in workloads:
                warm: list[dict[str, object]] = []
                for index in range(args.rounds + args.warmups):
                    sample = _one_warm_build(
                        path,
                        temporary / f"warm-{path.stem}-{index}",
                        client,
                    )
                    if index >= args.warmups:
                        warm.append(sample)
                cold = _cold_samples(
                    path,
                    companion,
                    args.rounds,
                    args.warmups,
                    temporary,
                )
                records.append(
                    {
                        "workload": str(path.relative_to(ROOT)),
                        "source_bytes": path.stat().st_size,
                        "warm_in_process": _aggregate_warm(warm),
                        "cold_cli_build": _summary(cold),
                        "cold_cli_raw_seconds": cold,
                    }
                )
    finally:
        delegate.close()

    bare = _process_baseline(
        [sys.executable, "-c", "pass"], args.rounds, args.warmups
    )
    imported = _process_baseline(
        [sys.executable, "-c", "import aether.cli"], args.rounds, args.warmups
    )
    result = {
        "schema_version": 1,
        "audit": "post-RUST-4.5 compiler architecture timing",
        "observational_only": True,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "python_executable": sys.executable,
            "companion": str(companion.relative_to(ROOT)),
            "clang": subprocess.run(
                ["clang", "--version"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.splitlines()[0],
        },
        "method": {
            "optimization_profile": "O0 (repository default)",
            "rounds": args.rounds,
            "warmups": args.warmups,
            "clock": "time.perf_counter",
            "dispersion": "median absolute deviation (MAD), plus min/max",
            "cold": "fresh Python, fresh Rust companion, and fresh clang per sample",
            "warm": "same Python process and one persistent release Rust companion",
            "instrumentation": "caller-side qualification-only method wrapping",
        },
        "startup_baselines": {
            "bare_python_process": _summary(bare),
            "import_aether_cli_process": _summary(imported),
            "raw_bare_seconds": bare,
            "raw_import_seconds": imported,
        },
        "workloads": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
