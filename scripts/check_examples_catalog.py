#!/usr/bin/env python3
"""Validate the authoritative Aether examples catalog."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from io import StringIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.backend.llvm import LLVMBuilder, LLVMRunner  # noqa: E402
from aether.capabilities import (  # noqa: E402
    CAPABILITY_PROFILE_VERSION,
    BackendIdentity,
    backend_capability_issues,
)
from aether.cli import main as cli_main  # noqa: E402
from aether.pipeline import IRBackend, SSAPipeline, prepare_typed_program  # noqa: E402
from aether.typechecker import TypeChecker  # noqa: E402
from aether.version import LANGUAGE_VERSION  # noqa: E402


MANIFEST_PATH = ROOT / "examples" / "v1_examples_manifest.json"
VALID_CLASSIFICATIONS = {"V1_NATIVE", "AST_ONLY_EXPERIMENTAL"}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
REQUIRED_FIELDS = {
    "path",
    "classification",
    "backends",
    "run",
    "expected_exit_code",
    "stdout_sha256",
    "stderr_sha256",
    "timeout_seconds",
    "condition",
}
ENTRY_CONTRACTS = {
    ("V1_NATIVE", True): ("native_execution", ["native"]),
    ("V1_NATIVE", False): ("native_module_emission", ["native"]),
    ("AST_ONLY_EXPERIMENTAL", True): ("ast_execution", ["ast"]),
    ("AST_ONLY_EXPERIMENTAL", False): ("frontend_acceptance", ["ast"]),
}


def load_manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def observation_sha256(text: str) -> str:
    """Hash canonical UTF-8 observation text with LF line endings."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def canonical_manifest_text(manifest: dict[str, object]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def write_manifest(manifest: dict[str, object], path: Path = MANIFEST_PATH) -> bool:
    rendered = canonical_manifest_text(manifest)
    if path.is_file() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.write_text(rendered, encoding="utf-8", newline="\n")
    return True


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
    if manifest.get("language_version") != LANGUAGE_VERSION:
        errors.append(
            "manifest language_version must match the compiler: "
            f"{LANGUAGE_VERSION}"
        )
    if manifest.get("native_capability_profile") != CAPABILITY_PROFILE_VERSION:
        errors.append(
            "manifest native_capability_profile must match the compiler: "
            f"{CAPABILITY_PROFILE_VERSION}"
        )
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
        normalized = PurePosixPath(path)
        if (
            "\\" in path
            or normalized.is_absolute()
            or "." in normalized.parts
            or ".." in normalized.parts
            or normalized.as_posix() != path
            or not path.startswith("examples/")
            or normalized.suffix != ".ae"
        ):
            errors.append(f"manifest path is not a normalized public example path: {path}")
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
                if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
                    errors.append(f"runnable entry needs {stream}_sha256: {path}")
        else:
            if entry.get("expected_exit_code") is not None:
                errors.append(f"non-runnable entry must use a null expected_exit_code: {path}")
            for stream in ("stdout", "stderr"):
                if entry.get(f"{stream}_sha256") is not None:
                    errors.append(f"non-runnable entry must use a null {stream}_sha256: {path}")
        if not isinstance(entry.get("timeout_seconds"), int) or entry.get("timeout_seconds", 0) <= 0:
            errors.append(f"entry timeout_seconds must be positive: {path}")
        if "ast_parity" in entry and not isinstance(entry["ast_parity"], bool):
            errors.append(f"entry ast_parity must be boolean: {path}")
        if entry.get("ast_parity") is False and (
            classification != "V1_NATIVE" or entry.get("run") is not True
        ):
            errors.append(
                f"AST parity exclusion requires a runnable V1_NATIVE entry: {path}"
            )
        if classification in VALID_CLASSIFICATIONS and isinstance(entry.get("run"), bool):
            expected_condition, expected_backends = ENTRY_CONTRACTS[
                (str(classification), bool(entry["run"]))
            ]
            if entry.get("condition") != expected_condition:
                errors.append(
                    f"entry condition mismatch for {path}: "
                    f"expected={expected_condition!r}, actual={entry.get('condition')!r}"
                )
            if entry.get("backends") != expected_backends:
                errors.append(
                    f"entry backend mismatch for {path}: "
                    f"expected={expected_backends!r}, actual={entry.get('backends')!r}"
                )
        if classification == "V1_NATIVE":
            if "native" not in entry.get("backends", []):
                errors.append(f"V1_NATIVE entry must declare native: {path}")
            if "outside_v1_features" in entry:
                errors.append(f"V1_NATIVE entry cannot declare outside_v1_features: {path}")
        if classification == "AST_ONLY_EXPERIMENTAL":
            features = entry.get("outside_v1_features")
            if not isinstance(features, list) or not features or not all(
                isinstance(feature, str) and feature for feature in features
            ):
                errors.append(f"experimental entry lacks outside_v1_features: {path}")
            elif features != sorted(set(features)):
                errors.append(f"experimental capabilities must be sorted and unique: {path}")
            if "native" in entry.get("backends", []):
                errors.append(f"experimental entry cannot declare native: {path}")

    if paths != sorted(paths):
        errors.append("manifest entries must use deterministic path ordering")
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
    documentation_claims = {
        ROOT / "docs" / "aether" / "AETHER_EXAMPLES_CATALOG_AUDIT.md": (
            f"catálogo actual contiene {len(entries)} rutas: "
            f"{counts['V1_NATIVE']} `V1_NATIVE`, "
            f"{counts['AST_ONLY_EXPERIMENTAL']} `AST_ONLY_EXPERIMENTAL`"
        ),
        ROOT / "docs" / "aether" / "AETHER_V1_PROFILE_AUDIT.md": (
            f"catálogo actual tiene {counts['V1_NATIVE']} `V1_NATIVE`, "
            f"{counts['AST_ONLY_EXPERIMENTAL']} `AST_ONLY_EXPERIMENTAL`"
        ),
        ROOT / "docs" / "aether" / "AETHER_1_0_0_RC4_RELEASE_NOTES.md": (
            f"schema-2 catalog classifies {counts['V1_NATIVE']} examples as "
            f"`V1_NATIVE`, {counts['AST_ONLY_EXPERIMENTAL']} as "
            f"`AST_ONLY_EXPERIMENTAL`"
        ),
    }
    for document, claim in documentation_claims.items():
        text = " ".join(
            line.lstrip("> ").strip()
            for line in document.read_text(encoding="utf-8").splitlines()
        )
        if claim not in text:
            errors.append(
                f"example count is stale in {document.relative_to(ROOT).as_posix()}"
            )
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
                    exit_code, stdout, stderr = runtime_observation(entry)
                    observations = (
                        ("exit code", exit_code, entry["expected_exit_code"]),
                        (
                            "stdout sha256",
                            observation_sha256(stdout),
                            entry.get("stdout_sha256"),
                        ),
                        (
                            "stderr sha256",
                            observation_sha256(stderr),
                            entry.get("stderr_sha256"),
                        ),
                    )
                    for label, actual, expected in observations:
                        if actual != expected:
                            errors.append(
                                f"{path} AST {label}: "
                                f"expected={expected!r}, actual={actual!r}"
                            )
                    if "Traceback" in stderr:
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
            exit_code = LLVMRunner().run(
                typed_entry(entry),
                stdout=stdout,
                stderr=stderr,
                timeout_seconds=int(entry["timeout_seconds"]),
            )
        except Exception as exc:
            errors.append(f"native execution failed for {entry['path']}: {type(exc).__name__}: {exc}")
            continue
        observations = (
            ("exit code", exit_code, entry["expected_exit_code"]),
            ("stdout sha256", observation_sha256(stdout.getvalue()), entry.get("stdout_sha256")),
            ("stderr sha256", observation_sha256(stderr.getvalue()), entry.get("stderr_sha256")),
        )
        for label, actual, expected in observations:
            if actual != expected:
                errors.append(f"{entry['path']} {label}: expected={expected!r}, actual={actual!r}")
    return errors


