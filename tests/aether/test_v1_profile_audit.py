from __future__ import annotations

from copy import deepcopy
from io import StringIO
import json
from pathlib import Path, PurePosixPath
import shutil

import pytest

from aether.backend.llvm import LLVMBuilder, LLVMRunner
from aether.capabilities import (
    BackendCapabilityError,
    BackendIdentity,
    Capability,
    backend_capability_issues,
)
from aether.cli import main as cli_main
from aether.pipeline import IRBackend, SSAPipeline, prepare_typed_program
from aether.typechecker import TypeChecker
from scripts.check_examples_catalog import (
    observation_sha256,
    structural_errors,
    write_manifest,
)


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

    assert MANIFEST["schema_version"] == 2
    assert MANIFEST["language_version"] == "1.0.0-rc.4"
    assert MANIFEST["native_capability_profile"] == "24"
    assert len(manifest_paths) == len(set(manifest_paths))
    assert set(manifest_paths) == actual_paths
    assert manifest_paths == sorted(manifest_paths)
    assert all(
        PurePosixPath(path).as_posix() == path
        and path.startswith("examples/")
        and path.endswith(".ae")
        for path in manifest_paths
    )
    assert {entry["classification"] for entry in ENTRIES} == {
        "V1_NATIVE",
        "AST_ONLY_EXPERIMENTAL",
    }
    assert not any(entry.get("classification") == "BROKEN" for entry in ENTRIES)
    assert all(
        {"path", "classification", "backends", "run", "expected_exit_code", "timeout_seconds"}
        <= entry.keys()
        for entry in ENTRIES
    )
    assert all(entry["timeout_seconds"] > 0 for entry in ENTRIES)
    assert all(
        entry["outside_v1_features"]
        for entry in ENTRIES
        if entry["classification"] == "AST_ONLY_EXPERIMENTAL"
    )
    assert not any(str(entry["path"]).startswith("tests/fixtures/") for entry in ENTRIES)


def test_manifest_structure_matches_the_canonical_validator() -> None:
    assert structural_errors(MANIFEST) == []


def test_manifest_validator_rejects_stale_release_and_profile_versions() -> None:
    stale = deepcopy(MANIFEST)
    stale["language_version"] = "1.0.0-rc.3"
    stale["native_capability_profile"] = "22"

    errors = structural_errors(stale)

    assert any("language_version must match the compiler" in error for error in errors)
    assert any(
        "native_capability_profile must match the compiler" in error
        for error in errors
    )


def test_manifest_validator_rejects_duplicate_paths() -> None:
    duplicate = deepcopy(MANIFEST)
    fixture_path = "examples/FormulaNumerosPrimos.ae"
    fixture = next(
        entry for entry in duplicate["entries"] if entry["path"] == fixture_path
    )
    duplicate["entries"].append(deepcopy(fixture))

    assert f"duplicate manifest path: {fixture_path}" in structural_errors(duplicate)


def test_observation_hashes_are_utf8_and_line_ending_portable() -> None:
    expected = observation_sha256("áether\nline two\n")

    assert observation_sha256("áether\r\nline two\r\n") == expected
    assert observation_sha256("áether\rline two\r") == expected


def test_canonical_manifest_writer_is_idempotent(tmp_path: Path) -> None:
    generated = tmp_path / "v1_examples_manifest.json"

    assert write_manifest(MANIFEST, generated)
    assert not write_manifest(MANIFEST, generated)
    assert generated.read_bytes().endswith(b"\n")


@pytest.mark.parametrize(
    "entry",
    ENTRIES,
    ids=[str(entry["path"]) for entry in ENTRIES],
)
def test_every_example_matches_its_manifest_classification(entry: dict[str, object]) -> None:
    classification = entry["classification"]
    typed = _typed(entry)
    issues = backend_capability_issues(typed, BackendIdentity.NATIVE)
    if classification == "AST_ONLY_EXPERIMENTAL":
        assert issues
        assert {issue.diagnostic_code for issue in issues} == set(
            entry["outside_v1_features"]
        )
        return

    assert classification == "V1_NATIVE"
    assert issues == ()
    IRBackend().lower_verified(typed)
    SSAPipeline().run(typed)
    LLVMBuilder().emit_llvm(typed)


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize(
    "entry",
    [
        entry
        for entry in ENTRIES
        if entry["classification"] == "V1_NATIVE" and entry["run"]
    ],
    ids=[
        str(entry["path"])
        for entry in ENTRIES
        if entry["classification"] == "V1_NATIVE" and entry["run"]
    ],
)
def test_v1_native_example_observations_match_manifest(entry: dict[str, object]) -> None:
    stdout = StringIO()
    stderr = StringIO()
    exit_code = LLVMRunner().run(
        _typed(entry),
        stdout=stdout,
        stderr=stderr,
        timeout_seconds=int(entry["timeout_seconds"]),
    )

    assert exit_code == entry["expected_exit_code"]
    assert observation_sha256(stdout.getvalue()) == entry["stdout_sha256"]
    assert observation_sha256(stderr.getvalue()) == entry["stderr_sha256"]


