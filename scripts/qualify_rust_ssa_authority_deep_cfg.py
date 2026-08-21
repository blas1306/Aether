#!/usr/bin/env python3
"""Run permanent Python/Rust deep-CFG requalification at 993/1000/5000."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter_ns


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from aether.ir.dto import ir_module_to_dto  # noqa: E402
from aether.ssa import GeneralSSABuilder, SSAVerifier  # noqa: E402
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    canonical_ssa,
)
from qualify_rust_ssa_lowering_adversarial import linear  # noqa: E402


DEFAULT_COMPANION = ROOT / "compiler-rs/target/debug/aether-ssa-shadow"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executable", type=Path, default=DEFAULT_COMPANION)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.build:
        cargo = shutil.which("cargo")
        if cargo is None:
            raise RuntimeError("cargo is required")
        subprocess.run(
            [cargo, "build", "-p", "aether-verifier", "--bin", "aether-ssa-shadow"],
            cwd=ROOT / "compiler-rs",
            check=True,
        )

    cargo_workspace = subprocess.run(
        [shutil.which("cargo") or "cargo", "test", "--workspace", "--locked"],
        cwd=ROOT / "compiler-rs",
        capture_output=True,
        text=True,
    )

    stress = {}
    with PersistentRustSSALoweringClient(
        args.executable.resolve(), timeout_seconds=180
    ) as client:
        for size in (993, 1000, 5000):
            module = linear(f"rust_3_5b_linear_{size}", size)
            payload = json.dumps(
                ir_module_to_dto(module), sort_keys=True, separators=(",", ":")
            ).encode()
            python_started = perf_counter_ns()
            python_ssa = GeneralSSABuilder().build(module)
            SSAVerifier(python_ssa).verify()
            python_ns = perf_counter_ns() - python_started
            rust_started = perf_counter_ns()
            response = client.lower(payload)
            rust_ns = perf_counter_ns() - rust_started
            rust_dto = response.get("ssa")
            rust_ok = response.get("ok") is True and isinstance(rust_dto, dict)
            canonical_equal = False
            exact = False
            if rust_ok:
                imported = ssa_module_from_dto(rust_dto)
                SSAVerifier(imported).verify()
                exact = ssa_module_to_dto(imported, schema_version=2) == rust_dto
                canonical_equal = canonical_ssa(
                    ssa_module_to_dto(python_ssa, schema_version=2)
                ) == canonical_ssa(rust_dto)
            passed = rust_ok and exact and canonical_equal
            stress[str(size)] = {
                "python": "PASS",
                "rust": "PASS" if passed else "FAIL",
                "lowered_blocks": len(python_ssa.functions[0].blocks),
                "canonical_ssa_parity": canonical_equal,
                "rust_owned_ssa_verification": rust_ok,
                "schema_v2_exact_reserialization": exact,
                "python_elapsed_ns": python_ns,
                "rust_elapsed_ns": rust_ns,
            }
        transport = {
            "requests": client.request_count,
            "process_startups": client.process_start_count,
        }
    passed = cargo_workspace.returncode == 0 and all(
        row["python"] == row["rust"] == "PASS" for row in stress.values()
    )
    report = {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.5b",
        "qualification_revision": args.revision,
        "decision": (
            "RUST_SSA_AUTHORITY_DEEP_CFG_PASS"
            if passed
            else "RUST_SSA_AUTHORITY_DEEP_CFG_BLOCKED"
        ),
        "stress": stress,
        "cargo_workspace": {
            "status": "PASS" if cargo_workspace.returncode == 0 else "FAIL",
            "summary": (
                cargo_workspace.stdout.strip().splitlines()[-1]
                if cargo_workspace.stdout.strip()
                else cargo_workspace.stderr.strip().splitlines()[-1]
                if cargo_workspace.stderr.strip()
                else ""
            ),
        },
        "transport": transport,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(report["decision"])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
