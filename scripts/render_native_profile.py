#!/usr/bin/env python3
"""Render or verify the generated capability table in the normative profile."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.capabilities import (  # noqa: E402
    CAPABILITY_CATALOG,
    CAPABILITY_PROFILE_VERSION,
    CapabilityState,
    NATIVE_CAPABILITY_PROFILE,
)


PROFILE_DOCUMENT = ROOT / "docs" / "aether" / "AETHER_NATIVE_PROFILE_V1.md"
START_MARKER = "<!-- BEGIN GENERATED CAPABILITY PROFILE -->"
END_MARKER = "<!-- END GENERATED CAPABILITY PROFILE -->"


def render_capability_table() -> str:
    counts = {
        state: sum(
            support.state is state
            for support in NATIVE_CAPABILITY_PROFILE.capabilities.values()
        )
        for state in CapabilityState
    }
    lines = [
        START_MARKER,
        f"Profile schema/version: `{CAPABILITY_PROFILE_VERSION}`.",
        "",
        (
            f"Inventory: {counts[CapabilityState.COMPLETE]} COMPLETE, "
            f"{counts[CapabilityState.PARTIAL]} PARTIAL, "
            f"{counts[CapabilityState.UNSUPPORTED]} UNSUPPORTED."
        ),
        "",
        "| Capability | State | Contract area |",
        "| --- | --- | --- |",
    ]
    for capability, support in NATIVE_CAPABILITY_PROFILE.capabilities.items():
        description = CAPABILITY_CATALOG[capability].description.replace("|", "\\|")
        lines.append(
            f"| `{capability.value}` | **{support.state.value.upper()}** | {description} |"
        )
    lines.append(END_MARKER)
    return "\n".join(lines)


def rendered_document(current: str) -> str:
    if START_MARKER not in current or END_MARKER not in current:
        raise ValueError(f"generated profile markers are missing from {PROFILE_DOCUMENT}")
    before, remainder = current.split(START_MARKER, 1)
    _old, after = remainder.split(END_MARKER, 1)
    return before + render_capability_table() + after


def check_document() -> bool:
    current = PROFILE_DOCUMENT.read_text(encoding="utf-8")
    return current == rendered_document(current)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()

    current = PROFILE_DOCUMENT.read_text(encoding="utf-8")
    expected = rendered_document(current)
    if args.check:
        if current != expected:
            print(
                f"{PROFILE_DOCUMENT.relative_to(ROOT)} is out of sync with capability profile "
                f"{CAPABILITY_PROFILE_VERSION}.",
                file=sys.stderr,
            )
            return 1
        print(
            f"PASS: normative native profile matches capability profile "
            f"{CAPABILITY_PROFILE_VERSION}."
        )
        return 0
    PROFILE_DOCUMENT.write_text(expected, encoding="utf-8")
    print(f"Updated {PROFILE_DOCUMENT.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
