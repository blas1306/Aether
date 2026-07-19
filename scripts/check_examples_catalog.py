#!/usr/bin/env python3
"""Validate the authoritative Aether examples catalog."""

from __future__ import annotations

import argparse
import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.backend.llvm import LLVMBuilder, LLVMRunner  # noqa: E402
from aether.capabilities import BackendIdentity, backend_capability_issues  # noqa: E402
from aether.cli import main as cli_main  # noqa: E402
from aether.pipeline import IRBackend, SSAPipeline, prepare_typed_program  # noqa: E402
from aether.typechecker import TypeChecker  # noqa: E402


MANIFEST_PATH = ROOT / "examples" / "v1_examples_manifest.json"
VALID_CLASSIFICATIONS = {"V1_NATIVE", "AST_ONLY_EXPERIMENTAL"}
REQUIRED_FIELDS = {
    "path",
    "classification",
    "backends",
    "run",
    "expected_exit_code",
    "timeout_seconds",
    "condition",
}


def load_manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def typed_entry(entry: dict[str, object]):
    path = ROOT / str(entry["path"])
    return prepare_typed_program(
        path.read_text(encoding="utf-8"),
        TypeChecker(source_root=path.parent, entry_path=path),
    )


def structural_errors(manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 2:
        errors.append("manifest schema_version must be 2")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        return [*errors, "manifest entries must be a list"]

    paths: list[str] = []
    counts = {classification: 0 for classification in VALID_CLASSIFICATIONS}
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            errors.append(f"entry {index} must be an object")
            continue
        entry = raw_entry
        missing = sorted(REQUIRED_FIELDS - entry.keys())
        if missing:
            errors.append(f"entry {index} is missing fields: {', '.join(missing)}")
        path = entry.get("path")
        if not isinstance(path, str):
            errors.append(f"entry {index} has a non-string path")
            continue
        paths.append(path)
        if not (ROOT / path).is_file():
            errors.append(f"manifest path does not exist: {path}")
        classification = entry.get("classification")
        if classification not in VALID_CLASSIFICATIONS:
            errors.append(f"unknown classification for {path}: {classification!r}")
        else:
            counts[str(classification)] += 1
        if "BROKEN" in {classification, entry.get("profile")}:
            errors.append(f"BROKEN entry is forbidden: {path}")
        if not isinstance(entry.get("backends"), list) or not entry.get("backends"):
            errors.append(f"entry must declare at least one backend: {path}")
        elif not set(entry["backends"]) <= {"native", "ast"}:
            errors.append(f"entry declares an unknown backend: {path}")
        if not isinstance(entry.get("run"), bool):
            errors.append(f"entry run field must be boolean: {path}")
        elif entry["run"]:
            if not isinstance(entry.get("expected_exit_code"), int):
                errors.append(f"runnable entry needs expected_exit_code: {path}")
            for stream in ("stdout", "stderr"):
                digest = entry.get(f"{stream}_sha256")
                if not isinstance(digest, str) or len(digest) != 64:
                    errors.append(f"runnable entry needs {stream}_sha256: {path}")
        if not isinstance(entry.get("timeout_seconds"), int) or entry.get("timeout_seconds", 0) <= 0:
            errors.append(f"entry timeout_seconds must be positive: {path}")
        if classification == "V1_NATIVE":
            if "native" not in entry.get("backends", []):
                errors.append(f"V1_NATIVE entry must declare native: {path}")
        if classification == "AST_ONLY_EXPERIMENTAL":
            features = entry.get("outside_v1_features")
            if not isinstance(features, list) or not features or not all(
                isinstance(feature, str) and feature for feature in features
            ):
                errors.append(f"experimental entry lacks outside_v1_features: {path}")
            if "native" in entry.get("backends", []):
                errors.append(f"experimental entry cannot declare native: {path}")

    duplicates = sorted({path for path in paths if paths.count(path) > 1})
    for path in duplicates:
        errors.append(f"duplicate manifest path: {path}")
    actual_paths = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "examples").rglob("*.ae")
    }
    catalog_paths = set(paths)
    for path in sorted(actual_paths - catalog_paths):
        errors.append(f"public example has no manifest entry: {path}")
    for path in sorted(catalog_paths - actual_paths):
        errors.append(f"manifest entry is not a public example: {path}")
    if any(path.startswith("tests/fixtures/") for path in paths):
        errors.append("test fixtures may not appear in the public examples manifest")

    readme = (ROOT / "examples" / "README.md").read_text(encoding="utf-8")
    count_line = (
        f"Catalog count: **{len(entries)} total = "
        f"{counts['V1_NATIVE']} V1_NATIVE + "
        f"{counts['AST_ONLY_EXPERIMENTAL']} AST_ONLY_EXPERIMENTAL; BROKEN = 0**."
    )
    if count_line not in readme:
        errors.append("examples README count does not match the manifest")
    stale_references = {
        "examples/minimos_cuadrados/interactive.ae",
        "examples/pruebaListas.ae",
    }
    for document in (ROOT / "README.md", ROOT / "examples" / "README.md"):
        text = document.read_text(encoding="utf-8")
        for stale in stale_references:
            if stale in text:
                errors.append(f"stale public-example reference in {document.relative_to(ROOT)}: {stale}")
    return errors


