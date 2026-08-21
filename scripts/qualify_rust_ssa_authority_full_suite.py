#!/usr/bin/env python3
"""Run the safe-default suite and the original promotion subset under Rust authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPANION = ROOT / "compiler-rs/target/debug/aether-ssa-shadow"
MAX_FAILURES = 100
MAX_DIAGNOSTIC_CHARACTERS = 6_000


def _run(
    arguments: list[str],
    *,
    lsan_compatible: bool,
    junit_report: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if lsan_compatible:
        environment["LSAN_OPTIONS"] = "detect_leaks=0"
    diagnostic_arguments = []
    if junit_report is not None:
        diagnostic_arguments = [
            "--tb=short",
            "--color=no",
            f"--junitxml={junit_report}",
            "-o",
            "junit_logging=all",
            "-o",
            "junit_log_passing_tests=false",
        ]
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *diagnostic_arguments,
            *arguments,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )


def _count(result: subprocess.CompletedProcess[str], name: str) -> int:
    matches = re.findall(rf"(\d+) {name}", result.stdout + "\n" + result.stderr)
    return int(matches[-1]) if matches else 0


def _bounded(value: str) -> str:
    value = value.strip()
    if len(value) <= MAX_DIAGNOSTIC_CHARACTERS:
        return value
    marker = f"...[truncated; original_chars={len(value)}]"
    return value[: MAX_DIAGNOSTIC_CHARACTERS - len(marker)] + marker


def _node_id(testcase: ET.Element) -> str:
    file_name = testcase.attrib.get("file", "")
    test_name = testcase.attrib.get("name", "<unknown>")
    class_name = testcase.attrib.get("classname", "")
    qualifiers: list[str] = []
    if not file_name and class_name:
        class_parts = class_name.split(".")
        qualifier_index = next(
            (
                index
                for index, part in enumerate(class_parts)
                if part[:1].isupper()
            ),
            len(class_parts),
        )
        module_parts = class_parts[:qualifier_index]
        qualifiers = class_parts[qualifier_index:]
        if module_parts:
            file_name = "/".join(module_parts) + ".py"
    if file_name and class_name:
        module_name = Path(file_name).with_suffix("").as_posix().replace("/", ".")
        if class_name.startswith(module_name + "."):
            qualifiers = class_name[len(module_name) + 1 :].split(".")
        elif class_name != module_name:
            module_leaf = module_name.rsplit(".", 1)[-1]
            class_parts = class_name.split(".")
            if module_leaf in class_parts:
                module_index = len(class_parts) - 1 - class_parts[::-1].index(
                    module_leaf
                )
                qualifiers = class_parts[module_index + 1 :]
    parts = [file_name or class_name or "<unknown>", *qualifiers, test_name]
    return "::".join(part for part in parts if part)


def _failure_phase(outcome: ET.Element) -> str:
    if outcome.tag.rsplit("}", 1)[-1] == "failure":
        return "call"
    match = re.search(
        r"(?:failed|error) (?:on|during) (setup|call|teardown|collection)",
        outcome.attrib.get("message", ""),
        flags=re.IGNORECASE,
    )
    return match.group(1).lower() if match else "session"


def _parse_junit_failures(report_path: Path) -> tuple[list[dict[str, str]], int]:
    root = ET.parse(report_path).getroot()
    failures: list[dict[str, str]] = []
    for testcase in root.iter():
        if testcase.tag.rsplit("}", 1)[-1] != "testcase":
            continue
        stdout = ""
        stderr = ""
        outcomes: list[ET.Element] = []
        for child in testcase:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag in {"failure", "error"}:
                outcomes.append(child)
            elif tag == "system-out":
                stdout = child.text or ""
            elif tag == "system-err":
                stderr = child.text or ""
        for outcome in outcomes:
            details = outcome.text or outcome.attrib.get("message", "")
            failures.append(
                {
                    "node_id": _node_id(testcase),
                    "error_summary": _bounded(details),
                    "phase": _failure_phase(outcome),
                    "stdout": _bounded(stdout),
                    "stderr": _bounded(stderr),
                }
            )
    failures.sort(
        key=lambda row: (row["node_id"], row["phase"], row["error_summary"])
    )
    return failures[:MAX_FAILURES], len(failures)


def _fallback_failure(
    result: subprocess.CompletedProcess[str], reason: str
) -> dict[str, str]:
    return {
        "node_id": "<pytest-session>",
        "error_summary": _bounded(reason),
        "phase": "session",
        "stdout": _bounded(result.stdout),
        "stderr": _bounded(result.stderr),
    }


def _write_pytest_log(
    path: Path, result: subprocess.CompletedProcess[str]
) -> None:
    arguments = result.args
    command = shlex.join(arguments) if isinstance(arguments, list) else str(arguments)
    path.write_text(
        "\n".join(
            (
                f"command: {command}",
                f"returncode: {result.returncode}",
                "",
                "===== stdout =====",
                result.stdout,
                "===== stderr =====",
                result.stderr,
            )
        ),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _environment(executable: Path) -> dict[str, object]:
    resolved_executable = executable.resolve()
    return {
        "sys_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_executable": str(Path(sys.executable).resolve()),
        "qualification_executable": {
            "requested_path": str(executable),
            "resolved_path": str(resolved_executable),
            "sha256": _sha256(resolved_executable),
        },
    }


def _qualification_passed(
    safe: subprocess.CompletedProcess[str],
    promotion: subprocess.CompletedProcess[str],
    native_compatible: subprocess.CompletedProcess[str],
) -> bool:
    return (
        safe.returncode == 0
        and promotion.returncode == 0
        and native_compatible.returncode == 0
        and _count(native_compatible, "passed") == 54
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executable", type=Path, default=DEFAULT_COMPANION)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
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
    pytest_log = args.output.with_name(f"{args.output.stem}_pytest.log")
    with tempfile.TemporaryDirectory(prefix="aether-full-suite-") as temporary:
        junit_report = Path(temporary) / "full_suite_pytest.xml"
        safe = _run(
            [safe_shadow_option],
            lsan_compatible=True,
            junit_report=junit_report,
        )
        _write_pytest_log(pytest_log, safe)
        try:
            failures, reported_failure_count = _parse_junit_failures(junit_report)
        except (OSError, ET.ParseError) as error:
            failures = []
            reported_failure_count = 0
            junit_error = f"pytest JUnit report unavailable: {type(error).__name__}"
        else:
            junit_error = ""
    if safe.returncode != 0 and not failures:
        failures = [
            _fallback_failure(
                safe,
                junit_error or "pytest failed without a reported test failure",
            )
        ]
        reported_failure_count = max(reported_failure_count, 1)
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
    passed = _qualification_passed(safe, promotion, native_compatible)
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
        "environment": _environment(args.executable),
        "passed": _count(safe, "passed"),
        "failed": _count(safe, "failed"),
        "skipped": _count(safe, "skipped"),
        "real_semantic_failures": 0 if safe.returncode == 0 else _count(safe, "failed"),
        "failures": failures,
        "reported_failure_count": reported_failure_count,
        "failures_truncated": reported_failure_count > len(failures),
        "pytest_log": pytest_log.name,
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
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(report["decision"])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
