#!/usr/bin/env python3
"""Run the safe-default suite and the original promotion subset under Rust authority."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPANION = ROOT / "compiler-rs/target/debug/aether-ssa-shadow"


def _run(arguments: list[str], *, lsan_compatible: bool) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if lsan_compatible:
        environment["LSAN_OPTIONS"] = "detect_leaks=0"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )


def _count(result: subprocess.CompletedProcess[str], name: str) -> int:
    matches = re.findall(rf"(\d+) {name}", result.stdout + "\n" + result.stderr)
    return int(matches[-1]) if matches else 0


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

    safe_shadow_option = (
        f"--rust-ssa-shadow-qualification-executable={args.executable.resolve()}"
    )
    safe = _run([safe_shadow_option], lsan_compatible=True)
    native_initial = _run(
        [safe_shadow_option, "tests/aether/test_native_exceptions.py"],
        lsan_compatible=False,
    )
    native_compatible = _run(
        [safe_shadow_option, "tests/aether/test_native_exceptions.py"],
        lsan_compatible=True,
    )
    audit = json.loads(
        (
            ROOT / "docs/compiler/rust_ssa_promotion_failure_root_cause_audit.json"
        ).read_text(encoding="utf-8")
    )
    promotion_nodes = [
        row["node_id"]
        for row in audit["failure_inventory"]
        if row["root_cause"] in {"RC1", "RC2", "RC3", "RC4", "RC5"}
    ]
    promotion = _run(
        [
            f"--rust-ssa-authority-qualification-executable={args.executable.resolve()}",
            *promotion_nodes,
        ],
        lsan_compatible=True,
    )
    native_text = native_initial.stdout + "\n" + native_initial.stderr
    lsan_classified = (
        _count(native_initial, "failed")
        if "LeakSanitizer" in native_text and "ptrace" in native_text
        else 0
    )
    native_compatible_passed = _count(native_compatible, "passed")
    passed = (
        safe.returncode == 0
        and promotion.returncode == 0
        and native_compatible.returncode == 0
        and native_compatible_passed == 54
    )
    report = {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.5b",
        "qualification_revision": args.revision,
        "decision": (
            "RUST_SSA_AUTHORITY_REQUALIFICATION_FULL_SUITE_PASS"
            if passed
            else "RUST_SSA_AUTHORITY_REQUALIFICATION_FULL_SUITE_BLOCKED"
        ),
        "mode": "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
        "passed": _count(safe, "passed"),
        "failed": _count(safe, "failed"),
        "skipped": _count(safe, "skipped"),
        "real_semantic_failures": 0 if safe.returncode == 0 else _count(safe, "failed"),
        "promotion_subset": {
            "selected": len(promotion_nodes),
            "passed": _count(promotion, "passed"),
            "failed": _count(promotion, "failed"),
            "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        },
        "promotion_subset_rust_authority_failures": _count(promotion, "failed"),
        "lsan_environmental_classification": {
            "initial_failed": _count(native_initial, "failed"),
            "classified_lsan_ptrace_aborts": lsan_classified,
            "procedure": "LSAN_OPTIONS=detect_leaks=0",
        },
        "native_exception_ptrace_compatible": (
            "54/54 PASS" if native_compatible_passed == 54 else "BLOCKED"
        ),
        "summaries": {
            "safe_default": safe.stdout.strip().splitlines()[-1] if safe.stdout.strip() else "",
            "promotion_subset": promotion.stdout.strip().splitlines()[-1] if promotion.stdout.strip() else "",
            "native_initial": native_initial.stdout.strip().splitlines()[-1] if native_initial.stdout.strip() else "",
            "native_compatible": native_compatible.stdout.strip().splitlines()[-1] if native_compatible.stdout.strip() else "",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(report["decision"])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
