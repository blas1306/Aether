#!/usr/bin/env python3
"""Run the permanent RUST-3.7a regression-family gate under the production default."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
FAMILIES = {
    "source_location_preservation": (
        "tests/aether/test_ssa_source_location_lowering_policy_v1.py",
        "tests/aether/test_ssa_source_location_codec_qualification.py",
        "tests/aether/test_ssa_dto_v2.py",
    ),
    "bounds_checked_provenance": (
        "tests/aether/test_ssa_lowering_policy_v1.py",
        "tests/aether/test_ssa_dto_v2.py",
    ),
    "aggregate_ownership": ("tests/aether/test_ssa_aggregate_ownership.py",),
    "class_interface_ownership": (
        "tests/aether/test_native_class_references.py",
        "tests/aether/test_native_struct_interface_boxing.py",
    ),
    "constructor_exceptional_cleanup": ("tests/aether/test_ssa_exceptions.py",),
    "nullable_ownership_and_casts": ("tests/aether/test_nullable_native.py",),
    "collection_temporary_ownership": (
        "tests/aether/test_ssa_collection_extraction_borrow.py",
    ),
    "indirect_calls_and_function_values": ("tests/aether/test_typed_callables.py",),
}
MAX_DIAGNOSTIC_CHARACTERS = 6_000


def _bounded(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_DIAGNOSTIC_CHARACTERS:
        return text
    marker = f"...[truncated; original_chars={len(text)}]"
    remaining = MAX_DIAGNOSTIC_CHARACTERS - len(marker)
    return text[: remaining // 2] + marker + text[-(remaining - remaining // 2) :]


def _path(testcase: ET.Element) -> str:
    path = testcase.attrib.get("file", "").replace("\\", "/")
    if not path:
        parts = testcase.attrib.get("classname", "").split(".")
        class_index = next(
            (index for index, part in enumerate(parts) if part[:1].isupper()),
            len(parts),
        )
        path = "/".join(parts[:class_index]) + ".py"
    if path.startswith("./"):
        path = path[2:]
    return path


def _result_rows(report: Path, session_failed: bool) -> dict[str, dict[str, object]]:
    root = ET.parse(report).getroot()
    cases = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "testcase"]
    rows: dict[str, dict[str, object]] = {}
    for family, files in FAMILIES.items():
        selected = [case for case in cases if _path(case) in files]
        failures = [
            case
            for case in selected
            if any(child.tag.rsplit("}", 1)[-1] in {"failure", "error"} for child in case)
        ]
        rows[family] = {
            "status": "PASS" if selected and not failures and not session_failed else "BLOCKED",
            "tests": len(selected),
            "failures": len(failures),
            "files": list(files),
        }
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    executable = args.executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(f"Rust SSA companion not found: {executable}")
    selected_files = sorted({path for paths in FAMILIES.values() for path in paths})
    environment = os.environ.copy()
    environment["LSAN_OPTIONS"] = "detect_leaks=0"
    with tempfile.TemporaryDirectory(prefix="aether-rust-3-7a-regressions-") as raw:
        junit = Path(raw) / "regressions.xml"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--tb=short",
                "--color=no",
                f"--junitxml={junit}",
                f"--rust-ssa-authority-qualification-executable={executable}",
                *selected_files,
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        try:
            families = _result_rows(junit, completed.returncode != 0)
        except (OSError, ET.ParseError):
            families = {
                name: {"status": "BLOCKED", "tests": 0, "failures": 1, "files": list(files)}
                for name, files in FAMILIES.items()
            }
    passed = completed.returncode == 0 and all(row["status"] == "PASS" for row in families.values())
    summary_match = re.findall(r"(?:^|\s)(\d+) passed", completed.stdout)
    report = {
        "artifact_schema_version": 1,
        "milestone": "RUST-3.7a",
        "qualification_revision": args.revision,
        "decision": "RUST_SSA_PRODUCTION_REGRESSIONS_PASS" if passed else "RUST_SSA_PRODUCTION_REGRESSIONS_BLOCKED",
        "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        "families": families,
        "selected_files": selected_files,
        "passed": int(summary_match[-1]) if summary_match else 0,
        "returncode": completed.returncode,
        "stdout": _bounded(completed.stdout),
        "stderr": _bounded(completed.stderr),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(report["decision"])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
