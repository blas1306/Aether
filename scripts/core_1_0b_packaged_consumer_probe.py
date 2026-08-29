#!/usr/bin/env python3
"""Probe one CORE-1.0B transport from an installed wheel-only consumer."""

from __future__ import annotations

import argparse
from importlib import metadata as importlib_metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _platform_id() -> str:
    system = platform.system().lower()
    os_name = (
        "macos"
        if system == "darwin"
        else "windows"
        if system == "windows"
        else "linux"
    )
    machine = platform.machine().lower().replace("-", "_")
    architecture = (
        "arm64"
        if machine in {"arm64", "aarch64"}
        else "x86_64"
        if machine in {"amd64", "x86_64"}
        else machine
    )
    return f"{os_name}-{architecture}"


def probe(args: argparse.Namespace) -> dict[str, object]:
    import aether
    import aether_compiler_core
    from aether.ir.model import IRModule
    from aether.pipeline import SSAPipeline
    from aether.ssa.shadow import (
        RUST_CORE_TRANSPORT_ENV,
        production_rust_ssa_lowering_client,
    )

    expected = args.expected_transport
    requested = os.environ.get(RUST_CORE_TRANSPORT_ENV)
    if args.expect_default:
        if requested is not None or expected != "in_process":
            raise RuntimeError("the default probe must run without a transport override")
    elif requested != expected:
        raise RuntimeError("the explicit transport override does not match the probe")

    language_distribution = importlib_metadata.distribution("aether-language")
    native_distribution = importlib_metadata.distribution("aether-compiler-core")
    requirements = tuple(language_distribution.requires or ())
    exact_dependency = any(
        requirement.replace(" ", "").lower()
        == "aether-compiler-core==1.0.0rc4"
        for requirement in requirements
    )
    if (
        language_distribution.version != "1.0.0rc4"
        or native_distribution.version != "1.0.0rc4"
        or not exact_dependency
    ):
        raise RuntimeError("installed productive distribution versions are incompatible")

    imported_paths = (
        Path(aether.__file__).resolve(),
        Path(aether_compiler_core.__file__).resolve(),
    )
    forbidden_root = args.forbidden_root.resolve()
    if any(_inside(path, forbidden_root) for path in imported_paths):
        raise RuntimeError("clean consumer imported a package from the source checkout")
    no_toolchain = shutil.which("cargo") is None and shutil.which("rustc") is None
    if not no_toolchain:
        raise RuntimeError("clean consumer unexpectedly has Cargo or rustc on PATH")

    metadata = aether_compiler_core.version_metadata()
    if metadata.get("build_identity") != args.revision:
        raise RuntimeError("installed native build identity differs from the exact revision")

    binding_calls = 0
    original_binding = aether_compiler_core.binding

    if expected == "companion":
        def forbidden_binding():
            nonlocal binding_calls
            binding_calls += 1
            raise AssertionError("companion transport executed the PyO3 binding")

        aether_compiler_core.binding = forbidden_binding

    try:
        first = SSAPipeline().run(IRModule())
        client = production_rust_ssa_lowering_client()
        failure = client.lower(b"{}")
        recovered = SSAPipeline().run(IRModule())
        provenance = client.provenance
        process_starts = client.process_start_count
        request_count = client.request_count
    finally:
        aether_compiler_core.binding = original_binding

    passed = (
        first.ssa_module.functions == []
        and recovered.ssa_module.functions == []
        and failure.get("ok") is False
        and provenance.requested_transport == expected
        and provenance.observed_transport == expected
        and process_starts == (1 if expected == "companion" else 0)
        and request_count == 3
        and binding_calls == 0
    )
    client.close()
    if not passed:
        raise RuntimeError("packaged production transport probe failed")

    return {
        "artifact_schema_version": 1,
        "kind": "core_1_0b_packaged_consumer",
        "milestone": "CORE-1.0B",
        "status": "PASS",
        "exact_revision": args.revision,
        "ci_run_id": args.ci_run_id,
        "platform": args.platform or _platform_id(),
        "python_minor": args.python_minor
        or f"{sys.version_info.major}.{sys.version_info.minor}",
        "expected_transport": expected,
        "default_selection": args.expect_default,
        "requested_transport": provenance.requested_transport,
        "observed_transport": provenance.observed_transport,
        "language_version": language_distribution.version,
        "native_version": native_distribution.version,
        "exact_native_dependency": exact_dependency,
        "native_build_identity": metadata["build_identity"],
        "outside_source_checkout": True,
        "cargo_available": False,
        "rustc_available": False,
        "handled_failure_recovery": True,
        "process_start_count": process_starts,
        "request_count": request_count,
        "pyo3_binding_calls": binding_calls,
        "imported_paths": [str(path) for path in imported_paths],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expected-transport", choices=("in_process", "companion"), required=True
    )
    parser.add_argument("--expect-default", action="store_true")
    parser.add_argument("--forbidden-root", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--ci-run-id", required=True)
    parser.add_argument("--platform")
    parser.add_argument("--python-minor")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = probe(args)
    except Exception as exc:
        evidence = {
            "artifact_schema_version": 1,
            "kind": "core_1_0b_packaged_consumer",
            "milestone": "CORE-1.0B",
            "status": "BLOCKED",
            "exact_revision": args.revision,
            "ci_run_id": args.ci_run_id,
            "platform": args.platform or _platform_id(),
            "python_minor": args.python_minor
            or f"{sys.version_info.major}.{sys.version_info.minor}",
            "expected_transport": args.expected_transport,
            "default_selection": args.expect_default,
            "error": f"{type(exc).__name__}: {exc}",
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
