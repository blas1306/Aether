#!/usr/bin/env python3
"""Measure RUST-3.11 Python-shadow phases and all three qualified routes."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from time import perf_counter
from typing import Callable, Iterator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import aether.ssa.general_builder as general_builder_module  # noqa: E402
import aether.ssa.verifier as verifier_module  # noqa: E402
import measure_rust_ssa_authority_performance as base  # noqa: E402
from aether.analysis.dominators import ReferenceDominatorAnalysis  # noqa: E402
from aether.ssa.dto import ssa_module_to_dto  # noqa: E402
from aether.ssa.general_builder import GeneralSSABuilder  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    canonical_ssa,
    diagnostic_lower_with_rust_authority_without_python_shadow,
    lower_with_rust_authority,
)
from qualify_rust_ssa_lowering_adversarial import linear  # noqa: E402


DEFAULT_EXECUTABLE = ROOT / "compiler-rs/target/release/aether-ssa-shadow"
ROUTES = ("python_shadow", "diagnostic_rust_only", "dual_lane")


def _summary(values: list[float]) -> dict[str, float | int]:
    return {
        "samples": len(values),
        "median_seconds": statistics.median(values),
        "min_seconds": min(values),
        "max_seconds": max(values),
    }


def _digest(value: object) -> str:
    dto = canonical_ssa(ssa_module_to_dto(value, schema_version=2))  # type: ignore[arg-type]
    encoded = json.dumps(dto, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


@contextmanager
def _dominance_variant(variant: str) -> Iterator[None]:
    if variant == "optimized":
        yield
        return
    old_builder = general_builder_module.DominatorAnalysis
    old_verifier = verifier_module.DominatorAnalysis
    general_builder_module.DominatorAnalysis = ReferenceDominatorAnalysis
    verifier_module.DominatorAnalysis = ReferenceDominatorAnalysis
    try:
        yield
    finally:
        general_builder_module.DominatorAnalysis = old_builder
        verifier_module.DominatorAnalysis = old_verifier


def _python_shadow(module: object) -> tuple[object, dict[str, object]]:
    phases: dict[str, float] = {}
    started = perf_counter()
    value = GeneralSSABuilder(phase_timings=phases).build(module)  # type: ignore[arg-type]
    total = perf_counter() - started
    return value, {"total_wall_seconds": total, "phase_timings_seconds": phases}


def _measure_module(
    module: object,
    client: PersistentRustSSALoweringClient,
    *,
    warmups: int,
    rounds: int,
) -> dict[str, object]:
    def rust_only() -> tuple[object, dict[str, object]]:
        value, report = diagnostic_lower_with_rust_authority_without_python_shadow(
            module, client  # type: ignore[arg-type]
        )
        assert report.performance is not None
        return value, report.performance.to_dict()

    def dual_lane() -> tuple[object, dict[str, object]]:
        value, report = lower_with_rust_authority(
            module, client, characterize_performance=True  # type: ignore[arg-type]
        )
        assert report.performance is not None
        return value, report.performance.to_dict()

    actions: tuple[
        tuple[str, Callable[[], tuple[object, dict[str, object]]]], ...
    ] = (
        ("python_shadow", lambda: _python_shadow(module)),
        ("diagnostic_rust_only", rust_only),
        ("dual_lane", dual_lane),
    )
    expected: str | None = None
    for _ in range(warmups):
        for _route, action in actions:
            value, _profile = action()
            digest = _digest(value)
            expected = expected or digest
            if digest != expected:
                raise RuntimeError("canonical SSA mismatch during warmup")

    samples: dict[str, list[dict[str, object]]] = {route: [] for route in ROUTES}
    for round_index in range(rounds):
        ordered = actions[round_index % len(actions) :] + actions[: round_index % len(actions)]
        for route, action in ordered:
            value, profile = action()
            if _digest(value) != expected:
                raise RuntimeError(f"canonical SSA mismatch in {route}")
            samples[route].append(profile)
    return {
        "canonical_ssa_sha256": expected,
        "samples": samples,
        "summary": {
            route: _summary(
                [float(sample["total_wall_seconds"]) for sample in route_samples]
            )
            for route, route_samples in samples.items()
        },
    }


def _revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("optimized", "reference"), default="optimized")
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--deep-rounds", type=int, default=7)
    parser.add_argument("--ordinary-rounds", type=int, default=15)
    parser.add_argument("--sizes", type=int, nargs="+", default=(100, 1000, 5000, 10000))
    parser.add_argument("--skip-deep", action="store_true")
    parser.add_argument("--skip-ordinary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.warmups < 2 or args.deep_rounds < 7 or args.ordinary_rounds < 15:
        parser.error("RUST-3.11 requires >=2 warmups, >=7 deep and >=15 ordinary rounds")

    record: dict[str, object] = {
        "milestone": "RUST-3.11",
        "variant": args.variant,
        "revision": _revision(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "executable": str(args.executable.relative_to(ROOT)),
        },
        "methodology": {
            "warmups": args.warmups,
            "deep_measured_rounds": args.deep_rounds,
            "ordinary_measured_rounds": args.ordinary_rounds,
            "clock": "time.perf_counter",
            "route_order": "rotated each round",
        },
        "deep_cfg": [],
        "ordinary": [],
    }
    with _dominance_variant(args.variant):
        with PersistentRustSSALoweringClient(args.executable) as client:
            if not args.skip_deep:
                for size in args.sizes:
                    measured = _measure_module(
                        linear(f"rust_3_11_{args.variant}_{size}", size),
                        client,
                        warmups=args.warmups,
                        rounds=args.deep_rounds,
                    )
                    record["deep_cfg"].append(  # type: ignore[union-attr]
                        {"blocks": size, **measured}
                    )
            if not args.skip_ordinary:
                for name, path, category in base.WORKLOADS:
                    module, source_digest = base._load_module(path)
                    measured = _measure_module(
                        module,
                        client,
                        warmups=args.warmups,
                        rounds=args.ordinary_rounds,
                    )
                    record["ordinary"].append(  # type: ignore[union-attr]
                        {
                            "id": name,
                            "path": path,
                            "category": category,
                            "source_sha256": source_digest,
                            **measured,
                        }
                    )

    rendered = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
