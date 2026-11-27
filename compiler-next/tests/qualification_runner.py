#!/usr/bin/env python3
"""Reproducible qualification profile runner for compiler-next."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import platform
import re
import shlex
import signal
import subprocess
import sys
import time
import tomllib
from typing import Any


VALID_PROFILES = {"core", "conformance", "oal", "full"}
VALID_KINDS = {"cargo-test", "script", "cargo-workspace", "cargo-gate", "runner-test"}
CORE_REQUIRED = {
    "cargo:aether-frontend:lib",
    "cargo:aether-frontend:symbol_source_mapping",
    "cargo:aether-middle:lib",
    "cargo:aether-backend-llvm:lib",
    "cargo:aether-driver:core_v1",
    "cargo:aether-driver:const_v1",
    "cargo:aether-driver:ssa_store_provenance_v1",
    "cargo:aether-driver:borrow_ergonomics_v1",
    "cargo:aether-driver:owning_struct_field_replacement_v1",
    "cargo:aether-driver:oop_v1",
    "cargo:aether-driver:oop_v2",
    "cargo:aether-driver:oop_v3",
    "cargo:aether-driver:oop_opt_1",
}
CONFORMANCE_REQUIRED = CORE_REQUIRED | {
    "script:test-differential-harness",
    "script:run-differential",
}
FULL_REQUIRED = {
    "full:cargo-workspace",
    "script:test-differential-harness",
    "script:run-differential",
    "full:clippy",
    "full:fmt",
}
FULL_EXACT_COMMAND = ["cargo", "test", "--workspace", "-j", "1", "--no-fail-fast"]


class ManifestError(ValueError):
    pass


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError(f"cannot parse {path}: {exc}") from exc
    if data.get("version") != 1 or not isinstance(data.get("suite"), list):
        raise ManifestError("manifest must have version = 1 and at least one [[suite]] table")
    return data


def integration_inventory(root: Path) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for test in sorted((root / "crates").glob("*/tests/*.rs")):
        found.add((test.parents[1].name, test.stem))
    return found


def _nonempty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item for item in value)


def validate_manifest(data: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    suites = data["suite"]
    errors: list[str] = []
    seen: set[str] = set()
    classified: set[tuple[str, str]] = set()
    ids_by_profile = {profile: set() for profile in VALID_PROFILES}

    for index, suite in enumerate(suites, 1):
        label = suite.get("id", f"suite #{index}")
        suite_id = suite.get("id")
        if not isinstance(suite_id, str) or not suite_id:
            errors.append(f"{label}: missing non-empty id")
        elif suite_id in seen:
            errors.append(f"{label}: duplicate id")
        else:
            seen.add(suite_id)
        profiles = suite.get("profiles")
        if not _nonempty_strings(profiles):
            errors.append(f"{label}: profiles must be a non-empty string array")
            profiles = []
        invalid = set(profiles) - VALID_PROFILES
        if invalid:
            errors.append(f"{label}: invalid profiles: {', '.join(sorted(invalid))}")
        for profile_name in set(profiles) & VALID_PROFILES:
            if isinstance(suite_id, str):
                ids_by_profile[profile_name].add(suite_id)
        primary = suite.get("primary_responsibility", "")
        if primary == "observable language and native-program conformance" and "conformance" not in profiles:
            errors.append(f"{label}: previously mandatory language suite omitted from Conformance")
        if primary == "compiler invariants, verifiers, ownership, and native runtime" and "core" not in profiles:
            errors.append(f"{label}: previously mandatory compiler suite omitted from Core")
        if suite.get("kind") not in VALID_KINDS:
            errors.append(f"{label}: invalid kind")
        command = suite.get("command")
        if not _nonempty_strings(command):
            errors.append(f"{label}: command must be a non-empty argv array")
        timeout = suite.get("timeout_seconds")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            errors.append(f"{label}: timeout_seconds must be a positive integer")
        for field in ("primary_responsibility", "owner", "optimization"):
            if not isinstance(suite.get(field), str) or not suite[field].strip():
                errors.append(f"{label}: missing {field}")
        if not isinstance(suite.get("secondary_responsibilities"), list):
            errors.append(f"{label}: secondary_responsibilities must be an array")
        if not _nonempty_strings(suite.get("platform")):
            errors.append(f"{label}: platform must be a non-empty string array")

        target_kind = suite.get("target_kind")
        crate = suite.get("crate")
        target = suite.get("target")
        if target_kind == "integration":
            if not isinstance(crate, str) or not isinstance(target, str):
                errors.append(f"{label}: integration target needs crate and target")
            else:
                key = (crate, target)
                if key in classified:
                    errors.append(f"{label}: integration target classified more than once: {crate}/{target}")
                classified.add(key)
                expected = ["cargo", "test", "-p", crate, "--test", target]
                if command != expected:
                    errors.append(f"{label}: integration command must be {shlex.join(expected)}")
        elif target_kind == "lib":
            expected = ["cargo", "test", "-p", crate, "--lib"]
            if command != expected:
                errors.append(f"{label}: library command must be {shlex.join(expected)}")
        if suite.get("kind") == "script":
            if not command or command[0] != "bash" or len(command) != 2:
                errors.append(f"{label}: script command must be ['bash', <path>]")
            elif not (root / command[1]).is_file():
                errors.append(f"{label}: script does not exist: {command[1]}")

    actual = integration_inventory(root)
    for crate, target in sorted(actual - classified):
        errors.append(f"unclassified integration test: {crate}/{target}")
    for crate, target in sorted(classified - actual):
        errors.append(f"manifest references missing integration test: {crate}/{target}")

    missing_core = CORE_REQUIRED - ids_by_profile["core"]
    missing_conformance = CONFORMANCE_REQUIRED - ids_by_profile["conformance"]
    if missing_core:
        errors.append("required Core suites omitted: " + ", ".join(sorted(missing_core)))
    if missing_conformance:
        errors.append("required Conformance suites omitted: " + ", ".join(sorted(missing_conformance)))
    missing_full = FULL_REQUIRED - ids_by_profile["full"]
    if missing_full:
        errors.append("required Full gates omitted: " + ", ".join(sorted(missing_full)))

    full_workspace = [s for s in suites if s.get("kind") == "cargo-workspace" and "full" in s.get("profiles", [])]
    if len(full_workspace) != 1 or full_workspace[0].get("command") != FULL_EXACT_COMMAND:
        errors.append("Full must contain exactly one literal cargo test --workspace -j 1 --no-fail-fast suite")
    elif full_workspace[0].get("timeout_seconds", 0) < 2400:
        errors.append("Full workspace timeout must be at least 2400 seconds")
    qr_suite = next((s for s in suites if s.get("id") == "cargo:aether-registry:registry"), None)
    if qr_suite is None or qr_suite.get("timeout_seconds", 0) < 1500:
        errors.append("registry/QR suite timeout must be at least 1500 seconds")
    if errors:
        raise ManifestError("manifest validation failed:\n  - " + "\n  - ".join(errors))
    return suites


def selected_suites(suites: list[dict[str, Any]], profile_name: str) -> list[dict[str, Any]]:
    if profile_name not in VALID_PROFILES:
        raise ManifestError(f"unknown profile: {profile_name}")
    # Full is deliberately aggregate: inventory entries tagged full document coverage,
    # while only aggregate/gate entries execute. Cargo remains the authority.
    if profile_name == "full":
        return [suite for suite in suites if profile_name in suite["profiles"] and suite.get("full_gate", False)]
    if profile_name == "conformance":
        core = [suite for suite in suites if "core" in suite["profiles"] and suite.get("execute", True)]
        additional = [
            suite for suite in suites
            if profile_name in suite["profiles"] and "core" not in suite["profiles"] and suite.get("execute", True)
        ]
        return core + additional
    return [suite for suite in suites if profile_name in suite["profiles"] and suite.get("execute", True)]


def platform_blocker(suite: dict[str, Any]) -> str | None:
    requirements = set(suite["platform"])
    if "linux" in requirements and sys.platform != "linux":
        return f"requires linux, found {sys.platform}"
    machine = platform.machine().lower()
    if "x86_64" in requirements and machine not in {"x86_64", "amd64"}:
        return f"requires x86_64, found {machine}"
    return None


def terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def sample_process_group(pgid: int) -> tuple[float, int]:
    """Return observable CPU seconds and aggregate RSS KiB for a Linux process group."""
    if sys.platform != "linux":
        return 0.0, 0
    ticks = os.sysconf("SC_CLK_TCK")
    page_kib = os.sysconf("SC_PAGE_SIZE") // 1024
    cpu_ticks = 0
    rss_pages = 0
    for stat_path in Path("/proc").glob("[0-9]*/stat"):
        try:
            raw = stat_path.read_text(encoding="ascii")
            fields = raw[raw.rfind(")") + 2:].split()
            if int(fields[2]) != pgid:
                continue
            cpu_ticks += int(fields[11]) + int(fields[12])
            rss_pages += max(0, int(fields[21]))
        except (OSError, ValueError, IndexError):
            continue
    return cpu_ticks / ticks, rss_pages * page_kib


def run_suite(suite: dict[str, Any], root: Path, log_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", suite["id"])
    log_path = log_dir / f"{safe_id}.log"
    blocker = platform_blocker(suite)
    result: dict[str, Any] = {
        "id": suite["id"],
        "command": suite["command"],
        "status": "BLOCKED",
        "duration_seconds": 0.0,
        "log": str(log_path),
        "phase": "preflight",
    }
    with log_path.open("wb") as log:
        log.write((f"suite: {suite['id']}\ncommand: {shlex.join(suite['command'])}\n").encode())
        if blocker:
            log.write((f"BLOCKED: {blocker}\n").encode())
            result["reason"] = blocker
            return result
        result["phase"] = "execution"
        try:
            process = subprocess.Popen(
                suite["command"], cwd=root, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            result["reason"] = f"cannot start command: {exc}"
            log.write((result["reason"] + "\n").encode())
        else:
            deadline = started + suite["timeout_seconds"]
            max_cpu_seconds = 0.0
            max_rss_kib = 0
            returncode = process.poll()
            while returncode is None and time.monotonic() < deadline:
                cpu_seconds, rss_kib = sample_process_group(process.pid)
                max_cpu_seconds = max(max_cpu_seconds, cpu_seconds)
                max_rss_kib = max(max_rss_kib, rss_kib)
                time.sleep(0.1)
                returncode = process.poll()
            result["cpu_seconds_observed"] = round(max_cpu_seconds, 3)
            result["max_rss_kib_observed"] = max_rss_kib
            if returncode is None:
                terminate_process_tree(process)
                result["reason"] = f"timeout after {suite['timeout_seconds']} seconds"
                log.write(("\nBLOCKED: " + result["reason"] + "\n").encode())
            else:
                result["returncode"] = returncode
                result["status"] = "PASS" if returncode == 0 else "FAIL"
                if returncode != 0:
                    result["reason"] = f"command exited with {returncode}"
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        return result


def write_json(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if str(path) == "-":
        sys.stdout.write(serialized)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=sorted(VALID_PROFILES))
    parser.add_argument("--list", action="store_true", help="validate and print the plan without executing")
    parser.add_argument("--json", type=Path, help="write a machine-readable result (use - for stdout)")
    parser.add_argument("--manifest", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    tests_dir = Path(__file__).resolve().parent
    root = (args.root or tests_dir.parent).resolve()
    manifest_path = (args.manifest or tests_dir / "qualification.toml").resolve()
    try:
        suites = validate_manifest(load_manifest(manifest_path), root)
        plan = selected_suites(suites, args.profile)
    except ManifestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.list:
        for position, suite in enumerate(plan, 1):
            print(f"{position:02d} {suite['id']} [{suite['timeout_seconds']}s] {shlex.join(suite['command'])}")
        if args.json:
            write_json(args.json, {"profile": args.profile, "mode": "plan", "suites": plan})
        return 0

    run_stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(os.environ.get("QUALIFY_OUTPUT_DIR", root / "qualification-results" / run_stamp))
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for position, suite in enumerate(plan, 1):
        print(f"[{position}/{len(plan)}] RUN {suite['id']}", flush=True)
        result = run_suite(suite, root, log_dir)
        results.append(result)
        print(f"[{position}/{len(plan)}] {result['status']} {suite['id']} ({result['duration_seconds']:.3f}s)", flush=True)
    counts = {status: sum(r["status"] == status for r in results) for status in ("PASS", "FAIL", "BLOCKED")}
    payload = {"profile": args.profile, "mode": "run", "results": results, "summary": counts}
    json_path = args.json or output_dir / "results.json"
    write_json(json_path, payload)
    print(f"SUMMARY PASS={counts['PASS']} FAIL={counts['FAIL']} BLOCKED={counts['BLOCKED']}")
    print(f"RESULTS {json_path}")
    return 1 if counts["FAIL"] or counts["BLOCKED"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
