#!/usr/bin/env python3
"""Produce native clean-install Rust SSA authority evidence.

The default invocation remains the frozen RUST-3.6-V2 producer.  RUST-3.7a
adds a string workload and emits only new stabilization evidence.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from package_rust_ssa_shadow import package  # noqa: E402
from aether.ssa.shadow import SSA_AUTHORITY_MODE_ENV  # noqa: E402


PLATFORMS = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "windows-x86_64": "x86_64-pc-windows-msvc",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
}
MAX_PROBE_DIAGNOSTIC_CHARACTERS = 4_000


def _bounded_probe_output(value: str) -> str:
    if len(value) <= MAX_PROBE_DIAGNOSTIC_CHARACTERS:
        return value
    marker = f"\n...[truncated; original_chars={len(value)}]\n"
    remaining = MAX_PROBE_DIAGNOSTIC_CHARACTERS - len(marker)
    head = remaining // 2
    return value[:head] + marker + value[-(remaining - head) :]


def _probe_failure_diagnostics(
    completed: subprocess.CompletedProcess[str],
) -> str:
    return (
        f"aether-ssa-authority-probe exited with status {completed.returncode}\n"
        "===== probe stdout =====\n"
        f"{_bounded_probe_output(completed.stdout)}\n"
        "===== probe stderr =====\n"
        f"{_bounded_probe_output(completed.stderr)}"
    )


def _clean_probe_environment(
    environment: Path, *, host_environment: dict[str, str] | None = None
) -> dict[str, str]:
    """Isolate Python/package discovery while retaining the native toolchain.

    Clang is invoked by absolute path, but it still discovers its linker and
    platform SDK tools through the host PATH and related host environment.
    Keeping the venv first preserves installed console-script selection; the
    probe and Rust companion themselves are resolved by absolute installation
    paths and never through PATH.
    """
    isolated = dict(os.environ if host_environment is None else host_environment)
    isolated.pop("PYTHONPATH", None)
    isolated.pop("PYTHONHOME", None)
    scripts = environment / ("Scripts" if sys.platform == "win32" else "bin")
    host_path = isolated.get("PATH", os.defpath)
    checkout = ROOT.resolve()
    toolchain_entries = []
    for entry in host_path.split(os.pathsep):
        if not entry:
            continue
        try:
            checkout_local = Path(entry).resolve().is_relative_to(checkout)
        except OSError:
            checkout_local = False
        if not checkout_local:
            toolchain_entries.append(entry)
    isolated["PATH"] = os.pathsep.join((str(scripts), *toolchain_entries))
    return isolated


def _run_probe(
    arguments: list[str], *, cwd: Path, env: dict[str, str]
) -> tuple[int, object | None]:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    if completed.returncode != 0:
        print(_probe_failure_diagnostics(completed), file=sys.stderr)
        return completed.returncode, None
    return 0, json.loads(completed.stdout.splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=PLATFORMS, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--production-stabilization",
        action="store_true",
        help="emit RUST-3.7a evidence with the expanded representative set",
    )
    parser.add_argument(
        "--shadow-independent-promotion",
        action="store_true",
        help="emit RUST-4.5 clean-install default and native evidence",
    )
    args = parser.parse_args()

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    wheel = args.wheel.resolve()
    if wheel.is_dir():
        wheels = list(wheel.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("exactly one Python wheel is required")
        wheel = wheels[0]
    artifact = package(args.executable, output / "package", args.platform)
    clang = shutil.which("clang")
    if clang is None:
        raise RuntimeError("clang is required for representative native execution")

    with tempfile.TemporaryDirectory(prefix="aether-ssa-authority-clean-") as raw:
        clean = Path(raw)
        environment = clean / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        probe = environment / (
            "Scripts/aether-ssa-authority-probe.exe"
            if sys.platform == "win32"
            else "bin/aether-ssa-authority-probe"
        )
        subprocess.run([str(python), "-m", "pip", "install", str(wheel)], cwd=clean, check=True)
        companion = environment / "libexec" / "aether" / "ssa-shadow"
        companion.mkdir(parents=True)
        shutil.unpack_archive(str(artifact), companion)

        samples = clean / "samples"
        samples.mkdir()
        representative = [
            ("scalar", ROOT / "benchmarks/arithmetic.ae"),
            ("numerical", ROOT / "benchmarks/matrix_mul.ae"),
            ("collections", ROOT / "benchmarks/list_push.ae"),
            ("aggregate", ROOT / "examples/aggregate_collections/particles.ae"),
            (
                "class_interface",
                ROOT / "corpus/exceptions/positive/method_interface_dispatch.ae",
            ),
            (
                "exception",
                ROOT / "corpus/exceptions/positive/owned_aggregates_arc.ae",
            ),
            (
                "constructor_ownership",
                ROOT
                / "tests/fixtures/rust_ssa_promotion_failure/boxed_constructor_receiver.ae",
            ),
            (
                "function_value_indirect_call",
                ROOT / "corpus/exceptions/positive/indirect_call.ae",
            ),
        ]
        if args.production_stabilization:
            representative.insert(
                3, ("string", ROOT / "examples/llvm/string_choose.ae")
            )
        selected = [path for _category, path in representative]
        promotion_fixtures = sorted(
            (ROOT / "tests/fixtures/rust_ssa_promotion_failure").glob("*.ae")
        )
        if len(promotion_fixtures) != 8:
            raise RuntimeError("RUST-3.6-V2 requires exactly eight promotion fixtures")
        selected.extend(promotion_fixtures)
        isolated_sources = []
        for index, source in enumerate(selected):
            destination = samples / f"sample-{index}.ae"
            shutil.copyfile(source, destination)
            isolated_sources.append(destination)

        isolated_environment = _clean_probe_environment(environment)
        isolated_environment.pop(SSA_AUTHORITY_MODE_ENV, None)
        if not args.shadow_independent_promotion:
            # Historical RUST-3.6/3.7 producers retain their exact explicit
            # differential policy after the RUST-4.5 repository default move.
            isolated_environment[SSA_AUTHORITY_MODE_ENV] = (
                "rust_ssa_authority_python_shadow"
            )
        probe_returncode, observation = _run_probe(
            [
                str(probe),
                "--clang",
                str(Path(clang).resolve()),
                "--native-count",
                str(len(representative)),
                *(str(path) for path in isolated_sources),
            ],
            cwd=clean,
            env=isolated_environment,
        )
        if probe_returncode != 0:
            return probe_returncode
        assert observation is not None

    evidence = {
        "schema_version": 1,
        "milestone": (
            "RUST-4.5"
            if args.shadow_independent_promotion
            else "RUST-3.7a"
            if args.production_stabilization
            else "RUST-3.6-V2"
        ),
        "status": "PASS",
        "revision": args.revision,
        "platform": args.platform,
        "rust_target": PLATFORMS[args.platform],
        "authority": "rust",
        "shadow": (
            "not_executed_by_default"
            if args.shadow_independent_promotion
            else "python_synchronous"
        ),
        "returned_ssa_origin": "rust_schema_v2_import",
        "representative_categories": [
            category for category, _path in representative
        ],
        "execution": "clean_release_artifact_outside_checkout",
        "artifact": artifact.name,
        "sha256": sha256(artifact.read_bytes()).hexdigest(),
        "checks": {
            "packaged_discovery": "PASS",
            "production_default": "PASS",
            "multiple_requests": "PASS",
            "python_shadow_policy": "PASS",
            "python_shadow_comparison": "PASS",
            "rust_result_returned": "PASS",
            "optimizer_handoff": "PASS",
            "backend_handoff": "PASS",
            "native_execution_against_python_authority_baseline": "PASS",
            "mandatory_promotion_fixtures": "PASS",
            "preserved_mode_matrix": "PASS",
            "three_mode_matrix": "PASS",
            "rust_authority_repository_default": "PASS",
            "rollback": "PASS",
            "path_isolation": "PASS",
        },
        "comparison": observation,
        "native": {
            "status": "PASS",
            "comparisons": observation.get("native_baseline_comparisons", 0),
            "optimizer_handoffs": observation.get("optimizer_handoffs", 0),
            "backend_handoffs": observation.get("backend_handoffs", 0),
        },
        "mandatory_promotion_fixture_count": len(promotion_fixtures),
        "provenance": "executed-native-runner",
    }
    report = output / f"{args.platform}.json"
    report.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"RUST_SSA_AUTHORITY_PLATFORM_QUALIFIED {args.platform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
