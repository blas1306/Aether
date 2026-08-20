from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path
import subprocess
import sys

import pytest

from aether.ir import IRBasicBlock, IRFunction, IRModule, IRReturn, VoidType
from aether.cli import main
from aether.pipeline import IRBackend
from shadow_validation_harness import ShadowValidationHarness


def _accepted_module() -> IRModule:
    return IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn()])],
            )
        ]
    )


def test_harness_explicitly_injects_and_restores_backend_shadow(
    rust_verifier_executable: Path,
) -> None:
    harness = ShadowValidationHarness(executable=rust_verifier_executable)
    original_init = IRBackend.__init__

    with harness.injected():
        harness.set_active_test("test_harness")
        backend = IRBackend()
        module = _accepted_module()

        assert backend.verify(module) is module
        assert backend.shadow_verifier is harness.coordinator
        assert len(harness.sink.reports) == 1

    assert IRBackend.__init__ is original_init
    assert IRBackend().shadow_verifier is None
    assert len(harness.sink.reports) == 1


def test_harness_summary_is_ordered_payload_free_and_has_timing_statistics(
    rust_verifier_executable: Path,
    tmp_path: Path,
) -> None:
    harness = ShadowValidationHarness(executable=rust_verifier_executable)
    harness.tests_collected = 2
    harness.tests_completed = 2

    with harness.injected():
        harness.set_active_test("tests/example.py::test_ir")
        IRBackend().verify(_accepted_module())
        harness.set_active_test(None)

    summary = harness.summary(population="focused")
    output = tmp_path / "shadow-summary.json"
    harness.write_summary(output, population="focused")
    decoded = json.loads(output.read_text(encoding="utf-8"))

    assert decoded == summary
    assert summary["observations"] == {
        "total": 1,
        "python_accepted": 1,
        "python_rejected": 0,
        "distinct_request_hashes": 1,
        "repeated_observations": 0,
    }
    assert summary["classifications"] == {"match_accepted": 1}
    assert summary["stages"] == {"initial": 1}
    assert summary["pytest"] == {
        "tests_collected": 2,
        "tests_completed": 2,
        "tests_exercising_shadow": 1,
    }
    timings = summary["timings_seconds"]
    assert timings["serialization"]["count"] == 1
    assert timings["rust_invocation"]["count"] == 1
    assert timings["total_shadow"]["count"] == 1
    assert not any(
        summary["privacy"]["forbidden_marker_hits"].values()
    )
    text = output.read_text(encoding="utf-8")
    assert '"payload":' not in text
    assert str(Path.home()) not in text


def test_canonical_request_hash_is_stable_across_python_processes_and_hash_seeds(
) -> None:
    repository_root = Path(__file__).parents[2]
    script = """
from hashlib import sha256
from aether.ir import build_canonical_rust_verifier_request
from aether.pipeline import IRBackend, prepare_typed_program
from aether.typechecker import TypeChecker

source = '''
int twice(int value) {
    return value * 2;
}

int main() {
    int total = 0;
    int i = 0;
    while (i < 4) {
        total = total + twice(i);
        i = i + 1;
    }
    return total;
}
'''
typed = prepare_typed_program(source, TypeChecker())
module = IRBackend().lower_verified(typed)
request = build_canonical_rust_verifier_request(module)
print(sha256(request.payload).hexdigest())
"""
    hashes = []
    for seed in ("0", "1", "17", "12345", "random"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = str(repository_root / "src")
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repository_root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        hashes.append(completed.stdout.strip())

    assert len(set(hashes)) == 1
    assert len(hashes[0]) == 64


def test_missing_rust_process_fails_closed_under_rp3_rust_authority(
    tmp_path: Path,
) -> None:
    program = tmp_path / "observational.ae"
    program.write_text(
        'int main() { println("unchanged"); return 0; }\n',
        encoding="utf-8",
    )

    def run() -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = main(
            ["--backend=ir", str(program)],
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
        )
        return exit_code, stdout.getvalue(), stderr.getvalue()

    disabled = run()
    harness = ShadowValidationHarness(
        executable=tmp_path / "missing-aether-ir-verifier"
    )
    with harness.injected():
        enabled = run()

    assert disabled == (0, "unchanged\n", "")
    assert enabled[0] == 1
    assert enabled[1] == ""
    assert "rust authoritative verifier failed: executable_not_found" in enabled[2]
    assert "at observational.ae" in enabled[2]
    assert harness.summary(population="failure_injection")["classifications"] == {
        "rust_integration_failure": 1
    }


def test_explicit_relative_executable_is_stable_after_working_directory_change(
    rust_verifier_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    relative_executable = rust_verifier_executable.relative_to(Path.cwd())
    harness = ShadowValidationHarness(executable=relative_executable)

    monkeypatch.chdir(tmp_path)
    with harness.injected():
        IRBackend().verify(_accepted_module())

    assert harness.summary(population="cwd_change")["classifications"] == {
        "match_accepted": 1
    }
