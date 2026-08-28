#!/usr/bin/env python3
"""Fail-closed aggregate checker for CORE-PKG-1 CI evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re


PENDING = "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_PENDING_CI"
QUALIFIED = "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED"
BLOCKED = "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_BLOCKED"
PLATFORMS = {"linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64"}
PYTHONS = {"3.11", "3.12", "3.13", "3.14"}


def check(evidence_dir: Path, *, ci_closure: bool = False) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    artifacts: list[tuple[Path, dict[str, object]]] = []
    for path in sorted(evidence_dir.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"{path}: invalid JSON: {error}")
            continue
        if isinstance(value, dict) and str(value.get("kind", "")).startswith("core_pkg_1_"):
            artifacts.append((path, value))

    platform_rows = [value for _, value in artifacts if value.get("matrix_role") == "platform"]
    python_rows = [value for _, value in artifacts if value.get("matrix_role") == "python_compatibility"]
    if {str(row.get("platform")) for row in platform_rows} != PLATFORMS:
        errors.append("native wheel platform matrix is incomplete")
    if {str(row.get("python_minor")) for row in python_rows} != PYTHONS:
        errors.append("CPython 3.11-3.14 wheel matrix is incomplete")

    for row in platform_rows + python_rows:
        native = row.get("native_wheel", {})
        language = row.get("language_wheel", {})
        consumer = row.get("clean_consumer", {})
        if row.get("decision") != PENDING:
            errors.append(f"qualification row is not pending-CI: {row.get('platform')} {row.get('python_minor')}")
        if not (
            isinstance(native, dict)
            and native.get("distribution") == "aether-compiler-core"
            and native.get("version") == "1.0.0rc4"
            and native.get("contains_binding") is True
            and native.get("contains_companion") is True
            and native.get("contains_native_manifest") is True
            and re.fullmatch(r"[0-9a-f]{64}", str(native.get("sha256", "")))
        ):
            errors.append("native wheel identity/content/hash evidence is incomplete")
        if not (
            isinstance(language, dict)
            and language.get("distribution") == "aether-language"
            and language.get("requires_exact_native_core") is True
        ):
            errors.append("aether-language exact native dependency evidence is missing")
        if not (
            isinstance(consumer, dict)
            and consumer.get("status") == "PASS"
            and consumer.get("consumer", {}).get("cargo_available") is False
            and consumer.get("consumer", {}).get("rustc_available") is False
            and consumer.get("binding", {}).get("qualification_only") is False
            and consumer.get("production_transport", {}).get("is_companion_client") is True
        ):
            errors.append("clean consumer/binding/companion/default-transport evidence failed")

    required_kinds = {
        "core_pkg_1_binding_smoke",
        "core_pkg_1_companion_smoke",
        "core_pkg_1_contract",
        "core_pkg_1_failure_campaign",
        "core_pkg_1_source_development",
    }
    present_kinds = {str(value.get("kind")) for _, value in artifacts}
    for kind in sorted(required_kinds - present_kinds):
        errors.append(f"missing mandatory evidence kind: {kind}")
    for _, value in artifacts:
        if value.get("kind") in required_kinds and value.get("status") != "PASS":
            errors.append(f"mandatory evidence failed: {value.get('kind')}")

    manifest = [
        {
            "path": path.relative_to(evidence_dir).as_posix(),
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "kind": value.get("kind"),
        }
        for path, value in artifacts
    ]
    decision = BLOCKED if errors else QUALIFIED if ci_closure else PENDING
    aggregate = {
        "artifact_schema_version": 1,
        "kind": "core_pkg_1_aggregate",
        "milestone": "CORE-PKG-1",
        "decision": decision,
        "production_transport": "companion",
        "in_process_promoted": False,
        "required_platforms": sorted(PLATFORMS),
        "required_python_minors": sorted(PYTHONS),
        "errors": errors,
        "artifact_manifest": manifest,
    }
    return aggregate, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ci-closure", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    aggregate, errors = check(args.evidence_dir, ci_closure=args.ci_closure)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(aggregate["decision"])
    for error in errors:
        print(f"- {error}")
    return 1 if args.require_ready and errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
