from __future__ import annotations

import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil

import pytest

from aether.backend.llvm import LLVMBuilder, LLVMRunner
from aether.capabilities import (
    BackendCapabilityError,
    BackendIdentity,
    Capability,
    backend_capability_issues,
)
from aether.errors import AetherError
from aether.pipeline import prepare_typed_program
from aether.typechecker import TypeChecker


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "examples" / "v1_examples_manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
ENTRIES = MANIFEST["entries"]


def _typed(entry: dict[str, object]):
    path = ROOT / str(entry["path"])
    return prepare_typed_program(
        path.read_text(encoding="utf-8"),
        TypeChecker(source_root=path.parent, entry_path=path),
    )


def test_example_manifest_is_complete_authoritative_and_uses_closed_states() -> None:
    actual_paths = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "examples").rglob("*.ae")
    }
    manifest_paths = [str(entry["path"]) for entry in ENTRIES]

    assert MANIFEST["language_version"] == "1.0.0-rc.2"
    assert MANIFEST["native_capability_profile"] == "22"
    assert len(manifest_paths) == len(set(manifest_paths))
    assert set(manifest_paths) == actual_paths
    assert {entry["profile"] for entry in ENTRIES} <= {
        "V1_NATIVE",
        "AST_ONLY_EXPERIMENTAL",
        "OUTDATED",
        "BROKEN",
    }
    assert sum(entry["profile"] == "V1_NATIVE" for entry in ENTRIES) == 78
    assert sum(entry["profile"] == "AST_ONLY_EXPERIMENTAL" for entry in ENTRIES) == 21
    assert sum(entry["profile"] == "BROKEN" for entry in ENTRIES) == 4
    assert all(entry["timeout_seconds"] > 0 for entry in ENTRIES)
    assert all(
        entry["reason"]
        for entry in ENTRIES
        if entry["profile"] != "V1_NATIVE"
    )


@pytest.mark.parametrize(
    "entry",
    ENTRIES,
    ids=[str(entry["path"]) for entry in ENTRIES],
)
def test_every_example_matches_its_manifest_classification(entry: dict[str, object]) -> None:
    profile = entry["profile"]
    if profile == "BROKEN":
        with pytest.raises(AetherError):
            _typed(entry)
        return

    typed = _typed(entry)
    issues = backend_capability_issues(typed, BackendIdentity.NATIVE)
    if profile == "AST_ONLY_EXPERIMENTAL":
        assert issues
        assert {issue.diagnostic_code for issue in issues} <= set(
            str(entry["reason"]).removeprefix("Outside native/v1: ").split(", ")
        )
        return

    assert profile == "V1_NATIVE"
    assert issues == ()
    LLVMBuilder().emit_llvm(typed)


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize(
    "entry",
    [entry for entry in ENTRIES if entry["condition"] == "native_execution"],
    ids=[
        str(entry["path"])
        for entry in ENTRIES
        if entry["condition"] == "native_execution"
    ],
)
def test_v1_native_example_observations_match_manifest(entry: dict[str, object]) -> None:
    stdout = StringIO()
    stderr = StringIO()
    exit_code = LLVMRunner().run(_typed(entry), stdout=stdout, stderr=stderr)

    assert exit_code == entry["expected_exit_code"]
    assert hashlib.sha256(stdout.getvalue().encode()).hexdigest() == entry["stdout_sha256"]
    assert hashlib.sha256(stderr.getvalue().encode()).hexdigest() == entry["stderr_sha256"]


@pytest.mark.parametrize(
    ("source", "expected_code"),
    [
        ("int main() { float value = float(1); return int(value); }", "AE-BACKEND-PRIMITIVE_TYPES"),
        ("int main() { complex value = 1im; println(value); return 0; }", "AE-BACKEND-PRIMITIVE_TYPES"),
        ("class Box { int value; } int main() { return 0; }", "AE-BACKEND-CLASSES"),
        ("interface Value { int get(); } int main() { return 0; }", "AE-BACKEND-INTERFACES"),
        ("int main() { (int, int) pair = (1, 2); return 0; }", "AE-BACKEND-PRIMITIVE_TYPES"),
        (
            "int main() { const values = 1:3; for (int value in values) { println(value); } return 0; }",
            "AE-BACKEND-FOR_IN",
        ),
        ('int main() { string value = input("value: "); return 0; }', "AE-BACKEND-INPUT"),
        ('int main() { int n = 2; println("n=$n$"); return 0; }', "AE-BACKEND-STRINGS"),
        (
            'int main() { try { throw "bad"; } catch (error) { println(error); } return 0; }',
            "AE-BACKEND-ERROR_HANDLING",
        ),
    ],
)
def test_outside_v1_surfaces_fail_at_capability_gate_before_lowering(
    source: str,
    expected_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typed = prepare_typed_program(source, TypeChecker())

    def fail_if_lowered(*_args, **_kwargs):
        raise AssertionError("IR lowering must not run for an outside-v1 feature")

    monkeypatch.setattr(
        "aether.ir.lowering.IRLowerer.lower_checked_program",
        fail_if_lowered,
    )
    with pytest.raises(BackendCapabilityError) as captured:
        LLVMBuilder().emit_llvm(typed)

    assert expected_code in {issue.diagnostic_code for issue in captured.value.issues}


def test_abbreviated_functions_are_declarations_not_function_values() -> None:
    source = "double square(double x) = x ^ 2; int main() { return int(square(3)); }"
    typed = prepare_typed_program(source, TypeChecker())
    issues = backend_capability_issues(typed, BackendIdentity.NATIVE)

    assert not any(
        issue.requirement.capability is Capability.FUNCTION_VALUES
        for issue in issues
    )
    assert issues == ()
    LLVMBuilder().emit_llvm(typed)


def test_capture_free_top_level_function_values_are_in_native_v1_subset() -> None:
    source = """
int twice(int value) = value * 2;
int apply(int(int) operation, int value) { return operation(value); }
int main() { return apply(twice, 4); }
"""
    typed = prepare_typed_program(source, TypeChecker())

    assert backend_capability_issues(typed, BackendIdentity.NATIVE) == ()
    assert "call i32 %" in LLVMBuilder().emit_llvm(typed)
