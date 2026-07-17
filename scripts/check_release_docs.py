#!/usr/bin/env python3
"""Validate normative-document links, classifications, and frozen contracts."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
NORMATIVE = (
    ROOT / "docs" / "aether" / "AETHER_LANGUAGE_SPEC_V1.md",
    ROOT / "docs" / "aether" / "AETHER_NATIVE_PROFILE_V1.md",
)
CLASSIFIED = {
    ROOT / "docs" / "EVOLUTION.md": "Historical",
    ROOT / "docs" / "aether" / "AETHER_V0_SPEC.md": "Historical",
    ROOT / "docs" / "aether" / "AETHER_V1_SCOPE.md": "Design/RFC",
    ROOT / "docs" / "aether" / "AETHER_V1_RELEASE_READINESS.md": "Audit",
    ROOT / "docs" / "aether" / "BACKEND_CAPABILITY_PROFILES.md": "Design/RFC",
    ROOT / "docs" / "aether" / "BACKEND_FEATURE_PARITY.md": "Audit",
    ROOT / "docs" / "aether" / "BUILTINS_AND_STDLIB_DESIGN.md": "Design/RFC",
    ROOT / "docs" / "aether" / "STRING_RUNTIME_DESIGN.md": "Design/RFC",
    ROOT / "docs" / "aether" / "COLLECTION_RUNTIME_DESIGN.md": "Design/RFC",
    ROOT / "docs" / "compiler" / "VALUE_LIFECYCLE_DESIGN.md": "Design/RFC",
    ROOT / "docs" / "aether" / "TEXT_FILE_IO_DESIGN.md": "Design/RFC",
    ROOT / "docs" / "aether" / "PERSISTENCE_FORMAT_DESIGN.md": "Design/RFC",
}


def _local_markdown_links(path: Path) -> tuple[Path, ...]:
    text = path.read_text(encoding="utf-8")
    targets: list[Path] = []
    for raw in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        target = raw.split("#", 1)[0].strip()
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        targets.append((path.parent / target).resolve())
    return tuple(targets)


def check() -> list[str]:
    errors: list[str] = []
    for document in NORMATIVE:
        if not document.is_file():
            errors.append(f"missing normative document: {document.relative_to(ROOT)}")
            continue
        text = document.read_text(encoding="utf-8")
        if "Classification: **Normative**" not in text:
            errors.append(f"missing Normative classification: {document.relative_to(ROOT)}")
        for target in _local_markdown_links(document):
            if not target.exists():
                errors.append(
                    f"broken link in {document.relative_to(ROOT)}: {target}"
                )

    for document, classification in CLASSIFIED.items():
        opening = "\n".join(document.read_text(encoding="utf-8").splitlines()[:10])
        if classification not in opening:
            errors.append(
                f"{document.relative_to(ROOT)} is not classified as {classification}"
            )

    spec = NORMATIVE[0].read_text(encoding="utf-8")
    required_contracts = (
        "zero-based, half-open `[start,end)`",
        "Array/List assignment is O(1) reference assignment",
        "A string is immutable valid UTF-8",
        "Classes, interfaces, callables",
        "Native v1 panics do not unwind",
        "Windows is not a\n+supported native platform".replace("\n+", "\n"),
    )
    combined = spec + "\n" + NORMATIVE[1].read_text(encoding="utf-8")
    for contract in required_contracts:
        if contract not in combined:
            errors.append(f"normative contract is missing: {contract!r}")

    rendered = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "render_native_profile.py"), "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if rendered.returncode != 0:
        errors.append(rendered.stderr.strip() or rendered.stdout.strip())
    return errors


def main() -> int:
    errors = check()
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: release documentation integrity and classification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
