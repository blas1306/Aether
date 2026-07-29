#!/usr/bin/env python3
"""Validate capability metadata against representative compiler lowering."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.backend.llvm import LLVMBuilder  # noqa: E402
from aether.capabilities import (  # noqa: E402
    AST_CAPABILITY_PROFILE,
    BACKEND_CAPABILITY_PROFILES,
    CAPABILITY_CATALOG,
    CAPABILITY_PROFILE_VERSION,
    E2E_TESTED_CAPABILITIES,
    NATIVE_CAPABILITY_PROFILE,
    BackendIdentity,
    Capability,
    CapabilityState,
    backend_capability_issues,
    detect_required_capabilities,
)
from aether.pipeline import prepare_typed_program  # noqa: E402
from aether.typechecker import TypeChecker  # noqa: E402


INTERFACE_PROBE = """
interface Value {
    int get();
}

class Counter implements Value {
    int value;

    constructor(int initial) {
        value = initial;
    }

    public int get() {
        return value;
    }
}

struct Box implements Value {
    int value;

    int get() {
        return value;
    }
}

int read(Value value) {
    return value.get();
}

int main() {
    Value classValue = Counter(3);
    Value structValue = Box(4);
    return read(classValue) + read(structValue) - 7;
}
"""


def check() -> list[str]:
    errors: list[str] = []
    if CAPABILITY_PROFILE_VERSION != "23":
        errors.append(
            f"expected capability profile 23, got {CAPABILITY_PROFILE_VERSION}"
        )
    if set(CAPABILITY_CATALOG) != set(Capability):
        errors.append("capability catalog does not exactly cover the enum")
    for profile in BACKEND_CAPABILITY_PROFILES.values():
        if profile.version != CAPABILITY_PROFILE_VERSION:
            errors.append(
                f"{profile.backend.value} profile version {profile.version} "
                f"does not match {CAPABILITY_PROFILE_VERSION}"
            )
        complete = {
            capability
            for capability, support in profile.capabilities.items()
            if support.state is CapabilityState.COMPLETE
        }
        missing_evidence = complete - E2E_TESTED_CAPABILITIES[profile.backend]
        if missing_evidence:
            errors.append(
                f"{profile.backend.value} COMPLETE capabilities lack E2E evidence: "
                + ", ".join(sorted(capability.value for capability in missing_evidence))
            )

    values = {capability.value for capability in Capability}
    for obsolete in ("native-interface-abi", "string-split-trim"):
        if obsolete in values:
            errors.append(f"obsolete capability remains in catalog: {obsolete}")

    for profile in (AST_CAPABILITY_PROFILE, NATIVE_CAPABILITY_PROFILE):
        state = profile.support_for(Capability.INTERFACES).state
        if state is not CapabilityState.COMPLETE:
            errors.append(
                f"{profile.backend.value} interfaces must be COMPLETE, got {state.value}"
            )

    try:
        typed = prepare_typed_program(INTERFACE_PROBE, TypeChecker())
        requirements = {
            requirement.capability
            for requirement in detect_required_capabilities(typed)
        }
        if Capability.INTERFACES not in requirements:
            errors.append("interface probe does not detect the interfaces capability")
        issues = backend_capability_issues(typed, BackendIdentity.NATIVE)
        if issues:
            errors.append(
                "native profile rejects the implemented interface probe: "
                + ", ".join(sorted(issue.diagnostic_code for issue in issues))
            )
        llvm = LLVMBuilder().emit_llvm(typed)
        for marker in ("%interface.call", ".copy_owned", "witness"):
            if marker not in llvm:
                errors.append(
                    f"interface probe LLVM is missing implemented marker {marker!r}"
                )
    except Exception as exc:
        errors.append(
            f"interface compiler probe failed: {type(exc).__name__}: {exc}"
        )

    return errors


def main() -> int:
    errors = check()
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(
        "PASS: capability profile matches catalog, evidence, and native "
        "class/struct interface lowering."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
