#!/usr/bin/env python3
"""Closed artifact inventory for RUST-IR-2 shadow qualification."""

from __future__ import annotations


MILESTONE = "RUST-IR-2"
BASELINE_REVISION = "b563054f5f94ab373089f4d9dd9ae7629f242a59"
BASELINE_SUBJECT = "Add Rust pre-lifecycle IR admission verification"
QUALIFIED = "RUST_INITIAL_IR_PRE_LIFECYCLE_SHADOW_QUALIFIED"
BLOCKED = "RUST_INITIAL_IR_PRE_LIFECYCLE_SHADOW_QUALIFICATION_BLOCKED"

BASE = {
    "rust-ir-2-contract": ("contract-and-baseline", "contract_and_baseline"),
    "rust-ir-2-rust-validation": ("rust-verifier-unit", "rust_verifier_unit"),
    "rust-ir-2-valid-corpus": ("valid-corpus-differential", "valid_corpus_differential"),
    "rust-ir-2-mutations": ("mutation-campaign", "mutation_campaign"),
    "rust-ir-2-irv041": ("critical-irv041-regressions", "critical_irv041_regressions"),
    "rust-ir-2-provenance": ("production-pre-lifecycle-provenance", "production_pre_lifecycle_provenance"),
    "rust-ir-2-lifecycle-boundary": ("lifecycle-boundary-regression", "lifecycle_boundary_regression"),
    "rust-ir-2-packaged-consumer": ("packaged-clean-consumer", "packaged_clean_consumer"),
    "rust-ir-2-source-install": ("source-development-install", "source_development_install"),
    "rust-ir-2-recovery": ("next-request-recovery", "next_request_recovery"),
    "rust-ir-2-transport": ("transport-continuity", "transport_continuity"),
    "rust-ir-2-performance": ("performance-characterization", "performance_characterization"),
}
PLATFORMS = (
    "linux-x86_64",
    "windows-x86_64",
    "macos-x86_64",
    "macos-arm64",
)
PYTHONS = ("3.11", "3.12", "3.13", "3.14")
TARGETS = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "windows-x86_64": "x86_64-pc-windows-msvc",
    "macos-x86_64": "x86_64-apple-darwin",
    "macos-arm64": "aarch64-apple-darwin",
}


def expected() -> dict[str, tuple[str, str]]:
    """Return the exact, non-substitutable mandatory artifact inventory."""

    result = dict(BASE)
    result.update(
        {
            f"rust-ir-2-platform-{platform}": (
                "platform-qualification",
                "platform_qualification",
            )
            for platform in PLATFORMS
        }
    )
    result.update(
        {
            f"rust-ir-2-python-{version}": (
                "python-compatibility",
                "python_compatibility",
            )
            for version in PYTHONS
        }
    )
    return result


def mandatory_jobs() -> set[str]:
    """Return the exact aggregate job-result keys."""

    return {job for job, _kind in BASE.values()} | {
        "platform-qualification",
        "python-compatibility",
    }


__all__ = [
    "BASE",
    "BASELINE_REVISION",
    "BASELINE_SUBJECT",
    "BLOCKED",
    "MILESTONE",
    "PLATFORMS",
    "PYTHONS",
    "QUALIFIED",
    "TARGETS",
    "expected",
    "mandatory_jobs",
]
