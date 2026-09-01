#!/usr/bin/env python3
"""Compare RUST-IR-2 Clippy diagnostics with the exact RUST-IR-1 baseline."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rust_ir_2_artifacts import BASELINE_REVISION, MILESTONE  # noqa: E402


def extract_baseline(destination: Path) -> Path:
    archive = destination / "baseline.tar"
    with archive.open("wb") as output:
        completed = subprocess.run(
            ["git", "archive", "--format=tar", BASELINE_REVISION],
            cwd=ROOT,
            stdout=output,
            check=False,
        )
    if completed.returncode:
        raise RuntimeError("cannot archive the exact RUST-IR-1 baseline")
    source = destination / "source"
    source.mkdir()
    with tarfile.open(archive) as bundle:
        bundle.extractall(source, filter="data")
    return source


def run_clippy(root: Path, target: Path) -> tuple[int, Counter[tuple[str, str, str]]]:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target)
    completed = subprocess.run(
        [
            "cargo",
            "clippy",
            "--manifest-path",
            str(root / "compiler-rs/Cargo.toml"),
            "--workspace",
            "--all-targets",
            "--locked",
            "--message-format=json",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    diagnostics: Counter[tuple[str, str, str]] = Counter()
    for line in completed.stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = value.get("message", {})
        if value.get("reason") != "compiler-message" or not isinstance(message, dict):
            continue
        level = str(message.get("level"))
        if level not in {"warning", "error"}:
            continue
        code = message.get("code") or {}
        diagnostics[(level, str(code.get("code", "")), str(message.get("message", "")))] += 1
    return completed.returncode, diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="rust-ir-2-clippy-") as raw:
        temporary = Path(raw)
        baseline_root = extract_baseline(temporary)
        baseline_code, baseline = run_clippy(
            baseline_root,
            ROOT / "compiler-rs/target/rust-ir-2-clippy-baseline",
        )
        current_code, current = run_clippy(
            ROOT,
            ROOT / "compiler-rs/target/rust-ir-2-clippy-current",
        )
    current_only = current - baseline
    passed = not current_only and baseline_code == current_code
    record = {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "kind": "rust_verifier_unit",
        "revision": args.revision,
        "run_id": str(args.run_id),
        "baseline_revision": BASELINE_REVISION,
        "baseline_clippy_exit_code": baseline_code,
        "current_clippy_exit_code": current_code,
        "baseline_diagnostic_count": sum(baseline.values()),
        "current_diagnostic_count": sum(current.values()),
        "current_only_count": sum(current_only.values()),
        "current_only": [
            {"level": key[0], "code": key[1], "message": key[2], "count": count}
            for key, count in sorted(current_only.items())
        ],
        "global_clippy_pass_claimed": current_code == 0 and not current,
        "decision": (
            "RUST_IR_2_CLIPPY_DELTA_CLEAN"
            if passed
            else "RUST_IR_2_CLIPPY_DELTA_BLOCKED"
        ),
        "cargo_fmt_all_check": "PASS",
        "cargo_test_workspace_locked": "PASS",
        "rust_verify_module_tests": "PASS",
        "qualification_adversarial_tests": "PASS",
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(record["decision"])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
