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
    ROOT / "docs" / "aether" / "AETHER_IR_DESIGN.md": "Design/RFC",
    ROOT / "docs" / "aether" / "AETHER_FRONTEND_EXPERIMENTS.md": "Non-normative",
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


def _expand_audit_ids(block: str) -> frozenset[str]:
    identifiers: set[str] = set()
    for token in block.split():
        match = re.fullmatch(r"([CTERB])(\d{2})(?:-([CTERB]?)(\d{2}))?", token)
        if match is None:
            raise ValueError(f"invalid audit row token in normative inventory: {token!r}")
        prefix, start_text, end_prefix, end_text = match.groups()
        start = int(start_text)
        if end_text is None:
            identifiers.add(f"{prefix}{start:02d}")
            continue
        if end_prefix and end_prefix != prefix:
            raise ValueError(f"mixed-prefix audit row range: {token!r}")
        identifiers.update(
            f"{prefix}{number:02d}" for number in range(start, int(end_text) + 1)
        )
    return frozenset(identifiers)


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
        "Aether 1.0 is the single language profile",
        "exactly the 75",
        "zero-based, half-open `[start,end)`",
        "Array/List assignment is O(1) reference assignment",
        "A string is immutable valid UTF-8",
        "Native v1 panics do not unwind",
        "Windows and macOS are not supported native platforms",
        "C01 C03-C05 C07-C12 C14 C16-C23 C25",
        "C02 C06 C13 C15 C24 C26",
    )
    combined = spec + "\n" + NORMATIVE[1].read_text(encoding="utf-8")
    for contract in required_contracts:
        if contract not in combined:
            errors.append(f"normative contract is missing: {contract!r}")

    audit = (ROOT / "docs" / "aether" / "AETHER_V1_PROFILE_AUDIT.md").read_text(
        encoding="utf-8"
    )
    audited: dict[str, set[str]] = {
        "SUPPORTED": set(),
        "OUTSIDE_V1": set(),
        "BROKEN": set(),
        "UNDECIDED": set(),
    }
    for row_id, state in re.findall(
        r"^\| ([CTERB]\d{2}) \|.*\| (SUPPORTED|OUTSIDE_V1|BROKEN|UNDECIDED) \|.*$",
        audit,
        flags=re.MULTILINE,
    ):
        audited[state].add(row_id)

    inventory_blocks = re.findall(r"```text\n((?:[CTERB]\d{2}[^\n]*\n)+)```", spec)
    try:
        normative_sets = [_expand_audit_ids(block) for block in inventory_blocks]
    except ValueError as exc:
        errors.append(str(exc))
        normative_sets = []
    if len(normative_sets) != 2:
        errors.append(
            "normative spec must contain exactly two audit-ID blocks "
            "(SUPPORTED and OUTSIDE_V1)"
        )
    else:
        for state, actual in zip(("SUPPORTED", "OUTSIDE_V1"), normative_sets):
            expected = frozenset(audited[state])
            if actual != expected:
                missing = sorted(expected - actual)
                extra = sorted(actual - expected)
                errors.append(
                    f"normative {state} inventory differs from audit: "
                    f"missing={missing}, extra={extra}"
                )
    observed_counts = {state: len(rows) for state, rows in audited.items()}
    expected_counts = {"SUPPORTED": 75, "OUTSIDE_V1": 46, "BROKEN": 2, "UNDECIDED": 0}
    if observed_counts != expected_counts:
        errors.append(
            f"profile audit counts changed: expected={expected_counts}, "
            f"actual={observed_counts}"
        )
    if audited["BROKEN"] != {"B12", "B13"}:
        errors.append(f"unexpected BROKEN audit rows: {sorted(audited['BROKEN'])}")

    contradictions = (
        "The AST profile is the semantic reference for the full frontend surface",
        "The native profile is a normative, deliberately smaller implementation subset",
        "Classes are defined by the language",
        "Interfaces are defined by the language",
        "Tuple values and destructuring are defined",
        "`${expression}` interpolation is part of the language",
        "The production and default backend is the AST backend",
    )
    normative_text = "\n".join(
        document.read_text(encoding="utf-8") for document in NORMATIVE
    )
    ir_design = (ROOT / "docs" / "aether" / "AETHER_IR_DESIGN.md").read_text(
        encoding="utf-8"
    )
    for contradiction in contradictions:
        if contradiction in normative_text or contradiction in ir_design:
            errors.append(f"known documentation contradiction: {contradiction!r}")

    readme = (ROOT / "docs" / "aether" / "README.md").read_text(encoding="utf-8")
    required_index_links = (
        "AETHER_LANGUAGE_SPEC_V1.md",
        "AETHER_NATIVE_PROFILE_V1.md",
        "AETHER_V1_PROFILE_AUDIT.md",
        "AETHER_V1_PROFILE_DECISION.md",
        "../../examples/v1_examples_manifest.json",
    )
    for target in required_index_links:
        if target not in readme:
            errors.append(f"documentation index is missing link: {target!r}")

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