def compiler_errors(manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for raw_entry in manifest["entries"]:  # type: ignore[index]
        entry = raw_entry
        path = str(entry["path"])
        try:
            typed = typed_entry(entry)
            issues = backend_capability_issues(typed, BackendIdentity.NATIVE)
            actual_codes = {issue.diagnostic_code for issue in issues}
            if entry["classification"] == "AST_ONLY_EXPERIMENTAL":
                expected_codes = set(entry["outside_v1_features"])
                if not actual_codes:
                    errors.append(f"experimental entry is no longer excluded from native: {path}")
                if actual_codes != expected_codes:
                    errors.append(
                        f"experimental capability mismatch for {path}: "
                        f"expected={sorted(expected_codes)}, actual={sorted(actual_codes)}"
                    )
                if entry["run"]:
                    stdout = StringIO()
                    stderr = StringIO()
                    exit_code = cli_main(
                        ["--backend", "ast", str(ROOT / path)],
                        stdout=stdout,
                        stderr=stderr,
                    )
                    observations = (
                        ("exit code", exit_code, entry["expected_exit_code"]),
                        (
                            "stdout sha256",
                            hashlib.sha256(stdout.getvalue().encode()).hexdigest(),
                            entry.get("stdout_sha256"),
                        ),
                        (
                            "stderr sha256",
                            hashlib.sha256(stderr.getvalue().encode()).hexdigest(),
                            entry.get("stderr_sha256"),
                        ),
                    )
                    for label, actual, expected in observations:
                        if actual != expected:
                            errors.append(
                                f"{path} AST {label}: "
                                f"expected={expected!r}, actual={actual!r}"
                            )
                    if "Traceback" in stderr.getvalue():
                        errors.append(f"AST execution leaked a traceback: {path}")
                continue
            if issues:
                errors.append(f"V1_NATIVE capability rejection for {path}: {sorted(actual_codes)}")
                continue
            IRBackend().lower_verified(typed)
            SSAPipeline().run(typed)
            LLVMBuilder().emit_llvm(typed)
        except Exception as exc:  # the gate reports every path in one pass
            errors.append(f"compiler validation failed for {path}: {type(exc).__name__}: {exc}")
    return errors


def native_errors(manifest: dict[str, object]) -> list[str]:
    if shutil.which("clang") is None:
        return ["clang is required for native example validation"]
    errors: list[str] = []
    for raw_entry in manifest["entries"]:  # type: ignore[index]
        entry = raw_entry
        if entry["classification"] != "V1_NATIVE" or not entry["run"]:
            continue
        stdout = StringIO()
        stderr = StringIO()
        try:
            exit_code = LLVMRunner().run(typed_entry(entry), stdout=stdout, stderr=stderr)
        except Exception as exc:
            errors.append(f"native execution failed for {entry['path']}: {type(exc).__name__}: {exc}")
            continue
        observations = (
            ("exit code", exit_code, entry["expected_exit_code"]),
            ("stdout sha256", hashlib.sha256(stdout.getvalue().encode()).hexdigest(), entry.get("stdout_sha256")),
            ("stderr sha256", hashlib.sha256(stderr.getvalue().encode()).hexdigest(), entry.get("stderr_sha256")),
        )
        for label, actual, expected in observations:
            if actual != expected:
                errors.append(f"{entry['path']} {label}: expected={expected!r}, actual={actual!r}")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--structure-only", action="store_true", help="Skip compiler validation.")
    parser.add_argument("--run-native", action="store_true", help="Compile and run all runnable V1_NATIVE entries.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_manifest()
    errors = structural_errors(manifest)
    if not args.structure_only:
        errors.extend(compiler_errors(manifest))
    if args.run_native:
        errors.extend(native_errors(manifest))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(
        "PASS: examples catalog has no BROKEN entries and matches its declared contracts."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