@pytest.mark.parametrize(
    "entry",
    [
        entry
        for entry in ENTRIES
        if entry["classification"] == "AST_ONLY_EXPERIMENTAL" and entry["run"]
    ],
    ids=[
        str(entry["path"])
        for entry in ENTRIES
        if entry["classification"] == "AST_ONLY_EXPERIMENTAL" and entry["run"]
    ],
)
def test_runnable_ast_experimental_observations_match_manifest(
    entry: dict[str, object],
) -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = cli_main(
        ["--backend", "ast", str(ROOT / str(entry["path"]))],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == entry["expected_exit_code"]
    assert observation_sha256(stdout.getvalue()) == entry["stdout_sha256"]
    assert observation_sha256(stderr.getvalue()) == entry["stderr_sha256"]
    assert "Traceback" not in stderr.getvalue()


def test_list_slice_assignment_is_a_structured_invalid_fixture() -> None:
    fixture = ROOT / "tests" / "fixtures" / "invalid" / "list_slice_assignment.ae"
    expectation = json.loads(fixture.with_suffix(".json").read_text(encoding="utf-8"))
    stdout = StringIO()
    stderr = StringIO()

    exit_code = cli_main([str(fixture)], stdout=stdout, stderr=stderr)

    assert exit_code == expectation["expected_exit_code"]
    assert expectation["diagnostic"] in stderr.getvalue()
    assert f"line {expectation['line']}, column {expectation['column']}" in stderr.getvalue()
    assert expectation["fragment"] in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()
    assert stdout.getvalue() == ""


def test_removed_broken_examples_are_not_public_or_manifested() -> None:
    removed = {
        "examples/minimos_cuadrados/interactive.ae",
        "examples/pruebaListas.ae",
    }

    assert removed.isdisjoint({str(entry["path"]) for entry in ENTRIES})
    assert all(not (ROOT / path).exists() for path in removed)
    assert (ROOT / "docs" / "aether" / "AETHER_EXAMPLES_CATALOG_AUDIT.md").is_file()


@pytest.mark.parametrize(
    ("source", "expected_code"),
    [
        ("int main() { float value = float(1); return int(value); }", "AE-BACKEND-PRIMITIVE_TYPES"),
        ("int main() { complex value = 1im; println(value); return 0; }", "AE-BACKEND-PRIMITIVE_TYPES"),
        ("int main() { (int, int) pair = (1, 2); return 0; }", "AE-BACKEND-PRIMITIVE_TYPES"),
        (
            "int main() { const values = 1:3; for (int value in values) { println(value); } return 0; }",
            "AE-BACKEND-FOR_IN",
        ),
        ('int main() { string value = input("value: "); return 0; }', "AE-BACKEND-INPUT"),
        ('int main() { int n = 2; println("n=$n$"); return 0; }', "AE-BACKEND-STRINGS"),
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


def test_exception_surface_is_inside_profile24_and_reaches_lowering() -> None:
    typed = prepare_typed_program(
        'struct E implements Error { string message() { return "stable"; } } '
        "int main() { try { throw E(); } catch (Error error) { "
        "println(error.message()); } return 0; }",
        TypeChecker(),
    )

    assert not backend_capability_issues(typed, BackendIdentity.NATIVE)
    assert "__ae_exception" in LLVMBuilder().emit_llvm(typed)


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
int apply(Function<(int), int> operation, int value) { return operation(value); }
int main() { return apply(twice, 4); }
"""
    typed = prepare_typed_program(source, TypeChecker())

    assert backend_capability_issues(typed, BackendIdentity.NATIVE) == ()
    assert "call i32 %" in LLVMBuilder().emit_llvm(typed)