ObservationProvider = Callable[[dict[str, object]], tuple[int, str, str]]


def runtime_observation(entry: dict[str, object]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    if entry["classification"] == "V1_NATIVE":
        exit_code = LLVMRunner().run(
            typed_entry(entry),
            stdout=stdout,
            stderr=stderr,
            timeout_seconds=int(entry["timeout_seconds"]),
        )
    else:
        previous_mode = os.environ.get("AETHER_PLOT_MODE")
        previous_directory = os.environ.get("AETHER_PLOT_DIR")
        with tempfile.TemporaryDirectory(prefix="aether-example-plots-") as plot_directory:
            os.environ["AETHER_PLOT_MODE"] = "document"
            os.environ["AETHER_PLOT_DIR"] = plot_directory
            try:
                exit_code = cli_main(
                    ["--backend", "ast", str(ROOT / str(entry["path"]))],
                    stdout=stdout,
                    stderr=stderr,
                )
            finally:
                if previous_mode is None:
                    os.environ.pop("AETHER_PLOT_MODE", None)
                else:
                    os.environ["AETHER_PLOT_MODE"] = previous_mode
                if previous_directory is None:
                    os.environ.pop("AETHER_PLOT_DIR", None)
                else:
                    os.environ["AETHER_PLOT_DIR"] = previous_directory
    return exit_code, stdout.getvalue(), stderr.getvalue()


def refreshed_manifest(
    manifest: dict[str, object],
    observation_provider: ObservationProvider = runtime_observation,
) -> dict[str, object]:
    refreshed = deepcopy(manifest)
    entries = refreshed["entries"]
    assert isinstance(entries, list)
    entries.sort(key=lambda entry: str(entry["path"]))
    for raw_entry in entries:
        assert isinstance(raw_entry, dict)
        entry = raw_entry
        typed = typed_entry(entry)
        issues = backend_capability_issues(typed, BackendIdentity.NATIVE)
        actual_codes = sorted(issue.diagnostic_code for issue in issues)
        if entry["classification"] == "V1_NATIVE":
            if issues:
                raise ValueError(
                    f"refusing to demote V1_NATIVE entry automatically: {entry['path']} "
                    f"has {actual_codes}"
                )
            IRBackend().lower_verified(typed)
            SSAPipeline().run(typed)
            LLVMBuilder().emit_llvm(typed)
        else:
            if not issues:
                raise ValueError(
                    f"refusing to promote AST_ONLY_EXPERIMENTAL entry automatically: "
                    f"{entry['path']} is accepted by native"
                )
            entry["outside_v1_features"] = actual_codes

        if not entry["run"]:
            entry["expected_exit_code"] = None
            entry["stdout_sha256"] = None
            entry["stderr_sha256"] = None
            continue
        exit_code, stdout, stderr = observation_provider(entry)
        if "Traceback" in stderr or (
            exit_code == 130 and "Aether interrupted." in stderr
        ):
            raise ValueError(f"refusing interrupted or traceback observation: {entry['path']}")
        entry["expected_exit_code"] = exit_code
        entry["stdout_sha256"] = observation_sha256(stdout)
        entry["stderr_sha256"] = observation_sha256(stderr)
    return refreshed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--structure-only", action="store_true", help="Skip compiler validation.")
    mode.add_argument(
        "--update",
        action="store_true",
        help="Refresh capability codes and canonical runtime observations.",
    )
    parser.add_argument(
        "--run-native",
        action="store_true",
        help="Compile and run all runnable V1_NATIVE entries.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.update and args.run_native:
        raise SystemExit("--update already runs native observations")
    manifest = load_manifest()
    errors = structural_errors(manifest)
    if args.update:
        if errors:
            for error in errors:
                print(f"FAIL: {error}", file=sys.stderr)
            return 1
        if shutil.which("clang") is None:
            print("FAIL: clang is required to update native observations", file=sys.stderr)
            return 1
        try:
            refreshed = refreshed_manifest(manifest)
        except Exception as exc:
            print(f"FAIL: manifest update failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        changed = write_manifest(refreshed)
        print("Updated examples manifest." if changed else "PASS: examples manifest is already current.")
        return 0
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
