#!/usr/bin/env python3
"""Validate normative-document links, classifications, and frozen contracts."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.capabilities import CAPABILITY_PROFILE_VERSION  # noqa: E402
from aether.version import LANGUAGE_VERSION, PACKAGE_VERSION  # noqa: E402


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
    ROOT / "docs" / "aether" / "AETHER_EXAMPLES_CATALOG_AUDIT.md": "Audit",
    ROOT / "docs" / "aether" / "AETHER_V1_PROFILE_AUDIT.md": "Audit",
    ROOT / "docs" / "aether" / "AETHER_V1_PROFILE_DECISION.md": "Audit",
    ROOT / "docs" / "compiler" / "BACKEND_FEATURE_PARITY.md": "Audit",
    ROOT / "docs" / "compiler" / "EXCEPTION_RELEASE_QUALIFICATION.md": "Audit",
}
CURRENT_REFERENCE = (
    ROOT / "README.md",
    *NORMATIVE,
    ROOT / "docs" / "aether" / "README.md",
    ROOT / "docs" / "compiler" / "FEATURE_MATRIX.md",
    ROOT / "docs" / "compiler" / "NATIVE_OBJECT_MODEL_DESIGN.md",
    ROOT / "docs" / "compiler" / "AETHER_NATIVE_ABI.md",
    ROOT / "docs" / "compiler" / "CI.md",
    ROOT / "docs" / "aether" / "AETHER_1_0_0_RC4_RELEASE_NOTES.md",
)


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
        "zero-based, half-open `[start,end)`",
        "Array/List assignment is O(1) reference assignment",
        "A string is immutable valid UTF-8",
        "Native v1 panics do not unwind",
        "Windows and macOS are not supported native platforms",
        "A `class` is a nominal mutable reference type",
        "An `interface` is a nominal method contract",
        "Profile 23 supports tagged nullable values",
    )
    combined = spec + "\n" + NORMATIVE[1].read_text(encoding="utf-8")
    for contract in required_contracts:
        if contract not in combined:
            errors.append(f"normative contract is missing: {contract!r}")
    for document in NORMATIVE:
        text = document.read_text(encoding="utf-8")
        if "`Error.message()`" not in text or "semantically non-throwing" not in text:
            errors.append(
                "normative Error.message() contract is missing: "
                f"{document.relative_to(ROOT)}"
            )

    contradictions = (
        "The AST profile is the semantic reference for the full frontend surface",
        "The native profile is a normative, deliberately smaller implementation subset",
        "Tuple values and destructuring are defined",
        "`${expression}` interpolation is part of the language",
        "The production and default backend is the AST backend",
        "classes por referencia e interfaces siguen solo AST",
        "interfaces` | **UNSUPPORTED**",
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

    release_document_id = (
        LANGUAGE_VERSION.replace("-rc.", "_RC").replace(".", "_").upper()
    )
    expected_release_note = (
        ROOT
        / "docs"
        / "aether"
        / f"AETHER_{release_document_id}_RELEASE_NOTES.md"
    )
    if expected_release_note not in CURRENT_REFERENCE or not expected_release_note.is_file():
        errors.append(
            "current release notes do not match canonical language version: "
            f"{expected_release_note.relative_to(ROOT)}"
        )

    current_text = {
        document: document.read_text(encoding="utf-8")
        for document in CURRENT_REFERENCE
    }
    identity_claims = {
        ROOT / "README.md": (LANGUAGE_VERSION, CAPABILITY_PROFILE_VERSION),
        NORMATIVE[0]: (LANGUAGE_VERSION, CAPABILITY_PROFILE_VERSION),
        NORMATIVE[1]: (LANGUAGE_VERSION, CAPABILITY_PROFILE_VERSION),
        expected_release_note: (
            LANGUAGE_VERSION,
            PACKAGE_VERSION,
            CAPABILITY_PROFILE_VERSION,
        ),
    }
    for document, expected in identity_claims.items():
        for identity in expected:
            if identity not in current_text[document]:
                errors.append(
                    f"{document.relative_to(ROOT)} is missing current identity {identity!r}"
                )

    compiler_claims = {
        ROOT / "docs" / "compiler" / "FEATURE_MATRIX.md": (
            "`interfaces` C",
            "structural\noperand traversal",
        ),
        ROOT / "docs" / "compiler" / "NATIVE_OBJECT_MODEL_DESIGN.md": (
            "boxing owned",
            "Phase 5.4C",
        ),
        ROOT / "docs" / "compiler" / "AETHER_NATIVE_ABI.md": (
            "profile native 23",
            "dispatch/boxing 5.4A–5.4C",
        ),
        ROOT / "docs" / "compiler" / "CI.md": (
            "capability consistency",
            "documentation consistency",
        ),
    }
    for document, claims in compiler_claims.items():
        for claim in claims:
            if claim not in current_text[document]:
                errors.append(
                    f"{document.relative_to(ROOT)} is missing compiler claim {claim!r}"
                )

    readme = (ROOT / "docs" / "aether" / "README.md").read_text(encoding="utf-8")
    required_index_links = (
        "AETHER_LANGUAGE_SPEC_V1.md",
        "AETHER_NATIVE_PROFILE_V1.md",
        "AETHER_V1_PROFILE_AUDIT.md",
        "AETHER_V1_PROFILE_DECISION.md",
        "../../examples/v1_examples_manifest.json",
        "AETHER_EXAMPLES_CATALOG_AUDIT.md",
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
